# Lens 12 — Data integrity (canonical-model soundness & silent loss)

**Summary:** The walker/matrix honesty machinery is in excellent shape (walker-completeness guard, reverse-parity, envelope exemptions all verified sound — the `ENVELOPE_AUDIT_BACKSTOPPED` claims check out against `tools/run_full_mesh.py`'s field comparator, and the v0.5.2/0.5.3 version-token/NTP-dialect gates are all correctly vendor-guarded). The real defects live one layer up, in the **rename-transform ↔ canonical-cross-reference seam**: `translate_port_names` rewrites only 8 of the 10+ places the tree stores port names, so the pipeline itself manufactures internally inconsistent trees that every downstream honesty guard is structurally blind to (the cross-mesh runs bare parse→render with no port translation, so none of these ever appear in phase-4 cells). Four findings, all reproduced or exact-code-confirmed.

---

### Finding 1 — Port-rename transform leaves `vxlan_vnis[].source_interface` and `vrrp_groups[].track_interfaces` stale → dangling references in rendered config on the DEFAULT cross-vendor flow

- **Severity:** MAJOR
- **Confidence:** confirmed (reproduced)
- **File:** `netcanon/migration/canonical/port_names.py:496` (rewrite sweep, lines 494–511) and `:534` (`_strip_dropped_ports`, lines 534–577)

`translate_port_names` documents that port-name references are rewritten "uniformly across ALL places the canonical tree stores them" and lists 8 mounts (interfaces, lag_member_of, vlan port lists, lags, static_routes.interface, dhcp_servers.interface). Two canonical fields that store vendor-native port names are missing from the sweep:

* `intent.vxlan_vnis[].source_interface` — worse, `intent.py`'s `CanonicalVxlan.source_interface` docstring explicitly promises "operators rename via the existing port-rename pane when crossing platforms", which is **false**: `resolve()` is never invoked on this field, so even an explicit `rename_map` entry cannot reach it.
* `intent.interfaces[].vrrp_groups[].track_interfaces` — vendor-native names per the schema docstring; never resolved.

Since v0.4.x the **default** `/plan` flow auto-translates port names (`port_rename_map={}` engages the classify→format bridge), so this fires with no operator action on the marquee EVPN-VXLAN path.

**Reproduced** (junos-shaped tree → arista_eos, auto bridge only):

```
renamed map: {'lo0.0': 'Loopback0', 'ge-0/0/1': 'Ethernet1', 'irb.10': 'Vlan10'}
vxlan source_interface: 'lo0.0'          # stale
track_interfaces: ['ge-0/0/1']           # stale
RENDER>    vrrp 10 track ge-0/0/1        # tracks a nonexistent port
RENDER>    vxlan source-interface lo0.0  # invalid EOS name; real loopback is Loopback0
```

The rendered EOS config is internally inconsistent: its own loopback is `Loopback0` but the Vxlan1 stanza binds the VTEP to `lo0.0` (rejected by EOS; on NX-OS the same path emits `source-interface lo0.0` inside `interface nve1`). The VRRP group tracks a port that does not exist post-rename, silently disabling the priority-decrement failover the operator configured. `_strip_dropped_ports` has the twin hole: a dropped interface leaves `source_interface`/`track_interfaces` dangling rather than cleared/filtered.

**Why every guard misses it:** the cross-mesh audit and all round-trip tests run bare parse→render (no port translation), so the inconsistency never appears in a phase-4 cell; live validation classifies xpaths against the *target matrix* and has no concept of intra-tree referential integrity.

**Fix:** in the rewrite sweep add `for vx in intent.vxlan_vnis: if vx.source_interface: vx.source_interface = resolve(vx.source_interface)` and `for iface ...: for grp in iface.vrrp_groups: grp.track_interfaces = [resolve(t) for t in grp.track_interfaces]`. In `_strip_dropped_ports`, filter `track_interfaces` against `dropped` and clear `source_interface` to `""` (renderers already fall back to a sensible default per the schema docstring). Update the two docstrings (`port_names.py` mount list; keep `intent.py`'s claim, now true).

---

### Finding 2 — Junos `group_content` verbatim re-emission resurrects pre-rename interfaces: renamed port's config is emitted for BOTH old and new names

- **Severity:** MAJOR
- **Confidence:** confirmed (reproduced)
- **File:** `netcanon/migration/codecs/juniper_junos/render.py:1190` (group re-emission, lines 1190–1207); root cause shared with `netcanon/migration/canonical/port_names.py:496`

`group_content` stores the verbatim token tails of every applied `set groups <G> ...` line (GAP 9b) and the Junos renderer re-emits them byte-for-byte. The rename transform never touches these opaque tokens. On a junos→junos migration with an operator rename map (the rename modal's core use case — moving to a box with a different port layout), the renamed data is emitted at top level under the NEW name while the group body re-emits the same config under the OLD name:

**Reproduced:**

```
input : set groups UPLINKS interfaces ge-0/0/1 ... address 10.9.9.1/30 ; apply-groups UPLINKS
rename: {'ge-0/0/1': 'xe-0/0/5'}
render: set interfaces xe-0/0/5 unit 0 family inet address 10.9.9.1/30
        set groups UPLINKS interfaces ge-0/0/1 unit 0 family inet address 10.9.9.1/30
        set apply-groups UPLINKS
re-parsed interfaces: ['ge-0/0/1', 'xe-0/0/5']   # stale port resurrected
```

Applied to a device, this configures the **same /30 address on two ports** (duplicate-subnet), plus whatever description/MTU/enabled state rode the group — the pipeline invents config for a port the operator explicitly renamed away. The same hole exists for the VLAN / local-user / SNMP rename panes when the renamed object was declared inside an apply-group.

Precedent for the fix already exists in-repo: `tools/sanitize.py:956–981` (v0.4.0 self-audit HIGH) recognised that verbatim group bodies bypass field-typed processing and strips them **fail-closed**.

**Fix (fail-closed, mirroring sanitize):** when any rename/drop was applied (`PortRenameResult.applied or .dropped` non-empty — or any other pane's result) and `tree.group_content` is non-empty, clear `group_content`/`apply_groups` (the flattened canonical data already carries the semantics, so nothing modelled is lost — top-level emission resumes for it) and append a warning: "apply-groups bodies flattened: renames cannot be applied to verbatim group content". A surgical alternative (rewrite `["interfaces", <name>, ...]` tokens through `resolve()`) round-trips prettier output but must also handle vlans/users tokens — fail-closed is the honest v1.

---

### Finding 3 — Rename-map target collisions are silently accepted: two source ports merge into one target interface with zero warnings

- **Severity:** MEDIUM
- **Confidence:** confirmed (reproduced)
- **File:** `netcanon/migration/canonical/port_names.py:375` (str_map branch of `resolve()`; no collision detection anywhere in the function, and `api/routes/migration.py` passes `body.port_rename_map` through unvalidated)

A rename map sending two source interfaces to the same target name (a one-character typo in the rename pane) produces two `CanonicalInterface` records with identical names, which the target render interleaves and a re-parse merges:

**Reproduced** (cisco_iosxe_cli → junos, map `{Gi0/1: ge-0/0/9, Gi0/2: ge-0/0/9}`):

```
warnings: []                                   # nothing surfaced
render:  set interfaces ge-0/0/9 description "LINK-A"
         set interfaces ge-0/0/9 unit 0 family inet address 10.0.1.1/30
         set interfaces ge-0/0/9 description "LINK-B"     # last-wins on device
         set interfaces ge-0/0/9 unit 0 family inet address 10.0.2.1/30
re-parsed: [('ge-0/0/9', 'LINK-B', ['10.0.1.1', '10.0.2.1'])]  # two links merged onto one port
```

Two physical links' L3 configs are silently fused onto one port — descriptions clobber, both /30s land on one unit. `PortRenameResult.warnings` is the designed channel for exactly this class of advisory and stays empty; the API layer does no dedupe either, so it is reachable end-to-end from the rename modal. (The auto-bridge can also collide in principle — e.g. an explicit override colliding with an auto-translated name — which per-entry map validation at the route layer would not catch; post-rename detection covers both.)

**Fix:** after the rewrite sweep, count post-rename `intent.interfaces` names (and LAG names); for any name with count > 1 append a warning (`"rename collision: N source interfaces map to '<name>' — their configs will merge"`). Optionally reject explicit maps with duplicate string values at the API boundary (400) since that is never intentional.

---

### Finding 4 — MikroTik silently substitutes SNMPv3 auth/priv algorithms with no lossy declaration → live validation reports `severity: ok` while the crypto algorithm changes

- **Severity:** MEDIUM
- **Confidence:** confirmed (exact code, both sides)
- **File:** `netcanon/migration/codecs/mikrotik_routeros/render.py:651` (`_CAN_TO_MT_AUTH` / `_CAN_TO_MT_PRIV`, lines 651–662 + `.get(..., "SHA1")` / `.get(..., "AES")` fallbacks at 666/678); matrix at `netcanon/migration/codecs/mikrotik_routeros/codec.py:151`

The render maps `sha224→SHA256`, `sha384→SHA512`, `3des→DES` (a cipher **downgrade**), and any unknown protocol falls back to `SHA1`/`AES` — all silent substitutions. The matrix declares `/snmp/v3-user` **supported** and only `engine-id`/`group` lossy; `/snmp/v3-user/auth-protocol` and `/snmp/v3-user/priv-protocol` are undeclared, so `classify()` fail-opens them to "supported". The walker yields exactly these xpaths when populated, and its own PR-2a comment states they exist so that "codecs that render the v3-user but DOWNGRADE the auth/priv algorithm … declare these lossy/unsupported … (a silent crypto downgrade)" — MikroTik is the codec that does the substitution and skipped the declaration (contrast: vyos, opnsense, cisco_iosxr, fortigate, cisco_iosxe, aruba_aoscx all declare theirs).

**Failure scenario:** FortiGate source with `set auth-proto sha224` + `priv-proto 3des` → target mikrotik_routeros: live migration report shows severity **ok** / fully supported; rendered RouterOS carries `authentication-protocol=SHA256 encryption-protocol=DES` — the operator's SNMP managers keyed for sha224/3DES stop authenticating, and 3DES→DES is a real strength downgrade, with no banner anywhere. (Same-vendor round-trip is unaffected — RouterOS input never produces the affected canonical values — which is why the round-trip suites never see it; the cross-mesh may show snmp drift but expectations-YAML disposition does not fix the live report's lie.)

**Fix:** add to the MikroTik matrix: `LossyPath("/snmp/v3-user/auth-protocol", reason="RouterOS supports MD5/SHA1/SHA256/SHA512 only; sha224→SHA256, sha384→SHA512, unknown→SHA1", severity="warn")` and `LossyPath("/snmp/v3-user/priv-protocol", reason="RouterOS has no 3DES; 3des→DES (strength downgrade), unknown→AES", severity="warn")`. Sibling nit while in the area: `aruba_aoss`/`arista_eos` emit `u.auth_protocol` verbatim, so an AOS-S target given `sha256` emits `auth sha256` which AOS-S grammar (md5|sha only) rejects at deploy time — visible-but-invalid rather than silent, worth an `auth-protocol` lossy declaration on aruba_aoss too.

---

## Verified-sound (checked, no finding — do not re-hunt)

* **Walker completeness / envelope exemptions:** `tests/unit/migration/test_walker_completeness.py` enumerates every scalar leaf; DHCP-pool / EVPN-Type5 / RADIUS-port sub-fields are consciously `ENVELOPE_AUDIT_BACKSTOPPED`, and I verified the backstop is real — `tools/run_full_mesh.py` compares full `model_dump()` records for `dhcp_servers`/`radius_servers`/`evpn_type5_routes` (only `is_secondary` is cosmetic-stripped, and only on `interfaces`). The known sub-field drops (iosxe_cli drops DHCP `range`, mikrotik drops DHCP `lease_time`/server-instance binding, fortigate drops RADIUS `acct_port`) are therefore visible to the offline audit per the documented design tradeoff.
* **v0.5.2/0.5.3 version-sensitive renders:** `_render_ntp_client`/`_ros_major`/`_all_ip_literals` (mikrotik) and all four `_release_token`/`_version_token` helpers (vyos/nxos/iosxr/aoscx) gate on `tree.source_vendor == <self>` before consuming `source_version` — no cross-vendor version confusion; v6-NTP double-sanitize non-idempotency is documented in the docstring and canonical-tree-invisible.
* **Registry honesty guards:** reverse-parity (supported ⊆ walkable), documented-synthetic allowlist for non-walkable lossy/unsupported (`/interfaces/interface/vrrp-groups/group/address-family` is a blessed marker), rendered⇒not-unsupported, naming-independent total-drop, static-route sub-value fidelity — all present and non-vacuous (guard-the-guard tests included).
* **SVI dual-mount:** `project_svi_to_vlan` is additive with `(ip, prefix)` de-dupe; `synthesize_svis_from_vlan_l3` only fires when no matching `Vlan<N>` interface exists — no double-emit path found.
* **Sanitizer vs `group_content`:** already stripped fail-closed (`tools/sanitize.py:956`) — no secret leak through group bodies.

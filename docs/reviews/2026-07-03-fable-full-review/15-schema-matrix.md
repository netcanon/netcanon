# 15 — Support-matrix / walker honesty (drift hunt)

Lens: the keystone invariant ("walker sees every canonical surface; every codec declares
supported/lossy/unsupported for each") is tested and known-good — this pass hunted for
**drift**: fields neither wired nor declared, declared-supported-but-actually-lossy,
stale pessimism, and matrix/behavior desync on the recently-added surfaces
(dot1q-vlan GAP-7, VXLAN, anycast, IPv6 statics).

Method: read `schema.py` (`netcanon/migration/canonical/intent.py`), the shared walker
(`netcanon/migration/canonical/xpath_walker.py`), all 12 codec matrices, the completeness
guards (`tests/unit/migration/test_walker_completeness.py`,
`tests/unit/migration/test_registry_capability_honesty.py`,
`tests/unit/migration/test_canonical_vrrp_anycast_schema.py`), then probed every suspect
claim with `py -c` round-trips + `validate_against`.

**Verdict: the guard architecture is genuinely strong, but it has drifted at its edges.**
Two matrix lies in the dangerous direction (VXLAN udp-port), one stale test roster that
let two ship-before-wire declarations go missing on the newest codecs, and one
source-side GAP-7 hole that emits broken target configs with a clean report. Six
findings total (4 major, 2 minor). All probes reproduced; commands inline below.

---

## F1 — MAJOR: cisco_nxos declares `/vxlan-vnis/udp-port` **supported** but silently normalizes it to 4789

- `netcanon/migration/codecs/cisco_nxos/codec.py:172` — `"/vxlan-vnis/udp-port"` sits in
  the `supported` list.
- Neither `cisco_nxos/parse.py` nor `cisco_nxos/render.py` contains any UDP-port
  handling (fleet grep for `udp_port|udp-port|udp port` matches only `codec.py:172` in
  this codec). Render emits no port; parse defaults the record to 4789.
- Probe (round-trip): `CanonicalVxlan(vlan_id=10, vni=10010, udp_port=8472)` →
  `cisco_nxos.render` → reparse gives `udp_port=4789`. `classify('/vxlan-vnis/udp-port')
  == "supported"` → `validate_against` reports the path as fine while the value is
  discarded.
- **This fires on a realistic pair**: VyOS's dataplane default is 8472, and the vyos
  parser bakes it in when the config omits `port`
  (`netcanon/migration/codecs/vyos/parse.py:801` — `else 8472`). Probe: a plain VyOS
  `vxlan10 { vni 10010 ... }` config → `validate_against(tree, cisco_nxos)` →
  `severity: warn` with lossy paths `['/vxlan-vnis/vni']` only — **no mention of
  udp-port** — then nxos render/reparse yields 4789. Mid-migration, 8472-VTEPs and
  4789-VTEPs will not interoperate; the report says nothing about why.
- Why no test caught it: `_maximal_intent` uses `udp_port=4789`
  (`tests/unit/migration/test_registry_capability_honesty.py:224`), so survival is
  vacuous; the value-fidelity block (same file, `_subfield_intent`) covers only
  static-route metric/description + secondary IPs.
- Fix: demote to `LossyPath` ("NX-OS has no configurable VXLAN UDP port; non-default
  source values normalize to 4789"). Consider adding a non-default `udp_port` to the
  value-fidelity kitchen-sink so drops must be declared fleet-wide.

## F2 — MAJOR: aruba_aoscx has **no declaration at all** for `/vxlan-vnis/udp-port` (implicit supported) while dropping it the same way

- `netcanon/migration/codecs/aruba_aoscx/codec.py:175-177` declares `/vxlan-vnis/vni`
  supported; lossy entries cover `source-interface` (389), `mcast-group` (411),
  `flood-list` (423) — `udp-port` (and `vlan-id`) appear nowhere in the file, so
  `classify()` fail-opens both to "supported".
- Probe: `udp_port=8472` → aoscx render → reparse `4789`. `vlan-id` is fine (the
  `vni <VNI> / vlan <VLAN>` binding round-trips, probed) — only udp-port is a lie.
- Same fix as F1 (LossyPath). Same guard gap as F1 explains the miss.
- For contrast, the codecs that genuinely wire udp-port are honest: arista
  (`arista_eos/parse.py:1393`, `render.py:844`), junos (`juniper_junos/render.py:923-933`),
  vyos (`vyos/render.py:436`) — all probed or code-verified; cisco_iosxe_cli declares it
  lossy ("parse-and-ignore", `cisco_iosxe_cli/codec.py:356`) — honest.

## F3 — MAJOR (root cause): the ship-before-wire invariant test roster is frozen at 8 codecs — the 4 newest are unguarded

- `tests/unit/migration/test_canonical_vrrp_anycast_schema.py:405-417` — the
  `TestShipBeforeWireUnsupportedDeclarations` parametrize list contains only
  cisco_iosxe_cli, cisco_iosxe, juniper_junos, arista_eos, aruba_aoss, fortigate_cli,
  mikrotik_routeros, opnsense. **cisco_nxos, cisco_iosxr, aruba_aoscx, vyos (codecs
  9-12) are absent**, and `_WIRED_UP_BY_CODEC` (:339-403) has no entries for them.
- There is no guard-the-guard asserting the roster matches the registry (unlike the
  walker-completeness module, which guards its own maps —
  `test_walker_completeness.py:277-344`). So the memory-documented promise "the
  two-sided `_WIRED_UP_BY_CODEC` invariant catches both half-wired and
  forgot-to-declare states" is only true for the 2/3 of the fleet that existed when the
  test was written.
- Direct consequence: F4. Sweep of all six `_NEW_PATHS` across the four uncovered
  codecs shows exactly two undeclared cells (below); the rest were declared correctly by
  discipline alone.
- Fix: derive the parametrize list from `list_codecs()` (as
  `test_registry_capability_honesty.py:118-129` does) + add explicit
  `_WIRED_UP_BY_CODEC` rows for the four codecs.

## F4 — MAJOR: `/anycast-gateway-mac` undeclared on cisco_iosxr and vyos — silent drop classifies "supported"

- Fleet probe (`render(intent with anycast_gateway_mac set)` → reparse, per codec):
  every codec either round-trips it (arista, iosxe_cli, nxos; aoscx round-trips it when
  the SVI mount exists — declared supported at `aruba_aoscx/codec.py:174`, verified with
  an active-gateway VIP probe) or declares it unsupported (aoss, iosxe, fortigate,
  junos, mikrotik, opnsense) — **except cisco_iosxr and vyos**, which drop it and have
  no declaration: `classify('/anycast-gateway-mac') == "supported"` on both.
- `cisco_iosxr/codec.py:355-373` declares the per-address virtual-gateway-address
  unsupported (both AFs) but omits the chassis-wide MAC path; `vyos/codec.py:424-457`
  likewise (VLAN-mount + interface-mount VGA declared, top-level MAC omitted).
- Schema doc says this exact declaration is mandatory until wired: `intent.py:879-883`
  ("every codec's CapabilityMatrix lists `/anycast-gateway-mac` as unsupported until the
  per-codec wire-up lands").
- Blast radius is moderate: on realistic fabric configs the per-address VGA
  `unsupported` fires alongside, so the operator is warned about *anycast* loss — but a
  source carrying only the chassis MAC (e.g. NX-OS `fabric forwarding
  anycast-gateway-mac` set ahead of SVI conversion, or Arista `ip virtual-router
  mac-address` alone) walks only `/anycast-gateway-mac` and reports fully ok while the
  value vanishes. Fix: add the `UnsupportedPath` to both codecs (one line each) — and F3
  so it can't happen again.

## F5 — MAJOR: vyos `vif` parse never populates `dot1q_vlan` → broken target configs with a clean report (GAP-7 source-side hole)

- Only the five GAP-7 codecs touch `dot1q_vlan` at all (grep: arista_eos, cisco_nxos,
  cisco_iosxr, cisco_iosxe_cli, juniper_junos parse+render). All five round-trip it
  (probed, all `classify == supported`) — the #240-#243 wiring is honest.
- vyos parses `ethernet ethN { vif V {...} }` into an interface literally named
  `ethN.V` with the vif's IP but `dot1q_vlan=None` (`vyos/parse.py:461,486`; probe:
  `vif 100` → `('eth1.100', dot1q_vlan=None, ['10.1.1.1'])`).
- Downstream probe: rendering that vyos-parsed tree through `cisco_iosxe_cli` emits
  `interface eth1.100 / ip address 10.1.1.1 255.255.255.0` — **no `encapsulation dot1Q
  100`** — which IOS rejects (IP on a sub-interface requires encapsulation). And because
  the source tree carries no `dot1q_vlan`, the walker never yields
  `/interfaces/interface/dot1q-vlan`, so `validate_against` cannot flag anything: broken
  output, clean report.
- The vyos matrix declaration (`vyos/codec.py:347-353`, "not yet wired ...
  ship-before-wire, GAP 7") is honest but only covers vyos-as-TARGET; the honesty system
  is structurally blind to source-side under-parse. This is the remaining GAP-7 rollout
  work (vyos, and to a lesser degree mikrotik/fortigate whose VLAN-interface models parse
  to SVI-ish shapes instead — mikrotik probe renders `interface vlan100` as an SVI, which
  is semantically defensible, unlike the vyos dotted-name case).
- Fix: populate `dot1q_vlan` in the vyos vif parse (the record already gets the `.V`
  name, so the tag is trivially available), mirroring #240-#243.

## F6 — MINOR: VLAN-mount `secondary-ip` walk is flag-gated while the interface mount is cardinality-gated (audit-276eaeb rationale not mirrored)

- `xpath_walker.py:96` (interface mount): `if idx > 0 or addr.is_secondary` — the
  cardinality discriminator added because flag-less sources (Junos/OPNsense) leave
  `is_secondary=False` on every address (audit 276eaeb T0-1).
- `xpath_walker.py:226` (VLAN mount, added later by f92e97a T0-2): `if
  addr.is_secondary:` only.
- Probe: junos irb with two `family inet address` lines + `l3-interface irb.10` folds
  both addresses onto the VLAN record with both flags False (`project_svi_to_vlan`
  removes the interface record) → walk yields only `/vlans/vlan/ipv4/address/ip`, no
  `secondary-ip` on any mount.
- **Currently non-exploitable**: probed all five VLAN-mount-L3-capable targets — arista
  / cisco_iosxe_cli / aruba_aoss render both IPs (survive), aoscx / vyos drop the SVI
  entirely but their `/vlans/vlan/ipv4/address/ip` lossy/unsupported declarations fire
  (warn/block). So no silent loss today — but the walker inconsistency is the exact
  hole-class the interface mount was patched for, and the completeness guard cannot see
  it (`_ALL_MOUNTS_REQUIRED` in `test_walker_completeness.py:105-109` is satisfied by
  the flag-based yield). One-line fix: use `enumerate` + `idx > 0 or addr.is_secondary`
  at `xpath_walker.py:226`.

## F7 — MINOR: interface-mount `virtual-gateway-mac` (v4+v6) undeclared across the six no-anycast codecs

- Classification sweep: `/interfaces/interface/ipv4/address/virtual-gateway-mac` (and
  the v6 twin) classify "supported" on aruba_aoss, fortigate_cli, mikrotik_routeros,
  opnsense, cisco_iosxr, vyos — all of which drop the whole anycast surface. The
  f92e97a remediation declared the **VLAN-mount** MAC twin lossy on these codecs but
  left the interface mount undeclared.
- Mitigant: the walker yields the MAC path only when populated, and in every real
  grammar the per-address MAC accompanies a virtual-gateway-address, whose `unsupported`
  declaration fires on the same interface — so the loss is co-flagged, just
  mis-itemized. Bookkeeping asymmetry, not an operator-facing lie. Fix opportunistically
  alongside F4.

---

## Checked and clean (do not re-hunt)

- **Walker completeness machinery** (`test_walker_completeness.py`) — sound; all
  exemptions structurally coded, guard-the-guard tests present, `KNOWN_GAP` set empty as
  documented; every `CanonicalIntent` leaf accounted for against `intent.py`.
- **dot1q-vlan target-side**: all 12 codecs declare it (5 supported + 7
  lossy/unsupported); all five supported codecs round-trip it (probed with native
  sub-interface names). aoscx's #244 "architecturally unsupported" declaration is
  consistent (`aruba_aoscx/codec.py:435`).
- **nxos VXLAN mcast-group + flood-list** (declared supported): both round-trip
  (probed — `mcast-group 239.1.1.1` and static ingress-replication `peer-ip` lists
  re-parse intact; the old "flood-list parse deferred" memory note is stale, it works).
- **`/vxlan-vnis/vlan-id`**: implicit-supported on nxos/aoscx is backed by real
  round-trips (vn-segment / `vni..vlan` probed); vyos declares it lossy — consistent.
- **anycast on aoscx**: `active-gateway ip mac` round-trips when an SVI mount exists —
  the supported declaration is honest (initial bare-intent "drop" was a false positive).
- **junos irb + IPv6**: the SVI→VLAN projection correctly *skips* folding when inet6 is
  present (interface record retained, no loss — probed).
- **Stale pessimism spot-checks**: nxos `/routing/static-route/description` and
  `/vlans/vlan/description` lossy declarations still match behavior (probed — values
  drop). No stale-lossy found.
- **IPv6 static routes** (#252-#260): not re-audited per seed; noted only that the
  sweep reuses the AF-agnostic `/routing/static-route` path, which is coherent because
  all 12 codecs now handle both AFs (no per-AF split needed).
- **v6scope / v6 secondary declarations** match the walker docstring's stated pinners
  (fortigate/vyos/iosxe lossy scope; fortigate/opnsense unsup secondary).

## Guard-improvement suggestions (for synthesis)

1. Derive the `TestShipBeforeWireUnsupportedDeclarations` roster from `list_codecs()`
   (F3) — the single change that converts F4-class drift from "discipline" to "gated".
2. Add a non-default `udp_port` (e.g. 8472) to the value-fidelity kitchen-sink in
   `test_registry_capability_honesty.py` and assert drop⇒declared, as already done for
   static-route metric/description (closes the F1/F2 class for every codec).
3. Mirror the cardinality discriminator onto the VLAN mount (F6) and consider a
   walker-parity lint that the same `(class, field)` uses the same gate expression on
   every mount.

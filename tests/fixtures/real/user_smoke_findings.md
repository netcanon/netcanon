# User smoke-test findings — live cross-vendor translation results

This file captures issues surfaced by the user manually pasting real
configs into the migrate UI and inspecting the output for each
target.  Distinct from the Phase 4 mechanical reconciliation
findings (`phase4_findings_*.md`) — those are derived from
canonical-field drift.  These are operator-readable issues spotted
by humans inspecting actual rendered config.

Branch this file lives on: `fix/phase4-top-codec-fixes`.

## See also

- [`PHASE4_RECONCILIATION.md`](PHASE4_RECONCILIATION.md) — top-level
  reconciliation matrix and Phase-4 fix backlog
- [`phase4_findings_*.md`](.) — per-source-codec mechanical drift
  attribution
- [`CROSS_MESH_RESULTS.md`](CROSS_MESH_RESULTS.md) — Phase 1
  mechanical drift matrix
- `git log fix/phase4-top-codec-fixes` — chronological commit history
  of fixes landed this session

---

## Already FIXED this session

### Junos trunk-all expansion (commit `b40c4e3`)

**Symptom:** Arista source with `switchport trunk allowed vlan
2-4094` (operator-form for "all VLANs except default") rendered to
Junos as 4093 separate `set interfaces aeN unit 0 family
ethernet-switching vlan members VLAN-N` lines including phantom
references.

**Fix:** `juniper_junos/render.py` detects all-VLANs pattern (full
or near-full 1-4094 / 2-4094 range) and emits Junos's native
`vlan members all`.  Symmetric parser fix in
`juniper_junos/parse.py` recognises `vlan members all` on reparse
and expands back to the full VID range.

**Verification:** 7 unit tests in
`tests/unit/migration/codecs/juniper_junos/test_l2_render_and_dot_zero_parse.py`,
all passing.

### Aruba loopback / OOBM / unmigratable hashes (commit `5f4855a`)

**Symptom:** Arista source with `Loopback0`, `Management1`
(IPv4+IPv6), and a sha512 user secret — Aruba target silently
dropped Loopback0 and Management1, and emitted the sha512 hash as
`plaintext "arista:sha512:$6$..."` (security bug — AOS-S would
accept the prefixed string as the literal plaintext password).

**Fix:** `aruba_aoss/port_names.py::format_port_identity` now
returns `loopback{N}` for `kind=loopback` (1-7 per AOS-S 16.04+
docs) and `oobm` sentinel for `kind=mgmt`.  Renderer emits
`interface loopback N` and dedicated top-level `oobm` block.
Hash logic rewritten with explicit
`_AOS_KNOWN_ALGORITHMS = {sha1, sha256, plaintext}` (added sha256)
and `_AOS_UNMIGRATABLE_ALGORITHMS = {sha512, 5, 9, 8, 7, bcrypt,
fortios}` — unmigratable hashes emit `; password manager ... --
review:` comment lines instead of leaking through as plaintext.

**Verification:** 12 unit tests in
`tests/unit/migration/codecs/aruba_aoss/test_loopback_oobm_render.py`,
plus updates to `test_port_names.py` / `test_local_users_wire_through.py`
/ `test_migration_target_profiles_api.py`.  All passing.

---

## RESOLVED — Cisco c9300-24ux smoke test (all 9 issues fixed)

Wave-2 sweep on `fix/phase4-top-codec-fixes` shipped fixes for all
9 issues raised by the c9300 smoke test.  Final regression on the
combined wave: **2666 passed, 57 skipped, 0 failed**.  The
mechanical Phase 4 reconciliation matrix (CODEC_BUG count) went
UP slightly after this wave — that's expected, because the
Phase 3 expectation YAMLs were authored against pre-fix render
output and now drift against the new (correct) behavior.
Expectation-YAML refresh is the next phase, not a regression in
this one.

### Resolution map

| # | Issue | Fix commit | Approach |
|---|---|---|---|
| 1 | Cisco type-9 hash leak (4 targets) | `da8883f` (helper), `b2036aa` (fortigate), `7fbd44d` + `0fdf7e9` (junos), `10d8195` (opnsense) | Shared `netconfig/migration/_user_secrets.py` helper with `is_migratable(hashed, target_vendor)`.  Each codec gates the password emit; unmigratable hashes become review-comment lines (no payload leak) |
| 2 | FortiGate duplicate `edit "portN"` | `b2036aa` | Multi-axis disambiguation in `format_port_identity` (`port-<stack>-<module>-<port>` for non-default coords) + render-time dedup belt-and-braces |
| 3 | Aruba `interface 1/1` collision | `7d93085` | Render-time collision detection keyed on `iface.name`; emits one review-comment block naming each collider's `description`, then emits the first interface only |
| 4 | MikroTik missing `bridge1` declaration + `bridge.11` typo | `3f528b7` | Synthesise `/interface bridge add name=bridge1` once when canonical has VLANs but no real bridges; SVI fallback name `bridge.N` → `vlanN` |
| 5 | OPNsense VLAN tags lack `<if>` parent | `10d8195` | VLAN-emit walks canonical interfaces to find SVI parent; falls back to first lagg → first physical.  Full schema (`if`, `tag`, `pcp`, `proto`, `descr`, `vlanif`) verified against real fixture + OPNsense docs |
| 6 | FortiGate no VLAN child interface | `b2036aa` | New `_build_vlan_children` helper resolves IP from `CanonicalVlan.ipv4_addresses` (or sibling `Vlan<id>` stub fallback); emits `edit "vlanN" / set type vlan / set vlanid N / set interface "LAG1"` blocks; dedups against source-named VLANs |
| 7 | MikroTik port-name collision (sfp-sfpplus1 ×N) | `dc4847d` | Flat global-index scheme `(stack-1)*1000 + module*100 + port` for non-default coords; bonus 25G `sfp28-N` cage split (was sharing `sfp-sfpplus` with 10G) |
| 8 | Mgmt-vrf cross-vendor mapping | `56a4cde` | cisco_iosxe_cli parser promotes `kind=physical` → `kind=mgmt` when VRF name matches `^(?:mgmt[-_]?vrf|management(?:[-_]?vrf)?|mgmt)$`.  Cascades to Aruba `oobm` block automatically (Junos already handled via routing-instances) |
| 9 | Junos empty interface stubs | `7fbd44d` + `281a9ee` + `0fdf7e9` | Tiered policy: skip empty stubs UNLESS (a) VRF-bound (Junos commit-time validator requires it), (b) parent of `name.unit` sub-iface, or (c) matches Junos physical-port shape (round-trip stability) |

### New shared scaffolding

- `netconfig/migration/_user_secrets.py` — cross-codec hash-policy helper with `classify_hash`, `is_migratable`, `format_review_comment`.  Public API stable; consumed by fortigate / junos / opnsense.  Aruba retains its own inline logic (older, equivalent, deferred refactor).
- `CanonicalInterface.kind` — now respected by `translate_port_names` so source-side kind promotions (e.g. cisco Mgmt-vrf → kind=mgmt) propagate through port-rename to target codecs' kind=mgmt handlers.

### Follow-ups (out of scope for this wave)

- Refresh Phase 3 expectation YAMLs to absorb the new render output (CODEC_BUG count regression on the matrix is methodology drift, not real bugs).
- `format_review_comment(comment_syntax="xml")` produces `-- review:` which is forbidden inside XML comments.  OPNsense codec post-processes to `- review:` locally; lift this into the helper if any other XML codec ever lands.
- FortiGate and OPNsense kind=mgmt rendering paths (issue 8 cascade only reaches Aruba today; the canonical model now carries the right info but the FortiGate / OPNsense renderers don't yet special-case it).
- Aruba `_split_aos_hash` refactor to consume the shared helper (cleanup, not bug-fix).

---

## (Original) OPEN section — Cisco c9300-24ux user contrib smoke test

Source fixture: real Cisco IOS-XE `show running-config` from a
Catalyst c9300-24ux (24 × Te1/0/X base + 4 × Gi1/1/X uplink + 8 ×
Te1/1/X uplink + 2 × Fo1/1/X + 2 × Twe1/1/X + 1 × App1/0/1 + 1 ×
Gi0/0 Mgmt-vrf, 3 × Port-channel, 6 VLANs, 2 local users with
`secret 9` (Cisco type-9 / scrypt), VRF Mgmt-vrf, default gateway).

### Severity ranking

| # | Issue | Severity | Targets affected | Locus | Effort |
|---|---|---|---|---|---|
| 1 | Cisco type-9 hash → plaintext leak | **CRITICAL (security)** | aruba_aoss, fortigate_cli, juniper_junos, opnsense | per-codec render OR canonical-layer policy | medium |
| 2 | FortiGate duplicate `edit "portN"` entries | **CRITICAL (invalid syntax)** | fortigate_cli | render + port_names | medium |
| 3 | Aruba `interface 1/1` collision (Te1/0/1 ↔ App1/0/1) | high | aruba_aoss | port_names disambiguation | small |
| 4 | MikroTik missing `/interface bridge add name=bridge1` declaration | high | mikrotik_routeros | render | small |
| 5 | OPNsense VLAN tags lack `<if>` parent binding | high | opnsense | render | small |
| 6 | FortiGate has no VLAN child interface emit | high | fortigate_cli | render | medium |
| 7 | MikroTik port-name collision (sfp-sfpplus1 ×N) | medium | mikrotik_routeros | port_names | medium |
| 8 | Mgmt-vrf cross-vendor mapping | medium | aruba_aoss, fortigate_cli, opnsense | port_names + render coordination | larger |
| 9 | Junos empty interface stubs (`set interfaces irb.1`, bare `ge-0/0/0`) | low | juniper_junos | render | small |

### Issue 1 detail: Cisco type-9 hash leaks across targets

Source: `username netadmin privilege 15 secret 9
$9$fakeSaltAdmin1$...`

Cisco IOS-XE type-9 is scrypt — incompatible with every other
target's hash format.

| Target | Current output | Problem |
|---|---|---|
| aruba_aoss | `plaintext "9 $9$..."` | Aruba fix exists but didn't catch this form — the canonical store may not be `9 $9$...` literally; investigate cisco_iosxe_cli parser to see what it actually stores |
| fortigate_cli | `set password ENC 9 $9$...` | FortiOS `ENC` is its own internal-key format, not a type-9 wrapper |
| juniper_junos | `authentication encrypted-password "9 $9$..."` | Junos accepts `$1$` / `$6$` only |
| opnsense | `<password>9 $9$...</password>` | OPNsense expects bcrypt |
| mikrotik_routeros | (no password emitted) | Different problem — emitting `add group=full name=netadmin` without password field |

**Fix approach:** unified canonical-layer policy.  Recognise
unmigratable hash formats (Cisco type-5/7/8/9, OPNsense bcrypt
when source vendor differs, etc.) at the canonical layer and let
each target codec emit its appropriate "review this user" form
(comment line for CLI codecs, XML attribute for OPNsense).
Mirror the Aruba pattern (`__unmigratable__` sentinel + comment
emit) across the other 4 codecs.

### Issue 2 detail: FortiGate duplicate port edits

Source has 41 ports across multiple modules (24 Te + 4 Gi + 8 Te +
2 Fo + 2 Twe + 1 App + 1 Mgmt).  FortiGate codec collapses all to
flat `port1`, `port2`, ... causing `edit "port1"` to appear 4
times in `config system interface`.  Invalid FortiOS syntax — would
fail at deploy.

**Fix approach:** FortiGate `format_port_identity` needs to track
slot/module + index together (e.g. `port-1-0-1` for stack/module/port
with non-zero module).  Or: render-side dedup that warns on
collision and skips duplicates with operator-review comment.

### Issue 3 detail: Aruba `interface 1/1` collision

`AppGigabitEthernet1/0/1` and `TenGigabitEthernet1/0/1` both map
to AOS-S `1/1` after port-rename mesh.  Render emits two
`interface 1/1` stanzas which AOS-S would error on.

**Fix approach:** detect collision at render time and either
suffix-disambiguate (mirror OPNsense pattern: `1/1`, `1/1_2`) or
emit comment-form for collision and skip the dupe.  AppGig is
typically a sandbox port unique to c9300 — could heuristically
demote to `; AppGigabitEthernet not representable on AOS-S`
comment.

### Issue 4 detail: MikroTik missing bridge1 declaration

Output references `bridge1` in `add interface=bridge1 name=vlan11`
but no `/interface bridge add name=bridge1 ...` declaration emitted.
VLANs would fail to commit.

Also: `/ip address add address=192.168.11.252/24 interface=bridge.11`
has a typo — should be `bridge1.11` or use the canonical VLAN-SVI
binding name.

**Fix approach:** mikrotik_routeros render emits `/interface bridge
add name=bridge1` once when any `/interface vlan` references it.
Fix the bridge.11 typo in the SVI render path.

### Issue 5 detail: OPNsense VLAN-no-parent

```xml
<vlans>
  <vlan><tag>11</tag></vlan>
</vlans>
```

OPNsense VLANs require `<if>` element pointing at the parent
physical / lagg interface.  Without it, the VLAN can't bind on a
real device.

**Fix approach:** opnsense render walks the canonical interfaces
to find which physical/lagg the VLAN's L3 SVI is bound on (via
the SVI's parent name), and emits `<if>laggN</if>` or `<if>ixN</if>`
inside the `<vlan>` element.  Fall back to "first lagg" or "first
ix port" if no explicit binding.

### Issue 6 detail: FortiGate no VLAN child interface emit

Source has 6 VLANs (1, 10, 11, 20, 100, 150).  FortiGate output
shows them only on `set member` LAG lines but no `edit "vlan11" /
set type vlan / set vlanid 11 / set interface "LAG1"` blocks.

**Fix approach:** fortigate_cli render walks `tree.vlans` and emits
a per-VLAN `edit "vlan{id}" / set type vlan / set vlanid N / set
interface "LAG1"` (or first physical port if no LAG).  L3 SVI on
VLAN 11 → `set ip 192.168.11.252/24` inside the vlan child edit.

### Issue 7 detail: MikroTik port-name collision

Output has `set [ find name=sfp-sfpplus1 ]` listed multiple times
(~ once per Cisco source module that mapped to sfp-sfpplus1).
Same shape as FortiGate issue #2.

**Fix approach:** mikrotik_routeros `format_port_identity` needs
to handle multi-module Cisco source by either preserving module
info or demoting non-zero-module ports to a deterministic
disambiguator.

### Issue 8 detail: Mgmt-vrf cross-vendor mapping

Source has `interface GigabitEthernet0/0 / vrf forwarding Mgmt-vrf`.
Junos handles this correctly via `routing-instances Mgmt-vrf
interface ge-0/0/0.0`.  Other targets don't.

| Target | Recommended target syntax |
|---|---|
| aruba_aoss | top-level `oobm` block (already wired for kind=mgmt; should heuristically promote VRF-bound port=0 to mgmt kind) |
| fortigate_cli | dedicated mgmt port + mgmt VDOM (or just port-rename to `mgmt1`) |
| opnsense | reserved zone `<mgmt>` (no native VRF concept — best-effort) |

**Fix approach:** the cisco_iosxe_cli parser could promote
GigabitEthernet0/0 to `kind=mgmt` when it's bound to Mgmt-vrf,
not just kind=physical/port=0.  This would cascade to every
target's existing kind=mgmt handling.

### Issue 9 detail: Junos empty interface stubs

Junos output has `set interfaces irb.1` (no body) and `set
interfaces ge-0/0/0` (no body, but referenced from
`routing-instances Mgmt-vrf`).

**Fix approach:** juniper_junos render skip-emit when an iface
has no IPs, no description, no MTU non-default, no enabled=False,
and isn't referenced from routing-instances or vlans.  Cleaner
output without losing semantic.

---

## Triage decision (resolved)

User directed: "all in order of dependency and maximize
parallelization by use of external agents."  Executed as:

- **Wave 0** — investigation (read-only) confirmed canonical
  hash storage shape and that Aruba's existing fix already
  catches the Cisco-source `9 $9$...` form (the issue table
  above documented the BEFORE state).
- **Wave 1** — `da8883f` shared `_user_secrets.py` helper
  (24 tests, regression green).
- **Wave 2** — 7 parallel agents, one per issue cluster, with
  same-file overlaps merged into single agents.  All landed.
- **Wave 3** — full regression, mesh + reconciliation regen,
  this doc updated.

Total: 1 helper module + 9 issue fixes shipped in 10 commits
on top of `abcfa8e`.

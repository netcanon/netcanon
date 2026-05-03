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
- [`../../../tools/run_phase4_reconciliation.py`](../../../tools/run_phase4_reconciliation.py)
  — module docstring defines the variance classes (CODEC_BUG,
  EXPECTED_LOSSY, EXPECTED_UNSUPPORTED, METHODOLOGY_*,
  STRUCTURAL_ONLY) and the structural-collapse rule
- `git log fix/phase4-top-codec-fixes` — chronological commit history
  of fixes landed this session

---

## Methodology improvements (this session)

### `STRUCTURAL_ONLY` variance class — comparator over-counting fix (commit `9db1eb9`)

**Symptom:** after the Wave 2 codec sweep, the Phase 4 reconciliation
showed CODEC_BUG count rising 254 → 345 (+91).  Triage revealed that
all 100 new CODEC_BUG entries shared the shape `interfaces[].<field>`
with `drift_summary: "count drift: N → M (interfaces)"` and zero
per-record detail — i.e. a single structural row-count signal from
Phase 1's list-drift summarizer was being amplified across every
per-field key the YAML keyed for that list (description, mtu, enabled,
ipv4_addresses, …).

**Why it surfaced now:** Wave 2 fixes (Junos empty-stub elision,
FortiGate VLAN-child emit, MikroTik bridge synthesis) deliberately
changed interface row counts.  Pre-Wave-2 the same multiplication
artefact was present but hidden — the genuinely-bug count was always
~108, with ~146 false multiplications baked into the 254 baseline.

**Fix (`9db1eb9`):** new `STRUCTURAL_ONLY` variance class.  In
`reconcile_cell`, the first sub-field of each list parent that
drifted PURELY on a structural list-length signal keeps its original
variance class (typically `CODEC_BUG`) and carries the
`drift_summary` string.  Every subsequent sub-field of the SAME
parent in the SAME cell collapses to `STRUCTURAL_ONLY` (low
severity), with a `structural_owner` pointer back to the YAML key
that owns the canonical signal.

**Safety constraint (tested):** the collapse only fires when
`isinstance(drift_summary, str) AND "per_record" not in drift_detail`.
Real per-field drift on surviving rows produces a `per_record` slice
(counts match → Phase 1 emits a per-record dict) and is **never**
collapsed.  See
`tests/unit/audit/test_run_phase4_reconciliation.py::test_count_drift_with_real_per_field_drift_preserves_both`
and `::test_count_drift_plus_real_per_field_drift_on_same_list_both_emit`.

**Aggregate impact (post-fix):**

| Variance class | Pre-fix | Post-fix | Δ |
|---|---:|---:|---:|
| ALIGNED | 2395 | 2395 | 0 |
| CODEC_BUG (severity=high) | 345 | 108 | -237 |
| EXPECTED_LOSSY | 998 | 865 | -133 |
| EXPECTED_UNSUPPORTED | 730 | 484 | -246 |
| METHODOLOGY_ISSUE_under | 7355 | 7355 | 0 |
| METHODOLOGY_ISSUE_over | 142 | 13 | -129 |
| **STRUCTURAL_ONLY** (new, low severity) | — | 745 | +745 |

The 108 post-fix CODEC_BUG count is the true cross-vendor drift
signal — every entry is either (a) a single canonical structural
signal per cell-parent OR (b) per-field semantic drift on
surviving rows.  No multiplication.  Phase 4b investigation
agents now operate on a much higher signal-to-noise input.

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

## OPEN — surfaced by OPNsense supergate user-contrib smoke test

Source fixture: real OPNsense 25.x `config.xml` from a "supergate"
home router (igc0 WAN DHCP + ixl0 LAN at 192.168.88.2/24, lo0
loopback, 5 VLANs on ixl0 (USER 10, MGMT 11, SERVER 20, CLUSTER 100,
IOT 150) with L3 SVI on each via `opt1`-`opt5`, 2 local users with
bcrypt $2y$11$ hashes, 17 DNS A-record overrides, 11 DHCP static
reservations + 5 DHCP scopes, 16 firewall rules, 3 NAT port
forwards, IDS-config-but-disabled).

Targets exercised: aruba_aoss, fortigate_cli, juniper_junos,
mikrotik_routeros, cisco_iosxe_cli, arista_eos.

### Severity ranking

| # | Issue | Severity | Targets | Locus | Effort |
|---|---|---|---|---|---|
| 1 | arista_eos bcrypt leaks as `secret 5 bcrypt:...` | **CRITICAL (security)** | arista_eos | render hash-emit | small |
| 2 | cisco_iosxe_cli bcrypt leaks as `secret 5 bcrypt:...` | **CRITICAL (security)** | cisco_iosxe_cli | render hash-emit | small |
| 3 | Junos `set interfaces irb.10 unit 0 ...` malformed | **CRITICAL (deploy block)** | juniper_junos | render SVI emit | small |
| 4 | Aruba L3 SVI IPs dropped entirely (vlan declared, `interface vlan N / ip address` missing) | **CRITICAL (5 networks unreachable)** | aruba_aoss | render SVI emit | medium |
| 5 | FortiGate VLAN child has type/vlanid/parent but no IP | **CRITICAL (5 networks unreachable)** | fortigate_cli | render `_build_vlan_children` SVI lookup | medium |
| 6 | FortiGate VLAN parent bound to igc0 (WAN) instead of LAN port | **CRITICAL** | fortigate_cli | render parent-lookup | small |
| 7 | MikroTik VLAN parent / LAN IP split (LAN on sfp-sfpplus0, VLANs on synthesized bridge1) | **CRITICAL** | mikrotik_routeros | render bridge-synth conditional | medium |
| 8 | `interface igc0` literal stub leaks across 4 codecs | high | aruba, fortigate, cisco, arista | render empty-stub elision | small per codec |
| 9 | Junos no WAN DHCP emit (igc0 entirely dropped, source has `<ipaddr>dhcp</ipaddr>`) | high | juniper_junos | render WAN/DHCP path | small |
| 10 | Firewall + NAT + DHCP + DNS-overrides all silently dropped | medium | all 6 targets | NEW render paths per codec | **LARGE — deferred to next session** |
| 11 | VLAN name (`<vlans><descr>`) vs SVI description (`<opt1><descr>`) inconsistent | low | informational | canonical descr reconciliation | low (decide policy first) |
| 12 | Domain `example.test` only emitted on cisco_iosxe_cli + junos | medium | aruba, fortigate, mikrotik, arista | render domain emit | small per codec |
| 13 | MikroTik users have wrong group (`read` instead of `full`/`operator`) and no password | medium | mikrotik_routeros | render user-group mapping | small |

### Notes on issue 1 + 2 (hash leak)

Wave 2 added cross-vendor hash gating in `_user_secrets.is_migratable`
and wired aruba_aoss, fortigate_cli, juniper_junos, opnsense to
call it.  arista_eos and cisco_iosxe_cli were NOT in the wave 2
scope and still emit `secret 5 bcrypt:$2y$11$...` for foreign hashes.
Fix is to mirror the wave 2 pattern (commit `b2036aa` fortigate is the
cleanest model): import the helper, gate the password emit, fall
back to a `! password manager user-name "X" -- review: ...` comment
when not migratable.  Also fix the wrong type tag — `secret 5` is
md5crypt; bcrypt should never appear with that tag regardless of the
gate decision.

### Notes on issue 3 (Junos `irb.X unit 0`) — FIXED

Junos render emitted `set interfaces irb.10 unit 0 family inet
address 192.168.10.1/24`.  In Junos syntax `irb.10` is shorthand
for `irb unit 10`, so adding `unit 0` produced `irb unit 10 unit 0`
— invalid.  Fix landed in
`netconfig/migration/codecs/juniper_junos/render.py`: a new
`_LOGICAL_SVI_NAME_RE` matches `irb.<N>` / `vlan.<N>` names in
the iface loop and routes them through the sub-interface branch
with parent=``irb`` (or ``vlan``) and unit=``N``, so the emitted
form becomes `set interfaces irb unit 10 family inet address
192.168.10.1/24` — accepted by Junos's commit-time validator.

Verification: 4 new unit tests in
`tests/unit/migration/codecs/juniper_junos/test_l2_render_and_dot_zero_parse.py`
(`test_irb_dot_unit_renders_without_double_unit`,
`test_irb_multiple_units_render_correctly`,
`test_physical_port_unit_0_still_emits` regression guard,
`test_irb_dot_unit_round_trip_canonical_stable`).

### Notes on issues 4 + 5 (SVI IP drops)

Both Aruba and FortiGate declare the VLANs but drop the L3 SVI IPs:

- Aruba: `vlan N / name "X" / exit` with no follow-up `interface
  vlan N / ip address X.X.X.X/Y` block.
- FortiGate: `edit "vlanN" / set type vlan / set vlanid N / set
  interface "..." / next` with no `set ip A.B.C.D M.M.M.M`.

Wave 2 commit `b2036aa` added FortiGate's `_build_vlan_children`
helper specifically to fix this for c9300 source — but apparently
the SVI-IP lookup walks `tree.vlans[].ipv4_addresses` whereas the
OPNsense parser stores VLAN SVI IPs on the corresponding
`CanonicalInterface` (the opt1-opt5 entries).  Fix: extend the
SVI-IP lookup to also walk interfaces with matching `vlan_id`
binding.  Mirror the same fix on the Aruba SVI render path
(which currently looks like it doesn't emit SVI L3 at all).

### Notes on issue 7 (MikroTik bridge synthesis)

Wave 2 commit `3f528b7` synthesises `/interface bridge add
name=bridge1` when canonical tree has VLANs but no real bridges.
For OPNsense source, `ixl0` IS the parent — bridge synthesis
should NOT fire when source already has a parent interface.
Conditional needs: only synthesise when there's no canonical
"parent of this VLAN" interface.  When ixl0 is the parent, VLANs
should bind to its target-side rename (`sfp-sfpplus0`), and the
LAN IP should also land there or on a per-vendor convention
that keeps everything cohesive.

### Notes on issue 8 (igc0 stub elision)

Junos already elides correctly (commit `0fdf7e9` tiered policy).
arista_eos, cisco_iosxe_cli, aruba_aoss, fortigate_cli all emit
some flavour of `interface igc0` (or `edit "igc0"` for FortiGate)
verbatim because the OPNsense source-vendor port name is preserved
in the canonical model and these codecs have no rule to elide
content-free non-native ports.  Mirror the Junos tiered elision
policy: skip empty stubs unless they're VRF-bound, parent of a
sub-unit, or match the target's physical-port shape.

### Notes on issue 9 (Junos no WAN DHCP) — canonical-layer-DEFERRED

OPNsense source has `<wan><ipaddr>dhcp</ipaddr>` on igc0 — DHCP
client semantic.  Junos render emits no equivalent because Junos's
empty-stub elision (correctly) suppresses an interface with no
static IP / no description / no MTU / no L2.

Investigation: `CanonicalInterface.dhcp_client: bool` exists on
the schema (`netconfig/migration/canonical/intent.py` line 139)
and IS consumed by both Cisco IOS-XE and MikroTik render paths
(`if iface.dhcp_client: out.append(" ip address dhcp")` /
equivalent).  But the OPNsense parser
(`netconfig/migration/codecs/opnsense/parse.py
_parse_interface_zone_canonical`) only handles static
`<ipaddr>X.X.X.X</ipaddr>` + `<subnet>N</subnet>`; the
`<ipaddr>dhcp</ipaddr>` keyword path is dropped on the floor.

**Scope decision:** the render-side fix (Junos emit
`set interfaces ge-0/0/X unit 0 family inet dhcp` when
`iface.dhcp_client=True`) is trivially small but currently
unreachable from OPNsense-source pipelines because the canonical
field is never populated.  Deferred in this session per the
"don't expand scope into the canonical layer" directive.  The
proper fix lives across two codecs:

- `opnsense/parse.py`: detect `<ipaddr>dhcp</ipaddr>` (also
  `dhcp6` for v6) and set `iface.dhcp_client=True` instead of
  silently skipping the address.
- `juniper_junos/render.py`: emit
  `set interfaces <name> unit 0 family inet dhcp` when
  `iface.dhcp_client=True`, AND skip the empty-stub elision for
  the same interface (dhcp_client makes it non-empty).

Sub-finding logged for follow-up:

| # | Issue | Severity | Targets | Locus | Effort |
|---|---|---|---|---|---|
| 9a | OPNsense parser silently drops `<ipaddr>dhcp</ipaddr>` (no `dhcp_client` set) | medium | opnsense parse | parse interface-zone | small |
| 9b | Junos render has no `family inet dhcp` emit path for `iface.dhcp_client=True` | medium | juniper_junos render | render interface loop | small |

Both small; both blocked on each other landing for the WAN-DHCP
end-to-end signal to surface.  Defer-as-a-pair until the OPNsense
parser side is in scope.

### Notes on issue 10 (wide silent drops — deferred)

OPNsense source has rich firewall (16 `<filter><rule>` entries),
NAT (3 `<nat><rule>` port forwards), DHCP (5 `<dhcp_ranges>`
scopes + 11 `<hosts>` static reservations via dnsmasq), DNS
overrides (17 `<unboundplus><hosts>` A records), and IDS config.
None of this appears in any target output.

Cross-vendor render paths for these would be substantial new
work per codec:
- RouterOS: `/ip firewall filter`, `/ip firewall nat`, `/ip
  dhcp-server`, `/ip dns static`
- FortiGate: `config firewall policy`, `config firewall vip`,
  `config system dhcp server`, `config system dns-database`
- Junos: `set firewall family inet filter`, `set security nat`,
  `set system services dhcp`, `set system static-host-mapping`
- Cisco IOS-XE / Arista: `ip access-list extended`, `ip nat
  inside source`, `ip dhcp pool`, `ip host`
- Aruba AOS-S: limited firewall (ACLs only); DHCP server pool;
  `ip dns server-domain-name`

Deferred to a separate session — too large for the current
sweep.  See cluster E in the session triage.

### Cluster mapping (parallel codec-grouped agents)

The 13 OPEN findings (excluding cluster E) split cleanly into
6 per-codec agents:

| Codec | Findings owned | Files |
|---|---|---|
| arista_eos | 1, 8 (igc0), 12 (domain) | arista_eos render |
| cisco_iosxe_cli | 2, 8, 12 (already does it actually) | cisco_iosxe_cli render |
| juniper_junos | 3, 9 | junos render |
| aruba_aoss | 4, 8, 12 | aruba render |
| fortigate_cli | 5, 6, 8, 12 | fortigate render + port_names |
| mikrotik_routeros | 7, 12, 13 | mikrotik render + port_names |

Finding 11 (descr reconciliation) is informational — both source
fields are different by design; render fidelity preserves both.
No action.

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

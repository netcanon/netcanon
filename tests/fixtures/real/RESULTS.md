# Real-capture validation results

Human-readable snapshot of `tests/unit/migration/test_real_captures.py`
as of the latest known-good run.  Provenance for every fixture is in
`NOTICE.md` alongside this file.

The harness asserts three invariants per fixture:

1. **Parse doesn't crash** — `codec.parse(raw)` must not raise.
2. **Parse produces something** — at least one canonical field is
   populated (zero extraction on a non-empty config is a silent-drop
   regression signature).
3. **Round-trip stability** (bidirectional codecs only) —
   `canonical(parse(render(parse(raw))))` matches `canonical(parse(raw))`.

Parse is also asserted deterministic (twice-parsed input produces
equal trees).

---

## cisco_iosxe_cli

**Codec:** `netconfig.migration.codecs.cisco_iosxe_cli.CiscoIOSXECLICodec`
**Direction:** `parse_only` *(round-trip N/A)*
**Certainty:** `best_effort`

### Coverage matrix

| Fixture | Lines | hostname | interfaces | vlans | routes | lags | snmp | Notes |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `batfish_cisco_interface.txt` | 337 | 1 | 24 | 9 | 0 | 1 | 0 | Grammar kitchen-sink — every interface sub-command Batfish supports. |
| `batfish_cisco_ip_route.txt` | 26 | 1 | 0 | 0 | 10 | 0 | 0 | Static-route variants (interface next-hops, IP next-hops). |
| `ntc_carrier_interfaces.txt` | 82 | 0 | 6 | 0 | 0 | 0 | 0 | Carrier IOS: VRFs, dot1Q Q-in-Q subinterfaces, QoS, ACL groups, uRPF. |
| `batfish_cisco_aaa.txt` | 102 | 1 | 0 | 0 | 0 | 0 | 0 | AAA stanzas — tests parser tolerance for unmodelled commands. |
| `batfish_cisco_snmp.txt` | 110 | 1 | 0 | 0 | 0 | 0 | 1 | `snmp-server community` with groups + views + users. |
| `batfish_cisco_logging.txt` | 101 | 1 | 0 | 0 | 0 | 0 | 0 | `logging host`, buffered, facility — not canonically modelled, validates "parse doesn't crash". |

### Findings

**Bug surfaced + fixed:** `_parse_lags` appended `Ethernet0` seven
times to a LAG member list when the Batfish kitchen-sink stacked
seven `channel-group 1 mode <variant>` lines on a single interface.
Dedupe + regression test landed in the same commit.

**Known silent drops (by design):** VRFs, Q-in-Q encap, QoS
service-policies, interface ACL groups, IPv6 addressing, proxy-ARP,
uRPF, bandwidth hint.  All mapped to existing roadmap buckets (Tier 3
raw_sections or Fidelity Polish).

---

## opnsense

**Codec:** `netconfig.migration.codecs.opnsense.OPNsenseCodec`
**Direction:** `bidirectional`
**Certainty:** `best_effort` *(unchanged)*

### Coverage matrix

| Fixture | Lines | hostname | interfaces | dhcp | local_users | Notes |
|---|---:|---:|---:|---:|---:|---|
| `opnsense_core_default.xml` | 141 | 1 | 2 | 0 | 1 | Upstream default `config.xml` template — system, users, groups, timeservers, interface stubs. |
| `opnsense_service_test_config.xml` | 91 | 0 | 3 | 0 | 0 | Service-layer test config with real wan/lan/opt1 zones, DHCP client + DHCPv6 prefix delegation, gateway tracking. |
| `opnsense_acl_test_config.xml` | 239 | 1 | 2 | 1 | 5 | ACL model test — 5 users + 4 groups with distinct priv sets.  Richest local_users surface in the corpus. |

### Findings

**Nothing failed.**  Both fixtures parse cleanly, round-trip cleanly.
The OPNsense codec benefits from `ElementTree`-based parsing — XML
grammar is rigidly enforced by the parser library, so "parse doesn't
crash" is a cheap-to-validate invariant.

### Certification decision

**Stay at `best_effort`.**  Two fixtures from a single source repo
(albeit the canonical upstream) don't meet the `certified` threshold
(≥3 captures from ≥2 OS versions).  Promotion awaits a second
upstream or a sanitised customer deployment config.

---

## mikrotik_routeros

**Codec:** `netconfig.migration.codecs.mikrotik_routeros.MikroTikRouterOSCodec`
**Direction:** `bidirectional`
**Certainty:** `best_effort` *(unchanged)*

### Coverage matrix

| Fixture | Lines | hostname | interfaces | vlans | dhcp | snmp | Notes |
|---|---:|---:|---:|---:|---:|---:|---|
| `ntc_ip_address_export.rsc` | 8 | 0 | 2 | 0 | 0 | 0 | Real RouterOS 6.48.6 `/export verbose` snippet — `/ip address` with quoted comments and vendor banner. |
| `routeros_diff_verbose_export.rsc` | 484 | 1 | 9 | 1 | 2 | 1 | Real RouterOS 6.48.1 `/export verbose` from an RB952Ui-5ac2nD home router.  Different OS version (gives MikroTik 2-OS-version coverage already).  `/interface bridge`, `/interface vlan`, `/ip dhcp-server network` + `/ip pool`, `/snmp` all exercised. |

### Known round-trip gap

`routeros_diff_verbose_export.rsc` **parses cleanly** but can't
round-trip bit-exact via our codec — whitelisted via
`_KNOWN_ROUNDTRIP_GAPS` in `test_real_captures.py`.  Two codec bugs
the fixture surfaced, both queued under Fidelity Polish in
translator-plans.txt:

1. **Bridge render not implemented.**  `/interface bridge add
   name=upstream` parses into `CanonicalInterface(interface_type=
   "ianaift:bridge")` but our renderer doesn't emit `/interface
   bridge` at all — the bridge survives the first parse, disappears
   on render, and the second parse sees nothing.
2. **VLAN interface name synthesis.**  The fixture defines a VLAN
   interface as `/interface vlan add name=gn-mgmt interface=ether3
   vlan-id=84` — name is `gn-mgmt`, not `vlan84`.  Our renderer
   emits it as synthetic `vlan84` which re-parses as a different
   name, dropping the `gn-mgmt` -> vlan-id=84 mapping.

### Findings

**Bug surfaced + fixed:** `parse → render → parse` round-trip was
unstable.  First parse saw only `/ip address` section and emitted
`CanonicalInterface(name="ether2", interface_type="")`.  Render
emitted a `/interface ethernet` stub based on the ether-name pattern.
Second parse then saw `/interface ethernet` and set
`interface_type="ianaift:ethernetCsmacd"` — breaking equality.

Fix: added `_infer_iface_type_from_name()` helper, now called from
every code path that materialises a fresh `CanonicalInterface`
(`_parse_ip_address`, LAG member reverse-linking, etc.).  Interface
type is now inferred from name pattern consistently on first parse,
regardless of which section introduces the name.  3 regression tests
in `TestInterfaceTypeInferenceRoundTrip`.

### Certification decision

**Stay at `best_effort`.**  Single fixture is well below the
`certified` threshold.  Need at least 2 more real exports (ideally
from RouterOS 7.x) to graduate.

---

## fortigate_cli

**Codec:** `netconfig.migration.codecs.fortigate_cli.FortiGateCLICodec`
**Direction:** `bidirectional`
**Certainty:** `best_effort` *(unchanged)*

### Coverage matrix

| Fixture | Lines | hostname | dns | interfaces | vlans | routes | lags | dhcp | local_users | Notes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `kevinguenay_fgt_70g_branch.conf` | 12,317 | 1 | 2 | 21 | 2 | 1 | 2 | 1 | 1 | Real FortiOS 7.6.6 branch config — `fortilink` + `LAG_INTERNAL` aggregates, VL_100/VL_101 VLAN subinterfaces on LAG_INTERNAL, LO_BGP loopback, SD-WAN, IPsec, firewall policies. |
| `kevinguenay_fgt_vm_hub.conf` | 13,827 | 1 | 2 | 19 | 0 | 1 | 1 | 1 | 1 | Real FortiOS 7.6.6 VM hub — the counterpart hub config for the branch above.  Same OS version → doesn't unlock `certified` tier on its own. |

### Findings

**Bug surfaced + fixed:** Our parser required `set type vlan`
explicitly on a VLAN subinterface edit.  Real FortiOS configs often
omit it — a VLAN is unambiguously implied by the pair
`set vlanid <N>` + `set interface "<parent>"`.  VL_100 and VL_101 in
the branch config had that shape and were previously mis-typed as
`ethernetCsmacd` (via the name-pattern fallback) and dropped from
`intent.vlans`.

Fix: `_apply_system_interface` now recognises `vlanid + parent` as
a VLAN signal even without `set type vlan`.  Also changed the VLAN
name to use the iface name (not the alias) so `_vlan_id_for` can
resolve it on render.  3 regression tests in
`TestRealConfigVlanInference` pin the corrected behaviour.

**Scale note:** 12,317 lines of real FortiOS config — the largest
fixture in the corpus by an order of magnitude — parsed and
round-tripped cleanly (after the VLAN fix).  Strong evidence that
the recursive block parser handles the full FortiOS `config / edit /
set / next / end` grammar at scale.

### Certification decision

**Stay at `best_effort`.**  One fixture, one OS version (7.6.6).
Promoting to `certified` needs 2 more captures, preferably from
FortiOS 6.x or 7.4.x.  Good candidates: FortiGate config-archive
repos from Fortinet Developer Network (FNDN) or community
deployments.

---

## aruba_aoss

**Codec:** `netconfig.migration.codecs.aruba_aoss.ArubaAOSSCodec`
**Direction:** `bidirectional`
**Certainty:** `best_effort` *(unchanged)*

### Coverage matrix

| Fixture | Lines | hostname | dns | interfaces | vlans | routes | lags | Notes |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `aruba_central_5memberstack_rendered.cfg` | 162 | 1 | 1 | 48 | 3 | 3 | 1 | Rendered from Aruba Central's 5MemberStack bulk-config template via in-tree script (see `aruba_aoss/README.md`).  Exercises hostname, module/snmp engine id, motd banner, logging, static routes (incl. default gateway), manager password stanza, NTP, VLAN 1 + VLAN 20 (USERS) + VLAN 30 (VOICE) with tagged/untagged port lists, 48 interfaces + A1, `trunk` LAG, STP, device-profile for APs. |

### Findings

**Harness refinement surfaced (not a codec bug):** The round-trip
invariant's strict-equality comparison broke on ordering differences.
First parse saw interfaces before `vlan` stanzas (template layout);
our render emits VLANs first; second parse then appended Vlan SVI
interfaces at the front, diverging from first parse's interface list
order.  Canonical *meaning* was identical — the ordering difference
was cosmetic.  Fixed the harness to sort collections by natural
identity key (interfaces by name, vlans by id, etc.) before comparing.
Applies to all codecs; no codec behaviour changed.

**Rendering-script refinement surfaced:** Initial render produced
only 22 lines (most VLANs/interfaces dropped) because the template
inconsistently uses `member.1.ports` (no underscore) vs.
`_member.N.ports` for N>1.  Populate both forms in the substitutions
dict.  Then: only 1 VLAN visible post-parse because the template's
nested `%if%` blocks indent `vlan <N>` sub-stanzas and our AOS-S
parser treats indented lines as stanza body (which is correct for
real AOS-S — real output doesn't have this problem).  Added a
post-pass to the render script that dedents any line starting with
a recognised AOS-S top-level keyword.  Final coverage: 3 VLANs,
48 interfaces, 3 static routes, 1 LAG — matches what the template
describes.

### Certification decision

**Stay at `best_effort`.**  The fixture is rendered, not captured,
so strictly speaking it's still exercising grammar Aruba's template
author anticipated — not the long tail of real deployments.
Promoting to `certified` requires a sanitised real capture.

### Do-better note

A genuine sanitised AOS-S capture would be strictly more valuable.
Candidate paths to get one are listed in `aruba_aoss/README.md`.
Swap the rendered fixture out whenever we find one.

---

## Summary

| Codec | Fixtures | OS versions | Bugs surfaced | Certainty | Certified blocker |
|---|---:|---:|---:|---|---|
| cisco_iosxe_cli | 6 | 1* | 1 (LAG member dedup) | best_effort | *all fixtures are Batfish/NTC test data; need a real captured 15.x/16.x/17.x config to count as a 2nd OS version |
| opnsense | 3 | 1 | 0 | best_effort | need fixture from a non-`opnsense/core` source |
| mikrotik_routeros | 2 | 2 (6.48.1 + 6.48.6) | 2 (round-trip interface_type drift; hostname-with-spaces quoting) | best_effort | need 1 more fixture (and ideally a RouterOS 7.x version) |
| fortigate_cli | 2 | 1 (7.6.6) | 1 (implicit VLAN typing) | best_effort | need fixture from 7.4.x or 6.x |
| aruba_aoss | 1 *(rendered from template, not captured)* | — | 0 (harness + render-script refinements only) | best_effort | need any real sanitised capture |
| **TOTAL** | **14** | — | **4** | — | — |

Three bugs surfaced in the first real-capture pass.  All three would
have survived arbitrarily long against our synthetic fixtures —
exactly the kind of regression class the harness was built to catch.
All fixes include regression tests so reverting them breaks CI.

**Notable success:** the 12K-line real FortiOS config parsed and
round-tripped cleanly after one grammar fix — strong evidence the
recursive block parser generalises beyond hand-crafted samples.

No codec is `certified` yet.  The threshold is ≥3 captures from
≥2 OS versions with round-trip stability — each vendor is ~2
captures short of that bar.  Follow-up: find more captures
(preferably from different OS versions) per vendor, and Aruba AOS-S
needs a first real capture at all.

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

| Fixture | Lines | hostname | interfaces | vlans | static_routes | lags | Notes |
|---|---:|---:|---:|---:|---:|---:|---|
| `batfish_cisco_interface.txt` | 337 | 1 | 24 | 9 | 0 | 1 | Grammar kitchen-sink — every interface sub-command Batfish supports. |
| `batfish_cisco_ip_route.txt` | 26 | 1 | 0 | 0 | 10 | 0 | Static-route variants (interface next-hops, IP next-hops). |
| `ntc_carrier_interfaces.txt` | 82 | 0 | 6 | 0 | 0 | 0 | Carrier IOS: VRFs, dot1Q Q-in-Q subinterfaces, QoS, ACL groups, uRPF. |

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

| Fixture | Lines | hostname | interfaces | Notes |
|---|---:|---:|---:|---|
| `opnsense_core_default.xml` | 141 | 1 | 2 | Upstream default `config.xml` template — system, users, groups, timeservers, interface stubs. |
| `opnsense_service_test_config.xml` | 91 | 0 | 3 | Service-layer test config with real wan/lan/opt1 zones, DHCP client + DHCPv6 prefix delegation, gateway tracking. |

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

| Fixture | Lines | hostname | interfaces | Notes |
|---|---:|---:|---:|---|
| `ntc_ip_address_export.rsc` | 8 | 0 | 2 | Real RouterOS 6.48.6 `/export verbose` snippet — `/ip address` with quoted comments and vendor banner. |

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

| Fixture | Lines | hostname | dns | interfaces | vlans | routes | lags | Notes |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `kevinguenay_fgt_70g_branch.conf` | 12,317 | 1 | 2 | 21 | 2 | 1 | 2 | Real FortiOS 7.6.6 branch config — `fortilink` + `LAG_INTERNAL` aggregates, VL_100/VL_101 VLAN subinterfaces on LAG_INTERNAL, LO_BGP loopback, SD-WAN, IPsec, firewall policies. |

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

**STATUS: BLOCKED** — see `aruba_aoss/README.md` for what was
searched and how to unblock.  No permissively-licensed public AOS-S
running-config captures found.

Follow-up sessions should consider rendering Aruba Central's
`central-sample-bulk-configurations` 5MemberStack template through a
placeholder-substitution script and committing the output with
provenance pointing at both the template and the script.

---

## Summary

| Codec | Fixtures | Bugs surfaced | Certainty |
|---|---:|---:|---|
| cisco_iosxe_cli | 3 | 1 (LAG member dedup) | best_effort |
| opnsense | 2 | 0 | best_effort |
| mikrotik_routeros | 1 | 1 (round-trip interface_type drift) | best_effort |
| fortigate_cli | 1 | 1 (implicit VLAN typing) | best_effort |
| aruba_aoss | 0 | BLOCKED | best_effort |
| **TOTAL** | **7** | **3** | — |

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

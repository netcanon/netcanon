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
**Certainty:** `certified` ✅

### Coverage matrix

| Fixture | Lines | hostname | interfaces | vlans | routes | lags | snmp | users | Notes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `batfish_cisco_interface.txt` | 337 | 1 | 24 | 9 | 0 | 1 | 0 | 0 | Grammar kitchen-sink — every interface sub-command Batfish supports. |
| `batfish_cisco_ip_route.txt` | 26 | 1 | 0 | 0 | 10 | 0 | 0 | 0 | Static-route variants (interface next-hops, IP next-hops). |
| `ntc_carrier_interfaces.txt` | 82 | 0 | 6 | 0 | 0 | 0 | 0 | 0 | Carrier IOS: VRFs, dot1Q Q-in-Q subinterfaces, QoS, ACL groups, uRPF. |
| `batfish_cisco_aaa.txt` | 102 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | AAA stanzas — tests parser tolerance for unmodelled commands. |
| `batfish_cisco_snmp.txt` | 110 | 1 | 0 | 0 | 0 | 0 | 1 | 0 | `snmp-server community` with groups + views + users. |
| `batfish_cisco_logging.txt` | 101 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | `logging host`, buffered, facility — not canonically modelled, validates "parse doesn't crash". |
| `racc_csr1000v_iosxe169_bgp_ospf.txt` | 280 | 1 | 11 | 0 | 1 | 0 | 0 | 2 | Real `show run` from CSR1000v on **IOS-XE 16.9 LTS**.  BGP AS 65001 (vpnv4 + rtfilter AFs), OSPF, QoS policy-maps, syslog-host, RESTCONF + NETCONF-YANG, `enable secret`. |
| `racc_csr1_iosxe173_umbrella_sig.txt` | 398 | 1 | 6 | 0 | 22 | 0 | 0 | 2 | Real `show run` from CSR1000v on **IOS-XE 17.3 LTS**.  EIGRP CITYNET, OSPF, 22 static routes (Cisco Umbrella SIG anycast), IKEv2 + IPsec profiles + `tunnel protection`, SSH pubkey-chain, guestshell. |
| `racc_cat8000v_iosxe179_netconf.txt` | 343 | 1 | 7 | 0 | 1 | 0 | 0 | 1 | Real `show run` from Cat8000V on **IOS-XE 17.9 LTS**.  `ip nat inside source list ... overload`, `telemetry ietf subscription` (YANG-push over grpc-tcp), app-hosting guestshell, RESTCONF + NETCONF-YANG, `username X secret 9 $9$...` type-9 hash. |

### Findings

**Bug surfaced + fixed:** `_parse_lags` appended `Ethernet0` seven
times to a LAG member list when the Batfish kitchen-sink stacked
seven `channel-group 1 mode <variant>` lines on a single interface.
Dedupe + regression test landed in the same commit.

**Known silent drops (by design):** VRFs, Q-in-Q encap, QoS
service-policies, interface ACL groups, IPv6 addressing, proxy-ARP,
uRPF, bandwidth hint.  All mapped to existing roadmap buckets (Tier 3
raw_sections or Fidelity Polish).

**Zero bugs surfaced by the 3 new real captures.**  All three racc
fixtures parsed cleanly on first contact and produced non-empty
canonical trees — evidence the grammar coverage from the Batfish /
NTC corpus already generalised to real deployed CSR1000v / Cat8000V
configs on 16.9 / 17.3 / 17.9 LTS.  The large cert chains, IKEv2
profiles, guestshell stanzas, telemetry subscriptions, and PKI
trustpoints fell through to "parse-and-ignore" without tripping the
parser — exactly as designed.

### Certification decision

**Promoted to `certified`.**  Three BSD-3-Clause real captures from
[nickrusso42518/racc](https://github.com/nickrusso42518/racc) landed
the corpus at 9 fixtures across 3 distinct LTS OS versions (**16.9,
17.3, 17.9**).  All three real captures start with the authoritative
`Building configuration...` / `Current configuration : NNNN bytes` /
`! Last configuration change at ...` / `version X.X` banners that
prove they're device outputs rather than hand-crafted grammar tests.
Parse-only direction means round-trip is N/A — the cert bar for
`parse_only` codecs is ≥3 real captures from ≥2 OS versions that
parse cleanly and produce populated canonical trees, which the three
racc fixtures meet decisively.

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
| `routeros_diff_verbose_export.rsc` | 484 | 1 | 9 | 1 | 2 | 1 | Real RouterOS 6.48.1 `/export verbose` from an RB952Ui-5ac2nD home router.  `/interface bridge`, `/interface vlan`, `/ip dhcp-server network` + `/ip pool`, `/snmp` all exercised. |
| `taqavi_initial_provisioning.rsc` | 133 | 0 | 7 | 0 | 1 | 0 | Real MikroTik provisioning script targeting an L009UiGS-2HaxD router.  Not a `/export` capture — a script admins run. |
| `user_contrib_crs310_ros7.rsc` | 630 | 1 | 16 | 5 | 0 | 1 | Real RouterOS 7.18.2 `/export verbose` from a CRS310-8G+2S+ switch (user contribution, sanitised).  Renamed ethernet ports (Desktop / "Access Point" / "CLUSTER - PVE3"...), 5 VLANs, full `/interface bridge port` table, extensive system-level config.  The fixture that unblocked MikroTik `certified` tier. |

### Codec bugs surfaced + fixed

Both previously-tracked round-trip gaps (bridge render, VLAN name
preservation) were fixed as Fidelity Polish items this session.  No
fixtures currently in `_KNOWN_ROUNDTRIP_GAPS`:

1. **Bridge render** — now emits `/interface bridge` section for
   every CanonicalInterface typed `ianaift:bridge`, preserving name
   (with quoting for spaces) and description.  Regression tests in
   `TestBridgeRender`.
2. **VLAN interface name preservation** — render now filters by
   `interface_type == "ianaift:l3ipvlan"` (not just name pattern),
   so named VLAN interfaces like `gn-mgmt` survive without being
   rewritten to synthetic `vlan<N>`.  Regression tests in
   `TestVlanInterfaceNamePreservation`.

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

**Promoted to `certified`.**  Four real fixtures across three
distinct OS versions (6.48.1, 6.48.6, 7.18.2) with all four round-
tripping cleanly after the bugs surfaced in-session were fixed.
Each bug added a regression test so reverting the fix breaks CI.
This is the first codec in the project to hit `certified` tier.

Bugs surfaced by the user-contributed CRS310 fixture and fixed in
the same pass to unblock the promotion:

* **Interface rename not captured.** Real configs do
  `set [ find default-name=ether2 ] name="Access Point"` — the
  canonical was storing `ether2` as the iface name, discarding the
  rename.  The rest of the config (bridge ports, VLAN parents, IP
  addresses, etc.) references the renamed name, so the canonical
  was fundamentally wrong.  Added
  `CanonicalInterface.default_name` field; parser now stores the
  renamed name as `.name` and the factory default-name as
  `.default_name`; renderer uses `.default_name` as the
  `find default-name=X` key and emits `name=X` only when the
  iface has actually been renamed (no `name=ether1` noops).
* **`CanonicalVlan.name` semantics.**  Was storing the comment
  ("Management", "Cluster"), which made render's `_vlan_id_for`
  lookup fail for named VLAN ifaces — producing ghost `vlan<N>`
  synthetic records alongside the real ones on round-trip.  Now
  stores the iface name (mgmtvlan11, clustervlan100); the comment
  moves to `CanonicalVlan.description`.  One existing test that
  asserted the old semantics was updated in the same commit.

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
**Certainty:** `certified` ✅

### Coverage matrix

| Fixture | Lines | hostname | dns | interfaces | vlans | routes | lags | snmp | Notes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `aruba_central_5memberstack_rendered.cfg` | 162 | 1 | 1 | 48 | 3 | 3 | 1 | 0 | Rendered from Aruba Central's 5MemberStack bulk-config template via in-tree script (see `aruba_aoss/README.md`).  Exercises hostname, module/snmp engine id, motd banner, logging, static routes (incl. default gateway), manager password stanza, NTP, VLAN 1 + VLAN 20 (USERS) + VLAN 30 (VOICE) with tagged/untagged port lists, 48 interfaces + A1, `trunk` LAG, STP, device-profile for APs. |
| `hpe_community_2930f_wc1607_intervlan.cfg` | 109 | 1 | 1 | 10 | 12 | 4 | 0 | 1 | Real 2930F `show running-config` on **WC.16.07.0002**.  12 VLANs with per-VLAN SVIs, `ip helper-address` (DHCP relay), `ip forward-protocol udp` for DNS/NTP, `primary-vlan`, 4 static routes including `ip default-gateway`.  Inter-VLAN L3 at realistic scale. |
| `hpe_community_2920_wb1608_dhcp_snooping.cfg` | 74 | 1 | 0 | 9 | 2 | 1 | 0 | 1 | Real 2920 `show running-config` on **WB.16.08.0001** — different switch family (2920 = J9729A vs 2930F/5406R) and major OS branch (WB vs WC).  Exercises `dhcp-snooping` with 13 authorized-servers, `ntp unicast` with public peer, `web-management ssl`, `ip authorized-managers`, `snmp-server host ... trap-level critical`. |
| `hpe_community_2930f_wc1610_dhcp_server.cfg` | 58 | 1 | 0 | 4 | 4 | 1 | 0 | 1 | Real 2930F `show running-config` on **WC.16.10.0005**.  `dhcp-server pool` grammar (3 pools with default-router + dns-server + network + range), per-VLAN `dhcp-server` enable flag, `allow-unsupported-transceiver`. |

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

**Promoted to `certified`.**  Three sanitised captures from HPE
Community forum threads landed the corpus at 4 fixtures across
**3 distinct OS versions** (WC.16.07.0002, WB.16.08.0001,
WC.16.10.0005) and **2 switch families** (2920 J9729A + 2930F
JL258A/JL260A).  All four round-trip clean on first parse — zero
codec bugs surfaced by the real-capture pass.  The pre-existing
rendered template fixture remains a 4th data point but is not
counted toward OS-version diversity (it's synthetic).

Grammar exercised across the three real captures that wasn't
exercised by the rendered template:

* **Real `ip default-gateway`** line (not synthesised into
  `ip route 0.0.0.0/0`) — validates Bug 4 fix holds on real input.
* **`ip helper-address`** (DHCP relay) at scale — 10 VLANs in C3
  use it; none previously.
* **`ip forward-protocol udp <ip> <service>`** (DNS/NTP helper
  forwarding) — parse-and-ignore grammar not in any other fixture.
* **`dhcp-snooping`** with `authorized-server`, `vlan` scope,
  trust-port, `no option 82` — silent-drop validation.
* **`dhcp-server pool`** with `default-router` / `dns-server` /
  `network` / `range` sub-lines, plus per-VLAN `dhcp-server` enable
  flag — the only capture exercising AOS-S's (rare) built-in DHCP
  server grammar.
* **`snmp-server host ... trap-level critical`** — trap-host
  target grammar.
* **`web-management ssl`**, **`ip authorized-managers ... access manager`**
  — silent-drop validation.
* **`primary-vlan N`**, **`allow-unsupported-transceiver`**,
  **`timesync ntp`** with `time daylight-time-rule` and `time timezone`
  — silent-drop validation.

---

## Summary

| Codec | Fixtures | OS versions | Bugs surfaced | Certainty | Certified blocker |
|---|---:|---:|---:|---|---|
| **cisco_iosxe_cli** | **9** (6 grammar-test + 3 real) | **3 LTS** (16.9 + 17.3 + 17.9) | 1 (LAG member dedup) | **certified** ✅ | — |
| opnsense | 3 | 1 | 0 | best_effort | need fixture from a non-`opnsense/core` source |
| **mikrotik_routeros** | **4** | **3** (6.48.1 + 6.48.6 + 7.18.2) | 6 | **certified** ✅ | — |
| fortigate_cli | 2 | 1 (7.6.6) | 1 (implicit VLAN typing) | best_effort | need fixture from 7.4.x or 6.x |
| **aruba_aoss** | **4** (3 real + 1 rendered) | **3** (WC.16.07 + WB.16.08 + WC.16.10) | 0 | **certified** ✅ | — |
| **TOTAL** | **22** | — | **8** | — | — |

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

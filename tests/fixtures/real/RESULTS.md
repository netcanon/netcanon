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
| `user_contrib_cat9300_iosxe1712.txt` | 491 | 1 | 47 | 6 | 1 | 3 | 0 | 2 | **Real physical Cat 9300-24UX on IOS-XE 17.12** (user-contributed, sanitised).  `switch 1 provision c9300-24ux`, Gi/TenG/FortyG/TwentyFiveG/AppG + Port-channel1-3 + Vlan SVIs + Mgmt-vrf, 3 LACP EtherChannels (`channel-group N mode active`), `switchport mode trunk/access` + `switchport trunk allowed vlan <list>` + `switchport trunk native vlan`, full Cat9k `class-map system-cpp-police-*` + `policy-map system-cpp-policy` CPP grammar, 28 × `privilege exec level 5 show X` delegation, multiple `line vty` ranges. |
| `cml_saumur_iosxe1712_pvrstp.txt` | 147 | 1 | 4 | 0 | 0 | 0 | 0 | 0 | Real `show run` from a CML virtual `ioll2-xe` on **IOS-XE 17.12**.  Uses `Ethernet0/N` IOL port notation (not physical `Gi1/0/N`) but the spanning-tree grammar is authentic: `spanning-tree mode rapid-pvst`, `spanning-tree pathcost method long`, `spanning-tree vlan 1-4094 priority 4096`, `spanning-tree link-type point-to-point`, `spanning-tree cost 2000000`.  Closes PVRST+ cost-tuning grammar coverage the Cat9300 fixture doesn't exercise. |

### Findings

**Bug surfaced + fixed:** `_parse_lags` appended `Ethernet0` seven
times to a LAG member list when the Batfish kitchen-sink stacked
seven `channel-group 1 mode <variant>` lines on a single interface.
Dedupe + regression test landed in the same commit.

**Known silent drops (by design):** VRFs, Q-in-Q encap, QoS
service-policies, interface ACL groups, IPv6 addressing, proxy-ARP,
uRPF, bandwidth hint.  All mapped to existing roadmap buckets (Tier 3
raw_sections or Fidelity Polish).

**Zero bugs surfaced by the 5 new real captures.**  All parsed
cleanly on first contact and produced populated canonical trees.
Large cert chains, IKEv2 profiles, guestshell stanzas, telemetry
subscriptions, Cat9k CPP `class-map`/`policy-map` stanzas, and PKI
trustpoints all fell through to "parse-and-ignore" without tripping
the parser — exactly as designed.  The Cat 9300 capture in
particular exercised grammar the earlier Batfish / NTC synthetic
corpus never stressed: real 3-part port notation (`TenGigabitEthernet1/0/N`,
`FortyGigabitEthernet1/1/N`, `TwentyFiveGigE1/1/N`, `AppGigabitEthernet`),
3 LACP `Port-channel` interfaces bound via `channel-group N mode
active`, the full Cat9k `class-map system-cpp-police-*` table, and
the long `privilege exec level 5 show X` delegation set — and
every one of them parsed cleanly.

### Certification decision

**Promoted to `certified`.**  Two complementary corpora meet the
bar decisively:

* **Router grammar (3 fixtures from 3 LTS OS versions)** —
  [nickrusso42518/racc](https://github.com/nickrusso42518/racc)
  under BSD-3-Clause:
  `racc_csr1000v_iosxe169_bgp_ospf.txt` (16.9 LTS, BGP+OSPF+QoS),
  `racc_csr1_iosxe173_umbrella_sig.txt` (17.3 LTS, IKEv2+IPsec+
  Umbrella SIG+EIGRP+OSPF), `racc_cat8000v_iosxe179_netconf.txt`
  (17.9 LTS, NAT+telemetry+NETCONF/RESTCONF).
* **Switch grammar (2 fixtures on IOS-XE 17.12)** —
  `user_contrib_cat9300_iosxe1712.txt` (real physical Cat 9300-
  24UX, user contribution, sanitised) + `cml_saumur_iosxe1712_pvrstp.txt`
  (CML virtual IOL under BSD-3 for PVRST+ cost grammar).

All 5 real captures start with authoritative
`Building configuration...` / `Current configuration : NNNN bytes` /
`! Last configuration change at ...` / `version X.X` banners that
prove they're device outputs rather than hand-crafted grammar tests.
`parse_only` direction means round-trip is N/A — the cert bar for
`parse_only` codecs is ≥3 real captures from ≥2 OS versions that
parse cleanly and produce populated canonical trees.  Across 4 real
OS-version anchors (16.9 + 17.3 + 17.9 + 17.12) and two distinct
device domains (virtual routers + physical switch + virtual switch),
the bar is met on both grammar fronts.

---

## opnsense

**Codec:** `netconfig.migration.codecs.opnsense.OPNsenseCodec`
**Direction:** `bidirectional`
**Certainty:** `certified` ✅

### Coverage matrix

| Fixture | Lines | hostname | interfaces | vlans | dhcp | local_users | Notes |
|---|---:|---:|---:|---:|---:|---:|---|
| `opnsense_core_default.xml` | 141 | 1 | 2 | 0 | 0 | 1 | Upstream default `config.xml` template — system, users, groups, timeservers, interface stubs. |
| `opnsense_service_test_config.xml` | 91 | 0 | 3 | 0 | 0 | 0 | Service-layer test config with real wan/lan/opt1 zones, DHCP client + DHCPv6 prefix delegation, gateway tracking. |
| `opnsense_acl_test_config.xml` | 239 | 1 | 2 | 0 | 1 | 5 | ACL model test — 5 users + 4 groups with distinct priv sets.  Richest local_users surface in the corpus. |
| `user_contrib_supergate_opn25.xml` | 2,302 | 1 | 8 | 5 | per-zone | 2 | **Real deployed OPNsense instance** (user-contributed, sanitised).  8 interfaces across wan/lan/opt1-5/loopback, 5 VLANs with `<tag>` + `<descr>`, extensive per-zone DHCP static MAC reservations (~20 per zone), Unbound DNS with local overrides, IPsec, WireGuard, SNMP, NTP, self-signed cert chain. |

### Findings

**Bug surfaced + fixed by the real fixture:** the render path
silently dropped every `CanonicalVlan` entry.  The parser read
`<vlans><vlan><tag/>` + `<descr/>` correctly (populating
`intent.vlans`) but `_render_canonical` had no inverse block, so a
`parse → render → parse` cycle on the supergate capture collapsed
5 VLANs down to 0.  The three upstream `opnsense/core` fixtures
didn't exercise the `<vlans>` block at all so this bug slept until
real-deployment contact.  Fix: added a `<vlans>` render block in
`_render_canonical` that emits `<tag>` + `<descr>` per VLAN.
Regression test in `TestRoundTrip::test_roundtrip_preserves_vlans`.

### Certification decision

**Promoted to `certified`.**  The corpus now spans 4 fixtures from
2 distinct sources — 3 from `opnsense/core` upstream (schema v9
test/default configs) + 1 real deployed user-contributed OPNsense
instance (2,302-line full `/conf/config.xml` with 5 VLANs, 8
interfaces, bcrypt-hashed local users, self-signed cert chain).
All four parse cleanly, produce populated canonical trees, and
round-trip stable after the VLAN-render fix.  Bar met decisively:
≥3 fixtures, ≥2 sources, round-trip stable after the fix, at least
one real-deployment capture (the highest-signal class of fixture).

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
**Certainty:** `certified` ✅

### Coverage matrix

| Fixture | Lines | hostname | dns | interfaces | vlans | routes | lags | dhcp | local_users | radius | Notes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `kevinguenay_fgt_70g_branch.conf` | 12,317 | 1 | 2 | 21 | 2 | 1 | 2 | 1 | 1 | 0 | Real FortiOS 7.6.6 branch config — `fortilink` + `LAG_INTERNAL` aggregates, VL_100/VL_101 VLAN subinterfaces on LAG_INTERNAL, LO_BGP loopback, SD-WAN, IPsec, firewall policies. |
| `kevinguenay_fgt_vm_hub.conf` | 13,827 | 1 | 2 | 19 | 0 | 1 | 1 | 1 | 1 | 0 | Real FortiOS 7.6.6 VM hub — the counterpart hub config for the branch above. |
| `user_contrib_fg100e_fos7213.conf` | ~35,000 | 1 | 2 | 34 | 5 | 0 | 2 | 6 | 3 | 1 | **Real physical FG100E on FortiOS 7.2.13** (user-contributed, sanitised).  34 interfaces, 5 VLANs, 2 LAGs, 6 DHCP servers, 3 admins, 1 RADIUS server, 1 SNMP community, full firewall policy table + VIPs + SDWAN + SSL-VPN. |

### Findings

**Bug surfaced + fixed (KevinGuenay):** Our parser required `set type
vlan` explicitly on a VLAN subinterface edit.  Real FortiOS configs
often omit it — a VLAN is unambiguously implied by the pair
`set vlanid <N>` + `set interface "<parent>"`.  VL_100 and VL_101 in
the branch config had that shape and were previously mis-typed as
`ethernetCsmacd` (via the name-pattern fallback) and dropped from
`intent.vlans`.  Fix landed in `_apply_system_interface`; 3
regression tests in `TestRealConfigVlanInference`.

**Bug surfaced + fixed (FG100E):** `set radius-port 0` is FortiOS's
idiom for "use the default port 1812" — and real FortiOS config
exports (including the FG100E 7.2.13 capture) emit this literally.
Our parser stored the 0 faithfully in `CanonicalRADIUSServer.auth_port`,
but the renderer had an early-out that omitted `radius-port` when
auth_port == 1812 (mirroring FortiOS's own default-omission
pattern).  Round-trip drift: first parse gave auth_port=0, render
emitted nothing (because 0 != 1812 but also 0 is falsy — the
`if server.auth_port and ...` check short-circuited to False),
re-parse defaulted to 1812.  Fix canonicalises `radius-port 0` to
1812 at parse time in `_apply_user_radius` (`radius-port 0` means
"use default" — canonical should store the effective value).
Regression test:
`TestRoundTrip::test_radius_port_zero_canonicalised_to_default`.

**Scale note:** The FG100E fixture is ~35,000 lines — nearly 3× the
prior largest fixture in the corpus.  Parsed and round-tripped
cleanly after the radius-port fix.  Strong evidence that the
recursive block parser handles the full FortiOS `config / edit /
set / next / end` grammar at production scale with real appliance
policy tables.

### Certification decision

**Promoted to `certified`.**  Three real captures across 2 OS
versions (7.2.13 + 7.6.6) and 3 distinct device forms (physical
FG100E + physical FGT-70G branch + FGT-VM hub).  All three parse
cleanly and round-trip stable after the radius-port fix.  Bar met
decisively: ≥3 fixtures, ≥2 OS versions, round-trip stable, at
least one real-appliance capture (the highest-signal class of
fixture).

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
| `user_contrib_2930m_wc1611.cfg` | 56 | 1 | 0 | 0 | 3 | 0 | 0 | 1 | **Real 2930M stack on WC.16.11.0025** (user-contributed, sanitised).  First fixture covering the 16.11 LTS branch.  Stacked-switch family: `JL323A` member + `JL083A` flexible-module uplinks, stack-aware port syntax (`1/1-1/47,1/A1-1/A4`), `stacking` stanza with priority + flexible-module type, `oobm` per-member IP config, `include-credentials` with `password manager sha1`, SNMPv3 engineid.  Password hash sanitised to obviously-fake `deadbeef…dead`.  `interfaces` = 0 because the config has no per-port overrides (bare config — all port behaviour inherits from VLAN membership). |

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

### Bugs surfaced by the WC.16.11.0025 2930M fixture

Two latent codec bugs, both fixed in the same commit as the fixture
landed.  Round-trip-stable invariant had hidden them because the
damage was symmetric (broken parse + broken render cancelled out):

**Bug 1 — `_expand_port_range` dropped slot prefix on stacked-switch
ranges.**  Old regex `^([A-Za-z]*)(\d+)(?:/(\d+))?$` expanded only
the first numeric group, silently discarding the slot.  Symptoms:

* `1/1-1/24` → `["1"]` (instead of 24 member-1 ports)
* `1/A1-1/A4` → `["1/A1", "1/A4"]` (regex failed to match, only
  endpoints survived — `1/A2` and `1/A3` lost)

The effect on pre-existing fixtures was severe: on
`aruba_central_5memberstack_rendered.cfg`, VLAN 1's untagged ports
went from the correctly-expanded 12 ports down to a single-entry
`["1"]`.  All four existing Aruba fixtures parsed with materially
incorrect VLAN port membership — coverage numbers in the matrix
above had been under-reporting by 40-80% on stacked captures.
Fixed with a simpler greedy-trailing-digits regex that treats
everything up to the final `\d+` as a shared prefix — handles
`1-24` / `A1-A4` / `1/1-1/24` / `1/A1-1/A4` / `2/1-2/48`
uniformly.  Regression tests in
`tests/unit/migration/test_aruba_aoss.py::TestPortListParsing`
cover all five forms.

**Bug 2 — LAG-member linking order-sensitive on rendered output.**
The inline `_build_lag_from_trunk_line` path linked trunk-member
interfaces to their LAGs *at the time the trunk line was parsed*.
On AOS-S native captures this worked because real devices emit
`interface <name>` stanzas before the `trunk` line, so interface
lookups succeeded.  Our renderer emits trunks BEFORE interface
stanzas — so the second parse (on rendered output) saw zero
linking.  Bug 1's symmetric damage had been masking this:
pre-fix LAG members were `["1"]` which matched (or mis-matched)
an interface named `"1"`, producing equivalent-if-wrong output
on both sides.  After Bug 1 fix the real names flowed through
and the ordering issue surfaced.  Fixed with a parse-time
post-pass that re-links exhaustively after all stanzas are
parsed.

### Certification decision (updated)

**Remains `certified`**, now covering **4 OS versions**
(WC.16.07.0002 + WB.16.08.0001 + WC.16.10.0005 + WC.16.11.0025)
and **3 switch families** (2920 + 2930F + 2930M).  The 16.11
LTS branch was the most-current un-covered AOS-S maintenance
line; closing that gap means the codec's "works on modern
Aruba" claim is defensible.

Bugs surfaced by this fixture ARE counted against the codec —
0 → 2 in the summary table — because even though they were
pre-existing, they'd never shown up in CI before.  This is
exactly the regression class the real-capture harness is
designed to catch.

---

## Summary

| Codec | Fixtures | OS versions | Bugs surfaced | Certainty | Certified blocker |
|---|---:|---:|---:|---|---|
| **cisco_iosxe_cli** | **11** (6 grammar-test + 5 real) | **4 LTS** (16.9 + 17.3 + 17.9 + 17.12) | 1 (LAG member dedup) | **certified** ✅ | — |
| **opnsense** | **4** (3 upstream + 1 real user-deployed) | 2 sources | 1 (render dropped VLANs) | **certified** ✅ | — |
| **mikrotik_routeros** | **4** | **3** (6.48.1 + 6.48.6 + 7.18.2) | 6 | **certified** ✅ | — |
| **fortigate_cli** | **3** | **2** (7.2.13 + 7.6.6) | 2 (implicit VLAN typing; radius-port 0) | **certified** ✅ | — |
| **aruba_aoss** | **5** (4 real + 1 rendered) | **4** (WC.16.07 + WB.16.08 + WC.16.10 + WC.16.11) | 2 (port-range slot drop; LAG-member link ordering) | **certified** ✅ | — |
| **TOTAL** | **26** | — | **10** | — | — |

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

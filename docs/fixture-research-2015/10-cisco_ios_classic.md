# Cisco IOS classic (pre-IOS-XE) — fixture catalogue (2015+)

> **Tier**: Tier-D (no codec yet — design implied by [`WANTED.md`](../../tests/fixtures/real/WANTED.md) §
> Tier-D table; SMB platforms still in production)
> **Existing corpus**: 0 dedicated; **2 IOS-classic captures filed under `cisco_iosxe/`**
> because our IOS-XE codec shares parse paths (~90 % grammar overlap):
>
> | File | Version | Platform | Why it's under cisco_iosxe |
> |---|---|---|---|
> | [`cml_basic_forwarding_iosv_r1_ospf.txt`](../../tests/fixtures/real/cisco_iosxe/cml_basic_forwarding_iosv_r1_ospf.txt) | IOSv 15.x | virtual IOSv | Shared `cisco_iosxe_cli` parse path |
> | [`batfish_iosxe_basic_vrrp.txt`](../../tests/fixtures/real/cisco_iosxe/batfish_iosxe_basic_vrrp.txt) | **15.7** (true classic) | IOSv/CSR-like lab | Codec doesn't distinguish; `version 15.7` line is the IOS-classic tell |
>
> The codec gap a Tier-D IOS-classic codec would close: the ~10 % delta
> where IOS classic and IOS-XE diverge (older command shapes, older
> `spanning-tree mode pvst` default, older `ip routing` semantics, older
> `crypto isakmp` IKEv1 grammar, line-card `module N type ...` declarations
> on Cat 6500 SUP-2T / Cat 4500 SUP7-E hardware). The corpus inventory
> below explicitly tags **IOSv-virtual** vs **hardware-platform** lineage
> per entry because the codec design choice (one codec for both vs split)
> hinges on which lineage operators actually run.

This catalogue references the source-class taxonomy in
[`00-source-analysis.md`](00-source-analysis.md) — see that file for
license-confidence + sanitisation expectations per source class
(GitHub repo / vendor doc / forum / pastebin / etc.).

---

## Version timeline

The "IOS 15.x" umbrella covers **ten release trains** (15.0 through 15.9)
spanning a 9-year period from 2010 to 2019, plus the late-12.4(15)T
sub-train that overlapped with early 15.x and is still seen on legacy
ISR-G1 hardware. Modern Cisco-IOS-classic deployments are concentrated
on **15.5 - 15.9** on ISR G2 (1900/2900/3900 series) and Cat 6500
SUP-2T cards. Pre-15.x trains exist in the SMB long-tail and on
end-of-life test gear.

| Train | First release | Last GA / EoS | Notable platforms | Grammar quirks vs IOS-XE | Priority |
|---|---|---|---|---|---|
| 12.4(15)T | 2007 | EoS 2016 (still deployed at SMB) | ISR-G1 (1841 / 2811 / 2851), some Cat 3550 | Older `crypto isakmp policy`; `ip http server` on by default; no `service compress-config` | Low-medium (long-tail SMB) |
| 15.0 | 2010 | EoS 2016 | Cat 6500 SUP-720, Cat 3750-X, Cat 2960 LANBASEK9 (15.0(2)SE4) | First train with `ip routing` independent of `ip cef`; older `vlan database` config-mode still works | Low |
| 15.1 | 2010 | EoS 2017 | ISR-G2 1921/2901, Cat 4500 SUP6-E | Some `ip route` syntax tweaks; PVST+ remained default | Low |
| 15.2 | 2011 | EoS 2019 | Cat 6500 SUP-2T (15.2(1)SY+), Cat 4500-X, Cat 3850 (early universal-k9) | First `spanning-tree mode rapid-pvst` as configurable default in some images; `class-map type qos` extensions | **Medium** (still common at SMB + utility verticals) |
| 15.3 | 2013 | EoS 2020 | ISR-G2 (2911/2951), some Cat 3650, Cat 6500 SUP-2T (15.3(1)S) | `mpls ldp` syntax tweaks; SSH-server algorithm-list config; first reliable `dot1Q vlan native` semantics | **Medium-high** (transition period to modern IOS) |
| 15.4 | 2014 | EoS 2020 | ISR-G2 (most popular train), Cat 6500 SUP-2T (15.4(1)SY) | Last train where `crypto pki trustpoint` had distinct defaults from IOS-XE | **High** (best 2015-2017 default-train representative) |
| 15.5 | 2015 | EoS 2021 | ISR-G2, Cat 6500 SUP-2T (15.5(1)SY) | First train with `ip access-list standard` enforcing `permit/deny` ordering normalisation on render; `ip ssh version 2` increasingly default | **High** (matches the 2015-2017 user-base) |
| 15.6 | 2016 | EoS 2022 | ISR-G2 (final-supported main train), some Cat 6500 SUP-2T(SY) | `cts (Cisco TrustSec)` keywords expanded; `service-policy type queueing` grammar tweaks | **High** |
| 15.7 | 2017 | EoS 2023 | ISR-G2 (final-supported `15.7(3)M` LTS), Cat 6500 SUP-2T | `vrf definition X` continues alongside legacy `ip vrf X` — both shipped; **batfish lab-validation uses 15.7 heavily** | **Highest** (most-captured modern IOS train) |
| 15.8 | 2018 | EoS 2024 | ISR-G2 (final 15.8(3)M LTS), IOSv 15.8(3)M2 | Last train where `radius-server host` non-`aaa group` form was first-class; some `ntp server` keyword tweaks | **Highest** (penultimate modern IOS classic) |
| 15.9 | 2019 | EoS 2024-25 | ISR-G2 (final-final 15.9(3)M LTS), IOSv 15.9(3)M (CML default) | The **terminal IOS-classic train** — Cisco's "no more IOS classic after this" position. CML IOSv ships 15.9 as the modern default. | **Highest** (current-LTS modern IOS classic) |

Cisco's GA position is that **no IOS classic version after 15.9 will be
released for ISR-G2 / Cat 6500**; the successor platforms run IOS-XE.
Real-world: SMBs run 15.5 / 15.6 / 15.7 / 15.8 on ISR-G2 because the
hardware lives forever and IOS classic was conservatively-licensed.

---

## Pull-target inventory

### 15.9 (most recent IOS classic — current LTS)

Two **realistic** sources for 15.9 captures:

#### GitHub repositories

| Source | Path | License | Lines (est.) | OS | Platform | Grammar surface | Sanitisation |
|---|---|---|---|---|---|---|---|
| [CiscoDevNet/cml-community](https://github.com/CiscoDevNet/cml-community) | `lab-topologies/ccna/Domain_1/1.6-configure_ipv4_addressing/1.6_IPv4_Router_Config_Solution.yaml` | BSD-3-Clause | ~30 per node (embedded `configuration: ` block ; multiple nodes per YAML) | **IOSv 15.9** | virtual (IOSv) | hostname + interface IPv4 routed-mode + minimal | None (already lab) |
| CiscoDevNet/cml-community | `lab-topologies/ccna/Domain_3/3.3-configure_static_routing/*Solution.yaml` | BSD-3-Clause | ~40-60 per node | IOSv 15.9 | virtual | `ip route` static-route grammar + multi-router IPv4 routing | None |
| CiscoDevNet/cml-community | `lab-topologies/ccna/Domain_3/3.4-configure_ospfv2_1/*Solution.yaml`, `3.4-configure_ospfv2_2/*Solution.yaml` | BSD-3-Clause | ~50-100 per node | IOSv 15.9 | virtual | `router ospf N` + `network ... area N` — multi-area OSPF | None |
| CiscoDevNet/cml-community | `lab-topologies/ccna/Domain_4/4.6-configure_dhcp_client/*Solution.yaml` | BSD-3-Clause | ~30-50 per node | IOSv 15.9 | virtual | `ip dhcp pool` + `ip address dhcp` client side | None |
| CiscoDevNet/cml-community | `lab-topologies/ccna/Domain_4/4.8-configure_remote_access_1/*Solution.yaml`, `4.8-configure_remote_access_2/*Solution.yaml` | BSD-3-Clause | ~50-80 per node | IOSv 15.9 | virtual | `crypto key generate rsa` + `ip ssh version 2` + `username X privilege 15 secret` + `line vty / transport input ssh` | None |

**Provenance class**: same as the existing `cml_basic_forwarding_iosv_r1_ospf.txt` and
`cml_saumur_iosxe1712_pvrstp.txt` (Tier-1.3 permissively-licensed lab platform).
**IOSv lineage** — these expand the IOSv 15.x coverage rather than hardware platform.

#### Caveats — 15.9

There is no public GitHub repo containing a **hardware-platform** 15.9
capture (real ISR 2921 / 3925, real Cat 6500 SUP-2T running 15.9). Such
captures would need operator contribution per
[`BUG_REPORTING.md`](../../BUG_REPORTING.md) sanitisation flow. The CML
captures above are all virtual IOSv.

---

### 15.6 - 15.8 (modern train, ISR-G2 final support)

#### GitHub repositories (highest leverage)

| Source | Path | License | Lines | OS | Platform lineage | Grammar surface | Sanitisation |
|---|---|---|---|---|---|---|---|
| [batfish/lab-validation](https://github.com/batfish/lab-validation) | `snapshots/ios_basic_vrrp/configs/BR1/show_running-config.txt` | Apache-2.0 | 154 | **15.7** | virtual lab | VRRP groups, multi-router 4-node lab (BR1/BR2/LAN-RTR/WAN-RTR siblings) | None (already lab) — **already in corpus as `batfish_iosxe_basic_vrrp.txt`** |
| batfish/lab-validation | `snapshots/ios_basic_vrrp/configs/BR2/show_running-config.txt` | Apache-2.0 | 152 | 15.7 | virtual lab | VRRP sibling | None |
| batfish/lab-validation | `snapshots/ios_basic_vrrp/configs/LAN-RTR/show_running-config.txt` | Apache-2.0 | 154 | 15.7 | virtual lab | LAN-router role of the 4-node VRRP lab | None |
| batfish/lab-validation | `snapshots/ios_basic_vrrp/configs/WAN-RTR/show_running-config.txt` | Apache-2.0 | ~150 | 15.7 | virtual lab | WAN-router role of the 4-node VRRP lab | None |
| batfish/lab-validation | `snapshots/ios_add_path/configs/{as1r1,as1r2,as2border,as2leaf,as2rr}/show_running-config.txt` | Apache-2.0 | 160 (as1r1); 5 sibling nodes | 15.7 | virtual lab | BGP `additional-paths` grammar + 5-node BGP fabric | None |
| batfish/lab-validation | `snapshots/ios_ibgp_split_horizon/configs/D1/show_running-config.txt` | Apache-2.0 | 178 | 15.7 | virtual lab | iBGP split-horizon scenario, 3-node fabric (D1/D2/D3) | None |
| batfish/lab-validation | `snapshots/ios_ibgp_split_horizon/configs/{D2,D3}/show_running-config.txt` | Apache-2.0 | ~178 each | 15.7 | virtual lab | Sibling pair configs | None |
| batfish/lab-validation | `snapshots/ios_nxos_bgp_local_as/configs/ios1/show_running-config.txt` | Apache-2.0 | ~150 | 15.7 | virtual lab | **Cross-vendor IOS-classic + NX-OS** BGP `local-as`; pairs with the NX-OS counterpart already in the [`docs/v0.2.0-planning/03-nxos-codec/05-fixture-targets.md`](../v0.2.0-planning/03-nxos-codec/05-fixture-targets.md) pull list | None |
| batfish/lab-validation | `snapshots/cisco_xr_ios_vpnv4/configs/{CE1,CE2,CE3,CE4}/show_running-config.txt` | Apache-2.0 | ~150 each | **15.7** | virtual lab (IOS classic CE alongside IOS-XR PE) | CE-side of a XR-IOS interop scenario; per [`docs/v0.2.0-planning/04-iosxr-codec/05-fixture-targets.md`](../v0.2.0-planning/04-iosxr-codec/05-fixture-targets.md): "CE1-CE4 in this snapshot are **IOS classic** (15.7) — not XR. They go into `tests/fixtures/real/cisco_iosxe/` instead" (or `cisco_ios_classic/` when codec ships) | None |
| [networktocode/ntc-templates](https://github.com/networktocode/ntc-templates) | `tests/cisco_ios/show_version/cisco_ios_show_version3.raw` | Apache-2.0 | (banner only, ~20 lines — `show version` not full running-config) | **15.8(3)M2** | **IOSv** (`VIOS-ADVENTERPRISEK9-M`) | Version-banner format reference only (no config body) | None |
| networktocode/ntc-templates | `tests/cisco_ios/show_version/cisco_ios_show_version6.raw` | Apache-2.0 | (banner only) | **15.2(4.0.55)E** test-engineering build | **vios_l2** (`vios_l2-ADVENTERPRISEK9-M`) | L2-IOSv banner format | None |
| networktocode/ntc-templates | `tests/cisco_ios/show_running-config_interface/cisco_ios_show_running-config_interface.raw` | Apache-2.0 | ~50 | IOS classic (version not banner-stamped) | (interface-only snippet, no version banner) | Carrier-grade interface block — VRFs, dot1Q sub-interfaces, QoS, ACL groups — **already in corpus as `ntc_carrier_interfaces.txt`** | None |

#### Forum / community posts (operator-share precedent)

| Source | Provenance | License posture | Likely OS surface |
|---|---|---|---|
| [Cisco Community](https://community.cisco.com/) — "Switching / Routing" forums | Per source-class taxonomy Tier 2.1 (operator-paste-for-troubleshooting precedent — matches our AOS-S `hpe_community_*` pattern) | Forum-share (heavy sanitisation needed on hostnames / IPs / passwords) | ISR-G2 15.x troubleshooting threads. Search: `"show running-config" "version 15.7" site:community.cisco.com` |
| [Network Engineering Stack Exchange](https://networkengineering.stackexchange.com) | Tier 2.3 CC-BY-SA (attribution required) | CC-BY-SA (compatible with our pool but needs attribution work) | Q&A snippets — partial running-configs in answers. Search: `"interface GigabitEthernet" "version 15" site:networkengineering.stackexchange.com` |
| [Reddit `r/cisco` / `r/networking`](https://reddit.com/r/cisco) | Tier 2.2 (implicit operator-share license; sanitisation usually pre-done) | Heavy sanitisation expected | 15.6-15.8 troubleshooting captures from ISR-G2 SMB ops |

#### Vendor docs / lab guides

* Cisco's "[3900 / 2900 / 1900 Series Software Configuration Guide](https://www.cisco.com/c/en/us/td/docs/routers/access/1900/software/configuration/guide/Software_Configuration/routconf.html)" embeds full `show running-config` examples in the appendix — Tier 1.2, CC-BY-permissive for example use. ISR-G2 15.4-15.7 grammar.
* "[Cisco IOS Release 15.7(3)M cross-platform release notes](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/15-7m/release/notes/15-7-3-m-rel-notes.html)" reference + "15.8(3)M release notes" — list known caveats around config grammar shifts.
* **Cisco DevNet Always-On sandbox** — IOSv 15.9(3)M sandbox accessible by API/SSH for live-capture (operator-shareable per Cisco's "example use" terms; equivalent to the CML lab platform precedent). Login-gated but configurations exportable.

#### Other (Internet Archive / blogs)

* [packetlife.net](https://packetlife.net/) (Jeremy Stretch) — many ISR / Cat 6500 / Cat 3550 config samples from 2010-2018 era. License: CC-BY operator-blog; **inspiration only** per source-class taxonomy (Tier 2.4), not direct import.
* [Internet Archive Wayback Machine](https://web.archive.org) — preserves 2015-era ISR / Cat 6500 blog posts that have since expired (e.g. `web.archive.org/web/2015*/inurl:lab "interface FastEthernet"`).

---

### 15.0 - 15.5 (mid retrospective)

The mid-15.x trains are useful for grammar-quirk coverage (older
`spanning-tree mode pvst` default, older `ip dhcp pool` syntax, older
`crypto isakmp` IKEv1-only grammar) but NOT for current-deployment
validation.

#### GitHub repositories

| Source | Path | License | OS | Platform lineage | Notes |
|---|---|---|---|---|---|
| [batfish/lab-validation](https://github.com/batfish/lab-validation) | `snapshots/ios_example_network/configs/{as1border1,as1border2,as1core1,as2border1,as2border2,as2core1,as2core2,as2dept1,as2dist1,as2dist2,as3border1,as3border2,as3core1}/show_running-config.txt` | Apache-2.0 | **15.2** | virtual lab | **13-node BGP example-network reference fabric** (≈ 4.2 KB per node) — borders / cores / distribution. The largest single-snapshot IOS-classic corpus in batfish/lab-validation. Exercises: `router bgp` confederation, OSPF underlay, multi-AS topology, per-node distinct grammar |
| batfish/lab-validation | `snapshots/ios_bgp_path_select_8/configs/leaf1/show_running-config.txt` | Apache-2.0 | **16.4** (note: 16.4 = IOS-XE territory, not IOS classic) | virtual lab | DROP — not IOS classic |
| [napalm-automation/napalm](https://github.com/napalm-automation/napalm) | `test/ios/mocked_data/test_get_config/normal/show_running_config.txt` (embedded in `expected_result.json`) | Apache-2.0 | **15.5** | **CSR1000V virtual** (`license udi pid CSR1000V`) | 84 lines — CSR1000V minimal OSPF config with `ip vrf MGMT`, `username cisco privilege 15 password 0`, OSPF area 0 with `redistribute connected subnets`. Note: CSR1000V on 15.x = IOS-XE pre-Denali rebrand; arguably still IOS classic grammar at 15.5 |
| napalm-automation/napalm | `test/ios/mocked_data/test_get_config/old-2950/show_running_config.txt` | Apache-2.0 | **12.1(22)EA13** | **Cat 2950 hardware** — `C2950-I6K2L2Q4-M` (legacy SMB switch from ~2001-2009) | Pre-2015, but represents the long-tail 12.x trains still seen at SMBs. Useful as a "lower bound" of grammar coverage |
| napalm-automation/napalm | `test/ios/mocked_data/test_get_facts/normal/show_version.txt` (banner only) | Apache-2.0 | **15.0(2)SE4** | **Cat 2960** hardware (`C2960-LANBASEK9-M`) | Pure IOS classic switch banner reference |

#### Vendor docs

* "Catalyst 3560 Switch Software Configuration Guide" (15.0(2)SE) — has full appendix configs.
* "Cisco IOS Release 15.2SY Configuration Guide for the Cat 6500 SUP-2T" — example configs throughout.

---

### 12.4(15)T retrospective (where realistic)

12.4(15)T is from 2007 but **still in production** at SMB on 1841 /
2811 / 2851 hardware. Modern captures of 12.4 hardware are rare on
GitHub — most public 12.4 configs live in defunct blogs accessible
only via the Internet Archive.

| Source | Provenance | OS / Platform | Notes |
|---|---|---|---|
| [networktocode/ntc-templates](https://github.com/networktocode/ntc-templates) | `tests/cisco_ios/show_version/cisco_ios_show_version_01.raw` | **12.4(6)T2** on **C180X-ADVIPSERVICESK9-M** (Cisco 1801 ISR-G1) | Apache-2.0 — banner reference for the 12.4 LTS train |
| [Internet Archive Wayback Machine](https://web.archive.org) | Tier 3.4 archived defunct blogs | 12.4(15)T from defunct CCIE-lab blogs (e.g. `web.archive.org/web/2014*/packetlife.net`) | Discovery-only — use as inspiration, not import (per source-class taxonomy Tier 3.4) |
| [Cisco IOS Release 12.4 Configuration Fundamentals Guide](https://www.cisco.com/c/en/us/td/docs/ios/fundamentals/command/reference/cf_book/cf_s4.html) | Cisco vendor docs (Tier 1.2) | 12.4 train | Embedded config samples; CC-BY example-use |

**Realistic 12.4 capture path**: re-synthesise from vendor doc examples
+ ntc-templates banner reference, NOT pull a real defunct-blog capture.

---

### Cross-vendor and "shared lineage" notes

* [`docs/v0.2.0-planning/03-nxos-codec/05-fixture-targets.md`](../v0.2.0-planning/03-nxos-codec/05-fixture-targets.md) §1.2 lists `snapshots/ios_nxos_bgp_local_as` as a multi-vendor pull. The `ios1/show_running-config.txt` from that snapshot belongs in **this** catalogue (IOS classic 15.7); the `nxos1` belongs in NX-OS.
* [`docs/v0.2.0-planning/04-iosxr-codec/05-fixture-targets.md`](../v0.2.0-planning/04-iosxr-codec/05-fixture-targets.md) — the `cisco_xr_ios_vpnv4/configs/CE1..CE4/` are IOS classic 15.7 (per the file's explicit note). If/when IOS classic codec ships, those four CE configs are immediate pull-candidates.
* The existing [`batfish_iosxe_basic_vrrp.txt`](../../tests/fixtures/real/cisco_iosxe/batfish_iosxe_basic_vrrp.txt) (corpus member, `version 15.7`) was sourced from `snapshots/ios_basic_vrrp/configs/BR1/` — when the IOS-classic codec ships, the file moves from `cisco_iosxe/` to `cisco_ios_classic/` and its 3 sibling configs (BR2 / LAN-RTR / WAN-RTR) become bonus pulls.

---

### Sources catalogued but UNUSABLE

| Source | Why excluded |
|---|---|
| [mpenning/ciscoconfparse](https://github.com/mpenning/ciscoconfparse) — `tests/fixtures/configs/sample_01.ios` through `sample_09.ios` | **GPL-3.0** — incompatible with our permissive (Apache/MIT/BSD/CC0) fixture pool. Use as inspiration only |
| [batfish/batfish](https://github.com/batfish/batfish) — `projects/batfish/src/test/resources/org/batfish/grammar/cisco/testconfigs/ios-*` (166 mini-grammar files) | Apache-2.0 license is fine, but these are tiny grammar-slice configs (1-10 lines each, no version banner, no end-to-end runtime config) — useful for parser-stress reference but NOT fixtures the codec is meant to ingest. Do not pull |
| [a-rey/CISCO_configs](https://github.com/a-rey/CISCO_configs) | Search engine cache claimed `c2811-CUCME.conf` etc., but the actual repo only contains LICENSE + README. Dead end |
| INE / IPexpert CCIE workbook samples | Paywalled — per source-class taxonomy Tier 3.2, do not import |
| GNS3 marketplace lab files (`gns3.com/marketplace`) | Mixed-licenses per lab; no permissive license tag — discovery-only |
| Cisco DevNet Always-On IOSv sandbox | Login-gated; Cisco "example use" terms vs explicit permissive license — open question per source-class taxonomy Tier 4. Best-effort: treat captures as personal-use, do not commit unless operator confirms |

---

## Recommended pull priority order

For a Phase 1 IOS-classic codec ship, recommend the following pull
order (mirrors the NX-OS / IOS-XR codec pull-target methodology in
`docs/v0.2.0-planning/03-nxos-codec/05-fixture-targets.md` §1):

### Phase 1 — IOS-classic baseline (hardware platforms not required)

1. **batfish `ios_basic_vrrp`** — promote the 3 sibling captures
   (`BR2`, `LAN-RTR`, `WAN-RTR`) alongside the existing `batfish_iosxe_basic_vrrp.txt`
   (rename + relocate to `cisco_ios_classic/`). Apache-2.0, 4 configs × ~150 lines, IOS 15.7.
2. **batfish `ios_example_network`** — pull 3-5 nodes from the 13-node
   BGP example-network reference fabric (suggest `as1border1` + `as2border1` + `as2core1`
   for grammar diversity). Apache-2.0, 15.2, mid-15.x grammar coverage.
3. **batfish `ios_add_path`** — 2 nodes (`as1r1` + `as2rr`). Apache-2.0, 15.7, BGP additional-paths surface.

After Phase 1 the corpus has **9 IOS-classic captures across 2 OS
versions** (15.2 + 15.7), clearing the certified-tier bar (≥3 captures
across ≥2 versions per the convention in `tests/fixtures/real/RESULTS.md`).

### Phase 2 — IOSv 15.9 modernity

4. **CML-community CCNA Domain 1/3/4 IOSv 15.9 lab YAML files** — extract
   embedded `configuration:` blocks from `lab-topologies/ccna/Domain_*/
   *Solution.yaml`. BSD-3-Clause, IOSv 15.9, mirrors the existing
   `cml_basic_forwarding_iosv_r1_ospf.txt` pull pattern.

### Phase 3 — hardware platform coverage (operator contribution)

5. **Operator-contributed real ISR 2911 / 3925 running-config** on 15.5-15.8 —
   sanitisation per [`BUG_REPORTING.md`](../../BUG_REPORTING.md). CC0
   under user-contribution precedent (matches the existing
   `user_contrib_cat9300_iosxe1712.txt` / `user_contrib_supergate_opn25.xml`).
6. **Operator-contributed Cat 6500 SUP-2T running-config** on 15.2(1)SY or 15.5(1)SY —
   gives the line-card `module N type ...` and SVI grammar surface that
   the IOSv virtual captures don't exercise.

### Phase 4 — 12.4 retrospective (low priority)

7. Synthesise a 12.4(15)T fixture from
   [Cisco IOS 12.4 Configuration Fundamentals Guide](https://www.cisco.com/c/en/us/td/docs/ios/fundamentals/command/reference/cf_book/cf_s4.html)
   examples + ntc-templates banner reference. Mark as
   **synthetic-from-vendor-docs** in NOTICE.md (CC-BY-vendor-example).

---

## Per-fixture grammar contribution forecast

If the Phase 1+2 pulls land, the IOS-classic corpus would exercise:

| Surface | Fixture(s) exercising it |
|---|---|
| `version 15.x` banner | every fixture |
| hostname + service-timestamps + boot-start-marker | every |
| `aaa new-model` + `aaa authentication login default local` | `ios_example_network/*` (15.2) |
| `interface FastEthernet0/N` (legacy 100-Mbit ports) | `ios_example_network` candidates |
| `interface GigabitEthernet0/N` | `ios_basic_vrrp/*`, IOSv CCNA labs |
| `interface GigabitEthernet0/N.<vlan>` (dot1Q sub-iface) | (gap — need ISR-G2 hardware capture) |
| `ip vrf <name>` (legacy VRF syntax, pre-`vrf definition`) | (potential gap; ntc-templates carrier-interface has it) |
| `vrf definition <name>` (modern VRF) | `ios_example_network/*` |
| `ip route <net> <mask> <next-hop>` | every fixture |
| `router ospf N` + `network ... area N` | CCNA Domain 3 IOSv labs |
| `router bgp <as>` + neighbor remote-as | `ios_example_network/*`, `ios_add_path/*`, `ios_ibgp_split_horizon/*` |
| `vrrp <gid> ip <vip>` | `ios_basic_vrrp/*` (4 nodes) |
| `spanning-tree mode pvst` (default) | (gap — need switch capture; IOSv router captures don't exercise STP) |
| `spanning-tree mode rapid-pvst` | (gap — Cat 6500 SUP-2T or Cat 4500-X capture needed) |
| `crypto isakmp policy N` (IKEv1) | (gap — need ISR-G2 VPN capture) |
| `crypto pki trustpoint <name>` | (gap — need real ISR-G2 capture with self-signed cert) |
| `line con 0` + `line vty 0 4` + `transport input ssh` | every fixture |
| `ip ssh version 2` + `crypto key generate rsa` | CCNA Domain 4 IOSv labs |
| `ip dhcp pool <name>` | CCNA Domain 4 IOSv labs |
| Cat 6500 `module N type ...` line-card declarations | (gap — operator contribution only) |
| `redundancy / mode sso` (SUP-redundant chassis) | (gap — operator contribution only) |

The Phase-1+2 corpus is **strong on routing + BGP + VRRP**, **weak on
spanning-tree / IKEv1 VPN / Cat-6500-hardware** grammar. The Phase 3
operator contributions close those gaps.

---

## Out-of-scope (deliberately excluded)

* **IOS-XE captures** (15.1S / 15.2S / 15.3S / etc. running on ISR 4000 / CSR 1000V) — these are NOT IOS classic; they belong in [`01-cisco_iosxe.md`](01-cisco_iosxe.md). The `version 15.x` line is shared but the platform is IOS-XE infrastructure. Tell from the `! Last configuration change at ...` header convention + `platform punt-keepalive disable-kernel-core` line that IOS-XE injects.
* **IOS-XR** — service-provider routers (CRS / ASR 9000 / NCS 540 / 5500) run IOS-XR with completely distinct grammar; see [`09-cisco_iosxr.md`](09-cisco_iosxr.md).
* **NX-OS** — DC switches (Nexus 5000 / 7000 / 9000) have completely distinct grammar; see [`08-cisco_nxos.md`](08-cisco_nxos.md).
* **Closed-source vendor-published configs from training material (CBT Nuggets, INE, IPexpert)** — paywalled; copyright is real per source-class taxonomy Tier 3.2.
* **Real production captures from operators without explicit consent** — per source-class taxonomy Tier 4 + [`BUG_REPORTING.md`](../../BUG_REPORTING.md) sanitisation flow.
* **Cisco Modeling Labs (CML) IOSv-L2 captures on 15.x** — `ioll2-xe` nodes (e.g. the existing `cml_saumur_iosxe1712_pvrstp.txt`) report `Cisco IOS Software, vios_l2 Software` but the grammar is IOS-XE-flavored per Cisco's labelling. Treat as IOS-XE not IOS classic.
* **Packet Tracer config exports** (`.pkt` files) — proprietary binary format; cannot ingest without Packet Tracer to export.

---

## Codec design implication (one-codec vs split)

A real **IOS-classic codec** would handle the ~10 % grammar delta from
IOS-XE. The biggest divergences observed across the pull-candidates:

1. **Header convention** — IOS classic has `Building configuration... / Current configuration : N bytes` preamble; IOS-XE adds `! Last configuration change at ...` + `platform punt-keepalive disable-kernel-core` + `platform console auto`.
2. **VRF syntax** — IOS classic supports BOTH `ip vrf NAME` (legacy) and `vrf definition NAME` (modern); IOS-XE only `vrf definition`.
3. **AAA defaults** — IOS classic ships `no aaa new-model` default on ISR-G2; IOS-XE ships `aaa new-model` default.
4. **Spanning-tree mode default** — IOS classic 15.0-15.4 default to `spanning-tree mode pvst`; IOS-XE 16+ default to `spanning-tree mode rapid-pvst`.
5. **Line-card declarations** — Cat 6500 SUP-2T has `module N type <PID>` blocks that IOS-XE chassis don't.
6. **Crypto** — IOS classic supports IKEv1 (`crypto isakmp policy`) as first-class; IOS-XE prefers IKEv2 (`crypto ikev2 proposal`).

The 90 % overlap means **a single codec with version-detection + flag-routing**
is realistic (cf. how the `cisco_iosxe_cli` codec currently parses 15.7
IOSv configs via shared paths). A split codec would only be justified
if Cat 6500 SUP-2T + ISR-G2 hardware-specific grammar volume exceeds
canonical-model effort budget.

**Recommendation per [WANTED.md](../../tests/fixtures/real/WANTED.md)**
Tier-D table: treat as a **flavor of `cisco_iosxe_cli`** with a
`syntax_flavor: ios_classic` discriminator on detection, rather than a
parallel codec. Reduces maintenance surface; matches the existing pull
pattern.

---

## See also

* [`00-source-analysis.md`](00-source-analysis.md) — source-class taxonomy referenced throughout this catalogue
* [`01-cisco_iosxe.md`](01-cisco_iosxe.md) — IOS-XE catalogue (shared codec, distinct platform tier)
* [`08-cisco_nxos.md`](08-cisco_nxos.md) — NX-OS catalogue (cross-references `snapshots/ios_nxos_bgp_local_as`)
* [`09-cisco_iosxr.md`](09-cisco_iosxr.md) — IOS-XR catalogue (cross-references `snapshots/cisco_xr_ios_vpnv4` whose CE nodes are IOS classic)
* [`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md) — existing fixture provenance (2 IOS-classic captures filed under `cisco_iosxe/`)
* [`../../tests/fixtures/real/WANTED.md`](../../tests/fixtures/real/WANTED.md) — Tier-D fixture-gap list (where IOS classic appears)
* [`../v0.2.0-planning/03-nxos-codec/05-fixture-targets.md`](../v0.2.0-planning/03-nxos-codec/05-fixture-targets.md) — NX-OS pull-target methodology (mirrored here)
* [`../v0.2.0-planning/04-iosxr-codec/05-fixture-targets.md`](../v0.2.0-planning/04-iosxr-codec/05-fixture-targets.md) — IOS-XR pull-target methodology + cross-reference for the CE1-CE4 IOS-classic siblings in the XR-IOS VPNv4 snapshot
* [`../../BUG_REPORTING.md`](../../BUG_REPORTING.md) — sanitisation + fixture-submission workflow for operator-contributed real captures

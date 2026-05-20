# Cisco IOS-XE — fixture catalogue (2015+)

> **Tier**: Shipped
> **Codec**: `cisco_iosxe_cli` (CLI text) + `cisco_iosxe` (NETCONF Phase-0.5 stub)
> **Existing corpus**: 12 fixtures (see `tests/fixtures/real/NOTICE.md` cisco_iosxe/ section)
> **Methodology**: see [`00-source-analysis.md`](00-source-analysis.md) for the 15 source-class taxonomy and licence-confidence guidance this catalogue uses.

IOS-XE is Cisco's flagship Linux-hosted IOS successor.  It runs across an
unusually broad device fleet: ISR 4400/4300, ASR 1000, CSR 1000v, Cat 8000V,
Cat 8200/8300/8500, the Catalyst 9000 LAN-switch family (9200/9300/9400/9500),
the C9800 Wireless LAN Controller (CL/40/80), and the IOL/IOLL2-XE virtual
chassis Cisco ships with CML.  This catalogue enumerates real-world pull
targets across every version family from 2015's IOS-XE Denali 16.1 through
the August 2025 LTS 17.18, including the WANTED.md-flagged **17.13+ gap**.

---

## Version timeline

Cisco ships IOS-XE on a time-based 4-month cadence with every third release
designated Extended-Maintenance LTS (30 months of bug fixes + 18 months
security-only).  All public dates below come from cisco.com release-notes
pages cross-referenced against `endoflife.date/cisco-ios-xe` and Cisco
EoS/EoL bulletins.

| Version | Train codename | Release date | EM-LTS | Maintenance end | Security end | Notable platforms first supported | In corpus? | Priority |
|---|---|---|---|---|---|---|---|---|
| 16.1.x | Denali | 2016-05-27 | No | 2017-05-27 | 2018-05-27 | ASR1k, CSR1000v, Cat3850 | No | Low (legacy) |
| 16.2.x | Denali | 2016-07-06 | No | 2017-07-06 | 2018-07-06 | ASR1k, CSR1000v, Cat3850 | No | Low (legacy) |
| 16.3.x | Denali | 2016-08-04 | Yes (first 16.x EM) | 2018-08-04 | 2019-08-04 | ASR1k, ISR 4k | No | Low |
| 16.4.x | Everest | 2016-12-08 | No | 2017-12-08 | 2018-12-08 | ASR1k | No | Low |
| 16.5.x | Everest | 2017-04-04 | No | 2018-04-04 | 2019-04-04 | ASR1k, Cat3850, Cat9300/9500 (initial 9k support) | No | Low |
| 16.6.x | Everest | 2017-08-04 | Yes | 2019-08-04 | 2020-08-04 | ASR1k, ISR 4k, Cat 9k | No | Medium (Cat9k bootstrap) |
| 16.7.x | Fuji | 2017-11-30 | No | 2018-11-30 | 2019-11-30 | ASR1k, ISR4k | No | Low |
| 16.8.x | Fuji | 2018-04-06 | No | 2019-04-06 | 2020-04-06 | Cat9k | No | Low |
| 16.9.x | Fuji | 2018-07-18 | Yes | 2020-07-18 | 2021-07-18 | CSR1000v, Cat9k, ASR1k | Yes (`racc_csr1000v_iosxe169_bgp_ospf.txt`) | Covered |
| 16.10.x | Gibraltar | 2018-11-19 | No | 2019-11-19 | 2020-11-19 | ASR1k | No | Low |
| 16.11.x | Gibraltar | 2019-03-26 | No | 2020-03-26 | 2021-03-26 | Cat9k, ASR1k | No | Low |
| 16.12.x | Gibraltar | 2019-07-31 | Yes | 2022-01-31 | 2023-07-31 | Cat9k, ASR1k, ISR 4k | No | **High (last 16.x LTS, common in SMB)** |
| 17.1.x | Amsterdam | 2019-11-12 | No | 2020-11-12 | 2021-11-12 | Cat9k, ASR1k, ISR 4k, C9800 WLC | No | Low |
| 17.2.x | Amsterdam | 2020-03-30 | No | 2021-03-30 | 2022-03-30 | Cat 8k introduction, C8000V, SD-WAN converged image | No | Medium |
| 17.3.x | Amsterdam | 2020-07-31 | Yes (LTS) | 2023-01-31 | 2024-07-31 | Cat8000V, C9800, Cat9k | Yes (`racc_csr1_iosxe173_umbrella_sig.txt`) | Covered |
| 17.4.x | Bengaluru | 2020-11-24 | No | 2021-11-24 | 2022-11-24 | Cat9k, C8000V | No | Low |
| 17.5.x | Bengaluru | 2021-03-24 | No | 2022-03-24 | 2023-03-24 | Cat 8500-L, Cat9k | No | Low |
| 17.6.x | Bengaluru | 2021-07-30 | Yes (LTS) | 2023-01-30 | 2024-07-30 | Cat9k, C8200/8300, SD-WAN | No | **High (LTS, widely deployed)** |
| 17.7.x | Cupertino | 2021-12-07 | No | 2022-12-07 | 2023-12-07 | Cat9k | No | Low |
| 17.8.x | Cupertino | 2022-03-29 | No | 2023-03-29 | 2024-03-29 | Cat9k | No | Low |
| 17.9.x | Cupertino | 2022-07-29 | Yes (LTS) | 2025-01-29 | 2026-07-29 | Cat9k, Cat8000V | Yes (`racc_cat8000v_iosxe179_netconf.txt`) | Covered |
| 17.10.x | Dublin | 2022-11-30 | No | 2023-11-30 | 2024-11-30 | Cat9k, C9800 | No | Low |
| 17.11.x | Dublin | 2023-03-28 | No | 2024-03-28 | 2025-03-28 | Cat9k | No | Low |
| 17.12.x | Dublin | 2023-07-28 | Yes (LTS) | 2026-01-28 | 2027-07-28 | Cat9300 hardware, Cat 9k | Yes (`user_contrib_cat9300_iosxe1712.txt`, `cml_saumur_iosxe1712_pvrstp.txt`) | Covered |
| 17.13.x | (no codename, time-based) | 2023-11-30 | No | 2024-11-30 | 2024-11-30 | Cat9k, ASR1k | No | **High (the WANTED.md gap)** |
| 17.14.x | (time-based) | 2024-04-13 | No | 2025-04-13 | 2025-04-13 | Cat9k, C8000V | No | **High (current GA bridge)** |
| 17.15.x | (time-based) | 2024-08-09 | Yes (LTS) | 2027-02-09 | 2028-08-09 | Cat9k, C9800, Cat8k | No | **Highest (current LTS, no fixture)** |
| 17.16.x | (time-based) | 2024-12-11 | No | 2025-12-11 | 2025-12-11 | Cat9k, C9800 | No | Medium |
| 17.17.x | (time-based) | 2025-03-31 | No | 2026-03-31 | 2026-03-31 | Cat9k | No | Medium |
| 17.18.x | (time-based) | 2025-08-08 | Yes (LTS) | 2028-02-08 | 2029-08-08 | Cat9k, C9800 | No | **High (current LTS)** |

> **Pre-2015 caveat.**  The catalogue's 2015-onward window means IOS-XE 3.x
> (3.13S Polaris / 3.16S Edison / 3.17S Edison) is technically in-scope but
> deliberately low-priority — they predate the unified 16/17 train and were
> the ASR1k-only era.  Skipped except where a specific source explicitly
> tags one.

---

## Existing corpus coverage

The 12 fixtures in `tests/fixtures/real/cisco_iosxe/` cover the following
version-platform-grammar surface (mid-2026 state):

| Fixture | Version | Platform | Grammar surface |
|---|---|---|---|
| `racc_csr1000v_iosxe169_bgp_ospf.txt` | 16.9 | CSR1000v | BGP vpnv4 + rtfilter, OSPF, QoS class-map/policy-map, NETCONF-YANG + RESTCONF |
| `racc_csr1_iosxe173_umbrella_sig.txt` | 17.3 | CSR1000v | EIGRP, IKEv2/IPsec, SIG tunnel, SSH pubkey-chain, guestshell, PKI |
| `racc_cat8000v_iosxe179_netconf.txt` | 17.9 | Cat8000V | PAT, telemetry IETF subscription (gRPC), AAA local + SSH pubkey |
| `user_contrib_cat9300_iosxe1712.txt` | 17.12 | Cat9300-24UX | LACP, Cat9k CPP system-cpp-police, switch provision, multi-VLAN trunks |
| `cml_saumur_iosxe1712_pvrstp.txt` | 17.12 | CML ioll2-xe | PVRST+, spanning-tree pathcost long, vlan internal allocation |
| `cml_basic_forwarding_iosv_r1_ospf.txt` | 15.x (IOSv) | CML IOSv | OSPF process, network/area, ip ospf cost, dot1Q sub-interfaces |
| `batfish_iosxe_basic_vrrp.txt` | IOS (BR1) | Cisco IOS router | VRRP grammar (vrrp N ip / priority), 4 routed interfaces |
| `ntc_carrier_interfaces.txt` | — | (interface stress test) | dot1Q Q-in-Q, VRFs, QoS service-policies, uRPF, ACL groups |
| `batfish_cisco_interface.txt` | — | (parse stress) | every interface sub-command Batfish recognises |
| `batfish_cisco_ip_route.txt` | — | (parse stress) | ip route variants — name, track, AD, tag, permanent |
| `batfish_cisco_aaa.txt` | — | (parse stress) | AAA accounting/auth/authorization |
| `batfish_cisco_snmp.txt` | — | (parse stress) | snmp-server community / group / user / trap dest |
| `batfish_cisco_logging.txt` | — | (parse stress) | logging host / buffered / facility |

**Covered version-families:** 15.x (IOSv), 16.9, 17.3, 17.9, 17.12.

**Gaps from WANTED.md and timeline analysis:**

* **17.13 / 17.14 / 17.15 / 17.16 / 17.17 / 17.18** — entire current GA
  train (Nov 2023 → today) is uncovered.  17.15 + 17.18 are the active
  LTS branches; both are absent.
* **17.6** — common LTS (Bengaluru), absent from corpus.
* **16.6 / 16.12** — Everest LTS + last 16.x LTS, still in production at
  SMB/branch sites and showcasing pre-17.x grammar quirks.
* **Platform classes not yet exercised**: C9800 WLC (wireless config
  grammar — `wireless tag policy`, AP join profile, RF tags), ISR
  4400/4300 (cellular interface grammar, voice-port stanzas), ASR 1000
  (carrier-grade subscriber QoS), Cat 8500-L (SD-WAN cEdge).
* **Sub-interface trunk on physical** — flagged in WANTED.md alongside
  the 17.13+ gap; tag-VLAN dot1Q on a physical interface with a routed
  sub-interface fleet not yet present.

---

## Pull-target inventory

### 17.13+ (current GA train — the WANTED.md gap)

#### GitHub repositories

##### myhomenwlab/Initial_configuration_of_C9800-CL_after_deployment_from_OVA_file

* **URL**: <https://github.com/myhomenwlab/Initial_configuration_of_C9800-CL_after_deployment_from_OVA_file>
* **License**: MIT (explicit `LICENSE` file)
* **Provenance class**: Tier 1.1 (Open-source code repository with explicit
  permissive license)
* **Platform**: C9800-CL Wireless LAN Controller (virtual)
* **Versions covered**: **A real `show running-config` capture for every
  IOS-XE point release from 17.9.1 through 17.16.1** — specifically:
  17.9.1, 17.9.2, 17.9.3, 17.9.4, 17.9.4a, 17.9.5, 17.10.1, 17.11.1,
  17.12.1, 17.12.2, 17.13.1, 17.14.1, 17.15.1, 17.15.2, 17.16.1
* **Approx line count**: 12,000-13,000 bytes per `show_run.txt` (≈ 350-450
  lines); the companion `show_run_all.txt` for each version is much larger
  (full default expansion).
* **Grammar surface (high-value, novel to corpus)**:
  - `wireless tag policy` / `wireless tag site` / `wireless tag rf` —
    the C9800 WLC configuration grammar, parse-and-ignore today but very
    structured (named tags with policy/RF/site profile binding).
  - `ap profile` / `ap remote-lan-profile` / `flex profile` — AP join
    profile grammar.
  - `wireless profile policy` — per-WLAN policy bindings with VLAN
    assignment, AAA override, mDNS, NAC.
  - `wireless cts sxp` — CTS SXP grammar.
  - `radius server` named-server form with key encryption.
  - `crypto pki certificate chain` self-signed + manufacturer-issued
    device cert (legitimate full-chain).
* **Sanitisation needed**: Minor.  The configs look defensible-default
  (no real WAN, no real customer data) but verify each on a per-file
  basis — sanitise any non-RFC1918 addressing, sanitise the self-signed
  cert public bits at the operator's discretion (likely keep for grammar
  coverage, like the user_contrib_cat9300_iosxe1712 precedent).
* **Quality signal**: **5/5** — first MIT-licensed, version-canonical,
  multi-point-release capture of any cisco platform in any public repo
  identified.  Closes the WANTED.md 17.13+ gap by itself across 5
  consecutive LTS branches (17.13/17.14/17.15/17.16/17.17 absent only).
* **Recommended pulls (highest first)**:
  1. `config/C9800-CL_v17.15.01_show_run.txt` — current LTS, no fixture
  2. `config/C9800-CL_v17.16.01_show_run.txt` — most current released
  3. `config/C9800-CL_v17.13.01_show_run.txt` — closes the named gap
  4. `config/C9800-CL_v17.14.01_show_run.txt` — completes bridge

##### jg1vxg/netcon-j57-public

* **URL**: <https://github.com/jg1vxg/netcon-j57-public>
* **License**: Unlicensed (no LICENSE file); content is competition lab
  answer-keys + SSH session logs from JANOG57's NETCON challenge.  Falls
  under Tier 2 "forum-share-style precedent" (operator-published device
  output for educational competition) per `00-source-analysis.md`.  Drop
  the fixture if the author objects.
* **Provenance class**: Tier 2 (community-share precedent)
* **Platform**: Virtual Cisco IOS-XE routers (RT-01..04 named hosts) in
  a JANOG57 contest topology
* **Versions covered**: **IOS-XE 17.15.3a** confirmed in `Level3-13/rt01-output.txt`
  (and almost certainly across all 41 lab levels — Level1-1 through Level3-13)
* **Approx line count per output**: 85-95 lines each (multiple `rt*-output.txt`
  files per level)
* **Grammar surface (novel)**:
  - BGP AS 65001 with loopback peering — multi-router scenarios
  - OSPF debugging stanzas (Level3-13 explicitly an OSPF investigation lab)
  - Tunnel interfaces (Level3-13's `check-tunnel-output.txt`,
    `fix-tunnel-mode-output.txt`)
  - Cross-router policy interactions (route-maps, prefix-lists)
  - Likely covers VRF, NAT, SSH, AAA across the 41 problem set
* **Sanitisation needed**: Heavy — lab credentials are public in
  `ssh-info.json`; verify the captures don't embed personal info.  Treat
  these as Tier 2 forum-share-class material.
* **Quality signal**: **3/5** — strong on novelty (multi-router lab
  scenarios at 17.15.3a), weak on licence (drop on author objection).
* **Recommended pulls (highest first)**:
  1. `Level3-13/rt01-output.txt` — confirmed 17.15.3a sample
  2. One representative from Level1-N for basic single-router grammar
  3. One representative from Level2-N for mid-tier grammar
* **Caveat**: Files are session transcripts (login prompt + show command
  output), not pure `show run` — need transcript-stripping similar to
  the OPNsense paramiko_shell pattern.

##### Mediacastnet/mediacast-netcatalog

* **URL**: <https://github.com/Mediacastnet/mediacast-netcatalog>
* **License**: not verified — needs check before pull (path
  `catalog/cisco-ios-xe.yaml` matched GitHub code-search for 17.12;
  contents not confirmed)
* **Provenance class**: Likely Tier 1.1 if licensed permissively
* **Quality signal**: 2/5 — needs verification, listed for follow-up

##### tkdebnath/simple-upgrade

* **URL**: <https://github.com/tkdebnath/simple-upgrade>
* **License**: not verified (matched 17.12 + 17.15 code-search)
* **Provenance class**: Tier 1.1 candidate
* **Quality signal**: 2/5 — follow-up

#### Forum / community posts

##### Cisco Community 17.15.2 config-saving thread

* **URL**: <https://community.cisco.com/t5/switching/ios-xe-17-15-2-not-saving-config-changes/m-p/5500189>
* **Provenance class**: Tier 2.1 (vendor community forum, operator-paste
  precedent matching the HPE Community 7026923 / 7051607 / 7084768 +
  6935784 fixtures already in corpus)
* **OS version**: 17.15.2 (explicitly named in the thread title)
* **Grammar surface**: per-interface show running-config snippets posted
  while troubleshooting config-rollback behaviour
* **Sanitisation needed**: Heavy — re-verify hostnames, IPs, hashes
  per the existing HPE forum-share precedent
* **Quality signal**: 3/5 — closing the 17.15 gap with operator-paste
  pedigree comparable to the AOS-S forum fixtures

##### Cisco Community privilege-level + IOS-XE 17.x

* **URL**: <https://community.cisco.com/t5/network-management/ios-ios-xe-privilege-level-for-show-running-config-only-version/td-p/4951976>
* **Provenance class**: Tier 2.1
* **OS version**: 17.x privilege-mode discussion — paste contains
  `privilege exec level N show ...` stanzas
* **Grammar surface**: privilege delegation grammar (already partially
  in `user_contrib_cat9300_iosxe1712.txt`'s 28-line table, but a thread
  worth crawling for additional patterns)
* **Quality signal**: 2/5

#### Vendor docs / lab guides

##### Cisco IOS XE 17.13 / 17.14 / 17.15 / 17.16 / 17.17 / 17.18 Configuration Guides

* **URLs** (per-platform, e.g. Cat9300 17.18):
  <https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-18/configuration_guide/sys_mgmt/b_1718_sys_mgmt_9300_cg/managing_configuration_files.html>
  and per-platform-per-release equivalents for ASR1k, ISR4k, CSR/C8000V,
  C9800, Cat9k
* **License**: Cisco-defined "example use" terms — historically pulled
  per fair-use excerpt in the existing corpus (no fixtures from this
  source yet because they're synthetic examples, not real captures)
* **Provenance class**: Tier 1.2 (vendor documentation examples)
* **Grammar surface**: synthesised exemplars per feature — useful for
  cross-checking grammar correctness, not for `show running-config`
  fixtures
* **Quality signal**: 2/5 for fixture purposes (good for grammar
  reference, weak for kitchen-sink coverage)

##### Cisco SD-WAN cEdge 17.13/17.14/17.15 CLI Templates

* **URLs**:
  <https://www.cisco.com/c/en/us/td/docs/routers/sdwan/configuration/system-interface/ios-xe-17/systems-interfaces-book-xe-sdwan/cli-template.html>
  + per-version SD-WAN config guides
* **License**: Cisco fair-use
* **Grammar surface**: SD-WAN controller-mode `sdwan` stanza, TLOC
  encapsulation, OMP, BFD per-TLOC — entirely missing from corpus today
* **Quality signal**: 3/5 — adds the controller-mode IOS-XE distinct
  from autonomous-mode (which is what we test today)

#### Other (pastebin / YouTube transcripts / Internet Archive / blogs)

##### Wires and Wi-Fi base configuration blog post (17.12.4)

* **URL**: <https://www.wiresandwi.fi/blog/cisco-ios-xe-switch-general-base-configuration-cli>
* **OS version**: 17.12.4 (tested on Cat C9200L-48P-4X, C9200CX-12P-2X2G)
* **Provenance class**: Tier 2.4 (operator blog) — use as discovery, not
  direct import (re-author as synthetic if pulled)
* **Grammar surface**: general access-switch base config — `aaa
  authentication`, `radius server`, `device-tracking`, `errdisable
  recovery`, dot1x, comprehensive operator-trusted starting point
* **Quality signal**: 3/5 — high-signal for grammar reference, not
  directly importable

##### Containerlab + Cisco IOL 17.12.01 / 17.16.01a community labs

* **URL**: <https://containerlab.dev/manual/kinds/cisco_iol/>,
  <https://torbjorn.dev/blog/cml-nodes-in-clab/>
* **OS versions**: 17.12.01 (well-documented in containerlab samples),
  17.16.01a (extracted from CML refplat ISOs)
* **Provenance class**: Tier 1.3 (lab platform) — IOL is the same
  ioll2-xe image we already use for `cml_saumur_iosxe1712_pvrstp.txt`
* **Grammar surface**: Ethernet0/N interface notation (IOL-specific),
  spanning-tree, OSPF/EIGRP/BGP, basic L3 grammar
* **Quality signal**: 4/5 — same pedigree as already-shipped CML
  fixture, just newer version

---

### 17.9-17.12

#### GitHub repositories

##### myhomenwlab/Initial_configuration_of_C9800-CL_after_deployment_from_OVA_file (continued)

Same repo as 17.13+ block.  Covers 17.9.1, 17.9.2, 17.9.3, 17.9.4,
17.9.4a, 17.9.5, 17.10.1, 17.11.1, 17.12.1, 17.12.2 with MIT licence.
For these versions the **gap is narrower** — corpus already has 17.9
(racc) and 17.12 (user_contrib + cml) — but the C9800 platform class
is unique (wireless grammar) and worth a single representative pull.

* **Recommended pull**: `C9800-CL_v17.11.01_show_run.txt` — fills the
  17.11 hole between corpus 17.9 and 17.12 covers.

##### nickrusso42518/racc additional samples

* **URL**: <https://github.com/nickrusso42518/racc>
* **License**: BSD-3-Clause
* **Already harvested**: csr1_20210629T142431/show_running-config.txt
  (17.3.2 → `racc_csr1_iosxe173_umbrella_sig.txt`),
  csr2_20230811T074823 (16.9 → `racc_csr1000v_iosxe169_bgp_ospf.txt`),
  csr1_20230811T074823 (17.9 → `racc_cat8000v_iosxe179_netconf.txt`)
* **Remaining samples**: csr2_20210629T142431 (also 17.3.2 — a sibling
  CSR1000v in the same lab snapshot to the already-pulled csr1; would
  add a peer router for round-trip multi-device scenarios), asav1
  (ASAv, distinct OS), n9kv1 (NX-OS), xrv1 (IOS-XR), vmx1 (Junos),
  veos1 (EOS), chr1 (RouterOS), f5lb1 (F5).  None are additional
  IOS-XE versions.
* **Provenance class**: Tier 1.1
* **Quality signal**: 3/5 for csr2_20210629 — duplicate version but
  peer-router scenario useful

#### Forum / community posts

##### Cisco Community routing / IOS-XE BGP threads

* **URL**: <https://community.cisco.com/t5/routing/forum-board>
* **Provenance class**: Tier 2.1
* **Versions covered**: many threads pin 17.9 / 17.12 in titles or
  device output
* **Sanitisation needed**: Heavy
* **Quality signal**: 3/5

#### Vendor docs / lab guides

##### CiscoDevNet/cml-community lab-topologies

* **URL**: <https://github.com/CiscoDevNet/cml-community>
* **License**: BSD-3-Clause
* **Already harvested**: `lab-topologies/ccna/Domain_2/2.5-interpret_stp/saumur_PVRSTP_solution.yaml` (17.12 → `cml_saumur_iosxe1712_pvrstp.txt`); `lab-topologies/basic-forwarding-behavior.yaml` (15.x IOSv → `cml_basic_forwarding_iosv_r1_ospf.txt`)
* **Remaining unmined sub-trees** (each `*_solution.yaml` or `*_Completed_Lab.yaml` typically embeds full `show running-config` per node):
  - `lab-topologies/ccna/Domain_2/` — 9 STP / VLAN / EtherChannel labs (`2.1-configure_vlans_{1,2,3}`, `2.2-configure_interswitch_connectivity_{1,2,3}`, `2.3-configure_l2_discovery_{1,2,3}`, `2.5-interpret_stp`) — covers L2 grammar (VTP, native VLAN, port-security, BPDU-guard)
  - `lab-topologies/ccna/Domain_3/3.4-configure_ospfv2_{1,2}/{Completed,Initial}_Lab.yaml` — full OSPF (2 router topologies)
  - `lab-topologies/ccna/Domain_3/3.3-configure_static_routing/` — static routing
  - `lab-topologies/ccna/Domain_4/4.6-configure_dhcp_client/`, `4.8-configure_remote_access_{1,2}/` — DHCP-client interface form + SSH/RADIUS AAA
  - `lab-topologies/ccna-prep/s1e1` (VLANs), `s1e2` (STP), `s1e3` (EtherChannel), `s1e4` (Static routes), `s1e5` (OSPF), `s2e1` (DHCP), `s2e2` (DNS), `s2e3` (NAT), `s2e4` (SSH), `s2e5` (NTP), `s2e6` (Syslog), `s2e7` (SNMP), `s3e1` (L2 security), `s3e2` (ACLs) — comprehensive CCNA-curriculum coverage; **every embedded `configuration: |` block is a real, BSD-3-licensed `show running-config` from CML's ioll2-xe / IOSv image**
  - `lab-topologies/aaa-tacacs-exploration/` — AAA + TACACS grammar
  - `lab-topologies/300-node-lab/300_node_lab.yaml` — large-scale topology, multi-router context for fabric-style grammar
* **Versions**: CML reference platform tracks current IOS-XE LTS;
  ioll2-xe images correspond to 17.12 (current reference) per the
  saumur capture's banner.  CML reference-platform image
  release-cadence aligns to ~17.12-17.15 in 2025-2026.
* **Provenance class**: Tier 1.3 (lab platform, BSD-3 explicit licence)
* **Quality signal**: 5/5 — same pedigree as existing CML fixtures,
  every CCNA-prep lab is a fresh grammar-surface capture.  Top
  expansion target.

#### Other

##### CCIE SPv5.1 Labs GitBook (containerlab + IOL 17.12)

* **URL**: <https://ccie-sp.gitbook.io/ccie-spv5.1-labs>
* **Provenance class**: Tier 3.2 (cert prep, study-guide); GitBook is
  publicly-readable but check copyright before pulling text
* **OS versions**: 17.12.x via IOL via containerlab
* **Grammar surface**: SP-routing — MPLS, RSVP-TE, L3VPN, BGP-LU
* **Quality signal**: 3/5 — useful for grammar reference, careful on
  direct quotation

##### theworldsgonemad.net "Lab as Code Part 2" (2025) IOL 17.16.01a

* **URL**: <https://theworldsgonemad.net/2025/lab-as-code-pt2/>
* **Provenance class**: Tier 2.4 (operator blog)
* **OS version**: 17.16.01a (most recent published reference)
* **Quality signal**: 3/5 — discovery; rewrite as synthetic if pulled

---

### 17.3-17.6 (Amsterdam / Bengaluru train)

#### GitHub repositories

##### batfish/lab-validation (IOS / IOS-XE snapshots) — **highest leverage**

* **URL**: <https://github.com/batfish/lab-validation>
* **License**: Apache-2.0 (same pedigree as already-shipped
  `batfish_iosxe_basic_vrrp.txt`, `batfish_cisco_*.txt` fixtures)
* **Provenance class**: Tier 1.1
* **Cisco IOS / IOS-XE snapshots present** (from `gh api` enumeration
  at commit `main`):
  1. `ios_add_path` — BGP ADD-PATH capability
  2. `ios_basic_vrrp` — already in corpus (`batfish_iosxe_basic_vrrp.txt`)
  3. `ios_bgp_path_select_8` — BGP path-selection grammar
  4. `ios_example_network` — general network example
  5. `ios_ibgp_split_horizon` — iBGP split-horizon
  6. `ios_nxos_bgp_local_as` — mixed IOS/NX-OS local-AS grammar
  7. `iosxe_bgp_confederation` — BGP confederation (6 devices: D1..D6
     each with `show_running-config.txt` ≈ 2.8KB / 90 lines)
  8. `iosxe_connectivity_sample` — basic connectivity / `iosxe_acl`
     device variant
  9. `iosxe_ebgp_loop_prevention` — eBGP loop-prevention
  10. `iosxe_eigrp_multi_process` — EIGRP with multiple processes
  11. `iosxe_eigrp_neighbor` — EIGRP neighbour relationships
  12. `iosxe_redistribution` — route redistribution between protocols
  13. `iosxe_undefined_route_map` — route-map handling edge cases
  14. `iosxe_vrf_route_leaking_bgp_peering` — VRF + BGP route-leaking
     (devices: d1_v12, d2_v34, d33_v3, d44_default, d55_default)
  15. `iosxe_vrf_route_leaking_classic_eigrp` — VRF + classic EIGRP
  16. `iosxe_vrf_route_leaking_export_map` — VRF + export-map
  17. `iosxe_vrf_route_leaking_wide_eigrp` — VRF + wide-mode EIGRP
* **Versions**: Batfish lab-validation snapshots are typically 17.3/17.6
  ioll2-xe-based — the exact version per snapshot needs verification
  from device-banner inspection.  Many snapshots have multi-device
  configs (5-6 routers each) totalling ~500-2,500 lines of real
  `show running-config` per snapshot.
* **Approx line counts**: 90-450 lines per device, 5-12 devices per
  snapshot, 12 snapshots × 5-7 devices = 60+ individual config files
* **Grammar surface (high-value, novel to corpus)**:
  - **VRF route-leaking grammar** (4 different snapshots — BGP peering,
    classic EIGRP, export-map, wide-mode EIGRP) — VRF grammar today
    parses-and-ignores in `cisco_iosxe_cli`; concrete kitchen-sink
    fixtures would drive `CanonicalRoutingInstance` schema design
  - **BGP confederation** (sub-AS members, confederation peers) —
    confederation grammar is parse-and-ignore today
  - **eBGP loop-prevention** — `bgp bestpath as-path multipath-relax`,
    `as-override`, allow-as-in
  - **Route-map / prefix-list edge cases** — undefined route-map
    handling, continue clauses
  - **EIGRP multi-process** — distinct from the simple EIGRP grammar
    `racc_csr1_iosxe173_umbrella_sig.txt` exercises (CITYNET single
    process)
* **Sanitisation needed**: None (already operator-shared in upstream
  Apache repo)
* **Quality signal**: **5/5** — Apache-2.0 licence + multi-device
  scenarios + 16 novel snapshots not yet in corpus.  Massive expansion
  target for `cisco_iosxe_cli` codec.
* **Recommended pulls (highest first)**:
  1. `snapshots/iosxe_vrf_route_leaking_bgp_peering/configs/d1_v12/show_running-config.txt`
     — VRF-leak grammar witness for `CanonicalRoutingInstance` future
     work (cross-vendor parity with batfish junos_l3vpn / nxos_evpn_l3vni
     already in corpus)
  2. `snapshots/iosxe_bgp_confederation/configs/D1/show_running-config.txt`
     — BGP confederation grammar witness (sub-AS members)
  3. `snapshots/iosxe_eigrp_multi_process/configs/<device>/show_running-config.txt`
     — multi-process EIGRP grammar
  4. `snapshots/iosxe_ebgp_loop_prevention/configs/<device>/show_running-config.txt`
     — loop-prevention grammar

##### karneliuk-com/batfish-mvp

* **URL**: <https://github.com/karneliuk-com/batfish-mvp>
* **License**: BSD-3-Clause (same as already-shipped
  `karneliuk_a_eos1_eos4260.txt`)
* **Snapshots**: `snapshots/nat/configs/{EOS1,VX1,XR1}.cfg` — **VX1.cfg
  is a virtual IOS-XE NAT-focused config**.  XR1 is IOS-XR, EOS1 is
  Arista (already in corpus).
* **VX1.cfg grammar surface**: NAT (ip nat inside / outside / static),
  BGP, basic OSPF — focused single-router scenario.
* **Version**: not specified in repo metadata; needs banner check —
  likely 17.x.
* **Quality signal**: 4/5 — small, focused capture; BSD-3 pedigree
  already vetted via the EOS1 fixture.

#### Forum / community posts

##### Cisco Community 17.6 / 17.3 Bengaluru threads

* Search: <https://community.cisco.com/t5/switching/bd-p/4461-discussions-switching>
* **Versions**: many 17.6 LTS deployments still surface in operator
  troubleshooting threads as of mid-2026 (17.6 security-EoL was
  2024-07-30 but enterprises rarely upgrade out)
* **Provenance class**: Tier 2.1, same precedent as the AOS-S HPE
  Community fixtures
* **Quality signal**: 3/5

#### Vendor docs / lab guides

* Cisco DevNet Sandbox IOS-XE Always-On (typically 17.3-17.6 in
  reservation banners) at <https://devnetsandbox.cisco.com/RM/Topology>
  — login-gated but configs exportable by sandbox-user.  Treat as
  Tier 4 unless operator publishes the export.
* Cisco SD-WAN Lab Guide (SWAT) at <https://swat-sdwanlab.github.io/>
  — cEdge dual-uplink scenarios on IOS-XE 17.6+

#### Other

* `0x2142.com/getting-started-with-ios-xe-guestshell` — operator blog,
  17.3+ guestshell config snippets; Tier 2.4 (rewrite as synthetic)

---

### 16.x (Everest / Fuji / Gibraltar / Polaris)

#### GitHub repositories

##### batfish/lab-validation — older IOS snapshots

* Snapshots without explicit version banner may default to older IOSv /
  ioll2-xe images (15.x or 16.x); needs per-snapshot banner inspection
* `ios_example_network`, `ios_bgp_path_select_8`, `ios_add_path` likely
  predate the iosxe_*-prefixed snapshots
* Already-shipped `batfish_iosxe_basic_vrrp.txt` is from `ios_basic_vrrp`
  with `version 15.X` banner (classic IOS, not IOS-XE) — illustrative
  that this snapshot family is IOS-classic on the BR1 device

##### nickrusso42518/racc 16.9 + 16.12 captures

* Already-harvested: csr2_20230811T074823 (16.9 → in corpus)
* No 16.12 capture in racc; **gap remains for 16.12 LTS**
* Quality signal: 5/5 for existing 16.9; no further racc work for 16.x

##### YangModels/yang vendor/cisco/xe/

* **URL**: <https://github.com/YangModels/yang/tree/main/vendor/cisco/xe>
* **License**: Apache-2.0
* **Content**: NETCONF/YANG capability XML + Cisco-published YANG
  models per IOS-XE release — **not running-config**, but useful for
  the NETCONF Phase-0.5 stub codec validation (`cisco_iosxe` codec
  alongside `cisco_iosxe_cli`)
* **Versions present**: `vendor/cisco/xe/{1631,1651,1661,1671,1691,16101,16111,16121,1711,1721,1731,1741,1751,1761,1771,1781,1791,17101,17111,17121,17131,17141,17151,17161,17171,17181}/`
  (i.e., every minor from 16.3.1 onwards has its own subfolder)
* **Provenance class**: Tier 1.1, Apache
* **Quality signal**: 5/5 for NETCONF stub; n/a for `cisco_iosxe_cli`

#### Forum / community posts

##### Cisco Community "All you need to know about Cisco IOS XE 16.x Releases" (blog)

* **URL**: <https://community.cisco.com/t5/networking-blogs/all-you-need-to-know-about-cisco-ios-xe-16-x-releases/ba-p/3661814>
* **Provenance class**: Tier 1.2 (vendor blog) — Cisco-published, fair use
* **Content**: Release-naming overview; no running-config inside
* **Quality signal**: 2/5 — context-only

#### Vendor docs / lab guides

##### Cisco Catalyst 3850 Series Switches IOS-XE Denali/Everest/Fuji release notes

* **URL**: <https://www.cisco.com/c/en/us/support/switches/catalyst-3850-series-switches/products-release-notes-list.html>
* **Provenance class**: Tier 1.2
* **Content**: Example configs synthesised per feature; no full
  running-config
* **Quality signal**: 2/5

##### Cisco ASR 1000 IOS-XE 16.x configuration examples (CCO docs)

* **URL**: <https://www.cisco.com/c/en/us/support/docs/routers/asr-1000-series-aggregation-services-routers/index.html>
* **Provenance class**: Tier 1.2
* **Quality signal**: 2/5 (synthesised, not real)

#### Other

##### Internet Archive Wayback captures of 2015-2019 operator blogs

* **URL**: <https://web.archive.org/web/2015*/inurl:lab "interface GigabitEthernet"> and similar
* **Provenance class**: Tier 3.4
* **Content**: Captures of blog posts that hosted 16.x config samples
  before being taken down
* **Quality signal**: 2/5 — discovery, treat as synthetic
* **Notable target**: <https://web.archive.org/web/2018*/packetlife.net*> —
  Jeremy Stretch's 16.x blog posts archived before site reorganisation

##### LukeDRussell/07740b7dc00ec181c89af64f7f5fa088 (GitHub Gist)

* **URL**: <https://gist.github.com/LukeDRussell/07740b7dc00ec181c89af64f7f5fa088>
* **Content**: Curated `show version` samples across IOS / IOS-XE
  versions — useful for version-string regex calibration but not for
  `show run` fixtures
* **License**: Gist default (no explicit licence)
* **Quality signal**: 2/5 for run-config; 4/5 for version-detection
  unit testing

---

### 3.x legacy (Polaris / Edison)

> Pre-2015 / early 2015 — deliberately low-priority per scope.

* **Cisco ASR 1000 IOS-XE 3.16S / 3.17S** release notes have CCO-published
  configuration examples but no full captures.  Skip unless a
  customer-specific bug surfaces against 3.x grammar (unlikely — most
  3.x deployments have migrated to 16.x by 2026).
* **GitHub** code-search returns very few 3.x captures; the `racc`
  toolchain explicitly tests against 16.12.01a forwards so no racc
  3.x sample exists.

---

## Recommended pull priority order

Highest-leverage pulls across the entire IOS-XE catalogue, in order:

1. **`myhomenwlab/.../C9800-CL_v17.15.01_show_run.txt`** — MIT, real
   `show run` from C9800-CL on **17.15 LTS** (the current LTS with zero
   corpus coverage).  First C9800 wireless-grammar fixture too.
   ≈350-450 lines.  Quality 5/5.
2. **`myhomenwlab/.../C9800-CL_v17.13.01_show_run.txt`** — MIT, closes
   the named WANTED.md 17.13+ gap explicitly.  Quality 5/5.
3. **`myhomenwlab/.../C9800-CL_v17.16.01_show_run.txt`** — MIT, most
   current release.  Quality 5/5.
4. **`batfish/lab-validation/snapshots/iosxe_vrf_route_leaking_bgp_peering/configs/d1_v12/show_running-config.txt`** —
   Apache-2.0, VRF-leaking grammar pattern absent from corpus; aligns
   with the cross-vendor `CanonicalRoutingInstance` work flagged in
   WANTED.md (alongside junos_l3vpn / nxos_evpn_l3vni already used).
   Quality 5/5.
5. **`batfish/lab-validation/snapshots/iosxe_bgp_confederation/configs/D1/show_running-config.txt`** —
   Apache-2.0, BGP confederation grammar (parse-and-ignore today;
   real-capture witness for future BGP confederation modelling).
   Quality 5/5.
6. **`CiscoDevNet/cml-community/lab-topologies/ccna-prep/s2e3` (NAT)** —
   BSD-3, real ioll2-xe NAT grammar (PAT, static NAT, NAT inside-source
   route-map); current corpus only has PAT via the racc Cat8000V 17.9
   fixture.  Quality 5/5.
7. **`CiscoDevNet/cml-community/lab-topologies/ccna-prep/s2e7` (SNMP)** —
   BSD-3, real SNMPv3 grammar (group / user / view) — current
   `batfish_cisco_snmp.txt` is parse-stress; this would be a clean,
   minimal, ioll2-xe-real capture.  Quality 4/5.
8. **`myhomenwlab/.../C9800-CL_v17.11.01_show_run.txt`** — fills the
   17.11 hole between corpus's 17.9 and 17.12; minimal incremental
   cost.  Quality 4/5.
9. **`batfish/lab-validation/snapshots/iosxe_eigrp_multi_process/configs/<device>/show_running-config.txt`** —
   Apache-2.0, multi-process EIGRP grammar absent from corpus.
   Quality 4/5.
10. **`CiscoDevNet/cml-community/lab-topologies/ccna-prep/s3e2` (ACLs)** —
    BSD-3, comprehensive ACL grammar (numbered + extended-named) — useful
    cross-check against `ntc_carrier_interfaces.txt`'s carrier-grade
    ACLs.  Quality 4/5.

### Secondary tier (when primary closed)

11. `karneliuk-com/batfish-mvp/snapshots/nat/configs/VX1.cfg` — BSD-3,
    NAT-focused single-router capture.  Quality 4/5.
12. `myhomenwlab/.../C9800-CL_v17.18.01_show_run.txt` — once 17.18.01
    publishes (Aug 2025); LTS coverage.  Quality 5/5 (when available).
13. Cisco Community 17.15.2 thread — Tier 2 forum-share; closes the
    operator-paste precedent for 17.x.  Quality 3/5.
14. `jg1vxg/netcon-j57-public/Level3-13/rt01-output.txt` — unlicensed
    Tier-2 transcript material; 17.15.3a multi-router lab.  Quality 3/5.

---

## Out-of-scope (deliberately excluded)

* **CCNA / CCNP / CCIE workbook configs** (Cisco Press, INE, CBT
  Nuggets, IPexpert) — copyright is real per `00-source-analysis.md` §
  3.2; treat as discovery only.  No direct import.
* **Cisco Press book example excerpts** — fair-use for blog quotation,
  not for fixture commit.  Excluded.
* **CCNA Packet Tracer `.pkt` files** — proprietary container format,
  cannot import as plain-text `show run` even if the embedded config
  would be permissive.
* **Cisco DevNet Sandbox login-gated configs** — Tier 4 per
  `00-source-analysis.md`; sandbox terms typically restrict
  republication.
* **Customer-deployed configs from consulting work** — Tier 4 hard line
  per `BUG_REPORTING.md`.
* **IOS-XE NETCONF capability XML alone** — useful for the
  `cisco_iosxe` NETCONF stub codec but not a `cisco_iosxe_cli`
  fixture target; tracked separately if/when the NETCONF stub
  becomes a full codec in a future release.
* **3.x IOS-XE pre-2015 captures** — pre-window per scope; skipped.
* **Pastebin anonymous IOS-XE captures** — Tier 3.1, low licence
  confidence + heavy sanitisation cost; only revisit if a high-value
  gap can't be closed via Tier 1.

---

## Notes on `cisco_iosxe` NETCONF Phase-0.5 stub

The `cisco_iosxe` codec (distinct from `cisco_iosxe_cli`) handles
NETCONF/YANG `<rpc-reply>` XML returned by the management plane.  No
real-capture fixture exists for it yet because:

* The `YangModels/yang/vendor/cisco/xe/` repo (Apache) provides per-version
  YANG models + capability XML for every IOS-XE release from 16.3.1
  onwards — these are the right fixture sources if the stub is promoted
  to a full codec.
* A `<get-config>` reply containing Cisco-IOS-XE-native YANG-modelled
  state is the actual fixture shape; pulling one requires running
  NETCONF against a real device (DevNet sandbox + sanitisation).
* The existing 12 CLI-text fixtures already exercise the `cisco_iosxe_cli`
  path comprehensively; NETCONF-stub fixture work is a separate
  expansion track flagged for a future v0.3.0+ effort.

---

## See also

* [`README.md`](README.md)
* [`00-source-analysis.md`](00-source-analysis.md)
* [`tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md)
* [`tests/fixtures/real/WANTED.md`](../../tests/fixtures/real/WANTED.md)
* [`BUG_REPORTING.md`](../../BUG_REPORTING.md) — sanitisation +
  fixture-submission workflow that any actual pull from this catalogue
  must follow

# Aruba AOS-S — fixture catalogue (2015+)

> **Tier**: Shipped
> **Codec**: `aruba_aoss`
> **Existing corpus**: 6 fixtures spanning WB.16.08 / WC.16.07-11 / KB.15.15

Per-OS catalogue for the **ArubaOS-Switch** family (formerly HP
ProVision; the `;NameA Configuration Editor; Created on release #X.16.YY`
header dialect — *not* the next-generation `arubaos-cx` switch OS
catalogued separately in [`11-aruba_aoscx.md`](11-aruba_aoscx.md)).
References the source-type taxonomy in
[`00-source-analysis.md`](00-source-analysis.md).

---

## Software-branch ↔ platform map

AOS-S software is released in parallel **branches**, each named for a
platform family.  Branch identifier is the prefix on the
`Created on release #<BRANCH>.<MAJOR>.<MINOR>.<PATCH>` header line.

| Branch | Platforms | Hardware class | First-party docs |
|---|---|---|---|
| **WB** | 2920 series | Stackable 1U L3 | [Aruba 2920 mgmt guide](https://arubanetworking.hpe.com/techdocs/AOS-Switch/16.10/Aruba%202920%20Management%20and%20Configuration%20Guide%20for%20ArubaOS-Switch%2016.10.pdf) |
| **WC** | 2930F / 2930M | Stackable 1U L3 (BPS / VSF) | [2930F/M release notes](https://arubanetworking.hpe.com/techdocs/AOS-Switch/RN/16.11/) |
| **KA** | 3800 / 5400zl (gen 1) | Stackable / 6-slot chassis (legacy) | [KA.16.04 release notes](https://arubanetworking.hpe.com/techdocs/AOS-Switch/RN/16.04/AOS-S%20Switch%20KA.16.04.0025%20Release%20Notes.pdf) |
| **KB** | 3810M / 5400R / 5400Rzl2 | Stackable (BPS) + 6-slot modular chassis | [KB 16.11 fixes](https://arubanetworking.hpe.com/techdocs/AOS-Switch-RN/Content/16.11RN/KB/Fixes.htm) |
| **RA** | 2620 series | Stackable 1U L3 (EoL'd) | [Microfocus device-support matrix](https://docs.microfocus.com/NOM/2017.11/Content/common/nom_device_support_matrix/DSD_EXT_HP_ProCurve.html) |
| **YA / YB** | 2530 series | Stackable 1U L2 (YA = 24/48-port, YB = 8G/24G fanless) | [YA/YB.15.18.0006 release notes](https://studylib.net/doc/18289892/ya-yb.15.18.0006-release-notes) |
| **YC** | 2540 series | Stackable 1U L2 (Aruba-Central-managed entry) | [YC 16.10 enhancements](https://arubanetworking.hpe.com/techdocs/AOS-Switch-RN/Content/16.10RN/YC/Enhancements.htm) |

The task spec named "YA / RA software branches; 8400 chassis class"
as the WANTED.md gap.  Two corrections worth noting for downstream
catalogue accuracy:

* **RA is the 2620 family**, *not* the 2540.  The 2540 is the **YC**
  branch.  Confirmed cross-referenced via the AOS-S techdocs URL path
  `/16.11/MRG/KB/content/kb/vla-ran-com-ka-kb-ra-wb-ya-yb-yc..htm`
  (which enumerates every AOS-S branch in canonical order) and
  [Microfocus' device-support matrix](https://docs.microfocus.com/NOM/2017.11/Content/common/nom_device_support_matrix/DSD_EXT_HP_ProCurve.html)
  (lists every branch + its tracked switch series).
* **8400 chassis is AOS-CX, not AOS-S** — confirmed via [Aruba CX
  8400 data sheet](https://andovercg.com/datasheets/aruba-CX-8400-series-switches.pdf)
  and the [AOS-CX 10.11 8400-series Fundamentals
  Guide](https://arubanetworking.hpe.com/techdocs/AOS-CX/10.11/PDF/fundamentals_8400.pdf).
  No AOS-S branch exists for the 8400 — that chassis class only
  ever shipped with AOS-CX.  The WANTED.md gap "8400 chassis class
  AOS-S running-config" is a doc typo — belongs in
  [`11-aruba_aoscx.md`](11-aruba_aoscx.md), not here.  This catalogue
  treats it as out-of-scope.

---

## Version timeline

AOS-S followed the `15.x` numbering pre-2017 and then renumbered to
`16.x` for the 16.01 onwards train.  Branches share major-minor
trains where they have feature parity (e.g. 16.11.0001 was released
across WB/WC/KA/KB/RA/YA/YB/YC in late 2020, with branch-specific
patch-level fixes thereafter).

| Major.minor | Release window | Branches | Notes |
|---|---|---|---|
| **15.12 - 15.18** | 2014 - mid-2016 | All branches (YA/YB/RA/WB/KA + S/T/U/W/Y precursors) | The pre-renumber "15-train".  Many production boxes still on 15.18.x today (in long-term support mode). |
| **16.01** | Jan-Mar 2017 | WB, WC, KA, KB, RA, YA/YB | First release of the unified 16.x major.  Built on YA/YB.15.18.0007, WB.15.18, KB.15.18. |
| **16.02** | Mar-Aug 2017 | All seven branches | Stable LTS-class train for 2017 — many fixtures from this period. |
| **16.03** | mid-2017 - 2018 | All seven branches | Initial release of new WebUI; broke remote management for some operators (covered in HPE Community 6934713). |
| **16.04** | 2018 | All seven branches | KA.16.04.0025 is the last KA-branch release (KA reached End-of-Software-Support in 2019). |
| **16.05 - 16.07** | 2018 - 2019 | WB, WC, KB, RA, YA/YB, YC | KA branch frozen from 16.04. |
| **16.08** | 2019 | WB, WC, KB, YA/YB, YC, RA | First 16.08.0022 is the last bug-fix-only release for RA before RA reached EoSS in 2020. |
| **16.09** | Q4 2019 | WB, WC, KB, YA/YB, YC | RA-branch dropped (2620 EoS). |
| **16.10** | 2020 | WB, WC, KB, YA/YB, YC | Last WB-branch GA train (2920 entered "maintenance-mode-only" in 2021). |
| **16.11** | Late 2020 - present | WB, WC, KB, YA/YB, YC | Active LTS train.  Patches through 16.11.0025+ as of 2025.  Most recent: 16.11.0025 (KB/3810). |

Per-branch detail:

* **KA** — frozen at 16.04.0025 (2019); platforms (5400zl gen1,
  3800) at EoS, no new feature work.
* **RA** — frozen at 16.08.x (2020); 2620 platform at EoS.
* **WB** — last 16.x branch GA was 16.10.x; some bug-fix patches
  trickle to 16.11.x but 2920 platform is in maintenance-mode-only.
* **WC / KB / YA / YB / YC** — all four are active branches with
  ongoing 16.11.x patches.

Source-of-record: [arubanetworking.hpe.com TechDocs AOS-Switch RN
portal](https://arubanetworking.hpe.com/techdocs/AOS-Switch-RN/) and
the per-branch [16.10 Fixes/Enhancements](https://arubanetworking.hpe.com/techdocs/AOS-Switch-RN/Content/16.10RN/) /
[16.11 Fixes/Enhancements](https://arubanetworking.hpe.com/techdocs/AOS-Switch-RN/Content/16.11RN/) sub-portals.

---

## Existing corpus coverage

From [`tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md)
`aruba_aoss/` section.  6 fixtures across **3 branches and 4 major
versions**:

| File | Branch.major | Platform | Source class |
|---|---|---|---|
| `aruba_central_5memberstack_rendered.cfg` | (synthetic; renders WC.16-ish grammar) | 5-member 2930M stack template | GitHub MIT (rendered) |
| `hpe_community_2930f_wc1607_intervlan.cfg` | WC.16.07 | 2930F | Forum-share |
| `hpe_community_2920_wb1608_dhcp_snooping.cfg` | WB.16.08 | 2920 | Forum-share |
| `hpe_community_2930f_wc1610_dhcp_server.cfg` | WC.16.10 | 2930F | Forum-share |
| `user_contrib_2930m_wc1611.cfg` | WC.16.11 | 2930M stack | User contribution |
| `hpe_community_5406rzl2_kb1515.cfg` | KB.15.15 | 5406Rzl2 chassis | Forum-share |

Effective branch coverage: **WB (1), WC (4 incl. rendered), KB (1)**.
Branches with **zero fixtures**: KA, RA, YA, YB, YC.  Versions with
zero coverage: any 16.01-16.06 train, any 15.x year-2015-era, the
entire YC track (2540).  Platform classes with zero coverage: 2530,
2540, 2620, 3800, 3810M, 5400zl gen-1.

Note: the existing NOTICE.md entry attributes `aruba_central_5memberstack_rendered.cfg`
to `BSD-2-Clause` upstream — but the upstream repo
[aruba/central-sample-bulk-configurations](https://github.com/aruba/central-sample-bulk-configurations)
license is actually **MIT** (verified via `gh api repos/aruba/central-sample-bulk-configurations/license`
returning `{"spdx_id":"MIT"}`, raw `LICENSE` header `MIT License /
Copyright (c) 2018 Aruba, a Hewlett Packard Enterprise company`).
Fixing the NOTICE.md attribution is a separate small task — not in
this catalogue's scope.

---

## Pull-target inventory

### YA / YB branch (2530 family — WANTED.md gap)

#### GitHub repositories

**[HPENetworking/HPEIMCUtils](https://github.com/HPENetworking/HPEIMCUtils)
— `ZeroTouchProvisioning/InitialConfigFiles/ArubaOS/2530/2530_Final_Config.cfg`**
* URL: <https://raw.githubusercontent.com/HPENetworking/HPEIMCUtils/master/ZeroTouchProvisioning/InitialConfigFiles/ArubaOS/2530/2530_Final_Config.cfg>
* License: **Apache-2.0** (root `LICENSE` file, copyright 2016 HPE
  Development LP — verified via `gh api repos/HPENetworking/HPEIMCUtils/license`
  returning `{"spdx_id":"Apache-2.0"}`)
* Lines: **54** (very compact)
* Header: `; J9773A Configuration Editor; Created on release #YA.15.13.0003`
* Grammar surface: `hostname`, `include-credentials`, `password
  manager user-name "admin" sha1`, `ip route 0.0.0.0/0`,
  `interface N / name "..." / energy-efficient-ethernet`,
  `snmp-server community public/private`, `snmpv3 engineid`,
  `vlan 1 / name DEFAULT_VLAN / untagged 1-28 / ip address
  dhcp-bootp`, `vlan 10 / name VLAN10 / tagged 1-28 / ip address
  10.11.10.6/24`, `spanning-tree`, `no tftp server`, `no dhcp
  config-file-update`.  Real HPE iMC ZTP capture — first-party HPE
  reference.
* Sanitisation: **None needed** — already sanitised by HPE (canonical
  `admin/admin` sha1 hash, RFC1918 addresses, generic SNMP communities).
* Quality: High — first-party HPE-maintained, Apache-2.0, exercises
  the `Configuration Editor` header form + every basic stanza class.
  **YA-branch coverage gap closer.**

**[HPENetworking/HPEIMCUtils](https://github.com/HPENetworking/HPEIMCUtils)
— `ZeroTouchProvisioning/InitialConfigFiles/ArubaOS/2530/ArubaOSInitialConfig_Ignore.cfg`**
* Same repo / license / sanitisation.  Smaller (initial-ZTP variant).
* Header form differs: uses the `IGNORE` flag for cross-platform
  multi-model ZTP (a documented AOS-S feature on 25xx/26xx/2540).
* Worth pulling for the IGNORE-flag grammar coverage that 2530_Final
  doesn't exercise.

#### Forum / community posts (HPE Community — forum-share precedent)

**HPE Community thread 7000797 — "Understanding Running Config on
HP 2530"**
* URL: <https://community.hpe.com/t5/Aruba-ProVision-based/Understanding-Running-Config-on-HP-2530/td-p/7000797>
* License: Forum-share (operator-posted config for troubleshooting —
  same precedent as the four existing forum-share fixtures already
  in NOTICE.md).
* Header: `Created on release #YA.15.10.0003`
* Lines: ~12 (bare-bones — only hostname, SNTP, default-gateway,
  SNMP community, single VLAN-1 with full-port-assignment, web-mgmt
  SSL).  Skip unless we want a "minimum viable AOS-S" datapoint.
* Quality: Low-medium — too sparse for grammar enrichment.

**HPE Community thread 7132110 — "Aruba 2530 Tagged VLAN no network
connection"**
* URL: <https://community.hpe.com/t5/lan-routing/aruba-2530-tagged-vlan-no-network-connection/td-p/7132110>
* Header: `YA.16.10.0013` mentioned, but only partial
  `show vlan 2` output posted — no full running-config.
* Skip — not actually a running-config paste.

**HPE Community thread 7056378 — "Aruba 2530 is not accessible"**
* URL: <https://community.hpe.com/t5/Aruba-ProVision-based/Aruba-2530-is-not-accessible/td-p/7056378>
* Header: `Created on release #YA.16.07.0003`
* Lines: ~35-40
* Grammar: VLANs with tagged/untagged port assignments, IP routing
  (static default), SNMP community, spanning-tree, password manager,
  service disabling (`no tftp`, `no dhcp config-file-update`,
  `no auto-update`).  IPsec-tunnel-troubleshooting context (so
  represents a real ROBO-style 2530 deployment).
* Sanitisation: Light — replace public WAN IPs (already partly
  redacted by poster), confirm no PII in interface descriptions.
* Quality: **High** — best forum-share candidate for YA.16 branch.

**HPE Community thread 7080056 / 6909311 — 2530 firmware-update
threads**
* Multiple confirmed `Created on release` lines spotted:
  YA.16.04.0016 (J9774A), YA.16.04.0008 (J9773A), YA.16.03.0004
  (J9778A), YA.16.11.0001 (J9776A).  Quality varies by thread —
  worth spot-checking each for grammar density.

**HPE Community thread 7211952 — "LACP between HPE 6300M 24SFP+ and
HPE 2530"**
* URL: <https://community.hpe.com/t5/other-hpe-product-questions/lacp-between-hpe-6300m-24sfp-and-hpe-2530/td-p/7211952>
* Header: `Created on release #YA.16.04.0008`
* Lines: ~25
* Grammar: `trunk 23-24 trk1 lacp` LACP aggregation, `interface Trk1`
  with tagged-VLAN list, two VLANs (`DEFAULT_VLAN`, `DMZ`).
* Quality: Medium — LACP-on-2530 narrow but the codec doesn't have
  a 2530+trunk-tagged-on-Trk fixture yet.

#### Vendor docs / lab guides

**[HP Switch Software Management and Configuration Guide for
WB.15.16 / YA/YB.15.16](https://www.ordinoscope.net/images/3/39/ProCurve_2920_-_Management_and_Configuration_Guide_for_WB.15.16.pdf)**
* PDF copies of the 2015 mgmt guides — embedded `show running-config`
  examples scattered throughout (typically ~10-20 line snippets per
  command-class section).
* License: HPE-published doc, technically CC-BY-equivalent for
  example excerpts but copying many in bulk is grey-area.  Use
  individual snippets as grammar-reference, not bulk import.

#### Other (pastebin / YouTube / blogs / Internet Archive)

* Reddit `r/networking` + `r/HPE`: search returns no 2530 / YA
  running-config full pastes — operators post snippets only.
* `abouthpnetworking.com` — Hank Yeomans' blog (HPE switching SE).
  Has 16.x feature walkthroughs but no full configs.
* Internet Archive: no high-signal 2015-era 2530 captures found in
  spot-search.

### RA branch (2620 family — WANTED.md gap)

#### Forum / community posts (HPE Community — forum-share precedent)

**HPE Community thread 6051049 — "2620 Vlan question"**
* URL: <https://community.hpe.com/t5/Aruba-ProVision-based/2620-Vlan-question/td-p/6051049>
* License: Forum-share precedent
* Header: `Created on release #RA.15.10.0010`
* Lines: ~60
* Grammar: `interface N / name "To Switch1"` per-port descriptions
  (multiple interfaces), VLAN definitions with tagged/untagged
  comma-separated port specs (`untagged 1-44,46-52`, `tagged
  2,4,6,8...`), `ip address 10.1.1.1 255.255.0.0`, `ip routing`
  enabled, `ip helper-address` on multi-VLAN, DHCP snooping,
  `voice` VLAN, `qos priority 6`, `web-management ssl`.  Rich.
* Sanitisation: Light — IPs RFC1918, generic hostnames; verify
  no PII in port descriptions.
* Quality: **High** — best RA-branch candidate.  Closes RA gap.

**HPE Community thread 6774058 — "Error counters - 2620-48 Switches"**
* URL: <https://community.hpe.com/t5/hpe-aruba-networking-provision/error-counters-2620-48-switches/td-p/6774058>
* Header: `Created on release #RA.15.16.0005`
* Lines: ~20
* Grammar: VLAN configuration (single VLAN), default gateway, SNMP,
  hostname, SNTP, spanning-tree, loop-protection, port ranges 1-48,
  web-management disabled, telnet disabled.
* Quality: Medium — light grammar, but a second RA datapoint at a
  higher minor (15.16 vs 15.10).

#### GitHub repositories

* No standalone RA-branch real-capture finds in spot-check.  The
  HPENetworking/HPEIMCUtils repo does NOT include a 2620 folder
  (only 2530, 2920, 3500yl, 3800, 5400, 5400R) — consistent with
  the IGNORE-flag note in the readme that 2620 piggybacks on 2530
  via `IGNORE` instead of having its own template.

#### Out

* Reddit, Wayback, blogs: no useful RA-branch fixture-grade captures
  in spot-check.

### KA branch (5400zl gen-1 + 3800 — legacy)

#### GitHub repositories

**[HPENetworking/HPEIMCUtils](https://github.com/HPENetworking/HPEIMCUtils)
— `ZeroTouchProvisioning/InitialConfigFiles/ArubaOS/3800/3800_Final_Config.cfg`**
* URL: <https://raw.githubusercontent.com/HPENetworking/HPEIMCUtils/master/ZeroTouchProvisioning/InitialConfigFiles/ArubaOS/3800/3800_Final_Config.cfg>
* License: Apache-2.0 (same repo)
* Lines: **67**
* Header: (KA.16.x — verify against raw file; the sibling 5400
  config is KA.16.01.0004 so this is in the same train)
* Platform: 3800 stackable (BPS-capable, predecessor to 3810M)
* Grammar: similar shape to the 2530_Final but with **stack-aware
  port IDs** (slot/port form) and the 3800's BPS stacking stanza.
* Sanitisation: None needed.
* Quality: **High** — closes the KA-branch gap entirely.

**[HPENetworking/HPEIMCUtils](https://github.com/HPENetworking/HPEIMCUtils)
— `ZeroTouchProvisioning/InitialConfigFiles/ArubaOS/5400/5400_Final_Config.cfg`**
* URL: <https://raw.githubusercontent.com/HPENetworking/HPEIMCUtils/master/ZeroTouchProvisioning/InitialConfigFiles/ArubaOS/5400/5400_Final_Config.cfg>
* License: Apache-2.0
* Lines: **128** (densest of the HPEIMCUtils ArubaOS configs)
* Header: `; J9573A Configuration Editor; Created on release #KA.16.01.0004`
* Platform: 5406zl (8-slot gen-1 chassis, J9573A)
* Grammar: `module A type ... / module B type ...`, multi-module
  port refs across A/B slots, oobm with `ip address dhcp-bootp`,
  spanning-tree, sflow polling/sampling, ip-route, snmp + snmpv3,
  vlan with tagged/untagged across modules.  Real KA-train modular
  chassis grammar.
* Sanitisation: None needed.
* Quality: **High** — closes the KA gap AND second modular-chassis
  fixture (complements existing KB.15.15 5406Rzl2).

### KB branch (3810M + 5400R chassis class)

The existing corpus has one KB.15.15.x fixture for the 5406Rzl2.
Worth adding 3810M (the stackable / VSF-capable platform within KB)
and a more recent 16.x KB capture.

#### GitHub repositories

**[HPENetworking/HPEIMCUtils](https://github.com/HPENetworking/HPEIMCUtils)
— `ZeroTouchProvisioning/InitialConfigFiles/ArubaOS/5400R/5400R_Final_Config.cfg`**
* URL: <https://raw.githubusercontent.com/HPENetworking/HPEIMCUtils/master/ZeroTouchProvisioning/InitialConfigFiles/ArubaOS/5400R/5400R_Final_Config.cfg>
* License: Apache-2.0
* Lines: **71**
* Header: `; J9850A Configuration Editor; Created on release #KB.16.01.0007`
* Platform: 5406Rzl2 (same chassis class as existing KB.15.15 fixture,
  but on KB.16.01 instead of KB.15.15 — bridges the major-version gap)
* Grammar: 4 module declarations (`module A type j9536a / B type
  j9534a / C type one-06 / D type one-06`), oobm interface, sflow
  destination + multi-port polling/sampling, `ip route 0.0.0.0/0`,
  SNMPv1/v3 with engineid, hostname "HP-5406Rzl2", `include-credentials`
  + `password manager ... sha1`, A/B/Ci/Di port range notation.
* Sanitisation: None needed.
* Quality: **High** — closes the KB.16 gap (existing is 15.15 only).

#### Forum / community posts

**HPE Community thread 7095676 — "ARUBA 3800 pinging between VLAN's
blocked"**
* URL: <https://community.hpe.com/t5/Aruba-ProVision-based/ARUBA-3800-pinging-between-VLAN-s-blocked-in-one-direction-work/m-p/7095676>
* Header: `Created on release #KB.16.04.0008` (3810M)
* Lines: ~25 (partial — focused on two VLANs)
* Grammar: **VRRP** (`ip vrrp vrid` + `virtual-ip-address` +
  priorities) on VLAN SVIs.  Two VLANs (1001 + 1031), tagged/untagged
  ports, IP addressing on SVIs.
* Sanitisation: Light — IPs RFC1918, redact any device descriptions.
* Quality: **VERY high** — **first VRRP-on-AOS-S real-capture
  fixture-candidate**.  AOS-S VRRP wire-up is shipped in v0.2.0
  (commit `e542b49`) but `WANTED.md` § "VRRP / HSRP / anycast-gateway"
  notes the fixture is "still wanted" — this thread closes that gap.

**HPE Community thread 6999145 — "Hp ARUBA Switch Vlan Issue"
(5400)**
* URL: <https://community.hpe.com/t5/hpe-aruba-networking-provision/hp-aruba-switch-vlan-issue/td-p/6999145>
* Header: `Created on release #KB.16.02.0013`
* Lines: ~130
* Grammar: `module A type j9990a` declarations, trunk aggregation
  with both LACP + static (`trunk A1-A2 trk1 lacp`), VLAN definitions
  with untagged/tagged port specs across multiple modules (`A3-A20,
  B1-B20`), nested vlan blocks, IP w/ DHCP-bootp, NTP unicast,
  spanning-tree priority settings.
* Sanitisation: Light — operational, RFC1918.
* Quality: **High** — densest KB-branch forum-share candidate.

**HPE Community thread 6821198 — "help with ip phones on new system"**
* Header: `Created on release #KB.15.17.0008` (5400 modular)
* Light grammar, but a third distinct KB minor (15.15 + 15.17 + 16.01
  + 16.02 + 16.04 would give 5 distinct KB minors).

### WC branch (2930F / 2930M)

Existing corpus has WC.16.07, WC.16.10, WC.16.11.  Gap: WC.16.01-06,
WC.16.08, WC.16.09.  Lower priority since WC is already best-covered
branch.

#### Forum / community posts

* HPE Community has rich 2930F/2930M discussions tagged with WC.16.x
  — search pattern `site:community.hpe.com 2930F "Created on release"
  WC.16.0` is fruitful.  Spot-checked threads tend to be 30-80 line
  partials.  Skip unless a specific feature gap (OSPF, MSTP, MAC-auth)
  needs filling.

#### GitHub repositories

* No additional 2930F/2930M real-capture finds beyond the existing
  `aruba_central_5memberstack_rendered.cfg`.

### WB branch (2920)

Existing corpus has WB.16.08.  Gap: any 16.10 capture (WB's last GA
train) + any 15.x retrospective.

#### GitHub repositories

**[HPENetworking/HPEIMCUtils](https://github.com/HPENetworking/HPEIMCUtils)
— `ZeroTouchProvisioning/InitialConfigFiles/ArubaOS/2920/2920_Final_Config.cfg`**
* URL: <https://raw.githubusercontent.com/HPENetworking/HPEIMCUtils/master/ZeroTouchProvisioning/InitialConfigFiles/ArubaOS/2920/2920_Final_Config.cfg>
* License: Apache-2.0
* Lines: **86**
* Header: `; J9727A Configuration Editor; Created on release #WB.16.01.0004`
* Platform: 2920 (J9727A 48-port + module slot)
* Grammar: hostname "2920", `module 1 type j9727a`, `no rest-interface`,
  `include-credentials`, sha1 password hash, `ip route 0.0.0.0/0`,
  SNMP communities iMCread/iMCwrite/public/private with operator/
  unrestricted access classes (4 communities — denser than other
  fixtures), `snmp-server contact "kontrol.issues@gmail.com"`
  (sanitise to `netadmin@example.test` to match existing precedent
  in `hpe_community_2930f_wc1607_intervlan.cfg`), `snmpv3 engineid`,
  `oobm`, VLANs with tagged/untagged.
* Sanitisation: **Light** — replace the SNMP contact email + hostname,
  IPs already RFC1918.
* Quality: **High** — closes the WB.16.01 (early-WB-16 train) gap
  that the existing WB.16.08 fixture doesn't cover.

### Pre-16.x legacy (15.x retrospective)

The 15.x train was active 2014 - 2016 and many production switches
still run 15.18.x today (the recommended pre-16.x stable build).
Coverage gap: zero 15.x WB/WC fixtures (KB has 15.15 already, YA has
15.10/15.13 above).

#### Vendor docs

* **WB.15.16 mgmt guide** (`https://www.ordinoscope.net/images/3/39/ProCurve_2920_-_Management_and_Configuration_Guide_for_WB.15.16.pdf`)
  — embedded examples.  Use as grammar reference.
* **YA/YB.15.18.0006 release notes** (`https://studylib.net/doc/18289892/ya-yb.15.18.0006-release-notes`)
  — quotes `show running-config` snippets in the change-list
  section.

#### Forum

* HPE Community 6907ish threads ("ProCurve 2510/2620/2520
  retrospective") show 15.x configs occasionally but they're K.15.x
  / J.15.x (HP ProCurve branches before the AOS-S rename, distinct
  from the `aruba_aoss` codec's input shape — be careful not to
  ingest pre-AOS-S K/J/W single-letter branches that the codec
  doesn't target).

---

## Recommended pull priority order

1. **HPENetworking/HPEIMCUtils — 2530_Final_Config.cfg (YA.15.13)**.
   Apache-2.0, sanitised already, closes the YA-branch gap with
   minimal effort.  ~1 minute.
2. **HPENetworking/HPEIMCUtils — 5400_Final_Config.cfg (KA.16.01)**.
   Apache-2.0, sanitised already, closes KA-branch gap +
   second modular-chassis fixture.  ~1 minute.
3. **HPENetworking/HPEIMCUtils — 5400R_Final_Config.cfg (KB.16.01)**.
   Apache-2.0, sanitised already, closes the KB-16-train gap
   (existing is KB.15.15 only).  ~1 minute.
4. **HPENetworking/HPEIMCUtils — 3800_Final_Config.cfg (KA-train)**.
   Apache-2.0, second KA platform class (3800 stackable vs 5400zl
   chassis).  ~1 minute.
5. **HPENetworking/HPEIMCUtils — 2920_Final_Config.cfg (WB.16.01)**.
   Apache-2.0, sanitised already, closes WB-16.01-early gap
   (existing is WB.16.08).  ~1 minute, light sanitisation
   (SNMP contact email).
6. **HPE Community 7095676 — 3810M VRRP capture (KB.16.04)**.
   Forum-share precedent.  Closes the VRRP-on-AOS-S fixture gap
   noted in WANTED.md.  ~15-30 minutes (sanitise IPs + verify no
   PII).
7. **HPE Community 6051049 — 2620 VLAN config (RA.15.10)**.
   Forum-share precedent.  Closes the RA-branch gap.  ~15-30 minutes
   sanitisation.
8. **HPE Community 7056378 — 2530 YA.16.07 deployed config**.
   Forum-share precedent.  Adds a second-major YA datapoint and
   adds the IPsec-tunnel-context grammar.  ~15-30 minutes.
9. **HPE Community 6999145 — 5400 KB.16.02 dense config**.
   Forum-share precedent.  Adds a third KB-minor and the densest
   modular-chassis forum-share candidate.  ~15-30 minutes.

A pull of items 1-5 alone closes 4 of the 5 branch gaps (YA, KA, KB-16,
WB-16-early) with **5 minutes of effort and zero sanitisation** since
HPEIMCUtils is Apache-2.0 first-party HPE-published.  Items 6-9 add
forum-share captures that exercise denser real-world grammar (VRRP,
multi-VLAN, multi-module chassis).  **YC (2540) remains the only
fully-uncovered branch** after items 1-9 — see Out-of-scope below.

---

## Out-of-scope

* **YC branch (2540)** — search across HPE Community + airheads.hpe.com
  + GitHub returned no fixture-grade real-capture pastes.  The 2540
  is well-documented (mgmt guide, quick-setup PDFs, marketing
  data-sheets) but operators don't seem to post 2540 running-configs
  for troubleshooting at the rate they post 2530/2920/2930F.  Possibly
  because 2540 is the entry-level "Aruba-Central-managed" switch
  and operators using it don't typically need CLI-paste forum support.
  **Resolution**: solicit a user-contributed 2540 capture (same
  pathway as the existing `user_contrib_2930m_wc1611.cfg`).
* **Aruba 8400 chassis** — this is **AOS-CX, not AOS-S**.  The
  WANTED.md "8400 chassis class" note is a doc typo.  Re-target to
  [`11-aruba_aoscx.md`](11-aruba_aoscx.md).  No AOS-S branch was ever
  cut for the 8400.
* **Pre-AOS-S ProCurve K/J/S/T/U/W single-letter branches** (e.g.
  `K.15.12.0012` on 8212zl from HPE Community 6682287).  These are
  the pre-`Aruba`-rebrand ProCurve trains and **the `aruba_aoss`
  codec doesn't target them** — the Configuration Editor header
  syntax was the same but the underlying grammar diverges in
  pre-15.16 idioms (`oobm` semantics, pre-VSF stacking).  Exclude
  unless a future `aruba_provision_legacy` codec ships.
* **AOS-S in Aruba Central** managed-config templates with `%variable%`
  interpolation — already represented by the rendered fixture;
  ingesting more would just exercise the renderer, not the codec.
* **Aruba Mobility Controller / Aruba Instant configs** — these
  are **AOS-Mobility (controller-class)** and **AOS-Instant
  (AP-class)** — separate OS families, separate codecs, separate
  catalogues (neither planned in v0.1.1 or v0.2.0).
* **HP / Aruba support paywalled material** (CCNA / ACNP / ACAP
  cert-prep workbooks, Aruba EDU on-demand courses) — copyright
  is real, use only as grammar inspiration.
* **`tempestcha/HP-Aruba-Procurve`** — repo has no fixtures, only
  a Python config-pull script.  License declared as `null`.
  Mentioned for completeness, not as a pull-target.

---

## See also

* [`00-source-analysis.md`](00-source-analysis.md) — source-type
  taxonomy referenced throughout
* [`README.md`](README.md) — folder index
* [`tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md)
  — existing fixtures and provenance (corpus section `aruba_aoss/`)
* [`tests/fixtures/real/WANTED.md`](../../tests/fixtures/real/WANTED.md)
  — operator-facing fixture gap list (the named "YA / RA software
  branches" + "8400 chassis class" gaps that this catalogue addresses /
  re-scopes)
* [`tests/fixtures/real/aruba_aoss/README.md`](../../tests/fixtures/real/aruba_aoss/README.md)
  — corpus-folder "do better later" note about the Aruba Central
  rendered template, recommending swap to real captures
* [`11-aruba_aoscx.md`](11-aruba_aoscx.md) — Aruba AOS-CX (where the
  8400 chassis class actually belongs)
* [`BUG_REPORTING.md`](../../BUG_REPORTING.md) — sanitisation and
  fixture-submission workflow
* [`docs/v0.2.0-planning/01-vrrp-canonical/IMPLEMENTED.md`](../v0.2.0-planning/01-vrrp-canonical/IMPLEMENTED.md)
  — AOS-S VRRP wire-up; HPE Community 7095676 (KB.16.04 3810M VRRP
  capture) closes the open "fixture still wanted" gap noted there

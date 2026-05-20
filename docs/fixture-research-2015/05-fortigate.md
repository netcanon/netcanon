# Fortinet FortiOS — fixture catalogue (2015+)

> **Tier**: Shipped
> **Codec**: `fortigate_cli`
> **Existing corpus**: 3 fixtures (FortiOS 7.2.13 + 7.6.6 + 7.6.6) —
> see [`tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md)
> `fortigate/` section.

FortiGate config grammar is `config <section> / edit <key> / set <attr>
<val> / next / end` — nested, position-significant, and verbose.  Full
`show full-configuration` outputs on a modestly-featured physical
FortiGate routinely exceed **10,000 lines**; the existing FG100E fixture
(`user_contrib_fg100e_fos7213.conf`) is 35K+ lines.  This means every
real-capture entry below has a length signal — short snippets (1-3K
lines) cover a slice; full backups (10K+) exercise the parser's
silently-carried-past tolerance for unmodelled sections (UTM profiles,
FortiGuard categories, internet-service tables).  Mark length carefully
during fixture import.

[`WANTED.md`](../../tests/fixtures/real/WANTED.md) gap callout:
**6.4.x; 7.0.x / 7.4.x bridge versions; SD-WAN multi-link with
health-check; IPsec-heavy** (multiple `phase1-interface` /
`phase2-interface` stanzas).

---

## Version timeline

Dates per [endoflife.date/fortios](https://endoflife.date/fortios) and
Fortinet Product Lifecycle pages.  EoEngS = end of engineering support
(no new bug fixes); EoS = end of support (no security patches).

| Major | First release | EoEngS | EoS | Notable platforms | In corpus? | Priority |
|---|---|---|---|---|---|---|
| 5.0 / 5.2 / 5.4 / 5.6 | 2013-2017 | past | past (5.6 EoS Sep 2020) | FG-60D / 90D / 100D / 200D / 300D / 1500D / 3000D / 3700D / VM | No | Low (legacy retrospective only) |
| 6.0 | 29 Mar 2018 | 29 Mar 2021 | 29 Sep 2022 | All FG-* + VM | No | Medium (historical bridge) |
| 6.2 | 28 Mar 2019 | 28 Mar 2022 | 28 Sep 2023 | All FG-* + VM | No | Medium (still seen on long-cycle deployments) |
| 6.4 | 31 Mar 2020 | 31 Mar 2023 | 30 Sep 2024 | FG-40F / 60F / 100E / 200F / VM | No | **High — WANTED.md gap, still common in SMB** |
| 7.0 | 30 Mar 2021 | 30 Mar 2024 | 30 Sep 2025 | FG-40F / 60F / 100F / 200F / 600F / VM | No | **High — WANTED.md LTS bridge gap** |
| 7.2 | 31 Mar 2022 | 31 Mar 2025 | 30 Sep 2026 | FG-40F / 60F / 100E (legacy) / 100F / 200F / 400F / 600F / VM | 7.2.13 (1 fixture) | Medium (have minimal coverage) |
| 7.4 | 11 May 2023 | 11 May 2027 | 11 Nov 2028 | FG-40F / 60F / 70G / 91G / 100F / 200F / 600F / 1100E / 3001F / VM | No | **High — WANTED.md current GA bridge gap** |
| 7.6 | 25 Jul 2024 | 25 Jul 2028 | 25 Jan 2030 | FG-40F / 60F / 70G / 100F / VM (current) | 7.6.6 (2 fixtures) | Medium (decent coverage; broaden platforms) |
| 8.0 | 21 Apr 2026 | 21 Apr 2029 | 21 Oct 2030 | Current GA (post-cutoff) | No | Future (out of 2015-cutoff scope for catalogue but worth tracking) |

Maintenance releases over the 10-year window: each major typically saw
8-15 sub-versions (e.g., 6.4 went from 6.4.0 to 6.4.15; 7.0 went 7.0.0
to 7.0.17; 7.2 went 7.2.0 to 7.2.13).  Grammar evolution within a major
is light (mostly new `set` attributes in existing stanzas + occasional
new `config` sections like 7.4.0's `config system standalone-cluster`);
across majors it's more substantial (SD-WAN reshape in 6.4 → 7.0; SSL
VPN deprecation hints in 7.4 → 7.6; HA-config grammar churn 7.2 → 7.4).

---

## Existing corpus coverage

| File | OS version | Platform | Lines | Stresses |
|---|---|---|---|---|
| `kevinguenay_fgt_70g_branch.conf` | 7.6.6 | FG-70G branch | 12,317 | ZTP branch, SD-WAN, IPsec, FortiLink aggregate, VLAN subifs, BGP loopback, firewall policies, VIPs |
| `kevinguenay_fgt_vm_hub.conf` | 7.6.6 | VM-hub | 13,827 | ZTP hub-side counterpart to above; same 7.6.6 major (intra-version pair) |
| `user_contrib_fg100e_fos7213.conf` | 7.2.13 | Physical FG-100E | 35K+ | First physical FG capture: 34 ifaces, 5 VLAN subifs, 2 LAGs, 6 DHCP servers, RADIUS, SNMP, full firewall policy table, SDWAN health-check, IPsec, SSL-VPN portal, FortiGuard categories |

**Coverage shape**: the existing fixtures already exercise SD-WAN +
firewall-policy + interface/VLAN grammar densely; what they DON'T
exercise:

* No 6.4.x or older — every fixture is on 7.x
* No 7.0.x or 7.4.x bridge — jump from 7.2.13 to 7.6.6
* SSL-VPN portal is present (FG100E) but no IPsec-heavy capture with
  10+ `phase1-interface` / `phase2-interface` pairs (multi-site VPN
  concentrator pattern)
* No HA-cluster fixture (`config system ha` is in FG100E but lone-unit
  shape; no companion device + heartbeat-interface pair)
* No 5.x / 6.x retrospective — useful for grammar evolution audits
* No VDOM-multi-tenant capture (`config vdom / edit X / config system
  interface`) — multi-VDOM is a distinct grammar surface that the
  current parser tolerates (silently carries past `config vdom`) but
  doesn't model

---

## Pull-target inventory

Cross-referenced against the source taxonomy in
[`00-source-analysis.md`](00-source-analysis.md).  Most high-value
FortiGate sources are **Tier 1.1 (GitHub repos with explicit licenses)**
and **Tier 1.3 (lab platforms)**.  Forum sources (Tier 2.1
community.fortinet.com + Tier 2.2 r/fortinet) are richer for snippets
but rare for full backups.

### 7.4.x (current GA bridge — WANTED.md gap)

#### GitHub repositories

* **[`fortinet/4D-Demo`](https://github.com/fortinet/4D-Demo) — MIT,
  Fortinet's own org** — most valuable single source.
  85 stars, Fortinet-maintained.
  Contains `4D-SDWAN/7.4/Dual hub/Branches/dual_hub_Branch{1,2}_base.txt`
  (~13K bytes each, ~250-300 lines) + `4D-SDWAN/7.4/Dual hub/Hub/
  dual_hub_HUB{1,2}_base_74.txt` (~7K bytes each, ~150 lines).
  Plus extension folders (`Extensions/ADVPN`, `Extensions/Adaptive FEC`)
  with 1-2K-byte snippet configs layering features on the base.
  Stresses: SD-WAN dual-hub overlay, BGP route-steering, ADVPN, IPsec
  phase1/phase2 pair × 2-4 tunnels per branch.
  Grammar surface: `config system interface`, `config vpn ipsec
  phase1-interface / phase2-interface`, `config router bgp`,
  `config system sdwan`, `config firewall policy`,
  `config firewall address`.
  Sanitisation: minimal — already lab-grade; uses RFC1918 + reserved
  documentation IPs.
* **[`batfish/lab-validation`](https://github.com/batfish/lab-validation)
  — Apache-2.0** — already a heavy source for our IOS-XE / Junos /
  EOS / Aruba fixtures.
  `snapshots/fortios_first_basic/configs/d2_fw/show.txt` and
  `snapshots/fortios_fw_policy_basic/configs/fw/show.txt` —
  **280 KB each**, dense full `show` captures from Batfish's FortiOS
  validation framework.  Sampled header confirms **FortiOS 6.4.4 on
  FortiGate-VM64-KVM** (NOT 7.4 — caveat below) but the snapshot
  shape exercises the full carrier-config surface including
  internet-service-name (500+ entries) which lone hand-crafted
  configs never include.  See "6.4.x" section below for the actual
  version-binding.
* **[`ytti/oxidized`](https://github.com/ytti/oxidized) — Apache-2.0,
  3,380 stars** — 5 small FortiGate test fixtures under
  `spec/model/data/`:
  * `fortigate#FortiGate-3001F_7.4.8_HA#output.txt` (2,530 bytes) —
    7.4.8 on chassis-class FG-3001F with HA
  * `fortigate#FortiGate-91G_7.4.7#output.txt` (4,030 bytes) —
    7.4.7 on FG-91G + companion `secret.yaml` + `significant_changes.yaml`
    metadata files
  * `fortigate#FortiGate-91G_7.4.7_autoupdate#custom_output.txt`
    (1,653 bytes) — variant with auto-update enabled
  * `fortigate#FortiGate-501E_vdomHAdown#output.txt` (2,755 bytes) —
    legacy FG-501E with multi-VDOM + HA failure mode (great for VDOM
    parser stress)
  * `fortios#FMG-VM64_7.4.6#output.txt` (2,843 bytes) — FortiManager
    7.4.6 (cousin product; not strictly FortiGate but uses same
    grammar — useful for FMG-style canary)
  These are tool-generated prompt-simulation fixtures (oxidized tests
  its CLI prompt detection), so they're snippets not full configs;
  but the version-binding + HA-shape + VDOM-shape make them high-
  signal fixtures for cross-version grammar evolution.
  Sanitisation: already lab-grade (no real IPs / hashes).

#### Forum / community posts

* **[community.fortinet.com](https://community.fortinet.com/)** —
  numerous troubleshooting threads include 7.4.x partial configs.
  High-value pattern: search for `"config vpn ipsec phase1-interface"`
  + `"7.4"` + `troubleshooting` filter.  Forum-share precedent applies
  (per existing HPE Community pulls).  Examples surfaced during
  research:
  * [Troubleshooting Tip: VPN IPsec VPN tunnel phase2 unstable after
    upgrading to v7.4.2](https://community.fortinet.com/t5/FortiGate/Troubleshooting-Tip-VPN-IPsec-VPN-tunnel-phase2-unstable-after/ta-p/305036)
    — phase2 grammar diff 7.2 → 7.4
  * [Technical Tip: Configure IPsec VPN with SD-WAN](https://community.fortinet.com/t5/FortiGate/Technical-Tip-Configure-IPsec-VPN-with-SD-WAN/ta-p/209840)
    — official tech-tip with multi-section snippets
* **[reddit.com/r/fortinet](https://www.reddit.com/r/fortinet/)** —
  smaller signal; mostly support-question shape with abbreviated
  configs.  Reddit forum-share precedent + CC-BY-SA-compatible default
  Reddit ToS.

#### Vendor docs / lab guides

* **[Fortinet Document Library](https://docs.fortinet.com)** — the
  per-version cookbook + administration guide examples are linked
  from every `phase1-interface` doc page.  These are short (2-15
  lines per example) but very high-quality and authoritative.
  License: Fortinet "documentation example" use is permissive
  per existing 4D-Demo MIT licensing of derived works.
* **[blog.boll.ch](https://blog.boll.ch)** ("Tech Blog" by Andreas Boll)
  — operator-published per-version "first config steps" guides:
  * [FortiGate with FortiOS 7.4: First Configuration
    Steps](https://blog.boll.ch/fortigate-with-fortios-7-4-first-configuration-steps/)
  * [Cheat Sheet — General FortiGate for FortiOS 7.4 v1.2](https://blog.boll.ch/wp-content/uploads/2023/11/CheatSheet-FortiOS-7.4-v1.2-1.pdf)
  Blog-share precedent applies (inspiration only, treat as synthetic
  rewrite).

#### Other

* **[`hyundonk/azure-terraform-fortigate-module`](https://github.com/hyundonk/azure-terraform-fortigate-module)**
  `firewall/config.txt` — Terraform-emitted FortiGate config (likely
  7.2 / 7.4 era).  License field None on repo — needs explicit license
  resolution before import.

---

### 7.0.x (LTS bridge — WANTED.md gap)

#### GitHub repositories

* **[`fortinet/4D-Demo`](https://github.com/fortinet/4D-Demo) — MIT** —
  same repo as 7.4 entry.  `4D-SDWAN/7.0/` folder contains the most
  comprehensive 7.0 SD-WAN coverage:
  * `Single hub/Branches/single_hub_Branch{1,2}_SD-WAN_Overlay.txt`
    (~5K bytes each, ~120-150 lines) — full single-hub branch config
    with 6-7 sections (`firewall address`, `vpn ipsec phase1/2-interface`,
    `system interface`, `router bgp`, `system sdwan`, `firewall policy`)
  * `Single hub/Hub/single_hub_HUB1_SD-WAN_Overlay.txt` (~4.6K) —
    hub-side companion
  * `Dual hub/Branches/dual_hub_Branch{1,2}_SD-WAN_Overlay.txt` (~7.7K
    each, ~180 lines) — dual-hub variant with 2 phase1+phase2 tunnel
    pairs per branch
  * `Dual hub/Hub/dual_hub_HUB{1,2}_SD-WAN_Overlay.txt` (~4.6K each)
  * Plus extension folders: ADVPN, Adaptive FEC, BGP Route Steering,
    SaaS Remote Internet Breakout — each adds 0.5-2K of additional
    grammar layered on the base config
  * `Standalone SD-WAN/standalone_Branch_SD-WAN.txt` — single-WAN
    variant with no hub
* **[`codedByJana/Implementing-VPN-Solutions-with-FortiGate`](https://github.com/codedByJana/Implementing-VPN-Solutions-with-FortiGate)
  — license None** — confirmed **FortiOS 7.0.17** capture
  (`FGVMK6-7.0.17-FW-build0682-250113`), FortiGate-VM64-KVM, >4K
  lines.  Header + multi-thousand-line internet-service-name table.
  Caveat: NO declared license; if pursued, contributor would need to
  contact owner.  Worth tracking as discovery signal but not
  pull-ready.
* **[`Azure/Azure-vpn-config-samples`](https://github.com/Azure/Azure-vpn-config-samples)
  — license None, Microsoft-owned** — `Fortinet/Current/
  fortigate_show full-configuration.txt` (328K bytes, 10,685 lines).
  Confirmed FortiOS 5.04 capture on FG100D (NOT 7.0 — see 5.x
  retrospective).  Mentioned here because the *Current* folder name is
  misleading; the file is legacy.
* **[`20eung/fortios-multi-vdom`](https://github.com/20eung/fortios-multi-vdom)
  — license None** — `fortios/5-site-b-fortigate-vdom-ussite-config.txt`
  — FortiGate VDOM-to-VDOM IPsec VPN configuration.  Multi-VDOM
  grammar surface (the existing FG100E corpus has single-VDOM).
  License None — discovery-only.

#### Forum / community posts

* **[community.fortinet.com](https://community.fortinet.com/)** —
  same source class as 7.4.x; many tech-tips reference 7.0.12 — 7.0.17
  for IPsec / SD-WAN / SSL-VPN.  Operator-paste shape covers gaps
  not in lab repos (e.g., dial-up IPsec with multiple peers).

#### Vendor docs / lab guides

* **[FortiOS 7.0.0 Administration Guide — IPsec
  VPNs](https://docs.fortinet.com/document/fortigate/7.0.0/administration-guide/520377/ipsec-vpns)**
  — official phase1-interface / phase2-interface examples.
* **[fortinetguru.com](https://www.fortinetguru.com)** — operator blog;
  multiple per-version cookbook reprints.

#### Other

* **[`fortinet/sdwan-thirdparty-integrations`](https://github.com/fortinet/sdwan-thirdparty-integrations)**
  — Fortinet org repo with NetSkope / Skyhigh / Zscaler IPsec
  templates.  License check needed.  Useful for grammar-surface
  expansion (third-party SD-WAN-integration shape).

---

### 7.6.x (most current — corpus already has 2 fixtures)

Corpus already has 2 FortiOS 7.6.6 fixtures from KevinGuenay
(`fortinet-resources` MIT).  Additional 7.6 sources for grammar
breadth + platform-class expansion:

* **[`fortinet/4D-Demo`](https://github.com/fortinet/4D-Demo) — MIT** —
  `4D-SDWAN/7.6/` is the most current SD-WAN reference.  Includes:
  * `Dual hub/Branches/dual_hub_Branch{1,2}_base_76.txt` (~12.5K each,
    ~240 lines)
  * `Dual hub/Hub/dual_hub_HUB{1,2}_base_76.txt` (~5.6K each)
  * `Single hub/Branches/single_hub_Branch{1,2}_SD-WAN_Overlay.txt`
    (~10.5K each)
  * `Single hub/Hub/HUB1.conf` (~6.7K) — note `.conf` extension here
    (others are `.txt`)
  * `HA/HighAvailability.txt` — **HA-pair config** (currently missing
    from corpus — `config system ha` shape with `set group-name`,
    `set group-id`, `set priority`, `set hbdev`, `set monitor`)
  * `SD-Branch/7.6/Single Hub/SD-Branch_BRANCH_2.txt` +
    `SD-Branch_HUB.txt` — SD-Branch (FortiGate + FortiSwitch
    integration) — exercises `config switch-controller` grammar that
    the existing corpus doesn't have
* **[`KevinGuenay/fortinet-resources`](https://github.com/KevinGuenay/fortinet-resources)
  — MIT** — already a source; the `blog_resources/fortigate_ztp/
  fortigate_configurations/` folder has the two existing
  fixtures.  No additional 7.6 captures in that repo at last check.

---

### 7.2.x (corpus has 7.2.13)

The FG100E user-contrib fixture covers 7.2.13 densely.  Additional
sources for grammar breadth on different platforms:

* **[`fortinet/4D-Demo`](https://github.com/fortinet/4D-Demo) — MIT** —
  the 4D-Demo repo has 7.0, 7.4, 7.6 folders but **no 7.2 folder**.
  This is a real gap in upstream Fortinet examples for 7.2.
* **[community.fortinet.com](https://community.fortinet.com/)** —
  most active for 7.2 since it overlaps with the longest 2022-2024
  deployment window.  Forum-share captures available across 7.2.0 →
  7.2.13.
* **[`leandropinheiro/FORTIGATE-HANDSON`](https://github.com/leandropinheiro/FORTIGATE-HANDSON)
  — CC-BY-SA-4.0** — caveat: `desc: Treinamento Hands On sobre
  Fortigate v6.0.2` (Portuguese / Brazilian operator-instructor
  training material).  Actually confirmed FortiOS **6.0.2**, NOT 7.2;
  retained in the 6.x section below.

---

### 6.4.x (still common SMB — WANTED.md gap)

#### GitHub repositories

* **[`batfish/lab-validation`](https://github.com/batfish/lab-validation)
  — Apache-2.0** — the **highest-value 6.4 pull** because batfish
  treats FortiOS as a first-class parser target.  Two snapshots:
  * `snapshots/fortios_first_basic/configs/d2_fw/show.txt`
    (280,122 bytes / ~3,500+ lines) — confirmed FortiOS 6.4.4 on
    FortiGate-VM64-KVM, includes the heavy internet-service-name
    table that the existing 7.x fixtures don't fully exercise (~500
    entries)
  * `snapshots/fortios_fw_policy_basic/configs/fw/show.txt`
    (280,122 bytes / ~3,500+ lines) — same OS major, different policy
    focus (firewall policy emphasis)
  License-compatible, lab-grade sanitisation already done, batfish's
  own parser already round-trips it (confirming the bytes are
  representative).  **Pull these first** for 6.4 coverage.
* **[`AbdulrhmanSobhyHanafy/Campus_Network`](https://github.com/AbdulrhmanSobhyHanafy/Campus_Network)
  — license None** — `Firewall configuration/FortiGate-VM64-KVM_6-4_
  1911_202411230908.conf.txt` — confirmed 6.4 vintage but no declared
  license (academic graduation project).  Discovery-only.
* **[`davidaulicino17/Laboratory_PNETLAB`](https://github.com/davidaulicino17/Laboratory_PNETLAB)
  — license None** — `LAB_Integrazione_Brownfield-Greenfield_con_DCI_
  VXLAN/Configs/Building-A/FGT-A.txt` — confirmed **FortiOS 6.4.3 on
  FortiGate-VM64-KVM**, lab context (Italian PNETLAB exercise).
  License None — discovery-only.

#### Forum / community posts

* **[community.fortinet.com](https://community.fortinet.com/)** —
  6.4.x is the longest-tail forum-paste source because it's still in
  production at SMBs and the LTS-style 6.4 community knowledge base
  is mature.  Forum-share precedent applies.

#### Vendor docs / lab guides

* **[FortiOS 6.4 Cookbook
  (docs.fortinet.com)](https://docs.fortinet.com/document/fortigate/6.4.0/)**
  — vendor-published 6.4 IPsec / SD-WAN / firewall-policy examples.

---

### 6.0 / 6.2 retrospective

The 6.x train introduced the first proper SD-WAN grammar (`config
system virtual-wan-link` → renamed `config system sdwan` in 6.4) — so
6.0/6.2 captures specifically exercise the *legacy* SD-WAN syntax that
the current codec parses-and-ignores or partial-models.  Useful for
backward-compat validation.

* **[`leandropinheiro/FORTIGATE-HANDSON`](https://github.com/leandropinheiro/FORTIGATE-HANDSON)
  — CC-BY-SA-4.0** — confirmed FortiOS **6.0.2** capture
  (`#config-version=FGVMK6-6.0.2-FW-build0163-180725`).  Two files:
  `LAB01/FINAL_SCRTIPS/FG_A.txt` + `FG_B.txt`.  Each is a complete
  config export (PuTTY terminal log captured 2018-08-28) covering
  system + firewall + vpn (3 phase1-interface + 3 phase2-interface
  including SITE_A-to-B-W1, SITE_A-to-B-W2, CLIENTVPN) + webfilter +
  application controls + antivirus + IPS sensors + user management.
  **No BGP** but rich IPsec + dual-WAN structure.
  License: CC-BY-SA-4.0 — compatible with our permissive pool with
  proper attribution; the share-alike clause means derived fixture
  must also be CC-BY-SA-4.0 — acceptable since fixtures are
  redistributable verbatim with the upstream license preserved.
  **The most attractive 6.x retrospective pull-target.**
* **[community.fortinet.com](https://community.fortinet.com/)** —
  archive search for 2018-2020 era posts.  Many threads from that
  window are still live.

---

### 5.x retrospective (legacy)

The 5.x train pre-dates SD-WAN-as-feature and runs the pre-modern
`config system interface` grammar; aggregate interface (`config system
virtual-switch` on lower-end hardware vs `config system aggregate-
interface` on higher-end) had different shape than today.  Captures
here are for grammar-evolution audit only.

* **[`Azure/Azure-vpn-config-samples`](https://github.com/Azure/Azure-vpn-config-samples)
  — license None, Microsoft-owned** —
  * `Fortinet/Current/fortigate_show full-configuration.txt` —
    328,775 bytes / 10,685 lines.  Confirmed FortiOS **5.04** (build
    1064) on FG100D physical hardware.  Despite the folder name
    "Current", this is the legacy capture.  Sections include 16-port
    LAN switch (`config system virtual-switch`), Site2Site IPsec
    tunnel, SSL VPN.  **License None on Azure-vpn-config-samples**
    — Microsoft hasn't declared one; informational pull only, not
    importable as fixture without rights-clearance via Microsoft
    legal.
  * `Fortinet/Older/Route_Based_FortiGate_v5.4.docx` — Word document
    with route-based VPN config for FortiOS 5.4.  Docx wrapper makes
    extraction lossy; not a direct text-fixture candidate.
* **Internet Archive Wayback Machine** — pre-2020 fortinetguru.com /
  yurisk.info / blog captures of 5.x configs (Tier 3.4).  Useful for
  cross-checking but not direct import (treat as synthetic-rewrite
  inspiration per source-analysis Tier 2.4).
* **[`tanvir410/ants_dashboard`](https://github.com/tanvir410/ants_dashboard)**
  `assets/snapshot_holder/configs/Fortinet-Fortigate 40+ Series-
  FortiOS 5.0+-ikev1.txt` + `...FortiOS 4.0+-ikev1.txt` — IKEv1
  legacy IPsec snippets for 5.0 / 4.0.  License None — discovery-only.

---

### IPsec-heavy captures (WANTED.md specific gap)

The WANTED.md callout asks for **multi-tunnel IPsec configurations**
(10+ `phase1-interface` / `phase2-interface` stanzas).  None of the
existing 3 fixtures hit this — they each have 1-3 tunnels.

* **[`fortinet/4D-Demo`](https://github.com/fortinet/4D-Demo) — MIT**
  Dual hub variants at 7.0 + 7.4 + 7.6 each have 2 phase1-interface +
  2 phase2-interface per branch (one to each hub).  Across all 4
  branch/hub configs in a single deployment that totals 8+ tunnel
  pairs — close to the WANTED bar.
* **[`fortinet/sdwan-thirdparty-integrations`](https://github.com/fortinet/sdwan-thirdparty-integrations)**
  — NetSkope + SkyHigh + Zscaler integration templates.  Each has
  3-4 tunnels for cloud-security vendor redundancy.  License unclear.
* **VPN-concentrator captures (community.fortinet.com)** — search
  pattern: `site:community.fortinet.com "config vpn ipsec phase1-
  interface" "edit" 10+` finds threads where operators paste configs
  with 10-20 tunnels for hub-and-spoke topologies.  Forum-share +
  heavy sanitisation required.
* **[`KevinGuenay/fortinet-resources`](https://github.com/KevinGuenay/fortinet-resources)
  — MIT** — the existing 70G branch fixture has SD-WAN with multiple
  IPsec; the VM hub variant has more.  Re-examination of these two
  files might surface an IPsec-heavy slice we haven't fully canonical-
  ised yet (no need for new fixture if a re-extraction of existing
  bytes works).

---

### HA-pair captures (corpus gap)

The existing FG100E fixture has `config system ha` but lone-unit
shape (the partner FG wasn't captured).  A real HA pair = two
companion configs from the active + standby unit.

* **[`fortinet/4D-Demo`](https://github.com/fortinet/4D-Demo) — MIT**
  `4D-SDWAN/7.6/HA/HighAvailability.txt` (~374 bytes — short snippet)
  + `HA/Standalone_topology.png` — short example, useful for grammar
  shape but not a full HA-pair capture.
* **[`ytti/oxidized`](https://github.com/ytti/oxidized) — Apache-2.0**
  `fortigate#FortiGate-3001F_7.4.8_HA#output.txt` + companion
  `simulation.yaml` — 7.4.8 chassis-class HA capture; 2,530 bytes is
  short but version + platform are signal.

---

## Recommended pull priority order

Ranked by fixture-corpus impact ÷ acquisition cost:

1. **batfish/lab-validation `fortios_first_basic` + `fortios_fw_policy_basic`**
   (Apache-2.0).  Two 280 KB FortiOS 6.4.4 captures.  Closes the
   6.4.x WANTED gap with one pull.  Source already gives us 5+ other
   vendor fixtures so the rights-clearance path is well-trodden.
   **Highest single-pull value.**

2. **fortinet/4D-Demo `4D-SDWAN/7.0/Single hub/`** (MIT, Fortinet org).
   Pull `single_hub_Branch1_SD-WAN_Overlay.txt` + companion HUB1 +
   one extension (BGP route steering or ADVPN).  Closes the 7.0.x
   WANTED gap with multi-section coverage (7 stanza types per file)
   and adds Fortinet-org-MIT provenance pattern.

3. **fortinet/4D-Demo `4D-SDWAN/7.4/Dual hub/`** (MIT).  Closes 7.4.x
   WANTED gap.  Dual-hub variant gives 2 phase1/phase2 pairs per
   branch — partial IPsec-heavy coverage.

4. **leandropinheiro/FORTIGATE-HANDSON `FG_A.txt`** (CC-BY-SA-4.0).
   FortiOS 6.0.2 retrospective with IPsec-heavy + dual-WAN + extensive
   UTM profile coverage (webfilter / antivirus / IPS sensors).  Adds
   6.x grammar evolution data point + CC-BY-SA precedent (new license
   class for the corpus — only fixture so far is permissive vendor
   doc / community-share / CC0 user-contrib).  Verify attribution
   workflow before import.

5. **fortinet/4D-Demo `4D-SDWAN/7.6/HA/`** + **oxidized
   `fortigate#FortiGate-3001F_7.4.8_HA#*`** (MIT + Apache-2.0).
   Two HA-related snippets to close the HA-pair grammar gap.  Light
   weight (combined < 5 KB) but signal-dense.

6. **fortinet/4D-Demo `SD-Branch/7.6/`** (MIT).  Adds `config switch-
   controller` grammar surface (FortiGate-as-controller for FortiSwitch
   stack).  Adjacent to but distinct from main firewall grammar.

7. **oxidized `fortigate#FortiGate-501E_vdomHAdown#output.txt`**
   (Apache-2.0).  Adds multi-VDOM grammar even though it's the
   "VDOM-HA-down" failure state.  ~2.7 KB.

8. **community.fortinet.com forum-share captures** for IPsec-
   concentrator patterns (10+ tunnel pairs).  Heavy sanitisation
   required.  Lowest cost/value ratio because forum captures need
   IP/hash/MAC sanitisation that the GitHub-sourced fixtures already
   have.

9. **Internet Archive Wayback Machine** — 5.x retrospective only,
   archive lookups for fortinetguru.com / yurisk.info posts pre-2020.
   Very low priority; treat as inspiration for synthetic 5.x grammar
   tests rather than direct import.

---

## Out-of-scope (deliberately excluded)

* **Vendor demo accounts (FortiCloud sandbox, FortiPoC)** — login-gated
  and ToS-restricted.  Tier 4 per source-analysis.
* **Customer-deployed configs from consulting** — explicitly excluded
  per `BUG_REPORTING.md`.
* **Closed-source / paid training material** (CBT Nuggets / INE
  FortiGate workbooks, Fortinet NSE training labs) — copyright in
  force; Tier 3.2 inspiration-only.
* **Azure-vpn-config-samples `Fortinet/Current/`** — large 5.04
  capture but **NO declared license** on the Microsoft-owned repo.
  Worth knowing exists; not importable without legal clearance.
* **`AbdulrhmanSobhyHanafy/Campus_Network`, `davidaulicino17/
  Laboratory_PNETLAB`, `codedByJana/Implementing-VPN-Solutions-with-
  FortiGate`** — confirmed-version useful captures but all on repos
  with no declared license.  Discovery-only.
* **FortiOS 8.0** — released April 2026, post-cutoff for this
  catalogue's 2015-current window.  Worth a separate v0.3.0 catalogue
  pass once FortiOS 8 maintenance releases stabilise.
* **`config vdom` multi-tenant deep-dive** — modeled by the codec as
  parse-and-ignore today.  Useful captures exist (oxidized 501E,
  20eung/fortios-multi-vdom) but pursuing them is a v0.2.0+ canonical-
  model task rather than a v0.1.x fixture-fill task.

---

## See also

* [`00-source-analysis.md`](00-source-analysis.md) — source-type
  taxonomy
* [`README.md`](README.md) — per-OS folder index
* [`tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md)
  — fortigate/ section: existing 3 fixtures + provenance
* [`tests/fixtures/real/WANTED.md`](../../tests/fixtures/real/WANTED.md)
  — operator-facing gap list (6.4.x; 7.0.x / 7.4.x; SD-WAN multi-link
  with health-check; physical-appliance VPN/IPsec-heavy)
* [`BUG_REPORTING.md`](../../BUG_REPORTING.md) — sanitisation +
  submission flow.  FortiGate-specific sanitisation rules: `ENC
  <base64>` secrets need synthetic `fakeEncodedSecret...` markers;
  `-----BEGIN (ENCRYPTED) PRIVATE KEY-----` blocks must be stripped
  to `REMOVED_FIXTURE_SANITISATION`; SSH pubkeys → `AAAAfakeSSHPublicKey...`;
  Firebase registration IDs sanitised; real WAN IPs → RFC 5737
  TEST-NET-3.

# Arista EOS — fixture catalogue (2015+)

> **Tier**: Shipped
> **Codec**: `arista_eos`
> **Existing corpus**: 5 fixtures spanning EOS 4.21 / 4.22 / 4.23 / 4.26
> (3× lab-validation, 1× ksator audit-tool, 1× karneliuk Batfish MVP);
> one of the two 4.23 fixtures is the **symmetric-IRB EVPN** Design Guide
> variant, the other is the **VLAN-based EVPN** Design Guide variant —
> the two prevailing EOS EVPN templates are both represented at 4.23
> but neither at any other major.  Source taxonomy + license-class
> guidance lives in [`00-source-analysis.md`](00-source-analysis.md).

The Arista corpus has solid lab-validation roots but **stops at EOS
4.26** (October 2021).  Three of the last five GA trains (4.27 / 4.28 /
4.29 / 4.30 / 4.31 / 4.32 / 4.33 / 4.34 / 4.35 / 4.36) are unrepresented,
which is the gap [`WANTED.md`](../../tests/fixtures/real/WANTED.md)
explicitly flags ("Arista EOS 4.27+ current GA train").  Three high-
leverage public sources close the bulk of that gap on permissive
licenses: the **`aristanetworks/avd`** Apache-2.0 example outputs
(modern AVD intended configs), the **`aristanetworks/eos-deployment-
guide-configs`** repo (Arista's own deployment-guide bundle), and
several **batfish/lab-validation** snapshots already on the 4.36
engineering build train.

---

## Version timeline

EOS GA trains land every 4–6 months.  Arista supports each major
release for 36 months from initial F-train post.  The table below
maps each release-train apex to its corpus coverage.

| Train | First F-train post | EoS (36 mo) | In corpus | Priority to add |
|---|---|---|---|---|
| 4.14 | 2015 Jan | EoS 2018 | no | low (legacy retrospective) |
| 4.15 | 2015 May | EoS 2018 | no | low |
| 4.16 | 2016 Mar | EoS 2019 | no | low |
| 4.17 | 2016 Aug | EoS 2019 | no | low |
| 4.18 | 2017 Jan | EoS 2020 | no | low (legacy) |
| 4.19 | 2017 Jun | EoS 2020 | no | low |
| 4.20 | 2017 Oct | EoS 2020 | no | low |
| 4.21 | 2018 Aug | EoS 2021 | **yes** (batfish `eos_private_asn`) | covered |
| 4.22 | 2019 Mar | EoS 2022 | **yes** (ksator audit, DCS-7150S-64) | covered |
| 4.23 | 2019 Sep | 2022-09-27 (past EoS) | **yes** (batfish symmetric-IRB + VLAN-based EVPN; multicast; route-map fixtures) | covered |
| 4.24 | 2020 May | EoS 2023 | no | low (gap-filler) |
| 4.25 | 2021 Mar | EoS 2024 | no | low |
| 4.26 | 2021 Oct | EoS 2024 | **yes** (karneliuk `A-EOS1.cfg`, EVPN/VXLAN kitchen-sink) | covered |
| 4.27 | 2022 Apr | EoS 2025 | no | **medium** (modern GA) |
| 4.28 | 2022 Oct | EoS 2025 | no | medium |
| 4.29 | 2022 Oct | 2025-10-31 (past EoS) | no | medium |
| 4.30 | 2023 Apr | 2026-04-14 | no | **high** (still GA, EVPN underlay grammar shifted) |
| 4.31 | 2023 Oct | 2026-10 (est.) | no | **high** (current LTS; `Arfa` default) |
| 4.32 | 2024 Apr | 2027-04 (est.) | no | **high** (MPLS data plane lit; widely used in 2025 labs) |
| 4.33 | 2024 Oct | 2027-10 (est.) | no | high |
| 4.34 | 2025 Apr | 2028 (est.) | no | high |
| 4.35 | 2025 Oct | 2028 (est.) | no | high (most-current LTS-candidate) |
| 4.36 | 2026 Apr | 2029 (est.) | indirectly (batfish 4.36 eng-build) | **medium** (current GA) |

**Codec gap shape**: the corpus jumps from `karneliuk_a_eos1_eos4260.txt`
(EOS 4.26.0.1F, October 2021) to nothing on the modern side.  Anything
in 4.27 → 4.36 closes the gap.

---

## Existing corpus coverage

See [`tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md)
arista_eos/ section for the canonical entries.  Quick recap of the
five fixtures and what each exercises (so this catalogue's
recommendations don't re-pull what's already in place):

| Fixture | EOS | Lines | Grammar focus | Variant |
|---|---|---|---|---|
| `ksator_dcs_7150s64_eos4224.txt` | 4.22.4M | 256 | hostname/AAA/SNMP/interfaces (52× Ethernet + 16× QSFP-breakout); single static route; `service routing protocols model multi-agent` | physical DCS-7150S-64 |
| `batfish_labval_dc1_leaf2a_eos4230.txt` | 4.23.0.1F | 429 | MLAG + VXLAN1 + VARP virtual-router MAC; 15 tenant VLANs; `router bgp 65102`; 2 VRFs (`Tenant_A_OP_Zone` + `WEB_Zone`); 5× Port-Channel MLAG | EVPN L3 Design Guide — **symmetric IRB** |
| `batfish_eos_evpn_vlan_based_leaf.txt` | 4.23.0.1F | 330 | same topology + node naming as the symmetric-IRB sibling, but **VLAN-based EVPN** (L2VNIs only with centralised L3 GW) | EVPN L3 Design Guide — **VLAN-based** |
| `batfish_duplicateprivate_eos4211.txt` | 4.21.1.1F | 64 | minimal — `router bgp 65001` with `neighbor ... remote-as 65001` (duplicate-private-ASN scenario) | vEOS |
| `karneliuk_a_eos1_eos4260.txt` | 4.26.0.1F | 82 | EVPN/VXLAN kitchen-sink (small): `service routing protocols model multi-agent`, VLAN 100, Vxlan1 vni 100, Loopback0/Mgmt1 (v4+v6), `router bgp 65033`, evpn redistribute-learned, ipv4/evpn AFs, route-maps | vEOS |

**Coverage strengths**: both prevailing EVPN templates (symmetric IRB +
VLAN-based) at EOS 4.23; one physical-chassis capture (DCS-7150S-64).

**Coverage gaps for the catalogue to target**:
* No fixture from **4.27 / 4.28 / 4.29 / 4.30 / 4.31 / 4.32 / 4.33 / 4.34 / 4.35 / 4.36**.
* No **all-active EVPN multihoming** (ESI) capture.
* No **MPLS L3VPN over Arista** (4.32+ MPLS data-plane).
* No **CV-Pathfinder / SD-WAN** Arista config (modern AVT grammar).
* No **5-stage Clos / super-spine** topology.
* No **IPv6 underlay BGP unnumbered** EVPN topology (only basic v4).
* No **MLAG-less EVPN with all-active ESI** variant.

---

## Pull-target inventory

### 4.30+ — modern train (WANTED.md gap; significant EVPN underlay grammar changes)

The highest-priority bucket.  EVPN underlay grammar shifted notably
in this window (notably `no neighbor X activate` becoming opt-in
instead of opt-out in some address-family sub-cases) and CloudVision
configuration handlers were rewritten.

#### GitHub repositories

* **`aristanetworks/avd`** — official Arista AVD repo, Apache-2.0,
  copyright 2019 Arista Networks.  Contains **9 example bundles**
  under `ansible_collections/arista/avd/examples/`, each with an
  `intended/configs/*.cfg` subdirectory of fully-rendered EOS
  configs.  AVD's intended/configs output is the *target* format for
  Arista's own validated designs — these are the same configs that
  CloudVision pushes to live cEOS / vEOS / physical 7280/7050 fleets.
  Filenames (per example):
    * `single-dc-l3ls/intended/configs/`: 6× leaf + 2× spine (`dc1-leaf1a..2c.cfg`, `dc1-spine1.cfg`, `dc1-spine2.cfg`).  L3LS EVPN/VXLAN symmetric IRB.  `dc1-leaf1a.cfg` is **~365 lines** with MLAG + VXLAN + EVPN + 3 VRFs (MGMT, VRF10, VRF11) + 12 VLANs + `ip virtual-router mac-address 00:1c:73:00:00:99` anycast.  `dc1-spine1.cfg` is **~138 lines** with BGP AS 65100, EVPN-overlay peering to 4 leaves, TerminAttr.  EOS version not embedded in the rendered output (AVD generates without `!device:` banner) — README + ansible-cvp release notes indicate 4.27+ target.
    * `dual-dc-l3ls/intended/configs/`: 12× leaf + 4× spine across DC1/DC2 (`dc1-leaf1a..2c.cfg`, `dc1-spine1..2.cfg`, `dc2-leaf1a..2c.cfg`, `dc2-spine1..2.cfg`).  Same EVPN DC-GW grammar twice over with explicit DCI.
    * `single-dc-l3ls-ipv6/intended/configs/`: IPv6 underlay variant.  `dc1-leaf1a.cfg` is **~436 lines** with `2001:db8:2::/64` p2p links, IPv6 EVPN-overlay loopbacks, IPv6 MLAG peer, VRF10/11/12.  **The only IPv6-underlay EVPN fixture target in the catalogue.**
    * `campus-fabric/intended/configs/`: 8× leaf + 2× spine (campus L2/L3 fabric).  `LEAF1A.cfg` / `SPINE1.cfg` etc.
    * `isis-ldp-ipvpn/intended/configs/`: 9× devices (`p1-4.cfg`, `pe1-3.cfg`, `rr1-2.cfg`) — **MPLS L3VPN PE/P/RR design**.  `pe1.cfg` is **~184 lines** with ISIS CORE level-2, LDP+MPLS, BGP MPLS-VPN, 2 customer VRFs (`C1_VRF1` + `C2_VRF1`).  Closes the L3VPN-over-Arista gap entirely.
    * `cv-pathfinder/intended/configs/`: 17 devices (`pf1-2.cfg`, `site1-4-border/wan/leaf*.cfg`, `inet-cloud.cfg`, `mpls-cloud.cfg`) — **CV-Pathfinder / AVT SD-WAN**.  `pf1.cfg` is **~402 lines** with `router adaptive-virtual-topology`, `router path-selection`, AVT path-groups (INTERNET / MPLS / LAN_HA), `router bgp 65000` with EVPN + path-selection + link-state AFs, 4 VRFs (MGMT/BLUE/RED/default).  Modern SD-WAN grammar; no equivalent in corpus.
    * `single-dc-multipod-l3ls/intended/configs/`: 5-stage Clos (super-spine + spine + leaf).  No equivalent topology class in corpus.
    * `l2ls-fabric/intended/configs/`: L2-only campus.
  Licence: Apache-2.0.  Sanitisation: minimal — these are intended
  configs not live captures, so no real PII; placeholder router-IDs
  (10.255.x.x), placeholder ASNs (65xxx), placeholder hostnames.
  Quality: extremely high — Arista-authored, deterministically
  rendered, version-pinned via AVD release.
  **Recommended first-pull**: `single-dc-l3ls/dc1-leaf1a.cfg` + a
  spine + one PE from `isis-ldp-ipvpn/` + a pf from `cv-pathfinder/`.
  Each picks up a different grammar surface the corpus doesn't have.

* **`vttrj/lab1-vxlan-her`** — containerlab VXLAN HER (head-end
  replication, not EVPN — VXLAN flood-list grammar without BGP-EVPN
  control plane) topology spanning 3 DCs.  cEOS 4.32.0.1F.
  `bootstrap-config/`: `dc1-leaf1.cfg`, `dc1-spine1a.cfg` (~150 lines,
  MLAG + VXLAN vlan-vni map + OSPF underlay), `dc1-spine1b.cfg`,
  `dc2-spine1.cfg`, `dc3-spine1.cfg`.  No EVPN/BGP — pure OSPF + VXLAN
  static flood-list.  Closes the "VXLAN without EVPN" coverage gap +
  is **the only 4.32 capture target identified**.  Licence: not
  declared (README only) — treat as discovery; sanitisation light
  (RFC1918 throughout, placeholder hostnames).  Quality: medium —
  community lab, not Arista-authored, but real bootstrap configs
  that boot cEOS into a functional VXLAN HER state.

* **`jonxstill/avd-evpn-multicast`** — AVD single-DC L3LS example
  with **EVPN multicast** support added (rare grammar — multicast
  carried over EVPN, distinct from the L2/L3 IRB variants in corpus).
  Generated `intended/configs/*.cfg` after `ansible-playbook build.yml`.
  License: not declared (no LICENSE file visible) — treat as
  discovery-tier.  EOS version not pinned (uses AVD collection
  versioning).  Quality: medium-high (AVD-rendered).

#### Forum / community posts

* **community.arista.com** — much smaller than Cisco / HPE
  community forums; most Arista community discussion happens on
  GitHub or Slack rather than a vendor forum.  Targeted Google
  searches (`site:community.arista.com "show running-config"`) return
  partial config snippets but rarely full captures.  Discovery-tier
  only; not a primary pull target.

* **r/arista** — small subreddit, occasional config snippets when
  operators ask for troubleshooting help.  Heavy sanitisation needed.
  Discovery-tier.

* **`reddit.com/r/networking` / `r/cisco`** — Arista configs surface
  occasionally in multi-vendor threads.  Use search:
  `site:reddit.com/r/networking "show running-config" arista`.
  Discovery-tier.

#### Vendor docs / lab guides

* **Arista EOS Sample Configurations** —
  `arista.com/en/um-eos/eos-sample-configurations` (per-release-train
  copy: `4.30.0F/`, `4.31.0F/`, `4.32.0F/`, ..., `4.36.0F/`).  Vendor
  docs published under CC-BY-style "example use" terms (per the source
  analysis Tier 1.2).  Each release-train doc set has chapters on
  MLAG, EVPN, VXLAN, BGP — each with embedded example configs.  Not
  full running-configs (per-feature snippets), but authoritative for
  grammar.  Quality: highest — vendor-authored.  Sanitisation: none
  needed (no PII).  License confidence: high (vendor docs).
  **Recommended**: scrape per-feature snippets and synthesize them
  into a representative 4.30+ "real-shape" fixture — same approach
  as the Aruba `aruba_central_5memberstack_rendered.cfg` precedent.

* **Arista ATD Lab Guides** (`labguides.testdrive.arista.com`) — vendor-
  hosted lab guides with full running-config excerpts.  L2 EVPN, L3
  EVPN, Symmetric IRB with MLAG, L2/L3 EVPN with All-Active
  Multihoming, ISIS-SR-EVPN.  Vendor doc license; quality: high.
  Useful for grammar reference; the embedded snippets aren't whole
  configs but are dense enough that 3–4 stitched together cover one
  device.  ATD uses cEOS, version varies per lab cycle (2024.3 /
  2025.1 / 2025.3 — currently on 4.32+).

* **Arista EOS Central** (`eos.arista.com`) — Arista's TOI / category
  pages for EVPN / VXLAN / MLAG / EOS+.  Per-article configs; license
  inherits CC-BY-style.  Quality: high.  Discovery for blog-style
  grammar references rather than full pulls.

#### Other (pastebin / YouTube / blogs / Internet Archive)

* **`overlaid.net`** — operator blog with multiple multi-thousand-word
  posts on Arista BGP EVPN configuration.  Examples are operator-
  authored (4.23-era), useful as inspiration / synthetic-fixture
  draft material — not direct import (per source-analysis Tier 2.4).

* **`scottstuff.net`** — 2025 post "EVPN-VXLAN Direct Routing With
  Arista" has full VLAN + virtual-router config blocks for direct-
  routing variant.  Discovery-tier (operator blog).

* **`karneliuk.com`** — multi-part "DC. Part N. EVPN/VXLAN for Data
  Centre" series with Arista config examples from 2018+.  Useful for
  historical grammar context.  Discovery-tier.

* **`blog.ipspace.net`** — Ivan Pepelnjak's series on EVPN designs;
  several 2024 posts ("EVPN Designs: VXLAN Leaf-and-Spine Fabric",
  "EVPN Designs: Scaling iBGP with Route Reflectors", "EVPN Designs:
  iBGP Full Mesh Between Leaf Switches", "Fast Arista cEOS Container
  Configuration") have netlab-companion topologies with rendered
  EOS configs accessible via GitHub (`ipspace/netlab` examples).
  Apache-2.0 (`ipspace/netlab` is Apache).  Quality: high.

### 4.27-4.29 — mid-modern gap

Three release trains without corpus coverage.  Pull-targets here
overlap with the 4.30+ bucket (AVD examples are version-agnostic in
rendering — they target whichever cEOS image you have).  The
narrower asks:

* **`arista-netdevops-community/eos_designs_to_containerlab`**
  (Apache-2.0) — references `ceos:4.28.0F` and `ceos:4.31.1F` in
  examples; deploys AVD-generated configs to containerlab.  Pulls
  back to AVD output structure, so same as above.

* **`arista-netdevops-community/avd-evpn-webinar-june-11`**
  (Apache-2.0) — webinar lab.  `intended/configs/`: `LEAF1A.cfg`,
  `LEAF2A.cfg`, `LEAF2B.cfg`, `SPINE1.cfg`, `SPINE2.cfg`.  `LEAF2A.cfg`
  is **~356 lines** with VLAN 10-41, MLAG Port-Channel47, Vxlan1 with
  7 VLANs + 2 VRFs, BGP EVPN overlay to spines (1.1.1.1/1.1.1.2),
  ip virtual-router anycast MAC.  `LEAF1A.cfg` is ~217 lines with
  symmetric IRB (VRF A + MGMT, 3 VLANs SVI, vlan-aware bundles, route-
  target 51:51).  `SPINE1.cfg` is ~150 lines with EVPN-OVERLAY peering
  and BGP aliases.  EOS version not pinned in headers but webinar
  date (June 11) ties to a 4.28-era cEOS image used in the live
  walkthrough.  **High-leverage pull** for 4.27-4.29 range.

* **`arista-netdevops-community/avd-cEOS-Lab`** (Apache-2.0) — 8
  EVPN labs under `labs/evpn/`: `avd_asym_irb`, `avd_asym_multihoming`,
  `avd_central_any_gw`, `avd_dual_dc_l3_gw`, `avd_dual_dc_multi_domain`,
  `avd_sym_irb`, `avd_sym_irb_ibgp`, `avd_sym_sa_multihoming`.  Plus
  2 MPLS LDP / MPLS EVPN labs.  Each lab renders AVD configs at runtime
  — pull them post-render.  Particularly valuable: `avd_asym_irb`
  (the asymmetric-IRB EVPN variant the corpus doesn't have), and
  `avd_sym_sa_multihoming` (single-active EVPN multihoming —
  distinct from all-active).

* **`srl-labs/multivendor-evpn-lab`** — multi-vendor (SR-Linux +
  Arista cEOS 4.26.2.1F + Juniper vQFX) L2 EVPN lab.  Per-node
  config files under `config/`.  License: not displayed.  Quality:
  medium.  4.26 image — already at corpus floor; pull only if
  cross-vendor parity validation is the goal.

### 4.24-4.26 — older modern (one fixture in corpus at the 4.26 ceiling)

Lower priority — `karneliuk_a_eos1_eos4260.txt` already covers 4.26.

* **`batfish/lab-validation`** snapshots already at 4.23 (in corpus)
  and 4.36 (eng build — see 4.30+ bucket below) — no 4.24-4.26 batfish
  snapshots in this range.

* **AVD pre-4.x releases** — early AVD (1.x / 2.x / 3.x) shipped
  EOS-design templates targeting 4.24+; the generated configs are
  stable across the major-versions because AVD abstracts versioning.

### 4.21-4.23 — covered, but more variants useful

Existing corpus has 3 fixtures in this range.  Additional variants
that close specific grammar gaps:

* **batfish `eos_evpn_l3_design_guide/configs/DC1-LEAF1A`** — sibling
  of `batfish_labval_dc1_leaf2a_eos4230.txt` (LEAF2A) but the *first
  leaf in the design guide*.  EOS-4.23.0.1F, **~269 lines**.  Same
  topology as LEAF2A, different VTEP role / VRF route-target / per-leaf
  loopback values.  Cross-validation candidate — would surface any
  per-device divergence in symmetric-IRB rendering.  Apache-2.0.

* **batfish `eos_evpn_l3_design_guide/configs/DC1-BL1A|DC1-BL1B`** —
  **border-leaf** variants (BL role, distinct from leaf).  Apache-2.0.
  EVPN border-leaf grammar (egress/ingress for off-fabric).  Not
  represented in corpus.

* **batfish `eos_evpn_l3_design_guide/configs/DC1-SVC3A|DC1-SVC3B`** —
  **service-leaf** variants (DC1-SVC role).  Apache-2.0.  Service-leaf
  EVPN grammar (firewall integration, FW redirect routes).  Not
  represented.

* **batfish `eos_evpn_l3_design_guide_vlan_based/configs/H-LEAF1A`** —
  sibling of `batfish_eos_evpn_vlan_based_leaf.txt` (H-LEAF2A).  Same
  rationale as DC1-LEAF1A above but on the VLAN-based variant side.
  Apache-2.0.

* **batfish `eos_evpn_l3_design_guide_vlan_based/configs/H-SPINE1|H-SPINE2`** —
  the spine side of the VLAN-based design.  Corpus has leaves but not
  spines.  Apache-2.0.  Modest grammar density but closes the role
  diversity gap.

* **batfish `eos_multicast_base/configs/rp1`** — EOS-4.23.0.1F vEOS
  with **PIM sparse-mode + multicast routing + static RP** grammar
  (mapped to ACLs 239.1.1.0/24 + 239.1.2.0/24).  ~77 lines.  Apache-2.0.
  **The first multicast Arista fixture target** — no PIM in corpus.

* **batfish `eos_ibgp_local_preference/configs/r1`** — EOS-4.23.0.1F
  with `route-map` + `set local-preference` + iBGP grammar.  ~77 lines.
  Apache-2.0.  Light grammar; gap-filler.

* **batfish `eos_ebgp_loop_prevention/configs/d1..d4`** — 4 devices
  on EOS-4.23.0.1F.  eBGP loop prevention (`allowas-in`) grammar.  ~58
  lines each.  Apache-2.0.  Light grammar.

* **batfish `eos_undefined_route_map/configs/`** — 3 devices (`d1`,
  `d2_in`, `d3_out`) on EOS-4.23.0.1F.  Route-map definition edge
  cases.  Apache-2.0.

* **batfish `eos_rm_undefined_continue/configs/`** — 4 devices on
  EOS-4.23.0.1F.  `route-map ... continue` grammar.  Apache-2.0.
  Discovery-tier (very narrow).

* **batfish `eos_ospf_unnumbered/configs/leaf1|leaf2|spine`** —
  **EOS-4.36.0.1F-47401373.43601F (engineering build)**.  ~44 lines.
  `ip address unnumbered Loopback0` + `ip ospf network point-to-point`
  + OSPF dead/hello tuning.  Apache-2.0.  **Closes the 4.36 gap with
  the smallest possible diff** — see 4.30+ section below.

* **batfish `eos_ceos_bgp_unnumbered/configs/leaf|spine`** —
  **EOS-4.36.0.1F-47401373.43601F**.  ~56 lines.  BGP-unnumbered with
  IPv6 link-local + `neighbor interface Ethernet1 peer-group SPINES`
  + `ipv6 unicast-routing`.  **The corpus has no BGP-unnumbered fixture
  at all** — high leverage.  Apache-2.0.

* **batfish `eos_ceos_ebgp/configs/r1|r2`** —
  **EOS-4.36.0.1F-47401373.43601F**.  ~40 lines.  Basic eBGP.  Apache-2.0.
  Light grammar; pulls because it's the smallest 4.36 capture.

* **batfish `eos_switchport_order/configs/r1|r2`** —
  **EOS-4.36.0.1F-47401373.43601F**.  ~40 lines.  Edge case for
  `switchport mode trunk` ordering.  Apache-2.0.  Light grammar.

* **batfish `eos_bgp_weight_behavior_multi_agent/configs/r1-423|r2-423`** —
  EOS-4.23.0.1F (`multi-agent` BGP).  ~71 lines.  Apache-2.0.  Gap-filler.

* **batfish `eos_bgp_aggregate/configs/EOS-1|EOS-2`** — EOS-4.23.0.1F.
  ~66 lines.  `aggregate-address` + `summary-only` BGP grammar.
  Apache-2.0.  Useful for BGP aggregate testing.

* **batfish `eos_ospf_bgp/configs/dlh15`** — actually Cisco IOSv 15.7,
  not Arista — skip (the `np01` / `np02` are likely the Arista nodes,
  confirm before pulling).

#### `aristanetworks/eos-deployment-guide-configs` (separate; no version pin)

* **`aristanetworks/eos-deployment-guide-configs`** — Arista's own
  repo housing the **EVPN Deployment Guide** final-configurations
  bundle.  No LICENSE file declared in the repo top-level (the
  README is one line).  Files: `A-LEAF1A`, `A-LEAF2A`, `A-LEAF2B`,
  `A-SPINE1`, `A-SPINE2`, `README.md` (under `EVPN Deployment
  Guide/`).  `A-LEAF1A` is **~160 lines** with EVPN VLAN-aware-bundles,
  Vxlan1 with VNI mappings, BGP underlay+overlay (AS 65101), 3 VRFs
  (A, B, MGMT) with route-targets — **symmetric IRB**.  No `!device:`
  banner / version pin.  `A-SPINE1` is ~102 lines (BGP underlay+overlay,
  peer-filters, EVPN AF, MGMT VRF isolation).  Provenance: Arista
  Networks GitHub org — vendor-authored.  License risk: unclear
  (no LICENSE file).  Treat as **forum-share-like provenance**:
  it's Arista's own publication of demo configs, so the share-precedent
  is strong but a formal LICENSE PR upstream would be safer.

### 4.14-4.20 — legacy retrospective (low priority)

Few public lab repos targeted these versions.  Anything pre-4.21 is
predominantly absent from GitHub (the `arista-netdevops-community`
GitHub org didn't exist until ~2018).  Discovery-only:

* **`networkop/arista-network-ci`** (BSD-3-Clause) — cEOS-Lab 4.20.0F
  Gitlab + Ansible + Robot Framework CI demo.  Spine/leaf topology
  generated dynamically; not pre-rendered configs in repo.  Low-yield
  pull target.

* **`wintermute000/arista-config`** (no LICENSE declared) — tested
  with vEOS 4.15.5M.  Ansible playbooks, no rendered output configs
  in repo.  Discovery-tier.

* **`krunal7558/vEOS-lab`** (Apache-2.0) — vEOS-lab 4.18.1F.  Ansible
  playbooks + `configs/` for generated configs + `backup/` for running-
  config backups.  Pre-4.21 but Apache-2.0 — could serve as a "legacy
  EOS 4.18" capture if a retrospective fixture is desired.

* **Internet Archive `web.archive.org`** captures of `packetlife.net`,
  `routereflector.com`, and `kbatcho.com` from 2015-2018 — operator-
  blog snippets only.  Discovery-tier for inspiration / synthetic
  draft.  Heavy sanitization + license re-verification.

---

## Recommended pull priority order

1. **`aristanetworks/avd/.../single-dc-l3ls/intended/configs/dc1-leaf1a.cfg`** — the canonical modern symmetric-IRB leaf, Apache-2.0, vendor-authored, ~365 lines.  Single pull closes the 4.27+ gap with the densest grammar surface available.
2. **`aristanetworks/avd/.../single-dc-l3ls/intended/configs/dc1-spine1.cfg`** — paired spine.  Together they exercise the full L3LS-EVPN underlay+overlay pair.
3. **`aristanetworks/avd/.../isis-ldp-ipvpn/intended/configs/pe1.cfg`** — closes the MPLS L3VPN gap for Arista — first ISIS / LDP / MP-BGP-VPNv4 Arista capture.  ~184 lines.
4. **`aristanetworks/avd/.../cv-pathfinder/intended/configs/pf1.cfg`** — closes the CV-Pathfinder / AVT SD-WAN gap.  ~402 lines.
5. **`batfish/lab-validation/snapshots/eos_ceos_bgp_unnumbered/configs/leaf/show_running-config.txt`** — closes the BGP-unnumbered gap + brings 4.36 (current GA train).  Apache-2.0.  ~56 lines.
6. **`batfish/lab-validation/snapshots/eos_multicast_base/configs/rp1/show_running-config.txt`** — closes the PIM/multicast gap.  Apache-2.0.  EOS-4.23.0.1F.  ~77 lines.
7. **`vttrj/lab1-vxlan-her/bootstrap-config/dc1-spine1a.cfg`** — closes the **EOS 4.32** gap explicitly + the VXLAN-HER-without-EVPN variant.  License unclear — verify or treat as discovery + synthetic redraft.
8. **`arista-netdevops-community/avd-evpn-webinar-june-11/intended/configs/LEAF2A.cfg`** — second modern leaf with MLAG anycast + 7-VLAN/2-VRF density at 4.28-era.  Apache-2.0.  ~356 lines.
9. **`aristanetworks/avd/.../single-dc-l3ls-ipv6/intended/configs/dc1-leaf1a.cfg`** — IPv6-underlay EVPN variant (first in corpus).  Apache-2.0.  ~436 lines.
10. **`batfish/lab-validation/snapshots/eos_evpn_l3_design_guide/configs/DC1-BL1A/show_running-config.txt`** — border-leaf role variant.  Apache-2.0.  Adds a new role-type to corpus.

Pulls 1-5 cover the **WANTED.md priority** ("4.27+ / 4.30+ current GA train; MLAG + EVPN VxLAN-multihoming") in 5 fixtures.  Pulls 6-10 extend coverage to PIM, IPv6-underlay, EVPN-multihoming, and border-leaf role.

---

## Out-of-scope (deliberately excluded)

* **Vendor demo accounts** (Arista TAC / SE-led demos) — login-gated
  on `arista.com/en/support`; TOS-restricted.
* **CCIE-DC / DC-fabric training workbooks** — likely paywalled
  (Cisco Press doesn't publish Arista; the Arista NCIE / ACE-IE
  training material is Arista-distributed and proprietary).
* **Customer-deployed Arista DC fleets** — only if the operator
  contributes per `BUG_REPORTING.md` sanitisation workflow + license.
* **Closed-source replays** of Arista config from non-public network
  captures (e.g., infosec leaks).

---

## See also

* [`README.md`](README.md) — folder index + per-OS catalogue shape
* [`00-source-analysis.md`](00-source-analysis.md) — source-type taxonomy
  + license guidance (this catalogue cites Tier 1.1 / 1.2 / 1.3 + 2.4
  bands).
* [`tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md)
  — existing 5-fixture provenance ledger (arista_eos/ section).
* [`tests/fixtures/real/WANTED.md`](../../tests/fixtures/real/WANTED.md)
  — the operator-facing "Arista EOS 4.27+" gap statement this
  catalogue is designed to close.
* [`BUG_REPORTING.md`](../../BUG_REPORTING.md) — sanitisation +
  fixture-submission workflow that any pull-target above must pass
  through before commit.

# Juniper Junos (EX / QFX / MX) — fixture catalogue (2015+)

> **Tier**: Shipped
> **Codec**: `juniper_junos` (set-form CLI + block-form)
> **Existing corpus**: 7 fixtures spanning 4 major versions — see
> [`tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md)
> § junos/

This catalogue is the per-OS sibling of
[`00-source-analysis.md`](00-source-analysis.md) — see that file for
the fifteen-class source taxonomy (Tier 1 permissive / Tier 2
forum-share / Tier 3 narrow-utility / Tier 4 off-limits) referenced
below by `Tier-N.M` shorthand.

**Scope note.**  This file covers Junos OS for the EX (campus +
small-DC switch), QFX (DC switch), and MX (SP / edge router)
platforms — i.e. everything Netcanon's shipped `juniper_junos` codec
targets.  The SRX security-platform family runs on the same Junos OS
codebase but its grammar surface (`security policies`, `security
nat`, `security zones`, `security ipsec`) is large enough to warrant
a distinct Tier-D codec scope; see
[`12-juniper_srx.md`](12-juniper_srx.md).

PTX (transport / 400G) and ACX (access / mobile-backhaul) platforms
run Junos OS as well, but the codec doesn't currently emit
PTX-specific grammar (`set chassis network-services` defaults differ;
forwarding-options PTX-only knobs are parse-and-ignore).  Junos OS
Evolved (`Junos Evo`) — the Linux-based rewrite shipped on
PTX10001-36MR / PTX10003 / PTX10004 / PTX10008 / QFX5130 / QFX5220 —
shares the same set-form CLI surface but has independent release
trains; included below as platform-class coverage notes rather than
distinct codec scope.

---

## Version timeline

Junos OS follows a quarterly cadence: `YY.Q.RN` where `YY` is the
2-digit year, `Q` is the quarter (1-4), and `RN` is the maintenance
release (R1 is the FRS, R2/R3 follow).  Service releases are denoted
`RN-S<n>` (e.g. `21.4R3-S4`).

**LTS / Extended End of Life (EEOL).**  Per Juniper's policy and
[Lindsay Hill's version-selection guide](https://lkhill.com/juniper-version-selection/),
**even-quarter releases** (X.2, X.4) are designated **EEOL**: 3 years
of Engineering Support + 6 months of customer support after FRS.
Odd-quarter releases (X.1, X.3) get 2 years of Engineering Support
and are *not* EEOL.  Most operator-deployed production code runs an
EEOL train.

Dates below sourced from
[Juniper's official Junos OS Dates & Milestones page](https://support.juniper.net/support/eol/software/junos/)
(authoritative) and the JunosGeek mirror
[2021 snapshot](http://junosgeek.blogspot.com/2021/04/junos-os-dates-milestones.html)
(for 17.4-21.1).  Dates after 21.1 derived from individual release
notes; cells marked "—" are unconfirmed at write time.

| Version | FRS (R1) date | EoE | EoS | EEOL? | Notable platforms (EX/QFX/MX) | In corpus? | Priority |
|---|---|---|---|---|---|---|---|
| **14.1** | 2014-06 | ~2016-06 | ~2016-12 | yes (.1 is annual in old scheme) | EX2200/3300/4200; MX80/240/480/960; QFX5100 (early) | no | LOW (retrospective only — pre-set-form-as-default era) |
| **14.2** | 2014-12 | ~2017-06 | — | yes | EX2200/3300/4200/4550; MX5/10/40; QFX5100 | no | LOW |
| **15.1** | 2015-06 | 2017-12 | 2018-06 | yes | EX2200/3300/4200/4550; MX5/10/40/80/104/240/480/960; QFX5100/3500 | **YES** (`ksator_labmgmt_ex4550_junos151.set`, 52 lines) | satisfied |
| **16.1** | 2016-06 | 2018-06 | 2019-03 | yes (annual) | EX, MX, QFX5100/5110/3500/3600 | no | LOW (retrospective) |
| **16.2** | 2016-12 | 2018-09 | 2019-03 | no | EX, MX, QFX | no | LOW |
| **17.1** | 2017-03 | 2018-09 | 2019-03 | no | EX, MX, QFX | no | LOW |
| **17.2** | 2017-06 | 2019-12 | 2020-06 | yes | EX, MX, QFX5100/5110/10K | no | LOW |
| **17.3** | 2017-09 | 2019-09 | 2020-03 | no | EX, MX, QFX5100/5110/10K | **YES** (3 fixtures: QFX5100/5110/10K2 all `ksator_labmgmt`) | satisfied |
| **17.4** | 2017-12 | 2020-12 | 2021-06 | yes | EX, MX, QFX, ACX, **PTX10K** | no | LOW (retrospective; could close a 17.4-specific gap but not urgent) |
| **18.1** | 2018-03 | 2021-03 | 2021-09 | no | EX, MX, QFX | no | LOW |
| **18.2** | 2018-06 | 2021-06 | 2021-12 | yes | EX, MX (including MX10K), QFX | no | LOW |
| **18.3** | 2018-09 | 2021-09 | 2022-03 | no | EX, MX, QFX | no | LOW |
| **18.4** | 2018-12 | 2021-12 | 2022-06 | yes | EX4600/9214; MX; QFX5K/10K; ACX; **PTX10003 Evo** | **YES** (`buraglio_netlab_junos184.set`, 28 lines) | satisfied (light fixture; could augment) |
| **19.1** | 2019-03 | 2022-03 | 2022-09 | no | EX, MX (5G refactor), QFX5K/10K | no | **HIGH — WANTED.md gap #1** |
| **19.2** | 2019-06 | 2022-06 | 2022-12 | yes | EX, MX, QFX | no | **HIGH** |
| **19.3** | 2019-09 | 2022-09 | 2023-03 | no | EX, MX, QFX | no | **HIGH** |
| **19.4** | 2019-12 | 2022-12 | 2023-06 | yes | EX4400; MX10003; QFX5K/10K (EVPN-VXLAN sym-IRB matures) | no | **HIGH — top single-version target** |
| **20.1** | 2020-03 | 2022-03 | 2022-09 | no | EX, MX, QFX | no | HIGH |
| **20.2** | 2020-06 | 2023-06 | 2023-12 | yes | EX, MX, QFX | no | HIGH |
| **20.3** | 2020-09 | 2022-09 | 2023-03 | no | EX, MX, QFX | no | HIGH |
| **20.4** | 2020-12 | 2023-12 | 2024-06 | yes | EX4100/4300/4400; MX; QFX5120/5130/5220; PTX10001-36MR (Evo only) | no | **HIGH — operator-popular EEOL** |
| **21.1** | 2021-03 | 2023-03 | 2023-09 | no | EX, MX, QFX | no | MEDIUM |
| **21.2** | 2021-06 | 2024-06 | 2024-12 | yes | EX, MX, QFX | no | HIGH |
| **21.3** | 2021-09 | 2023-09 | 2024-03 | no | EX, MX, QFX | no | MEDIUM |
| **21.4** | 2021-12 | 2024-12 | 2025-06 | yes | EX, MX, QFX, ACX7K | no | **HIGH — common production train** |
| **22.1** | 2022-03 | 2024-03 | 2024-09 | no | EX, MX, QFX | no | MEDIUM |
| **22.2** | 2022-06 | 2025-06 | 2025-12 | yes | EX, MX, QFX | no | HIGH |
| **22.3** | 2022-09 | 2024-09 | 2025-03 | no | EX, MX, QFX | no | MEDIUM |
| **22.4** | 2022-12 | 2025-12 | 2026-06 | yes | EX4400/4650; MX10004; QFX5K/10K; ACX7K | no | **HIGH — current operator deployment** |
| **23.1** | 2023-03 | 2025-03 | 2025-09 | no | EX, MX, QFX; **vJunos-switch FRS** | no | MEDIUM |
| **23.2** | 2023-06 | 2026-06 | 2026-12 | yes | EX, MX, QFX; vJunos-switch | no | MEDIUM |
| **23.3** | 2023-09 | 2025-09 | 2026-03 | no | EX, MX, QFX | no | MEDIUM |
| **23.4** | 2023-12 | 2026-12 | 2027-06 | yes | EX, MX, QFX; vJunos-switch | no | MEDIUM |
| **24.1** | 2024-03 | 2026-03 | 2026-09 | no | EX, MX, QFX | no | LOW |
| **24.2** | 2024-06 | 2027-06 | 2027-12 | yes | EX, MX, QFX; vJunos-router | no | MEDIUM |
| **24.3** | 2024-09 | 2026-09 | 2027-03 | no | EX, MX, QFX | no | LOW |
| **24.4** | 2024-12 | 2027-12 | 2028-06 | yes | EX, MX, QFX | no | LOW |
| **25.1** | 2025-03 | 2027-03 | 2027-09 | no | EX, MX, QFX | no | LOW |
| **25.2** | 2025-06 | 2028-06 | 2028-12 | yes | EX, MX, QFX | no | LOW (modern train) |
| **25.4** | 2025-12 | 2028-12 | 2029-06 | yes | EX, MX, QFX | **YES** (2 fixtures: `batfish_evpntype5_router1_junos2541.set` + `batfish_l3vpn_pe1_junos2541.set`) | satisfied |

Date precision caveat: Juniper's day-precision (`2018-12-22`)
appears in
[the JunosGeek mirror](http://junosgeek.blogspot.com/2021/04/junos-os-dates-milestones.html)
through 21.1; later versions here use month-precision derived from
release notes timestamps.  The
[official Juniper Dates & Milestones page](https://support.juniper.net/support/eol/software/junos/)
remains authoritative.

---

## Existing corpus coverage

Seven fixtures, four distinct major versions (15.1, 17.3, 18.4,
25.4) — see [`NOTICE.md`](../../tests/fixtures/real/NOTICE.md)
junos/ rows for the full provenance ledger:

| Fixture | Version | Platform | Lines | Provenance |
|---|---|---|---|---|
| `ksator_labmgmt_ex4550_junos151.set` | 15.1R6.7 | EX4550 (campus access) | 52 | ksator/lab_management MIT |
| `ksator_labmgmt_qfx5100_junos173.set` | 17.3R1.10 | QFX5100 (DC leaf) | 106 | ksator/lab_management MIT |
| `ksator_labmgmt_qfx5110_junos173.set` | 17.3R1-S2.1 | QFX5110 (DC leaf, newer ASIC) | 52 | ksator/lab_management MIT |
| `ksator_labmgmt_qfx10k2_junos173.set` | 17.3R1-S2.1 | **QFX10002-72Q (spine)** | 391 | ksator/lab_management MIT |
| `buraglio_netlab_junos184.set` | 18.4R1-S1.1 | vMX-like SP router (ES.net netlab-ns) | 28 | buraglio/Juniper-SR-PCE |
| `batfish_evpntype5_router1_junos2541.set` | 25.4R1.12 | EVPN Type-5 leaf | 151 | batfish/lab-validation Apache-2.0 |
| `batfish_l3vpn_pe1_junos2541.set` | 25.4R1.12 | MPLS L3VPN PE | 34 | batfish/lab-validation Apache-2.0 |

All seven are **set-form**.  Block-form (curly-brace hierarchy)
captures are **absent from the corpus** but should be added — the
codec parses both surfaces, and operators frequently archive
configs via the block-form `show configuration` output as well.

Grammar surface covered today:
* `set version` parse-and-ignore
* `set system host-name` (incl. FQDN form)
* `set system root-authentication` + `set system login user / class
  / authentication encrypted-password`
* `set system services {ssh,netconf}`
* `set chassis aggregated-devices ethernet device-count`
* `set chassis fpc N pic M number-of-ports`
* `set interfaces <iface>` family inet / inet6 / iso / mpls /
  ethernet-switching with unit, vlan-id, address, ESI, channelized
  break-out (`xe-0/0/6:2.10`)
* `set vlans <name> vxlan vni <vni>` (GAP 6 wired up via 25.4
  fixtures)
* `set routing-instances <name> instance-type vrf / route-distinguisher
  / vrf-target / interface`
* `set policy-options policy-statement` (parse-and-ignore in v1, but
  exercised by the 25.4 fixtures)
* `set protocols {bgp,ospf,isis,mpls,evpn,ldp,lldp}` (mostly
  parse-and-ignore beyond the EVPN/VXLAN intersection)
* `apply-groups` inheritance pattern (Tier-3 parse-and-ignore)

**Gaps the gap years would fill:**
* 19.x — first major with mature EVPN-VXLAN symmetric IRB grammar
  outside the lab snapshots; `set protocols evpn vni-options`,
  `set switch-options vrf-import / vrf-export` shaped here
* 20.x — `set chassis network-services enhanced-ip` default change
  on MX10003+ that 18.4 corpus doesn't exercise
* 21.x — `set protocols bgp group ... family evpn signaling
  vpws-control-word` and EVPN multihoming maturation
* 22.x — `set system commit synchronize` and Apstra-rendered config
  shape (operator-popular train)
* SRX-platform set-form fixtures (excluded from this scope — see
  [`12-juniper_srx.md`](12-juniper_srx.md))
* Block-form (curly-brace) configs for either set-form complement
  or for operators capturing via `show configuration` not
  `show configuration | display set`

---

## Pull-target inventory

Each entry per source class.  Format: target → URL → license →
approx lines → grammar surface → sanitisation effort (none / minor
/ heavy) → quality (1-5) → set-form or block-form.

### 19.x (the #1 WANTED.md gap)

#### Tier-1.1 — GitHub repositories

* **`srl-labs/multivendor-evpn-lab` leaf3.txt / leaf4.txt**
  — https://github.com/srl-labs/multivendor-evpn-lab/tree/master/config
  — license **not declared at repo root** (LICENSE file absent per
  WebFetch);  treat as forum-share precedent (operator demo,
  permissive intent based on srl-labs convention)
  — ~150-250 lines per file (estimate; raw URLs returned 404 so
  exact path/extension TBD — file might be `.cfg` or under
  `configs/` subdir; needs git-clone to confirm)
  — **vQFX 19.4R1.10** image declared in `multivendor-evpn.clab.yml`
  — grammar: L2 EVPN underlay (OSPF) + iBGP overlay + Type-2 / Type-3
  route advertisement on leaf, VXLAN VTEPs
  — sanitisation: minor (already a lab demo, RFC1918 + RFC 5737)
  — quality: **4/5** — first 19.x fixture would close the WANTED.md
  #1 gap, and the multi-vendor parity (lab also has Arista cEOS +
  Nokia SR Linux configs from the same topology) is a value-add
  — form: TBD — needs file inspection; lab convention is **set-form**
    via containerlab `startup-config` but block-form possible

* **`bytesofcloud/Juniper-JNCIS-MCLAG`**
  — https://github.com/bytesofcloud/Juniper-JNCIS-MCLAG
  — license **not specified**; small repo (6 files; 1 ZIP + README +
  4 logs).  Treat as forum-share precedent only.
  — **Junos 19.1R3.9** on vMX
  — grammar: **MC-LAG** active/active + active/passive (not in
  corpus elsewhere — chassis aggregated-devices ethernet-options +
  mc-ae redundancy-group + iccp + bfd-liveness-detection),
  **VRRP** classic form, L2 + L3 segmentation, SVI configs
  — sanitisation: heavy (lab logs + ZIP need extraction + scrub)
  — quality: **3/5** — high-value grammar (MC-LAG isn't anywhere in
  corpus today and is a real operator deployment pattern) but
  license is murky and ZIP extraction is friction
  — form: standard Junos block-form likely (vMX backup convention)

* **`JNPRAutomate/ansible-junos-evpn-vxlan`**
  — https://github.com/JNPRAutomate/ansible-junos-evpn-vxlan/tree/master/config
  — license **MIT** (per repo metadata)
  — archived 2024-07-19 (read-only — stable target)
  — 10 rendered configs: `spine-01.conf`-`spine-04.conf` +
  `leaf-01.conf`-`leaf-04.conf` + `fabric-01.conf` + `fabric-02.conf`
  — version: not version-annotated but corresponds to a **2019-era
  Jinja template set** (Junos 18.x-19.x grammar; QFX5K/10K/MX
  templates per README)
  — grammar: EVPN/VXLAN underlay-overlay with multi-pod multi-tenant
  spine/leaf/fabric (3-stage Clos) — full vendor-recommended
  reference design
  — sanitisation: minor — already rendered with synthetic IPs +
  hostnames
  — quality: **4/5** — JNPRAutomate is the Juniper-Automation org's
  official sample; MIT license is clean; the 3-stage Clos rendered
  output is the canonical EVPN-VXLAN reference shape
  — form: **block-form** (`.conf` extension; Jinja2 renders to
  curly-brace hierarchy)
  — caveat: not version-stamped, so it's a "19.x-era reference
  design" rather than a captured device; corresponds well to the
  19.x grammar GAP but a contributor should treat the "exact OS
  version" cell as "19.x reference design (Jinja-rendered)"

#### Tier-1.2 — Vendor documentation examples

* **Juniper TechLibrary — EVPN-VXLAN Centrally-Routed Bridging
  example for MX spine + QFX leaf**
  — https://www.juniper.net/documentation/us/en/software/junos/evpn/topics/example/evpn-vxlan-mx-qfx-configuring.html
  — license: Juniper documentation example (treat as fair-use
  excerpt with attribution + CC-BY-style "example use"
  permission)
  — written against Junos 18.x-19.x grammar shape
  — grammar: full 5-stage Clos with MX spines + QFX5100 leaves;
  CRB design; aggregated-ethernet ESI; route-targets
  — sanitisation: none (already synthetic IPs + lab hostnames per
  TechLibrary convention)
  — quality: **5/5** — vendor-canonical reference; the inverse of
  the 25.4 batfish/lab-validation EVPN fixture (different topology
  layer)
  — form: set-form excerpt in the docs (extracted via copy-paste)

#### Tier-1.3 — Lab platforms

* **`Juniper/vqfx10k-vagrant`** — light-1qfx / full-2qfx /
  light-ipfabric-2S-3L topologies
  — https://github.com/Juniper/vqfx10k-vagrant
  — license **Apache-2.0**
  — Junos versions per box: 17.4R1 / 18.1R1 / 18.4R1 era (per
  vqfx box-version conventions; 19.x boxes existed but the repo
  hasn't been refreshed)
  — grammar: per-topology Vagrantfile + per-VM startup config;
  L2 + L3 leaf-spine variations
  — sanitisation: none
  — quality: 3/5 — official Juniper org + Apache-2.0 is excellent
  provenance, but the boxes are mostly 18.x-era so this is a
  18.x-augmentation target rather than a true 19.x gap-closer
  — form: **block-form** likely (Vagrantfile-embedded configs)

#### Tier-2.1 — Forum / community

* **Juniper Community blog (Aninda Chatterjee 2023-10-27)** —
  "Building virtual fabrics with vJunos-switch and Containerlab"
  — https://community.juniper.net/blogs/aninda-chatterjee/2023/10/27/virtual-fabrics-vjunos-switch-and-containerlab
  — license: forum-share / blog (fair-use for extraction)
  — Junos: vJunos-switch 23.1R1.8 — **NOT 19.x**, listed here
  because the post pattern (set-form configs for spine/leaf) is
  the template a 19.x version of would follow
  — quality: 2/5 — version-mismatched for this section

#### Tier-3 (discovery-only)

* **Internet Archive Wayback captures** of operator blogs covering
  19.x grammar — see search pattern note at end of file
* **Reddit `r/juniper`** — 19.x deployment troubleshooting threads
  occasionally include set-form pastes; sanitisation heavy

---

### 20.x

#### Tier-1.1 — GitHub repositories

* **`srl-labs/multivendor-evpn-lab` spine1.txt / spine2.txt**
  — same repo as above; spine2 is vMX **21.1R1.11** (not 20.x —
  listed under 21.x below) and spine1 is Nokia SROS (not Junos).
  No 20.x Juniper coverage in this lab.

* **`ckishimo/juniper-ztp-upgrade`**
  — https://github.com/ckishimo/juniper-ztp-upgrade
  — license **unspecified**
  — covers Junos upgrade flow on QFX5200 across the version path
  15.1 → 17.4 → 18.4 → **20.2** with snapshot configs at each step
  — grammar: ZTP-flow snapshots; minimal but covers the
  20.x version barrier
  — sanitisation: minor
  — quality: **3/5** — useful for 20.2 in particular; not heavy on
  feature surface
  — form: probably block-form snapshots (typical Junos ZTP output)

#### Tier-1.2 — Vendor docs

* **Juniper TechLibrary — EVPN-VXLAN Edge-Routed Bridging with
  Anycast Gateway**
  — https://www.juniper.net/documentation/us/en/software/junos/evpn/topics/example/evpn-vxlan-collapsed-topology.html
  — license: Juniper docs ("example use")
  — grammar: ERB topology with anycast-gateway IRB; vendor-canonical
  20.x-era reference
  — quality: **5/5**
  — form: set-form

* **Day One Book — "Inside the MX 5G"** (David Roy)
  — https://www.juniper.net/documentation/en_US/day-one-books/DO_MX5G.pdf
  — license: Day One Books are typically **CC-BY-ND** or
  publication-permission grant (verify per-book)
  — covers MX 5G hardware refactor that landed in 20.x
  — grammar: MX-specific (`set chassis network-services
  enhanced-ip`, line-card config), various EX/QFX command
  references
  — quality: 4/5 — extracted excerpts work better than the whole
  book; book is PDF so OCR / copy-paste needed
  — form: set-form excerpts

#### Tier-1.3 — Lab platforms

* **`Juniper-SE/Apstra-configlets`**
  — https://github.com/Juniper-SE/Apstra-configlets
  — license **unspecified** at root; treat as Juniper-SE permissive
  (forum-share precedent), archived 2025-07-01
  — covers Juniper Junos + Arista + Cisco + SONiC configlet
  templates for Apstra fabric-management extensions
  — grammar: Jinja2 templates that render to 20.x-23.x Junos
  configs depending on Apstra version
  — sanitisation: minor (templates are already abstracted)
  — quality: 3/5 — primarily Jinja templates, not committed
  rendered configs; useful as a grammar-surface witness but not a
  direct fixture target
  — form: templates → block-form when rendered

#### Tier-2.1 — Forum / community

* **Juniper Community discussion threads** — 20.x BGP / OSPF /
  EVPN troubleshooting threads with set-form pastes; sanitisation
  heavy
* Forum-share precedent applies (per NOTICE.md HPE Community
  precedent)

---

### 21.x

#### Tier-1.1 — GitHub repositories

* **`srl-labs/multivendor-evpn-lab` spine2.txt**
  — https://github.com/srl-labs/multivendor-evpn-lab
  — license: not declared (forum-share precedent)
  — **vMX 21.1R1.11**
  — grammar: spine in 3-stage Clos; OSPF underlay + iBGP overlay
  route-reflector for EVPN
  — sanitisation: minor
  — quality: **4/5** — first 21.x fixture; vMX in route-reflector
  role complements the existing leaf-heavy corpus
  — form: TBD (containerlab convention is set-form via
  startup-config; needs file inspection)
  — note: same caveat as 19.x leaf3 entry — actual file path / format
  inside the `config/` (or `configs/`) folder needs git-clone verify

* **`jtkristoff/junos`** templates
  — https://github.com/jtkristoff/junos
  — license **unspecified** (12 `.conf` files; author archived /
  unmaintained as of 2021-01)
  — grammar: BGP (iBGP, LOCAL_PREF policies, prefix limits),
  firewall filters, OSPF, BFD, BGP-BMP, IPFIX, ROV (Route Origin
  Validation), ingress loopback protection
  — sanitisation: minor (already templates, no real IPs)
  — quality: **3/5** — template-grade, not version-stamped, but
  written in the 2019-2021 grammar window; useful as a "21.x-era
  reference" target for specific feature areas not covered by
  vendor docs (e.g. BMP, ROV)
  — form: block-form (`.conf` extension; curly-brace hierarchy)

* **`jcoeder/juniper-configurations`**
  — https://github.com/jcoeder/juniper-configurations
  — license **unspecified** (READ as forum-share precedent)
  — ~30+ snippets across MX (dual-RE), QFX5100, QFX/MX MC-LAG,
  EVPN-VXLAN, SRX (out of scope), EX, plus BGP policies, OSPF
  exports, prefix-lists, firewall rules, chassis redundancy,
  SNMP, TACACS, routing-instances, IPFIX
  — sanitisation: minor
  — quality: **3/5** — wide surface, light depth per file
  — form: **mixed set-form + block-form** (per the WebFetch
  inspection — useful for the codec parity story since both
  forms get exercised by separate snippets in the same repo)

#### Tier-1.2 — Vendor docs

* **Day One Book — "Junos Ambassadors' Cookbook"** (multiple years)
  — https://higherlogicdownload.s3.amazonaws.com/JUNIPER/MigratedAssets3/DO_Ambassadors_2014.pdf
  (2014 ed) + more recent editions on Juniper TechLibrary
  — license: Day One Books (verify per-book)
  — grammar: MSTP on QFX5100, EVPN configs, various vendor-canonical
  recipes
  — quality: 4/5 — vendor-vetted; extraction-friendly
  — form: set-form excerpts

#### Tier-1.3 — Lab platforms

* **`netlab.tools` / `ipspace/netlab`** examples
  — https://github.com/ipspace/netlab
  — license **GPL-3.0** (verify; some examples may have different
  per-example licenses)
  — covers Junos vMX / vQFX / vJunos-router/-switch labs across
  21.x-25.x via YAML topology + auto-generated configs
  — grammar: OSPF / IS-IS / BGP / EVPN-VXLAN with anycast-gateway;
  netlab generates per-platform configs from intent
  — quality: 3/5 — value depends on running `netlab create` and
  capturing the generated output; the *templates* aren't direct
  fixtures, but the *generated configs* are real Junos shape
  — form: set-form (netlab default for Junos)
  — caveat: **GPL-3.0 conflicts with Netcanon's permissive fixture
  policy** — captured *generated output* might be OK as
  derivative-work (the device runs the generated config; the
  config-as-text is the operator's own composition), but consult
  before pulling

#### Tier-2.1 — Forum / community

* **`ipspace.net` blog (Ivan Pepelnjak)** — multiple posts in 2021
  covering Junos vMX / vQFX EVPN labs
  — forum-share precedent for excerpts
  — quality: 4/5 for inspiration; treat as inspiration not direct
  import

---

### 22.x

#### Tier-1.1 — GitHub repositories

* **`Juniper-SE/apstra-freeform`** — CRB_stage3 templates +
  freeform Jinja
  — https://github.com/Juniper-SE/apstra-freeform
  — license **unspecified** at root (Juniper-SE org permissive
  intent assumed); **archived 2025-07-01**
  — covers Apstra 4.1-4.2 design templates — match the 22.x-23.x
  Junos grammar epoch
  — grammar: 3-stage CRB Clos, small-london-underground topology,
  ESXi-demo, NFD-TFL demo
  — quality: **4/5** — Jinja templates render to block-form Junos;
  the templates themselves are the grammar-surface witnesses
  — form: templates → block-form Junos

#### Tier-1.2 — Vendor docs

* **Day One Book — "Apstra Freeform"** (Juniper publication)
  — https://www.juniper.net/documentation/jnbooks/us/en/day-one-books
  — license: Day One Books
  — grammar: Freeform blueprint design + per-device config
  templating
  — quality: 4/5 — vendor-vetted reference for 22.x Apstra-managed
  fabrics

* **Juniper documentation portal — Apstra 4.2 / 5.0 Cloudlabs lab
  guides**
  — https://cloudlabs.apstra.com/labguide/Cloudlabs/6.0.0/lab1-junos/
  — license: Juniper docs (excerpt with attribution)
  — grammar: 5-stage IP fabric + EVPN-VXLAN
  — quality: 4/5

#### Tier-1.3 — Lab platforms

* **Juniper vLabs** sandbox configs (login-gated)
  — https://jlabs.juniper.net/vlabs/
  — license: ToS-bound but operator-exportable per the demo's intent
  — grammar: per-lab variation across MX / QFX / vJunos
  — quality: 3/5 — login-gated means harder to pull but the configs
  themselves are fair-game once exported

#### Tier-2.x — Forum / community / blog

* **`packetswitch.co.uk` blog — vJunos-router in Containerlab**
  — https://www.packetswitch.co.uk/juniper-vjunos-router-in-containerlab/
  — covers 22.x-era vMX/vJunos-router lab configs
  — forum-share / blog precedent for excerpts

* **`saidvandeklundert.net` — Junos and all things syslog (and
  many other posts 2015-2024)**
  — covers 22.x-era syslog + system configs in set-form
  — quality: 4/5 inspiration

---

### 23.x / 24.x (modern)

#### Tier-1.1 — GitHub repositories

* **`Juniper-SE/Apstra-configlets`** — Junos folder
  — same repo as 20.x entry
  — archived 2025-07; Apstra-freeform 5.x = Junos 23.x/24.x grammar
  — quality: 3/5
  — form: templates → block-form

* **`Ihemail/vJunos_on_Proxmox`**
  — https://github.com/Ihemail/vJunos_on_Proxmox
  — license **unspecified**
  — base-config startup scripts for vJunos-switch / vJunos-router /
  vJunosEvolved on Proxmox 8.2
  — grammar: minimal startup configs (hostname + mgmt + user)
  — quality: 2/5 — too thin to be a grammar-density fixture
  — form: set-form (vrnetlab convention)

* **`ddella/JunOS`**
  — https://github.com/ddella/JunOS/blob/main/vJunOS.md
  — license **unspecified**
  — vJunos lab notes + sample configs
  — quality: 2/5
  — form: set-form

#### Tier-1.2 — Vendor docs

* **Juniper TechLibrary release notes — 23.4R1 / 24.4R1 / 25.4R1**
  — embedded config examples per feature
  — https://www.juniper.net/documentation/us/en/software/junos/release-notes/
  — license: Juniper docs (excerpt with attribution)
  — quality: 5/5 for individual feature snippets but tiny line
  counts per feature — would need stitching across multiple
  release-notes to assemble a full-config-density fixture

* **Day One Book — "Routing the Internet Protocol"** (2023+)
  — https://www.juniper.net/documentation/en_US/day-one-books/DO_Routing_the_IP.pdf
  — license: Day One Books
  — grammar: routing-fundamentals 23.x-era recipes
  — quality: 4/5

#### Tier-1.3 — Lab platforms

* **`srl-labs/containerlab` lab-examples — `srl-vjunosevolved`**
  — https://github.com/srl-labs/containerlab/tree/main/docs/lab-examples
  — license **BSD-3-Clause** (containerlab itself)
  — vJunosEvolved 23.x basic interface config (3-port ping demo)
  — grammar: thin (3 routed interfaces) but **first PTX-class Evo
  capture would close a platform-class gap**
  — quality: 3/5 (thin) but unique platform-class coverage
  — form: set-form (containerlab startup-config convention)

* **`vrnetlab` upstream** — vqfx / vmx Dockerfiles + sample configs
  — https://github.com/vrnetlab/vrnetlab/tree/master/vqfx
  + https://github.com/vrnetlab/vrnetlab/blob/master/vmx/README.md
  — license **MIT** (per repo metadata)
  — vQFX images tag-correspond to Junos versions (15.1X53-D60,
  17.4R1, 18.4R1, 19.4R1, 20.2R1, etc.)
  — grammar: per-image baseline configs (`launch.py` defaults)
  — quality: 3/5 — useful as a baseline-config witness across many
  versions; not feature-dense
  — form: set-form bootstrap

#### Tier-2.x

* **`community.juniper.net` Aninda Chatterjee blog — vJunos-switch
  + Containerlab fabric**
  — https://community.juniper.net/blogs/aninda-chatterjee/2023/10/27/virtual-fabrics-vjunos-switch-and-containerlab
  — vJunos-switch 23.1R1.8 set-form fabric configs
  — forum-share precedent
  — quality: 4/5 (rich grammar + clear license-by-precedent)

* **`vithuslab.net` — Containerlab Startup-Config on vJunos-Switch**
  — https://www.vithuslab.net/post/containerlab-startup-config-on-vjunos-switch
  — vJunos-switch 23.2R1 / 23.4R2 startup-config examples
  — blog/forum precedent

---

### 18.x / 17.x / 16.x / 15.x / 14.x (legacy retrospective)

The existing corpus already covers 15.1, 17.3, 18.4 — these are
mostly **closed gaps**.  Listed here for completeness:

#### Tier-1.1 — GitHub

* **`ksator/lab_management`** — origin of 4 of our 7 existing
  fixtures; license MIT
  — https://github.com/ksator/lab_management/tree/master/backup
  — additional backups beyond the 4 we already use exist
  (`QFX5200-181_config.2017-...`, `MX80-205_config.2017-...`,
  `MX480-200_config.2017-...`, etc.) — all 2017-12-19 captures so
  17.3 / 17.4-era
  — quality: 5/5 if augmenting 17.x density; already-vetted
  provenance; could add MX-platform-class coverage missing today
  — form: set-form

* **`buraglio/Juniper-SR-PCE`** — origin of `buraglio_netlab_junos184.set`;
  ES.net netlab-ns demo
  — quality: 5/5 if augmenting 18.4 density; same provenance class

* **`batfish/lab-validation`** — origin of the 2 × 25.4R1.12
  fixtures
  — https://github.com/batfish/lab-validation/tree/master/snapshots
  — Apache-2.0
  — additional Junos snapshots present: `junos_as_path_acl`,
  `junos_commit_check`, `junos_community_delete`,
  `junos_cross_term_match`, `junos_default_address_selection`,
  `junos_ebgp_loop_prevention`, `junos_l3vpn` (already used),
  `junos_policy_chain_visibility`, `junos_private_asn`,
  `junos_rmw_localpref`, `junos_undefined_prefix_list_export/import`
  — these are likely also 25.x-era given the snapshot batch is
  the same `d40faf6` commit; each is a small targeted feature
  fixture (10-50 lines each) rather than a dense full-config
  — quality: 4/5 each — feature-specific grammar witnesses, not
  full-config-density

#### Tier-1.2 — Vendor docs (retrospective)

* Day One Books archive (CC-BY-style "example use")
  — https://www.juniper.net/documentation/jnbooks/us/en/day-one-books
  — covers 14.x-18.x retrospectively

#### Tier-2.4 — Operator blogs (archived)

* Internet Archive Wayback captures of `juniperdays.com` (Junos-focused
  blog), `roanguigon.com` (Juniper SP routing), `daniels.netdevops.me`
  (Daniel Hertzberg netdevops content) — all listed in
  [`00-source-analysis.md`](00-source-analysis.md) § 2.4
  — primarily for grammar surface inspiration; rewrite as synthetic
  fixtures rather than direct import

---

## Recommended pull priority order

1. **`srl-labs/multivendor-evpn-lab/config/leaf3.txt`** — vQFX
   **19.4R1.10**.  Closes WANTED.md gap #1.  Verify license (no
   LICENSE file at root — needs author email or contributor
   sign-off; failing that, treat as forum-share precedent — same
   class as the HPE Community fixtures).  Verify form (set vs
   block) via git-clone.  **Single most impactful pull.**

2. **`srl-labs/multivendor-evpn-lab/config/spine2.txt`** — vMX
   **21.1R1.11**.  Pairs with #1 to give us 2 gap-year fixtures
   from the same clean lab in one acquisition cycle.

3. **`JNPRAutomate/ansible-junos-evpn-vxlan/config/spine-01.conf`
   (or any of the 10 files in `config/`)** — Junos 19.x reference
   design, **MIT** license, **block-form**.  Adds the first
   block-form fixture to the corpus (the existing 7 are all
   set-form).  Solves the form-coverage gap independent of the
   version gap.

4. **`Juniper/vqfx10k-vagrant`** — light-ipfabric-2S-3L topology
   on Junos **18.4R1** or **19.4R1** box.  Apache-2.0, official
   Juniper org.  Augment 18.4 (light-density `buraglio` fixture
   is only 28 lines today) and/or close 19.4 if a 19.4 vqfx10k
   box exists.

5. **Juniper TechLibrary EVPN-VXLAN CRB MX + QFX example** —
   extract from the public docs.  Vendor-canonical reference
   topology; 5-star grammar quality; sanitisation = none.  Fills
   the gap for a vendor-rigor witness (the existing 25.4 batfish
   fixtures cover EVPN-VXLAN but use lab-validation IPs, not
   vendor reference).

6. **`ksator/lab_management/backup/MX80-205_config.2017-...`** —
   add MX platform-class coverage to the existing ksator family.
   17.3-era; same MIT license.  Currently the corpus only has 1
   MX-class fixture (`buraglio_netlab_junos184.set`, light density);
   a dense MX 17.3 capture would help MX/EX/QFX platform-class
   parity.

7. **`bytesofcloud/Juniper-JNCIS-MCLAG`** — Junos **19.1R3.9** vMX
   MC-LAG configs.  Only well-licensed source for MC-LAG grammar
   (not in corpus anywhere today).  License is murky → contributor
   needs to seek explicit confirmation from the author or paraphrase
   as synthetic fixture inspired by the ZIP contents.

8. **`jcoeder/juniper-configurations`** — mix of set-form + block-form
   snippets.  License unspecified → forum-share precedent.  Useful
   for closing specific feature gaps (MC-LAG, dual-RE, IPFIX,
   TACACS-auth) one snippet at a time rather than a single dense
   fixture.

9. **Apstra-freeform templates rendered for a 22.x deployment** —
   render the `Juniper-SE/apstra-freeform` templates against a
   23.x-25.x vJunos-switch and capture the rendered output.
   Two-step process (template + render + capture) is higher
   friction but produces a controllable 22.x-23.x fixture.

10. **`srl-labs/containerlab` lab-example for vJunosEvolved** —
    closes the PTX-class Evo platform gap (currently absent from
    corpus).  Thin grammar (3 interfaces) but unique platform
    coverage.

---

## Out-of-scope (deliberately excluded)

* **Juniper SRX security-platform fixtures** — covered separately
  in [`12-juniper_srx.md`](12-juniper_srx.md).  Even though SRX
  runs Junos OS, the `security policies / nat / zones / ipsec`
  grammar is a distinct codec scope.
* **Junos Evo as a separate codec** — Evo shares the set-form CLI
  surface with classic Junos and is parsed by the same
  `juniper_junos` codec.  Evo-only platform fixtures (PTX10001/3/4/8,
  QFX5130, QFX5220) are noted above under the relevant version-year
  but don't justify a separate catalogue.
* **Closed-source Juniper customer configs** — explicitly excluded
  per [`BUG_REPORTING.md`](../../BUG_REPORTING.md): "Closed-source
  vendor configs you don't have rights to share."
* **Juniper Apstra blueprint JSON exports** — these are not Junos
  CLI configs; the codec doesn't parse them.  Apstra-rendered Junos
  configs are in-scope (see priority #9).
* **Pastebin / paste.ee anonymous dumps** — too unreliable for
  license-confidence.  Listed in
  [`00-source-analysis.md`](00-source-analysis.md) § 3.1 as
  discovery-only.
* **Juniper Day One Books PDFs** — usable as **inspiration** /
  reference for grammar surface only; treat extracted configs as
  synthetic operator-authored examples rather than direct imports,
  unless the book has explicit reuse permission (verify per-book).
* **Cert prep workbooks (JNCIA / JNCIS / JNCIE)** — copyrighted; do
  not import per
  [`00-source-analysis.md`](00-source-analysis.md) § 3.2.
* **Production-network captures without operator consent** — Tier-4
  in the source taxonomy; off-limits.

---

## Notes on set-form vs block-form

The shipped `juniper_junos` codec parses **both** forms, but the
existing 7-fixture corpus is **100% set-form**.  This catalogue
deliberately calls out form for each pull-target because:

* **Set-form** (`set interfaces ge-0/0/0 unit 0 family inet
  address 10.0.0.1/24`) — what `show configuration | display set`
  emits; operator-preferred for round-trip testing because each
  command is self-contained on one line.  All 7 existing fixtures
  use this form.
* **Block-form** (curly-brace hierarchy:
  `interfaces { ge-0/0/0 { unit 0 { family inet { address
  10.0.0.1/24; } } } }`) — what `show configuration` emits
  natively; what `.conf` extension files typically contain (per
  the `JNPRAutomate/ansible-junos-evpn-vxlan/config/*.conf`
  convention).  **Zero block-form fixtures in corpus today.**

The codec internally normalises block-form → set-form for parsing,
then re-renders back to set-form (the canonical Junos serialisation
output of Netcanon).  A block-form fixture is therefore valuable
as a **round-trip witness**: parse block → canonical → emit set,
then verify the set output matches the equivalent of `display set`
on the source device.

**Recommendation**: pull at least one block-form fixture per
version-bridge (e.g. `JNPRAutomate/ansible-junos-evpn-vxlan/config/spine-01.conf`
for 19.x).  The form gap is independent of the version gap.

---

## Discovery search patterns (Junos-specific)

For agents crawling beyond this catalogue, useful queries:

* GitHub set-form: `language:Text "set system host-name" "set
  routing-options autonomous-system"` (forces both anchors so we
  match real configs, not snippets)
* GitHub block-form: `language:Text "system {" "host-name" "}" "interfaces {"`
* Generic Google: `"show configuration | display set" filetype:txt`
* Forum-specific: `"set version 19" OR "set version 20" OR "set
  version 21" OR "set version 22" site:community.juniper.net`
* Internet Archive: `web.archive.org/web/2018*/juniperdays.com`
  (Junos-focused blog archive)
* Wayback for Day One archive: `web.archive.org/web/2020*/juniper.net/documentation/en_US/day-one-books`
* Pastebin (last-resort): Google `site:pastebin.com "set system
  host-name" junos`

---

## See also

* [`00-source-analysis.md`](00-source-analysis.md) — source-class
  taxonomy referenced throughout (Tier-N.M shorthand)
* [`README.md`](README.md) — folder index + per-OS catalogue ToC
* [`12-juniper_srx.md`](12-juniper_srx.md) — Juniper SRX security
  platform (distinct codec scope, same Junos OS)
* [`tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md)
  — provenance ledger of the 7 existing junos/ fixtures
* [`tests/fixtures/real/WANTED.md`](../../tests/fixtures/real/WANTED.md)
  — gap list (Junos 19-22.x bridge listed as priority #1)
* [`BUG_REPORTING.md`](../../BUG_REPORTING.md) — sanitisation +
  fixture submission workflow (mandatory for every pull-target
  in this catalogue)

### Provenance — authoritative external references

* [Juniper Networks — Junos OS Dates & Milestones (official)](https://support.juniper.net/support/eol/software/junos/)
* [JunosGeek mirror — Junos OS Dates & Milestones (2021 snapshot)](http://junosgeek.blogspot.com/2021/04/junos-os-dates-milestones.html)
* [Lindsay Hill — Juniper Version Selection](https://lkhill.com/juniper-version-selection/)
* [Juniper Day One Books portal](https://www.juniper.net/documentation/jnbooks/us/en/day-one-books)
* [Wikipedia — Junos OS](https://en.wikipedia.org/wiki/Junos_OS)
* [Containerlab — Juniper vMX / vQFX / vJunos-router / vJunos-switch /
  vJunosEvolved kind docs](https://containerlab.dev/manual/kinds/)

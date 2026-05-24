# Aruba AOS-CX — fixture catalogue (2015+)

> **Tier**: Tier-D (no codec yet)
> **Existing corpus**: 0 fixtures
> **Distinct from AOS-S** (different OS, different grammar, different
> platform line — see `04-aruba_aoss.md` for the legacy ProVision
> codec already shipped in `v0.1.1`)

AOS-CX is the modern Aruba switch OS introduced August 2017 with
the Aruba 8400 chassis at HPE Discover 2017.  It is not a successor
to AOS-S in the parser sense — the grammar was redesigned from the
ground up and is **explicitly inspired by Arista EOS** (Aruba hired
ex-Arista engineers when starting the project).  Stanzas are
multi-line with explicit `exit` boundaries; interface names use the
`module/slot/port` triple (`interface 1/1/1` ...
`ip address 10.0.0.1/24` ... `no shutdown` ... `exit`); routing
protocol contexts mirror EOS's `router bgp / address-family X /
neighbor Y` nested structure.  **For an eventual codec author: model
the parser on `arista_eos`, not `aruba_aoss`.**  The two share
nothing beyond the vendor logo.

Hardware-platform-distinctive features:
* **VSX** (Virtual Switching Extension) — Aruba's MLAG/VSS
  equivalent.  Two-chassis cluster with ISL keepalive, shared
  active-gateway, role primary/secondary.  Stanza:
  `vsx / system-mac / inter-switch-link lag N / role primary | secondary / keepalive peer X source Y vrf mgmt`.
* **EVPN-VXLAN** support on the 8325 / 8360 / 8400 / 9300 /
  CX-10000 (data-center) platforms — full IBGP / EBGP EVPN
  underlays with L2VNI + L3VNI symmetric-IRB.  Stanza shape:
  `vxlan / vni N / vlan N / exit` plus `evpn / vlan N / rd auto / route-target export / route-target import` plus `router bgp X / address-family l2vpn evpn`.
* **VSF** (Virtual Switching Framework) — separate stacking
  technology for the 6300 (which does NOT support VSX); analogous
  to Cisco's StackWise.
* **Active-gateway** — anycast-gateway equivalent at the SVI
  (`interface vlan N / active-gateway ip X / active-gateway mac Y`).

## Version timeline
| Version | Release date | Notable platforms | Priority |
|---|---|---|---|
| 10.0 | Aug 2017 (limited GA) | 8400 chassis (first shipping CX platform) | Low (early; obsolete grammar) |
| 10.1 / 10.2 / 10.3 | 2018 | 8400 only | Low (pre-EVPN) |
| 10.4 | 2018-2019 | + 8320 + early 6300 | Low-Medium |
| 10.5 | 2019 | + 6300 GA | Medium (first NAPALM-supported version) |
| 10.6 | 2020 | + 6200 + 8325 + 8360 | Medium-High (first EVPN-VSX) |
| 10.7 | 2020 | + 6100 + 8400v3 | High (first widespread DC fabric deployments) |
| 10.8 | 2021 | + 6200F / 6400v3 | High |
| 10.9 | Dec 2021 | + 6000 series | High |
| 10.10 | 2022 (LSR) | broad portfolio | High (Long Supported Release) |
| 10.11 | 2022-2023 | + CX-10000 (Pensando DPU) | High (modern) |
| 10.12 | 2023 | + 8100 | High (modern) |
| 10.13 | Jan 2024 (LSR — 5-year support) | + 9300 (high-density data center) | **Highest** (current LSR — operator install base settles here) |
| 10.14 | 2024 | + 5420 | High |
| 10.15 | 2024-2025 | + 8325H | High |
| 10.16 | 2025 | (current SSR train) | High (newest grammar surface) |

LSR (Long Supported Release) vs SSR (Short Supported Release) is
worth tracking: 10.10 + 10.13 are LSRs (5-year support window) and
will dominate the operator install base.  Capture priority should
weight LSRs heavily.

## Pull-target inventory

### 10.13+ (current LSR / SSR train)

#### GitHub repositories

* **`crispyfi/clab-aos-cx-demo`** — MIT license, containerlab demo
  with `configs/agg2-config.txt` and other persistent node configs.
  Runs **Virtual.10.13.1110** (build 2025-06-16).  Demonstrates a
  simulator-backed AOS-CX deployment.  This is the strongest single
  pull-target for a 10.13 baseline:
  https://github.com/crispyfi/clab-aos-cx-demo
  Provenance: explicit MIT, clean operator-authored examples,
  no real-environment PII (lab-only).
  Grammar exercised: interface 1/1/X, VLAN, LAG, mgmt VRF,
  spanning-tree, https-server, plus whatever fabric features the
  containerlab topology declares.

* **`Shajeervu/arubavsx`** + **`cheddarking/arubavsx`** — forks of
  the crispyfi codespaces lab; same Virtual.10.13.x simulator
  base, may carry diverged VSX-specific topologies:
  https://github.com/Shajeervu/arubavsx
  https://github.com/cheddarking/arubavsx
  License: check per-fork (likely MIT inherited).
  Quality signal: lab-authored, no PII expected.

#### Vendor docs / lab guides

* **Aruba TechDocs PDF guides for 10.13** — all under HPE Aruba's
  documentation copyright.  Examples are inline configuration
  snippets, NOT bulk runnable configs.  Use as **synthetic-fixture
  inspiration**, not direct import:
  * `https://arubanetworking.hpe.com/techdocs/AOS-CX/10.13/PDF/vxlan.pdf` — EVPN VXLAN guide (6200, 6300, 6400, 8100, 8325, 8360, 8400, 9300, 10000)
  * `https://arubanetworking.hpe.com/techdocs/AOS-CX/10.13/PDF/vsx.pdf` — VSX guide
  * `https://arubanetworking.hpe.com/techdocs/AOS-CX/10.13/PDF/cli_6300-6400.pdf` — Per-platform CLI guide

#### AOS-CX Switch Simulator (vendor-distributed)

* Aruba ships a **free downloadable AOS-CX simulator OVA**
  (registration required, no purchase).  Currently distributing
  10.13.x and 10.14.x images.  EULA at
  `https://www.arubanetworks.com/assets/support/ArubaOS-CX_OVA_EULA.pdf`
  and ALA at
  `https://www.arubanetworks.com/assets/support/ArubaOS-CX_OVA_ALA.pdf`.
  **License caveat**: the simulator itself is proprietary (no
  republication right) but **configs you author by hand on the
  simulator and run `show running-config` against are operator-
  authored** — the same logic that lets pfSense/OPNsense lab
  fixtures be Apache/MIT-licensed by their authors despite the
  underlying OS being separately licensed.  Treat capture from the
  simulator as your-own-work + Apache-2.0 / MIT contribution.

### 10.11-10.12 (modern)

#### GitHub repositories

* **`aruba/aoscx-ansible-dcn-workflows`** — **Apache-2.0 — primary
  pull-target.**  Vendor-published DCN (Data Center Networking)
  workflows.  Contains **`configs/sample_configs/`** with already-
  rendered final-form running-configs across four architectures:
  https://github.com/aruba/aoscx-ansible-dcn-workflows
  * `configs/sample_configs/arch1/` — 2-tier core-only (e.g.
    `Zone1-Core1a-final.conf` — `ArubaOS-CX GL.10.04.0040`,
    110 lines, OSPF + VSX + LAG).
  * `configs/sample_configs/arch3_eBGP/` — 3-tier eBGP-EVPN spine/
    leaf fabric.  Six configs: `Zone1-Spine1-final.conf`,
    `Zone1-Spine2-final.conf`, `Zone1-Rack1-Leaf1a-final.conf`,
    `Zone1-Rack1-Leaf1b-final.conf`, `Zone1-Rack3-Leaf3a-final.conf`,
    `Zone1-Rack3-Leaf3b-final.conf`.  Each ~111 lines.  Leaf configs
    stamped `GL.10.04.0020`; spine configs `GL.10.04.0040`.  Grammar
    exercised: VSX, VXLAN, EVPN, eBGP (multi-AS), LAG, active-
    gateway.
  * `configs/sample_configs/arch3_iBGP/` — iBGP-EVPN variant; same
    six-config shape, OSPF underlay + iBGP EVPN overlay.
  * `configs/sample_configs/arch2/` + `arch4/` — additional two-tier
    + multi-rack variants.

  Grammar surface across the whole set:
  hostname / user / ssh server vrf / vlan N (+ EVPN per-VLAN RD/RT) /
  spanning-tree / lag N / interface 1/1/N (access, uplink, ISL,
  routed-port, mgmt) / interface loopback N / interface vxlan N /
  interface vlan N (+ active-gateway) / vsx / router ospf N /
  router bgp N (+ address-family ipv4 unicast + address-family
  l2vpn evpn) / vxlan N / evpn / vlan N (RD/RT) / https-server.

  Sanitisation needed: heavy (each file has admin password
  ciphertext, real-looking RFC1918 management IPs, BGP ASNs).
  Standard scrub.

  *Note on firmware-version stamping*: The on-disk samples are
  stamped GL.10.04.xx because the repo originated against 10.4-era
  documentation, but the grammar is forward-compatible with 10.11+
  (the dcn-workflows repo continues to be maintained and the
  templates render against newer collections).  For a 10.11/10.12-
  vintage capture, the recommended path is to render the Jinja2
  templates against current Aruba Ansible Collection (Apache-2.0)
  using a 10.11+ inventory.

* **`aruba/aoscx-ansible-collection`** — Apache-2.0.  Vendor-
  maintained Ansible collection (the consumer of the templates
  above).  Tests live under `tests/sanity/`; no integration
  fixtures with full running-configs visible at top level.
  https://github.com/aruba/aoscx-ansible-collection

* **`aruba/aoscx-ansible-workflows`** — Apache-2.0.  Companion
  repo of single-feature playbooks (`configure_vlans.yml`,
  `configure_acl.yml`, `configure_l2_interfaces.yml`,
  `configure_l3_interfaces.yml`, `configure_using_cli_template.yml`,
  `check_firmware_then_upgrade.yml`).  Useful for understanding
  per-feature grammar fragments; less useful for full-config
  capture.
  https://github.com/aruba/aoscx-ansible-workflows

* **`aruba/aoscx-ansible-role`** — Apache-2.0.  Older role variant
  (pre-Ansible-collections).
  https://github.com/aruba/aoscx-ansible-role

* **`aruba/pyaoscx`** — Apache-2.0.  Python SDK; the `workflows/`
  subfolder has imperative-style scripts (e.g.
  `print_system_info.py`) rather than declarative configs, but
  exercises REST-driven config-shape per JSON resource.
  https://github.com/aruba/pyaoscx

* **`aruba/terraform-provider-aoscx`** — Apache-2.0.  HCL examples
  for VLAN / interface / L2-interface resources.  Useful for the
  declarative-shape comparison.
  https://github.com/aruba/terraform-provider-aoscx

#### Forum / community posts (HPE Community)

* `community.hpe.com` → HPE Aruba Networking section.  AOS-CX
  threads grew sharply 2022-2024 as the install base expanded.
  Search pattern: `site:community.hpe.com "AOS-CX" "show running-config"`.
  The simulator-promotion thread itself (`community.hpe.com/t5/network-simulator/improve-your-networking-skills-with-the-aos-cx-switch-simulator/td-p/7133803`)
  often spawns config-show follow-ups.
  Provenance: forum-share precedent already used for AOS-S
  fixtures (see `04-aruba_aoss.md`); operators paste with
  troubleshoot-intent.  Heavy sanitisation expected.
  Quality signal: medium-high (operator-paste with implicit
  share intent).

#### Vendor docs / lab guides

* **Aruba Developer Hub `developer.arubanetworks.com/aoscx`** —
  the four "Architecture III" reference designs include
  expandable code-blocks with full final-form configs:
  * `architecture-iii-dedicated-data-center-layer-3-spineleaf-topology-ebgp-evpn-multi-as-vxlan-with-vsx`
    — same six-config set as the dcn-workflows arch3_eBGP folder
    (versions `GL.10.04.0020` + `GL.10.04.0040`).
  * `architecture-iii-dedicated-data-center-layer-3-spineleaf-topology-ibgp-evpn-vxlan-with-vsx`
    — iBGP variant.
  License: **no explicit CC-BY**; Aruba developer docs ship under
  HPE's general doc terms.  Treat as fair-use excerpt for grammar
  reference; pull the dcn-workflows GitHub copies (Apache-2.0)
  for actual import.

* **HPE Aruba TechDocs PDF guides** — same caveat as 10.13:
  inline snippets only, copyrighted, useful as inspiration.

### 10.7-10.10 (transitional)

#### GitHub repositories

* The dcn-workflows configs were originally rendered against
  ~10.4 imagery but the *grammar surface* (VSX + EVPN + VXLAN +
  per-VLAN EVPN RD/RT) is essentially the same as what shipped
  in 10.7-10.10.  The version-banner stamp is the smallest
  difference; reformatting the banner to `GL.10.10.xxxx` keeps
  the fixture meaningful for a 10.10 codec regression.

* **`BrettVerney/cliSnips`** — MIT.  Includes an `Aruba AOS-CX/`
  directory with feature-focused snippets:
  `checkpoints.txt`, `factory_reset.txt`, `firmware_management.txt`,
  `smart_link.txt`, `spanning-tree_RPVST.txt`, `tacacs_mgmt.txt`,
  `vsf_stacking.txt`, `vsx.txt`.  Each is a feature fragment, not
  a full running-config.  Useful for exercising single-stanza
  grammar variants (e.g. the VSF stack stanza, distinct from
  VSX) where the dcn-workflows configs don't cover.
  https://github.com/BrettVerney/cliSnips
  Sanitisation: minimal — these are operator-authored snippets
  with no real-IP / no-password content.

#### Forum / community posts

* HPE Community AOS-CX threads from 2020-2022 — same query
  approach as above; volume grows monotonically per year.
  Heavy sanitisation per operator-paste norm.

### 10.0-10.6 (early retrospective; lower priority)

#### GitHub repositories

* **`napalm-automation-community/napalm-aruba-cx`** — Apache-2.0.
  Documents "AOS-CX firmware should be version **10.05** or later"
  as the minimum supported; the `napalm_aoscx/` directory is the
  driver code itself.  No `tests/fixtures/` directory visible at
  the README level; the driver is REST-API-based so its testing
  pattern is JSON mocks, not CLI text fixtures.  Low priority for
  a CLI-grammar codec.
  https://github.com/napalm-automation-community/napalm-aruba-cx

* The dcn-workflows `GL.10.04.0020` + `GL.10.04.0040` configs
  literally hit this version window.  They are doubly useful:
  (a) as a 10.4-era retrospective capture and (b) as a
  forward-port template for 10.11+.

#### Vendor docs / lab guides

* `arubanetworking.hpe.com/techdocs/AOS-CX/10.06/PDF/vxlan.pdf` —
  the **first VXLAN/EVPN guide** for AOS-CX; codifies the
  EVPN-VSX support matrix as it was at 10.06.  Grammar is
  near-identical to current; the parser interest in 10.04-10.06
  is largely about edge-case stanzas that were later deprecated
  (e.g. earlier `evpn` stanza ordering before consolidation).

#### Other

* **Internet Archive `web.archive.org`** — for 10.0-10.3
  retrospective.  AOS-CX 10.0 was 8400-only and limited GA; very
  little public config exists for that vintage.  Treat as
  archaeological interest only.

### Cross-cutting non-vendor sources

#### Operator blogs (synthesis only — heavy redaction or
operator-authored synthetic examples)

* **CrispyFi Blog** (`blog.crispyfi.com`) — Tobias / CrispyFi
  publishes AOS-CX containerlab walkthroughs ("Aruba CX
  Infrastructure as Code Lab with Containerlab in Google Cloud
  Platform", "Aruba CX lab with Containerlab and GitHub
  Codespaces").  Same author as the `crispyfi/clab-aos-cx-demo`
  repo above.  Blog posts excerpt configs from the repo + add
  walkthrough commentary.  Cite the GitHub repo for import; cite
  blog for grammar-context.

#### YouTube + recorded training

* **Aruba Networks official YouTube** — has AOS-CX feature demos
  with on-screen `show running-config` output.  Transcript-only;
  capture by re-typing or running the demonstrated commands on
  the free simulator.

## Recommended pull priority order

1. **`aruba/aoscx-ansible-dcn-workflows/configs/sample_configs/`**
   — Apache-2.0, vendor-published, **12 full configs across 4
   architectures** with VSX + EVPN + VXLAN + BGP + OSPF grammar
   all present.  Single highest-leverage import for the entire
   Tier-D AOS-CX bring-up.  Start with `arch3_eBGP/Zone1-Spine1-final.conf`
   + `arch3_eBGP/Zone1-Rack1-Leaf1a-final.conf` as the first
   two fixtures — they cover the spine + leaf grammar shapes in
   one EVPN-VXLAN data-center deployment.
2. **`crispyfi/clab-aos-cx-demo`** — MIT, runs Virtual.10.13.1110,
   currently-current LSR-grammar capture.  Pull `configs/*.txt`
   for a 10.13 fixture pair alongside the dcn-workflows 10.4-era
   pair to bracket the version window.
3. **`BrettVerney/cliSnips/Aruba AOS-CX/vsx.txt`** + `vsf_stacking.txt`
   — MIT, feature-fragment grammar that the dcn-workflows configs
   don't cover (specifically the VSF stack stanza on 6300).
4. **AOS-CX free simulator + operator-authored config** — render
   a synthetic 10.13 / 10.14 / 10.16 LSR-class config locally on
   the simulator and contribute under your own Apache-2.0 / MIT
   declaration.  This is the cleanest path to a fixture targeting
   10.13+ grammar with zero attribution overhead.
5. **HPE Community forum captures** — only after the above are
   in.  Heavy sanitisation; useful for closing edge-case grammar
   gaps (e.g. third-party-platform interop quirks the vendor
   examples don't show).
6. **Aruba Developer Hub architecture pages** — same configs as
   #1 but in HTML form with no explicit license.  Don't import;
   use as a sanity check that the GitHub repo's `*.conf` files
   match the canonical reference designs.

## Out-of-scope

* **NAPALM-aoscx test fixtures** — driver is REST-API-driven; no
  CLI-text fixtures to import.
* **Aruba Central / SDN-controller-rendered configs** — Aruba
  Central can render AOS-CX configs from intent.  The
  `aruba_central_5memberstack_rendered.cfg` in the existing
  AOS-S corpus is a precedent for that path, but the Central
  CX template fleet is younger and we haven't found a comparable
  public-domain Central-CX export yet.
* **`aruba/terraform-provider-aoscx` HCL examples** — HCL is not
  the AOS-CX grammar; it's an IaC abstraction.  Useful for
  declarative-shape comparison only.
* **`aruba/pyaoscx` workflows** — REST/JSON, not CLI text.  Out
  of scope for a CLI codec.
* **Aruba certification training material** (ACMA / ACMP / ACDX
  for CX) — paywalled HPE Education content; copyright-respecting
  exclusion.
* **AOS-CX `show tech-support` bundles posted to support tickets**
  — TSR-style multi-file archives; not standalone running-configs
  and may contain PII even after sanitisation.
* **CX-10000 Pensando DPU-specific stanzas** — distinct
  `pensando` / `dss` (distributed services switch) sub-grammar
  that only the CX-10000 emits.  Defer to a v0.3.0+ refinement
  pass once the base AOS-CX codec lands.

## See also

* [`WANTED.md` Tier-D entry](../../tests/fixtures/real/WANTED.md#tier-d--entirely-new-codec-opportunities)
  — Aruba AOS-CX listed as "Modern Aruba replacing AOS-S".
* [`04-aruba_aoss.md`](04-aruba_aoss.md) — the legacy ProVision
  catalogue.  Useful contrast: AOS-S share-precedent on HPE
  Community thread captures applies equally to AOS-CX, but the
  grammar models DO NOT cross over.
* [`03-arista_eos.md`](03-arista_eos.md) — the architectural
  model the AOS-CX parser should mirror.  Multi-line stanzas
  with explicit `exit` boundaries, `router bgp / address-family
  / neighbor` nesting, `interface Ethernet1` → `interface 1/1/1`
  swap, `ip address virtual` (Arista anycast/VARP) →
  `active-gateway ip` (AOS-CX anycast) equivalence.
* [`00-source-analysis.md`](00-source-analysis.md) — meta-analysis
  of source TYPES, license tiers, and discovery patterns.

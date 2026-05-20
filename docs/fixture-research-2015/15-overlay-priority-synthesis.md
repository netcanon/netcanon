# 15 — Overlay-priority synthesis

> **Purpose.**  Translate the 14 per-OS fixture catalogues
> (`01-cisco_iosxe.md` through `14-pfsense.md`) into a concrete
> overlay-authoring backlog for `definitions/<vendor>/<os>/<version>.yaml`.

The catalogues identify where to find real configs.  This
document identifies which **per-version overlay YAMLs**
those real configs unblock — the leverage point the catalogue
research was commissioned to inform.

---

## What "version overlay ability" means concretely

`definitions/<vendor>/<os>/<version>.yaml` files are the
**connection-layer + prompt-behavior overlay** netcanon uses to
talk to a device of a specific OS version.  Each YAML carries:

* `prompts.trailing` — regex for the version's CLI prompt shapes
  (a Cat 9300 on 17.12 has a tighter `(config[^)]*)#` prompt than
  the 17.x family base catches)
* `connection` block — `needs_enable`, `cisco_more_paging`,
  `opnsense_shell_menu`, etc.
* `commands` — per-version `show running-config` syntax + pre /
  post-command surface
* `file_extension`, `collector.strategy`, `collector.netmiko_device_type`
* `probe` block (optional — version-specific probe variants)

The longest-match resolver picks the most specific version YAML for
a pinned `DeviceTarget`; un-pinned targets fall back to the family
base (`17.x.yaml`).

**Distinct from codec-level parse/render grammar.**  The codec's
parse + render is mostly version-agnostic (the `cisco_iosxe_cli`
codec parses IOS 12.4 through IOS-XE 17.x with the same dispatch
table; per-version edge cases get fixed at the codec layer, e.g.
the channelized sub-interface render fix in `f52489c`).
**Overlays carry the device-talking concerns** (how to log in,
what prompts to look for, what `show` command to run).  A
fixture-pull informs an overlay by exposing the per-version
prompt + paging + command shape we need to handle.

---

## Current overlay state (the gap to close)

As of v0.1.1 (commit `5c928e5`):

| OS | Family bases | Version overlays | Versions in catalogue | Coverage gap |
|---|---|---|---|---|
| Arista EOS | none | `4.32.yaml` only | 4.14 – 4.36 (~22 majors) | **~95% un-covered** |
| Aruba AOS-S | `16.x.yaml` | none | 7 branches × major.minor | **~95% un-covered** (single family) |
| Cisco IOS-XE | `17.x.yaml` | `17.12.yaml` | 16.x (4 trains) + 17.x (5 trains) + 3.x | **~85% un-covered** |
| FortiGate | `7.x.yaml` | none | 5.x / 6.0 / 6.2 / 6.4 / 7.0 / 7.2 / 7.4 / 7.6 | **~88% un-covered** (no train granularity) |
| Juniper Junos | `22.x.yaml` | none | 14.x – 25.x (12 majors) | **~92% un-covered** |
| MikroTik RouterOS | `7.x.yaml` | none | 6.x + 7.x | **~80% un-covered** (no platform-class variants) |
| OPNsense | `25.x.yaml` | none | 15.1 – 26.1 (22 majors) | **~95% un-covered** |
| **TOTAL** | **7 files** | **8 files** | **~95 majors across 7 shipped OSs** | **~88% gap** |

The 7 Tier-D OSs (Cisco NX-OS / Cisco IOS-XR / Cisco IOS classic /
Aruba AOS-CX / Juniper SRX / VyOS / pfSense) have **zero** overlay
coverage because their codecs don't ship yet.  When those codecs
land in v0.3.0+, each will need its own family-base YAML plus
per-major overlays.

---

## Catalogue findings — one-paragraph summary per OS

### Cisco IOS-XE (`01-cisco_iosxe.md`, 695 lines)

Catalogues 8 release trains × 28 sub-versions.  **Headline pull
target**: `myhomenwlab/Initial_configuration_of_C9800-CL_*`
(MIT, every point release 17.9 → 17.16 on the Catalyst 9800-CL
wireless LAN controller).  Single-handedly closes the WANTED.md
17.13+ gap AND introduces first wireless-grammar capture.
Secondary: `batfish/lab-validation` IOS-XE snapshots (16 unmined,
VRF / BGP / EIGRP variants); CiscoDevNet/cml-community CCNA labs.

### Juniper Junos EX / QFX / MX (`02-juniper_junos.md`, 812 lines)

Documents 14.x → 25.x quarterly majors with FRS/EoE/EoS dates from
Juniper's Dates & Milestones page.  Catalogue spans 12 majors;
corpus has 4 (15.1 / 17.3 / 18.4 / 25.4 — 4-year 19-22 gap).
**Headline pull target**: `srl-labs/multivendor-evpn-lab` —
vQFX 19.4R1.10 + vMX 21.1R1.11 in one repo, closes the gap in
one bulk pull.  Block-form coverage is a separate gap;
`JNPRAutomate/ansible-junos-evpn-vxlan` ships block-form Junos
19.x EVPN-VXLAN configs under MIT.

### Arista EOS (`03-arista_eos.md`, 445 lines)

Catalogues 4.14 → 4.36.  **Headline pull target**:
`aristanetworks/avd` (Apache-2.0, official Arista repo, 9 example
bundles with `intended/configs/*.cfg` — including
`single-dc-l3ls`, `isis-ldp-ipvpn`, `cv-pathfinder` SD-WAN,
`single-dc-l3ls-ipv6`).  Secondary: batfish has 18 EOS snapshots
including several on **4.36 engineering build** (BGP-unnumbered
grammar absent from corpus today).  Closes the WANTED.md 4.27+
gap in a single AVD bulk pull.

### Aruba AOS-S (`04-aruba_aoss.md`, 536 lines)

Two scope corrections vs WANTED.md: **RA branch is 2620, not
2540** (YC is 2540); **8400 chassis is AOS-CX**, not AOS-S (doc
typo).  **Headline pull target**: `HPENetworking/HPEIMCUtils`
(Apache-2.0, first-party HPE ZTP configs covering 2530 / 2920 /
3800 / 5400 / 5400R).  Closes 4 branch gaps in ~5 minutes.
Secondary: HPE Community thread 7095676 — 3810M with VRRP grammar
(unblocks the v0.2.0 VRRP wire-up real-capture gap).

### Fortinet FortiOS (`05-fortigate.md`, 547 lines)

Catalogue spans 5.x → 7.6.x.  **Headline pull targets** for the
three WANTED.md gaps:
- **6.4.x**: batfish/lab-validation has 2 FortiOS 6.4.4 captures
  (`fortios_first_basic` + `fortios_fw_policy_basic`) under
  Apache-2.0 — one PR closes the gap with a license source we
  already use.
- **7.0 / 7.4**: `fortinet/4D-Demo` (MIT, official Fortinet org)
  has dedicated per-version SD-WAN reference configs.
- **IPsec-heavy**: 4D-Demo dual-hub variants partially serve;
  `leandropinheiro/FORTIGATE-HANDSON` (CC-BY-SA-4.0) has full
  FortiOS 6.0.2 IPsec-heavy capture (would introduce a new
  license class — review needed).

### MikroTik RouterOS (`06-mikrotik_routeros.md`, 582 lines)

Documents 6.30 → 7.22.  **Headline pull target**:
`yottabit42/routeros` (BSD-3, explicit v7.1.1 tag — closes the
WANTED.md "early v7" gap).  Secondary: `Benewend/mikrotik-config-
templates` + additional Taqavi scenarios (MIT, zero license
vetting cost).

### OPNsense (`07-opnsense.md`, 374 lines)

Documents 15.1 → 26.1 (22 majors at semi-annual cadence).
**Headline pull target**: `opnsense/docs` ships a CARP HA pair
example at
`source/manual/how-tos/resources/Carp_example_master.xml` +
`Carp_example_backup.xml` under BSD-2-Clause.  Single PR closes
the corpus's biggest real-capture absence (the v0.2.0 codec wires
CARP grammar but has zero `<virtualip><mode>carp</mode>` fixtures
today).  Secondary: bulk-pull from `opnsense/core` at each
`22.1/22.7/23.1/...` release tag closes the version-bridge gap.

### Cisco NX-OS (`08-cisco_nxos.md`, 544 lines, Tier-D)

Documents 6.x → 10.x.  Extends `docs/v0.2.0-planning/03-nxos-
codec/05-fixture-targets.md` with non-batfish targets:
`yakiimo-bsp/n9kv-evpn-vxlan-lab` (BSD-3, 10.x EVPN-VXLAN);
`christung16/vxlan_in_a_box` (BSD-3, 9.2.3); NAPALM mocked-data
tree (Apache-2.0, fills N9K-hardware-vs-N9Kv gap).  Catalogue
deliberately doesn't duplicate the 13-row batfish table the
planning doc already curates — see that doc for the canonical
pull list when the codec ships.

### Cisco IOS-XR (`09-cisco_iosxr.md`, 585 lines, Tier-D)

Documents 5.x → 24.x with the 7.10 → 24.x rebrand called out.
**Headline pull target uncovered**: `ios-xr/xrd-tools`
(Apache-2.0, Cisco-maintained official org).  Five multi-node
topologies under `samples/xr_compose_topos/`: `simple-bgp`,
`ospf-bgp-rr`, `isis-ipfrr`, `segment-routing` (8 nodes),
`srv6-l3vpn`.  Verified by direct file inspection — closes
batfish's SR + SRv6 + flex-algo + PCE gap entirely.  Audience
analysis remains narrow (~1.5 orders-of-magnitude fewer routers
than NX-OS) but per-fixture grammar density is high.

### Cisco IOS classic (`10-cisco_ios_classic.md`, 321 lines, Tier-D)

Documents 12.4(15)T → 15.9.  Notes existing corpus reality: two
IOS-classic captures already live under `cisco_iosxe/`
(`cml_basic_forwarding_iosv_r1_ospf.txt` + `batfish_iosxe_basic_
vrrp.txt`) because the codecs share ~90% of parse path.
**Recommendation in catalogue**: treat IOS-classic as a
`syntax_flavor: ios_classic` discriminator on the existing
`cisco_iosxe_cli` codec rather than a parallel codec.  Best pull:
`batfish/lab-validation` has 6 IOS-classic snapshots totaling
~30 configs (15.2 / 15.7 grammar).

### Aruba AOS-CX (`11-aruba_aoscx.md`, 376 lines, Tier-D)

Documents 10.0 → 10.16.  **Headline pull target**:
`aruba/aoscx-ansible-dcn-workflows` (Apache-2.0) under
`configs/sample_configs/` — **12 already-rendered final-form
running-configs** across 4 architectures (2-tier core, eBGP-EVPN
spine/leaf, iBGP-EVPN spine/leaf, multi-rack).  Each ~110 lines,
stamped `ArubaOS-CX GL.10.04.0020`/`GL.10.04.0040`.  Closes
codec-bring-up corpus in one repo.  **Architectural call-out
from catalogue**: AOS-CX grammar is explicitly modelled on Arista
EOS (Aruba hired ex-Arista engineers) — future codec author
should mirror `arista_eos` parser shape, NOT `aruba_aoss`
ProVision shape.

### Juniper SRX (`12-juniper_srx.md`, 434 lines, Tier-D)

Documents 15.1X49 → 23.x with hardware-tier breakdown (SRX300
branch / SRX1500-5800 DC).  Three license-significant findings:
(1) Day One Books are **© Juniper Networks, free-to-download
but NOT CC-BY** — WANTED.md mischaracterised this; use as
inspiration not direct import; (2) `batfish/parsing-tests/
srx-testbed` has 3 Apache-2.0 SRX configs on Junos 15.1X49-D15.4
(IKE + IPsec + zones + policies + screen — closes seed-corpus
gap); (3) future SRX codec can share ~70% of `juniper_junos`
parse scaffolding.

### VyOS (`13-vyos.md`, 377 lines, Tier-D)

Documents 1.1 Helium → 1.5 Circinus.  **License findings**:
`vyos/vyos-1x` smoketest configs are the largest corpus (50+
purpose-built fixtures) but the repo is LGPL-2.1 — arguably
bare config text is data not derivative, but conservative
approach is to flag for maintainer-clearance.  Four community
Apache-2.0 repos clear cleanly: `binaryn3vus/VyosConfig`,
`onedr0p/vyos-config`, `bjw-s/vyos-config`, `budimanjojo/vyos-
config`.  `docs.vyos.io` was assumed CC-BY-NC-SA but actual
license is murkier — excluded from pull targets.  Forum-share
precedent is exceptionally strong for VyOS (docs explicitly
teach `show configuration commands | strip-private` as the
forum-paste idiom).  Architectural note: VyOS set-form syntax is
Vyatta-derived and Junos-set-form-compatible at the tokeniser
level — codec could share `juniper_junos` set-form tokeniser.

### pfSense (`14-pfsense.md`, 177 lines, Tier-D)

**Headline correction**: `pfsense/pfsense` is **Apache-2.0**,
not BSD as WANTED.md assumed.  Improves the license-compatibility
story.  **Headline pull target**:
`sheridans/pfopn-convert/fixtures/pfsense-base.xml` (BSD-2,
pfSense 23.3 / Plus, sanitised, ~2,100 lines covering
interfaces / dhcpd / openvpn / wireguard / snmpd / unbound /
gateways).  **Codec-sharing-with-OPNsense feasibility: STRONGLY
RECOMMENDED** — ~70% of OPNsense codec's parse / render paths
transfer directly (identical `<system>`, `<interfaces>`,
`<vlans>`, `<dhcpd>`, `<snmpd>`, `<virtualip>` shapes; CARP HA
primitive).  Real divergences: root tag (`<pfsense>` vs
`<opnsense>`), user-password element, Kea DHCP backend (pfSense
2.7+/Plus 23+, OPNsense doesn't), WireGuard XPath prefix
(root vs `<OPNsense>` namespace).  Recommend a
`pfsense_opnsense_xml` shared codec with root-tag dispatcher —
estimated 30% of from-scratch cost.

---

## Per-OS overlay-authoring priority

For each shipped-codec OS, the per-version overlay YAML
authoring backlog, ranked by leverage (capture availability ×
operator deployment density × prompt-shape variance).

### Cisco IOS-XE

| # | Overlay file | Evidence (capture) | Estimated delta carried | Priority |
|---|---|---|---|---|
| 1 | `definitions/cisco/ios-xe/16.x.yaml` (family base) | racc CSR1000v 16.9 already in corpus | 16.x train uses pre-17.x prompt + `vlan internal allocation` defaults differ | **P1** (closes 4-year retrospective gap) |
| 2 | `definitions/cisco/ios-xe/17.3.yaml` | racc CSR1 17.3 already in corpus | Amsterdam-era prompt + first-tier 17.x defaults | **P2** |
| 3 | `definitions/cisco/ios-xe/17.9.yaml` | racc Cat8000V 17.9 already in corpus | Cupertino-era | **P2** |
| 4 | `definitions/cisco/ios-xe/17.16.yaml` | NEW: myhomenwlab/C9800-CL pull | C9800-CL WLC-class prompts; closes 17.13+ gap | **P1** |
| 5 | `definitions/cisco/ios-xe/16.9.yaml` (specific) | racc 16.9 already in corpus | LTS-era; pre-Catalyst-9000 | **P3** |
| 6 | `definitions/cisco/ios-xe/3.x.yaml` retrospective | Internet Archive blog pulls | Pre-IOS-XE-rebrand era | **P4** |

**Wave 1 net additions: 4 IOS-XE overlays.**

### Juniper Junos

| # | Overlay file | Evidence | Delta | Priority |
|---|---|---|---|---|
| 1 | `definitions/juniper/junos/19.x.yaml` | NEW: srl-labs/multivendor-evpn-lab leaf3 (19.4) | Closes WANTED.md priority #1 gap; pre-2020 prompts + paging | **P1** |
| 2 | `definitions/juniper/junos/20.x.yaml` | Spec-search needed (catalogue identifies candidates) | Spans 2020 release window | **P1** |
| 3 | `definitions/juniper/junos/21.x.yaml` | NEW: srl-labs/multivendor-evpn-lab spine2 (21.1) | Same repo as 19.4 | **P1** |
| 4 | `definitions/juniper/junos/17.x.yaml` (family base) | ksator QFX5100 / QFX5110 17.3 already in corpus | Closes Wave-A retrospective | **P2** |
| 5 | `definitions/juniper/junos/18.x.yaml` (family base) | buraglio 18.4 already in corpus | Same | **P2** |
| 6 | `definitions/juniper/junos/15.x.yaml` (family base) | ksator EX4550 15.1 already in corpus | Same | **P3** |
| 7 | `definitions/juniper/junos/25.x.yaml` (already has 22.x; clarify) | batfish 25.4 already in corpus | Current GA | **P2** |
| 8 | `definitions/juniper/junos/23.x.yaml` | New pull needed | Bridge gap | **P3** |
| 9 | `definitions/juniper/junos/24.x.yaml` | New pull needed | Bridge gap | **P3** |

**Wave 1 net additions: 6 Junos overlays.**

### Arista EOS

| # | Overlay file | Evidence | Delta | Priority |
|---|---|---|---|---|
| 1 | `definitions/arista/eos/4.30.yaml` | NEW: aristanetworks/avd single-dc-l3ls (4.30+) | EVPN underlay grammar changes per WANTED.md; new prompt mode-changes | **P1** |
| 2 | `definitions/arista/eos/4.28.yaml` | NEW: arista-netdevops-community webinar configs | Closes 4.27-4.29 gap | **P1** |
| 3 | `definitions/arista/eos/4.26.yaml` | karneliuk A-EOS1 4.26 already in corpus | Closes retrospective | **P2** |
| 4 | `definitions/arista/eos/4.23.yaml` | batfish DC1-LEAF2A + H-LEAF2A 4.23 already in corpus | LSR-era | **P2** |
| 5 | `definitions/arista/eos/4.22.yaml` | ksator DCS-7150S 4.22 already in corpus | Same | **P2** |
| 6 | `definitions/arista/eos/4.21.yaml` | batfish DuplicatePrivate 4.21 already in corpus | Earliest in corpus | **P3** |
| 7 | `definitions/arista/eos/4.36.yaml` | NEW: batfish 4.36-engineering | BGP-unnumbered new grammar | **P2** |

**Wave 1 net additions: 6-7 Arista overlays.**

### Aruba AOS-S

| # | Overlay file | Evidence | Delta | Priority |
|---|---|---|---|---|
| 1 | `definitions/aruba/aos-s/YA.yaml` | NEW: HPENetworking/HPEIMCUtils 2530 fixtures | Closes WANTED.md YA-branch gap; 2530-class | **P1** |
| 2 | `definitions/aruba/aos-s/YC.yaml` | Spec-search (2540 capture) | Closes 2540 (RA was mis-attributed in WANTED.md) | **P1** |
| 3 | `definitions/aruba/aos-s/KA.yaml` | NEW: HPENetworking/HPEIMCUtils 5400R fixtures | 5400R legacy | **P2** |
| 4 | `definitions/aruba/aos-s/KB-16.04.yaml` | HPE Community 3810M VRRP capture | First fine-grained branch overlay; introduces VRRP grammar real-capture | **P1** |
| 5 | `definitions/aruba/aos-s/RA.yaml` | Spec-search (2620 capture) | 2620 family — WANTED.md said "RA = 2540" but it's actually 2620 | **P2** |
| 6 | `definitions/aruba/aos-s/15.x.yaml` (legacy retrospective) | Existing 5406Rzl2 KB.15.15 | Pre-16.x branch | **P3** |

**Wave 1 net additions: 4 AOS-S overlays.**

### Fortinet FortiOS

| # | Overlay file | Evidence | Delta | Priority |
|---|---|---|---|---|
| 1 | `definitions/fortigate/fortios/6.4.yaml` | NEW: batfish fortios 6.4.4 captures | Closes WANTED.md 6.4 SMB gap; pre-7.x paging defaults | **P1** |
| 2 | `definitions/fortigate/fortios/7.0.yaml` | NEW: fortinet/4D-Demo 7.0 SD-WAN | LTS-era; closes WANTED.md gap | **P1** |
| 3 | `definitions/fortigate/fortios/7.4.yaml` | NEW: fortinet/4D-Demo 7.4 SD-WAN | Current LTS | **P1** |
| 4 | `definitions/fortigate/fortios/7.6.yaml` | Existing KevinGuenay 7.6.6 already in corpus | Current latest | **P2** |
| 5 | `definitions/fortigate/fortios/7.2.yaml` | Existing user_contrib_fg100e 7.2.13 already in corpus | Same | **P2** |
| 6 | `definitions/fortigate/fortios/6.0.yaml` retrospective | Internet Archive / forum | Legacy | **P4** |
| 7 | `definitions/fortigate/fortios/5.x.yaml` retrospective | Internet Archive / forum | Legacy | **P4** |

**Wave 1 net additions: 5 FortiGate overlays.**

### MikroTik RouterOS

| # | Overlay file | Evidence | Delta | Priority |
|---|---|---|---|---|
| 1 | `definitions/mikrotik/routeros/7.1.yaml` (early v7) | NEW: yottabit42/routeros v7.1.1 | Early-v7 grammar quirks per WANTED.md | **P1** |
| 2 | `definitions/mikrotik/routeros/6.49.yaml` (last 6.x LT) | Spec-search needed | Long-term branch close-out | **P2** |
| 3 | `definitions/mikrotik/routeros/7.18.yaml` | Existing user_contrib_crs310 7.18.2 already in corpus | Modern v7 | **P2** |
| 4 | `definitions/mikrotik/routeros/6.48.yaml` | Existing ntc + routeros-diff 6.48 already in corpus | Mid-6.x | **P2** |
| 5 | `definitions/mikrotik/routeros/CHR.yaml` (variant) | Spec-search (CHR cloud-hosted-router) | Platform variant per WANTED.md | **P2** |
| 6 | `definitions/mikrotik/routeros/CCR.yaml` (variant) | Spec-search (CCR variants) | Same | **P3** |

**Wave 1 net additions: 4 MikroTik overlays.**

### OPNsense

| # | Overlay file | Evidence | Delta | Priority |
|---|---|---|---|---|
| 1 | `definitions/opnsense/opnsense/24.x.yaml` | NEW: opnsense/core@24.7 tag pull | Closes WANTED.md gap | **P1** |
| 2 | `definitions/opnsense/opnsense/23.x.yaml` | NEW: opnsense/core@23.7 tag pull | Closes WANTED.md gap | **P1** |
| 3 | `definitions/opnsense/opnsense/22.x.yaml` | NEW: opnsense/core@22.7 tag pull | Closes WANTED.md gap | **P1** |
| 4 | `definitions/opnsense/opnsense/HA-CARP.yaml` (HA-specific) | NEW: opnsense/docs CARP example | HA-pair-specific paging; **closes v0.2.0 codec real-capture gap** | **P1** |
| 5 | `definitions/opnsense/opnsense/21.x.yaml` | Spec-search | Retrospective | **P3** |
| 6 | `definitions/opnsense/opnsense/20.x.yaml` | Spec-search | Retrospective | **P3** |
| 7 | `definitions/opnsense/opnsense/15.x-19.x.yaml` | Internet Archive sweep | Long retrospective | **P4** |

**Wave 1 net additions: 4 OPNsense overlays.**

---

## Tier-D OSs — overlay scaffolding (when codecs ship)

For each Tier-D OS, when its codec lands (v0.3.0+), the per-version
overlay backlog is pre-mapped from the catalogues.  No overlays
needed pre-codec.

### Cisco NX-OS (planned v0.3.0)

Initial overlay set when codec ships: `9.x.yaml` (family base) +
`10.x.yaml` + `7.x.yaml` (LTS retrospective).  Evidence: 8 batfish
snapshots + planning doc references.

### Cisco IOS-XR (planned v0.3.0+; defer until NX-OS lands)

Initial: `7.x.yaml` + `24.x.yaml` (rebrand) + `6.x.yaml`
retrospective.  Evidence: `ios-xr/xrd-tools` topologies.

### Cisco IOS classic

Catalogue recommends `syntax_flavor: ios_classic` overlay on the
existing `cisco_iosxe_cli` codec — no separate codec.  Implies
overlays under `definitions/cisco/ios/` (new family) with `15.x` +
`15.9` + `12.4(15)T` retrospective.

### Aruba AOS-CX (planned v0.3.0+)

Initial: `10.13.yaml` + `10.10.yaml` (LSR) + `10.04.yaml`
(retrospective).  Evidence: `aruba/aoscx-ansible-dcn-workflows`
+ `crispyfi/clab-aos-cx-demo` (10.13.1110).  Codec mirrors
`arista_eos` parser shape per catalogue analysis.

### Juniper SRX

Initial: `21.x.yaml` + `15.1X49.yaml`.  Evidence: batfish
srx-testbed.  Codec shares 70% of `juniper_junos` scaffolding.

### VyOS

Initial: `1.4.yaml` (current LTS) + `1.5.yaml` (rolling).
Evidence: four Apache-2.0 community repos.  Codec shares
`juniper_junos` set-form tokeniser.

### pfSense

Initial: `2.7.yaml` (CE) + `Plus-23.x.yaml`.  Evidence:
`sheridans/pfopn-convert` + `pfsense/pfsense` factory default
(Apache-2.0, **better than WANTED.md assumed**).  Codec shares
70% of `opnsense` codec; recommend `pfsense_opnsense_xml`
shared codec with root-tag dispatcher.

---

## Recommended overlay-authoring sequence (cross-OS)

### Wave A — close v0.1.x WANTED.md gaps (high leverage, small scope)

Target: ~12 new overlays + ~8 new fixtures.  Roughly 5-7 PRs.

* `cisco/ios-xe/17.16.yaml` + WLC fixture (myhomenwlab pull)
* `cisco/ios-xe/16.x.yaml` family base + 16.9 / 17.3 / 17.9 promotions
* `juniper/junos/19.x.yaml` + `21.x.yaml` + srl-labs lab pulls
* `arista/eos/4.30.yaml` + AVD bundle pulls
* `aruba/aos-s/KB-16.04.yaml` + 3810M VRRP HPE-Community pull
* `fortigate/fortios/6.4.yaml` + batfish pulls
* `mikrotik/routeros/7.1.yaml` + yottabit42 pull
* `opnsense/opnsense/22.x.yaml` + `23.x.yaml` + `24.x.yaml` + opnsense/core tag pulls
* `opnsense/opnsense/HA-CARP.yaml` + opnsense/docs CARP-example pull

Estimated cumulative impact: 7 overlays → **~19 overlays** (≈2.7× expansion).

### Wave B — fill retrospective gaps + version-bridge (medium scope)

Target: ~20 additional overlays.  Roughly 8-12 PRs spread across
the shipped-OS matrix.  Sources are catalogue's secondary tier
(batfish, Apache-2.0 community labs, vendor doc examples).

Estimated cumulative impact: 19 → **~39 overlays** (≈5.5× expansion).

### Wave C — deep retrospective + platform variants (catch-up)

Target: ~28 additional overlays covering 15.x-and-older
retrospectives, OPNsense semi-annual catch-up, MikroTik
CHR/CCR variants, Aruba YA/YB/RA per-platform splits.

Estimated cumulative impact: 39 → **~67 overlays** (≈9.5× expansion).

### Wave D — Tier-D codec overlays (post-v0.3.0)

When Tier-D codecs ship (NX-OS, IOS-XR, AOS-CX, etc.), each gets
a family-base YAML + 3-5 per-version overlays mapped from its
catalogue.  Estimated +30 overlays.

Cumulative target: **~95-100 overlay YAMLs** across the matrix
(~13× the v0.1.1 baseline).

---

## Implementation approach per overlay

Each overlay PR follows the same shape:

1. **Pull a real-world capture** from the catalogue's recommended
   pull-priority order, per the `BUG_REPORTING.md` sanitisation flow.
2. **Author the per-version YAML** under `definitions/<vendor>/<os>/<version>.yaml`.
   - Start from the existing family-base file (e.g. `17.x.yaml`)
   - Document the per-version delta inline (which prompts.trailing
     regex narrowed, which connection params shifted)
   - Set `priority` higher than family base so longest-match resolver
     picks it for pinned `os_version`
3. **Add regression test** — connect to a synthetic device-fingerprint
   per the captured config and verify the collector strategy +
   prompt regex match.
4. **Update `tests/fixtures/real/NOTICE.md`** with the fixture
   provenance (origin URL, license, sanitisation notes, grammar
   coverage).
5. **Update `tests/fixtures/real/RESULTS.md`** if the overlay
   coverage tier shifts.
6. **Cross-reference catalogue** in the commit message
   (`docs/fixture-research-2015/<NN>-<os>.md` § "Recommended pull
   priority order").

---

## Catalogue findings that DO NOT translate to overlays

For honesty: not every catalogue finding informs an overlay.
Examples of pulls that are codec-grammar or fixture-only value:

* **block-form Junos** captures (e.g. JNPRAutomate ansible-junos-
  evpn-vxlan) — testing the existing codec's block-form converter,
  not overlay-relevant
* **EVPN-VXLAN grammar variety** captures (Arista AVD bundles,
  ksator QFX10K2) — exercises codec dispatch tables, not collector
  behaviour
* **VRRP / HSRP / CARP fixtures** (HPE Community 3810M, opnsense/
  docs CARP HA) — informs codec regression tests for v0.2.0 wire-up,
  not connection-layer overlays
* **Cross-vendor grammar reference** (Arista L3VPN-over-MPLS,
  Junos vJunos labs) — codec grammar surface, not overlay

These are still high-leverage corpus additions; they just hit a
different lens than the overlay-expansion goal.

---

## See also

* [`README.md`](README.md) — folder index
* [`00-source-analysis.md`](00-source-analysis.md) — source-class taxonomy
* Per-OS catalogues `01-cisco_iosxe.md` through `14-pfsense.md`
* [`tests/fixtures/real/WANTED.md`](../../tests/fixtures/real/WANTED.md) — current operator-facing gap list (corrections from catalogue research called out per-OS above)
* [`tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md) — existing fixture provenance ledger
* [`BUG_REPORTING.md`](../../BUG_REPORTING.md) — sanitisation + fixture-submission workflow
* [`definitions/cisco/ios-xe/17.12.yaml`](../../definitions/cisco/ios-xe/17.12.yaml) — exemplar overlay file (reference for new overlay authoring shape)

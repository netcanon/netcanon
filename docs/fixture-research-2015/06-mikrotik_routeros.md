# MikroTik RouterOS — fixture catalogue (2015+)

> **Tier**: Shipped
> **Codec**: `mikrotik_routeros`
> **Existing corpus**: 4 fixtures (6.48.1 / 6.48.6 / 7.18.2)

RouterOS is MikroTik's Linux-based network OS that powers the RB
(RouterBoard) consumer line, CRS (Cloud Router Switch) hardware,
CCR (Cloud Core Router) carrier-grade boxes, and the CHR (Cloud
Hosted Router) virtual edition.  The CLI grammar is uniform across
every platform — the same `/export verbose` produces the same shape
on a hAP mini, a CCR2004, and a CHR running in AWS — so a fixture
sourced from any of those platforms exercises the same codec paths.
The only platform-specific variance is the **interface namespace**
(an RB951 has `wlan1/wlan2`, a CRS3xx has `sfp-sfpplus1..2`, a CCR has
`combo1-combo12`, a CHR has only generic `ether1..N`) and the
**default-configuration footprint** (each model ships with its own
defconf script).

> **Note on file extensions** — RouterOS captures land as either
> `.rsc` (the canonical export-script form produced by `/export` /
> `/export verbose`, with `set [find ...]`-style mutations on
> default objects) or `.scr` (raw script files an admin runs to
> *provision* a router — `add` statements rather than `set`).  Both
> parse fine.  `.rsc` is operator-preferred and what `/export
> verbose` produces; `.scr` is the human-authored provisioning
> form.  This catalogue flags which form each pull-target is.

This catalogue references the shared source taxonomy in
[`00-source-analysis.md`](00-source-analysis.md).

---

## Version timeline

| Version family | First release | LTS / current | Notable platforms | In corpus | Priority |
|---|---|---|---|---|---|
| 6.30 (early-LT) | 2015-07-08 | EOL 2015-08-25 | RB2011, RB951G, RB750Gr3 | — | Low (very small grammar drift vs 6.40+) |
| 6.35 | 2016-04-14 | EOL 2016-06-09 | RB951Ui, CCR1009 (gen-1) | — | Low |
| 6.40 (LT) | 2017-07-21 | EOL 2018-08-20 | hAP ac², RB4011, CCR1036 | — | Medium (last pre-IPv6-ND-rewrite branch) |
| 6.45 (LT) | 2019-06-21 | EOL 2020-04-30 | CCR2004-1G-12S+2XS first sold | — | Medium |
| 6.46 (LT) | 2019-12-02 | EOL 2020-10-29 | hEX S, hAP ac³, CCR2004 mainline | — | Medium |
| 6.47 | 2020-06-02 | EOL 2021-05-31 | CRS354, RBSXTsq | — | Medium |
| **6.48 (LT)** | 2020-12-22 | (LT — branch active until 6.48.7 2023-05-23) | full fleet inc. hAP mini | **2 fixtures (6.48.1 / 6.48.6)** | Already strong |
| 6.49 (LT) | 2021-10-06 | EOL 2025-09-30 (most-recent v6) | RB5009, L009UiGS, CRS520 | — | **HIGH** (last v6 LTS — terminal v6 grammar baseline) |
| 7.0 (stable) | 2021-12-01 (as 7.1; 7.0.x was beta) | superseded | introduced /routing rewrite | — | **HIGH** (WANTED.md gap) |
| 7.1 | 2021-12-01 | superseded | full /routing/bgp redesign (no `instance` / `peer`) | — | **HIGH** (WANTED.md gap — first stable v7) |
| 7.2-7.5 | 2022 | superseded | /interface/wireguard mainstreamed, OSPFv3 stabilised | — | **HIGH** (WANTED.md gap) |
| 7.6-7.10 | 2022-2023 | superseded | container support, vlan-filtering defaults shifted | — | **HIGH** (WANTED.md gap — late "early v7") |
| 7.11-7.14 | 2023-2024 | superseded | `/interface/wifi` (wireless rewrite replacing `/interface/wireless`) | — | Medium |
| 7.15-7.17 | 2024 | superseded | CEF logging, BTH (Back-to-Home) | — | Medium |
| **7.18 (LT)** | 2025 | LT branch | most-current LT capture target | **1 fixture (7.18.2)** | Already covered |
| 7.19-7.20 | 2025-late-2025 | LT (7.20) | "trusted" cert-store, BGP grammar shifts | — | Medium |
| 7.21-7.22 | 2026 (current) | 7.21 LT / 7.22 stable | current GA train | — | Medium |

Sources for the dates above: [`endoflife.date/routeros`](https://endoflife.date/routeros),
[`mikrotik.com/download/changelogs`](https://mikrotik.com/download/changelogs),
[`forum.mikrotik.com` announcements](https://forum.mikrotik.com/c/announcements/4).

> **Reading the table.**  The codec sits comfortably on 6.48.x and
> 7.18.x.  The **highest-value gaps** are 6.49.x (last v6 LT), the
> early-v7 series (7.0-7.10 per WANTED.md), and the absence of
> CHR-derived and CCR-derived captures — both platforms have
> distinct default-config footprints from the SOHO/SMB hardware
> already represented.

---

## Existing corpus coverage

The four fixtures in `tests/fixtures/real/mikrotik/` are
(per [`NOTICE.md`](../../tests/fixtures/real/NOTICE.md)):

| Filename | OS version | Source | Form |
|---|---|---|---|
| `ntc_ip_address_export.rsc` | 6.48.6 | [`networktocode/ntc-templates`](https://github.com/networktocode/ntc-templates) — Apache-2.0 | `/export verbose` snippet, `/ip address` only (9 lines) |
| `routeros_diff_verbose_export.rsc` | 6.48.1 | [`adamcharnock/routeros-diff`](https://github.com/adamcharnock/routeros-diff) — MIT | full `/export verbose` from RB952Ui-5ac2nD (484 lines) |
| `taqavi_initial_provisioning.rsc` | (unmarked, ~7.x) | [`AmirArsalanTaqavi/Mikrotik-Config-Examples`](https://github.com/AmirArsalanTaqavi/Mikrotik-Config-Examples) — MIT | provisioning `.rsc` for L009UiGS-2HaxD |
| `user_contrib_crs310_ros7.rsc` | 7.18.2 | User contribution — CC0-1.0 | full `/export verbose` from CRS310-8G+2S+ (630 lines) |

Surface covered today: bridge + bridge VLAN-filtering, 802.1q on
parent / VLAN interfaces, `/ip address`, `/ip dhcp-server`,
`/ip pool`, `/snmp`, `/interface wireless` (v6) + `/interface
wireguard` + `l2tp-server` + `sstp-server`, `/interface bridge port`,
`/system identity`, `/system clock`, `/system watchdog`, `/system
leds`, `/queue tree`, MPLS-stub, BGP-template-stub, IPv6 ND
(v7.18 shape).

Surface NOT covered today: full BGP session/template config in v7
shape, OSPFv2 / v3 area + neighbor stanzas, CAPsMAN controller,
container interfaces (v7.10+), the v7-rewritten `/interface/wifi`
grammar (introduced ~7.13), early-v7 BGP grammar quirks (7.0-7.10
period), CHR-specific defconf footprint, CCR-class `combo1-combo12`
+ multi-CPU resource allocation grammar.

---

## Pull-target inventory

### 7.0-7.10 (early v7 — WANTED.md gap; grammar quirks)

The early-v7 series introduced sweeping changes vs v6 — particularly
the complete BGP-config rewrite (no more `instance` + `peer` →
new `connection` + `template` + `session` menus), the `/routing
filter` rule selection model, and IPv6 ND grammar shifts.  Captures
from this era surface migration behaviour the codec hasn't been
tested against.

#### GitHub repositories

* [**`yottabit42/routeros`**](https://github.com/yottabit42/routeros)
  — BSD-3-Clause.  10 `.rsc` files including `dual_wan_failover.rsc`
  explicitly tagged for **RouterOS v7.1.1**.  Audience-router tweaks,
  fail2ban-style firewall, QoS rules.  Modular scripts (`.rsc` in
  provisioning form, not `/export verbose`).  Form: **.rsc
  provisioning**.  Sanitisation: light.

* [**`madsbacha/routeros-vpn`**](https://github.com/madsbacha/routeros-vpn)
  — RouterOS script for Private Internet Access WireGuard setup; runs
  natively on v7.1+ where WireGuard was introduced.  Single .rsc
  provisioning script.  Sanitisation: light (replace PIA credentials).

* [**`1ricardo66/RouterOSv7-BGP`**](https://github.com/1ricardo66/RouterOSv7-BGP)
  — **Portuguese-language** BGP-in-v7 examples, **tested on v7.6**.
  No explicit LICENSE file but is essentially educational config
  examples; covers BGP filtering input/output rules, local pref,
  communities, AS-path prepending, network announcement, peer
  configuration, address-list-based prefix mgmt.  Form: **.rsc
  snippets** embedded in README + screenshots.  License risk:
  medium — best treated as inspiration, not direct import.

* [**`AmirArsalanTaqavi/Mikrotik-Config-Examples`**](https://github.com/AmirArsalanTaqavi/Mikrotik-Config-Examples)
  — MIT.  Already partially in corpus (`taqavi_initial_provisioning.rsc`);
  the **remaining scenarios are not yet ingested**: `wireguard-server.rsc`,
  `wireguard-site-to-site.rsc`, `l2tp-ipsec-vpn.rsc`,
  `multi-wan-pcc-load-balance.rsc`, `firewall-secure-default.rsc`.
  Each is a self-contained provisioning script — ideal "feature-isolated"
  fixtures.  Form: **.rsc provisioning**.

#### Forum / community posts

* [**MikroTik forum — "BGP + OSPF with V7"**](https://forum.mikrotik.com/t/bgp-ospf-with-v7/263999) and
  [**"COnfig BGP on Mikrotik V7.6"**](https://forum.mikrotik.com/viewtopic.php?t=162751)
  — operators pasting full `/export` blocks while troubleshooting v7
  BGP migration from v6.  Forum-share precedent applies (same class
  as the HPE Community Aruba captures already in corpus).
  Sanitisation: **heavy** (operators often paste real AS numbers,
  peering IPs, sometimes routing-filter rules with sensitive prefixes).

* [**MikroTik forum — "7.x OSPF"**](https://forum.mikrotik.com/t/7-x-ospf/158875)
  — long-running thread covering 7.0-7.6 OSPFv2/v3 grammar
  evolution.  Multiple `/routing/ospf` exports posted by operators.

#### Vendor docs / lab guides

* [**`help.mikrotik.com` — "Moving from ROSv6 to v7 with examples"**](https://help.mikrotik.com/docs/spaces/ROS/pages/30474256/Moving+from+ROSv6+to+v7+with+examples)
  — official MikroTik migration cookbook.  Embedded v6 → v7 config
  pairs.  License: vendor-doc "example use" terms.  Form: **inline
  `.rsc` snippets**.  Already-canonical reference material; could
  pull individual feature stanzas as synthetic fixtures.

#### Operator blogs / Other

* [**`stubarea51.net` — RouterOS v7 first look (BGP/OSPF/IPv6)**](https://stubarea51.net/2020/12/30/mikrotik-routerosv7-first-look-dynamic-routing-with-ipv6-and-ospfv3-bgp/)
  — Kevin Myers' walkthrough of v7.0 dynamic routing.  Full lab
  configs embedded.  License: implicit blog fair-use; best treated as
  inspiration not direct import.  Captures the 7.0 grammar pre-stable.

* [**`knowledgebase.servperso.net` — minimal BGP on RouterOS 7**](https://knowledgebase.servperso.net/bgp-mikrotik-router-os-7-minimal-setup-configuration/)
  — early-v7 minimal BGP config; useful as grammar reference.

---

### 7.11-7.18+ (modern v7)

The modern v7 branch added `/interface/wifi` (replacing `/interface/wireless`
in 7.13+), container support, BTH (Back-to-Home), and CEF logging.
Strong corpus already at 7.18.2; the gap is **non-CRS platforms** on
modern v7 (existing v7 fixture is a CRS310 switch — no router-class
v7 fixture).

#### GitHub repositories

* [**`floeff/routeros-configuration`**](https://github.com/floeff/routeros-configuration)
  — **GPL-3.0** (incompatible with Apache/MIT/BSD/CC0 we accept; do
  NOT directly import).  Listed for reference only; targets RouterOS
  7.x with three modular .rsc files (`01-variables.rsc`,
  `02-devices.rsc`, `03-base.rsc`).  Could inform grammar discovery
  without copy.

* [**`Benewend/mikrotik-config-templates`**](https://github.com/Benewend/mikrotik-config-templates)
  — **MIT**.  Targets RouterOS v7.x+ with template configs for SOHO,
  enterprise-branch, ISP-CPE, WISP roles.  Mix of complete templates
  + modular security/monitoring scripts.  Form: **.rsc**.
  Sanitisation: minor (some placeholder credentials).
  **HIGH-priority pull**: 4-5 distinct role templates each give a
  feature surface the codec hasn't seen on a v7-router-class fixture.

* [**`Disassembler0/mikrotik-scripts`**](https://github.com/Disassembler0/mikrotik-scripts)
  — **MIT**.  Snippet-style scripts (6to4, backup, firewall, mtu,
  restrict-country, sstp-lets-encrypt).  Not complete configs —
  treat as feature-isolated `.rsc` snippets.

* [**`n3tuk/scripts-mikrotik`**](https://github.com/n3tuk/scripts-mikrotik)
  — **MIT**.  Includes `update.rsc` (comprehensive: interfaces,
  bridges, VLANs, firewalls, users), `network.rsc`, `firewall.rsc`,
  `users.rsc`, `dns.rsc`, `certificates.rsc`.  Modular but the
  `update.rsc` is close to complete-config shape.  Hardware
  interface naming targets multi-generation (1GbE through QSFP28),
  so applicable to CRS3xx + CCR.  Sanitisation: light.

* [**`eworm-de/routeros-scripts`**](https://github.com/eworm-de/routeros-scripts)
  — **GPL-3.0** — incompatible license.  Listed for reference only
  (50+ utility scripts targeting RouterOS 7.19+).  Inspiration source
  for what kinds of operations operators run; do not pull directly.

* [**`Bert-Proesmans/Mikrotik-Scripts`**](https://github.com/Bert-Proesmans/Mikrotik-Scripts)
  — **MIT**.  RouterOS 6.46 (slightly older v6 baseline).  Shard
  pattern: `init.rsc` + `shard-default.rsc` / `shard-identity.rsc`
  / `shard-ppp.rsc` / `shard-QOS.rsc` / `shard-users.rsc`.
  Form: **.rsc provisioning**.

#### GitHub gists

* [**`elico/1ecf2904f137e98a7b7bffe2140ae7d9` — hAP ac² 7.15 default**](https://gist.github.com/elico/1ecf2904f137e98a7b7bffe2140ae7d9)
  — defconf-derived `.rsc` for hAP ac² on **RouterOS 7.15**.
  Single-file; bridge + DHCP + dual-band wireless + firewall + NAT.
  License: implicit gist-share.  Sanitisation: minor.  **MEDIUM-HIGH
  pull**: a v7.15 router-class capture would close the
  v7-non-CRS-class gap.

* [**`maurice-w/402eea6750738c7a6765219c34260283` — RouterOS 7.22 PPPoE offloader**](https://gist.github.com/maurice-w/402eea6750738c7a6765219c34260283)
  — hEX S (RB760iGS) on RouterOS 7.22.  Specialized config:
  PPPoE-upstream, DHCP-downstream, management-interface isolation.
  Form: **.rsc with embedded RouterOS script** (dynamic
  reconfiguration logic).  Sanitisation: light.

* [**`valeriansaliou/380ca483e295dc96efc51a2142187260` — Orange/Sosh Livebox 4 fiber config**](https://gist.github.com/valeriansaliou/380ca483e295dc96efc51a2142187260)
  — RB750Gr3 on **RouterOS 6.46.1** (note: v6 fixture, listed here
  because the gist style would also fit a v7 capture).  Full
  `/export` with VLAN 832, IPv6 DHCPv6 PD, dual-stack firewall,
  UPnP, DNS caching.  License: implicit gist-share.

#### Forum / community posts

* [**MikroTik forum announcements (7.19.6, 7.20.x, 7.21.x, 7.22.x)**](https://forum.mikrotik.com/c/announcements/4)
  — release-note threads.  Useful for understanding grammar shifts
  but **not config-source threads** (operators don't paste full
  configs in announcement threads).  Use as version-bridging context.

* [**MikroTik forum — general troubleshooting threads**](https://forum.mikrotik.com/)
  — same forum-share precedent as the HPE Community fixtures.
  Search patterns: `"export"` + version filter, `"OSPF"` + v7,
  `"BGP"` + v7, `"CCR"` + config.  Sanitisation: heavy.

#### Vendor docs / lab guides

* [**Containerlab MikroTik RouterOS kind**](https://containerlab.dev/manual/kinds/vr-ros/)
  — `mikrotik_ros` kind; supports `startup-config: <file.rsc>`
  with auto-import via `.auto.rsc` filename.  No fixtures bundled
  (containerlab itself ships the kind handler, not example configs).
  **Indirect pull target**: search GitHub for `clab-topo` topic
  repositories that include MikroTik nodes — those topology files
  include `startup-config` paths pointing to operator-authored
  `.rsc` files.

* [**`tikoci/chr-utm`**](https://github.com/tikoci/chr-utm) and
  [**`tikoci.github.io`**](https://tikoci.github.io/) — TIKOCI
  open-source RouterOS toolkit; includes RAML / OpenAPI schemas for
  multiple v7 versions (7.15+) but ship as schema definitions, not
  config exports.  Useful for grammar-shape reference.

---

### 6.x late (6.46-6.49)

The terminal v6 branches.  6.48 is well-covered (2 fixtures).
**6.49 — the last v6 LTS — is missing**; this is the most natural
"closing fixture" for the v6 era and would round out OS-version
coverage to 4 v6 captures vs 1 v7 capture.

#### GitHub repositories

* [**`AmirArsalanTaqavi/Mikrotik-Config-Examples`** (other scenarios)](https://github.com/AmirArsalanTaqavi/Mikrotik-Config-Examples)
  — MIT.  See "early v7" listing above; the scenario files are
  RouterOS-version-agnostic and parse cleanly on 6.x as well.

* [**`adamcharnock/routeros-diff` (`tests/test_files/`)**](https://github.com/adamcharnock/routeros-diff)
  — MIT.  `verbose_export.rsc` already in corpus (6.48.1).  No
  additional `.rsc` files in that test directory beyond the one
  ingested fixture; the rest of the repo is the diff tool itself
  with synthetic test cases.

* [**`networktocode/ntc-templates` (`tests/mikrotik_routeros/`)**](https://github.com/networktocode/ntc-templates)
  — Apache-2.0.  `ip_address_export_verbose/` already in corpus
  (6.48.6).  **Additional NTC test fixtures NOT yet ingested**
  cover individual `/print` commands (interface_bridge_host,
  interface_ethernet_poe, interface_vlan, interface_wireguard,
  ip_arp, ip_dhcp-server lease, ip_firewall filter/nat/address-list,
  ip_route, routing_bgp_peer, routing_ospf_neighbor, system_clock,
  system_identity, system_resource, user) — these are command-output
  parser fixtures rather than config exports, but useful for the
  codec's parse-and-print-output paths if those get wired in.
  Form: per-command `.raw` outputs (treat as `.rsc`-adjacent).

#### Forum / community posts

* [**MikroTik forum — RouterOS release-history thread**](https://forum.mikrotik.com/t/routeros-release-history/155483)
  — community-maintained version-date index; useful for
  cross-referencing capture vintage to LT/stable status.

* [**`forum.mikrotik.com` — long-running OSPF / BGP threads tagged 6.40-6.48**](https://forum.mikrotik.com/c/forwarding-protocols/8)
  — many operator-pasted configs from the v6 era.  Search:
  `"export" "RouterOS 6.49"` or `"export" "RouterOS 6.48"` in the
  Forwarding-Protocols subforum.  Forum-share precedent applies.

#### Operator blogs / Other

* [**`itnetworking.cz` (Czech)**](https://itnetworking.cz/) — Czech
  operator blog called out in [`00-source-analysis.md`](00-source-analysis.md);
  heavy on Mikrotik tutorials.  Search-engine indexing weak in
  English; direct site search needed.  License: implicit blog
  fair-use; inspiration-only.

* [**`klyonrad/mikrotik-vlan-dhcp-config`**](https://github.com/klyonrad/mikrotik-vlan-dhcp-config)
  — single `config-export` file for **RouterOS 6.34.2** (2016
  vintage — earlier than current corpus minimum).  hAP-class
  hardware with bridge + 2 VLANs (200, 300) + 3 DHCP servers +
  802.11n + firewall + hotspot.  License: not stated in repo.
  Form: **`/export verbose`** output.  Sanitisation: moderate
  (real-looking IPs are RFC1918 already).  **MEDIUM pull**: would
  add the only sub-6.40 capture in corpus.

---

### 6.x mid (6.40-6.45)

#### GitHub repositories

* [**`Bert-Proesmans/Mikrotik-Scripts`**](https://github.com/Bert-Proesmans/Mikrotik-Scripts)
  — MIT.  Targets **RouterOS 6.46** (right at the 6.45/6.46
  boundary).  See "modern v7" listing for shard pattern.  Useful
  for the 6.x late→mid handoff capture.

* [**`Disassembler0/mikrotik-scripts`**](https://github.com/Disassembler0/mikrotik-scripts)
  — MIT (snippet-style; see above).  Long-running, started in
  6.40-ish era — many of the scripts predate v7.

#### Operator blogs / Other

* [**`derekseaman.com` — Home Lab: CCR2004 + CRS317 (March 2021)**](https://www.derekseaman.com/2021/03/home-lab-mikrotik-ccr2004-and-crs317-configuration.html)
  — Derek Seaman's full CCR2004 home-lab config.  Copy-pasteable
  `/export`-style block covering 3 VLANs (mgmt/vMotion/VM),
  bridge with VLAN filtering, jumbo-frame MTU=9000.  RouterOS
  version not explicitly stated but post-dates 6.46.  License:
  blog fair-use only — best as inspiration, not direct import.

---

### 6.x early (6.30-6.39)

This era predates the corpus coverage window's natural bottom; most
of the discoverable configs from 2015-2017 still parse cleanly but
the grammar drift from 6.40+ is small.  Low priority unless a very
specific 6.x-only feature regression surfaces.

#### GitHub repositories

* [**`klyonrad/mikrotik-vlan-dhcp-config`**](https://github.com/klyonrad/mikrotik-vlan-dhcp-config)
  — see "6.x late" listing; 6.34.2 capture (~July 2016).

#### Operator blogs / Other

* [**Internet Archive captures of operator blogs**](https://web.archive.org/web/2015*/)
  — Wayback Machine has many 2015-2017 RouterOS blog posts that
  have since 404'd; use for grammar-archaeology if a regression
  ever points there.  Sanitisation expectation: heavy (blog quality
  varies).

---

### CHR (cloud-hosted router) configs — distinct platform

CHR (Cloud Hosted Router) is the RouterOS-on-VM edition for AWS,
Azure, DigitalOcean, Hetzner, Proxmox, ESXi, KVM, Hyper-V.  The
defconf footprint is **explicitly minimal** vs the SOHO/SMB hardware
— no wireless, no per-port interface defaults, no `default-name=ether2`
mutations.  Captures from CHR are valuable because:

1. They exercise the **bare-defconf** code paths that hardware
   captures don't (the corpus has 0 CHR fixtures today).
2. The interface namespace is uniform (`ether1`, `ether2`, ...)
   without platform-specific naming.
3. Use-cases are typically VPN gateway / BGP edge / NAT gateway —
   different grammar surfaces than SOHO bridge+wireless captures.

#### GitHub repositories

* [**`tikoci/chr-utm`**](https://github.com/tikoci/chr-utm) —
  RouterOS CHR packaged for UTM on macOS.  Image-distribution repo;
  not a config-source.  License: see repo (TIKOCI toolkit).

* [**`bschapendonk/azure-mikrotik-chr`**](https://github.com/bschapendonk/azure-mikrotik-chr)
  — Bicep-templated Azure CHR deployment.  Includes startup-config
  examples for Azure-specific networking.  License: see repo.

* [**`hreskiv/chr-on-vps`**](https://github.com/hreskiv/chr-on-vps)
  — Bash auto-installer for VPS-hosted CHR; injects an autorun
  `.rsc` with static IP, gateway, password.  Example `.rsc`
  in the install script.  License: see repo.

* [**`GNS3/gns3-registry` — `mikrotik-chr.gns3a`**](https://github.com/GNS3/gns3-registry/blob/master/appliances/mikrotik-chr.gns3a)
  — GNS3 appliance definition for CHR; no embedded configs but
  lists the canonical CHR image versions GNS3 community uses.

#### Vendor docs / lab guides

* [**`help.mikrotik.com` — Cloud Hosted Router, CHR**](https://help.mikrotik.com/docs/spaces/ROS/pages/18350234/Cloud+Hosted+Router+CHR)
  — official CHR doc.  Embedded `/export`-style snippets for VPN
  gateway / firewall / NAT.  License: vendor-doc "example use"
  terms.

* [**MikroTik forum — "Real Docker images for CHR to run in Containerlab"**](https://forum.mikrotik.com/t/real-docker-images-for-chr-to-run-in-containerlalb/181934)
  — discussion of CHR image production for `mikrotik_ros`
  containerlab kind.  Useful context for sourcing a clean CHR
  snapshot to capture from.

* [**`iparchitechs/chr` Docker image + IP ArchiTechs blog**](https://iparchitechs.com/network-modeling-automating-mikrotik-routeros-chr-containerlab-images/)
  — IP ArchiTechs has CHR-in-containerlab automation; the blog walks
  through CHR image extraction.  Their startup-config examples are
  small but show clean CHR defconf shape.

#### Operator blogs / Other

* [**DigitalOcean — Configure MikroTik CHR as VPN/NAT Gateway**](https://www.digitalocean.com/community/developer-center/configure-mikrotik-cloud-host-router-chr-as-vpn-nat-gateway-on-digitalocean)
  — full CHR-on-DO config: VPN gateway + NAT-overload.  License:
  DigitalOcean Community-content; usually CC-BY-NC-SA.  Treat as
  inspiration not direct import.

* [**`yandex.cloud` Mikrotik CHR tutorial**](https://yandex.cloud/en/docs/tutorials/routing/mikrotik)
  — CHR-on-Yandex-Cloud full deployment; cloud-vendor docs with
  embedded `.rsc` snippets.

* [**Hetzner Community CHR tutorial**](https://community.hetzner.com/tutorials/mikrotik-chr-basic-setup/)
  — Hetzner-specific CHR basic setup with full `.rsc` config flow.

---

### CCR variants

CCR (Cloud Core Router) is the carrier-grade hardware tier — multi-core
TileGX / ARM64 (CCR2004 / CCR2116), `combo1-combo12` SFP+SFP+
hybrid ports on certain models, 100GbE on CCR2216.  The codec hasn't
seen a CCR capture; both the namespace (`combo1` vs `ether1`) and
the typical use-case (BGP edge, MPLS PE) are distinct.

#### GitHub repositories

* [**`svlsResearch/ha-mikrotik`**](https://github.com/svlsResearch/ha-mikrotik)
  — high-availability VRRP config for **CCR1009-8g-1s-1s+** on
  **RouterOS 6.33.5** / **6.44.6**.  Real CCR config exercising
  VRRP across two routers + dedicated heartbeat interface (ether8).
  License: see repo (research code).  Form: **`HA_init.rsc`**
  initialization script.  **HIGH-priority pull** for CCR coverage
  + VRRP exercise (matches the v0.2.0 VRRP wire-up that ships
  but lacks a MikroTik fixture per WANTED.md table).

#### Operator blogs / Other

* [**`derekseaman.com` CCR2004 home-lab post (above)**](https://www.derekseaman.com/2021/03/home-lab-mikrotik-ccr2004-and-crs317-configuration.html)
  — CCR2004 with VLAN routing + jumbo frames.  Inspiration only
  (no explicit license).

* [**`savazzi.net` — CCR2004-16G-2S+PC configuration**](https://savazzi.net/internet/mikrotik-ccr2004-configuration.html)
  — full CCR2004 deployment writeup.  Operator-blog; inspiration
  only.

* [**`blog.cavelab.dev` — Getting started with MikroTik CCR1009 and RouterOS**](https://blog.cavelab.dev/2021/08/mikrotik-ccr1009-routeros-setup/)
  — CCR1009 full setup walkthrough.

#### Forum / community posts

* [**MikroTik forum — "CCR2004 Finally Working... now what do I do??"**](https://forum.mikrotik.com/viewtopic.php?t=193324)
  — Beginner-level CCR2004 thread with full configs pasted while
  troubleshooting.  Forum-share precedent applies.

---

## Recommended pull priority order

Ordered by closing the WANTED.md gaps, license confidence, and
grammar-surface diversity:

1. **Early-v7 (7.0-7.10) router-class capture** — `yottabit42/routeros`
   `dual_wan_failover.rsc` (BSD-3, **explicitly tagged v7.1.1**) is
   the cleanest single-license-clear early-v7 source.  Closes the
   primary WANTED.md gap.

2. **Additional Taqavi scenarios** —
   `AmirArsalanTaqavi/Mikrotik-Config-Examples` already trusts this
   source (one fixture ingested under MIT); pulling the remaining
   5 scenario files (wireguard-server, wireguard-site-to-site,
   l2tp-ipsec, multi-wan-pcc, firewall-secure-default) each adds
   feature-isolated coverage at near-zero license-vetting cost.
   `.rsc` provisioning form.

3. **6.49.x last-LT v6 capture** — close the v6 LT-train coverage
   to 6.48 + 6.49.  Most achievable via Taqavi or NTC sources at
   v6.49.x version, or via forum-share captures where operators
   pasted 6.49.x running-configs.  Forum-share precedent applies
   for forum.mikrotik.com.

4. **`Benewend/mikrotik-config-templates`** — MIT, 4-5 distinct role
   templates (SOHO / branch / ISP-CPE / WISP), v7.x+.  Highest
   feature-density-per-fixture for v7-non-CRS-class platforms.

5. **CCR fixture from `svlsResearch/ha-mikrotik` `HA_init.rsc`** —
   adds CCR1009 platform + VRRP grammar (matches the v0.2.0 VRRP
   wire-up that currently has no MikroTik fixture per WANTED.md
   redundancy table).

6. **CHR-class capture** — clean CHR defconf via `tikoci/chr-utm`
   or one of the cloud-vendor CHR tutorials (DigitalOcean / Yandex /
   Hetzner).  Closes the "no virtual-platform RouterOS" gap.
   Sanitisation needed but baseline-clean (no real WAN IPs in tutorial
   defconfs).

7. **`klyonrad/mikrotik-vlan-dhcp-config`** — only sub-6.40 capture
   on offer (6.34.2, 2016 vintage).  Adds historic-grammar coverage;
   medium priority because 6.34.2→6.48 grammar drift is small.

8. **`gist:elico/hap-ac2-7.15-default`** — v7.15 hAP ac² defconf-
   derived capture.  Closes the v7-router-class gap if other 7.x
   pulls don't land there first.

9. **`n3tuk/scripts-mikrotik`** — MIT, multi-generation hardware
   coverage; comprehensive `update.rsc`.  Inspiration / cross-check
   source for what a "comprehensive `.rsc` mass-provisioning script"
   looks like.

10. **Forum-share captures** (MikroTik forum BGP/OSPF v7 threads) —
    lowest license-confidence path; heaviest sanitisation; reserve
    for cases where 1-8 don't surface a specific grammar.

---

## Out-of-scope

* **Encrypted `.backup` files** — RouterOS binary backups are
  encrypted blobs (not `.rsc` text).  The codec parses text exports
  only; `.backup` is out of scope.
* **Firmware NPK files** — image archives, not configurations.
* **MikroTik commercial training material (MTCNA / MTCRE / MTCINE
  workbook configs)** — copyright-restricted; do not import.
* **Pirated archives** — repos like `ice-wzl/MikroTik-NPK-Archive`
  store firmware MikroTik has pulled from public distribution.
  Not config sources; license unclear.
* **WinBox-only snapshots** — `.umb` config exports from WinBox GUI
  are not text `/export verbose` output; not parser fixtures.
* **`elseif/MikroTikPatch` releases** — kernel-patch fork
  redistributing modified RouterOS images; out of scope for fixture
  research.
* **`Vlad1mir-D/routeros-7-source`** — GPL'd portions of RouterOS 7
  source.  Source code, not configuration.  Out of scope.
* **Captures from `pakoti/Mikrotik_Hero`** — cheatsheet-shape, not
  config-shape; useful as inspiration but not a fixture target.

---

## See also

* [`00-source-analysis.md`](00-source-analysis.md) — meta source-type
  taxonomy + license-class guidance referenced throughout this file.
* [`README.md`](README.md) — folder index + scope.
* [`tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md)
  — provenance ledger for the 4 fixtures currently in
  `tests/fixtures/real/mikrotik/`.
* [`tests/fixtures/real/WANTED.md`](../../tests/fixtures/real/WANTED.md)
  — operator-facing gap list; the early-v7 / CHR / CCR gaps this
  catalogue targets.
* [`BUG_REPORTING.md`](../../BUG_REPORTING.md) — sanitisation
  workflow + permissive-license verification.

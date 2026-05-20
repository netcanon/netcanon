# Juniper SRX (Junos firewall platform) — fixture catalogue (2015+)

> **Tier**: Tier-D (no codec yet; could share parse-side scaffolding with `juniper_junos`)
> **Existing corpus**: 0 SRX-specific fixtures.  Current `juniper_junos` fixtures
> (`tests/fixtures/real/junos/`) are EX/QFX/MX captures — `set chassis`,
> `set interfaces irb`, `set policy-options policy-statement`, `set protocols bgp`
> grammar surfaces only.  None exercise `set security ...`.
> **Distinct grammar**: `set security policies from-zone X to-zone Y policy ...`,
> `set security zones security-zone Z interfaces ...` /`host-inbound-traffic ...`,
> `set security ike { proposal | policy | gateway }`,
> `set security ipsec { proposal | policy | vpn }`,
> `set security nat { source | destination | static }`,
> `set security screen ids-option`,
> `set applications application ...` /`application-set ...`,
> `set security utm`, `set security application-firewall`,
> `set security idp`, `set security flow`,
> `set chassis cluster cluster-id N` /`reth-count` /`redundancy-group`.

SRX runs **Junos OS** — the set-form tokeniser, block-form converter,
`apply-groups`, and `set system` /`set interfaces` /`set routing-options`
hierarchies are byte-identical to `juniper_junos`.  The differentiator is the
dispatch table for the `security`, `applications`, `services`, and (for HA)
`chassis cluster` hierarchies.  A future `juniper_srx` codec should share
~70% of `juniper_junos`'s parse scaffolding and add a new dispatch tree for
the firewall / VPN / NAT / screen / UTM / IDP grammar.  See § "See also"
for codec-architecture cross-references.

---

## Hardware platforms in scope

SRX hardware splits into three tiers — each ran a different Junos branch and
hit EOL on its own schedule:

| Tier | Models | Junos branches seen | Status (2026) |
|---|---|---|---|
| **Legacy branch (EOS)** | SRX100 / SRX110 / SRX210 / SRX220 / SRX240 / SRX550 | 10.x → 12.1X46 → 12.3X48 | All EOS pre-2020 (SRX100 family EOS 2019-05-10) |
| **Branch (mid-life)** | SRX300 / SRX320 / SRX340 / SRX345 / SRX380 / SRX550M | 15.1X49 → 18.4 → 19.4 → 20.4 → 21.4 → 22.x | SRX300-series still shipping; SRX380 datasheet Junos 21.4R1 |
| **Data-center / SP / chassis** | SRX1400 / SRX1500 / SRX1600 / SRX3400 / SRX3600 / SRX4100 / SRX4200 / SRX4600 / SRX5400 / SRX5600 / SRX5800 | 12.x → 15.x → 17.x → 18.x → 19.x → 20.x → 21.x → 22.x → 23.x → 24.x | SRX5400/5600/5800 EOL 2021-10-06, EOS 2027-09-15.  SRX1500 / 4100 / 4200 still GA. |
| **Virtual** | vSRX (KVM/VMware/Hyper-V/AWS/Azure/GCP), vSRX3.0 | 15.1X49 → all subsequent | Active development; vSRX3.0 introduced ~2019 |

Junos versioning quirk on SRX: legacy 12.x → 15.x used the `15.1X49-DNN`
suffix branch (X-train); from 18.x onward the SRX consumed the mainline
Junos numbering (18.4R1, 19.4R1, 21.4R1, 22.4R1, etc.).  Any per-version
fixture should record both the marketing version (e.g. `15.1X49-D110.4`)
and the SRX model.

---

## Version timeline

| Junos branch | Released | SRX platforms | Notable grammar | Fixture priority |
|---|---|---|---|---|
| **12.1X46** | 2014 | SRX100/210/240/550, SRX1400 | Pre-modern security flow grammar; `set security alg` differs | Low (legacy) |
| **15.1X49** | 2015-Q2 | SRX300/320/340/345 (branch), SRX1500 | `set chassis cluster` modernised; `address-book global` widely used | **High** (still in field) |
| **17.4 / 17.3X** | 2017 | SRX1500, SRX4100/4200 | `set security application-firewall` matured; AppQoS introduced | Medium |
| **18.4** | 2018-Q4 | SRX300 line, SRX1500, SRX4100/4200, SRX5400/5600/5800 | First LTS for SRX1500 deployments | **High** (large install base) |
| **19.4** | 2019-Q4 | All current SRX | `set security flow tcp-mss` defaults shifted | Medium |
| **20.4** | 2020-Q4 | All current SRX | `tenant` /multi-tenant grammar introduced | Medium |
| **21.4** | 2021-Q4 | All current SRX + datasheet SRX380 | Day One+ "Guided Setup" branded around 21.4R1 on SRX300-line | **High** (current branch officials write to) |
| **22.4** | 2022-Q4 | All current SRX | `set services ssl proxy` enhancements | Medium |
| **23.2 / 23.4** | 2023 | All current SRX + new SRX1600 | vSRX3.0 mainline image; `juniper_vsrx` containerlab kind tracks this | **High** (containerlab tracks here) |
| **24.x** | 2024 | All current SRX | Continued AppSec / SecIntel updates | Medium |

---

## Pull-target inventory

### 24.x / 23.x current

#### Vendor docs

* **Day One: SRX Series Up and Running with Advanced Security Services** (Alexandre Cezar, 2018; revisions through 2022).
  PDF: `https://www.juniper.net/documentation/en_US/day-one-books/DO_SRX_UR.pdf`
  Mirror: `https://www.juniper.net/documentation/us/en/software/nce/do-srx-ur/DO_SRX_UR.pdf`
  Apple Books: `https://books.apple.com/gb/book/day-one-srx-series-up-and-running-with-advanced/id1362076029`
  Provenance class: vendor doc / Day One license ("free for educational use" — see § "License notes").  Covers SRX setup, zones, policies, IPsec site-to-site, SSL client VPN, UTM, NGFW (App-FW, AppQoS, SSL-Proxy), IPS, Sky ATP, SecIntel.  Multi-recipe (~5-15 distinct configs); each recipe is 30-150 lines of set-form.
  Grammar exercised: `set security zones`, `set security policies`, `set security ike`, `set security ipsec`, `set security utm`, `set security application-firewall`, `set security idp`.

* **Day One: Amazon Web Services with vSRX Cookbook** (Chirag Patel, Ali Bidabadi, Charlie Chang-Hyun Kim, Lionel Ruggeri, 2022).
  PDF: `https://www.juniper.net/documentation/en_US/day-one-books/AWS_vSRX_Cookbook22.pdf`
  Provenance: vendor Day One.  vSRX-specific cloud-deployment configs (IGW, NAT-GW, transit-VPC) — each recipe includes a complete vSRX config snippet (~50-200 lines).
  Grammar: vSRX-specific `set system services`, `set interfaces ge-0/0/0 unit 0`, plus full security stack.

* **Day One+ SRX300 / SRX320 / SRX345 / SRX380** (Guided Setup — vendor PDFs).
  URLs:
  - `https://www.juniper.net/documentation/us/en/quick-start/srx300/srx300-day-one-plus.pdf`
  - `https://www.juniper.net/documentation/us/en/quick-start/srx320/srx320-day-one-plus.pdf`
  - `https://www.juniper.net/documentation/us/en/day-one-plus/srx345/srx320-day-one-plus.pdf`
  - `https://www.juniper.net/documentation/us/en/quick-start/srx345/srx345-day-one-plus.pdf`
  - `https://www.juniper.net/documentation/us/en/quick-start/srx380/srx380-day-one-plus.pdf`
  Each contains a full "zero-touch" branch-office SRX config in set-form (~80-150 lines).  Junos 21.4R1 baseline documented.
  Grammar: `set system services dhcp`, `set security zones security-zone trust /untrust`, `set security policies`, `set security nat source rule-set internet`, `set applications application-set junos-defaults` references.

* **Guided Setup: How to Configure and Operate Juniper SRX 300 Series Firewalls** (Branch SRX Guided Setup, Junos 21.4R1).
  `https://www.juniper.net/documentation/us/en/guided-setup/branch-srx-gs/branch-srx-gs.pdf`
  HTML: `https://www.juniper.net/documentation/us/en/software/guided-setup/branch-srx-gs/index.html`
  Step-by-step config recipes for SRX300/320/340/345/380.  Includes IPsec VPN, NAT, security policies, UTM enablement.  Total config across all recipes ~400-600 lines.

* **Junos OS Chassis Cluster User Guide for SRX Series Devices** (live document).
  PDF: `https://www.juniper.net/documentation/us/en/software/junos/chassis-cluster-security-devices/chassis-cluster-security-devices.pdf`
  Vendor doc with worked HA cluster configs for SRX1500 / 4100 / 4200 / 5400 / 5600 / 5800 — `set chassis cluster cluster-id`, `set interfaces fab0 fabric-options member-interfaces`, `set chassis cluster redundancy-group N`.  Each example is 80-150 lines.

* **IPsec VPN User Guide** (live document, refreshed annually).
  PDF: `https://www.juniper.net/documentation/us/en/software/junos/vpn-ipsec/vpn-ipsec.pdf`
  Vendor doc.  Many recipes (route-based VPN, policy-based VPN, IKEv2, GRE-over-IPsec, ADVPN).  Each recipe 40-120 lines of SRX-target set-form.

* **Junos OS Content Security (UTM) User Guide** (live, 2025-12-07).
  PDF: `https://www.juniper.net/documentation/us/en/software/junos/utm/utm.pdf`
  Vendor doc.  Antivirus / antispam / content-filtering / web-filtering configs.  `set security utm feature-profile`, `set security utm utm-policy`.

* **Junos OS Security Policies User Guide for Security Devices**.
  PDF: `https://www.juniper.net/documentation/us/en/software/junos/security-policies/security-policies.pdf`
  Vendor doc.  Worked examples for global policies, zone-pair policies, scheduled policies, dynamic-application policies.

#### GitHub repositories (Apache-2.0 / MIT confirmed)

* **`Juniper/vSRX-AWS`** — `https://github.com/Juniper/vSRX-AWS`
  License: **Apache-2.0**.  Contains AWS Terraform modules + Junos init configs that bootstrap vSRX with security zones + IPsec ready for transit-VPC.  HCL-heavy but Junos snippets are embedded.

* **`Juniper/vSRX-Azure`** — `https://github.com/Juniper/vSRX-Azure`
  License: **Apache-2.0**.  ARM templates + sample vSRX startup configs for Azure deployment.

* **`srl-labs/containerlab`** — `https://github.com/srl-labs/containerlab`
  License: **BSD-3-Clause**.  `lab-examples/vsrx01/` contains `srx1.cfg` (37 lines) + `vsrx01.yml` topology.  References `vrnetlab/vr-vsrx:23.2R1.13` — Junos 23.2 baseline.  Minimal coverage (zones + interfaces only, no policies/IKE/NAT) but BSD-licensed and trivially extensible.

* **`srl-labs/vrnetlab`** (PR #112 — `https://github.com/srl-labs/vrnetlab/pull/112`) — vSRX3.0 support landed 2023.  Bootstrap scripts include sample base configs (BSD-3-Clause).

### 22.x / 21.x / 20.x / 19.x

#### GitHub repositories

* **`bowlercbtlabs/Juniper-vLabs-Lab-2`** — `https://github.com/bowlercbtlabs/Juniper-vLabs-Lab-2`
  Junos version: **18.3R1.9** on vSRX.
  Contains "Full Initial Config" + "Full Final Config" folders — pre/post lab configs (~200-300 lines each) demonstrating security zones + policies (ALLOW_SSH, ALLOW_ICMP).  License: not explicitly stated (likely educational/permissive — verify before import).
  Grammar: `set security zones security-zone trust /untrust`, `set security policies from-zone trust to-zone trust /to-zone untrust`.

* **`thomaxxl/juniper-sec`** — `https://github.com/thomaxxl/juniper-sec`
  JNCIS-SEC study material.  Folders: "Base Config", "IPSEC Debugging", "Chassis Cluster", "NAT", "IPS", "UTM".  Junos version: 12.1 referenced in inline links, but configs are syntactically valid for 15.x+.  License: **not stated** (heavy sanitisation required).
  Coverage: full SRX security stack including chassis cluster, IPsec, UTM, IDP — but each individual config is incomplete (study fragments, not full running configs).

* **`farsonic/pi-disco`** — `https://github.com/farsonic/pi-disco`
  License: **MIT**.  Junos version: **15.1X49-D110** (tested), REST-API needs ≥ 15.1X49-D70.
  Contains SRX integration example configs — `set security policies from-zone trust to-zone untrust policy denied-users match source-end-user-profile denied` — small (illustrative not full), but tagged with model + version.

* **`TrooperT/junos-labs`** — `https://github.com/TrooperT/junos-labs`
  License: **MIT**.  4 lab folders: S2S route-based VPN, S2S OSPF, S2S BGP, hub-spoke route-based VPN.  Configs target SRX (vSRX).  Junos version not stated explicitly — verify per file.
  Grammar exercised: `set security ike`, `set security ipsec`, `set protocols ospf`, `set protocols bgp` on SRX-zoned interfaces.

* **`MrSmitt-tec/juniper-srx100`** — `https://github.com/MrSmitt-tec/juniper-srx100`
  Minimal SRX100B "router-mode" config.  License: **not stated** (use as inspiration, not direct import).  Junos version not explicit.  Demonstrates VLAN-on-SRX, security zones (untrust_internet, trust_zone), port-forwarding NAT.

* **`mohanbvk/JuniperSRX_Cheat_Sheets`** — `https://github.com/mohanbvk/JuniperSRX_Cheat_Sheets`
  License: **GPL-3.0** — **incompatible with Netcanon's permissive fixture pool** (treat as discovery only; do not import directly).  Five cheat-sheet files (hostname/banner, root-auth, interfaces, firewall filters, screen).

* **`SeanBurford/srx300`** — `https://github.com/SeanBurford/srx300`
  Personal install/config notes for an SRX300.  License: not stated.  Inspirational only.

* **`kujiraitakahiro/junos`** — `https://github.com/kujiraitakahiro/junos`
  Contains SRX300 boot logs + `show configuration groups junos-defaults SRX300 15.1X49-D110.4.txt` + `RSI_SRX300_15.1X49-D50.3.txt`.  License: **not stated**.  The `groups junos-defaults` capture is interesting because it documents the vendor's pre-bundled apply-group SRX defaults — useful for testing the codec's `apply-groups` resolution against real SRX defaults.  Junos 15.1X49-D50.3, D110.4, D140.2 captured.

* **`entercas/sd-wan-lte`** — `https://github.com/entercas/sd-wan-lte`
  Jinja2 templates (`sd-wan-lte.j2`, `sd-wan-2wan-lte.j2`) that render to SRX300/320/340/345/550M configs.  License: **not stated**.  Templates not full configs but render to full set-form output.

* **`Azure/Azure-vpn-config-samples`** — `https://github.com/Azure/Azure-vpn-config-samples`
  Path: `Juniper/Current/SRX/juniper-srx-junos_12.1_show_configuration.txt` (326 lines, Junos 12.1, IKEv2 + AES-256 + IPsec + zone-based policy for Azure connectivity) and `Juniper/Older/SRX/juniper-srx-junos-10.2.cfg` (16 KB) + `juniper-srx-junos-11.4-dynamic-routing.cfg` (17 KB).
  License: **not explicitly stated** in repo (Microsoft Azure samples — usually MIT or Microsoft permissive, verify via repo LICENSE before import; the repo does not have a top-level LICENSE file).
  Grammar exercised: full IKE+IPsec route-based VPN, security policies, zones, NAT, screen.

* **`GoogleCloudPlatform/community` (archived)** — `https://github.com/GoogleCloudPlatform/community/blob/master/archived/using-cloud-vpn-with-juniper-srx/index.md`
  Junos version: **15.1X49-D100.6** on SRX300 (also applies to SRX220/240/550/1400/3400, vSRX).
  Embedded config: ~150-200 lines of set-form covering IKE proposal/policy/gateway, IPsec proposal/policy/VPN, BGP-over-tunnel, security zones (trust/untrust/vpn-gcp), policies.
  License: GoogleCloudPlatform/community archived; explicit disclaimer "informational in nature".  Likely Apache-2.0 (matches the org default) — verify before import.

* **`Juniper-SE/SRX-configure-security-policies`** — `https://github.com/Juniper-SE/SRX-configure-security-policies`
  License: **Apache-2.0**.  Nornir + Jinja2 templates for security-policy rendering.  Not full configs but the Jinja2 templates render to authentic SRX set-form output.

* **`djaity/juniper-config-parser`** — `https://github.com/djaity/juniper-config-parser`
  License: **MIT**.  Parser tool (Python).  README documents the expected SRX address-book / address-set / zone / policy grammar — useful reference but the test-data corpus is generated from live devices (not committed to repo).

* **`JNPRAutomate/JNPRAutomateDemo-Class`** — `https://github.com/JNPRAutomate/JNPRAutomateDemo-Class`
  License: **MIT**.  vSRX automation class material — set-security playbooks render full security policy + zone configs.  ~35 stars.  Junos version not stated; templates are version-agnostic.

* **`cloud-design-dev/IBM-Cloud-JunipervSRX-Terraform-Ansible`** — `https://github.com/cloud-design-dev/IBM-Cloud-JunipervSRX-Terraform-Ansible`
  License: **not stated** (verify).  vSRX on IBM Cloud — Ansible playbooks for interfaces, security policies, IPsec, logging.

* **`ibm-cloud-docs/vsrx`** — `https://github.com/ibm-cloud-docs/vsrx`
  IBM Cloud vSRX docs.  `vsrx-version-notes.md` is a useful version-compatibility reference (notes 19.4R3-S2 clustering bug).  Docs license usually Apache-2.0 for IBM Cloud Docs repos — verify.

#### GitHub Gists

* **`gist.github.com/njh/f39bee575099a3d6057baecf62807d4c`** — Full SRX config (~250 lines) for cable-router setup, Junos 12.1X46-D66.1, DHCP client (WAN) + DHCP server (LAN) + source-NAT + zones (trust/untrust) + screen options.  License: implicit gist default (no explicit LICENSE).
* **`gist.github.com/adionditsak/6ec696fc1961c4829d71`** — SRX cheatsheet (~60 lines).  Set-form syntax reference, no full config.
* **`gist.github.com/5d7a97224ad5bcfece9b90105a3af70e`** — "Template-Juniper_SRX300_RETH-BASIC-IPoE" — RETH (chassis cluster) + IPoE config template.

#### Batfish parsing-test corpus (highest-leverage seed)

* **`batfish/batfish` → `tests/parsing-tests/networks/srx-testbed/configs/`** —
  License: **Apache-2.0** (matches repo default).
  - `junos-srx-1.cfg` — ~180 lines, **Junos 15.1X49-D15.4**.  IKE + IPsec (2 gateways, 2 tunnels with PFS), zones (trust/untrust/hostos/loopback), security policies (zone-pair + global default-deny), screen IDS (SYN-flood, ping-death, source-route, tear-drop, land), host-inbound-traffic.
  - `junos-srx-2.cfg` — ~110 lines, **Junos 15.1X49-D15.4**.  IKE + IPsec (vpn-1, vpn-3), screen, 4 zones, default-deny, SSH RSA + encrypted passwords.
  - `junos-srx-3.cfg` — ~150 lines (estimated from 7.4 KB), **Junos 15.1X49 family**.  Similar shape.
  **These three files are the strongest candidate seed corpus** — explicit version, broad grammar coverage, clean Apache-2.0 license, already sanitised (batfish project hygiene).  Recommend importing these as the foundation of the SRX fixture set, mirroring the pattern used by the batfish-sourced fixtures already in `tests/fixtures/real/junos/` and `arista_eos/` etc.
* **`batfish/batfish` → `projects/batfish/src/test/resources/org/batfish/grammar/juniper/testconfigs/`** —
  License: **Apache-2.0**.  Per-feature parser-grammar tests.  Small (each 100-2400 bytes, ~5-80 lines) but each isolates a specific security grammar surface — perfect for unit-style fixtures:
  - `firewall-combined-policies` (1852 bytes), `firewall-zone-address-book-attach` (783), `firewall-zone-address-book-global` (724), `firewall-zone-address-book-inline` (743), `firewall-global-policy` (557), `firewall-global-policy-global-address-book` (637), `firewall-policies` (648), `firewall-source-address` / `firewall-destination-address` / `firewall-address`
  - `ike-policy` (719), `ike-proposal` (469), `ipsec-policy` (1106), `ipsec-proposal` (1160), `ipsec-proposal-set` (160), `ipsec-vpn` (2303), `ipsec-bugs` (403)
  - `juniper-nat-pat` (838), `juniper-nat-static` (1478), `juniper-nat-vrf` (234), `juniper-sourcenat-pool` (344)
  - `security-address-book-global-address` (121), `security-policy` (527), `security-zone-term-refs` (170)
  - `screen-options` (6686 bytes — largest single file; covers a lot of `set security screen ids-option` syntax)
  - `application-set` (934), `application-set-nested` (831), `application-with-terms` (439), `applications` (847), `pre-defined-junos-applications` (4096) /`pre-defined-junos-application-sets` (2424) /`pre-defined-junos-applications-converted` (16996)
  These pair well with the three `srx-testbed` configs above — together they'd give the codec both per-feature unit coverage and integrated grammar.

#### Operator blogs (inspiration, not direct import)

* `jncie.tech/2017/07/13/srx-security-zones-and-policies/` — security zones + policies walkthrough.
* `rayka-co.com/lesson/juniper-srx-*` — multi-lesson series covering zones, policies, screen options, NAT, IKE/IPsec VPN, monitoring.  Comprehensive but operator-written examples; treat as fair-use reference for drafting synthetic fixtures.
* `letsconfig.com/configure-juniper-srx-from-scratch/` and `letsconfig.com/how-to-configure-site-to-site-route-based-ipsec-vpn-on-juniper-srx/` — practical walkthroughs.
* `packetswitch.co.uk/juniper-srx-nat-configuration-example/` — NAT-focused walkthrough.
* `petenetlive.com/KB/Article/0000995` — static one-to-one NAT.
* `tunnelsup.com/configuring-nat-in-juniper-srx-platforms-using-junos/` — NAT recipes.
* `blog.netpro.be/setting-up-a-virtual-lab-topology-with-juniper-vsrx/` — vSRX lab setup with security zones.
* `saidvandeklundert.net/2015-08-01-juniper-vsrx-lab-setup-configuration/` — vSRX init config example.
* `blog.marquis.co/posts/2015-04-29-creating-ha-juniper-srx-chassis-cluster/` — chassis-cluster walkthrough.
* `medium.com/@mohsinzia90/how-to-configure-chassis-cluster-in-juniper-srx-860c02ddfbbf` — chassis-cluster step-by-step.
* `iosonounrouter.wordpress.com/tag/srx/` — series of SRX deep-dives.
* `doittherightway.wordpress.com/2015/01/27/how-to-change-the-order-of-security-policies-in-juniper-srx/` — policy ordering.

#### Forum threads (operator-share precedent — heavy sanitisation needed)

* `community.juniper.net/discussion/srx-policy-ordering-with-mulitple-zones` — concrete SRX zone-policy thread.  Operator-share precedent (similar to the HPE Community forum entries already in `NOTICE.md`).
* `community.juniper.net` "Ingenious Champions" thread "New SRX Day One Book!" — discussion threads frequently include sanitised SRX configs from JTAC questions.
* Network Engineering Stack Exchange — `networkengineering.stackexchange.com` SRX-tagged questions (CC-BY-SA-licensed; compatible with permissive pool with attribution).  Search: `[juniper] [srx]` and `[junos] [srx]` tags.

#### Cisco-ASA-to-SRX migration tools (orthogonal value — render full SRX configs)

* `glennake/DirectFire_Converter` (61 stars) — multi-vendor converter that emits SRX security-policy syntax from ASA input.  Output examples can be imported as fixtures *if* the source ASA-input license permits the derivative work.
* `glennake/SRX-to-ASA-Converter`, `joshcorr/asa-to-srx-converter`, `mbaniadam/Juniper-SRX-to-FortiGate` — similar inversion tools.

### 18.x / 17.x / 16.x / 15.x retrospective

The 15.1X49-D and 17.4 / 18.4 branches are heavily represented in legacy
fixtures.  Most of the entries already listed above target these branches
(batfish srx-testbed is 15.1X49-D15.4; `farsonic/pi-disco` is 15.1X49-D110;
`kujiraitakahiro/junos` is 15.1X49-D50/D110/D140; `GoogleCloudPlatform/community`
is 15.1X49-D100.6).  Additional retrospective sources:

* **`O'Reilly Juniper SRX Series` (Gregg + Woodberg, 2013)** — 2013 publication
  but Junos 12.x grammar is identical for the security hierarchy.  Chapters
  with config: ALG (ch.10), IPsec VPN (ch.10), policies + zones.  Free
  preview at `https://www.oreilly.com/library/view/juniper-srx-series/9781449339029/`.
  Provenance class: copyrighted (cert prep / commercial book — do NOT import
  directly; use as inspiration only).
* **Day One: Deploying SRX Series Services Gateways** (Barny Sanchez, 2010).
  Older; superseded by "SRX Series Up and Running" (2018).  Available on
  Scribd / Google Books.  Discovery-only.
* **Day One: Configuring SRX Series with J-Web** (Mark Smallwood + Uma Rao).
  Browser-config-focused; less set-form content but recipes are valid.
* **Day One: Migrating from Cisco ASA to Juniper SRX Series / Migrating from
  Cisco to Juniper Networks** (Martin Brown, Rob Jeffery, 2018).  Apple Books:
  `https://books.apple.com/us/book/day-one-migrating-from-cisco-to-juniper-networks/id1342334133`.
  Detailed ASA→SRX command pairing with worked configs.
* **Day One: IPsec VPN Cookbook 2018** (Johan Andersson).
  PDF: `https://www.juniper.net/documentation/en_US/day-one-books/DO_IPsec_VPNs_2018.pdf`.
  Cookbook of IKE/IPsec recipes — ~20-30 full SRX config examples.
* **Day One: vSRX on KVM** (2019).  Apple Books:
  `https://books.apple.com/us/book/day-one-vsrx-on-kvm/id1457102454`.
* **Day One: Juniper Ambassadors' Cookbook 2014 / 2019** —
  - 2014: `https://higherlogicdownload.s3.amazonaws.com/JUNIPER/MigratedAssets3/DO_Ambassadors_2014.pdf`
    contains "Recipe 18: Quick Configuration of the Juniper-Kaspersky Antivirus on the SRX"
    and "Recipe 3: Configuring a SRX Series Integrated Firewall".
  - 2019: `https://www.juniper.net/documentation/en_US/day-one-books/DO_Ambassadors2019.pdf`
* **SRX Series Security Services poster** (laminated reference; PDF at
  `https://www.juniper.net/assets/us/en/local/pdf/books/day-one-poster-srx-security-services.pdf`)
  — small set-form snippets, useful as cross-reference.

#### TechLibrary individual examples (HTML — easy to extract, well-versioned)

* `https://www.juniper.net/documentation/en_US/junos12.1x46/topics/example/security-srx-device-zone-and-policy-configuring.html`
  — "Example: Configuring Security Zones and Policies for SRX Series" (12.1X46 documented; same syntax through 22.x).
* `https://www.juniper.net/documentation/en_US/junos12.3/topics/example/nat-configuration-examples-srx-series.html`
  — "Example: Configuring NAT on SRX Series and J Series Devices" (12.3 era; syntax stable).
* `https://www.juniper.net/documentation/en_US/junos12.1x47/topics/example/security-branch-device-utm-configuring.html`
  — "Example: Configuring UTM for a Branch SRX".
* `https://www.juniper.net/documentation/en_US/release-independent/nce/topics/example/nce-139-srx-series-security-configuration.html`
  — Release-independent "Quick Start" SRX security config example.
* `https://www.juniper.net/documentation/us/en/software/junos/chassis-cluster-security-devices/topics/example/chassis-cluster-srx-full-mesh-configuring.html`
  — "Example: Configure Full Mesh Chassis Cluster" (versioned).

---

## Recommended pull priority order

1. **Three batfish `srx-testbed` configs** (Apache-2.0, ≥100 lines each,
   Junos 15.1X49-D15.4, broad grammar coverage — IKE/IPsec + zones + policies
   + screen).  Mirror the import pattern already used in
   `tests/fixtures/real/junos/batfish_evpntype5_router1_junos2541.set`
   and friends.  **Single highest-leverage import**.
2. **Day One+ SRX300/320/345/380 PDFs** (vendor docs; full branch-office
   configs in set-form including NAT-source-rule-set + UTM + zones + policies;
   Junos 21.4R1 baseline).  Day One license verification required — see
   § "License notes".
3. **`Azure/Azure-vpn-config-samples`** Juniper SRX captures (legacy 10.2/11.4
   + current 12.1 — three configs of 8-17 KB each, full IKE+IPsec+policy+zone+NAT)
   pending license verification (no top-level LICENSE file in repo).
4. **`GoogleCloudPlatform/community` archived SRX VPN guide** (15.1X49-D100.6;
   150-200 line config — IKE + IPsec + BGP-over-tunnel + zones).  Apache-2.0
   org default likely applies — verify.
5. **`bowlercbtlabs/Juniper-vLabs-Lab-2`** Full Initial / Final configs
   (Junos 18.3R1.9 on vSRX; 200-300 lines each).  License verification needed
   (likely educational — get authorisation from author).
6. **`farsonic/pi-disco`** (MIT, 15.1X49-D110 SRX device-profile policy example)
   — small but explicit version + MIT license.
7. **`TrooperT/junos-labs`** (MIT, 4 lab folders covering S2S route-based VPN,
   OSPF, BGP, hub-spoke route-based VPN on SRX).
8. **`Juniper/vSRX-AWS` + `Juniper/vSRX-Azure`** (Apache-2.0; cloud-deployment
   bootstrap configs — extract embedded Junos snippets).
9. **`srl-labs/containerlab` vsrx01 example** (BSD-3, minimal 37-line vSRX 23.2
   starter — useful as a *modern Junos branch* anchor even though small).
10. **Per-feature batfish testconfigs** (Apache-2.0; unit-style fixtures —
    `firewall-combined-policies`, `screen-options`, `ipsec-vpn`,
    `juniper-nat-static`, etc.).  Treat as a second wave once the integration
    fixtures from (1)+(3) land.

This pulls 2015 / 18.x / 21.x / 23.x branches, covers branch + DC + virtual
hardware classes, exercises the entire SRX security grammar, and stays inside
the existing license-confidence profile (Apache-2.0 / MIT / BSD-3 dominate).

---

## License notes

### Day One Books "free for educational use"

Juniper's Day One PDFs are downloadable at no cost from
`juniper.net/dayone` (Juniper J-Net account login).  The cover-page legal
text on most Day One books reads "© Juniper Networks, Inc. ... All
rights reserved" — **this is NOT a CC-BY license**, contrary to
[`WANTED.md`](../../tests/fixtures/real/WANTED.md) and
[`00-source-analysis.md`](00-source-analysis.md) which both characterise
Day One Books as CC-BY.  Specifically:

* Day One PDFs are free to **download and read**.
* Inline code samples are typically marked "Use these recipes" or
  "verify before using" — vendor doc fair-use precedent applies.
* The CONFIGURATIONS inside are vendor-authored examples (synthetic
  IPs, fictional hostnames) — these are commonly understood as
  "reference material" the way Cisco Configuration Guide examples are.

**Recommendation**: treat Day One configs as **inspiration, not direct
import** — the fair-use boundary for vendor examples is "use, don't
republish the whole PDF".  When pulling a recipe, *rewrite* it as a
synthetic fixture rather than copying verbatim, and credit the source
in NOTICE.md.  Or contact Juniper for an explicit license clarification.

This is similar to how the per-vendor catalogues should handle Cisco
Configuration Guide examples (see `01-cisco_iosxe.md` discussion).

### Microsoft Azure VPN config samples

`Azure/Azure-vpn-config-samples` does not have a top-level LICENSE file.
Microsoft typically applies MIT to public Azure samples repos.  Confirm via
the org's blanket license policy or open an issue before importing.

### vSRX clustering bug warning (IBM Cloud)

IBM Cloud vSRX docs flag "all versions before 19.4R3-S2 are prone to
clustering issues and crashing" — fixtures captured from those versions
may include workaround grammar (e.g. extra `set chassis cluster`
heartbeat-tuning) that operators don't want propagated as canonical
examples.  Filter accordingly.

---

## Out-of-scope (deliberately excluded)

* **ScreenOS** — pre-Junos firewall OS (the original NetScreen/SSG line).
  Distinct grammar, no Junos heritage, no codec opportunity for SRX shared
  scaffolding.  `Azure/Azure-vpn-config-samples` has `Juniper/Older/SSG/`
  and `Juniper/Older/ISG/` directories — those are ScreenOS, not SRX, and
  should not be pulled into a `juniper_srx` fixture pool.
* **J-Series / SRX-A** — branch routers pre-dating SRX300 line.  Some
  shared `set security` grammar but the platforms are EOS and operationally
  irrelevant for 2026 capture.
* **Cert prep workbooks** — JNCIA-SEC / JNCIS-SEC / JNCIP-SEC study
  guides (Pluralsight, Udemy, INE, official Juniper Education courseware).
  Copyrighted; don't import.
* **`O'Reilly Juniper SRX Series` book** (Gregg + Woodberg, 2013) —
  copyrighted; useful for inspiration but no direct import.
* **`mohanbvk/JuniperSRX_Cheat_Sheets`** — **GPL-3.0**; copyleft
  incompatible with permissive fixture pool.
* **Operator-deployed configs from forum threads** — implicit operator-
  share precedent applies but requires heavy sanitisation per
  [`BUG_REPORTING.md`](../../BUG_REPORTING.md) (real-WAN IP scrub,
  hashed-password scrub, hostname scrub).  Treat as a *secondary* source
  after Tier-1 / vendor-doc sources are exhausted.

---

## See also

* [`README.md`](README.md) — folder index + scope.
* [`00-source-analysis.md`](00-source-analysis.md) — source-type taxonomy
  + license-confidence guidance.
* [`02-juniper_junos.md`](02-juniper_junos.md) — sibling EX/QFX/MX catalogue.
  Most of the Junos versioning / GitHub-discovery patterns identified here
  carry over.  Cross-reference for `juniper_junos` codec-architecture decisions:
  - Set-form tokeniser (`set system host-name X`) is shared.
  - Block-form converter (`{` /`}` /`;` to set-form normalisation) is shared.
  - `apply-groups` resolution is shared (`groups junos-defaults` from
    `kujiraitakahiro/junos` captures is an SRX-specific apply-groups
    target).
  - Differentiator is the SRX dispatch tree for `security`, `applications`,
    `services`, `chassis cluster` — a future `juniper_srx` codec should
    implement these as a **second dispatcher tier** registered with the
    same lexer.
* [`tests/fixtures/real/junos/`](../../tests/fixtures/real/junos/) —
  existing 7-file `juniper_junos` corpus (no SRX content; all EX/QFX/MX).
  When SRX fixtures land, they should live alongside under a sibling
  `tests/fixtures/real/junos_srx/` to keep the codec dispatch separable.
* [`tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md) —
  provenance ledger of existing fixtures; the `batfish_*_junos2541.set` and
  `ksator_labmgmt_*.set` entries provide the template for documenting any
  imported SRX fixtures.
* [`tests/fixtures/real/WANTED.md`](../../tests/fixtures/real/WANTED.md) —
  operator-facing gap list; the "Juniper SRX" row in the Tier-D table
  cites "Juniper Day One Books PDFs (CC-BY), Junos Genius" — the CC-BY
  characterisation is **inaccurate** per § "License notes" above.  Open
  an issue to update WANTED.md once a codec lands.
* [`BUG_REPORTING.md`](../../BUG_REPORTING.md) — sanitisation +
  fixture-submission workflow.
* [`docs/v0.2.0-planning/`](../v0.2.0-planning/) — no SRX-specific design
  doc exists yet (the `03-nxos-codec/` and `04-iosxr-codec/` siblings
  show the design-doc shape a future `juniper_srx` codec would follow).

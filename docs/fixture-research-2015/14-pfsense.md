# pfSense — fixture catalogue (2015+)

> **Tier**: Tier-D (no codec yet; **could share codec layer with `opnsense`** per WANTED.md)
> **Existing corpus**: 0 pfSense-specific fixtures
> **Adjacent codec**: `opnsense` codec parses the OPNsense `config.xml` which is structurally similar but NOT identical (OPNsense fork in 2015 has added / renamed / removed elements over time — see Codec-sharing feasibility below)

pfSense is the upstream BSD firewall distribution that OPNsense forked from in January 2015 (the very start of this catalogue's window). Configurations are stored in a single XML file at `/cf/conf/config.xml` (alias `/conf/config.xml`) with a `<pfsense>` root element. The schema overlaps substantially with OPNsense's `<opnsense>` tree — top-level zones `<system>`, `<interfaces>`, `<vlans>`, `<dhcpd>`, `<virtualip>`, `<snmpd>`, `<gateways>`, `<openvpn>`, `<ipsec>`, etc. are all named identically — but field-level differences are real (notable: pfSense user passwords land in `<bcrypt-hash>`, OPNsense in `<password>`; pfSense's default user is `admin`, OPNsense's is `root`).

The pfSense main repository [`pfsense/pfsense`](https://github.com/pfsense/pfsense) is **Apache-2.0 licensed** (not BSD as the WANTED.md note assumed — easier license-compatibility story than expected). The repo ships a factory-default `config.xml` template that's reusable as a trivial parse fixture.

## Version timeline

pfSense's release-numbering scheme split in 2021 when Netgate introduced the **pfSense Plus** branding alongside the existing CE (Community Edition). CE keeps the `2.X.Y` numbering; Plus uses `YY.MM` calendar-versioning. Both share a common code base but ship on different cadences with Plus carrying Netgate-exclusive features (e.g. AWS / Azure integration, advanced ZFS).

| Version | Release | Notable changes | Plus vs CE | Priority |
|---|---|---|---|---|
| 2.2 | 2015-01-23 | FreeBSD 10.1; **pre-OPNsense-fork** (fork made Jan 2015 from 2.1.x) | n/a (single product) | Low (legacy) |
| 2.2.6 | 2015-12-21 | Last 2015-era patch | n/a | Low |
| 2.3 | 2016-04-12 | Major UI rewrite (Bootstrap 3); FreeBSD 10.3 | n/a | Low |
| 2.4 | 2017-10-08 | **First 64-bit-only release**; FreeBSD 11.1; nginx replaces lighttpd | n/a | Medium |
| 2.4.4 | 2018-09-24 | TLS 1.3, Coreboot | n/a | Medium |
| 2.4.5 | 2020-03-26 | FreeBSD 11.3; **last pre-Plus-split release** | n/a | Medium |
| 2.5.0 | 2021-02-17 | **Plus split begins**; WireGuard included, FreeBSD 12.2; ZFS default | first split | High |
| 2.5.2 | 2021-07-07 | Final 2.5.x; WireGuard pulled to package | CE side | High |
| 21.02 → 21.05 | 2021 | Plus inaugural branch (formerly Netgate Factory) | Plus side | High |
| 2.6.0 | 2022-02-14 | FreeBSD 12.3-STABLE; new XMLRPC sync; FRR mature | CE | High |
| 22.01 / 22.05 | 2022 | Plus 22.x; ZFS native pool encryption | Plus | High |
| 2.7.0 | 2023-06-29 | FreeBSD 14.0-CURRENT; **Kea DHCP** option (ISC dhcpd default still); pfsensible-friendly | CE | High |
| 23.01 / 23.05 / 23.09 | 2023 | Plus 23.x; Kea DHCP, Tailscale package | Plus | **Highest** (modern + Plus-specific elements) |
| 2.7.2 | 2023-12-07 | Last 2.7.x patch | CE | High |
| 2.8.0 | 2025-05-28 | FreeBSD 15.0-CURRENT; Kea DHCP default; deprecated ISC dhcpd | CE | **Highest** (current CE) |
| 2.8.1 | 2025-09-04 | Latest CE | CE | High |
| 24.03 / 24.11 | 2024 | Plus 24.x | Plus | High |
| 25.07 / 25.11 | 2025 | Plus 25.x | Plus | **Highest** (current Plus) |

## Codec-sharing feasibility with `opnsense`

WANTED.md notes "could share codec layer with OPNsense". Assessment after surveying both schemas:

**Shared (parse with the same handlers, modulo root-tag dispatch):**

* `<system>/<hostname>`, `<system>/<domain>`, `<system>/<timezone>`, `<system>/<timeservers>`, `<system>/<dnsserver>` — identical element shape.
* `<interfaces>/<wan|lan|optN>` — identical zone-keyed flattening; `<if>`, `<descr>`, `<enable/>`, `<ipaddr>`, `<subnet>`, `<ipaddrv6>`, `<subnetv6>` all match.
* `<vlans>/<vlan>` — identical; `<if>`, `<tag>`, `<descr>`, `<vlanif>`.
* `<dhcpd>/<wan|lan|optN>` — same pool-per-zone shape (with the caveat that pfSense 2.7+ / Plus 23.x+ optionally uses Kea — see below).
* `<snmpd>` — same `<rocommunity>`, `<syslocation>`, `<syscontact>`, `<trap*>` shape.
* `<virtualip>/<vip>` with `<mode>carp</mode>` — same CARP HA primitive (`<vhid>`, `<advskew>`, `<advbase>`, `<subnet>`, `<subnet_bits>`, `<password>`); the canonical `CanonicalVRRPGroup(mode="carp")` path in the existing OPNsense codec should round-trip both.
* `<gateways>/<gateway_item>` — same shape (gateway groups slightly diverged after 2.6).

**Diverged (need a per-vendor branch on the same canonical schema):**

* **Root element**: `<pfsense>` vs `<opnsense>`. The OPNsense codec's `parse_intent` hard-checks `root.tag != "opnsense"`; need to relax to accept either, or split codecs at the dispatcher.
* **`<version>` semantics**: pfSense embeds a config-schema version number (e.g. `<version>23.3</version>` for a Plus 23.x export, `<version>22.9</version>` for CE 2.7-era); OPNsense's `<version>` carries a different generation scheme. Codec must NOT use it to infer the product — use the root tag instead.
* **User password field**: pfSense `<system>/<user>/<bcrypt-hash>` vs OPNsense `<system>/<user>/<password>`. Existing `CanonicalLocalUser` parse already tolerates either with a fork at the element name.
* **Default user**: pfSense `admin`, OPNsense `root`. Cosmetic; doesn't affect schema.
* **DHCP backend (pfSense 2.7+ / Plus 23.x+ only)**: Kea sections appear under `<kea>` rather than `<dhcpd>`. Operators migrating to Kea may have BOTH (with `<dhcpd>` disabled but present) or just `<kea>`. The `opnsense` codec doesn't parse Kea today; pfSense codec needs a new branch.
* **WireGuard**: pfSense uses `<wireguard>` directly under root; OPNsense uses `<OPNsense><wireguard>` (nested under a vendor-namespace block). Same field names inside, different XPath prefix.
* **OpenVPN**: same structural shape but pfSense ships `<openvpn>` at root; OPNsense has the same.
* **IPsec**: pfSense `<ipsec>/<phase1>`+`<phase2>` shape is roughly preserved on the OPNsense side but field renames around 2.4+.
* **NAT / filter rules**: both have `<nat>` and `<filter>/<rule>` but the per-rule attribute set has drifted significantly — OPNsense added a `<floating>` flag with a comma-separated `<interface>` list (custom InterfaceList type) where pfSense uses repeated children.
* **HA sync (`xmlsyncport`, `synchronize*`)**: lives under `<hasync>` in pfSense; OPNsense relocated this.

**Recommendation**: ship a single `pfsense_opnsense_xml` codec layer with a vendor-detect dispatcher reading the root element (`<pfsense>` vs `<opnsense>`), branching only at the genuinely divergent fields. The existing `opnsense` codec's `parse_intent` and `render_intent` are good scaffolding to lift into a shared `_xml_firewall_common` module with `vendor` parameter. Estimated incremental cost: ~30% of a from-scratch codec given how much can reuse the OPNsense path.

## Pull-target inventory

### pfSense Plus 24.x / 25.x current

#### GitHub repositories

* **[`sheridans/pfopn-convert`](https://github.com/sheridans/pfopn-convert)** — BSD-2-Clause. Bidirectional pfSense↔OPNsense converter with a `fixtures/` directory containing the highest-value pull-targets in this catalogue:
  * [`fixtures/pfsense-base.xml`](https://github.com/sheridans/pfopn-convert/blob/main/fixtures/pfsense-base.xml) — 88 KB, ~2 100 lines, `<version>23.3</version>`, hostname `host.example.com`. Exercises `<interfaces>` (WAN/LAN), `<dhcpd>`, `<dhcpdv6>`, `<openvpn>`, `<wireguard>`, `<snmpd>`, `<unbound>`, `<gateways>`. **No VLANs / VirtualIP / IPsec / CARP / Syncrules** (standalone deployment). Best single-fixture parse-coverage target.
  * [`fixtures/pfsense-base-kea.xml`](https://github.com/sheridans/pfopn-convert/blob/main/fixtures/pfsense-base-kea.xml) — 82 KB, ~2 850 lines, `<version>23.3</version>`. Same hostname; exercises the **Kea DHCP** backend (Plus 23.x feature), plus traffic-shaping rules, NAT port forwarding for VoIP, Snort IDS/IPS, Squid+antivirus, pfBlockerNG, Tailscale integration as installed packages. Demonstrates the modern Plus-era schema.
  * Sanitisation: **already done by the upstream author** (host.example.com placeholder, no real IPs); minor re-verification recommended.
  * License confidence: **High** (BSD-2-Clause).
  * Grammar surface: hostname, dns/ntp, interfaces (zone-flattened), dhcpd v4/v6, kea, openvpn, wireguard, snmpd, unbound, gateways.

#### Forum / community posts (Netgate Forum)

* `forum.netgate.com` — Tier 2.1 in `00-source-analysis.md`. Operators paste sanitised config.xml excerpts heavily for help requests. CARP HA, multi-WAN load-balancing, IPsec VPN troubleshooting threads are the high-leverage clusters.
  * [CARP and failover guide](https://forum.netgate.com/topic/105330/carp-and-failover-guide) — config snippets for HA pairs, `<vhid>`/`<advskew>`/`<advbase>` patterns.
  * [Multi-WAN: Load Balancing and Fail-over Setup](https://forum.netgate.com/topic/65547/multi-wan-load-balancing-and-fail-over-setup) — `<gateways>/<gateway_group>` shape.
  * [HA Setup](https://forum.netgate.com/topic/197194/ha-setup) — current-era HA pasted excerpts.
  * Sanitisation: **heavy** (hostnames, IPs, hashes may not all be redacted).
  * License confidence: Medium (forum-share precedent per NOTICE.md).

#### Vendor docs / lab guides

* [docs.netgate.com — XML Configuration File](https://docs.netgate.com/pfsense/en/latest/config/xml-configuration-file.html) — top-level explainer; no full sample but documents the storage path and edit workflow.
* [docs.netgate.com — High Availability Configuration Example](https://docs.netgate.com/pfsense/en/latest/recipes/high-availability.html) — reference HA pair shape that synthetic fixtures can mirror.
* [docs.netgate.com — WireGuard Site-to-Site VPN Configuration Example](https://docs.netgate.com/pfsense/en/latest/recipes/wireguard-s2s.html) — modern (2.7+) wireguard config example.
* [docs.netgate.com — Releases / Versions Index](https://docs.netgate.com/pfsense/en/latest/releases/versions.html) — full release timeline (sourced for the version table above).
* License: Netgate documentation appears under Creative Commons-style permissive reuse for examples; cite source per NOTICE.md.

### pfSense CE 2.7 / 2.8 current

#### GitHub repositories

* **[`pfsense/pfsense`](https://github.com/pfsense/pfsense)** (Apache-2.0) — the main repo. The factory default config.xml lives somewhere under `src/conf.default/config.xml` (path referenced from `src/etc/inc/config.lib.inc` as `{$g['conf_default_path']}/config.xml`). Direct WebFetch returned 404 — needs `gh api` exploration when actually pulling. This is the absolute baseline parse fixture (no operator content, trivial sanitisation).
* **[`ahuacate/pfsense-setup`](https://github.com/ahuacate/pfsense-setup)** — targets pfSense **2.7+**. Includes ready-to-restore XML files under [`restore/`](https://github.com/ahuacate/pfsense-setup/tree/main/restore):
  * `pfsense.all.xml` — comprehensive config (full backup shape).
  * `pfsense.aliases.xml` — `<aliases>/<alias>` subtree (firewall aliases).
  * `pfsense.firewall.rules.xml` — `<filter>/<rule>` subtree.
  * License: not explicitly stated on the repo card — verify before pulling. Sanitisation: already-baselined templates, no real-network content expected.
  * Grammar surface: full backup, aliases, filter rules.
* **[`nixbitcoin/pfSense-guide`](https://github.com/nixbitcoin/pfSense-guide/blob/master/config-pfSense.xml)** — 1146-line config.xml from pfSense **2.4-era** (`<version>19.1</version>` ≈ schema-version-19.1, CE 2.4.x). Exercises `<system>`, `<interfaces>` (WAN/LAN/DMZ/VLANs/VPN tunnels), `<dhcpd>`, `<dhcpdv6>`, `<snmpd>`, `<nat>`, `<filter>`, `<cron>`, `<load_balancer>`, `<ipsec>`. Three VLANs, multiple OpenVPN connections (MULLVAD1/2), policy-based routing, port forwarding. **No CARP/HA**. License: not explicitly stated — verify; partial-fairness use as research reference clearly OK.
* **[`broccoliandpepper/Infra-pfSense`](https://github.com/broccoliandpepper/Infra-pfSense)** — production homelab infrastructure. Hyper-V + Samba AD + VLANs + DMZ + Traefik reverse proxy. Worth scanning for the documentation; may have a config dump.
* **[`StefanScherer/pfsense-packer`](https://github.com/StefanScherer/pfsense-packer/blob/master/http/config.xml)** — Packer-template config.xml. **538 lines**, encodes pfSense **2.x-era** (`<version>9.8</version>` ≈ very-early 2.x schema-version). Exercises baseline system/interfaces/DHCP/dnsmasq/SNMP/syslog/firewall/sysctls/cron/load-balancer/certificates. **Pre-2.4-era**, useful as a legacy-baseline parse target.
* **[`ladysheraz/pfSense-HomeLab-Setup`](https://github.com/ladysheraz/pfSense-HomeLab-Setup)** — SOC homelab guide; WAN+LAN+DMZ(OPT1), DHCP, firewall/NAT.

#### Forum / community posts

Same as Plus 24.x / 25.x — Netgate Forum dominates. Older CE-specific threads (2.4 / 2.5 era) cluster around the 2018-2021 timeframe.

#### Other

* **[pfSense Redmine bug tracker](https://redmine.pfsense.org)** — operator-attached sanitised config.xml files on issues. Concrete examples:
  * [Attachment 2803 (`config-sanitized.xml`)](https://redmine.pfsense.org/attachments/2803/config-sanitized.xml) — Tinc VPN status issue (#9740). `<version>19.7</version>` (≈ 2.5-development-branch CE), hostname `pf4`. WAN/LAN(MGMT)/WAN2/PFSYNC interfaces (the PFSYNC interface confirms an HA pair), DHCP v4/v6 pools, filter rules for WAN/LAN/Tinc VPN. **Extensive package list**: Snort, Suricata, Squid, HAProxy, FRR routing, Tinc. Sanitisation already heavy (passwords marked `xxxxx`). High-value HA + package-rich pfSense 2.5-dev fixture.
  * [Attachment 2515 (`config.xml`)](https://redmine.pfsense.org/attachments/2515/config.xml) — another bug-tracker attachment; verify content before pulling.
  * [Attachment 3833](https://redmine.pfsense.org/attachments/3833) (`config-20210818131204.xml`) — 2021-dated.
  * [Attachment 3664](https://redmine.pfsense.org/attachments/3664) (`config-pfSense.home.arpa-20210518194823.xml`) — 2021 home.arpa-domain export.
  * License: Redmine attachments inherit issue-poster's implicit share-for-help intent; verify per-attachment, treat as Tier 2 forum-share class.
* **[`smccloud/pfSense-to-OPNSense-Config-File-Converter`](https://github.com/smccloud/pfSense-to-OPNSense-Config-File-Converter)** — MIT-licensed converter. Does NOT include sample fixtures (operator-byo workflow), but the source code documents the field-mapping table — useful for the codec-sharing analysis above.
* GitHub Gists — small / structurally-incomplete:
  * [`Paxxi/68b64ef19d0e68c255d0`](https://gist.github.com/Paxxi/68b64ef19d0e68c255d0) — "Working with pfsense dhcpd.xml in Powershell" — DHCP-only excerpts.
  * [`deergod1/818ec78ab70947a2f89df2bb5bb28896`](https://gist.github.com/deergod1/818ec78ab70947a2f89df2bb5bb28896) — HP t620 Plus setup guide.
  * [`mwpastore/9b47ba0fd9d07b93dbf795c4ee33dead`](https://gist.github.com/mwpastore/9b47ba0fd9d07b93dbf795c4ee33dead) — Unbound + dnsmasq custom DNS configuration.

### pfSense 2.5 / 2.6 (CE)

* [`StefanScherer/pfsense-packer`](https://github.com/StefanScherer/pfsense-packer) Packer config.xml — listed above; the legacy-baseline.
* pfSense Redmine attachments dated 2021 (the 2021-08 and 2021-05 attachments above) — 2.5-era schema-version exports.

### pfSense 2.4 retrospective

* [`nixbitcoin/pfSense-guide/config-pfSense.xml`](https://github.com/nixbitcoin/pfSense-guide/blob/master/config-pfSense.xml) — `<version>19.1</version>`, CE 2.4.x.
* Netgate Forum threads from 2017-2020 — Tier 2 forum-share; verify per-paste.
* Archive.org — [pfSense 2.4.x install ISO archives](https://archive.org/details/pfSense-some-old-releases) (the ISO itself is not a config but useful to spin up + dump a default config under a virt env).

### pfSense 2.3 / 2.2 retrospective

* Very-thin direct GitHub source — the platform was less GitHub-paste-heavy in 2015-2016. The `archive.org` ISO collection at [pfSense some old releases](https://archive.org/details/pfSense-some-old-releases) covers 2.3.4-2.6.0 (no 2.2.x specifically).
* Netgate Forum pre-2017 threads — Tier 2 forum-share; very heavy sanitisation needed (operators in 2015-2016 were less consistent about redaction).
* Internet Archive (Wayback Machine) for old `doc.pfsense.org` snapshots — used to be 2.2 / 2.3 manuals before docs moved to Netgate domain.

## Recommended pull priority order

The order below assumes the codec ships first as a shared `pfsense_opnsense_xml` layer (per feasibility analysis above) — fixtures should validate both the shared parse path AND the pfSense-specific branches.

1. **`sheridans/pfopn-convert/fixtures/pfsense-base.xml`** — single best fixture. BSD-2-Clause, sanitised, modern (Plus 23.3 ≈ CE 2.7), broad parse coverage. Pull first; establishes baseline.
2. **`sheridans/pfopn-convert/fixtures/pfsense-base-kea.xml`** — same license / sanitisation; exercises the **Kea DHCP** branch that diverges from OPNsense's parse path. Critical for the Plus 23.x+ / CE 2.8 grammar surface.
3. **`pfsense/pfsense` factory default `config.xml`** — Apache-2.0, trivially clean, smallest-possible parse baseline. Locate the file under `src/conf.default/config.xml` via `gh api repos/pfsense/pfsense/contents/src/conf.default` when pulling.
4. **`ahuacate/pfsense-setup/restore/pfsense.all.xml`** — pfSense 2.7+ comprehensive backup; full grammar surface in one file. Verify license before pulling.
5. **`StefanScherer/pfsense-packer/http/config.xml`** — legacy-2.x baseline (538 lines, schema version 9.8). Pulls a pre-2.4 grammar snapshot for regression coverage. Verify license.
6. **Redmine attachment 2803 (`config-sanitized.xml`)** — HA pair (PFSYNC interface) + package-rich (Snort/Suricata/Squid/HAProxy/FRR/Tinc). Sanitisation pre-done; CE 2.5-dev grammar. Pull as the HA / package-coverage fixture.
7. **`nixbitcoin/pfSense-guide/config-pfSense.xml`** — pfSense 2.4-era (`<version>19.1</version>`), VLAN + OpenVPN-as-interface + policy-routing-rich. Pull as the 2.4 retrospective + VLAN-grammar exercise.
8. **Netgate Forum CARP / multi-WAN threads** — pull synthetic-derived fixtures (operator-blog Tier 2.4) rather than direct paste; treat as grammar inspiration for synthetic kitchen-sink construction.

## Out-of-scope (deliberately excluded)

* **Production captures with incomplete sanitisation** — implicitly excluded per `BUG_REPORTING.md` provenance policy.
* **Plus-only license-gated features** — Netgate Plus 23.x+ has features locked to Netgate hardware (e.g. AWS instance integration). Plus-specific elements in `<openvpn>` or `<system>` may appear in operator configs but won't run on CE; the codec should parse them tolerantly but not require them in synthetics.
* **`pfFocus` test fixtures** — although the project is interesting structurally (parses pfSense backup → markdown), its `tests/configs/` directory is empty in the visible upstream snapshot, and pfFocus is **GPL-3.0** which doesn't mix cleanly with the MIT-licensed Netcanon corpus. Use as a structural reference (READ the parsing code for element-name discovery), don't vendor any of its assets.
* **Vendor cert-prep workbooks** — pfSense has no formal certification track, so this Tier 3.2 source class doesn't apply.
* **Pastebin** — search-restricted and historically thin for pfSense (operators prefer Netgate Forum); not worth the noise.
* **YouTube transcripts** — Lawrence Systems, Tom Lawrence, NetworkChuck have many pfSense tutorials but the configs appear on-screen rather than in machine-readable form. Skip unless transcripts surface in description boxes.

## See also

* [`tests/fixtures/real/opnsense/`](../../tests/fixtures/real/opnsense/) (sibling codec corpus; pfSense fixtures may share parser scaffolding — see Codec-sharing feasibility section above)
* [`netcanon/migration/codecs/opnsense/parse.py`](../../netcanon/migration/codecs/opnsense/parse.py) — the parse path most of the shared pfSense logic would lift from
* [`netcanon/migration/codecs/opnsense/codec.py`](../../netcanon/migration/codecs/opnsense/codec.py) — capability matrix to mirror for pfSense (almost all `/system/`, `/interfaces/`, `/vlans/`, `/snmp/`, CARP-group paths transfer directly)
* [`tests/fixtures/real/WANTED.md`](../../tests/fixtures/real/WANTED.md) — Tier-D entry for pfSense
* [`docs/fixture-research-2015/00-source-analysis.md`](00-source-analysis.md) — source-class taxonomy + sanitisation expectations (Tier 1.1 GitHub repo, Tier 2.1 Netgate Forum classes apply most)
* [`tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md) — provenance ledger for committed fixtures (forum-share precedent referenced)

When the codec ships, fixtures will need a new `tests/fixtures/real/pfsense/` directory and a `"pfsense": "pfsense_opnsense_xml"` (or `"pfsense"`) entry in `_DIR_TO_CODEC_NAME` at `tests/unit/migration/test_real_captures.py:80`.

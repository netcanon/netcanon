# OPNsense — fixture catalogue (2015+)

> **Tier**: Shipped
> **Codec**: `opnsense` — see `netcanon/migration/codecs/opnsense/`
> **Existing corpus**: 5 fixtures all on OPNsense 25.x (see
> [`tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md))
> **License-class hint**: OPNsense `config.xml` files are **XML
> documents**, not CLI text.  The codec parses + renders the
> `<opnsense>` root with attention to `<system>` / `<interfaces>` /
> `<vlans>` / `<dhcpd>` / `<unbound>` / `<snmpd>` / `<virtualip>`
> (CARP, wired in v0.1.1 — see codec docstring) / `<openvpn>` /
> `<ipsec>` / `<wireguard>` / `<cert>` / `<user>` / `<group>`.

---

## Version timeline

OPNsense uses Calendar Versioning (`YY.M`): two major releases per
year — `.1` in January, `.7` in July — each with a 6-month
support tail (only the latest major is officially supported with
security patches every two weeks).  Historic versions listed for
completeness; only the most recent two are realistically deployed
on production boxes today, though long-lived home-lab / SMB
installs frequently lag behind by 1-2 majors.

| Version | Codename | Release date | EoS / EoL | In corpus | Priority |
|---|---|---|---|---|---|
| 15.1 | Ascending Albatross | Jan 2015 | Jul 2015 | no | retrospective only |
| 15.7 | Brave Badger | Jul 2015 | Jan 2016 | no | retrospective only |
| 16.1 | Crafty Coyote | Jan 2016 | Jul 2016 | no | retrospective only |
| 16.7 | Dancing Dolphin | Jul 2016 | Jan 2017 | no | retrospective only |
| 17.1 | Eclectic Eagle | Jan 2017 | Jul 2017 | no | retrospective only |
| 17.7 | Free Fox | Jul 2017 | Jan 2018 | no | retrospective only |
| 18.1 | Groovy Gecko | Jan 2018 | Jul 2018 | no | retrospective only |
| 18.7 | Happy Hippo | Jul 2018 | Jan 2019 | no | retrospective only |
| 19.1 | Inspiring Iguana | Jan 2019 | Jul 2019 | no | retrospective only |
| 19.7 | Jazzy Jaguar | Jul 2019 | Jan 2020 | no | retrospective only |
| 20.1 | Keen Kingfisher | Jan 2020 | Jul 2020 | no | retrospective only |
| 20.7 | Legendary Lion | Jul 2020 | Jan 2021 | no | retrospective only |
| 21.1 | Marvelous Meerkat | Jan 2021 | Jul 2021 | no | retrospective only |
| 21.7 | Noble Nightingale | Jul 2021 | Jan 2022 | no | retrospective only |
| 22.1 | Observant Owl | 25 Jan 2022 | 25 Jul 2022 | no | **HIGH (WANTED.md gap)** |
| 22.7 | Powerful Panther | 25 Jul 2022 | 25 Jan 2023 | no | **HIGH (WANTED.md gap)** |
| 23.1 | Quintessential Quail | 25 Jan 2023 | 28 Jul 2023 | no | **HIGH (WANTED.md gap)** |
| 23.7 | Restless Roadrunner | 28 Jul 2023 | 26 Jan 2024 | no | **HIGH (WANTED.md gap)** |
| 24.1 | Savvy Shark | 26 Jan 2024 | 25 Jul 2024 | no | **HIGH (WANTED.md gap)** |
| 24.7 | Thriving Tiger | 23 Jul 2024 | 28 Jan 2025 | no | **HIGH (WANTED.md gap)** |
| 25.1 | Ultimate Unicorn | 28 Jan 2025 | 23 Jul 2025 | yes (`user_contrib_supergate_opn25.xml` is OPNsense 25.x train) | covered |
| 25.7 | Visionary Viper | 22 Jul 2025 | 28 Jan 2026 | no (current; nice-to-have) | nice-to-have |
| 26.1 | Witty Woodpecker | 28 Jan 2026 | (active) | no | nice-to-have |

Dates from
[`endoflife.date/opnsense`](https://endoflife.date/opnsense) +
[`docs.opnsense.org/releases.html`](https://docs.opnsense.org/releases.html).
22.1 onward have firm dates from the official cadence — Jan
24-28 and Jul 22-28 windows.  Older 15-21 dates not authoritatively
sourced; listed by month only.

---

## Existing corpus coverage

Five fixtures, all on the OPNsense 25.x train:

| Fixture | Origin | License | Grammar covered |
|---|---|---|---|
| `opnsense_core_default.xml` | `opnsense/core` repo, `src/etc/config.xml.sample` | BSD-2-Clause | upstream default template — `<system>`, `<users>`, `<groups>`, `<webgui>`, timeservers, bogons, firewall scaffolding |
| `opnsense_service_test_config.xml` | `opnsense/core` repo, `src/opnsense/service/tests/config/config.xml` | BSD-2-Clause | service-layer test — WAN/LAN zone names, DHCP client settings, DHCPv6 prefix delegation, gateway tracking |
| `opnsense_acl_test_config.xml` | `opnsense/core` repo, `src/opnsense/mvc/tests/app/models/OPNsense/ACL/AclConfig/config.xml` | BSD-2-Clause | ACL model test — 4 groups + 5 users; richest `local_users` surface in corpus |
| `user_contrib_supergate_opn25.xml` | User-contributed real `/conf/config.xml` from deployed OPNsense ("supergate") | CC0-1.0 | 2,302-line real deployment: 8 interfaces, 5 VLANs, 2 local users with bcrypt, per-zone DHCP with static MAC reservations, Unbound DNS local overrides, NTP, SNMP, IPsec, WireGuard, self-signed CA + cert chain |
| `opnsense_paramiko_shell_capture.xml` | Synthesised regression fixture (default body with `cat /conf/config.xml\r\r\n` prefix) | BSD-2-Clause *(derived)* | regression fixture for the paramiko-shell command-echo bug |

**Notable absence in existing corpus**: zero CARP / `<virtualip>`
fixtures, despite the codec wiring CARP HA grammar in v0.1.1 (per
`netcanon/migration/codecs/opnsense/parse.py:348-359` —
`<virtualip><vip><mode>carp</mode>` → `CanonicalVRRPGroup` with
`authentication = "carp-key:X"`).  Closing this gap is the
single highest-value pull for the OPNsense codec.

---

## Pull-target inventory

### 24.x (WANTED.md gap — high priority)

#### GitHub repositories
* **`opnsense/core` repository at the `24.1` and `24.7` release
  tags**
  ([https://github.com/opnsense/core/releases/tag/24.1](https://github.com/opnsense/core/releases/tag/24.1) +
  [`/24.7`](https://github.com/opnsense/core/releases/tag/24.7)).
  Same path as the existing 4 fixtures
  (`src/etc/config.xml.sample`,
  `src/opnsense/service/tests/config/config.xml`,
  `src/opnsense/mvc/tests/app/models/OPNsense/ACL/AclConfig/config.xml`)
  but at the **24.1 / 24.7 release tags** rather than `master`.
  Will surface any schema drift the codec hasn't been validated
  against on the 24.x train.  License: BSD-2-Clause.  Sanitisation:
  none (already permissive upstream).  Quality: high — same source
  the 4 existing GitHub-derived fixtures came from.
* **`opnsense/docs` at `24.x` tags**
  ([https://github.com/opnsense/docs/blob/master/source/manual/how-tos/resources/Carp_example_master.xml](https://github.com/opnsense/docs/blob/master/source/manual/how-tos/resources/Carp_example_master.xml)
  + `Carp_example_backup.xml`).  License: BSD-2-Clause per
  `LICENSE` file in repo.  See dedicated CARP section below.

#### Operator GitHub repositories
* **[`Vinetos/infrastructure`](https://github.com/Vinetos/infrastructure)**
  (Apache-2.0) — homelab with Proxmox, Terraform, Ansible, k3s,
  OPNsense.  Description references VLAN distribution.  Worth
  inspecting for actual `config.xml` artefacts in subdirs; some
  homelab repos commit the full XML, others only commit Ansible
  variables or terraform vars.
* **[`marcdely1/homelab-01-proxmox-opnsense`](https://github.com/marcdely1/homelab-01-proxmox-opnsense)**
  — cybersecurity home lab on Dell Optiplex 3060 Micro. Check
  whether `config.xml` is committed in the repo itself.
* **[`rogerp02/proxmox-homelab-infra`](https://github.com/rogerp02/proxmox-homelab-infra)**
  — virtualised homelab with OPNsense + AdGuard + Windows Server
  AD.  License + actual XML presence need confirming.

#### Forum / community posts
* **`forum.opnsense.org` filtered by 24.1/24.7 sub-categories** —
  search for "config.xml" "show" "paste" "share" in
  troubleshooting threads.  Apply HPE Community forum-share
  precedent (heavy sanitisation, attribution).  High value because
  forum posts often include full `<system>` + `<interfaces>` +
  problem-area XML excerpts the operator pasted while requesting
  help.
* **[Forum thread topic=18193](https://forum.opnsense.org/index.php?topic=18193.0)
  "Documentation of config.xml settings"** — points at
  config.xml internals discussions where operators paste fragments.

#### Vendor docs / lab guides
* **[`docs.opnsense.org`](https://docs.opnsense.org/) HA/CARP +
  VLAN tutorials** at the 24.x snapshot — the documentation site
  embeds full XML examples (see CARP section below).  License:
  BSD-2-Clause per `opnsense/docs` repo `LICENSE`.

### 23.x (WANTED.md gap — high priority)

#### GitHub repositories
* **`opnsense/core` at the `23.1` + `23.7` release tags**
  ([https://github.com/opnsense/core/releases/tag/23.1](https://github.com/opnsense/core/releases/tag/23.1) +
  [`/23.7`](https://github.com/opnsense/core/releases/tag/23.7)).
  Same fixture trio as 24.x.  23.7 saw the introduction of
  encrypted-backup support during initial config import; the
  `config.xml.sample` at this tag captures that schema baseline.
* **`opnsense/plugins` repo at 23.x tags** for plugin-specific
  test configs.  License: BSD-2-Clause.

#### Forum / community posts
* **`forum.opnsense.org` 23.1 / 23.7 troubleshooting** — same
  forum-share workflow.  Many threads about the v23.x DHCP /
  Unbound / `vlanif` rename transition where operators paste
  fragments mid-debug.

#### Other
* Internet Archive snapshots of
  `docs.opnsense.org/manual/how-tos/carp.html` from the 23.x
  era — capture the XML examples as they existed pre-25.x
  schema additions.

### 22.x (WANTED.md gap — high priority)

#### GitHub repositories
* **`opnsense/core` at the `22.1` + `22.7` release tags**
  ([https://github.com/opnsense/core/releases/tag/22.1](https://github.com/opnsense/core/releases/tag/22.1) +
  [`/22.7`](https://github.com/opnsense/core/releases/tag/22.7)).
  22.1 has known issues around VLAN interface creation
  (issue #5650 — "Creating new VLAN interfaces fails to bring
  them up") — pulling 22.1 fixtures specifically validates the
  parent VLAN interface form the codec models.

#### Forum / community posts
* **`forum.opnsense.org` 22.1 VLAN tagging threads** —
  operator-posted XML from the 22.1 VLAN-creation issue.  Heavy
  sanitisation required; high value because 22.1 surface predates
  the 23.x schema renumbering.

#### Other
* **[`bmn-m/Stormshield-SN300-opnsense`](https://github.com/bmn-m/Stormshield-SN300-opnsense)**
  — Stormshield SN300 hardware running OPNsense.  Check repo for
  pinned-version `config.xml`.

### 21.x retrospective

#### GitHub repositories
* **`opnsense/core` at `21.1` + `21.7` tags** — same fixture
  trio; lowest priority since 21.x is years past EoS but useful
  as a schema baseline pre-22.1's VLAN changes.
* **[`dmauser/opnazure`](https://github.com/dmauser/opnazure/blob/master/scripts/config.xml)**
  — Azure deployment scripts; the committed `config.xml`
  declares `<version>11.2</version>` (an internal config-schema
  version, not the OPNsense product version — corresponds roughly
  to 19.x-20.x era).  License: not confirmed visible.  Provides
  Azure NAT + WAN + LAN interface forms.
* **[`mcree/vagrant-opnsense`](https://github.com/mcree/vagrant-opnsense/blob/master/config.xml)**
  — Packer/Vagrant build artifact; 851 lines, no version
  declared but config-schema version implies 20.x era.  License:
  not confirmed visible.  Empty `<vip/>` + empty `<openvpn-server/>`
  scaffolding.

### 20.x / 19.x retrospective

#### GitHub repositories
* **`opnsense/core` at `19.1` / `19.7` / `20.1` / `20.7` tags**
  — same fixture trio.  Pre-23.x schema; lower priority but
  cheap to pull since it's identical methodology to the existing 4.
* **`opnsense/changelog`**
  ([https://github.com/opnsense/changelog](https://github.com/opnsense/changelog))
  has per-version changelog docs that surface schema-change
  notes useful for pull-target prioritisation.

### 18.x / 17.x / 16.x / 15.x retrospective

#### GitHub repositories
* **`opnsense/core` at 15.1 / 15.7 / 16.1 / 16.7 / 17.1 / 17.7 /
  18.1 / 18.7 tags** — same fixture trio at each tag.  Bulk-pull
  via a small loop over the release tags would land all 16 in
  one go.  Value: comprehensive retrospective baseline; useful
  if the codec ever ships a 2015-era schema-migration path.
* The pre-15.x m0n0wall heritage is **out-of-scope** per the
  catalogue (m0n0wall ≠ OPNsense; different codec entirely).

#### Other
* **Internet Archive Wayback Machine** — snapshots of
  `docs.opnsense.org` at 2015-2018 timestamps preserve the
  examples that existed before the 19.x doc reorganisation.

### High-availability (CARP) deployments — special focus per WANTED.md

This is the **single highest-value pull** for the OPNsense codec.
The v0.1.1 codec wired CARP grammar (per
`netcanon/migration/codecs/opnsense/parse.py`) but the corpus has
zero CARP fixtures — meaning the entire CARP code path has only
unit-test coverage, never been validated against a real-capture
HA pair.  Per [`tests/fixtures/real/WANTED.md`](../../tests/fixtures/real/WANTED.md)
the CARP HA gap is explicitly called out:

> OPNsense (CARP) | `<virtualip><vip><mode>carp</mode>...` | not in corpus | shipped (CARP variant via `mode="carp"` discriminator; fixture still wanted)

#### Pull-target candidates (in priority order)

1. **`opnsense/docs/source/manual/how-tos/resources/Carp_example_master.xml`**
   ([https://github.com/opnsense/docs/blob/master/source/manual/how-tos/resources/Carp_example_master.xml](https://github.com/opnsense/docs/blob/master/source/manual/how-tos/resources/Carp_example_master.xml))
   **+ `Carp_example_backup.xml`** ([https://github.com/opnsense/docs/blob/master/source/manual/how-tos/resources/Carp_example_backup.xml](https://github.com/opnsense/docs/blob/master/source/manual/how-tos/resources/Carp_example_backup.xml))
   — the **official OPNsense docs CARP HA pair example**, 704
   lines each, declaring `<version>11.2</version>` (internal
   config-schema version, not product version), license
   BSD-2-Clause.  Exercises the complete `<virtualip>` block with
   2 `<vip>` entries (WAN VHID 1 / LAN VHID 3) in `<mode>carp</mode>`,
   PFSYNC peer (`em2` 10.0.0.1/24), full HA sync settings
   (xmlrpc rules/NAT/DHCP/VIP sync).  **Highest priority because:**
   (a) it's an HA *pair* (master + backup) so cross-validates the
   codec against both sides of a CARP relationship; (b) the
   `<virtualip>` grammar is direct upstream-vendor example, not
   operator-paste; (c) BSD-2-Clause licensing means zero
   sanitisation effort; (d) closes the codec's biggest
   real-capture gap with one PR.
2. **`forum.opnsense.org` CARP-pair posts** — search
   `"<mode>carp</mode>" OR "virtualip" site:forum.opnsense.org`
   for operator-pasted HA configs in troubleshooting threads.
   Heavy sanitisation per HPE Community precedent; the docs
   sample above should be pulled FIRST to anchor the grammar,
   then operator-deployed captures pulled to validate against
   real-world variation.
3. **[`kyntrp/Intrusion-Detection-and-High-Availability-Firewall-Lab-OPNsense-`](https://github.com/kyntrp/Intrusion-Detection-and-High-Availability-Firewall-Lab-OPNsense-)**
   — tutorial repo with HA CARP setup walkthrough, but inspection
   confirms it's instructions-only (README), no committed
   `config.xml`.  Skip.
4. **[`nett-media/opnsense-config-generator`](https://github.com/nett-media/opnsense-config-generator)**
   — has `init/init_CARP.xml` template for generating CARP entries.
   License not visible; if confirmed BSD/MIT/Apache the
   generated full `config.xml` could synthesise a CARP fixture.
   Lower priority because synthesised ≠ real-capture.
5. **r/opnsense Reddit threads** with CARP HA paste — implicit
   operator-share license; useful as cross-checks against the
   docs sample but not primary import.

#### Codec grammar the CARP fixtures will exercise

Per `netcanon/migration/codecs/opnsense/parse.py:689-803`:

* `<virtualip><vip>` → list of CARP / VRRP groups
* `<mode>carp</mode>` discriminator (filters out `<mode>ipalias</mode>`
  and `<mode>proxyarp</mode>` non-FHRP forms)
* `<vhid>` → VRRP group ID (1-255)
* `<subnet>` + `<subnet_bits>` → virtual address + prefix
* `<advfreq>` + `<advbase>` → advertisement timing
* `<password>` → `authentication = "carp-key:X"` (CARP-specific;
  not plain/md5 like classic VRRP)
* `<interface>` → parent interface zone-name binding
* HA sync settings in `<hasync>` (xmlrpc peer + per-section
  sync booleans for rules/NAT/DHCP/VIP)

A CARP-pair fixture exercises all these surfaces; the docs sample
covers every field listed.

---

## Recommended pull priority order

1. **`opnsense/docs` `Carp_example_master.xml` +
   `Carp_example_backup.xml`** — closes the WANTED.md CARP HA gap
   (the codec's biggest real-capture absence) with one BSD-2-Clause
   PR.  Master + backup pair cross-validates both sides of a CARP
   relationship.  Zero sanitisation effort.  **Single highest-value
   pull for this codec.**
2. **`opnsense/core` at `24.1` / `24.7` release tags** —
   `config.xml.sample` + service tests + ACL tests, same trio
   the existing 4 fixtures came from.  Closes the 24.x WANTED.md
   gap.  BSD-2-Clause; zero sanitisation.
3. **`opnsense/core` at `23.1` / `23.7` tags** — same trio.
   Closes 23.x gap.  Captures the pre-encrypted-backup-support
   schema baseline.
4. **`opnsense/core` at `22.1` / `22.7` tags** — same trio.
   Closes 22.x gap.  22.1 specifically validates the codec
   against the pre-23.x VLAN-creation grammar that 22.1.4_1 had
   known issues with (issue #5650).
5. **`forum.opnsense.org` operator-paste CARP HA configs** — once
   the docs sample (priority 1) anchors the grammar, real-world
   operator pastes validate the codec against deployment variation.
   Heavy sanitisation per HPE Community precedent; attribution
   required.
6. **`opnsense/core` at older 15.x-21.x release tags (bulk)** —
   single-loop pull lands 16 retrospective fixtures.  Lower
   per-fixture value but cheap; useful schema-baseline reference.
7. **Operator homelab repos (Vinetos / marcdely1 / rogerp02)** —
   require per-repo confirmation that actual `config.xml` artefacts
   are committed (vs only Ansible variables / Terraform vars).
   License varies; Apache-2.0 (Vinetos) confirmed.
8. **`mcree/vagrant-opnsense` + `dmauser/opnazure`** — committed
   `config.xml` artifacts but licensing not visibly confirmed;
   would require license clarification before import.

---

## Out-of-scope

* **m0n0wall heritage** (pre-15.1) — OPNsense forked m0n0wall in
  2015 but pre-15.1 config schemas are a different codec entirely;
  not in scope for the `opnsense` codec catalogue.
* **pfSense `config.xml`** — same XML *shape* on the surface
  (both fork m0n0wall) but pfSense schema has diverged enough
  that codec-sharing is a [Tier-D planned codec](14-pfsense.md),
  not part of this catalogue.  pfSense fixtures go in the
  pfSense codec catalogue (file `14-pfsense.md`).
* **Vendor-confidential deployments** — closed-source operator
  configs without explicit consent + permissive licensing.  Per
  `BUG_REPORTING.md`: provenance must be permissive.
* **Business Edition (BE) release lines** — OPNsense BE
  (25.10, 25.4, 24.10, etc.) is the same codebase as CE with a
  delayed release cadence; CE fixtures cover the schema, so BE
  is treated as duplicate-coverage and out-of-scope for the
  fixture pull list.  (Ansible roles like Rosa-Luxemburgstiftung
  do target BE explicitly, but the resulting `config.xml` is
  schema-identical to CE.)
* **Synthesised configs from generators**
  (`nett-media/opnsense-config-generator`, `malwarology/opnsense-confgen`)
  — useful for synthesising rich CARP/VLAN fixtures but
  synthesised ≠ real-capture per the corpus design intent.
  Acceptable as fallback only if no real CARP HA pair surfaces.

---

## See also

* [`00-source-analysis.md`](00-source-analysis.md) — meta source-type taxonomy
* [`tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md) — existing OPNsense corpus provenance
* [`tests/fixtures/real/WANTED.md`](../../tests/fixtures/real/WANTED.md) — operator-facing gap list (OPNsense row + CARP HA row)
* [`14-pfsense.md`](14-pfsense.md) — Tier-D pfSense codec catalogue (likely shares codec layer with OPNsense)
* [`netcanon/migration/codecs/opnsense/parse.py`](../../netcanon/migration/codecs/opnsense/parse.py) — CARP `<virtualip>` parse path (Wave B v0.1.1)
* [`netcanon/migration/codecs/opnsense/render.py`](../../netcanon/migration/codecs/opnsense/render.py) — CARP render path
* [`docs.opnsense.org/manual/how-tos/carp.html`](https://docs.opnsense.org/manual/how-tos/carp.html) — CARP HA tutorial w/ downloadable `Carp_example_master.xml` + `Carp_example_backup.xml`
* [`endoflife.date/opnsense`](https://endoflife.date/opnsense) — authoritative release-date + EoL table
* [`docs.opnsense.org/releases.html`](https://docs.opnsense.org/releases.html) — OPNsense official release index w/ codenames

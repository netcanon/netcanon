# Source-type analysis — where in the wild network configs live

This is the meta-document referenced by every per-OS catalogue in
this folder.  Rather than each per-OS file repeat the source-type
taxonomy + license-class guidance, the per-OS files cite this one.

Surface-level overview of the fifteen source classes I'd consider
when looking for real-world network configurations beyond GitHub
repositories.  Each class has a different license-confidence
profile + sanitisation expectation + signal-to-noise ratio.

---

## Tier 1 — high-confidence permissive sources

These have explicit, well-known licenses + community norms around
republication.

### 1.1  Open-source code repositories (already in heavy use)

* **GitHub** — searchable by license tag (`Apache-2.0`, `MIT`,
  `BSD-3-Clause`, `CC0`), language, topic.  All existing fixtures
  in [`tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md)
  come from here (batfish/lab-validation, ksator/lab_management,
  buraglio/Juniper-SR-PCE, etc.).
* **GitLab.com / self-hosted GitLab instances** — often hosts
  university lab repos under the same permissive licenses.
* **Bitbucket** — niche; some legacy operator labs.
* **Codeberg / sourcehut / sr.ht** — small but quality-focused
  open-source hubs.
* **GitHub Gists** — single-file config snippets searchable via
  `https://gist.github.com/search?q=...`.  License inherits from
  the owning user's account default (rarely explicit).

### 1.2  Vendor documentation examples

Almost all major-vendor docs publish under permissive licenses
(usually CC-BY or vendor-defined "example use" terms).

* **Cisco** — Configuration Guides per platform; example configs
  embedded in Cisco Press books (some examples free; others
  paywalled).  CCO documentation typically OK to excerpt with
  attribution.
* **Juniper TechLibrary** — Day One Books (CC-BY), Junos Genius
  workbooks, "Configuration Examples" portal.
* **Arista Networks** — TOI (Theory of Operation) docs, EOS Central
  blog, Configlets repository.
* **HPE Aruba** — Aruba Networks docs (mostly CC-BY for examples).
* **Fortinet** — Fortinet Cookbook (community-contributed examples
  under FNDN program), some are Apache-licensed.
* **MikroTik wiki** — `wiki.mikrotik.com` — extensive config samples,
  no explicit license but published as reference material.
* **OPNsense / pfSense** — documentation under Apache 2 (OPNsense)
  or partially BSD (pfSense); example configs in admin guides.
* **VyOS** — official docs at `docs.vyos.io` (CC-BY-NC-SA).

### 1.3  Permissively-licensed network lab platforms

* **CiscoDevNet/cml-community** (GitHub, BSD-3) — already used for
  2 IOS-XE fixtures.  Has labs for IOS, IOS-XE, NX-OS, IOS-XR.
* **containerlab** — `srl-labs/containerlab` on GitHub (BSD-3);
  the `clab-topo` GitHub topic has community labs with full
  configs per node.
* **Juniper vLabs** — public sandboxes (login-gated but configs
  exportable).
* **Arista cEOS-lab / vEOS** — Docker-runnable; some pre-built lab
  topologies under the `arista-netdevops-community` GitHub org.
* **Cisco Modeling Labs Sandbox** (DevNet) — login-gated but
  configs are operator-shareable.
* **GNS3 community labs** — `gns3.com/marketplace/all` (mixed
  licenses; check per-lab).
* **EVE-NG community labs** — `eve-ng.net/index.php/community/`
  (mixed licenses).

### 1.4  Academic course material

Networking courses at universities often publish lab configs as
PDFs or text files.

* **University networking course pages** — searchable via
  `site:edu inurl:lab "running-config"`.
* **Cisco Networking Academy partner schools** — some publish
  Packet Tracer files (`.pkt`) that contain embedded configs.
* **Stanford / Berkeley / CMU / MIT** networking courses
  (CS-144, CS-168, 15-441, 6.829 etc.) — lab handouts often
  contain Cisco / Junos config samples.

---

## Tier 2 — community-share precedent (forum / Q&A)

The "forum-share" license precedent in
[`NOTICE.md`](../../tests/fixtures/real/NOTICE.md) — operators
posting their configs publicly for troubleshooting help.  Cited
fixtures: HPE Community 7026923 / 7051607 / 7084768 (Aruba
AOS-S) + 6935784 (5406Rzl2).

### 2.1  Vendor community forums

* **Cisco Community** (`community.cisco.com`) — formerly Cisco
  Learning Network + Cisco Support Community.  Heavily-trafficked
  for IOS / IOS-XE / NX-OS / IOS-XR / Wireless.
* **HPE Aruba Networking Community** (`community.hpe.com` →
  Aruba Networking section) — primary source for AOS-S
  troubleshooting.
* **Juniper Community** (`community.juniper.net`) — JTAC-style
  troubleshooting threads.
* **Fortinet Community** (`community.fortinet.com`) — FortiOS
  config questions.
* **MikroTik Forum** (`forum.mikrotik.com`) — RouterOS-specific.
* **OPNsense Forum** (`forum.opnsense.org`) — heavily-trafficked.
* **pfSense / Netgate Forum** (`forum.netgate.com`) — primary
  pfSense forum.
* **VyOS Forum** (`forum.vyos.io`) — small but high-signal.
* **Arista Community** (`community.arista.com`) — smaller; most
  Arista community discussion happens on GitHub or Slack.

### 2.2  Reddit subreddits

Subreddits where operators paste configs (often partially
redacted) for troubleshooting.  Implicit operator-share license;
sanitisation usually already done by the poster.

* `r/networking` — broadest; multi-vendor.
* `r/cisco` — specific to Cisco platforms (IOS, IOS-XE, NX-OS).
* `r/juniper` — small but high-signal.
* `r/arista` — small.
* `r/Aruba` + `r/HPE` — Aruba / HPE AOS-S.
* `r/fortinet` — FortiOS troubleshooting.
* `r/mikrotik` — RouterOS.
* `r/opnsense` + `r/pfsense` — firewall distros.
* `r/vyos` — small.
* `r/homelab` — multi-vendor; operator-deployed configurations.
* `r/sysadmin` — multi-vendor; usually higher-level.

### 2.3  Stack Exchange family

* **Network Engineering Stack Exchange**
  (`networkengineering.stackexchange.com`) — Q&A format with
  config snippets in answers.  CC-BY-SA-licensed (compatible
  with our permissive fixture pool but attribution required).
* **Server Fault** (`serverfault.com`) — broader sysadmin focus
  but network configs surface in answers.
* **Stack Overflow** — less network-config focused but occasional.
* **Unix Stack Exchange** — VyOS / pfSense / OPNsense crossover.

### 2.4  Operator blogs (CC-attributed or implicit)

* `packetlife.net` — Jeremy Stretch's blog, lots of config samples.
* `ipspace.net` — Ivan Pepelnjak's network-design content.
* `networkdirection.net` — multi-vendor tutorials.
* `thenetworkdna.com` — DC-fabric focused.
* `chrisjwest.com` / `routereflector.com` / `kbatcho.com` —
  operator-run blogs.
* `daniels.netdevops.me` — Daniel Hertzberg's netdevops content.
* `itnetworking.cz` — Czech tech blog, heavy on Mikrotik /
  Junos examples.
* `juniperdays.com` — Junos-focused.
* `roanguigon.com` — Juniper SP-routing.

License assessment: blog posts inherently shareable for educational
quote / fair use; the configs themselves are usually fictional or
operator-authored examples.  Use as inspiration, not direct
import.

---

## Tier 3 — narrow-utility sources

Sources where configs exist but quality/license is mixed.  Useful
for discovery, less useful for direct import.

### 3.1  Paste services

* **Pastebin** (`pastebin.com`) — heavily abused; search restricted
  but `site:pastebin.com running-config` Google query works.
  Anonymous posts: implicit public-domain.
* **`hastebin.com`**, **`paste.ee`**, **`controlc.com`**,
  **`paste.opensuse.org`** — smaller alternatives.
* **GitHub Gists** (covered above) — better discoverability via
  API.

### 3.2  Cert prep / training material

* **CCNA / CCNP / CCIE study guide configs** — Cisco Press, INE,
  CBT Nuggets, IPexpert workbooks.  Mostly paywalled; some free
  samples on vendor's site.  Use carefully — copyright is real.
* **JNCIA / JNCIS / JNCIE study guides** — Juniper-published or
  Juniper Networks Education Services material.

### 3.3  YouTube + recorded training

* **David Bombal**, **NetworkChuck**, **Kevin Wallace**,
  **CCNAdaily**, **AllThingsCisco**, **Boson Software** — many
  CCNA/CCNP prep channels with config text in video descriptions
  or pinned comments.  Copyright on the video itself; the
  embedded config is usually operator-authored example.
* **Vendor official YouTube** — Cisco DevNet, Juniper Networks,
  Arista TechHub — has lab walkthroughs with full configs.

### 3.4  Archived defunct blogs

* **Internet Archive Wayback Machine** (`web.archive.org`) —
  preserves 2015-era blog posts that have since expired.
  Particularly useful for IOS 12.x / 15.x captures pre-dating
  the current GA train.

### 3.5  Lab archive sites

* **`labgopher.com`** — vendor-platform-comparison; sometimes
  has config samples.
* **`networklessons.com`** — Rene Molenaar's content; mostly
  paywalled but free articles exist.
* **`router-switch.com` blog** — hardware-focused, but lab
  configs occasionally surface.

### 3.6  GitHub topic-based discovery

* **GitHub Topics** — `clab-topo` for containerlab repos;
  `cisco-ios`, `junos`, `eos-network-automation`, `aruba-aos-s`,
  `fortinet` etc. as topic tags.
* **`awesome-` lists** — `awesome-networking`,
  `awesome-pentest-networking`, `awesome-network-stuff` —
  meta-curated.

---

## Tier 4 — operator-deployed environments (off-limits without consent)

For completeness — these exist but the project doesn't accept
them without explicit consent from the operator.

* **Production-network captures** posted to public threads —
  may still be in-use; sanitisation incomplete.
* **Customer-deployed configs** seen during consulting work —
  contractually private.
* **Vendor demo accounts / sandbox accounts** behind login walls
  — may have terms-of-service preventing republication.

Per [`BUG_REPORTING.md`](../../BUG_REPORTING.md):
"Closed-source vendor configs you don't have rights to share.
Provenance must be permissive (operator's own network with
appropriate authorisation; public-research repos under MIT /
Apache / BSD; vendor docs)."

---

## Per-source-class quality + sanitisation expectation

For each per-OS catalogue, classify discovered configs:

| Class | Sanitisation needed | License confidence | Effort to verify |
|---|---|---|---|
| GitHub repo with explicit license | None (operator already shared) | High | 1 min (check LICENSE) |
| GitHub Gist (no explicit license) | Light (re-verify no PII) | Medium | 5 min (skim file) |
| Vendor doc example | None | High | 5 min (verify CC-BY / fair-use) |
| Lab platform fixture (containerlab etc.) | None | High | 5 min |
| Forum thread (operator-paste) | Heavy (re-verify hostnames, IPs, hashes) | Medium-high (forum-share precedent) | 15-30 min |
| Reddit thread | Heavy | Medium | 15-30 min |
| Stack Exchange answer | Heavy | High (CC-BY-SA-licensed) | 15 min + attribution work |
| Operator blog | Heavy (treat as example, not import) | Low (fair-use for excerpt) | n/a (rewrite as synthetic) |
| Pastebin | Heavy | Low | 30+ min |
| Cert prep workbook | Don't import | Low (copyright) | n/a |

**Rule of thumb**: anything from Tier 1 + Tier 2.1 + Tier 2.3 is
generally importable with sanitisation.  Tier 2.2 + 2.4 + 3.x is
discovery-only — use as inspiration, draft synthetic fixtures
rather than direct import.

---

## Discovery search patterns (per source class)

For agents crawling each source class, useful search-engine
queries:

* GitHub: `language:Text "show running-config"`,
  `language:Text "set system host-name"`,
  `path:**/configs/ extension:txt OR extension:cfg`.
* Google generic: `"show running-config" site:cisco.com inurl:document`.
* Forum-specific: `"show running-config" site:community.cisco.com`.
* Reddit: `"running-config" site:reddit.com/r/cisco`.
* Pastebin: Google `site:pastebin.com "Building configuration..."`.
* Internet Archive: `web.archive.org/web/2015*/inurl:lab "interface GigabitEthernet"`.

Each per-OS catalogue uses these patterns adapted to the
target vendor's command shape (e.g. for Junos:
`"set system host-name"` or `"display set"`).

---

## See also

* [`README.md`](README.md) — folder index + scope
* [`tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md)
  — existing fixtures' provenance (the "forum-share" precedent
  + the Apache/MIT/BSD-3 examples)
* [`tests/fixtures/real/WANTED.md`](../../tests/fixtures/real/WANTED.md)
  — current operator-facing fixture gap list
* [`BUG_REPORTING.md`](../../BUG_REPORTING.md) — sanitisation
  + fixture submission workflow

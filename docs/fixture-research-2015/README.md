# Real-capture fixture research — 2015 onward

This folder catalogues **where in the wild** real-world network
configurations can be sourced for each of the 14 OSs in
Netcanon's current or planned codec matrix, covering every major
firmware/release version from 2015 through today.

> **Purpose.**  Inform deliberate fixture expansion.  The current
> corpus (45 fixtures across 7 OSs as of `v0.1.1` —
> see [`tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md))
> covers a small subset of OS versions and even smaller subset of
> grammar surfaces.  When an operator (or a future maintainer)
> wants to add fixtures for a specific version-bridge gap, they
> should be able to open this folder, find their OS, find the
> version, and have a vetted list of public sources to pull from.

> **Read-only research.**  Nothing in this folder modifies
> production code or commits fixtures.  Acting on a catalogued
> pull-target requires a separate fixture-submission flow per
> [`BUG_REPORTING.md`](../../BUG_REPORTING.md) (sanitisation +
> license verification + NOTICE.md + RESULTS.md updates).

---

## Coverage matrix

The fourteen OSs split across two tiers:

| Tier | Status | OSs |
|---|---|---|
| **Shipped codecs** (7) | wired in `v0.1.1` | Cisco IOS-XE, Juniper Junos (EX/QFX/MX), Arista EOS, Aruba AOS-S, Fortinet FortiOS, MikroTik RouterOS, OPNsense |
| **Tier-D planned codecs** (7) | design-complete or vendor-noted in [`WANTED.md`](../../tests/fixtures/real/WANTED.md) | Cisco NX-OS (v0.3.0), Cisco IOS-XR (v0.3.0+), Cisco IOS classic, Aruba AOS-CX, Juniper SRX, VyOS, pfSense |

Version window: **2015 January through today** (10-year window).

---

## Folder contents

* [`00-source-analysis.md`](00-source-analysis.md) — meta-analysis
  of source TYPES beyond GitHub (forums, vendor docs, lab platforms,
  pastebin, YouTube transcripts, Internet Archive, etc.).  Each
  per-OS file in this folder references the source taxonomy here.
* [`15-overlay-priority-synthesis.md`](15-overlay-priority-synthesis.md)
  — **Synthesis pass**.  Translates the 14 catalogues into a
  concrete overlay-authoring backlog at
  `definitions/<vendor>/<os>/<version>.yaml`.  Maps each OS's
  pull-priority recommendations to per-version YAML targets,
  recommends a 4-wave sequence (Wave A → ~19 overlays, Wave B →
  ~39, Wave C → ~67, Wave D → ~95+ post-Tier-D), and documents
  the implementation approach per overlay.  **Start here** if
  you're trying to understand what overlays to author next.
* Per-OS catalogues (one file each):

| # | OS | Codec status |
|---|---|---|
| 1 | [`01-cisco_iosxe.md`](01-cisco_iosxe.md) | Shipped (`cisco_iosxe_cli` + `cisco_iosxe` NETCONF stub) |
| 2 | [`02-juniper_junos.md`](02-juniper_junos.md) | Shipped (`juniper_junos`) |
| 3 | [`03-arista_eos.md`](03-arista_eos.md) | Shipped (`arista_eos`) |
| 4 | [`04-aruba_aoss.md`](04-aruba_aoss.md) | Shipped (`aruba_aoss`) |
| 5 | [`05-fortigate.md`](05-fortigate.md) | Shipped (`fortigate_cli`) |
| 6 | [`06-mikrotik_routeros.md`](06-mikrotik_routeros.md) | Shipped (`mikrotik_routeros`) |
| 7 | [`07-opnsense.md`](07-opnsense.md) | Shipped (`opnsense`) |
| 8 | [`08-cisco_nxos.md`](08-cisco_nxos.md) | Tier-D — design at `docs/v0.2.0-planning/03-nxos-codec/` |
| 9 | [`09-cisco_iosxr.md`](09-cisco_iosxr.md) | Tier-D — design at `docs/v0.2.0-planning/04-iosxr-codec/` |
| 10 | [`10-cisco_ios_classic.md`](10-cisco_ios_classic.md) | Tier-D |
| 11 | [`11-aruba_aoscx.md`](11-aruba_aoscx.md) | Tier-D |
| 12 | [`12-juniper_srx.md`](12-juniper_srx.md) | Tier-D — same OS as Junos but distinct codec scope (firewall + security-policy grammar) |
| 13 | [`13-vyos.md`](13-vyos.md) | Tier-D |
| 14 | [`14-pfsense.md`](14-pfsense.md) | Tier-D — likely shares codec layer with OPNsense |

---

## How each catalogue is structured

Every per-OS file follows the same shape so a reader scanning for
"Junos 19.x sources" or "FortiOS 7.4 sources" knows exactly where
to look:

```
# <OS Name> — fixture catalogue (2015+)

## Version timeline
| Version | Release date | EoS | In corpus | Priority |

## Pull-target inventory
### <Version family>
#### GitHub repositories
#### Forum / community posts
#### Vendor docs / lab guides
#### Other (pastebin / YouTube / blogs / Internet Archive)

## Recommended pull priority order
## Out-of-scope (deliberately excluded)
## See also
```

Per-target metadata captured for each entry:

* URL (or stable reference)
* Apparent license / provenance class
* Approximate config length (lines) if known
* Grammar surface(s) the capture would exercise
* Sanitisation needed (yes / minor / heavy)
* OS version + platform
* Quality signal (forum-share confidence, vendor-doc rigor, etc.)

---

## What this folder is NOT

* **Not a commit pipeline.**  Catalogued URLs are pull-candidates,
  not fixtures.  Importing each requires the
  [`BUG_REPORTING.md`](../../BUG_REPORTING.md) sanitisation flow
  and `NOTICE.md` provenance entry.
* **Not exhaustive.**  Web search returns more than is useful; each
  per-OS agent did its best to prioritise high-leverage targets
  but the catalogues should grow over time as contributors add
  new sources.
* **Not license advice.**  License assessments are best-effort.
  Confirming an apparent permissive license + the right-to-share
  is the responsibility of whoever actually pulls the fixture.

---

## See also

* [`tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md)
  — provenance ledger of fixtures currently in the corpus
* [`tests/fixtures/real/WANTED.md`](../../tests/fixtures/real/WANTED.md)
  — operator-facing fixture-submission gap list
* [`BUG_REPORTING.md`](../../BUG_REPORTING.md) — sanitisation +
  fixture-submission workflow
* [`docs/v0.2.0-planning/03-nxos-codec/06-fixture-targets.md`](../v0.2.0-planning/03-nxos-codec/06-fixture-targets.md)
  — concrete batfish NX-OS pull list (intersect with this folder's
  Cisco NX-OS catalogue)
* [`docs/v0.2.0-planning/04-iosxr-codec/06-fixture-targets.md`](../v0.2.0-planning/04-iosxr-codec/06-fixture-targets.md)
  — concrete batfish IOS-XR pull list (intersect with this folder's
  Cisco IOS-XR catalogue)

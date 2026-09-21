# Dell SmartFabric OS10 — pre-codec research dossier

Gathered 2026-09-21.  This directory is the **knowledge corpus** for a
prospective `dell_os10` codec: grammar, real-config inventory, licence
provenance, and the wiring/risk analysis.  No code has been written.

> **Scope decision (user, 2026-09-21): OS10 only.**  Dell ships three
> unrelated network operating systems (below).  OS10 is the real-world
> use case; OS9/FTOS material gathered incidentally is kept in
> [`40-os9-appendix.md`](40-os9-appendix.md) but is **not** being pursued.

## The three Dell NOSes are not dialects of each other

| NOS | Lineage | VLAN model | Port naming | Status here |
|---|---|---|---|---|
| **SmartFabric OS10** | Debian-based, ONIE | **port-centric** — `switchport access/trunk` on the interface | `ethernet 1/1/1` (3-segment, lowercase) | **TARGET** |
| OS9 / FTOS / DNOS 9 | Force10, NetBSD | **VLAN-centric** — `interface Vlan N` + `tagged`/`untagged` member lists | `TenGigabitEthernet 0/1` | appendix only |
| OS6 / PowerConnect | VxWorks | n/a | n/a | out of scope |

OS10's VLAN model matches Cisco/Arista; OS9's matches Aruba AOS-S.  They
would be **two separate codecs**, not one with a version gate.  (OS10 does
carry a `feature config-os9-style` compatibility toggle — noted in
[`30-codec-plan.md`](30-codec-plan.md) as a future hazard, not a bridge.)

## Documents

| File | Contents |
|---|---|
| [`10-grammar.md`](10-grammar.md) | OS10 CLI grammar mapped to the canonical surface, with manual citations |
| [`20-corpus.md`](20-corpus.md) | Real-config inventory + **licence ledger** + sanitisation status |
| [`30-codec-plan.md`](30-codec-plan.md) | Wiring checklist, the measured detection defect, risks |
| [`40-os9-appendix.md`](40-os9-appendix.md) | OS9/FTOS notes, parked |

## Raw material — `local/dell-os10/` (gitignored)

The full corpus (~140 MB) lives at **`local/dell-os10/`**.  `local/` is
gitignored (`.gitignore:116`), so it is durable on disk but never reaches
the public repo — the correct place for copyrighted vendor manuals and
unsanitised configs.

```
local/dell-os10/
    manuals/   8 Dell PDFs
    text/      8 pdftotext -layout extracts (~450k lines)
    configs/   19 real configs (see 20-corpus.md for the licence ledger)
    guides/    7 MIT-licensed OS10 chapter guides
    ansible/   16 GPL role docs — reference index only, see 20-corpus.md
```

Deliberately **not** added to the repo:

- **7 Dell PDF manuals**, ~450k lines of extracted text (`pdftotext -layout`).
  Dell documentation is copyrighted; this repo's convention
  ([`docs/vendor-references/README.md`](../../vendor-references/README.md))
  is to cache *curated summaries with citations*, not vendor manuals.
- **17 real configs** — see the licence ledger in [`20-corpus.md`](20-corpus.md).
  Not committed because fixture ingestion requires the sanitisation
  workflow in [`BUG_REPORTING.md`](../../../BUG_REPORTING.md) first; at
  least one carries a real `$6$` password hash.

## Manuals consulted

| Document | Release | Lines | Role |
|---|---|---|---|
| SmartFabric OS10 User Guide | 10.5.2 | 107,223 | primary grammar source |
| SmartFabric OS10 User Guide | 10.5.1 | 94,202 | cross-check |
| SmartFabric OS10 User Guide | 10.5.0 | 84,369 | cross-check |
| VXLAN and BGP EVPN Config Guide | 10.5.0 | 9,591 | overlay grammar |
| OS10 Product Lifecycle Policy | — | 115 | support windows |
| (OS9 Config Guide S4048-ON 9.14.2.0) | — | 63,736 | appendix |
| (OS9 CLI Reference S4048-ON 9.14.2.5) | — | 101,622 | appendix |

Dell's HTML manual pages return navigation-only to a fetcher and
`infohub.delltechnologies.com` returns 403; the PDFs at `dl.dell.com`
download fine with a normal user-agent.  **PDF URLs are not guessable** —
seven pattern guesses all 404'd; they must come from the manuals index at
`dell.com/support/product-details/…/smartfabric-os10-emp-partner/resources/manuals`.

## Version / lifecycle

⚠️ **`endoflife.date` does not track Dell OS10** (404 on
`/api/dell-smartfabric-os10.json`), so the repo's usual canonical timeline
source — used by every file in
[`docs/fixture-research-2015/`](../../fixture-research-2015/) — is
unavailable here.

From Dell's Product Lifecycle Policy:

- Release types: **Major**, **Minor** (twice a year, e.g. `10.5.4.x`),
  **Maintenance** (e.g. `10.5.5.4`).
- **36 months** standard support from a major release's RTW date.
- The policy is only effective **from release 10.5.3.0**.
- Per-version End-of-Standard-Support dates are published **per release
  note**, not in any consolidated table.

Consequence: a version-timeline table equivalent to the other vendors'
cannot be built from a single source.  Releases seen in the wild in this
corpus: **10.5.1.0** (JetPack captures) and **10.5.2.4** (manual examples).
Current trains at time of writing: 10.5.6, 10.6.0, 10.6.1.

## `show version` (device-definition probe anchor)

```
OS10# show version
Dell EMC Networking OS10 Enterprise
Copyright (c) 1999-2021 by Dell Inc. All Rights Reserved.
OS Version: 10.5.2.4
Build Version: 10.5.2.4.215
Build Time: 2021-04-11T21:35:41+0000
System Type: S5248F-ON
Architecture: x86_64
Up Time: 1 day 00:54:13
```

Probe anchors: `OS Version:\s*(\d+\.\d+\.\d+(?:\.\d+)?)` for version,
`System Type:\s*(\S+)` for model.

⚠️ The banner reads **`Dell EMC Networking OS10 Enterprise`** in the
10.5.x manuals.  Dell rebranded the product to *Dell SmartFabric OS10*
(dropping "EMC"), so a newer image may emit a different first line — an
anchor on the banner text alone risks the AOS-CX simulator trap
(a probe regex that cannot fire on the image you actually have; see
[`docs/reviews/2026-06-17-virtual-nos-viability/99-synthesis.md`](../../reviews/2026-06-17-virtual-nos-viability/99-synthesis.md)).
**Anchor on `OS Version:`, not on the product banner**, and verify against
a real image before graduating any device definition.

## Virtual image availability

Dell publishes **free OS10 virtualisation bundles** (GNS3, and qcow2 for
EVE-NG/PNETLAB) from the Dell Support site under Networking → Operating
Systems → SmartFabric OS10 Software.  These run the same software as
hardware minus the hardware abstraction layer.

This matters: it means an OS10 device definition could be **live-validated**
rather than shipped provisional — unlike `CiscoNXOS` / `CiscoIOSXR` /
`ArubaCX`, which remain `NOT YET VALIDATED`.  Gated on the Proxmox estate
returning (offline since 2026-07-27, see [[project_dogfood_lab]]).

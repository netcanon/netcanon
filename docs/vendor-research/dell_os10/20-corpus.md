# Dell OS10 — config corpus inventory + licence ledger

Gathered 2026-09-21.  Files live at **`local/dell-os10/configs/`** —
gitignored (`.gitignore:116`), so durable on disk but not in the public
repo.  Ingestion as *fixtures* is a separate step requiring the
sanitisation workflow in
[`BUG_REPORTING.md`](../../../BUG_REPORTING.md) first.

[`tests/fixtures/real/NOTICE.md`](../../../tests/fixtures/real/NOTICE.md)
requires a **permissive licence (Apache / MIT / BSD / CC0) with documented
provenance**.  Licence was checked **before** download in every case.

---

## ✅ Ingestible — permissive licence

| Source | Licence | Files | OS10 release | Shape |
|---|---|---|---|---|
| `dsp-jetpack/JetPack` | **Apache-2.0** | 6 | 10.5.1.0 | real `show running-configuration` dumps |
| `DellGEOS/AzureLocalHOLs` | **MIT** | 4 | — | hand-authored config scripts |
| `AzureLocal/azurelocal-toolkit` | **MIT** | 2 (+7 guides) | — | authored scripts w/ placeholders |
| `Azure/AzureLocal-Supportability` | **MIT** | 2 | — | cleaned sample configs |

`dsp-jetpack/JetPack` is **Dell's own** OpenStack reference stack;
`DellGEOS` is **Dell's own** GEOS org.  Both are first-party.

### Highest-value items

- `jetpack_S5232F-1.txt` / `-2` and the `4-NICS` variants — genuine device
  dumps carrying `! Version 10.5.1.0` + `! Last configuration change at`.
  These are the only true round-trip fixtures in the set.
- `dellgeos_S5212F-TOR1-Advanced.cfg` — small (2.8 KB), complete, and
  exercises interfaces + VLANs + port-channel + VLT + **VRRP** in one file.
- `azurelocal-toolkit` ships **~500 KB of MIT-licensed OS10 chapter
  guides** (`os10-ch05-cli-basics.md` 117 KB, `ch17-security` 198 KB,
  `ch19-acl` 196 KB) — prose, not configs, but freely quotable unlike
  Dell's own manuals.

### ⚠️ Sanitisation required before ingestion

`jetpack_S5232F-*` and `jetpack_S3048*` contain **real `$6$` SHA-512
password hashes** on `username admin …` and `system-user linuxadmin …`
lines.  Public and permissively licensed, but the corpus convention is to
sanitise secrets regardless.

---

## ⛔ NOT ingestible — no licence

| Source | Files | Note |
|---|---|---|
| `dell-tsb/dell-mec` | 6 (leaf/spine/mgmt) | **no licence** — Dell TSB org |
| `dell-tsb/dell-dme` | 6 (leaf/spine/mgmt) | **no licence** |
| `install-safe-press/gb10-playbooks` | 1 (S4112F-ON) | **no licence** |
| `grantcurell/projects` | several | **no licence** |
| `piwi3910/openfroyo`, `dav1x/how-to-switch` | — | **no licence** |

No licence means all rights reserved — these are **knowledge-only**.  The
`dell-tsb` sets are the best-structured leaf/spine OS10 configs found and
would be worth an explicit licensing request to Dell TSB.

## ⛔ NOT ingestible — copyleft

| Source | Licence | Note |
|---|---|---|
| `ansible-collections/dellemc.os10` | **GPL-3.0** | see below |
| `berkut-ad/dell-parser` | GPL-3.0 | a Dell config parser |

### The GPL boundary — a deliberate decision

`ansible-collections/dellemc.os10` contains
`roles/*/templates/os10_*.j2` — 28 Jinja templates totalling ~190 KB that
constitute, in effect, **an OS10 renderer** (`os10_vxlan.j2` 15.8 KB,
`os10_snmp.j2` 17.4 KB, `os10_bgp.j2` 47.8 KB).  It also has a real
`show_running-config` test fixture.

Netcanon is Apache-2.0.  Deriving our renderer from GPL-3.0 templates is a
licence-contamination risk.  **Decision: the `.j2` templates were not read
and will not be used.**  Dell's own manuals (450k lines of extracted text,
now held locally) are the authoritative grammar source, and they are
sufficient — every form in [`10-grammar.md`](10-grammar.md) is cited to a
manual or a permissively-licensed capture.

The collection's 31 **role names** were used only as an index of which
OS10 resources exist (`os10_interface`, `os10_vlan`, `os10_vrf`,
`os10_vrrp`, `os10_snmp`, `os10_users`, `os10_vlt`, `os10_vxlan`, …).
A list of feature names is not copyrightable expression.

---

## Corpus adequacy — honest assessment

| Vendor | Committed fixtures | OS versions |
|---|---|---|
| existing codecs | 3–14 each | 2–6 versions |
| **dell_os10 (candidate)** | **12 permissive** | **1 confirmed (10.5.1.0)** |

Count is adequate; **version spread is not**.  Only the six JetPack files
carry a version banner at all, and all six say `10.5.1.0`.  Current OS10
trains are 10.5.6 / 10.6.0 / 10.6.1 — the corpus is **five minor releases
behind** and has zero coverage of the 10.6.x grammar.

Also: only 6 of 12 are genuine device dumps; the rest are authored
scripts.  Authored scripts are useful for parse coverage but are **not
valid round-trip fixtures** — they contain `configure terminal`,
`write memory`, `<PLACEHOLDER>` tokens, and `#`-style comments that a
device never emits.

**Recommendation:** treat the JetPack six as the round-trip corpus and the
rest as parse-only material, and add a 10.6.x ask to
[`WANTED.md`](../../../tests/fixtures/real/WANTED.md) if the codec proceeds.

---

## Tooling note

`gh search code` and `gh search repos` return **exit 0 with empty stdout
and empty stderr** in this environment — a silent tool failure, not "no
results".  Use `gh api -X GET search/code -f q='…'` instead, which works.
Fetch file contents by **blob SHA** (`git/blobs/<sha>`) rather than by
path: several Dell config paths contain spaces.

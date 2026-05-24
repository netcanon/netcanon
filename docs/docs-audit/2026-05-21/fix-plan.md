# Stage 2 — Documentation hygiene fix-plan

128 unique findings to close.  Total scope: ~50 .md files + ~15
.py files across the project.  All fixes are mechanical (docstring
edits, table additions, link path corrections, pointer conversions).
**No implementation agents needed** — orchestrator-direct execution
is the right shape.

Detailed evidence and rationale live in
[`99-synthesis.md`](99-synthesis.md); this file is the execution
checklist.

## Commit sequence (17 commits, sequenced by leverage)

### ☐ Commit 1 — `fix(docs): SECURITY.md v0.1.2 supply-chain hardening catch-up`

Single-file: `SECURITY.md`.  Closes the v0.1.2 update-trigger
violations:

* **Dependency Supply Chain table** — add `defusedxml>=0.7.1` row
  with XXE-mitigation rationale (S1)
* **Supply-Chain Integrity section** — add v0.1.2 sub-section
  enumerating new controls: zizmor workflow scanning + Trivy image
  scanning + 11 SHA-pinned third-party actions + `.github/zizmor.yml`
  policy + workflow-level `permissions: contents: read` +
  `persist-credentials: false` + Dependabot cooldown blocks +
  private vulnerability reporting + secret scanning + push protection
  + CodeQL default setup (S2)
* **New Input Validation section** for operator-uploaded XML
  documenting both swap sites + entity-bomb rejection class (S3)
* **See also** — add `docs/docs-audit/` reciprocal link (S5)
* (S6 — sharpening the trigger list enforcement — addressed in commit 3)

### ☐ Commit 2 — `fix(docs): ARCHITECTURE.md corrections (unsupported_rename + partials + v0.2.0)`

Single-file: `ARCHITECTURE.md`.  Closes:

* **Lines 329-337** — rewrite the `unsupported_rename_categories`
  paragraph: every bidirectional codec is empty EXCEPT OPNsense +
  Cisco IOS-XE NETCONF which declare `{'snmpv3'}` (A1)
* **Lines 594-636** — partials inventory: convert to one-line
  pointer per AGENTS.md row #14, OR add `kbd-cheatsheet.js` bullet
  (A2, A's W11 — same finding)
* **Lines 807-818** — Evolution roadmap: add v0.1.1 Wave A+B+C VRRP
  bullet (A3)
* **Lines 819-835** — optionally add v0.2.0 fixture-research catalogue
  reference (A4)
* **See also** — add `docs/docs-audit/` pointer (A's I3)

### ☐ Commit 3 — `fix(docs): AGENTS.md doc-sync rows for 5 recurring patterns`

Single-file: `AGENTS.md`.  Add 5 new doc-sync table rows + sharpen
1 existing row:

* **M1** — sanitiser categories → `SECURITY.md` Sanitiser table +
  `BUG_REPORTING.md`
* **M2** — canonical transforms (`canonical/transforms.py`) →
  `codecs/README.md` cross-codec utilities + `ARCHITECTURE.md`
* **M3** — top-level migration `_*.py` siblings → `ARCHITECTURE.md`
  cross-cutting policies
* **M4** — codec `unsupported_rename_categories` entries →
  `ARCHITECTURE.md` per-pane overrides + codec docstring
* **M5** — fixture-research catalogue updates → `README.md`
  + `RELEASE_PLAN.md` (low-priority — could fold into existing)
* **Row #29 sharpening** — explicitly fold SECURITY.md's 7-trigger
  list into the row so contributors don't round-trip

Also extend the AGENTS.md doc-sync row that fires on new fixtures
to include `docs/vendors/<vendor>.md` per Pattern P3.

### ☐ Commit 4 — `fix(docs): broken-link + path-relativity cleanup`

Multi-file mechanical fixes.  All A WRONG-class:

| File:Line | Edit |
|---|---|
| `README.md:260` | Remove `\| HUMAN_TESTING.md \|` row entirely (W1) |
| `BUG_REPORTING.md:26, :124, :151` | `../netcanon/tools/sanitize.py` → `netcanon/tools/sanitize.py` (×3) (W2-W4) |
| `tests/fixtures/real/WANTED.md:8, :92` | `../../BUG_REPORTING.md` → `../../../BUG_REPORTING.md` (×2) (W5-W6) |
| `docs/fixture-research-2015/README.md:134, :137` | `06-fixture-targets.md` → `05-fixture-targets.md` (×2) (W7-W8) |
| `docs/v0.2.0-planning/02-anycast-gateway/06-fixture-targets.md:17, :144` | `03-nxos-codec/06-fixture-targets.md` → `05-fixture-targets.md` (×2) (W9-W10) |
| `netcanon/api/routes/README.md:27-35` | Add table rows for `health.py` + `sanitize.py` (W12) |
| `tools/README.md` | Add `## demo.py` + `## load_cross_vendor_expectations.py` sections (or top-level overview table) (W13) |

### ☐ Commit 5 — `fix(docs): vendor pages + RESULTS.md + WANTED.md — under-listed fixtures (P3 batch)`

Multi-file.  Closes B's vendor-page INCOMPLETE + F's F3 + F4:

| File:Line | Edit |
|---|---|
| `docs/vendors/cisco_iosxe.md:171-184` | Add `batfish_iosxe_basic_vrrp.txt` + `ntc_carrier_interfaces.txt` rows |
| `docs/vendors/juniper_junos.md:164-181` | Add `ksator_labmgmt_qfx5110_junos173.set` + `ksator_labmgmt_qfx10k2_junos173.set` rows; update count summary |
| `docs/vendors/arista_eos.md:153-167` | Add `batfish_eos_evpn_vlan_based_leaf.txt` row |
| `docs/vendors/opnsense.md:160-181` | Add `opnsense_docs_carp_ha_master.xml` + `_backup.xml` rows |
| `docs/vendors/aruba_aoss.md:162-163` | Remove "2530 /" from hardware-classes summary OR rephrase |
| `tests/fixtures/real/RESULTS.md:36-48` (cisco_iosxe) + `:529-534` (arista_eos) + `:567-573` (junos) + `:169-175` (opnsense) | Add matrix row for each missing fixture |
| `tests/fixtures/real/RESULTS.md:614-623` (Summary) | Refresh per-codec counts: cisco_iosxe_cli 12→13, opnsense 5→7, arista_eos 4→5, junos 5→7, TOTAL 39→45 |
| `tests/fixtures/real/WANTED.md:21-27` | cisco_iosxe 12→13; arista_eos 4→5 |

### ☐ Commit 6 — `fix(docs): user-facing accuracy fixes`

Multi-file, all B-cluster WRONG + STYLE:

| File:Line | Edit |
|---|---|
| `README.md:277` | Add "3.14" to Python version list (or replace with "3.11+" pointer) |
| `docs/vendors/cisco_iosxe.md:13` | "parse-only" → "parse + render bidirectional" |
| `docs/TROUBLESHOOTING.md:112` | Drop "Phase 4.5" wording → "Use the sanitiser:" or `netcanon sanitize` |
| `README.md:25-26` | Add note on Docker quickstart's ephemeral key behaviour (B's #2; optional) |

### ☐ Commit 7 — `fix(docs): contributor-misleading instructions`

Multi-file.  Closes C's medium-priority misleading content:

| File | Edit |
|---|---|
| `netcanon/migration/canonical/README.md:152-154` | Rewrite the `_SOURCE_CAPABLE` instruction to point at per-category `_<CATEGORY>_TARGET_CAPABLE` pattern (C3) |
| `docs/RELEASE_PLAN.md:127-134` | "Next: tag v0.1.0 final" → reframe with v0.1.1 + v0.1.2 shipped (R2) |
| `docs/adding-a-canonical-field.md:245-254` | Drop the HUMAN_TESTING.md step (M15) |
| `docs/METHODOLOGY.md` lines 75-77, 124, 148, 243, 302, 311, 423, 464, 474, 501 | Replace hard-coded AGENTS.md / codec line ranges with section-name anchors (M2, M3) |
| `docs/glossary.md` | Add missing terms: `unsupported_rename_categories`, `MODULE_VARIANT_PROFILES`, `dropped_tier3_sections`, `effective_ports`, `WANTED.md`, "ship-before-wire", "Capability matrix" (M12) |

### ☐ Commit 8 — `fix(docs): codec operator-facing descriptions`

Multi-codec.  Closes D's operator-facing WRONG:

| File:Line | Edit |
|---|---|
| `juniper_junos/codec.py:85-91` | Rewrite `description` ClassVar — block-form auto-detection (D-JU-1) |
| `cisco_iosxe_cli/codec.py:44-46` | Remove or rewrite "secondary IPs ignored" bullet (D-IC-1) |
| `aruba_aoss/__init__.py:41` | Move RADIUS out of "Out of scope (future)" (D-AA-2) |
| `mikrotik_routeros/__init__.py:36-39` | "best_effort" → "certified" (D-MT-1) |
| `cisco_iosxe/codec.py:624` | `render(tree: dict[str, Any] \| CanonicalIntent)` signature + docstring update (D-CN-2) |

### ☐ Commit 9 — `fix(docs): codec __init__.py — convert Scope enumerations to pointers (P1)`

Multi-file (6 codecs).  Per AGENTS.md row #14 "prefer pointers":

| File | Edit |
|---|---|
| `arista_eos/__init__.py:26-41` | Replace "Supported blocks" enumeration with pointer to `_CAPS.supported` in codec.py |
| `aruba_aoss/__init__.py:19-27` | Same pattern |
| `cisco_iosxe/__init__.py:9-11` | Add IPv6 to scope OR pointer-ize |
| `fortigate_cli/__init__.py:10-24` | Replace enumeration with pointer |
| `mikrotik_routeros/__init__.py:12-25` | Replace "Scope (current)" with pointer |
| `opnsense/__init__.py:15-19` | Replace "Scope (Phase 1)" with pointer |

Reference template: `cisco_iosxe_cli/__init__.py`.

### ☐ Commit 10 — `fix(docs): codec parse_intent/render_intent Google-style sections (P2)`

Multi-file (7 codecs).  Propagate `cisco_iosxe_cli/parse.py:444-450`
Args/Returns/Raises template:

* `arista_eos/parse.py:351-352` + `render.py:148-149`
* `aruba_aoss/parse.py:759-761` + `render.py:365-368`
* `cisco_iosxe_cli/render.py` (parse already done; render needs sections)
* `fortigate_cli/parse.py:881-885` + `render.py:413-415`
* `juniper_junos/parse.py:77-78` + `render.py` (likely)
* `mikrotik_routeros/parse.py:65-72` + `render.py:100-104`
* `opnsense/parse.py:162-176` + `render.py:55-66`

Per-function: add Args, Returns, Raises blocks matching the
established cisco_iosxe_cli pattern.

### ☐ Commit 11 — `fix(docs): platform single-token fixes`

Multi-file, all single-line code/docstring fixes:

| File:Line | Edit |
|---|---|
| `netcanon/main.py:218` | Replace literal `version="0.1.0"` with `importlib.metadata.version("netcanon")` pattern (E-top-1) |
| `netcanon/tools/sanitize.py:35` | `CanonicalRADIUSServer.shared_secret` → `CanonicalRADIUSServer.key` (E-tools-1) |
| `netcanon/api/routes/migration.py:269` | `/plan/local-users` → `/plan/local_users` (E-api-1) |
| `netcanon/api/routes/migration.py:18` | Extend dispatch list to include `snmpv3_user_rename_map` (E-api-2) |
| `netcanon/__init__.py:5-12` | Add `netcanon.migration` to package layout list (E-top-2) |

**Test verification required after this commit** (touches Python
code in main.py + sanitize.py).  Run `py -m pytest tests/unit/api
tests/unit/migration -p no:cacheprovider`.

### ☐ Commit 12 — `fix(docs): paramiko_collector security framing + file_store MAX_CONFIG_SIZE`

Multi-file structural docstring fixes:

| File | Edit |
|---|---|
| `netcanon/collectors/paramiko_collector.py:1-16, 118-127, 147, 237` | Add "Security model" section to module docstring naming AutoAddPolicy + operator-as-trust-anchor; add comment above each `set_missing_host_key_policy()` call site citing `docs/security-triage/2026-05-21/` (E-col-1) |
| `netcanon/storage/file_store.py:133-138` | Hoist `MAX_CONFIG_SIZE` to module-level constant (match `config.py:MAX_BACKUP_CONCURRENCY` pattern) with rationale comment; add `Raises: ValueError` to `save()` docstring (E-store-1) |
| `netcanon/storage/file_store.py:91-99` (`__init__`) | Add 1-line note about `_migrate_flat_files()` legacy migration (E-store-2) |
| `netcanon/collectors/netmiko_collector.py:11-15` | Convert "Supported netmiko_device_type values" inline list to "see `definitions/*/collector.yaml`" pointer (E-col-2) |

### ☐ Commit 13 — `fix(docs): canonical intent.py Tier annotations + Pydantic Attributes consistency (P5+P6)`

Single-file: `netcanon/migration/canonical/intent.py` + 3 model
files.  Systematic edits per Patterns P5 + P6:

* Per-class Tier annotation (16 classes): add `(Tier N — rationale)`
  suffix to docstring
* `CanonicalInterface` (line 171-172): convert inline field
  comments into `Attributes:` block OR add pointer (E-canon-1)
* `CanonicalIntent` (line 764-774): same (E-canon-2)
* `CanonicalDHCPPool`, `CanonicalLAG`, `CanonicalLocalUser`,
  `CanonicalRADIUSServer`: expand to Attributes blocks (E-canon-3 through E-canon-6)
* `models/migration.py:310-343` `MigrationJob` Attributes (15 missing) — decide pattern + apply (E-mod-1)
* `models/backup.py:87-100` `BackupJob` Attributes (2 missing) (E-mod-2)
* `models/migration.py:154-172` `CapabilityMatrix` Attributes (2 missing) (E-mod-3)

**Test verification required after this commit** if docstring
changes affect any tests that read `__doc__` (unlikely but check).
Run `py -m pytest tests/unit/migration -p no:cacheprovider`.

### ☐ Commit 14 — `fix(docs): migration_pipeline.py FROZEN docstring forward-looking pointers`

Single-file: `netcanon/services/migration_pipeline.py`.

**⚠ FROZEN: docstring changes ONLY. Signatures of `run_plan`,
`run_plan_with_rename`, `run_plan_with_overrides` MUST NOT change.**

* `:323-328` Planned future-commit categories — replace inline list with pointer to `docs/v0.2.0-planning/` (E-svc-1)
* `:11-12` Public surface section — add cross-ref to Capture-first transform section further down (E-svc-2)

### ☐ Commit 15 — `fix(docs): cross-doc small fixes (See-also + CODE_OF_CONDUCT + style)`

Multi-file batch:

| File | Edit |
|---|---|
| `README.md` | Append `## See also` section per AGENTS.md exemplar (M1 — A) |
| `tests/README.md` | Add `## See also` section OR rename "Related documentation" → "See also" (M2 — A) |
| `CODE_OF_CONDUCT.md:40` | Substitute `[INSERT CONTACT METHOD]` with security advisory URL or contact email (C15 — A's M3 + C's C15) |
| `CONTRIBUTING.md` (or `README.md` "For contributors" table) | Add reference to `CODE_OF_CONDUCT.md` (M3 — A) |
| `docs/vendor-references/README.md` + `tests/fixtures/cross_vendor_expectations/README.md` | Convert bare-backtick See-also entries to `[label](path)` form (I1, I2 — A) |
| `docs/fixture-research-2015/11-aruba_aoscx.md:363` | em-dash anchor → ASCII (S3 — A) |
| `netcanon/api/routes/README.md:194-199` | Optional: point at specific files instead of directories (S5 — A) |

### ☐ Commit 16 — `fix(docs): tests cluster cleanup (testid + CHANGELOG + slow marker)`

Multi-file:

| File:Line | Edit |
|---|---|
| `tests/testid_reference.md:348-357` | Delete 10 stale `sched-device-*` rows + add subsection-removed note (F1) |
| `tests/testid_reference.md` (Sanitize section) | Add `sanitize-safety-note` row (F2) |
| `pyproject.toml:151` + `tests/README.md:127` | Either delete `slow` marker (zero usages) OR wire into cross-mesh `>5s` tests (F5) |
| `CHANGELOG.md:24,173` | Flip 0.1.1 to UTC date (2026-05-20) OR flip 0.1.2 to local (2026-05-20); document convention in preamble (F6) |
| `CHANGELOG.md:201-202` | Drop the test-delta arithmetic parenthetical OR recompute against `git log v0.1.0-rc9..v0.1.1 --stat` (F7) |
| `CHANGELOG.md:155` ("Real-capture fixture corpus — no additions") | Footnote: CARP HA additions in `4686198` predated the security-cycle commits captured in 0.1.2's main commit list (F3 secondary) |

### ☐ Commit 17 — `docs(audit): 2026-05-21 evidence trail + snapshot correction + AGENTS see-also`

Multi-file final commit (mirrors security-triage pattern):

* `docs/docs-audit/2026-05-21/` — the per-cluster JSON-style files + investigation reports + synthesis + this fix-plan
* `docs/docs-audit/2026-05-21/00-snapshot.md` — correct "7 codecs" to "8 codecs (cisco_iosxe + cisco_iosxe_cli are distinct)" per F's cross-cutting note 5
* `AGENTS.md` See also — confirm `docs/docs-audit/` entry present (added during scaffolding)
* `docs/security-triage/README.md` See also — confirm `docs/docs-audit/` reciprocal added during scaffolding

## Total alert closure (predicted)

```
128 unique findings closed across 17 commits:
  Commit 1   →  5 closed  (SECURITY.md S1-S6)
  Commit 2   →  5 closed  (ARCHITECTURE A1-A5)
  Commit 3   →  5 closed  (AGENTS.md doc-sync M1-M5) + 1 sharpening
  Commit 4   → 10 closed  (broken links W1-W13 minus W11 overlap with C2)
  Commit 5   →  9 closed  (vendor pages + RESULTS + WANTED)
  Commit 6   →  3 closed  (user-facing single-line fixes)
  Commit 7   →  6 closed  (contributor-misleading)
  Commit 8   →  5 closed  (codec operator descriptions)
  Commit 9   →  6 closed  (codec __init__ scope)
  Commit 10  → 14 closed  (codec Google-style sections, 7 codecs × 2 funcs)
  Commit 11  →  5 closed  (platform single-token)
  Commit 12  →  4 closed  (paramiko + file_store + netmiko)
  Commit 13  → ~22 closed  (intent.py Tier + Pydantic Attributes)
  Commit 14  →  2 closed  (FROZEN docstring)
  Commit 15  →  7 closed  (cross-doc small)
  Commit 16  →  6 closed  (tests + CHANGELOG)
  Commit 17  →  2 closed  (snapshot + see-also)
            ────
              ~116 closed (gap covers STYLE noise + EXPECTED-STALE)
```

Defer-eligible STYLE (~12 findings) batched into the final commit
or left for a follow-up hygiene cycle.

## Post-execution verification

* After commit 11: `py -m pytest tests/unit/api tests/unit/migration -p no:cacheprovider`
* After commit 13: `py -m pytest tests/unit/migration -p no:cacheprovider`
* After commit 17 (final): `py -m pytest tests/unit --tb=no -p no:cacheprovider` full suite
* `git push` all commits
* No GitHub re-scan needed (this is docs-only)

## Awareness items captured for next audit

* **AGENTS.md doc-sync row #14** ("prefer pointers over inventories")
  is the single most-applicable rule across this audit's findings.
  Future hygiene cycles should weight enforcement of this rule.
* **The codec corpus has a clear "reference template" pattern** —
  `cisco_iosxe_cli/__init__.py` for minimal package docstrings,
  `cisco_iosxe_cli/parse.py:444-450` for Google-style sections.
  Use these as templates in propagation passes.
* **The Tier annotation convention** (Tier 1/2/3 from `intent.py`)
  is load-bearing but invisible at `help()`/IDE-tooltip level.
  Per-class annotations close that gap.
* **SECURITY.md update discipline** would benefit from explicit
  release-cycle integration — proposed: SECURITY.md catch-up as a
  required commit before any `vX.Y.Z` tag, enforced by checklist.

## See also

* [`README.md`](../README.md) — audit process + cluster taxonomy
* [`00-snapshot.md`](00-snapshot.md) — initial state + scope
* [`99-synthesis.md`](99-synthesis.md) — full per-cluster findings

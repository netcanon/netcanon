# 2026-05-21 — Synthesis

Consolidated verdict across 6 read-only Stage 1 Opus 4.7 1M agents.
Reconciled from
[`01-investigation-A.md`](01-investigation-A.md) (interlinking),
[`01-investigation-B.md`](01-investigation-B.md) (user-facing),
[`01-investigation-C.md`](01-investigation-C.md) (developer-facing),
[`01-investigation-D.md`](01-investigation-D.md) (codec docstrings),
[`01-investigation-E.md`](01-investigation-E.md) (platform docstrings),
[`01-investigation-F.md`](01-investigation-F.md) (tests + CHANGELOG).

## Tally — 134 findings across 6 clusters

| Cluster | WRONG | MISSING | INCOMPLETE | STYLE | EXPECTED | Total |
|---|---|---|---|---|---|---|
| A — Interlinking            | 13 |  3 |  3 | 6 | 0 | **25** |
| B — User-facing             |  2 |  0 |  9 | 3 | 0 | **14** |
| C — Developer-facing        |  6 |  5 |  6 | 4 | 3 | **24** |
| D — Codec docstrings        |  3 |  0 | 30 | 9 | 0 | **42** |
| E — Platform docstrings     |  3 |  1 | 13 | 4 | 1 | **22** |
| F — Tests + CHANGELOG       |  1 |  2 |  2 | 2 | 0 |  **7** |
| **Total**                   | **28** | **11** | **63** | **28** | **4** | **134** |

After cross-cluster overlap reconciliation (see § Cross-cluster
overlaps), unique findings ≈ **128**.

## Headline narrative (3 sentences)

Documentation hygiene is in **good shape overall** — 91 of 778 .md
files carry a `## See also` section, every CHANGELOG-cited SHA on
v0.1.1 + v0.1.2 resolves, NOTICE.md is byte-exhaustive (45/45 fixtures
have provenance rows), IDENTITY.md matches GitHub repo metadata
byte-for-byte, the AGENTS.md doc-sync table passes 28 of 32 rows,
hard rules all map to enforcement points, and v0.1.2's defusedxml
safe-import comments correctly cite the security-triage trail.  The
**biggest concentrated drift is on SECURITY.md** (v0.1.2 met 3 of its
own 7 update triggers and was not refreshed), with secondary drift
concentrated on **vendor pages chronically under-listing fixtures**
(4 of 6 affected, same root cause as RESULTS.md matrix drift) and
**codec `__init__.py` "Scope" lists lagging `_CAPS.supported` by
1-3 Waves** (6 of 8 codecs).  The systematic pattern across all
clusters: **inline inventories rot; AGENTS.md doc-sync rule #14
("prefer pointers over exhaustive inventories") would close the
recurring drift class if applied uniformly.**

## Cross-cluster overlaps (deduplicate before Stage 2)

| Finding | Surfaced by | Single fix |
|---|---|---|
| `BUG_REPORTING.md` 3 broken `../netcanon/` links | A (W2-W4) + B (#4) | One commit |
| `ARCHITECTURE.md` partials list missing `kbd-cheatsheet.js` | A (W11) + C (A2) | One commit |
| RESULTS.md matrix missing 5 fixtures + vendor pages under-list same 5 | B (vendor pages) + F (F3) | One commit (cross-doc) |
| `HUMAN_TESTING.md` reference in README + adding-a-canonical-field | A (W1) + C (M15) | One commit |
| `00-snapshot.md` "7 codecs" but tree has 8 | F (cross-cutting note 5) | One-line fix in final commit |
| `unsupported_rename_categories` doc claim vs codec declarations | C (A1) + needs cross-check with D | One commit (ARCHITECTURE) + doc-sync row addition |

## Highest-priority findings (must-fix before defer-eligible noise)

These 12 are the WRONG findings whose downstream impact is broadest
(operator-facing claim violation OR contributor-misleading) and that
should land in early Stage 2 commits:

### Operator-trust load-bearing

1. **`SECURITY.md`** — defusedxml not in Dependency Supply Chain
   table; v0.1.2 supply-chain hardening (zizmor + Trivy + SHA pinning
   + permissions + Dependabot cooldown + scanner enablement) not in
   Supply-Chain Integrity section; no Input Validation section for
   operator-uploaded XML.  (C: S1, S2, S3)
2. **`docs/vendors/cisco_iosxe.md:13`** — calls `cisco_iosxe_cli`
   "parse-only"; codec is `bidirectional` with 817-line `render.py`
   and is the source AND target across every walkthrough.  (B: #5)
3. **`README.md:277`** — Python matrix lists 3.11/3.12/3.13; CI
   runs 3.14 too and pyproject has the 3.14 classifier.  (B: #1)
4. **`netcanon/main.py:218`** — FastAPI `version="0.1.0"`
   hard-coded; current release is v0.1.2; exposed via OpenAPI
   schema + `/docs` UI.  (E: E-top-1)
5. **`CODE_OF_CONDUCT.md:40`** — `[INSERT CONTACT METHOD]`
   contributor-covenant placeholder unsubstituted; operators with
   conduct concerns have no actionable channel.  (C: C15)

### Codec operator-facing descriptions

6. **`juniper_junos/codec.py:85-91`** — operator-facing
   `description` says "Block-form is NOT parsed in v1" but codec
   auto-detects + converts block-form to set-form.  (D: D-JU-1)
7. **`cisco_iosxe_cli/codec.py:44-46`** — Limitations bullet
   "secondary IPs ignored on parse" contradicts parse.py:778-792
   (handles secondaries) and render.py (emits `secondary` keyword).
   (D: D-IC-1)
8. **`aruba_aoss/__init__.py:41`** — "Out of scope (future): RADIUS"
   but RADIUS is actively populated.  (D: D-AA-2)
9. **`mikrotik_routeros/__init__.py:36-39`** — claims
   `best_effort`; `codec.py:100` declares `certified`.  (D: D-MT-1)

### Contributor-misleading

10. **`ARCHITECTURE.md:329-337`** — claims every bidirectional codec
    has `unsupported_rename_categories` empty post-Option-A; OPNsense
    and Cisco IOS-XE NETCONF both declare `{"snmpv3"}`.  (C: A1)
11. **`netcanon/migration/canonical/README.md:152-154`** — tells
    new-rename-category authors to extend legacy `_SOURCE_CAPABLE`/
    `_TARGET_CAPABLE` globals; actual pattern is per-category
    `_<CATEGORY>_TARGET_CAPABLE` lists.  (C: C3)
12. **`netcanon/tools/sanitize.py:35`** — docstring claims
    `CanonicalRADIUSServer.shared_secret`; actual field name is
    `key`.  (E: E-tools-1)

## Systematic patterns (single batch fixes a class)

These aren't individual findings but pattern-level discoveries.
Stage 2 should address each via a thematic commit.

### Pattern P1 — Codec `__init__.py` "Scope" lag (6 of 8 codecs)

6 of 8 codec packages declare "Scope (Phase 1)" / "Scope (Tier 1)"
enumerations lagging `_CAPS.supported` by 1-3 Tiers/Waves.

**Fix shape:** convert to one-line pointer (`"See _CAPS.supported
in codec.py for the canonical scope list."`) per AGENTS.md row #14.
`cisco_iosxe_cli/__init__.py` is the clean reference template.

Affected: arista_eos, aruba_aoss, cisco_iosxe (NETCONF stub),
fortigate_cli, mikrotik_routeros, opnsense.

### Pattern P2 — Codec `parse_intent` / `render_intent` Google-style sections absent (7 of 8 codecs)

Per AGENTS.md doc-sync row: public-function signature changes need
Google-style Args/Returns/Raises sections.  Only
`cisco_iosxe_cli/parse.py:444-450` follows the pattern.

**Fix shape:** propagate the cisco_iosxe_cli template across 7
codecs in one mechanical pass.

### Pattern P3 — Vendor pages under-list fixtures (4 of 6) + RESULTS.md matrix stale

Same root cause: AGENTS.md doc-sync row for new real-capture
fixtures fires `NOTICE.md` + `RESULTS.md` but doesn't include the
per-vendor doc page.  Result: 5 fixtures landed (one cisco_iosxe,
one arista_eos, two opnsense CARP, two junos QFX) without
propagating to vendor pages OR to RESULTS.md matrix tables OR to
WANTED.md corpus-snapshot counts.

**Fix shape:** one commit adds the 5 missing entries across
`docs/vendors/{cisco_iosxe,juniper_junos,arista_eos,opnsense}.md` +
`tests/fixtures/real/RESULTS.md` + `tests/fixtures/real/WANTED.md`
counts.  Plus a new AGENTS.md doc-sync row to prevent re-occurrence.

### Pattern P4 — Inline inventories rot (cross-cluster)

`tools/README.md` script inventory missing 2 scripts;
`netcanon/api/routes/README.md` route inventory missing 2 routers;
`ARCHITECTURE.md` partials list missing 1 partial;
`migration_pipeline.py` planned-future-categories list will drift;
`netcanon/__init__.py` package-layout list omits `migration`.

**Fix shape:** convert each to a pointer ("see directory listing"
or "see specific section") rather than maintaining inline
enumerations.  Same fix philosophy as P1.

### Pattern P5 — Pydantic `Attributes:` blocks lag field additions

`MigrationJob` (15 fields not in Attributes block; documented via
inline `#:` Sphinx markers); `BackupJob` (2 missing); `CapabilityMatrix`
(2 missing).  Drift class: `Attributes:` block written with original
fields, later additions use `#:` markers; Sphinx renders correctly
but `help()` shows incomplete docstring.

**Fix shape:** pick one convention (either commit to `#:` and
shorten Attributes to "see field-level docs" pointer, OR commit to
Attributes block and update on every field add); apply uniformly.

### Pattern P6 — Tier annotations on canonical classes (CC-1)

`intent.py` module docstring declares Tier 1/2/3 taxonomy; per-class
docstrings don't carry tier annotation.  Reader of
`CanonicalDHCPPool.__doc__` via `help()` or IDE tooltip sees no tier
context.

**Fix shape:** 16-line systematic edit — add `(Tier N — rationale)`
suffix to each canonical class docstring.

### Pattern P7 — `_partials/` contents-map drift is recurrent

ARCHITECTURE.md partials inventory has gone stale once
(`kbd-cheatsheet.js`).  AGENTS.md doc-sync row #2 covers
`_partials/` additions but no enforcement test.  Pattern: every time
a new partial lands, the inventory rots unless the same commit
touches ARCHITECTURE.md.

**Fix shape:** convert ARCHITECTURE.md enumeration to "see `ls
netcanon/templates/_partials/`" pointer (or per-partial header
comments — discussed in A's cross-cutting observations).

## Findings by file (grouped for Stage 2 commit dispatch)

### `SECURITY.md` — 5 findings, single-file commit

* S1 [WRONG]: Dependency Supply Chain table missing `defusedxml`
* S2 [WRONG]: Supply-Chain Integrity section missing v0.1.2 hardening
* S3 [MISSING]: No Input Validation section for operator-uploaded XML
* S5 [INCOMPLETE]: See also doesn't link `docs/docs-audit/`
* S6 [INCOMPLETE]: 7-trigger list not enforced by AGENTS.md row

### `ARCHITECTURE.md` — 5 findings, single-file commit

* A1 [WRONG]: `unsupported_rename_categories` claim contradicts code
* A2 [INCOMPLETE]: Partials inventory missing `kbd-cheatsheet.js`
* A3 [INCOMPLETE]: Evolution roadmap missing v0.2.0 Wave A+B+C
* A4 [INCOMPLETE]: Evolution missing fixture-research catalogue
* A5 [STYLE]: Qualitative phrasing (defer-eligible)

### `AGENTS.md` — 5 MISSING doc-sync rows + 1 row #29 sharpening

* M1: sanitiser categories → SECURITY.md
* M2: canonical transforms → codecs/README + ARCHITECTURE
* M3: top-level migration `_*.py` siblings → ARCHITECTURE
* M4: codec `unsupported_rename_categories` additions → ARCHITECTURE + codec docstring
* M5: fixture-research catalogue updates (low priority)
* Row #29: also include SECURITY.md trigger list explicitly

### Broken-link cleanup (A's WRONG) — multi-file commit

* W1: README.md HUMAN_TESTING.md row → remove
* W2-W4: BUG_REPORTING.md `../netcanon/...` × 3 → strip `../`
* W5-W6: WANTED.md `../../BUG_REPORTING.md` × 2 → `../../../`
* W7-W10: v0.2.0-planning off-by-one `06-fixture-targets.md` (×4) → `05-`
* W11: ARCHITECTURE.md partials inventory `kbd-cheatsheet.js` (also part of ARCHITECTURE commit above; pick one)
* W12: api/routes/README.md missing `health.py` + `sanitize.py`
* W13: tools/README.md missing `demo.py` + `load_cross_vendor_expectations.py`

### Vendor pages + tests RESULTS.md + WANTED.md (P3 batch) — multi-file commit

* `docs/vendors/cisco_iosxe.md:171-184`: add 2 missing fixtures
* `docs/vendors/juniper_junos.md:164-181`: add 2 missing QFX fixtures
* `docs/vendors/arista_eos.md:153-167`: add 1 missing EVPN fixture
* `docs/vendors/opnsense.md:160-181`: add 2 missing CARP HA fixtures
* `docs/vendors/aruba_aoss.md:162-163`: remove "2530" overclaim
* `docs/vendors/cisco_iosxe.md:13`: "parse-only" → "bidirectional"
* `tests/fixtures/real/RESULTS.md`: 5 matrix rows + Summary refresh
* `tests/fixtures/real/WANTED.md:21-27`: cisco_iosxe 12→13, arista 4→5

### Codec operator-facing descriptions (D WRONG batch) — multi-file commit

* `juniper_junos/codec.py:85-91`: rewrite description for block-form auto-detection
* `cisco_iosxe_cli/codec.py:44-46`: remove or rewrite "secondary IPs ignored"
* `aruba_aoss/__init__.py:41`: remove RADIUS from Out-of-scope
* `mikrotik_routeros/__init__.py:36-39`: best_effort → certified
* `cisco_iosxe/codec.py:624`: update render() type signature

### Codec `__init__.py` Scope-pointer conversion (P1 batch) — multi-file commit

6 codecs: arista_eos, aruba_aoss, cisco_iosxe (NETCONF stub),
fortigate_cli, mikrotik_routeros, opnsense.  Replace "Scope (Phase
1)" / "Scope (Tier 1)" enumerations with one-line pointers.

### Codec `parse_intent` / `render_intent` Google-style sections (P2 batch) — multi-file commit

7 codecs: arista_eos, aruba_aoss, cisco_iosxe_cli, fortigate_cli,
juniper_junos, mikrotik_routeros, opnsense.  Propagate
cisco_iosxe_cli template to add Args/Returns/Raises.

### Platform single-token fixes — multi-file commit

* `netcanon/main.py:218`: `version="0.1.0"` → dynamic via importlib.metadata
* `netcanon/tools/sanitize.py:35`: `shared_secret` → `key`
* `netcanon/api/routes/migration.py:269`: `/plan/local-users` → `/plan/local_users`
* `netcanon/api/routes/migration.py:18`: extend dispatch list to include `snmpv3_user_rename_map`

### `canonical/intent.py` — Tier annotations + Attributes blocks (P5+P6 batch)

* Add `(Tier N — rationale)` to every canonical class docstring (16-line edit)
* Extend Attributes blocks for `CanonicalInterface` + `CanonicalIntent` to enumerate v0.2.0 Wave A additions (or convert to "see field-level inline comments" pointer)

### `paramiko_collector.py` security framing (E-col-1)

Add "Security model" section to module docstring + comment above each `set_missing_host_key_policy()` call site citing security-triage decision.

### `file_store.py` MAX_CONFIG_SIZE hoist (E-store-1)

Hoist `MAX_CONFIG_SIZE` to module-level constant with rationale (match `config.py:MAX_BACKUP_CONCURRENCY` pattern).  Add `Raises: ValueError` to `save()` docstring.

### `migration_pipeline.py` — FROZEN docstring-only edits

* E-svc-1: Replace "Planned future-commit categories" inline list with pointer to `docs/v0.2.0-planning/`
* E-svc-2: Add cross-ref from "Public surface" section to "Capture-first transform" section

**FROZEN: signature must NOT change. Stage 2 touches docstring ONLY.**

### Pydantic `Attributes:` block consistency (P5 batch)

* `MigrationJob` (15 missing) — `models/migration.py:310-343`
* `BackupJob` (2 missing) — `models/backup.py:87-100`
* `CapabilityMatrix` (2 missing) — `models/migration.py:154-172`

### tests cluster fixes — multi-file commit

* `tests/testid_reference.md:348-357`: delete 10 stale `sched-device-*` rows
* `tests/testid_reference.md`: add `sanitize-safety-note` row
* `pyproject.toml:151` + `tests/README.md:127`: decide on `slow` marker (delete or wire)
* `CHANGELOG.md:24,173`: pick UTC vs local date convention; document in preamble
* `CHANGELOG.md:201-202`: drop or recompute the test-delta arithmetic

### Contributor-misleading fixes — multi-file commit

* `netcanon/migration/canonical/README.md:152-154`: correct _SOURCE_CAPABLE instruction
* `docs/RELEASE_PLAN.md:127-134`: "Next" reframe (v0.1.1 + v0.1.2 shipped)
* `docs/adding-a-canonical-field.md:245-254`: drop the HUMAN_TESTING.md step
* `METHODOLOGY.md`: replace hard-coded line ranges (110-134, 142-159, 191-200, 209-219) with section-name anchors
* `docs/glossary.md`: add missing terms (unsupported_rename_categories, MODULE_VARIANT_PROFILES, dropped_tier3_sections, effective_ports, WANTED.md, ship-before-wire, Capability matrix)

### Cross-doc smaller fixes — multi-file commit

* `README.md`: add `## See also` section per AGENTS.md exemplar
* `tests/README.md`: add `## See also` section (or rename "Related documentation")
* `CODE_OF_CONDUCT.md:40`: substitute `[INSERT CONTACT METHOD]`
* `CONTRIBUTING.md` (or `README.md`): add reference to CODE_OF_CONDUCT.md
* `docs/TROUBLESHOOTING.md:112`: drop "Phase 4.5" wording
* `docs/vendor-references/README.md` + `tests/fixtures/cross_vendor_expectations/README.md`: convert bare-backtick See-also entries to `[label](path)` form
* `docs/fixture-research-2015/11-aruba_aoscx.md:363`: em-dash anchor → ASCII

## Defer-eligible STYLE findings (~28 across clusters)

These are documented in their per-cluster reports but don't warrant
Stage 2 commits.  Pick up in a future hygiene pass:

* Vendor-references hyphen vs underscore filename convention (A: S2)
* Various single-line stylistic drifts
* `RELEASE_PLAN.md` hard-coded test counts (acceptable per archival exemption)
* Bare-backtick See also (low-priority style)

## EXPECTED-STALE findings (4 — no action)

* METHODOLOGY.md pre-launch SHA citations (C: M1; documented in CHANGELOG preamble)
* RELEASE_PLAN.md "Post-launch roadmap notes" forward-looking section (C: R5)
* RELEASE_PLAN.md "Pre-launch quality hardening" aspirational section (C: R6)
* `canonical/loader.py` Phase-0.5 stub (E: E-canon-7 — documented in canonical/README)

## Stage 2 dispatch shape

All Stage 2 work is orchestrator-direct (no implementation agents
needed).  Mechanical edits across well-defined files.  Test-suite
verification only needed if Python code changes (commits touching
canonical/intent.py, intent docstrings; or main.py version logic).

**Proposed commit cadence (~15 commits):**

1. `fix(docs): SECURITY.md v0.1.2 supply-chain hardening catch-up`
2. `fix(docs): ARCHITECTURE.md corrections (unsupported_rename + partials + v0.2.0)`
3. `fix(docs): AGENTS.md doc-sync rows for 5 recurring patterns`
4. `fix(docs): broken-link + path-relativity cleanup across .md files`
5. `fix(docs): vendor pages + RESULTS.md + WANTED.md — under-listed fixtures`
6. `fix(docs): user-facing accuracy (cisco parse-only, README Python version, TROUBLESHOOTING)`
7. `fix(docs): contributor-misleading instructions (canonical/README, RELEASE_PLAN, adding-a-canonical-field, METHODOLOGY anchors, glossary)`
8. `fix(docs): codec operator-facing descriptions (junos block-form, cisco-iosxe secondary IPs, aruba RADIUS, mikrotik certified)`
9. `fix(docs): codec __init__.py — convert Scope enumerations to pointers (P1)`
10. `fix(docs): codec parse_intent/render_intent Google-style Args/Returns/Raises (P2)`
11. `fix(docs): platform single-token fixes (main.py version, sanitize.py shared_secret, migration.py underscore)`
12. `fix(docs): paramiko_collector security framing + file_store MAX_CONFIG_SIZE hoist`
13. `fix(docs): canonical intent.py Tier annotations + Pydantic Attributes block consistency`
14. `fix(docs): migration_pipeline.py FROZEN docstring forward-looking pointers (docstring-only)`
15. `fix(docs): cross-doc smaller fixes (README + tests/README See-also, CODE_OF_CONDUCT, CONTRIBUTING, bare-backtick conversions)`
16. `fix(docs): tests cluster cleanup (testid_reference stale + missing, CHANGELOG dates + arithmetic, slow marker)`
17. `docs(audit): 2026-05-21 audit evidence trail + 00-snapshot 7→8 codec correction + AGENTS see-also`

Sequencing notes:
* Commits 1-3 are highest-leverage (SECURITY.md + ARCHITECTURE.md
  + AGENTS.md are the load-bearing contributor docs); land first.
* Commits 4-7 are operator-trust cleanup.
* Commits 8-10 are codec docstring hygiene.
* Commits 11-14 are platform docstring hygiene.
* Commits 15-16 are cross-doc small fixes.
* Commit 17 is the audit evidence trail (mirrors security-triage
  pattern).

All commits are file-disjoint except where cross-doc edits span;
no merge-conflict risk.

## Verification post-fixes

* `py -m pytest tests/unit --tb=no -p no:cacheprovider` after
  commit 11 (platform single-token fixes touching code) and
  commit 13 (canonical intent.py changes if any).  Other commits
  are docs-only.
* `py -c "import yaml; ..."` on any workflow file touched (none
  expected in this audit cycle).
* No re-scan needed (this is a docs audit, not a security cycle).

## See also

* [`README.md`](../README.md) — process doc + cluster taxonomy
* [`00-snapshot.md`](00-snapshot.md) — initial state + scope
* [`fix-plan.md`](fix-plan.md) — Stage 2 execution checklist

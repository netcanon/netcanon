# Investigation DC — Test-ID Inventory + Per-Test Explanation Discipline

**Reviewer:** DC (Fleet D, documentation review)
**Commit:** `b08040c` / v0.1.2
**Scope:** READ-ONLY. `tests/testid_reference.md`; `tests/README.md`;
the docstring/naming/comment quality of test modules themselves;
the real-capture documentation surfaces (`RESULTS.md`, `WANTED.md`,
`NOTICE.md`, `PHASE4_RECONCILIATION.md`, `CROSS_MESH_RESULTS.md`).
Cross-checked against `pyproject.toml [tool.pytest.ini_options]`,
`AGENTS.md`, and the 2026-05-21 docs-audit fix-plan.

---

## 1. Scope & method

This lens has two halves, and I treated them as two independent
audits joined only by the file that documents the test surface.

**Half 1 — Test-ID inventory integrity.** The project's testing
discipline (codified in `AGENTS.md` and stated at
`tests/testid_reference.md:1-6`) is that *every interactive HTML
element carries a `data-testid`*, E2E tests select on those
attributes exclusively, and `tests/testid_reference.md` is the
canonical inventory. A reference doc like this rots in two
directions: **template-only drift** (an element gains a testid that
never gets a doc row) and **doc-only drift** (a row outlives the
element it described). I measured both, mechanically, with
placeholder-aware normalization.

Method: I enumerated `data-testid` occurrences three ways, because
testids are constructed three ways in this codebase:

1. Literal HTML attributes `data-testid="..."` (the bulk).
2. JS `setAttribute('data-testid', <expr>)` inside the
   `_partials/*.js` renderers and inline `<script>` blocks (e.g.
   `_partials/rename-table.js:223`, `_partials/job-progress.js:64`).
3. Ternary / string-concatenation forms
   (`configs.html:241`: `crossVendor ? 'compare-option-cross-vendor'
   : 'compare-option'`; `migrate.html:1544`:
   `'migrate-tier3-section-' + idx`).

A naive `grep data-testid="` misses (2) and (3) entirely and
produces ~28 false "doc-only" findings. I wrote a normalizer that
collapses dynamic suffixes (`<source>`, `<id>`, `-N`, `{category}`,
`' + idx + '`) to a common `<*>` family token on both sides, then
diffed. I then hand-verified every residual mismatch against the
actual template line.

I also checked a *second* HTML rendering source the lens statement
doesn't mention but which carries testids: the hand-rolled fallback
nav in `netcanon/api/routes/ui.py:543-552`.

**Half 2 — Are the tests adequately explained?** I parsed all 179
`test_*.py` modules with Python's `ast` to measure module / class /
function docstring coverage, flagged terse module docstrings, audited
all 4 `conftest.py` files for fixture rationale, surveyed every
`@pytest.mark.parametrize` for cryptic auto-generated IDs, and
sampled module docstrings across all four declared tiers (`unit`,
`integration`, `e2e`, `desktop`) plus the audit-harness tests. I
verified the marker table in `tests/README.md` and
`pyproject.toml` against actual marker usage, with specific
attention to the just-removed `slow` marker.

**Real-capture consistency.** I established filesystem ground truth
(`find` per vendor dir) and cross-tabulated the fixture counts and
certification claims across all five real-capture docs, plus a
per-fixture presence cross-tab for the six fixtures the docs-audit
flagged as a pending refresh.

I did **not** re-flag the three items the 2026-05-21 docs-audit
closed (the `slow` marker removal, the 10 stale `sched-device-*`
rows, the added `sanitize-safety-note`); I verified they landed and
looked for what remains.

---

## 2. Executive summary

**The test surface is in genuinely strong shape — among the best
I'd expect to see.** The headline numbers:

* **Test-ID drift is effectively zero in both directions.** Of 366
  distinct `data-testid` literals in `netcanon/templates/**`,
  normalizing to 364 testid families, **every shipped family has a
  matching row** in `tests/testid_reference.md`. The only doc rows
  with no template element are the six explicitly-labelled
  *RESERVED Phase 2* names (`testid_reference.md:676-696`), whose
  absence the doc itself predicts ("Searching ... will return zero
  hits — that is expected"). The Python fallback nav in `ui.py`
  introduces **zero** new testids — it is a strict subset of the
  documented set.
* **All 179 test modules carry a module docstring** (0 missing),
  and the sampled docstrings genuinely state the invariant guarded
  rather than restating the filename.
* **All four `conftest.py` files document every fixture with
  rationale**, including the *why* (e.g. the cross-platform keyring
  story at `tests/conftest.py:198-223`).
* The docs-audit's three claimed test-cluster fixes (Commit 16) all
  **landed cleanly and left no dangling references**.

The findings that remain are concentrated in the **real-capture
documentation cluster**, and they are mostly *staleness* and
*internal count contradictions*, not correctness defects:

* **DC-01 (medium):** `RESULTS.md` contains a self-contradiction —
  the Summary table says **17** total bugs surfaced; the prose two
  lines later says **"10 total bugs ... across all five"** codecs
  (it's now seven codecs, 17 bugs).
* **DC-02 (medium):** `CROSS_MESH_RESULTS.md` and
  `PHASE4_RECONCILIATION.md` are pinned to a pre-batch **39-real**
  fixture snapshot while `RESULTS.md`/`WANTED.md`/`NOTICE.md` reflect
  the current **45**. `RESULTS.md` discloses its own staleness;
  `CROSS_MESH_RESULTS.md` carries no such banner.
* The rest are low-severity: a dangling `@pytest.mark.slow` in an
  unshipped planning doc, a crossed `tests/README.md` directory
  description, a stale "kept because `test_results_md.py` imports
  it" comment citing a deleted file, and an under-inventoried
  orientation paragraph in the testid doc.

No HIGH-severity findings. Nothing here blocks anything; the cluster
is "finish the disclosed follow-up + reconcile two prose numbers."

---

## 3. Findings (severity-ordered)

### DC-01 — `RESULTS.md` self-contradicts on total bug count (10 vs 17) — **MEDIUM**

* **File:** `tests/fixtures/real/RESULTS.md:623` vs `:639`
* **Claim:** The same document reports two different totals for
  "bugs surfaced by the real-capture harness."
* **Evidence:**
  * `:623` — Summary table TOTAL row: `| **TOTAL** | **45** | — |
    **17** | — | — |`. The per-codec "Bugs surfaced" column sums
    exactly: cisco_iosxe_cli 1 + opnsense 2 + mikrotik 6 +
    fortigate 2 + aruba 2 + arista 3 + junos 1 = **17**. The table
    is internally correct.
  * `:639` — prose immediately below: "10 total bugs surfaced by the
    real-capture harness across all **five** codecs." Both the count
    (10) and the codec cardinality (five) are stale — the Summary
    table lists **seven** codecs.
  * Corroboration that "seven, 17" is the current truth: `:677-684`
    "Certification state (April 2026)" says "All **five** codecs are
    now certified" — *also* stale on cardinality; and `:705`
    "the lower-certainty codecs (none exist)" confirms all are
    certified, so the table's 7 rows are real.
* **Suggested direction:** Update `:639` to "17 total bugs surfaced
  ... across all seven codecs," and `:679` "All five codecs" →
  "All seven codecs." This is the v0.1.1-era "five codecs"
  vocabulary surviving past the arista/junos additions. (Note the
  prose at `:640-643` "Every one would have survived ... against our
  synthetic fixtures" is the valuable part and stays; only the
  arithmetic + cardinality need the bump.)

### DC-02 — `CROSS_MESH_RESULTS.md` (and `PHASE4_RECONCILIATION.md`) pinned to the 39-real snapshot, undisclosed — **MEDIUM**

* **File:** `tests/fixtures/real/CROSS_MESH_RESULTS.md:3`;
  `tests/fixtures/real/PHASE4_RECONCILIATION.md:3,5,7`
* **Claim:** Two of the five real-capture docs reflect a fixture
  corpus of **39 real fixtures**; the corpus is now **45**. The
  staleness is real and is *disclosed in `RESULTS.md`* but **not**
  in `CROSS_MESH_RESULTS.md` itself.
* **Evidence:**
  * Filesystem ground truth (count of parser-fixture files per
    `tests/fixtures/real/<vendor>/`): arista_eos 5, aruba_aoss 6,
    cisco_iosxe 13, fortigate 3, junos 7, mikrotik 4, opnsense 7 =
    **45 total**.
  * `CROSS_MESH_RESULTS.md:3` — "376 cells (**39 real** + 8 synthetic
    fixtures × 8 bidirectional targets)." Counting the real-matrix
    rows (`:22-60`): arista_eos **4**, aruba_aoss 6, cisco_iosxe
    **12**, fortigate 3, junos **5**, mikrotik 4, opnsense **5** =
    **39**. The six missing fixtures are exactly:
    `batfish_iosxe_basic_vrrp.txt`,
    `batfish_eos_evpn_vlan_based_leaf.txt`,
    `ksator_labmgmt_qfx5110_junos173.set`,
    `ksator_labmgmt_qfx10k2_junos173.set`,
    `opnsense_docs_carp_ha_master.xml`, and `_backup.xml` (presence
    cross-tab: 0 hits each in `CROSS_MESH_RESULTS.md`).
  * `PHASE4_RECONCILIATION.md:3` joins against the same
    `20260505T062803Z.json` Phase-1 run and "**56** per-pair Phase 3
    expectation YAMLs"; `:5` "Total cells reconciled: **376**." It is
    internally consistent *with `CROSS_MESH_RESULTS.md`* (both are
    the 39-real-era 2026-05-05 snapshot) — so the two generated docs
    agree with each other, just not with the current corpus.
  * **The disclosure asymmetry:** `RESULTS.md:625-637` carries an
    explicit "Note (2026-05-21 docs-audit)" stating the per-codec
    matrices are "pending a row-level refresh for 5 fixtures" and
    naming all six files + their commits, attributing it to
    docs-audit cluster **F3**. `CROSS_MESH_RESULTS.md` has the same
    39-vs-45 gap but no equivalent banner — a reader who lands there
    first sees stale numbers with no warning.
* **Suggested direction:** (a) Add a one-paragraph "stale snapshot —
  regenerate" banner to the top of `CROSS_MESH_RESULTS.md` mirroring
  the `RESULTS.md` note (these are *generated* files —
  `tools/run_full_mesh.py` / `tools/run_phase4_reconciliation.py` —
  so the proper close is to re-run the generators against the 45-fixture
  corpus and recommit). (b) The F3 follow-up is now one full audit
  cycle old; consider promoting "regenerate the mesh + reconciliation
  artifacts whenever a real fixture lands" into an `AGENTS.md`
  doc-sync row so it stops drifting. **Note:** this is partially
  self-disclosed pre-existing work, not a hidden error — scored
  MEDIUM only because of the undisclosed leg in `CROSS_MESH_RESULTS.md`.

### DC-03 — `RESULTS.md` per-codec matrices contradict their own Summary row counts — **LOW** *(disclosed)*

* **File:** `tests/fixtures/real/RESULTS.md` — opnsense matrix
  `:171-175`, arista matrix `:531-534`, junos matrix `:569-573`
  vs Summary `:617,621,622`
* **Claim:** Within a single file, three codecs carry two different
  fixture counts: the per-codec Coverage matrix (old) and the
  Summary table (new).
* **Evidence:**
  * opnsense per-codec matrix lists **5** fixtures (`:171-175`,
    missing both CARP HA files); the opnsense Summary row `:617`
    says **7**. (`opnsense_docs_carp_ha_backup` has **0** mentions
    anywhere in `RESULTS.md` except the F3 note.)
  * arista per-codec matrix lists **4** (`:531-534`), prose at `:525`
    + `:552` says "four real captures"; Summary `:621` says **5**.
  * junos per-codec matrix lists **5** (`:569-573`), prose at `:563`
    + `:597` says "five real captures"; Summary `:622` says **7**.
* **Status:** This is the same F3-deferred work as DC-02 and is
  **transparently disclosed** by the `:625-637` note ("the per-codec
  matrices land in a follow-up commit because the per-field cell
  counts need a parse pass to fill accurately rather than
  estimation"). I record it for completeness and to confirm F3 is
  genuinely still open, not as a new hidden defect. The minor wording
  bug worth fixing inside the note itself: `:632` says "5 fixtures"
  but enumerates **six** files (the opnsense pair is two files;
  39 → 45 is six fixtures).
* **Suggested direction:** Same as DC-02 — close F3 by running a
  parse pass and filling the three per-codec matrices, which
  resolves DC-02/DC-03 together. Fix "5 fixtures" → "6 fixtures" in
  the note.

### DC-04 — Dangling `@pytest.mark.slow` in NX-OS planning test-plan — **LOW**

* **File:** `docs/v0.2.0-planning/03-nxos-codec/04-test-plan.md:478`
* **Claim:** The just-removed `slow` marker is still referenced as a
  usable marker in a planning doc; under the project's
  `--strict-markers` setting it would fail.
* **Evidence:** The 2026-05-21 docs-audit (Commit 16, fix-plan
  `:245`) deleted the `slow` marker from `pyproject.toml` (the
  current marker list at `pyproject.toml:146-152` has only `unit`,
  `integration`, `e2e`, `desktop`, `cross_mesh`; `tests/README.md:121-127`
  matches). The chosen resolution was *delete*, not *wire*. But
  `04-test-plan.md:477-479` still presents, in a fenced code block,
  "For long-running cross-vendor round-trip tests:
  ````python\n@pytest.mark.slow\n```` " as the recommended pattern
  for future NX-OS tests. `pyproject.toml:154` sets
  `addopts = "... --strict-markers ..."`, so any test scaffolded from
  this snippet would error with "unknown marker" until `slow` is
  re-declared.
* **Severity rationale:** LOW — it lives in an aspirational,
  not-yet-shipped planning tree (`docs/v0.2.0-planning/03-nxos-codec/`),
  so no live test is affected today. But it's a genuine instance of
  the `slow`-removal sweep being incomplete, and it's a trap for the
  contributor who eventually builds the NX-OS codec from this plan.
* **Suggested direction:** Either change the snippet to
  `@pytest.mark.cross_mesh` (the surviving marker that already owns
  the "long-running cross-vendor" semantics, per `README.md:127`),
  or add a parenthetical "(declare the marker in `pyproject.toml`
  first — `slow` was removed in v0.1.2)".

### DC-05 — `tests/README.md` `tools/` vs `audit/` directory descriptions are crossed — **LOW**

* **File:** `tests/README.md:23-25`
* **Claim:** The Layout block's one-line descriptions of
  `tests/unit/tools/` and `tests/unit/audit/` don't match what the
  directories actually contain.
* **Evidence:**
  * `README.md:23` — "`tools/` ... Audit-harness scripts
    (`run_full_mesh`, `run_phase4_reconciliation`)"; `:25` —
    "`audit/` ... Reconciler-internal unit tests."
  * Actual `tests/unit/tools/`: `test_run_full_mesh_dict_drift.py`,
    `test_run_phase4_reconciliation_lag_rename.py`,
    `test_sanitize.py`.
  * Actual `tests/unit/audit/`: `test_run_full_mesh.py`,
    `test_run_phase4_reconciliation.py`.
  * So tests for `run_full_mesh` and `run_phase4_reconciliation`
    exist in **both** dirs; the clean "tools = harness scripts /
    audit = reconciler-internal" split the README implies doesn't
    hold, and `test_sanitize.py` (the most clearly "tool"-shaped
    test, for `tools/sanitize.py`) isn't reflected in the
    description at all.
* **Suggested direction:** Either rename one of the description
  lines to reflect the real split (e.g. `tools/` = "unit tests for
  `tools/*.py` including `sanitize.py` + drift/edge-case slices";
  `audit/` = "core reconciler building-block units
  (`compute_field_disposition`, `derive_variance`)"), or merge the
  two directories. Low priority; the descriptions are *roughly*
  right and no one is misled into a wrong file for long.

### DC-06 — Stale "kept because `test_results_md.py` imports it" comment in `test_real_captures.py` — **LOW**

* **File:** `tests/unit/migration/test_real_captures.py:100-106`
* **Claim:** A code comment justifies keeping a legacy alias by
  citing a test file that no longer exists.
* **Evidence:** `:100-103` — "Legacy alias — kept because
  ``test_results_md.py`` imports it by name. New code should use
  ``_codec_for_dir`` or the registry directly." Then `:104`
  defines `_VENDOR_TO_CODEC`. A repo-wide search finds **no file
  named `test_results_md.py`** anywhere under `tests/`, and
  `_VENDOR_TO_CODEC` is referenced **only inside
  `test_real_captures.py` itself** (`:137,200,256,298`). So the
  alias is *not* dead (it's used internally), but the stated reason
  for its existence is false — the external importer was deleted.
* **Suggested direction:** Update the comment to reflect reality:
  the alias is now used by the module's own discovery/parametrize
  paths, so either drop the "legacy" framing or note "still used by
  this module's discovery loop." Trivial, but it's exactly the class
  of comment that misleads a future cleanup ("safe to delete — the
  importer is gone" → breaks the parametrization).

### DC-07 — Testid doc's Tier-3-modal orientation paragraph under-inventories the partials — **LOW**

* **File:** `tests/testid_reference.md:556-566`
* **Claim:** The prose intro to the "Tier-3 rename modal" section
  names only four partials as the JS behind the modal, but the modal
  is driven by nine.
* **Evidence:** `:559-563` says the modal's JS "lives in two
  partials ... `_partials/rename-table.js` ... and
  `_partials/rename-panel.js` ... with `_partials/fit-check.js` ...
  and `_partials/classify.js`." The actual `_partials/` dir holds
  nine relevant JS files: the four named plus
  `vlan-rename-table.js`, `local-user-rename-table.js`,
  `snmp-rename-table.js`, `snmpv3-user-rename-table.js`, and
  `rename-apply.js` — and the per-category panes (VLAN / local-users
  / SNMP / SNMPv3) whose testids *are* fully documented in the tables
  below (`:633-674`) are rendered precisely by those un-named
  partials.
* **Severity rationale:** LOW and arguably cosmetic — every testid
  is still correctly documented in the tables; only the prose
  orientation sentence is incomplete, and it predates the
  per-category panes (P2C3–P2C6). It's a DE-adjacent "orientation
  header" nit on a DC-owned file.
* **Suggested direction:** Extend the sentence to list the
  per-category renderers, or soften to "...lives in several
  `_partials/*.js` files — `rename-table.js` + `rename-panel.js`
  drive ports; `vlan-/local-user-/snmp-/snmpv3-*-rename-table.js`
  drive their panes; `fit-check.js`, `classify.js`, and
  `rename-apply.js` are shared."

### DC-08 — `tests/README.md` desktop-conftest fixture list omits `mock_write_ico` — **LOW**

* **File:** `tests/README.md:46-48,116`
* **Claim:** The README lists three desktop fixtures; the conftest
  exports four.
* **Evidence:** `README.md:46-48` describes
  `tests/desktop/conftest.py` as providing "`mock_pyside6`,
  `mock_pystray`, `mock_generate_tray_image`", and `:116` repeats
  the trio. The actual conftest (`tests/desktop/conftest.py`) also
  defines and documents `mock_write_ico` (`:118-127`) plus the
  `_EventSlot` helper class (`:135-148`). The omitted fixture is a
  real, used fixture.
* **Suggested direction:** Add `mock_write_ico` to the two README
  mentions, or change "the ... fixtures" to "fixtures including ..."
  to avoid implying the list is exhaustive. Lowest priority — the
  conftest itself is well-documented; this is just the README
  summary lagging by one fixture.

---

## 4. Test-ID drift table

Numbers are *testid families* (dynamic suffixes such as `<source>`,
`-N`, `{category}` collapsed to one family on both sides), computed
with the three-construction extraction described in §1 and then
hand-verified.

| Metric | Count |
|---|---:|
| Distinct `data-testid` literals in `templates/**` | 366 |
| Template testid families (after normalization) | 364 |
| Doc table rows (raw, first column) | 412 |
| Doc rows that are real testids (minus 16 non-id rows) | 396 |
| Doc testid families | 396 |
| **Template-only families (template, not doc) — real drift** | **0** |
| **Doc-only families excl. RESERVED (doc, not template) — real drift** | **0** |
| Doc-only families that ARE the RESERVED Phase-2 block (expected) | 6 |

The 16 "non-id" doc rows excluded from the testid comparison are
correctly *not* testids and are properly labelled in the doc as
something else: the `data-testid` table-header literal; the four
per-device status SOP values (`queued`/`running`/`success`/`failed`,
`:179-184`); the seven tokenizer CSS classes (`tok-*`, `:224-232`,
explicitly "not `data-testid`s but useful for E2E assertions"); and
the four `netcanon:job-*` CustomEvent names (`:171-176`, an *Event*
column, not a testid). Excluding them is correct, not a finding.

### Template-only (testid in template, no doc row)

**None.** The first-pass diff surfaced three candidates; all three
are normalization artifacts, hand-verified as documented:

| Candidate | Template construction | Doc row | Verdict |
|---|---|---|---|
| `codec-caps-detail-list-<*>` | `definitions.html:813` literal `-supported` + `:828` `'-list-' + bucket` | `:308-310` enumerates all three buckets | documented (doc is more specific) |
| `migrate-tier3-section-<*>` | `migrate.html:1544` `'migrate-tier3-section-' + idx` | `:516` `migrate-tier3-section-N` | documented |
| `migrate-rename-snmp-community-row` | `_partials/snmp-rename-table.js:89` `setAttribute(...)` | `:659` | documented (my capture grabbed a trailing comma) |

### Doc-only (doc row, no template element)

**None beyond the explicitly-RESERVED block.** The six RESERVED
names (`testid_reference.md:689-696`) — `migrate-transforms-list`,
`migrate-add-transform-btn`, `migrate-semantic-delta-banner`,
`migrate-semantic-delta-item`, `migrate-deploy-btn`,
`migrate-confirm-deploy-btn` — return zero template hits, which the
doc states is expected and intentional (`:676-687`). This is correct
forward-declaration, not drift.

The large first-pass "doc-only" list (~28 names, e.g.
`migrate-rename-row-<source>`, `compare-option`,
`job-progress-device-row`, the VLAN/SNMP/SNMPv3/local-user row+drop+
override families) was **entirely** a false-positive cluster from
testids built via `setAttribute(...)` / ternary in the
`_partials/*.js` renderers rather than literal `data-testid="..."`.
Each was verified present, e.g. `_partials/rename-table.js:188,223,265`,
`configs.html:241`, `_partials/job-progress.js:64,82`,
`definitions.html:870`, `migrate.html:1388`.

### Second rendering source — `netcanon/api/routes/ui.py`

The hand-rolled fallback nav at `ui.py:543-552` carries 13 testids
(`nav`, `nav-brand`, `nav-home`, `nav-devices`, `nav-jobs`,
`nav-schedules`, `nav-configs`, `nav-definitions`, `nav-migrate`,
`nav-sanitize`, `nav-api-docs`, `nav-theme-toggle`,
`kbd-cheatsheet-open-btn`). Diffed against both templates and the
doc: **zero** testids unique to `ui.py`. The same nav identifiers are
duplicated across `base.html:349-371` and `ui.py`, and both stay
consistent with the doc — a small robustness win rather than a
finding.

---

## 5. Test-explanation assessment (per-tier sample with verdicts)

Mechanical baseline across all 179 `test_*.py`:

| Metric | Value |
|---|---|
| Modules with a module docstring | **179 / 179 (100%)** |
| Module docstrings under 40 chars (too terse to state an invariant) | 0 |
| `test_*` functions with a docstring | 1370 / 3331 (41%) |
| `Test*` classes with a docstring | 268 / 674 (39%) |

The 41% / 39% function/class figures are **not** a concern: in the
sampled modules the undocumented functions have self-describing names
(e.g. `test_returns_200`, `test_includes_mock_adapter`,
`test_multiple_users_no_line_bleed`) and live under a class or module
docstring that frames the group. The discipline in this repo is
"docstring the module and the non-obvious case; let descriptive names
carry the obvious ones," and it's applied consistently.

| Tier | Sampled module | Verdict | Evidence |
|---|---|---|---|
| Root conftest | `tests/conftest.py` | **Exemplary** | Every fixture documented; `_mock_keyring` (`:198-223`) explains the Ubuntu-CI `NoKeyringError` rationale and the `_fernet` cache reset — the kind of *why* that prevents a future contributor from "simplifying" the fixture into a bug. |
| unit (codec) | `tests/unit/migration/test_real_captures.py` | **Exemplary** | Module docstring (`:1-38`) is structured Purpose / "What's asserted (hard gate)" / "What's reported (soft)"; `_DIR_TO_CODEC_NAME` (`:71-88`) and the empty `_KNOWN_UNSUPPORTED`/`_KNOWN_ROUNDTRIP_GAPS` whitelists (`:112-124`) are documented inline with the "fails loud if you forget" guard contract. (Carries DC-06's one stale comment.) |
| unit (definitions) | `tests/unit/definitions/test_arista_eos_definition.py` | **Good, one nit** | Functions explain contractual intent (`:208-209`, `:231-232`). Nit folded into §9 OQ-1: the `:214-221` parametrize over `(sample, ...)` where `sample` is a multi-line `show version` string yields an opaque auto-ID; an `ids=` over the model name would read better. |
| unit (audit harness) | `tests/unit/audit/test_run_full_mesh.py`, `test_run_phase4_reconciliation.py` | **Exemplary** | Both docstrings (`:1-9`, `:1-12`) state precisely what they pin and *why* — "pin the building blocks ... so a regression in `compute_field_disposition` fails loud rather than silently mis-classifying every cell in the next audit pass." Textbook invariant-statement. |
| integration | `tests/integration/conftest.py`, `test_migration_api.py` | **Exemplary** | Conftest (`:1-11`) documents the BackgroundTasks-runs-synchronously behaviour that makes polling unnecessary (matches a known footgun in my memory notes); `client` fixture (`:22-41`) names the exact patch target + why context-manager form is used. Module docstring (`:1-8`) lists routes covered. |
| e2e | `tests/e2e/conftest.py`, `test_migrate_rename_modal.py` | **Exemplary** | Conftest carries an "Architecture" + "Running E2E tests" section (`:1-27`); the rename-modal module docstring (`:1-12`) enumerates the five behaviours under test (visibility gating, per-kind sections, live preview, collision-disables-Apply, Apply re-renders). |
| desktop | `tests/desktop/conftest.py`, `test_app.py` | **Exemplary** | `mock_pyside6` (`:24-35`) explains the `sys.modules` injection trick and lists the namespace it yields; `mock_write_ico` (`:118-127`) explains why the patch target is the module not the call site. (README lags by one fixture — DC-08.) |

**Parametrize IDs.** Across 24 files using `@pytest.mark.parametrize`
there are **8 real `ids=` usages**, and they are exactly where
opaque parameter objects would otherwise produce cryptic
auto-IDs: `test_cisco_iosxe.py:337` (`ids=["min","with-subinterface"]`
over config-text constants), `test_cross_codec_matrix.py:68,139`
(`ids=[_pair_id(s,t) ...]`), `test_real_captures.py:193,248,280` and
`test_synthetic_kitchen_sink_round_trips.py:152,188,222`
(`ids=[_param_id(p) ...]` over `Path` objects). Every *other*
parametrize set iterates over readable string/enum literals
(`"arista_eos"`, `"dhcp6"`, `("gre ip","gre")`, `("nav-home","/")`)
that pytest auto-renders into legible IDs (`[arista_eos]`,
`[gre ip-gre]`). **Cryptic parametrize IDs are not a problem in this
suite** — the single readability nit is OQ-1 (the arista-definition
`show version` tuple).

**Markers.** `pyproject.toml:146-152` and `tests/README.md:121-127`
agree exactly: `unit`, `integration`, `e2e`, `desktop`, `cross_mesh`.
The `slow` marker is gone from both, confirming Commit 16 landed. The
only surviving `slow`-as-marker reference is the dangling planning-doc
snippet (DC-04); all other "slow" hits are legitimate prose ("slow
devices", "slow to respond") or historical audit-dossier text.
`cross_mesh` carries a real runtime budget note ("under 30s") in both
places — consistent.

**Commit-16 cleanup verification.** The removed `sched-device-*`
inline-list testids appear **only** in the testid_reference removal
note (`testid_reference.md:350-357`) and in **zero** test files —
no dangling E2E selector references. `sanitize-safety-note` is
present in both the doc (`:719`) and the template
(`sanitize.html:64`). Clean.

---

## 6. Real-capture doc consistency check

Filesystem ground truth and the five docs cross-tabulated. **Counts**
agree across the three "current" docs (`NOTICE.md`, `RESULTS.md`
Summary, `WANTED.md`) and the filesystem; the two "generated
snapshot" docs lag (DC-02).

| Codec | Filesystem | NOTICE.md rows | WANTED.md snapshot (`:21-27`) | RESULTS.md Summary (`:616-622`) | RESULTS.md per-codec matrix | CROSS_MESH real-matrix rows |
|---|---:|---:|---:|---:|---:|---:|
| cisco_iosxe | 13 | 13 | 13 | 13 | 12 *(F3 note)* | **12** |
| arista_eos | 5 | 5 | 5 | 5 | 4 | **4** |
| aruba_aoss | 6 | 6 | 6 | 6 | 6 | 6 |
| fortigate | 3 | 3 | 3 | 3 | 3 | 3 |
| junos | 7 | 7 | 7 | 7 | 5 | **5** |
| mikrotik | 4 | 4 | 4 | 4 | 4 | 4 |
| opnsense | 7 | 7 | 7 | 7 | 5 | **5** |
| **TOTAL** | **45** | **45** | — | **45** | — | **39** |

Observations:

1. **`NOTICE.md` is perfect** — exactly 45 provenance rows, one per
   filesystem fixture, correct per-vendor distribution. The "Adding
   new captures" contract (`:99-107`) correctly describes the
   auto-discovery harness (`test_real_captures.py` picks up
   `*.txt/.cfg/.xml/.conf/.rsc/.set` automatically).
2. **`WANTED.md` snapshot is current** (45) and its OS-version
   coverage strings line up with `RESULTS.md` Summary (e.g. junos
   "15.1 / 17.3 / 18.4 / 25.4"; arista "4.21 / 4.22 / 4.23 / 4.26").
   It is a *gap* doc, so it deliberately doesn't name every fixture
   — not naming `ksator_labmgmt_qfx5110` or the CARP files in prose
   is correct, since its count table already reflects them.
3. **`RESULTS.md` is consistent with itself only via its disclosure
   note.** Summary = 45 (current); per-codec matrices = 39-era
   (arista 4, junos 5, opnsense 5); the `:625-637` note bridges the
   gap and is honest about why (F3 deferred, needs a parse pass).
   The internal `10 vs 17` bug-count contradiction (DC-01) is the
   one *un*-disclosed inconsistency in this file.
4. **`CROSS_MESH_RESULTS.md` + `PHASE4_RECONCILIATION.md` are a
   matched pair** at the 2026-05-05 / 39-real snapshot. They agree
   with *each other* (same run JSON, same 376 cells, same 56 pair
   YAMLs) — a good sign they were generated together — but they lag
   the corpus by six fixtures and (for CROSS_MESH) carry no staleness
   banner (DC-02).
5. **Certification states agree.** All five count-bearing docs that
   mention certification say every codec is `certified`
   (`RESULTS.md:616-622` ✅ per row, `:677-684`; `WANTED.md:144-149`
   "Shipped in v0.2.0"). No doc claims a codec is certified while
   another calls it best_effort. `PHASE4_RECONCILIATION.md:13-23`
   reports **0 CODEC_BUG** cells ("every drifted field aligned with
   a documented expectation") — consistent with all-certified.
6. **Per-fixture presence cross-tab** (the six pending fixtures):
   `CROSS_MESH_RESULTS.md` has 0/6; `RESULTS.md` has 5/6 (only the
   docs-audit note, not matrix rows) and notably **0** for
   `opnsense_docs_carp_ha_backup` — the master CARP fixture is named
   in the note but the backup one isn't named anywhere in
   `RESULTS.md`. Folded into DC-03.

Net: the real-capture documentation is **internally honest** (the
one file with stale numbers says so) but has **one undisclosed prose
contradiction** (DC-01) and **one undisclosed stale snapshot**
(DC-02 / `CROSS_MESH_RESULTS.md`), plus the disclosed-but-still-open
F3 follow-up (DC-03).

---

## 7. What's GOOD

* **Zero-drift testid inventory in both directions.** This is hard
  to achieve and harder to maintain across 364 testids and two
  rendering sources (templates + `ui.py` fallback). The discipline
  holds even for dynamically-constructed testids in nine JS partials.
* **The RESERVED Phase-2 pattern** (`testid_reference.md:676-696`) is
  exactly right: forward-declared selector names with an explicit
  "these return zero hits today, that's expected" warning so the
  doc-only diff doesn't false-positive and Phase-2 lands with stable
  names. This is the correct way to pre-register names.
* **100% module-docstring coverage** with genuine invariant
  statements, not filename echoes. The audit-harness tests
  (`tests/unit/audit/`) and `test_real_captures.py` are model
  examples of "say what breaks if this regresses."
* **All four conftests document the *why*, not just the *what*** —
  the keyring cross-platform story, the BackgroundTasks-synchronous
  note, the `sys.modules` PySide6 injection, the session-scoped live
  server. These are precisely the fixtures where an undocumented
  mechanism would cost a future contributor hours.
* **`NOTICE.md` provenance discipline is impeccable** — 45 fixtures,
  each with origin URL, license, sanitization notes, and a
  feature-coverage description. The sanitization disclosures
  (synthetic-marked hashes, OUI-preserving MAC rewrites, RFC-5737
  WAN-IP substitutions) are detailed enough to audit.
* **`RESULTS.md` self-discloses its own staleness** (`:625-637`)
  rather than silently shipping wrong per-codec numbers. The
  honesty here is the difference between DC-03 being LOW vs MEDIUM.
* **The docs-audit Commit-16 cleanup landed cleanly** — `slow`
  marker gone everywhere it mattered, `sched-device-*` rows removed
  with a tombstone note and no dangling test references,
  `sanitize-safety-note` added and matching the template.
* **`tests/README.md` and `testid_reference.md` both carry "See
  also" sections** wiring the test docs into the broader graph
  (`README.md:129-139`, `testid_reference.md:756-761`) — good
  interlinking hygiene (DB's lens, but worth noting it supports the
  DC surface).

---

## 8. Coverage table

| Area | Coverage | Notes |
|---|---|---|
| `data-testid` enumeration (templates) | Full | 3-construction extraction (literal + setAttribute + ternary/concat), 366 literals → 364 families |
| Second rendering source (`ui.py` fallback nav) | Full | 13 testids, 0 unique — strict subset of doc |
| `testid_reference.md` row inventory | Full | 412 rows parsed; 396 real testids + 16 correctly-non-id rows |
| Bidirectional drift | Full | Both directions = 0 (excl. 6 RESERVED) |
| `pyproject.toml` / README marker tables | Full | Agree; `slow` confirmed removed |
| `slow` marker dangling-reference sweep | Full | One residual in NX-OS planning doc (DC-04) |
| Module-docstring presence (all tiers) | Full (AST, 179 files) | 100% |
| Function/class docstring rate | Full (AST) | 41% / 39% — adequate given naming discipline |
| conftest fixture documentation | Full (all 4) | Exemplary |
| Parametrize ID readability | Full (24 files) | 8 `ids=` where needed; 1 nit (OQ-1) |
| Module-docstring *quality* | Sampled (7 tiers/modules) | All "good" or "exemplary" |
| Real-capture count consistency | Full cross-tab (5 docs + filesystem) | DC-01, DC-02, DC-03 |
| Real-capture certification consistency | Full | Agree (all certified) |
| Per-fixture presence cross-tab | Full (6 pending fixtures × 4 docs) | Confirms F3 open |
| Per-cell *values* in CROSS_MESH / phase4 matrices | Not verified | Out of scope — would require running `tools/run_full_mesh.py`; treated as generated artifact per snapshot guidance |
| `phase4_findings_*.md` + `user_smoke_findings.md` + `phase4_spawn_tasks.md` contents | Not deep-read | Listed in scope's "test-doc surfaces" loosely; spot-checked existence + that `PHASE4_RECONCILIATION.md:46-48` correctly points to them. Per-finding accuracy is a codec-correctness concern (Fleet C), not test-doc consistency |

---

## 9. Open questions

* **OQ-1 (readability nit, near-finding):**
  `tests/unit/definitions/test_arista_eos_definition.py:214-221`
  parametrizes over `(_SHOW_VERSION_DCS_7050, "4.32",
  "DCS-7050SX-64-F")` tuples whose first element is a multi-line
  `show version` blob, with no `ids=`. pytest will auto-generate an
  opaque/truncated ID from that blob. An `ids=[m for _,_,m in cases]`
  (model name) would make `-k` selection and failure output
  readable. Too small to be a standalone finding; flagging for the
  remediation pass. *(Same authors clearly know the pattern — they
  use `ids=` correctly in `test_cisco_iosxe.py:337`.)*

* **OQ-2:** Is there any test that *guards* the doc surfaces I
  audited — i.e. a test that fails if `RESULTS.md`'s counts drift
  from the filesystem, or if a template testid lacks a doc row?
  Searching found `test_real_captures.py` discovers fixtures from
  the filesystem (so a *missing* NOTICE row wouldn't fail a test —
  the harness keys off the dir, not the doc), and the
  `test_results_md.py` once referenced (DC-06) is gone. If no such
  guard exists, DC-01/DC-02/DC-03 are the *expected* failure mode of
  hand-maintained snapshots — a `tools/`-level "regenerate +
  diff-check in CI" guard would convert this whole cluster from
  "periodically drifts" to "can't drift." Worth a design note. (This
  is a *suggestion*, not a finding — UNVERIFIED whether the
  maintainers want CI coupled to generated snapshots.)

* **OQ-3 (UNVERIFIED):** `CROSS_MESH_RESULTS.md:5` says "Until then,
  treat every WARN cell as 'unverified'" and references
  `tests/fixtures/cross_vendor_expectations.yaml (planned)`. The
  actual path is the *directory*
  `tests/fixtures/cross_vendor_expectations/` (56 pair YAMLs, per
  `PHASE4_RECONCILIATION.md:54`), and Phase 3/4 are clearly *done*
  (PHASE4_RECONCILIATION.md exists and reports 0 CODEC_BUG). So
  CROSS_MESH's "Phase 3 ... will add" future-tense framing at
  `:5` and the "(planned)" annotation are themselves stale — they
  describe Phase 3 as upcoming when it has shipped. This reinforces
  DC-02 (the whole file is a pre-Phase-3 snapshot). I did not file it
  separately because it's the same regenerate-the-file fix; noting it
  so the remediation captures the future-tense prose too.

---

### Appendix — commands used (reproducibility)

* Testid extraction + bidirectional diff: a `py` script reading
  `netcanon/templates/**` for `data-testid="..."`,
  `setAttribute('data-testid', ...)`, and ternary forms; normalizing
  dynamic suffixes to `<*>`; diffing against first-column backtick
  tokens in `tests/testid_reference.md`.
* Module-docstring coverage: `ast.get_docstring` over all
  `tests/{unit,integration,e2e,desktop}/**/test_*.py`.
* Real-capture ground truth: `find tests/fixtures/real/<vendor>/`
  filtered to `*.txt|*.cfg|*.conf|*.xml|*.set|*.rsc|*.boot`.
* Per-fixture cross-tab: `grep -c <fixture>` over the five docs.
* `py`, not `python` (Windows Store-shim avoidance per maintainer
  environment note).

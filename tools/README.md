# tools/

Operator-facing scripts that aren't part of the FastAPI app or the test
suite.  Standalone executables — invoke directly with `python tools/<name>.py`
from the repo root.

## Scripts overview

| Script | Purpose |
|---|---|
| `run_full_mesh.py` | Cross-mesh translation fidelity audit — every fixture × every bidirectional codec.  Emits a per-cell JSON record + (with `--matrix`) the human-readable `CROSS_MESH_RESULTS.md`. |
| `run_phase4_reconciliation.py` | Phase 4 8-class variance taxonomy reconciliation.  Consumes the run_full_mesh JSON, classifies each variance, emits `PHASE4_RECONCILIATION.md`.  See `docs/HOW_WE_TEST.md` for the variance-class taxonomy. |
| `demo.py` | Operator-facing scenario runner — translates 4 pre-bundled synthetic configs (Cisco↔Junos, FortiGate↔MikroTik, Aruba↔Arista, OPNsense↔Junos) so the `docker run … python tools/demo.py …` quickstart shows real translation output without operator-supplied input.  Paired 1:1 with `docs/walkthroughs/<source>_to_<target>.md`. |
| `load_cross_vendor_expectations.py` | Phase 3 lint utility — loads every YAML under `tests/fixtures/cross_vendor_expectations/` and validates against the Pydantic expectation schema.  Used as a pre-commit guard to catch malformed expectation files before they break the cross-mesh audit. |

Detailed sections below cover the primary cross-mesh tooling.

## `run_full_mesh.py` — cross-mesh translation fidelity audit

Walks every committed fixture (real-world captures under
`tests/fixtures/real/<vendor>/` AND hand-authored synthetic
kitchen-sinks under `tests/fixtures/synthetic/<codec_name>/`) and
runs every bidirectional codec in the registry against it as a
translation target.  For each `(fixture, target_codec)` cell it
performs:

```
canonical_source = source_codec.parse(fixture_text)
rendered         = target_codec.render(canonical_source)
canonical_target = target_codec.parse(rendered)
```

then compares `canonical_source` and `canonical_target` field-by-field
on the top-level :class:`CanonicalIntent` shape.  Drift is recorded in
a per-cell JSON record with the source/target values for every field
that didn't round-trip cleanly.

### Usage

```sh
# Run the audit; emit JSON only.  Fast (well under a minute on the
# current corpus).  The script prints the path to the new JSON file
# on stdout; progress messages go to stderr.
python tools/run_full_mesh.py

# Run the audit AND regenerate the human-readable matrix:
python tools/run_full_mesh.py --matrix
```

### Output structure

* **JSON (always written):**
  `tests/fixtures/real/_cross_mesh_runs/<UTC-timestamp>.json` — one
  record per cell with full per-field drift detail.  Each cell carries
  `fixture_kind: "real"` or `fixture_kind: "synthetic"` so downstream
  tooling can group them.  This directory is gitignored; per-run
  output is operator scratch space.
* **Matrix markdown (`--matrix` only):**
  `tests/fixtures/real/CROSS_MESH_RESULTS.md` — operator-readable
  matrix overwritten on each invocation.  This file IS committed; the
  operator commits the regenerated version manually.  The markdown
  carries TWO matrices (real + synthetic) with separate drill-downs
  for each — see "Real vs synthetic fixtures" below.

### Cell statuses

The matrix uses five status codes per cell:

| Status   | Meaning                                                                |
|----------|------------------------------------------------------------------------|
| `OK`     | Every field preserved (or unsupported-by-design on the target).        |
| `WARN`   | Render succeeded but at least one field drifted that the target does NOT declare unsupported.  Either a codec defect OR an expected vendor-feature mismatch (Phase 3 disambiguates). |
| `RENDER` | `target_codec.render()` raised — codec bug.                            |
| `PARSE`  | `target_codec.render()` succeeded but the round-trip parse failed — render emitted invalid syntax (codec bug). |
| `SOURCE` | The source codec couldn't even parse its own fixture (parser regression on `tests/fixtures/real/`). |

The `N/M` count after `OK`/`WARN` shows how many top-level canonical
fields were preserved or unsupported-by-design out of the audited total.

### What this is + isn't

This is a **mechanical drift audit**.  It tells you which fields
survived a parse-render-parse trip; it does NOT yet interpret which
drift is expected.  Phase 3 of the audit adds a vendor-doc-grounded
expectations file (`tests/fixtures/cross_vendor_expectations.yaml`,
planned) that classifies each drift as expected-vs-defect.  Until
then, treat every WARN cell as "unverified" rather than "broken".

### Real vs synthetic fixtures

Two fixture corpora feed the matrix:

* **Real captures** (`tests/fixtures/real/<vendor>/<file>`) — configs
  drawn from carriers, Batfish parser tests, and vendor-published
  examples.  Each row reflects whatever feature slice the original
  operator chose to deploy.  Feature absence in a row doesn't mean the
  codec can't handle it — just that the fixture doesn't exercise it.
* **Synthetic kitchen-sinks** (`tests/fixtures/synthetic/<codec>/kitchen_sink.<ext>`) —
  one hand-authored fixture per codec exercising every field the
  codec's `CapabilityMatrix` declares as `supported` or `lossy`.
  Drift here is the worst-case feature-complete signal — every
  supported field is present at once, so a WARN cell unambiguously
  means the target lost something the source could express.

The markdown matrix renders both corpora as separate sections with
separate drill-downs.  Real and synthetic are kept apart because
mixing them conflates "feature absent in source" with "feature
dropped in translation".

### Adding a new fixture or target codec

* New fixture file under `tests/fixtures/real/<vendor>/` — picks up
  automatically on the next run; no script change needed.
* New real-fixture vendor directory — add a `<dir> → <codec_name>`
  row to `_DIR_TO_CODEC_NAME` in this script (mirrors the test-harness
  mapping in `tests/unit/migration/test_real_captures.py`).  The
  script reports unmapped directories explicitly in the JSON's
  `unmapped_fixture_dirs` field rather than silently dropping them.
* New synthetic kitchen-sink — drop the file at
  `tests/fixtures/synthetic/<codec_name>/kitchen_sink.<ext>` (the
  parent directory name must match the registered `CodecBase.name`
  exactly).  No script change needed — discovery uses the directory
  name as the codec name directly.
* New target codec — registers automatically via the existing
  `@register` decorator at codec import time.  The script filters to
  `direction == "bidirectional"` so parse-only codecs are skipped.

### Phase 1 vs later phases

* **Phase 1 (this script):** mechanical drift matrix.
* **Phase 2:** drift trend tracking — diff the latest matrix vs the
  previous committed one to highlight regressions.
* **Phase 3:** vendor-doc-grounded expectations YAML; enrich the
  matrix to call out expected-vs-defect drift.
* **Phase 4:** automated codec-defect ticket creation from the
  expected-vs-defect classification.

See `translator-plans.txt` "CROSS-MESH FIDELITY AUDIT" entry for the
roadmap.

### See also

* `tests/fixtures/real/RESULTS.md` — per-codec real-capture parse
  coverage (different axis: source-side parse fidelity, not
  target-side translation fidelity).
* `tests/fixtures/real/NOTICE.md` — provenance + attribution for
  every committed real-capture fixture.
* `tests/unit/audit/test_run_full_mesh.py` — unit tests pinning the
  drift-computation building blocks.

## `run_phase4_reconciliation.py` — Phase 4a reconciliation

Joins the Phase 1 mechanical drift JSON
(`tests/fixtures/real/_cross_mesh_runs/<timestamp>.json`) with the
Phase 3 vendor-doc-grounded expectation YAMLs
(`tests/fixtures/cross_vendor_expectations/<src>__<tgt>.yaml`) to
produce a per-cell variance classification.  Each canonical field's
**actual** disposition (preserved vs drifted, from Phase 1) is
reconciled against its **expected** disposition (good / lossy /
unsupported / not_applicable, from Phase 3) and bucketed into one of:

| Variance class            | Meaning                                                       | Severity |
|---------------------------|---------------------------------------------------------------|----------|
| `ALIGNED`                 | preserved + expected good                                     | ok       |
| `EXPECTED_LOSSY`          | drifted + expected lossy (matches docs)                       | ok       |
| `EXPECTED_UNSUPPORTED`    | drifted + expected unsupported (matches docs)                 | ok       |
| `TRIVIAL_EMPTY`           | drift only because one side held `[]` / `{}` / `""` and the other held `None`; no semantic divergence | ok |
| `METHODOLOGY_ISSUE_under` | preserved against {lossy/unsupported/N-A} expectation         | low/medium |
| `METHODOLOGY_ISSUE_over`  | drifted against `not_applicable` expectation                  | low      |
| `CODEC_BUG`               | drifted + expected good (the docs/code disagreement to fix)   | **high** |

### Usage

```sh
# Reconcile against the most recent Phase 1 run.
python tools/run_phase4_reconciliation.py

# Pin a specific Phase 1 JSON (e.g. a known-good baseline).
python tools/run_phase4_reconciliation.py --mesh-json \
    tests/fixtures/real/_cross_mesh_runs/<timestamp>.json
```

### Output structure

* **JSON archive (gitignored):**
  `tests/fixtures/real/_phase4_runs/<UTC-timestamp>.json` — one
  record per cell with full per-field variance breakdown.
* **JSON snapshot (committed):**
  `tests/fixtures/real/_phase4_runs/latest.json` — stable mirror
  overwritten on every run.  Phase 4b investigation agents read this
  to surface CODEC_BUG findings per source vendor without the operator
  having to track timestamped names.
* **Skeleton report (committed, overwritten on every run):**
  `tests/fixtures/real/PHASE4_RECONCILIATION.md` — aggregate
  variance counts, per-(source × target) CODEC_BUG matrix, top-N
  pairs by CODEC_BUG count, and a placeholder for per-vendor
  findings reports.

### Phase 4a vs Phase 4b

* **Phase 4a (this script):** mechanical reconciliation — produces the
  variance JSON and skeleton report.  No subjective judgement.
* **Phase 4b (separate investigation agents):** read the per-run JSON,
  triage each CODEC_BUG finding for an assigned source vendor, and
  produce a per-vendor findings report at
  `tests/fixtures/real/phase4_findings_<source_vendor>.md`.

---

## See also

- [`../tests/fixtures/real/RESULTS.md`](../tests/fixtures/real/RESULTS.md) — per-codec real-capture parse certification state
- [`../tests/fixtures/real/CROSS_MESH_RESULTS.md`](../tests/fixtures/real/CROSS_MESH_RESULTS.md) — Phase 1 mechanical drift matrix produced by `run_full_mesh.py`
- [`../tests/fixtures/real/PHASE4_RECONCILIATION.md`](../tests/fixtures/real/PHASE4_RECONCILIATION.md) — Phase 4a reconciliation skeleton produced by `run_phase4_reconciliation.py`
- [`../docs/glossary.md`](../docs/glossary.md) — variance-class vocabulary (ALIGNED, CODEC_BUG, TRIVIAL_EMPTY, etc.)

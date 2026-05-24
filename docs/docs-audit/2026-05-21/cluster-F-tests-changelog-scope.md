# Cluster F — Tests, fixture provenance + CHANGELOG accuracy

## Scope

Test-layer documentation + project history accuracy.

### In scope

* `tests/README.md` — test-suite layout + mocking strategy
* `tests/testid_reference.md` — `data-testid` enumeration for UI
  tests
* `tests/fixtures/real/NOTICE.md` — fixture provenance + license
  attribution
* `tests/fixtures/real/RESULTS.md` — coverage matrix per codec
  (`certified` / `best_effort` / etc.)
* `tests/fixtures/real/WANTED.md` — operator-facing gap list
* `tests/fixtures/real/BUG_REPORTING.md` (if exists) — fixture
  submission flow from test-side
* All `tests/.../README.md` sub-READMEs (if any)
* `pyproject.toml` — `[tool.pytest.ini_options]` markers + their
  alignment with conftest usage
* `tests/conftest.py` (root) + key sub-conftest files —
  fixture/marker definitions
* `tests/unit/migration/test_real_captures.py` — specifically the
  `_DIR_TO_CODEC_NAME` mapping (cited in AGENTS.md doc-sync as
  load-bearing)
* `CHANGELOG.md` — verify entries match actual git history
* `tests/fixtures/module_variants.py` — module-variant allowlist
  cited in AGENTS.md doc-sync

### Out of scope

* Actual test code (this is a docs audit, not a test audit)
* Codec docstrings (Cluster D)
* Platform docstrings (Cluster E)

## What to verify

1. **`tests/README.md` accuracy.**  Test-suite layout described
   should match actual directory structure.  Mocking strategy
   description should match what `conftest.py` does.

2. **`testid_reference.md` coverage.**  Per AGENTS.md doc-sync row:
   > A new interactive HTML element (button, input, link, row,
   > <select>, <option> inside a form) | tests/testid_reference.md
   > — document the new data-testid in the appropriate page section.
   Walk every `data-testid="..."` in `netcanon/templates/`.  Verify
   each is documented in `testid_reference.md` under the right
   page section.  Surface MISSING entries.  Surface entries in
   `testid_reference.md` that no longer exist in templates (WRONG).

3. **`NOTICE.md` provenance integrity.**  Walk every fixture under
   `tests/fixtures/real/<vendor>/`.  Verify each has a row in
   NOTICE.md with (provenance, license, commit SHA where
   applicable).  Surface MISSING rows.  Surface NOTICE.md entries
   for fixtures that no longer exist.

4. **`RESULTS.md` coverage matrix.**  Per AGENTS.md doc-sync row:
   > A codec is promoted to `best_effort` or `certified` |
   > tests/fixtures/real/RESULTS.md — update the coverage matrix
   > and certification decision.
   Verify the matrix lists every codec with the right certification
   state.  Cross-check vs codec count in `00-snapshot.md`.

5. **`WANTED.md` gap-list freshness.**  Verify items marked
   "shipped" / "closed" actually have a corresponding NOTICE.md
   fixture row.  Surface stale "wanted" items that have actually
   landed.

6. **`pyproject.toml` marker definitions.**  Per AGENTS.md:
   > A new pytest marker in `pyproject.toml` (`[tool.pytest.ini_options]
   > markers = [...]`) or a new conftest fixture that meaningfully
   > changes how a whole test tier runs | tests/README.md — the
   > markers table and/or the "How to run" section.
   Verify each declared marker in pyproject.toml is documented in
   `tests/README.md`.  Surface MISSING entries.  Surface unused
   markers (defined but no `@pytest.mark.<x>` usage anywhere).

7. **`_DIR_TO_CODEC_NAME` mapping completeness.**  Open
   `tests/unit/migration/test_real_captures.py` at line ~80.
   Verify every subdir of `tests/fixtures/real/` (with at least
   one fixture file) has a row in `_DIR_TO_CODEC_NAME`.  Surface
   MISSING rows.

8. **`module_variants.py` allowlist coverage.**  Per AGENTS.md
   doc-sync:
   > A target-profile gains `modules:` (migrates to module-variant
   > shape) | Add its `{vendor}/{model}` key to the canonical
   > allowlist at `tests/fixtures/module_variants.py`.
   Walk `definitions/target_profiles/*.yaml`.  For any profile
   declaring `modules:`, verify the corresponding allowlist entry
   exists.

9. **`CHANGELOG.md` git-history accuracy.**  For each release
   entry (`## [0.1.x] - YYYY-MM-DD`):
   * Verify the date matches the actual tag date.
   * Verify cited commit SHAs resolve (`git show <sha>`).
   * Verify the cited changes match the actual diff between this
     tag and the prior.
   * Caveat: per CHANGELOG.md's "Note on pre-launch commit SHAs",
     entries before the Phase 1 filter-repo rewrite may have
     stale SHAs — those don't need verification.

10. **Cross-references from CHANGELOG.md.**  Linked file paths
    should all resolve.  Linked commit SHAs should resolve (modulo
    the Phase 1 caveat).

## Methodology

* `Read` each in-scope doc.
* `Grep` for `data-testid="..."` across `netcanon/templates/` to
  build the source-of-truth set.
* `Bash` (`git tag --format='%(refname:short) %(taggerdate:iso8601)'`)
  to verify CHANGELOG dates.
* `Bash` (`git show <sha>` per cited SHA) to verify commit refs.
* `find tests/fixtures/real -mindepth 2 -maxdepth 2 | sort | uniq`
  to enumerate fixture directories.

## Severity tagging

| Severity | Examples |
|---|---|
| **WRONG** | NOTICE.md cites a fixture file that doesn't exist; CHANGELOG cites a non-existent SHA (modulo pre-launch caveat); testid_reference.md documents a testid that isn't in any template |
| **MISSING** | A fixture exists but no NOTICE row; a data-testid exists in templates but not in testid_reference; a pytest marker is declared but no test uses it |
| **INCOMPLETE** | NOTICE row exists but missing license/provenance fields; RESULTS matrix has the codec but missing the certification column |
| **STYLE** | CHANGELOG format drift; inconsistent date format |

## Output format

Write to: `docs/docs-audit/2026-05-21/01-investigation-F.md`

```markdown
# Cluster F — Tests, fixture provenance + CHANGELOG accuracy

## Summary

## Tests/README.md audit

## testid_reference.md audit
* Templates scanned: ...
* testids in templates: ...
* testids documented: ...
* Findings:

## fixtures/real/NOTICE.md audit
* Fixture files scanned: ...
* Rows in NOTICE: ...
* Per-vendor missing-row counts: ...

## fixtures/real/RESULTS.md audit

## fixtures/real/WANTED.md audit

## pyproject.toml markers audit

## _DIR_TO_CODEC_NAME mapping audit

## module_variants.py allowlist audit

## CHANGELOG.md accuracy audit
* Releases checked: 0.1.0-rc* + 0.1.1 + 0.1.2
* Date verification: ...
* SHA resolution: ...
* Diff-vs-claim verification: ...

## Cross-cutting observations
```

## Constraints

* **READ-ONLY.**  Single output file.
* Hard rules from `AGENTS.md`.
* Time budget: ~30-45 min.  Mechanical cross-checks dominate;
  CHANGELOG diff-vs-claim is the deepest single task.

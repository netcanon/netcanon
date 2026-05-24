# Cluster C — Developer / contributor-facing documentation accuracy

## Scope

Documentation read by contributors (codec authors, canonical-field
additions, test-writers, agent dispatch).  Verify claims against
current implementation.

### In scope (full audit)

* `AGENTS.md` — contributor directives, hard rules, documentation
  sync checklist (**critical** — the doc-sync table is a checklist
  contributors are supposed to follow; out-of-date rows actively
  mislead)
* `ARCHITECTURE.md` — four-layer design + migration pipeline
* `docs/METHODOLOGY.md` — distilled matrix-honesty discipline
* `docs/RELEASE_PLAN.md` — forward-looking plan (audit only for
  internal consistency + landed-vs-not labelling; do NOT flag
  forward-looking content as drift)
* `docs/adding-a-canonical-field.md` — worked example for canonical
  expansion
* `docs/adding-a-target-profile.md` — worked example for profile
  authoring
* `docs/glossary.md` — terminology definitions
* `docs/feature-parity-walkthrough.md` — feature-parity checklist
  worked example
* `SECURITY.md` — security architecture + supply-chain controls
* `CONTRIBUTING.md` — contributor onboarding
* `CODE_OF_CONDUCT.md` — read for cross-ref completeness only

### In scope (sub-READMEs)

* `netcanon/migration/codecs/README.md` (if present)
* `netcanon/migration/canonical/README.md` (if present)
* `definitions/README.md` (if present)
* Any `README.md` inside `netcanon/.../` subdirs

### Out of scope

* User-facing docs (Cluster B)
* Codec docstrings (Cluster D)
* Test docs (Cluster F)
* `docs/security-triage/README.md` — read for cross-ref only (sister-process doc)
* `docs/docs-audit/README.md` — meta; just read for cross-ref
* Special folders (per audit charter) — read for context only

## What to verify

1. **`AGENTS.md` Documentation Sync Checklist coverage.**  Walk
   through every row of the doc-sync table.  For each row:
   * Does the trigger ("If you change ... add a new ... ") still
     match a real surface in current code?
   * Does the required action ("Then touch ... ") point at a file
     that still exists at the claimed path?
   * Are there current-code surfaces that SHOULD trigger a doc-sync
     row but don't?  E.g. is there a recurring class of change that
     contributors forget?

2. **`AGENTS.md` Hard Rules.**  Verify each hard rule still maps to
   current code:
   * "Never include real password hashes" — verify sanitiser
     enforcement still in place
   * Frozen pipeline-stage signatures — verify the named functions
     are still frozen (signature unchanged)
   * Etc.  Walk each hard rule and find its enforcement point.

3. **`ARCHITECTURE.md` four-layer design.**  Verify the layers
   described (definitions/ + canonical/ + codecs/ + migration
   pipeline) still match what's in `netcanon/`.  Surface anything
   in the code that doesn't map cleanly into one of the layers.

4. **`METHODOLOGY.md` worked-example citations.**  Each cited file
   path + commit SHA should resolve (or have the "pre-launch SHA"
   caveat from CHANGELOG.md applied).

5. **`adding-a-canonical-field.md` accuracy.**  Walk through the
   MTU worked example as if you were adding a new field today.
   Does every cited file path resolve?  Does the canonical model
   shape still match the example?

6. **`adding-a-target-profile.md` accuracy.**  Walk through the
   target-profile creation pattern.  Does the example schema match
   current `TargetProfile` definition?

7. **`glossary.md` coverage.**  Verify defined terms are still used
   in code/docs.  Surface code/doc terms that aren't in the
   glossary but probably should be.

8. **`SECURITY.md` "Updating This Document" trigger list.**  Verify
   the trigger list (line ~385) covers recent changes (e.g. did
   v0.1.2's defusedxml swap require a SECURITY.md update? was it
   done?).  Surface gaps.

9. **`RELEASE_PLAN.md` Phase tracking.**  Verify Phase 6 / Phase 7
   landing status matches actual repo state.  Forward-looking
   phases that haven't shipped = EXPECTED-STALE.  Phases marked
   "shipped" should actually be shipped.

10. **Sub-README internal consistency.**  Each sub-README typically
    enumerates the module's public surface or layout.  Verify the
    enumeration matches the actual file/function set.

## Methodology

* `Read` each in-scope doc fully.
* `Grep` for cited file paths / function names / commit SHAs.
* `Bash` (`git show <sha>`, `git log --grep`) to verify commit-trail
  citations.
* Use the codec layout from `00-snapshot.md` as the source-of-truth
  for "what currently exists."

## Severity tagging

| Severity | Examples |
|---|---|
| **WRONG** | Doc-sync table row points at a deleted file; hard rule references a function that no longer exists; ARCHITECTURE.md describes a layer that's been refactored away |
| **MISSING** | A recurring code-change pattern doesn't have a doc-sync row; a code surface isn't covered by ARCHITECTURE.md; a frozen function isn't tagged in its module docstring |
| **INCOMPLETE** | Worked example covers part of the workflow but skips a now-required step; sub-README enumerates some modules but not the new ones |
| **STYLE** | Outdated terminology not yet updated in glossary; inconsistent capitalisation across docs |
| **EXPECTED-STALE** | `RELEASE_PLAN.md` describes Phase 7 which hasn't shipped — that's forward-looking by design |

## Output format

Write to: `docs/docs-audit/2026-05-21/01-investigation-C.md`

```markdown
# Cluster C — Developer-facing documentation accuracy

## Summary

(2-3 sentence verdict)

## AGENTS.md doc-sync table audit

(Row-by-row verification; especially important since it's the
contributor checklist surface.  Flag any row that's WRONG or any
recurring code-change pattern that's MISSING.)

## ARCHITECTURE.md verification

## METHODOLOGY.md / adding-a-* / glossary verification

## SECURITY.md "Updating This Document" coverage

## Per-doc findings

(For each in-scope doc, severity-tagged finding table.)

## Cross-cutting observations
```

## Constraints

* **READ-ONLY.**  Single output file.
* Hard rules from `AGENTS.md`.
* Time budget: ~45-60 min.
* AGENTS.md is the most critical doc in this cluster — give it
  the most depth.  Contributors actively follow its checklist;
  errors there compound across every commit.

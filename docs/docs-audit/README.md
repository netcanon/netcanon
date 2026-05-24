# Documentation hygiene audit — process

Docs and code drift silently — claims in docstrings / READMEs /
walkthroughs become lies the moment the underlying surface
changes, and the gap is invisible until someone actually tries to
follow the doc.  This folder is where each audit *run* records its
evidence trail so future-you (or a future agent) can reproduce the
verdict without re-investigating.

Sister process to [`docs/security-triage/`](../security-triage/) —
same scaffolding pattern (per-run dated subfolder + cluster
taxonomy + read-only Stage 1 agents + orchestrator synthesis + Stage
2 fix execution).  Differences are scoped to *what gets investigated*
(documentation vs security alerts), not *how the work flows*.

## When to invoke

Run a documentation hygiene cycle when:

* After a thematic series of code changes has landed (security
  cycle, codec wave, canonical-model expansion) — the drift
  surface is widest right after a wave.
* Before a release tag, as a defence-in-depth gate against
  "the docs lied to me" operator reports.
* When the open-questions volume on a doc has crept up to "is this
  still right?"
* On a recurring cadence (quarterly is the rough default for a
  project the size of netcanon) — drift compounds even between
  obvious change waves.

For one-off doc updates landing alongside their code change, just
do the doc-sync inline per `AGENTS.md` § "Documentation Sync
Checklist" — don't spin up the full process.

## Folder layout per run

```
docs/docs-audit/<YYYY-MM-DD>/
  00-snapshot.md                              # initial inventory + scope (human-readable)
  cluster-A-interlinking-scope.md             # per-cluster scoped input for the agent
  cluster-B-user-docs-scope.md
  cluster-C-developer-docs-scope.md
  cluster-D-codec-docstrings-scope.md
  cluster-E-platform-docstrings-scope.md
  cluster-F-tests-changelog-scope.md
  01-investigation-A.md                       # per-cluster verdict (Stage 1 agent output)
  ... (one per cluster)
  99-synthesis.md                             # consolidated verdict (orchestrator)
  fix-plan.md                                 # Stage 2 work breakdown (orchestrator)
```

The date folder name is **the UTC date of the audit start**, not
the local date — matches the timestamps that will appear in
commit metadata.

## Cluster taxonomy (stable across runs)

Like security-triage, clusters group findings by the *kind of
investigation* they need, not by their file type:

| Cluster | Scope | Investigation depth |
|---|---|---|
| **A — Interlinking & structural integrity** | All `*.md` files: build a cross-reference graph, find broken links, missing "See also" reciprocity, contents-map drift, orphan docs | Mechanical — Grep-driven; verify references resolve |
| **B — User-facing documentation accuracy** | Operator-readable docs: `README.md`, `docs/CAPABILITIES.md`, `docs/TROUBLESHOOTING.md`, `BUG_REPORTING.md`, `docs/vendors/`, `docs/walkthroughs/`, `docs/HOW_WE_TEST.md`, `docs/COMPARISON.md`, `docs/IDENTITY.md`, sampled pages from `docs/vendor-references/` | Deep — verify claims against current code, fixtures, capability matrix |
| **C — Developer / contributor-facing documentation accuracy** | Contributor docs: `AGENTS.md`, `ARCHITECTURE.md`, `docs/METHODOLOGY.md`, `docs/RELEASE_PLAN.md`, `docs/adding-a-canonical-field.md`, `docs/adding-a-target-profile.md`, `docs/glossary.md`, `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, all `netcanon/.../README.md` sub-READMEs | Deep — verify against current implementation; especially AGENTS.md doc-sync table coverage |
| **D — Codec docstrings + file headers** | `netcanon/migration/codecs/<vendor>/*.py` for all 7+ codecs (parse.py, render.py, codec.py, port_names.py, sub-modules) | Module docstrings, class docstrings, function docstrings; verify "Public surface" lists, top-of-file purpose comments |
| **E — Platform code docstrings** | All `netcanon/*.py` outside `migration/codecs/`: canonical/, services/, api/, collectors/, storage/, models/, cli.py | Same docstring scope as D, applied to non-codec surfaces |
| **F — Tests, fixture provenance + CHANGELOG accuracy** | `tests/` tree (READMEs + testid_reference + fixtures/real/{NOTICE,RESULTS,WANTED}.md + conftest docstrings), `pyproject.toml` markers, `CHANGELOG.md` entries vs actual git history | Verify cross-refs + commit-trail accuracy + marker definitions match conftest usage + `_DIR_TO_CODEC_NAME` covers all fixture dirs |

Use these labels consistently across runs.  Future-you searching
for "the codec-docstring audit pattern" benefits from finding past
investigations under a stable cluster name.

## Treatment of "special" folders

Some folders have semantics that differ from current-state docs —
agents must distinguish "drift" from "expected pattern":

| Folder | Semantics | Audit treatment |
|---|---|---|
| `docs/security-triage/<date>/` | Frozen evidence trail of a past triage cycle | Read for interlinking, but don't flag content as "stale" — it's a snapshot |
| `docs/v0.2.0-planning/` | Forward-looking design artifacts (some implemented, some not) | Don't flag gap between "described future" and "current state" as drift |
| `docs/fixture-research-2015/` | Historical research snapshot for the v0.2.0 overlay-authoring plan | Read for interlinking; don't audit accuracy against present state |
| `docs/templates/` | Aspirational starter scaffolding for cloning the methodology to other projects | Don't flag gap with netcanon-specific content — template is generic-by-design |
| `docs/archive/` | Retired docs preserved for citation | Skip accuracy audit; verify only that cross-refs into it from current docs still resolve |
| `docs/vendor-references/<pair>/` | Per-vendor-pair reference pages (~42 pairs × 13-16 files = ~600 docs) | Sample 1-2 pairs in depth; for the rest, verify the template shape is consistent rather than auditing each page individually |

## Severity tagging

Each finding gets one of:

* **WRONG** — claim contradicts current reality.  Doc says X, code does Y.  Fix in Stage 2.
* **MISSING** — surface exists in code but has no documentation, OR doc structure expects content that isn't there.  Add in Stage 2.
* **INCOMPLETE** — partial doc; covers some surface but not all.  Fill in Stage 2.
* **STYLE** — formatting / cross-reference / readability issue.  Lower-priority; may batch.
* **EXPECTED-STALE** — flagged-but-expected per the special-folder taxonomy above.  Document and skip.

## Two-stage operation

### Stage 1 — Read-only analysis (parallel agents)

Per cluster needing investigation, spawn one read-only Opus 4.7 1M
agent with:

* The cluster's scope file (which files / what to audit)
* The cluster's methodology + severity tagging convention
* Output file path under the run folder (e.g. `01-investigation-A.md`)
* Strict read-only on repo code — only writes its designated output
* Hard rules inheritance from `AGENTS.md` § "Hard Rules (Never
  Break)"
* The special-folder treatment table above
* Forward-looking content discipline (don't flag aspirational docs
  as "wrong")

The agent's deliverable is a verdict table per finding:

```
| # | Path:Line | Severity | Finding | Fix shape |
```

### Stage 2 — Synthesis + action

Orchestrator (not an agent) reads the per-cluster verdicts and:

1. Writes `99-synthesis.md` — consolidated WRONG list + MISSING
   list + INCOMPLETE list, grouped by file/theme for Stage 2
   dispatch.
2. Writes `fix-plan.md` — Stage 2 work breakdown.  Distinguishes
   "orchestrator-direct" (small mechanical edits) from "needs an
   agent" (multi-file scope, semantic work).
3. Executes fixes commit-by-commit, one logical theme per commit.
4. Re-runs whichever Stage 1 agents would re-verify the fixed
   surface, OR just trusts the edit was correct (per-theme call).

## Model + isolation policy

* **All Stage 1 agents run as Opus 4.7 1M.**  Documentation review
  benefits from the model's long-context retention across many
  files + careful reading.
* **No worktree isolation in Stage 1** — read-only, no edit
  risk.  Saves disk + dispatch cost.
* **Stage 2 implementation** runs orchestrator-direct unless a
  cluster's fix surface spans 10+ files with semantic complexity
  (then one Opus agent per surface, with worktree isolation if
  parallelising).

## See also

* [`AGENTS.md`](../../AGENTS.md) — hard rules + "Documentation Sync
  Checklist" all Stage 1/2 agents inherit
* [`docs/security-triage/`](../security-triage/) — sister process
  for security-alert triage; same scaffolding shape applied to a
  different domain
* [`ARCHITECTURE.md`](../../ARCHITECTURE.md) — the four-layer design
  that load-bearing docstrings describe

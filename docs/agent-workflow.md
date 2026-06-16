# Distributed agent work — how we run reviews, audits & research

This is the **binding process** for any multi-agent review, audit, or research task in netcanon. It is the
project's own methodology — the [`docs/security-triage/`](security-triage/) and [`docs/docs-audit/`](docs-audit/)
sister-processes are worked instances of it — now formalized behind a single reusable runner so the discipline
is inherited by construction rather than re-derived from memory each time.

The one-line shape:

> **snapshot → cluster scope → parallel read-only agents → orchestrator synthesis → fix-plan → main-thread
> actuation → evidence-trail commit**

## The load-bearing rule: read-only agents, main thread actuates

- **Stage-1 agents are strictly read-only.** An agent may read anything; it may **write ONLY its one designated
  report file** under the run folder. No source/test/fixture/doc edits, no `git add`/commit/tag, no running the
  regen tools (`tools/run_full_mesh.py` / `tools/run_phase4_reconciliation.py`), no starting the app, no
  actuation of any kind. It must never read or write under `docs/codebase-review/` (the uncommitted PII
  dossier). No worktree isolation is needed precisely *because* agents cannot edit (saves disk + dispatch cost).
- **The orchestrator (main thread) is the only actor that validates and actuates.** It reads the agents'
  reports, reconciles them into a synthesis + fix-plan, then applies fixes, runs the gate, and commits — itself,
  or by dispatching **Stage-2 implementation agents** *only* where the fix scope genuinely warrants it (and
  those use worktree isolation if they edit shared files in parallel).

Research fans out cheaply and safely; mutation is centralized and verified. This is the same split the
security-triage and docs-audit processes already use.

## Ultracode runs — the Workflow-tool blackboard (the consistent mechanism)

Ultracode runs (the `ultracode` keyword opts a turn into multi-agent orchestration) operationalize the process
above through the **`Workflow` tool** + the reusable runner
[../.claude/workflows/blackboard.js](../.claude/workflows/blackboard.js) (invoked by **`scriptPath`** —
`Workflow({ scriptPath: "<repo>/.claude/workflows/blackboard.js", args })`; the `name:` registry is reserved
for built-in/plugin workflows). **This runner is the only sanctioned shape** — it bakes the load-bearing rule
in (read-only agents, one report file each, main thread actuates) so the discipline can't be re-hand-rolled or
drift. The `args` contract + invocation recipe live in
[../.claude/workflows/README.md](../.claude/workflows/README.md); this section is the convention it implements.

**Run folder** = `docs/reviews/<UTC-date>-<slug>/` (the topical `-<slug>` distinguishes a focused
research+design run from a whole-repo audit, which may drop the slug — same family, phase-appropriate file
names):

```
docs/reviews/<UTC-date>-<slug>/
  00-blackboard.md            # SEED — the MAIN THREAD writes this BEFORE the run: mission, hard constraints, roster
  10-research-<x>.md          # Stage-1 research agents (10s) — each its ONLY write
  11-research-<y>.md
  20-design-<a>.md            # Stage-1 design agents (20s) — read the 10s for peer comms
  21-design-<b>.md
  30-review-adversarial.md    # adversarial review (30s) — reads all 10s + 20s
  99-synthesis.md             # SYNTHESIS — the MAIN THREAD writes this AFTER: reconciled decisions + buildable-now
```

- **Numeric prefixes encode phase order** (10s research → 20s design → 30s review); the prefix is the agent's
  `id` *and* its report filename. Phases run as `parallel()` barriers; later phases read earlier reports for
  comms.
- **The runner has NO filesystem access** — it only orchestrates agents. So the **main thread owns the
  bookends**: write `00-blackboard.md` (the seed) before invoking, `99-synthesis.md` after, and then
  fix / verify / commit — the sole actuator. Agents write only their one `NN-*.md`.
- **Agents return only a pointer/summary**; the long-form analysis lives in the file (keeps the main thread
  light). Reviewers return a verdict + severity-tagged must-fixes.
- **Opus for every agent** (the runner's default) — long-context retention + design/audit quality. Never
  under-model a design/audit/research agent.

### The `00-blackboard.md` seed template (the main thread fills + writes this before invoking)

```markdown
# Blackboard — <mission title> (<UTC-date>)

**Process:** netcanon file-per-agent blackboard. Read-only agents each write EXACTLY ONE report in this dir; the
main thread seeds this file + writes 99-synthesis.md + is the sole actor that verifies/commits.

## Mission
<what this run examines/decides — 1-3 bullets>

## Hard constraints (apply to every report)
<the non-negotiables for THIS run — e.g. behaviour-preserving (cross-mesh CODEC_BUG flat at 5; artifacts
byte-identical); no over-engineering; the pseudonym/PII commit rules; matrix-honesty (declare what you drop)>

## File roster
| File | Phase | Author | Covers |
|---|---|---|---|
| 00-blackboard.md | seed | main thread | this protocol + mission + constraints |
| 10-research-<x>.md | research | R1 | ... |
| 30-review-adversarial.md | review | V1 | GO/NO-GO + must-fixes |
| 99-synthesis.md | synthesis | main thread | reconciled decisions + buildable-now contract |

## Decisions already locked (context)
<prior decisions the agents should treat as fixed>
```

### Evidence-trail conventions

- Folder name carries the **UTC date** of the run (matches commit/GitHub timestamps).
- Numeric prefixes encode pipeline order: `00-` seed, `10/20/30-` Stage-1 outputs by phase, `99-` synthesis.
- These folders are **EXPECTED-STALE**: a later audit must never flag a past run's evidence as drift. They are
  a frozen record, not live docs.
- Agents hand off purely via their `NN-*.md`; the orchestrator reconciles in `99-synthesis.md`.

## Agent report format

A research/design agent's report is long-form prose + tables (headings, rationale, `file:line` citations,
concrete code/markup sketches). A reviewer's report is a verdict table the orchestrator can reconcile fast:

```
| # | Path:Line | Severity | Finding | Verdict (CONFIRMED/DISMISSED) | Fix shape |
```

Pick severity tags that fit the run. For a UX/UI review: **BROKEN / CONFUSING / INCONSISTENT / A11Y / POLISH**.
For a docs/scaffolding review: **WRONG / MISSING / INCOMPLETE / STYLE / EXPECTED-STALE** (the last = a
deliberate pattern, not a defect).

## Cluster taxonomy (how work is scoped & parallelized)

Group work by the **kind of investigation** it needs, not by file type — that is what makes it parallelizable.
Labels should be **stable across runs** so future searches find prior investigations under the same name. Each
agent owns a **non-overlapping scope**. The cluster set is run-type-specific; representative netcanon clusters:

| Run type | Typical clusters |
|---|---|
| **Codec / fidelity** | per-codec round-trip + cross-mesh CODEC_BUG; canonical-model surface coverage; matrix-honesty (declare-what-you-drop) |
| **Docs** | interlinking & structure; user-facing accuracy; developer-facing accuracy; codec/platform docstrings; tests + CHANGELOG (see `docs/docs-audit/`) |
| **Security** | attack-surface alerts; pattern-class alerts; workflow/secret handling (see `docs/security-triage/`) |
| **UX / UI** | information architecture & navigation; state coverage (loading/empty/error/success); accessibility & semantics; consistency & visual system; microcopy & honesty (limitation messages match `docs/CAPABILITIES.md`) |

## Dispatch heuristics

- **Model:** Opus for the read-only investigation agents (long-context retention across many files); the
  orchestrator runs on the main thread.
- **Parallelism:** one agent per cluster, dispatched together. More agents ≠ faster when each cluster is
  file-bounded — and harder to reconcile.
- **File-overlap check before dispatch:** if two Stage-2 agents would need to *edit* the same file, serialize
  them or split the file. Stage-1 is read-only so overlap is harmless.
- **Keep findings in files, not the main thread.** Agents write full detail to their report file and return
  only a short summary + the path, so the main thread's context stays light (the whole point of off-thread
  research).

## When to invoke vs. inline

- **Invoke the full process** on a *wave*: a UX/scaffolding/doc audit, a pre-release gate, a post-large-change
  sweep, or a periodic cadence.
- **For a one-off** finding or small fix, just fix it inline — don't spin up the process.

## Stage 2 (actuation) — netcanon rules

The orchestrator executes fixes **one logical theme per PR/commit**, with rationale-first commit messages. Each
behaviour-affecting change is gated on the netcanon proof bar before commit:

> ruff clean → `compileall` → `pytest tests/unit tests/integration` green → (for codec changes) regen
> `run_full_mesh --matrix` + `run_phase4_reconciliation`, confirm **CODEC_BUG flat at 5** and
> `CROSS_MESH_RESULTS.md` / `PHASE4_RECONCILIATION.md` byte-identical → prune the regen `*Z.json` + revert
> `_phase4_runs/latest.json`. For UI changes, add live preview verification (visual testing catches what CI
> doesn't).

Standing actuation constraints (see [`../AGENTS.md`](../AGENTS.md) § Hard Rules): commit under the pseudonym
identity with the `Co-Authored-By` trailer; stage files explicitly (never `git add -A` — the `docs/codebase-review/`
dossier must stay uncommitted); branch before committing; confirm before each merge; a release tag = publish and
needs explicit user go-ahead. Stage-2 agents are spawned only for genuinely multi-file fixes.

## See also
- [`../AGENTS.md`](../AGENTS.md) — contributor directives + Hard Rules + the Documentation Sync Checklist
- [`METHODOLOGY.md`](METHODOLOGY.md) — the matrix-honesty discipline the audits enforce
- [`security-triage/`](security-triage/) — worked instance: Code Scanning / Dependabot alert-wave triage
- [`docs-audit/`](docs-audit/) — worked instance: documentation-hygiene sweep

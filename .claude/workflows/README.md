# .claude/workflows — reusable ultracode workflows

Reusable `Workflow`-tool scripts for this repo. **Invoke them by `scriptPath`** (not `name:` — the `name:`
registry is reserved for built-in/plugin workflows like `deep-research` / `code-review`; custom files here are
addressed by their path). The binding process they implement is
[docs/agent-workflow.md](../../docs/agent-workflow.md).

## `blackboard.js` — the file-per-agent blackboard (the consistent ultracode pattern)

Every ultracode run uses this runner so the discipline never has to be re-hand-rolled (and can't drift). It
bakes in the load-bearing contract:

- **Read-only agents, one report file each.** Each agent writes EXACTLY ONE long-form report (its `id`.md under
  the run dir) and is otherwise strictly read-only — no source/test/fixture/doc edits, no git/regen/build, no
  actuation, and never touches the uncommitted `docs/codebase-review/` PII dossier. The contract preamble is
  prepended to every agent prompt automatically.
- **File-based peer comms.** Later-phase agents read earlier phases' report files (`readsPrior: true`, or an
  explicit per-agent `reads: [id,…]`).
- **Short returns.** Agents return only a pointer/summary (`report_file`, `headline`, `key_points`; reviewers
  return `verdict` + `must_fixes`). The depth lives in the markdown files, so the main thread's context stays
  light.
- **Opus by default** for every agent (override per-agent/phase with `model`).

### The main thread owns the bookends (NOT the runner — it has no filesystem access)

1. **Before invoking:** write `<dir>/00-blackboard.md` — the seed: mission, hard constraints, file roster. Use
   the template in [docs/agent-workflow.md](../../docs/agent-workflow.md) (§ Ultracode runs).
2. **Invoke** the runner (see below).
3. **After it returns:** read the `NN-*.md` report files, write `<dir>/99-synthesis.md` (reconciled decisions +
   the buildable-now contract, applying the review's must-fixes), then build/verify/commit. Agents NEVER
   actuate — the main thread is the sole actor that runs tests / regen / live preview and commits (pseudonym
   identity, explicit staging, confirm-before-merge — see [../../AGENTS.md](../../AGENTS.md)).

### Invocation

```
// main thread, before the call: Write <repo>/docs/reviews/<UTC-date>-<slug>/00-blackboard.md (the seed)
Workflow({ scriptPath: "<repo>/.claude/workflows/blackboard.js", args: {
  dir: "<absolute-repo-path>/docs/reviews/<UTC-date>-<slug>",  // ABSOLUTE; date-stamped + slug
  slug: "ux-review",
  mission: "one-line mission (logged at start)",
  phases: [
    { title: "Research", agents: [
      { id: "10-research-x", label: "R1:x", task: "<run-specific prompt body>" },
      { id: "11-research-y", label: "R2:y", task: "…" },
    ] },
    { title: "Design", readsPrior: true, agents: [
      { id: "20-design-a", label: "D1:a", task: "…" },
    ] },
    { title: "Review", readsPrior: true, review: true, agents: [
      { id: "30-review", label: "V1", task: "…" },
    ] },
  ],
} })
```

### `args` contract

| key | required | meaning |
|---|---|---|
| `dir` | yes | ABSOLUTE run-folder path (`<repo>/docs/reviews/<UTC-date>-<slug>`). The runner has no FS access, so the caller computes it (matches the caller's path separator automatically). |
| `slug` | no | short topic label for the progress narrator. |
| `mission` | no | one-line mission, `log()`-ed at start. |
| `phases[]` | yes | ordered phases; each runs as a `parallel()` barrier. |
| `phases[].title` | yes | progress group + the phase tag. |
| `phases[].readsPrior` | no | `true` → every agent reads ALL earlier-phase report files. |
| `phases[].review` | no | `true` → agents use the `REVIEW_SUMMARY` schema (verdict + must_fixes). |
| `phases[].model` | no | model for the whole phase (default `opus`). |
| `agents[].id` | yes | report filename stem; numeric-prefixed + **unique** (it IS the agent's only write target). |
| `agents[].task` | yes | the run-specific prompt body (the read-only contract is prepended for you). |
| `agents[].label` | no | progress label (default = `id`). |
| `agents[].reads` | no | explicit `[id,…]` peer reports to read (overrides `readsPrior`). |
| `agents[].model` | no | per-agent model override. |

Returns `{ dir, files:{id→path}, phases:[{title, results:[{id,file,summary}]}], review }`.

### Iterate / resume

Edit `blackboard.js` (or the per-run caller) and re-invoke with `scriptPath` + `resumeFromRunId` — unchanged
agents return cached results. Note: `Date.now()`/`new Date()` are unavailable in workflow scripts (they break
resume), which is why the caller stamps the date into `dir`.

## Lineage

This runner formalizes netcanon's own multi-agent methodology — the `docs/security-triage/` and `docs/docs-audit/`
sister-processes (snapshot → cluster → parallel read-only agents → orchestrator synthesis → main-thread
actuation). It was hardened into a reusable runner in a sibling project and brought back here so every future
ultracode run inherits the same discipline by construction rather than by memory.

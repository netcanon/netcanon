# Security alert triage — process

GitHub Code Scanning + Dependabot + Secret Scanning surface a steady
trickle of alerts.  Some are real fixes; many are policy-noise or
by-design patterns that need dismissal-with-reason.  This folder is
where each triage *run* records its evidence trail so future-you (or
a future agent) can reproduce the verdict without re-investigating.

## When to invoke

Run a triage cycle when:

* A new scanner is enabled (initial alert wave) — see `2026-05-21/`
  for the worked example covering CodeQL + zizmor first-fire
* A scanner version-bumps and surfaces a wave of newly-covered rules
* The open-alert count creeps past a "what changed?" threshold
  (rule of thumb: > 10 new alerts since last triage)
* Before a release tag, as a defence-in-depth gate

For one-off alerts arriving during normal development, fix or
dismiss inline — don't spin up the full process.

## Folder layout per run

```
docs/security-triage/<YYYY-MM-DD>/
  00-snapshot.md              # alert inventory at start of run (human-readable)
  alerts-raw.json             # full per-alert API dump (machine-readable)
  cluster-<X>-<name>.json     # per-cluster alert subset for agent input
  01-investigation-<X>.md     # per-cluster verdict (written by Stage 1 agent)
  99-synthesis.md             # consolidated verdict (written by orchestrator)
  dismissals.json             # batch dismissal payload (machine-readable)
  fix-plan.md                 # Stage 2 work breakdown (written by orchestrator)
```

The date folder name is **the UTC date of the alert snapshot**, not
the local date — matches the timestamps on GitHub-side artefacts.

## Cluster taxonomy (stable across runs)

Alerts cluster by the *kind of investigation* they need, not by
their tool of origin.  This taxonomy is what makes the workflow
parallelisable:

| Cluster | Scope | Typical investigation depth |
|---|---|---|
| **A — Real attack surface** | XSS, XXE, deserialisation, credential logging, cache poisoning, anything that depends on attacker-supplied input being parsed | Deep — read the affected code, model the attacker, decide if the framing is real |
| **B — Pattern verification** | Bulk findings on regex DoS, hard-coded patterns CodeQL flags conservatively (paramiko AutoAddPolicy, etc.), zizmor's unpinned-uses on first-party actions | Grep-and-confirm — verify all instances share the by-design framing, then bulk-dismiss as a class |
| **C — Workflow security** | GHA-specific findings: missing permissions blocks, excessive GITHUB_TOKEN scopes, persist-credentials, cache-poisoning in publish workflows, dependabot cooldown gaps | Workflow-file-level — read each affected workflow, identify per-finding line + fix shape |
| **D — Already-identified** | Things the orchestrator already triaged before spawning (e.g. line-X template-injection caught in pre-merge review) | None — already in the fix queue |

Use these labels consistently across runs.  Future-you searching
for "the OPNsense XXE pattern" benefits from finding past
investigations under a stable cluster name.

## Two-stage operation

### Stage 1 — Read-only analysis (parallel agents)

Per cluster needing investigation, spawn one read-only agent with:

* The cluster's JSON file (focused input — not all 79 alerts)
* Output file path under the run folder (e.g. `01-investigation-A.md`)
* Strict read-only on repo code (only writes its designated output)
* Hard-rules inheritance from `AGENTS.md` (especially the "no real
  password hashes" rule when inspecting test fixtures)

The agent's deliverable is a verdict table:

```
| Alert # | Path:Line | Verdict (REAL / DISMISS) | Severity if real | Fix approach if real | Dismissal reason if dismiss |
```

### Stage 2 — Synthesis + action

Orchestrator (not an agent) reads the per-cluster verdicts and:

1. Writes `99-synthesis.md` — consolidated REAL list + consolidated DISMISS list
2. Writes `dismissals.json` — batch payload of `{alert_id, reason, comment}` tuples
3. Writes `fix-plan.md` — groups REAL fixes by file/codec for Stage 2 dispatch
4. Applies dismissals via `gh api PATCH /repos/<org>/<repo>/code-scanning/alerts/<n>`
5. Spawns Stage 2 implementation agents only where multi-file scope warrants

GitHub-accepted `dismissed_reason` values:

* `false positive` — scanner misread, not actually vulnerable
* `won't fix` — accepted-risk / by-design pattern
* `used in tests` — fixture / test-scaffolding code, not prod

Always set a `dismissed_comment` (free-text) so the next person
reading the alert sees *why* — "won't fix" alone is opaque six
months later.

**Hard limit observed in practice (2026-05-21 run):** `dismissed_comment`
is capped at **280 characters**.  Comments that exceed this fail
with `HTTP 422 / Only 280 characters are allowed; N were supplied.`
Keep comments compact — lead with the reason, point at the run's
investigation file for the long-form analysis (e.g.
`docs/security-triage/<date>/01-investigation-X.md`).  Patterns
that proved fittable: ~200-235 chars typical; ~270 chars with
detail-pointer URL is the practical upper bound.

## Dispatch sizing

* **3 agents max in Stage 1** — matches the cluster count.  More
  agents = no faster (each cluster is independently file-bounded)
  and harder to reconcile.
* **Stage 2 grouping depends on Stage 1 output** — typically 1-3
  agents max.  Bulk dismissals are an orchestrator script (no agent
  needed).  Workflow fixes usually fit in one agent.  Codec fixes
  may need one agent per codec if scope is genuinely independent.
* **No worktree isolation in Stage 1** (read-only, no edit risk).
  Use worktree isolation in Stage 2 if multiple agents touch the
  same load-bearing files in parallel.

## See also

* [`AGENTS.md`](../../AGENTS.md) — hard rules + documentation sync
  conventions all Stage 1/2 agents inherit
* [`SECURITY.md`](../../SECURITY.md) — supply-chain integrity surface
  (what each scanner is gating against)
* [`BUG_REPORTING.md`](../../BUG_REPORTING.md) — sanitiser pattern
  Stage 1 agents apply when their cluster touches operator-supplied
  fixtures

# Full project review — 2026-06-06

A top-to-bottom, **read-only** review of netcanon at commit `b08040c`
(post-v0.1.2, post-security-triage, post-docs-audit).  Two parallel
fleets of Opus 4.8 (1M-context) reviewers, each agent descriptively
qualified for one lens, each writing its own long-form investigation
file into this dossier.

This is the third dated review dossier in the project, and it
deliberately re-uses the scaffolding shape established by its two
predecessors:

* [`docs/security-triage/2026-05-21/`](../../security-triage/2026-05-21/)
  — Code Scanning / Dependabot alert triage
* [`docs/docs-audit/2026-05-21/`](../../docs-audit/2026-05-21/)
  — documentation hygiene audit

Shape (shared across all three): **snapshot → per-cluster scope →
parallel read-only investigations → synthesis → consolidated
register + remediation plan.**

## What makes this run different

* **Two fleets, not one.**  A documentation fleet (6 reviewers) *and*
  a code/architecture fleet (6 reviewers), run as separate waves.
* **Long-form by mandate.**  Investigations are sized well past the
  300–600-word agent norm; each is a standalone audit chapter.
* **Adversarial verification.**  The highest-severity *code* findings
  are independently refuted/confirmed by a second agent before they
  enter the consolidated register (the docs findings are
  factually checkable and verified inline).
* **Read-only, top to bottom.**  No agent (or sub-agent) holds
  Edit/Write access to project code or docs.  The *only* writes are
  the dossier files under this folder.  The constraint is passed
  down to any sub-agents explicitly in every prompt.

## Fleets and clusters

### Fleet D — documentation (`docs-review/`)

| ID | Reviewer qualification | Output |
|----|------------------------|--------|
| DA | Operator/human-facing docs accuracy | `01-investigation-DA-human-facing.md` |
| DB | Scaffolding / `.md` interlinking-graph integrity | `01-investigation-DB-scaffolding.md` |
| DC | Test-ID inventory + per-test explanation discipline | `01-investigation-DC-testids-tests.md` |
| DD | Docstring accuracy + completeness | `01-investigation-DD-docstrings.md` |
| DE | File-header conventions where appropriate | `01-investigation-DE-headers.md` |
| DF | Contributor/architecture docs + meta-docs | `01-investigation-DF-other-docs.md` |

Scope detail: [`docs-review/00-docs-scope.md`](docs-review/00-docs-scope.md).

### Fleet C — code & architecture (`code-review/`)

| ID | Reviewer qualification | Output |
|----|------------------------|--------|
| CA | Application architecture (layering, seams, data flow) | `01-investigation-CA-app-architecture.md` |
| CB | File-by-file, platform (non-codec) source + desktop | `01-investigation-CB-file-by-file-platform.md` |
| CC | Codec architecture + per-codec file-by-file | `01-investigation-CC-codec-architecture.md` |
| CD | Modularity & coupling | `01-investigation-CD-modularity.md` |
| CE | God-file / cohesion / SRP assessment | `01-investigation-CE-god-file.md` |
| CF | Cross-cutting: error-handling, security posture, perf, deps | `01-investigation-CF-cross-cutting.md` |

Scope detail: [`code-review/00-code-scope.md`](code-review/00-code-scope.md).

## Severity scale (shared by both fleets)

| Tier | Meaning |
|------|---------|
| **P0** | Correctness/security defect with operator-visible impact; fix before next release |
| **P1** | Real defect or strong design smell; should be scheduled |
| **P2** | Worth doing; low risk, clear benefit |
| **P3** | Nit / stylistic / optional |
| **OBSERVATION** | Not a defect — context, praise, or a design note worth recording |

Every finding carries: `file:line` anchor, severity, a one-line claim,
the evidence, and a suggested direction (NOT an executed fix — this
pass is read-only).

## Outputs

* `00-snapshot.md` — repo state the review was taken against
* `docs-review/01-investigation-D*.md` — six doc investigations
* `code-review/01-investigation-C*.md` — six code investigations
* `docs-review/99-docs-synthesis.md` / `code-review/99-code-synthesis.md`
* `99-synthesis.md` — top-level cross-fleet synthesis
* `findings-register.md` — every finding, deduped + prioritized
* `recommended-remediation-plan.md` — a *plan* (sequenced), not an
  execution

## Status convention

Investigation files are authored by their agent.  Synthesis,
register, and plan are authored by the orchestrator after both fleets
land and the adversarial-verification pass completes.

## See also

* [`docs/docs-audit/2026-05-21/README.md`](../../docs-audit/2026-05-21/README.md) — prior hygiene audit (sister process)
* [`docs/security-triage/2026-05-21/README.md`](../../security-triage/2026-05-21/README.md) — prior alert triage (sister process)
* [`AGENTS.md`](../../../AGENTS.md) — the contributor directives + doc-sync checklist these reviews enforce
* [`docs/METHODOLOGY.md`](../../METHODOLOGY.md) — the matrix-honesty discipline the codebase is built on

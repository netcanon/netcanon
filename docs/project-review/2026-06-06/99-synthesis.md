# 99 — Top-level cross-fleet synthesis (2026-06-06)

The executive view across both fleets (12 investigations + an
adversarial-verification pass).  Read this first; drop into
`docs-review/99-docs-synthesis.md` / `code-review/99-code-synthesis.md`
for fleet detail, `findings-register.md` for every finding, and
`recommended-remediation-plan.md` for the sequenced (read-only) plan.

## Overall health verdict

**netcanon at `b08040c` is a mature, disciplined codebase with strong
documentation — the review found no P0, no crash-class defect, no
god-files, no import cycles, and no layering violations.** Two
independent fleets and an adversarial pass converged on the same
picture: the engineering discipline this project documents
(matrix-honesty, frozen pipeline signatures, ship-before-wire,
credential hygiene) is *actually upheld in the code*, not just
described in the docs.

The actionable surface is **two P1s, ~10 P2s, and a tail of P3
hygiene** — almost all small, high-confidence, and cheap to fix. The
single most important finding is a **security gap in the sanitiser**
that the rest of the project's discipline would normally have caught,
which is itself the strongest evidence the discipline is worth
investing another increment in.

## The two things to fix first (both P1, both verified)

1. **The bug-report sanitiser leaks VRRP/CARP authentication secrets**
   (R-01 / CF-01). `netcanon sanitize` is the tool operators are told
   to run to make a config safe to publish — and it does not redact
   `vrrp_groups[].authentication`, a cleartext-bearing field that three
   renderers emit verbatim. `--dry-run` shows nothing, giving false
   assurance. *Adversarially verified P1* — a refuter tried four
   refutation angles and all failed. This is a secret-disclosure path
   in a security tool; it leads the plan.

2. **`tools/` ships in nothing** (R-02 / CF-02 / DA-01). The README's
   flagship "See it in 10 seconds" `docker run … python tools/demo.py`
   and the pip-install demo are broken in every distributed artifact
   because `tools/` is excluded from both the wheel and the image.
   *Deterministically confirmed* from packaging config. It's the first
   command a new user runs, and it fails.

Neither is architectural; both are a few lines.

## Where the two fleets converge (the signal)

The most interesting findings are the ones **both fleets independently
pointed at the same place** — those are the real ones:

- **The sanitiser** is simultaneously a *code* security gap (CF-01) and
  a *doc* gap (SECURITY.md's redaction table omits the field, DF/DC
  territory). The fix is one change touching both code and SECURITY.md
  — exactly the kind of doc-sync the project's own AGENTS.md row
  demands.
- **The Junos `render_intent` `TypeError`** was surfaced *independently*
  by the docstring lens (DD-01), the codec-architecture lens (CC-01),
  and the error-handling lens (CF-03), and previously by the
  2026-05-21 docs-audit. Four independent arrivals at one 1-line
  contract violation — it should finally land.
- **Matrix-honesty holds in code but drifts in prose.** CB flagged
  `intent.py` VRRP/anycast docstrings as possibly dishonest; the
  adversarial pass proved the `_CAPS` (the load-bearing artifact) are
  *correct* and only the prose is stale. Symmetrically, DA found the
  `CAPABILITIES.md` Tier-1 *summary sentences* over-claim while the
  per-codec tables below them are honest. The discipline is intact at
  the structured layer; it's the human-readable summaries that rot.
- **`best_effort`/`certified` consistency** — DE caught the Aruba
  header contradiction the prior audit's MikroTik fix missed; CC
  confirmed the certainty ClassVars are otherwise honest. A
  header-vs-ClassVar guard test closes the class.

## Cross-cutting recommendation: turn three documented invariants into guard tests

A recurring shape across CD-03, DE-01, and the matrix-honesty findings:
**the project documents invariants it does not mechanically enforce.**
Three cheap guard tests would convert "social enforcement" into CI:
1. `inspect.signature` freeze-guard on the three pipeline functions (CD-03).
2. Header-`certainty`-line vs `codec.certainty` ClassVar equality (DE-01 class).
3. Sanitiser-covers-every-secret-bearing-canonical-field (would have
   caught CF-01 + CF-04): assert each secret-ish field on the model has
   a redaction rule.

This is the highest-leverage structural suggestion in the review:
it doesn't just fix the findings, it prevents their recurrence — and
it fits the project's existing taste (the `_WIRED_UP_BY_CODEC` two-sided
invariant test is exactly this pattern already).

## Adversarial-pass outcomes (verification earned its keep)

| Finding | Pre-verification | Post-verification |
|---------|------------------|-------------------|
| CF-01 sanitiser leak | P2 (reviewer) | **P1 — CONFIRMED** (4 refutation angles failed) |
| CB-01 VRRP docstrings | potential P2 methodology violation | **P3 — docstring-only** (8-codec table proved no half-wiring) |
| DD-03 `is_secondary` "already wired" | MED | **Refuted as stated** → replaced by accurate CC-02 (P3, narrow loss) |
| CF-02 packaging | P2, UNVERIFIED | **P1 — confirmed deterministically** |

Two findings up, one down, one corrected. The pass prevented one
over-claim (CB-01) and sharpened one security finding into its true
severity (CF-01).

## Severity rollup (whole review, deduped)

| Sev | Count | Theme |
|-----|------:|-------|
| **P0** | 0 | — |
| **P1** | 2 | sanitiser secret leak · packaging/demo broken |
| **P2** | ~10 | Junos `TypeError` · sanitize blocks event loop · Aruba cert header · CAPABILITIES over-claim · RESULTS self-contradiction · ARCHITECTURE `security/` gap + AGENTS false claim · AGENTS line-ref drift · no freeze-guard · ui.py split · generated-artifact staleness |
| **P3** | ~18 | is_secondary loss · VRRP docstring drift · Phase-0/libyang docstrings · PII redaction tail · interlink reciprocity · header uniformity · misc refactor watches |
| **OBSERVATION** | many | positives + design notes (see chapters) |

## What the review confirms is genuinely good
- Clean acyclic dependency graph; the codec layer is exemplary;
  `_CAPS` two-sided matrix-honesty actually holds.
- 100% module-docstring coverage; impeccable fixture provenance;
  0 dead links; the 2026-05-21 audit's fixes verifiably stuck.
- Credential hygiene (SecretStr + Fernet + 3-tier keys); all XML input
  on defusedxml; atomic storage writes; the rename-orchestrator family.

## Process note
This is the third dated review dossier (after security-triage and
docs-audit). The scaffolding shape is now a proven, repeatable
instrument. The whole pass was read-only: no project file was modified;
the only writes are this dossier. Remediation is a **plan**, not an
execution — see `recommended-remediation-plan.md`.

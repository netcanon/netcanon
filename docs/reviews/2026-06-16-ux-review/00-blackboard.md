# Blackboard — Wide UI/UX review (2026-06-16)

**Process:** netcanon file-per-agent blackboard ([docs/agent-workflow.md](../../agent-workflow.md)). Read-only
agents each write EXACTLY ONE report in this dir; the main thread seeds this file, writes 99-synthesis.md, runs
the LIVE preview verification, and is the sole actor that builds/commits. First run under the newly-formalized
ultracode protocol.

## Mission
- A full-pass, UI-focused **UX review** of netcanon's FastAPI + Jinja2 web app (the operator-facing UI).
- Find concrete, fixable UX defects across information architecture, state coverage, accessibility, visual
  consistency, and microcopy/honesty — each tied to `file:line` with a fix shape.
- Output feeds a prioritized fix-plan; the main thread then verifies the top findings LIVE in a browser preview
  before any fix lands.

## Surface under review (the snapshot)
- **Templates** (`netcanon/templates/`): `base.html` (650L — the shared shell + inline design system + nav),
  `index.html` (Dashboard, 373L), `configs.html` (314L), `diff.html` (288L), `definitions.html` (926L),
  `devices.html` (513L), `migrate.html` (2477L — the core migration flow), `sanitize.html` (468L),
  `jobs.html` (185L), `schedules.html` (302L). CSS/JS appear **inline** (no `static/` dir).
- **Page routes** (`netcanon/api/routes/ui.py`): `/`, `/jobs`, `/schedules`, `/configs`,
  `/configs/{left}/vs/{right}` (diff), `/devices`, `/definitions`, `/migrate`, `/sanitize`.
- **Data/async routes** (`netcanon/api/routes/`): `migration.py`, `backups.py`, `configs.py`,
  `definitions.py`, `device_profiles.py`, `sanitize.py`, `schedules.py`, `health.py`.

## Hard constraints (apply to every report)
- **Read-only.** Audit source only; do NOT run the app, edit anything, or run git/tests. Never read/write
  `docs/codebase-review/`.
- **Cite repo-relative paths only** (`netcanon/templates/migrate.html:1234`) — NEVER absolute/`C:\...` paths
  (this folder is committed; a leaked machine path fails the PII-guard CI).
- **Right-sized, not gold-plated.** netcanon is a self-hostable operator tool, not a consumer SaaS. Flag real
  UX defects; explicitly mark speculative/maximalist suggestions as `POLISH` (nice-to-have) so the synthesis
  can triage. Call out over-engineering in your `over_engineering_flags`.
- **Honesty is a product value.** The matrix-honesty discipline (declare-what-you-drop; Tier-3 vs Lossy vs
  CODEC_BUG) is load-bearing — UI limitation/lossy messaging must match `docs/CAPABILITIES.md` +
  `docs/TROUBLESHOOTING.md`. Treat dishonest/optimistic UI copy as a real defect, not polish.
- **Severity tags:** `BROKEN` (UX is wrong/dead) / `CONFUSING` (works but misleads or surprises) /
  `INCONSISTENT` (diverges from the rest of the app) / `A11Y` (accessibility) / `POLISH` (nice-to-have).
- **Report format:** long-form prose + a findings table:
  `| # | Path:Line | Severity | Finding | Fix shape | Effort (S/M/L) |`. Lead with your top 5.

## File roster
| File | Phase | Author | Covers |
|---|---|---|---|
| 00-blackboard.md | seed | main thread | this protocol + mission + constraints |
| 10-ia-navigation.md | audit | R1 | information architecture, nav, page-level flows & journeys, routing |
| 11-state-coverage.md | audit | R2 | loading / empty / error / success states + async UX (jobs, migrate, backups, sanitize) |
| 12-accessibility.md | audit | R3 | semantic HTML, labels/aria/roles, keyboard nav, focus, contrast, form a11y |
| 13-visual-consistency.md | audit | R4 | the inline design system (CSS vars, type/space/color), components, dark mode, responsive |
| 14-microcopy-honesty.md | audit | R5 | labels/helptext/error & empty copy; limitation/lossy/Tier-3 messaging vs CAPABILITIES.md |
| 30-review-adversarial.md | review | V1 | GO/NO-GO; dedup + prioritize must-fixes; flag over-reach |
| 99-synthesis.md | synthesis | main thread | reconciled, prioritized fix-plan + live-verification results |

## Decisions already locked (context)
- This is a **review**, not a redesign. The deliverable is a prioritized, `file:line`-anchored fix-plan — not a
  new design system. Don't propose framework swaps (no React/Tailwind/etc.); the app is server-rendered Jinja
  with inline assets by design.
- Fixes land later as small, behaviour-preserving PRs (the orchestrator verifies each live). Agents propose; the
  main thread disposes.
- Read `AGENTS.md` (esp. Selectors, Feature Parity, Documentation Sync) + `docs/CAPABILITIES.md` for ground truth.

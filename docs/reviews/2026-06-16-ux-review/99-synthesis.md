# 99 — Synthesis: Wide UI/UX review (2026-06-16)

**Author:** main thread (orchestrator). Reconciles the five audit reports (`10`–`14`) + the adversarial
review (`30`), adds **live-verification** results against the running app (uvicorn on a local port), and
emits a prioritized, batched fix-plan. Per the blackboard protocol, agents proposed (read-only); this
file is the main-thread decision record. Fixes land later as small, behaviour-preserving PRs.

## Verdict: **GO-WITH-FIXES** (audit sound; no top-tier false positives)

The web UI is **fundamentally healthy** — nav is complete and consistent (single `base.html` shell,
`aria-current` on the active link), the async layer is genuinely strong (a shared `formatApiError` +
toast, a robust poll/persist job panel that correctly never trusts the 202 POST body), and the audits
were unusually disciplined (every finding `file:line`-cited; authors pre-flagged their own over-reach).
Defects cluster in five places: **one first-paint bug**, **error-state wayfinding**, **accessibility**
(disclosures / modal focus / contrast / labels), **honesty copy** on the headline Migrate flow, and a
batch of **consistency/polish** nits.

## Live-verification (main-thread, against the running app)

The protocol's distinctive step — confirm the highest-impact findings in the *running* UI, not just the
source. All four held:

| MF | Finding | Live result | Verdict |
|---|---|---|---|
| **MF-1** | `/sanitize` `#san-result` `class="hidden"` but no `.hidden{display:none}` rule | computed `display:block`, `offsetHeight 257px`, empty "SANITIZED OUTPUT / Substitution audit" scaffold **visible on first load** | ✅ CONFIRMED (real first-paint defect) |
| **MF-5** | No 404/500 handler | bogus URL → `{"detail":"Not Found"}`, `content-type: application/json`, **no nav shell** | ✅ CONFIRMED (drops operator out of the themed app) |
| **MF-3** | `--text-faint` sub-AA for info-bearing text | token live = `#808088` (dark) / `#888888` (light, 3.54:1 — fails AA 4.5:1); drives `.empty-msg` | ✅ CONFIRMED |
| **MF-4** | Disclosure headers `<div onclick>` not keyboard-operable | `.job-card-header` = `DIV`, `tabindex:null`, `role:null`, `aria-expanded:null`, `keyboardFocusable:false` | ✅ CONFIRMED |

(The reviewer additionally verified 11 of the highest-severity claims directly against source — see
[`30-review-adversarial.md`](30-review-adversarial.md) § "What I verified".)

## Prioritized fix-plan (batched into behaviour-preserving PRs)

Adopting the reviewer's deduped IDs (MF-1…MF-20; full detail + `file:line` in
[`30-review-adversarial.md`](30-review-adversarial.md)). Severity uses the operator-tool lens
(blocker = wrong UX on a normal path; major = misleads / locks out a modality / breaks the honesty
discipline; minor = polish). Grouped so each PR is one coherent, low-risk theme.

### PR-1 — "First-paint + honesty + token" (CSS/copy/token only; highest impact, lowest risk)
- **MF-1** (major) — kill the Sanitize empty-scaffold: inline `style="display:none"` on `#san-result` +
  toggle in the existing reveal (mirrors the `#mig-result` pattern). *Live-verified.*
- **MF-2** (major, honesty) — soften the Migrate OK banner (`migrate.html:1516`) from "every path
  round-trips cleanly" → "every field that translates maps to a supported path on the target; review
  before applying — Netcanon has no deploy path." Add a one-line review-before-deploy note.
- **MF-3** (major, a11y) — darken/lighten `--text-faint` to clear AA in both themes; add a dedicated
  `--focus-ring` token that clears 3:1; optionally point `.empty-msg` at `--text-muted`. *Live-verified.*
- **MF-20** (minor) — Configs orienting lead `<p>` (matches the other pages).

### PR-2 — "a11y quick wins" (aria/attribute one-liners, no layout change)
- **MF-11** remove the overriding `aria-label` on `#_job-progress-summary` (`base.html:538`).
- **MF-10** error-variant toast → `role="alert"`/`aria-live="assertive"`.
- **MF-9** `aria-label` on icon-only download/compare buttons (alongside `title`).
- **MF-13** (partial) de-jargon the literal `raw_sections` string → plain prose.
- **MF-15** repoint `#fd7e14` orange badges to the existing `var(--badge-partial-*)`; dark-mode the chips.
- **MF-17** toast `z-index:10001` + `var(--shadow-lift)`, moved into a `#_toast{}` rule.

### PR-3 — "async edges" (small JS)
- **MF-16** disable inline per-row buttons in flight; treat 404-on-delete-after-success as success.
- **MF-18** full job id in `/jobs#` fragment + "not found / aged out" toast on miss.
- **MF-19** `/jobs` "Refresh" button + "does not auto-update" hint (NOT interval polling — see deferred).

### PR-4 — "error page" (new template + app-factory handlers; reaches desktop via embedded server)
- **MF-5** (major) — `error.html` extending `base.html` + `StarletteHTTPException`(404)/generic(500)
  handlers in `create_app`. Minimal: one message + "Back to Dashboard"; do **not** echo exception
  detail. *Live-verified.* Confirm the desktop test tier per the AGENTS.md Feature-Parity checklist.

### PR-5 — "keyboard operability" (layout-sensitive a11y, 3 sites)
- **MF-4** (major) — convert disclosure `<div onclick>` → `<button>` (or `role="button" tabindex="0"` +
  Enter/Space) at `jobs.html:56`, `devices.html:124`, `base.html:531`; toggle `aria-expanded`. *Live-verified.*
- **MF-6** (major) — rename-modal Esc-to-close + focus-on-open + focus-restore (mirror
  `kbd-cheatsheet.js`). Esc + focus mgmt only — **no** focus-trap library (modal is intentionally
  non-blocking/draggable).

### PR-6 — "forms + tables a11y sweep" (mechanical, multi-site)
- **MF-8** `scope="col"` on every column `<th>`; visually-hidden skip-link + `.sr-only` + `id="main"`.
- **MF-12** associate dashboard/devices/schedules `<label>`s with their inputs (`for`/`id` or wrap).
- **MF-14** converge *visible labels only* (config/configuration/backup; adapter/codec/vendor); at
  minimum align Migrate "Source adapter" with Sanitize "Source vendor".

### Deferred — onward links (do the cheap slice, defer the rest)
- **MF-7** result-footer links to `TROUBLESHOOTING.md` + `BUG_REPORTING.md` + "Sanitize this output"
  (cheap — fold into PR-2/PR-3). The **"Save as stored config"** half is M (new endpoint + desktop
  parity) — defer to its own scoped PR.

## Explicitly deferred / rejected (over-engineering — do NOT do as part of this review)
Endorsing the reviewer's flags: shared-component extraction (`.nc-card`/`.nc-modal`/`.btn-sm`) — adopt
the "next new card lands in base.html" rule instead; a full responsive/mobile pass (cap at an
opportunistic `nav { flex-wrap: wrap }` + `overflow-x:auto` on wide tables if desired); interval job
polling; an in-app glossary/help subsystem or CODEC_BUG detector; a full ARIA focus-trap; a CI guard for
in-prose certainty numbers. The certainty-threshold copy in `definitions.html` was **softened to minor**
(it's a policy criterion, not a drifting tally).

## Sequencing note (honesty is load-bearing)
MF-2 and MF-7-links directly serve the project's matrix-honesty product value — sequence them early
(PR-1 / PR-2) above their nominal severity. PR-1 is the highest-ROI starting point: three
live-verified, behaviour-preserving wins (first-paint, honesty copy, contrast) in one small CSS/copy PR.

## Out-of-UX-scope observation (logged, not part of this review)
App boot logs ~13 `definitions/target_profiles/opnsense_*.yaml` device-definition files failing schema
validation (`os`/`type_key`/`connection`/`commands` missing). The Migrate flow's 54 target profiles load
fine (different loader), so **no UI impact** — but worth a separate data/loader look.

## Source reports (depth lives here)
- [`10-ia-navigation.md`](10-ia-navigation.md) · [`11-state-coverage.md`](11-state-coverage.md) ·
  [`12-accessibility.md`](12-accessibility.md) · [`13-visual-consistency.md`](13-visual-consistency.md) ·
  [`14-microcopy-honesty.md`](14-microcopy-honesty.md) · [`30-review-adversarial.md`](30-review-adversarial.md)

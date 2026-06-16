# 30 — Adversarial review & dedup (V1)

**Role:** Adversarial reviewer for the 2026-06-16 UX audit. Read all five audit reports
(`10-ia-navigation`, `11-state-coverage`, `12-accessibility`, `13-visual-consistency`,
`14-microcopy-honesty`) + the seed, spot-checked the highest-severity claims against `base.html`,
`migrate.html`, `sanitize.html`, `index.html`, `jobs.html`, `devices.html`, `configs.html`,
`schedules.html`, `definitions.html`, `main.py`, `backups.py`, and `docs/CAPABILITIES.md`. Produced a
GO verdict, a deduped/prioritized must-fix list, over-engineering flags, and a buildable-now set.

---

## Verdict: **GO-WITH-FIXES**

The audit is **sound and actionable**. I verified eleven of the highest-severity claims directly
against source and every one held — including the two BROKEN-class findings (sanitize `.hidden`,
missing 404/500 handler), the load-bearing honesty over-claim ("round-trips cleanly"), and the four
palette/keyboard a11y findings. There are **no top-tier false positives**; the audits are unusually
disciplined about citing `file:line` and pre-marking their own over-reach as `POLISH`. The
"GO-WITH-FIXES" qualifier (rather than a clean GO) reflects three reconciliation duties the synthesis
must perform before the fix-plan is clean, not a soundness problem:

1. **Two reports independently found the same sanitize `.hidden` bug** (R2 #1 BROKEN, R4 #2
   CONFUSING/borderline-BROKEN) — these MUST merge into one fix, and the severity should resolve to
   **major** (first-paint defect, but the page still works; not "dead").
2. **The `--text-faint` contrast finding (R3 A3/A9) and the visual report's token-hygiene findings
   overlap** — the *fix* is one token edit that serves both the a11y and consistency goals; don't
   double-count or split it across two PRs.
3. **A cluster of small, real but low-impact findings** (trailing-slash redirect, hash non-uniqueness,
   injected-row `data-utc`, z-index, toast shadow) should be batched, not each shipped as its own PR
   touching the 2477-line `migrate.html` or the shared `base.html`.

The audits also correctly self-police against the seed's "review not redesign" constraint: R4 flags
its own component-extraction findings (6/7/13) as over-reach, R3 flags the full focus-trap library and
`<fieldset>` churn, R2 flags the heavy job-polling variant, and R5 flags the in-app-glossary
temptation. I concur with all of those self-flags and add a few below.

### What I verified against source (claim → ground truth)

| Claim | Report | Verified? | Evidence |
|---|---|---|---|
| `#san-result class="hidden"` but no global `.hidden{display:none}` → empty cards visible on first load | R2 #1 / R4 #2 | **YES** | `sanitize.html:128` has `class="hidden"`; grep of whole `templates/` tree finds the *only* `.hidden` rule at `migrate.html:52` `#mig-result.hidden{display:none}` (ID-scoped). `base.html` has no `.hidden`. Static result cards at `sanitize.html:129-181` render visible. |
| No custom 404/500 handler → unstyled JSON dead-end | R1 #1 | **YES** | No `@app.exception_handler`/`add_exception_handler` anywhere in `netcanon/` (grep: only ref is a *docstring* in `api/_errors.py:48` explaining it is NOT a handler). `create_app()` (`main.py:227-238`) registers none; no catch-all UI route. |
| Migrate OK banner says "every path round-trips cleanly" (over-claim vs CAPABILITIES) | R5 #1/#2 | **YES** | `migrate.html:1516` literally returns `&#10003; Validation OK — every path round-trips cleanly.` CAPABILITIES.md:48-51 ("Certified ≠ deploy-ready … no deploy path"), :527 (`ok` = "every **populated** … leaf"), :579-588 (round-trip = same-vendor term) all confirm the conflict. |
| Card/panel headers are `<div onclick>` — not keyboard-operable | R3 A1 | **YES** | `jobs.html:56-57` `<div class="job-card-header" onclick="toggleJob(this)">`; `devices.html:124-125` `<div … onclick="toggleDevice(this)">`; `base.html:531-533` job-progress header `<div … onclick="toggleJobProgress()">`. No `tabindex`/`role`/`aria-expanded`. Inner device buttons DO `event.stopPropagation()` (`devices.html:138-153`) — confirms only the disclosure affordance is dead. |
| `--text-faint` fails AA; focus ring fails 3:1 | R3 A3/A9 | **YES** | `base.html:53` `--text-faint:#888888` → 3.54:1 on white (math confirmed). `base.html:68` `--accent:#7eb8f7` used as `input:focus outline` (`base.html:257`) → ~2:1 on white. `.empty-msg{color:var(--text-faint)}` (`base.html:266`) proves it is information-bearing text. |
| Rename modal has no Esc / focus-on-open / focus-restore | R3 A2 | **YES** | grep `Escape`/`.focus(`/`activeElement` in `migrate.html` → no modal hits. `openRenameModal()` (`:2341-2390`) never focuses or stores `activeElement`; `closeRenameModal()` (`:2392-2396`) only hides. `aria-modal="false"` confirmed `:514`. |
| `aria-label` on job-progress summary span overrides its live text | R3 A18 | **YES** | `base.html:536-538` `<span id="_job-progress-summary" … aria-label="Job progress summary">` with JS-populated text content — label wins for SR. |
| Dashboard form inputs use adjacent `<label>` with no `for`/`id` | R3 A6 | **YES** | `index.html:15,30,42,48,54,61` are bare `<label>` siblings of unlabelled `<select>`/`<input>`. Contrast: `sanitize.html:78` uses `<label for="san-source">` — the inconsistency is real. |
| `/api/v1/backups` (no slash) → 307 redirect | R2 #7 | **YES** | `index.html:311` POSTs `/api/v1/backups`; route is `@router.post("/")` under `/backups` prefix (`backups.py:142`); `create_app` doesn't set `redirect_slashes=False`, so default 307 applies. (Works; extra round-trip.) |
| `/jobs#<id[:8]>` silently no-ops on miss | R1 #4 | **YES** | `jobs.html:165-170` `getElementById('job-'+hash)` then `if(card){…}` with no else — null = silent. Link uses `[:8]` (`schedules.html:159`, `jobs.html:54`). |
| In-app certainty gloss hard-codes "≥3 captures from ≥2 OS versions" | R5 #8 | **PARTIAL** | `definitions.html:587-589` confirmed verbatim. But these are *policy thresholds* (criteria), not a current-state tally that rots as fixtures land — softer than the AGENTS.md "never hard-code a count" rule targets. Downgraded to minor; see rejected/softened list. |

---

## Deduped, prioritized must-fixes

Merged across all five reports, false positives dropped, ranked by **user-impact × inverse-effort**.
IDs are stable for the synthesis to reference. Severity uses the seed's product lens (operator tool,
not consumer SaaS): **blocker** = wrong/broken UX a real operator hits on a normal path;
**major** = misleads, locks out an input modality, or contradicts the honesty discipline;
**minor** = polish / edge / consistency.

| ID | Issue (merged) | Source findings | Severity | Target file(s) | Fix shape | Effort |
|---|---|---|---|---|---|---|
| **MF-1** | Sanitize result region renders empty grey cards + empty "Substitution audit" table on first load — `class="hidden"` resolves to nothing (no global `.hidden` rule). | R2 #1, R4 #2 (**same bug**) | major | `netcanon/templates/sanitize.html:128` (+ `base.html` `<style>`) | Add `.hidden{display:none}` to `base.html`'s `<style>` (generic, reusable) **or** change `sanitize.html:128` to inline `style="display:none"` and toggle `style.display` in the JS reveal at `:384` (matches the migrate `#mig-result` pattern). Prefer the inline-style route to avoid a new global class that other code might lean on unaudited. | S |
| **MF-2** | Migrate OK banner over-claims: "Validation OK — every path round-trips cleanly" implies deploy-safe + same-vendor round-trip on a cross-vendor result; contradicts the project's own "Certified ≠ deploy-ready" promise; visually contradicts a simultaneous Tier-3 "we dropped N sections" banner. | R5 #1, R5 #2 (**merge**) | major (honesty) | `netcanon/templates/migrate.html:1516` (+ a standing note near `:450`) | Rescope to *"Validation OK — every field that translates maps to a supported path on the target. Review before applying; Netcanon has no deploy path."* Add the one-line review-before-deploy note in the Rendered-output header. Behaviour-preserving copy. | S |
| **MF-3** | `--text-faint` (#888 light / #808088 dark) fails WCAG-AA for normal text, and it is the colour of every empty-state "what next" message + job metadata; the `--accent` focus ring fails the 3:1 UI minimum on light surfaces. | R3 A3, R3 A9, R4 (token-hygiene overlap) | major (a11y) | `netcanon/templates/base.html:53,68,126,257,266` | Darken `--text-faint` to ≈#6e6e6e (light) / lighten to ≈#9a9aa4 (dark) — both theme tokens per the AGENTS.md token rule. For focus: add a dedicated `--focus-ring` token that clears 3:1 on white, used by `input:focus`/`:focus-visible`. (Optional cheap win: point `.empty-msg` at `--text-muted` 7.46:1 instead of `--text-faint` — R3 A9.) | S–M |
| **MF-4** | Card/panel disclosure headers are `<div onclick>` — not in tab order, no role, no `aria-expanded`; keyboard/SR users cannot expand Jobs results, Devices history, or the job-progress panel. | R3 A1 | major (a11y) | `netcanon/templates/jobs.html:56`, `devices.html:124`, `base.html:531` | Convert each to `<button type="button">` (or `role="button" tabindex="0"` + Enter/Space keydown if the flex layout resists); toggle `aria-expanded` inside the existing `toggleJob`/`toggleDevice`/`toggleJobProgress`; add `aria-controls` on the job-panel header. JS toggles already exist. | M |
| **MF-5** | No custom 404/500 page — typo'd URLs and uncaught 500s drop the operator onto unstyled, nav-less JSON, out of the themed shell entirely. | R1 #1 | major | `netcanon/main.py` (`create_app`, ~`:238`) + new `netcanon/templates/error.html` | Register a `StarletteHTTPException` (404) + generic-exception (500) handler that renders a minimal `error.html` extending `base.html` (inherits nav+theme) with one message + a "Back to Dashboard" link. Keep it minimal — do NOT echo exception detail (the codebase already treats that as an anti-pattern). Lands once, reaches desktop too (embedded server). | M |
| **MF-6** | Rename modal — the app's most complex interactive surface — has no Esc-to-close, no focus-on-open, no focus-restore; keyboard/SR focus stays on the obscured trigger. | R3 A2, R3 A7 | major (a11y) | `netcanon/templates/migrate.html:2341` (open), `:2392` (close) | Mirror `kbd-cheatsheet.js`: on open, store `document.activeElement` + focus the close button; on close, restore; add a document-level Esc handler gated on the modal being open. Esc + focus-restore are the must-haves; full trap is optional given the intentional `aria-modal="false"` draggable design (do NOT over-trap). | M |
| **MF-7** | Migrate is a journey dead-end: after Translate, only Copy/Download — no "save as stored config" (which would unlock Diff-against-source) and no "Sanitize this output" hand-off. Plus there is no in-app on-ramp to the troubleshooting / bug-report flow (CODEC_BUG, the third honesty leg, has zero UI surface). | R1 #2, R5 #4 (**merge** — same result-region gap) | major | `netcanon/templates/migrate.html` (result region, ~`:446-475`) | Phase it: (a) **cheap, ship now** — add a result-footer with links to `docs/TROUBLESHOOTING.md` + `BUG_REPORTING.md` ("output missing something or wrong? …") and a "Sanitize this output" link pre-selecting the target vendor; (b) **larger, defer** — "Save as stored config" (new endpoint + desktop parity). Don't conflate the two in one PR. | S (links) / M (save-back) |
| **MF-8** | No `<th scope>` on any table; no skip-link before the 10-link nav; no `sr-only` utility exists to build one. | R3 A5 | minor (a11y) | all table templates; `base.html:348-381` (+ `<style>`) | Add `scope="col"` to every column-header `<th>` (mechanical sweep). Add a visually-hidden-until-focused skip-link as `<body>`'s first child + `id="main"` on `<main>`, plus the `.sr-only` utility class it needs. | S (skip-link) / M (scope sweep) |
| **MF-9** | Icon-only / glyph-only action buttons (`↓` download, `⇄` compare) rely on `title=` alone — not reliably announced, never on touch. | R3 A10, R3 A11 | minor (a11y) | `configs.html:26-50`, `devices.html:288-296`, `jobs.html:118` | Add `aria-label="Download {{filename}}"` / `aria-label="Compare …"` alongside the existing `title`. The remove-device button (`index.html:84`) is the in-app model — it already has `aria-label`. | S |
| **MF-10** | Error toasts + job-failure updates use `role="status"`/`aria-live="polite"` — errors are queued behind whatever the SR is speaking instead of interrupting, and may auto-dismiss (4s) before being read. | R3 A4 | minor (a11y) | `base.html:560,579,526` | When `variant==='error'`, set the toast `role="alert"`/`aria-live="assertive"` for that message (toggle back for info/success), or keep a second always-present `role="alert"` element for errors only. (Job-panel assertive verdict region is the optional M part — defer.) | S |
| **MF-11** | `aria-label` on `#_job-progress-summary` overrides its live numeric text ("3/4 complete") with the static label "Job progress summary" for SR users. | R3 A18 | minor (a11y) | `base.html:538` | Remove the `aria-label` (let text content be read) or move the label to the parent region. One-line. | S |
| **MF-12** | Dashboard form inputs use adjacent `<label>` with no `for`/`id` (label not programmatically associated); migrate/sanitize already do it right. | R3 A6 | minor (a11y) | `index.html:15,30,42,48,54,61`; `devices.html`; `schedules.html` | Add `id` + matching `for=`, or wrap each input in its `<label>`. Mechanical but multi-site. | M |
| **MF-13** | Unexplained matrix jargon reaches operator strings with no gloss or doc link (`canonical`, `device class`, `Tier-3`, and the literal field name `raw_sections`). | R5 #3 | minor | `migrate.html:322,413-415,968-969,2080` | De-jargon `raw_sections` → plain prose ("kept as opaque pass-through"); one-clause gloss on "device class" in the Force tooltip; link the intro to CAPABILITIES/TROUBLESHOOTING (overlaps MF-7's footer link). Do NOT build a glossary subsystem. | S |
| **MF-14** | Terminology drift: same artifact is "config" / "configuration" / "backup file"; same selector is "adapter" / "codec" / "vendor"; raw codec ids (`cisco_iosxe_cli`) leak in some toasts. Migrate says "Source adapter"; Sanitize says "Source vendor" for the same control. | R5 #5 | minor | `configs.html:57-59`, `migrate.html:330,337,392`, `sanitize.html:78`, toast at `migrate.html:1007` | Converge *visible labels only* — keep routes/testids/API fields (`/configs`, `source`/`target`) as contracts. At minimum align migrate+sanitize "Source" label. | M |
| **MF-15** | `.mig-chip.class-*` device-class palette + `#fd7e14` warn badges are raw hex that ignore dark mode; `--badge-partial-*` already exists for the orange (used correctly two lines away). | R4 #3 | minor (consistency) | `migrate.html:24-30,197,312` | Repoint the orange to `var(--badge-partial-bg/fg)` (token exists). For the 7 class chips, add a `[data-theme="dark"]` override block (matches the badge pattern) — or accept as intentional semantic colour (POLISH). | S |
| **MF-16** | Inline per-row async buttons (schedules toggle/delete-confirm, configs delete-confirm, jobs Open) don't disable in flight → double-click races; a second DELETE 404s → false red "Delete failed" toast on a success. | R2 #5 | minor | `schedules.html:257,284`; `configs.html:147`; `jobs.html:176` | Disable the clicked button at the top of each inline handler; treat 404-on-delete-after-success as success. (Verified `configs.html:148-169` has no top-of-handler disable.) | S each |
| **MF-17** | Toast `z-index:9999` < config-viewer modal `10000`: a toast fired while the viewer is open is painted behind it; toast `box-shadow` is inline `rgba(0,0,0,.25)` instead of `var(--shadow-lift)` (too weak in dark). | R4 #8, R4 #4 (**batch** — same `#_toast` element) | minor (consistency) | `base.html:560-563` | Move the inline styles into a `#_toast{}` rule, bump `z-index` to `10001`, use `var(--shadow-lift)`. One small CSS edit serves both. | S |
| **MF-18** | `/jobs#<id[:8]>` deep link silently no-ops when the job aged out of the in-memory store (and the 8-char prefix is non-unique in theory). | R1 #4 | minor | `schedules.html:159`, `jobs.html:54,162-172`, `index.html:115` | Use the full job id in the fragment; show a "job not found / may have aged out" toast when no card matches. (Non-uniqueness is low blast radius for a single-operator tool — the silent-miss is the real fix driver.) | S |
| **MF-19** | Jobs list never polls; a still-running job is frozen at "Still running…" until manual refresh (the live panel only tracks the just-started job in localStorage). | R2 #2 | minor | `jobs.html:142` | Add a "Refresh" button + "this list does not auto-update" hint (S). Do NOT build full interval polling for a single-operator local tool (R2 self-flagged the M variant as over-reach — concur). | S |
| **MF-20** | Configs page lacks the orienting lead paragraph the other pages have; it reads as a terminal list rather than the hub that feeds Diff + Migrate. | R1 #5 | minor | `configs.html:5` | Add a one-line muted intro matching `sanitize.html:54`/`migrate.html:319`. | S |

**Findings I deliberately did NOT promote to must-fix** (acknowledged, lower than the bar above, or
covered by an over-engineering flag): R4 #6/#7/#13 (component extraction — see over-engineering), R4
#9/#10/#11/#12 (dead CSS / tok-triplication / `--pre-*` reuse / `.btn-sm` — pure tidy, no user-visible
change), R2 #3 (injected-row `data-utc` — cosmetic, R3 A19 agrees it's not a11y), R2 #6 (job-panel
retry on `MAX_ERRORS` — acceptable for v1 per R2), R2 #8 (schedule-create full reload — R2 marks
optional), R3 A8/A15/A17 (R3's own POLISH/verify-only notes), R5 #10/#13/#14 (drift-watch / positive
examples). These are fine to fold into opportunistic cleanup but should not gate or expand the PRs above.

---

## Softened / rejected claims (skepticism of the audits)

No top-tier finding was a clean false positive. Two claims I **softened**, and several
self-flagged-POLISH items I **agree should not be must-fixes**:

1. **R5 #8 — certainty numbers in `definitions.html:587-589` — SOFTENED to minor/arguable.**
   Verified the text exists verbatim. But "≥3 real captures from ≥2 OS versions" is a *policy
   threshold* (the definition of the `certified` tier), not a current-state count that rots as
   fixtures accrue. The AGENTS.md "never hard-code a count" rule targets tallies that drift silently
   (e.g. "44 supported xpaths"); a criterion changes only on a deliberate methodology change that
   would itself trigger doc-sync. R5's own over-engineering note already says "removal toward
   qualitative phrasing, not a CI guard." Keep it as a low-priority copy nicety (link to RESULTS.md as
   source of truth), not a honesty defect. **Do not treat as blocker/major.**

2. **R1 #4 non-uniqueness sub-claim — SOFTENED.** The 8-char-prefix *collision* risk is real in
   theory (32 bits) but negligible for a single-operator local tool that holds jobs in an in-memory
   store that ages them out long before thousands accrue. The *silent no-op on an aged-out job* is the
   legitimate driver; I kept the finding (MF-18) but scoped the fix rationale to the silent-miss, not
   the birthday problem.

3. **R4 #1 responsive / `@media` — VERIFIED-but-SCOPED.** The "zero `@media` breakpoints" claim is
   factually correct, and the nav-no-`flex-wrap` overflow at a half-screen split is a real desktop
   hit. But the seed explicitly frames this as a workstation tool, and R4 itself marks the
   mobile-modal-stacking and diff-gutter parts as POLISH. I did **not** promote the responsive work to
   must-fix: the *only* slice with real desktop blast radius is `nav { flex-wrap: wrap }` + wrapping
   wide tables in `overflow-x:auto`, and even that is a comfort fix, not a correctness one. Synthesis
   may include the two-line nav-wrap as an opportunistic buildable-now (it is genuinely safe), but a
   responsive-design pass is out of scope for this review.

4. **Self-flagged POLISH I endorse skipping:** R4's component extraction (`.nc-card`/`.nc-modal`/
   `.btn-sm`), R3's full focus-trap library + `<fieldset>`/`<legend>` rework, R2's interval job
   polling, R5's in-app glossary modal and CODEC_BUG detector. All correctly pre-flagged by their
   authors; I concur.

---

## Over-engineering flags (gold-plating to defer for a self-hostable operator tool)

1. **Shared-component extraction (R4 #3/#6/#7/#13).** Extracting `.nc-card`, `.nc-modal`,
   `.nc-modal-header`, `.btn-sm`, and a `--radius-*` scale is textbook design-system maturity, but it
   touches ~8 templates for **zero user-visible change** and invites regressions in hand-synced
   markup that currently looks coherent. Adopt R4's forward rule ("next new card/modal lands in
   `base.html`") instead. **Defer indefinitely.**

2. **Full responsive / mobile design pass (R4 #1).** No `@media` breakpoints is correct, but a
   mobile-first rework is gold-plating for a workstation operator tool. Cap any work at the two-line
   `nav { flex-wrap: wrap }` + table `overflow-x:auto` wrappers if the synthesis wants a safe comfort
   win; do not stack the rename modal or re-flow the diff grid for phones.

3. **Interval job-polling on `/jobs` (R2 #2 M variant).** A live-polling list for a single-operator
   local tool is more machinery than the surprise warrants. The "Refresh button + hint" is the
   right-sized fix (MF-19).

4. **In-app glossary / help subsystem and a CODEC_BUG detector (R5 #3/#4).** The jargon and
   honesty-on-ramp gaps are real, but the fix is *links to existing docs* + de-jargoning a handful of
   strings (MF-13, MF-7-links) — not a new help-content subsystem or heuristics that guess whether
   output is buggy. The docs are already the source of truth.

5. **Full ARIA focus-trap on the rename modal (R3 A2).** The modal is deliberately non-blocking and
   draggable (`aria-modal="false"`, `migrate.html:514`); over-trapping would fight that design. Esc +
   focus-on-open + focus-restore are the high-value 80% (MF-6); skip the trap library.

6. **A CI guard to keep in-prose certainty numbers honest (R5 #8).** If anything, remove the numbers
   toward qualitative phrasing — adding a guard to police a string that shouldn't carry a tally is
   gold-plating a non-problem.

7. **`title`→`aria-describedby` for *every* tooltip (R3 A17).** The dense forms would get cluttered.
   Promote only the load-bearing source/target/device-type help; leave the rest as `title`.

---

## Buildable-now confirmed (small, safe, behaviour-preserving — ready to implement now)

These are the must-fixes that are a few-line change, isolated, and carry no behaviour risk. The
synthesis should batch the CSS/copy ones and verify the two visible-defect ones (MF-1, MF-2) live
first. Ordered by impact.

1. **MF-1** — sanitize `.hidden` first-load empty cards. One-line: inline `style="display:none"` on
   `#san-result` + toggle `style.display` in the existing reveal (or add `.hidden{display:none}` to
   `base.html`). **Verify live** — highest first-impression payoff.
2. **MF-2** — soften the migrate OK banner copy + add the review-before-deploy note. Pure string
   change at `migrate.html:1516`; honesty-load-bearing.
3. **MF-3** — darken/lighten the `--text-faint` tokens + add a `--focus-ring` token (and optionally
   repoint `.empty-msg` to `--text-muted`). Token-only edits per the AGENTS.md two-block rule.
4. **MF-11** — remove the overriding `aria-label` on `#_job-progress-summary` (`base.html:538`).
5. **MF-10** — error-variant toast → `role="alert"`/`aria-live="assertive"` (`base.html:579`).
6. **MF-9** — `aria-label` on the icon-only download/compare buttons (alongside existing `title`).
7. **MF-17** — toast `z-index:10001` + `var(--shadow-lift)` shadow, moved into a `#_toast{}` rule.
8. **MF-15** — repoint `#fd7e14` orange badges to `var(--badge-partial-*)` (token already exists).
9. **MF-13** (partial) — replace the literal `raw_sections` (`migrate.html:2080`) with plain prose.
10. **MF-16** — disable inline per-row buttons at handler top + treat 404-on-delete-after-success as
    success (small, per-handler).
11. **MF-18** — full job id in the `/jobs#` fragment + "not found / aged out" toast on miss.
12. **MF-20** — Configs lead paragraph (one muted `<p>` matching the other pages).
13. **MF-7 (links slice only)** — result-footer links to TROUBLESHOOTING/BUG_REPORTING + "Sanitize
    this output" link. (The "Save as stored config" half is M and deferred.)
14. **MF-19** — "Refresh" button + "does not auto-update" hint on `/jobs`.

**NOT buildable-now (need a template + handler / multi-site sweep / parity check):** MF-4 (3 sites,
layout-sensitive, M), MF-5 (new `error.html` + app-factory handlers + desktop parity, M), MF-6
(modal focus mgmt + Esc, M), MF-8 (scope sweep across all tables, M), MF-12 (multi-site label
association, M), MF-14 (terminology sweep across several templates, M), MF-7 save-back (new endpoint
+ parity, M).

---

## Cross-references for synthesis

- **Merge pairs:** MF-1 = R2 #1 + R4 #2; MF-2 = R5 #1 + R5 #2; MF-7 = R1 #2 + R5 #4; MF-17 = R4 #8 +
  R4 #4. Do not double-count these in the fix-plan.
- **Token-edit MF-3** serves both R3 (a11y) and R4 (consistency) — one PR, two reviewers satisfied.
- **Feature-parity note (AGENTS.md):** MF-5 (error page) and the MF-7 save-back endpoint are *server
  behaviours*, so they reach the desktop platform automatically via the embedded server — but the
  synthesis must still confirm the desktop test tier per the parity checklist before merge.
- **Honesty discipline is load-bearing:** MF-2 and MF-7 directly serve the project's matrix-honesty
  product value; treat them as higher priority than their "minor/major" tag alone suggests when
  sequencing.

# 12 — Accessibility & Semantics audit

**Author:** R3 (audit phase) · **Scope:** `base.html` + the 9 page templates + the modal/job
JS partials (`_partials/config-viewer.js`, `kbd-cheatsheet.js`, `theme-toggle.js`, `job-progress.js`,
`rename-apply.js`).
**Lens:** semantic HTML, labels/ARIA/roles, live regions, keyboard nav + focus management,
WCAG-AA contrast (light **and** dark), text alternatives, table semantics.

This app starts from a *better-than-typical* a11y baseline: the nav uses real `<a>`/`<button>`
elements with `aria-current`, the theme toggle keeps its `aria-label`/`aria-pressed` in sync,
the config-viewer + cheatsheet modals carry `role="dialog"`/`aria-modal`/`aria-labelledby`,
the diff collapsed-context markers are real `<button>`s with `aria-expanded`, the
definitions capability chips are real `<button>`s, the toast + job panel are wired as
live regions, and `<details>`/`<summary>` is used for native disclosure on definitions and
the "advanced" port pins. Credit where due — most of what follows is **gaps in an
otherwise-careful surface**, not a greenfield mess.

The defects cluster into five real themes: (1) **clickable `<div>` card headers** that no
keyboard or screen-reader user can operate; (2) the **migrate rename modal** is missing the
focus-trap/Esc/restore the other two modals have; (3) **`--text-faint` and the focus-ring
accent fail WCAG-AA contrast** in both themes; (4) **error toasts/job-failures are announced
as polite status, not assertive alerts**; (5) **no `<th scope>` on any table** and **no
skip-link**. None is "BROKEN-the-page-is-dead", but #1 and #2 lock keyboard-only and
screen-reader operators out of core flows (Jobs detail, Devices edit/backup, interface rename).

---

## Top 5 (lead findings)

### A1 — Clickable card headers are `<div onclick>` — not keyboard-operable, no role (BROKEN for keyboard/SR)
`netcanon/templates/jobs.html:56` (`.job-card-header` `<div … onclick="toggleJob(this)">`),
`netcanon/templates/devices.html:124` (`.device-card-header` `<div … onclick="toggleDevice(this)">`),
and the global job-progress header `netcanon/templates/base.html:531`
(`<div id="_job-progress-header" … onclick="toggleJobProgress()">`).

These are the *primary* disclosure control for each Jobs card (reveals the per-device
results table) and each Devices card (reveals backup history). A `<div>` with an `onclick`:
- is **not in the tab order** (no `tabindex`), so keyboard-only users can never reach it;
- has **no `role`**, so a screen reader announces inert text, not "button, collapsed";
- responds to mouse click only — Enter/Space do nothing.

The chevron inside is `aria-hidden="true"` (correct, decorative) but there is no
`aria-expanded` to convey state. Note the *inner* action buttons on the device header
(Backup/Edit/Delete, `devices.html:136-153`) ARE real buttons and call
`event.stopPropagation()` — so the row's own buttons work; it's only the
expand/collapse affordance that's dead for keyboard users.

**Fix shape:** convert each header to `<button type="button">` (or add
`role="button" tabindex="0"` + an Enter/Space `keydown` handler if the flex layout makes a
`<button>` awkward) and toggle `aria-expanded` in `toggleJob`/`toggleDevice`/`toggleJobProgress`
to mirror `body.style.display`. The job-progress header additionally needs `aria-controls`
pointing at `_job-progress-body`. **Effort: M** (3 sites, layout-sensitive, but the JS toggles already exist).

### A2 — Migrate "Interface rename" modal has no Esc, no focus trap, no focus restore (A11Y, core flow)
`netcanon/templates/migrate.html:513` (`<div id="mig-rename-modal" role="dialog" aria-modal="false">`),
opened by `openRenameModal()` at `migrate.html:2341` and closed by `closeRenameModal()` at
`migrate.html:2392`.

Compared with the two well-behaved modals (config-viewer + cheatsheet), this one — the most
complex interactive surface in the app (5 rename panes, dropdowns, editable rows) — is missing
every modal-a11y affordance:
- **No Esc-to-close handler** anywhere (`grep Escape` in `migrate.html` and `rename-apply.js`
  returns nothing). Operators escape every other modal with Esc; this one traps them.
- **No initial focus move** — `openRenameModal()` shows the modal but never focuses anything
  inside it, so a keyboard/SR user's focus stays on the now-obscured "Interface rename"
  trigger button behind the overlay.
- **No focus restore** on close — focus is never returned to the trigger.
- **No focus trap** — Tab walks straight out of the modal into the page underneath.
- `aria-modal="false"` is *intentional* (the modal is draggable and non-blocking by design,
  per the comment at `migrate.html:86-87`), which is a defensible product choice — but it
  makes the missing keyboard escape hatch worse, not better, because the page behind stays
  interactive and focus can wander anywhere.

The header close button (`migrate.html:527`) has `aria-label="Close"` (good) but the grip
glyph and "Reset all"/Cancel/Apply are reachable only if you can Tab into the modal at all.

**Fix shape:** mirror `kbd-cheatsheet.js`'s pattern — on open, `closeBtn.focus()` (or focus
the first rail button) and remember `document.activeElement` to restore on close; add a
document-level `keydown` Esc handler that calls `closeRenameModal()` when the modal is open;
add a lightweight focus-trap (wrap Tab at first/last focusable). Esc + focus-restore are the
must-haves; full trap is nice-to-have given the non-blocking design. **Effort: M.**

### A3 — `--text-faint` fails WCAG-AA for normal text in BOTH themes; focus-ring accent fails 3:1 UI contrast (A11Y, palette-wide)
`netcanon/templates/base.html:53` (`--text-faint: #888888` light),
`base.html:126` (`--text-faint: #808088` dark), and the focus ring
`base.html:257` (`input:focus { outline: 2px solid var(--accent) }`, `--accent: #7eb8f7`).

Measured ratios (sRGB, WCAG 2.x):
| Pair | Ratio | AA normal text (4.5) | UI/large (3.0) |
|---|---|---|---|
| `--text-faint` #888 on `--surface` #fff | **3.54** | FAIL | ok |
| `--text-faint` #888 on `--surface-alt` #fafafa | **3.40** | FAIL | ok |
| `--text-faint` #888 on `--page-bg` #f5f5f5 | **3.25** | FAIL | ok |
| dark `--text-faint` #808088 on `--surface` #1e1e1e | **4.26** | FAIL (marginal) | ok |
| `--accent` #7eb8f7 focus ring vs white surface | **2.08** | — | **FAIL (3.0)** |
| diff line-num #555 on `#1e1e1e` body (`diff.html:53`) | 2.24 | FAIL | FAIL |

`--text-faint` is not decorative-only — it's the colour of `.empty-msg` (every empty state:
"No backup jobs yet", "No device profiles yet", "No schedules yet"), the
`.jp-icon-queued`/`jp-duration` job-panel metadata, job-card timestamps' "Manual" trigger,
the "(optional)" hints, the Devices "N backup(s)" count, config-row host in the compare
picker, and the migrate empty-pane explanatory paragraphs. These are real, information-bearing
text. The focus ring at 2.08:1 means keyboard users on light backgrounds can barely see where
focus is — and `base.html:226` even sets `outline:none` on the nav icon buttons, relying on a
subtle background tint that is itself low-contrast.

**Fix shape:** darken `--text-faint` to ~#6e6e6e (≈4.6:1 on white) light / lighten to ~#9a9aa4
dark; these are theme tokens so one edit each side per the AGENTS.md token rule. For the focus
ring, either pair the accent outline with a contrasting `outline-offset` + dark companion, or
add a second darker focus token used specifically for `:focus-visible` outlines so the ring
clears 3:1 against white. Leave `--accent` for nav (8.19:1 on navy — fine there). **Effort: S
for the token tweaks; M if you add a dedicated focus-visible token + audit the `outline:none`
sites.**

### A4 — Error/failure async updates announced as polite `status`, not assertive `alert` (A11Y)
`netcanon/templates/base.html:560` (`<div id="_toast" role="status" aria-live="polite">`) and
`base.html:526-530` (`<div id="_job-progress" role="region" aria-live="polite">`).

`showToast(msg, 'error')` (`base.html:579`) reuses the single `#_toast` element regardless of
severity — the only differentiator is a CSS class for colour. Because the live region is
`role="status"`/`aria-live="polite"`, an **error** message ("Error: host: invalid IPv4",
"Network error", "Delete failed", "Sanitize failed") is queued behind whatever the SR is
already speaking instead of interrupting — exactly backwards for an error. Errors that
disappear after a 4-second timeout (`base.html:588`) may never be announced at all if the SR
was mid-utterance. Likewise the job-progress panel's terminal "failed" state and per-device
error rows (`job-progress.js:79-87`) update inside a `polite` region, so a failed backup is
announced (if at all) as a low-priority status change.

**Fix shape:** when `variant === 'error'`, set the toast's `role="alert"` /
`aria-live="assertive"` for that message (toggle back to `status`/`polite` for info/success),
OR keep a second always-present `role="alert"` element used only for errors. For the job
panel, consider a small assertive live region that announces the terminal verdict
("Backup completed: 3/4 succeeded — 1 failed"). **Effort: S** (toast), **M** (job-panel summary).

### A5 — No `<th scope>` on any table; no skip-link to bypass nav (A11Y)
**Scope:** zero `scope=` attributes exist across all templates (`grep scope=` → 0). Tables with
real header rows include: dashboard recent-jobs (`index.html:108`), configs
(`configs.html:9`), jobs per-device results (`jobs.html:95`), schedules (`schedules.html:115`),
devices config-history (`devices.html:268`), sanitize audit (`sanitize.html:169`), definitions
device/overlay/profile/vendor tables, and the migrate rename table (`migrate.html:247`). All
use `<th>` in a `<thead><tr>` (column headers), so the correct, cheap fix is
`<th scope="col">` on each. Without it, SR users navigating cells lose the
header→cell association on wide tables (the schedules table has 7 columns, definitions vendor
table 5).

**Skip-link:** `base.html:348-381` renders the `<nav>` (10 links + 2 buttons) before `<main>`
with no "Skip to main content" link, so every keyboard/SR user re-traverses the entire nav on
every page load. `<main>` exists (`base.html:379`) but has no `id` to target.

**Fix shape:** add `scope="col"` to every `<th>` in a column-header row (mechanical; M only
because of the number of sites). Add a visually-hidden-until-focused skip-link as the first
child of `<body>` (`<a href="#main" class="skip-link">Skip to main content</a>`) and
`id="main"` on `<main>`. **Effort: S** (skip-link), **M** (scope sweep).

---

## Findings table

| # | Path:Line | Severity | Finding | Fix shape | Effort |
|---|---|---|---|---|---|
| A1 | `jobs.html:56`, `devices.html:124`, `base.html:531` | A11Y / BROKEN | Card/panel disclosure headers are `<div onclick>` — not tabbable, no role, no `aria-expanded`, Enter/Space dead | `<button>` (or `role=button tabindex=0` + keydown); toggle `aria-expanded`; `aria-controls` on job-panel header | M |
| A2 | `migrate.html:513`, `:2341`, `:2392` | A11Y | Rename modal: no Esc, no initial focus, no focus restore, no trap | Mirror cheatsheet: focus-on-open, store/restore activeElement, document Esc handler, light trap | M |
| A3 | `base.html:53`, `:126`, `:257` | A11Y | `--text-faint` 3.25–3.54:1 (light) / 4.26:1 (dark) fails AA normal text; `--accent` focus ring 2.08:1 fails 3:1 | Darken/lighten `--text-faint` tokens; dedicated focus-visible token clearing 3:1 | S–M |
| A4 | `base.html:560`, `:579`, `:526` | A11Y | Error toasts + job failures use `aria-live=polite`/`role=status` — errors not announced assertively | `role=alert`/`aria-live=assertive` for error variant; assertive job-verdict region | S–M |
| A5 | all tables; `base.html:348-381` | A11Y | No `<th scope>` on any table; no skip-link before nav | `scope="col"` sweep; visually-hidden skip-link + `id=main` on `<main>` | S–M |
| A6 | `index.html:16`, `:31`, `:43`…; `devices.html:27`…; `schedules.html:28` | A11Y | Form inputs use **adjacent** `<label>` with no `for`/`id` (label not programmatically associated). Sanitize + migrate DO use `for=` correctly | Wrap input in label, or add `id` + `for=` to every form-group | M |
| A7 | `migrate.html:514` | A11Y (verify) | `aria-modal="false"` is intentional (draggable non-blocking) but combined with A2 leaves no keyboard exit; confirm the product intent vs SR expectation | Keep `false` but add Esc + focus mgmt (A2); document the choice | S |
| A8 | `diff.html:281-285` | A11Y | Collapsed-marker keydown handler doesn't update `aria-expanded` before the button removes itself — and the `<template>` siblings are inert; minor. Marker IS a real focusable button (good) | On expand, the marker is removed so state is moot; acceptable — note only | — |
| A9 | `base.html:266` `.empty-msg` uses `--text-faint` + `font-style:italic` | A11Y | Empty-state copy (core "what next" guidance) is the lowest-contrast text in the app (see A3) and italicised, compounding low legibility | Use `--text-muted` (7.46:1) for `.empty-msg` instead of `--text-faint` | S |
| A10 | `configs.html:26-50`, `devices.html:288-296`, `jobs.html:118` | A11Y / CONFUSING | Icon-only action buttons (`↓` download `&#8595;`, `⇄` compare `&#8644;`) rely on `title=` only — no `aria-label`. `title` is not reliably announced and never on touch | Add `aria-label="Download {{filename}}"` / `aria-label="Compare …"` alongside `title` | S |
| A11 | `index.html:84` remove-device `&#x2715;`, `migrate.html:531` close `&#10005;` | A11Y | Glyph-only buttons: remove-device HAS `aria-label` (good); some rename/cv glyph buttons have `aria-label`, verify all. Config-viewer prev/next/close all carry `aria-label` (good) | Audit each glyph button for `aria-label`; remove-device is the model | S |
| A12 | `schedules.html:62-71`, `:79-96` | A11Y | Two checkbox groups ("Target by Device Type", "Target Specific Devices") use `<h3>` headings, not `<fieldset>`/`<legend>` — group semantics lost for SR | Wrap each group in `<fieldset>` with `<legend>` (can visually restyle to match the h3) | M |
| A13 | `base.html:560` toast text | A11Y | `aria-atomic="true"` is correct on toast; but the persistent error icon/text inside job rows uses `title=result.error` only (`job-progress.js:82`), truncated text + tooltip — full error not SR-reachable | Keep title; ensure the visible truncated text + a screen-reader-only full-text span, or link to job detail | S |
| A14 | `base.html:267` `pre`, `diff.html:43` `.diff-body`, `migrate.html:60` `pre.mig-output` | A11Y (verify) | Code/diff/output `<pre>` blocks are `overflow:auto` scroll containers but not focusable (`tabindex`), so keyboard users can't scroll long output without a mouse | Add `tabindex="0"` + a label (`role="region" aria-label="…"`) to long scrollable code panes | S |
| A15 | `index.html:67`, `devices.html:74`, `schedules.html` `<details>` "⚙ Port" `<summary>` | POLISH | `list-style:none` + custom gear glyph on `<summary>` removes the native disclosure triangle; native keyboard works but the affordance reads as a link not a toggle. `<details>` keyboard behaviour intact | Optionally add `aria-label`/visible caret; native behaviour is fine — low priority | S |
| A16 | `base.html:204-226` nav icon buttons set `outline:none` on `:focus-visible`, replacing with low-contrast tint | A11Y | Focus indicator for the `?` + theme-toggle buttons is a `rgba(255,255,255,.08)` background (very low contrast on the navy nav) instead of a visible outline | Keep a visible focus ring (e.g. `outline:2px solid var(--nav-accent)`) instead of `outline:none` | S |
| A17 | `sanitize.html:79`, `migrate.html:331/338` `<select>` with `title=` long help | POLISH | Long explanatory `title=` tooltips on selects/inputs are the primary help text but are mouse-hover-only and not SR-announced as descriptions | Promote load-bearing `title` help to `aria-describedby` pointing at a visible/`sr-only` hint, or a help `<span>` | M |
| A18 | `base.html:539` `#_job-progress-summary` `aria-label="Job progress summary"` on a span that ALSO has text content | A11Y | `aria-label` on the summary span OVERRIDES its visible text content for SR — the live numeric summary ("3/4 complete") is replaced by the static label "Job progress summary" | Remove the `aria-label` (let the text content be read), or move the label to the parent region | S |
| A19 | `index.html:106` jobs table `style="display:none"` when empty | A11Y (verify) | Empty-state pattern hides the `<table>` and shows a `<p>` — correct; but injected rows (`injectJobRow`) build `<td>` without `data-utc` localisation re-run — cosmetic, not a11y | none (note) | — |
| A20 | `base.html:2` `<html lang="en">` | OK | `lang` is set correctly; document title per page via `{% block title %}` — good baseline | none | — |

---

## Theme-by-theme contrast detail (A3 backing data)

Light mode (`base.html:45-109`):
- `--text-primary #222` on `--surface #fff` → ~15.9:1 (AAA, fine).
- `--text-muted #555` on `#fff` → **7.46:1** (AAA, fine) — this is the right floor.
- `--text-faint #888` on `#fff / #fafafa / #f5f5f5` → **3.54 / 3.40 / 3.25:1** → fails AA(4.5).
- `--btn-secondary-fg #383d41` on `--btn-secondary-bg #e2e3e5` → 8.55:1 (fine).
- Focus ring `--accent #7eb8f7` vs `#fff` → 2.08:1 → fails the 3:1 non-text UI minimum.

Dark mode (`base.html:118-171`):
- `--text-primary #e8e8ea` on `--surface #1e1e1e` → ~13:1 (fine).
- `--text-muted #b0b0b8` on `#1e1e1e` → 7.74:1 (fine).
- `--text-faint #808088` on `--surface #1e1e1e` → **4.26:1** → marginally fails AA(4.5);
  passes 4.78:1 on `--page-bg #121212` only. Inconsistent — bump it.
- Badge fg/bg pairs were retuned for dark (`base.html:148-160`) and the comment claims
  "WCAG 4.5:1 body-text contrast" — spot-check `--badge-completed-fg #a8e6b8` on
  `--badge-completed-bg #183e23` etc. is plausible; the badges are the *careful* part. The
  gap is specifically `--text-faint` and the focus ring, not the badges.

The diff body's hard-coded `#555` line numbers on `#1e1e1e` (`diff.html:52-54`, 2.24:1) and
`#777` collapsed-range text on `#2a2a3e` (`diff.html:75`, 3.13:1) are below AA, but line
numbers/range hints are arguably decorative-secondary; flag as POLISH, fix opportunistically.
Note these are **raw hex, not tokens** — they also won't re-theme, but the diff body is
intentionally always-dark (VS Code palette) per the design, so theme drift isn't the issue,
contrast is.

---

## What's already correct (don't "fix" these)

- `base.html:2` `lang="en"`; per-page `<title>`.
- Nav links are real `<a>` with `aria-current="page"` on the active item (`base.html:351-358`).
- Theme toggle keeps `aria-label` + `aria-pressed` in sync via `theme-toggle.js:32-43`;
  glyph swap is CSS-only so no DOM thrash; `aria-hidden` on the decorative sun/moon spans.
- Config-viewer modal (`base.html:384`) + cheatsheet modal (`base.html:415`):
  `role="dialog" aria-modal="true" aria-labelledby`, Esc handling, search-count is a
  `aria-live="polite"` region, every glyph button has `aria-label`. Cheatsheet focuses its
  close button on open (`kbd-cheatsheet.js:36`). **This is the model A2 should copy.**
- Diff collapsed markers are real `<button type="button">` with `aria-expanded="false"` and a
  descriptive `aria-label` (`diff.html:192-196`) + Enter/Space keydown belt-and-braces
  (`diff.html:281`).
- Definitions capability chips are real `<button type="button">` with `disabled` when count=0
  and `aria-expanded` toggled on the active bucket (`definitions.html:649-677`, `:906`).
- Definitions disclosure uses native `<details>`/`<summary>` throughout — zero-JS, full
  native keyboard + SR behaviour (`definitions.html:4-18` documents this intentionally).
- Decorative glyphs (`mig-arrow`, chevrons, grip, spacer) carry `aria-hidden="true"`.
- The `?` cheatsheet handler correctly bails when a text-editable field is focused
  (`kbd-cheatsheet.js:75-93`) — doesn't hijack literal `?` typed into forms.
- `formatApiError` (`base.html:602`) renders Pydantic 422 arrays into readable field-prefixed
  messages — so the error *content* is good once it's announced (A4 is about *how*, not *what*).

---

## Over-engineering / scope caution flags

- **Don't add a full ARIA focus-trap library or `inert`-polyfill** for A2 — the modal is
  deliberately non-blocking/draggable (`migrate.html:86-87`). Esc + focus-on-open +
  focus-restore are the high-value 80%; a perfect trap is optional given `aria-modal="false"`.
  Over-trapping would actually fight the drag-aside design.
- **Don't migrate the diff/output `<pre>` palettes to theme tokens** for contrast — they're
  intentionally always-dark VS-Code-style panes (documented). The fix is the specific low
  ratios (line numbers), not a re-theming churn.
- **`<fieldset>`/`<legend>` (A12)** is correct semantics but a `<fieldset>` brings default
  border/padding/legend-positioning baggage; restyling to match the current `<h3>` look is the
  bulk of the effort. Right-sized: do it, but it's M not S, and it's lower priority than A1/A2.
- **A17 (`title`→`aria-describedby`)**: the long `title` tooltips are genuinely useful help
  text, but converting *every* one to a visible/`aria-describedby` hint risks cluttering the
  dense forms. Prioritise the load-bearing ones (source/target adapter, device-type) and leave
  the rest as `title`. Flag as POLISH-leaning-M.
- A8 / A19 are noted for completeness but are non-defects — don't spend fix budget there.

---

## Cross-references
- IA/nav peer (`10-ia-navigation.md`): skip-link (A5) and the nav focus ring (A16) overlap
  with nav structure.
- Visual-consistency peer (`13-visual-consistency.md`): the `--text-faint` token (A3/A9) and
  the raw-hex diff palette are shared territory — contrast fix is a11y, token-hygiene is theirs.
- State-coverage peer (`11-state-coverage.md`): the error-toast `aria-live` (A4) and job-panel
  live region intersect their async-state findings; `.empty-msg` legibility (A9) is shared.

# 13 — Visual design system & consistency audit

**Agent:** R4 (audit) · **Scope:** the inline design system in `base.html`, token discipline, component
consistency, dark-mode coverage, responsive behaviour, visual hierarchy/density. Read-only; cites
repo-relative `file:line`.

**Surface read in full:** `base.html` (650L), `index.html`, `configs.html`, `diff.html`,
`definitions.html`, `devices.html`, `migrate.html` (2477L, markup + `<style>`), `sanitize.html`,
`jobs.html`, `schedules.html`. Cross-checked against `ARCHITECTURE.md` § "Theming (dark mode)"
(the three load-bearing rules + the explicit "incremental migration of edge-case declarations is
tolerated" carve-out) and `AGENTS.md`'s doc-sync row mandating `var(--token)` for any new colour.

## Headline

**The design system is genuinely good and the token discipline is mostly real.** `base.html` ships a
single, well-curated `:root`/`[data-theme="dark"]` token set (`base.html:45-171`); every page's
page-scoped `<style>` block leads with a comment asserting "all colours flow through tokens" and, for
the most part, honours it. Dark mode is a first-class, FOUC-free design (`base.html:13-32`), and the
recently-completed tokenization sweep (visible in the per-page "pre-tokenization this stayed light"
comments) closed the worst dark-mode bugs. This is **not** a hex-soup codebase.

The real defects are narrower and concentrated:

1. **No responsive design at all** — zero `@media` breakpoints anywhere in the app. The nav, the dense
   `migrate.html` rename modal, the diff grid, and the wide tables (`configs`, `schedules`,
   `definitions`) all assume a desktop-width viewport and overflow/clip below ~700px. This is the
   single biggest visual-consistency gap.
2. **A residual hardcoded-hex island that does NOT honour dark mode** — the `.mig-chip.class-*`
   device-class palette (`migrate.html:24-30`) and the `#fd7e14` orange "warn count" badges
   (`migrate.html:197,312`) render identically in both themes; on dark surfaces they read as
   light-mode pills, exactly the failure the tokenization sweep set out to kill.
3. **Component fragmentation** — there is no shared component CSS beyond `base.html`'s primitives.
   Every page re-invents its own card (`device-card`, `job-card`, `defs-section`, `mig-result-section`,
   `san-result-section`), its own chip/pill (`type-chip`, `mig-chip`, `defs-pill`, `defs-port-chip`,
   `san-chip`, `rail-count`), and its own modal shell (config-viewer, kbd-cheatsheet, compare-picker,
   rename-modal — four near-identical-but-divergent dark-header dialogs). They look like one family
   today only because the same author kept them in sync by hand.

None of these are `BROKEN` in the "UX is dead" sense — the app works on a desktop browser. They are
`INCONSISTENT` / `POLISH` with one `A11Y`-adjacent responsive concern. The honesty discipline is not
implicated by visual consistency (microcopy is R5's lane).

---

## Top 5 findings (lead)

### 1. No `@media` breakpoints — the entire app is desktop-only `[INCONSISTENT]` (effort M)

`grep '@media'` over `netcanon/templates/` returns **zero matches**. Every layout primitive assumes a
wide viewport:

- **Nav** (`base.html:191`): `nav { ... display: flex; gap: 1.5rem; ... }` with **no `flex-wrap`**.
  It hosts brand + 9 links (`Dashboard … API Docs`) + spacer + 2 icon buttons (`base.html:350-377`).
  Below roughly 760px these overflow the viewport horizontally — the right-rail theme toggle and "?"
  button push off-screen or force a horizontal scrollbar on the whole page. The `nav` horizontal
  padding `max(1rem, calc(50vw - 550px))` (`base.html:191`) correctly collapses to a 1rem gutter on
  narrow screens, but that only helps if the *content* wraps, which it can't.
- **`migrate.html` rename modal**: fixed `width:min(1100px,94vw)` (`migrate.html:89`) with a 3-column
  body — `#mig-rename-rail` 140px + `#mig-rename-table-pane` `min-width:400px` (`migrate.html:203`) +
  `#mig-rename-preview-pane` `min-width:300px` (`migrate.html:211`). 140+400+300 = 840px of hard
  minimums inside a 94vw box: below ~890px the panes overflow their container and the preview pane
  clips. There is no stacking fallback.
- **`diff.html` diff grid** (`diff.html:48-51`): `.diff-line { display:grid;
  grid-template-columns:3.5rem 3.5rem 1.2rem 1fr; ... white-space:pre; }`. The two 3.5rem gutters +
  marker are fine, but `white-space:pre` on the text column means long config lines never wrap; the
  `.diff-body` is `overflow:auto` (`diff.html:46`) so it scrolls horizontally — acceptable on
  desktop, painful on mobile where the whole 7rem of line-number gutter eats the viewport before any
  config text shows.
- **Wide tables**: `configs.html` (6 cols incl. a 4-button Actions cell), `schedules.html` (7 cols),
  `definitions.html` (7-col definitions table + vendor-codec table). `base.html`'s `table { width:100% }`
  (`base.html:242`) means they shrink-to-fit but the `white-space:nowrap` Actions cells
  (`configs.html:25`, `devices.html:287`) force horizontal overflow with no scroll container — the
  table just pushes past `main`'s `padding:0 1rem` and triggers page-level horizontal scroll.

**Fix shape:** add one `@media (max-width: 760px)` block in `base.html` that (a) gives `nav`
`flex-wrap:wrap`, (b) wraps wide tables in an `overflow-x:auto` container or sets them to
`display:block; overflow-x:auto` on narrow screens, and (c) in `migrate.html` collapses the
3-pane modal to a stacked single column (`flex-direction:column` on `#mig-rename-modal-body`,
drop the `min-width`s to `0`). This is the highest-leverage single change; **per the seed, mark the
mobile-modal stacking as `POLISH`** (operators run this tool on a workstation) but the **nav-wrap and
table-overflow are real** because even desktop users at a narrowed/split window hit page-level
horizontal scroll.

### 2. `.mig-chip.class-*` device-class palette + `#fd7e14` badges ignore dark mode `[INCONSISTENT]` (effort S)

`migrate.html:24-30` hardcodes seven device-class chip backgrounds in raw hex:

```css
.mig-chip.class-switch          { background:#0c5460; }
.mig-chip.class-router          { background:#155724; }
.mig-chip.class-firewall        { background:#721c24; }
.mig-chip.class-load_balancer   { background:#7a5d00; }
.mig-chip.class-wireless_controller { background:#3d195a; }
.mig-chip.class-access_point    { background:#44085a; }
.mig-chip.class-waf             { background:#6a1f0b; }
```

These are reasonable dark-ish hues with white text, so they happen to read OK in *both* themes — but
they're frozen: they don't retune contrast for the dark `--surface`, and they violate the AGENTS.md
hard rule ("a new raw hex that only works in light mode WILL look wrong in dark mode"). The same goes
for the two `#fd7e14` orange "warn-count" badges with `color:#fff` (`migrate.html:197` rail-badge-warn,
`migrate.html:312` `.badge-count`) — these are the *only* warm-orange in the app, sit on dark and light
surfaces alike, and don't track `--badge-partial-*`. **Note:** the same warm-amber semantic *does* have
tokens (`--badge-partial-bg/fg`) which are used correctly two lines away (`migrate.html:127-128`,
`241`), so this is an inconsistency *within a single file*.

**Fix shape:** either (a) accept the device-class palette as intentional semantic colour and add a
short `[data-theme="dark"]` override block for the seven classes (cheapest, matches the badge
pattern), or (b) for the orange badges, switch to `var(--badge-partial-bg)/var(--badge-partial-fg)`.
The device-class colours are arguably `POLISH` (they read acceptably); the orange `#fd7e14` is a
clearer `INCONSISTENT` because a token already exists.

### 3. No shared component layer — every page re-invents card / chip / modal `[INCONSISTENT]` (effort L)

`base.html` exposes only *primitives*: `.badge`, `.btn-primary/secondary/danger`, `table`, `form`,
`.alert`, `.empty-msg`, `pre`. There is no shared `.card`, `.chip`, or `.modal`. Consequently:

- **Cards** are redefined three times with near-identical rules: `.device-card` (`devices.html:8`),
  `.job-card` (`jobs.html:10`), `.defs-section` (`definitions.html:38`), plus `.mig-result-section`
  (`migrate.html:53`) and `.san-result-section` (`sanitize.html:26`). All five are
  `background:var(--surface); border-radius:6-8px; box-shadow:var(--shadow-card)` — the *same*
  component spelled five ways. Radii diverge: cards use `6px` (`devices`, `jobs`,
  `mig-result-section`) vs `8px` (`defs-section:42`), and modals use `8px`. No token governs radius.
- **Chips/pills** appear in at least seven flavours: `.badge` (base), `.diff-chip`/`.diff-role-label`
  (`diff.html:11,21`), `.mig-chip` (`migrate.html:18`), `.defs-pill`/`.defs-port-chip`/`.defs-caps-chip`
  (`definitions.html:174,132,212`), `.type-chip` (`configs.html:89`), `.san-chip` (`sanitize.html:44`),
  `.rail-count`/`.badge-count` (`migrate.html:188,311`). Each picks its own padding, radius (`3px`,
  `4px`, `8px`), and font-size (`.68`–`.8rem`).
- **Modals**: four dialogs share the *exact* same shell idea (fixed inset-0 backdrop
  `rgba(0,0,0,.55)`, `var(--surface)` box, `var(--shadow-modal)`, dark navy header) but each is
  hand-written: config-viewer (`base.html:276`), kbd-cheatsheet (`base.html:307`), compare-picker
  (`configs.html:68`), rename-modal (`migrate.html:87`). They diverge in header padding
  (`.5rem 1rem` vs `.65rem 1rem` vs `.55rem .8rem`), `z-index` (`10000` for three, `9500` for the
  rename-modal — see finding 8), and close-button styling.

**Fix shape:** extract `.nc-card`, `.nc-chip`, `.nc-modal` / `.nc-modal-header` into `base.html` and
have pages opt in. **This is a refactor, not a bug fix** — flag it `POLISH`. The seed explicitly says
"this is a review, not a redesign," so the recommendation is: *don't* do the big extraction now, but
treat `base.html` as the home for the next shared component rather than adding a 6th bespoke card.

### 4. Diff "to" role-label colour `#0b6e37` is a one-off green, not a token `[INCONSISTENT]` (effort S)

`diff.html:26`: `.diff-role-label.to { background:#0b6e37; }` — a bespoke mid-green used nowhere else,
while the rest of the diff stats correctly use `--badge-completed-fg` for "added" (`diff.html:30`).
The "from" label uses the dark-navy `#1a1a2e` (`diff.html:24`) which is the documented intentional
chrome colour, but the "to" green is unmanaged. In dark mode the green stays the same mid-tone against
a different body, and its `color:#eee` (inherited from the base `.diff-role-label` rule) gives a
contrast that wasn't tuned for dark. **Fix shape:** point it at a token (`--badge-completed-fg` family,
or add a `--role-to` token to both `:root` and dark). Small, isolated.

### 5. Hardcoded toast box-shadow bypasses the shadow token `[INCONSISTENT]` (effort S)

The toast element (`base.html:560-563`) is styled with an **inline** `box-shadow:0 2px 8px
rgba(0,0,0,.25)` rather than `var(--shadow-lift)`. The job-progress panel right next to it correctly
uses `box-shadow:var(--shadow-lift)` (`base.html:470`), and `--shadow-lift` in dark mode is
`0 2px 10px rgba(0,0,0,.55)` (`base.html:166`) — deliberately stronger because shadows vanish on the
off-black base. So in dark mode the toast's shadow is *too weak* relative to every other elevated
surface. The toast colour pair is correctly tokenized via `.toast-*` classes (`base.html:522-524`,
matching ARCHITECTURE rule 3) — only the shadow leaked. **Fix shape:** move the inline styles into a
`#_toast { ... }` rule (there's already a `<style>` block at `base.html:465-525`) and use
`var(--shadow-lift)`.

---

## Detailed findings by evaluation axis

### (1) Token discipline

**Verdict: strong, with a documented-tolerated tail.** The `:root` token set
(`base.html:45-109`) is comprehensive: page/surface/text/border (incl. `surface-alt`, `surface-elev`,
`surface-hover` for elevation steps), full nav palette, three button variants × bg/hover/fg, a
five-state badge palette, alert-info pair, three shadow tiers, and a `--pre-*` code-viewer pair. The
`[data-theme="dark"]` block (`base.html:118-171`) overrides every one. Page `<style>` blocks
overwhelmingly reference `var(--...)`.

**Genuine raw-hex divergences (colour, not glyph entities):**

| Where | Hex | Disposition |
|---|---|---|
| `migrate.html:24-30` | `.mig-chip.class-*` 7 device-class bgs | **INCONSISTENT** — frozen, finding 2 |
| `migrate.html:197,312` | `#fd7e14`/`#fff` warn-count badges | **INCONSISTENT** — token exists, finding 2 |
| `diff.html:26` | `#0b6e37` "to" role label | **INCONSISTENT** — finding 4 |
| `base.html:561` | toast `rgba(0,0,0,.25)` shadow | **INCONSISTENT** — finding 5 |
| `migrate.html:108,112` `base.html:280,286,287` | modal-button borders `#444/#333/#555` | tolerated (lives inside the always-dark chrome) |
| `migrate.html:190,194` `definitions...` | `rgba(0,0,0,.08)`, `rgba(255,255,255,.18)` rail-count bgs | tolerated (tints on fixed-dark active button) |

**Intentional, doc-sanctioned hex (NOT defects):** the dark code/header chrome — `#1a1a2e` (nav navy,
reused for every modal header and the `mig-chip` base / `diff-role-label` "from"), `#1e1e1e`/`#d4d4d4`
(`pre` / diff-body / mig-output / preview-pane), and the VS-Code "Dark+" `tok-*` syntax palette
(`base.html:291-300`, duplicated verbatim in `diff.html:77-83` and `migrate.html:68-74`). These are
explicitly called out in `base.html`'s own comments (`base.html:57-59, 105-108, 270-275`) and in
ARCHITECTURE.md as intentional "already-dark-in-both-themes" surfaces. The `--pre-bg`/`--pre-fg` tokens
exist (`base.html:107`) but the diff-body and mig-output hardcode `#1e1e1e`/`#d4d4d4` instead of
referencing them — a **missed opportunity, POLISH only**: pointing `.diff-body`/`.mig-output` at
`var(--pre-bg)/var(--pre-fg)` would let a future operator re-theme the code viewer once and have it
propagate. The `tok-*` triplication is the same: three identical copies that should be one rule set,
but it's `POLISH` (they're byte-identical so no drift risk today).

**No magic-`px` problem:** spacing/sizing is almost entirely `rem`-based (`.25rem`–`1.5rem` rhythm).
The few raw `px` values are legitimate fixed widths (`width:72px` port input `index.html:71`;
`width:140px` rail `migrate.html:167`; `min-width:200px` filter `definitions.html:204`) — these are
content-driven, not theme-driven, and don't belong in tokens.

**Radius is the one un-tokenized scale.** Radii are scattered raw: `3px` (chips, small controls),
`4px` (inputs, buttons, alerts), `6px` (tables, forms, cards, pre), `8px` (modals, `defs-section`,
chip pills). There's no `--radius-sm/md/lg`. This is the most defensible *new* token to add — but
`POLISH`, since the values are internally consistent enough that nothing looks wrong.

### (2) Component consistency

- **Buttons** — *consistent and correct.* `.btn-primary/secondary/danger` (`base.html:260-265`) are
  used everywhere; pages override only `font-size`/`padding` inline for compact contexts (e.g.
  `configs.html:28` `font-size:.8rem;padding:.3rem .6rem`). This per-instance sizing is repeated ~30
  times across configs/devices/jobs/schedules with slightly different values (`.3rem .6rem` vs
  `.3rem .7rem` vs `.2rem .5rem`) — visually close but not pixel-identical. **POLISH:** a `.btn-sm`
  modifier in base would replace ~30 inline style attributes. One semantic mismatch worth noting:
  `jobs.html` invents `.btn-link`/`.btn-link-btn` (`jobs.html:27-34`) for the row action links —
  these duplicate `.btn-secondary` with `font-weight:normal`; a `.btn-secondary.btn-sm` would do.
- **Tables** — base `table/th/td` (`base.html:242-245`) is the shared spine; every table uses it.
  `.job-results-table` and `.san-audit-table` (`sanitize.html:36`) re-declare cell padding/border;
  `san-audit-table` even re-implements `border-collapse` and its own `border-bottom` rather than
  inheriting. **POLISH/INCONSISTENT-minor.**
- **Cards** — five divergent definitions (finding 3). **INCONSISTENT.**
- **Badges/pills** — `.badge` + the five `.badge-{state}` classes are the canonical, well-tokenized
  set. But the seven *other* pill/chip variants (finding 3) fragment the look. The schedules
  enabled/disabled badges (`.enabled-badge`/`.disabled-badge` `schedules.html:12-13`) correctly reuse
  `--badge-completed-*`/`--badge-pending-*` tokens — good. The device-type display badge
  (`devices.html:128-129`, `schedules.html:86`) abuses `.badge` with an *inline*
  `style="background:var(--surface-elev);color:var(--text-primary)"` override instead of a class —
  works, but it's the same chip rendered inline twice. **POLISH.**
- **Toasts** — single shared implementation (`base.html:560`, `showToast` `base.html:579`), correctly
  variant-classed. *Consistent* (modulo the shadow leak, finding 5). Good.
- **Modals** — four hand-rolled shells (finding 3). The compare-picker (`configs.html`) and
  rename-modal (`migrate.html`) were clearly cloned from the config-viewer but drifted.
  **INCONSISTENT.**
- **Form controls** — base `input/select/textarea` + `:focus` (`base.html:256-257`) are shared and
  used universally; `.form-row`/`.form-group`/`label` give a consistent stacked-label pattern across
  index/devices/schedules/migrate/sanitize. *Consistent and good.* The focus ring
  (`outline:2px solid var(--accent); border-color:transparent`) is uniform — a real a11y win that
  also reads as visual consistency. (Deeper a11y is R3's lane.)

### (3) Dark mode

**Verdict: comprehensive and well-engineered, with the small leaks already listed.** The boot script
(`base.html:13-32`) eliminates FOUC; the `[data-theme]` gate is the sole switch (no competing
`@media (prefers-color-scheme)` rule blocks); the 150ms colour transition (`base.html:176-180`) is
scoped to colour properties only, avoiding layout judder. Dark-mode badge values are deliberately
re-tuned for WCAG body-text contrast (`base.html:148-160` comment). Shadows step stronger in dark
(`base.html:165-167`). Every page's `<style>` comment documents what dark-mode bug it closed
(e.g. `sanitize.html:16-21` "two token names that aren't declared … fallback hex took effect and the
textarea stayed light"; `configs.html:65-67` "pre-fix the box stayed white"). This is mature work.

**Residual dark-mode leaks** (all minor, all listed above): `.mig-chip.class-*` + `#fd7e14`
(finding 2), `#0b6e37` (finding 4), toast shadow (finding 5), and the missed `--pre-*` reuse. There
are **no full-page dark-mode failures** — I could not find a page that renders light-on-light or
dark-on-dark in either theme. The `definitions.html` defensive fallbacks
(`var(--badge-completed-fg, #22863a)` etc., `definitions.html:239-241,282-283`) are belt-and-braces
and harmless (the token always resolves).

### (4) Responsive

**Verdict: absent.** Covered in finding 1. To restate the concrete clip/overflow risks ranked by
likelihood of a desktop user actually hitting them:

1. **Nav horizontal overflow** (`base.html:191`, no `flex-wrap`) — hits at any window < ~760px,
   including a half-screen split. Most likely to be seen.
2. **Wide-table page-level horizontal scroll** — `configs`/`schedules`/`definitions` Actions cells are
   `white-space:nowrap`; with 4 action buttons (`configs.html:25-50`) the row can't shrink and pushes
   past `main`. Seen on laptops at definitions/configs with long filenames.
3. **Rename-modal pane clipping** (`migrate.html:203,211`, 700px+ of hard `min-width`) — only at very
   narrow widths; the modal is `94vw` so it's mostly OK on laptops. `POLISH` per seed.
4. **Diff line-number gutters eating mobile width** — `POLISH` (mobile isn't the target).

### (5) Visual hierarchy / alignment / density + layout bugs

- **Hierarchy is clean.** `h1` 1.5rem / `h2` 1.15rem / `h3` ~0.95rem (`base.html:240-241`,
  `schedules.html:57`) with consistent muted-grey section intros (`var(--text-muted)`,
  `font-size:.9rem`) on every page's lede (`migrate.html:319`, `sanitize.html:54`,
  `definitions.html:24`). The `--text-primary/muted/faint` three-tier system is applied consistently
  for primary/secondary/tertiary text everywhere. Good.
- **Density is appropriate for an operator tool.** Tables at `.85-.9rem`, monospace for IDs/filenames
  (`.job-id`, `.filename`, `.diff-chip`). The `migrate.html` rename modal is dense but the left-rail
  navigation + collapsible kind-sections manage it well.
- **Layout-bug-class issues found in markup:**
  - **`#mig-rename-modal` double `display` declaration** (`migrate.html:88` `display:none;` then
    `migrate.html:94` `display:none; flex-direction:column;`). Harmless (the `.open` class flips it to
    `flex` at `migrate.html:97`) but it's dead/confusing CSS — the second `display:none` overrides the
    first to no effect. **POLISH** (cosmetic CSS cleanliness).
  - **z-index inconsistency across modals** — config-viewer/kbd-cheatsheet/compare-picker are all
    `z-index:10000` (`base.html:276,307`, `configs.html:70`); the rename-modal is `9500`
    (`migrate.html:89`) and the job-progress panel `9998` (`base.html:467`), toast `9999`
    (`base.html:561`). The rename-modal being *below* the others is intentional (it's a non-blocking
    `aria-modal="false"` draggable window, `migrate.html:514`) — but a toast (9999) and the
    job-progress panel (9998) will paint *over* an open config-viewer (10000)? No — 10000 > 9999, so
    the viewer covers the toast. That means a toast fired while the config-viewer is open is **hidden
    behind the modal**. Minor `INCONSISTENT`/`CONFUSING` edge — toasts should sit above modals. **Fix
    shape:** bump toast to `z-index:10001`.
  - **`sanitize.html` `.hidden` class** — `#san-result` ships `class="hidden"` (`sanitize.html:128`)
    and JS calls `result.classList.remove('hidden')` (`sanitize.html:384`), but **`.hidden` is never
    defined in `sanitize.html` or `base.html`** (the only `.hidden` rule in the app is
    `#mig-result.hidden{display:none}` at `migrate.html:52`, scoped by ID to the migrate page). So on
    the sanitize page the result region is **NOT actually hidden on initial load** — it relies on
    being empty (no children rendered until submit). It happens to look empty, but the
    `.san-result-section` wrappers are static children of `#san-result` (`sanitize.html:129-180`), so
    the **empty status/stats/output/audit cards render visible on page load before any sanitize runs.**
    This is a **real visual bug**: the user sees three empty grey cards + an empty "Substitution audit"
    table on first paint. **Severity: CONFUSING / borderline BROKEN.** **Fix shape:** add a global
    `.hidden { display:none !important; }` to `base.html` (it's referenced as if it were global), or
    change `sanitize.html:128` to inline `style="display:none"` and have the JS clear it. *This is the
    most concrete actionable defect in this report after the responsive gap — recommend the orchestrator
    verify it live.*
  - **Alignment**: `.form-row { align-items:flex-end }` (`base.html:253`) plus the
    `align-self:flex-end` on `<details class="port-details">` (`index.html:67`, `devices.html:74`)
    keeps the collapsed-Advanced gear baseline-aligned with input bottoms — nicely done. No
    misalignment bugs found in the forms.

---

## Findings table

| # | Path:Line | Severity | Finding | Fix shape | Effort |
|---|---|---|---|---|---|
| 1 | `base.html:191` (+ app-wide) | INCONSISTENT | No `@media` breakpoints; nav has no `flex-wrap`, wide tables + rename modal overflow on narrow/split viewports | One `@media(max-width:760px)`: nav `flex-wrap`, table `overflow-x:auto` wrapper, modal pane stack | M |
| 2 | `sanitize.html:128,384` | CONFUSING | `.hidden` class is undefined globally (only `#mig-result.hidden` exists, ID-scoped to migrate); sanitize result region's empty cards render visible on first load | Add global `.hidden{display:none!important}` to base, OR inline `style="display:none"` | S |
| 3 | `migrate.html:24-30,197,312` | INCONSISTENT | `.mig-chip.class-*` palette + `#fd7e14` warn badges are raw hex, don't retune for dark; `--badge-partial-*` already exists for the orange | Add `[data-theme="dark"]` overrides for the 7 chips; repoint orange to `var(--badge-partial-*)` | S |
| 4 | `base.html:561` | INCONSISTENT | Toast `box-shadow` inline `rgba(0,0,0,.25)` bypasses `--shadow-lift`; too weak in dark mode | Move to a `#_toast` rule, use `var(--shadow-lift)` | S |
| 5 | `diff.html:26` | INCONSISTENT | `.diff-role-label.to` `#0b6e37` is a one-off green, untokenized, untuned for dark | Point at `--badge-completed-*` family or add `--role-to` token (both themes) | S |
| 6 | `base.html:276,307`,`configs.html:68`,`migrate.html:87` | INCONSISTENT | Four hand-rolled modal shells share the pattern but drift (header padding, z-index, close-btn) | Extract `.nc-modal`/`.nc-modal-header` to base; opt pages in over time | L (POLISH) |
| 7 | `devices.html:8`,`jobs.html:10`,`definitions.html:38`,`migrate.html:53`,`sanitize.html:26` | INCONSISTENT | Card component re-declared 5×; radius diverges 6px vs 8px; no radius token | Extract `.nc-card`; add `--radius-*` tokens | L (POLISH) |
| 8 | `base.html:561` vs `:276` | CONFUSING | Toast `z-index:9999` < config-viewer `10000`: a toast fired while the viewer is open is hidden behind it | Bump toast to `10001` | S |
| 9 | `migrate.html:88,94` | POLISH | `#mig-rename-modal` has a duplicate `display:none` declaration (dead CSS) | Drop the redundant first `display:none` | S |
| 10 | `base.html:291-300`,`diff.html:77-83`,`migrate.html:68-74` | POLISH | `tok-*` syntax palette triplicated verbatim across 3 files | Hoist to one shared selector list in base | S |
| 11 | `diff.html:44`,`migrate.html:61,211` | POLISH | Code panes hardcode `#1e1e1e`/`#d4d4d4` instead of the existing `--pre-bg`/`--pre-fg` tokens | Repoint to `var(--pre-*)` | S |
| 12 | `jobs.html:27-34` | POLISH | `.btn-link`/`.btn-link-btn` duplicate `.btn-secondary` (compact) | Replace with `.btn-secondary` + a base `.btn-sm` modifier | S |
| 13 | configs/devices/jobs/schedules (~30 sites) | POLISH | Per-instance inline button sizing (`.3rem .6rem` vs `.3rem .7rem` vs `.2rem .5rem`) — visually close, not uniform | Add `.btn-sm` to base; replace inline styles | M (POLISH) |

---

## Over-engineering flags

- **Findings 6, 7, 13 (shared-component extraction)** are genuinely worth flagging as *potential
  over-reach* against the seed's "review not redesign / right-sized not gold-plated" constraint.
  Extracting `.nc-card`/`.nc-modal`/`.btn-sm` is the textbook "design-system maturity" move, but the
  current hand-synced duplication *works* and looks coherent. The risk of a big extraction PR is it
  touches 8 templates for zero user-visible change and invites regressions. **Recommendation:** do NOT
  schedule a component-extraction PR. Instead adopt a forward rule (next new card/modal lands in base)
  and only repoint the cheap, isolated leaks (findings 2,4,5,8,11).
- **Adding a full `--radius-*` / `--space-*` token scale** would be over-engineering for a 10-page
  operator tool — the existing rem rhythm is consistent enough. Skip.
- **The `definitions.html` `var(--token, #fallback)` defensive fallbacks** (`definitions.html:239-241`)
  are mild over-engineering (the token always resolves since base defines it) but harmless — not worth
  touching.

## Buildable-now (small, isolated, low-risk — recommend the orchestrator verify these live first)

These are the findings that are genuinely user-visible *and* a few-line fix, in priority order:

1. **Finding 2 (`sanitize.html` `.hidden`)** — empty cards on first load is a real first-impression
   bug; one-line base.html addition.
2. **Finding 1, nav-wrap slice only** — `nav { flex-wrap: wrap; }` (+ table overflow wrappers) — the
   modal-stacking part can be deferred as POLISH.
3. **Finding 8 (toast z-index)** — toast-behind-modal; one value.
4. **Finding 4 (toast shadow token)** and **Finding 5 (diff `to` green)** — pure token hygiene, no
   behaviour change.

## Cross-references to peer reports

- **R3 (12-accessibility)** owns focus/contrast depth; this report only notes the shared focus ring
  (`base.html:257`) and dark-mode contrast tuning as *consistency* wins. The toast-behind-modal
  z-index (finding 8) and the diff line-number-gutter-on-mobile (finding 1) have a11y overlap.
- **R2 (11-state-coverage)** owns empty/loading states; the `sanitize.html` `.hidden` bug (finding 2)
  is a *visual* manifestation but its root is an initial-state bug — flagging the overlap so the
  synthesis dedups.
- **R1 (10-ia-navigation)** owns the nav as IA; finding 1's nav-overflow is a *visual/responsive*
  manifestation of the same element.

# 10 — Information Architecture, Navigation & Page Flows (R1)

**Scope:** the shared shell + global nav (`base.html`), every page-level template's top-level
structure, and the page-route context wiring in `netcanon/api/routes/ui.py`. Evaluated for: nav
completeness/consistency/current-page indication; per-page IA (title, purpose, one obvious primary
action, heading hierarchy); cross-page journeys (migrate, configs→diff, jobs/schedules, sanitize,
dashboard→detail); and wayfinding (breadcrumbs, 404/error IA, internal-link integrity).

**Verdict:** the IA is fundamentally healthy. The global nav is complete (every page is reachable),
consistent (rendered once from `base.html`, inherited by all), and indicates the current page with
both a visual underline and `aria-current="page"`. Pages have clear titles and mostly a single
primary action. The real defects cluster in three places: (1) **error-page wayfinding** — there is
no custom 404/500 handler, so unknown URLs and server errors drop the operator onto an unstyled,
nav-less JSON page (a true dead-end); (2) **the migrate page is a journey dead-end** — after a
successful translation there is no hand-off to *save / re-backup / sanitize the result*, and no
cross-link anywhere into the rest of the app; and (3) **the diff page is the only page with a
back-link**, leaving the dashboard→jobs→config and migrate flows without "where do I go next"
affordances. Everything else is `POLISH`.

---

## Top 5 findings (lead)

1. **No custom 404 / 500 / error page — unknown URLs and server errors are a styled-app dead-end.**
   `netcanon/main.py:227` constructs `FastAPI(...)` with no exception handlers, and there is no
   `@app.exception_handler` anywhere in the package (grep over `netcanon/**.py` finds only
   `api/_errors.py`, which is explicitly *not* a FastAPI handler — see its docstring at
   `netcanon/api/_errors.py:44-49`). Consequence: a typo'd URL (e.g. `/config`, `/migrations`) or
   any uncaught 500 renders Starlette's default `{"detail":"Not Found"}` plain-JSON body with **no
   nav, no theme, no link home**. For a server-rendered operator tool whose entire IA depends on the
   persistent nav, this is the single biggest wayfinding gap. `BROKEN`.

2. **The Migrate page is a hard journey dead-end after translation.** `migrate.html` contains
   **zero internal `href` links** (grep for `href=` in the file returns nothing; the only `save*`
   tokens are the rename-modal's `saveRenameAck` localStorage helpers). After a successful
   `Translate`, the operator gets Copy / Download buttons (`migrate.html:463-472`) but no
   next-step: no "save this as a stored config", no "sanitize this output before sharing", no
   "back to Configs". Migration is the app's headline workflow (the 2477-line template) yet it is an
   island. `CONFUSING`.

3. **Only the Diff page offers a back-link; no other interior page has one (and there are no
   breadcrumbs).** The diff view has an explicit `← Configs` link (`diff.html:88-91`) plus a
   Reverse-direction link (`diff.html:103`). Every *other* page relies solely on the top nav to get
   "back" — which is fine for top-level pages but means contextual flows (a config opened from a job
   result, a schedule's last-job link) have no breadcrumb telling the operator where they came from
   or what context they're in. The diff page proves the team knows the pattern; it just isn't applied
   to the rest. `POLISH` (acceptable for a flat 9-page IA, but the migrate/diff/sanitize cluster
   would benefit).

4. **`/jobs#<id>` deep-link uses an 8-char prefix that is not guaranteed unique and silently
   no-ops on miss.** `schedules.html:159` links to `/jobs#{{ sched.last_job_id[:8] }}` and
   `jobs.html:54` sets `id="job-{{ job.id[:8] }}"`, while the jobs hash handler
   (`jobs.html:162-172`) does `getElementById('job-' + hash)`. Two jobs sharing an 8-hex-char prefix
   (birthday-collision territory once a deployment accrues thousands of jobs) would scroll to the
   wrong card; more commonly, if the target job has aged out of the in-memory store the link lands on
   `/jobs` and **does nothing** — no toast, no "job not found" state. The `index.html` job table
   (`index.html:115`) also truncates the displayed ID to `[:8]`, so the operator can't even
   eyeball-confirm which job a link points at. `CONFUSING`.

5. **`configs.html` and `migrate.html` lack the orienting lead paragraph that `sanitize.html`,
   `definitions.html` (and migrate, partially) have — the page title alone carries the purpose.**
   `sanitize.html:54-62` and `definitions.html:24-32` open with a muted intro paragraph explaining
   what the page does; `migrate.html:319-325` has one too. But `configs.html:5` jumps straight from
   `<h1>Stored Configurations</h1>` into the table with no "these are the raw backups you've
   captured; compare or migrate them from here" framing, and there's no signpost that a config is the
   *input* to both Diff and Migrate. The IA treats Configs as a terminal list when it is actually the
   hub that feeds the two most valuable workflows. `INCONSISTENT` / `POLISH`.

---

## 1. Global navigation

### 1.1 Completeness — every route is reachable (no orphans)

The nav is defined once in `base.html:349-378` and inherited by every page via
`{% extends "base.html" %}`. Cross-referencing the nav links against the nine page routes in
`ui.py`:

| Route (`ui.py`) | Nav link (`base.html`) | Reachable from nav? |
|---|---|---|
| `/` (`index`, line 79) | `nav-home` / `nav-brand` (350-351) | Yes |
| `/devices` (267) | `nav-devices` (352) | Yes |
| `/jobs` (106) | `nav-jobs` (353) | Yes |
| `/schedules` (130) | `nav-schedules` (354) | Yes |
| `/configs` (157) | `nav-configs` (355) | Yes |
| `/definitions` (303) | `nav-definitions` (356) | Yes |
| `/migrate` (402) | `nav-migrate` (357) | Yes |
| `/sanitize` (424) | `nav-sanitize` (358) | Yes |
| `/configs/{left}/vs/{right}` (diff, 177) | — (no direct nav link) | **Indirect only** |

The diff route is **correctly** not a top-level nav item — it requires two filename params and is
reached contextually from the configs compare-picker (`configs.html:243-246`), from a job result's
View link, and from the diff page's own Reverse link. That is the right IA call; flagging only to
confirm it is intentional, not an orphan. There are **no orphaned routes** — all nine are reachable.

The nav also includes `/docs` ("API Docs", `base.html:359`). This is a real, mounted page
(`docs.py:416`, registered at `main.py:305`) that renders its own nav-wrapped Swagger UI (the
"API Docs" link is marked `active` inside `docs.py:138`). Good — it is not a broken link, and the
doc page maintains the shell.

### 1.2 Consistency — single source, inherited everywhere

Because the nav lives in `base.html` and every template extends it, there is no divergence risk
across the Jinja pages. The one place the nav is **duplicated** is `docs.py:61-65,138`, which
re-declares the theme tokens and re-emits the nav markup by hand (because `/docs` doesn't extend
`base.html`). The file's own comment (`docs.py:61-65`) flags the drift risk explicitly. This is a
known, contained tradeoff — `INCONSISTENT` but already documented; not a new finding. (Visual-design
agent R4 owns the token-duplication angle.)

### 1.3 Current-page indication — present and accessible

`active_page` is passed in every `ui.py` context (`"active_page": "home"` line 91, `"jobs"` 119,
`"schedules"` 142, `"configs"` 165, `"devices"` 287, `"definitions"` 387, `"migrate"` 413,
`"sanitize"` 442). The nav template gates `class="active" aria-current="page"` on each link
(`base.html:351-358`). The active style is a visible underline (`base.html:194`). Both the visual
and the programmatic cues are present — good a11y hygiene (R3 owns the deeper a11y pass).

**Sub-finding — the Diff page highlights "Configs" as active, which is correct by design but worth
noting.** `ui.py` sets `"active_page": "configs"` for all four diff render branches (lines 213, 230,
249) so the nav shows Configs as current while viewing a diff. That is the right call (diff is a
child of configs), and the diff page reinforces it with its `← Configs` back-link. No change needed;
documenting so synthesis doesn't mistake it for a bug.

---

## 2. Per-page IA

| Page | `<h1>` | Lead/purpose copy | One obvious primary action | Heading hierarchy |
|---|---|---|---|---|
| Dashboard (`index.html:5`) | "Dashboard" | none (form `<h2>` carries it) | `Start Backup` (93) | h1 → h2 (New Backup, Recent Jobs) — clean |
| Jobs (`jobs.html:38`) | "Backup Jobs" + count | none | (read-only list; no primary action) | h1 only; per-card tables use `<th>` |
| Schedules (`schedules.html:19`) | "Schedules" | none | `Create Schedule` (100) | h1 → h2 → **h3** (target groups, 57/74) — clean |
| Configs (`configs.html:5`) | "Stored Configurations" | **none** | ambiguous (per-row View/Download/Compare/Delete) | h1 only |
| Diff (`diff.html:87`) | "Diff" | none (toolbar chips carry context) | (read-only; Reverse/Compare-anyway are secondary) | h1 only |
| Devices (`devices.html:18`) | "Devices" | none | `Add Device Profile` (102) | h1 → h2 (New, Profiles) — clean |
| Definitions (`definitions.html:22`) | "Definitions Browser" | yes (24-32) | (read-only browser; no action) | h1 → h2 ×4 (289/351/415/576) — clean |
| Migrate (`migrate.html:318`) | "Migrate" | yes (319-325) | `Translate` (419) | h1 → h2 "Rendered output" (450) — clean |
| Sanitize (`sanitize.html:53`) | "Sanitize" | yes (54-62) + safety note (64-73) | `Sanitize` (123) | h1 only (result sections use `<span>` labels, not headings) |

**Observations:**

- **Title clarity:** every page has a unique `<h1>` and a matching `<title>` block
  (`{% block title %}… — Netcanon{% endblock %}`). Good.
- **One primary action:** the three form pages (Dashboard, Schedules, Devices) and the two
  workbenches (Migrate, Sanitize) each have exactly one `.btn-primary` submit, visually distinct
  from the secondary/danger buttons. Strong. The exception is **Configs**, where the per-row action
  cluster (View / Download / Compare / Open / Delete, `configs.html:25-50`) gives no hierarchy —
  every config row presents 4-5 equally-weighted buttons and the page has no page-level primary
  action at all. For a *list/browser* page that's defensible, but the lack of any framing
  (see Finding 5) compounds it. `POLISH`.
- **Heading hierarchy:** no skipped levels anywhere (no h1→h3 jumps). Schedules correctly nests
  h3 under h2. The one soft spot is **Sanitize**, whose result region uses uppercase `<span>`
  pseudo-labels ("Sanitized output", `sanitize.html:139`) and a `<details><summary>` for the audit
  ("Substitution audit", 161) rather than real headings — fine visually, but a screen-reader
  user scanning by heading gets nothing below the h1. (R3 a11y owns this; noting the IA angle.)
  `A11Y`/`POLISH`.

---

## 3. Cross-page journeys

### 3.1 Dashboard → backup → Jobs / Configs (the core loop) — mostly good

The dashboard backup form submits async (`index.html:311`), hands off to the global floating
job-progress panel (`base.html:526-557`, `startJobProgress`), and on completion injects a row into
the Recent Jobs table (`index.html:342-371`). The job-progress panel persists across navigation and
has a "View full job details" link (`base.html:550`). The Jobs page links each successful result to
`/configs#<filename>` (`jobs.html:115`), and the Configs page's hash handler scrolls to + opens the
viewer for that file (`configs.html:269-280`). **This is a well-built, discoverable end-to-end loop**
— backup → see progress → open job → view captured config. The empty-state copy on Jobs even points
back to the Dashboard and Schedules (`jobs.html:44-45`). Strong.

### 3.2 Configs → Diff — good, with the only proper back-link in the app

The compare button on each config row (`configs.html:33-39`) opens a modal picker
(`openComparePicker`, 195) that lists same-vendor configs first and offers a "Show cross-vendor"
toggle, building deep-linkable `/configs/{l}/vs/{r}` URLs (243-246). The diff page itself is
deep-linkable (the route docstring at `ui.py:182-184` calls this out), has a `← Configs` back-link
(`diff.html:88`), a Reverse-direction link (103), and a "Compare anyway" override for incompatible
pairs (130). This journey is the **gold standard** in the app for hand-offs. No defects.

### 3.3 Schedules → Jobs — good

A schedule row links its last job via `/jobs#<id-prefix>` (`schedules.html:157-166`), and the empty
"Target Specific Devices" state links to `/devices` to add a profile first (`schedules.html:93-94`).
The only wrinkle is the 8-char prefix fragility (Finding 4). Otherwise the schedule→job→config chain
is coherent.

### 3.4 Migrate — dead-end after success (Finding 2, expanded)

Migrate is the most valuable and largest workflow, but it terminates in itself:

- **No save-back:** the rendered output (`migrate.html:446-475`) can only be Copy'd or Download'd.
  There's no "save as a stored config" — so a translated config can't be re-fed into Diff (to
  compare source vs. target) or back into the Configs list. Given the app already has a config store
  and a diff engine, "save the translation and diff it against the source" is the obvious missing
  next-step.
- **No bridge to Sanitize:** the migrate output is exactly the kind of artifact an operator shares
  in a bug report, yet there's no "sanitize this output" hand-off — the operator must manually
  Copy → navigate to Sanitize → choose the *target* vendor → paste. A "Sanitize this output" link
  pre-selecting the target vendor would close the loop.
- **No cross-link at all:** the page has zero internal `href`s (grep confirms). Even the Tier-3
  banner (`migrate.html:432-440`), which tells the operator "apply these manually on the target
  device", doesn't link to the per-vendor capability docs or the Definitions page that explains the
  matrix. (Microcopy agent R5 owns whether the banner *text* matches CAPABILITIES.md; the IA gap is
  the absence of any onward link.)

`CONFUSING` — the workflow completes functionally but leaves the operator at a wall.

### 3.5 Sanitize — self-contained, acceptable

Sanitize mirrors migrate's input-mode pattern (paste raw / pick stored, `sanitize.html:85-112`) and
ends with Copy / Download (142-153) plus a clear "for sharing only" safety note (64-73). Like
migrate it's a workbench with no onward link, but unlike migrate that's appropriate — the sanitized
output's *destination is external* (a ticket), so a dead-end is the correct terminal state. No
hand-off finding here; the safety-note framing is genuinely good IA.

### 3.6 Dashboard → detail — fine

Recent Jobs rows on the dashboard (`index.html:113-126`) are not themselves linked to `/jobs#<id>`
(the row is display-only; the global panel's "View full job details" link is the path to detail).
Minor: a dashboard job row that is not clickable, while the full Jobs page makes the whole card a
toggle, is a small inconsistency, but the panel link covers the journey. `POLISH`.

---

## 4. Wayfinding

### 4.1 Breadcrumbs — none (acceptable for a flat IA)

The IA is two levels deep at most (top-level page, or a diff under configs). With nine flat pages and
a persistent nav, full breadcrumbs would be over-engineering. The diff page's `← Configs` link is the
right lightweight substitute. **Do not add a breadcrumb component** — see over-engineering flags.

### 4.2 404 / error-page IA — the real gap (Finding 1, expanded)

No custom handlers exist. Concretely:

- `GET /nonexistent` → Starlette default `404 {"detail":"Not Found"}`, plain text, no nav, no theme.
- An uncaught exception in a UI route → FastAPI default `500 Internal Server Error` plain body.
- The **diff route is the one place that handles "not found" gracefully** — it deliberately
  re-renders `diff.html` with an error banner instead of 404-ing the user out
  (`ui.py:202-220`, and the docstring at 186-191 explains the design intent). This proves the team
  values keeping the operator inside the styled shell on error — the gap is that this discipline
  isn't generalized to a global 404/500 handler.

**Fix shape:** register a small `StarletteHTTPException` (404) + generic-exception (500) handler in
`main.py` that renders a minimal `error.html` extending `base.html` (so it inherits the nav + theme),
with a one-line message and a "Back to Dashboard" link. This is a single template + ~15 lines in the
app factory. (Note: feature-parity — the desktop platform embeds the same server, so this lands once
and reaches both per AGENTS.md "Web only"/parity rules; it is a server behaviour, not a desktop-only
affordance.) `BROKEN`, effort **M**.

### 4.3 Internal link integrity — clean, with two fragilities

Every internal `href` was enumerated (grep over `netcanon/templates/`). All point at real routes:

- `/` , `/devices`, `/jobs`, `/schedules`, `/configs`, `/definitions`, `/migrate`, `/sanitize`,
  `/docs` — all mounted (`ui.py` + `docs.py`/`main.py:305`).
- `/configs#<filename>` (`jobs.html:115`) → handled by `configs.html:269-280`. Works.
- `/jobs#<id[:8]>` (`schedules.html:159`) → handled by `jobs.html:162-172`. Works but
  **prefix-fragile** (Finding 4): no uniqueness guarantee and a silent no-op on a missed/aged-out
  job. Fix shape: use the full job id in the fragment + a "couldn't find that job" toast when the
  card is absent.
- `/configs/{l}/vs/{r}` and its `?force=true` variants (`diff.html:103,130`, `configs.html:243`) —
  all URL-encoded (`| urlencode`, `encodeURIComponent`). No injection/encoding gap. Good.

No broken internal links found.

### 4.4 Empty-state wayfinding — a strength

Most list pages turn their empty state into a signpost rather than a void:

- Configs empty → "Run a backup from the Dashboard" link (`configs.html:57-60`).
- Jobs empty → links to Dashboard *and* Schedules (`jobs.html:44-45`).
- Schedules empty → "Fill in the form above" (`schedules.html:110-111`); device-target empty →
  "Add a device profile" link to `/devices` (93-94).
- Devices empty → "Fill in the form above" (`devices.html:112-113`).

The gaps: **Migrate and Sanitize have no first-run guidance** when there are no stored configs — the
"Pick a stored config" dropdown just renders `— pick one —` with nothing under it
(`migrate.html:395`, `sanitize.html:103`), with no "you haven't captured any configs yet — back up a
device first" hint and no link to the Dashboard. (R2 state-coverage owns the empty-state depth;
the IA angle is the missing onward link.) `POLISH`.

---

## 5. Findings table

| # | Path:Line | Severity | Finding | Fix shape | Effort |
|---|---|---|---|---|---|
| 1 | `netcanon/main.py:227` (no handler); cf. `api/_errors.py:44-49` | BROKEN | No custom 404/500 page; unknown URLs & server errors render unstyled, nav-less default JSON — a dead-end out of the styled app | Register `StarletteHTTPException`(404) + generic-exception(500) handlers in the app factory rendering an `error.html` that extends `base.html` (inherits nav+theme) with a "Back to Dashboard" link | M |
| 2 | `migrate.html` (whole file — no `href`); output actions `migrate.html:463-472` | CONFUSING | Migrate is a journey dead-end: after Translate there's only Copy/Download — no save-as-stored-config, no "Sanitize this output", no onward link | Add a "Save as stored config" action (re-uses the config store + unlocks Diff-against-source) and a "Sanitize this output" link pre-selecting the target vendor | M |
| 3 | `diff.html:88` (only back-link in app) | POLISH | Only the Diff page has a back-link / contextual return; migrate/sanitize/job-opened-config flows rely solely on top nav | Add a lightweight contextual back affordance to the workbench pages (mirror diff's `← Configs` pattern); do NOT add full breadcrumbs | S |
| 4 | `schedules.html:159`, `jobs.html:54,162-172`, `index.html:115` | CONFUSING | `/jobs#<id[:8]>` deep-link uses a non-unique 8-char prefix and silently no-ops when the job is absent/aged-out | Use the full job id in the fragment + show a "job not found / may have aged out" toast when no card matches | S |
| 5 | `configs.html:5` (vs `sanitize.html:54-62`, `definitions.html:24-32`, `migrate.html:319-325`) | INCONSISTENT | Configs (and to a lesser degree the Configs→Diff/Migrate role) lacks the orienting lead paragraph other pages have; the hub page reads as a terminal list | Add a one-line muted intro framing Configs as the source for Diff & Migrate, matching the other pages' lead-paragraph pattern | S |
| 6 | `migrate.html:395`, `sanitize.html:103` | POLISH | Migrate/Sanitize "Pick a stored config" dropdowns show `— pick one —` with no first-run guidance when no configs exist | When `configs` is empty, render an inline hint + link to the Dashboard to capture a config first | S |
| 7 | `sanitize.html:139,161` (result labels are `<span>`/`<summary>`, not headings) | A11Y | Sanitize result region has no real heading below the h1, so heading-navigation surfaces nothing for the output/audit sections | Promote "Sanitized output" / "Substitution audit" to `<h2>`/`<h3>` (R3 a11y owns depth) | S |
| 8 | `docs.py:61-65,138` | INCONSISTENT | `/docs` re-declares the nav + theme tokens by hand instead of extending `base.html` (self-documented drift risk) | Already documented; no action beyond keeping tokens in sync — R4 owns the token-duplication call | — |

---

## 6. Over-engineering flags (things NOT to do)

- **No full breadcrumb component.** A nine-page flat IA with a persistent nav doesn't warrant
  breadcrumbs; the diff page's single back-link is the right-sized pattern (Finding 3 deliberately
  scopes to "lightweight back affordance", not a breadcrumb system).
- **No nav reorganization / grouping / mega-menu.** Nine top-level links fit comfortably in one row
  (`base.html:191` already handles wide/narrow gutters). Don't introduce dropdowns or sections.
- **No client-side router / SPA shell.** The seed locks server-rendered Jinja; the per-page reloads
  are fine for this tool. Finding 1's error pages must also be server-rendered, not a JS catch-all.
- **The error page should be minimal** — one message + one link. Resist building a rich "report this
  error" / stack-trace surface; the desktop platform already logs to `%APPDATA%\Netcanon\netcanon.log`
  (per AGENTS.md), and echoing exception detail to the browser is an explicit anti-pattern in this
  codebase (`configs.py:203-204`).

---

## 7. Cross-references for synthesis

- **R2 (state-coverage):** owns empty-state *depth* and async UX; Findings 6 (empty config dropdowns)
  and the migrate/sanitize result rendering overlap — coordinate so we don't double-count.
- **R3 (a11y):** owns Finding 7 (heading semantics) and `aria-current` correctness; I only flagged
  the IA-visible surface.
- **R4 (visual):** owns Finding 8 (`/docs` token duplication) and the nav's active-underline styling.
- **R5 (microcopy/honesty):** owns whether the Migrate Tier-3 banner text and the Configs/Diff
  compatibility copy match `docs/CAPABILITIES.md`; Finding 2's "no onward link" is the IA half of the
  same banner.

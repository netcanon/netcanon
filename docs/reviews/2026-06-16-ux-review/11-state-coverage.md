# 11 — State coverage & async UX audit (R2)

**Scope:** LOADING / EMPTY / ERROR / SUCCESS state coverage and async-UX
correctness across the JS-driven templates (`migrate.html`, `jobs.html`,
`configs.html`, `sanitize.html`, `definitions.html`, dashboard `index.html`,
`schedules.html`), the shared async infra in `base.html` +
`_partials/job-progress.js`, and the backing routes (`migration.py`,
`backups.py`, `sanitize.py`, `schedules.py`, `configs.py`).

**Headline verdict:** the async UX is in genuinely good shape. The shared
`formatApiError()` + `showToast()` helpers are consistently wired into nearly
every `fetch()` handler; submit buttons are disabled + relabelled during
flight; the global job-progress panel polls, persists across reload, caps its
own error retries, and dispatches a clean event API. This is well above the bar
for a self-hosted operator tool. The defects below are real but mostly narrow:
one true BROKEN empty-state on the Sanitize page, a couple of CONFUSING
stale-data-after-mutation gaps on the Jobs/Schedules list pages, and a cluster
of POLISH-grade silent-failure / double-submit edges.

---

## Top 5 (lead findings)

1. **BROKEN — Sanitize result scaffold is visible on first load (dead `.hidden`
   class).** `sanitize.html:128` renders the entire result region with
   `class="hidden"`, and the JS reveals it via
   `result.classList.remove('hidden')` (`sanitize.html:384`). But **no
   `.hidden { display:none }` rule exists in scope** — the only `.hidden`
   declaration in the codebase is `#mig-result.hidden` scoped to `#mig-result`
   in `migrate.html:52`. base.html defines no global `.hidden`. So on a fresh
   `/sanitize` load (before the operator does anything) the empty status line,
   empty stats strip, the "Sanitized output" panel header with Copy/Download
   buttons, and the "Substitution audit" `<details open>` with an empty table
   are all already on screen. This is a confusing first-run empty state that
   looks like a half-rendered page. **Fix shape:** add `.hidden{display:none}`
   to base.html's `<style>` (it's a generic utility every page can reuse), or
   add an inline `style="display:none"` to `#san-result` and toggle
   `style.display` instead of the class (matching the migrate pattern). Effort: S.

2. **CONFUSING — Jobs LIST page (`/jobs`) never refreshes a still-running job.**
   `jobs.html` is fully server-rendered; a job whose body has no results yet
   shows a static `"Still running…"` (`jobs.html:142`) with **no polling**. The
   global job-progress panel (`_partials/job-progress.js`) only tracks the job
   whose ID is in `localStorage` (the one the operator just started from the
   dashboard), so a job started in another tab / by a schedule / before this
   page load sits frozen at "Still running…" until a manual refresh. There's no
   "Refresh" affordance and no auto-reload. **Fix shape:** either poll
   `GET /api/v1/backups/` on an interval and re-render rows, or (cheaper, S) add
   a visible "Refresh" button + a one-line hint ("this list does not
   auto-update"). The dashboard's Recent-Jobs table has the same property but is
   less surprising because the live panel covers the just-started job. Effort:
   S (button+hint) / M (polling).

3. **CONFUSING — Dashboard "Recent Jobs" injected row shows local time while
   server-rendered rows show a different format, and the injected row is never
   reconciled.** `injectJobRow()` (`index.html:357-371`) builds the new row with
   `new Date(j.created_at).toLocaleString()` and the status from the terminal
   poll. That's fine, but the row is injected client-side only — it is **not**
   the same DOM shape the server renders on reload (server rows carry
   `data-utc` + `data-testid="job-created"` for the localize pass;
   `index.html:122-124`), and the injected row omits `data-utc`. Minor
   inconsistency, but the larger gap: if the operator starts a second backup the
   panel/handoff works, yet nothing dedupes against a job that already exists in
   the table after a reload. Low blast radius. **Fix shape:** give the injected
   row the same `data-utc` attribute + run the localize pass, or just reload the
   table region. Effort: S. (POLISH-leaning CONFUSING.)

4. **POLISH/CONFUSING — Auto-detect and several enrichment fetches fail
   completely silently.** `runAutoDetect()` swallows non-OK and network errors
   with `clearDetectBanner()` and a bare `catch` (`migrate.html:1105-1114`);
   `enrichParseFailureBanner()` returns silently on every error
   (`migrate.html:1351-1361`); `loadRenameTargetProfiles()` silent-ignores
   (`migrate.html:1707-1716`). These are *deliberately* best-effort (documented
   in-comment) and that's a defensible call for a nice-to-have suggestion layer
   — but the source-vendor dropdown population in `loadAdapters()`
   (`migrate.html:885-927`) and the rename-target-profile load are load-bearing,
   and a silent failure there leaves the operator with an empty/half-populated
   form and no explanation. `loadAdapters()` at least toasts; the
   target-profiles load does not. **Fix shape:** keep detect/enrich silent;
   surface a one-line inline note when `loadRenameTargetProfiles()` fails so the
   "Interface rename" modal's empty vendor dropdown isn't a mystery. Effort: S.

5. **POLISH — Double-submit / re-entrancy is well-guarded on the primary forms
   but NOT on the per-row action buttons.** The Backup, Schedule, Sanitize, and
   Migrate submit handlers all disable+relabel their button first thing
   (`index.html:236-237`, `schedules.html:208-209`, `sanitize.html:346-348`,
   `migrate.html:1227-1229`) — good. But the inline per-row buttons don't lock:
   the schedule **toggle** button (`schedules.html:257`) and **delete-confirm**
   (`schedules.html:284`) fire their fetch with no disable, so a double-click
   sends two `POST /toggle` (net no-op but two reloads race) or two `DELETE`
   (second gets 404 → red "Error" toast on an action that actually succeeded).
   The config **delete-confirm** (`configs.html:147`) and the jobs/configs
   **Open** button (`jobs.html:176`) similarly don't guard, though configs.html's
   Open button *does* disable (`configs.html:288-290`) — inconsistent within the
   same concern. **Fix shape:** disable the clicked button at the top of each
   inline async handler; treat a 404 on delete-after-success as success.
   Effort: S each.

---

## Per-surface walk-through

### Shared infra — `base.html` + `_partials/job-progress.js`

- **LOADING:** `showToast()` (`base.html:579-589`) and the job-progress spinner
  (`.jp-icon-running` CSS animation, `base.html:499`) are solid. The config
  viewer modal seeds `Loading…` text (`base.html:410`). No global page spinner,
  but the app's pattern is per-button disable, which is fine.
- **ERROR:** `formatApiError()` (`base.html:602-618`) correctly normalises both
  FastAPI shapes (string `detail` and the Pydantic-422 array) — this is the
  keystone that stops `[object Object]` toasts. `downloadConfig()`
  (`base.html:635-646`) has both a non-OK guard and a `.catch`. Good.
- **Polling correctness:** `job-progress.js` is the strongest async code in the
  app. `_tick()` (`:156-187`) handles 404 (purged job → dismiss quietly),
  non-OK (throw → counted), and network error; it caps at `MAX_ERRORS=3`
  (`:181-185`) and degrades to a visible "Lost contact with server" summary
  instead of spinning forever. `_resume()` (`:203-228`) restores a non-terminal
  job after a full reload from `localStorage`. Terminal state stops the poll and
  sets a sticky footer flag (`:171-179`). One nit (POLISH): on the
  `MAX_ERRORS` degrade path the panel shows "Lost contact" but leaves the last
  device rows on screen with stale spinners — there's no "retry" affordance, the
  only recovery is reload. Acceptable for v1.
- **A11Y/honesty note for sibling reports:** the panel is `aria-live="polite"`
  (`base.html:528`) — good — but the spinner glyph swap is CSS-only; covered by
  R3.

### Dashboard `/` (`index.html`) — Backup start

- **LOADING:** submit disabled + "Running…" (`index.html:236-237`); re-enabled
  on every early-return error path and via the `netcanon:job-complete` /
  `netcanon:job-dismissed` listeners (`index.html:342-354`). The two-phase flow
  (optionally POST a new profile, then POST the backup) re-enables the button on
  profile-save failure (`index.html:273-283`) — correctly handled.
- **EMPTY:** good first-run empty state with an actionable pointer
  (`index.html:129-133`: "Fill in the form above and click Start Backup").
- **ERROR:** profile-save and backup-POST both use `formatApiError` + toast and
  have `.catch` (`index.html:270-284`, `:316-324`). No silent fetch.
- **SUCCESS / STALE:** POST returns `202 pending` (`backups.py:141-143`); the UI
  correctly does NOT trust the POST body — it hands the job ID to
  `startJobProgress()` which polls to terminal state (`index.html:334`), then
  injects the final row on `netcanon:job-complete`. This is the correct
  pattern and matches the AGENTS.md hard rule ("never assert on the POST body
  for final state"). The injected-row format/`data-utc` mismatch (finding #3) is
  the only blemish.
- **Trailing-slash note:** the form POSTs to `/api/v1/backups` (no slash) while
  the route is `@router.post("/")` under prefix `/backups`
  (`backups.py:141`, mounted `main.py:300`). Starlette's default
  `redirect_slashes=True` 307-redirects to `/api/v1/backups/`, preserving method
  + body, so this works — but it's an avoidable extra round-trip and a 307 is
  surprising in the network tab. POLISH: post to the canonical `/api/v1/backups/`.

### Jobs `/jobs` (`jobs.html`)

- **EMPTY:** good — `no-jobs-msg` with pointers to Dashboard + Schedules
  (`jobs.html:42-46`).
- **EMPTY (per-job):** a job with no results yet shows `"Still running…"`
  (`jobs.html:142`) but the page never polls (finding #2) — the static label
  becomes a lie the moment the job finishes elsewhere.
- **ERROR:** the only async here is `openJobConfig()` (`jobs.html:175-182`),
  guarded by status-204 check + `formatApiError` + `.catch`. Fine.
- **No double-submit guard on Open** (`jobs.html:176`) — POLISH (finding #5).
- **Honesty/microcopy (for R5):** the per-result error is truncated to 100 chars
  with a `title` tooltip carrying the full text (`jobs.html:128-131`) — good
  surfacing, not a swallow.

### Configs `/configs` (`configs.html`)

- **EMPTY:** good — `no-configs-msg` with Dashboard pointer
  (`configs.html:56-60`).
- **LOADING:** delete uses an inline Yes/No confirm (`configs.html:129-170`) —
  good (no native `confirm()`); Open button disables + shows "Opening…"
  (`configs.html:288-290`).
- **ERROR:** delete handler has non-OK branch (restores button + toast) and
  `.catch` (`configs.html:159-168`); Open handler has `formatApiError` + `.catch`
  + `finally` re-enable (`configs.html:295-307`). No silent fetch.
- **STALE-after-mutation:** delete removes the row in-place and only reloads when
  the last row is gone to restore the empty-state (`configs.html:154-158`) —
  correct, no stale full-table reload needed.
- **Double-submit on delete-confirm:** the "Yes" button isn't disabled while the
  DELETE is in flight (`configs.html:147-169`); a double-click second DELETE
  returns 404 → "Delete failed" red toast on an operation that succeeded.
  POLISH (finding #5).

### Sanitize `/sanitize` (`sanitize.html`)

- **BROKEN empty state:** finding #1 — result scaffold visible on load.
- **LOADING:** submit disabled + "Sanitizing…" with `finally` restore
  (`sanitize.html:346-348`, `:401-404`). Good.
- **ERROR:** very thorough — both parallel calls (`auditPromise` /
  `outputPromise`) are individually checked for non-OK before any body is
  consumed (`sanitize.html:369-380`), each routed through `formatApiError`;
  outer `catch` handles build/network errors (`:399-400`). `loadAdapters()`
  toasts on both non-OK and network error (`:229-248`). No silent fetch on the
  load-bearing paths.
- **SUCCESS:** clear status summary with timing + redaction count + dry-run note
  (`sanitize.html:386-389`); scrolls result into view. Copy guards missing
  Clipboard API (`:409-411`); Download guards empty output (`:421-424`). Strong.
- **Honesty (for R5):** the "For sharing only" banner (`sanitize.html:64-73`) is
  good matrix-honesty UX. No state defect.

### Migrate `/migrate` (`migrate.html`)

- **LOADING:** submit disabled + "Translating…" with `finally` restore
  (`migrate.html:1227-1229`, `:1308-1311`).
- **EMPTY:** `#mig-result.hidden` correctly hides the result until first
  translate (`migrate.html:52`); empty-input guard for filename mode
  (`:1249-1255`). Auto-detect clears its banner on short/empty input
  (`:1081-1084`).
- **ERROR (request-shape):** `/plan` non-OK → `formatApiError` + toast
  (`migrate.html:1267-1271`); outer `.catch` for network (`:1306-1307`).
- **ERROR (in-band parse failure):** correctly handled as a 200 with
  `job.status==='failed'` / `job.error` (route confirms `/plan` returns the job
  even on parse failure, `migration.py:200-211`); the banner severity ladder
  (`migrate.html:1416-1434`) renders it red, and `enrichParseFailureBanner()`
  adds a "Did you mean: <vendor>?" suggestion. This is excellent error UX — the
  failure is actionable, not silent.
- **Silent best-effort fetches:** detect / enrich / target-profiles
  (finding #4). Defensible except the target-profiles load feeding the rename
  modal.
- **STALE:** result is fully re-rendered per submit (`renderResult`,
  `migrate.html:1409`); `captureJobForRename` re-seeds the rename modal each
  time (`:1276`). No stale-data risk on re-translate.

### Schedules `/schedules` (`schedules.html`)

- **EMPTY:** good — `no-schedules-msg` (`schedules.html:110-112`) and a separate
  `no-profiles-for-sched-msg` with a "/devices" pointer when no profiles exist
  (`:91-95`).
- **LOADING:** create submit disabled + "Creating…" + `finally` restore
  (`schedules.html:208-209`, `:251-253`). Client-side validation (at least one
  target) toasts before any fetch (`:223-228`) — good, no wasted round-trip.
- **ERROR:** create uses `formatApiError` + toast + `.catch`
  (`schedules.html:241-249`); toggle and delete-confirm both use
  `formatApiError` + `.catch` (`:257-269`, `:284-300`).
- **SUCCESS / STALE:** create reloads the page after an 800ms toast
  (`schedules.html:246-247`) — acceptable but jarring (full reload to show one
  new row). Delete removes the row in-place and only reloads to restore the
  empty state (`:289-292`) — good. Toggle does a full `window.location.reload()`
  (`:265`) — heavier than needed but correct.
- **Double-submit:** toggle + delete-confirm don't disable (finding #5). Toggle
  is idempotent server-side so harmless; delete-confirm second click → 404
  → false error toast.

### Definitions `/definitions` (`definitions.html`)

- **EMPTY:** every section has a tailored empty state — `no-definitions-msg`
  (`definitions.html:339-343`), `no-overlays-msg` (`:401-407`),
  `no-target-profiles-msg` (`:565-568`), and a per-vendor "No codecs registered"
  (`:684-686`). The profile-filter shows a live match count (`:746-751`). This
  is the best empty-state coverage in the app.
- **LOADING:** reload-defs button disables + "Reloading…"
  (`definitions.html:698-701`); caps-chip click disables briefly to dedupe rapid
  clicks (`:901`, `:920-922`).
- **ERROR:** reload handler has non-OK branch (restores button + toast) and
  `.catch` (`definitions.html:704-717`). Caps-detail fetch failure renders an
  **inline** "Failed to load: …" detail row (`:907-919`) — good, errors are
  surfaced where the operator is looking, not just as a toast. The in-flight
  de-dupe via `loading[codecName]` promise cache (`:780-800`) is a nice touch.
- **STALE:** caps cache is per-page-lifetime and documented as intentional
  (`definitions.html:771-774`); reload-defs reloads the whole page so no stale
  table. No defect.

---

## Findings table

| # | Path:Line | Severity | Finding | Fix shape | Effort |
|---|---|---|---|---|---|
| 1 | `netcanon/templates/sanitize.html:128`, `:384` (+ missing rule; cf. `migrate.html:52`) | BROKEN | `#san-result` uses `class="hidden"` but no `.hidden{display:none}` exists in scope → empty result scaffold is visible on first load | Add global `.hidden{display:none}` to `base.html` `<style>`, or use inline `style="display:none"` + toggle `style.display` | S |
| 2 | `netcanon/templates/jobs.html:142` (and `index.html:103-134`) | CONFUSING | Jobs list never polls; a still-running job is frozen at "Still running…" until manual refresh | Add a "Refresh" button + "does not auto-update" hint (S), or poll `GET /api/v1/backups/` (M) | S/M |
| 3 | `netcanon/templates/index.html:357-371` (vs server rows `:122-124`) | CONFUSING | Client-injected Recent-Jobs row omits `data-utc` + differs in shape from server-rendered rows; no dedupe against existing rows | Give injected row `data-utc` + run localize pass, or reload the table region | S |
| 4 | `netcanon/templates/migrate.html:1707-1716` (also `:1105-1114`, `:1351-1361`) | POLISH | Best-effort fetches fail silently; acceptable for detect/enrich but the rename-modal target-profile load leaves an unexplained empty vendor dropdown | Keep detect/enrich silent; surface a one-line inline note when `loadRenameTargetProfiles()` fails | S |
| 5 | `schedules.html:257`,`:284`; `configs.html:147`; `jobs.html:176` | POLISH | Inline per-row async buttons (toggle/delete-confirm/open) don't disable in flight → double-click races; delete-confirm second click 404s → false "Error" toast on a success | Disable clicked button at top of handler; treat 404-on-delete-after-success as success | S each |
| 6 | `netcanon/templates/_partials/job-progress.js:181-185` | POLISH | On `MAX_ERRORS` degrade the panel shows "Lost contact" but leaves stale spinning device rows and offers no retry (only reload recovers) | Add a small "Retry" link that restarts polling, or freeze the spinners to a neutral glyph | S |
| 7 | `netcanon/templates/index.html:311` vs route `backups.py:141` / `main.py:300` | POLISH | Dashboard POSTs `/api/v1/backups` (no slash) → 307 redirect to `/api/v1/backups/`; extra round-trip, surprising in network tab | POST to canonical `/api/v1/backups/` | S |
| 8 | `netcanon/templates/schedules.html:246-247` | POLISH | Schedule-create does a full `window.location.reload()` after success instead of injecting the new row (heavier than the in-place pattern used elsewhere) | Inject the new schedule row client-side (matches configs/dashboard pattern) — or accept as-is for a low-frequency action | M (optional) |

---

## What's notably GOOD (so synthesis doesn't "fix" non-problems)

- `formatApiError()` is the single most important async-UX asset — it's wired
  into essentially every load-bearing handler. Don't regress it.
- The job-progress panel's poll/persist/error-cap/event model is robust and
  correct; the "never trust the 202 POST body, poll to terminal" discipline is
  honored on the dashboard.
- Migrate's in-band parse-failure handling (200 + `job.error` + "Did you mean"
  suggestion) is genuinely good error UX, not a swallow.
- Empty states are present and actionable on every list page **except** the
  Sanitize-result-scaffold bug (finding #1).
- Inline Yes/No confirms (configs delete, schedules delete) instead of native
  `confirm()` are the right call for a themed app.

## Over-engineering / scope flags

- Finding #2's full-polling variant (M) may be more than `/jobs` warrants for a
  single-operator local tool — the cheap "Refresh button + hint" (S) is likely
  the right-sized fix. Flagging so synthesis doesn't reach for the heavier one.
- Finding #8 is optional; a full reload on a rare create action is acceptable.
  Listed only for consistency with the in-place pattern used elsewhere.
- Do NOT add a global blocking spinner/overlay — the per-button-disable pattern
  is the established, correct convention here; a global overlay would be a
  regression in feel.

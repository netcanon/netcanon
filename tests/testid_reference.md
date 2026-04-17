# `data-testid` Reference

Every interactive HTML element in the NetConfig templates carries a
`data-testid` attribute.  E2E tests use these attributes exclusively — never
CSS class names or element structure — so UI refactoring does not break tests.

## Navigation (`base.html`)

| `data-testid`      | Element | Notes |
|--------------------|---------|-------|
| `nav`              | `<nav>` | Top navigation bar |
| `nav-brand`        | `<a>`   | "NetConfig" brand link — navigates to `/` |
| `nav-home`         | `<a>`   | Link to `/`; has `class="active"` and `aria-current="page"` on Dashboard |
| `nav-jobs`         | `<a>`   | Link to `/jobs`; active on Jobs page |
| `nav-schedules`    | `<a>`   | Link to `/schedules`; active on Schedules page |
| `nav-configs`      | `<a>`   | Link to `/configs`; active on Configs page |
| `nav-definitions`  | `<a>`   | Link to `/definitions`; active on Definitions page |
| `nav-api-docs`     | `<a>`   | Link to `/docs` |
| `toast`            | `<div>` | Fixed-position toast notification; hidden by default |

## Dashboard (`index.html`)

### Backup form

| `data-testid`           | Element | Notes |
|-------------------------|---------|-------|
| `backup-form-section`   | `<section>` | Wraps the entire backup form |
| `backup-form`           | `<form>` | The form element itself |
| `device-list`           | `<div>` | Container for all device entry rows |
| `device-entry`          | `<div>` | One device row (cloned when adding devices) |
| `device-type-select`    | `<select>` | Device type dropdown; options carry `data-needs-enable` |
| `device-host-input`     | `<input>` | Host / IP field |
| `device-port-input`     | `<input type="number">` | SSH port (inside collapsed `<details>`; default 22) |
| `device-username-input` | `<input>` | Username field |
| `device-password-input` | `<input type="password">` | Password field |
| `device-enable-input`   | `<input type="password">` | Enable password; hidden when `data-needs-enable="false"` |
| `remove-device-btn`     | `<button>` | Remove this device row; hidden when only one row exists |
| `add-device-btn`        | `<button>` | Add a new device row |
| `submit-backup-btn`     | `<button type="submit">` | Start the backup job; disabled while job is in flight |

### Job status / results (now driven by the global Job progress panel)

The inline "banner" on the dashboard was replaced by a global floating
progress panel defined in `base.html` — see the **Job progress panel**
section below.  The legacy testids (`job-status-banner`, `job-id-display`,
`job-status-display`) are still exposed on the panel for backward
compatibility with existing E2E tests and helpers.

| `data-testid`          | Element | Notes |
|------------------------|---------|-------|
| `job-status-banner`    | `<div>` | **Alias** of `job-progress-panel` — the floating widget |
| `job-id-display`       | `<strong>` | First 8 chars of job UUID + "…" in the panel header |
| `job-status-display`   | `<span>` | Aggregated job status: `pending` / `running` / `completed` / `partial` / `failed`; hidden visually but readable for tests |

### Recent jobs table

| `data-testid`         | Element | Notes |
|-----------------------|---------|-------|
| `recent-jobs-section` | `<section>` | Wraps table + heading |
| `jobs-table`          | `<table>` | Always in DOM; `display:none` until first job exists |
| `job-row`             | `<tr>` | One row per job; also has `data-job-id` |
| `job-id-text`         | `<td>` | First 8 chars of job UUID + "…" (plain text, no link) |
| `job-status`          | `<span>` | Badge showing job status |
| `job-success-count`   | `<td>` | `success / total` |
| `job-created`         | `<td>` | Creation time (localised by JS); also has `data-utc` |
| `no-jobs-msg`         | `<p>` | Shown when no jobs exist; hidden by JS when first row injected |

## Configs page (`configs.html`)

| `data-testid`              | Element | Notes |
|----------------------------|---------|-------|
| `configs-table`            | `<table>` | Visible when configs exist |
| `config-row`               | `<tr>` | One row per config; also has `data-filename` |
| `config-filename`          | `<td>` | Filename (plain text) |
| `config-device-type`       | `<td>` | Device type |
| `config-host`              | `<td>` | Source device host |
| `config-timestamp`         | `<td>` | Capture time (localised by JS); also has `data-utc` |
| `config-size`              | `<td>` | Human-readable file size |
| `config-view-link`         | `<button>` | Opens config content in the shared modal viewer via `viewConfig()` |
| `config-download-btn`      | `<button>` | Triggers browser file download via `downloadConfig()` (WebView-safe blob approach) |
| `config-open-btn`          | `<button>` | Opens file in OS default editor via `POST …/open`; **only rendered when `open_in_editor=True`** (desktop app) |
| `config-delete-btn`        | `<button>` | Shows inline confirm — does NOT call `confirm()` |
| `config-delete-confirm-btn`| `<button>` | "Yes" — confirms deletion |
| `config-delete-cancel-btn` | `<button>` | "No" — cancels and restores Delete button |
| `no-configs-msg`           | `<p>` | Shown when no configs exist |
| `config-compare-btn`       | `<button>` | Opens the compare target-picker for that row; carries `data-filename`, `data-type-key`, `data-ext` |

### Compare target picker (modal on `/configs`)

Lightweight picker opened by `config-compare-btn`.  By default lists only
configs with matching `type_key` + `file_extension` (the compat anchors);
the "Show cross-vendor" toggle reveals the rest, dimmed.  Picking an
option navigates to `/configs/{source}/vs/{target}` (adding `?force=true`
for cross-vendor picks).

| `data-testid`                        | Element    | Notes |
|--------------------------------------|------------|-------|
| `compare-picker`                     | `<div>`    | Outer modal, `role="dialog"`, `aria-modal="true"` |
| `compare-picker-title`               | `<span>`   | "Compare {filename} with…" |
| `compare-picker-body`                | `<div>`    | Scrollable list of options |
| `compare-picker-show-all`            | `<input type="checkbox">` | Reveals cross-vendor options |
| `compare-picker-close`               | `<button>` | × — closes the modal |
| `compare-picker-empty`               | `<p>`      | Shown when no compatible options exist and cross-vendor is hidden |
| `compare-option`                     | `<a>`      | Compatible option (same `type_key` + ext); carries `data-filename` |
| `compare-option-cross-vendor`        | `<a>`      | Dimmed cross-vendor option; href includes `?force=true` |

### Diff page (`/configs/{left}/vs/{right}`)

Deep-linkable textual line-diff view.  The compatibility banner encodes
its severity via `data-severity="ok"|"warn"|"block"`.  Diff lines carry
`data-kind="equal"|"add"|"remove"` and `data-left-no` / `data-right-no`.

**Directional paradigm.** The URL's `left` is labelled "from" (the
starting point); `right` is "to" (the destination).  `+N` / `-M` in the
stats strip mean "added / removed going from the left file to the right
file".  The labels are temporally neutral — you might be comparing two
old configs, or yesterday's vs today's; the diff's direction holds either
way.  The "Reverse direction" button swaps the two.

| `data-testid`                     | Element    | Notes |
|-----------------------------------|------------|-------|
| `diff-back-link`                  | `<a>`      | ← Configs |
| `diff-from-label`                 | `<span>`   | "FROM" badge next to the left chip |
| `diff-left-filename`              | `<span>`   | Left file chip (monospace) — the "from" file |
| `diff-to-label`                   | `<span>`   | "TO" badge next to the right chip |
| `diff-right-filename`             | `<span>`   | Right file chip (monospace) — the "to" file |
| `diff-reverse-btn`                | `<a>`      | ⇋ Reverse direction — swaps FROM/TO by navigating to the URL with the two filenames swapped |
| `diff-compatibility-banner`       | `<div>`    | Carries `data-severity`; text + reasons |
| `diff-force-override-btn`         | `<a>`      | "Compare anyway" — only rendered for block + force=false |
| `diff-stats-added`                | `<span>`   | "+N" |
| `diff-stats-removed`              | `<span>`   | "−M" |
| `diff-stats-equal`                | `<span>`   | "N equal" |
| `diff-body`                       | `<div>`    | Dark container for the diff; carries `data-file-extension` for the syntax highlighter |
| `diff-line`                       | `<div>`    | One per diff line; carries `data-kind`, `data-left-no`, `data-right-no` |
| `diff-line-number-left`           | `<span>`   | Left-side line number (empty for `add`) |
| `diff-line-number-right`          | `<span>`   | Right-side line number (empty for `remove`) |
| `diff-line-marker`                | `<span>`   | `+`, `−`, or space |
| `diff-line-text`                  | `<span>`   | Line body; post-render, gets `.tok-*` syntax spans via `_cvRenderHighlighted` |
| `diff-line-collapsed`             | `<button>` | Expandable marker for a folded run of equal context; carries `data-count` (hidden line count) and `aria-expanded="false"`. Click / Enter / Space swaps in the hidden lines and removes the marker |
| `diff-collapsed-template`         | `<template>` | Immediate sibling of each `diff-line-collapsed` holding the hidden diff-line rows; content is inert until the marker is clicked |

## Job progress panel (`base.html` — global, persistent)

Floating bottom-right widget rendered on every page.  Receives job updates
via `startJobProgress(jobId)` and survives full page reloads — the active
job ID is stored in `localStorage["netconfig.activeJob"]`.  The panel
dispatches `CustomEvent`s on `document` that page-level code can listen for:

| Event                          | Detail              | When |
|--------------------------------|---------------------|------|
| `netconfig:job-started`        | `{ jobId }`         | `startJobProgress()` called |
| `netconfig:job-progress`       | `{ job }`           | Each poll tick |
| `netconfig:job-complete`       | `{ job }`           | Job reached terminal state |
| `netconfig:job-dismissed`      | `{ jobId }`         | User clicked dismiss OR manual clear |

### Per-device status SOP (values of `data-status` on a device row)

| value     | meaning                                            | icon  |
|-----------|----------------------------------------------------|-------|
| `queued`  | in the job but collector not yet called             | ○     |
| `running` | collector actively working on this device          | ⟳     |
| `success` | config saved to disk (terminal)                    | ✓     |
| `failed`  | error caught (terminal)                            | ✗     |

### Testids

| `data-testid`                    | Element    | Notes |
|----------------------------------|------------|-------|
| `job-progress-panel`             | `<div>`    | Outer panel; `aria-live="polite"`, `role="region"`. Also carries `data-job-status` attr for tests |
| `job-progress-header`            | `<div>`    | Clickable; toggles `job-progress-body` |
| `job-progress-summary`           | `<span>`   | "N/M complete — running: X — queued: Y" or final counts |
| `job-progress-toggle`            | `<span>`   | Chevron; gains `.open` when expanded |
| `job-progress-body`              | `<div>`    | Scrollable container for per-device rows |
| `job-progress-device-row`        | `<div>`    | One per device; carries `data-host`, `data-status` |
| `job-progress-device-status`     | `<span>`   | Status icon span with `.jp-icon-<status>` class |
| `job-progress-device-host`       | `<span>`   | "{device_type} {host}" label |
| `job-progress-device-duration`   | `<span>`   | "N.Ns" once device reaches terminal state |
| `job-progress-device-error`      | `<div>`    | Only rendered when `data-status="failed"`; truncated error with `title` |
| `job-progress-footer`            | `<div>`    | Appears only after job reaches terminal state |
| `job-progress-view-link`         | `<a>`      | Deep link to `/jobs#<job-id-short>` |
| `job-progress-dismiss`           | `<button>` | Hides panel AND clears the localStorage key |

## Config viewer modal (`base.html` — global)

Injected at the bottom of every page and opened by `viewConfig(filename)` (called
by every `config-view-link`, `job-config-view-link`, or `device-config-view-link`
button).  Carries in-modal search + syntax highlighting.

| `data-testid`                     | Element    | Notes |
|-----------------------------------|------------|-------|
| `config-viewer`                   | `<div>`    | Outer modal container; `display:none` when closed. `role="dialog"`, `aria-modal="true"` |
| `config-viewer-title`             | `<span>`   | Filename of the config currently displayed |
| `config-viewer-content`           | `<pre>`    | Rendered config with `.tok-*` syntax-highlight spans and `<mark>` search highlights |
| `config-viewer-search`            | `<input>`  | Incremental search input; Enter = next match, Shift+Enter = prev, Escape = clear / close |
| `config-viewer-search-count`      | `<span>`   | Live match counter: empty / "N / M" / "No matches" (aria-live="polite") |
| `config-viewer-search-prev`       | `<button>` | Jump to previous match (wraps); disabled when no matches |
| `config-viewer-search-next`       | `<button>` | Jump to next match (wraps); disabled when no matches |
| `config-viewer-close`             | `<button>` | `×` — closes the modal |

Syntax-highlight CSS classes applied by the tokenizer (not `data-testid`s but
useful for E2E assertions):

| Class          | Meaning |
|----------------|---------|
| `tok-comment`  | `!` / `#` comment lines (cfg) or `<!-- … -->` blocks (xml) |
| `tok-keyword`  | Vendor-agnostic keywords: `interface`, `hostname`, `ip`, `set`, `config`, … |
| `tok-string`   | Double-quoted strings |
| `tok-ip`       | IPv4 address (optionally with CIDR suffix) |
| `tok-number`   | Bare numeric token (non-IP) |
| `tok-tag`      | XML tag name (`<foo`, `</foo`) |
| `tok-attr`     | XML attribute name |

## Definitions page (`definitions.html`)

| `data-testid`          | Element | Notes |
|------------------------|---------|-------|
| `def-reload-btn`       | `<button>` | POSTs to `/api/v1/definitions/reload`; reloads page on success |
| `definitions-table`    | `<table>` | Visible when definitions are loaded |
| `definition-row`       | `<tr>` | One row per definition; also has `data-type-key` |
| `def-type-key`         | `<td>` | Type key cell |
| `def-vendor`           | `<td>` | Vendor name |
| `def-os`               | `<td>` | OS name |
| `def-strategy`         | `<td>` | Human-readable collection method (e.g. "SSH (Netmiko)") + optional device-type sub-line |
| `def-ext`              | `<td>` | File extension |
| `def-priority`         | `<td>` | Priority value |
| `def-notes`            | `<td>` | Notes truncated at 120 chars; full text in `title` tooltip |
| `no-definitions-msg`   | `<p>` | Shown when no definitions are loaded |

## Jobs page (`jobs.html`)

| `data-testid`             | Element | Notes |
|---------------------------|---------|-------|
| `no-jobs-msg`             | `<p>`   | Shown when no jobs exist |
| `job-card`                | `<div>` | One collapsible card per job; also has `data-job-id` and `id="job-{id[:8]}"` for anchor linking |
| `job-card-header`         | `<div>` | Clickable header row; calls `toggleJob()` to expand/collapse body |
| `job-id-text`             | `<span>`| First 8 chars of job UUID + "…" |
| `job-status`              | `<span>`| Status badge (`pending`, `running`, `completed`, `partial`, `failed`) |
| `job-success-count`       | `<span>`| `success / total` with ✓ (all-success), ⚠ (partial) or ✗ (all-fail) indicator |
| `job-created`             | `<span>`| Creation timestamp (localised by JS); also has `data-utc` |
| `job-duration`            | `<span>`| Total job duration in seconds; absent until job completes |
| `job-trigger`             | `<span>`| Schedule name (with calendar icon) or "Manual" for ad-hoc runs |
| `job-card-body`           | `<div>` | Expanded body; hidden by default |
| `job-result-row`          | `<tr>`  | One row per device result |
| `job-result-type`         | `<td>`  | Device type key |
| `job-result-host`         | `<td>`  | Device host / IP |
| `job-result-status`       | `<span>`| Per-device status badge |
| `job-result-file`         | `<td>`  | Config file cell — contains view/download/(open) links on success, or error message on failure |
| `job-config-view-link`    | `<a>`   | Navigates to `/configs#{filename}` — lands on Configs page, highlights the row, and auto-opens the viewer modal |
| `job-config-download-btn` | `<button>` | Triggers browser file download via `downloadConfig()` (WebView-safe blob approach) |
| `job-config-open-btn`     | `<button>` | Opens file in OS default editor; **only rendered when `open_in_editor=True`** (desktop app) |
| `job-result-error`        | `<span>`| Error text (≤100 chars, full text in `title` tooltip); shown when no config file exists |
| `job-result-duration`     | `<td>`  | Per-device duration in seconds |

## Schedules page (`schedules.html`)

### New schedule form

| `data-testid`                  | Element | Notes |
|-------------------------------|---------|-------|
| `new-schedule-section`         | `<section>` | Wraps the new schedule form |
| `schedule-form`                | `<form>` | The form element |
| `sched-name-input`             | `<input>` | Schedule name |
| `sched-interval-select`        | `<select>` | Preset interval: 1h / 6h / 12h / 24h (default) / 7d / Custom |
| `sched-custom-interval-input`  | `<input type="number">` | Custom interval in minutes; shown only when "Custom…" is selected |
| `sched-device-list`            | `<div>` | Container for all schedule device rows |
| `sched-device-entry`           | `<div>` | One device row (cloned on add) |
| `sched-device-type-select`     | `<select>` | Device type dropdown; options carry `data-needs-enable` |
| `sched-device-host-input`      | `<input>` | Host / IP field |
| `sched-device-username-input`  | `<input>` | Username field |
| `sched-device-password-input`  | `<input type="password">` | Password field |
| `sched-device-enable-input`    | `<input type="password">` | Enable password; hidden when `data-needs-enable="false"` |
| `sched-device-port-input`      | `<input type="number">` | SSH port (inside collapsed `<details>`; default 22) |
| `sched-remove-device-btn`      | `<button>` | Remove device row; hidden when only one row exists |
| `sched-add-device-btn`         | `<button>` | Add a new device row |
| `sched-submit-btn`             | `<button type="submit">` | Create schedule; disabled while request is in flight |

### Existing schedules table

| `data-testid`                  | Element | Notes |
|-------------------------------|---------|-------|
| `schedules-section`            | `<section>` | Wraps the schedules table |
| `no-schedules-msg`             | `<p>`   | Shown when no schedules exist |
| `schedules-table`              | `<table>` | Schedules table |
| `schedule-row`                 | `<tr>`  | One row per schedule; also has `data-schedule-id` |
| `schedule-name`                | `<td>`  | Schedule name (bold) with short UUID below |
| `schedule-interval`            | `<td>`  | Human-readable interval (e.g. "Every 24 hours") |
| `schedule-toggle-btn`          | `<button>` | Styled badge; click to toggle enabled/disabled; reloads page |
| `schedule-next-run`            | `<td>`  | Next scheduled run (localised by JS); also has `data-utc` |
| `schedule-last-run`            | `<td>`  | Last run timestamp (localised by JS); "Never" when never run; also has `data-utc` |
| `schedule-last-job`            | `<td>`  | Link to last job card (`/jobs#{id[:8]}`); "—" if none |
| `schedule-delete-btn`          | `<button>` | Shows inline confirm — does NOT call `confirm()` |
| `schedule-delete-confirm-btn`  | `<button>` | "Yes" — confirms deletion |
| `schedule-delete-cancel-btn`   | `<button>` | "No" — cancels and restores Delete button |

## Devices page (`devices.html`)

### New device profile form

| `data-testid`              | Element | Notes |
|----------------------------|---------|-------|
| `new-device-section`       | `<section>` | Wraps the new profile form |
| `device-form`              | `<form>` | The form element |
| `device-name-input`        | `<input>` | Profile name |
| `device-type-select`       | `<select>` | Device type dropdown; options carry `data-needs-enable` |
| `device-host-input`        | `<input>` | Host / IP field |
| `device-username-input`    | `<input>` | Username field |
| `device-password-input`    | `<input type="password">` | Password field |
| `device-enable-input`      | `<input type="password">` | Enable password; hidden when `data-needs-enable="false"` |
| `device-notes-input`       | `<input>` | Optional notes |
| `device-port-input`        | `<input type="number">` | SSH port (inside collapsed `<details>`; default 22) |
| `device-submit-btn`        | `<button type="submit">` | Create device profile |

### Existing device profile cards

| `data-testid`                  | Element | Notes |
|-------------------------------|---------|-------|
| `devices-section`              | `<section>` | Wraps all device cards |
| `no-devices-msg`               | `<p>` | Shown when no profiles exist |
| `device-card`                  | `<div>` | One collapsible card per profile; also has `data-device-id` and `data-profile` (JSON) |
| `device-card-header`           | `<div>` | Clickable header; `toggleDevice()` to show/hide config history |
| `device-name`                  | `<strong>` | Profile name |
| `device-type`                  | `<span>` | Type key badge |
| `device-host`                  | `<span>` | Host / IP |
| `device-run-btn`               | `<button>` | Triggers an immediate backup for this profile |
| `device-edit-btn`              | `<button>` | Shows/hides the inline edit panel |
| `device-delete-btn`            | `<button>` | Shows inline confirm — does NOT call `confirm()` |
| `device-delete-confirm-btn`    | `<button>` | "Yes" — confirms deletion |
| `device-delete-cancel-btn`     | `<button>` | "No" — cancels and restores Delete button |
| `device-card-body`             | `<div>` | Config history table; hidden by default |
| `device-config-row`            | `<tr>` | One row per config backup |
| `device-config-file`           | `<td>` | Config filename (monospace) |
| `device-config-timestamp`      | `<td>` | Capture time (localised by JS); also has `data-utc` |
| `device-config-size`           | `<td>` | Human-readable file size |
| `device-config-view-link`      | `<button>` | Opens config content in the shared modal viewer via `viewConfig()` |
| `device-config-download-btn`   | `<button>` | Triggers browser file download via `downloadConfig()` (WebView-safe blob approach) |

### Inline edit panel

| `data-testid`                  | Element | Notes |
|-------------------------------|---------|-------|
| `device-edit-panel`            | `<div>` | Inline edit form; hidden by default; also has `data-device-id` |
| `device-edit-form`             | `<form>` | Edit form element |
| `device-edit-name-input`       | `<input>` | Profile name |
| `device-edit-type-select`      | `<select>` | Device type dropdown |
| `device-edit-host-input`       | `<input>` | Host / IP |
| `device-edit-username-input`   | `<input>` | Username |
| `device-edit-password-input`   | `<input type="password">` | New password; leave blank to keep existing |
| `device-edit-enable-input`     | `<input type="password">` | New enable password; leave blank to keep existing |
| `device-edit-notes-input`      | `<input>` | Notes |
| `device-edit-port-input`       | `<input type="number">` | SSH port (inside collapsed `<details>`) |
| `device-edit-save-btn`         | `<button type="submit">` | Save changes |
| `device-edit-cancel-btn`       | `<button type="button">` | Cancel and close edit panel |

## Playwright Selector Patterns

```python
# Single element by testid
page.locator('[data-testid="backup-form"]')

# Row with a specific attribute value
page.locator('[data-testid="definition-row"][data-type-key="Cisco"]')

# First device entry's host input
page.locator('[data-testid="device-entry"]').first.locator('[data-testid="device-host-input"]')

# All definition rows
page.locator('[data-testid="definition-row"]').all()

# Inline delete confirm flow
page.locator('[data-testid="config-delete-btn"]').first.click()
page.locator('[data-testid="config-delete-confirm-btn"]').click()
```

## Migrate page (`/migrate`)

Translator workbench.  Pick a source and target adapter, paste or pick a
config, submit to `POST /api/v1/migration/plan`, review the validation
banner + rendered output in-place.  Reuses the config viewer's syntax-
highlight palette (via `_cvRenderHighlighted` from `base.html`) and the
diff page's banner severity palette (`diff-banner-*` / `mig-banner-*`).

### Shipped testids (Phase 2, part 1 — form + results)

| `data-testid`                         | Element    | Notes |
|---------------------------------------|------------|-------|
| `nav-migrate`                         | `<a>`      | Top-nav link, `active` when on `/migrate` |
| `migrate-form`                        | `<form>`   | Outer form; submit triggers `POST /plan` |
| `migrate-source-select`               | `<select>` | Source adapter; populated from `GET /adapters` |
| `migrate-target-select`               | `<select>` | Target adapter |
| `migrate-adapter-info`                | `<div>`    | Info strip: device-class chips + supported/lossy/unsupported counts for both adapters |
| `migrate-class-hint`                  | `<div>`    | Warning row rendered ONLY when source + target classes are disjoint (the class-guard would block) |
| `migrate-input-mode`                  | `<div>`    | Radio-group container |
| `migrate-input-mode-raw`              | `<input type="radio">` | Radio: paste raw text |
| `migrate-input-mode-filename`         | `<input type="radio">` | Radio: pick a stored config |
| `migrate-raw-wrap`                    | `<div>`    | Wrapper around the textarea; hidden when filename mode is active |
| `migrate-raw-input`                   | `<textarea>` | Config text input |
| `migrate-filename-wrap`               | `<div>`    | Wrapper around the stored-config dropdown |
| `migrate-filename-select`             | `<select>` | Options are existing ConfigRecord filenames |
| `migrate-force-checkbox`              | `<input type="checkbox">` | `force=true` skips the class guard |
| `migrate-submit-btn`                  | `<button type="submit">` | Runs the pipeline |
| `migrate-format-hint`                 | `<div>`    | Banner explaining what `parse()` expects for the picked source adapter; carries `data-input-format` attribute |
| `migrate-load-sample-btn`             | `<button>` | Populates the textarea with a known-good sample for the source adapter |
| `migrate-filename-compat-warn`        | `<div>`    | Visible only when the picked stored config's extension is unlikely to parse under the source adapter's `input_format` |
| `migrate-path-entry`                  | `<div>`    | One row inside any `migrate-paths-*` bucket; duplicate paths coalesce into a single entry with an `×N` count chip |
| `migrate-result`                      | `<div>`    | Hidden container for everything below; revealed after first result |
| `migrate-status-summary`              | `<div>`    | "Job {id}… — status: completed/partial/failed" |
| `migrate-compatibility-banner`        | `<div>`    | Severity-coloured banner mirroring `ValidationReport.severity` |
| `migrate-stats`                       | `<div>`    | Supported/lossy/unsupported path counts |
| `migrate-stat-supported`              | `<strong>` | Count number |
| `migrate-stat-lossy`                  | `<strong>` | Count number |
| `migrate-stat-unsupported`            | `<strong>` | Count number |
| `migrate-output-section`              | `<div>`    | Wrapper for the rendered-output block |
| `migrate-output`                      | `<pre>`    | Syntax-highlighted rendered text (`.tok-*` spans) |
| `migrate-copy-output-btn`             | `<button>` | Copies the plain rendered text to clipboard |
| `migrate-paths-section`               | `<div>`    | Expandable validation-details `<details>` |
| `migrate-paths-supported`             | `<div>`    | Path list for supported bucket |
| `migrate-paths-supported-count`       | `<span>`   | Count next to the heading |
| `migrate-paths-lossy`                 | `<div>`    | Path list for lossy bucket |
| `migrate-paths-lossy-count`           | `<span>`   | Count |
| `migrate-paths-unsupported`           | `<div>`    | Path list for unsupported bucket |
| `migrate-paths-unsupported-count`     | `<span>`   | Count |

### RESERVED for Phase 2 (transforms + deploy)

| `data-testid` (planned)               | Purpose |
|---------------------------------------|---------|
| `migrate-transforms-list`             | Container for applied transforms |
| `migrate-add-transform-btn`           | Open transform wizard |
| `migrate-semantic-delta-banner`       | Summary of `XPathDelta` list above the textual diff |
| `migrate-semantic-delta-item`         | One row per `XPathDelta` |
| `migrate-deploy-btn`                  | Initiate deploy (disabled while validation is blocked) |
| `migrate-confirm-deploy-btn`          | Inline "Yes, deploy now" confirmation |

Note: the rendered-output review step reuses the existing `/configs/{L}/vs/{R}`
diff page — no `migrate-diff-viewer` testid is needed.


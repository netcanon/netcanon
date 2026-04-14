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

### Job status / results banner

| `data-testid`          | Element | Notes |
|------------------------|---------|-------|
| `job-status-banner`    | `<div>` | Shown after form submit; hidden initially |
| `job-id-display`       | `<strong>` | First 8 chars of job UUID + "…" |
| `job-status-display`   | `<span>` | Live status: `pending` → `running` → `completed`/`failed`; replaced by per-device results table on completion |

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
| `config-view-link`         | `<a>` | Opens raw config in new tab |
| `config-download-btn`      | `<a download>` | Triggers browser file download |
| `config-open-btn`          | `<button>` | Opens file in OS default editor via `POST …/open`; **only rendered when `open_in_editor=True`** (desktop app) |
| `config-delete-btn`        | `<button>` | Shows inline confirm — does NOT call `confirm()` |
| `config-delete-confirm-btn`| `<button>` | "Yes" — confirms deletion |
| `config-delete-cancel-btn` | `<button>` | "No" — cancels and restores Delete button |
| `no-configs-msg`           | `<p>` | Shown when no configs exist |

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
| `job-status`              | `<span>`| Status badge (`pending`, `running`, `completed`, `failed`) |
| `job-success-count`       | `<span>`| `success / total` with ✓ or ✗ indicator |
| `job-created`             | `<span>`| Creation timestamp (localised by JS); also has `data-utc` |
| `job-duration`            | `<span>`| Total job duration in seconds; absent until job completes |
| `job-trigger`             | `<span>`| Schedule name (with calendar icon) or "Manual" for ad-hoc runs |
| `job-card-body`           | `<div>` | Expanded body; hidden by default |
| `job-result-row`          | `<tr>`  | One row per device result |
| `job-result-type`         | `<td>`  | Device type key |
| `job-result-host`         | `<td>`  | Device host / IP |
| `job-result-status`       | `<span>`| Per-device status badge |
| `job-result-file`         | `<td>`  | Config file cell — contains view/download/(open) links on success, or error message on failure |
| `job-config-view-link`    | `<a>`   | Opens raw config in new tab |
| `job-config-download-btn` | `<a download>` | Triggers browser file download |
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

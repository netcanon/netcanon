# `data-testid` Reference

Every interactive HTML element in the NetConfig templates carries a
`data-testid` attribute.  E2E tests use these attributes exclusively — never
CSS class names or element structure — so UI refactoring does not break tests.

## Navigation (`base.html`)

| `data-testid`      | Element | Notes |
|--------------------|---------|-------|
| `nav`              | `<nav>` | Top navigation bar |
| `nav-brand`        | `<span>` | "NetConfig" brand text |
| `nav-home`         | `<a>` | Link to `/` |
| `nav-configs`      | `<a>` | Link to `/configs` |
| `nav-definitions`  | `<a>` | Link to `/definitions` |
| `nav-api-docs`     | `<a>` | Link to `/docs` |

## Dashboard (`index.html`)

### Backup form

| `data-testid`           | Element | Notes |
|-------------------------|---------|-------|
| `backup-form-section`   | `<section>` | Wraps the entire backup form |
| `backup-form`           | `<form>` | The form element itself |
| `device-list`           | `<div>` | Container for all device entry rows |
| `device-entry`          | `<div>` | One device row (cloned when adding devices) |
| `device-type-select`    | `<select>` | Device type dropdown |
| `device-host-input`     | `<input>` | Host / IP field |
| `device-port-input`     | `<input type="number">` | SSH port field |
| `device-username-input` | `<input>` | Username field |
| `device-password-input` | `<input type="password">` | Password field |
| `device-enable-input`   | `<input type="password">` | Enable password (Cisco only) |
| `remove-device-btn`     | `<button>` | Remove this device row; hidden when only one row exists |
| `add-device-btn`        | `<button>` | Add a new device row |
| `submit-backup-btn`     | `<button type="submit">` | Start the backup job |

### Job status banner

| `data-testid`          | Element | Notes |
|------------------------|---------|-------|
| `job-status-banner`    | `<div>` | Shown after form submit; hidden initially |
| `job-id-display`       | `<strong>` | First 8 chars of job UUID + "…" |
| `job-status-display`   | `<span>` | Live status: `pending` → `running` → `completed`/`failed` |

### Recent jobs table

| `data-testid`         | Element | Notes |
|-----------------------|---------|-------|
| `recent-jobs-section` | `<section>` | Wraps table + heading |
| `jobs-table`          | `<table>` | Visible when jobs exist |
| `job-row`             | `<tr>` | One row per job; also has `data-job-id` |
| `job-link`            | `<a>` | Link to `GET /api/v1/backups/{id}` |
| `job-status`          | `<span>` | Badge showing job status |
| `job-device-count`    | `<td>` | Total device count |
| `job-success-count`   | `<td>` | `success / total` |
| `job-created`         | `<td>` | UTC creation time |
| `no-jobs-msg`         | `<p>` | Shown when no jobs exist |

## Configs page (`configs.html`)

| `data-testid`        | Element | Notes |
|----------------------|---------|-------|
| `configs-table`      | `<table>` | Visible when configs exist |
| `config-row`         | `<tr>` | One row per config; also has `data-filename` |
| `config-filename`    | `<td>` | Filename cell |
| `config-view-link`   | `<a>` | Opens raw config in new tab |
| `config-device-type` | `<td>` | Device type |
| `config-host`        | `<td>` | Source device host |
| `config-timestamp`   | `<td>` | Capture UTC timestamp |
| `config-size`        | `<td>` | Human-readable file size |
| `config-delete-btn`  | `<button>` | Delete this config (triggers JS fetch DELETE) |
| `no-configs-msg`     | `<p>` | Shown when no configs exist |

## Definitions page (`definitions.html`)

| `data-testid`          | Element | Notes |
|------------------------|---------|-------|
| `definitions-table`    | `<table>` | Visible when definitions are loaded |
| `definition-row`       | `<tr>` | One row per definition; also has `data-type-key` |
| `def-type-key`         | `<td>` | Type key cell |
| `def-vendor`           | `<td>` | Vendor name |
| `def-os`               | `<td>` | OS name |
| `def-strategy`         | `<td>` | Collector strategy + optional Netmiko device type |
| `def-ext`              | `<td>` | File extension |
| `def-priority`         | `<td>` | Priority value |
| `def-notes`            | `<td>` | Notes (truncated at 120 chars) |
| `no-definitions-msg`   | `<p>` | Shown when no definitions are loaded |

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
```

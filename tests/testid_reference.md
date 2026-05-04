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
| `nav-devices`      | `<a>`   | Link to `/devices`; active on Devices page |
| `nav-definitions`  | `<a>`   | Link to `/definitions`; active on Definitions page |
| `nav-api-docs`     | `<a>`   | Link to `/docs` |
| `nav-theme-toggle` | `<button>` | Right-aligned sun/moon toggle; flips `<html data-theme>` between `light`/`dark`, persists to `localStorage["netconfig.theme.v1"]`.  `aria-label` and `aria-pressed` live-update to reflect the ACTION (next-state), not the current state |
| `toast`            | `<div>` | Fixed-position toast notification; hidden by default |

## Dashboard (`index.html`)

### Backup form

| `data-testid`           | Element | Notes |
|-------------------------|---------|-------|
| `backup-form-section`   | `<section>` | Wraps the entire backup form |
| `backup-form`           | `<form>` | The form element itself |
| `device-list`           | `<div>` | Container for all device entry rows |
| `device-entry`          | `<div>` | One device row (cloned when adding devices) |
| `device-profile-select` | `<select>` | "Saved Device" picker — first option is ``— new device —`` for ad-hoc; subsequent options pre-fill the row from a persisted `DeviceProfile`.  Option elements carry `data-type-key`, `data-host`, `data-port`, `data-username` for client-side pre-fill |
| `device-type-select`    | `<select>` | Device type dropdown; options carry `data-needs-enable` |
| `device-host-input`     | `<input>` | Host / IP field |
| `device-port-input`     | `<input type="number">` | SSH port (inside collapsed `<details>`; default 22) |
| `device-username-input` | `<input>` | Username field |
| `device-password-input` | `<input type="password">` | Password field |
| `device-enable-input`   | `<input type="password">` | Enable password; hidden when `data-needs-enable="false"` |
| `remove-device-btn`     | `<button>` | Remove this device row; hidden when only one row exists |
| `add-device-btn`        | `<button>` | Add a new device row |
| `device-profile-name-input` | `<input>` | "Save as Profile" — optional free-text name.  When populated, the backup route creates/updates a persisted `DeviceProfile` alongside running the backup |
| `submit-backup-btn`     | `<button type="submit">` | Start the backup job; disabled while job is in flight |

### Job status / results (now driven by the global Job progress panel)

The inline "banner" on the dashboard was replaced by a global floating
progress panel defined in `base.html` — see the **Job progress panel**
section below.  Legacy `job-id-display` / `job-status-display` testids
are still exposed on the panel for backward compatibility with existing
E2E tests and helpers.

| `data-testid`          | Element | Notes |
|------------------------|---------|-------|
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

The page exposes four sections — one `section-*` testid per container.

### Section 1 — Backup-side device definitions

| `data-testid`          | Element | Notes |
|------------------------|---------|-------|
| `section-device-definitions`       | `<section>` | Wraps backup-side definitions section |
| `section-device-definitions-count` | `<span>` | Count badge in the section header |
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

### Section 2 — Version / model overlays

| `data-testid`          | Element | Notes |
|------------------------|---------|-------|
| `section-overlays`        | `<section>` | Wraps the overlays section (only rendered when overlays exist) |
| `section-overlays-count`  | `<span>` | Count badge in the section header |
| `overlays-table`          | `<table>` | Table of all loaded overlays |
| `overlay-row`             | `<tr>` | One row per overlay; also has `data-type-key`, `data-os-version`, `data-model` |
| `overlay-os-version`      | `<td>` | OS version pin (or em-dash if absent) |
| `overlay-model`           | `<td>` | Model pin (or em-dash if absent) |

### Section 3 — Migration target profiles

| `data-testid`          | Element | Notes |
|------------------------|---------|-------|
| `section-target-profiles`       | `<section>` | Wraps the target-profiles browsing section |
| `section-target-profiles-count` | `<span>` | Total profile count badge |
| `defs-profile-filter`           | `<input type="search">` | Live client-side filter over vendor + model + display name |
| `defs-profile-filter-count`     | `<span>` | "N matches" live count while filter is active (empty when blank) |
| `profile-vendor-group`          | `<details>` | Outer collapsible per vendor; `data-vendor` carries the vendor key |
| `profile-vendor-name`           | `<span>` | Vendor label inside the group summary |
| `target-profile-row`            | `<details>` | One collapsible per model; carries `data-vendor`, `data-model`, `data-haystack` (pre-lowercased for filter match) |
| `profile-display-name`          | `<span>` | Human-readable model label inside the profile summary |
| `profile-module-count`          | `<span>` | "N module variant(s)" hint in the summary (absent when profile has no modules) |
| `profile-base-ports-heading`    | `<div>` | Sub-heading for the chassis-fixed port chip list |
| `profile-base-ports`            | `<div>` | Port-chip container for the base ports |
| `profile-modules-heading`       | `<div>` | Sub-heading for the modules section (absent when profile has no modules) |
| `profile-module`                | `<div>` | One module card; `data-sku` carries the module SKU |
| `profile-module-sku`            | `<span>` | SKU label inside the module card |
| `profile-module-ports`          | `<div>` | Port-chip container for this module's uplinks |
| `no-target-profiles-msg`        | `<p>` | Empty-state message when no profiles are loaded |

### Section 4 — Migration vendors + codec capabilities

| `data-testid`          | Element | Notes |
|------------------------|---------|-------|
| `section-vendors`       | `<section>` | Wraps the vendors section |
| `section-vendors-count` | `<span>` | Vendor count badge |
| `vendor-row`            | `<details>` | One collapsible per vendor; `data-vendor-id` carries the vendor ID |
| `vendor-display-name`   | `<span>` | Human-readable vendor name in the summary |
| `vendor-id`             | `<code>` | Stable vendor ID (e.g. `cisco_iosxe`) |
| `vendor-codecs-table`   | `<table>` | Nested table of codecs registered under this vendor |
| `vendor-codec-row`      | `<tr>` | One codec row; `data-codec-name` carries the codec name |
| `codec-name`            | `<code>` | Codec identifier (matches `CodecBase.name`) |
| `codec-direction`       | `<span class="defs-pill">` | Pill: `parse_only` / `render_only` / `bidirectional` |
| `codec-certainty`       | `<span class="defs-pill defs-pill-<tier>">` | Pill: `certified` / `best_effort` / `experimental` |
| `codec-caps-counts`     | `<td>` | Capability-matrix counts cell wrapping the three chips below |
| `codec-caps-chip-supported`   | `<button>` | Clickable count chip `✓ N` for supported xpaths.  Click expands a detail row showing the full path list.  `disabled` when `N == 0` |
| `codec-caps-chip-lossy`       | `<button>` | Clickable count chip `⚠ N` for lossy xpaths.  Click expands a detail row showing each path + reason + severity (`warn` / `error`) |
| `codec-caps-chip-unsupported` | `<button>` | Clickable count chip `✗ N` for unsupported xpaths.  Click expands a detail row showing each path + reason |
| `codec-caps-detail-row`       | `<tr>` | Dynamically-inserted row that drops in beneath a `vendor-codec-row` when a chip is clicked.  `data-codec-name` matches the parent codec; `data-bucket` is `supported` / `lossy` / `unsupported` |
| `codec-caps-detail-list-supported`  | `<ul>` | Inside the detail row when bucket=supported.  Two-column grid: path, blank reason cell |
| `codec-caps-detail-list-lossy`      | `<ul>` | Inside the detail row when bucket=lossy.  Two-column grid: path, severity-tagged reason |
| `codec-caps-detail-list-unsupported`| `<ul>` | Inside the detail row when bucket=unsupported.  Two-column grid: path, severity-tagged reason |

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

### Target pickers (device-type × specific-profile)

Flanking the inline device list, the schedule form exposes two
checkbox grids that let the operator back up "all profiles of
these types" OR "these specific profiles" (or both — inclusive
union).  Empty-state messages render when no device profiles
exist yet.

| `data-testid`                  | Element | Notes |
|-------------------------------|---------|-------|
| `sched-type-keys-section`      | `<div>` | Wraps the type-key checkbox grid — one checkbox per loaded device definition |
| `sched-type-key-checkbox`      | `<input type="checkbox">` | One per `type_key`; `value` carries the definition key; checked types get every matching `DeviceProfile` in the resulting schedule |
| `sched-devices-section`        | `<div>` | Wraps the specific-profile checkbox grid — one checkbox per persisted `DeviceProfile` |
| `sched-device-checkbox`        | `<input type="checkbox">` | One per saved profile; `value` carries the profile UUID; checked profiles get included in the schedule regardless of `type_key` selection |
| `no-profiles-for-sched-msg`    | `<p>` | Empty-state — shown inside `sched-devices-section` when no `DeviceProfile` records exist yet.  Links to `/devices` for the user to add one |

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
| `device-os-version-input`  | `<input>` | Optional OS-version pin (e.g. ``17.12``).  Layered-definitions overlay selector — when set, the backup pipeline's `DefinitionLoader.resolve()` picks a matching overlay YAML instead of the family base.  Inside a collapsed `<details>` labelled "Pin" |
| `device-model-input`       | `<input>` | Optional hardware-model pin (e.g. ``C9300-48P``).  Same overlay-selection semantics as ``device-os-version-input`` — rarely needed since backup CLI behaviour almost never varies by model |
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
| `device-confirm-<id>`          | `<span>` | Inline confirm container revealed by `device-delete-btn`; `<id>` is the device profile UUID. Wraps the Yes/No buttons below |
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
| `device-edit-os-version-input` | `<input>` | Edit the OS-version pin.  Inside a collapsed `<details>` labelled "Pin"; the `<details>` is auto-opened when the profile already has a pin set.  Blank = "keep existing" (same pattern as ``enable_password`` / ``notes``) |
| `device-edit-model-input`      | `<input>` | Edit the model pin |
| `device-edit-detected-facts`   | `<div>` | Read-only panel shown only when ``profile.detected_facts`` is non-null.  Populated by a server-side probe on a previous backup (P1C3 wiring); operators cross-reference against their pinned OS-version / model above.  Contents are per-fact child spans; not editable |
| `device-edit-detected-fact-<key>` | `<div>` | One per-fact display row inside ``device-edit-detected-facts``.  ``<key>`` is the fact key with underscores converted to hyphens (e.g. ``device-edit-detected-fact-os-version``, ``device-edit-detected-fact-firmware-build``, ``device-edit-detected-fact-probe-timestamp``) |
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
| `migrate-tier3-banner`                | `<div>`    | Notification banner — visible iff `MigrationJob.dropped_tier3_sections` is non-empty.  Surfaces source-side stanza headers the parser deliberately drops (ACLs, NAT, QoS, route-maps, IPsec, etc).  See `netconfig/migration/_tier3_detection.py` |
| `migrate-tier3-count`                 | `<strong>` | Detected-section count rendered inside the Tier-3 banner |
| `migrate-tier3-section-N`             | `<li>`     | One row per detected stanza header, indexed `N=0..len-1`.  Children are `<code>` elements with the literal label |
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

### Auto-detection (R5 — source codec suggestion)

| `data-testid`                         | Element    | Notes |
|---------------------------------------|------------|-------|
| `migrate-detect-banner`               | `<div>`    | Shown after `POST /api/v1/migration/detect` returns a candidate.  Carries `data-detected-codec` + `data-detected-confidence` attrs.  Green when the user has already picked the detected codec; blue when a switch is offered |
| `migrate-detect-use-btn`              | `<button>` | "Use this source" — clicking sets `migrate-source-select` to the detected codec.  Only rendered when the currently-selected source differs from the detected one |

### Rendered-output actions

| `data-testid`                         | Element    | Notes |
|---------------------------------------|------------|-------|
| `migrate-download-output-btn`         | `<button>` | Downloads the rendered text as a file (uses the extension from the target codec's `output_extension`) |

### Validation-details headings

Inside each `migrate-paths-<bucket>` container:

| `data-testid`                         | Element    | Notes |
|---------------------------------------|------------|-------|
| `migrate-paths-supported-heading`     | `<h4>` / `<summary>` | Heading for the supported-paths bucket |
| `migrate-paths-lossy-heading`         | `<h4>` / `<summary>` | Heading for the lossy-paths bucket |
| `migrate-paths-unsupported-heading`   | `<h4>` / `<summary>` | Heading for the unsupported-paths bucket |

### Tier-3 rename modal

Interactive port-name override surface opened from the migration
result banner.  JS lives in two partials that migrate.html pulls in
via Jinja `{% include %}`: `_partials/rename-table.js` (the
per-kind expandable sections) and `_partials/rename-panel.js`
(preview + summary), with `_partials/fit-check.js` rendering the
hardware-capacity banner and `_partials/classify.js` housing the
shared `_guessKind` / `_looksLikeUplink` classifiers both renderers
reuse.  The modal is re-rendered whenever the user changes any
override, drop, or selector.

**Open / trigger:**

| `data-testid`                         | Element    | Notes |
|---------------------------------------|------------|-------|
| `migrate-rename-open-btn`             | `<button>` | "Rename port names" — opens the modal; only rendered when the result has at least one `port_renames` entry or a port-name warning |
| `migrate-rename-badge-count`          | `<span>`   | Small badge on the open button showing the server's auto-renamed count |

**Modal chrome:**

| `data-testid`                         | Element    | Notes |
|---------------------------------------|------------|-------|
| `migrate-rename-modal`                | `<div>`    | Outer modal container; `role="dialog"`. Has `open` class when visible; CSS `transform: translateX(-50%)` flips to absolute positioning during drag |
| `migrate-rename-modal-header`         | `<div>`    | Drag handle; `mousedown` on header starts the modal drag. Buttons inside the header are excluded from the drag hit region |
| `migrate-rename-modal-close`          | `<button>` | × — closes without applying |
| `migrate-rename-modal-reset`          | `<button>` | "Clear all" — wipes `_renameUserMap` and re-renders |
| `migrate-rename-apply-btn`            | `<button>` | "Apply" — re-POSTs to `/api/v1/migration/plan` with `port_rename_map`; disabled when any collisions exist |
| `migrate-rename-cancel-btn`           | `<button>` | "Cancel" — closes the modal |
| `migrate-rename-status`               | `<div>`    | Inline status line ("Applying…", "Applied. Rendered output refreshed.", etc.) |

**Three-stage target-profile selector** (vendor → model → module).
The module dropdown is hidden for legacy profiles and surfaces only
when the picked profile declares `modules:` in its YAML:

| `data-testid`                         | Element    | Notes |
|---------------------------------------|------------|-------|
| `migrate-rename-target-vendor-select` | `<select>` | Stage 1 — vendor family |
| `migrate-rename-target-model-select`  | `<select>` | Stage 2 — chassis model; cascades to reset the module dropdown |
| `migrate-rename-target-module-select` | `<select>` | Stage 3 — swappable uplink module (NM-8X, NM-2Q, JL083A, …); hidden when `profile.modules == {}` |
| `migrate-rename-target-profile-group` | `<span>`   | Wrapper around the three vendor / model / module dropdowns — hidden (`display:none`) when active rail category is not `ports`, since profile data drives only the ports pane's dropdown-vs-freetext rows and the fit-check banner |

**Per-kind row table** (driven by `_RENAME_KIND_ORDER` in
migrate.html):

| `data-testid`                         | Element    | Notes |
|---------------------------------------|------------|-------|
| `migrate-rename-table-pane`           | `<div>`    | Left pane holding the kind sections and the empty-state message |
| `migrate-rename-sections`             | `<div>`    | Container the renderer clears and rebuilds on each call |
| `migrate-rename-section-<kind>`       | `<details>`| One per non-empty kind; `<kind>` is one of `physical`, `breakout`, `lag`, `svi`, `loopback`, `tunnel`, `mgmt`, `hw_aggregate`, `virtual`, `unknown` |
| `migrate-rename-row-<source>`         | `<tr>`     | One per port; `<source>` is the literal source-side port name (e.g. `GigabitEthernet1/0/1`).  **Forward slashes and dots are preserved verbatim** in the attribute value — do not URL-encode or escape.  CSS classes `has-warning` / `has-collision` / `has-override` / `has-drop` / `has-auto-drop` signal row state |
| `migrate-rename-override-<source>`    | `<select>` or `<input>` | Target-name dropdown when a profile is selected; free-form input when not.  The dropdown's first option is "(auto: X)" / "(auto-dropped)" and lists the profile's valid port IDs filtered by kind |
| `migrate-rename-drop-<source>`        | `<span>`   | Inline link beside free-form inputs.  Text cycles "drop" / "un-drop" / "keep verbatim" based on the row's drop state |
| `migrate-rename-table-empty`          | `<div>`    | Empty-state message when no renames or warnings exist |

**Supplementary panels:**

| `data-testid`                         | Element    | Notes |
|---------------------------------------|------------|-------|
| `migrate-rename-preview-pane`         | `<div>`    | Right pane holding preview + summary + fit-check |
| `migrate-rename-preview`              | `<pre>`    | Client-side approximation of the target output with user overrides applied via whole-word replacement; informational only — the Apply button re-runs the server-side render for the authoritative result |
| `migrate-rename-summary`              | `<div>`    | Inline summary above Apply: "N auto / M override / K drops / W ⚠ / C collisions". Collision count disables the Apply button |
| `migrate-rename-summary-vlans`        | `<span>`   | Nested sub-summary inside `migrate-rename-summary` — "VLAN: A auto / B overrides / C drops".  Only present when any VLAN-category state exists (server-applied rewrites or user overrides/drops); absent from port-only sessions |
| `migrate-rename-fitcheck`             | `<div>`    | Hardware fit-check banner.  CSS class `fit-ok` / `fit-warn` / `fit-block` encodes overall state |
| `migrate-fitcheck-kind-<kind>`        | `<span>`   | Per-kind count line ("access: 24 / 24"); `<kind>` is one of `physical`, `uplink`, `mgmt` — **closed enumeration** as of this writing (fit-check.js hardcodes the list in `KIND_ORDER`).  Adding a new kind requires touching both the partial and this doc |
| `migrate-fitcheck-module-note`        | `<span>`   | "(module: NM-8X)" suffix on the banner when a module SKU is selected; omitted for legacy profiles |

**Left-rail category nav + VLAN pane** (P2C3 — per-category override
surfaces under a shared left-rail navigation):

| `data-testid`                         | Element    | Notes |
|---------------------------------------|------------|-------|
| `migrate-rename-rail`                 | `<nav>`    | Left rail — vertical list of category buttons.  `aria-label="Rename modal categories"` |
| `migrate-rename-rail-ports`           | `<button>` | Activates the Ports category pane.  Carries `data-category="ports"` and `active` CSS class when selected |
| `migrate-rename-rail-ports-count`     | `<span>`   | Row-count badge on the Ports rail button (applied + warned rows) |
| `migrate-rename-rail-vlans`           | `<button>` | Activates the VLANs category pane.  `data-category="vlans"` |
| `migrate-rename-rail-vlans-count`     | `<span>`   | Row-count badge on the VLANs rail button (source_vlans.length) |
| `migrate-rename-ports-pane`           | `<div>`    | Ports category pane wrapper — holds the per-kind rename sections.  `active` CSS class when visible |
| `migrate-rename-vlans-pane`           | `<div>`    | VLANs category pane wrapper.  `active` CSS class when visible |
| `migrate-rename-vlans-empty`          | `<div>`    | Empty-state message when the source config declared no VLANs |
| `migrate-rename-vlans-sections`       | `<div>`    | Container the VLAN pane renderer clears and rebuilds on each call |
| `migrate-rename-vlans-table`          | `<table>`  | The single VLAN rewrite table — no per-kind sections, since VLAN IDs don't have a physical taxonomy |
| `migrate-rename-vlan-row-<id>`        | `<tr>`     | One per source VLAN; `<id>` is the literal integer source VLAN ID (e.g. `10`, `4094`).  CSS classes `has-override` / `has-drop` / `has-auto-drop` / `has-collision` signal row state |
| `migrate-rename-vlan-override-<id>`   | `<input>`  | Integer target-ID input.  `type="number"` with `min=1 max=4094`; blank = accept auto default.  Typing invalid input (non-numeric, out-of-range) silently no-ops rather than storing the bad value |
| `migrate-rename-vlan-drop-<id>`       | `<span>`   | Inline drop / un-drop / keep-verbatim link beside the override input — same three-state logic as port rows |
| `migrate-rename-rail-local-users`     | `<button>` | Activates the Local Users category pane.  `data-category="local_users"` |
| `migrate-rename-rail-local-users-count` | `<span>` | Row-count badge on the Local Users rail button (source_local_users.length) |
| `migrate-rename-local-users-pane`     | `<div>`    | Local-users category pane wrapper.  `active` CSS class when visible |
| `migrate-rename-local-users-empty`    | `<div>`    | Empty-state message when the source config declared no local users |
| `migrate-rename-local-users-sections` | `<div>`    | Container the local-users pane renderer clears and rebuilds on each call |
| `migrate-rename-local-users-table`    | `<table>`  | The single local-user rewrite table — no per-kind sections (users are uncategorised strings) |
| `migrate-rename-local-user-row-<username>` | `<tr>` | One per source local user; `<username>` is the literal source username (alphanumerics, hyphens, etc. preserved verbatim).  CSS classes `has-override` / `has-drop` / `has-auto-drop` / `has-collision` signal row state |
| `migrate-rename-local-user-override-<username>` | `<input>` | Free-text target-username input.  `type="text"`; blank = accept auto default / keep unchanged.  Non-empty value triggers a rename on Apply |
| `migrate-rename-local-user-drop-<username>` | `<span>` | Inline drop / un-drop / keep-verbatim link — same three-state logic as port + VLAN rows |
| `migrate-rename-summary-local-users`  | `<span>`   | Nested sub-summary inside `migrate-rename-summary` — "Users: A auto / B overrides / C drops".  Only present when any local-user-category state exists |
| `migrate-rename-local-users-compat`   | `<div>`    | Amber target-codec compatibility banner inside the local-users pane.  Shows when the active target codec's `unsupported_rename_categories` list includes `local_users`.  Warns the operator that rename overrides will apply to the canonical tree but won't reach rendered output until the codec's Tier-2 parse+render path ships |
| `migrate-rename-vlans-fitcheck`       | `<div>`    | Per-pane fit-check banner inside the VLANs pane.  Shows when the active target profile declares `max_vlans`.  Three CSS states: hidden (no profile / no limit), `mig-banner-ok` (source count ≤ limit), `mig-banner-block` (source count > limit) |
| `migrate-rename-local-users-fitcheck` | `<div>`    | Per-pane fit-check banner inside the local-users pane.  Same three-state contract as the VLAN banner, driven by target profile's `max_local_users` field |
| `migrate-rename-rail-snmp`            | `<button>` | Activates the SNMP category pane.  `data-category="snmp"`.  Fourth per-pane category (P2C5) |
| `migrate-rename-rail-snmp-count`      | `<span>`   | Row-count badge on the SNMP rail button.  Shows `1` when the source config declared a community string, `0` otherwise (scalar canonical surface, not a list) |
| `migrate-rename-snmp-pane`            | `<div>`    | SNMP category pane wrapper.  `active` CSS class when visible |
| `migrate-rename-snmp-empty`           | `<div>`    | Empty-state message when the source config has no SNMP block or a bare block without a community configured |
| `migrate-rename-snmp-sections`        | `<div>`    | Container the SNMP pane renderer clears and rebuilds on each call.  Holds the single-row community-rename table |
| `migrate-rename-snmp-table`           | `<table>`  | The single-row SNMP community rewrite table.  Structurally a table for visual parity with the list-oriented panes; always exactly one data row because the canonical tree holds one community string |
| `migrate-rename-snmp-community-row`   | `<tr>`     | The single community-rename row.  No per-row `<src>` suffix — there's only one.  CSS classes `has-override` / `has-drop` / `has-auto-drop` signal row state |
| `migrate-rename-snmp-community-override` | `<input>` | Free-text new-community input.  `type="text"`; blank = keep current / accept auto.  Non-empty value triggers a rename on Apply |
| `migrate-rename-snmp-community-drop`  | `<span>`   | Inline clear / un-clear / keep-verbatim link.  "clear" is the SNMP equivalent of "drop" — renders the SNMP block out entirely rather than removing an identity |
| `migrate-rename-summary-snmp`         | `<span>`   | Nested sub-summary inside `migrate-rename-summary` — "SNMP: A auto / B overrides / C clears".  Only present when any SNMP-category state exists |
| `migrate-rename-snmp-compat`          | `<div>`    | Amber target-codec compatibility banner inside the SNMP pane.  Shows when the active target codec's `unsupported_rename_categories` list includes `snmp`.  Mirrors the local-users pane's banner pattern |
| `migrate-rename-rail-snmpv3`          | `<button>` | Activates the SNMPv3 category pane.  `data-category="snmpv3"`.  Fifth per-pane category (P2C6) |
| `migrate-rename-rail-snmpv3-count`    | `<span>`   | Row-count badge on the SNMPv3 rail button.  Shows source USM user count — list-oriented surface, parallel to local_users |
| `migrate-rename-snmpv3-pane`          | `<div>`    | SNMPv3 category pane wrapper.  `active` CSS class when visible |
| `migrate-rename-snmpv3-empty`         | `<div>`    | Empty-state message when the source config has no SNMPv3 users (v1/v2c-only source, or no SNMP block at all) |
| `migrate-rename-snmpv3-sections`      | `<div>`    | Container the SNMPv3 pane renderer clears and rebuilds.  Holds the per-user rename table |
| `migrate-rename-snmpv3-table`         | `<table>`  | The SNMPv3 USM user rewrite table — structural sibling of `migrate-rename-local-users-table` (list-oriented, one row per user) |
| `migrate-rename-snmpv3-user-row-<name>` | `<tr>`   | One per source SNMPv3 user; `<name>` is the literal USM securityName.  CSS classes `has-override` / `has-drop` / `has-auto-drop` / `has-collision` signal row state |
| `migrate-rename-snmpv3-user-override-<name>` | `<input>` | Free-text target-securityName input.  `type="text"`; blank = keep unchanged; non-empty = rename on Apply.  Auth / priv / group / engine_id follow the renamed record |
| `migrate-rename-snmpv3-user-drop-<name>` | `<span>` | Inline drop / un-drop / keep-verbatim link — three-state logic parallel to the local-users pane |
| `migrate-rename-summary-snmpv3`       | `<span>`   | Nested sub-summary inside `migrate-rename-summary` — "SNMPv3: A auto / B overrides / C drops".  Only present when any v3-category state exists |
| `migrate-rename-snmpv3-compat`        | `<div>`    | Amber target-codec compatibility banner inside the SNMPv3 pane.  Shows when the active target codec's `unsupported_rename_categories` list includes `snmpv3` (OPNsense, Cisco IOS-XE NETCONF stub) |

### RESERVED for Phase 2 (transforms + deploy)

> **Aspirational — not yet shipped.**  The testids in the table below are
> reserved names for the upcoming Phase 2 work (transforms wizard, semantic
> delta banner, deploy confirmation flow).  None of these testids exist in
> any template today.  Searching the `netconfig/templates/` tree for any of
> them will return zero hits — that is expected.
>
> They are listed here so the Phase 2 implementation lands with stable
> selectors that match the rest of the migrate-page naming convention.  Do
> not write E2E tests against these names until the corresponding template
> elements exist; the tests will fail.

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

---

## See also

- [`README.md`](README.md) — test-suite layout, markers, mocking strategy
- [`../ARCHITECTURE.md`](../ARCHITECTURE.md) — four-layer design and template organisation
- [`../CLAUDE.md`](../CLAUDE.md) — selectors discipline (every interactive element carries a `data-testid`)


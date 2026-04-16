# Changelog

All notable changes to NetConfig are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Added (translator Phase 1 — OPNsense adapter + write endpoints)

- **Second real adapter: `OPNsenseAdapter`** under
  `netconfig/migration/adapters/opnsense/`.  Parses/renders OPNsense
  `config.xml`.  Scope: system hostname/domain and interfaces
  (zone, `if`, descr, enable-flag, ipaddr, subnet).  Declares
  `device_classes=[firewall, router]`.
- **OPNsense zone-keyed interface idiom flattened** at parse time:
  native `<wan>…</wan><lan>…</lan>` children become a list of dicts
  with a synthetic `zone` key, so `iter_xpaths` can emit OpenConfig-
  style schema paths (no list keys).  The render step reverses the
  transformation.  Round-trip invariant `parse(render(tree)) == tree`
  is tested with sanitised 3-interface fixture.
- **Cross-vendor guardrail shown working:** OPNsense ∩ IOS-XE =
  `{router}`, so the class guard permits the migration; the per-
  xpath capability matrices then honestly flag firewall rules
  (`/filter/rule`, `/nat/outbound`) as unsupported by IOS-XE.
  The intended layering — class guard for coarse "is this meaningful
  at all?", capability matrix for fine "which features translate?".

- **New write endpoints:**
  - `POST /api/v1/migration/plan` — runs the full pipeline
    (class-guard → parse → transforms → validate → render) on a
    raw config payload.  Returns the `MigrationJob` as JSON, even
    on parse failure (the error is in `job.error`, not an HTTP
    status).  Callers inspect `job.status` for the outcome.
  - `POST /api/v1/migration/render` — currently an alias for
    `/plan`; kept as a separate route so Phase 2 can split plan
    (no side effects) from render (pre-deploy snapshot + diff URL)
    without another API rev.
  - Input mode toggle: request body supplies EITHER `raw_text` OR
    `source_filename` (which loads from the existing backup store).
    Exactly one MUST be set — otherwise 422.  Source-filename
    shorthand means you can migrate any stored config without
    shipping the bytes through HTTP.
  - `force=true` in the body skips the device-class guard.
- **New model:** `MigrationPlanRequest` in
  `netconfig.models.migration` — documented, tested, ready for a
  Phase 2 UI to reuse.

- **Manual testing now possible** end-to-end via curl:

      curl -X POST http://127.0.0.1:8000/api/v1/migration/plan \
           -H 'Content-Type: application/json' \
           -d '{"source":"cisco_iosxe","target":"cisco_iosxe",
                "raw_text":"<interfaces xmlns=\"http://openconfig.net/yang/interfaces\">…"}'

- **Tests (+32):**
  - `tests/unit/migration/test_opnsense.py` (21): parse, errors,
    render determinism, round-trip invariant (inline + fixture),
    iter_xpaths coverage, capability declarations, cross-adapter
    class-intersection, registry.
  - `tests/integration/test_migration_api.py` (+11): plan endpoint
    happy path, 422 variants (unknown source, unknown target,
    neither/both input modes), 404 for missing filename, parse
    failure returns 200 with failed job, force flag round-trip,
    render is alias, end-to-end integration with backup store.
  - `tests/fixtures/opnsense/config_simple.xml` — sanitised sample.

- **Total suite:** 567 passing (was 535, +32).  Migration suite
  alone: 184 tests (was 140, +44 across OPNsense + API integration).

### Added (translator: adversarial-input hardening + cross-adapter tests)

- **Strict YANG boolean parsing.** `CiscoIOSXEAdapter` used to silently
  coerce any `<enabled>` text other than literal `true` to `False` —
  meaning `<enabled>yes</enabled>` would ship a DISABLED interface.
  The parser now rejects every non-RFC-7950 spelling (`yes`, `no`,
  `1`, `0`, `on`, `off`, empty string, …) with a `ParseError` that
  names the exact xpath.
- **IPv4 prefix-length range check.** Previously values like `99`
  or `-1` were accepted silently and round-tripped into the rendered
  NETCONF payload, where the device would reject the edit at deploy
  time.  The parser now enforces the YANG `inet:ipv4-prefix` range
  (`0..32`).
- **Interface-index error paths.** Empty or missing `<name>` elements
  now raise a `ParseError` whose `path` includes the zero-based
  `interface[N]` index and whose `snippet` contains the offending
  element serialised to XML (capped at 200 chars).  A device
  returning ten interfaces with one malformed entry is now locatable
  in ~5 seconds instead of "open the XML and scroll".
- **UTF-8 BOM tolerance.** Some devices (and some editors) prepend a
  BOM to their XML declaration.  Test lock-in so this stays working.
- **Cross-adapter pipeline tests** (`tests/unit/migration/
  test_cross_adapter_pipeline.py`): prove stage transitions, error
  routing, and type boundaries that no single-adapter test touches:
  - IOS-XE → mock: class guard permits, nested walker reaches leaves,
    render produces JSON despite type-shape mismatch.
  - Mock → IOS-XE: render mismatch caught as `failed` with useful
    error; validation still ran first; `completed_at` is always set.
  - Partial-status routing: a validation `block` with a successful
    render correctly lands in `partial`, not `completed` or `failed`.
  - Stage ordering: class guard runs at stage 0, before parse — a
    disjoint-class pair with broken XML fails with the class-guard
    error, not a parser error.
- **Tests (+22)**:
  - `test_cisco_iosxe.py`: 10 new adversarial-input tests covering
    the four hardening items above.
  - `test_cross_adapter_pipeline.py`: 11 new pipeline scenarios.
  - Full migration suite now 140 tests (was 97 before this hardening
    pass, 77 before Phase 0.5's round-trip work, 30 at end of Phase 0).
- Full project suite: **535 passing** (was 513).  Zero regressions.

### Added (translator Phase 0.5 — Cisco IOS-XE adapter)

- **First real adapter: `CiscoIOSXEAdapter`** under
  `netconfig/migration/adapters/cisco_iosxe/`.  Scope:
  `openconfig-interfaces` + `openconfig-if-ip` subset (name,
  description, enabled, type, IPv4 address + prefix-length on
  subinterfaces).  Enough to prove the adapter contract against
  real OpenConfig NETCONF payloads.
- **Internal tree shape:** nested dict mirroring the OpenConfig XML
  structure, namespace-stripped for readability.  Canonical namespaces
  are re-attached on render.  Operates against captured NETCONF
  `<get-config>` responses today; live `ncclient` transport is
  Phase 1's responsibility (same split as the existing
  collectors-vs-collector-consumers layout).
- **Stdlib only** — `xml.etree.ElementTree` for parse/render.  No new
  runtime dependencies; libyang canonical validation is deferred to
  Phase 0.7 behind a "validates if installed" seam.
- **Round-trip invariant enforced:** `parse(render(tree)) == tree`
  for every supported tree.  Tested over inline samples and a real
  sanitised 3-interface fixture under `tests/fixtures/iosxe/`.
- **Capability matrix declares:**
  - 9 supported paths (name, config.name, config.description,
    config.enabled, config.type, subinterface.index, address.ip,
    address.config.ip, address.config.prefix-length).
  - Lossy: `/interfaces/interface/config/mtu` — YANG model doesn't
    round-trip every platform-specific MTU tweak.
  - Unsupported: IPv6 subtree (Phase 1 work).
  - `device_classes=[router, switch]` — IOS-XE platforms routinely
    fulfil both roles.

### Changed (translator: adapter-driven tree walker)

- **`AdapterBase` gets `iter_xpaths(tree)`** — non-abstract, defaults
  to the flat `dict[str, str]` walker so the mock adapter and any
  existing callers keep working.  Adapters with nested tree shapes
  (the new `CiscoIOSXEAdapter`) override to yield schema xpaths
  (no list-key predicates) that match their declared capability
  matrix.
- **`validate_against(tree, target)` gains an optional
  `source` adapter parameter.**  When supplied, the validator uses
  `source.iter_xpaths` to walk the tree — required for adapters
  whose internal tree shape isn't a flat dict.  Backward-compatible:
  omitting `source` keeps the Phase 0 behaviour.
- **`run_plan` threads `source` through to `validate_against`**
  automatically, so all pipeline callers get adapter-aware walking
  for free.

### Tests (+41 over Phase 0 baseline)

- `tests/unit/migration/test_cisco_iosxe.py` (30): parse (bare +
  envelope), parse errors (malformed XML, missing interfaces,
  non-integer prefix-length, interface without name), render
  determinism, round-trip invariant (inline + fixture), iter_xpaths
  predicate-freedom + matrix alignment, capability declarations,
  pipeline integration, registry.
- `tests/integration/test_migration_api.py`: new assertions that
  `cisco_iosxe` appears in the list endpoint, declares the expected
  device_classes, and exposes its full capability matrix (lossy
  MTU + unsupported IPv6) via the detail endpoint.
- `tests/fixtures/iosxe/get_config_simple.xml` — sanitised 3-interface
  NETCONF `<get-config>` response (RFC 5737 documentation IPs).

### Added (translator: cross-device-class guardrail)

- **Coarse-grained device-class compatibility check** prevents
  nonsensical migrations (e.g. trying to render a Layer-2 switch
  config through a firewall adapter).  Adapters declare one or more
  ``DeviceClass`` values on their ``CapabilityMatrix``; the pipeline
  refuses a pair with no class in common unless ``force=True``.
- **New `DeviceClass` enum** in `netconfig.models.migration`:
  ``switch``, ``router``, ``firewall``, ``load_balancer``,
  ``wireless_controller``, ``access_point``, ``waf``.  Taxonomy is
  flat and additive; multi-class devices (L3 switches, UTM
  appliances) declare multiple values.
- **`CapabilityMatrix.device_classes: list[DeviceClass]`** — empty
  default is "uncommitted" and produces a ``warn`` (not block) so
  adapters can be developed before their class declarations are
  finalised.
- **`check_class_compat(source, target) -> CompatibilityReport`** in
  `netconfig.services.migration_validate`.  Reuses the
  `CompatibilityReport` shape from the diff models so UIs can render
  both class-mismatch and xpath-mismatch banners with the same
  component.  Severity branches: same/overlapping class → `ok`;
  either side undeclared → `warn`; both declared but disjoint → `block`.
- **`run_plan` stage-0 guard**: the class check runs BEFORE parse,
  so mismatched adapters fail instantly with a clear
  ``"Device-class guard refused migration: …"`` error.  A new
  ``force: bool = False`` parameter on `run_plan` skips the guard
  for deliberate cross-class experiments (same idiom as the diff
  page's `?force=true` override).
- **API surface**: `AdapterInfo.device_classes` is now returned on
  ``GET /api/v1/migration/adapters`` so UIs can filter the target
  picker to compatible adapters before the user commits.  The
  detailed ``CapabilityMatrix`` response also surfaces the field.
- **Tests (+20)**: `tests/unit/migration/test_device_class.py`
  covers the enum shape, pydantic coercion of string values (for
  capabilities.yaml loading in Phase 1), every `check_class_compat`
  severity branch, and the `run_plan` stage-0 guard (default
  behaviour + `force=True` override + no-op when already
  compatible).  Integration test added for the new
  `device_classes` field on the list endpoint.

### Added (translator Phase 0 — adapter contract + pipeline skeleton)

- **Phase 0 of the translator / migration engine landed.**  Scope per
  `translator-plans.txt` §12: prove the shape end-to-end with a
  reference adapter, no real YANG tooling required yet.
- **New pydantic models** in `netconfig.models.migration`:
  `CapabilityMatrix` (with a `classify()` resolver using
  "strictest-wins" semantics — unsupported > lossy > supported),
  `LossyPath`, `UnsupportedPath`, `ValidationReport`, `XPathDelta`,
  `TransformSpec`, `MigrationJob`, `MigrationJobStatus`, `AdapterInfo`.
  Shape deliberately mirrors `CompatibilityReport` + `BackupJob` so UI
  banners and lifecycle conventions stay consistent.
- **`netconfig.migration` package**:
  - `adapters/base.py` — `AdapterBase` ABC + `ParseError` / `RenderError`.
  - `adapters/registry.py` — in-memory `register` / `get_adapter` /
    `list_adapters` with name-collision and missing-name guards.
  - `adapters/_mock/` — reference adapter that round-trips a flat
    `dict[str, str]` via JSON; exercises every `classify()` branch
    (supported, lossy, unsupported).
  - `canonical/loader.py` — Phase 0.5 stub; `NotImplementedError`
    with clear roadmap pointer.  `PLANNED_MODULES` tuple documents
    the OpenConfig + `netconfig-ext` modules that will be pinned
    once libyang lands.
- **New services**:
  - `services/migration_validate.py` — walks a tree's xpaths,
    classifies each against the target's `CapabilityMatrix`, returns
    a `ValidationReport` with `ok` / `warn` / `block` severity.
  - `services/migration_pipeline.py` — `run_plan(source, target,
    raw_text, transforms)` orchestrator covering stages
    parse → transform → validate → render.  Each failure class
    (`ParseError`, `RenderError`, generic `Exception`) yields a
    terminal `failed` job with a `.error` summary.  A successful
    render against a `block`-severity validation yields `partial`
    (output available for review, not safe to auto-deploy).
- **New API endpoints** (read-only Phase 0):
  - `GET /api/v1/migration/adapters` — list registered adapters
    with summary counts.
  - `GET /api/v1/migration/adapters/{name}/capabilities` — full
    `CapabilityMatrix`; 404 for unknown adapters.
- **Tests (+77)**:
  - `tests/unit/migration/test_models.py` (20) — every pydantic
    type + `classify` resolution rules.
  - `tests/unit/migration/test_registry.py` (10) — decorator
    contract, collision detection, idempotent re-registration,
    LookupError on unknown names, mock always registered.
  - `tests/unit/migration/test_mock_adapter.py` (14) — round-trip
    invariant over 5 sample trees, deterministic output, parse
    error paths, capability-matrix shape.
  - `tests/unit/migration/test_validate.py` (11) — every severity
    branch including `error`-level lossy escalation, mixed
    unsupported+lossy, empty tree, non-dict tree.
  - `tests/unit/migration/test_pipeline.py` (9) — happy path,
    transform ordering + failure, parse failure, validation
    block → partial status, failed-job timing.
  - `tests/unit/migration/test_canonical_loader.py` (4) — stubs
    raise `NotImplementedError` with roadmap pointer.
  - `tests/integration/test_migration_api.py` (9) — list + detail
    endpoints, 404 for unknown adapter, summary/detail consistency.
- **No UI in this phase.**  testids for the migration UI are
  queued for Phase 2 (`migrate-source-select`, etc. — see
  `translator-plans.txt` §11); the config diff page already
  handles rendered-output review so no second viewer is needed.

### Changed (diff page: directional paradigm — `FROM → TO`)

- **"Sides" paradigm replaced with a temporally-neutral direction.**
  The unified diff layout has directionality (`+N` added / `-M`
  removed going from one file to another), not sides.  The UI now
  surfaces that explicitly with `FROM` and `TO` role labels:
  - Each filename chip is preceded by a role badge: `FROM` (dark)
    next to the left chip, `TO` (green) next to the right chip.
  - A directional arrow (`→`) replaces the neutral "vs".
  - The stats strip is prefixed `from → to:` so `+12 / −3` reads
    naturally ("12 added, 3 removed going from the left file to the
    right file").
  - The `⇄ Swap sides` button becomes `⇋ Reverse direction`; its
    tooltip explains that the click swaps FROM/TO.
- **Why `from`/`to` instead of `baseline`/`current`?**  `current`
  implied one of the configs was from "now", which is wrong when you
  diff two old configs against each other.  `from`/`to` encodes only
  direction, not time — perfect for any pairwise comparison whether
  both configs are historical, both are fresh, or mixed.
- **Testid renames:**
  - `diff-swap-sides-btn` → `diff-reverse-btn`
  - New testids: `diff-from-label`, `diff-to-label`
- **Helper / test updates:** `DiffPage.swap_sides_btn` →
  `DiffPage.reverse_btn`; `test_swap_sides_link_reverses_url` →
  `test_reverse_direction_link_reverses_url`; new assertion
  `test_from_and_to_role_labels_visible`.

### Added (diff: collapsed-context folding for large configs)

- **Context folding** on `/configs/{left}/vs/{right}`.  Long runs of
  equal lines far from any change are squashed into a single expandable
  "… N unchanged lines …" marker, matching the convention used by git,
  GitHub, GitLab and VS Code.  Drops a real-world FortiGate vs
  FortiGate comparison from **35,422 rendered `<div>`s** to **~900** —
  a ~32× reduction in browser layout cost.
- **Zero-round-trip expansion.**  Every collapsed marker ships a
  sibling `<template>` element carrying the hidden lines as
  pre-rendered markup.  Clicking the marker clones the fragment into
  the DOM in place of the marker, applies syntax highlighting to the
  new lines, and removes the marker + template.  No network call, no
  flash of unstyled content.
- Keyboard-accessible: markers are `<button>`s so Tab / Enter / Space
  all work.
- **New model:** `netconfig.models.diff.DiffGroup` — `{kind, lines}`
  where ``kind`` is the per-line classification or the new
  ``"collapsed"`` group.
- **New service:** `netconfig.services.diff.fold_context(lines,
  context=3)` — pure, two-sweep Manhattan-style distance-to-change
  computation.  Default context (`3` lines) matches unified-diff
  convention.
- **New testids:** `diff-line-collapsed`, `diff-collapsed-template`.
- **Tests:** 9 new unit tests in `tests/unit/test_diff_service.py`
  exercising the folding algorithm (boundaries, adjacent changes,
  context=0, default=3, negative rejected, order preservation).
  3 new E2E tests in `TestDiffContextFolding` covering marker
  visibility, count attribute, and click-to-expand behaviour.

### Added (config diff — Tier 1 textual line diff with compatibility guardrails)

- **`POST /api/v1/configs/diff`** — line-level unified diff between two
  stored configurations.  Body: `{left, right, force?}`.  Returns a
  `DiffReport` containing the per-line breakdown, aggregate stats
  (`{added, removed, equal}`), and a compatibility report.  Uses
  stdlib `difflib.SequenceMatcher`; no new runtime dependencies.
- **Compatibility guardrails (defence in depth).**  Two configs are
  considered diff-compatible when `type_key` (`device_type`) AND
  `file_extension` match on both records.  Mismatches:
  - API refuses with **HTTP 422** unless the caller explicitly passes
    `force=true` in the body.
  - UI: the "Compare" button on `/configs` opens a target picker that
    lists only matching configs by default; cross-vendor options are
    hidden behind a "Show cross-vendor" toggle and dimmed.
  - `/configs/{left}/vs/{right}` page always renders, but an
    incompatible pair without `?force=true` gets a red block banner
    and a "Compare anyway" override button in place of the diff body.
  - With `force=true` the diff is computed anyway; a red banner warns
    semantic equivalence is not guaranteed.
- **Deep-linkable diff URL** at `/configs/{left}/vs/{right}` (with
  optional `?force=true`).  Reuses the config viewer's syntax
  highlighter client-side — each diff line's `<span>` goes through
  `_cvRenderHighlighted(text, ext)` post-render so cfg/xml colouring
  stays consistent between the viewer and the diff view.
- **Compare button** on every row of `/configs`; lightweight modal
  picker keyed on `type_key` + `file_extension`.
- **New models:** `netconfig.models.diff.{DiffLine, CompatibilityReport,
  DiffRequest, DiffReport}`.  **New service:**
  `netconfig.services.diff.{check_compatibility, compute_diff}` — pure,
  no I/O, easily testable.
- **New tests:**
  - `tests/unit/test_diff_service.py` (12 tests): pure-function tests
    for compat logic, add/remove/replace, force annotation, empty input,
    trailing-newline handling.
  - `tests/integration/test_configs_api.py::TestDiffCompatibility` +
    `::TestDiffOutput` (8 tests): same-type OK, cross-vendor 422,
    force override, 404 on missing filename, line-number monotonicity.
  - `tests/e2e/test_backup_flow.py::TestDiffApi` +
    `::TestDiffPageUI` + `::TestDiffPageContent` (13 tests): live-API
    wiring, Compare button and picker, cross-vendor hide/show, banner
    severity, force override, swap-sides link.
- **New testids** for Compare picker and the diff page; see
  `tests/testid_reference.md`.

### Fixed (config viewer search misses queries that cross syntax-highlight spans)

- **Cross-span search now works.** The syntax highlighter splits the
  config text into many text nodes interleaved with ``<span class="tok-*">``
  elements.  The previous per-text-node ``indexOf`` loop couldn't see a
  match that straddled a span boundary, so queries like ``64:ff9b``
  (FortiGate IPv6 NAT prefix — ``64`` is a ``tok-number`` span, ``:ff9b``
  is plain text in the next node) or ``hostname Router`` (keyword span
  followed by plain text) silently returned zero matches even when the
  substring was clearly present.
- **Fix:** ``_cvSearch`` in ``base.html`` now flattens the ``<pre>`` into
  a single string while building a ``(node, absolute_offset)`` segment
  map, finds matches in the flat text, and wraps each match across
  whatever boundaries it crosses.  Matches are processed in reverse
  document order so earlier offsets stay valid as later ones mutate
  the DOM.  A single logical match becomes a *group* of ``<mark>``
  elements; ``configViewerNav`` toggles the ``.current`` class on every
  element in the group and scrolls to the first.
- **New E2E tests** in ``tests/e2e/test_backup_flow.py``:
  - ``test_cross_span_query_finds_match`` — asserts ``"hostname Router"``
    (straddles the ``tok-keyword`` span) now matches.
  - ``test_cross_span_match_current_class_applied_to_all_pieces`` —
    asserts every ``<mark>`` in the group gets ``.current``.

### Added (parallel backup execution within a job)

- **Per-job parallelism** — `_run_backup_job` now dispatches device work
  to a bounded `ThreadPoolExecutor`.  Up to `backup_concurrency` devices
  run simultaneously; additional devices wait in the executor's FIFO
  queue and start as slots free up.  A 30-device job with 30 s per
  device now completes in ~3 × the per-device latency instead of 30 ×.
- **`Settings.backup_concurrency`** — new configurable, range `[1, 10]`,
  default `10`.  Hard-capped at `MAX_BACKUP_CONCURRENCY = 10` in
  `netconfig/config.py` to protect target SSH servers (most vendor caps
  are 5–16) and bound server thread count.  Override via
  `NETCONFIG_BACKUP_CONCURRENCY`; see `.env.example`.
- **Serial fast-path** — jobs with a single device (or deployments
  pinned to `backup_concurrency=1`) skip the thread pool entirely;
  traces and error paths stay unchanged for those callers.
- **Thread-safety contract** documented in the `_run_backup_job`
  docstring: results list is pre-populated and never resized, each
  worker mutates exactly one index, and `FileConfigStore` atomic writes
  handle storage concurrency.
- Tests default to serial execution (`test_settings` sets
  `backup_concurrency=1`) so the existing observation test and all
  ordering-sensitive assertions remain deterministic.  Explicit parallel
  tests in `TestBackupConcurrency` exercise the pool via `Barrier(n)`.

### Added (persistent backup-progress panel + per-device lifecycle states)

- **`BackupResult.status` lifecycle** — new intermediate values `queued`
  and `running` alongside the existing terminal `success` / `failed`.
  `_run_backup_job` now pre-populates one `BackupResult` per device in
  `queued` state, flips each to `running` when its collector is invoked,
  and sets the terminal state on completion.  Polling clients can snapshot
  the results list at any point and see exactly which device the engine is
  working on.
- **Floating job-progress panel** (`base.html` — global):
  - Bottom-right floating widget, present on every page.
  - Collapsible header showing aggregated job status + live summary
    (`2/5 complete — running: 1 — queued: 2` or `5/5 succeeded`).
  - One row per device with status icon (`○` queued, `⟳` running, `✓`
    success, `✗` failed), host label, per-device duration, and truncated
    error on failure.
  - **Persists across full page reloads** — the active job ID is stored
    in `localStorage["netconfig.activeJob"]`; on `DOMContentLoaded` the
    panel resumes polling if the stored job is still non-terminal, and
    renders the final state otherwise.
  - Explicit `Dismiss` button (no auto-dismiss) clears the panel AND the
    localStorage key.  A "View full job details" deep link jumps to the
    corresponding card on `/jobs`.
  - Dispatches `netconfig:job-started`, `netconfig:job-progress`,
    `netconfig:job-complete`, and `netconfig:job-dismissed` `CustomEvent`s
    on `document` so page-level code (e.g. the dashboard row injector)
    can react without re-polling.
- **New `data-testid`s:** `job-progress-panel`, `job-progress-header`,
  `job-progress-summary`, `job-progress-toggle`, `job-progress-body`,
  `job-progress-device-row`, `job-progress-device-status`,
  `job-progress-device-host`, `job-progress-device-duration`,
  `job-progress-device-error`, `job-progress-footer`,
  `job-progress-view-link`, `job-progress-dismiss`.  The legacy
  `job-status-banner`, `job-id-display`, and `job-status-display` testids
  are aliased onto the new panel for backward compatibility.

### Removed

- **Inline job status banner** on `index.html` — replaced by the global
  floating progress panel (above).  The dashboard's submit handler now
  delegates to `startJobProgress(jobId)` and listens for the
  `netconfig:job-complete` event for the "inject a row into the recent
  jobs table" step.

### Added (config viewer: syntax highlighting + in-modal search)

- **Syntax highlighting** in the shared config viewer modal (`viewConfig()`):
  comments, keywords, strings, IP addresses, and numbers for Cisco / Fortigate /
  Mikrotik `.cfg` output, plus tags and attributes for OPNsense XML.  Unknown
  extensions fall back to escaped plain text.  Palette is VS Code "Dark+"
  inspired; all tokens are rendered as `<span class="tok-*">` so E2E tests and
  custom themes can target them.
- **In-modal search** with live match counter, previous / next navigation
  (▲ / ▼ buttons), keyboard shortcuts (Enter = next, Shift+Enter = previous,
  Escape = clear or close), and wrap-around.  Matches are wrapped in `<mark>`
  elements; the currently-selected match gets `mark.current` for a distinct
  highlight colour and is auto-scrolled into view.
- **New `data-testid`s** for the viewer: `config-viewer`, `config-viewer-title`,
  `config-viewer-content`, `config-viewer-search`, `config-viewer-search-count`,
  `config-viewer-search-prev`, `config-viewer-search-next`, `config-viewer-close`.
  Full reference in `tests/testid_reference.md`.

### Changed (job status reflects per-device outcomes)

- **`JobStatus.partial`** — new terminal state for backup jobs where at least
  one device succeeded AND at least one failed.  Terminal-state semantics are
  now:
  - `completed` — every device succeeded.
  - `partial`   — mixed result (≥1 success, ≥1 failure).
  - `failed`    — zero successes (every device failed).

  Previously a job was marked `completed` regardless of per-device outcomes;
  users had to look at the success/total column to notice failures.  The UI
  now shows an amber `badge-partial` and a ⚠ indicator for mixed runs.

### Added (backup jobs page + recurring schedules)

- **Job persistence** — `FileJobStore` writes one JSON file per completed backup
  job to `{data_root}/jobs/`.  All jobs are reloaded into `app.state.jobs` at
  startup, so job history survives server restarts.
- **`BackupJob.schedule_id` / `schedule_name`** — new optional fields track
  which schedule triggered a job (snapshot of name at run time).  `None` for
  manually triggered runs.
- **`GET /jobs`** — dedicated Jobs page listing all backup jobs newest-first.
  Each job is a collapsible card showing: short ID, status badge, success/total
  count, timestamp, duration, and trigger (schedule name or "Manual").  Expanded
  body shows a per-device results table with View / Download / (Open) links and
  the config filename.  URL hash navigation: `/jobs#a1b2c3d4` auto-expands and
  scrolls to the matching job card.
- **`/schedules`** — Schedule management page and backing API:
  - **`GET /api/v1/schedules/`** — list all schedules
  - **`POST /api/v1/schedules/`** — create a recurring backup schedule
    (name, interval\_minutes, devices list)
  - **`DELETE /api/v1/schedules/{id}`** — delete a schedule
  - **`POST /api/v1/schedules/{id}/toggle`** — enable / disable a schedule
- **`BackupSchedule` model** (`netconfig/models/schedule.py`) — stores schedule
  metadata: id, name, enabled, interval\_minutes, devices, created\_at,
  last\_run\_at, next\_run\_at, last\_job\_id.
- **`FileScheduleStore`** (`netconfig/storage/schedule_store.py`) — persists
  schedule definitions as JSON under `{data_root}/schedules/`.
- **APScheduler integration** — `AsyncIOScheduler` (timezone=UTC) is started in
  the app lifespan.  Each enabled schedule registers an `IntervalTrigger` job.
  Blocking SSH runs via `asyncio.to_thread` so it never blocks the event loop.
  Scheduler state is purely in-memory; schedule definitions are re-loaded from
  disk and re-registered on every startup.
- **`next_run_at` tracking** — captured from APScheduler after registration and
  after each run; persisted to disk so the Schedules page always shows an
  accurate value even before the first tick.
- **Nav updated** — "Jobs" and "Schedules" links added between Dashboard and
  Configs in the nav bar (order: Dashboard | Jobs | Schedules | Configs |
  Definitions | API Docs).  Swagger nav updated to match.
- **`apscheduler>=3.10.4`** added to `requirements.txt` and `pyproject.toml`.

### Added (nav bar on API Docs page)

- **`GET /docs`** — FastAPI's built-in Swagger UI is now replaced by a
  custom route that injects the NetConfig nav bar (sticky, same style as
  all other pages) so users can always navigate back from the API explorer.
  The raw `/openapi.json` schema endpoint is unchanged.  `/redoc` is
  disabled (it was unreachable from the UI anyway).

### Changed (vendor-specific field naming)

- **`ConnectionConfig.handle_paging` → `cisco_more_paging`** — renamed to make
  clear this flag controls Cisco `--More--` space-injection specifically.
  `terminal length 0` remains deliberately avoided on all Cisco definitions.
- **`ConnectionConfig.needs_shell_menu` → `opnsense_shell_menu`** — renamed to
  make clear this flag detects and dismisses the OPNsense numbered console menu
  (sends `"8"` to enter the shell).  Not applicable to any other current vendor.
- **`ConnectionConfig.needs_enable`** — unchanged.  Enable/privileged-mode
  escalation is a cross-vendor concept in Netmiko (Cisco IOS, HP ProCurve,
  Aruba OS-CX, and others).
- Updated all four YAML definition files, both collectors, all test YAML strings,
  `tests/fixtures/definitions.py`, `Get-NetworkConfigs.ps1`,
  `Test-NetworkConfigs.ps1`, and all README/doc files to match.

### Added (config storage & open-in-editor)

- **Subdirectory storage layout** — config files are now saved under
  `{device_type}/{safe_host}/` inside `configs_dir` instead of a flat root.
  Example: `configs/Cisco/192-168-1-1/Cisco_192-168-1-1_20260414_120000.cfg`.
  The self-describing filename format is unchanged.
- **Startup migration** — `FileConfigStore.__init__` automatically moves any
  flat files left by older versions into the correct subdirectory.  Non-config
  files (log files, README) are left untouched.
- **Collision safety** — if two backups of the same device complete within the
  same second, a numeric suffix is appended (`…_1.cfg`, `…_2.cfg`, …) so no
  file is ever silently overwritten.
- **`resolve_path(filename)`** — new public method on `BaseConfigStore` and
  `FileConfigStore`.  Returns the absolute filesystem path for a given filename,
  checking the subdirectory location first then falling back to the root for
  files that pre-date migration.
- **`Settings.open_in_editor: bool = False`** — new flag.  When `True`, enables
  the `POST /api/v1/configs/{filename}/open` endpoint.  Set to `True` in
  `netconfig_desktop/settings.py`.  Can also be enabled for local web
  deployments via `NETCONFIG_OPEN_IN_EDITOR=true`.
- **`POST /api/v1/configs/{filename}/open`** — opens the named config file in
  the OS default text editor (`os.startfile` on Windows, `open` on macOS,
  `xdg-open` on Linux).  Returns 204 on success; 403 if disabled; 404 if not
  found; 500 if the OS refuses to open the file.  Documented as desktop-only
  in `CLAUDE.md`; the web equivalent is the existing View button.
- **"Open" button** (`data-testid="config-open-btn"`) — appears in the Actions
  column of the Configs page only when `open_in_editor=True`.  Calls the open
  endpoint; shows a success or error toast via `showToast()`.

### Tests (config storage & open-in-editor)

- `tests/unit/test_storage.py` — 19 new/updated tests: subdirectory save,
  collision safety (triple-collision), `resolve_path` (subdir + flat fallback +
  missing), startup migration (multiple files, non-config left in place,
  idempotent), and `rglob`-based listing.  Existing tests updated to use
  `store.resolve_path()` instead of manually constructing paths.
- `tests/integration/test_configs_api.py` — `TestOpenConfig` (5 tests): 403
  when disabled, 404 for missing file, 204 on success, correct path passed to
  `os.startfile`, 500 when OS refuses.
- `tests/testid_reference.md` — `config-open-btn` added with conditional
  visibility note.

---

### Added (logging)

- **`netconfig/logging_config.py`** — New `configure_logging(level, log_file)` function.
  Sets up a `StreamHandler` (stderr) plus an optional `RotatingFileHandler` (5 MB, 3
  backups) on the root logger.  Idempotent: skips when real (non-pytest) handlers are
  already present.  Suppresses `paramiko`, `uvicorn.access`, `multipart`, and `asyncio`
  to `WARNING` regardless of root level to reduce noise in INFO/DEBUG runs.
- **`netconfig_desktop/__main__.py`** — `_configure_logging()` called before
  `DesktopApp()`.  In frozen (installed) mode writes to
  `%APPDATA%\NetConfig\netconfig.log`; in dev mode uses console only.  Fatal startup
  exceptions now go through `logger.critical(..., exc_info=True)` before the message
  box so the stack trace is captured in the log file.
- **`netconfig_desktop/server.py`** — `log_config=None` added to `uvicorn.Config` so
  uvicorn's startup does not call `logging.config.dictConfig()` and overwrite the root
  logger configuration set by `configure_logging()`.
- **`netconfig_desktop/settings.py`** — `log_level` default raised from `"warning"` to
  `"info"` so desktop INFO logs reach the file handler.

### Changed (logging)

- **`netconfig/api/routes/backups.py`** — Device backup failures upgraded from
  `WARNING` to `ERROR` and now include `exc_info=True` for full traceback capture.
- **`netconfig/api/routes/configs.py`** — Added module logger; all three endpoints now
  emit structured log records (`DEBUG` for list/get, `INFO` for delete success,
  `WARNING` for 404 paths).
- **`netconfig/api/routes/definitions.py`** — Added module logger; reload endpoint
  logs loaded count and source directory at `INFO`.
- **`netconfig/storage/file_store.py`** — Added module logger; `save()` logs filename
  and byte count at `INFO`, `list_configs()` at `DEBUG`, `delete()` at `INFO`.
- **`netconfig_desktop/app.py`** — Lifecycle events (start, server ready, quit, window
  closed) logged at `INFO`.
- **`netconfig_desktop/tray.py`** — Added module logger; `run_detached()` at `DEBUG`,
  Show/Quit callbacks at `DEBUG`/`INFO`, `stop()` exception swallowed at `DEBUG`
  (was silent).
- **`netconfig_desktop/window.py`** — Added module logger; `create()` and `start()` at
  `INFO`, show/hide/destroy at `DEBUG`, `on_closed` callback exception at `DEBUG`
  (was silent).

### Tests (logging)

- `tests/unit/test_logging_config.py` — 17 new unit tests across three classes:
  `TestConfigureLoggingBasic` (handler type, levels, idempotency),
  `TestFileHandler` (rotating handler, directory creation, write-through),
  `TestNoisyLoggerSuppression` (third-party loggers capped at WARNING, netconfig.*
  left at NOTSET).  `reset_root_logger` autouse fixture restores root logger state
  after each test.

---

### Security

- **Credential encryption at rest** (`netconfig/security/credentials.py`) —
  Device passwords and enable passwords are now encrypted with Fernet
  symmetric encryption before being written to disk.  The key is stored in
  the OS secure credential store (Windows Credential Manager / macOS Keychain
  / Linux SecretService) via the `keyring` library.  Existing plaintext
  profiles and schedule device lists are automatically migrated to encrypted
  storage on first load.  In-memory model objects always hold plaintext;
  encryption is a storage-layer concern only.
- **Path traversal protection** (`netconfig/storage/file_store.py`) —
  `resolve_path()` now rejects any filename that does not match the expected
  naming convention regex before touching the filesystem.  Both the
  subdirectory and flat-fallback paths are verified to lie inside the storage
  root via `Path.resolve().is_relative_to()`.
- **Open-in-editor extension whitelist** (`netconfig/api/routes/configs.py`) —
  `POST /api/v1/configs/{filename}/open` now checks the file extension against
  an explicit allowlist (`{.cfg, .conf, .txt, .xml, .log}`) and returns 400
  for any other type, preventing the OS handler from being invoked on
  executables or other unintended file types.
- **Host field validation** (`netconfig/models/device.py`,
  `netconfig/models/device_profile.py`) — `DeviceTarget.host`,
  `DeviceProfileCreate.host`, and `DeviceProfileUpdate.host` now validate
  against `ipaddress.ip_address()` or an RFC-1123 hostname regex.  Shell
  metacharacters, path separators, and other invalid values are rejected
  with HTTP 422.
- **Passwords removed from HTML DOM** — `data-password` /
  `data-enable-password` attributes removed from the Dashboard
  `<option>` elements (`index.html`).  Credentials are fetched via
  `GET /api/v1/devices/{id}` when a saved device is selected.  The
  `data-profile` attribute on Devices page cards (`devices.html`) no
  longer includes credential fields; `runDeviceBackup()` fetches the full
  profile from the API on demand.
- **Data directories added to `.gitignore`** — `devices/`, `schedules/`,
  `jobs/`, and `configs/` are now excluded from version control to prevent
  credential-bearing files from being committed.
- **`cryptography>=41.0.0` and `keyring>=24.0.0`** added to
  `requirements.txt` and `pyproject.toml` dependencies.
- **`SECURITY.md`** — new document describing the security architecture,
  threat model, implemented controls, and known limitations.  Must be kept
  up-to-date with any security-relevant change.

### Tests (security)

- `tests/unit/test_credentials.py` — 18 tests covering key initialisation
  (first run, cached reload, idempotent), `encrypt`/`decrypt` round-trip
  (empty string, unicode, uniqueness per call), `InvalidToken` on garbage
  input, and `decrypt_field()` migration helper (encrypted→True,
  plaintext→False, empty→False).
- `tests/unit/test_storage.py` → `TestResolvePathSecurity` — 7 tests
  covering `../` traversal, `.cfg`-suffixed traversal, absolute paths,
  subdir-relative paths, empty string, and a positive case asserting the
  resolved path stays inside the storage root.
- `tests/unit/test_models.py` → `TestDeviceTarget` — 7 host validation tests:
  IPv4, IPv6, hostname accepted; `../`, `/`, space, semicolon rejected.
- `tests/integration/test_configs_api.py` → `TestOpenConfig` — 2 new tests
  for extension whitelist (`.exe`, `.zip` → 400).
- `tests/integration/test_configs_api.py` → `TestPathTraversal` — 4 new
  tests: `../../etc/passwd` GET/DELETE → 404, `.cfg`-suffixed traversal →
  404, absolute path → 404.

### Added (device profiles)

- **`DeviceProfile` model** (`netconfig/models/device_profile.py`) — stores
  profile metadata: `id` (UUID), `name`, `type_key`, `host`, `port`, `username`,
  `password`, `enable_password` (optional), `notes` (optional), `created_at`.
  `DeviceProfileCreate` and `DeviceProfileUpdate` companion models.
- **`FileDeviceProfileStore`** (`netconfig/storage/device_profile_store.py`) —
  persists profiles as JSON under `{data_root}/devices/{id}.json`.
- **`GET/POST /api/v1/devices/`** and **`GET/PUT/DELETE /api/v1/devices/{id}`** —
  full CRUD for device profiles.
- **`GET /devices`** — Devices page listing all profiles as collapsible cards.
  Each card shows name, type badge, host, backup count, and actions (▶ Backup /
  Edit / Delete).  Expanding the card reveals a per-config history table.
  Inline edit panel (`device-edit-panel`) allows credential updates without
  leaving the page.
- **Dashboard — saved device select** (`data-testid="device-profile-select"`) —
  selecting a saved profile pre-fills all form fields.  Optional "Save as Profile"
  name input (`data-testid="device-profile-name-input"`) creates or links a profile
  when the backup form is submitted.
- **`ConfigRecord.device_profile_id`** — new optional field linking a stored
  config to the device profile that produced it.  Persisted as a sidecar
  `{filename}.meta.json` alongside each config file; sidecar is cleaned up on
  delete.  `list_configs()` reads sidecars to populate the field.
- **`BackupSchedule` — two-pronged targeting** — `target_type_keys: list[str]`
  (back up all profiles of matching types) and `target_device_ids: list[str]`
  (back up specific profile UUIDs); mix is permitted.  Inline `devices` list
  retained for backward compatibility.  `ScheduleCreate` validates that at least
  one target field is non-empty.
- **`GET /devices` nav link** added between Dashboard and Jobs.
  Order: Dashboard | Devices | Jobs | Schedules | Configs | Definitions | API Docs.

### Fixed (View / Download buttons — WebView compatibility)

- **`base.html`** — Added shared `viewConfig(filename)` function (fetches config
  and displays it in a new inline modal), `downloadConfig(filename)` function
  (blob-based download, works in Qt WebEngine where `<a download>` is unreliable),
  and `closeConfigViewer()`.  New config viewer modal (`#_config-viewer`) added to
  the base layout; closes on backdrop click or Escape key.
- **`configs.html`** — View (`config-view-link`) and Download (`config-download-btn`)
  changed from `<a target="_blank">` / `<a download>` to `<button>` elements
  calling `viewConfig()` / `downloadConfig()`.  Added `DOMContentLoaded` hash
  handler: navigating to `/configs#{filename}` scrolls to the matching row,
  briefly highlights it, and auto-opens the viewer modal.
- **`jobs.html`** — View (`job-config-view-link`) changed from
  `<a href="/api/v1/configs/…" target="_blank">` to `<a href="/configs#{filename}">`
  so clicking View on a job result navigates to the Configs tab with the file
  pre-selected.  Download (`job-config-download-btn`) changed from `<a download>`
  to `<button onclick="downloadConfig(…)">`.
- **`devices.html`** — Same View / Download fix as `configs.html` applied to the
  per-device config history table.

### Fixed

- **`configs.html`** — Post-delete empty-check used CSS selector `.config-row`
  (no such class) instead of `[data-testid="config-row"]`, causing the page to
  reload after *every* deletion rather than only when the last config was removed.
- **`base.html`** — Removed orphaned `.badge-success` CSS rule that duplicated
  `.badge-completed` and leaked device-result vocabulary into the job-level badge
  namespace.

### Added

- **`POST /api/v1/definitions/reload`** — New API endpoint that re-reads all YAML
  files from `definitions_dir` and replaces the in-memory registry without a server
  restart.  Returns `{ "loaded": N, "type_keys": [...] }`.
- **Definitions page** — "↻ Reload" button (`data-testid="def-reload-btn"`) that
  calls the new reload endpoint and refreshes the page on success.
- **Configs page** — "View" link (`data-testid="config-view-link"`) and download
  button (`data-testid="config-download-btn"`) are now separate explicit actions in
  the Actions column.  The filename cell is now plain text.
- **Toast notifications** (`data-testid="toast"`) — Global `showToast(msg, type)`
  function in `base.html` replaces all `alert()` calls with a non-blocking,
  auto-dismissing notification (4 s timeout).  Types: `info`, `success`, `error`.
- **Inline job results** — After a backup job completes, per-device results
  (host, type, success/failure, error message) are rendered directly in the status
  banner.  The recent-jobs table row is injected by JS; no full-page reload occurs.
- **Active nav state** — Current page is highlighted in the navbar
  (`class="active"`, `aria-current="page"`).  `active_page` context variable added
  to all three UI route responses in `main.py`.
- **UTC timestamp localisation** — All `[data-utc]` elements are converted to
  browser-local time on `DOMContentLoaded` via a global script in `base.html`.
  Server-rendered fallback (UTC string) is preserved for non-JS contexts.
- **Enable Password conditional visibility** — The Enable Password field is shown
  only for device types where `connection.needs_enable` is `true`.  Driven by
  `data-needs-enable` attributes on `<option>` elements; toggled on type change.
- **Port collapsed to Advanced** — The SSH port field (default 22, rarely changed)
  is now inside a `<details>` summary labelled "⚙ Port", reducing visual noise in
  the backup form.
- **Inline delete confirmation** — The Delete button on the Configs page now shows
  an in-row "Delete? Yes / No" prompt instead of the browser's native `confirm()`
  dialog (which can be suppressed in embedded WebView contexts).
- **Empty-state guidance** — All three pages now include actionable text in their
  empty states rather than bare declarative messages.

### Changed

- **Nav brand** (`data-testid="nav-brand"`) changed from `<span>` to `<a href="/">`
  so clicking the product name navigates home, per standard convention.
- **Submit button** (`data-testid="submit-backup-btn"`) is now disabled and labelled
  "Running…" while a backup job is in flight, preventing double-submission.
- **Polling error handling** — The job-status polling `setInterval` now counts
  consecutive fetch failures and stops after 3, showing a toast instead of silently
  looping forever.
- **Jobs table** — "Devices" column removed (redundant with "Success / Total"
  denominator).  "Job ID" column is now plain text (`data-testid="job-id-text"`)
  rather than a link to the raw JSON API response.  "Created (UTC)" header
  simplified to "Created" (timestamps are localised by JS).
- **Configs table** — "Captured (UTC)" column header simplified to "Captured".
  Filename column is now plain text; view/download actions moved to the Actions
  column.
- **Definitions table** — "Strategy" column renamed to "Collection"; strategy
  values are now human-readable ("SSH (Netmiko)", "SSH (Shell)") rather than
  internal Python identifiers.  "Ext" column header renamed to "File Ext".
  Notes cell gains a `title` tooltip showing the full (untruncated) text.
- **`button:disabled`** CSS rule added to `base.html` — disabled buttons now show
  `opacity: 0.6` and `cursor: not-allowed` globally.
- **E2E test** `test_submit_completes_and_page_reloads` renamed to
  `test_submit_completes_and_shows_job_in_table` and updated to assert that the
  jobs table becomes visible via JS injection (no `wait_for_load_state` needed).
- **Remove device button** gains `aria-label="Remove this device"` for
  accessibility.

### Tests

- `tests/integration/test_definitions_api.py` — Added `TestReloadDefinitions`
  (5 tests): 200 response, loaded count, type_keys list, post-reload registry
  accessibility, idempotency.
- `tests/testid_reference.md` — Updated for all new/changed testids: `toast`,
  `job-id-text` (replaces `job-link`), `config-view-link` (moved to Actions),
  `config-download-btn`, `config-delete-confirm-btn`, `config-delete-cancel-btn`,
  `def-reload-btn`.  Notes added for conditional visibility and `data-utc`.

---

## [0.1.0] — initial release

- Multi-vendor SSH configuration backup via Netmiko and Paramiko Shell strategies
- FastAPI + Jinja2 web UI: Dashboard, Configs browser, Definitions viewer
- Windows desktop shell: PySide6/QtWebEngine window, pystray system-tray icon,
  embedded Uvicorn server (`netconfig_desktop`)
- cx_Freeze MSI installer (`setup_desktop.py`)
- Four-layer test suite: unit, integration, E2E (Playwright), desktop

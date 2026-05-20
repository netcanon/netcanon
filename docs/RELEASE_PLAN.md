# Public Release Plan / Release Notes

This file tracked the work to take Netcanon from private development to
public release.  The original forward-looking *plan* sections (launch
venue list, audience analysis, marketing framing copy, priority
ranking, posting cadence, etc.) have been pruned now that the work
those sections informed has shipped.  What remains is the as-shipped
phase record, the still-pending pre-launch quality hardening notes,
and the post-launch roadmap items that don't gate v0.1.0.

For the chronological per-wave shipping log, see
[`../CHANGELOG.md`](../CHANGELOG.md) `[Unreleased]`.  The phases
listed in the status block below correspond 1:1 to entries in
that file.

---

## Status

**In flight.**  Phases shipped:

* **Phase 1** — pre-flight checklist + rebrand `NetConfig` →
  `Netcanon` + PII scrub + history rewrite via `git filter-repo`.
* **Phase 1.5** — package directory rename + import paths +
  env-var prefix `NETCONFIG_*` → `NETCANON_*`.
* **Phase 2** — project identity foundation (tagline,
  `docs/IDENTITY.md`, `docs/COMPARISON.md`).
* **Phase 4.5** — sanitization tooling (`netcanon.tools.sanitize`
  shared library + CLI subcommand `netcanon sanitize` + HTTP
  endpoint `POST /api/v1/sanitize`; field-typed redactions on the
  canonical model; counter-per-session stable substitutions;
  `--dry-run` mode).
* **Phase 5** — operator-facing docs (per-vendor pages + index
  in `docs/vendors/`, `docs/HOW_WE_TEST.md`,
  `docs/TROUBLESHOOTING.md`, `BUG_REPORTING.md`; AGENTS.md
  doc-sync row + hard rule about user-facing-doc updates).
* **Phase 6** — packaging foundation (multi-stage Dockerfile,
  GHCR + Docker Hub mirror publish workflow with cosign keyless
  signing + syft SBOM attestation, PyPI Trusted Publishing
  workflow, `/health` endpoint).  v0.1.0-rc1 + rc2 published.
* **Phase 4** — demo + walkthroughs (`tools/demo.py` with 4
  scenarios; `docs/walkthroughs/` with paired narrative pages).
* **Phase 7** — README rewrite (operator-facing front door).
  Tagline above the fold; concrete before/after demo; trust
  signal as invitation; headline `docker run` install; Phase-4
  walkthroughs promoted; Tier-1/2/3 summary inline; contributor
  scaffolding demoted below the operator content.
* **Phase 3 (complete, 14/14 MUST-tier rounds shipped)** —
  pre-launch quality hardening, executed as an audit-driven
  multi-session arc.  The audit catalogued three buckets
  (failure-mode quality, browser / desktop polish, operator-facing
  copy quality) and produced a punch list; each round closes a
  thematic cluster.  Shipped:
  - **Round 1**: actionable editor-endpoint errors +
    visible overlays empty state on `/definitions`.
  - **Round 2**: vocabulary discipline pass — one
    canonical term per concept across UI labels and error
    messages (e.g. "Device Type", "Device Profile").
  - **Round 1.5**: defects surfaced during the post-R2
    visual sanity check — Pydantic 422 errors no longer render
    as `[object Object]`; `/api/v1/definitions/reload` now also
    refreshes the overlay registry.
  - **Round 3**: operator-error translator at
    `netcanon.api._errors` — humanizes 13 specific exception types
    + typed fallback on the backup-execute surface.
  - **Round 3.1**: Netmiko `__context__`-peek hotfix —
    DNS / refused / unreachable failures now produce distinct
    operator messages instead of three identical timeouts.
  - **Round 4**: migrate-page UX cluster —
    detect-suggest-on-parse-failure JS helper + four empty-state
    banner rewrites in Tier-3 voice + operator-facing header
    rewrite.
  - **Round 4.1**: detect-suggest button now flips
    target too when the operator's original setup was round-trip.
  - **Round 4.2**: shared
    `_input_shape.detect_input_shape()` helper across all 6 CLI
    codecs — tolerates leading shell-echo / banner framing on
    real captures (previously a permissive XML guard silently
    accepted wrong-vendor input).
  - **Round 5**: 21 `title=` tooltips on form-heavy
    pages — backup / devices / schedules / migrate.
  - **Round 6**: new `/sanitize` UI page mirroring
    `/migrate` idioms (paste raw / pick stored), with dual-fetch
    on submit for audit + sanitized text together.
  - **Round 6.1**: username redaction
    (`local-user-name`, `snmpv3-user-name` categories with
    iterative per-class numbering) + operator-facing safety note
    about non-functional placeholders.
  - **Round 7**: keyboard-shortcut cheatsheet modal (`?` opens)
    documenting the existing-but-undocumented shortcuts
    (config-viewer search Enter / Shift+Enter / Esc, diff-page
    collapsed-marker Enter / Space, configs-page compare-picker
    Esc) on a global modal with discoverability via the nav-bar
    `?` button.
  - **Round 7.1**: dark-mode coverage sweep across in-app
    surfaces — six pre-existing dark-mode regressions on
    devices / jobs / schedules / configs compare-picker / migrate
    textarea + form + rename modal / sanitize page, all tokenized
    via the existing `var(--surface)` / `var(--badge-*)` system.
  - **Round 7.2**: Swagger UI `/docs` page dark mode + nav sync —
    boot script + token definitions injected at `<body>` open,
    nav-bar parity with base.html (page-nav + `?` cheatsheet +
    theme toggle), ~30 Swagger UI dark-mode CSS overrides.
  - **Round 8**: backup-job registry refactor — `app.state.jobs`
    swapped from unbounded `dict[str, BackupJob]` to
    `BackupJobRegistry` with LRU eviction at `max_memory_jobs`
    (default 1000) + transparent disk lazy-load on get-by-id miss.
    Caps memory at ~5 MB regardless of historical job count.
  - **Round 9**: runtime checks — 6 lightweight load + memory
    smoke tests (sustained load, eviction + persistence,
    concurrent backups, multi-device burst, BackupJob instance
    count bound, tracemalloc peak) + manual browser-compat sweep
    in Chrome + Firefox.
  - **Round 10**: cut `v0.1.0-rc7` + finalize CHANGELOG +
    RELEASE_PLAN status (this entry) + pre-public-flip privacy
    workflow (CHANGELOG PII scrub + private PR-archive retention
    at netcanon/netcanon-archive + repo migration: old repo
    renamed to netcanon-old, fresh netcanon/netcanon created
    from current main, all rc tags + history preserved on new
    repo; old repo retained private with PR history intact).

  Cumulative impact: full unit + integration suite grew from
  3266 (post-Phase-7) to **3556 tests** (+290 over Phase 3).
  Every Phase 3 PR squash-merged + green on the 4-Python-version
  CI matrix.

**Next:**

* **Public flip + tag v0.1.0 final** — convert repo from private
  to public visibility, push v0.1.0 final tag, set GitHub Topics +
  extended description per [`IDENTITY.md`](IDENTITY.md).
  Prerequisites: `DOCKERHUB_TOKEN` + `DOCKERHUB_USERNAME` re-added
  as repo secrets (these stayed on the old repo post-rename);
  PyPI Trusted Publisher re-linked to the new repo slug.

**Optional:**

* **Phase 8 — private beta** with trusted-tester exposure before
  fully public flip.  Skippable if confident the v0.1.0-rc cycle
  surfaced enough.

---

## v0.2.0 — VRRP / HSRP / CARP + anycast-gateway (in flight)

Cross-vendor L3-redundancy enrichment.  Closes the
canonical-model gap surfaced in
[`tests/fixtures/real/WANTED.md`](../tests/fixtures/real/WANTED.md)
§ "Cross-vendor canonical-model enrichment".  Five commits since
v0.1.0:

* **Fixture + planning seed** — `8adaefd`.  2 batfish samples
  (IOS VRRP + EOS VLAN-based EVPN) + the v0.2.0+ VRRP enrichment
  proposal documented inline in `WANTED.md`.  +6 auto-discovered
  fixture-harness tests.
* **Planning round** — `5adee9b`.  4-agent parallel research pass
  produces `docs/v0.2.0-planning/` (28 design artifacts +
  top-level synthesis README; ~13,700 lines).  Pure
  documentation; no production source modified.  Resolves the T1
  vs T2 architectural conflict as **HYBRID** (classic FHRP gets
  `CanonicalVRRPGroup` with `mode in {vrrp,hsrp,carp}`; anycast
  gets per-address `virtual_gateway_address` fields and a
  system-wide `anycast_gateway_mac`).
* **Wave A schema** — `c5da044`.  Ship-before-wire canonical
  schema landing: `CanonicalVRRPGroup` model,
  `CanonicalInterface.vrrp_groups`,
  `CanonicalIPv4Address.virtual_gateway_address` /
  `virtual_gateway_mac`, IPv6 siblings,
  `CanonicalIntent.anycast_gateway_mac`,
  `CanonicalStaticRoute.vrf`, plus `is_secondary` on address
  records.  Every codec matrix declares the 5 new paths
  `unsupported` until per-codec wire-up lands.  +31 schema
  tests.
* **IOS-XE password round-trip bugfix** (side-quest) — `b85c39c`.
  Sub-task spawned during the planning round: `password 0 X` was
  being captured as `hashed_password = "0 X"` then double-prefixed
  on render.  Fix strips the type-0 plaintext prefix on parse;
  the IOS VRRP fixture restored to upstream verbatim form.
  +8 tests.
* **Waves B + C codec wire-up** — `e542b49`.  Seven parallel agents
  in isolated worktrees wire VRRP / HSRP / CARP across 7 bidi
  codecs (Wave B) and anycast-gateway across 3 codecs (Wave C).
  Per-codec deltas: aruba_aoss (+17), fortigate_cli (+17),
  mikrotik_routeros (+20), opnsense CARP (+21), juniper_junos
  (+23), arista_eos (+24), cisco_iosxe_cli (+27) = +149 tests
  across the 7 codec test files.  Unified
  `_WIRED_UP_BY_CODEC` map (graduated paths per codec) reconciled
  from 4 agent variants; two-sided invariant (graduated MUST NOT
  be `unsupported`; un-graduated MUST be `unsupported`).
  29 files modified, 6079 insertions.

**Cumulative impact**: +180 tests (31 schema + 149 codec), 6800+
LOC of design docs landed in `docs/v0.2.0-planning/`, 6300+ LOC of
implementation across Wave A + Waves B/C.  Full unit suite: 3341
passed / 56 skipped / 0 failed.

**Planning-folder closure**: design subfolders 1 + 2 (VRRP +
anycast) marked Shipped via `IMPLEMENTED.md` stubs pointing at
the merge commits.  Subfolders 3 + 4 (NX-OS + IOS-XR codecs)
remain Design complete pending v0.3.0+ implementation.

**Open / queued for v0.3.0+**:

* **T3 NX-OS bidirectional codec** — design ready
  (`docs/v0.2.0-planning/03-nxos-codec/`); ~2,400-3,200 codec LOC
  + ~1,800-2,400 test LOC across 4 phases.  Phase 2 (L2 + HSRP)
  consumes the Wave A `CanonicalVRRPGroup`; Phase 4 (EVPN-VXLAN
  + DAG) consumes the Wave A anycast surface.
* **T4 IOS-XR bidirectional codec** — design ready
  (`docs/v0.2.0-planning/04-iosxr-codec/`); ~1,900-2,700 codec
  LOC + ~1,200-1,700 test LOC across 4 phases.  Agent
  recommendation: defer until T3 lands (enterprise reach > SP
  audience for the same review-budget cost).
* **Cisco IOS-XE NETCONF stub (`cisco_iosxe`)** VRRP / anycast
  wire-up — currently `unsupported` per its Phase-0.5 stub
  policy.
* **Modern Arista + IOS-XE VRRP address-family multi-line form**
  with full per-AF priority / preempt round-trip — declared
  `lossy` for now (group-ID-only shell parses, AF body drops).
* **Junos `/routing/static-route/vrf`** — declared `lossy`;
  routing-instances dispatcher needs per-VRF static-route harvest
  in a separate scope.

---

## Post-launch roadmap notes

These don't gate v0.1.0 but are tracked so they don't get lost
once this file is finally retired:

* **Backup-job pagination + retention.**  R8 capped the in-memory
  registry at `max_memory_jobs` (default 1000) with disk lazy-load
  on get-by-id miss, but the list endpoint still returns only
  memory-resident jobs and disk grows forever.  Three v0.2.0
  follow-ups:
  - Pagination on `GET /api/v1/backups/` (`?limit=N&offset=M`) +
    UI updates so operators can browse history past the in-memory
    cap.
  - `max_disk_jobs` setting + daily cleanup task that prunes
    ``jobs/*.json`` past the cap (and the corresponding ``configs/``
    files if cross-referenced).
  - Stat-sort warm-cache so startup stays sub-second even at 100k+
    jobs (today's `load_all` parses every JSON file).
  - `/diagnostics` endpoint exposing `jobs_memory` vs `jobs_disk`
    counts for operators who want to monitor cache state.
* **Backup retention / rolling delete on scheduled jobs.**  Today
  every scheduled-job run lands a fresh `configs/<host>_<ts>.<ext>`
  file with no automatic cleanup; long-running scheduled jobs grow
  the backup directory unbounded.  Want: a per-schedule retention
  policy (keep N most recent, OR keep configs newer than D days,
  OR both) configurable at schedule-creation time, plus a one-shot
  manual-cleanup endpoint for operators who want to prune existing
  backups.  Touches `netcanon/storage/file_store.py` (a
  `prune_older_than` / `keep_n_newest` helper), the schedule model
  (`netcanon/models/schedule.py`), the schedule-creation form
  (`netcanon/templates/schedules.html`), the desktop equivalent in
  the preferences dialog, and a new `DELETE /api/v1/configs` (or
  `POST /api/v1/configs/prune`) endpoint.  Keep operator-explicit:
  default policy is "keep everything" so existing operators don't
  see backups vanish on upgrade.

* **Pinned dependency manifest** (`requirements.lock` / `uv.lock`).
  Production builds currently resolve from `pyproject.toml`
  ranges; lock-file resolution is a follow-up wave for operators
  in regulated environments.  See `SECURITY.md` "Supply-Chain
  Integrity" section for the current shipped vs pending state.

* **Auto-sync Docker Hub repo description.**  Manual paste at
  v0.1.0 launch; could be wired via `peter-evans/dockerhub-description`
  on push to main if maintenance overhead becomes real.

---

## Pre-launch quality hardening

Items in this section don't ship features; they ship POLISH.  An
operator's first 5 minutes after install determines whether they
bookmark the project or drift away.  Defer-friendly: can be
interleaved with private-beta feedback (operators tell you which
polish actually matters).

### Failure-mode quality

The tool has good code quality, but qualitative trust often hinges
on failure modes.  Worth a deliberate audit:

* **What happens with a 50MB config file?**  The file_store has a
  50MB cap; what does the operator see when they hit it?  Stack
  trace or graceful error?
* **What happens if SSH disconnects mid-backup?**  Is the partial
  config persisted?  Is it cleaned up?  Is the operator told?
* **What happens if a probe regex doesn't match?**  Does the backup
  proceed without facts, or fail?
* **What happens if the operator pastes the wrong vendor's config
  in the migrate page?**  Auto-detection is a thing; what's the
  error message?
* **Memory under load** — 10 devices × 100KB configs × concurrent
  backups.  Does the tool sit at reasonable RSS or balloon?

These are the things that will surface in early bug reports.  A
pre-release "failure mode tour" pass to make every error path
produce an actionable message (not a stack trace) pays for itself
in reduced GitHub-issue noise.

### Browser / desktop polish

The web platform is the primary surface.  The desktop wrapper is a
Tier-3 audience.  Both deserve a polish pass:

* **Browser compat.**  Latest Chrome / Firefox / Safari / Edge.
  The dark-mode work helps, but unverified Safari is the typical
  gap.
* **Empty states.**  What does the migrate page look like before
  any device is added?  Before any config is saved?  With one
  device?  Operators land on an empty UI more often than you'd
  think.
* **Loading states.**  Long-running operations (backup, render,
  validation) need clear "working..." feedback.  Operators who
  don't see progress assume the tool hung.
* **Keyboard navigation / accessibility.**  Network engineers run
  multiple tabs / Vim-style workflows.  Keyboard shortcuts (already
  partially present) deserve documentation; tab order should be
  sensible.

The matrix-honesty discipline applied to UI: every interactive
element needs a `data-testid` (already enforced).  Every error
state needs an actionable message (less enforced).  Every empty
state needs context (mostly missing).

### Operator-facing copy quality

The text on every page is operator-facing copy.  The tone of that
copy signals what kind of project this is.

* **Error messages.**  "Validation failed" → tell them WHAT failed
  and HOW to fix it.  The validation pass aligned in-app limitation
  messages with `CAPABILITIES.md`; that discipline should extend to
  all operator-facing text.
* **Tooltips.**  Most fields don't have tooltips.  Tooltips with
  concrete examples help operators who don't read docs.
* **Banner copy on the migrate page.**  The Tier-3 detection banner
  is well-worded.  Look at every other banner with that lens.
* **Form-field labels.**  "Device type" vs "Vendor" vs "Codec" —
  three concepts, three labels, sometimes used interchangeably.
  Pick one term per concept and use it consistently.

---

## What we deliberately don't do

These are scope-and-discipline calls, not strategic launch decisions.
They apply at every release, not just v0.1.0.

* **No "v1.0" until external validation.**  The codebase is mature
  in scope but ten thousand operators haven't beaten on it yet.
  v0.1.0 → v0.2.0 → ... → v1.0.0 after sustained external use.
  Pre-1.0 sets honest expectations.

* **No public-facing demo instance.**  Either the tool runs on
  the operator's machine or in their network — public hosted
  instances create credential-exposure incentives.

* **No binary device-config submissions in issues.**  Force the
  sanitization step.  A leaked production config in a public issue
  is a much worse outcome than slightly-higher-friction bug
  reporting.  See [`../BUG_REPORTING.md`](../BUG_REPORTING.md).

* **No promise of auto-translation of firewall rules.**  The
  deferral is the right call; advertise it as a deliberate design
  choice, not a "we haven't gotten to it."  Firewall translation
  is a different product — see `CAPABILITIES.md` Tier-3 boundary.

* **No GitHub Discussions until triage capacity exists.**
  Discussions create an expectation of response.  Better to ship
  with Issues only and add Discussions when the sustained cadence
  is realistic.

* **No silent-drop translations.**  Every codec that can't carry
  a field declares it `lossy` or `unsupported` with a cited
  reason.  The Tier-3 banner surfaces what was detected-but-not-
  translated.  Matrix-honesty discipline.

---

## See also

* [`../CHANGELOG.md`](../CHANGELOG.md) — chronological shipped work.
  The phase entries here are 1:1 with the `[Unreleased]` block
  above (and will fold into `[0.1.0]` when v0.1.0 final is tagged).
* [`../README.md`](../README.md) — operator-facing front door.
* [`../ARCHITECTURE.md`](../ARCHITECTURE.md) — internal four-layer
  design.
* [`../AGENTS.md`](../AGENTS.md) — contributor directives + the
  doc-sync table that anchors many of the shipped phases.
* [`CAPABILITIES.md`](CAPABILITIES.md) — operator-facing source of
  truth on what translates and what doesn't.
* [`IDENTITY.md`](IDENTITY.md) — project identity + distribution
  surfaces (tagline, GitHub repo description, Topics, Docker Hub /
  GHCR / PyPI namespace conventions).
* [`HOW_WE_TEST.md`](HOW_WE_TEST.md) — the matrix-honesty discipline
  narrated for operators.
* [`../tests/fixtures/real/RESULTS.md`](../tests/fixtures/real/RESULTS.md)
  — live per-codec certification.
* [`../tests/fixtures/real/PHASE4_RECONCILIATION.md`](../tests/fixtures/real/PHASE4_RECONCILIATION.md)
  — live cross-mesh audit matrix.

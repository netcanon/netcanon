# 20 — Architecture/Maintainability + Performance (merged lens)

Reviewer: Fable fresh-eyes pass, 2026-07-03. Repo state: main @ `79c29a0` (v0.4.15 worktree).
Method: full read of `netcanon/migration/` shared infrastructure + orchestrator + validator +
loader; AST scans (re.compile-inside-def, nested loops over canonical collections, linear
membership tests inside loops, module import-cycle SCCs, never-imported modules); four
read-only `py -c` probes against the local package (scaling measurements quoted inline).

**Verdict: GO-WITH-FIXES.** The architecture is in genuinely good shape — the
"minimal utilities, no base class" codec decision is holding, regex discipline is
near-perfect, and the complexity ratchet is real and wired. One **major** finding:
the AOS-S *port-range* expander is the one range-materialization surface the
VLAN-DoS clamp sweep missed, and it is reachable from `POST /plan` with a 30-byte
line (probe-verified amplification). Everything else is minor or note-grade.

---

## Part B first — Performance (contains the major)

### PERF-1 (MAJOR) — AOS-S port-range expansion is unclamped: small-input OOM amplification

- `netcanon/migration/codecs/aruba_aoss/parse.py:447-455` — `_expand_port_range` does
  `return [f"{prefix_lo}{n}" for n in range(num_lo, num_hi + 1)]` with **no bound on the span**.
- The gate regex `_AOS_PORT_SHAPE_RE` (`parse.py:367-369`) is `\d+` — unbounded digit count, so
  `1-3000000000` passes the "AOS-S native port shape" check on both endpoints.
- Reachable call sites, all fed by raw uploaded config text: `_parse_port_list` (`parse.py:406`)
  ← trunk lines (`parse.py:461`), VLAN `untagged`/`tagged`/`no untagged` lines
  (`parse.py:527,532,539`).

**Probe (input scale cited):** parsing a 5-line AOS-S config containing the single body line
`untagged 1-300000` materializes **300,000 port-name strings in 0.59 s** (verified via
`parse_intent`, count == 300000). Growth is linear in the span, so `untagged 1-3000000000`
(a 22-character line) attempts ~3×10⁹ strings ≈ tens-to-hundreds of GB → worker OOM. The
`MigrationPlanRequest.raw_text` 10 M-char cap (`netcanon/models/migration.py:663`) explicitly
calls itself "a defence-in-depth complement to the VLAN-range clamp" — but it does **not**
protect here because this is amplification, not payload size.

This is *exactly* the DoS class the 2026-06 remediation clamped ×4 on VLAN-id lists — and
those clamps are present and regression-tested (`_helpers.py:131`, `arista_eos/parse.py:1501`,
`tests/unit/migration/test_vlan_expansion_bounds.py:40` covers eos/aoscx/nxos/iosxe) — but the
sweep only covered **VLAN-id** expanders. The AOS-S **port-name** expander is the same shape on
a different axis and was never in scope. Fix contour: clamp the span before materializing
(no real AOS-S stack exceeds ~26 members × ~52 ports; a `hi - lo > 4096 → return [lo, hi]`
bail or a `\d{1,4}` bound in `_AOS_PORT_SHAPE_RE` both work), mirroring the documented
"clamp BEFORE the range is materialised" convention in `_helpers._parse_vlan_list`.

Secondary blast radius once expanded: the 300k-entry `untagged_ports` list then flows into
every downstream linear scan (PERF-2's `_add_unique`, the walker's per-port yields → PERF-4's
per-path classify), multiplying the damage.

### PERF-2 (MINOR) — Quadratic list-membership scans in the VLAN projection transforms

- `netcanon/migration/canonical/transforms.py:129-131` — `_add_unique` is
  `if name not in lst: lst.append(name)`, i.e. O(len) per insert over a plain list; called from
  the per-interface projection loops at `transforms.py:153,178,181,185`.
- `transforms.py:290-292` — `if vid not in iface.trunk_allowed_vlans` per vid on the reverse
  projection (O(vids²) per interface).

**Probe (input scale cited):** `project_switchport_to_vlan` on 96 trunk interfaces × 4000
allowed VLANs (deliberately 1-4000 so the trunk-all sentinel at `transforms.py:156-158` does
NOT short-circuit — the sentinel only matches the *exact* sets {1..4094}/{2..4094}, so a
real-world `1-4000` or `10-4000` trunk misses it) took **0.46 s**; growth is quadratic in port
count (each vlan's `tagged_ports` scan grows with every port added), so ~500 ports × 4000
VLANs extrapolates to ~10 s and 1000 ports to ~50 s of pure CPU inside one web request.
A set-shadow alongside each list (or dict.fromkeys dedup at the end) makes it linear.
Not a blocker at today's typical corpus scale (dogfood configs are far smaller), but it is
the multiplier that turns PERF-1's expanded lists into minutes.

### PERF-3 (MINOR) — opnsense `_vlan_parent_for` rescans everything per VLAN

`netcanon/migration/codecs/opnsense/render.py:617-641`, called once **per VLAN** from
`render.py:308`: pass 1 iterates `lags × interfaces` plus `lags × members × interfaces`, and
`lag_member_set` (`render.py:631-633`) is rebuilt on every call. Total
O(V·L·M·I) name comparisons plus `vlan.id in iface.trunk_allowed_vlans` list-membership
inside. For a big-switch→opnsense cross-vendor render (500 ifaces, 20 LAGs, 1000 VLANs) that
is ~10⁸ comparisons. A one-time `vid → parent` index built before the VLAN loop collapses it
to O(V+I). Low urgency (firewall targets are typically small) but it's the only render-side
hot loop of this shape left — every other renderer builds its lookup sets once
(e.g. `arista_eos/render.py:497-501`, `cisco_iosxe_cli/render.py:278-282`).

### PERF-4 (NOTE, measured-fine) — `CapabilityMatrix.classify` is a linear scan per xpath, and the dicts already exist one frame up

`netcanon/models/migration.py:221-228` scans `self.unsupported` then `self.lossy` lists per
call; `classify_tree` (`netcanon/services/migration_validate.py:77-88`) builds
`lossy_by_path`/`unsupp_by_path` dicts **and then still calls the linear `caps.classify`**
inside the walk loop. Matrix sizes are 8-67 unsupported + up to 25 lossy per codec (probed all
13 registered codecs), so worst case ~90 pydantic-attribute string compares per yielded path.
**Probe:** validate of a 2000-interface intent (16,001 yielded paths) = **21 ms** — so this is
NOT a current hotspot; flagged because the O(1) fix is two lines in a function that already
half-implements it, and because pathological inputs (PERF-1) multiply the path count.

### PERF-5 (NOTE) — Validation report keeps one entry per occurrence → response bloat at scale

By documented design (`migration_validate.py:66-68` "duplicate xpaths are preserved... so
counts reflect impact"), `supported_paths` holds one string per leaf and `lossy_paths`/
`unsupported_paths` one full object (with reason text) per occurrence. The 2000-interface
probe produced 12,001 supported strings + 4,000 duplicate `UnsupportedPath` objects in one
`ValidationReport`, all of which serialize into the `MigrationJob` JSON response. Counts-plus-
exemplars would carry the same signal at 1/1000th the payload. Design decision, not a bug —
recording so a future "the /plan response is 8 MB" ticket has a citation.

### PERF-clean — things I specifically hunted and did NOT find

- **Per-line regex recompilation: none.** AST scan of every `def` in `netcanon/` found exactly
  ONE `re.compile` inside a function body — `collectors/probe.py:81` — and that one compiles
  operator-defined probe patterns once per *probe invocation* (a handful of patterns per SSH
  session), not per line. Every codec keeps its grammar regexes at module scope. Excellent
  discipline for a 55 k-line package.
- **Input caps exist where they should:** inline paste capped at 10 M chars
  (`models/migration.py:658-663`); auto-detect probes only a 500-byte prefix
  (`services/migration_detect.py:31,74`); `_input_shape.detect_input_shape` scans ≤5 lines.
- **Registry/loader scans are boot-time only:** `DefinitionLoader`, `load_vendors`,
  `load_profiles_dir` all load once in `main.py:107-121` (+ an explicit reload endpoint);
  `DefinitionLoader.resolve` is O(#variants) per call over dozens of entries — fine.
- **No whole-file-slurp regressions:** parse paths are `splitlines()` over the capped input;
  `FileConfigStore.get_content` reads one stored config, not the directory.
- **junos "vlan members all"** (`juniper_junos/parse.py:557`) and `merge_trunk_allowed`
  `all`/`except` (`_helpers.py:191,196`) materialize the fixed 4094-wide range only — bounded.
- One residual unclamped expansion besides PERF-1: `target_profiles.py:439-447`
  (`_expand_range_entries`, `_RANGE_RE` digits unbounded) — a profile YAML `range: "1-999999999"`
  would OOM at **boot**. Operator-authored file, boot-time, fail-visible → minor;
  worth a one-line `end - start` sanity cap the next time that file is touched.

---

## Part A — Architecture / Maintainability

### ARCH-1 (MINOR) — the `_walk_canonical` relocation is half-finished: 11 codecs still couple to a vendor leaf

The shared walker moved to `netcanon/migration/canonical/xpath_walker.py` (docstring: run3
`walk-canonical-vendor-leaf`) with a compatibility re-export left in
`cisco_iosxe_cli/codec.py:60`. But only the shim's own module was repointed — **all 11 other
codecs still import the walker from the vendor leaf**:
`arista_eos/codec.py:430`, `aruba_aoscx/codec.py:680`, `aruba_aoss/codec.py:466`,
`cisco_iosxe/codec.py:978`, `cisco_iosxr/codec.py:598`, `cisco_nxos/codec.py:605`,
`fortigate_cli/codec.py:542`, `juniper_junos/codec.py:416`, `mikrotik_routeros/codec.py:487`,
`opnsense/codec.py:591`, `vyos/codec.py:620` — each inside a byte-identical 3-line
`iter_xpaths` override (`if isinstance(tree, CanonicalIntent): from ..cisco_iosxe_cli.codec
import _walk_canonical; yield from _walk_canonical(tree)`).

Two costs: (a) a false dependency edge — renaming/retiring the iosxe_cli codec module breaks
validation for every codec; (b) 11 duplicate methods that are precisely the thing
`CodecBase.iter_xpaths` (`codecs/base.py:322-340`, currently dict-only) should do by default:
"if CanonicalIntent → neutral walker; if dict → mock fallback". That default would delete all
11 overrides and make the 13th codec one method shorter. Mechanical, low-risk, high
drift-removal-per-line — the best next increment of the Stage-2 abstraction work.

### ARCH-2 (MINOR) — `run_plan_with_overrides` boilerplate grows ~40 lines per rename pane, and 5 more panes are planned

`netcanon/services/migration_pipeline.py:370-742` (`# noqa: C901`, 373 lines): each of the 5
shipped categories contributes an engaged-log branch (:513-528), a build-transform branch
(:595-646), a result-attach block (:663-703), and a slot in the 22-arg debug format
(:719-741) — four near-identical copies per category, differing only in names. The docstring
(:404-408) says NTP / DNS / syslog / RADIUS / trap-host panes are the planned next categories;
at that point this one function is ~700 lines of category boilerplate. The shape is already
perfectly regular (every `build_*_rename_transform` returns `(transform, result)` and every
result has `.applied/.warnings/.dropped`), so a small category descriptor table
(`name, builder, job_field_prefix`) collapses all four copy sites without touching the frozen
signature. Recommend doing it **before** the sixth category lands, not after the tenth.

### ARCH-3 (NOTE) — C901 ratchet: holding, but it pins *count*, not *size*; three functions are past 700 lines

The ratchet is genuinely wired: `pyproject.toml:225,259` (C90 select + max-complexity=25) and
`tests/unit/test_complexity_ratchet.py:41` pin exactly 25 grandfathered suppressions
(re-counted: 25 markers, matches). What the ratchet cannot see is growth *inside* pinned
functions. Measured sizes of the pinned set (AST `end_lineno - lineno`):

| function | lines |
|---|---|
| `juniper_junos/render.py::render_intent` (:81) | **1144** |
| `tools/sanitize.py::sanitize_intent` (:248) | 713 |
| `juniper_junos/parse.py::parse_intent` (:77) | 742 |
| `mikrotik_routeros/render.py::render_intent` (:99) | 640 |
| `cisco_iosxe_cli/render.py::render_intent` (:62) | 626 |
| `fortigate_cli/render.py::render_intent` (:414) | 569 |
| `arista_eos/render.py::render_intent` (:147) | 809 |

Are they genuinely un-refactorable? Mostly **no, but benignly so**: every `render_intent` is
linear paragraph-style emission (one canonical surface per block, appending to `lines`) —
complexity is breadth, not tangled state, and each block is extractable as
`_render_<surface>(intent, lines)` with zero behaviour risk. The junos pair is the real
maintenance hotspot: 2544-line parse.py + 1144-line render function in the codec that gets
touched most (it was the biggest residual-tail source in the 2026-07 dogfood arc). If any
ratchet decrement is ever budgeted, spend it there. By contrast `_walk_canonical`
(`xpath_walker.py:23`) and `translate_port_names` (`port_names.py:244`) are cohesive
single-concern functions where a split would hurt — those pins are legitimate.

### ARCH-4 (GOOD / no finding) — the "minimal utilities, no base class" decision is holding

Checked for post-Stage-2 copy-paste drift across the 12 codecs; the shared seams are healthy:

- `codecs/_helpers.py` — MAC/link-local/mask/VLAN-list/coalesce/`merge_trunk_allowed`; 23
  import sites across parse/render. The two remaining "duplicates" are *documented deliberate
  near-twins with guard tests*: `arista_eos/parse.py:1477-1487` (`_expand_vlan_list`, accepts
  `int()`-forms the shared `isdigit()` gate rejects, injected into `merge_trunk_allowed` as
  `parse_ids`, equivalence-tested in `tests/unit/migration/codecs/test_helpers_equivalence.py`)
  and `fortigate_cli/parse.py:81-91` (`_prefix_to_mask` = explicit thin vendor-binding shim
  over the shared helper). This is exactly what the "duplicate only with a reason" doctrine
  should look like.
- `codecs/_scanner.py::scan_stanzas` — clean opt-in loop skeleton, zero canonical knowledge,
  adopted by 5 line-scan codecs (arista/aoscx/iosxe_cli/iosxr/nxos); the opt-outs
  (brace-stack vyos, XML opnsense/iosxe, set-form junos, nested-block aoss) are documented in
  the module docstring and genuinely don't fit the shape.
- `_input_shape.py`, `_tier3_detection.py`, `_naming.py`, `_user_secrets.py`,
  `canonical/xpath_walker.py` — all single-purpose, vendor-neutral, imported where expected.
- Per-codec `codec.py` boilerplate (parse delegation + tier3 attach + port-name delegation +
  probe) compared newest (vyos) vs oldest-style (arista): consistent, with only justified
  variation (vyos normalizes set-form→brace before tier3 detection, `vyos/codec.py:598-608`).
- `cisco_iosxe` (NETCONF) remaining a monolithic 1507-line `codec.py` without the
  parse/render/port_names split is a *documented* Phase-0.5 stub with honest
  `unsupported_rename_categories` declarations (`cisco_iosxe/codec.py:207-223`) — layout
  inconsistency is intentional, not drift.

### ARCH-5 (clean sweeps — no findings)

- **Circular imports:** SCC analysis over module-level imports found only the benign
  package-`__init__` ↔ submodule relative-import cycles every codec package has by
  construction (`from . import port_names` inside codec.py). No cross-package cycles; the two
  places that *would* cycle (pipeline ↔ canonical orchestrators, `port_names` ↔ intent) are
  correctly broken with documented lazy imports (`migration_pipeline.py:493-505`,
  `port_names.py:38-40,315`).
- **Dead code:** module-level orphan scan (all imports across netcanon/tests/tools/desktop)
  found zero never-imported modules. `fixture_dirs.py` living in the prod package is
  deliberate + documented (shared by audit scripts and tests to kill a drift class it cites).
- **TODO/FIXME/HACK/XXX debt:** effectively zero — the only two grep hits are docstring
  references to the literal UI string `VL_XXX` (`fortigate_cli/port_names.py:234,326`).
  Remarkable for a codebase this size.
- **God-module check:** largest modules are per-codec parse/render (expected; vendor grammar
  is irreducibly wordy) and `canonical/intent.py` (955 lines, pure data model, **no**
  validators — probed; so no hidden per-construction costs). `models/migration.py` (857)
  mixes job/matrix/request models but along one coherent domain. No action.

---

## Priority summary

| # | Severity | One-liner |
|---|----------|-----------|
| PERF-1 | **Major** | `aruba_aoss/parse.py:447-455` port-range expansion unclamped — 22-byte config line → multi-GB OOM via `POST /plan`; the VLAN-DoS clamp sweep missed the port-name axis (probe: 300k strings/0.59 s, linear) |
| ARCH-1 | Minor | 11 codecs import `_walk_canonical` from the `cisco_iosxe_cli.codec` shim instead of `canonical/xpath_walker` — half-finished relocation + 11 duplicate `iter_xpaths` that should be the `CodecBase` default |
| PERF-2 | Minor | `canonical/transforms.py:129-131,290-292` quadratic list-membership in VLAN projections (0.46 s @ 96 ifaces × 4000 vlans; quadratic in port count; multiplies PERF-1) |
| ARCH-2 | Minor | `migration_pipeline.py:370-742` ~40 lines boilerplate per rename pane × 5 more panes planned — table-drive before pane #6 |
| PERF-3 | Minor | `opnsense/render.py:617-641` per-VLAN O(L·M·I) parent rescan; build a vid→parent index once |
| misc | Minor | `target_profiles.py:439-447` boot-time range expansion unclamped (operator YAML, fail-visible) |
| ARCH-3 | Note | C901 ratchet holds count (25) but not size; junos `render_intent` = 1144 lines, top refactor candidate |
| PERF-4/5 | Note | `classify()` linear scan (dicts already built one frame up) + per-occurrence report duplication — both measured fine today (21 ms / 2000 ifaces), cited for the future |

# RA-docs result — R-23, R-25, R-26, R-27

Agent: RA-docs (Sonnet).  All changes are doc-only.  No Python, no HTML, no
test logic touched.

---

## R-23 — AGENTS.md line 171 cites wrong exemplar for contents-map

### Finding + current state

`AGENTS.md:171` reads:

> A file-tree listing or "contents map" in any doc (`ARCHITECTURE.md` partial
> inventories, **migrate.html header comment**, sub-README directory trees)

The phrase "migrate.html header comment" implies that file has a header comment
enumerating its contents.  It does not.  `netcanon/templates/migrate.html` opens
with `{% extends "base.html" %}` then immediately enters a `<style>` block — no
contents map of any kind.

`netcanon/templates/definitions.html:4–19` is the file that actually has a
top-of-file Jinja comment block enumerating four sections.

### Decision

Repoint the exemplar to `definitions.html` (honest, minimal, zero risk).  Adding
a contents map to `migrate.html` would be churn on a file the review already
flags as a refactor candidate (R-29 WATCH); that trade is worse.

### Proposed change

**File:** `AGENTS.md`

```
OLD (line 171, within the table cell):
| A file-tree listing or "contents map" in any doc (`ARCHITECTURE.md` partial inventories, migrate.html header comment, sub-README directory trees) |

NEW:
| A file-tree listing or "contents map" in any doc (`ARCHITECTURE.md` partial inventories, `definitions.html` header comment, sub-README directory trees) |
```

Exact old string (unique in file):

```
(`ARCHITECTURE.md` partial inventories, migrate.html header comment, sub-README directory trees)
```

Exact new string:

```
(`ARCHITECTURE.md` partial inventories, `definitions.html` header comment, sub-README directory trees)
```

### Test plan

Visual diff only.  Confirm `grep -n "migrate.html header comment" AGENTS.md`
returns no matches after the edit; confirm
`grep -n "definitions.html header comment" AGENTS.md` returns exactly one match
(the row just edited).

### Risk + blast radius

Doc-only.  No code path is affected.  The row is informational; changing the
exemplar from one template file to another carries zero regression risk.

---

## R-25 — tests/README.md "See also" has no upward links

### Finding + current state

`AGENTS.md` § "Cross-reference discipline" (lines 208–214) names three
exemplar reciprocity pairs.  The first is:

> `tests/README.md` → `testid_reference.md`, `fixtures/real/RESULTS.md`,
> `fixtures/real/NOTICE.md`

`tests/README.md:129–139` has exactly those three downstream links.
However the same section states:

> A contributor who lands on one doc should be one hop from the others.

`README.md` links to `tests/README.md` (line 263); `AGENTS.md` links to
`tests/README.md` via the "Code Organisation" section (line 225).  Neither is
reciprocated: `tests/README.md` never links back to `README.md` or `AGENTS.md`.

### Proposed change

**File:** `tests/README.md`

Add two rows to the existing "See also" table at lines 129–139.  The table ends
at line 139; insert after the last row, before the closing blank line.

Exact old string (the last two rows of the table plus the trailing newline):

```
| Codec authoring (how to add a new vendor) | [`../netcanon/migration/codecs/README.md`](../netcanon/migration/codecs/README.md) |
| Device-definition + target-profile schema | [`../definitions/README.md`](../definitions/README.md) |
```

Exact new string:

```
| Codec authoring (how to add a new vendor) | [`../netcanon/migration/codecs/README.md`](../netcanon/migration/codecs/README.md) |
| Device-definition + target-profile schema | [`../definitions/README.md`](../definitions/README.md) |
| Project orientation + quickstart | [`../README.md`](../README.md) |
| Contributor rules + hard rules | [`../AGENTS.md`](../AGENTS.md) |
```

### Test plan

No automated test.  Visual check:

1. `grep -n "README.md\|AGENTS.md" tests/README.md` — confirm both new links appear.
2. Confirm the table still renders correctly in a Markdown viewer (two extra rows,
   consistent pipe-style).

### Risk + blast radius

Doc-only, additive.  No existing link is removed or altered.  The two added links
point to files that already exist and are stable.

---

## R-26 — nxos-codec README sub-pages listed as bare backticks

### Finding + current state

`docs/v0.2.0-planning/03-nxos-codec/README.md:518–531` "References + further
reading" section lists sub-pages as bare backtick-wrapped filenames, not
Markdown links.  Example: `` `02-codec-architecture.md` `` rather than
`[02-codec-architecture.md](02-codec-architecture.md)`.

Actual files present in the directory (confirmed via Glob):

```
docs/v0.2.0-planning/03-nxos-codec/
  01-grammar-survey.md
  02-codec-architecture.md
  03-canonical-mapping.md
  04-test-plan.md
  05-fixture-targets.md
  06-capabilities-matrix.md
```

All six files from the listing exist.  The section currently reads:

```
* `01-grammar-survey.md` — full per-stanza grammar inventory + IOS-XE
  delta table.
* `02-codec-architecture.md` — module layout, class shape, parse +
  render strategies, port-name handling, probe ladder.
* `03-canonical-mapping.md` — xpath → NX-OS command table + schema
  extension list.
* `04-test-plan.md` — unit + real-capture + cross-vendor test
  matrix, per-phase test counts.
* `05-fixture-targets.md` — batfish + community corpus targets,
  per-fixture grammar coverage.
* `06-capabilities-matrix.md` — proposed `CapabilityMatrix` row
  list with grammar-pointer justifications.
```

### Proposed change

**File:** `docs/v0.2.0-planning/03-nxos-codec/README.md`

Exact old string:

```
* `01-grammar-survey.md` — full per-stanza grammar inventory + IOS-XE
  delta table.
* `02-codec-architecture.md` — module layout, class shape, parse +
  render strategies, port-name handling, probe ladder.
* `03-canonical-mapping.md` — xpath → NX-OS command table + schema
  extension list.
* `04-test-plan.md` — unit + real-capture + cross-vendor test
  matrix, per-phase test counts.
* `05-fixture-targets.md` — batfish + community corpus targets,
  per-fixture grammar coverage.
* `06-capabilities-matrix.md` — proposed `CapabilityMatrix` row
  list with grammar-pointer justifications.
```

Exact new string:

```
* [`01-grammar-survey.md`](01-grammar-survey.md) — full per-stanza grammar inventory + IOS-XE
  delta table.
* [`02-codec-architecture.md`](02-codec-architecture.md) — module layout, class shape, parse +
  render strategies, port-name handling, probe ladder.
* [`03-canonical-mapping.md`](03-canonical-mapping.md) — xpath → NX-OS command table + schema
  extension list.
* [`04-test-plan.md`](04-test-plan.md) — unit + real-capture + cross-vendor test
  matrix, per-phase test counts.
* [`05-fixture-targets.md`](05-fixture-targets.md) — batfish + community corpus targets,
  per-fixture grammar coverage.
* [`06-capabilities-matrix.md`](06-capabilities-matrix.md) — proposed `CapabilityMatrix` row
  list with grammar-pointer justifications.
```

### Test plan

1. Confirm all six target filenames exist:
   `ls docs/v0.2.0-planning/03-nxos-codec/*.md` — all six should appear.
2. Render `docs/v0.2.0-planning/03-nxos-codec/README.md` in a Markdown viewer;
   every bullet should now be a clickable link.
3. `grep -n '^\* \`[0-9]' docs/v0.2.0-planning/03-nxos-codec/README.md` should
   return no matches (no bare-backtick filename bullets remain).

### Risk + blast radius

Doc-only, planning dossier.  Links use relative paths relative to the file's own
directory — the correct form for sibling files in the same directory.  All target
files confirmed to exist.

---

## R-27 — Four leaf docs with zero inbound Markdown links

### Finding + current state

Four files have no inbound Markdown link from any committed `.md` file in the
repo (confirmed via the investigation dossier `docs/project-review/2026-06-06/
docs-review/01-investigation-DB-scaffolding.md`):

| File | Status |
|------|--------|
| `tools/README.md` | Bare-backtick mentions only; no `[...](tools/README.md)` link |
| `netcanon_desktop/README.md` | No inbound link |
| `netcanon/definitions/README.md` | No inbound link (distinct from top-level `definitions/README.md` which is well-linked) |
| `tests/fixtures/real/phase4_spawn_tasks.md` | No inbound link |

For each, the best parent is identified below and one natural insertion proposed.

---

### R-27a — `tools/README.md`

**Parent:** `ARCHITECTURE.md` § "Cross-mesh fidelity audit harness"
(lines 768–776).  That section names `tools/run_full_mesh.py` and
`tools/run_phase4_reconciliation.py` but not `tools/README.md`.

**Proposed change — File:** `ARCHITECTURE.md`

The paragraph at line 771 reads:

```
Beyond the test layers above, a separate audit harness lives at
`tools/run_full_mesh.py` (Phase 1: mechanical drift) +
`tools/run_phase4_reconciliation.py` (Phase 4: classify drift
against per-pair Phase-3 expectation YAMLs in
`tests/fixtures/cross_vendor_expectations/`).  Output committed as
`tests/fixtures/real/CROSS_MESH_RESULTS.md` and
`tests/fixtures/real/PHASE4_RECONCILIATION.md`.
```

Exact old string:

```
Beyond the test layers above, a separate audit harness lives at
`tools/run_full_mesh.py` (Phase 1: mechanical drift) +
`tools/run_phase4_reconciliation.py` (Phase 4: classify drift
against per-pair Phase-3 expectation YAMLs in
`tests/fixtures/cross_vendor_expectations/`).  Output committed as
`tests/fixtures/real/CROSS_MESH_RESULTS.md` and
`tests/fixtures/real/PHASE4_RECONCILIATION.md`.
```

Exact new string:

```
Beyond the test layers above, a separate audit harness lives at
[`tools/run_full_mesh.py`](tools/run_full_mesh.py) (Phase 1: mechanical drift) +
[`tools/run_phase4_reconciliation.py`](tools/run_phase4_reconciliation.py) (Phase 4: classify drift
against per-pair Phase-3 expectation YAMLs in
`tests/fixtures/cross_vendor_expectations/`).  Output committed as
`tests/fixtures/real/CROSS_MESH_RESULTS.md` and
`tests/fixtures/real/PHASE4_RECONCILIATION.md`.
See [`tools/README.md`](tools/README.md) for full usage notes and cell-status legend.
```

---

### R-27b — `netcanon_desktop/README.md`

**Parent:** `README.md` § "Desktop (Windows)" (lines 147–159).  That section
describes the desktop shell but links only to the GitHub Releases page and
the `[desktop]` extra — it never links to `netcanon_desktop/README.md`.

**Proposed change — File:** `README.md`

The paragraph at line 158 reads:

```
The desktop shell runs the same FastAPI app inside a PySide6 webview
with a tray icon — same UI, no command-line.
```

Exact old string:

```
The desktop shell runs the same FastAPI app inside a PySide6 webview
with a tray icon — same UI, no command-line.
```

Exact new string:

```
The desktop shell runs the same FastAPI app inside a PySide6 webview
with a tray icon — same UI, no command-line.  See
[`netcanon_desktop/README.md`](netcanon_desktop/README.md) for the
threading model, settings, and MSI build instructions.
```

---

### R-27c — `netcanon/definitions/README.md`

**Parent:** `ARCHITECTURE.md` § "Layer 1 — Vendor Definition" (lines 102–134).
That section mentions `netcanon/definitions/schema.py` (line 114) and links to
`definitions/README.md` (line 133) but never links to `netcanon/definitions/README.md`
(the loader / Pydantic-model README, a distinct file).

**Proposed change — File:** `ARCHITECTURE.md`

The sentence at line 133 reads:

```
See [`definitions/README.md`](definitions/README.md) for the full
authoring guide.
```

Exact old string:

```
See [`definitions/README.md`](definitions/README.md) for the full
authoring guide.
```

Exact new string:

```
See [`definitions/README.md`](definitions/README.md) for the full
authoring guide; [`netcanon/definitions/README.md`](netcanon/definitions/README.md)
for the loader implementation and Pydantic schema reference.
```

---

### R-27d — `tests/fixtures/real/phase4_spawn_tasks.md`

**Parent:** `tests/fixtures/real/PHASE4_RECONCILIATION.md` — that file's "See
also" section (lines 50–58) already links to `CROSS_MESH_RESULTS.md`,
`user_smoke_findings.md`, `_phase4_runs/`, etc., but not to
`phase4_spawn_tasks.md`.  The spawn-tasks file is the direct action-items
document that follows from the reconciliation, so this is the most natural
parent.

**Proposed change — File:** `tests/fixtures/real/PHASE4_RECONCILIATION.md`

The "See also" section ends at:

```
- ``tests/fixtures/real/user_smoke_findings.md`` — operator-spotted issues + methodology improvements (incl. the 2026-05-03 structural-collapse comparator fix)
```

Exact old string (the last bullet of the See-also block):

```
- ``tests/fixtures/real/user_smoke_findings.md`` — operator-spotted issues + methodology improvements (incl. the 2026-05-03 structural-collapse comparator fix)
```

Exact new string:

```
- ``tests/fixtures/real/user_smoke_findings.md`` — operator-spotted issues + methodology improvements (incl. the 2026-05-03 structural-collapse comparator fix)
- ``tests/fixtures/real/phase4_spawn_tasks.md`` — self-contained fix-task prompt drafts for the top-6 CODEC_BUG leverage items; ready to pass to a spawned agent session
```

Note: `PHASE4_RECONCILIATION.md` uses double-backtick ``code`` style throughout
its See-also section (it is a generated file and uses that convention), so the
new entry matches that style rather than Markdown link syntax.  The text is
still a path that a reader can navigate to; a Markdown link would work too but
would be inconsistent with the rest of the section.  If the orchestrator prefers
a Markdown link, the equivalent is:

```
- [`tests/fixtures/real/phase4_spawn_tasks.md`](phase4_spawn_tasks.md) — self-contained fix-task prompt drafts for the top-6 CODEC_BUG leverage items; ready to pass to a spawned agent session
```

---

### Test plan (R-27 aggregate)

```
# After all four edits:
grep -rn "tools/README.md" ARCHITECTURE.md            # expect ≥1 Markdown link
grep -rn "netcanon_desktop/README.md" README.md        # expect ≥1 Markdown link
grep -rn "netcanon/definitions/README.md" ARCHITECTURE.md  # expect ≥1 Markdown link
grep -rn "phase4_spawn_tasks" tests/fixtures/real/PHASE4_RECONCILIATION.md  # expect 1 hit
```

No Python tests are affected; all changes are doc-only.

### Risk + blast radius

All four changes are additive (new sentences / new table rows / new bullets).
No existing content is removed or altered.  All target files confirmed to exist.
The `PHASE4_RECONCILIATION.md` note matches that file's existing style
(double-backtick paths in the See-also section).

---

## Self-assessment

| Finding | Confidence | Notes |
|---------|-----------|-------|
| R-23 | High | Both template files read; exemplar swap is a one-string change with no ambiguity |
| R-25 | High | Two rows added to an existing table; anchor paths verified (`../README.md`, `../AGENTS.md` from `tests/` are correct relative paths) |
| R-26 | High | All six target filenames confirmed present in the directory; relative path form `[label](filename)` is correct for siblings |
| R-27a | High | Insertion point in ARCHITECTURE.md § "Cross-mesh fidelity audit harness" clearly identified; old string is unique in the file |
| R-27b | High | Insertion sentence at end of Desktop paragraph; old string unique |
| R-27c | High | Old string unique; the loader README path `netcanon/definitions/README.md` confirmed to exist |
| R-27d | Medium | `PHASE4_RECONCILIATION.md` is described as a generated file; if it is fully overwritten on the next `tools/run_phase4_reconciliation.py` run the link will be lost.  The orchestrator should decide whether to add this link to the generation script's template instead.  As a safe fallback the link is also appropriate in `tests/README.md`'s "See also" table (the Phase-4 tooling is already linked there) — adding it there would survive regeneration. |

### Open question for orchestrator (R-27d only)

`PHASE4_RECONCILIATION.md` is listed as "committed, overwritten on every run"
in `tools/README.md:194`.  If the orchestrator prefers not to edit a generated
file, the alternative insertion point is `tests/fixtures/real/RESULTS.md`
"See also" block, or `tests/README.md`'s "See also" table (adding a row:
`| Phase 4b fix-task prompt drafts | [phase4_spawn_tasks.md](fixtures/real/phase4_spawn_tasks.md) |`).
Both parent files are stable non-generated docs.  Recommend orchestrator picks
one of the three options; all three are valid.

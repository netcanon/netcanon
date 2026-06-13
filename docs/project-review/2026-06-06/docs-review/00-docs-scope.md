# Fleet D — documentation review scope

Six read-only reviewers.  Each owns a lens, reads broadly across the
repo for that lens, and writes one long-form investigation file.
Boundaries are drawn to minimize overlap; where two lenses touch the
same file (e.g. a codec `__init__.py` has both a header AND a
docstring), the owning lens is named below.

Common baseline for every D reviewer:

* Ground every claim in `file:line`.  Quote the offending text.
* "Accurate to current state" means **HEAD `b08040c` / v0.1.2**.
  Watch for stale Phase-N language, pre-rename repo URLs, version
  strings, counts that should be pointers, shipped-vs-claimed drift.
* Cross-check against `AGENTS.md` § Documentation Sync Checklist —
  many doc rules are codified there; cite the row a finding violates.
* The 2026-05-21 docs-audit already fixed a batch; do **not** re-flag
  what it closed (check `docs/docs-audit/2026-05-21/fix-plan.md`).
  New drift since, or things that audit missed, are in scope.

---

## DA — Human / operator-facing documentation accuracy

**Owns:** `README.md`; `docs/CAPABILITIES.md`, `docs/TROUBLESHOOTING.md`,
`docs/COMPARISON.md`, `docs/HOW_WE_TEST.md`, `docs/glossary.md`,
`docs/IDENTITY.md`; `docs/vendors/*.md`; `docs/walkthroughs/*.md`;
`BUG_REPORTING.md`; operator-facing sections of `SECURITY.md`.

**Questions:** Does what we tell operators match what the code does?
Are the capability claims matrix-honest (no over/under-claim)? Are
quickstart / install / Docker / pip / MSI instructions runnable as
written? Are the per-vendor pages' fixture/feature claims current?
Is the Tier-1/2/3 story coherent and consistent across pages? Dead
operator-facing links?

## DB — Scaffolding / `.md` interlinking-graph integrity

**Owns:** the cross-reference *graph* across ALL hand-authored `.md`
(top-level, `docs/`, `tests/`, sub-READMEs, `netcanon/**/README.md`).
The `docs/vendor-references/<pair>/` cache is in scope only at the
`_INDEX.md` + schema level (is it linked, is the index complete) —
not per-cell.

**Questions:** Is the "See also" reciprocity actually bidirectional
(AGENTS.md § Cross-reference discipline)? Orphan docs nothing links
to? Broken relative paths / anchor fragments? Does every directory
that should have a README have one? Are the three dated dossiers
(security-triage, docs-audit, project-review) discoverable from the
docs they describe? Produce an explicit **link-graph adjacency
summary** + a dead/one-way-link table.

## DC — Test-ID inventory + per-test explanation discipline

**Owns:** `tests/testid_reference.md`; `tests/README.md`; the
docstring/naming/comment quality *of test modules themselves*
(are tests adequately explained?); `tests/fixtures/real/RESULTS.md`,
`WANTED.md`, `NOTICE.md`, `PHASE4_RECONCILIATION.md`,
`CROSS_MESH_RESULTS.md` as test-documentation surfaces.

**Questions:** Does every `data-testid` in `templates/` have a row in
`testid_reference.md` and vice-versa (drift in both directions)? Are
test modules explained — module docstrings stating what invariant
the file guards, non-obvious fixtures documented, cryptic
parametrize IDs? Is the markers table accurate (the `slow` marker
was just removed — verify no dangling refs)? Are the real-capture
result docs consistent with each other on counts/certification?

## DD — Docstring accuracy + completeness

**Owns:** module / class / function docstrings across `netcanon/`
source (NOT tests — that's DC; NOT pure header blocks — that's DE).
Special attention to the surfaces the 2026-05-21 audit touched
(canonical Tier annotations, codec `parse_intent`/`render_intent`
Google-style sections, frozen-signature notes) — verify they're
correct and consistent, and find the ones the audit didn't reach.

**Questions:** Do docstrings describe what the code does *now*?
Google-style Args/Returns/Raises present where the signature is
non-trivial? Do `Raises:` blocks match what's actually raised
(recall the Junos `render_intent` `TypeError`-vs-`RenderError`
inconsistency flagged 2026-05-21)? Public functions without
docstrings? Stale "Phase N will…" futures? Pydantic `Attributes:`
consistency on models.

## DE — File-header conventions where appropriate

**Owns:** top-of-file header blocks: module docstring "headers"
(the orientation paragraph + Module layout / Scope blocks in codec
`__init__.py` and `codec.py`), template header comment blocks (e.g.
`migrate.html`'s "Contents map"), `tools/*.py` headers, any
license/SPDX headers, shebangs.  Where a header IS the module
docstring, DE judges the *header-as-orientation* role; DD judges the
API-doc role.

**Questions:** Is there a consistent header convention, and is it
followed? Do the codec `__init__.py` headers (just converted to
pointers in the audit) read consistently across all 8? Do large
templates carry a contents-map header (migrate.html does — do the
others that warrant it)? Missing/!misleading orientation headers on
the god-files? Any copy-paste header bleed (one codec's header naming
another)?

## DF — Contributor / architecture / meta documentation

**Owns:** `AGENTS.md`, `ARCHITECTURE.md`, `docs/METHODOLOGY.md`,
`docs/RELEASE_PLAN.md`, `CHANGELOG.md`, `CONTRIBUTING.md` (if present),
`CODE_OF_CONDUCT.md`, `docs/adding-a-canonical-field.md`,
`docs/adding-a-target-profile.md`, `docs/feature-parity-walkthrough.md`,
the planning trees (`docs/v0.2.0-planning/`, `docs/fixture-research-*/`)
at a structural level, and the prior dossiers' READMEs.

**Questions:** Do the contributor directives match reality (e.g.
does AGENTS.md's doc-sync table reference line ranges that have since
drifted — METHODOLOGY just migrated off those)? Is ARCHITECTURE.md's
component inventory current with the 112-file source tree? Does
CHANGELOG follow its own stated conventions? Are the planning folders
honestly marked shipped/deferred? Internal consistency between
AGENTS.md hard-rules and what the code actually enforces.

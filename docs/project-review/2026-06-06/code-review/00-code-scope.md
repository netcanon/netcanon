# Fleet C — code & architecture review scope

Six read-only, review-grade reviewers at the Opus 4.8 1M tier.  Each
owns a lens; the file-by-file coverage is split between CB (platform)
and CC (codecs) so every source file has an owner.  CA/CD/CE/CF are
cross-cutting lenses over the same tree.

Common baseline for every C reviewer:

* Ground every finding in `file:line`, with the offending code quoted
  and a concrete failure scenario where applicable.
* Severity per the README scale (P0–P3 / OBSERVATION).  Be honest
  about confidence; mark anything you couldn't fully verify as
  `UNVERIFIED` so the adversarial pass can target it.
* This is a **mature, deliberately-disciplined** codebase (matrix-
  honesty methodology, frozen pipeline signatures, ship-before-wire).
  Read `docs/METHODOLOGY.md` + `AGENTS.md` § Hard Rules first so you
  don't flag an intentional invariant as a bug.  When something looks
  wrong but is load-bearing-by-design, record it as an OBSERVATION
  with the rationale, not a P-level defect.
* Tiered file-by-file: **every file in your partition gets at least a
  one-line verdict**; core/complex/high-risk files get full long-form
  treatment.
* Read-only.  If you spawn sub-agents, they are read-only too and you
  say so in their prompt.

---

## CA — Application architecture

**Lens, whole tree.**  The four-layer model (wire ↔ codec ↔ canonical
↔ wire), the two co-hosted concerns (backup vs migration), request
lifecycle (`main.py` factory → routers → services → storage/
collectors), dependency *direction* (does anything import "upward"?),
the `get_collector` / `get_storage` seams, where business logic lives
vs. leaks into routes, async vs sync boundaries, the desktop embedded-
server split.  Assess against `ARCHITECTURE.md`'s claimed design — do
code and doc agree? Name the load-bearing seams and any layering
violations.

## CB — File-by-file: platform (non-codec) source + desktop

**Owns (tiered, every file gets a verdict):** everything under
`netcanon/` EXCEPT `migration/codecs/` — i.e. `main.py`, `cli.py`,
`config.py`, `logging_config.py`, `api/` (incl. all routes), `services/`,
`storage/`, `collectors/`, `models/`, `security/`, `definitions/`,
`tools/`, `migration/_*.py`, `migration/target_profiles.py`,
`migration/canonical/*`, plus `netcanon_desktop/` (11 files).
Deep-dive the platform god-files: `api/routes/ui.py` (894),
`models/migration.py` (842), `services/migration_pipeline.py` (711),
`api/routes/migration.py` (678), `canonical/port_names.py` (614),
`tools/sanitize.py` (565), `target_profiles.py` (544),
`canonical/intent.py` (926 — coordinate with CE on god-file framing;
you cover correctness/clarity, CE covers cohesion/SRP).

## CC — Codec architecture + per-codec file-by-file

**Owns (tiered):** all of `migration/codecs/` — `base.py`,
`registry.py`, `_input_shape.py`, `_mock/`, and the 8 real codecs
(`__init__.py` + `codec.py` + `parse.py`/`render.py` + `port_names.py`
+ codec-specific helpers like `vlan_heuristics.py`, `_svi_absorption.py`).
Assess the **codec contract**: is the split-codec vs single-file
(`cisco_iosxe` NETCONF) divergence justified? Is the
parse→canonical→render round-trip discipline uniform? Probe/registry
mechanics, port-name bridge consistency, capability-matrix authoring
consistency.  Deep-dive the parse god-files (junos 2455, iosxe_cli
1672, arista 1387, mikrotik 1291, aruba 1215).  Flag per-codec
divergences that should be shared (DRY across codecs) — but respect
that some divergence is genuine vendor-grammar difference.

## CD — Modularity & coupling

**Lens, whole tree.**  Import graph health (cycles? layering
inversions? deep reach-ins like `from ....models import`?), the
shared-transform story (`canonical/transforms.py`, `_naming.py`,
`_tier3_detection.py`, `_user_secrets.py` — are they consumed
uniformly or copy-pasted?), the per-pane rename-orchestrator pattern
(`*_names.py`), extension-point cleanliness (adding a codec / a
canonical field / a rename category — how many files must change?),
the frozen-signature contract on `migration_pipeline.py`.  Where is
coupling too tight, and where is it appropriately loose?

## CE — God-file / cohesion / SRP assessment

**Lens, targeted.**  The LOC leaders from `00-snapshot.md`: source
(`juniper_junos/parse.py` 2455, `cisco_iosxe_cli/parse.py` 1672,
`intent.py` 926, `ui.py` 894, `models/migration.py` 842,
`migration_pipeline.py` 711, `port_names.py` 614, `sanitize.py` 565)
and templates (`migrate.html` 2477, `definitions.html` 926).  For
each: is the size *earned* (irreducible vendor grammar / a single
cohesive responsibility) or is it a god-file (multiple
responsibilities that want splitting)? Give a per-file verdict:
KEEP-AS-IS (with rationale) / SPLIT (with a concrete seam proposal) /
WATCH.  Be concrete about *where* a split line would fall.

## CF — Cross-cutting: error-handling, security, perf, dependencies

**Lens, whole tree.**  Error-handling discipline (exception taxonomy
— `ParseError`/`RenderError`/`ValidationError`; the Junos `TypeError`
outlier; are errors caught at the right layer; silent-drop vs
surfaced); input-validation / security posture (the v0.1.2 defusedxml
swaps — are ALL XML parse sites covered? `paramiko` AutoAddPolicy
trust model; `file_store` size guard; any `eval`/`exec`/`subprocess`/
path-traversal/SSRF surface; secret handling in `security/` +
`_user_secrets.py` + sanitiser); performance footguns (unbounded
loops, O(n²) over configs, regex catastrophic-backtrack risk in the
big parsers, memory in job registry); dependency hygiene
(`pyproject.toml` pins, defusedxml, unused/over-broad deps).  Note: a
full security audit landed 2026-05-21 — confirm it stuck and look for
what it didn't cover.

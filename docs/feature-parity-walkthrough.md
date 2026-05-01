# Feature-parity walkthrough — SNMPv3 USM rename (P2C6)

## Why this doc exists

`CLAUDE.md` lays out the feature-parity discipline abstractly: every
functional change must land on both platforms in the same branch, every
new interactive HTML element needs a `data-testid`, every new module or
endpoint that changes a docstring inventory must update that
inventory in the same commit.  The rules are concrete; the *shape*
of a real feature that actually exercises all of them is not.  This
doc takes one canonical commit — the SNMPv3 USM cross-mesh override
(`145642e`) — and walks through every file it touched, layer by
layer, so a new contributor can pattern-match instead of guessing
which inventory rows apply to a feature with similar reach.

## The feature (SNMPv3 USM rename)

NetConfig's migrate UI lets operators rewrite identity-bearing names
during cross-vendor migration: ports, VLANs, local users, SNMP v1/v2c
communities — and now SNMPv3 USM `securityName` values too.  When the
operator opens the rename modal, picks the SNMPv3 rail, and types a
target name (or a drop) for a row, the pipeline rewrites the canonical
intent so every downstream codec emits the new name on render.  Auth /
priv keys, group, and `engine_id` follow the renamed record verbatim;
crypto material is never combined across users.  Codecs that don't
support v3 (OPNsense, the Cisco IOS-XE NETCONF stub) declare `snmpv3`
in their `unsupported_rename_categories` set so the UI can fire a
target-codec compatibility banner instead of silently dropping the
operator's overrides.

## Layer-by-layer file inventory

The numbered list below is the file-touch sequence from `git show
145642e --stat`.  Every entry names a real file that lives in the tree
today; verify by running `git show 145642e:<path>` against any
suspicion.

1. **Canonical schema — `netconfig/migration/canonical/intent.py`.**
   Adds the `CanonicalSNMPv3User` model (`name`, `group`,
   `auth_protocol`, `auth_passphrase`, `priv_protocol`,
   `priv_passphrase`, `engine_id`) and a `v3_users:
   list[CanonicalSNMPv3User]` field on the existing `CanonicalSNMP`
   container.  The schema change is upstream of every other layer —
   parse paths populate it, render paths consume it, the orchestrator
   walks it.
2. **Per-codec parse + render — six bidirectional codecs.**
   `arista_eos/codec.py`, `aruba_aoss/codec.py`,
   `cisco_iosxe_cli/codec.py`, `fortigate_cli/codec.py` (with
   `parse.py` + `render.py` siblings), `juniper_junos/codec.py`,
   `mikrotik_routeros/codec.py` each grew parse rules that extract
   USM users from the wire format and render rules that emit them
   back.  The `parse_only` Cisco IOS-XE CLI codec gained parse-only
   coverage (it can read v3 user lines from a backup but doesn't
   render them — see the codec's `direction` ClassVar).
3. **Capability declarations — non-supporting codecs.**
   `netconfig/migration/codecs/opnsense/codec.py` and
   `netconfig/migration/codecs/cisco_iosxe/codec.py` (the NETCONF
   stub) added `"snmpv3"` to their `unsupported_rename_categories`
   ClassVar.  This is the only signal the UI consults to decide
   whether the SNMPv3 pane should show its compatibility banner.
4. **Rename orchestrator — `netconfig/migration/canonical/snmpv3_user_names.py`.**
   New module, sibling to `port_names.py`, `vlan_names.py`,
   `local_user_names.py`, and `snmp_names.py`.  Same shape as its
   siblings: a public `build_snmpv3_user_rename_transform(rename_map=...)`
   that returns a `(transform, result)` pair the pipeline composes
   into the override stack.  Sentinel semantics match the four older
   orchestrators — `None` is "do nothing", `{}` is "auto-introspect",
   `{src: tgt}` renames, `{src: None}` drops.
5. **Pipeline wiring — `netconfig/services/migration_pipeline.py`.**
   `run_plan_with_overrides` gained an optional
   `snmpv3_user_rename_map` keyword argument.  The signature
   *extension* respects the Hard Rule against changing existing
   pipeline-stage signatures: every prior caller still works because
   the parameter has a `None` default.  The module's top-of-file
   docstring lists "the five rename categories" as the engaged-
   category vocabulary; that count is anchored in code, not prose.
6. **API endpoint — `netconfig/api/routes/migration.py`.**
   New route `POST /api/v1/migration/plan/snmpv3` (handler
   `plan_migration_snmpv3`).  Delegates straight into
   `run_plan_with_overrides` with only `snmpv3_user_rename_map`
   populated — the other four maps default to `None`.  The module
   docstring's "Endpoints" inventory was updated in the same commit;
   that's the inventory-rot rule from CLAUDE.md applied.
7. **Web UI — `netconfig/templates/migrate.html` + new partial.**
   The template gained a fifth rail button
   (`migrate-rename-rail-snmpv3`), a pane wrapper, an empty-state
   slot, the per-user rename table, and a compat-banner slot.  The
   per-user row rendering logic lives in
   `netconfig/templates/_partials/snmpv3-user-rename-table.js` — a
   new partial added in the same commit.  Two existing partials
   (`rename-panel.js`, `rename-apply.js`) gained branches for the
   new category.  The migrate.html "Contents map" comment block at
   the top of the file lists the partials it includes; that map was
   updated in the same commit (CLAUDE.md doc-sync rule for new
   partials).
8. **Desktop platform — no diff.**
   The desktop shell (`netconfig_desktop/`) embeds the same FastAPI
   app and renders the same HTML through a WebView.  A pure server +
   template feature like this one needs no desktop-specific code —
   the new pane appears in the embedded window automatically.  The
   parity check is *visual*, not code: open the desktop shell, hit
   the SNMPv3 rail, confirm the rename table fits at the embedded
   window's default size, confirm the compat banner doesn't overflow
   the modal.  This is the moment to look for window-chrome
   regressions that the web-only test tier wouldn't catch.
9. **Cross-mesh smoke — `tests/unit/migration/test_cross_mesh_overrides.py`.**
   New `_SNMPV3_SRC_CONFIGS` dict carries one source config per
   v3-supporting codec (the synthesised configs are the
   ground-truth fixtures the smoke tests parse from).  New
   `_SNMPV3_CAPABLE` and `_SNMPV3_TARGET_CAPABLE` lists drive a
   parametrised `test_snmpv3_user_rename_smoke_cross_codec` over the
   full Cartesian product.  These two lists follow the
   per-category naming pattern already used by
   `_LOCAL_USER_TARGET_CAPABLE` and `_SNMP_TARGET_CAPABLE` —
   *not* a single global `_SOURCE_CAPABLE` / `_TARGET_CAPABLE`
   pair.  The "everything-at-once" combined test
   (`test_combined_overrides_all_categories`) gained a fifth
   category in the same map.
10. **Bidirectionality invariants — `tests/unit/migration/test_bidirectionality_invariants.py`.**
    The existing meta-test catches structural gaps where a codec
    advertises a wire format it can't actually round-trip.  No
    SNMPv3-specific assertions were added — the meta-test verifies
    "every CLI vendor has a CLI render path" at the codec level, and
    SNMPv3 inherits that guarantee by living inside the bidirectional
    codecs.  If a future commit demotes a v3-supporting codec to
    `parse_only` without updating capability advertisements, this
    file fails first with an actionable message.
11. **Per-codec wire-through — `tests/unit/migration/test_snmpv3_wire_through.py`.**
    New file.  One test class per supporting codec with parse-then-
    render assertions covering: every documented v3 grammar variant,
    the sentinel `aes` / `aes256` / `aes 128` Arista forms, the
    Aruba two-line user-then-group merge, the Junos VACM
    `security-to-group` join, and the MikroTik `/snmp community`
    overload disambiguation by `authentication-protocol=`.  This is
    where the per-codec correctness lives; the cross-mesh smoke test
    only checks "doesn't crash and the rename map applied".
12. **Orchestrator unit tests — `tests/unit/migration/test_snmpv3_user_names.py`.**
    Pure-function coverage of the orchestrator's public surface:
    sentinel handling, collision merge ("first-wins"), dropped-
    user state propagation, auth/priv-key follow-through.
13. **Integration — `tests/integration/test_migration_api.py`.**
    `TestPlanSnmpV3Endpoint` exercises `POST
    /api/v1/migration/plan/snmpv3` through the FastAPI TestClient.
    Asserts `source_snmpv3_users` populates correctly, the rename
    map round-trips into `snmpv3_user_renames`, and drops
    surface in `snmpv3_user_drops`.  (The prompt for this doc
    pointed at `tests/integration/test_ui_routes.py`; the actual
    SNMPv3 endpoint tests live in `test_migration_api.py`.  The UI-
    routes file mentions SNMPv3 only in passing as an example of an
    unsupported-on-target category.)
14. **E2E — gap.**
    `tests/e2e/test_migrate_rename_modal.py` covers the rename modal
    generally but does not have an SNMPv3-specific scenario as of
    this commit.  Adding one is a reasonable follow-up; it should
    open the SNMPv3 rail, type a rename in a row, submit, and assert
    the resulting plan response includes the rewrite.  Same shape as
    the existing local-users scenario.
15. **Desktop tests — gap.**
    `tests/desktop/` does not have an SNMPv3-specific test in this
    commit.  The general desktop server fixture (`test_server.py`)
    already exercises the embedded FastAPI app, so the v3 endpoint
    is reachable through the desktop's bound port; what's missing is
    a targeted assertion.  Worth a follow-up if SNMPv3-on-desktop
    becomes a regression vector.
16. **testid inventory — `tests/testid_reference.md`.**
    Eleven new testids documented in the SNMPv3 section of the
    migrate-page table: rail button, rail count badge, pane
    wrapper, empty state, sections container, table, per-user row
    template, per-user override input, per-user drop link, summary
    sub-line, and compat banner.  Run the CLAUDE.md self-grep
    (`grep -r 'data-testid="<new-id>"' tests/testid_reference.md`)
    on each new ID to confirm the doc actually picks them up.
17. **Module docstrings.**
    `migration_pipeline.py`'s docstring enumerates "the five rename
    categories" as a numbered list; that list was updated.
    `routes/migration.py`'s docstring enumerates per-pane endpoints;
    `/plan/snmpv3` was added there in the same commit.  Skipping
    either docstring update would have shipped a stale inventory —
    exactly what the CLAUDE.md "module docstring inventory" row
    catches.
18. **Architecture doc — `ARCHITECTURE.md`.**
    Three sections name the new category: the override-pipeline
    composition order ("ports → vlans → local_users → snmp_community
    → snmpv3_users"), the partial inventory's bullet for
    `snmpv3-user-rename-table.js`, and the per-pane summary
    paragraph.  CLAUDE.md's "fourth or subsequent commit shipping
    pieces of the same conceptual subsystem" rule applied here:
    P2C6 was the sixth per-pane commit, well past the threshold for
    explicit architecture-level acknowledgement.
19. **Roadmap — `translator-plans.txt`.**
    The shipped feature was struck through; future cross-mesh
    candidates (NTP / DNS / syslog / SNMP trap-host / RADIUS) were
    audited and recorded with a viability verdict.  This is part of
    the same conceptual subsystem and lives outside the formal
    doc-sync table, but updating it during the commit closes the
    "what's next" question for the next contributor.

## The discipline checklist

| Layer | Do you need this? | Where |
|---|---|---|
| Canonical schema | If new field shape | `netconfig/migration/canonical/intent.py` |
| Per-codec parse | If existing wire-format carries the data | each `<vendor>/codec.py` |
| Per-codec render | If target codecs need to emit | each `<vendor>/codec.py` |
| Capability declaration | If some codecs don't support the entity | `unsupported_rename_categories` ClassVar on the non-supporting codec(s) |
| Rename orchestrator | If user can rename / drop the entity | new sibling under `netconfig/migration/canonical/` |
| Pipeline parameter | If overrides flow from API | `migration_pipeline.run_plan_with_overrides` (extension only — never change existing parameter shapes) |
| API endpoint | If UI surfaces overrides | `netconfig/api/routes/migration.py` |
| Web UI | If operator-facing | `netconfig/templates/migrate.html` + new partial |
| Desktop UI parity | Always for new visible surfaces | WebView visual sanity check |
| testids | Always for new interactive elements | `tests/testid_reference.md` self-grep |
| Orchestrator unit tests | If orchestrator added | `tests/unit/migration/test_<feature>_names.py` |
| Per-codec wire-through | If parse + render added on multiple codecs | `tests/unit/migration/test_<feature>_wire_through.py` |
| Cross-mesh smoke | If touches a codec surface | `tests/unit/migration/test_cross_mesh_overrides.py` — add `_<FEATURE>_SRC_CONFIGS` and `_<FEATURE>_CAPABLE` / `_<FEATURE>_TARGET_CAPABLE` lists |
| Meta-guards | Always | `tests/unit/migration/test_bidirectionality_invariants.py` should still pass |
| API integration | If API endpoint added | `tests/integration/test_migration_api.py` |
| E2E | If web UI surface added | `tests/e2e/` |
| Desktop tests | If server behaviour changed | `tests/desktop/` |
| Module docstrings | If module enumerates endpoints / phases | the docstring inventory at the top of the file |
| Architecture doc | At commit 3-5 of a thematic series | `ARCHITECTURE.md` |
| Doc-sync table | Always | the "Documentation Sync Checklist" in `CLAUDE.md` |

## Common pitfalls (extracted from real bugs)

* **Forgetting to extend the per-category capability list in
  `test_cross_mesh_overrides.py`.** Smoke tests only run over
  codec pairs the contributor remembered to enumerate.  A v3-capable
  codec missing from `_SNMPV3_CAPABLE` looks fine in CI and explodes
  in production the first time someone selects it as a source.
* **Adding a render path without promoting `direction: ClassVar[str]`
  from `parse_only` to `bidirectional`.** The bidirectionality meta-
  test (`tests/unit/migration/test_bidirectionality_invariants.py`)
  catches this with an actionable error.  Trust the failure message —
  it tells you exactly which codec mismatched.
* **Forgetting `data-testid` on a new interactive element.** CLAUDE.md
  says E2E tests use testids exclusively; a missing testid is silent
  until someone tries to write the E2E test.  The doc-side guard is
  the self-grep against `tests/testid_reference.md` before commit.
* **Adding a partial without listing it in `migrate.html`'s "Contents
  map" comment block.** The block is the only inventory of which
  partials the page includes.  A partial silently appended to
  `_partials/` without a map update is a doc-rot landmine for the
  next contributor reading the template top-down.
* **Changing the existing pipeline-stage signature instead of
  extending it.** The Hard Rule is "never change signatures of
  existing pipeline-stage functions."  *Adding* a new keyword
  argument with a `None` default is fine — every prior caller still
  works.  *Reordering* or *renaming* an existing argument is not.
* **Bumping the canonical-orchestrator return shape.** The four older
  orchestrators all return `(transform, result)` pairs.  A new
  orchestrator that returns `(transform, result, extra)` instead
  forces every pipeline-stage caller to deconstruct differently;
  match the sibling shape exactly unless you have a reason
  load-bearing enough to write down.
* **Skipping the "fourth-commit architecture review" gate.** Each
  per-pane category was a single commit, but the *concept* of
  per-pane category overrides accumulated over six commits before
  ARCHITECTURE.md got an explicit section.  The doc-sync rule says
  acknowledge the concept around commit 3-5 of a thematic series; if
  you're commit 4 and the architecture doc still describes piecemeal
  mechanics, you're the one who closes the gap.

## See also

* [`../CLAUDE.md`](../CLAUDE.md) — Feature-Parity Checklist + Doc
  Sync Checklist (the abstract rules this doc instantiates)
* [`../ARCHITECTURE.md`](../ARCHITECTURE.md) — 4-layer architecture
  and the per-pane category section
* [`adding-a-canonical-field.md`](adding-a-canonical-field.md) —
  sibling worked example for a smaller-shape feature (MTU
  wire-through), useful when only the canonical-field row applies
* [`../netconfig/migration/canonical/README.md`](../netconfig/migration/canonical/README.md)
  — orchestrator pattern (Layer 3 entry guide)
* [`../netconfig/api/routes/README.md`](../netconfig/api/routes/README.md)
  — route conventions (Layer 4 entry guide)
* [`../tests/testid_reference.md`](../tests/testid_reference.md) —
  interactive-element inventory and the SNMPv3 section that landed
  in the same commit
* [`../netconfig/migration/codecs/README.md`](../netconfig/migration/codecs/README.md)
  — codec authorship guide; consult when extending the per-codec
  parse + render row above

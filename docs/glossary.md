# Glossary

A central reference for project-specific jargon used across NetConfig.
New contributors (humans and Claude agents) should skim this before
diving into `ARCHITECTURE.md` or codec-level READMEs. Terms are grouped
by concern and listed alphabetically within each section.

## Architecture & data flow

- **CanonicalIntent** — the root model of the 4-layer intermediate
  representation. Every codec parses into, and renders from, this
  vendor-neutral tree. Reference `netconfig/migration/canonical/intent.py`.
- **Capture-first transform** — load-bearing pattern in
  `run_plan_with_overrides` that populates `source_vlans`,
  `source_local_users`, `source_snmp_community`, `source_snmpv3_users`,
  and `source_hostname` BEFORE any rename engages, so UI panes can
  enumerate source entities even when the user has not yet supplied a
  rename map.
- **Frozen pipeline signatures** — Hard Rule. The parameter shapes of
  `run_plan`, `run_plan_with_rename`, and `run_plan_with_overrides` are
  immutable; new override categories are added onto
  `run_plan_with_overrides` rather than by changing existing signatures.
  Reference `netconfig/services/migration_pipeline.py`.
- **Sentinel semantics** — convention for per-pane override maps.
  `None` = don't engage the rename rail; `{}` = auto-heuristic;
  `{src: tgt}` = explicit rename; `{src: None}` = drop the entity.
- **Ship-before-wire** — design pattern in which the canonical schema
  gains a field before any codec parses or renders it. Lets UI and
  pipeline plumbing advance independently of vendor-support breadth.
- **Tier 1 / Tier 2 / Tier 3** — canonical-field categorisation.
  Tier 1 = auto-translatable (hostname, interfaces, vlans,
  static_routes); Tier 2 = review-required (SNMP, local_users, lags,
  dhcp/radius); Tier 3 = `raw_sections` passthrough.

## Codec layer

- **Bidirectional codec** — codec that implements both `parse()` and
  `render()`, allowing it to act as either source or target.
- **Direction** — codec ClassVar declaring its capability; one of
  `bidirectional`, `parse_only`, or `render_only`.
- **INPUT_FORMATS** — codec ClassVar string family (e.g. `cli`,
  `netconf-xml`, `xml`) shown in the target dropdown to disambiguate
  variants of the same vendor (e.g. Cisco IOS-XE NETCONF vs CLI).
- **Probe** — `classmethod probe(raw_prefix) -> (confidence, reason) | None`.
  Each codec votes on a candidate input; the orchestrator picks the
  highest-confidence match for source detection.
- **Wire format** — the operator-paste form of a config: CLI
  `show run`, NETCONF XML, OPNsense `config.xml`, MikroTik `/export`,
  and similar.

## Cross-mesh + testing

- **Cross-mesh / full-mesh** — every-source by every-target test
  matrix. `tests/unit/migration/test_cross_mesh_overrides.py`
  exercises 8x8 bidirectional pairs.
- **Drift guard** — meta-test that catches silent coverage shrinkage
  (e.g. `_DIR_TO_CODEC_NAME` missing a fixture directory, or
  `_SOURCE_CAPABLE` missing a bidirectional codec).
- **Real-capture fixture** — third-party operator config under
  `tests/fixtures/real/<vendor>/`. Source of truth for round-trip
  stability assertions.
- **Round-trip stability** — invariant where
  `parse(raw) -> render(intent) -> parse(rendered)` yields a
  canonically-equal intent. Per-fixture certification state lives in
  `tests/fixtures/real/RESULTS.md`.
- **Port-rename mesh / classify_port_name / format_port_identity** —
  every codec exposes both helpers, allowing port names to translate
  across vendors via the shared `PortIdentity` IR.

## UI + presentation

- **Capability chips** — clickable indicators on `/definitions`
  rendered as `OK N / WARN N / FAIL N` showing per-codec xpath coverage.
- **Per-pane overrides** — the five rename rails surfaced in the
  migrate modal: ports, VLANs, Local Users, SNMP, and SNMPv3.
- **testid discipline** — invariant that every interactive HTML
  element carries a `data-testid`. Inventory lives in
  `tests/testid_reference.md`.

## Operational

- **Backup vs. migration** — the two co-hosted concerns of the
  FastAPI app. Backup pulls raw configs from devices over
  SSH / NETCONF / REST; migration translates a stored backup between
  vendors via the canonical IR.
- **Definitions** — vendor YAML files at `definitions/` describing
  how to log into a given device class.
- **get_collector** — the single mock-point for backup tests. Hard
  Rule: never patch `ConnectHandler` or `paramiko.SSHClient` directly;
  patch this factory instead.
- **Target profile** — hardware-shape definition under
  `definitions/target_profiles/<vendor>/<model>.yaml`. Drives port
  rename and VLAN/user fit-checks in the UI.

## See also

- [`../README.md`](../README.md) — project orientation and quickstart
- [`../ARCHITECTURE.md`](../ARCHITECTURE.md) — the 4-layer design
- [`../CLAUDE.md`](../CLAUDE.md) — contributor directives

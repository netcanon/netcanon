# Glossary

A central reference for project-specific jargon used across Netcanon.
New contributors (human or AI-assisted) should skim this before
diving into `ARCHITECTURE.md` or codec-level READMEs. Terms are grouped
by concern and listed alphabetically within each section.

## Architecture & data flow

- **CanonicalIntent** — the root model of the 4-layer intermediate
  representation. Every codec parses into, and renders from, this
  vendor-neutral tree. Reference `netcanon/migration/canonical/intent.py`.
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
  Reference `netcanon/services/migration_pipeline.py`.
- **Sentinel semantics** — convention for per-pane override maps.
  `None` = don't engage the rename rail; `{}` = auto-heuristic;
  `{src: tgt}` = explicit rename; `{src: None}` = drop the entity.
- **Ship-before-wire** — design pattern in which the canonical schema
  gains a field before any codec parses or renders it. Lets UI and
  pipeline plumbing advance independently of vendor-support breadth.
- **Tier 1 / Tier 2 / Tier 3** — canonical-field categorisation.
  Tier 1 = cross-vendor stable, auto-translatable (hostname,
  interfaces, vlans, static_routes, DNS/NTP/syslog).  Tier 2 =
  translatable with caveats (SNMP, local_users, lags, dhcp,
  radius, vxlan_vnis, evpn_type5_routes, routing_instances,
  apply_groups).  Tier 3 = detected-but-deliberately-not-translated;
  surfaced via `CanonicalIntent.dropped_tier3_sections`
  (notification-only — never auto-rendered).  See
  [`CAPABILITIES.md`](CAPABILITIES.md) for the full list.

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

## Phase 4 reconciliation

- **ALIGNED** — Phase 4 variance class for a per-cell field that
  was preserved on round-trip AND expected to be preserved per the
  Phase 3 vendor-doc-grounded YAML.  Severity: ok.
- **CODEC_BUG** — Phase 4 variance class for a field that drifted
  on round-trip when the docs say it should have been preserved.
  Severity: high — the actionable pile for codec authors.
- **EXPECTED_LOSSY / EXPECTED_UNSUPPORTED** — Phase 4 variance
  classes confirming that drift matches a documented vendor
  limitation or capability gap.  Severity: ok (no codec work
  required).
- **METHODOLOGY_ISSUE_under / METHODOLOGY_ISSUE_over** — Phase 4
  variance classes flagging that the Phase 3 expectation YAML
  disagrees with reality (the codec preserved a field marked
  `lossy`, or drifted on a field marked `not_applicable`).
  Severity: low/medium — usually a docs/expectation update.
- **STRUCTURAL_ONLY** — Phase 4 sub-class on per-cell drift where
  every drift signal in a list-shaped field reduces to ordering /
  representation noise rather than semantic content change.  Used
  by the Phase 4 comparator to collapse a noisy fan-out into a
  single signal per cell.
- **TRIVIAL_EMPTY** — Phase 4 sub-class for fields that drifted
  only because one side held an empty container (`[]`, `{}`, `""`)
  and the other held `None`, or vice versa.  Treated as no-signal
  in the reconciliation summary; useful for filtering audit noise
  on cells with no real divergence.

## See also

- [`../README.md`](../README.md) — project orientation and quickstart
- [`../ARCHITECTURE.md`](../ARCHITECTURE.md) — the 4-layer design
- [`../AGENTS.md`](../AGENTS.md) — contributor directives

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
  `source_ports` and `source_hostname` BEFORE any rename engages, so UI panes can
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
- **dropped_tier3_sections** — `list[str]` field on `CanonicalIntent`
  populated by parsers when they detect Tier-3 surfaces (firewall,
  NAT, VPN, QoS, routing protocols, PKI) and deliberately don't
  attempt cross-vendor translation. Surfaces to the migrate page's
  Tier-3 banner so operators see what was deliberately skipped.
  See [`CAPABILITIES.md`](CAPABILITIES.md) "Tier 3 — opaque carry".
- **Ship-before-wire** — design pattern in which the canonical schema
  gains a field before any codec parses or renders it. Lets UI and
  pipeline plumbing advance independently of vendor-support breadth.
  The cross-codec invariant is enforced by `_WIRED_UP_BY_CODEC` maps
  in the matching schema-test guard files.
- **Tier 1 / Tier 2 / Tier 3** — canonical-field categorisation.
  Tier 1 = cross-vendor stable, auto-translatable (hostname,
  interfaces, vlans, static_routes, DNS/NTP; plus `timezone` and
  `syslog_servers`, which are Tier-1 by data shape but wired on only a
  subset of codecs — see `docs/CAPABILITIES.md`).  Tier 2 =
  translatable with caveats (SNMP, local_users, lags, dhcp,
  radius, vxlan_vnis, evpn_type5_routes, routing_instances,
  apply_groups).  Tier 3 = detected-but-deliberately-not-translated;
  surfaced via `CanonicalIntent.dropped_tier3_sections`
  (notification-only — never auto-rendered).  See
  [`CAPABILITIES.md`](CAPABILITIES.md) for the full list.

## Codec layer

- **Bidirectional codec** — codec that implements both `parse()` and
  `render()`, allowing it to act as either source or target.
- **Capability matrix** — per-codec `CapabilityMatrix` ClassVar listing
  three triads: `supported` (xpaths that round-trip cleanly),
  `lossy` (with per-entry `LossyPath(reason, severity)`),
  `unsupported` (with per-entry `UnsupportedPath(reason)`).
  No silent unsupported — every gap is declared with rationale.
  Drives the migrate-page Validation panel + Phase 4 reconciliation.
  Reference `netcanon/migration/canonical/intent.py` for the
  `CapabilityMatrix` model itself; each codec's `codec.py` declares
  its instance.
- **Direction** — codec ClassVar declaring its capability; one of
  `bidirectional`, `parse_only`, or `render_only`.
- **INPUT_FORMATS** — codec ClassVar string family (e.g. `cli`,
  `netconf-xml`, `xml`) shown in the target dropdown to disambiguate
  variants of the same vendor (e.g. Cisco IOS-XE NETCONF vs CLI).
- **Primary device class** — the **first** entry in a codec's
  `device_classes` (declared in `netcanon/migration/vendors/<vendor>.yaml`
  and mirrored in its `CapabilityMatrix`).  It is the project's
  authoritative scope declaration for that platform, so the order of
  the list is load-bearing, not cosmetic.  A `firewall`-primary codec
  (`fortigate_cli`, `opnsense`) is one Netcanon translates at the
  L2/L3 layer only, and one that does not front the product — see the
  two-clause scope test in [`AGENTS.md`](../AGENTS.md) § Hard Rules,
  guarded by
  [`tests/unit/migration/test_scope_boundary.py`](../tests/unit/migration/test_scope_boundary.py).
  Distinct from the *set* of device classes, which is only used by the
  cross-device-class compatibility guard.
- **Probe** — `classmethod probe(raw_prefix) -> (confidence, reason) | None`.
  Each codec votes on a candidate input; the orchestrator picks the
  highest-confidence match for source detection.
- **unsupported_rename_categories** — codec ClassVar (`frozenset[str]`)
  enumerating per-pane-override categories where the codec parses or
  renders but doesn't round-trip the entity end-to-end. Drives the
  amber compatibility banner on the rename rail when the codec is
  selected as target. Every bidirectional codec declares it as empty
  EXCEPT OPNsense (`{"snmpv3"}`) and Cisco IOS-XE NETCONF
  (`{"snmpv3", "ports"}` — the stub has no port-name translation).
- **Wire format** — the operator-paste form of a config: CLI
  `show run`, NETCONF XML, OPNsense `config.xml`, MikroTik `/export`,
  and similar.

## Cross-mesh + testing

- **Cross-mesh / full-mesh** — every-source by every-target test
  matrix. `tests/unit/migration/test_cross_mesh_overrides.py`
  exercises every certified bidirectional pair (a 12-codec
  source × target mesh).
- **Drift guard** — meta-test that catches silent coverage shrinkage
  (e.g. `_DIR_TO_CODEC_NAME` missing a fixture directory, or
  `_SOURCE_CAPABLE` missing a bidirectional codec).
- **Real-capture fixture** — third-party operator config under
  `tests/fixtures/real/<vendor>/`. Source of truth for round-trip
  stability assertions.
- **WANTED.md** — `tests/fixtures/real/WANTED.md`; operator-facing
  catalogue of fixtures we'd like to receive (per-vendor gaps,
  feature surfaces, OS versions). Pairs with `RESULTS.md` (what we
  have + certification state) and `NOTICE.md` (provenance +
  attribution).
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
- **Definitions** — vendor YAML files at `netcanon/definitions/library/` describing
  how to log into a given device class.
- **get_collector** — the single mock-point for backup tests. Hard
  Rule: never patch `ConnectHandler` or `paramiko.SSHClient` directly;
  patch this factory instead.
- **Target profile** — hardware-shape definition, one YAML per model
  under `netcanon/definitions/library/target_profiles/`. Drives port
  rename and VLAN/user fit-checks in the UI. A profile can state the
  one **deployment state** its port names describe and carry an
  **evidence grade** (`capture` / `vendor-doc` / `inferred`) for them;
  one that carries no grade has not been checked yet. See
  ARCHITECTURE.md, "Provenance".
- **Model family** — one YAML under
  `netcanon/definitions/library/model_families/`: models that share a
  naming rule, a set of deployment modes and a set of modules. Unlike a
  target profile it lists facts, not names; names are computed for one
  stated deployment. See ARCHITECTURE.md, "Device models and
  inventories".
- **Deployment** — a device as actually deployed: a **mode** (the state
  that decides port names — standalone, VSF, stacked) plus an ordered
  list of members, each a model with its fitted modules. What a request
  declares for the source and the target.
- **Inventory** — what a deployment compiles to: the ordered list of
  ports that exist, each with its real name, role, position and
  evidence grade.
- **Naming rule** — a small pure function beside a vendor's codec that
  renders one port's name from its coordinates. One per naming grammar,
  not per product line.
- **Name-shape translator** — the ordinary port translation: a target
  name derived from the shape of the source name
  (`GigabitEthernet1/0/1` becomes `1/1`), without knowing either
  device model. What positional port mapping replaces for the ports
  it can pair, and what still handles every other name.
- **Positional port mapping** — pairing the ports of two inventories
  by member rank, role and order, instead of translating names by their
  shape. Produces an ordinary `port_rename_map`.
- **Unplaced / off-inventory / displaced** — the ways a used
  source name can be left without a paired target. *Unplaced*: a port
  of the declared source with no position on the target (dropped,
  unless it is a management port). *Off-inventory*: a name the config
  uses that is not a port of the declared source at all. *Displaced*:
  a name nobody decided — one of either kind, or a logical interface —
  that the name-shape translator would have put on a name another
  interface ends on, or on a port of the target, and that was dropped
  instead.
- **Fused** — a target port that more than one source port ended on.
  Positional mapping never produces one; an operator override can.
- **Factory name / labelled port** — RouterOS keeps a port's factory
  name (`ether2`, its hardware identity) beside the name an operator
  gave it (`core-a`). A *labelled port* is one with such a name. It is
  paired by its factory name and goes by the operator's name
  everywhere else. An entry of a rename map NAMES a port; only a
  request that declares the target device can MOVE one onto other
  hardware.
- **Unbound port** — on a RouterOS target, a port that no line of
  its own in the output looks up by its hardware: its name reads as
  another kind of interface (a VLAN, a bridge, a LAG, a loopback), or
  the config has no interface for it and an entry gave it a name.
  Found by reading the output back; the job is `partial` until the
  port has a port of the target, or a name that can carry a line.
- **Landed off-target** — a logical name nobody decided that the
  name-shape translator gave a port-shaped name the declared target
  does not list. Kept, reported, and in need of a decision.
- **Stale next hop** — a static route left naming, as next hop, an
  interface that was renamed or dropped, because the next hop was not
  exactly that interface's name.
- **Capture claim** — a committed real capture plus the exact
  deployment it is of. The only source of a `capture` evidence grade
  for a model family, granted only where a deployment matches exactly.
- **MODULE_VARIANT_PROFILES** — allowlist (`tests/fixtures/module_variants.py`)
  of `{vendor}/{model}` keys whose target profiles ship `modules:`
  declarations. Both unit + integration test tiers import from this
  shared module; the `test_module_variant_allowlist_shared_with_integration_tier`
  CI guard enforces single-source-of-truth across the test pyramid.
- **effective_ports** — `TargetProfile.effective_ports(module_sku)`
  method returning the base `ports` list plus the module's ports
  (if the target profile is module-variant-shaped). The migrate
  page's fit-check uses this to enumerate the operator-selected
  chassis + module combination.

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

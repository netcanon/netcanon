# Canonical layer — orientation guide

Layer 3 of the four-layer migration architecture (see
[`../../../ARCHITECTURE.md`](../../../ARCHITECTURE.md)).  This directory
holds the canonical Intermediate Representation (IR) plus the per-category
rename orchestrators that operate on it.  It sits between Layer 2 (codec
parse / render under `../codecs/`) and Layer 4 (the pipeline orchestrator
in `../../services/migration_pipeline.py`).

If you're adding a new vendor parser, start with
[`../codecs/README.md`](../codecs/README.md).  If you're adding a new
top-level canonical field, follow
[`../../../docs/adding-a-canonical-field.md`](../../../docs/adding-a-canonical-field.md).
This README is for contributors adding a new **rename category** (a sixth
or later per-pane override surface) or wiring a fresh shared transform.

---

## Purpose

Every codec's `parse()` produces a `CanonicalIntent` instance; every
codec's `render()` consumes one.  The canonical layer owns:

* the **shape** of that tree (`intent.py`),
* the **representation-bridging transforms** that codecs run at the end
  of `parse()` to fill in mirror representations (`transforms.py`), and
* the **per-category rename orchestrators** that the pipeline applies
  before render so operator overrides mesh across every (source, target)
  vendor pair without per-pair code (`port_names.py`, `vlan_names.py`,
  `local_user_names.py`, `snmp_names.py`, `snmpv3_user_names.py`).

The pipeline (`../../services/migration_pipeline.py`) calls into this
layer; codecs (`../codecs/`) implement the small per-vendor methods the
orchestrators consume (`classify_port_name`, `format_port_identity`).
Nothing here knows about specific vendors by name — vendor identity
lives entirely in `../codecs/`.

---

## Module layout

**Model**

| File | Role |
|---|---|
| `intent.py` | The pydantic schema for `CanonicalIntent` and its child models (`CanonicalInterface`, `CanonicalVlan`, `CanonicalSNMPv3User`, `CanonicalRoutingInstance`, `CanonicalVxlan`, etc.).  Tier 1 / Tier 2 / Tier 3 fields are grouped with section comments. |

**Shared transforms**

| File | Role |
|---|---|
| `transforms.py` | `project_switchport_to_vlan` (port-centric → VLAN-centric mirror, used by Cisco-family codecs at the end of `parse()`), `project_vlan_to_switchport` (the reverse, with `synthesise_missing` to build interface stanzas when a VLAN-centric source renders into a port-centric target), `project_svi_to_vlan` (synthesises `CanonicalVlan` records from L3 SVI interfaces — `Vlan100`, `irb.100` — when a source-side parser populates the iface but not the corresponding VLAN; added Wave 7c so `arista_eos` and other CLI codecs share the same SVI-fold semantics), and `_natural_port_sort_key` (deterministic operator-natural ordering for synthesis output). |

**Rename orchestrators**

| File | Category | Factory |
|---|---|---|
| `port_names.py` | physical + logical port names | `build_port_rename_transform(source_codec, target_codec, rename_map, strip_unmappable=True)` |
| `vlan_names.py` | VLAN ID rewrite (1-4094 → 1-4094) | `build_vlan_rename_transform(rename_map)` |
| `local_user_names.py` | local user account names | `build_local_user_rename_transform(rename_map)` |
| `snmp_names.py` | SNMPv1 / v2c community string | `build_snmp_community_rename_transform(rename_map)` |
| `snmpv3_user_names.py` | SNMPv3 USM user names | `build_snmpv3_user_rename_transform(rename_map)` |

Each module exposes a `<Category>RenameResult` pydantic model alongside
its factory; the pipeline collects these into a `RenameOutcomes`
container before returning.

**Loader (stub)**

| File | Role |
|---|---|
| `loader.py` | Phase-0.5 placeholder for the libyang context loader.  Both `get_libyang_context()` and `validate_against_canonical()` raise `NotImplementedError` with a pointer to the roadmap.  Do not call from production code. |

---

## The orchestrator pattern

Every rename category implements the same factory contract.  Worked
example — `port_names.py`:

```python
from netcanon.migration.canonical.port_names import build_port_rename_transform

transform, result = build_port_rename_transform(
    source_codec=src,
    target_codec=tgt,
    rename_map={"GigabitEthernet1/0/1": "1/1",   # explicit
                "GigabitEthernet1/0/2": None},   # drop
    strip_unmappable=True,
)
intent = transform(intent)         # mutates and returns the tree
print(result.applied, result.warnings, result.dropped)
```

The `port_names` factory is the heaviest case (it brokers between two
codecs via `classify_port_name` / `format_port_identity`); the four
list-surface orchestrators (`vlan_names`, `local_user_names`,
`snmp_names`, `snmpv3_user_names`) take just `rename_map` because their
domains are vendor-agnostic (integers, opaque strings).

**Sentinel semantics (uniform across all five categories):**

| `rename_map` value | Meaning |
|---|---|
| `None` (the parameter itself) | Orchestrator is a no-op; pipeline still runs, no rewrites happen. |
| `{}` (empty dict) | Heuristic / auto-derive path runs.  `port_names` engages its full classify-then-format mesh; the simpler categories stay no-op. |
| `{src: tgt}` with non-empty `tgt` | Explicit rewrite — operator override wins over heuristics. |
| `{src: None}` | Drop the entry entirely.  The orchestrator strips every reference from the canonical tree (port names cascade through `interfaces`, `vlans[].tagged_ports`, `lags[].members`, `static_routes[].interface`, `dhcp_servers[].interface`; VLANs cascade through interface switchport state; etc.). |

**Output contract:**

* `transform: Callable[[CanonicalIntent], CanonicalIntent]` — fits the
  `run_plan(transforms=...)` signature.  May mutate in place; always
  returns the (possibly same) intent.
* `result: <Category>RenameResult` — pydantic model with `applied`,
  `warnings`, `dropped` (and category-specific extras).  The factory
  closes over the result so the caller can read it after pipeline run.

**Purity expectations:** the transform never reaches outside the intent
tree.  No filesystem I/O, no codec re-parse, no network calls.
Side-effect surfaces (collisions, fit-check warnings, dropped entries)
flow exclusively through the result model — never through exceptions or
logger-only channels.

---

## Adding a new rename category

A "category" is a sixth (or later) per-pane override surface in the
migration UI.  The repo currently ships five (ports, vlans,
local_users, snmp_community, snmpv3_users); future candidates
(NTP / DNS / syslog / RADIUS / SNMP trap hosts) follow the same shape.

Concrete checklist:

1. **New module.**  Add `<category>_names.py` next to the existing five.
   Copy the closest sibling — `snmp_names.py` for a single-scalar
   surface, `local_user_names.py` for a list-of-named-records surface,
   `port_names.py` only if the category needs cross-codec semantic
   bridging (rare).
2. **Implement the factory.**  Match the contract above:
   `build_<category>_rename_transform(rename_map) → (transform, result)`.
   Define a `<Category>RenameResult` pydantic model with at minimum
   `applied`, `warnings`, `dropped`.
3. **Wire onto `run_plan_with_overrides`.**  Hard rule (see AGENTS.md):
   never change the signatures of `run_plan` or `run_plan_with_rename`
   — they're frozen.  Add the new category to the override-dict
   handling inside `run_plan_with_overrides` in
   `../../services/migration_pipeline.py` and import the new factory
   alongside the existing five.  Update the module's top-of-file
   docstring "Per-pane override categories" listing.
4. **Cross-mesh test coverage.**  Extend `_SOURCE_CAPABLE` /
   `_TARGET_CAPABLE` lists in
   `tests/unit/migration/test_cross_mesh_overrides.py` to include
   every codec that supports the new category (parse + render).
   Codecs that don't yet round-trip the new field declare it in
   their `unsupported_rename_categories` ClassVar so the UI shows
   the amber compatibility banner.
5. **UI surface.**  Add a rename rail in `netcanon/templates/migrate.html`
   and a per-pane endpoint in `netcanon/api/routes/migration.py`
   (`POST /api/v1/migration/plan/<category>`).  Every interactive
   element needs a `data-testid`; document each in
   `tests/testid_reference.md` in the same commit.
6. **Capture-first plumbing.**  Extend the capture-first transform in
   `migration_pipeline.py` to populate `source_<category>` on the
   captured `CanonicalIntent` so the rename modal can pre-populate
   suggestions from the source side.
7. **Tests at every layer.**  Unit tests per orchestrator under
   `tests/unit/migration/test_<category>_names.py`; integration tests
   per route under `tests/integration/test_ui_routes.py` (or sibling);
   e2e Playwright coverage of the new rename rail.

If the new category needs canonical-schema fields that don't exist
yet, follow `../../../docs/adding-a-canonical-field.md` first — the
rename orchestrator goes in afterward.

---

## Schema tiers

`intent.py` partitions canonical fields into three tiers, marked by
section comments.  The tier governs the pipeline's validation banner
and the codec's `CapabilityMatrix` declarations:

* **Tier 1 — auto-translatable.**  Every vendor models the concept;
  cross-vendor semantics are stable.  Fields: `hostname`, `domain`,
  `dns_servers`, `ntp_servers`, `timezone`, `syslog_servers`,
  `interfaces`, `vlans`, `static_routes`.  Codecs that don't yet wire
  a Tier 1 field are bugs, not gaps.
* **Tier 2 — auto-translate with review.**  Common enough to model;
  vendor mappings are partially lossy.  Fields: `dhcp_servers`,
  `snmp` (community + v3 users), `lags`, `local_users`,
  `radius_servers`, plus the ship-before-wire EVPN-VXLAN and VRF
  schemas (`vxlan_vnis`, `evpn_type5_routes`, `routing_instances`,
  per-interface `vrf`).  The UI surfaces a "MANUAL REVIEW REQUIRED"
  banner; codecs declare unsupported entries in their
  `CapabilityMatrix`.
* **Tier 3 — informational only.**  `raw_sections: dict[str, str]`
  carries firewall rules, NAT, VPN, routing-protocol stanzas through
  for display.  Never auto-rendered into a target dialect.

The class docstring on `CanonicalIntent` enumerates the per-tier scope.
Adding a field to a tier is a schema change — touch
`adding-a-canonical-field.md` and confirm every codec's
`CapabilityMatrix` declares the new xpath (`supported`, `lossy`, or
`unsupported`).

---

## Ship-before-wire

A canonical field can land in `intent.py` *before* any codec parses or
renders it.  This decouples UI / pipeline plumbing from vendor support
breadth — the schema, capability declarations, and unsupported-path
banner advance independently of per-codec parser work.

The pattern:

1. Add the pydantic model + the field on `CanonicalIntent`, with a
   docstring listing the per-vendor grammar shape (see
   `CanonicalVxlan`, `CanonicalEvpnType5Route`, `CanonicalRoutingInstance`
   for worked examples).
2. Every codec's `CapabilityMatrix` declares the new xpath under
   `unsupported` in the same commit.  The UI's unsupported-path
   banner immediately reports the gap to operators.
3. Subsequent commits demote the entry to `supported` (or `lossy`)
   per codec as parse + render land.  Each demotion is a self-contained
   commit with its own wire-through tests.

EVPN-VXLAN is the canonical reference (one schema commit, then per-codec
wiring on Arista / NX-OS / Junos as they land).  MTU is the wire-through
reference for a Tier 2 numeric field (see
[`../../../docs/adding-a-canonical-field.md`](../../../docs/adding-a-canonical-field.md)).

---

## See also

* [`../codecs/README.md`](../codecs/README.md) — codec authorship guide (Layer 2 sibling)
* [`../../services/migration_pipeline.py`](../../services/migration_pipeline.py) module docstring — frozen pipeline signatures + per-pane override surface
* [`../../../ARCHITECTURE.md`](../../../ARCHITECTURE.md) — the four-layer architecture (this layer is Layer 3)
* [`../../../docs/adding-a-canonical-field.md`](../../../docs/adding-a-canonical-field.md) — worked example: MTU wire-through across every codec
* [`../../../docs/glossary.md`](../../../docs/glossary.md) — project-jargon reference (canonical, codec, mesh, ship-before-wire)

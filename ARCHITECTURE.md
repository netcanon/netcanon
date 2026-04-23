# NetConfig — Architecture

This is the conceptual map.  For day-to-day contributor rules see
[`CLAUDE.md`](CLAUDE.md); for the active roadmap and backlog see
[`translator-plans.txt`](translator-plans.txt).

---

## Two concerns, one app

NetConfig is a FastAPI application that co-hosts two independent jobs:

```
            ┌────────────────────────────────────────────────────┐
            │                  FastAPI app                        │
            │  (netconfig/main.py, shared by web + desktop)      │
            └──────────────┬─────────────────────────┬────────────┘
                           │                         │
                  ┌────────▼────────┐       ┌────────▼────────┐
                  │    BACKUP       │       │   MIGRATION     │
                  │                 │       │                 │
                  │  devices → SSH  │       │  raw config →   │
                  │   → configs/    │       │  CanonicalIntent│
                  │                 │       │  → raw config   │
                  │                 │       │   (other vendor)│
                  └─────────────────┘       └─────────────────┘
```

**Backup** (`netconfig/collectors/`, `netconfig/api/routes/backups.py`):
fetches the current running configuration from devices over a
pluggable transport (SSH via Netmiko / NETCONF / REST), validates
against a device-class schema, stores in `configs/<host>.<ext>`.
Scheduled or on-demand.  Mocked in tests at a single factory
(`get_collector`).

**Migration** (`netconfig/migration/`): the subject of most of this
document.  Takes a stored backup, parses it into a shared intent tree,
and renders that tree in another vendor's native format.

The rest of this document is about the migration layer.  The backup
layer is architecturally simpler — see
[`netconfig/collectors/README.md`](netconfig/collectors/README.md).

---

## Migration — four-layer model

The migration pipeline decouples four concerns that tend to get
conflated in vendor-specific tooling:

```
┌─────────────────────────┐  ┌──────────────────────────┐
│  Vendor Definition      │  │  Canonical Intent Model  │
│  (what device is this?) │  │  (what is the tree?)     │
└──────────┬──────────────┘  └─────────────┬────────────┘
           │                                │
           ▼                                ▼
┌─────────────────────────┐  ┌──────────────────────────┐
│  Format Codec           │─▶│  Schema Validator        │
│  (CLI/XML/JSON ↔ tree)  │  │  (strictness policy)     │
└──────────┬──────────────┘  └──────────────────────────┘
           │
           ▼
┌─────────────────────────┐
│  Transport              │
│  (how to get bytes      │
│   in/out of device)     │
└─────────────────────────┘
```

### Layer 1 — Vendor Definition

**Where:** `definitions/*.yaml`
**What:** A small declarative struct per vendor/device family:
`{name, device_classes, cli_prompt_hints, default_timeout}`.  No code.

**Purpose:**
- UX grouping in the migration picker ("Show me all FortiGate codecs")
- Default `device_class` declaration
- Shared taxonomy anchor with the backup layer's `type_key` field

**Layered definitions (backup side).**  The `DeviceDefinition` schema
in `netconfig/definitions/schema.py` supports two-level lookup:

* **Family-base** entries (`os_version` and `model` both unset) form
  the default `dict[type_key, DeviceDefinition]` returned by
  `DefinitionLoader.load_all()`.  Existing callers that don't know
  about variants hit exactly these entries.
* **Overlays** (entries with `os_version` or `model` set) live in a
  parallel variant registry reachable via `DefinitionLoader.resolve(
  type_key, os_version=None, model=None)`.  The resolver does
  longest-match: exact triple → version-pin → model-pin → family base.

Operators pin the axes they know by setting `os_version` and/or
`model` on their `DeviceProfile`.  The backup pipeline passes the
pins through `DeviceTarget`; unpinned targets fall back to the
family base automatically.  Probe-driven auto-detection (future
commit) writes back to `DeviceProfile.detected_facts`, which operators
see read-only in the device edit panel so they can reconcile their
pins against what the device actually reports.

See [`definitions/README.md`](definitions/README.md) for the full
authoring guide.

### Layer 2 — Format Codec

**Where:** `netconfig/migration/codecs/<vendor>/codec.py`
**What:** Translates between a **wire format** and the **canonical
intent tree**.  Every codec declares:

```python
vendor:           str      # points at a Vendor YAML
format:           str      # machine-readable format tag
direction:        enum     # parse_only | render_only | bidirectional
canonical_model:  str      # which CIM it speaks
capability_matrix: ...     # what xpaths it can round-trip
certainty:        enum     # certified | best_effort | experimental
```

**Key design choices:**

* **Direction is independent of the vendor.** Many CLI parsers are
  `parse_only` because rendering clean CLI is harder than parsing it.
  The migration UI shows `parse_only` codecs only as source options,
  `render_only` codecs only as target options.
* **Multiple codecs can share a vendor.** `cisco_iosxe` (NETCONF
  OpenConfig) and `cisco_iosxe_cli` (`show running-config` parser) are
  both `vendor_id="cisco_iosxe"` but speak different wire formats.
* **Auto-registration.** Drop a subpackage under
  `netconfig/migration/codecs/`, decorate the class with `@register`,
  and `pkgutil` auto-discovery at app startup picks it up — no manual
  wiring.

For authoring instructions see
[`netconfig/migration/codecs/README.md`](netconfig/migration/codecs/README.md).

### Layer 3 — Canonical Intent Model (CIM)

**Where:** `netconfig/migration/canonical/intent.py`
**What:** The shared tree shape codecs parse into and render out of.

The current CIM is a lightweight OpenConfig-inspired pydantic model
with fields tiered by semantic stability:

| Tier | Meaning | Examples |
|---|---|---|
| **Tier 1** | Every vendor models it, stable cross-vendor semantics | `hostname`, `dns_servers`, `ntp_servers`, `interfaces[]` with ipv4_addresses, `vlans[]` with tagged/untagged port lists, `static_routes[]` |
| **Tier 2** | Common enough to model, vendor mappings are lossy | `snmp`, `lags[]`, `local_users[]`, `dhcp_servers[]`, `radius_servers[]`, per-port `mtu` |
| **Tier 3** | Opaque carry-through, never auto-rendered | `raw_sections[]` — firewall rules, PKI chains, QoS policies, vendor-specific |

**The design bet:** most cross-vendor translation value lives in
Tiers 1 + 2.  Tier 3 features get preserved as opaque blobs so they
survive the round-trip but don't have to be modelled end-to-end.

**Shared transforms:** `netconfig/migration/canonical/transforms.py`
holds post-parse passes that bridge representation differences (e.g.
`project_switchport_to_vlan` converts Cisco's per-port VLAN
membership to Aruba's VLAN-centric membership lists).  These run
after the codec's `parse()` so the canonical tree is complete
regardless of which vendor originated it.

### Layer 4 — Transport

**Where:** `netconfig/collectors/` (currently only the backup side
exercises transport layer; migration is file-input for now)
**What:** How bytes get in and out of a device.  SSH via Netmiko,
NETCONF, REST APIs — pluggable per vendor.

Migration's Phase 2+ deploy story will push rendered configs back to
devices via this layer; for now the flow is file → codec → file.

---

## Certification model

Every codec declares `certainty` — a promise about how battle-tested
it is:

| Level | Criterion | Deploy-ready? |
|---|---|---|
| `experimental` | Synthetic fixtures only | No — UI shows red banner |
| `best_effort` | ≥1 real fixture round-trips clean | Staging only — UI shows yellow banner |
| `certified` | ≥3 real captures from ≥2 OS versions, all round-trip stable | Yes — UI shows green chip |

The bar is intentionally strict.  Per-codec status is tracked in
[`tests/fixtures/real/RESULTS.md`](tests/fixtures/real/RESULTS.md) —
consult it as the source of truth, not this doc (this paragraph goes
stale as codecs promote).

---

## Pipeline orchestration

**Where:** `netconfig/services/migration_pipeline.py`
**What:** A single public function `run_plan(source_codec, target_codec,
raw, transforms=...)` that drives:

```
raw_text
  → source_codec.parse(raw_text)         # returns CanonicalIntent
  → apply transforms (zero or more)
  → validate against schema + capability matrix
  → target_codec.render(tree)            # returns raw_text
```

**Critical invariant:** the signatures of pipeline-stage functions in
`migration_pipeline.py` **must never change**.  Dozens of tests and
API routes depend on the exact shape.  Later phases add NEW public
functions (e.g. `plan_with_deploy`, `plan_with_diff`); existing
stages stay frozen.  See the module docstring.

---

## Auto-detection

**Where:** `netconfig/services/migration_detect.py` + per-codec `probe()`

The migration UI can auto-propose the right source codec when given
raw config text.  Each codec's `probe(raw_prefix)` returns
`(confidence, reason)` or `None`; the detector walks the registry and
returns a ranked list.  Structural markers that discriminate vendors:
`! J####A Configuration Editor` (Aruba), `# ... by RouterOS` (MikroTik),
`<opnsense>` root element, `config system global` (FortiOS), etc.

---

## Target profiles (hardware-aware rename-modal metadata)

**Where:** `definitions/target_profiles/*.yaml` +
`netconfig/migration/target_profiles.py`
**What:** Declarative descriptions of a target device's port
inventory — vendor, model, device class, stacking mode,
chassis-fixed ports + optional swappable-module variants, LAG
capacity.  Loaded from YAML at startup; never modified at runtime.

**Purpose:** drive the Tier-3 **rename modal** in `/migrate`:

* Populate the per-row target-name dropdown with the profile's
  valid port ids (so a Cat 9300-48P offers `GigabitEthernet1/0/1`
  … `1/0/48` + the selected uplink module, not free-form text).
* Drive the hardware fit-check banner (source vs. target per-kind
  capacity comparison).
* Drive the three-stage `vendor → model → module` selector cascade.

Profiles are **optional** — leaving the target-profile dropdown
empty falls back to Tier-2 free-form input (the codec still runs,
no dropdown validation).  The `opnsense/Generic` profile with
``ports: []`` is an explicit opt-out for bring-your-own-hardware
cases.

### Two shapes: legacy vs. module-variant

**Legacy** (fixed hardware — 2930F, C9500, fixed-port firewalls):

```yaml
vendor: aruba_aoss
model: 2930F-48G
ports:
  - {range: "1/1-1/48", kind: physical, speed: gig}
  - {range: "1/A1-1/A4", kind: uplink, speed: 10gig, sfp: true}
lags: {max: 24, prefix: Trk}
```

**Module-variant** (chassis + swappable uplink module — Cat 9300
NM slot, Aruba 3810M expansion slot):

```yaml
vendor: cisco_iosxe
model: C9300-48P
ports:                              # chassis-fixed
  - {range: "GigabitEthernet1/0/1-48", kind: physical, speed: gig, poe: true}
  - {id: "GigabitEthernet0/0", kind: mgmt, speed: gig}
modules:
  NM-8X:
    description: "8x 10G SFP+"
    ports:
      - {range: "TenGigabitEthernet1/1/1-8", kind: uplink, speed: 10gig, sfp: true}
  NM-2Q:
    description: "2x 40G QSFP+"
    ports:
      - {range: "FortyGigabitEthernet1/1/1-2", kind: uplink, speed: 40gig, sfp: true}
```

Modules are **additive**: `effective_ports(sku) = chassis_ports +
modules[sku].ports`.  The UI's third-stage dropdown enumerates
declared SKUs; operator picks the module they have installed and
the dropdown options reconfigure.  `MODULE_VARIANT_PROFILES`
allowlists in
[`tests/unit/migration/test_target_profile_shipped.py`](tests/unit/migration/test_target_profile_shipped.py)
and [`tests/integration/test_migration_target_profiles_api.py`](tests/integration/test_migration_target_profiles_api.py)
guard against silent drift — a profile listed there must actually
declare `modules:`, and a legacy profile must keep `modules: {}`.

### Relationship to backup-side device definitions

The two subsystems share a vendor slug (`cisco_iosxe`,
`aruba_aoss`, etc.) but not a schema.  Backup definitions describe
**how to fetch bytes** (`prompts.trailing`, paging, netmiko
device_type); target profiles describe **what port ids exist on
the target**.  No automatic cross-link today; a future `PlatformKey`
shared type may unify on `(vendor, os_family)` — see
[`translator-plans.txt`](translator-plans.txt).

See [`definitions/README.md`](definitions/README.md) for full
schema + authoring guide;
[`netconfig/migration/target_profiles.py`](netconfig/migration/target_profiles.py)
for the loader + accessor implementation.

---

## Template organisation

Jinja2 templates live in `netconfig/templates/`.  The base layout is
`base.html`; each page is an extending template.

**Large page templates split into partials.**  `migrate.html` and
`base.html` both use the `{% include "_partials/<name>.js" %}` pattern
to factor long `<script>` blocks out into reusable partial files:

```
netconfig/templates/
├── migrate.html              # ~1,500 LOC — outer HTML + script
├── base.html                 #   ~520 LOC — outer chrome + global JS
└── _partials/
    ├── classify.js           # shared _guessKind / _looksLikeUplink
    ├── config-viewer.js      # modal viewer + search (base.html)
    ├── fit-check.js          # hardware-capacity banner (migrate.html)
    ├── job-progress.js       # floating job widget (base.html)
    ├── rename-apply.js       # rename-modal apply flow + drag handlers
    │                         #   + vendor/model/module selector wiring
    ├── rename-panel.js       # rename-modal preview + summary
    └── rename-table.js       # rename-modal per-kind table renderer
```

**Why include-splice rather than ES-modules?** The templates embed
inline `<script>` blocks that share lexical scope with the rest of the
page's client JS (state vars like `_lastJob`, `_renameUserMap`, and
cross-function references).  Jinja `{% include %}` splices the partial
verbatim into that scope at render time — no module boundary to cross,
no export/import plumbing, no build step.  Downside: the partials
aren't unit-testable in isolation; e2e tests via `data-testid`
selectors are the safety net.

**Selector discipline** (CLAUDE.md hard rule): every interactive
element in every template — including content generated inside
partials — carries a `data-testid` attribute.  The full inventory
lives in [`tests/testid_reference.md`](tests/testid_reference.md).

---

## Test architecture

Four layers, each with specific isolation guarantees:

| Layer | Path | Mocking | Runtime |
|---|---|---|---|
| Unit | `tests/unit/` | None — pure functions | <1s per file |
| Integration | `tests/integration/` | `get_collector` patched in TestClient fixture | <1s per file |
| E2E | `tests/e2e/` | `get_collector` patched for session's live Uvicorn | ~30s full sweep |
| Desktop | `tests/desktop/` | PySide6 + pystray fully mocked via sys.modules | <1s per file |

**Real-capture validation** lives at `tests/unit/migration/test_real_captures.py`.
It auto-discovers fixtures under `tests/fixtures/real/<vendor>/`,
runs parse + round-trip + determinism assertions, and prints
per-fixture coverage metrics.  The harness is what gates codec
promotion to `certified`.

Mocking single entry point: **SSH collection is mocked at
`netconfig.api.routes.backups.get_collector`, never at `ConnectHandler`
or `paramiko.SSHClient` directly** (see CLAUDE.md hard rule).

---

## Evolution roadmap

For the active backlog see [`translator-plans.txt`](translator-plans.txt)
(dense, grep-friendly, opens with a TL;DR).  Big structural pieces
that have shipped:

- **Phase 0** — codec scaffold + mock adapter (`run_plan`, capability matrix)
- **Phase 0.5** — canonical intent model + pluggable CIMs
- **Phase 1** — 5 real codecs (Cisco NETCONF + CLI, Aruba AOS-S, OPNsense, MikroTik, FortiGate)
- **R5** — auto-detection probe
- **R6/7** — real-capture validation harness + fixture corpus
- **Tier 2 wire-throughs** — SNMP, LAGs, local_users, DHCP pools, RADIUS, MTU

What's queued:
- Fixture hunting to promote more codecs toward `certified`
- Fidelity polish bucket (VRFs, STP globals, PKI chains → Tier 3)
- Deploy phase (transport layer wiring for migration output push)
- Additional canonical models (firewall-specific, wireless-specific CIMs)

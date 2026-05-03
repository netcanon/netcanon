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
| **Tier 2 (ship-before-wire)** | Schema shipped ahead of any codec populating it; DC codecs declare the xpath under `unsupported` so the UI banner surfaces the gap | `vxlan_vnis[]` (VLAN↔VNI mappings), `evpn_type5_routes[]` (BGP-EVPN IP-prefix advertisements), `routing_instances[]` + per-interface `vrf` (VRF / routing-instance declarations) |
| **Tier 3** | Opaque carry-through, never auto-rendered | `raw_sections[]` — firewall rules, PKI chains, QoS policies, vendor-specific |

**The design bet:** most cross-vendor translation value lives in
Tiers 1 + 2.  Tier 3 features get preserved as opaque blobs so they
survive the round-trip but don't have to be modelled end-to-end.

**Ship-before-wire** is the pattern for features whose canonical
shape we're confident about but whose codec implementations will
land incrementally.  The schema ships with `Unsupported` capability-
matrix entries on every relevant codec; each codec-wiring commit
demotes the entry (to `supported` or `lossy`) as parse+render land.
EVPN-VXLAN is the reference case: `CanonicalVxlan` + `CanonicalEvpnType5Route`
landed in a single commit ahead of any Arista / Junos / NX-OS
wire-up, letting the UI report "VXLAN detected but not translated"
instead of silently dropping it.

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

## Per-pane overrides (Tier-3 rename modal)

**Where:** `run_plan_with_overrides` in
`netconfig/services/migration_pipeline.py` +
`netconfig/migration/canonical/{port_names,vlan_names,local_user_names,snmp_names}.py`
+ `netconfig/api/routes/migration.py` (per-pane POST endpoints) +
the left-rail category nav in `netconfig/templates/migrate.html`
with per-category partials under `_partials/`.

**What:** The Tier-3 rename modal lets operators override the
auto-heuristic for individual canonical categories without
leaving the translate workflow.  Each category (Ports, VLANs,
Local Users, SNMP community today; future SNMP trap-hosts /
RADIUS) has:

1. **An orchestrator** under `netconfig/migration/canonical/`
   that walks the canonical tree and applies a caller-supplied
   override map.  Returns a result struct with `applied`,
   `dropped`, and `warnings` lists so the UI can show exactly
   what happened.
2. **A per-pane API endpoint** — `POST /api/v1/migration/plan/ports`,
   `POST /api/v1/migration/plan/vlans`,
   `POST /api/v1/migration/plan/local_users`,
   `POST /api/v1/migration/plan/snmp` — that accepts only
   its category's override map and delegates to
   `run_plan_with_overrides` with the other categories' maps
   defaulted to `None`.
3. **A rail button + category pane** in the modal UI.  Panes are
   mutually exclusive (one visible at a time); the preview on
   the right stays cross-category.

**Growth-safe engine:** `run_plan_with_overrides` is the one
function new per-pane categories extend.  New parameters go there
as optional maps defaulting to `None`; `run_plan` and
`run_plan_with_rename` signatures stay frozen.  Adding a new
category follows the established three-step recipe (proven five
times over: ports → vlans → local_users → snmp_community →
snmpv3_users): orchestrator module → wire into
`run_plan_with_overrides` under a None-vs-dict sentinel guard →
add endpoint + rail button + pane partial.  Each new category
also extends the capture transform if the UI pane needs to
enumerate source-tree entities (VLAN IDs, usernames, SNMP
community, SNMPv3 user names, etc.).

**Scalar vs list canonical surfaces:** ports / VLANs / local_users
are list-like (many rows per pane, collision detection, merge
semantics).  SNMP community is scalar — one string per canonical
tree — so its pane renders a single-row table for visual parity
with the list-oriented siblings and collision detection
definitionally returns zero.  Future categories in either shape
class fit the same recipe; the map shape is uniformly
`dict[T, T | None] | None` even when T is effectively singleton.

**Sentinel semantics (all override maps):**

* `None` — don't engage the category's transform at all (legacy
  behaviour).
* `{}` — engage with auto-heuristic only.  The UI sends this on
  first translate to turn the rename pipeline on without yet
  specifying overrides.
* `{src: tgt, ...}` — engage with explicit per-entry overrides.
  Values may include `None` to drop.

**Cross-category ordering:** port rename runs BEFORE VLAN rename
in `run_plan_with_overrides` so port-name rewrites don't race
with VLAN-ID references changing underneath them.  Current order
is ports → vlans → local_users → snmp_community → snmpv3_users;
the last four are independent of each other (VLANs don't
reference users, users don't reference SNMP, SNMP doesn't
reference ports/VLANs, SNMPv3 users are orthogonal to v1/v2c
community) so only the ports-first constraint is load-bearing.
Adding a future category requires deciding its order relative to
the existing transforms; document the choice in both
`run_plan_with_overrides` and the orchestrator module.

**localStorage ack persistence (UI):** operator overrides are
persisted under
`netconfig.rename-ack.v1:<source_codec>:<target_codec>:<hostname>`.
Moving to a different device (different hostname), different
codec pair, or pressing Reset-all clears or scopes away saved
state.  Version segments for source/target are omitted until
parsers start populating `CanonicalIntent.source_version`.

**Source-shape capture:** `run_plan_with_overrides` injects a
capture-first transform that populates `MigrationJob.source_vlans`,
`source_local_users`, `source_snmp_community`, and
`source_hostname` from the post-parse, pre-transform tree.  This
is load-bearing for the VLAN / local-users / SNMP panes (they
have no "auto-rewritten" rows to fall back on if the operator
hasn't already sent overrides) and for the localStorage key
(hostname).

**Target-codec compatibility banners:** each codec exposes
`unsupported_rename_categories: frozenset[str]` listing per-pane
categories it can't round-trip.  The rename modal surfaces an
amber warning on the affected pane when the operator's active
target is in the declaring set — prevents the ghost-success bug
where rename overrides apply to the canonical tree but vanish
from rendered output.

**Current state:** every shipped bidirectional codec has the
attribute empty (post-Option-A).  Earlier `OPNsenseCodec` and
`FortiGateCLICodec` declared `{"local_users"}` under an incorrect
assumption that those codecs kept user blocks in `raw_sections`;
verified otherwise (both round-trip `CanonicalLocalUser` end-to-end
and always did — see `test_local_users_wire_through.py`).  The
attribute stays wired as an extension point — the next codec
that genuinely ships without a Tier-2 round-trip for a category
declares it and gets the banner for free.

**Per-pane capacity fit-checks:** each pane renders its own
fit-check banner (separate from the ports fit-check in
`_partials/fit-check.js`).  Banner state is a pure function of
the active target profile's capacity fields
(`TargetProfile.max_vlans`, `TargetProfile.max_local_users`) and
the corresponding source count — no cross-pane coupling.  Hidden
when the profile doesn't declare the limit, same discipline as
the ports fit-check's "no profile = no banner" rule.

See [`netconfig/migration/codecs/README.md`](netconfig/migration/codecs/README.md)
for the codec-authorship side of this (every codec must expose
`classify_port_name` / `format_port_identity` to participate in
the port-rename mesh; VLAN orchestrator is codec-agnostic).

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

## Cross-cutting render-time policies

Some concerns are vendor-agnostic and live in shared sibling modules
at the migration-package root rather than per-codec.  Each policy is
called by multiple codecs to keep cross-vendor behaviour consistent:

**Hash-portability policy** (`netconfig/migration/_user_secrets.py`).
When a render path consumes `CanonicalLocalUser.hashed_password`, it
calls `is_migratable(hashed, target_vendor)` to decide whether the
target's CLI accepts that hash form.  Cross-vendor mismatches (e.g.
Cisco type-9 scrypt → Junos, OPNsense bcrypt → Arista) emit a
`format_review_comment(...)` line in the appropriate per-codec
syntax instead of leaking the hash literal as plaintext.  Per-target
accepted-algorithm sets live in `_TARGET_ACCEPTS[<vendor>]`.

**Naming-value sanitisation** (`netconfig/migration/_naming.py`).
Some target CLI parsers (Arista EOS, Cisco IOS-XE) reject whitespace
in hostname / domain / VRF-name tokens; renderers call
`sanitise_hostname()` so the wire form round-trips through the
target's own parser.  Source state preserved on canonical, sanitised
only at the wire boundary.

**Switchport ↔ VLAN projection**
(`netconfig/migration/canonical/transforms.py`).  The
canonical model carries L2 membership both ways: per-iface
`switchport_mode`/`access_vlan`/`trunk_allowed_vlans` AND per-vlan
`tagged_ports`/`untagged_ports`.  Codecs whose parse populates only
one direction call `project_switchport_to_vlan(intent)` (or the
inverse `project_vlan_to_switchport`) as a post-pass for round-trip
stability.  The forward helper guards the Junos `vlan members all`
sentinel (`range(1,4095)`) to avoid synthesising 4094 phantom VLANs.

**`kind=mgmt` cascade**.  Source-side codecs promote
`CanonicalInterface.kind` from `physical` to `mgmt` when context
indicates an out-of-band management interface (e.g. cisco_iosxe_cli
parser detects `Mgmt-vrf` binding on a `GigabitEthernet0/0`).
Target codecs route `kind=mgmt` interfaces through dedicated emit
paths: Aruba `oobm` block, FortiGate `mgmt1` port, OPNsense
`opt_mgmt` zone, Junos routing-instance binding.  Honours the
canonical `kind` field; never emit a regular physical port for
mgmt-classified interfaces.

When adding a new codec, audit each policy and decide whether to
opt in.  Most cases: opt in.  Re-implementing the policy locally is
the wrong call — see `netconfig/migration/codecs/README.md`
"Cross-codec shared utilities" section.

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

### Per-category capacity limits

Profiles may declare `max_vlans` and/or `max_local_users` to
drive per-pane fit-check banners in the rename modal (VLAN pane +
local-users pane each render their own banner when the active
profile declares the corresponding limit).  Both fields are
optional — `None` means "no limit known / declared" and hides the
banner for that pane.  Same discipline as the existing ports
fit-check: no profile selected = no banner; no limit on a profile
= no banner for that category.

Values should come from vendor datasheets and be hedged
conservatively — silently-wrong limits are worse than missing
ones because they let bad migrations look safe.  Every shipped
profile currently declares `max_vlans`; per-vendor rationale:

* Aruba 2930F family — 2048 (AOS-S 16.11 datasheet).
* Aruba 3810M / 6300M + Cisco C9300 / C9500 — 4094 (enforced
  protocol ceiling).
* MikroTik RouterOS + OPNsense — 4094 (protocol ceiling;
  software-VLAN stacks have no hardware cap).
* FortiGate 40F / 60F — 512; 100E — 1024 (FortiOS 7.x
  "Maximum Values Table").

`max_local_users` is declared only where the datasheet number is
small enough to matter and the codec actually round-trips users
(Aruba 2930F family = 16; 6300M = 64).  OPNsense + FortiGate
profiles leave it unset because their codecs list `local_users`
in `unsupported_rename_categories` — the compatibility banner
handles that UX.  MikroTik leaves it unset because RouterOS's
user count is software-unbounded.  Shipped-profile lock-in tests
in
[`tests/unit/migration/test_target_profile_shipped.py`](tests/unit/migration/test_target_profile_shipped.py)
guard against drift on both fields.

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

### The `/definitions` browsing page

`/definitions` is the single browsing view for everything
NetConfig knows about — four sections in one page:

1. **Backup-side device definitions** (`section-device-definitions`):
   the legacy table — what vendor YAMLs the backup layer
   recognises (`Cisco`, `Fortigate`, etc.).  Excludes overlays so
   each `type_key` appears exactly once.
2. **Version / model overlays** (`section-overlays`, conditional):
   the extra variants (`Cisco 17.12`) that the loader keeps in
   its `_variants` registry but filters out of `load_all()`.
   Explains "loaded N but showed N-M" on the startup log.
3. **Migration target profiles** (`section-target-profiles`):
   the 50+ hardware models with per-model port layouts, module
   variants (NM-8X, NM-2Q, JL084A, …), stacking caps, VLAN/user
   limits.  Previously only reachable through the Tier-3
   rename-modal dropdown — now browsable with vendor grouping +
   live filter.
4. **Migration vendors + codec capabilities** (`section-vendors`):
   each of the 8 vendors with its registered codecs, direction
   (`parse_only` / `bidirectional`), certainty tier (`certified`
   / `best_effort` / `experimental`), and per-codec capability-
   matrix counts (supported / lossy / unsupported xpaths).

Template: [`netconfig/templates/definitions.html`](netconfig/templates/definitions.html).
Route: [`netconfig/api/routes/ui.py::definitions_page`](netconfig/api/routes/ui.py).
Collapsible panels use native `<details>` / `<summary>` — zero
JS, browser-built-in keyboard + screen-reader behaviour.
The profile filter is a pure DOM hide/show on a pre-lowercased
`data-haystack` attribute set server-side (vendor + model +
display_name concatenated).  See
[`tests/testid_reference.md`](tests/testid_reference.md) for
the full testid inventory (one `section-*` testid per
container, plus per-row, per-module, per-codec testids).

---

## Template organisation

Jinja2 templates live in `netconfig/templates/`.  The base layout is
`base.html`; each page is an extending template.

**Large page templates split into partials.**  `migrate.html` and
`base.html` both use the `{% include "_partials/<name>.js" %}` pattern
to factor long `<script>` blocks out into reusable partial files:

```
netconfig/templates/
├── migrate.html              # outer HTML + script — the largest
│                             # page template, hosts the Tier-3
│                             # rename modal that depends on the
│                             # partials below
├── base.html                 # outer chrome + global JS
└── _partials/                # see the directory for the current set;
                              # included via Jinja `{% include %}`
```

Current partials (at time of writing — contents of `_partials/` is
the source of truth):

* **classify.js** — shared `_guessKind` / `_looksLikeUplink`
  client-side port classifiers, used by both rename-table.js and
  fit-check.js.
* **config-viewer.js** — modal viewer with syntax highlighting +
  search, mounted globally from base.html.
* **fit-check.js** — hardware-capacity banner on the rename modal
  (access/uplink/mgmt per-kind overage indicators).
* **job-progress.js** — floating job-status widget, mounted
  globally from base.html; survives page navigation via
  localStorage.
* **rename-apply.js** — rename-modal Apply-button flow + drag
  handlers + vendor/model/module selector wiring.
* **rename-panel.js** — rename-modal preview + summary renderer.
* **rename-table.js** — rename-modal per-kind expandable sections
  with per-row override dropdowns, collision detection, drop links.
* **vlan-rename-table.js** — rename-modal VLAN-category pane
  renderer; structurally parallels rename-table.js but simpler
  (integer IDs, no per-kind sections, no target-profile dropdown).
* **local-user-rename-table.js** — rename-modal local-users
  category pane renderer (P2C4); third per-pane category after
  ports + VLANs.  Free-text rewrite, collision warning is
  informational (server merges on max privilege + first-wins role).
* **snmp-rename-table.js** — rename-modal SNMP-community pane
  renderer (P2C5); fourth per-pane category.  Scalar canonical
  surface (one community string) so the pane renders a single-row
  table for visual parity with the list-oriented panes.
  "Clear" replaces "drop" semantically — clearing the community
  causes the render path to omit the entire SNMP block.
* **snmpv3-user-rename-table.js** — rename-modal SNMPv3 USM user
  pane renderer (P2C6); fifth per-pane category.  List-oriented
  sibling of the local-users pane — one row per source USM user.
  Rename is identity-only: auth / priv / group / engine_id
  follow the renamed record.  Collisions merge on first-wins
  (auth/priv keys are NEVER combined across users).
* **theme-toggle.js** — global light/dark mode toggle wired to
  the `nav-theme-toggle` button.  Flips `<html data-theme>`
  between `light`/`dark`, persists to
  `localStorage["netconfig.theme.v1"]`, updates `aria-label` +
  `aria-pressed` to reflect the next-action.  The inline boot
  script in `base.html`'s `<head>` (NOT this partial) sets the
  initial theme synchronously before CSS parses — required for
  FOUC prevention.

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

**Theming (dark mode).**  The app supports light + dark modes via
CSS custom properties toggled on `<html data-theme>`.  One source
of truth: the `:root` block in `base.html` defines light-mode
tokens; the `[data-theme="dark"]` selector overrides the same
names with dark-mode values.  All themed CSS declarations use
`var(--token)` — never raw hex.  Tokens are curated for the
80/20 high-visibility surfaces (page / surface / text / border /
badges / buttons / nav); incremental migration of edge-case
declarations is tolerated.

Three rules keep the pattern robust:

1. **Inline boot script, blocking, in `<head>`.**  The tiny IIFE
   in `base.html`'s `<head>` reads `localStorage["netconfig.theme.v1"]`
   (user override) then falls back to `prefers-color-scheme` and
   sets the `data-theme` attribute on `documentElement`
   *synchronously* before any CSS parses.  This prevents FOUC
   (flash of unstyled content) on reload.  Do NOT move the boot
   script to an external `<script src=>`; it must block.
2. **JS-driven theme apply, not `@media (prefers-color-scheme)`.**
   One `[data-theme]` selector is the sole theme gate; the media
   query is read ONCE by the boot script, not by CSS.  This
   lets localStorage cleanly override the system preference
   without duplicated rule blocks or cascade-order headaches.
3. **Theme-aware toast/alert colour pairs via CSS class, never
   inline style.**  `showToast()` assigns a CSS class
   (`.toast-info` / `.toast-error` / `.toast-success`) instead
   of writing `element.style.background = '#...'` — the class
   resolves to `var(--badge-*-bg)` / `var(--badge-*-fg)` so
   dark mode inherits the semantic pair automatically.

The global toggle is a single icon button
(`data-testid="nav-theme-toggle"`) right-aligned on the nav; sun
glyph in dark mode, moon glyph in light mode, swap via CSS
attribute-selectors so JS never mutates the button content.  See
`_partials/theme-toggle.js` for the toggle function +
`aria-label` updater.

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
per-fixture coverage metrics.  The harness is what gated codec
promotion to `certified` during the real-capture-pass sessions —
all five shipped codecs are now at `certified` (see
`tests/fixtures/real/RESULTS.md` for the per-vendor matrix and
cert decisions).  The harness now drives *hardening* rather than
promotion: new fixtures surface latent bugs and cover grammar
surfaces the current corpus doesn't touch.

Mocking single entry point: **SSH collection is mocked at
`netconfig.api.routes.backups.get_collector`, never at `ConnectHandler`
or `paramiko.SSHClient` directly** (see CLAUDE.md hard rule).

### Cross-mesh fidelity audit harness

Beyond the test layers above, a separate audit harness lives at
`tools/run_full_mesh.py` (Phase 1: mechanical drift) +
`tools/run_phase4_reconciliation.py` (Phase 4: classify drift
against per-pair Phase-3 expectation YAMLs in
`tests/fixtures/cross_vendor_expectations/`).  Output committed as
`tests/fixtures/real/CROSS_MESH_RESULTS.md` and
`tests/fixtures/real/PHASE4_RECONCILIATION.md`.

Phase 4 classifies every `(source_codec, target_codec, fixture,
field)` cell into one of seven variance classes:

* **ALIGNED** — drift matches expectation; no action.
* **CODEC_BUG** — drifted where YAML says `disposition: good`.
  This is the high-severity signal — real cross-vendor drift the
  codec author should fix.
* **EXPECTED_LOSSY** — drifted, YAML says `disposition: lossy`
  (acknowledged loss).
* **EXPECTED_UNSUPPORTED** — drifted, YAML says
  `disposition: unsupported` (target vendor has no equivalent).
* **METHODOLOGY_ISSUE_under** — YAML says `lossy`/`unsupported` but
  the cell actually aligns (over-claiming loss).
* **METHODOLOGY_ISSUE_over** — YAML says `good` but cell is
  `not_applicable` (over-claiming applicability).
* **STRUCTURAL_ONLY** — list-row count drift (e.g. 17 source
  interfaces → 2 target interfaces) collapsed to a single signal
  per cell-parent rather than amplified across N per-field keys.
  Added to prevent a single `count drift: 17 → 2 (interfaces)`
  signal from inflating CODEC_BUG by 6× across `interfaces[].mtu`,
  `interfaces[].description`, etc.  Per-record drift on surviving
  rows still fires CODEC_BUG normally.

Per-source-vendor investigation reports under
`tests/fixtures/real/phase4_findings_<vendor>.md` carry per-cell
triage: real bug (codec fix), stale expectation (YAML refresh), or
acceptable lossy (reclassify).  This audit is what gates
"is-the-cross-vendor-translation-honest?" — failing CODEC_BUG cells
become backlog items for codec waves; failing METHODOLOGY cells
flag expectation drift.

---

## Evolution roadmap

For the active backlog see [`translator-plans.txt`](translator-plans.txt)
(dense, grep-friendly, opens with a TL;DR).  Big structural pieces
that have shipped:

- **Phase 0** — codec scaffold + mock adapter (`run_plan`, capability matrix)
- **Phase 0.5** — canonical intent model + pluggable CIMs
- **Phase 1** — 7 real codecs (Cisco NETCONF + CLI, Aruba AOS-S, OPNsense, MikroTik, FortiGate, Arista EOS, Juniper Junos parse-only)
- **R5** — auto-detection probe
- **R6/7** — real-capture validation harness + fixture corpus
- **Tier 2 wire-throughs** — SNMP, LAGs, local_users, DHCP pools, RADIUS, MTU

What's queued:
- Opportunistic grammar-diversity fixtures (FortiGate multi-VDOM,
  FortiOS 7.4, RouterOS 7.19+, OPNsense 25.x, AOS-S 16.11 late
  patches — all hardening, no longer cert-promotion — see
  `tests/fixtures/real/RESULTS.md`)
- Fidelity polish bucket (VRFs, STP globals, PKI chains → Tier 3)
- Deploy phase (transport layer wiring for migration output push)
- Additional canonical models (firewall-specific, wireless-specific CIMs)
- Per-pane overrides for **NTP servers**, **DNS servers**,
  **syslog servers**, **SNMP trap-hosts**, and **RADIUS** — all
  list-oriented cross-vendor-stable management-plane surfaces with
  per-codec parse+render already in place.  Following the same
  three-step recipe (orchestrator → pipeline → pane) as ports /
  VLANs / local_users / SNMP-community / SNMPv3-users.  See
  [`translator-plans.txt`](translator-plans.txt) for viability
  audit + ordering decisions.

---

## See also

- [`definitions/README.md`](definitions/README.md) — device-definition + target-profile YAML schema
- [`netconfig/migration/codecs/README.md`](netconfig/migration/codecs/README.md) — codec authorship guide
- [`netconfig/migration/canonical/README.md`](netconfig/migration/canonical/README.md) — canonical intent model and Tier 1 / 2 / 3 promotion rules
- [`netconfig/api/routes/README.md`](netconfig/api/routes/README.md) — HTTP route inventory and frozen pipeline-stage signatures
- [`docs/glossary.md`](docs/glossary.md) — project-jargon reference
- [`docs/adding-a-canonical-field.md`](docs/adding-a-canonical-field.md) — worked example: MTU wire-through across every codec
- [`docs/adding-a-target-profile.md`](docs/adding-a-target-profile.md) — worked example: shipping a hardware-shape YAML for the rename UI fit-checks
- [`docs/feature-parity-walkthrough.md`](docs/feature-parity-walkthrough.md) — worked example: SNMPv3 USM landing across canonical + codec + pipeline + UI + tests + docs
- [`translator-plans.txt`](translator-plans.txt) — active roadmap and backlog
- [`tests/fixtures/real/RESULTS.md`](tests/fixtures/real/RESULTS.md) — per-codec certification state

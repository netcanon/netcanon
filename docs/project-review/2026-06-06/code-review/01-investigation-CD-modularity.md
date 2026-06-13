# 01 — Investigation CD: Modularity & Coupling

*Reviewer CD, Fleet C (code & architecture). Read-only, review-grade.
Commit `b08040c` (v0.1.2). Lens: whole-tree modularity & coupling —
import-graph health, shared-transform consumption uniformity, the
per-pane rename-orchestrator replication, extension-point cost, and
the frozen-signature contract on `migration_pipeline.py`.*

---

## 1. Scope & method

This chapter assesses Netcanon's **module structure and the edges
between modules**, not the correctness of any single function. Where
CA owns the four-layer story and CB/CC own file-by-file coverage, CD
asks a narrower set of structural questions:

* **Import-graph shape.** Are there cycles? Layering inversions (a
  lower layer importing a higher one)? Deep multi-level reach-ins
  (`from ....models.migration import …`) and are they justified?
* **Shared-transform story.** Are the four cross-codec utilities
  (`canonical/transforms.py`, `migration/_naming.py`,
  `migration/_tier3_detection.py`, `migration/_user_secrets.py`)
  consumed uniformly by every codec, or is logic copy-pasted per
  codec?
* **Per-pane rename-orchestrator pattern.** The five
  `canonical/*_names.py` modules — clean replication or divergence?
* **Extension-point cleanliness.** To add a codec, a canonical field,
  or a rename category — how many files change, and is that count
  earned?
* **Frozen-signature contract.** Is the "never change a
  `migration_pipeline.py` stage signature; add a new function instead"
  rule actually honoured and enforced?

**Method.** I mapped every internal import edge with Grep across
`netcanon/` (259 relative-import statements across 82 files; 480
absolute `netcanon.` imports across 163 test/tool/desktop files).
I read the four shared utilities in full, all five rename
orchestrators in full, `migration_pipeline.py` in full, the codec
`base.py` + `registry.py` + `migration/__init__.py` discovery
machinery, `api/routes/migration.py`'s per-pane endpoints, and the
`docs/adding-a-canonical-field.md` extension-point reference. Cycle
claims were verified by checking the specific candidate back-edges
(`canonical → codecs`, `models → migration`, `canonical → services`)
rather than asserting acyclicity from a tool's say-so. The
methodology and `AGENTS.md` Hard Rules were read first so that
intentional invariants (frozen signatures, ship-before-wire,
extension-point no-ops) are judged against the project's own stated
goals rather than flagged as bugs.

All `file:line` citations are against commit `b08040c`. Findings I
could not fully confirm are marked `UNVERIFIED`.

---

## 2. Executive summary

**Netcanon's module graph is healthy and deliberately layered. I
found no import cycles and no layering inversions.** The dependency
direction is strictly downward: `api → services → {migration, models,
storage, collectors} → models`, with `models/` and
`canonical/intent.py` sitting as true leaf nodes that import only
stdlib + pydantic. The one structurally interesting edge —
`canonical/port_names.py` needing the `CodecBase` type — is correctly
quarantined under `TYPE_CHECKING`, so the obvious back-edge
(`canonical → codecs`) does not exist at runtime. This is the single
most important coupling result in the review and it is clean.

The **shared-transform story is excellent**. All four cross-codec
utilities are consumed through real shared imports, not copy-paste.
`_user_secrets` is consumed by all 8 render-capable codecs;
`_tier3_detection` by all 9 codecs (one per-vendor detector each);
`canonical/transforms` by every codec whose vendor grammar needs the
port↔VLAN mirror; `_naming` by exactly the 2 codecs whose parsers
reject whitespace (and the scoping is documented as intentional).
The codec→`port_names` delegation is mechanically uniform: every one
of the 8 split-codecs exposes `classify_port_name` /
`format_port_identity` as identical one-line forwards to its local
`port_names` module.

The **five rename orchestrators are a model of clean replication**.
`port_names`, `vlan_names`, `local_user_names`, `snmp_names`,
`snmpv3_user_names` share an identical contract shape (`translate_X`
+ `build_X_rename_transform` returning `(transform, result)`, with a
`*RenameResult` Pydantic struct carrying `applied`/`dropped`/
`warnings`). The divergence between them is exactly the irreducible
domain difference (ports need a vendor bridge; VLANs are bare ints;
SNMP community is a scalar) — not accidental drift.

The **frozen-signature contract is honoured in the code** and is
well-documented in three places (module docstring, AGENTS.md Hard
Rules, ARCHITECTURE.md). The five rename categories were added the
right way — each as an optional `…_rename_map=None` parameter on
`run_plan_with_overrides`, never by mutating `run_plan` /
`run_plan_with_rename`. The one soft spot: **the freeze is enforced
only socially**, not by an `inspect.signature` guard test (CD-03).

**Extension-point cost is justified and well-documented.** Adding a
codec is a genuine drop-in (auto-discovery, zero edits to the
registry); adding a canonical field is a known ~one-commit
wire-through with a reference doc; adding a rename category is a
proven five-times three-step recipe. The honest cost is that
"add a field" and "add a rename category" each touch ~8–15 files,
but that count is structural (one canonical surface × N codecs) and
the project documents it openly rather than hiding it.

Findings are mostly OBSERVATION / P3. There is **one P2** (the
absence of a signature-freeze guard given how load-bearing the
contract is) and **one P3 doc-coupling drift** in ARCHITECTURE.md.
No P0/P1.

---

## 3. Package-level import-edge map

### 3.1 Internal edges (runtime, module-level)

Relative-import edges among the top-level `netcanon/` packages,
collapsed to the package level (read `A → B` as "A imports from B"):

```
                          ┌──────────────────────────────┐
   main.py ──────────────▶│ api.routes.* (8 routers)      │
        │                 └──────────────────────────────┘
        │                          │   │   │
        │                          ▼   │   ▼
        │            api.deps ◀─────┘   │   services.*
        │                 │             │      │
        ▼                 ▼             ▼      ▼
   storage.*          definitions.*   models.* (LEAF)
        │                                  ▲   ▲
        ▼                                  │   │
   security.*                              │   │
                                           │   │
   collectors.* ───────────────────────────┘   │
                                                │
   migration/ (pkg __init__ auto-discovers codecs)
        │
        ├── services.migration_pipeline ─▶ migration.codecs.base ─▶ models.migration
        │                               └▶ (lazy) canonical.*_names
        │
        ├── codecs/<vendor>/codec.py ─▶ models.migration  (real, multi-level)
        │                            ─▶ canonical.intent    (real)
        │                            ─▶ codecs.base, codecs.registry, codecs._input_shape (real)
        │                            ─▶ (lazy in parse/render) canonical.transforms
        │                            ─▶ (real) _naming / _user_secrets / _tier3_detection
        │
        ├── canonical/intent.py ─▶ (stdlib + pydantic only)  [LEAF]
        ├── canonical/transforms.py ─▶ canonical.intent
        ├── canonical/port_names.py ─▶ (TYPE_CHECKING only) codecs.base  ← key non-edge
        └── canonical/{vlan,local_user,snmp,snmpv3_user}_names.py ─▶ (lazy) canonical.intent
```

**Direction is strictly downward.** Nothing in `models/` imports
anything else in `netcanon` (verified: `Grep "from \.\.\.|import
netcanon"` over `netcanon/models/**` returns zero hits). `models/`
and `canonical/intent.py` are the two foundation leaves — both import
only `pydantic` + stdlib (`intent.py` lines 73–77;
`models/migration.py` lines 16–23). Every higher layer can depend on
them with no risk of a back-edge.

**`api → services → migration/models/storage/collectors`** is the
spine and it never reverses. `services/migration_pipeline.py` imports
`codecs.base` and `models.migration` at module level (lines 107–112)
and `migration_validate` (line 113); it imports the five rename
orchestrators **lazily** inside `run_plan_with_overrides` (lines
420–430). No route, service, model, or codec imports `api.*` or
`main`.

### 3.2 Cycle analysis — the one edge that matters

The structurally interesting question is the relationship between
`canonical/` and `codecs/`:

* `codecs/<vendor>/codec.py` imports `canonical.intent` and
  `canonical.port_names` **for real, at module scope** (e.g.
  `arista_eos/codec.py:48`, `aruba_aoss/parse.py:47`). This is the
  expected direction — codecs populate the canonical tree.
* The back-edge `canonical/port_names.py → codecs.base` exists **only
  under `TYPE_CHECKING`** (`port_names.py:37–38`). At runtime there is
  no import; the `CodecBase` references in signatures are string
  annotations (`source_codec: "CodecBase"`, line 224). The few places
  that genuinely need a concrete canonical class at runtime
  (`from .intent import CanonicalIntent`) import **intra-package**
  inside the function body (e.g. `port_names.py:293`).

**Conclusion: no cycle.** `canonical` depends on `codecs` only at
type-check time; `codecs` depends on `canonical` at runtime. The two
are runtime-acyclic. This is the correct way to express the
"orchestrator references the codec contract but the codec implements
against the canonical shape" relationship without inverting layers.

I explicitly checked the other two plausible cycles and both are
absent:

* `canonical/* → services/*` or `canonical/* → codecs/*` at runtime —
  `Grep` over `canonical/**` for `import.*services|import.*codecs|from
  ..codecs|...services` returns **only** the single TYPE_CHECKING line
  in `port_names.py`. The four other orchestrators import nothing but
  stdlib + pydantic + lazy intra-package `intent` (confirmed in
  `local_user_names.py:51–59,115`).
* `models/* → migration/*` — zero hits.

### 3.3 Deep multi-level reach-ins (`from ....`)

The deepest relative imports are the four-dot
`from ....models.migration import …` in each codec's `codec.py`
(8 codecs + `_mock`; e.g. `cisco_iosxe/codec.py:103`,
`arista_eos/codec.py:42`, `mikrotik_routeros/codec.py:69`). Three-dot
`from ...models.migration` / `from ...canonical.intent` /
`from ..._user_secrets` are pervasive in the codec tree.

These are **deep but not reach-ins in the pejorative sense**: every
one targets a stable, intentional surface — the canonical model
(`models.migration.CapabilityMatrix`, `models.migration.DeviceClass`)
or the canonical IR (`canonical.intent.*`) or a sibling shared util
(`_user_secrets`, `_naming`). A codec living at
`migration/codecs/<vendor>/` is four levels below `netcanon/`, so
reaching `models/` (two levels below `netcanon/`) is necessarily a
four-dot climb. The depth is a function of the (reasonable) directory
nesting, not of modules grabbing at internals they shouldn't. I found
**no** case of a codec importing another codec's internals, a service
importing a route, or a model importing a codec.

The one mild readability cost: four-dot imports are visually noisy and
a contributor refactoring the package tree (e.g. flattening
`codecs/<vendor>/` to `codecs/<vendor>.py`) would have to re-count
dots across ~40 sites. This is an OBSERVATION (CD-05), not a defect —
it is the standard trade-off of relative imports plus deep packages,
and the project has chosen relative imports consistently.

---

## 4. Shared-utility consumption audit

The central DRY question: are the four shared utilities consumed
uniformly, or re-implemented per codec? **Verdict: uniformly
consumed, with intentional scoping where a utility genuinely doesn't
apply to a vendor.**

### 4.1 `migration/_user_secrets.py` — hash-portability policy

Consumed by **all 8 render-capable codecs**. Every render path imports
`classify_hash` / `is_migratable` / `format_review_comment` (or the
subset it needs) from `..._user_secrets`:

| Codec | Imports from `_user_secrets` | Site |
|---|---|---|
| arista_eos | classify_hash, format_review_comment, is_migratable | `render.py:36` |
| aruba_aoss | classify_hash, is_migratable | `render.py:34` |
| cisco_iosxe_cli | classify_hash, format_review_comment, is_migratable | `render.py:49` |
| fortigate_cli | classify_hash, format_review_comment, is_migratable | `render.py:49` |
| juniper_junos | classify_hash, format_review_comment, is_migratable | `render.py:70` |
| mikrotik_routeros | classify_hash, format_review_comment, is_migratable | `render.py:37` |
| opnsense | classify_hash, format_review_comment, is_migratable | `render.py:41` |
| cisco_iosxe (NETCONF) | (none — target codec doesn't emit user hashes) | n/a |

The per-target accepted-algorithm sets live in **one place**
(`_user_secrets.py:96–104`, the `_TARGET_ACCEPTS` dict). The codec's
own emit-form table (e.g. arista's `_ARISTA_SECRET_TYPE`) dispatches
the wire syntax, but the *migratability decision* is centralised. The
module docstring (lines 1–46) explicitly records that this logic "was
previously duplicated in aruba_aoss/render.py" — i.e. the project
already paid down a copy-paste debt here. The aruba render even
documents itself as "a thin wrapper over the shared … policy"
(`aruba_aoss/render.py:197–198`). This is a strong DRY result.

### 4.2 `migration/_tier3_detection.py` — silent-drop notification

Consumed by **all 9 codecs** (8 real + mock-irrelevant). Each codec's
`parse()` ends with a one-line call to its per-vendor detector, all
imported lazily from `..._tier3_detection`:

| Codec | Detector | Site |
|---|---|---|
| cisco_iosxe_cli | detect_tier3_sections_iosxe_cli | `codec.py:334` |
| arista_eos | detect_tier3_sections_iosxe_cli *(shared CLI grammar)* | `codec.py:273` |
| aruba_aoss | detect_tier3_sections_iosxe_cli *(shared CLI grammar)* | `codec.py:260` |
| fortigate_cli | detect_tier3_sections_fortios | `codec.py:308` |
| juniper_junos | detect_tier3_sections_junos | `codec.py:285` |
| mikrotik_routeros | detect_tier3_sections_routeros | `codec.py:268` |
| opnsense | detect_tier3_sections_opnsense | `codec.py:294` |
| cisco_iosxe (NETCONF) | detect_tier3_sections_iosxe_xml *(no-op by design)* | `codec.py:604` |

Notable good design: arista and aruba **reuse** the iosxe_cli
detector because they share the IOS-style CLI grammar — no third copy
of the firewall/ACL/QoS regex set. The NETCONF codec gets a no-op
detector (`_tier3_detection.py:170–187`) kept "for parity so every
codec's parse() goes through the same one-line hook." That symmetry
is precisely the kind of uniformity that prevents a future codec from
forgetting the surface.

### 4.3 `canonical/transforms.py` — port↔VLAN / SVI mirrors

Consumed by every codec whose vendor grammar needs the bridge, via
**lazy intra-call imports** (so the transform is pulled only when the
codec actually mirrors):

| Codec | Transform(s) consumed | Site |
|---|---|---|
| cisco_iosxe_cli | project_switchport_to_vlan (parse), project_vlan_to_switchport (render) | `parse.py:562`, `render.py:81` |
| arista_eos | project_svi_to_vlan + project_switchport_to_vlan (parse), project_vlan_to_switchport (render) | `parse.py:554`, `render.py:171` |
| aruba_aoss | project_switchport_to_vlan + project_vlan_to_switchport (parse) | `parse.py:1185` |
| juniper_junos | project_switchport_to_vlan (parse), project_vlan_to_switchport (render); `_natural_port_sort_key` reused | `parse.py:729`, `render.py:119`, `parse.py:338` |

The natural-sort key (`_natural_port_sort_key`) is itself reused by
junos and cisco_iosxe_cli (`juniper_junos/parse.py:338`,
`cisco_iosxe_cli/render.py:225`) rather than reimplemented — even the
*helper inside* the shared module is shared. Codecs that are
inherently VLAN-centric or port-centric and don't need a mirror
(fortigate, mikrotik for most paths, opnsense) simply don't call it.
This is correct: the transform is consumed where the vendor model
diverges from canonical and skipped where it doesn't.

### 4.4 `migration/_naming.py` — hostname whitespace sanitisation

Consumed by **exactly 2 codecs** — `cisco_iosxe_cli` (`render.py:48`,
applied at `:102`) and `arista_eos` (`render.py:35`, applied at
`:184`). At first glance this looks like under-adoption, but the
module docstring (`_naming.py:24–29`) makes the scoping **explicit and
correct**: only Arista and Cisco IOS-XE parsers actively *reject*
whitespace in hostname tokens (truncate at first space or refuse the
line). "Per-vendor sanitisation policy may differ for other
naming-value slots (Junos / Aruba / FortiGate may have looser or
stricter rules). This helper currently targets the two codecs whose
parsers actively reject whitespace; expand the call sites only after
auditing each new codec's parser grammar." This is **appropriately
loose coupling** — the utility exists centrally for when it's needed,
and is documented as deliberately not force-fit onto codecs that
don't need it. Not a finding.

### 4.5 Consumption summary

| Utility | Consuming codecs | Mode | Duplication? |
|---|---|---|---|
| `_user_secrets` | 8 / 8 render codecs | real import | none (was de-duped) |
| `_tier3_detection` | 9 / 9 | lazy import | none (arista+aruba reuse iosxe_cli) |
| `canonical/transforms` | 4 (where grammar needs mirror) | lazy import | none (`_natural_port_sort_key` also shared) |
| `_naming` | 2 (by design) | real import | none |

There is **no copy-pasted shared logic** of the kind CD was asked to
hunt for. The closest thing to duplication is each codec's local
`port_names.py` regex set — but that is genuine per-vendor grammar
(Arista's flat `Ethernet1` vs Cisco's `Gi1/0/24`), not shareable
logic, and CC owns that DRY-vs-vendor-grammar call.

---

## 5. The per-pane rename-orchestrator pattern

Five modules under `canonical/` implement the per-pane override
surface: `port_names.py`, `vlan_names.py`, `local_user_names.py`,
`snmp_names.py`, `snmpv3_user_names.py`. CD's question: clean
replication or divergent?

**Verdict: clean, disciplined replication.** Every orchestrator
ships the identical three-part contract:

1. A `*RenameResult` Pydantic model with exactly three fields:
   `applied: dict`, `dropped: list`, `warnings: list[str]`
   (`PortRenameResult` `port_names.py:183`; `VlanRenameResult`
   `vlan_names.py:73`; `LocalUserRenameResult` `local_user_names.py:64`;
   `SnmpRenameResult` `snmp_names.py:81`; `SnmpV3UserRenameResult`
   `snmpv3_user_names.py:72`). Each docstring explicitly says "Mirrors
   `PortRenameResult` / …" — the symmetry is a stated invariant, not
   an accident.
2. A `translate_X(intent, rename_map=None) -> *RenameResult` worker
   that: logs an entry breadcrumb on every call (even no-ops),
   isinstance-guards against non-`CanonicalIntent` mock trees, returns
   early on empty map, validates the map (warning + discard on bad
   entries), splits renames from drops, mutates in place, and logs an
   exit summary. This skeleton is byte-for-byte parallel across all
   five (compare `vlan_names.py:129–154` with
   `local_user_names.py:115–137` with `snmp_names.py:142–165`).
3. A `build_X_rename_transform(rename_map=None) -> (transform_fn,
   result)` factory that wraps the worker into a pipeline-compatible
   `Callable[[intent], intent]` plus a shared result accumulator
   (`port_names.py:539`, `vlan_names.py:333`, `local_user_names.py:244`,
   `snmp_names.py:240`, `snmpv3_user_names.py:242`). Each factory's
   docstring cross-references the other four by name.

**The divergence between them is exactly the domain difference, and
nothing more:**

* `port_names` is the heavyweight — it needs the vendor-agnostic
  `PortIdentity` bridge + `classify_port_name`/`format_port_identity`
  round-trip + a `_strip_dropped_ports` cascade across 8 canonical
  fields (`port_names.py:493`). It is the only one taking
  `source_codec`/`target_codec` arguments because port names are the
  only category with vendor-specific encoding.
* `vlan_names` drops the codec bridge entirely (ints are universal)
  and adds VLAN-specific range validation + collision-merge
  (`vlan_names.py:306` `_merge_vlan`).
* `local_user_names` adds a privilege/role/hash merge
  (`local_user_names.py:227` `_merge_user`).
* `snmp_names` collapses to a scalar — its docstring (lines 57–65)
  explicitly explains why the dict shape is *kept* for API symmetry
  even though the canonical surface is a single string.
* `snmpv3_user_names` is list-shaped like local_users but uses
  first-wins-on-collision (documented rationale: "merging by-union
  would risk preserving stale crypto on the target",
  `snmpv3_user_names.py:46–52`).

This is the textbook outcome: **a shared shape with per-domain
specialisation, where every deviation has a one-paragraph rationale in
the module docstring.** The replication is maintained by docstring
cross-references rather than a base class, which is a reasonable choice
for five ~250-line modules whose only shared behaviour is structural
(the actual walk differs per category). A `RenameOrchestrator` ABC
could be argued for (CD-04, OBSERVATION) but would add an abstraction
layer over genuinely-different tree walks for limited gain; the
project's "mirror by convention + docstring" approach is defensible.

---

## 6. Extension-point cost analysis

### 6.1 Add a codec — **drop-in; verdict: excellent**

Files that *must* change to add a working codec: effectively **the new
codec package itself, and nothing else in the core**.

* Auto-discovery: `migration/__init__.py:40–70`
  (`_discover_and_register_codecs`) walks `codecs/` with
  `pkgutil.iter_modules` and imports every package, firing each
  module's `@register` decorator. The module docstring (lines 17–23)
  states the contract: "Adding a new codec is therefore a drop-in:
  create `…/<vendor>/__init__.py` that imports `<vendor>.codec` … no
  edit to this file required." I verified the registry
  (`registry.py:32`) is a decorator with collision detection and
  idempotent re-registration — no central list to append to.
* The `CodecBase` contract (`base.py:102–364`) makes every optional
  hook a **safe default no-op**: `classify_port_name` returns
  `kind="unknown"` (`:281`), `format_port_identity` returns `None`
  (`:305`), `probe` returns `None` (`:331`), `iter_xpaths` handles the
  flat-dict shape (`:242`). So a minimal codec implements only
  `name` + `capabilities` + `parse` + `render` and inherits working
  (if degraded) behaviour everywhere else. This is the cleanest
  extension point in the codebase.

The *documented* cost beyond the code is doc-sync (codecs/README,
ARCHITECTURE.md if a new wire-format) per the AGENTS.md table — but
that is doc hygiene, not coupling. The `cisco_iosxe` NETCONF codec is
a real demonstration of the no-op safety net: it does **not** implement
`classify_port_name`/`format_port_identity` (verified: `Grep` returns
zero hits in `cisco_iosxe/codec.py`), so port-rename through it is a
silent no-op by inherited default. That is intentional (NETCONF is a
rarely-a-source target codec) and correct — but see CD-06 for the
observability gap it creates.

### 6.2 Add a canonical field — **~one commit, N codecs; verdict: earned**

`docs/adding-a-canonical-field.md` is a genuine, accurate
extension-point reference (the MTU wire-through). Files touched for a
cross-cutting Tier-1/2 field:

* `canonical/intent.py` (the model) — 1 file.
* Every shipped codec's `parse.py` + `render.py` (or `codec.py` for
  the single-file NETCONF codec) — up to **16 files** (8 codecs ×
  2 sides), minus deliberate skips where a vendor can't carry the
  field (the doc names Aruba MTU as such a skip, lines 133–136).
* `tests/unit/migration/test_<feature>_wire_through.py` — 1 new file.
* Each codec's `_CAPS` capability-matrix entry (doc step 6).
* Optionally `translator-plans.txt`, a `tools/demo.py` scenario.

This is the highest file-count extension, but the count is
**structural and irreducible**: a canonical field that N codecs
support must be wired in N codecs. The doc is explicit that this is
"one logical feature that touches every shipped codec … in a single
commit" and budgets it at 30–60 min for a simple field. The
ship-before-wire alternative (schema + `Unsupported` matrix entries
only, codecs wired incrementally) is documented as the escape hatch
for niche fields (lines 16–22). Crucially, the canonical model stays
**vendor-clean** — the doc's "Per-vendor quirks go in codec code, not
canonical" gotcha (lines 299–304) protects the leaf-node purity of
`intent.py` that makes the whole import graph acyclic. Verdict: the
cost is earned and the project is honest about it.

### 6.3 Add a rename category — **proven 3-step recipe; verdict: clean**

ARCHITECTURE.md (lines 260–271) documents a "proven five times over"
recipe; the code confirms it. To add (say) an NTP-server rename pane:

1. **New orchestrator module** `canonical/ntp_names.py` — clone the
   ~250-line shape from any existing `*_names.py`.
2. **Wire into `run_plan_with_overrides`** as a new
   `ntp_rename_map: dict | None = None` parameter + a `if … is not
   None:` sentinel block appending the transform
   (`migration_pipeline.py:565–571` is the template) + an outcome
   block (`:622–628`) + a capture-transform extension if the pane
   enumerates source entities (`:504–512`).
3. **New endpoint + request/result fields + UI**:
   `api/routes/migration.py` per-pane POST (the snmpv3 endpoint at
   `:495–557` is a ~15-line clone), `models/migration.py`
   request field (`MigrationPlanRequest.*_rename_map`, see `:767`) +
   result fields (`MigrationJob.*_renames` / `*_drops`, `:589–595`),
   plus `migrate.html` rail button + pane partial.

Honest file count: **~6–7 files** (1 new orchestrator, pipeline,
routes, models, 1–2 templates, 1 test file). The recipe is uniform
and the sentinel semantics (`None` = not engaged, `{}` = auto,
`{src:tgt}` = explicit, `{src:None}` = drop) are identical across all
five existing categories and documented in three places. The
extension is genuinely append-only on the pipeline — no existing
parameter or block is touched. Verdict: clean and low-friction; the
file count is the irreducible "engine + endpoint + model + UI" fan-out
of a user-facing feature, not coupling debt.

A small coupling observation (CD-07): the `MigrationPlanRequest`
carries **all five** rename-map fields on **one** body model, and
every per-pane endpoint accepts the same body but reads only its own
field. This is convenient (one DTO) but means the request model grows
unboundedly with categories, and a client can post all five maps to a
single-category endpoint where four are silently ignored (the
docstring at `migration.py:539` notes "Ignores other override maps").
This is a deliberate API-symmetry choice, not a bug — recorded as
OBSERVATION.

---

## 7. Findings

Severity scale per the review README (P0–P3 / OBSERVATION). Ordered
by severity.

---

### CD-01 — Import graph is acyclic with no layering inversions *(POSITIVE / OBSERVATION)*

**File:** whole tree; key evidence `canonical/port_names.py:37–38`,
`models/migration.py:16–23`, `canonical/intent.py:73–77`.

**Claim.** There are no import cycles and no layering inversions in
`netcanon/`. Dependency direction is strictly downward.

**Evidence.** `models/` and `canonical/intent.py` import only stdlib +
pydantic (leaf nodes). The only `canonical → codecs` edge is under
`TYPE_CHECKING` (`port_names.py:37–38`); at runtime `canonical` does
not import `codecs` (Grep over `canonical/**` for runtime codec/
service imports returns only that one type-only line). `services →
canonical` is lazy (`migration_pipeline.py:420–430`) and `canonical`
never imports `services`. No route is imported by any service/model/
codec.

**Suggested direction.** None — this is the healthy baseline. Recorded
so the adversarial pass and future refactors know the acyclicity is a
verified property to *preserve*, not an assumption.

---

### CD-02 — Shared transforms are consumed uniformly, not copy-pasted *(POSITIVE / OBSERVATION)*

**File:** `migration/_user_secrets.py`, `_tier3_detection.py`,
`canonical/transforms.py`, `_naming.py` and their consumers (see
§4 tables).

**Claim.** All four cross-codec utilities are consumed via real shared
imports with zero re-implementation; scoping (e.g. `_naming` on 2
codecs) is intentional and documented.

**Evidence.** `_user_secrets` → 8/8 render codecs; `_tier3_detection`
→ 9/9 codecs (arista+aruba reuse the iosxe_cli detector); transforms →
4 codecs where the grammar needs the mirror (`_natural_port_sort_key`
itself reused); `_naming` → exactly the 2 codecs whose parsers reject
whitespace, with the scoping documented at `_naming.py:24–29`. The
`_user_secrets` docstring records that this logic "was previously
duplicated in aruba_aoss/render.py" and is now centralised.

**Suggested direction.** None. This is the DRY outcome the lens was
hunting for and it holds.

---

### CD-03 — Frozen pipeline signatures are not guarded by an `inspect.signature` test *(P2)*

**File:** `netcanon/services/migration_pipeline.py:126`, `:295`, `:670`
(the three frozen functions); `tests/unit/migration/test_pipeline.py`,
`tests/unit/migration/test_run_plan_overrides.py` (no guard present).

**Claim.** The "never change a pipeline-stage signature" Hard Rule is
documented in three places (module docstring lines 87–97, AGENTS.md
Hard Rules, ARCHITECTURE.md lines 260–263) and *honoured* in the code,
but it is **enforced only socially**. There is no test that asserts the
parameter names/order/defaults of `run_plan`, `run_plan_with_rename`,
or `run_plan_with_overrides`.

**Evidence.** Grep for `inspect`, `signature`, `getfullargspec`,
`parameters[` across `tests/` finds no signature-introspection guard on
these functions. The contract relies on (a) AGENTS.md compliance and
(b) the indirect protection that "dozens of tests" call the functions
with specific keyword args, so a *removed or renamed* parameter would
break them. But a *reordered* positional parameter, a changed default
(e.g. `force=False` → `force=True`), or an inserted positional
parameter ahead of an existing one could pass the existing tests while
silently breaking external callers (the README sample code, the
desktop server, any third-party integration) that bind positionally.
The methodology's own "validation theatre" anti-pattern warns against
trusting that tests cover an invariant they don't explicitly assert.

**Why P2 not P3.** The module docstring calls this "THE migration
orchestrator … every code path … funnels through one of the three
public functions"; the contract is maximally load-bearing, and the
project has invested heavily in documenting it. A 20-line guard test
(`assert list(inspect.signature(run_plan).parameters) == [...]` for
each of the three, asserting names + order + defaults) would convert a
social contract into a CI-enforced one — exactly the discipline the
rest of the codebase applies to capability matrices and module-variant
allowlists. The gap is the *absence of the guard the project's own
methodology would predict*, hence P2.

**Suggested direction.** Add `tests/unit/migration/
test_pipeline_signature_freeze.py` that pins the exact parameter list
(names, order, and defaults) of all three functions, with a comment
pointing at the AGENTS.md Hard Rule. Failing the test then *is* the
"you changed a frozen signature" alarm, rather than discovering it via
a broken downstream caller.

---

### CD-04 — Five rename orchestrators replicate by convention, not by a shared base *(OBSERVATION)*

**File:** `canonical/{port,vlan,local_user,snmp,snmpv3_user}_names.py`.

**Claim.** The five orchestrators share an identical structural
contract (result struct + `translate_X` + `build_X_rename_transform`)
maintained purely by docstring cross-reference and copy-shape
convention. There is no `RenameOrchestrator` ABC or shared
`build_rename_transform` helper.

**Evidence.** Each `build_*_rename_transform` body is near-identical
(compare `vlan_names.py:333–364` with `local_user_names.py:244–275`
with `snmp_names.py:240–273`): construct result, define inner
`_transform` that calls the worker and merges `applied`/`dropped`/
`warnings` into the shared result, return `(transform, result)`. The
only delta is which `translate_X` is called. The validation/normalise
preamble (`isinstance` guard, empty-map early return, per-entry
warning-and-discard) is also structurally duplicated.

**Assessment.** This is *replication*, but it is **disciplined,
documented replication of ~30 lines of boilerplate**, not divergent
copy-paste — every module's docstring names its four siblings and the
"Mirrors X" invariant. Extracting a base would consolidate the
`build_*` wrapper and the merge logic, but the *worker* tree-walks are
genuinely different per category (the part that matters), so the
shared surface is mostly the trivial wrapper. The trade-off is real:
an ABC adds an indirection that a contributor adding category #6 must
learn, against saving ~30 lines of well-understood boilerplate.

**Suggested direction.** Optional, low priority. If a 6th/7th category
lands, consider lifting the `build_*_rename_transform` wrapper + the
result-merge into a single `build_rename_transform(translate_fn,
result_cls)` helper in a `canonical/_rename_base.py`; leave the
per-category `translate_X` walkers as-is. Until then, the
convention-plus-docstring approach is acceptable and arguably clearer.

---

### CD-05 — Deep four-dot relative imports are pervasive in the codec tree *(OBSERVATION)*

**File:** every `codecs/<vendor>/codec.py` (~9 files), e.g.
`cisco_iosxe/codec.py:103`, `arista_eos/codec.py:42`,
`mikrotik_routeros/codec.py:69`.

**Claim.** Codecs reach `models.migration` via four-dot relative
imports (`from ....models.migration import …`) and the canonical IR /
shared utils via three-dot imports. This is correct by layering but
visually noisy and refactor-fragile.

**Evidence.** The codec packages sit four levels under `netcanon/`
(`netcanon/migration/codecs/<vendor>/`), so reaching `netcanon/models/`
is a necessary four-dot climb. ~40 sites use three/four-dot relative
imports. No import targets another module's *internals* — all hit
stable surfaces (`models.migration`, `canonical.intent`,
`_user_secrets`, `_naming`).

**Assessment.** Not a defect — this is the standard cost of consistent
relative imports + deep packages, and the targets are all intentional
public-ish surfaces. The only downside is that a structural refactor
(e.g. flattening `<vendor>/codec.py`) would require re-counting dots
across many files, and four-dot imports are harder to read than an
absolute `from netcanon.models.migration import …`.

**Suggested direction.** None required. If the team ever finds the
relative-import depth painful, a project-wide switch to absolute
imports for the cross-package edges (`netcanon.models.*`,
`netcanon.migration.canonical.*`) would make the edges self-describing
at the cost of a one-time mechanical change. Pure preference; the
current state is internally consistent.

---

### CD-06 — `cisco_iosxe` NETCONF codec inherits port-name no-ops silently *(OBSERVATION / P3)*

**File:** `netcanon/migration/codecs/cisco_iosxe/codec.py` (no
`classify_port_name` / `format_port_identity` override);
`base.py:281,305` (the inherited no-ops).

**Claim.** The single-file NETCONF codec does not implement the
port-name bridge, so it inherits `classify_port_name → kind="unknown"`
and `format_port_identity → None`. As a *source*, every port name it
produces classifies as unknown (left verbatim + warning); as a
*target*, it can format no identities (everything left verbatim +
warning, or auto-dropped under `strip_unmappable`). This degradation
is correct-by-design but not surfaced as a first-class capability
signal.

**Evidence.** `Grep "def classify_port_name|def format_port_identity"`
over `cisco_iosxe/codec.py` returns zero hits, vs all 8 split-codecs
which delegate to their local `port_names` (§4.5). The codec does
correctly declare `unsupported_rename_categories` (`codec.py:181`),
which is the right declarative hook — but that frozenset covers the
*rename-pane* compatibility banner, not the port-name auto-heuristic
no-op specifically.

**Assessment.** The behaviour is intentional (NETCONF is overwhelmingly
a target, and OpenConfig interface names are a narrow subtree). The
inherited no-op is the *designed* graceful-degradation path
(`base.py:262–278` documents exactly this incremental-adoption
intent). The only gap is observability: an operator translating *into*
the NETCONF codec gets per-port warnings rather than an up-front
"this target doesn't participate in port-name translation" banner.

**Suggested direction.** Low priority. Either (a) implement the two
methods even minimally (OpenConfig uses the source vendor's names
verbatim in many flows), or (b) confirm `"ports"` is (or should be) in
this codec's `unsupported_rename_categories` so the UI shows the
up-front banner instead of N per-port warnings. Cross-check with CC,
who owns the codec contract and may already track this. `UNVERIFIED`
whether the NETCONF codec's matrix/banner already covers this case to
the operator's satisfaction — I confirmed the no-op, not the UX.

---

### CD-07 — Single request DTO carries all five rename maps for all per-pane endpoints *(OBSERVATION)*

**File:** `netcanon/models/migration.py:622` (`MigrationPlanRequest`,
fields at `:651,688,711,740,767`); `api/routes/migration.py` per-pane
endpoints (e.g. `:539`).

**Claim.** Every per-pane POST endpoint accepts the same
`MigrationPlanRequest` body, which carries all five `*_rename_map`
fields. Each endpoint reads only its own field and ignores the rest;
the request model grows by one optional field per future category.

**Evidence.** `/plan/snmpv3` (`migration.py:545–547`) passes only
`snmpv3_user_rename_map=body.snmpv3_user_rename_map or {}` and its
docstring (`:539`) states "Ignores other override maps if the body
carries them." The body model has all five maps (`:651`–`:767`).

**Assessment.** This is a deliberate API-symmetry decision (one DTO,
uniform client serialisation per pane) and is documented. The coupling
cost is mild: (a) the DTO accretes a field per category, and (b) a
client mistakenly posting the wrong map to an endpoint gets a silent
no-op rather than a 422. Neither is a defect; both are documented
trade-offs of the shared-body design.

**Suggested direction.** None required. If strictness is ever wanted,
per-endpoint request sub-models would make "wrong map → 422" explicit,
at the cost of the uniform-body convenience. Recorded for completeness.

---

## 8. Coverage table

| Area | Files examined (read in full unless noted) | Verdict |
|---|---|---|
| Import-edge extraction | Grep over all `netcanon/**` relative + absolute imports (259 + 480 edges) | No cycles; no inversions |
| Foundation leaves | `models/migration.py` (imports), `canonical/intent.py` (imports), `canonical/__init__.py` | Clean leaves (stdlib + pydantic only) |
| Pipeline / frozen signatures | `services/migration_pipeline.py` (full) | Honoured; **no guard test (CD-03)** |
| Codec contract / discovery | `codecs/base.py` (full), `codecs/registry.py` (full), `migration/__init__.py` (full) | Excellent drop-in extension point |
| Shared util: user secrets | `_user_secrets.py` (full) + 8 consumer import-sites | Uniform; de-duped |
| Shared util: tier3 detect | `_tier3_detection.py` (full) + 9 consumer sites | Uniform; arista/aruba reuse |
| Shared util: transforms | `canonical/transforms.py` (full) + 4 consumer sites | Uniform; helper also shared |
| Shared util: naming | `_naming.py` (full) + 2 consumer sites | Intentionally scoped |
| Rename orchestrators (×5) | `port_names.py`, `vlan_names.py`, `local_user_names.py`, `snmp_names.py`, `snmpv3_user_names.py` (all full) | Clean replication |
| Codec port-name delegation | `Grep` of all 8 `codec.py` classify/format methods + `arista_eos/port_names.py` (full) | Mechanically uniform |
| `_input_shape` consumption | `Grep` across codec tree | 7 ambiguous-format codecs; correctly skipped by NETCONF/OPNsense |
| Per-pane endpoint cost | `api/routes/migration.py` (snmpv3 endpoint + endpoint map), `models/migration.py` (rename fields) | Clean 3-step recipe |
| Extension-point doc | `docs/adding-a-canonical-field.md` (full), ARCHITECTURE.md §§ per-pane + cross-cutting | Accurate; one drift (CD-doc, §9) |
| Methodology / rules baseline | `docs/METHODOLOGY.md` (full), `AGENTS.md` (full) | Invariants understood, not mis-flagged |

**Not covered by CD (owned elsewhere):** per-codec parser internals
and the DRY-vs-vendor-grammar call on local `port_names.py` regex sets
(CC); god-file cohesion of `intent.py`/`port_names.py` (CE);
error-taxonomy and security of the import targets (CF); request
lifecycle and the four-layer doc-vs-code agreement (CA).

---

## 9. Open questions & doc-coupling note

**Doc-coupling drift (P3) — ARCHITECTURE.md per-pane section is
internally inconsistent.** `ARCHITECTURE.md:233` enumerates the
orchestrator modules as
`{port_names,vlan_names,local_user_names,snmp_names}.py` — **four**,
omitting `snmpv3_user_names.py`. Lines 249–252 list **four**
endpoints (`/plan/ports`, `/plan/vlans`, `/plan/local_users`,
`/plan/snmp`), omitting `/plan/snmpv3`. Yet the *same document's* prose
at lines 264–271 correctly says the recipe is "proven five times over
(ports → vlans → local_users → snmp_community → snmpv3_users)" and
line 295 lists the five-category ordering. The code ships five
(`migration_pipeline.py:295–307` has all five `*_rename_map` params;
`/plan/snmpv3` exists at `migration.py:495`). So the file-path list at
:233 and the endpoint list at :249–252 are stale relative to the
document's own prose and the shipped code. **Suggested direction:**
update both enumerations to include `snmpv3_user_names.py` /
`/plan/snmpv3`, or convert them to a pointer ("see
`canonical/*_names.py` for the current set") per the AGENTS.md doc-sync
"file-tree listing" row, which explicitly prefers pointers over
exhaustive inventories that rot. (This overlaps Fleet D's
developer-doc lens; flagged here because it is a *coupling*
manifestation — the doc enumerates the extension surface and drifted
from it.)

**Open question 1 (for CC).** Is `"ports"` intended to appear in the
`cisco_iosxe` NETCONF codec's `unsupported_rename_categories`? If yes,
CD-06's observability gap is already closed at the banner level and
CD-06 downgrades to informational. `UNVERIFIED` — I confirmed the
port-name methods are absent but did not trace the rename-pane banner
for that specific codec.

**Open question 2 (for the adversarial pass).** The lazy-import
rationale comment at `migration_pipeline.py:418–419` states the five
orchestrator imports are lazy "to avoid circular dependency … (these
modules import CodecBase; this module imports CodecBase)." I verified
this is **imprecise**: only `port_names.py` references `CodecBase`, and
even there only under `TYPE_CHECKING` (no runtime import). The other
four orchestrators import neither `CodecBase` nor `codecs` at all — a
top-level import of those four would not cycle. The laziness is
harmless (and arguably good defensive hygiene / import-time-cost
avoidance), but the *stated reason* is inaccurate. This is a
comment-accuracy nit, not a defect — recorded so the adversarial pass
can decide whether it rises to a doc-sync P3 or stays a non-finding.
My read: non-finding (the comment over-claims a justification but the
behaviour is correct and safe).

**Open question 3.** No `inspect.signature` guard exists for the
frozen pipeline functions (CD-03). Should a guard also pin the
`*RenameResult` struct field names (the cross-orchestrator "Mirrors X"
invariant)? Currently that symmetry, like the signature freeze, is
docstring-enforced only. Lower priority than CD-03 but the same class
of social-vs-CI gap.

---

*End of CD investigation. No project files were modified; this chapter
is the only artefact written.*

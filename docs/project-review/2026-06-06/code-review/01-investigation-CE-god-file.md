# 01 — Investigation CE — God-File / Cohesion / SRP Assessment

*Reviewer lens: CE. Read-only, review-grade. Commit `b08040c` (v0.1.2).*
*Repo root: `<repo>`.*

---

## 1. Scope & method

This chapter judges the LOC leaders enumerated in
`docs/project-review/2026-06-06/00-snapshot.md` against a single
question: **is the file's size *earned* by one cohesive
responsibility (or an irreducible vendor grammar), or is it a
god-file housing multiple responsibilities that want a seam?**

The framing the methodology demands (and `00-code-scope.md`
reiterates) is that a big file is **not** automatically a god-file.
A 2455-line parser may be irreducible vendor grammar with one
responsibility. I therefore counted, per file:

1. **Distinct responsibilities.** Not "distinct functions" — a parser
   with 40 `_apply_*` helpers that all feed one `parse_intent()` has
   *one* responsibility (translate this vendor's grammar into the
   canonical tree), not 40.
2. **Internal section structure.** Are there clear seams already
   (comment-banner sections, an extraction pattern in flight)? A file
   that is already sectioned and whose sections are independently
   coherent is a different risk than an undifferentiated wall.
3. **Whether a split would help or merely scatter.** Splitting a
   cohesive grammar across files imposes a cross-file import tax and
   an "where does X live?" lookup cost with no cohesion gain. Splitting
   a file that genuinely interleaves two concerns *removes* a reader's
   need to hold both in their head.

Verdicts are one of:

* **KEEP-AS-IS** — size earned by a single cohesive responsibility or
  irreducible grammar; splitting would scatter.
* **SPLIT** — multiple responsibilities; a concrete seam is named.
* **WATCH** — borderline; the trigger that would tip it to SPLIT is
  named.

Every target file in the CE list was read in full or, for the largest
parsers, read in full across paginated reads plus a structural grep of
its function/section table. I verified the snapshot LOC figures with
`wc -l` (all 15 matched exactly). I cross-checked load-bearing
constraints against `AGENTS.md` § Hard Rules (the frozen-signature
contract on `migration_pipeline.py`) and `docs/METHODOLOGY.md`
(ship-before-wire, the partial-extraction pattern). I respected the
CB/CE coordination note: CB owns correctness/clarity of `intent.py`,
`ui.py`, `models/migration.py` etc.; this chapter covers **only their
cohesion/SRP dimension**.

A note on confidence: cohesion is a judgement, not a measurement.
Where my verdict rests on a structural fact I can cite (`file:line`,
section count, an in-flight extraction pattern) I mark it grounded;
where it rests on taste I say so.

---

## 2. Executive summary

**There are no true god-files in the source tree.** Every large source
file is a single cohesive responsibility. The codec parsers (Junos
2455, IOS-XE-CLI 1672, Arista 1387, MikroTik 1291) are textbook
"irreducible vendor grammar" — each is one `parse_intent()` fed by a
flat dispatch table of per-section helpers, and splitting them would
scatter a grammar that reads best in one place. The two big canonical
data modules (`intent.py` 926, `models/migration.py` 842) are almost
pure Pydantic schema (16 classes / 0 methods, and 12 classes / 1
method respectively) — they are *large because the canonical surface
is large*, which is a documentation win, not a god-file.

**The genuinely interesting cohesion findings are three, and none is a
classic god-file:**

1. **`api/routes/ui.py` (894) interleaves two unrelated concerns.**
   Eight thin server-rendered page handlers (~10-40 lines each) share
   a module with ~430 lines (≈48% of the file) of embedded
   Swagger-UI dark-mode theming — CSS-in-Python-string constants
   (`_DOCS_*`) plus the `/docs` post-processing handler. The page
   handlers and the Swagger re-skin have nothing in common except
   "returns HTML." This is the clearest SPLIT case in the source tree,
   and it is low-risk. **[CE-01]**

2. **`templates/migrate.html` (2477) is the single biggest file in the
   repo, but it is *already mid-extraction* along a documented seam.**
   Its `<script>` block (1686 lines) already off-loads 8 large JS
   blocks to `_partials/*.js` via Jinja `{% include %}`, with an
   explicit "Contents map" comment naming what is inline vs extracted
   and *why* ("depend on inline state that hasn't been extracted yet").
   The remaining ~1090 inline JS lines fall into 6 coherent clusters
   that fit the same seam. This is a **WATCH leaning SPLIT** — the
   project has the pattern; the file just hasn't finished walking it.
   **[CE-02]**

3. **`juniper_junos/render.py` (1503) is a 1130-line single
   function.** Unlike its parse sibling (a flat dispatch of small
   `_apply_*` functions), `render_intent()` is one monolith with 14
   `# --- section ---` banner comments inside it. It is cohesive (one
   responsibility: CanonicalIntent → Junos set-form) but the
   monolithic shape is a readability/testability WATCH; the banners are
   a ready-made extraction map. **[CE-03]**

The remaining files — `migration_pipeline.py` (711, frozen-signature
orchestrator), `canonical/port_names.py` (614), `tools/sanitize.py`
(565), `target_profiles.py` (544), `intent.py` (926),
`models/migration.py` (842), `definitions.html` (926) — are all
**KEEP-AS-IS**, each for a concrete reason given in its card.

**Verdict tally:** KEEP-AS-IS = 12 · WATCH = 2 · SPLIT = 1.
(`ui.py` SPLIT; `migrate.html` and `juniper_junos/render.py` WATCH;
the other 12 KEEP.)

---

## 3. Per-file verdict cards

### 3.1 `netcanon/migration/codecs/juniper_junos/parse.py` — 2455 LOC — **KEEP-AS-IS**

* **Responsibilities counted: 1.** Translate Junos `set`-form (and
  block-form, via a `_blockform_to_setform` pre-pass) into a
  `CanonicalIntent`.
* **Structure.** One public `parse_intent()` (lines 77-815) that owns
  the materialisation order, plus a flat family of pure helpers:
  `_tokenise_set`, `_dispatch_set` (the dispatch table, lines
  1020-1084), and one `_apply_<section>` per top-level Junos stanza
  (`_apply_system`, `_apply_interfaces`, `_apply_interface_range`,
  `_apply_vlans`, `_apply_switch_options`, `_apply_routing_instances`,
  `_apply_routing_options`, `_apply_snmp`, `_apply_snmp_v3`,
  `_apply_access`, `_apply_system_services_dhcp`,
  `_apply_vrrp_group_sub`) plus small inference helpers
  (`_infer_iface_type`, `_infer_tunnel_type`, `_materialise_vrrp_group`).
* **Why KEEP.** This is the canonical "irreducible vendor grammar"
  case the methodology warns against mis-flagging. The size is driven
  by Junos being the hardest grammar in the corpus: it is the only
  codec that must handle *two* input dialects (set-form + block-form),
  a *two-pass* apply-groups inheritance model (GAP 8/9b, lines
  184-273), structural-collapse of `interface-range` blocks (lines
  275-320), and an IRB-SVI-to-VLAN fold with load-bearing-field
  guards (lines 559-690). Each of these is *the same responsibility*
  (faithfully reconstructing operator intent from Junos syntax), just
  applied to a richer grammar. The `_apply_*` functions are already
  the natural seam if one were ever forced; they sit one import away
  from being split into `parse/_system.py`, `parse/_interfaces.py`,
  etc. But there is no cohesion reason to do so: a contributor
  debugging a Junos round-trip wants the whole grammar in one
  greppable file, and the dispatch table at line 1020 is the index.
* **Risk/effort if split:** medium effort, **negative** value —
  scatters one grammar across ~10 files and forces the materialisation
  order in `parse_intent()` to reach across module boundaries into the
  accumulator dicts (`iface_state`, `irb_state`, `lag_state`, …) that
  the `_apply_*` functions mutate. The shared-mutable-accumulator
  design is precisely what makes a single file the right home.

### 3.2 `netcanon/migration/codecs/cisco_iosxe_cli/parse.py` — 1672 LOC — **KEEP-AS-IS**

* **Responsibilities counted: 1.** `show running-config` text →
  `CanonicalIntent`.
* **Structure.** `parse_intent()` (line 444) orchestrates a set of
  section parsers each returning its slice of the tree:
  `_parse_globals`, `_parse_routing_instances`, `_parse_interfaces`,
  `_dispatch_vrrp_line`, `_build_canonical_interface`, `_parse_vlans`,
  `_synthesize_vlans_from_svis`, `_parse_lags`, `_parse_static_routes`,
  `_parse_dhcp_pools`, `_parse_radius_servers`, `_parse_local_users`,
  `_parse_snmp`, plus pure utilities (`_mask_to_prefix`,
  `_normalise_mac_to_colon_hex`, `_is_link_local_v6`, `_is_mgmt_vrf`,
  `_infer_type`, `_lag_sort_key`).
* **Why KEEP.** Same shape as Junos but a notch simpler. The
  `_parse_<section>(raw) -> list[Canonical*]` convention is *cleaner*
  than Junos's mutable-accumulator pattern — each section parser is
  independently testable and returns a pure slice. This is cohesion
  done well: every helper exists because IOS-XE has that stanza, and
  the file is the vendor's grammar. The module docstring (lines 1-38)
  is an honest inventory of exactly these helpers.
* **Risk/effort if split:** low-medium effort, **negative** value.
  The `_parse_*` functions are already pure and could in principle
  live in submodules, but a Cisco-grammar debugger benefits from one
  file. WATCH-trigger if it ever grows past ~2500 and the SVI/LAG/VRF
  cross-references (e.g. `_synthesize_vlans_from_svis` reaching into
  interfaces) start needing shared mutable state like Junos's — at
  that point the Junos pattern, not a split, is the answer.

### 3.3 `netcanon/migration/codecs/juniper_junos/render.py` — 1503 LOC — **WATCH (leaning SPLIT)** — see **[CE-03]**

* **Responsibilities counted: 1** (CanonicalIntent → Junos set-form),
  but realised as **one ~1130-line function**.
* **Structure.** `render_intent()` (lines 80-1208) is a single
  function containing 14 inline `# --- section ---` banners: system,
  login users, structural-collapse detection, interfaces (the giant —
  lines 362-790, ~430 lines), LAG stanzas, vlans + VNI, routing-
  instances, routing-options, snmp, DHCP pools, apply-groups/group-
  content. Only a handful of small helpers are factored out
  (`_emit_vrrp_groups_for_address`, `_lag_name_to_ae`,
  `_split_subiface_name`, `_quote_if_needed`, `_quote_always`,
  `_dhcp_pool_name`, `_is_md5crypt_tagged`).
* **Why WATCH not KEEP.** The responsibility is single and the output
  ordering is genuinely coupled (deterministic byte-for-byte render is
  a stated invariant — lines 83-96 — and ordering matters for the
  downstream diff stage). That coupling is a real argument against
  over-splitting. **But** the asymmetry with the parse sibling is
  striking: parse dispatches to ~12 small `_apply_*` functions while
  render inlines the equivalent 14 sections into one function body.
  The interface-emission section alone (~430 lines) is larger than
  several entire codecs' render files. A single 1130-line function is
  hard to unit-test section-by-section and hard to review.
* **Why not a hard SPLIT.** The sections share a lot of local state
  (the `out: list[str]` accumulator, the `vlan_key` lookup, the
  range-collapse candidate set, the empty-interface elision
  predicate). A naive extraction would thread 5-6 parameters through
  every helper. The honest call is WATCH: the banners are a
  ready-made map, but the extraction needs care (pass a small render
  context object, not a bare line list) and is a quality refactor, not
  a defect fix.
* **Concrete seam if pursued:** extract the interface-emission block
  (362-790) into `render/_interfaces.py::emit_interfaces(ctx)` and the
  apply-groups block (1163-1208) into `render/_groups.py`, leaving the
  scalar sections (system/snmp/routing) inline. Pass a
  `_RenderCtx` dataclass carrying `out`, the vid→vlan-key map, the
  LAG-mode map, and the range-member set.
* **Risk/effort:** medium effort, modest readability value. **P3.**

### 3.4 `netcanon/migration/codecs/arista_eos/parse.py` — 1387 LOC — **KEEP-AS-IS**

* **Responsibilities counted: 1.** Arista EOS `show running-config` →
  `CanonicalIntent`.
* **Structure.** `parse_intent()` (line 351) + `_parse_stanzas`,
  `_parse_router_bgp` (EVPN MAC-VRF + Type-5 extraction — genuinely
  Arista-specific BGP-EVPN grammar), `_apply_iface_subcommand` (the
  per-interface sub-line dispatcher), `_parse_dhcp_pools`,
  `_vrrp_group_for`, `_mask_to_prefix`, `_infer_iface_type`,
  `_expand_vlan_list`. Clear `# ---` section banners at 65, 196, 346,
  602, 1345.
* **Why KEEP.** Arista carries the most VXLAN/EVPN surface of any
  codec (the docstring at lines 1-33 enumerates MAC-VRFs, VXLAN VNIs,
  VARP anycast). `_parse_router_bgp` is the only place that BGP-EVPN
  grammar lives, and it belongs next to the rest of the Arista
  grammar. One responsibility, well-sectioned.
* **Risk/effort if split:** low effort, **negative** value.

### 3.5 `netcanon/migration/codecs/mikrotik_routeros/parse.py` — 1291 LOC — **KEEP-AS-IS**

* **Responsibilities counted: 1.** RouterOS `/export` → `CanonicalIntent`.
* **Structure.** This is the *best-factored* of the big parsers.
  `parse_intent()` (line 65) dispatches on the leading `/path`, then
  delegates to a per-interface-type family (`_parse_interface_ethernet`,
  `_parse_interface_vlan`, `_parse_interface_bridge`,
  `_parse_interface_bonding`, `_parse_interface_tunnel`,
  `_parse_interface_vrrp`) and per-section parsers (`_parse_ip_address`,
  `_parse_ipv6_address`, `_parse_snmp_root`, `_parse_radius`,
  `_parse_dhcp_server_network`, `_parse_ip_pool`, `_parse_user`,
  `_parse_snmp_community`, `_parse_ip_route`). Generic helpers
  (`_join_continuations`, `_group_by_section`, `_parse_kv`) handle
  RouterOS's line-continuation + key=value grammar once.
* **Why KEEP.** Notably, four helpers (`_is_ethernet_name`,
  `_is_vlan_name`, `_infer_iface_type_from_name`, `_sort_interfaces`)
  are **deliberately shared with the render sibling** via a single
  directional import edge (documented at docstring lines 27-31). That
  is the codecs/README split-codec discipline working as designed —
  the file is cohesive *and* its shared surface is explicit. Splitting
  further would break a clean design.
* **Risk/effort if split:** low effort, **negative** value.

### 3.6 `netcanon/migration/codecs/cisco_iosxe/codec.py` — 1254 LOC — **KEEP-AS-IS** (the most-likely-god-file, cleared)

* **Responsibilities counted: arguably 4, but they are the codec
  contract, not independent concerns.** This is the only *single-file*
  codec (NETCONF/OpenConfig), so it carries parse + render + probe +
  capability-matrix in one module where every other codec splits
  parse/render. The scope brief flagged it as "the most likely true
  god-file."
* **Verdict: KEEP, with the size dominated by an honest matrix.** Of
  the 1254 lines, roughly **320 (lines 204-522) are the
  `_CAPS` CapabilityMatrix declaration** — a wall of
  `UnsupportedPath(path=…, reason=…)` entries, each with a multiline
  rationale. That is not god-file bloat; it is the matrix-honesty
  discipline made concrete (the Wave 10γ-2 fix that declared 16
  unrendered surfaces unsupported, closing 6,677 spurious audit
  cells — `METHODOLOGY.md` lines 65-72). The actual code is modest:
  `parse()` is a thin walk (532-618), `_render_canonical()` is ~50
  lines (672-718), the parse helpers (`_parse_interface`,
  `_parse_config`, `_parse_ipv4`, `_parse_ipv6`) are small and pure,
  and `probe()` is 17 lines.
* **Why the single-file shape is justified here.** The codec is a
  documented Phase-0.5 *stub* — it renders only the
  `openconfig-interfaces` subtree. Its parse and render are small
  enough that splitting them into `parse.py`/`render.py` would create
  two thin files plus a `codec.py` that still holds the 320-line
  matrix — net more files, no cohesion gain. When/if the NETCONF
  render grows to parity with the CLI sibling, *that* is the
  WATCH-trigger to split it to match the split-codec convention.
* **One cohesion nit (not a defect):** `iter_xpaths()` reaches into
  the *sibling* CLI codec (`from ..cisco_iosxe_cli.codec import
  _walk_canonical`, line 734) and `_synthesize_vlans_from_svis`
  re-implements the CLI sibling's logic with a local `_re` import
  (lines 1183-1222) "to avoid a cross-codec import." Those two choices
  pull in *opposite directions* (one imports the sibling, one
  duplicates it). Worth a coordinated note with CC/CD on the
  cross-codec coupling story — but it is not a god-file symptom.
* **Risk/effort if split:** low effort, **negative** value at current
  size.

### 3.7 `netcanon/migration/canonical/intent.py` — 926 LOC — **KEEP-AS-IS**

* **Responsibilities counted: 1.** Define the canonical tree schema.
* **Structure.** 16 Pydantic model classes, **zero methods** (verified
  by grep — no `def` inside any class). Tier-banner sections (Tier 1 /
  Tier 2 / ship-before-wire / top-level intent) organise the classes;
  every field carries a docstring with the cross-vendor mapping.
* **Why KEEP.** This is a *schema*, and the schema for an 8-vendor
  cross-translation canonical surface is intrinsically large. The size
  is almost entirely field docstrings (the
  `CanonicalVRRPGroup`/`CanonicalIPv4Address`/`CanonicalInterface`
  docstrings carry the per-vendor grammar tables that make the
  canonical model self-documenting). Splitting the models across files
  would (a) break the single-import-site convenience every codec
  relies on (`from ...canonical.intent import …` — a 14-symbol import
  in several parsers) and (b) scatter a schema whose whole value is
  being readable top-to-bottom as "here is everything Netcanon can
  represent." A pure-data module with no behaviour cannot be a
  god-file in the SRP sense — there is exactly one reason to change
  it (the canonical surface changed). CB owns the field-correctness
  dimension; from a cohesion standpoint this is exemplary.
* **Risk/effort if split:** low effort, **negative** value.

### 3.8 `netcanon/api/routes/ui.py` — 894 LOC — **SPLIT** — see **[CE-01]**

* **Responsibilities counted: 2 (interleaved).** (a) Serve the
  server-rendered Jinja page routes; (b) post-process and re-skin the
  third-party Swagger-UI `/docs` page for dark-mode parity.
* **Structure.** Eight thin page handlers (`index`, `jobs_page`,
  `schedules_page`, `configs_page`, `diff_page`, `devices_page`,
  `definitions_page`, `migrate_page`, `sanitize_page` — lines 79-444,
  most ~10-40 lines, `definitions_page` the meatiest at ~90), then a
  **block of `_DOCS_*` string constants spanning lines 457-828**
  (`_DOCS_BOOT_SCRIPT`, `_DOCS_TOKEN_STYLES`, `_DOCS_NAV_HTML`,
  `_DOCS_NAV_CSS`, `_DOCS_TOGGLE_JS`, `_DOCS_SWAGGER_DARK_CSS` — the
  last alone is ~160 lines of CSS-in-a-Python-string), then the
  `/docs` handler (831-884) that string-replaces them into the vanilla
  Swagger HTML.
* **Why SPLIT.** The `/docs` re-skin shares nothing with the page
  handlers except the `HTMLResponse` return type. It is ~430 lines —
  **roughly 48% of the file** — of embedded front-end assets that have
  no business living in a routes module. The file's own docstring
  admits the awkwardness ("The Swagger UI wrapper at `/docs` is also
  here because it's a rendered HTML page even though it wraps an API
  surface"). The `_DOCS_TOKEN_STYLES`/`_DOCS_NAV_CSS` blocks are
  *duplicated theme tokens* from `base.html` with a standing "stay in
  sync with base.html" hazard (lines 452-456, 476-481) — burying them
  in a routes file makes that drift harder to police, which is a
  matrix-honesty-adjacent concern (a stale duplicated token renders
  `/docs` in the wrong colours).
* **Concrete seam.** Move the entire Swagger surface to a dedicated
  module — `netcanon/api/routes/docs.py` (or
  `api/_swagger_theme.py` for the constants + a thin handler in
  `docs.py`). The line falls cleanly at **line 447** (the
  `# --- Swagger UI (custom-wrapped) ---` banner): everything above is
  page routes, everything below is the Swagger re-skin. `main.py`
  already composes routers, so registering a second router is one
  line. After the move, `ui.py` drops to ~450 lines of cohesive page
  handlers.
* **Risk/effort:** **low effort, clear value.** No behaviour change,
  no shared state to thread, just relocate one self-contained feature.
  This is the strongest SPLIT case in the source tree. **P2/P3.**

### 3.9 `netcanon/models/migration.py` — 842 LOC — **KEEP-AS-IS**

* **Responsibilities counted: 1** (define the migration-engine data
  contract) realised as a family of related models.
* **Structure.** 12 classes, **exactly one method**
  (`CapabilityMatrix.classify`, line 194 — and that method is the
  matrix's own resolution rule, intrinsic to the type). The classes
  form one tight cluster: `DeviceClass`, `VendorInfo`, `LossyPath`,
  `UnsupportedPath`, `CapabilityMatrix`, `XPathDelta`,
  `ValidationReport`, `TransformSpec`, `MigrationJobStatus`,
  `MigrationJob`, `MigrationPlanRequest`, `CodecInfo`.
* **Why KEEP despite the scope note flagging "MigrationJob +
  request/response + matrix together."** They *are* together, and they
  *belong* together — they are the single data vocabulary of one
  subsystem (the migration engine), and they reference each other
  (`MigrationJob.validation: ValidationReport`,
  `ValidationReport.lossy_paths: list[LossyPath]`,
  `CapabilityMatrix.device_classes: list[DeviceClass]`). The bulk of
  the LOC is the `MigrationJob` field docstrings (lines 318-460) and
  the `MigrationPlanRequest` per-pane override field docstrings (lines
  622-797) — both are documenting the five-category per-pane override
  surface that is genuinely that elaborate. This is a schema module
  with one reason to change (the migration data contract changed). It
  is the back-end peer of `intent.py` and earns its size the same way.
* **Possible WATCH-trigger (not today):** if `CapabilityMatrix` ever
  grows real behaviour (glob/prefix xpath matching is hinted as a
  future enhancement in the `classify` docstring, lines 208-210), the
  matrix logic could justify its own `capabilities.py`. At present
  it is one 25-line method. KEEP.
* **Risk/effort if split:** low effort, **negative** value.

### 3.10 `netcanon/services/migration_pipeline.py` — 711 LOC — **KEEP-AS-IS** (frozen-signature constraint honoured)

* **Responsibilities counted: 1.** Orchestrate parse → transform →
  validate → render.
* **Structure.** Three public functions only — `run_plan` (the minimal
  pipeline), `run_plan_with_overrides` (the per-pane override engine),
  and `run_plan_with_rename` (a thin legacy forward). The bulk of the
  711 lines is **docstring** (the module docstring is 98 lines; the
  `run_plan_with_overrides` docstring is ~110 lines documenting
  sentinel semantics and the capture-first transform). Actual logic in
  `run_plan_with_overrides` is one linear composition of the five
  override transforms followed by result-marshalling.
* **Why KEEP — and why it *must not* be split along its public seam.**
  `AGENTS.md` § Hard Rules and the module docstring (lines 87-98)
  freeze these three signatures: "API routes and dozens of tests
  depend on their exact shape … New rename categories grow
  `run_plan_with_overrides` as additional optional parameters." A split
  must not change the three public signatures. The honest reading is
  that there is nothing *to* split: this is one orchestrator with one
  responsibility, and its length is documentation + the
  five-category result-marshalling boilerplate (lines 588-628), which
  is inherently repetitive-but-cohesive (each category does the same
  `if result: job.x_renames = …; job.warnings.extend(…)` dance). One
  *could* table-drive that marshalling to shrink it, but that is a
  micro-refactor, not a god-file remediation, and it risks obscuring
  the per-category specifics that make the code greppable.
* **Risk/effort if split:** the frozen contract makes any signature-
  touching split **forbidden**; a behaviour-preserving internal
  refactor is low-value. KEEP.

### 3.11 `netcanon/migration/canonical/port_names.py` — 614 LOC — **KEEP-AS-IS**

* **Responsibilities counted: 1.** The vendor-agnostic cross-vendor
  port-name translation bridge.
* **Structure.** `PortIdentity` + `AggregateKind`/`PortKind` literals +
  `PortRenameResult` (the data shapes), `translate_port_names()` (the
  orchestrator), `_strip_dropped_ports()` (the cascade helper), and
  `build_port_rename_transform()` (the pipeline-factory). Much of the
  LOC is, again, docstring — the `PortIdentity` field docs (lines
  70-180) carry the per-vendor encoding semantics, and
  `translate_port_names`'s docstring (229-283) is the priority-rules
  spec.
* **Why KEEP.** This is a single conceptual unit: "the place where
  source port names become target port names without either codec
  knowing the other." The data shape, the orchestrator, and the
  factory are three faces of one responsibility and reference each
  other directly. The module docstring (lines 1-28) states the
  modular boundary explicitly ("each codec knows ONLY its own vendor's
  naming convention … the orchestrator below sits in the middle and
  never hard-codes a vendor name"). Splitting `PortIdentity` into a
  separate schema file would be the only candidate, but it is
  consumed exclusively here and by the codecs' `classify_port_name` /
  `format_port_identity` methods, so it reads best next to its
  orchestrator. It is also the template the other four per-pane
  orchestrators (`vlan_names`, `local_user_names`, `snmp_names`,
  `snmpv3_user_names`) follow — a uniform per-file pattern, not a
  god-file.
* **Risk/effort if split:** low effort, **negative** value.

### 3.12 `netcanon/tools/sanitize.py` — 565 LOC — **KEEP-AS-IS**

* **Responsibilities counted: 1.** Produce a redacted copy of a config
  by walking the canonical tree.
* **Structure.** Two public functions (`sanitize_text` — the
  parse→sanitize→render pipeline; `sanitize_intent` — the field-typed
  walk), the `_SubstitutionTable` class (counter-per-session redaction
  state), and `_redact_ip_list` (one shared helper). The
  `sanitize_intent` walk (lines 166-362) is linear — one block per
  canonical surface (hostname, domain, IP-lists, interfaces, local
  users, SNMP, RADIUS, DHCP, static routes, Tier-3 strip) — mirroring
  the canonical schema exactly.
* **Why KEEP.** The walk's length is a direct function of the
  canonical surface's breadth (it must visit every redactable field);
  that is cohesion, not sprawl. `_SubstitutionTable` is the one piece
  with state, and it is correctly encapsulated as a class. The module
  docstring (lines 1-66) is the operator-facing redaction-rule
  catalogue, which `AGENTS.md`'s doc-sync table treats as a
  load-bearing artefact (the "new redaction category" row). Splitting
  would separate the walk from the table it drives, for no gain.
* **Risk/effort if split:** low effort, **negative** value.

### 3.13 `netcanon/migration/target_profiles.py` — 544 LOC — **KEEP-AS-IS**

* **Responsibilities counted: 1.** The target-device hardware-profile
  model + its YAML loader.
* **Structure.** Four models (`TargetPort`, `TargetModule`,
  `TargetLAGCaps`, `TargetProfile`) with helper *accessors* on
  `TargetProfile` (`effective_ports`, `port_ids`, `lookup_port`, etc.
  — UI-decoupling convenience, not business logic), plus the loader
  (`_expand_range_entries`, `load_profile_file`, `load_profiles_dir`,
  `ProfileLoadError`). The class docstring (lines 31-85) carries a
  worked YAML example that `AGENTS.md`'s doc-sync table pins as
  must-stay-accurate.
* **Why KEEP.** Model + its loader is a textbook cohesive pairing —
  the loader exists only to produce these models, and the
  range-shorthand expansion (`_expand_range_entries`) is intrinsic to
  the YAML shape the models accept. The accessor methods keep UI code
  decoupled from the YAML structure (a deliberate design stated at
  line 268). One responsibility, one reason to change (the
  target-profile schema or its YAML grammar). A model/loader split is
  conceivable but would be two thin files where one cohesive one
  reads better.
* **Risk/effort if split:** low effort, **negative** value.

### 3.14 `netcanon/templates/migrate.html` — 2477 LOC — **WATCH (leaning SPLIT)** — see **[CE-02]**

* **Responsibilities counted: 1 page, but ~3 layers co-resident**
  (CSS, HTML markup, client JS), with the JS layer carrying most of
  the weight.
* **Structure (measured).**
  * Lines 5-316: `<style>` (311 lines, page-specific CSS — banner
    palette, rename-modal chrome, syntax-highlight tokens).
  * Lines 317-787: HTML markup (~470 lines — the form, the result
    panes, the draggable rename modal skeleton).
  * Lines 790-2476: `<script>` (1686 lines), of which **8 large blocks
    are already extracted** to `_partials/*.js` via Jinja
    `{% include %}` (lines 2422-2447: `rename-table.js`,
    `vlan-rename-table.js`, `local-user-rename-table.js`,
    `snmp-rename-table.js`, `snmpv3-user-rename-table.js`,
    `rename-panel.js`, `fit-check.js`, `classify.js`,
    `rename-apply.js`), leaving ~1090 inline JS lines.
* **Why WATCH and not a clean KEEP.** It is the largest file in the
  repository and a single-file front-end for one page is at the outer
  edge of reasonable. **But** the project has *already built the seam*:
  there is a `_partials/` directory with 13 JS partials, an explicit
  "Contents map" comment (lines 796-820) documenting what is inline vs
  extracted, and a stated reason for what remains inline ("depend on
  inline state that hasn't been extracted yet"). This is a file that
  is *actively being walked down*, not a neglected god-file. The
  `AGENTS.md` doc-sync table even has rows governing the
  partial-extraction discipline (the "new Jinja partial" row). Per the
  methodology framing, a file mid-disciplined-extraction is "earned-
  size being actively managed," which is closer to KEEP than to a
  defect — hence WATCH, not SPLIT.
* **Why it leans SPLIT.** The remaining ~1090 inline lines are not
  irreducible — they cluster into 6 coherent groups, each a candidate
  partial along the existing seam:
  1. Adapter/format metadata + form wiring (854-1058):
     `adapterEntry`, `compatibleExtensions`, `renderAdapterInfo`,
     `renderFormatHint`, `applyPlaceholder`, `onInputModeChange`.
  2. Auto-detect (1068-1407): `scheduleAutoDetect`,
     `renderDetectBanner`, `applyDetectedCodec`.
  3. Result rendering (1409-1651): `renderResult`,
     `renderBannerContents`, `renderTier3Banner`, `fillPathList`,
     `escapeHtml`.
  4. Target-profile dropdown populators (1701-1871):
     `populateRenameVendorDropdown`/`…Model…`/`…Module…`,
     `effectivePortsFor`.
  5. localStorage ack persistence (1872-2015): `_ackKey`,
     `loadRenameAck`, `saveRenameAck`, `applyLoadedRenameAck`.
  6. Compat/fit-check rail rendering (2045-2421):
     `renderCompatBanners`, `renderPerPaneFitCheck`,
     `renderRenameRailCounts`, `captureJobForRename`.
* **Concrete seam / trigger.** The WATCH tips to SPLIT the next time
  this template is edited for a feature touching the inline JS:
  extract clusters 2 (auto-detect) and 3 (result rendering) to
  `_partials/migrate-autodetect.js` and `_partials/migrate-result.js`
  — both are largely self-contained and the lowest-coupling clusters
  (cluster 1's form wiring shares the most module-scope state and
  should stay inline as the orchestrating IIFE). That alone would
  remove ~500 lines and bring the file under ~2000.
* **Risk/effort:** medium effort (must preserve the shared-IIFE
  module-scope-state contract the Contents map warns about); modest
  value; no behaviour change. **P3.**

### 3.15 `netcanon/templates/definitions.html` — 926 LOC — **KEEP-AS-IS**

* **Responsibilities counted: 1.** The definitions browser page
  (backup defs + overlays + target profiles + vendor/codec
  capabilities — the four sections the `definitions_page` handler
  feeds, `ui.py` lines 303-394).
* **Structure (measured).** Lines 34-284: `<style>` (250 lines). Lines
  285-695: HTML markup (~410 lines — four `<details>`-organised
  sections). Lines 696-925: `<script>` (229 lines inline JS, **no
  partials**).
* **Why KEEP.** At 926 lines with a 229-line script and four
  genuinely-distinct-but-related data sections on one page, this is
  comfortably within "one cohesive page." Its inline JS (229 lines) is
  well below the threshold where the `_partials` extraction the
  migrate page uses would pay for itself — extracting 229 lines into a
  partial would add an include indirection for little readability gain.
  The four sections are the four facets of "what data sources does
  Netcanon know about," which is one page's job. No interleaved second
  concern (unlike `ui.py`).
* **WATCH-trigger (not today):** if a fifth/sixth data section lands
  and the script crosses ~500 lines, adopt the migrate-page partial
  pattern. For now, KEEP.
* **Risk/effort if split:** low effort, **negative** value at current
  size.

---

## 4. Findings

Severity scale per the review README (P0-P3 / OBSERVATION). Per the
scope brief, a SPLIT recommendation is typically P2/P3 unless a
cohesion failure causes bugs — none here does, so all are P2/P3/OBS.
Findings are severity-ordered.

### CE-01 — `api/routes/ui.py` interleaves page routes with ~430 lines of Swagger-UI theming — **P2**

* **File:line.** `netcanon/api/routes/ui.py:447-884` (the
  `# --- Swagger UI (custom-wrapped) ---` banner through the
  `swagger_ui()` handler), with the embedded-asset constants at
  `457-828`.
* **Claim.** ~48% of this routes module is the `/docs` page's
  embedded dark-mode CSS/JS (`_DOCS_BOOT_SCRIPT`, `_DOCS_TOKEN_STYLES`,
  `_DOCS_NAV_HTML`, `_DOCS_NAV_CSS`, `_DOCS_TOGGLE_JS`,
  `_DOCS_SWAGGER_DARK_CSS`) plus the handler that string-injects them
  into vanilla Swagger HTML — a concern unrelated to the eight thin
  server-rendered page handlers it shares the file with.
* **Evidence.** Grep confirms the `_DOCS_*` constants span 457-828;
  `_DOCS_SWAGGER_DARK_CSS` alone is ~160 lines of CSS-in-a-string. The
  page handlers above (79-444) average ~10-40 lines. The file's own
  docstring concedes the `/docs` page "is also here because it's a
  rendered HTML page even though it wraps an API surface." Two of the
  constants are *duplicated theme tokens from `base.html`* carrying a
  "stay in sync" hazard (comments at 452-456, 476-481).
* **Suggested direction.** Move the Swagger surface to
  `netcanon/api/routes/docs.py` (constants optionally to
  `api/_swagger_theme.py`); register the new router in `main.py`. Seam
  falls at line 447. No behaviour change; `ui.py` becomes a cohesive
  ~450-line page-routes module and the base.html-token-drift hazard
  gets a more visible home. Low effort, clear value.
* **Confidence.** High (grounded in measured line ranges + the file's
  own docstring admission).

### CE-02 — `templates/migrate.html` is the repo's largest file; inline JS half-extracted along an existing seam — **P3**

* **File:line.** `netcanon/templates/migrate.html:790-2476` (the
  `<script>` block); extraction precedent at `2422-2447`; "Contents
  map" at `796-820`.
* **Claim.** 2477 LOC total, 1686 in one `<script>`. The project
  already extracts 8 JS blocks to `_partials/*.js`; ~1090 inline lines
  remain and cluster into 6 further-extractable groups. This is
  earned-size *being actively managed*, but it is the largest file in
  the repo and the management is unfinished.
* **Evidence.** `Glob` shows 13 `_partials/*.js`; grep shows 8
  `{% include "_partials/…" %}` directives at 2422-2447 and an explicit
  Contents-map comment naming inline-vs-extracted and the reason
  ("depend on inline state that hasn't been extracted yet"). The 6
  remaining inline clusters are enumerated in card 3.14 with line
  ranges.
* **Suggested direction.** On the next feature touching this template's
  JS, extract the auto-detect cluster (1068-1407 →
  `_partials/migrate-autodetect.js`) and the result-rendering cluster
  (1409-1651 → `_partials/migrate-result.js`) — the two lowest-coupling
  groups — removing ~500 lines. Keep the form-wiring IIFE inline as the
  orchestrator (it holds the shared module-scope state the Contents map
  warns about). Honour the "new Jinja partial" doc-sync row.
* **Confidence.** High on the facts (measured); medium on the
  prioritisation (extraction order is a judgement). Not a defect — a
  quality WATCH.

### CE-03 — `juniper_junos/render.py` is a single ~1130-line function; asymmetric with its dispatched parse sibling — **P3**

* **File:line.** `netcanon/migration/codecs/juniper_junos/render.py:80-1208`
  (`render_intent`), with the oversized interface-emission section at
  `362-790`.
* **Claim.** One cohesive responsibility, but realised as a single
  monolithic function with 14 inline `# --- section ---` banners —
  whereas the parse sibling dispatches the equivalent grammar to ~12
  small `_apply_*` functions. The ~430-line interface section is
  larger than several whole codecs' render files and is hard to
  unit-test/read in isolation.
* **Evidence.** Grep of the function body shows 14 `# --- … ---`
  banners (system / login / structural-collapse / interfaces / LAG /
  vlans / routing-instances / routing-options / snmp / DHCP /
  apply-groups). Only ~7 small helpers are factored out. The parse
  sibling (card 3.1) factors the same surface into a dispatch table.
* **Suggested direction.** Extract the interface-emission block
  (362-790) into `render/_interfaces.py::emit_interfaces(ctx)` and the
  apply-groups block (1163-1208) into a helper, passing a small
  `_RenderCtx` dataclass (the `out` accumulator + the vid→vlan-key map
  + the LAG-mode map + the range-member set) rather than threading 5-6
  bare parameters. Leave the scalar sections inline. This is a
  readability/testability refactor, not a bug fix; the deterministic-
  ordering invariant (lines 83-96) must be preserved exactly.
* **Confidence.** Medium-high. The fact (one big function) is grounded;
  whether to split is a taste call balanced against the genuine
  ordering coupling — hence WATCH not SPLIT.

### CE-04 (OBSERVATION) — `cisco_iosxe/codec.py` cross-codec coupling pulls two ways

* **File:line.** `netcanon/migration/codecs/cisco_iosxe/codec.py:734`
  (`from ..cisco_iosxe_cli.codec import _walk_canonical`) vs
  `1183-1222` (`_synthesize_vlans_from_svis` duplicated locally with a
  function-scope `import re as _re` "to avoid a cross-codec import").
* **Claim.** The NETCONF codec *imports* one helper from its CLI
  sibling and *duplicates* another to avoid importing from the same
  sibling — two opposite choices for the same coupling problem. Not a
  god-file symptom and not a cohesion defect per se, but a cross-codec
  consistency wrinkle worth flagging to CC (codec architecture) and CD
  (modularity/coupling), who own that lens.
* **Suggested direction.** Decide one policy: either both helpers live
  in a shared `cisco_iosxe_cli` (or a neutral `_shared`) module and
  both codecs import it, or both are duplicated. The
  `_synthesize_vlans_from_svis` logic is already documented as
  "mirrors the cisco_iosxe_cli sibling" — a shared home would remove
  the drift risk.
* **Confidence.** High on the facts; deliberately scoped as an
  OBSERVATION for the coupling reviewers, not a CE verdict.

### CE-05 (OBSERVATION) — `migration_pipeline.py` per-category result-marshalling is repetitive-by-design

* **File:line.** `netcanon/services/migration_pipeline.py:588-637`.
* **Claim.** Five near-identical `if result: job.x_renames = …;
  job.warnings.extend(…); job.x_drops = …` blocks. This is cohesive
  (one orchestrator) and the repetition aids greppability, but it is
  the one spot a future sixth per-pane category will copy-paste a
  block. Noted as an OBSERVATION because the frozen-signature rule
  forbids any seam-touching refactor and a table-drive would trade
  greppability for brevity — a wash, not a fix.
* **Suggested direction.** None required. If a sixth category lands and
  the pattern feels heavy, consider a small `(result, rename_attr,
  drops_attr)` table iterated once — but only if it does not obscure
  per-category specifics. KEEP as-is today.
* **Confidence.** High; intentionally low-stakes.

---

## 5. What's GOOD — earned-size files done right

The headline of this review is positive: this codebase has *no true
god-files*, and several of its large files are exemplars of how to earn
size without sprawl. Worth calling out explicitly so the orchestrator
can weight the findings correctly.

* **The codec parsers are a masterclass in "irreducible grammar."**
  Junos (2455), IOS-XE-CLI (1672), Arista (1387), MikroTik (1291) all
  follow the same shape: one `parse_intent()` + a flat dispatch table
  of per-stanza helpers, each helper existing only because the vendor
  has that stanza. The MikroTik parser is the standout — it shares
  four helpers with its render sibling via a single documented
  directional import edge, exactly the codecs/README split-codec
  discipline. None of these is a god-file; each is one vendor's grammar
  in the one place a debugger wants it.

* **`intent.py` (926) and `models/migration.py` (842) are
  documentation-dense schema, not bloat.** 16 classes / 0 methods and
  12 classes / 1 method respectively. The LOC is field docstrings
  carrying the cross-vendor mapping tables — the canonical model
  *documents itself*. A pure-data module with one reason to change
  cannot be a god-file in the SRP sense.

* **`cisco_iosxe/codec.py`'s size is the matrix-honesty discipline made
  visible.** ~320 of its 1254 lines are the `_CAPS` declaration, each
  `UnsupportedPath` carrying a multiline rationale. That is the Wave
  10γ-2 fix (6,677 spurious audit cells closed) crystallised into code.
  The single-file shape is justified for a Phase-0.5 stub whose
  parse+render are genuinely small.

* **`migration_pipeline.py` (711) respects its own frozen contract.**
  Three public functions, signatures frozen per `AGENTS.md`, the bulk
  of the LOC being the sentinel-semantics + capture-first-transform
  documentation that makes the per-pane override engine
  comprehensible. Nothing to split; the discipline is the feature.

* **The per-pane orchestrator pattern is uniform.** `port_names.py`
  (614) is the template; `vlan_names`/`local_user_names`/`snmp_names`/
  `snmpv3_user_names` follow it. Five files with one shape is a
  *system*, not five god-files.

* **The template-extraction discipline is real and documented.** That
  `migrate.html` has a `_partials/` directory, an explicit Contents-map
  comment, and `AGENTS.md` doc-sync rows governing partial extraction
  shows the team treats template size as something to manage actively
  — which is why its size reads as WATCH, not SPLIT.

---

## 6. Coverage table

| File | LOC (verified) | Responsibilities | Verdict | Finding |
|------|---:|---|---|---|
| `migration/codecs/juniper_junos/parse.py` | 2455 | 1 (Junos grammar → IR) | KEEP-AS-IS | — |
| `migration/codecs/cisco_iosxe_cli/parse.py` | 1672 | 1 (IOS-XE CLI → IR) | KEEP-AS-IS | — |
| `migration/codecs/juniper_junos/render.py` | 1503 | 1 (IR → Junos), monolithic fn | WATCH→SPLIT | CE-03 (P3) |
| `migration/codecs/arista_eos/parse.py` | 1387 | 1 (EOS → IR) | KEEP-AS-IS | — |
| `migration/codecs/mikrotik_routeros/parse.py` | 1291 | 1 (RouterOS → IR) | KEEP-AS-IS | — |
| `migration/codecs/cisco_iosxe/codec.py` | 1254 | codec contract (parse+render+probe+matrix) | KEEP-AS-IS | CE-04 (OBS) |
| `migration/canonical/intent.py` | 926 | 1 (canonical schema) | KEEP-AS-IS | — |
| `templates/definitions.html` | 926 | 1 (definitions page) | KEEP-AS-IS | — |
| `api/routes/ui.py` | 894 | **2 (page routes + Swagger re-skin)** | **SPLIT** | **CE-01 (P2)** |
| `models/migration.py` | 842 | 1 (migration data contract) | KEEP-AS-IS | — |
| `services/migration_pipeline.py` | 711 | 1 (orchestrator, frozen sigs) | KEEP-AS-IS | CE-05 (OBS) |
| `migration/canonical/port_names.py` | 614 | 1 (port-name bridge) | KEEP-AS-IS | — |
| `tools/sanitize.py` | 565 | 1 (canonical-walk redaction) | KEEP-AS-IS | — |
| `migration/target_profiles.py` | 544 | 1 (profile model + loader) | KEEP-AS-IS | — |
| `templates/migrate.html` | 2477 | 1 page, JS half-extracted | WATCH→SPLIT | CE-02 (P3) |

**Tally:** KEEP-AS-IS 12 · WATCH 2 · SPLIT 1. Findings: 1×P2, 2×P3,
2×OBSERVATION.

All 15 target files received a full verdict card. LOC figures were
re-verified against `wc -l` (all matched the snapshot exactly).

---

## 7. Open questions

1. **`ui.py` Swagger split — who owns the seam?** CE-01 is a clean
   relocation, but it touches `main.py` router registration and the
   base.html-token-duplication hazard. Whether the duplicated theme
   tokens should be deduplicated (single source in `base.html`,
   read by `/docs`) or stay copied with a CI drift-guard is a
   *theming-architecture* decision that overlaps CB/CA more than CE.
   Flagging for cross-fleet synthesis.

2. **`cisco_iosxe/codec.py` cross-codec coupling (CE-04).** The
   import-sibling-vs-duplicate inconsistency is squarely CC (codec
   architecture) + CD (coupling) territory. CE notes it but defers the
   verdict; the synthesis should fold CE-04 into whatever CC/CD
   conclude about the NETCONF↔CLI sibling relationship.

3. **`migrate.html` extraction completeness — is "done" defined?** The
   Contents map says the remaining inline JS "depend[s] on inline state
   that hasn't been extracted yet." Is there a target end-state (e.g.
   "the IIFE keeps only orchestration; every renderer is a partial"),
   or is the current split considered terminal? If terminal, CE-02
   downgrades to a pure OBSERVATION; if there is an intended end-state,
   CE-02's suggested next two extractions are the path.

4. **`juniper_junos/render.py` (CE-03) vs the other render files.**
   This chapter only had the four *parse* leaders plus Junos *render*
   in scope. The other render files (mikrotik 1025, fortigate 958,
   arista 916, aruba 845, iosxe_cli 817) were not CE targets — but if
   Junos render is monolithic, it is worth a one-line check by CC
   whether the other renders share the single-giant-function shape or
   already dispatch. If they dispatch, Junos render is an outlier worth
   the CE-03 refactor; if they are all monolithic, it is a codebase-
   wide render-style convention and CE-03 becomes a convention question
   for CA, not a per-file WATCH.

---

*End of CE chapter. Read-only review; no project files were modified.*

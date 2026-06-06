# 01 — Investigation CC: Codec architecture + per-codec file-by-file

**Reviewer lens:** CC — Codec Architecture + Per-Codec File-by-File
**Scope:** all of `netcanon/migration/codecs/` (`base.py`, `registry.py`,
`_input_shape.py`, `_mock/`, + the 8 real codecs)
**Commit:** `b08040c` (v0.1.2)
**Mode:** READ-ONLY. No project file was mutated. (Sub-agent
parallelisation was unavailable in this environment — no Task/Agent
dispatch tool was present — so every file was read directly by the
lead reviewer against the 1M context window. This is noted for the
adversarial pass: coverage is first-hand, not delegated.)

---

## 1. Scope & method

The codec layer is Layer 2 of the four-layer architecture (wire ↔
**codec** ↔ canonical ↔ pipeline). It owns the single most safety-
critical contract in the project: parse vendor text into a
`CanonicalIntent`, render a `CanonicalIntent` back to vendor text,
and declare — honestly — what survives that round-trip.

Method:

1. Read the contract docs first (`codecs/README.md`,
   `canonical/README.md`, `METHODOLOGY.md`, `AGENTS.md` Hard Rules)
   so intentional invariants weren't misread as defects.
2. Read the four contract-surface files in full (`base.py`,
   `registry.py`, `_input_shape.py`, `codecs/__init__.py`) plus the
   `_mock` reference codec.
3. Read all 8 real `codec.py` files in full (the metadata + `_CAPS` +
   probe + delegation surface) — this is where the contract is either
   honoured or broken.
4. Deep-read the NETCONF single-file codec (`cisco_iosxe/codec.py`,
   1254 LOC) since it is the principal architectural divergence.
5. Structural-skeleton + targeted deep-reads of the five parse
   god-files (junos 2455, iosxe_cli 1672, arista 1387, mikrotik 1291,
   aruba 1215) and the junos render god-file (1503), plus the shared
   render-error guards across all renderers.
6. Read every codec `port_names.py` (the cross-vendor bridge) +
   the canonical orchestrator (`canonical/port_names.py`) to assess
   bridge consistency.
7. Cross-checked the two Fleet-D candidate issues against the actual
   code, the pipeline's exception handling
   (`services/migration_pipeline.py`), the validator
   (`services/migration_validate.py`), and `CapabilityMatrix.classify`
   (`models/migration.py`).

Every file in the partition gets at least a one-line verdict in §4.

---

## 2. Executive summary

**The codec layer is the strongest part of the codebase I reviewed.**
The contract (`CodecBase`) is tight, the split-codec convention is
applied uniformly and is genuinely justified, the registry is minimal
and correct, the `_CAPS` declarations are exemplary (multiline cited
reasons, ship-before-wire discipline, Wave-commit citations), and the
cross-vendor port-name bridge is a clean vendor-agnostic mesh. The
shared-helper story (`_user_secrets`, `_tier3_detection`, `transforms`,
`_input_shape`) is consumed uniformly, not copy-pasted, with two
narrow exceptions noted below. Intentional vendor-grammar divergence
dominates the per-codec differences and is correctly *not* a DRY
defect.

The findings are mostly **consistency** defects, not correctness
crashes — which is exactly what you'd expect from a matrix-honest,
test-heavy codebase. The headline items:

* **`CC-01` (P2):** `juniper_junos/render.py:105` raises `TypeError`
  on its wrong-input guard. It is the *only* `raise TypeError` in the
  entire codec layer; all 7 other codecs raise `RenderError`. The
  pipeline catches it via the `except Exception` catch-all so it does
  **not** crash the worker, but the job lands in the wrong error
  bucket ("unexpected error in stage rendering" instead of "render
  failed") and violates the `CodecBase.render` docstring contract.
  **Fleet-D candidate #1: CONFIRMED** (with the blast-radius nuance
  that it is caught, not fatal).
* **`CC-02` (P3):** `is_secondary` on `CanonicalIPv4Address` /
  `CanonicalIPv6Address` is wired flag-driven in **arista_eos** but
  position-driven (and the flag left unset) in **cisco_iosxe_cli**.
  Cross-vendor `cisco_iosxe_cli → arista_eos` therefore loses the
  secondary designation. **Fleet-D candidate #2: REFUTED as stated**
  — the `is_secondary` *field* is genuinely unwired in
  `cisco_iosxe_cli`; the codec round-trips the `secondary` *keyword*
  only by positional convention, and the captured VRRP `secondary`
  regex group is dead.
* **`CC-03` (P3):** `PortIdentity.original` is required by the
  `CodecBase.classify_port_name` contract ("Must populate
  `.original = name`") but **arista_eos** and **juniper_junos**
  populate it on *zero* return paths, while the other 6 codecs
  populate it on *every* path. Currently latent (the orchestrator's
  verbatim fallback uses the dict key, not `identity.original`) but a
  documented-contract violation and a latent trap.
* **`CC-04` (P3 / OBSERVATION):** `/dhcp_servers/pool` (arista,
  underscore) vs `/dhcp-servers/pool` (junos, hyphen) — inconsistent
  spelling of the *same* capability, and **neither is ever emitted by
  the shared `_walk_canonical` walker**, so both `supported`
  declarations are inert (a soft matrix-honesty gap: a declared
  supported xpath that validation never exercises).

Nothing in the codec layer is a P0/P1. The two candidate issues are
both real-but-bounded.

---

## 3. The codec contract as-built

### 3.1 `CodecBase` (the abstract contract)

`base.py` defines a clean ABC. Required surface:

* `name` (ClassVar) — registry key.
* `capabilities` (abstract property) → `CapabilityMatrix`.
* `parse(raw) -> Any` (abstract) — raises `ParseError`.
* `render(tree) -> str` (abstract) — raises `RenderError`.

Optional/overridable with safe defaults:

* `iter_xpaths(tree)` — default handles flat `dict`; nested-tree
  codecs override. Used by the validator.
* `classify_port_name` / `format_port_identity` — default no-ops
  (`kind="unknown"` / `None`) so port-name participation is
  incremental.
* `probe(raw_prefix)` — default `None` (no opinion).
* Metadata classvars: `version_hint`, `input_format` (validated
  against `INPUT_FORMATS`), `direction`, `certainty`,
  `canonical_model`, `description`, `sample_input`, `output_extension`,
  `absorbs_svi_into_vlan`, `unsupported_rename_categories`.

The error taxonomy is well-designed: `CodecError` → `ParseError`
(carries `path`, `snippet`) and `RenderError` (carries `yang_path`).
The docstrings for `parse`/`render` *explicitly* state which exception
each raises. This is the contract that `CC-01` violates.

**Verdict:** Exemplary. The class docstring documents thread-safety
(fresh instance per call, stateless), the round-trip invariant, and
the rationale for every default. The only nit is that `parse` is typed
`-> Any` rather than `-> CanonicalIntent`; this is a deliberate Phase-0
hedge (the docstring says so) but now that all 8 codecs return
`CanonicalIntent`, the loose type lets the `_mock` codec's
`dict[str,str]` return slip through and is the root reason the
orchestrator and validator both need defensive `isinstance` guards.

### 3.2 `registry.py`

42 lines after docstring. `@register` decorator keyed on `cls.name`;
collision detection (raises `ValueError` if two classes claim the same
name; idempotent re-registration of the *same* class is allowed for
test reloads). `get_codec(name)` instantiates fresh; `list_codecs()`
sorted. Thread-safety reasoning is documented (registration is
import-time, dict effectively read-only at request time). The two
`ValueError`s here are the *only* non-`CodecError` raises in the layer
besides `CC-01`, and they fire at decoration time, never on a pipeline
path — appropriate.

**Verdict:** Minimal and correct. No notes.

### 3.3 `_input_shape.py`

Shared XML/JSON shape-sniffer. Every CLI/XML codec calls
`detect_input_shape(raw_prefix)` at the top of `probe()` (and the
junos/fortigate parsers call it inside `parse()`) so operators who
paste the wrong format hit a clean `ParseError`/`None` rather than a
silent empty render. The bounded-scan design (`max_lines=5`) tolerates
leading shell-echo/banner framing (the "Round 4.2 fix") — this is a
real lesson learned encoded as shared code. The Junos-curly-brace
non-conflict is documented and correct.

**Verdict:** Clean, well-reasoned, uniformly consumed. The single
shared shape-guard is exactly the right call vs per-codec inline
checks.

### 3.4 The split-codec convention — is the divergence justified?

**Yes, on both axes.**

*Split (parse.py/render.py) — 7 of 8 codecs.* `codec.py` keeps the
class (metadata + `_CAPS` + probe + port-name delegates) and delegates
`parse()`/`render()` to module-level `parse_intent`/`render_intent`.
Pure helpers (`_mask_to_prefix`, `_infer_iface_type`, mode tables)
live in `parse.py` and are re-imported into `render.py` — one
directional edge, no cycle. Test-pinned internal symbols are
re-exported via `codec.py.__all__` (fortigate, opnsense, aruba) so the
split didn't break tests. The convention is applied identically across
all 7, which is itself a strong consistency signal.

*Single-file — `cisco_iosxe` (NETCONF) only.* The README's
justification ("XML-tree traversal differs enough from CLI-text codecs
that the split offered no clarity win") holds up on reading. The
NETCONF codec's structure is fundamentally different: a nested-dict
intermediate mirroring the OpenConfig XML tree, ElementTree walks,
`defusedxml` parsing, and module-level pure helpers (`_parse_interface`,
`_render_interface`, `_walk`) that are already cohesively factored
*within* the single file. Splitting it would create artificial
boundaries. The 1254 LOC is earned by the XML-shape machinery, not by
a god-file mixing concerns. **The divergence is principled, not
accidental.**

`_walk_canonical` is deliberately kept at module level in
`cisco_iosxe_cli/codec.py` and imported by 7 other codecs'
`iter_xpaths`. This is the one place the split-codec convention bends
(a render/validate helper living in a `codec.py` rather than a
`parse.py`), and the docstring explains precisely why (preserving the
`from ...cisco_iosxe_cli.codec import _walk_canonical` import surface
every consumer relies on). Acceptable and documented.

### 3.5 The round-trip discipline

Uniform. Every codec's `parse()` returns a `CanonicalIntent`; every
`render()` consumes one. The round-trip invariant
(`parse(render(parse(raw))) == parse(raw)` at the canonical level) is
asserted per-codec in `tests/unit/migration/test_<vendor>.py` and
cross-checked by `test_real_captures.py`. Representation-bridging
transforms (`project_switchport_to_vlan`, `project_vlan_to_switchport`,
`project_svi_to_vlan`) are called as parse/render post-passes uniformly
where the vendor grammar needs them (e.g. junos render calls
`project_vlan_to_switchport` at render.py:119 with a cross-referenced
rationale). Hash handling routes through the shared `_user_secrets`
policy uniformly — junos render's hash-gate-first pattern
(render.py:161-174) explicitly mirrors cisco's `continue`-on-
unmigratable with a code citation. This is the matrix-honesty
discipline working as designed.

### 3.6 Probe / registry mechanics

Probe scoring follows the documented convention (95-100 unique marker,
75-94 format features, 40-74 structure-only). Every probe rejects
XML/JSON shape first via `detect_input_shape`. The collision-handling
between the two Cisco probes is notably careful: `cisco_iosxe_cli`
explicitly *defers* to Aruba's probe when an Aruba banner is present
(codec.py:415-419) and demotes bare `show running-config` from a
diagnostic signal to a confidence multiplier — a documented lesson
from a false-positive (the phrase is the operator's command, not a
Cisco banner). The NETCONF codec scores on the OpenConfig namespace.
No two probes claim the same unique marker.

**One observation:** two distinct codecs share `vendor_id=cisco_iosxe`
(`cisco_iosxe` NETCONF and `cisco_iosxe_cli`). This is intentional
(same vendor YAML, different wire formats) and the registry keys on
`name` not `vendor_id`, so there's no collision. But it does mean the
cross-mesh matrix has two "cisco_iosxe" columns that a casual reader
could conflate; the snapshot doc already calls this out.

---

## 4. Per-codec file-by-file verdicts

### 4.1 Contract surface

| File | LOC | Verdict |
|---|---:|---|
| `base.py` | 364 | **Exemplary.** Tight ABC, documented error taxonomy, safe defaults, port-name bridge contract. `parse -> Any` is a loose-typed Phase-0 hedge (now that all codecs return `CanonicalIntent`) that forces defensive guards downstream. |
| `registry.py` | 72 | **Correct.** Minimal import-time registry, collision + idempotent-reload handling, thread-safety documented. No notes. |
| `_input_shape.py` | 126 | **Clean.** Shared bounded XML/JSON sniffer; tolerant of banner framing; uniformly consumed. The right anti-duplication call. |
| `codecs/__init__.py` | 14 | Re-exports the contract symbols. Fine. |
| `_mock/__init__.py` | 18 | One-line export. Fine. |
| `_mock/codec.py` | 153 | **Good reference.** Flat `dict[str,str]` tree, exercises every `classify` branch (supported/lossy/unsupported). Proves the contract. Its non-`CanonicalIntent` return is the reason orchestrator/validator carry dict-fallback guards. |

### 4.2 `cisco_iosxe` (NETCONF, single-file)

| File | LOC | Verdict |
|---|---:|---|
| `__init__.py` | 30 | Export only. Fine. |
| `codec.py` | 1254 | **Strong, earned size.** Single-file divergence is justified (§3.4). `_CAPS` is the matrix-honesty showcase: the Wave-10γ-2 honest declaration of 16 unrendered surfaces as `unsupported`, with BOTH granular xpaths (for `validate_against`) AND top-level field markers (for `run_full_mesh.py`) — closing 6,677 spurious cells. `defusedxml` swap (line 100) with a precise XXE/billion-laughs threat-model comment. Strict YANG-boolean + prefix-range parsing (rejects "yes"/"1", rejects prefix>32) is correct fail-loud behaviour. `render` raises `RenderError` at both guards (649, 1052). **Two micro-nits:** (a) `_find_interfaces` (781-795) has a dead `for path in (...): pass` loop — vestigial, does nothing; (b) it has no `port_names.py` and does not override `classify_port_name`/`format_port_identity`, so it inherits the no-op base and silently does not participate in the rename mesh (consistent with it being a Phase-0.5 stub, but undocumented as a gap in its own class). |

### 4.3 `cisco_iosxe_cli` (split)

| File | LOC | Verdict |
|---|---:|---|
| `__init__.py` | 28 | Export only. Fine. |
| `codec.py` | 561 | **The canonical reference.** Hosts `_walk_canonical` (reused by 7 codecs) and `_IOS_BANNER_HITS`. `_CAPS` is the authoring exemplar cited by `METHODOLOGY.md` — every lossy/unsupported entry has a multiline cited reason, including the `/routing-instances/instance` lossy entry citing commit `40de39c`. Probe collision-handling with Aruba is the most careful in the tree. |
| `parse.py` | 1672 | **Earned god-file.** ~50 module-level compiled regexes (no per-call compilation), per-stanza dispatch (`_parse_interfaces`, `_parse_vlans`, `_parse_lags`, `_parse_static_routes`, `_parse_dhcp_pools`, `_parse_radius_servers`, `_parse_local_users`, `_parse_snmp`, `_parse_routing_instances`). Mgmt-VRF detection, link-local v6 inference (RFC 4291), VRRP classic+AF detection. Site of `CC-02`: the interface `ip address … secondary` parse drops the `secondary` token and never sets `is_secondary` (782-792); the VRRP `_VRRP_IP_RE` `secondary` named group (127) is captured but **never read** (982-983). |
| `render.py` | 817 | **Solid.** `render_intent` raises `RenderError` at the type-guard (70). Site of `CC-02` render side: secondary IP emitted by list position `idx>0` (287), VRRP secondary VIP emitted by position (447-451) — both position-driven, consistent with each other but inconsistent with arista's flag-driven approach. Hash-gate-on-unmigratable pattern present. |
| `port_names.py` | 321 | **Good, contract-compliant.** Sets `original=name` on every return path including `kind="unknown"` (225). Cisco 3-part `<stack>/<module>/<port>` + speed-prefix family. |

### 4.4 `arista_eos` (split)

| File | LOC | Verdict |
|---|---:|---|
| `__init__.py` | 46 | Export + scope notes. Fine. |
| `codec.py` | 353 | **Good.** Thin delegator, `_walk_canonical` reuse, well-cited `_CAPS`. Site of `CC-04`: declares `/dhcp_servers/pool` with an **underscore** (line 133), inconsistent with junos's hyphen and not emitted by `_walk_canonical`. |
| `parse.py` | 1387 | **Earned.** `_parse_stanzas`, `_parse_router_bgp` (a focused VRF/MAC-VRF RD/RT extractor — neighbor tables stay parse-and-ignore, consistent with `/routing/bgp` unsupported), `_apply_iface_subcommand`. Site of `CC-02` correct side: reads `tokens[1]=="secondary"` and stores `is_secondary` (960, 1003, 975, 1014). `_mask_to_prefix` is a byte-for-byte copy of cisco's (327-343) with an in-code comment acknowledging the duplication (`CC-05`). |
| `render.py` | 916 | **Solid.** `RenderError` at guard (155). VARP `ip address virtual … [secondary]` emitted flag-driven from `is_secondary` (584, 594, 612). |
| `port_names.py` | 190 | **Contract violation (`CC-03`).** Clean classify/format for EOS flat `Ethernet<N>` + 2-part breakout, BUT populates `original` on **zero** return paths (85, 92, 101, 111, 118) — including the `kind="unknown"` fallback where it matters most. Docstring even says "pass through verbatim" but doesn't set the field. |

### 4.5 `aruba_aoss` (split)

| File | LOC | Verdict |
|---|---:|---|
| `__init__.py` | 58 | Export + test-symbol re-export. Fine. |
| `codec.py` | 367 | **Good.** `absorbs_svi_into_vlan=True` sourced from `_svi_absorption.ABSORBS_SVI_INTO_VLAN` (single source of truth). `iter_xpaths` correctly adds the VLAN tagged/untagged-port xpaths (this is the only codec that populates them) on top of `_walk_canonical`. |
| `parse.py` | 1215 | **Earned.** Positional port-list parsing (`_parse_port_list`, `_expand_port_range`), VLAN-stanza SVI absorption, multi-line hash continuation handling (`_PASSWORD_HASH_CONTINUATION_RE`), VRRP-in-VLAN. The banner/`;`-comment grammar is genuinely distinct from Cisco. `_mask_to_prefix` is again a near-identical copy (`CC-05`). |
| `render.py` | 845 | **Solid.** `RenderError` at guard (373). SVI L3 absorbed into `vlan` stanza per the documented 3-codepath rule. |
| `port_names.py` | 219 | **Good, contract-compliant.** Sets `original=name` everywhere (118). `format_port_identity` returns `None` for `loopback` (no AOS-S concept) — exactly the documented case. |
| `_svi_absorption.py` | 111 | **Model doc-module.** Pure documentation + the `ABSORBS_SVI_INTO_VLAN` constant; zero logic. Ties 3 code paths (parse/render/port-name) to one grep target. This is the README's "shared invariant doc-module" pattern done right. |

### 4.6 `fortigate_cli` (split)

| File | LOC | Verdict |
|---|---:|---|
| `__init__.py` | 51 | Export + test-symbol re-export. Fine. |
| `codec.py` | 376 | **Good.** Carries a *corrected*-drift comment block (98-107) documenting that `unsupported_rename_categories` was wrongly `{"local_users"}` and was cleared under Option A — matrix-honesty self-documentation. Well-cited VRRP `_CAPS`. |
| `parse.py` | 950 | **Earned.** Recursive `config/edit/set/next/end` block model (`_ConfigBlock`/`_EditBlock`/`_parse_blocks`), per-`config`-path `_apply_*` dispatch, VRRP-in-interface. `_prefix_to_mask`/`_mask_to_prefix` live here and are re-exported (`CC-05`). |
| `render.py` | 958 | **Solid.** `RenderError` at guard (421). VRRP lossy edges (single `vrip`, single `vrdst`) emitted with `# review:` lines rather than silent drop. |
| `port_names.py` | 317 | **Good, contract-compliant.** `original=name` everywhere (210). Role-based `wan1`/`lan2` names stash `{"role": "wan"}` in `meta` — the documented vendor-hint pattern. |
| `vlan_heuristics.py` | 156 | **Good shared helper.** Pure VLAN-detection (`looks_like_vlan_iface`, `vlan_id_for`, `parent_for_vlan_iface`, `infer_iface_type`) shared between parse and render — one source of truth for "is this a VLAN iface?" given FortiOS's permissive grammar. Cited to a real capture. |

### 4.7 `juniper_junos` (split)

| File | LOC | Verdict |
|---|---:|---|
| `__init__.py` | 81 | Export + scope/grammar notes. Fine. |
| `codec.py` | 364 | **Good.** Thin delegator. `_CAPS` is rich and well-cited (per-VRF static-route lossy, anycast-MAC unsupported with the IRB-per-unit rationale). Delegates `render()` straight to `render_intent` — which is where `CC-01` lives. Declares `/dhcp-servers/pool` with a **hyphen** (148), inconsistent with arista's underscore (`CC-04`). |
| `parse.py` | 2455 | **Largest file; earned but at the watch-line.** Two-pass apply-groups dispatch (groups bucketed, replayed reverse-apply-order, then top-level), block-form→set-form auto-conversion, `_apply_*` per-stanza dispatch, VXLAN switch-options back-patch post-pass, VRRP-in-`family inet address`, anycast per-unit MAC scratch threaded onto both `iface_state` and `irb_state`. The apply-groups composition semantics (direct-intent-wins for scalars, accumulate for lists) are documented and correct. Genuinely irreducible Junos grammar; CE owns the split-vs-keep call. |
| `render.py` | 1503 | **Solid except `CC-01`.** `render_intent` raises **`TypeError`** at the type-guard (105) — the lone outlier in the layer. Otherwise excellent: deterministic ordering, interface-range structural collapse, sub-interface unit splitting, hash-gate-first mirroring cisco. The `_SUBIFACE_RE` channelized-parent fix (from prior session memory) is present. |
| `port_names.py` | 191 | **Contract violation (`CC-03`).** Clean media/FPC/PIC/port classification, BUT populates `original` on **zero** return paths (91-140), including the `kind="unknown"` fallback (140). |

### 4.8 `mikrotik_routeros` (split)

| File | LOC | Verdict |
|---|---:|---|
| `__init__.py` | 37 | Export only. Fine. |
| `codec.py` | 346 | **Good.** `device_classes=[router, firewall]`. Well-cited VRRP `_CAPS` (native `/interface vrrp`); VLAN-name lossy entry honestly documents the MikroTik "VLAN name IS the L3 iface name" quirk (the historical round-trip bug from project memory). |
| `parse.py` | 1291 | **Earned.** Section/`add`/`set` grammar (`_group_by_section`, `_parse_kv`, continuation-joining), `[ find default-name= ]` idiom, per-section dispatch (ethernet/vlan/bridge/bonding/tunnel/vrrp), interval parsing. The slash-prefixed CLI grammar is genuinely distinct. |
| `render.py` | 1025 | **Solid.** `RenderError` at guard (107). Emits MikroTik-conventional defaults so repeated cycles stabilise after one pass. |
| `port_names.py` | 345 | **Good, contract-compliant.** Largest port-names module (handles `ether`/`sfp`/`sfp-sfpplus`/`wlan`/`bridge`/`bond`/tunnel kinds); sets `original=name` on every path (193). |

---

## 5. Cross-codec consistency matrix

| Codec | Shape | `render` type-guard error | port-name bridge | `original` set? | `_CAPS` cited reasons | `_walk_canonical` reuse | `absorbs_svi` |
|---|---|---|---|---|---|---|---|
| `cisco_iosxe` (NETCONF) | **single-file** | `RenderError` ✓ | **none (no-op base)** | n/a | ✓ exemplary | ✓ | false |
| `cisco_iosxe_cli` | split | `RenderError` ✓ | full | ✓ all paths | ✓ exemplary | hosts it | false |
| `arista_eos` | split | `RenderError` ✓ | full | **✗ zero paths** | ✓ | ✓ | false |
| `aruba_aoss` | split | `RenderError` ✓ | full | ✓ all paths | ✓ | ✓ | **true** |
| `fortigate_cli` | split | `RenderError` ✓ | full | ✓ all paths | ✓ | ✓ | false |
| `juniper_junos` | split | **`TypeError` ✗** | full | **✗ zero paths** | ✓ | ✓ | false |
| `mikrotik_routeros` | split | `RenderError` ✓ | full | ✓ all paths | ✓ | ✓ | false |
| `opnsense` | split | `RenderError` ✓ | full | ✓ all paths | ✓ | ✓ | false |
| `_mock` | single-file | (n/a — accepts both) | none (no-op base) | n/a | ✓ (test stub) | no (flat dict) | false |

Two columns carry the cross-codec defects: the **error-type** column
(junos is the sole `TypeError`) and the **`original`** column (arista +
junos are the sole non-populators). Everything else is uniform.

DHCP-pool xpath spelling (not a column above): arista `/dhcp_servers/pool`
(underscore) · junos `/dhcp-servers/pool` (hyphen) · iosxe_cli declares
neither (parses DHCP but no `_CAPS` entry) · all others omit. `CC-04`.

---

## 6. Findings (severity-ordered)

### CC-01 — Junos render raises `TypeError`, not `RenderError`, on its input-type guard — P2

* **File:** `netcanon/migration/codecs/juniper_junos/render.py:104-108`
  (delegated to by `juniper_junos/codec.py:294-295`).
* **Claim:** The wrong-input-type guard in `render_intent` raises a
  bare `TypeError` where the `CodecBase.render` contract and all 7
  other codecs raise `RenderError`.
* **Evidence:**
  ```python
  # juniper_junos/render.py
  if not isinstance(tree, CanonicalIntent):
      raise TypeError(
          "juniper_junos.render: expected CanonicalIntent, got "
          f"{type(tree).__name__}"
      )
  ```
  A tree-wide grep confirms this is the **only** `raise TypeError` in
  `migration/codecs/`; every other render guard raises `RenderError`
  (`cisco_iosxe_cli:70`, `arista_eos:155`, `aruba_aoss:373`,
  `fortigate_cli:421`, `opnsense:74`, `mikrotik_routeros:107`,
  `cisco_iosxe:649`). The `base.py` `render` docstring states
  "Raises: RenderError". The docstring on `render_intent` itself
  (line 102) even *documents* it as raising `TypeError`, so the code
  and its own docstring agree with each other but disagree with the
  contract.
* **Blast radius (the nuance Fleet D flagged to verify):** The
  pipeline (`services/migration_pipeline.py:241-265`) has three
  handlers: `except ParseError`, `except RenderError`, and a final
  `except Exception` catch-all (line 255, `# noqa: BLE001 — honest
  catch-all`). The `TypeError` therefore **does not crash the
  worker** — it is caught by the catch-all and the job is marked
  `failed`. BUT:
  - The job `error` reads `"unexpected error in stage rendering: …"`
    instead of the dedicated `"render failed: …"` (line 250 vs 261).
  - The dedicated render-failure log line (252-254) is bypassed in
    favour of the generic "unexpected error" log (262-265).
  - Any caller that specifically catches `RenderError` (the contract-
    sanctioned behaviour, e.g. a future direct codec consumer outside
    the pipeline, or a test) would NOT catch this and would see an
    uncaught `TypeError`.
* **Why it matters:** This is a matrix-honesty/contract defect, not a
  crash. It is caught today only because the pipeline happens to have
  a catch-all; the catch-all exists for genuinely-unexpected bugs, and
  routing a *known* wrong-input condition through it muddies the
  signal an operator and a log-scraper see.
* **Suggested direction:** Change `raise TypeError(...)` →
  `raise RenderError(..., yang_path="/")` and update the
  `render_intent` docstring's `Raises:` to `RenderError`. One-line
  fix + one docstring line. Consider a cross-codec invariant test
  asserting every registered codec's `render(<wrong-type>)` raises
  `RenderError` (would have caught this and pins it forever).
* **Fleet-D candidate #1: CONFIRMED** (real; bounded — caught by the
  catch-all, so P2 not P1).

### CC-02 — `is_secondary` wired in arista_eos but position-driven (flag unset) in cisco_iosxe_cli — P3

* **Files:** `cisco_iosxe_cli/parse.py:782-792` &
  `cisco_iosxe_cli/render.py:285-288`;
  `arista_eos/parse.py:960,975,1003,1014` &
  `arista_eos/render.py:584,594,612`;
  canonical field at `canonical/intent.py:125,166`.
* **Claim:** Two codecs that share the IOS-family `ip address …
  secondary` semantics handle the canonical `is_secondary` flag
  differently. Arista is flag-driven (parse reads the keyword → sets
  `is_secondary`; render emits from the flag). IOS-XE-CLI is
  position-driven (parse drops the keyword and never sets the flag;
  render emits `secondary` for any address at list index > 0).
* **Evidence:**
  ```python
  # cisco_iosxe_cli/parse.py — secondary token captured but discarded
  current["ipv4"].append({"ip": ip_str, "prefix_length": prefix_len})
  # render.py — keyword reconstructed purely from position
  suffix = " secondary" if idx > 0 else ""
  ```
  ```python
  # arista_eos/parse.py — keyword read and stored on the canonical record
  is_secondary = len(tokens) >= 2 and tokens[1].lower() == "secondary"
  iface.ipv4_addresses.append(CanonicalIPv4Address(..., is_secondary=is_secondary, ...))
  # render.py — emitted from the flag
  if addr.is_secondary: line += " secondary"
  ```
  Additionally, the `cisco_iosxe_cli` VRRP regex `_VRRP_IP_RE`
  (`parse.py:125-129`) captures a `(?P<secondary>…)` named group that
  the consumer (`parse.py:980-983`) **never reads** — dead capture;
  the VRRP secondary VIP is likewise reconstructed by position on
  render (`render.py:447-451`).
* **Impact:** Same-vendor round-trips are fine for both (cisco's
  position convention is internally consistent; arista's flag is
  internally consistent). The drift bites **cross-vendor**: a
  `cisco_iosxe_cli` source parse produces addresses with
  `is_secondary=False` on every record, so a render into `arista_eos`
  (target) emits no `secondary` trailer on what were secondary
  addresses — the designation is lost. `arista_eos → arista_eos`
  preserves it.
* **Fleet-D candidate #2 verdict: REFUTED as stated.** The candidate
  claim was that `cisco_iosxe_cli` "may already parse/render the
  `secondary` IP keyword despite docs calling `is_secondary` unwired."
  In fact the docs are **correct**: the `is_secondary` *field* is
  genuinely unwired in `cisco_iosxe_cli`. What the codec does is
  round-trip the `secondary` *keyword* via positional convention,
  which is a different mechanism than the `is_secondary` flag. The
  candidate conflated keyword-behaviour with field-wiring.
* **Suggested direction:** Pick one mechanism. Either (a) wire
  `is_secondary` on the cisco parse side (set it when the token is
  present, emit from the flag on render — matching arista, and making
  cross-vendor faithful), or (b) document explicitly on
  `CanonicalIPv4Address.is_secondary` that IOS-family codecs rely on
  list-order and the flag is arista-only. Option (a) is the
  matrix-honest choice and also lets the dead VRRP `secondary` capture
  group earn its place. Low risk; covered by per-codec round-trip
  tests.

### CC-03 — `PortIdentity.original` left unpopulated by arista_eos and juniper_junos (contract violation) — P3

* **Files:** `arista_eos/port_names.py:85,92,101,111,118`;
  `juniper_junos/port_names.py:91,102,111,119,127,135,140`. Contract
  at `base.py:296-300`.
* **Claim:** The `classify_port_name` contract docstring states "Must
  populate `.original = name` so downstream fallbacks have the source
  name." 6 of 8 codecs comply on every return path; arista and junos
  comply on **none**.
* **Evidence:** A grep for `original=` across all `port_names.py`
  shows cisco_iosxe_cli, aruba_aoss, opnsense, mikrotik_routeros, and
  fortigate_cli each set `original=name` on every `return PortIdentity(…)`
  including the `kind="unknown"` fallback. arista's 5 returns and
  junos's 7 returns set it on zero. Arista's unknown-fallback even
  comments "pass through verbatim … source name" without setting the
  field.
* **Impact (latent today):** The orchestrator's verbatim fallback in
  `canonical/port_names.py::resolve` uses the local `name` parameter
  (lines 351, 365-366, 446-447), NOT `identity.original` — a grep for
  `.original` in the orchestrator returns no matches. So there is **no
  runtime bug today**. But: (a) it violates a written contract, which
  the matrix-honesty discipline treats as a defect (code and
  declaration must agree); (b) `format_port_identity` docstrings
  describe `original` as the "last-resort fallback," reserving the
  field for target formatters to consult — none do today, but a future
  one (or a future orchestrator refactor) that reads `identity.original`
  would silently break for arista/junos sources only, and the failure
  would be invisible in same-vendor tests.
* **Suggested direction:** Add `original=name` to every
  `return PortIdentity(...)` in the two offending modules (mechanical;
  ~12 call sites). Optionally promote to an enforced invariant: a
  parametrised test asserting
  `codec.classify_port_name("zzz").original == "zzz"` for every
  registered codec.

### CC-04 — Inconsistent + inert `dhcp pool` capability xpath (`/dhcp_servers/pool` vs `/dhcp-servers/pool`) — P3 / OBSERVATION

* **Files:** `arista_eos/codec.py:133` (`/dhcp_servers/pool`,
  underscore) vs `juniper_junos/codec.py:148` (`/dhcp-servers/pool`,
  hyphen). `cisco_iosxe_cli/codec.py` declares neither despite
  shipping `_parse_dhcp_pools`.
* **Claim:** The same capability is spelled two different ways across
  codecs, and neither spelling is ever emitted by the shared
  `_walk_canonical` walker — so both `supported` declarations are
  inert.
* **Evidence:** `_walk_canonical` (`cisco_iosxe_cli/codec.py:503-562`)
  has no DHCP-pool branch — it only yields
  `/interfaces/interface/dhcp-client-v6` for DHCP-adjacent state. So
  when `validate_against` walks a tree via `iter_xpaths`
  (→`_walk_canonical`), it never produces `/dhcp_servers/pool` or
  `/dhcp-servers/pool`, and the `_CAPS.supported` entry is never
  matched by `CapabilityMatrix.classify`. The cross-codec matrix test
  (`test_cross_codec_matrix.py`) is a "does not crash" smoke test that
  doesn't assert `iter_xpaths ⊆ supported`, so the dead entry isn't
  caught there either.
* **Why it matters:** This is a soft matrix-honesty gap — a codec
  *declares* a supported xpath that the validation harness can never
  see, and two codecs disagree on its name. The DHCP capability itself
  is truthful (both arista and junos genuinely have `_parse_dhcp_pools`
  + render paths), so this is cosmetic/consistency, not an
  over-claim. There is **no `KeyError` risk**:
  `CapabilityMatrix.classify` defaults unknown xpaths to "supported"
  (`models/migration.py:218`), so even if a walker emitted the path it
  would hit the no-lookup `supported` branch in
  `classify_tree`, not the `lossy_by_path[...]`/`unsupp_by_path[...]`
  dict index.
* **Suggested direction:** (1) Standardise the spelling
  (hyphenated `/dhcp-servers/pool` matches the rest of the canonical
  xpath vocabulary). (2) Either add a `/dhcp-servers/pool` branch to
  `_walk_canonical` (so the declaration is actually exercised by
  validation) or drop the dead `supported` entries. Pairs naturally
  with closing the gap that `cisco_iosxe_cli` parses DHCP but declares
  nothing.

### CC-05 — `_mask_to_prefix` duplicated byte-for-byte across 3+ codecs — OBSERVATION

* **Files:** `cisco_iosxe_cli/parse.py:279-297`,
  `arista_eos/parse.py:324-343`, `aruba_aoss/parse.py:310-325`
  (+ `fortigate_cli` ships its own `_mask_to_prefix`/`_prefix_to_mask`
  pair, re-exported from `codec.py`).
* **Claim:** The dotted-mask→prefix helper is functionally identical
  across the IOS-family codecs — same `ipaddress.IPv4Address` parse,
  same `"01" in bits` non-contiguity check, same `bits.count("1")` —
  differing only in the vendor-prefix string inside the `ParseError`
  message. The arista copy carries an in-code comment explicitly
  noting it is a "Local copy of the cisco_iosxe_cli helper … avoids a
  cross-codec import."
* **Why it's only an OBSERVATION:** The README sanctions
  intentional vendor-grammar divergence, and the authors made a
  *deliberate* choice to avoid a cross-codec import edge for one tiny
  helper. That is defensible. But this is the textbook case the
  shared-utility section of `codecs/README.md` describes ("When you
  find yourself wanting per-codec versions of … add to one of the
  helpers above instead of duplicating logic"): the logic is identical,
  vendor-agnostic, and IP-mask math has subtle edge cases (`/0`, `/32`,
  leading-zero truncation in `bin()`) you'd rather verify once.
* **Suggested direction:** Lift a single
  `mask_to_prefix(mask, *, vendor) ` (or a bare `mask_to_prefix` that
  raises a generic `ParseError` the caller re-wraps) into a shared
  `canonical/transforms.py` or a new `codecs/_ip_utils.py`, re-imported
  by the IOS-family parsers. Low priority; the current duplication is
  honest and tested per-codec.

### CC-06 — `cisco_iosxe` NETCONF codec silently opts out of the port-name mesh — OBSERVATION

* **File:** `cisco_iosxe/codec.py` (no `port_names.py`; no
  `classify_port_name`/`format_port_identity` override → inherits
  `base.py` no-ops).
* **Claim:** The NETCONF codec is the only real codec that does not
  override the port-name bridge methods, so it participates in the
  rename mesh as a pure no-op (`kind="unknown"` / `None`), silently
  leaving names verbatim. This is consistent with it being a
  Phase-0.5 `best_effort` stub, but it is **not declared** anywhere on
  the class (no `unsupported_rename_categories={"ports"}` entry, unlike
  the explicit `{"snmpv3"}` it does declare).
* **Why it's only an OBSERVATION:** The codec's render coverage is
  already honestly declared as interface+ipv4/ipv6-only via 16
  `unsupported` paths, and its `best_effort` certainty signals
  incompleteness. But the rename-mesh opt-out is a distinct surface
  from render coverage and isn't surfaced to operators the way the
  SNMPv3 gap is.
* **Suggested direction:** Either add a `port_names.py` reusing the
  `cisco_iosxe_cli` patterns (the name grammar is identical) or declare
  `unsupported_rename_categories=frozenset({"snmpv3", "ports"})` so the
  amber pane-compat banner fires for the ports rail when the NETCONF
  codec is the target.

### CC-07 — Vestigial dead loop in `_find_interfaces` — OBSERVATION (trivial)

* **File:** `cisco_iosxe/codec.py:786-790`.
* **Claim:** A `for path in ("./data/interfaces", "./{*}data/{*}interfaces"): pass`
  loop does nothing (the body is `pass`); the real work is the
  hand-walk immediately below it. Vestige of an abandoned approach.
* **Suggested direction:** Delete the loop and fold its explanatory
  comment into the hand-walk above. Trivial cleanup.

---

## 7. What's GOOD

This section is deliberately substantial because the codec layer
earns it.

1. **`_CAPS` authoring is the matrix-honesty discipline made
   concrete.** Every lossy/unsupported entry carries a multiline
   reason; many cite the exact commit that confirmed the round-trip
   (`40de39c` for iosxe_cli VRF, Wave-10γ-2 for NETCONF). The
   ship-before-wire pattern is visible everywhere: VRRP/anycast/
   per-VRF paths landed as `unsupported` across all 8 codecs in one
   wave, then flipped to `supported`/`lossy` per codec as wire-up
   landed, with the v0.2.0-planning doc pointers intact. The NETCONF
   codec's dual granular+top-level unsupported markers (closing 6,677
   spurious cells) is a genuinely sophisticated bit of audit
   engineering.

2. **The split-codec convention is uniform and the single-file
   exception is principled.** 7 codecs split identically; the one
   that doesn't (NETCONF) has a defensible structural reason and is
   already cohesively factored within its single file. Test-pinned
   internal symbols are re-exported so the split never broke tests.

3. **The port-name bridge is a clean vendor-agnostic mesh.** The
   `PortIdentity` meeting-point is richly documented (every field
   explains which vendors use it and why), the orchestrator never
   hard-codes a vendor pair, the drop/verbatim/override cascade is
   documented, and the `kind`-override hook (Cisco Mgmt-vrf →
   `kind=mgmt` set by the parser, cascading to every target's mgmt
   handling) is an elegant way to thread context into a pure
   name-based classifier without per-target code.

4. **Shared-helper consumption is uniform, not copy-paste.**
   `_user_secrets` (hash portability), `_tier3_detection` (silent-drop
   notification), `_input_shape` (format sniffing), and
   `transforms.py` (switchport↔vlan↔svi projections) are imported and
   used identically across codecs. The junos render hash-gate
   explicitly cross-references the cisco pattern by file:line. The only
   genuine duplication is `_mask_to_prefix` (`CC-05`), which the
   authors duplicated *deliberately* and documented.

5. **The doc-module pattern (`_svi_absorption.py`,
   `vlan_heuristics.py`) is exemplary.** `_svi_absorption.py` is pure
   documentation + one constant tying 3 code paths to a single grep
   target and a single source of truth for the class flag. This is the
   "cross-cutting invariant spanning 3+ code paths" pattern done
   exactly as the README prescribes.

6. **Fail-loud parsing where it counts.** The NETCONF codec rejects
   non-YANG-boolean `<enabled>` values and out-of-range prefix-lengths
   (with the explicit rationale that silently shipping a disabled
   interface is a night-long debugging session). The CLI mask parsers
   reject non-contiguous masks. Probes reject XML/JSON shape before
   scoring.

7. **Probe collision-handling is careful.** The two Cisco probes
   don't fight; iosxe_cli defers to Aruba on an Aruba banner and
   demotes the ambiguous `show running-config` phrase. This is the
   kind of thing that's only right after it's been wrong once — and
   the comments say so.

---

## 8. Coverage table

| Path | Read | Depth |
|---|---|---|
| `codecs/base.py` | ✓ | full |
| `codecs/registry.py` | ✓ | full |
| `codecs/_input_shape.py` | ✓ | full |
| `codecs/__init__.py` | ✓ | full |
| `codecs/_mock/__init__.py` | ✓ | full |
| `codecs/_mock/codec.py` | ✓ | full |
| `cisco_iosxe/__init__.py` | ✓ | header |
| `cisco_iosxe/codec.py` | ✓ | full (1254) |
| `cisco_iosxe_cli/__init__.py` | ✓ | header |
| `cisco_iosxe_cli/codec.py` | ✓ | full (561) |
| `cisco_iosxe_cli/parse.py` | ✓ | skeleton + targeted deep (secondary, mask, VRRP, globals) |
| `cisco_iosxe_cli/render.py` | ✓ | targeted (guard, secondary, VRRP) |
| `cisco_iosxe_cli/port_names.py` | ✓ | grep-confirmed `original` + spot |
| `arista_eos/__init__.py` | ✓ | header |
| `arista_eos/codec.py` | ✓ | full |
| `arista_eos/parse.py` | ✓ | skeleton + targeted deep (BGP/VRF, secondary, mask) |
| `arista_eos/render.py` | ✓ | targeted (guard, VARP secondary) |
| `arista_eos/port_names.py` | ✓ | full |
| `aruba_aoss/__init__.py` | ✓ | header |
| `aruba_aoss/codec.py` | ✓ | full |
| `aruba_aoss/parse.py` | ✓ | skeleton + targeted (mask, port-list) |
| `aruba_aoss/render.py` | ✓ | guard-confirmed |
| `aruba_aoss/port_names.py` | ✓ | grep-confirmed `original` |
| `aruba_aoss/_svi_absorption.py` | ✓ | full |
| `fortigate_cli/__init__.py` | ✓ | header |
| `fortigate_cli/codec.py` | ✓ | full |
| `fortigate_cli/parse.py` | ✓ | skeleton + header |
| `fortigate_cli/render.py` | ✓ | guard-confirmed |
| `fortigate_cli/port_names.py` | ✓ | grep-confirmed `original` |
| `fortigate_cli/vlan_heuristics.py` | ✓ | full |
| `juniper_junos/__init__.py` | ✓ | header |
| `juniper_junos/codec.py` | ✓ | full |
| `juniper_junos/parse.py` | ✓ | skeleton + targeted deep (two-pass dispatch, apply-groups) |
| `juniper_junos/render.py` | ✓ | targeted deep (guard `CC-01`, hash-gate, structure) |
| `juniper_junos/port_names.py` | ✓ | full |
| `mikrotik_routeros/__init__.py` | ✓ | header |
| `mikrotik_routeros/codec.py` | ✓ | full |
| `mikrotik_routeros/parse.py` | ✓ | skeleton |
| `mikrotik_routeros/render.py` | ✓ | guard-confirmed |
| `mikrotik_routeros/port_names.py` | ✓ | grep-confirmed `original` |
| `opnsense/__init__.py` | ✓ | header |
| `opnsense/codec.py` | ✓ | full |
| `opnsense/parse.py` | ✓ | header (via codec docstring + render xref) |
| `opnsense/render.py` | ✓ | guard-confirmed (accepts both shapes) |
| `opnsense/port_names.py` | ✓ | full |

**45 of 45 files** in the partition have a verdict. Cross-cutting
files consulted for blast-radius (out of partition, read-only):
`services/migration_pipeline.py`, `services/migration_validate.py`,
`models/migration.py` (`CapabilityMatrix.classify`),
`canonical/port_names.py` (orchestrator),
`tests/unit/migration/test_cross_codec_matrix.py`.

---

## 9. Open questions

1. **`CC-02` direction of fix.** Is the IOS-family list-order
   convention for secondary addresses an *intentional* canonical
   contract (i.e. "primary is always index 0, secondaries follow")
   that arista's flag *redundantly* duplicates, or is the flag the
   intended single source of truth? If the former, arista's flag is
   the anomaly and the doc should say "IOS-family relies on order";
   if the latter, cisco_iosxe_cli is under-wired. This is a canonical-
   model intent question (CB/CE own `intent.py`) — flagged for the
   synthesis pass to reconcile with the `CanonicalIPv4Address`
   docstring. `UNVERIFIED` which way the authors intend.

2. **`CC-04` / DHCP coverage.** Does any harness exercise the
   `dhcp_servers` round-trip end-to-end? `_walk_canonical` not
   emitting a dhcp xpath means the cross-vendor *validation* never
   classifies DHCP, yet `run_full_mesh.py` may exercise it via the
   field-disposition shape (the NETCONF codec declares `/dhcp_servers`
   as a top-level field marker, suggesting the mesh harness keys on
   `/{field}`). Worth confirming whether DHCP round-trip fidelity is
   actually audited or only unit-tested per-codec. `UNVERIFIED`.

3. **`classify_tree` dict-index fragility.** `classify_tree`
   (`migration_validate.py:85,87`) does `lossy_by_path[xpath]` /
   `unsupp_by_path[xpath]` as direct indexes. This is safe *given the
   current shared `_walk_canonical`* (every emitted xpath that
   `classify` routes to lossy/unsupported is a declared dict key) and
   `classify`'s string-equality matching. But the `classify` docstring
   says "Phase 1 adds glob/prefix matching" — once a pattern like
   `/foo/**` can match an xpath that isn't itself a dict key, this
   index will `KeyError`. Not a codec-layer bug today; flagged for CF
   (error-handling) as a latent trap that the codec layer's shared
   walker currently masks.

4. **Junos parse.py at the watch-line.** At 2455 LOC it is the
   largest file in the source tree. It is *earned* (irreducible Junos
   grammar + two-pass apply-groups + block/set dual-form), and CE owns
   the formal split-vs-keep verdict. From a codec-contract standpoint I
   have no concern; from a maintainability standpoint the
   apply-groups two-pass and the VXLAN back-patch post-pass are the two
   sub-systems that would most cleanly extract if a split is ever
   wanted. Deferred to CE.

---

*End of CC investigation chapter.*

# 01 — Investigation DD: Docstring accuracy + completeness

**Reviewer:** DD (Docstring Accuracy + Completeness)
**Fleet:** D (documentation review), read-only
**Commit:** `b08040c` / v0.1.2
**Date:** 2026-06-06

---

## 1. Scope & method

My lens is the **module / class / function docstrings inside `netcanon/`
source** — the API-documentation role of every docstring, as distinct
from DC (test-module docstrings) and DE (top-of-file orientation /
"header" blocks). Where a module docstring doubles as both an
orientation header *and* a behavioural-contract statement, I judge only
the contract-accuracy half and defer the orientation-prose half to DE.

Core questions, per the Fleet-D charter and the DD brief:

1. Do docstrings describe what the code does **now** (HEAD `b08040c`)?
2. Are Google-style `Args:` / `Returns:` / `Raises:` present where the
   signature is non-trivial?
3. **Do `Raises:` blocks match what is actually raised?** — with
   specific re-examination of the Junos `render_intent`
   `TypeError`-vs-`RenderError` inconsistency flagged on 2026-05-21.
4. Public functions / classes missing docstrings?
5. Stale "Phase N will…" futures that already shipped?
6. Pydantic `Attributes:` consistency on models.

**Method.** I deep-read the cross-cutting canonical model
(`migration/canonical/intent.py`, 926 LOC), the frozen-signature
pipeline (`services/migration_pipeline.py`, 711 LOC), the adapter
contract (`migration/codecs/base.py`), and all eight codecs'
`parse_intent` / `render_intent` / `codec.py` entrypoints. I then
sampled `models/*`, `storage/*`, `collectors/*`, `tools/*`,
`api/routes/*`, `security/*`, and the canonical sub-modules
(`transforms.py`, `loader.py`, the package `__init__.py` files). For the
`Raises:`-accuracy sweep I grepped every `raise` statement under
`migration/codecs/` and cross-checked each render/parse entrypoint's
documented exceptions against the actual guard. I cross-referenced the
2026-05-21 docs-audit fix-plan (Commits 8–14) and that audit's
per-cluster investigation files (cluster D + E) so I do not re-flag what
it deliberately closed or deliberately left.

Every claim below is grounded in `file:line`. Shaky inferences are
marked `UNVERIFIED`.

---

## 2. Executive summary

**The docstring surface is in genuinely good shape**, and the 2026-05-21
audit's docstring commits (8–14) landed accurately. Spot-verification of
the audit-touched surfaces confirms: `CanonicalIPv4Address` /
`CanonicalInterface` / `CanonicalIntent` carry per-attribute
`Attributes:` blocks and per-class Tier annotations
(`intent.py:86, 172, 788`); `MigrationJob` and `BackupJob` and
`CapabilityMatrix` Attributes blocks are now complete
(`models/migration.py:326`, `models/backup.py:93`,
`models/migration.py:162`); `file_store.py` hoisted `MAX_CONFIG_SIZE`
with rationale and documents `Raises: ValueError`
(`storage/file_store.py:88, 145`); the paramiko collector carries a
"Security model" section citing the AutoAddPolicy call sites
(`collectors/paramiko_collector.py:17–31`); `main.py` resolves the app
version from installed metadata (`main.py:213–222`); `tools/sanitize.py`
correctly references `CanonicalRADIUSServer.key`
(`tools/sanitize.py:35`); the netmiko collector inline list became a
pointer (`collectors/netmiko_collector.py:10–15`).

The findings that remain cluster into three groups:

* **One confirmed `Raises:` *contract* inconsistency** (DD-01,
  **HIGH**): the Junos `render_intent` is the sole codec that raises
  `TypeError` for the wrong-input-type guard, where the abstract
  `CodecBase.render` contract documents `RenderError` and all six other
  split-codec renders (plus the NETCONF codec) raise `RenderError`. The
  Junos docstring *honestly documents* the `TypeError` it raises, so the
  function is internally self-consistent — but it violates the base
  contract its own `codec.py` delegator inherits, and the pipeline's
  `except RenderError` path (`migration_pipeline.py:248`) will not catch
  it. This is the same defect flagged on 2026-05-21; it remains open.

* **A systematic stale-"Phase 0" framing the audit did not reach**
  (DD-02, **MEDIUM**): the engine's foundational module docstrings still
  describe the project as "Phase 0" with the canonical tree as an
  "opaque adapter-internal `dict[str, str]`" and transforms as "out of
  scope … Phase 2+", contradicting the shipped state where all 8 real
  codecs return a validated `CanonicalIntent` and `canonical/transforms.py`
  is a fully-shipped, documented module called by every render path.
  The prior audit examined `loader.py` (and chose EXPECTED-STALE) but
  did **not** examine `migration/__init__.py:13–15` or
  `canonical/__init__.py:5–7` against the transforms/canonical-tree
  shipped reality.

* **A handful of localized accuracy / completeness drifts** (DD-03…DD-08,
  LOW–MEDIUM): a `is_secondary` "ship-before-wire (v0.2.0)" tag that the
  IOS-XE CLI codec already contradicts; an in-prose route pointer that
  drifted from the renamed endpoint; the bare-delegator `codec.py`
  parse/render overrides carrying no docstring (so they silently inherit
  a base `Raises:` contract Junos breaks); the `migration_pipeline.py`
  "Phase 1+ collectors" slot wording; the Junos `render_intent`
  `Order:` block being a stale 6-item summary of a now much-richer
  render; and the `MigrationJob` double-documentation (Attributes block
  *and* per-field `#:` comments).

No finding rises to "dangerously wrong public API documentation". The
HIGH item is a genuine behavioural contract break (mis-typed exception),
not merely cosmetic.

---

## 3. Findings (severity-ordered)

### DD-01 — Junos `render_intent` raises `TypeError`, breaking the `CodecBase.render` `RenderError` contract — **HIGH**

* **File:line:** `netcanon/migration/codecs/juniper_junos/render.py:101–108`
  (docstring + raise); contract at
  `netcanon/migration/codecs/base.py:228–240`; pipeline catch at
  `netcanon/services/migration_pipeline.py:248`.
* **Claim:** Junos's render entrypoint documents and raises `TypeError`
  for a non-`CanonicalIntent` argument, where every other render
  entrypoint documents and raises `RenderError`, and where the abstract
  base method's docstring promises `RenderError`.
* **Evidence:**
  * Junos: docstring says `Raises: TypeError: If *tree* is not a
    :class:`CanonicalIntent`.` (render.py:101–102) and the body does
    `raise TypeError(...)` (render.py:105).
  * Base contract: `CodecBase.render` docstring says `Raises:
    RenderError: When *tree* contains paths the adapter cannot emit.`
    (base.py:235–239).
  * Every peer render raises `RenderError` for the identical guard:
    `arista_eos/render.py:155`, `aruba_aoss/render.py:373`,
    `cisco_iosxe_cli/render.py:70`, `fortigate_cli/render.py:421`,
    `mikrotik_routeros/render.py:107`, `opnsense/render.py:74`, and the
    single-file NETCONF codec `cisco_iosxe/codec.py:649`. Each of those
    docstrings says `Raises: RenderError: If *tree* is not a
    CanonicalIntent.`
  * The pipeline's render stage only catches `RenderError`
    (`migration_pipeline.py:248: except RenderError as exc:`). A
    `TypeError` from Junos therefore falls through to the generic
    `except Exception` catch-all (`migration_pipeline.py:255`) and is
    reported as an `"unexpected error in stage rendering"` rather than
    the clean `"render failed: …"` message the other codecs produce.
* **Why this is more than cosmetic:** the docstring is *accurate to the
  code* (it really does raise `TypeError`), so a pure
  docstring-vs-code reviewer might pass it. But the docstring documents
  the *wrong exception type relative to the contract it is implementing*.
  The honest fix is in the code (raise `RenderError` like every sibling)
  plus the one-word docstring change; a docs-only fix that merely
  renamed the documented exception would be lying about a real
  behavioural divergence. This is the exact item flagged on 2026-05-21
  and it is still open at `b08040c`.
* **Suggested direction:** change `render.py:105` to raise
  `RenderError("juniper_junos: tree must be a CanonicalIntent.",
  yang_path="/")` and update the docstring `Raises:` to `RenderError`.
  Add a one-line regression assertion to the Junos test module (DC's
  surface) that `render(<non-intent>)` raises `RenderError`. Flagged
  as out-of-scope-for-this-review code change via spawn_task.

### DD-02 — Engine "Phase 0" framing is stale: canonical tree + transforms have shipped — **MEDIUM**

* **File:line:** `netcanon/migration/__init__.py:2, 13–15`;
  `netcanon/migration/canonical/__init__.py:4–7`; with corroborating
  context in `netcanon/models/migration.py:4–6, 321–324` and
  `netcanon/migration/codecs/base.py:10, 220–221`.
* **Claim:** The migration engine's foundational module docstrings
  describe the system as "Phase 0" with the canonical tree as an opaque
  `dict[str, str]` and transforms as future "Phase 2+" work, but at
  v0.1.2 the canonical `CanonicalIntent` pydantic tree is the shipped
  reality for all 8 real codecs and `canonical/transforms.py` is a
  fully-shipped module.
* **Evidence:**
  * `migration/__init__.py:13–15`:
    > "Out of scope for Phase 0 (queued for Phase 0.5+): … *
    > Transforms, deploy, snapshot (Phase 2+)."
    But `canonical/transforms.py:1–40` is a real, documented module
    ("Shared post-parse transforms on `CanonicalIntent`") whose
    `project_vlan_to_switchport` is called by every render path (e.g.
    `arista_eos/render.py:172`, `cisco_iosxe_cli/render.py:82`,
    `juniper_junos/render.py:119`). Transforms have shipped.
  * `canonical/__init__.py:5–7`:
    > "Phase 0 code treats the 'tree' as an opaque adapter-internal type
    > and the mock adapter round-trips via plain `dict[str, str]`."
    This is now false for production: all 8 real codecs' `parse_intent`
    are typed `-> CanonicalIntent` and return the validated pydantic
    model (`arista_eos/parse.py:351`, `aruba_aoss/parse.py:759`,
    `cisco_iosxe_cli/parse.py:444`, `fortigate_cli/parse.py:881`,
    `juniper_junos/parse.py:77`, `mikrotik_routeros/parse.py:65`,
    `opnsense/parse.py:162`, and the NETCONF
    `cisco_iosxe/codec.py:532`). Only the `_mock` codec uses
    `dict[str, str]` (`_mock/codec.py:93`).
* **Audit-overlap caveat (important):** the 2026-05-21 audit explicitly
  examined `canonical/loader.py` and classified its "Phase 0 stub"
  framing as **EXPECTED-STALE** (cluster-E finding E-canon-7), choosing
  to leave it because `loader.py` genuinely still raises
  `NotImplementedError` on every call (`loader.py:43, 58`) and is a
  documented phased deliverable. **I am not re-flagging `loader.py`.**
  The audit's cluster-C investigation (`01-investigation-C.md:313–318`)
  separately *noted* the tension that `loader.py:38, 54` call Phase 0.5
  "future" while `RELEASE_PLAN.md` lists Phase 0.5 as shipped — but that
  tension was logged, not resolved, and it did not extend to the
  `migration/__init__.py` "transforms = Phase 2+" claim or the
  `canonical/__init__.py` "opaque dict" claim. Those two are what the
  audit did **not** reach and are squarely in scope as "things the audit
  missed."
* **Why MEDIUM not HIGH:** these are package-level orientation docstrings;
  they do not mis-document a callable's contract, and a contributor who
  reads the actual code sees `CanonicalIntent` immediately. But the "tree
  is an opaque dict" sentence is *affirmatively wrong* about the
  shipped data model and will actively mislead a new contributor about
  the single most load-bearing type in the codebase.
* **Note on the DD/DE boundary:** these are module/package orientation
  blocks, which leans DE. I raise them under DD because the specific
  defect is a *behavioural-accuracy* claim ("tree is a dict",
  "transforms out of scope"), not a header-convention/orientation
  judgment. DE may also touch these; recommend joint ownership in
  synthesis.
* **Suggested direction:** reframe `canonical/__init__.py` and
  `migration/__init__.py`'s "out of scope" block to state that the
  canonical tree shipped as pydantic `CanonicalIntent` (the libyang
  context in `loader.py` remains the deferred Phase-0.5 item), and move
  "Transforms" out of the Phase-2+ "out of scope" list with a pointer to
  `canonical/transforms.py`. Keep the `loader.py` stub framing as-is per
  the prior audit's deliberate decision.

### DD-03 — `CanonicalIPv4Address.is_secondary` documented "ship-before-wire (v0.2.0)" but already wired for IOS-XE CLI — **MEDIUM**

* **File:line:** `netcanon/migration/canonical/intent.py:90–97`; contradicted
  by `cisco_iosxe_cli/parse.py:127, 782–785` + `render.py:279–287`.
* **Claim:** The `is_secondary` attribute doc says it is
  "Ship-before-wire (v0.2.0) — codecs that haven't been updated still
  treat all addresses as primary", implying no codec wires it yet — but
  the IOS-XE CLI codec parses the `secondary` keyword into the field and
  re-emits it on render.
* **Evidence:**
  * Doc: "`is_secondary`: … Ship-before-wire (v0.2.0) — codecs that
    haven't been updated still treat all addresses as primary."
    (intent.py:94–97).
  * IOS-XE CLI parse captures it: regex group
    `(?P<secondary>\s+secondary)?` (parse.py:127) with the comment "set
    the `secondary` keyword for index>=1" (parse.py:782–785).
  * IOS-XE CLI render emits it: `suffix = " secondary" if idx > 0 else
    ""` (render.py:287).
  * The *same docstring* even names the vendors that mark secondaries
    ("Cisco / Arista mark these with a `secondary` trailer", intent.py:92–93),
    which sits awkwardly beside the blanket "ship-before-wire / treat all
    as primary" tag.
* **Interpretation caveat (`UNVERIFIED` nuance):** "ship-before-wire" may
  be intended to mean *cross-vendor completeness* (the field exists on
  the schema before every codec round-trips it), in which case the tag
  is half-true. But the literal sentence "codecs that haven't been
  updated still treat all addresses as primary" reads as "no codec has
  been updated", which is false. I did not exhaustively check all 8
  codecs for secondary support — at least IOS-XE CLI wires it, which is
  enough to make the blanket claim misleading.
* **Suggested direction:** soften to "wired on the codecs whose grammar
  has a secondary-address marker (IOS-XE CLI today); other codecs treat
  all addresses as primary until updated" — mirroring how the
  `virtual_gateway_address` doc just below it correctly scopes its
  ship-before-wire claim per-codec.

### DD-04 — Split-codec `codec.py` `parse`/`render` overrides have no docstring, silently inheriting a `Raises:` contract Junos violates — **MEDIUM**

* **File:line:** seven codecs' delegators, e.g.
  `arista_eos/codec.py:282–283`, `aruba_aoss/codec.py:268–269`,
  `fortigate_cli/codec.py:317–318`, `cisco_iosxe_cli/codec.py:343–344`,
  `mikrotik_routeros/codec.py:277–278`, `opnsense/codec.py:303–304`,
  `juniper_junos/codec.py:294–295`.
* **Claim:** Every split codec's class-level `render(self, tree)` (and
  most `parse(self, raw)`) is a one-line delegator with **no docstring**:
  it relies on the sibling `render_intent` / `parse_intent` function's
  docstring carrying the API documentation. That is a reasonable
  convention, but it means the *public method* a caller sees on the codec
  object inherits the abstract base's `Raises: RenderError` promise
  (base.py:235–239) — which Junos's delegated `render_intent` then
  breaks by raising `TypeError` (see DD-01).
* **Evidence:** `juniper_junos/codec.py:294–295`:
  ```
  def render(self, tree: Any) -> str:
      return render_intent(tree)
  ```
  No docstring; `help(JunosCodec.render)` shows the base contract's
  `RenderError`, while the actual behaviour is `TypeError`. The other six
  delegators are the same shape but their `render_intent` honours the
  contract, so only Junos is *wrong* — but all seven are
  *undocumented at the method level*.
* **Why this matters for DD specifically:** the abstract base's `Raises:`
  block is the only API documentation a tooltip/`help()` consumer gets
  for these methods. It is correct for 7 of 8 codecs and silently wrong
  for Junos. Fixing DD-01 closes the wrongness; the missing per-method
  docstrings are a lower-severity completeness gap.
* **Suggested direction:** acceptable to leave the delegators
  docstring-less *if* DD-01 is fixed (then the inherited contract is
  uniformly honoured). Optionally add a one-liner `"""Delegates to
  :func:`render_intent`."""` for IDE discoverability. The
  `cisco_iosxe` (NETCONF) single-file codec already documents its
  `parse`/`render` fully (`codec.py:533, 625`) and is the good model.

### DD-05 — `migration.py` route docstring points at `/plan/snmpv3_users`, but the shipped route is `/plan/snmpv3` — **LOW**

* **File:line:** `netcanon/api/routes/migration.py:270` vs the actual
  route decorator at `migration.py:496`.
* **Claim:** The `plan_migration_ports` docstring enumerates the sibling
  per-pane endpoints as "(`/plan/vlans`, `/plan/snmp`,
  `/plan/local_users`, `/plan/snmpv3_users`)" but the registered route is
  `/plan/snmpv3`, not `/plan/snmpv3_users`.
* **Evidence:**
  * Docstring: `migration.py:270` lists `/plan/snmpv3_users`.
  * Actual route: `@router.post("/plan/snmpv3", …)` at `migration.py:496`;
    the module header correctly lists `POST
    /api/v1/migration/plan/snmpv3` (migration.py:51).
* **Note:** the 2026-05-21 audit (Commit 11, E-api-1) fixed the
  *route-level* token `/plan/local-users` → `/plan/local_users` but did
  not catch this in-prose pointer inside a neighbouring handler's
  docstring. Pure drift, harmless at runtime (it's prose, not a route),
  but it points an operator/contributor at a 404 URL.
* **Suggested direction:** `/plan/snmpv3_users` → `/plan/snmpv3` at
  migration.py:270.

### DD-06 — `migration_pipeline.run_plan` "Phase 1+ collectors" wording in `Args:` is stale framing — **LOW**

* **File:line:** `netcanon/services/migration_pipeline.py:152–155`.
* **Claim:** The `raw_text` arg doc says "In Phase 1+ this slot is fed by
  the existing collectors layer, matching the backup engine's design."
  The collectors layer (`netcanon/collectors/`) is shipped at v0.1.2, so
  the future-tense "In Phase 1+" framing dates the doc.
* **Evidence:** `migration_pipeline.py:152–154`:
  > "raw_text: Raw config text from *source*. In Phase 1+ this slot is
  > fed by the existing collectors layer, matching the backup engine's
  > design."
  The collectors exist now (`collectors/paramiko_collector.py`,
  `netmiko_collector.py`), and the pipeline is a "load-bearing migration
  engine" per its own module docstring (`migration_pipeline.py:2`).
* **Audit note:** Commit 14 touched this file's docstrings under a
  **FROZEN-signature** rule (docstring-only edits to the future-commit
  categories list at `:323–333` and the public-surface cross-ref). It
  did not revisit the `Args:` phase wording. Re-confirming: the frozen
  signatures (`run_plan`, `run_plan_with_rename`,
  `run_plan_with_overrides`) are intact (`migration_pipeline.py:126,
  295, 670`) and their docstrings are otherwise excellent and current.
* **Suggested direction:** "In Phase 1+ this slot is fed by …" →
  "This slot is fed by the collectors layer (`netcanon.collectors`),
  matching the backup engine's design." Trivial, docstring-only,
  signature-safe.

### DD-07 — Junos `render_intent` `Order:` block is a stale 6-item summary of a now much-richer render — **LOW**

* **File:line:** `netcanon/migration/codecs/juniper_junos/render.py:87–96`
  (the `Order:` list) vs the module docstring's accurate richer
  enumeration at `render.py:6–26`.
* **Claim:** The `render_intent` docstring's `Order:` block lists six
  emission steps (host-name → login user → interfaces → vlans →
  routing-options static → snmp). The render now also emits domain / DNS
  / NTP / syslog, switch-options (VTEP), routing-instances, VRRP groups,
  anycast-gateway, and apply-groups — all accurately described in the
  *module* docstring (render.py:6–26) but absent from the function-level
  `Order:` list, which reads as an exhaustive ordering.
* **Evidence:** the module docstring (render.py:6–26) enumerates
  "switch-options … routing-instances … apply-groups + group-content …
  VRRP groups … anycast-gateway"; the function `Order:` (render.py:88–96)
  stops at six items and does not mention any of those. A reader trusting
  the function docstring's `Order:` as canonical would think Junos emits
  no VRF / VRRP / anycast output.
* **Why LOW:** the authoritative detail lives correctly in the module
  docstring directly above; the function `Order:` is a summary that
  drifted. Not wrong about what it lists, just incomplete.
* **Suggested direction:** either append the missing surfaces to the
  `Order:` list or replace it with "see the module docstring for the full
  deterministic emission order."

### DD-08 — `MigrationJob` is double-documented (Attributes block + per-field `#:` comments) — **LOW** (consistency)

* **File:line:** `netcanon/models/migration.py:326–460` (Attributes
  block) and `:475–548+` (per-field `#:` Sphinx comments).
* **Claim:** `MigrationJob` documents most fields **twice** — once in the
  class `Attributes:` block (the audit's Commit-13 addition) and again as
  per-field `#:` comments on the field declarations. The two are
  near-verbatim duplicates (e.g. `warnings` at :338–342 and again at
  :475–480). This is not *wrong*, but it is a maintenance hazard: a
  future field-doc edit must be made in two places or the two drift.
* **Evidence:** compare the `port_renames` prose at :343–348 with the
  identical `#:` block at :482–488. Contrast with `CanonicalInterface`
  (intent.py:172–261), which uses *only* the Attributes block, and
  `CanonicalSNMP` (intent.py:463–470), which uses *only* `#:` comments —
  the codebase is inconsistent about which pattern to use.
* **Audit context:** the fix-plan's E-mod-1 ("`MigrationJob` Attributes
  (15 missing) — decide pattern + apply") explicitly called for a pattern
  decision; the result kept both. Per AGENTS.md's "prefer one canonical
  surface" spirit this should be one or the other.
* **Suggested direction:** pick one (the Attributes block is the more
  common choice across `intent.py`) and drop the redundant `#:` comments,
  or vice-versa. Cosmetic; no runtime impact.

---

## 4. `Raises:`-accuracy sweep

I grepped every `raise` under `migration/codecs/` and matched each
parse/render **entrypoint** against its documented `Raises:`. Internal
helper raises (e.g. `_prefix_to_mask`) are noted but not scored as
entrypoint mismatches.

| Function | Documented `Raises:` | Actually raised | Verdict |
|---|---|---|---|
| `juniper_junos.render_intent` (render.py:80) | `TypeError` (render.py:102) | `TypeError` (render.py:105) | **MISMATCH vs base contract** — code matches its own doc, but both diverge from `CodecBase.render` → `RenderError` and from all 6 peers. **DD-01.** |
| `arista_eos.render_intent` (render.py:148) | `RenderError` (render.py:152) | `RenderError` (render.py:155) | ✅ match |
| `aruba_aoss.render_intent` (render.py:365) | `RenderError` (render.py:370) | `RenderError` (render.py:373) | ✅ match |
| `cisco_iosxe_cli.render_intent` (render.py:62) | `RenderError` (render.py:67) | `RenderError` (render.py:70) | ✅ match |
| `fortigate_cli.render_intent` (render.py:413) | `RenderError` (render.py:417) | `RenderError` (render.py:421) | ✅ match |
| `mikrotik_routeros.render_intent` (render.py:100) | `RenderError` (render.py:104) | `RenderError` (render.py:107) | ✅ match |
| `opnsense.render_intent` (render.py:55) | `RenderError` (render.py:67) | `RenderError` (render.py:74) | ✅ match (also documents the dict-vs-intent dual path — accurate) |
| `cisco_iosxe.render` (codec.py:624, NETCONF) | `RenderError` (codec.py:640–642) | `RenderError` (codec.py:649) | ✅ match |
| `juniper_junos.parse_intent` (parse.py:77) | `ParseError` (parse.py:84–87) | `ParseError` ×4 (parse.py:90, 98, 115, 127) | ✅ match — doc enumerates empty / XML / `{`-not-blockform / block-conversion-failure; all four raise sites present |
| `arista_eos.parse_intent` (parse.py:351) | `ParseError` (parse.py:355–357) | `ParseError` (parse.py:360, 367, 372) | ✅ match |
| `aruba_aoss.parse_intent` (parse.py:759) | `ParseError` (parse.py:763–765) | `ParseError` (parse.py:768, 776, 781) | ✅ match |
| `cisco_iosxe_cli.parse_intent` (parse.py:444) | `ParseError` (parse.py:448–450) | `ParseError` (parse.py:453, 465) | ✅ match |
| `fortigate_cli.parse_intent` (parse.py:881) | `ParseError` (parse.py:888–890) | `ParseError` (parse.py:893, 900) | ✅ match |
| `mikrotik_routeros.parse_intent` (parse.py:65) | `ParseError` (parse.py:69–71) | `ParseError` (parse.py:74, 82, 88) | ✅ match |
| `opnsense.parse_intent` (parse.py:162) | `ParseError` (parse.py:175–176) | `ParseError` ×3 incl. `DefusedXmlException`→`ParseError` re-raise (parse.py:182, 188, 194) | ✅ match — XXE/entity-bomb re-raised as `ParseError`, consistent with doc |
| `cisco_iosxe.parse` (codec.py:532, NETCONF) | `ParseError` (verified body raises at codec.py:558, 564, 572, 817…) | `ParseError` | ✅ match |
| `_mock.parse` (codec.py:93) | `ParseError` (codec.py:96–98) | `ParseError` (codec.py:103, 108, 114) | ✅ match |
| `CodecBase.parse` (base.py:217, abstract) | `ParseError` (base.py:223–224) | — (abstract) | ✅ contract correct |
| `CodecBase.render` (base.py:228, abstract) | `RenderError` (base.py:235–239) | — (abstract) | ✅ contract correct **but Junos delegate breaks it — DD-01** |
| `canonical/loader.get_libyang_context` (loader.py:34) | `NotImplementedError` (loader.py:37–41) | `NotImplementedError` (loader.py:43) | ✅ match (stub by design) |
| `canonical/loader.validate_against_canonical` (loader.py:50) | `NotImplementedError` (loader.py:53–56) | `NotImplementedError` (loader.py:58) | ✅ match (stub by design) |
| `storage/file_store.FileConfigStore.save` (file_store.py:124) | `ValueError` (file_store.py:145–148) | `ValueError` (file_store.py:153) | ✅ match (audit E-store-1) |
| `storage/file_store.FileConfigStore.__init__` (file_store.py:110) | `OSError` (class-level Raises, file_store.py:106–107) | `mkdir` may raise `OSError` (file_store.py:117) | ✅ match |

**Helper-raise notes (not entrypoint mismatches):**
* `fortigate_cli/parse.py:87` raises `RenderError` from inside the
  *parse* module — but the function is `_prefix_to_mask`, a **render-path
  helper** that lives in parse.py for import-cycle reasons (documented at
  parse.py:81–85). The raise type is correct for its (render) caller; the
  function is undocumented for `Raises:` but it is private. Not a finding.
* `registry.py:43, 48` raise `ValueError` for duplicate/unknown codec
  registration — `register()` / `get_codec()` docstrings should ideally
  note these; minor, not pursued.

**Net `Raises:`-mismatch count: 1** (DD-01, Junos render
`TypeError`-vs-contract). Every other documented `Raises:` block matches
the code exactly. This is a strong result and confirms the audit's
Commit-10 propagation of the Google-style `Raises:` sections was done
accurately for the six codecs it touched.

**Sub-observation on the Commit-10 "Args/Returns/Raises" claim:** the
fix-plan (Commit 10) stated each codec's `parse_intent`/`render_intent`
would get "Args, Returns, Raises blocks". In practice the landed
docstrings (and the reference template at
`cisco_iosxe_cli/parse.py:444`) carry **only `Raises:`** — no `Args:` or
`Returns:` sections. Given these functions have a single obvious `raw:
str` / `tree: Any` parameter and an obvious `-> CanonicalIntent` /
`-> str` return, omitting `Args:`/`Returns:` is defensible and the
`opnsense.render_intent` doc (render.py:59–64) *does* add an `Args:`
where the dual dict/intent path warrants it. I do **not** flag the
missing `Args:`/`Returns:` as a defect — but note the fix-plan's wording
slightly over-described what shipped. (Informational.)

---

## 5. Missing-docstring inventory (public surfaces)

Sampled across the source tree. "Public" = no leading underscore and
reachable as a module/class/function API.

* **Split-codec `parse`/`render` class methods — no docstring**
  (7 codecs): `arista_eos/codec.py:282`, `aruba_aoss/codec.py:268`,
  `fortigate_cli/codec.py:317`, `cisco_iosxe_cli/codec.py:343`,
  `mikrotik_routeros/codec.py:277`, `opnsense/codec.py:303`,
  `juniper_junos/codec.py:294`. Inherit the base contract (DD-04).
  Acceptable-but-suboptimal; the underlying `*_intent` functions are
  documented.
* **Codec `iter_xpaths` overrides — mostly no docstring**:
  `arista_eos/codec.py:289`, `aruba_aoss/codec.py:275`,
  `fortigate_cli/codec.py:324`, `juniper_junos/codec.py:301` have none;
  `cisco_iosxe_cli/codec.py:350` and `opnsense/codec.py:310` and
  `mikrotik_routeros/codec.py:284` do have one-liners. Inconsistent. The
  abstract `CodecBase.iter_xpaths` (base.py:242) is well-documented, so
  the inherited contract covers them; LOW.
* **Codec `classify_port_name` / `format_port_identity` delegators — no
  docstring**: e.g. `juniper_junos/codec.py:310, 313`. Inherit the
  thoroughly-documented base contracts (base.py:281, 305). Acceptable.
* **`JunosCodec` class docstring is a single line** (codec.py:77):
  "Bidirectional codec for Juniper Junos `set`-form configuration." —
  thin compared to the rich module docstring above it (codec.py:1–53),
  but the class metadata is self-describing via ClassVars and the module
  docstring carries the detail. Consistent with the other split codecs'
  class docstrings; not a finding.
* **No public *function* or *class* was found entirely undocumented**
  where a docstring is conventionally expected (every module-level
  public function and every pydantic model class I sampled has at least a
  summary line). The gaps are confined to the trivial-delegator methods
  above.

**Verdict:** no material missing-docstring defect on a non-trivial public
surface. The delegator gap is uniform and contract-covered.

---

## 6. What's GOOD

The docstring surface is one of the stronger parts of this codebase, and
the 2026-05-21 audit's docstring commits verifiably landed:

* **The canonical model (`intent.py`) is exemplary.** Every class carries
  a one-line summary with its Tier annotation in-line (e.g.
  "(Tier 1 — auto-translatable IP primitive)" at intent.py:86; "(Tier 2 —
  FHRP redundancy; cross-vendor grammar diverges)" at intent.py:491), and
  the non-trivial models have full `Attributes:` blocks with per-vendor
  grammar references that are genuinely useful (the `CanonicalVRRPGroup`
  and `CanonicalSNMPv3User` docstrings at intent.py:490–594 and 365–446
  are small reference manuals). The module docstring's Tier 1/2/3 +
  ship-before-wire + wire-through taxonomy (intent.py:31–70) is coherent
  and matches the field declarations.
* **The pipeline (`migration_pipeline.py`) is thoroughly and accurately
  documented**, including the frozen-signature Hard Rules block
  (lines 87–98), the five per-pane override categories (lines 38–50),
  the sentinel `None`-vs-`{}`-vs-`{k:v}` semantics (lines 51–67), and the
  capture-first transform contract (lines 68–86). The Commit-14
  future-categories pointer to `docs/v0.2.0-planning/` (lines 329–333) is
  in place and the three frozen signatures are intact.
* **`Raises:` accuracy is near-perfect** — 22 of 23 entrypoints match
  exactly; the lone exception (Junos) is itself self-consistent and only
  diverges from the base contract.
* **Audit-touched surfaces verified correct:** `MigrationJob` /
  `BackupJob` / `CapabilityMatrix` Attributes blocks complete;
  `MAX_CONFIG_SIZE` hoisted with rationale + `Raises: ValueError`;
  paramiko "Security model" section with call-site citations;
  `main.py` metadata-driven version; `sanitize.py` `.key` reference;
  netmiko inline-list → pointer; `cisco_iosxe_cli` description no longer
  claims "secondary IPs ignored".
* **The `cisco_iosxe` NETCONF codec self-documents honestly as a "Phase
  0.5 stub"** with per-path `unsupported` reasons spelling out exactly
  what the stub render omits (codec.py:239–434) — this is the *good*
  kind of phase language: it accurately describes a genuinely incomplete
  surface, unlike the stale Phase-0 framing in DD-02.
* **`tools/sanitize.py`** carries an excellent, current module docstring
  enumerating every field-typed redaction rule with shipped field names
  (sanitize.py:16–53).
* **`security/credentials.py`** documents the three-tier Fernet key
  resolution precisely and matches the code's resolution order
  (credentials.py:4–30).

---

## 7. Coverage table

| Surface | Files read (depth) | Findings | Notes |
|---|---|---|---|
| `migration/canonical/intent.py` | full deep-read (926 LOC) | DD-03 | Tier annotations + Attributes verified accurate; one stale ship-before-wire tag |
| `services/migration_pipeline.py` | full deep-read (711 LOC) | DD-06 | Frozen sigs intact; one stale "Phase 1+" `Args:` phrase |
| `migration/codecs/base.py` | full deep-read | (DD-01 contract) | Abstract contracts correct; Junos delegate breaks render contract |
| 8 codecs `parse_intent`/`render_intent` | all 14 entrypoints read | DD-01, DD-07 | `Raises:` swept; Junos `TypeError` + stale `Order:` |
| 8 codecs `codec.py` entrypoints | parse/render delegators read | DD-04 | Undocumented delegators inheriting base contract |
| `models/migration.py` | deep-read (842 LOC, key classes) | DD-08 | Attributes complete; double-documentation pattern |
| `models/backup.py` | BackupJob read | — | Attributes complete (audit E-mod-2 ✅) |
| `storage/file_store.py` | deep-read | — | Exemplary; audit E-store-1/2 ✅ |
| `collectors/paramiko_collector.py` | header + security section | — | Security model section ✅ (audit E-col-1) |
| `collectors/netmiko_collector.py` | header | — | Pointer-ized ✅ (audit E-col-2) |
| `tools/sanitize.py` | header read | — | Accurate; `.key` ✅ |
| `api/routes/migration.py` | header + handlers sampled | DD-05 | Route-pointer drift in one handler docstring |
| `security/credentials.py` | header | — | Accurate |
| `migration/__init__.py`, `canonical/__init__.py`, `canonical/loader.py`, `canonical/transforms.py` | full read | DD-02 | Stale Phase-0 framing (loader stub left per prior audit) |
| `models/*` (diff/device/schedule/validators/device_profile) | sampled via grep | — | No entrypoint-level defect surfaced in sweep |
| `api/routes/*` (ui/backups/configs/etc.) | sampled | — | Not deep-read; see Open questions |

---

## 8. Open questions

1. **DD-01 fix locus.** The clean fix is a *code* change (raise
   `RenderError` in Junos), not a docstring edit — confirming this with
   the orchestrator since it crosses the docs/code boundary. Flagged via
   spawn_task. Is a docs-only "document that Junos raises `TypeError`"
   acceptable as an interim, or must the contract divergence be closed in
   code? I recommend code.
2. **DD-02 scope vs the prior audit's EXPECTED-STALE call.** The audit
   deliberately left `loader.py`'s Phase-0 framing. Does the project want
   the *sibling* package docstrings (`migration/__init__.py`,
   `canonical/__init__.py`) brought into line with the shipped
   canonical-tree/transforms reality, or is the whole "Phase 0/0.5"
   vocabulary considered a deliberate engine-internal roadmap label that
   should be normalised in one pass (perhaps by DF, who owns
   RELEASE_PLAN/METHODOLOGY phase semantics)? There is a coordination
   seam here with DF.
3. **`is_secondary` per-codec wiring (`UNVERIFIED`).** I confirmed IOS-XE
   CLI wires `is_secondary`; I did not exhaustively check Arista / Junos /
   the others. A code-lens reviewer (Fleet C) should confirm the actual
   per-codec coverage so DD-03's rewording is accurate about *which*
   codecs wire it.
4. **`api/routes/ui.py` (894 LOC) and the larger route handlers** were
   sampled, not deep-read. They are mostly HTML-GET handlers whose
   docstrings are low-risk, but a fuller pass could surface more
   route-pointer drift of the DD-05 class. Out of budget for this
   chapter; noting for completeness.
5. **Historical-provenance comments** ("Phase 4b Wave 7c-C", "Phase 4
   rank-4", "Round 4.2", "P2C1") are pervasive in code comments
   (40+ hits). These are *comments*, not docstrings, and are
   backward-looking provenance rather than stale futures — out of strict
   DD scope. If the project wants them normalised that is a separate
   hygiene cycle; I did not treat them as findings.

---

*End of investigation DD.*

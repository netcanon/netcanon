# netcanon "version vector" — feasibility verdict & implementation plan

**Date:** 2026-07-05 · **Status:** PROPOSED — awaiting explicit user go (the backlog entry is gated: "data now, work later — do NOT start without go")
**Provenance:** blackboard ultracode run — 5 understanding lenses → 3 candidate designs → adversarial verification (with empirical reproductions) → feasibility assessment → this synthesis. All file:line cites re-verified against the working tree at synthesis time.
**Repo root:** `<repo-root>` (all paths below repo-relative).

---

## 1. Executive summary

`CanonicalIntent.source_version` (intent.py:951) has been captured by all 12 codecs since PR #235 / v0.4.12 and is deliberately inert — excluded from both comparators, never echoed by render, exempted in five guard registries. The deferred work was framed as "wire it into version-GATED parse and render behaviour."

**The investigation inverted that framing.** Across all 12 codecs, **no modeled surface has same-token-different-meaning across OS versions** — every real version delta is a disjoint-grammar delta, and the codebase's incumbent **union-grammar** pattern (10+ shipped sites) beats version gating on every reproduced case *and* survives the empty-version wild majority (arista ~7.5% / junos ~6.5% coverage; opnsense 0% forever by design). Version-gated **parse** is therefore dead on the evidence. What survives is narrow and concrete:

1. **Four reproduced legacy-grammar losses** fixable version-agnostically (mikrotik v6 NTP, junos pre-ELS access→trunk misparse, arista pre-4.23 `vrf definition`, IOS-12 `ip vrf`) — most of the initiative's correctness value, no version machinery needed.
2. **A fidelity defect:** sanitize/same-vendor renders stamp hardcoded fake versions (`9.3(11)`, `Virtual.10.13.1000`, `6.6.2`, `1.4`) onto real devices' configs.
3. **Exactly two semantic version-gating customers:** RouterOS-6 targets reject the v7-only NTP emission (device-validity payoff), and NX-OS 10 `localizedV2key` (warning-sharpener).

All three candidate designs survived adversarial verification (SOUND-WITH-CAVEATS, zero fatal flaws). Design A (mikrotik same-vendor gate) was additionally validated **empirically** — the verifier simulated the post-change mesh across all 13 codecs: zero CODEC_BUG movement, no baseline regeneration. Design C's explicit target-version channel survived structurally. Design B's generalized overlay layer survived but is ~10× machinery for two customers — **rejected** with a defined revisit trigger.

**Recommendation: harvest, then narrow-gate.** Ship Phases 0–3 (truth maintenance, union-grammar fixes, banner echo, mikrotik same-vendor gate — all S, ≈ M cumulative). Hold Phase 4–5 (the explicit, binding, default-off `target_version` channel with two dialect packs + UI) behind a separate go. Keep `classify()` and the capability matrices version-less permanently in this effort.

---

## 2. Feasibility breakdown

**Overall: MARGINAL as originally conceived → GREEN for the descoped kernel this plan ships.**

| Dimension | Rating | One-line verdict |
|---|---|---|
| User/demand value | 🟡 | Backlog-named, but the presumed core (version-gated parse) is falsified by the code; residual value = 4 union fixes + sanitize fidelity + 2 semantic gates |
| Wild source-version availability | 🔴 | ""-majority for arista/junos, 0% opnsense by design, post-render values poisoned; version also under-determines grammar (junos ELS is platform×version) → nothing may *assume* detection; plan routes value through same-vendor evidence or operator choice |
| Round-trip / mesh-baseline risk | 🟡 | Failure mode proven (reverted junos-LAG, CODEC_BUG 5→26) but safe patterns verified: metadata allowlist-excluded; bare mesh calls codecs **directly** (run_full_mesh.py:655/665/675 — transforms never compose); Phase 3 empirically simulated at zero movement |
| Matrix + ratchet cost | 🟢/🔴 | GREEN under this plan's constraint (classify() stays version-less; strictest-unconditional declarations with version-naming lossy reasons — shipped precedents); RED if version-scoped matrices were attempted (exact-match fail-open at models/migration.py:243-244 would silently under-warn on a mis-scoped predicate). Ratchet (exactly 25 pinned noqa) satisfied by construction |
| Effort spread / value concentration | 🟡 | 1 semantic codec (mikrotik) + 1 warning-sharpener (nxos) + 3 banner-only + 6-7 with nothing → kills Design B's economics; makes each increment S–M and severable |
| Maintenance burden | 🟡 | Extraction layer already needed #263; CodeQL bit this feature's own regexes twice. Bounded by: coarse major-bucket keys, no regex over raw config text in new code, union parse never stops reading old forms, default-off degradation |
| Testing w/o per-version corpus | 🟡 | Committed fixtures already span families; dialects testable synthetically (declaration-requires-union-parse guard); honesty guards run version-less so "" is the tested-by-default path. Hard ceiling: on-device VALIDITY of old dialects not certifiable (harness scores preservation; VM lab parked) — downside capped at status quo |
| Architectural readiness | 🟢 | Every hook exists: version assigned before every stanza loop; Metadata slot for `target_version` (intent.py:948-951); transform factory shipped (port_names.py:580); `run_plan_with_overrides` growth doubly sanctioned (:92-94 Hard Rules AND its own :415-419 docstring); BOTH /plan branches already call it (migration.py:263-285, :294-296); UI hook pre-designed (migrate.html:1895-1901) |

### What the adversarial pass established

**Survived (build on these):**
- Design A end-to-end, incl. an empirical mesh simulation: injected the post-union-parse NTP values into the real parsed fixture intents, rendered+reparsed through all 13 codecs — the five reconciled 'good' pairs (arista/aoss/iosxe_cli/fortigate/junos) all preserve; droppers are declared or unreconciled; **zero CODEC_BUG movement, latest.json untouched**. Effort re-confirmed S.
- Design C's mechanism: pipeline ordering (transforms → validate → render, migration_pipeline.py:286-299) makes tree-borne stamping reach both consumers; the bare mesh **cannot** see it (direct codec calls, stronger than designed); 4 of 5 exclusion registries fail loudly on a missed entry.
- Design B's structural safety (relax-only overlays, default==base byte-equality) — sound, but not worth building yet.

**Corrected (folded into the plan):**
- Phase-4 mesh bucketing is driven by `tests/fixtures/cross_vendor_expectations/*.yaml` dispositions, **not** CapabilityMatrix declarations; pairs without a YAML structurally cannot CODEC_BUG.
- There is **no bare `run_plan` branch** in POST /plan — both branches call `run_plan_with_overrides`; thread the new param at both sites, predicate extension optional.
- The `_compare` pops are hygiene, not a loud gate, for an always-`""` field — land them WITH the new stamped-intent tests.
- The dialect transform must **duck-type-guard** plain-dict trees (mock codec).
- Banner-token-only "dialects" (iosxr/aoscx/vyos) dropped from Phase 4 — cosmetic dropdown choices are #292-adjacent over-promise; the Phase-2 echo serves their fidelity.

**Flagged uncertain (handle explicitly):**
- RouterOS-6 `primary-ntp=` **single-server** line validity on-device (no fixture exhibit; verify against vendor docs; downside capped at status quo).
- The v6 `server-dns-names=` third NTP key is un-read by the proposed union parse — residual gap unless read (recommended).

---

## 3. Recommended architecture

### Standing doctrine (non-negotiable within this effort)

1. **Parse is union-grammar, never version-gated.** Old and new forms are token/section-disjoint everywhere found; union parse is correct at `source_version == ""` (the wild majority) and is the incumbent pattern (arista vrf-forwarding, vyos ntp roots, iosxr dual banners, nxos `localized(V2)?key`, …).
2. **`classify()` and the matrices stay version-less.** Version divergence keeps being expressed as an *unconditional strictest* declaration with a version-naming lossy reason (shipped precedents: iosxe VRRP-AF `codec.py:274-292`; nxos V2key `codec.py:382-392`). Never smuggle version into xpath microsyntax; never add a version parameter to `classify()` (exact-match fail-open would make a mis-scoped predicate silently under-warn).
3. **Target dialect is tree-borne and default-off.** Reaches render via a transform-stamped `CanonicalIntent.target_version` metadata field — no ABC signature change, no per-instance codec state, `run_plan` byte-identical. Every unstamped path (bare mesh, sanitize, comparators, library callers) renders today's bytes.
4. **`""` / unknown / garbage version is the first-class default path** — affirmative evidence only; garbage tokens (the #263 literal-`version` class) resolve to the default, never a guess.
5. **Coarse enumerated dialect keys, no range engine.** `("7","6")`, `("9","10")` — the version-string zoo (`9.3(11)`, `25.4R1.12`, `FL.10.13.1000`, `4.22.4M-2GB`) defeats PEP 440; the definitions layer's capture-granularity==match-granularity lesson applies.
6. **No knob is documented before it gates real output** (the #292 strip_unsupported lesson).
7. **The definitions/library axis stays disjoint.** Imitate `loader.py resolve()`'s most-specific-wins/fall-through *pattern* if ever needed; never import the code (wrong schema/namespace/lifecycle). OPNsense stays outside the version story forever; its Kea-vs-ISC gap needs a separate config-schema-version field (separate feature, if ever).

### How the two adopted kernels compose

- **Phase 3 (Design A):** same-vendor auto-gate in mikrotik render — the only context where source version IS the target version by construction (sanitize + mikrotik→mikrotik), guarded by `source_vendor` + affirmative major-6 evidence + shape checks. Serves the path Phase 4 structurally cannot (sanitize has no request body).
- **Phase 4 (trimmed Design C):** explicit, binding, operator-selected `target_version` for cross-vendor flows — where `source_version` is categorically the wrong key (a Junos `25.4R1.12` says nothing about RouterOS 6 vs 7).
- **Precedence when both exist:** explicit `tree.target_version` wins → else the same-vendor auto-gate → else the codec default. Phase 3's helpers (`_ros_major`, `_render_ntp_v6`) are directly reused by Phase 4's dispatch.

### Explicitly rejected (with revisit trigger)

- **Design B (version-profile overlay layer):** sound but ~10× the point fixes for two customers. Revisit only when a **third semantic dialect customer** materializes — most plausibly RouterOS v6 `/routing bgp instance`+`peer` vs v7 `connection`/`template` when `CanonicalBGPProcess` (translator-plans.txt:826-848) ships; that schema work should reserve a grammar-family discriminator from day one.
- Version-gated parse; version-scoped matrices; PEP-440/range machinery; cosmetic-only dialect keys; backfilling the OPNsense axis.

---

## 4. Phased roadmap

> Verification ritual for every behaviour-bearing PR: helpers not inline branches (ratchet pins **exactly 25** noqa C901); in-process mesh + phase4; full `pytest tests/unit tests/integration --basetemp=D:/nc-pytest-tmp` (py3.11 floor — no nested same-quote f-strings); any baseline shift is a conscious documented re-baseline per `test_cross_mesh_ci_guard.py:17-22`, never silent. New tests use **inline snippets**, never new files under `tests/fixtures/real` (cells_total pinned at 1224).

### Phase 0 — Decision gate + truth maintenance — **S** (hours)

*Goal:* record the go; stop the metadata rot (#292 doctrine); zero behaviour change.

| Work | Files |
|---|---|
| Record user go (Phases 1–3 now; 4–5 separately gated); commit this plan | `docs/version-vector-plan.md` (NEW) |
| Fix stale claim "parsers don't yet populate source_version" (false since #235) — preserve the `@<version>` ack-key design comment | `netcanon/templates/migrate.html:1896-1897` |
| Same staleness | `ARCHITECTURE.md:354-360` |
| Reword the false "version gating lives in the CapabilityMatrix" docstring → point at this plan | `netcanon/migration/codecs/base.py:148-150` |
| Severable display-honesty: mikrotik `version_hint`/`version_range` `'7.x'` → `'6.x / 7.x'` (display-only; sole consumer `_migration_helpers.py:144`; API tests are presence-only; certified corpus includes 6.48.x) | `netcanon/migration/codecs/mikrotik_routeros/codec.py:98,:127` |
| CHANGELOG `[Unreleased]` (CRLF — splice via `py` with `newline=""`); note #292 is merged-unreleased | `CHANGELOG.md` |

*Exit:* go recorded; docs merged; no behaviour-bearing line changed; unit suite green.
*Dependencies:* none.

### Phase 1 — Union-grammar harvest (4 independent version-AGNOSTIC bugfix PRs) — **S each, M total**

*Goal:* close the four reproduced legacy-grammar losses; deliver most of the initiative's correctness value; establish the reparse prerequisite for any dialect emission.

**1a MikroTik NTP** *(empirically pre-validated mesh-safe)* — extend `_parse_system_ntp` (`mikrotik_routeros/parse.py:376-383`) to union-read v6 `primary-ntp=`/`secondary-ntp=` (+ recommended: `server-dns-names=`) alongside v7 `servers=`; skip empties and the `0.0.0.0` v6 unset-sentinel; order-preserving dedup (junos `parse.py:1171` precedent); one dispatch `elif` for `/system ntp client servers` (table `:144-188`, currently "silently ignored" at `:188`) + a tiny `add address=X` handler. Today **all four committed real mikrotik fixtures parse `ntp_servers=[]`** (reproduced).
**1b Arista pre-4.23 VRF** — harvest `vrf definition <name>` alongside `vrf instance` (`arista_eos/parse.py:180,:565-571`; exclusion tuple `:1241-1243` proves the form is known). Inline fixtures — committed 4.21/4.22 files carry no VRFs, so CI can't see this today.
**1c IOS-12 VRF** — accept classic top-level `ip vrf <name>` alongside `vrf definition` (`cisco_iosxe_cli/parse.py:388-390`; interface binding already unioned `:411-413`).
**1d Junos pre-ELS** *(highest semantic severity: access port silently becomes a trunk)* — accept `port-mode` alongside `interface-mode` (`juniper_junos/parse.py:1531-1541`); demote the default-to-trunk heuristic (`:530-539`) **narrowly** (only when an explicit access statement is present); regression-pin the committed `ksator_labmgmt_ex4550_junos151.set` trunk lines (`:32/:36/:41`).

*Files:* the four parse.py files + their unit test files + (verify-only) `tests/fixtures/real/_phase4_runs/latest.json`.
*Exit:* reproduced losses closed with unit tests; junos access-misparse fixed with ksator unchanged; mesh guard green — CODEC_BUG=5, pairs unchanged, cells_total=1224 (or a documented re-baseline); ratchet at 25.
*Dependencies:* Phase 0 go. Fixes mutually independent and independently revertible. **1a is a hard prerequisite for Phases 3 and 4b-mikrotik.**
*PR-description note (adversarial correction):* phase-4 buckets come from `cross_vendor_expectations/*.yaml`, not matrices; pairs without a YAML cannot CODEC_BUG; future YAML additions must declare the newly-populated fields' dispositions.

### Phase 2 — Same-vendor version-stamp echo — **S**

*Goal:* stop the sanitizer (`tools/sanitize.py:233→:264`, same-codec re-render) silently relabeling devices: echo `tree.source_version` when `source_vendor == own codec` AND non-empty; else today's constants — byte-identical fallback.

| Site | Change |
|---|---|
| `cisco_nxos/render.py:40,:70,:171` | banner `version <ver> Bios:version` + boot `nxos.<ver>.bin` echo (fixes "sanitized 10.x config claims 9.3(11)") |
| `cisco_iosxr/render.py:49,:70` | `!! IOS XR Configuration <ver>` echo |
| `aruba_aoscx/render.py:54,:72` | version TOKEN only — the `!Version ArubaOS-CX` prefix is the codec's own probe marker; keep `probe(render(parse(x)))` (test_aruba_aoscx.py:598-601) green + add an echoed-version variant |
| `vyos/render.py:60,:103` | Release-version token only — NEVER the component vector (`:50-58`); note the residual 1.3-token/1.4-vector inconsistency as strictly-better-than-today |

Pre-work: sweep `tests/e2e` + desktop suite for byte-exact **banner** assertions (unit known clean; the adversarial sweep covered mikrotik NTP strings only). No echo for the six version-silent renders; leave fortigate's deliberately non-recapturable stamp alone. Comparator-invisible by verified construction (source_version popped/allowlisted everywhere; banner text not an audited field).
*Exit:* sanitize preserves the device's stamp; probe assertions green; no registry changes; mesh green.
*Dependencies:* Phase 0 go; independent of Phases 1/3.

### Phase 3 — MikroTik RouterOS-6 same-vendor NTP dialect gate (Design A kernel) — **S**

*Goal:* make `source_version` behaviour-bearing in exactly one provably-safe place — the backlog's flagship 6-vs-7 case — with zero API/schema/matrix churn.

Work:
- Extract the NTP block (`render.py:727-733`) into `_render_ntp_client(tree)` (grandfathered `render_intent :99` gets simpler); micro-helpers `_ros_major(version) -> int|None` (anchored `(\d+)\.` on the short pre-extracted token — `""`/garbage/bare-`6` → None) and `_all_ip_literals` (stdlib `ipaddress`).
- Gate: `source_vendor=='mikrotik_routeros'` AND `_ros_major==6` AND `1<=len(ntp_servers)<=2` AND all IP literals → emit `set enabled=yes primary-ntp=A [secondary-ntp=B]` (mirrors fixture `routeros_diff_verbose_export.rsc:446`) + a comment line carrying `RouterOS <source_version>` (re-captured by `_VERSION_RE :230`, skipped by `_COMMENT_RE :225`, verified no confound → idempotent across repeated sanitize). **Else today's v7 output byte-for-byte.**
- Update the now-conditionally-false `_extract_version` docstring (`parse.py:236-237`).
- Tests: fire/inert matrix (`''`/garbage/`7.18.2`/foreign vendor/3+ servers/hostnames), round-trip both dialects (v6 output read back by 1a's union parse), double-round-trip idempotency; existing exact-output test (`test_mikrotik_routeros.py:300-309`) stays green unmodified.

*Exit:* 6.48.x source sanitize emits v6 NTP + echo; all fallbacks byte-identical; mesh green with latest.json untouched (self-pair cells give the fired gate free reparse-crash coverage); ratchet at 25.
*Dependencies:* **1a.** Independent of Phase 2.

### Phase 4 — Explicit target-version channel (trimmed Design C) — **M** — *CONDITIONAL, separate go*

*Goal:* the binding, operator-selected, codec-enumerated target dialect key for cross-vendor flows; default-off on every unstamped path.

**4a mechanism PR (atomic, zero output change):**
- `CanonicalIntent.target_version: str = ""` beside `source_version` (`intent.py:948-951`) — stamped only by the orchestrator transform, never by parse.
- **5-registry sweep in the same PR:** `test_run_full_mesh.py:367-374` metadata_fields · `test_walker_completeness.py:145-153` `_WALK_EXEMPT` · `test_registry_capability_honesty.py:538-542` `_NON_CAPABILITY_FIELDS` · `test_sanitize_completeness.py` `_NON_SENSITIVE` · the `_compare` pops (`test_real_captures.py:336-347` + kitchen-sink mirrors). *Adversarial correction:* the pops are silent-safe while the field is always `""` — land them anyway; they become load-bearing with 4b's tests. Then run the FULL local suite (the #235 full-intent-equality-straggler lesson).
- `CodecBase.render_dialects: ClassVar[tuple[str, ...]] = ()` beside `version_hint` (`base.py:163-164`); first entry = default.
- NEW `netcanon/migration/canonical/dialects.py`: `build_target_dialect_transform(target_codec, target_version)` cloning `port_names.py:580` — **duck-type-guarded** (mock codec parse returns a plain dict; mirror `_capture_source_shape`); `ValueError` on undeclared keys.
- `run_plan_with_overrides` grows `target_version: str | None = None` — cite its own docstring `:415-419` ("signature free to grow … optional param with default None — backwards compatible"), not just Hard Rules `:92-94`; compose the dialect transform FIRST.
- `MigrationPlanRequest.target_version: str | None = None` beside `:713-725` with an explicitly **contrasting BINDING** docstring (siblings say "does not affect rendering"); thread at **BOTH** /plan call sites (`migration.py:263-285` AND `:294-296` — no bare `run_plan` branch exists; predicate extension optional); **422** on unknown keys listing the offered dialects; `CodecInfo.render_dialects`.
- NEW guard `test_dialect_round_trips.py`: **declaration-requires-union-parse** — per codec × declared dialect: stamp kitchen-sink → render → reparse → content-equal modulo metadata pops (incl. the `target_version` pop). Lands before any pack.

**4b dialect packs (2 only):**
- **mikrotik `("7","6")`** — dispatch reuses Phase-3 helpers; precedence: explicit stamp → same-vendor auto-gate → default `"7"`; 3+-server/hostname intents under `"6"` fall back with an in-output lossy comment.
- **cisco_nxos `("9","10")`** — banner `:70` + boot `:171` token per dialect; `:280` emits `localizedV2key` under `"10"` (`parse.py:204` union-accepts both → reparse-safe day one). Defer `LossyPath.cleared_by_dialect` (the over-warn fix) to a later v2 decision.
- **NO dialect keys for iosxr/aoscx/vyos** — cosmetic-only choices are #292-adjacent over-promise; Phase 2 already serves their fidelity. `classify()`, matrices, walker untouched.

*Exit:* bare mesh byte-identical (transforms never compose there — verified `run_full_mesh.py:655/:665/:675` direct codec calls), latest.json untouched; unstamped/`""` paths render today's bytes; invalid key → 422 with the offered list; version-only requests produce dialect output through BOTH dispatch branches; per-dialect stamped round-trips green; registries atomic; full local suite green.
*Dependencies:* separate go; design call #5 resolved. 4b-mikrotik ← 1a + 3; 4b-nxos ← 4a only.

### Phase 5 — UI + operator docs — **S** — *CONDITIONAL, follows Phase 4*

Dropdown from `CodecInfo.render_dialects` (empty tuple → no control); execute the pre-planned `migrate.html:1895-1901` hook — `_ackKey` `@<version>` per side + `_ACK_SCHEMA_VERSION` bump, bundled **here** because the bump invalidates saved rename acks and is only justified once versions change output; `docs/CAPABILITIES.md` dialect rows (only-after-it-gates); OpenAPI/CHANGELOG stating `target_version` is binding.
*Exit:* dropdown offers exactly the declared dialects; no documented affordance without a gating implementation; e2e/desktop green.

---

## 5. Total effort (honest)

| Slice | Effort |
|---|---|
| **Recommended core (0–3)** | ~6 small PRs, each S → **≈ M cumulative** (~3–5 focused sessions) |
| **Conditional extension (4–5)** | +**M** (mechanism PR M; two S packs reusing Phase-3 helpers; S UI/docs; ~3–4 sessions) |
| **Full program** | **≈ L** |
| Backlog-as-conceived (gated parse + Design-B machinery) | would have been **L–XL**, most of the parse half anti-value — deliberately not built |

---

## 6. Risks & mitigations

| # | Risk | Mitigation |
|---|---|---|
| 1 | Latent NTP bug in a 'good'-pair target → new CODEC_BUG pair (1a) | Pre-discharged: adversarial simulation across all 13 codecs shows the five reconciled 'good' pairs preserve; droppers declared or unreconciled. Mandatory local mesh run; fix-forward in own commit or documented re-baseline — never silent |
| 2 | Bucket-mechanism mis-model propagates (matrices ≠ dispositions) | Corrected mechanics recorded here + in each Phase-1 PR: `cross_vendor_expectations/*.yaml` drives buckets; future YAML additions must declare new-field dispositions |
| 3 | Phase-3 precedent objection (render reads tree metadata) | Confined to same-vendor (where source==target by construction, incl. body-less sanitize), affirmative-evidence guards, provably inert cross-vendor, comparator-invisible; escape hatch = Phase-4 precedence subsumes it |
| 4 | Comment-echo rejected in review → idempotency loss | Verified parse-inert + re-capturable + no confound; fallback: documented non-idempotency (second-gen render flips to v7); tree-level round-trip unaffected |
| 5 | On-device validity of v6 forms uncertifiable (primary-only line UNCERTAIN; `server-dns-names=` residual; lab parked) | Downside capped at status quo (today's v7-only output equally invalid on 6.x); strict fallback on >2/hostnames; read `server-dns-names=` (decision #4); vendor-doc check before merge |
| 6 | Junos heuristic demotion shifts cells / regresses ELS configs (1d) | Narrow demotion (explicit access statement only); ksator regression pin; own PR, independently revertible; full mesh locally |
| 7 | Phase-4 registry-sweep gaps (`_compare` pops silent-safe; #235-class stragglers) | Atomic PR; pops land WITH the stamped-intent tests; FULL local unit+integration on py3.11-safe syntax, `--basetemp=D:/nc-pytest-tmp` |
| 8 | Transform crashes on dict trees (mock codec, `migration_pipeline.py:160-171`) | Duck-type getattr guard per `_capture_source_shape`; unit test through the mock codec |
| 9 | Declared dialect the codec can't reparse → mesh crash invariant | Declaration-requires-union-parse guard in 4a BEFORE any pack; mikrotik `"6"` hard-blocked on 1a; nxos `"10"` verified reparse-safe (`parse.py:204`) |
| 10 | Advisory-vs-binding confusion (`target_version` beside "does not affect rendering" siblings) | Contrasting docstring + OpenAPI + UI copy; fail-closed 422, never a silent wrong-dialect fallback |
| 11 | Scope creep (gated parse / version-scoped matrices / cosmetic dialects / Design-B) | Doctrine §3 + module docstring notes ("semantic divergence evidence required"); revisit trigger = third semantic customer (RouterOS BGP w/ `CanonicalBGPProcess`) |
| 12 | CodeQL (py/polynomial-redos bit #235's own regexes ×2; clear-text-logging) | No regex over raw config text in new code (`_ros_major` on the short token; `ipaddress` for IPs); fortigate `:155-163` bounded-class discipline + redos-budget tests for any future pattern; never log versions with config text |
| 13 | e2e/desktop banner snapshots (Phase 2) | Sweep first (unit clean; mikrotik NTP already swept); aoscx varies token only, probe assertion preserved |
| 14 | Ack-key bump invalidates saved acknowledgements | Bundled in Phase 5 only, once versions actually change output |

---

## 7. Open decisions (user calls)

1. **The go + scope split:** approve Phases 0–3 now with 4–5 separately gated (recommended), or the full program at once? (The backlog gate requires an explicit go for any of it.)
2. **Phase-3 precedent:** accept the same-vendor render-reads-metadata gate, or defer all dialect behaviour to Phase 4 — forfeiting the sanitize-path value (sanitize has no request body)?
3. **Idempotency mechanism:** the `# … RouterOS <version>` comment echo (verified safe) vs documented non-idempotency across double-sanitize?
4. **v6 `server-dns-names=`:** read it in 1a (recommended — one more kv key) or document as residual?
5. **Phase-4 vehicle:** optional param on `run_plan_with_overrides` (recommended — its own `:415-419` docstring blesses growth; five rename categories precedent) vs a new `run_plan_with_target` under a strict Hard-Rules reading?
6. **Junos demotion breadth (1d):** narrow (recommended) vs broader heuristic rework?
7. **`version_hint`/`version_range` end-state:** derive from `render_dialects` in Phase 4/5, or retire? (Phase 0 interim: mikrotik widened to `'6.x / 7.x'` either way.)
8. **Re-baseline policy** if a Phase-1 fix surfaces a latent target bug: fix-forward (recommended) vs documented re-baseline?
9. **Re-measure wild coverage** on the current dogfood corpus before any Phase-4+ expansion? (The ~7.5%/~6.5% figures are memory-sourced, not repo-reproducible.)
10. **OPNsense Kea-vs-ISC:** file the separate config-schema-version feature ticket now, or leave unfiled? (Out of scope here either way.)

---

## 8. Appendix — load-bearing anchors (all re-verified at synthesis)

| Fact | Anchor |
|---|---|
| `source_version` field + Metadata block | `netcanon/migration/canonical/intent.py:948-951` (docstring `:901-902`) |
| mikrotik: noqa, vendor/version assignment, dispatch, NTP parse, regexes | `mikrotik_routeros/parse.py:66,:96-99,:144-188,:225,:230,:376-383` |
| mikrotik render: noqa + v7-only NTP block | `mikrotik_routeros/render.py:99,:727-733` |
| v6 NTP fixture evidence (6.48.1) | `tests/fixtures/real/mikrotik/routeros_diff_verbose_export.rsc:445-446`; v7 subsection: `taqavi_initial_provisioning.rsc:124-127` |
| Pipeline: Hard Rules; transforms→validate→render; overrides signature + "free to grow" | `netcanon/services/migration_pipeline.py:87-96,:286-299,:370-382,:415-419` |
| POST /plan: BOTH branches call `run_plan_with_overrides` | `netcanon/api/routes/migration.py:263-285,:294-296` |
| Advisory-only sibling fields | `netcanon/models/migration.py:713-725` |
| `classify()` exact-match fail-open | `netcanon/models/migration.py:211-244` (default `:243-244`) |
| Transform factory pattern | `netcanon/migration/canonical/port_names.py:580-592` |
| nxos: banner/boot constants, `localizedkey` hardcode, union parse regex, lossy decl | `cisco_nxos/render.py:40,:70,:171,:280`; `parse.py:198-207`; `codec.py:382-392` |
| Banner constants (echo sites) | `cisco_iosxr/render.py:49,:70`; `aruba_aoscx/render.py:54,:72` (+probe test `test_aruba_aoscx.py:598-601`); `vyos/render.py:50-60,:102-103` |
| Bare mesh calls codecs directly (no transforms) | `tools/run_full_mesh.py:655,:665,:675`; `_AUDITED_FIELDS :131-161` |
| Mesh CI guard: 6 assertions; baseline CODEC_BUG=5, cells_total=1224, 4 pairs | `tests/integration/test_cross_mesh_ci_guard.py:49-52,:92-206`; `tests/fixtures/real/_phase4_runs/latest.json` |
| Bucket mechanics (YAML-driven, not matrix) | `tests/fixtures/cross_vendor_expectations/*.yaml`; `tools/run_phase4_reconciliation.py:738-844` |
| Ratchet: exactly-25 pinned noqa; mccabe 25 | `tests/unit/test_complexity_ratchet.py:41,:60-75` |
| 5 exclusion registries for a new metadata field | `test_real_captures.py:336-347` (+ kitchen-sink mirrors); `test_run_full_mesh.py:362-382`; `test_walker_completeness.py:145-153`; `test_registry_capability_honesty.py:538-542`; `test_sanitize_completeness.py:113-152` |
| Mock codec returns plain dict (duck-type-guard requirement) | `netcanon/services/migration_pipeline.py:160-171` |
| Sanitize = same-codec parse→render (Phase-2/3 motivation) | `netcanon/tools/sanitize.py:233,:264` |
| OPNsense honest-empty by design | `opnsense/parse.py:205-212` |
| Junos pre-ELS misparse sites | `juniper_junos/parse.py:530-539,:1531-1541`; fixture `ksator_labmgmt_ex4550_junos151.set:32-41` |
| Arista / IOS-12 legacy VRF harvest gaps | `arista_eos/parse.py:180,:565-571,:1241-1243`; `cisco_iosxe_cli/parse.py:388-390,:411-413` |
| UI hook + stale clause | `netcanon/templates/migrate.html:1895-1901` (stale `:1896-1897`) |
| Dormant surfaces + false docstring | `base.py:148-150,:163-164`; `models/migration.py:184,:201,:858`; `_migration_helpers.py:144` |
| Founding intent (version-awareness planned day one) | `translator-plans.txt:1824-1836,:1866-1868` |
| ReDoS discipline precedent | `fortigate_cli/parse.py:155-163`; `tests/unit/migration/test_redos_hardening.py` |

### Phase-4 new-field checklist (copy into the 4a PR)

- [ ] `intent.py` field + docstring ("stamped only by the orchestrator transform")
- [ ] `test_run_full_mesh.py` `metadata_fields` += target_version
- [ ] `test_walker_completeness.py` `_WALK_EXEMPT[(CanonicalIntent, target_version)] = ("METADATA", "requested render dialect")`
- [ ] `test_registry_capability_honesty.py` `_NON_CAPABILITY_FIELDS` += target_version
- [ ] `test_sanitize_completeness.py` `_NON_SENSITIVE` += target_version (METADATA)
- [ ] `_compare` pops: `test_real_captures.py` + `test_synthetic_kitchen_sink_round_trips.py` + fortigate/mikrotik/aoss kitchen-sink mirrors (land WITH the stamped-intent tests)
- [ ] Duck-type-guard in the transform (mock-codec dict trees) + unit test
- [ ] Thread at BOTH `/plan` call sites; 422 on unknown key
- [ ] `test_dialect_round_trips.py` declaration-requires-union-parse guard (pops target_version)
- [ ] FULL local `pytest tests/unit tests/integration --basetemp=D:/nc-pytest-tmp` (py3.11-safe syntax)

---

*End of plan. Nothing in this document authorizes implementation — the backlog gate ("do NOT start without go") applies to Phase 0 onward.*
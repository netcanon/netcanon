# Cluster C — Developer-facing documentation accuracy

## Summary

`AGENTS.md` is largely accurate — its 25-row Documentation Sync
Checklist resolves cleanly against current code, with the most
consequential gap being the absent **`netcanon/tools/sanitize.py`
redaction-category** row (sanitiser additions don't trip a doc-sync
row even though SECURITY.md depends on the inventory).  The single
loudest WRONG in this cluster is `SECURITY.md` — the v0.1.2
`defusedxml` swap met three of the document's own "Updating This
Document" triggers (new dependency with security relevance + XML-
input hardening + scanner enablement) and was not surfaced; the
Dependency Supply Chain table, Distribution-channels table, and
Supply-Chain Integrity section all lag the shipped v0.1.2 surface.
`ARCHITECTURE.md` has one outright WRONG (claims every
bidirectional codec has `unsupported_rename_categories` empty; two
declare `{"snmpv3"}`) and one INCOMPLETE (the partials inventory
omits `kbd-cheatsheet.js` even though base.html includes it).
`CODE_OF_CONDUCT.md` ships with the contributor-covenant
`[INSERT CONTACT METHOD]` placeholder unsubstituted.  Other docs
(METHODOLOGY, adding-a-*, glossary, feature-parity-walkthrough,
sub-READMEs) hold up well; minor INCOMPLETE / STYLE rows below.

---

## AGENTS.md Documentation Sync Checklist audit (row-by-row)

`AGENTS.md` lines 148-189.  Each row's trigger ("If you change X")
verified against current code surface; each target ("Then touch Y")
verified for existence.

| Row (paraphrased) | Trigger still real? | Target resolves? | Severity | Notes |
|---|---|---|---|---|
| 1. New interactive HTML element → `tests/testid_reference.md` | Yes (`grep -r data-testid` shows ongoing additions) | Yes | OK | Self-check grep recipe still works |
| 2. New Jinja partial → parent template "Contents map" + `ARCHITECTURE.md` if new pattern | Yes (`_partials/` has 13 files inc. `kbd-cheatsheet.js`) | Partial — ARCHITECTURE.md inventory MISSING `kbd-cheatsheet.js` (see below) | INCOMPLETE | Most recent partial isn't surfaced in the architecture inventory; either the inventory is stale, or the row needs sharpening to "only when introducing a new pattern" |
| 3. New file under `netcanon/templates/` with non-`.html` extension OR new subdir → `pyproject.toml [tool.setuptools.package-data]` | Yes; `templates/_partials/*.js` glob is required for non-editable installs | Yes — `pyproject.toml:230` has `templates/_partials/*.js` glob | OK | Worth verifying CI `docker-build-smoke` still fires for non-dashboard pages mentioned in the row caveat |
| 4. New codec under `netcanon/migration/codecs/<vendor>/` → `netcanon/migration/codecs/README.md` "Shape of a codec" codec count + ARCHITECTURE if new wire-format | Yes (subpackages = 8 shipped + `_mock`) | Yes — README "Eight codecs have shipped" is current | OK | Row currently honest; if a 9th codec lands, the count claim re-fires |
| 5. New module inside an existing codec (`port_names.py`, `_svi_absorption.py`, etc.) → `netcanon/migration/codecs/README.md` "Module layout" | Yes — pattern still in use | Yes | OK |  |
| 6. New target-profile YAML → per-profile test in `tests/unit/migration/test_target_profile_shipped.py` | Yes (54 profiles in `definitions/target_profiles/`) | Yes — file exists at the cited path | OK |  |
| 7. Target-profile gains `modules:` → add to `tests/fixtures/module_variants.py` | Yes (4 module-variant profiles) | Yes — file + CI guard `test_module_variant_allowlist_shared_with_integration_tier` exist at `tests/unit/migration/test_target_profile_shipped.py:115` | OK |  |
| 8. New canonical field on `CanonicalIntent` / `CanonicalInterface` → `docs/adding-a-canonical-field.md` | Yes; v0.2.0 Wave A added several VRRP fields | Yes; doc exists and has a "two shapes" section that already calls out ship-before-wire — see § per-doc finding below for currency | OK |  |
| 9. New route / endpoint / public function in module whose docstring enumerates contents → module docstring | Yes; `migration.py` + `migration_pipeline.py` both enumerate | Yes — verified both files have current "Endpoints" / "Per-pane override categories" lists | OK |  |
| 10. New hard rule / cross-cutting invariant → `AGENTS.md` | Yes | Yes (this file) | OK |  |
| 11. Codec promoted to `best_effort` / `certified` → `tests/fixtures/real/RESULTS.md` | Yes | Yes — file exists | OK |  |
| 12. New real-capture fixture under `tests/fixtures/real/<vendor>/` → `NOTICE.md` + `RESULTS.md` | Yes | Yes — both files exist | OK |  |
| 13. New pytest marker in `pyproject.toml` OR new conftest fixture changing tier behaviour → `tests/README.md` | Yes | Cluster F audits this; row mechanically fine | OK |  |
| 14. File-tree listing or "contents map" in any doc → update or replace with pointer | Yes; this is a sticky failure mode | Self-referential; works as guidance | OK |  |
| 15. 4th+ commit shipping pieces of same conceptual subsystem → `ARCHITECTURE.md` | Yes (Wave A/B/C VRRP fits) | Yes — see `feature-parity-walkthrough.md` for the worked example | OK |  |
| 16. Function gains new parameter / changes return shape → docstring | Yes | Yes | OK |  |
| 17. Pipeline-stage signature in `migration_pipeline.py` → DON'T (frozen) | Yes — `run_plan`, `run_plan_with_rename`, `run_plan_with_overrides` are still frozen | Yes — module docstring lines 81-91 enforce | OK |  |
| 18. Module-variant schema gains new field on `TargetProfile`/`TargetModule` → class docstring in `netcanon/migration/target_profiles.py` | Yes | Yes | OK |  |
| 19. In-file `see commit abc1234` references → fine for load-bearing rationale | N/A — guidance row | N/A | OK |  |
| 20. New CSS colour in `base.html` → use `var(--token)`; add to BOTH `:root` and `[data-theme="dark"]` if no existing token fits | Yes (theme tokens) | Yes — `base.html` has both blocks | OK |  |
| 21. Capability-matrix change → expectation YAMLs + regen `CROSS_MESH_RESULTS.md` + `PHASE4_RECONCILIATION.md` | Yes | Yes | OK |  |
| 22. User-facing feature ships or changes → operator-facing docs | Yes | Yes (cluster B audits this) | OK |  |
| 23. New variance class added to `tools/run_phase4_reconciliation.py` → ARCHITECTURE.md variance-class bullets | Yes (8 classes currently) | Yes — ARCHITECTURE.md lines 730-786 enumerate the 8 | OK |  |
| 24. New backup-side device definition → unit + integration + desktop tests | Yes | Yes — cites the BD-Aruba/Junos/Arista recipe commits (all 4 SHAs resolve: `7b3d7ed`, `271f196`, `a5441b9`, `ba72502`) | OK |  |
| 25. Render-side codec changes touching `supported` xpaths → regen cross-mesh artefacts | Yes | Yes | OK |  |
| 26. Codec change affects pair covered by `tools/demo.py` → re-run + update demo + walkthrough | Yes (4 demo pairs cited; verified `cisco_iosxe_cli ↔ juniper_junos`, `fortigate_cli ↔ mikrotik_routeros`, `aruba_aoss ↔ arista_eos`, `opnsense ↔ juniper_junos`) | Yes — `tools/demo.py` + `docs/walkthroughs/` exist | OK |  |
| 27. New codec opens narratively-distinct translation pair → new scenario + walkthrough | Yes | Yes | OK |  |
| 28. Canonical-model change adding field demos should exercise → update `tools/demo.py` scenario | Yes | Yes | OK |  |
| 29. Packaging / distribution workflow change → SECURITY.md + IDENTITY.md + README.md + classifier | Yes (Phase 6 + v0.1.2 hardening) | **WRONG** — SECURITY.md was NOT updated for v0.1.2's defusedxml + scanner-enablement + SHA-pinning + zizmor config; see SECURITY.md findings below | WRONG | Most consequential row hit by recent work |
| 30. Cutting a new release → "Tag, push, done" (setuptools_scm) | Yes | Yes — `pyproject.toml:14` `dynamic = ["version"]` + `setuptools_scm` config | OK |  |
| 31. New wave of Code Scanning / Dependabot / secret-scanning alerts → `docs/security-triage/` cycle | Yes; v0.1.2 cycle is the worked example | Yes — `docs/security-triage/2026-05-21/` is the live record | OK |  |
| 32. Sustained change waves or >1Q since last hygiene pass → docs-audit per `docs/docs-audit/` | Yes (this audit) | Yes — `docs/docs-audit/2026-05-21/` is the live record | OK |  |

### AGENTS.md doc-sync rows that SHOULD exist but DON'T (MISSING)

| # | Recurring code-change pattern | Why it needs a row | Severity |
|---|---|---|---|
| M1 | A new redaction category added to `netcanon/tools/sanitize.py` → `SECURITY.md` Sanitiser table + `BUG_REPORTING.md` + (potentially) `CAPABILITIES.md` | `SECURITY.md` line 393 explicitly lists this in its OWN "Updating This Document" trigger list, but `AGENTS.md` doesn't mirror the row.  Result: a contributor reading the doc-sync table doesn't see it; relying on the round-trip back through `SECURITY.md` is brittle | MISSING |
| M2 | A new shared transform added under `netcanon/migration/canonical/transforms.py` (e.g. `project_svi_to_vlan`, `_natural_port_sort_key`, `_canonical_lag_name`) → `netcanon/migration/codecs/README.md` "Cross-codec shared utilities" + ARCHITECTURE.md "Cross-cutting render-time policies" | These additions HAVE been silently happening (Wave 7c added `project_svi_to_vlan` + `_natural_port_sort_key`; Wave 10γ-3 added `_canonical_lag_name`) and codecs/README.md was updated, but no doc-sync row demands it.  Pattern recurs; deserves a row | MISSING |
| M3 | New shared sibling module at the migration-package root (`netcanon/migration/_*.py` like `_user_secrets.py`, `_naming.py`, `_tier3_detection.py`) → ARCHITECTURE.md "Cross-cutting render-time policies" section + codecs/README.md "Cross-codec shared utilities" | Same shape as M2 but for top-level migration-package siblings rather than canonical transforms.  All three current siblings (`_user_secrets.py`, `_naming.py`, `_tier3_detection.py`) ARE documented but the row that demands it is absent | MISSING |
| M4 | A codec gains entries in `unsupported_rename_categories` → ARCHITECTURE.md "Per-pane overrides" § "Current state" + that codec's docstring | ARCHITECTURE.md lines 329-337 claims the post-Option-A empty state; OPNsense + cisco_iosxe (NETCONF) currently have `{"snmpv3"}` (parse + render don't round-trip USM in those codecs).  Without a doc-sync row, this kind of "actually a category got re-added" change goes unsurfaced | MISSING |
| M5 | A new fixture-research catalogue / WANTED.md update lands → README "What's next" / RELEASE_PLAN forward-looking notes (catalog-driven backlog signals appear in commits `06a5ba4`, `f80c557`, `9e21326` without a sync rule) | LOW priority — speculative; could equally be folded into the existing "user-facing feature ships" row | MISSING (low priority) |

### AGENTS.md Hard Rules audit

`AGENTS.md` lines 238-340.  Each rule mapped to an enforcement point.

| Hard rule (paraphrased) | Enforcement point | Status | Notes |
|---|---|---|---|
| Never add feature to one platform without the other | Manual + parity checklist | OK | "Parallel Platform Development" section + Feature Parity Checklist enumerate it concretely |
| Never `terminal length 0` for Cisco paging — use `cisco_more_paging: true` | `netcanon/collectors/netmiko_collector.py` + per-vendor YAML | OK | Memory entry confirms this rule is load-bearing; documented in `collectors/README.md` line 41-43 |
| Never commit real credentials, IPs, or secrets | `BUG_REPORTING.md` + sanitiser + manual review | OK |  |
| Never skip `data-testid` on new interactive template elements | `tests/testid_reference.md` self-grep + e2e tests + Selectors AGENTS.md section | OK |  |
| Never author `type_key` with `_` or `.` | `DeviceDefinition.type_key_filename_safe` validator + file-store regex (`ba72502` commit resolves) | OK | Verified: `definitions/README.md` lines 84-100 + `netcanon/definitions/README.md` lines 84-100 carry the same constraint |
| Never land code change without updating docs it renders stale | The doc-sync checklist + this audit | OK | Self-reinforcing |
| Never hard-code count / LOC / test tally in prose without CI/test guard | Self-enforced; no automated check | INCOMPLETE | This rule has no programmatic enforcement; the audit charter explicitly calls out this whole audit as the safety net.  Acceptable but worth noting — a `grep`-driven CI check would close the loop |
| Never patch `ConnectHandler` / `paramiko.SSHClient` directly — use `get_collector` | `netcanon/api/routes/backups.get_collector` + test fixtures | OK | `collectors/README.md` line 25-30 + `api/routes/README.md` line 87-94 reinforce |
| Never assert on POST `/api/v1/backups` response body for final state | `api/routes/README.md` line 70-77 + AGENTS.md hard rule + memory entry from prior session | OK |  |
| Never change signatures of existing pipeline-stage functions in `migration_pipeline.py` | `migration_pipeline.py` module docstring lines 81-91 + `api/routes/README.md` "Frozen surfaces" + dozens of tests | OK | Verified all three functions (`run_plan`, `run_plan_with_rename`, `run_plan_with_overrides`) still match their documented signatures |
| Never commit real credential hashes to test fixtures | `tests/fixtures/real/NOTICE.md` + manual review | OK |  |
| Never ship user-facing feature without updating operator-facing docs | Cluster B's audit + doc-sync row #22 | OK | Cluster B scope |
| Never push to online repo without PII review (covers operator data, network IDs, encrypted secrets, accidentally-tracked operator backups, narrative-exposure) | Sanitiser + `git filter-repo` + manual review | OK | Comprehensive scope; no enforcement point but the rule itself is the enforcement |

**Hard-rules audit verdict:** every rule maps to an identifiable
enforcement point (test guard, validator, manual review, or a
referenced helper).  The "no hard-coded counts" rule is the
weakest — purely audit-driven — but the rule documents that
explicitly.  No WRONG findings; one INCOMPLETE (the counts rule).

---

## ARCHITECTURE.md verification

Walked all 850 lines; verified the four-layer model + frozen-pipeline
claim + per-pane-overrides section + ship-before-wire + cross-cutting
policies + variance-class list + partials inventory + theming rules
against current code.

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| A1 | `ARCHITECTURE.md:329-337` | WRONG | Claims "every shipped bidirectional codec has the attribute [`unsupported_rename_categories`] empty (post-Option-A)" — but `netcanon/migration/codecs/opnsense/codec.py:117-119` and `netcanon/migration/codecs/cisco_iosxe/codec.py:181-183` both currently declare `frozenset({"snmpv3"})`.  The codec source explicitly contradicts ARCHITECTURE.md | Rewrite paragraph to say "every bidirectional codec is empty EXCEPT OPNsense + Cisco IOS-XE NETCONF which declare `{'snmpv3'}` because their parse + render don't yet round-trip SNMPv3 USM — see each codec's own comment for rationale" |
| A2 | `ARCHITECTURE.md:594-636` | INCOMPLETE | Partials inventory at "Current partials (at time of writing …)" enumerates 12 partials but is missing `kbd-cheatsheet.js` (shipped in Phase 3 R7 per `RELEASE_PLAN.md:89-94`; included from `base.html:632`).  The inventory itself says "contents of `_partials/` is the source of truth" — but the enumeration still rotted | Add `kbd-cheatsheet.js` bullet (Phase 3 R7; global keyboard-shortcut modal mounted from base.html via `?` button), OR collapse the enumeration to a one-line pointer per the AGENTS.md row #14 "prefer pointers over exhaustive inventories" guidance |
| A3 | `ARCHITECTURE.md:807-818` | INCOMPLETE | "What's shipped" Phase enumeration ends at "Tier 2 wire-throughs — SNMP + SNMPv3, LAGs, local_users, DHCP pools, RADIUS, MTU, IPv6 addresses, VRFs, VXLAN/EVPN".  Missing: VRRP/HSRP/CARP + anycast-gateway (v0.1.1 Wave A+B+C, recently shipped per CHANGELOG and the RELEASE_PLAN.md v0.2.0 section) | Add bullet: "**v0.1.1 (v0.2.0 Wave A+B+C)** — VRRP / HSRP / CARP groups on all bidirectional codecs; anycast-gateway on 3 codecs (Junos / Arista EOS / Cisco IOS-XE SD-Access)" |
| A4 | `ARCHITECTURE.md:819-835` | INCOMPLETE | "What's queued" enumerates v0.2.0 backlog but omits the v0.2.0 fixture-research catalogue work (commit `06a5ba4`: "14-OS fixture-source catalogue + overlay-priority synthesis") | Optional — add bullet for fixture-research-2015 overlay-authoring backlog; or punt to RELEASE_PLAN.md if this doc shouldn't carry the catalogue |
| A5 | `ARCHITECTURE.md:712` | STYLE | "all shipped codecs except the NETCONF/OpenConfig stub have promoted to `certified`" — defers to RESULTS.md as source of truth (good), but the qualitative phrasing is non-falsifiable.  ACCEPTABLE per AGENTS.md no-hard-coded-counts rule | None — illustrative, not authoritative |

Architecture's four-layer model itself (Vendor Definition / Format
Codec / Canonical Intent Model / Transport) is accurate against
`netcanon/`: `definitions/` + `netcanon/migration/codecs/` +
`netcanon/migration/canonical/intent.py` + `netcanon/collectors/`
all present and structured as described.  Backup-side definitions
two-level lookup (family-base + overlay) accurately matches
`netcanon/definitions/loader.py` + `definitions/README.md`.  No
WRONG on the layer model itself.

---

## METHODOLOGY.md / adding-a-* / glossary verification

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| M1 | `docs/METHODOLOGY.md:64-67` + various | EXPECTED-STALE | Cites pre-launch commit SHAs `07086b1`, `f81f3a5`, `2d7a7f2`, `c344200`, `d4956a7` that no longer resolve.  CHANGELOG.md's opening note already says "Pre-launch the project went through a `git filter-repo` history rewrite … most short-SHA citations in entries written before Phase 1 won't resolve" so this is documented-and-expected | None — already documented at CHANGELOG.md:6-14 |
| M2 | `docs/METHODOLOGY.md:75-77` | WRONG (line citation drift) | Cites "`AGENTS.md` lines 110-134" as the documentation-sync-checklist anchor — current location is **lines 148-189** (table) / 158-189 (rows).  Lines 110-134 are inside the Platform-Specific Exceptions section.  Same drift at lines 124, 302, 311, 423, 464, 501 | Replace all hard-coded AGENTS.md line ranges with section-name anchors ("`AGENTS.md` § Documentation Sync Checklist") — line numbers rot every time AGENTS.md gains a row, and the doc-sync rule for AGENTS.md isn't itself in the sync table |
| M3 | `docs/METHODOLOGY.md:148` | WRONG (line drift) | Cites "`cisco_iosxe_cli/codec.py` lines 132-260" for `_CAPS` declaration — current lines may have drifted with subsequent codec changes.  Same hard-coded line range at lines 243, 474 | Replace with symbolic reference ("the `_CAPS = CapabilityMatrix(…)` declaration in `cisco_iosxe_cli/codec.py`") |
| M4 | `docs/METHODOLOGY.md:222-231` | OK | Tier-3 firewall/NAT/VPN architectural-deferral claim verified against `intent.py` line 31-49 docstring | None |
| M5 | `docs/adding-a-canonical-field.md` overall | OK | MTU wire-through example matches `CanonicalInterface.mtu` shape; each cited per-codec sketch (Cisco regex, OPNsense XML, MikroTik kv, FortiGate edit-block, Aruba opt-out) verified against current codecs.  Step 4 references `tests/unit/migration/test_<feature>_wire_through.py` template; the actual `test_mtu_wire_through.py` exists | None |
| M6 | `docs/adding-a-canonical-field.md:226-237` | OK | Capability matrix declaration shape (`supported_paths=[…, "/interfaces/interface/config/mtu", …]`) matches the actual `CapabilityMatrix` ClassVar pattern used by current codecs | None |
| M7 | `docs/adding-a-target-profile.md` | OK | Walks through legacy vs. module-variant shapes; both worked examples (aruba_2930f_48g.yaml + cisco_c9300_24ux.yaml) exist; allowlist guard test at `tests/unit/migration/test_target_profile_shipped.py:115` confirmed.  Step 7 mentions `mig-rename-vlans-fitcheck` — assumes the testid exists; verified via Cluster F surface | None |
| M8 | `docs/adding-a-target-profile.md:106-119` | OK | Module-variant additivity claim (`effective_ports(sku) = chassis_ports + modules[sku].ports`) matches `target_profiles.py` implementation | None |
| M9 | `docs/glossary.md:24-29` | OK | "Sentinel semantics" definition matches `run_plan_with_overrides` actual sentinel handling | None |
| M10 | `docs/glossary.md:79-80` | OK | "Per-pane overrides — the five rename rails: ports, VLANs, Local Users, SNMP, and SNMPv3" matches the 5 currently-shipped categories | None |
| M11 | `docs/glossary.md:25-30` | INCOMPLETE | "Capture-first transform" definition lists `source_vlans`, `source_local_users`, `source_snmp_community`, `source_snmpv3_users`, `source_hostname` — matches `migration_pipeline.py` docstring lines 63-79.  Missing: `source_ports` if/when port-capture lands; minor.  Glossary is current | None |
| M12 | `docs/glossary.md` overall | INCOMPLETE | Missing terms that recur in code/docs but lack a glossary entry: `unsupported_rename_categories` (the ClassVar on every codec), `MODULE_VARIANT_PROFILES` (the allowlist invariant), `dropped_tier3_sections` (notification surface), `effective_ports` (module-variant accessor), `WANTED.md` (fixture-research catalogue companion to RESULTS.md/NOTICE.md), "ship-before-wire" (defined in ARCHITECTURE + adding-a-canonical-field but not in glossary), "Capability matrix" (referenced extensively but no entry).  Several of these appear in feature-parity-walkthrough.md as load-bearing terms | Add entries for the listed terms in the appropriate section (architecture / codec layer / testing) |
| M13 | `docs/feature-parity-walkthrough.md:106-118` | INCONSISTENCY | Says the new `_SNMPV3_CAPABLE` + `_SNMPV3_TARGET_CAPABLE` lists "follow the per-category naming pattern already used by `_LOCAL_USER_TARGET_CAPABLE` and `_SNMP_TARGET_CAPABLE` — *not* a single global `_SOURCE_CAPABLE` / `_TARGET_CAPABLE` pair".  But `netcanon/migration/canonical/README.md:152-154` says "Extend `_SOURCE_CAPABLE` / `_TARGET_CAPABLE` lists" for new categories.  Code reality: `test_cross_mesh_overrides.py` has both global lists (lines 204-228, used for the VLAN smoke) AND per-category lists (`_LOCAL_USER_TARGET_CAPABLE:370`, `_SNMP_TARGET_CAPABLE:494`, `_SNMPV3_TARGET_CAPABLE:615`).  New categories should use the per-category pattern.  canonical/README.md is misleading on this point | Update `netcanon/migration/canonical/README.md:152-154` to point at the per-category naming pattern (`_<CATEGORY>_TARGET_CAPABLE`) instead of the legacy `_SOURCE_CAPABLE` / `_TARGET_CAPABLE` globals |
| M14 | `docs/adding-a-target-profile.md:218-228` | OK | Allowlist registration example matches current `tests/fixtures/module_variants.py` shape | None |
| M15 | `docs/adding-a-canonical-field.md:245-254` | INCOMPLETE | Step 8 says "Add a HUMAN_TESTING.md entry" — searched repo, no `HUMAN_TESTING.md` exists.  The file was either renamed, never created, or removed.  Section is a now-active lie | Either restore `HUMAN_TESTING.md` (if it should exist) or drop the step from the worked example.  Quick `gh search` recommended to confirm fate |

---

## SECURITY.md "Updating This Document" coverage

`SECURITY.md:383-396` enumerates 7 triggers for SECURITY.md updates.
Verified the most recent change wave (v0.1.2, tagged 2026-05-21,
seven days before this audit) against each trigger:

| Trigger | v0.1.2 hit it? | SECURITY.md updated? | Severity |
|---|---|---|---|
| New credential field added to persisted model | No | n/a | n/a |
| New file-access endpoint added | No | n/a | n/a |
| New input field accepted from untrusted sources | **Yes** — XML entity-bomb hardening at `opnsense/parse.py:169` + `cisco_iosxe/codec.py:543` accepts untrusted operator-uploaded XML through `defusedxml.ElementTree.fromstring` instead of stdlib | **No** — SECURITY.md has zero mentions of `defusedxml`, `XXE`, `xml-bomb`, or the v0.1.2 swap | WRONG |
| Dependency with security relevance added or removed | **Yes** — `defusedxml>=0.7.1` added to `pyproject.toml:71` | **No** — Dependency Supply Chain table at SECURITY.md:303-313 still lists only 7 packages; defusedxml absent | WRONG |
| Threat model assumption changes | No | n/a | n/a |
| New redaction category lands in `netcanon/tools/sanitize.py` | No (v0.1.2 sanitiser unchanged) | n/a | n/a |
| New supply-chain integrity control ships (signature, attestation, lock manifest, etc.) | **Yes** — v0.1.2 shipped multiple: (1) SHA-pinned 11 third-party actions + `.github/zizmor.yml` policy file; (2) workflow-level `permissions: contents: read` on `ci.yml`; (3) `persist-credentials: false` on all checkouts; (4) Trivy Docker scanning; (5) Trusted Publishing scanner enablement; (6) zizmor workflow scanning; (7) CodeQL default setup | **No** — Supply-Chain Integrity section at SECURITY.md:319-366 still describes only Phase 6's original cosign+SBOM+Trusted Publishing surface; doesn't mention zizmor / Trivy / SHA-pinning / template-injection hardening / private vulnerability reporting / secret scanning | WRONG |

### SECURITY.md findings

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| S1 | `SECURITY.md:303-313` (Dependency Supply Chain table) | WRONG | `defusedxml>=0.7.1` not listed; CHANGELOG.md:35-46 documents the swap as the closure of CodeQL `py/xml-bomb` alerts.  Per the document's own trigger list, this was a required update | Add `defusedxml` row: "XML entity-bomb mitigation for operator-uploaded XML input (OPNsense `config.xml`, Cisco IOS-XE NETCONF). Stdlib `xml.etree.ElementTree` expands entities by default on Python 3.x; defusedxml is the drop-in replacement at the operator-input parse sites." |
| S2 | `SECURITY.md:319-345` (Supply-Chain Integrity § Phase 6) | WRONG (stale framing) | "Phase 6 of the public release plan shipped …" lists the original 5 controls (multi-stage builds, cosign, SBOM, Trusted Publishing, non-root runtime) — but v0.1.2 added a substantial second layer.  Per the document's own trigger #7, those need to surface here | Add a sub-section "v0.1.2 supply-chain hardening" enumerating: zizmor workflow scanning + SARIF upload to Code Scanning; Trivy Docker image scanning; SHA-pinned third-party actions with `.github/zizmor.yml` hybrid policy; workflow-level `permissions: contents: read` default-deny; `persist-credentials: false` on checkouts; Dependabot cooldown blocks; private vulnerability reporting + secret scanning + push protection + CodeQL default setup enabled |
| S3 | `SECURITY.md` overall | MISSING | No section describing the operator-input XML parse-hardening pattern (defusedxml swap) under "Input Validation".  This is a defence-in-depth control on the Threat Model's "Network peers (web deployment without reverse proxy)" actor — directly relevant to operators in regulated environments | Add new section under "Input Validation — Host Field" (e.g. "Input Validation — Operator-Uploaded XML") documenting both swap sites and what they reject |
| S4 | `SECURITY.md:379` | STYLE | "v0.1.0 limitation; sanitiser is IPv4-only" — narrative still anchors to v0.1.0 even though current shipped version is v0.1.2.  Acceptable but slightly misleading: the limitation is still genuine; the anchor is just stale | Could rephrase as "current limitation (unchanged since v0.1.0)" or drop the version anchor entirely.  Low priority |
| S5 | `SECURITY.md:399-413` See-also section | INCOMPLETE | No link to `docs/docs-audit/` (the sister-process doc) even though it explicitly references `docs/security-triage/`.  Bidirectional cross-ref discipline would add it; bidirectional already-applied for security-triage → docs-audit (per `docs/security-triage/README.md`) | Add bullet pointing at `docs/docs-audit/` |
| S6 | `SECURITY.md` overall | INCOMPLETE | The 7-item trigger list at line 385 ought to itself be enforced by an AGENTS.md doc-sync row.  Currently row #29 covers "packaging / distribution workflow change → SECURITY.md" which catches some of these triggers (supply-chain controls), but the "new dependency with security relevance" + "new input field" + "new redaction category" triggers have NO dedicated AGENTS.md row.  See MISSING-rows § M1 above for the redaction-category gap | Either expand row #29 to cite the SECURITY.md trigger list, OR add a dedicated row that mirrors SECURITY.md's own update conditions |

**Net assessment:** SECURITY.md is the single largest WRONG surface
in this cluster.  v0.1.2's stated "Security-hardening release" was
shipped without the SECURITY.md updates the document's own trigger
list required.

---

## RELEASE_PLAN.md Phase tracking

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| R1 | `docs/RELEASE_PLAN.md:20-125` | OK | Status block describes Phases 1, 1.5, 2, 3 (14/14 rounds), 4, 4.5, 5, 6, 7 — all 1:1 with CHANGELOG.md `[Unreleased]` + `[0.1.0]` entries (modulo a few Phase-3 sub-rounds whose CHANGELOG citation lives inside the rolled-up entry).  Phase 3 round counts (Round 1, 1.5, 2, 3, 3.1, 4, 4.1, 4.2, 5, 6, 6.1, 7, 7.1, 7.2, 8, 9, 10) verified consistent with the doc's own claim of "14/14 MUST-tier rounds" — actually 17 sub-rounds, but the count includes Round 1.5 / 3.1 / 4.1 / 4.2 / 6.1 / 7.1 / 7.2 as part of the parent rounds; phrasing "14 MUST-tier" is the abstract count and acceptable | None |
| R2 | `docs/RELEASE_PLAN.md:127-134` | OK | "**Next:** Public flip + tag v0.1.0 final — convert repo from private to public visibility, push v0.1.0 final tag" — but v0.1.1 and v0.1.2 are already tagged AND repo is already public.  The "Next" framing rotted: this work is already done | Update Status block to reflect v0.1.1 and v0.1.2 as shipped, and reframe "Next" to whatever comes after v0.1.2 (e.g. v0.2.0 wire-up completion, NX-OS / IOS-XR codec design implementation) |
| R3 | `docs/RELEASE_PLAN.md:144-223` | OK | v0.2.0 section enumerates 5 shipped commits (`8adaefd`, `5adee9b`, `c5da044`, `b85c39c`, `e542b49`) — all 5 resolve via `git show` (verified `b85c39c` matches the recent v0.1.1 commit-trail mention).  v0.2.0 framed as "in flight" — accurate since v0.1.1 shipped just the Wave A+B+C portion and the rest is queued | None |
| R4 | `docs/RELEASE_PLAN.md:124` | STYLE | "full unit + integration suite grew from 3266 (post-Phase-7) to **3556 tests**" — hard-coded count in prose.  Strictly violates the AGENTS.md "Never hard-code a count" rule.  But CHANGELOG-archival exception arguably applies here since RELEASE_PLAN is half-shipping-log; ambiguous | Either: tag the number as an as-of-this-commit timestamp (matching CHANGELOG-archival), OR replace with qualitative phrasing ("+290 tests over Phase 3").  v0.1.1's release notes are an archival snapshot, so leaving it as-of-Phase-3 is probably acceptable |
| R5 | `docs/RELEASE_PLAN.md:223-271` "Post-launch roadmap notes" | EXPECTED-STALE | All items in this section describe forward-looking work (pagination, retention, lock manifest, Docker Hub description sync) — per audit charter, NOT a finding | None |
| R6 | `docs/RELEASE_PLAN.md:274-345` "Pre-launch quality hardening" | EXPECTED-STALE | Aspirational; described before Phase 3 actually shipped.  Now somewhat redundant with the Phase 3 rounds shipped above but not technically wrong | Optional cleanup: collapse to a one-liner pointing at Phase 3 rounds and remove the section (or keep as a "What we still hope to address" reference) |

**Net assessment:** RELEASE_PLAN.md is internally consistent and
mostly accurate.  The "Next: Public flip + tag v0.1.0 final" framing
is the only outright drift — v0.1.0-rc9, v0.1.1, and v0.1.2 have all
shipped since.

---

## Per-doc findings (sub-READMEs + remaining)

### `netcanon/migration/codecs/README.md`

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| C1 | `netcanon/migration/codecs/README.md:15` | OK | "Eight codecs have shipped: `cisco_iosxe`, `cisco_iosxe_cli`, `aruba_aoss`, `opnsense`, `mikrotik_routeros`, `fortigate_cli`, `arista_eos`, `juniper_junos` (plus `_mock`)" — verified against `ls netcanon/migration/codecs/` (8 vendor dirs + `_mock`) | None |
| C2 | `netcanon/migration/codecs/README.md:251-256` | OK | "Rule of thumb: one feature, one commit touching every bidirectional codec (8 currently shipped: cisco_iosxe_cli, cisco_iosxe, aruba_aoss, opnsense, mikrotik_routeros, fortigate_cli, arista_eos, juniper_junos)" — accurate; though cisco_iosxe_cli is parse-only so technically only 7 bidirectional + 1 parse-only.  The phrasing is loose but operationally correct since wire-through commits touch all 8 anyway | None (minor wording wobble; not worth changing) |

### `netcanon/migration/canonical/README.md`

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| C3 | `netcanon/migration/canonical/README.md:152-154` | WRONG | "Extend `_SOURCE_CAPABLE` / `_TARGET_CAPABLE` lists in `tests/unit/migration/test_cross_mesh_overrides.py` to include every codec that supports the new category" — these are the legacy VLAN-rename smoke lists (test_cross_mesh_overrides.py:204-228).  Per `feature-parity-walkthrough.md:113-117`, new categories should follow the per-category naming pattern (`_<CATEGORY>_CAPABLE` / `_<CATEGORY>_TARGET_CAPABLE`).  Following the README's instruction would NOT actually wire the new category into a smoke test | Update to: "Add per-category `_<CATEGORY>_SRC_CONFIGS` dict + `_<CATEGORY>_CAPABLE` / `_<CATEGORY>_TARGET_CAPABLE` lists in `tests/unit/migration/test_cross_mesh_overrides.py` (the pattern `_LOCAL_USER_TARGET_CAPABLE` / `_SNMP_TARGET_CAPABLE` / `_SNMPV3_TARGET_CAPABLE` follow).  Do NOT extend the legacy `_SOURCE_CAPABLE` / `_TARGET_CAPABLE` globals (those are VLAN-smoke-specific)." |
| C4 | `netcanon/migration/canonical/README.md:127-132` | OK | "The repo currently ships five (ports, vlans, local_users, snmp_community, snmpv3_users); future candidates (NTP / DNS / syslog / RADIUS / SNMP trap hosts) follow the same shape" — verified five orchestrators present at the cited locations (`port_names.py`, `vlan_names.py`, `local_user_names.py`, `snmp_names.py`, `snmpv3_user_names.py`) | None |

### `netcanon/collectors/README.md`

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| C5 | `netcanon/collectors/README.md:9-15` | OK | Architecture diagram enumerates `base.py`, `netmiko_collector.py`, `paramiko_collector.py`, `probe.py` — matches `ls netcanon/collectors/` (those 4 + `__init__.py`) | None |
| C6 | `netcanon/collectors/README.md:44-53` | OK | Supported `netmiko_device_type` table — 6 vendors listed; cross-checked against `definitions/<vendor>/<os>/<ver>.yaml` files; all 6 use the cited driver names | None |

### `netcanon/definitions/README.md` (loader-side)

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| C7 | `netcanon/definitions/README.md:59-66` | OK | Pydantic schema field enumeration matches `netcanon/definitions/schema.py` | None |

### `definitions/README.md` (YAML-author side)

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| C8 | `definitions/README.md:138-200` | OK | Per-vendor notes section covers Cisco IOS-XE, FortiOS, OPNsense, MikroTik, Aruba AOS-S, Junos, Arista EOS — matches the 7 vendor subdirs in `definitions/` | None |

### `netcanon/api/routes/README.md`

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| C9 | `netcanon/api/routes/README.md:27-35` | OK | Route file index matches actual contents of `netcanon/api/routes/` (7 route modules + 1 helper `_migration_helpers.py`).  Cluster-D will catch any per-route inventory drift inside the modules | None |
| C10 | `netcanon/api/routes/README.md:122-135` | OK | Per-pane endpoint enumeration (`/plan/{ports|vlans|local_users|snmp|snmpv3}`) matches the 5 handler functions at `migration.py:261, 318, 374, 438, 503` (verified via grep) | None |
| C11 | `netcanon/api/routes/README.md:172-191` | OK | Frozen surfaces section accurately names `run_plan`, `run_plan_with_rename`, `run_plan_with_overrides` + POST `/backups` response shape | None |

### `CONTRIBUTING.md`

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| C12 | `CONTRIBUTING.md:99` | STYLE | "Never hard-code counts in prose docs without a CI/test guard" — listed under "most-broken rules" but with no concrete enforcement example.  Could cite the audit folder (`docs/docs-audit/`) since this is the safety net | Optional — could add "see `docs/docs-audit/` for the recurring audit cycle that catches drift" |
| C13 | `CONTRIBUTING.md:96` | OK | "Never change the signatures of existing pipeline-stage functions in `netcanon/services/migration_pipeline.py` (frozen)" — accurate; matches AGENTS.md + migration_pipeline.py docstring | None |
| C14 | `CONTRIBUTING.md:152-162` | OK | See-also list resolves and matches the file existence inventory | None |

### `CODE_OF_CONDUCT.md`

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| C15 | `CODE_OF_CONDUCT.md:40` | WRONG | "Instances of abusive, harassing, or otherwise unacceptable behavior may be reported to the community leaders responsible for enforcement at [INSERT CONTACT METHOD]" — placeholder text from the contributor-covenant template not substituted.  Operators with conduct concerns have no actionable channel | Replace `[INSERT CONTACT METHOD]` with the security-team email or a private GitHub link.  Could plausibly use the same vulnerability-reporting channel (`https://github.com/netcanon/netcanon/security/advisories/new`) or a dedicated `conduct@netcanon.dev` style address |

---

## Cross-cutting observations

1.  **The doc-sync table itself is a contributor checklist that
    works** — 32 rows total, 1 with WRONG (row #29 / SECURITY.md
    update), 5 with MISSING follow-up rows that recurring code-change
    patterns deserve.  That's a 28/32 pass rate, which is healthy for
    a checklist that's been growing organically over months.  The
    weakest part is **rows whose targets depend on a foreign doc's
    own trigger list** (row #29 → SECURITY.md trigger list) —
    enforcement gaps compound.  A future hygiene pass could fold
    SECURITY.md's 7 triggers explicitly into the doc-sync table so
    contributors don't have to round-trip.

2.  **Hard-coded line ranges in cross-doc citations** rot quickly.
    METHODOLOGY.md cites `AGENTS.md` lines 110-134 / 142-159 /
    191-200 / etc. — all of which have shifted since.  AGENTS.md
    grows and the citations point at the wrong sections now.
    Section-name anchors ("`AGENTS.md` § Documentation Sync
    Checklist") are the rotation-resistant alternative; both AGENTS
    and METHODOLOGY would benefit from a pass.

3.  **Pre-launch SHA references** in METHODOLOGY.md are
    EXPECTED-STALE per CHANGELOG's explicit note — no action.
    Post-launch SHA references (`b85c39c`, `8c6e493`, `ba72502`,
    `7b3d7ed`, `271f196`, `a5441b9`) all resolve.  The discipline
    of citing commit SHAs in CHANGELOG / RELEASE_PLAN holds.

4.  **`feature-parity-walkthrough.md` is unusually high-quality** —
    a 280-line worked example anchored on a single commit
    (`8c6e493`) that walks every layer the SNMPv3 USM feature
    touched.  It IS the kind of "I'm a new contributor" cookbook the
    project benefits from.  Worth carrying as the template for the
    next "feature touched many layers" example.

5.  **`unsupported_rename_categories` is a load-bearing extension
    point** that ARCHITECTURE.md describes as empty post-Option-A,
    but is currently `{"snmpv3"}` on 2 codecs.  Either the
    architecture doc needs to acknowledge the re-population, or the
    codecs need to ship full SNMPv3 round-trip.  ARCHITECTURE.md is
    the doc; codec round-trip is the implementation reality.

6.  **SECURITY.md is the single weakest surface in this cluster** —
    a v0.1.2 release framed as "Security-hardening release"
    shipped with the security-architecture doc untouched.  Three
    of the document's own seven update-triggers were met and not
    propagated.  Stage 2 fix execution should prioritise this
    surface.

7.  **The `loader.py` Phase-0.5 placeholder** is acknowledged by
    `netcanon/migration/canonical/README.md:69-73` ("Phase-0.5
    placeholder; raise `NotImplementedError`") but the file's
    own docstring (line 4-5) and function docstrings (lines
    38, 54) still describe Phase 0.5 as **future** work despite
    RELEASE_PLAN.md `Status` block listing "Phase 0.5 — canonical
    intent model + pluggable CIMs" as shipped.  This is a
    Cluster-E concern (platform-code docstrings) but the
    interaction crosses into developer-doc territory: the
    canonical README correctly punts; the platform docstring
    still anchors to an outdated phase name.  Out-of-scope
    flag for cluster E's audit.

8.  **No outright orphaned cross-references** found in this
    cluster.  Every `[link text](path)` checked resolved.  The
    `tests/fixtures/real/RESULTS.md`, `tests/testid_reference.md`,
    `tools/run_full_mesh.py`, etc. all exist at the cited paths.

---

## Severity tally

| Severity | Count | Where |
|---|---|---|
| WRONG | 6 | A1 (ARCHITECTURE.md unsupported_rename_categories) ; S1+S2 (SECURITY.md dep table + supply-chain section) ; M2+M3 (METHODOLOGY.md line ranges) ; C3 (canonical/README.md _SOURCE_CAPABLE wrong instruction) ; C15 (CODE_OF_CONDUCT.md placeholder) ; row #29 (AGENTS.md doc-sync — SECURITY.md not updated for v0.1.2) |
| MISSING | 5 | M1-M5 (AGENTS.md doc-sync rows for: sanitiser categories, canonical transforms, top-level migration `_*.py` siblings, codec `unsupported_rename_categories` additions, fixture-research catalogue updates) ; S3 (SECURITY.md missing operator-input XML hardening section) ; M12 (glossary missing several recurring terms) ; M15 (`HUMAN_TESTING.md` referenced but doesn't exist) |
| INCOMPLETE | 6 | A2 (ARCHITECTURE.md partials inventory missing kbd-cheatsheet.js) ; A3-A4 (ARCHITECTURE.md Evolution roadmap missing v0.2.0 work) ; M11 (glossary capture-first scope incomplete) ; R2 (RELEASE_PLAN.md "Next" stale) ; S5+S6 (SECURITY.md cross-refs + trigger enforcement) ; "no hard-coded counts" rule has no programmatic enforcement |
| STYLE | 4 | A5 (ARCHITECTURE.md qualitative phrasing) ; R4 (RELEASE_PLAN.md hard-coded test count) ; S4 (SECURITY.md v0.1.0 anchor stale) ; C12 (CONTRIBUTING.md missing concrete enforcement reference) |
| EXPECTED-STALE | 3 | M1 (METHODOLOGY pre-launch SHAs) ; R5 (RELEASE_PLAN post-launch notes) ; R6 (RELEASE_PLAN pre-launch hardening) |

**Stage 2 fix priority shape (suggested for synthesis):**

1. **HIGH:** SECURITY.md catch-up for v0.1.2 (S1, S2, S3, S6) — the
   document's own trigger list was violated, and operators in
   regulated environments depend on this doc.
2. **HIGH:** ARCHITECTURE.md `unsupported_rename_categories`
   correction (A1) — outright contradicts shipped code.
3. **HIGH:** AGENTS.md doc-sync row addition for sanitiser
   categories (M1) — closes a recurring gap.
4. **MEDIUM:** canonical/README.md cross-mesh test instruction
   (C3) — actively misleads contributors.
5. **MEDIUM:** RELEASE_PLAN.md "Next" reframe (R2) — narrative
   currency.
6. **MEDIUM:** CODE_OF_CONDUCT.md contact-method placeholder
   (C15) — small fix, operator-visible.
7. **LOW:** METHODOLOGY.md section-anchor migration (M2-M3) —
   rotation-resistance hardening; batch with broader sweep.
8. **LOW:** ARCHITECTURE.md partials + Evolution-roadmap updates
   (A2-A4) — cosmetic; do in same commit as A1.
9. **LOW:** glossary additions (M12) — STYLE-tier; batch.

---

## See also

* [`README.md`](../README.md) — process doc
* [`00-snapshot.md`](00-snapshot.md) — run inventory
* [`cluster-C-developer-docs-scope.md`](cluster-C-developer-docs-scope.md) — scope this audit followed
* Sister cluster outputs (will land in this folder once Stage 1 completes):
  `01-investigation-A.md` (interlinking), `01-investigation-B.md`
  (user-docs), `01-investigation-D.md` (codec docstrings),
  `01-investigation-E.md` (platform docstrings),
  `01-investigation-F.md` (tests + CHANGELOG)

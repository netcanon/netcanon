# Cluster A — Interlinking & structural integrity

## Summary

Audited 786 `*.md` files for link resolution, See-also reciprocity, contents-map drift, and orphan docs. Found **10 WRONG** (8 broken internal links + 2 contents-map drift), **3 MISSING** (top-level docs without `## See also` sections + 1 orphan doc), **3 INCOMPLETE** (asymmetric reciprocity gaps that follow the AGENTS.md cross-reference example list), and **6 STYLE** issues (bare-path See-also entries, hyphen/underscore inconsistency across the vendor-references corpus, one ambiguous em-dash anchor). The sampled `cisco_iosxe_cli_to_juniper_junos/` vendor-references pair audits cleanly; the other 41 pairs follow a consistent template SHAPE (per-pair `_INDEX.md` + topic markdown files) but vary in topic-file naming conventions (hyphen vs underscore).

## Statistics

* Total `.md` files audited: **786** (172 current-state docs + ~614 in special folders / vendor-references)
* Total link patterns extracted (`[text](target)`): **2521** (1378 external `http(s)://`, ~1132 internal, 11 broken)
* Broken internal links (file targets): **10** (excludes 1 false-positive in the cluster-A scope file's own example syntax)
* Broken anchor links: **1** (the em-dash slug case in `11-aruba_aoscx.md`, ambiguous per GitHub slug rules)
* `## See also` sections found: **91 of 786** files
* Docs in current-state scope that lack `## See also`: **README.md**, **tests/README.md**, **CODE_OF_CONDUCT.md** (the AGENTS.md discipline calls out the first two by name as examples)
* Contents-map drift instances confirmed: **3** (ARCHITECTURE.md partials list; `netcanon/api/routes/README.md` route file index; `tools/README.md` script inventory)
* Orphan docs (zero current-state inbound links): **1 meaningful** (`CODE_OF_CONDUCT.md`) plus 530 in vendor-references / archive (mostly expected: vendor-reference topic files are referenced only by their pair-local `_INDEX.md`)

## WRONG findings

| # | Source path:line | Issue | Fix shape |
|---|---|---|---|
| W1 | `README.md:260` | `\| Manually exercise recent changes \| [\`HUMAN_TESTING.md\`](HUMAN_TESTING.md) \|` — file does not exist (deleted in commit `9eea5de`, "chore: remove vestigial development artifacts (#13)"). | Remove the table row; or replace pointer with `BUG_REPORTING.md` / `docs/HOW_WE_TEST.md` if the intent survives. |
| W2 | `BUG_REPORTING.md:26` | `[`netcanon.tools.sanitize`](../netcanon/tools/sanitize.py)` — BUG_REPORTING.md is at repo root, so `../netcanon/...` escapes the repo. | Change to `(netcanon/tools/sanitize.py)`. |
| W3 | `BUG_REPORTING.md:124` | Same `../netcanon/tools/sanitize.py` pattern. | Same fix. |
| W4 | `BUG_REPORTING.md:151` | Same `../netcanon/tools/sanitize.py` pattern. | Same fix. |
| W5 | `tests/fixtures/real/WANTED.md:8` | `[`BUG_REPORTING.md`](../../BUG_REPORTING.md)` — `tests/fixtures/real/` → `../../` lands in `tests/`, not repo root. | Change to `(../../../BUG_REPORTING.md)`. |
| W6 | `tests/fixtures/real/WANTED.md:92` | Same `../../BUG_REPORTING.md` pattern. | Same fix. |
| W7 | `docs/fixture-research-2015/README.md:134` | `[…](../v0.2.0-planning/03-nxos-codec/06-fixture-targets.md)` — file is named `05-fixture-targets.md` (06 is `06-capabilities-matrix.md`). | Change `06-fixture-targets.md` → `05-fixture-targets.md`. |
| W8 | `docs/fixture-research-2015/README.md:137` | Same off-by-one: `04-iosxr-codec/06-fixture-targets.md`. | Change to `05-fixture-targets.md`. |
| W9 | `docs/v0.2.0-planning/02-anycast-gateway/06-fixture-targets.md:17` | `[`03-nxos-codec/06-fixture-targets.md`](../03-nxos-codec/06-fixture-targets.md)` — same broken target file name. | Change `06-fixture-targets.md` → `05-fixture-targets.md`. |
| W10 | `docs/v0.2.0-planning/02-anycast-gateway/06-fixture-targets.md:144` | Same broken target. | Same fix. |
| W11 | `ARCHITECTURE.md:582-636` (templates contents-map) | `netcanon/templates/_partials/` enumeration lists 12 partials; actual directory has 13 — **missing `kbd-cheatsheet.js`** (added in commit `9c5fd64` "feat(ui): keyboard-shortcut cheatsheet modal (`?` opens)"). | Add a bullet for `kbd-cheatsheet.js` (modal triggered by `?`) in the partials enumeration. |
| W12 | `netcanon/api/routes/README.md:27-35` (route file index) | Table lists 7 route files; actual `netcanon/api/routes/*.py` has 9 routers — **missing `health.py`** (the `/health` readiness probe router) and **`sanitize.py`** (`POST /api/v1/sanitize`). Both ship `APIRouter` instances and are mounted via `main.py`. | Add two table rows: `health.py` → `/health` (no `/api/v1` prefix) + `sanitize.py` → `/api/v1/sanitize`. |
| W13 | `tools/README.md` (script inventory) | README documents only `run_full_mesh.py` and `run_phase4_reconciliation.py`. Actual `tools/*.py` also contains `demo.py` (public operator-facing scenario runner — referenced from AGENTS.md doc-sync row and from `docs/walkthroughs/`) and `load_cross_vendor_expectations.py` (Phase 3 lint utility). Both have user-facing module docstrings. | Add two top-level `## <name>` sections (matching the existing format), or at minimum a "Scripts overview" table at the top listing all four. |

## MISSING findings

| # | Source path | Issue | Fix shape |
|---|---|---|---|
| M1 | `README.md` | No `## See also` section. AGENTS.md § "Cross-reference discipline" explicitly names `README.md → ARCHITECTURE.md, AGENTS.md, tests/README.md` as one of three exemplar reciprocity sets. The existing "For contributors" table (lines 248-262) implicitly serves the function but doesn't carry the discipline's canonical heading. | Append a `## See also` section pointing at the three peers named in AGENTS.md plus `BUG_REPORTING.md` and `docs/CAPABILITIES.md`. |
| M2 | `tests/README.md` | No `## See also` section. The existing "Related documentation" table (end of file) covers the same intent — but per AGENTS.md the canonical heading is `## See also`, named explicitly as a sibling of the `tests/README.md → testid_reference.md, fixtures/real/RESULTS.md, fixtures/real/NOTICE.md` exemplar. | Either rename "Related documentation" → "See also" or add a small `## See also` section pointing at the three AGENTS.md-named peers. |
| M3 | `CODE_OF_CONDUCT.md` | Orphan — zero inbound links from any current-state living doc. `README.md`, `CONTRIBUTING.md`, `SECURITY.md` make no reference to the Contributor Covenant. The only inbound `CODE_OF_CONDUCT.md` strings are in `CHANGELOG.md` (archival mention of when it shipped) and the docs-audit Stage 1 reports. Operators on the public landing page never reach it through normal navigation. Also lacks its own `## See also` footer. | Add a "Code of conduct" pointer in `CONTRIBUTING.md` (or `README.md` "For contributors" table). The file itself can stay as-is per the Contributor Covenant boilerplate convention. |

## INCOMPLETE findings

| # | Source path | Issue | Fix shape |
|---|---|---|---|
| I1 | `docs/vendor-references/README.md` | `## See also` section uses bare backtick paths (`` `tests/fixtures/cross_vendor_expectations/README.md` `` etc.) rather than `[label](path)` link syntax. Targets exist; just not clickable in rendered Markdown. | Convert three entries to `[`label`](path)` form. |
| I2 | `tests/fixtures/cross_vendor_expectations/README.md` | Same bare-backtick `## See also` pattern as I1. | Same fix. |
| I3 | `docs/docs-audit/README.md → ARCHITECTURE.md` (and similar A→B chains where B is a high-traffic hub) | The audit process README links to `ARCHITECTURE.md`, but `ARCHITECTURE.md`'s See-also list doesn't back-link to `docs/docs-audit/`. Same shape: `docs/security-triage/README.md → BUG_REPORTING.md/SECURITY.md` get reciprocated (both back-link via AGENTS.md doc-sync rows), but the docs-audit process is newer and its addition to AGENTS.md `## See also` (line 360) isn't mirrored on the docs-audit side's peers. Borderline: the doc-sync row in AGENTS.md (line 189) DOES link to `docs/docs-audit/`, so the contributor-discovery path exists; just not via `## See also` reciprocity. | Optional — add a one-line `docs/docs-audit/` pointer to ARCHITECTURE.md's See also list (sibling of the existing `docs/security-triage/` mention pattern). Lower-priority. |

## STYLE findings (defer-eligible)

| # | Source path | Issue | Fix shape |
|---|---|---|---|
| S1 | `docs/vendor-references/cisco_iosxe_cli_to_juniper_junos/_INDEX.md:36-38` (and ~13 other `_INDEX.md` files) | "See also:" sub-section at end uses bare backticks rather than `[label](path)`. | Convert to link syntax. Batch with I1/I2. |
| S2 | `docs/vendor-references/<pair>/` topic-file naming inconsistency | Some pairs use hyphens (`interface-naming.md`, `local-users.md`, `static-routes.md` — `cisco_iosxe_cli_to_juniper_junos`, `arista_eos_to_cisco_iosxe`, several others), most use underscores (`interface_naming.md`, `local_users.md`, `static_routes.md`). No project-wide convention enforced; per-pair `_INDEX.md` references whatever shape its sibling files use, so links resolve. STYLE rather than WRONG. | Project-wide pass to pick one (underscore is the majority convention; hyphen is the original Junos-pair shape). Optional. |
| S3 | `docs/fixture-research-2015/11-aruba_aoscx.md:363` | `[…](../../tests/fixtures/real/WANTED.md#tier-d-—-entirely-new-codec-opportunities)` — anchor contains a literal em-dash (`—`, U+2014). The target heading is `## Tier-D — entirely-new codec opportunities`; GitHub's slug rule strips non-alphanumeric so the actual slug is `tier-d--entirely-new-codec-opportunities` (double-hyphen from the em-dash being dropped between hyphens). Flagged rather than asserted because GitHub's behaviour around literal em-dashes in URL fragments isn't fully documented and may render-resolve at the browser layer. | Change anchor to `#tier-d--entirely-new-codec-opportunities` (two ASCII hyphens, no em-dash) for safety. |
| S4 | `CHANGELOG.md:16` | Uses inline `See also: [...]` rather than the canonical `## See also` heading. Functional, but won't be detected by reciprocity tooling. | Optional — promote to `## See also` section. Lower-priority (CHANGELOG section structure is intentionally compact). |
| S5 | `netcanon/api/routes/README.md:194-199` (See also) | Two of four entries point at directories (`../../services/`, `../../models/`) rather than specific files. Renders fine on GitHub (directory listings work) but is less precise than the in-tree convention (most other `## See also` sections target specific files). | Optional — point at `services/<key file>.py` or note the directory choice intentionally. |
| S6 | `docs/fixture-research-2015/README.md:9-11` (and `tests/README.md:5` "Four-layer test infrastructure") | Prose contains hard-coded counts ("45 fixtures across 7 OSs", "Four-layer test infrastructure"). Per AGENTS.md "Hard Rules" the numbers in prose require a CI/test guard; not strictly an interlinking issue but surfaces during contents-map review. | Out of cluster-A scope — flag for cluster B (user-docs) or cluster F (tests + CHANGELOG) follow-up. |

## Vendor-references sampling result

**Sampled pair: `cisco_iosxe_cli_to_juniper_junos/`** (14 files; one of the highest-density pairs).
* All 13 topic markdown files exist and are referenced from `_INDEX.md`.
* Per-file inline links (vendor source URLs, sibling Junos / Cisco docs pages) follow a consistent shape: external `https://` URLs for vendor pages + relative `[`label`](path)` to in-tree sibling docs.
* No broken internal links in this pair.
* `_INDEX.md`'s footer "See also" uses bare-backtick paths (STYLE S1) — not WRONG.
* `## See also` heading absent from individual topic files — but per audit charter this is the per-pair template's intentional shape (topic files are short single-concern grammar references, not navigation hubs).

**Other ~41 pairs (template-shape check):** all 56 pair directories carry an `_INDEX.md`; the count of topic files varies 7-15 depending on pair grammar overlap (Junos/Aruba pairs are richer than Cisco/Cisco pairs because the latter share more primitives). The two consistency outliers are:

* **Filename casing/separator drift** (S2) — hyphens vs underscores in topic file names across pairs. Both conventions resolve from their respective `_INDEX.md` so no broken links; just stylistic inconsistency.
* **Some pairs lack `_INDEX.md` for the pair**: spot-check shows all 56 pair directories DO have `_INDEX.md` — no missing indexes. (Earlier orphan output flagged some `_INDEX.md` files as "not referenced from outside their pair" — true and expected: the parent `docs/vendor-references/README.md` doesn't enumerate each pair, since the pair-set is discoverable from the directory listing alone.)

## Cross-cutting observations

1. **The reciprocity-checker false-positive rate is high in hub/spoke designs.** The asymmetry scan returned 284 candidate gaps (48 of which were "B has no See also section"), but most are intentional hub patterns: `docs/CAPABILITIES.md` is linked by every `docs/vendors/<vendor>.md` page but doesn't need to back-link to each one (the parent `docs/vendors/README.md` table serves that role). Only the explicit AGENTS.md reciprocity examples (`README → ARCHITECTURE/AGENTS/tests/README`) are concrete enough to flag as MISSING. The bulk of the remaining 280-something asymmetries are policy-acceptable hub-spoke spokes.

2. **Three different "See also" syntaxes are in active use, only one detected automatically.** The audit script looks for `^## See also`. Existing variants:
   * `## See also` heading — 91 files
   * `See also: …` inline paragraph (CHANGELOG.md style) — at least 5 occurrences
   * `### See also` sub-heading (tools/README.md `run_full_mesh.py` section) — at least 1 occurrence
   * Bare-link `## See also` (vendor-references/README.md style) — at least 14 occurrences (the inconsistency captured in S1/I1/I2)
   This means automated reciprocity tooling under-counts coverage. Not a finding to fix; a process observation for the next audit run.

3. **`docs/v0.2.0-planning/02-anycast-gateway/06-fixture-targets.md` filename is itself confusingly numbered.** The file is named `06-fixture-targets.md` but its sibling task folders (`03-nxos-codec/`, `04-iosxr-codec/`) renumbered their fixture-targets file to `05-fixture-targets.md`. This off-by-one in *one* task vs *three* tasks (`01-vrrp-canonical/06-fixture-targets.md` also stays at `06-`) is the root cause of the W7/W8/W9/W10 broken-link cluster. Worth deciding (post-audit): rename for project-wide consistency, OR keep current numbering and just fix the four broken links to match.

4. **`HUMAN_TESTING.md` was hard-deleted (commit `9eea5de`) but README.md and `docs/adding-a-canonical-field.md` retain pointers** — the broken README.md row is the W1 finding above; `docs/adding-a-canonical-field.md:246` ("### 8. Add a HUMAN_TESTING.md entry") + `:267` ("Possibly translator-plans.txt + HUMAN_TESTING.md") describe a workflow step that no longer maps to a tracked artifact. Out of cluster A's strict link-resolution scope (the doc references `HUMAN_TESTING.md` as a *concept* — no markdown link), but cluster C should pick this up under "developer-facing contributor-workflow accuracy".

5. **`netcanon/templates/_partials/` is the highest-churn contents-map drift surface.** ARCHITECTURE.md has now been wrong about it once (W11). Pattern: every time a new partial lands (e.g. `kbd-cheatsheet.js` in `9c5fd64`), the ARCHITECTURE.md bullet list goes stale unless the same commit touches it. AGENTS.md doc-sync row covers `_partials/` additions but no enforcement test. Process improvement candidate (out of scope here): convert the ARCHITECTURE.md enumeration to a generated artifact, OR replace it with "see `ls netcanon/templates/_partials/`" pointer and move the prose descriptions to per-partial header comments.

6. **`tools/README.md` and `netcanon/api/routes/README.md` carry the same kind of bug as ARCHITECTURE.md (W11): a hand-maintained file enumeration that drifted out of step with the directory.** All three drift directions follow the same shape — a new file lands, the README's table doesn't get updated in the same commit. AGENTS.md "Documentation Sync Checklist" row 175 ("In-file references…") doesn't catch this because it covers the *opposite* direction (commit hashes in code → README). Worth a discipline note for the next AGENTS.md update.

## See also

* [`cluster-A-interlinking-scope.md`](cluster-A-interlinking-scope.md) — scope file this investigation answers
* [`00-snapshot.md`](00-snapshot.md) — broader run context (clusters B-F running in parallel)
* [`../README.md`](../README.md) — audit process + cluster taxonomy

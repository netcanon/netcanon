# 43 — Product adversarial verification (covers 17-tests, 19-docs-ux, 21-cli-api)

Verifier: Fable adversarial pass, 2026-07-03. Method: every finding re-checked
against the live file (`path:line` re-read) and, where behavioural, re-reproduced
with my own read-only `py -c` probes (not the peer's transcripts). No files
touched except this report.

**Verdict: the three reports are unusually accurate — 22 of 24 findings CONFIRMED
as claimed, 2 DOWNGRADED to nit, 0 REFUTED, 0 killed as parked-architecture
duplicates.** All four majors survive adversarial re-verification, three of them
reproduced end-to-end by independent probe. Severity inflation is minimal; both
downgrades are in report 19's minor tail.

---

## Correction to the verification brief (important for synthesis)

The brief presumed 17 F-1 and 21 F-1 "describe the same /detect +
`source_filename` surface." **They do not — they are two distinct, independently
valid findings:**

- **17 F-1** = a dead integration test on `POST /api/v1/migration/detect` +
  `source_filename` (test-side defect).
- **21 F-1** = the `POST /api/v1/migration/plan` port-rename-map dispatch trap
  (API-contract defect). Different endpoint, different failure mode.

The only 21-report touchpoints on the /detect surface are F-8 (missing
`max_length` on the detect body) and a "checked, no finding" note that
`resolve_input_text` (the **/plan** loader) is traversal-guarded. Also for the
record: the /detect stored-file flow is **untested, not demonstrably broken** —
neither report claims it is broken, and the route body
(`netcanon/api/routes/migration.py:654-673`) is a straight
`storage.get_content` → `detect_codec` whose halves are covered separately
(404 at `test_migration_api.py:1727`, raw-text detect at `:1690-1762`). The gap
is real; the flow itself showed no defect under inspection.

## Parked-item adjudication (per the seed's "do not re-litigate" list)

Checked every finding against the parked port-name-layer architecture and the
declared-lossy-honesty concept. **Nothing needed killing:**

- **21 F-1 is NOT the parked item.** The parked decision is "bare `run_plan`
  renders verbatim names by design" (library layer). F-1 is about the HTTP
  `/plan` endpoint, whose adjudicated v0.3.2 contract is auto-translate-by-
  default — the finding shows an inconsistency hole *inside that shipped
  contract* (route conditional `migration.py:262-266`), and its suggested fix
  points in the same direction the adjudication chose. Keep.
- **19 M-2 / m-2 are NOT the declared-lossy-honesty concept.** They are
  *drift*: matrix reason-strings and CAPABILITIES.md rows left asserting the
  pre-0.4.13/0.4.14 state after the code graduated. The seed explicitly asks
  for regressions/drift in the honesty system. Keep.

---

## Report 17 — Tests

| ID | Adjudication | Final severity | Evidence |
|----|--------------|----------------|----------|
| F-1 | **CONFIRMED** | **MAJOR** | `tests/integration/test_migration_api.py:1780-1781` skips on `!= 200`; the route is `status_code=202` (`netcanon/api/routes/backups.py:143`) and 10+ sibling tests assert `== 202` (`test_backups_api.py:50` etc.) — the test has never run past the skip. Grep confirms lines 1792-1800 are the ONLY /detect+`source_filename` happy-path coverage. Fix-note also verified: the shared fixture's FakeCollector returns `CISCO_FAKE_OUTPUT` for every type_key (`tests/integration/conftest.py:35-39`), so `!= 202` alone would trade the silent skip for a wrong-content failure/skip at :1783/:1791. |
| F-2 | **CONFIRMED** | MINOR | Probe: `latest.json` stores `pair_codec_bug_counts` with per-pair `codec_bug_count` (arista→iosxe_cli:2, cisco_iosxe→iosxe_cli:1, junos→aoss:1, junos→iosxe_cli:1; total 5); the guard compares only total `<=` (`test_cross_mesh_ci_guard.py:136`) and pair-set membership (`:148-156`) — the 2→3-while-1→0 scenario passes green exactly as claimed. |
| F-3 | **CONFIRMED** | MINOR | Parametrize lists exactly 8 codecs (`test_canonical_vrrp_anycast_schema.py:405-417`); vyos declares vrrp-groups unsupported (`vyos/codec.py:358` — citation exact) yet `test_vyos.py:837-846` doesn't pin it; dangerous-direction mitigation verified real (`test_registry_capability_honesty.py:463-484` walks all `_CODEC_NAMES`). |
| F-4 | **CONFIRMED** | MINOR (hardening) | Marker is the exact substring `"# noqa: C901"` (`test_complexity_ratchet.py:36,49`); `PGH004` absent from the select list (`pyproject.toml:214-226`); `test_mccabe_gate_is_configured` (`:69-75`) never reads per-file-ignores (`pyproject.toml:279-292`, currently no C901). My grep count: 26 `noqa.*C901` hits = 25 production + the ratchet test's own marker-assembly line — codebase currently clean, matching the peer's probe. |
| F-5 | **CONFIRMED** | MINOR | `test_load_and_memory.py:334-368`: docstring says "Best-effort — flaky in CI envs" while asserting `total_delta < 5_000_000` hard; with `-x` in addopts one flake aborts the whole CI run. Not observed failing (pattern flag, honestly labelled by the peer). |
| F-6 | **CONFIRMED** | NIT | `test_cross_mesh_ci_guard.py:121` computes `failing - _ALLOWED_RENDER_FAILURES` only; a fixed pair leaves a stale allowlist entry. |
| F-7 | **CONFIRMED** | NIT | `test_migrate_page.py:433-434` conditional skip; configs dir is session-scoped-empty (`tests/e2e/conftest.py:112-115`), populated only by earlier files. `_find_free_port` TOCTOU at `:47-51` is the standard pattern. |
| F-8 | **CONFIRMED** | INFO | `skipif(sys.platform != "win32")` at `test_configs_api.py:182-211`; CI is ubuntu-only. Declared honestly in the skip reasons; correctly filed as info. |

## Report 19 — Docs-honesty + Web UI/UX

| ID | Adjudication | Final severity | Evidence |
|----|--------------|----------------|----------|
| M-1 | **CONFIRMED** | **MAJOR** | `adapterEntry` returns `{codec, label, desc, sample, ext, inputFormat}` — no `vendor_display_name`, no `name` (`migrate.html:860-875`); `:1373-1375` dereferences both → `undefined`; `escapeHtml` does `String(s)` (`:1629`) → literal `"undefined"` in the banner (`:1384-1390`) and button (`:1398-1399`). Trigger chain verified reachable: pipeline sets `job.error = f"parse failed: {exc}"` (`migration_pipeline.py:303`) → `:1301-1303` prefix match → enrichment fires in the normal case (adapters cache always loaded). Contrast at `:1146-1147` correct as claimed. Survival explanation verified: no test asserts the label or clicks the testid (grep: only `tests/testid_reference.md:513`). |
| M-2 | **CONFIRMED** | **MAJOR** | Three-way contradiction verified: junos supported list carries `/interfaces/interface/dot1q-vlan` with a "first codec wired" comment (`juniper_junos/codec.py:135-139`); the same file's subinterface `LossyPath.reason` still says "`unit N vlan-id 100` still parses-and-ignores" (`:264-277`) — and lossy reasons render to operators (`migrate.html:1610-1611`); parse.py wires it for real (`:1516-1528`); `docs/CAPABILITIES.md:278` repeats the stale sentence and the doc has zero `dot1q_vlan` mentions (only the unrelated IOS-XR phrasing at :31/:366). Drift, not the parked honesty concept. |
| M-3 | **CONFIRMED** | **MAJOR** (borderline — low practical legal risk, trivial fix) | All four direct runtime deps verified in `pyproject.toml` (`pydantic-settings:63`, `aiofiles:69`, `apscheduler:74`, `tzlocal:83`) and `requirements.lock` (:588/:7/:25/:756); zero hits for any of them (or rich/pygments/ruamel) in `THIRD-PARTY-NOTICES.txt`. `rich`/`ruamel-yaml` confirmed "via netmiko" in the lock (`:718,:722`) so they land in the MSI freeze. The file's own framing (lines 4-14, 69-71) claims MSI-redistribution completeness. |
| m-1 | **CONFIRMED** | MINOR | `SECURITY.md:232-240` claims browser-fetched passwords; `index.html:189-193` and `devices.html:412-433` document/implement server-side resolution; devices routes respond `DeviceProfilePublic` (`device_profiles.py:33,49`). Understates security + internally inconsistent, as claimed. |
| m-2 | **CONFIRMED** | MINOR | `CAPABILITIES.md:257` says "owner maps to … 254 (255 unrepresentable)"; code says "now representable" and maps owner↔255 both directions (`aruba_aoss/parse.py:604-605,651-659`, `render.py:673-678`). |
| m-3 | **CONFIRMED** | MINOR | `CONTRIBUTING.md:50-52` tells contributors `--matrix` regenerates `PHASE4_RECONCILIATION.md`; `tools/run_full_mesh.py:24-29` says `--matrix` writes `CROSS_MESH_RESULTS.md`. Wrong tool/output pairing exactly as claimed. |
| m-4 | **CONFIRMED** | MINOR | `CAPABILITIES.md:549-551` says both codecs list only `"snmpv3"`; `cisco_iosxe/codec.py:220-223` declares `{"snmpv3", "ports"}`. |
| m-5 | **CONFIRMED** | MINOR | `CAPABILITIES.md:93-95` "wired across all seven bidirectional codecs" in a 12-codec registry; violates `CONTRIBUTING.md:99` ("Never hard-code counts in prose docs"). |
| m-6 | **DOWNGRADED** | **NIT** | Counts verified: 12 labels (`sanitize.html:196-209`) vs 29 emitted categories (grep `category="…"` in `tools/sanitize.py` → 29 distinct). But the raw-key fallback is deliberate and documented in the code comment itself (`sanitize.html:193-195`), nothing breaks, and the peer already called it cosmetic — that is a nit, not a minor. |
| m-7 | **DOWNGRADED** | **NIT** | Underlying security claims verified TRUE (defusedxml at `opnsense/parse.py:181`, `cisco_iosxe/codec.py:799`, `DefusedXmlException` imported in both); only the line-number anchors in `SECURITY.md:287-288` rotted. Doc-anchor rot with a true claim is a nit. |
| m-8 | **CONFIRMED** | NIT (as filed) | Only `scripts/git-hooks/pre-push` exists; no `.pre-commit-config.yaml` anywhere; `CONTRIBUTING.md:115-116` says "pre-commit hooks". |

## Report 21 — CLI / API contract

| ID | Adjudication | Final severity | Evidence |
|----|--------------|----------------|----------|
| F-1 | **CONFIRMED (independently reproduced)** | **MAJOR** | Route conditional verified (`migration.py:262-266`); pipeline sentinel verified ("None means don't run the translator at all", `migration_pipeline.py:592-599`). My own probe (cisco_iosxe_cli→junos): `port_rename_map={}` → completed, 1 rename, `ge-1/0/1`; vlan-map-only → completed, 0 renames, **`set interfaces GigabitEthernet1/0/1 description "Server-A"`**, zero warnings. UI immunity verified: `rename-apply.js:31` unconditionally sets `body.port_rename_map`. NOT a parked-architecture duplicate (see adjudication section). Bonus corroboration found during verification: the pipeline's own param doc self-contradicts ("Empty / None = fully auto" at `migration_pipeline.py:426-427` vs the `:592-594` None-disengages reality). |
| F-2 | **CONFIRMED** | MINOR | Per-pane routes pass single category (`migration.py:339-343,397-399`); grep for `plan/(vlans\|ports\|…)` hits no file under `netcanon/templates/` — the "UI's pane-switch behaviour" rationale (`:322-326`) is fictional; `:314` names `/plan/snmpv3_users`, shipped route is `/plan/snmpv3` (`:541`). The verbatim-names behaviour is at least stated for these routes (`:390-392`). |
| F-3 | **CONFIRMED** | MINOR | `cli.py:173-174` `write_text` sits outside any try; the sanitize try (`:142-158`) catches only `ValueError`/`ParseError` (input side handled at `:137-140`, exit 2 — asymmetry as claimed). `RenderError` surface real: `tools/sanitize.py:241` calls `codec.render`; HTTP route catches `ParseError` only (`routes/sanitize.py:82-86`) → 500. |
| F-4 | **CONFIRMED (independently reproduced)** | MINOR | My probe: junos config sanitized as `cisco_iosxe_cli` → 0 substitutions, output = `'Building configuration...\n\n! Generated by netcanon translator…'` scaffold. Pipeline-side guard exists (`_input_not_recognized`, `migration_pipeline.py:127-156`, wired at `:340-354`); `sanitize_text` (`tools/sanitize.py:184-245`) has no equivalent — parity gap real. |
| F-5 | **CONFIRMED (probe-verified)** | MINOR | `demo.py:274` string-suffix check; probe: `str(MigrationJobStatus.failed)` = `'MigrationJobStatus.failed'` (works today), `partial` does not match → demo prints success + exits 0 on a partial job. Prospective (no current demo scenario yields partial), correctly filed minor. |
| F-6 | **CONFIRMED** | MINOR | `_migration_helpers.py:173-174` still promises "plain run_plan path unchanged"; else-branch actually calls `run_plan_with_overrides(..., port_rename_map={})` (`migration.py:281-283`). README grep for `run_plan|from netcanon` → zero matches, so `migration_pipeline.py:27` misstates the compat constituency. Additional instance found during verification: `models/migration.py:666-671` (`port_rename_map` field doc) still says unset callers "get the legacy behaviour (no port-name translation at all)" — same stale-else-branch family; fold into the F-6 fix. |
| F-7 | **CONFIRMED** | MINOR | Grep: `force` appears in `migration_pipeline.py` only at the stage-0 class guard (`:246`) and signature threading (`:656,:785`); block-severity → partial unconditionally (`:331-339`). Model docstrings promise force-clears-block (`models/migration.py:128-130,141-143`); the request-model doc (`:653`) is the correct one. |
| F-8 | **CONFIRMED** | MINOR | `MigrationDetectRequest.raw_text` has no `max_length` (`routes/migration.py:131`); `MigrationPlanRequest.raw_text` capped at 10 M chars (`models/migration.py:658-663`) with an explicit abuse-guard comment. Docstring at `:648-650` claims "same contract as /plan". |

---

## Summary of adjustments

- 0 REFUTED, 0 parked-duplicates killed.
- 2 DOWNGRADED: 19 m-6 (deliberate fallback, cosmetic) and 19 m-7 (line-anchor
  rot on true claims) → both NIT.
- 1 severity note: 19 M-3 kept MAJOR on the file's own completeness contract,
  but flagged borderline (all-permissive licenses, one-paragraph fix).
- 2 corroborating micro-instances discovered (attach to existing findings, not
  new IDs): `models/migration.py:666-671` stale port-map field doc (→ 21 F-6);
  `migration_pipeline.py:426-427` "Empty / None = fully auto" self-contradiction
  (→ 21 F-1's doc cleanup).
- Brief correction: 17 F-1 and 21 F-1 are distinct findings on different
  endpoints; both stand independently. The /detect stored-file flow is
  untested, not shown broken.

## Fix-priority view (confirmed majors only)

1. **21 F-1** — one-token route fix (`else {}`), restores the adjudicated
   auto-translate invariant for API callers; add an integration test posting a
   vlan-only override and asserting translated names.
2. **19 M-1** — one-line JS fix (use `adapters.find` like `:1147` or add
   `vendor_display_name` to `adapterEntry`); add an e2e assertion on the
   button's visible text.
3. **17 F-1** — `!= 202` + an OPNsense-outputting collector for that test (the
   `OPNSENSE_FAKE_OUTPUT` constant exists in `tests/conftest.py`).
4. **19 M-2** — rewrite the junos subinterface `LossyPath.reason` + sync
   CAPABILITIES.md (dot1q_vlan surface, junos row, aoscx #244 adjudication);
   fold m-2/m-4/m-5 into the same doc PR.
5. **19 M-3** — add the 7 missing entries to THIRD-PARTY-NOTICES.txt before the
   next MSI-bearing release.

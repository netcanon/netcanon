# Lens 08 — Test quality & coverage honesty

Target: main @ 8598d74 (v0.5.3). Read-only; every finding below was verified by reading the exact code and, where marked, by running a reproduction. Overall verdict: the guard architecture (walker completeness, sanitizer partition, ship-before-wire, vacuous-skip guards, changelog/tag coupling) is unusually strong — most "obvious" attacks are already pre-empted by guard-the-guard tests. The real gaps cluster around the cross-mesh CI guard's *scope* (what it can and cannot see) and two fixture-wide/self-limiting escape hatches. Nothing found suggests a currently-red or trivially-green suite; the findings are about regressions the current suite would NOT catch.

Verified-clean areas (checked, no finding): sanitizer `_SENSITIVE_REDACTED` registry vs actual `sanitize_intent` behaviour (reproduced end-to-end — all "surviving" values were RFC1918/ULA/benchmarking addresses, which the sanitizer *documents* as preserved; public IPs and all secrets redact correctly); walker-completeness guard incl. its synthetic-leaf self-tests; registry capability-honesty guards incl. `_maximal_intent` anti-vacuity check; ship-before-wire two-sided invariant + registry-derived roster (MTX-3 fix intact); real-capture and synthetic harness vacuous-skip guards; changelog↔tag guard; v0.5.2/v0.5.3 fix commits (#293–#297) all carry direct unit tests, including the RouterOS-6 NTP dialect gate (dialect table + real-fixture round-trip) and the four same-vendor version-echo tests (aoscx echo test even re-asserts probe detection post-render); `test_load_and_memory` skip-on-flake is the reviewed TEST-5 remediation, not re-flagged.

---

### F1. Cross-mesh fidelity ratchet silently covers only 41% of the mesh — every pair involving the 4 newest codecs is outside it  [MAJOR / confirmed]

**File:** `tests/integration/test_cross_mesh_ci_guard.py:129` (`test_codec_bug_count_within_baseline`, and the three sibling disposition tests), data at `tests/fixtures/cross_vendor_expectations/` and `tests/fixtures/real/_phase4_runs/latest.json`.

**Evidence (measured):** `tools/run_phase4_reconciliation.py::reconcile_cell` (line ~797) reconciles ONLY fields listed in the pair's expectation YAML; a cell whose `(source, target)` pair has no YAML gets `field_variances = {}` / `fields_total = 0` and contributes nothing to `CODEC_BUG`, pair counts, or severity. The committed corpus has 56 YAMLs = exactly the full 8×7 mesh of the eight *original* codecs. `latest.json` records `cells_without_expectation_yaml` = **723 of 1224 cells (59%)** across **76 distinct pairs** — every pair where `cisco_nxos`, `cisco_iosxr`, `aruba_aoscx`, or `vyos` is source or target (verified: those four names appear in zero YAML filenames).

**Failure scenario:** a renderer regression makes `arista_eos → cisco_nxos` drop every static route (or VLAN, or description) on the committed corpus. The mesh cell still renders and reparses fine, so `test_reparse_of_own_render_never_crashes` and the render allowlist pass; the drift never becomes a disposition because there is no `arista_eos__cisco_nxos.yaml`; CODEC_BUG stays 5; cells_total stays 1224. All six guard tests stay green. The only mesh-wide fidelity floor covering those pairs is `test_cross_codec_matrix.py::test_every_source_ip_appears_in_rendered_output` (one `sample_input` per codec, IPs only) — descriptions/VLAN membership/routes-beyond-IP are unguarded cross-vendor for those 76 pairs. Note also same-vendor cells are excluded from reconciliation *by design* (`intra_vendor_cells_skipped`) — the exact surface v0.5.3/#297 touched relies solely on per-codec unit tests.

**Fix:** two independent steps. (1) Cheap, immediate: extend the CI guard with a coarse drift ratchet over YAML-less cells — pin `sum(cell.summary.fields_drifted)` per uncovered pair (available in the mesh output regardless of YAML) against a committed baseline, exactly like the CODEC_BUG pair ratchet. (2) Longer-term: author expectation YAMLs for the 76 uncovered pairs (or at least the 8 pairs among the 4 new codecs and their highest-traffic partners), which brings them into the real confusion-matrix ratchet.

---

### F2. The guard never pins expectation-YAML coverage — deleting one YAML file silently deletes baseline CODEC_BUGs and stays green  [MEDIUM / confirmed]

**File:** `tests/integration/test_cross_mesh_ci_guard.py:195` (`test_mesh_cell_count_matches_baseline` is the only corpus-shape pin; nothing pins the reconciliation inputs).

**Failure scenario:** delete (or orphan via a codec rename) `tests/fixtures/cross_vendor_expectations/arista_eos__cisco_iosxe_cli.yaml` — the pair holding 2 of the 5 baseline CODEC_BUGs. On the next guard run: live CODEC_BUG = 3 ≤ 5 → pass; live pair set shrinks, and `test_no_new_codec_bug_pairs` only checks `live − base` → pass; `test_no_pair_codec_bug_count_regressed` computes `live.get(pair, 0) > base[pair]` → 0 > 2 is false → pass; `cells_total` is `len(cells_out)` which counts YAML-less cells too → unchanged → pass. The ratchet quietly lost a fifth of its teeth and two known-bad pairs became invisible. The same mechanism applies at finer grain: removing a *field key* from a YAML removes that field from reconciliation everywhere. `expectation_yamls_loaded` (56) and `aggregate.fields_total` (15220) are already present in both live result and committed baseline but are asserted nowhere.

**Fix:** add two one-line assertions to the guard: `result["expectation_yamls_loaded"] >= baseline["expectation_yamls_loaded"]` and `len(result["cells_without_expectation_yaml"]) <= len(baseline["cells_without_expectation_yaml"])` (optionally also `aggregate["fields_total"] >= baseline`, which catches per-field-key shrinkage). All three ratchet in the safe direction and only need a baseline regen when coverage legitimately *grows*.

---

### F3. Render-failure allowlist is (source,target)-pair-scoped, masking ~24 committed cells it was never meant to cover  [MEDIUM / confirmed]

**File:** `tests/integration/test_cross_mesh_ci_guard.py:49` (`_ALLOWED_RENDER_FAILURES`) and `:112` (`test_render_failures_within_allowlist`).

**Evidence:** the allowlist comment scopes the exemption to "the vyos synthetic kitchen-sink", and `CROSS_MESH_RESULTS.md` confirms only `vyos/kitchen_sink.conf → {cisco_iosxe_cli, fortigate_cli}` currently fails (`prefix length 48 out of range`). But the test reduces failures to a `(source_codec, target_codec)` set before subtracting the allowlist, and `run_full_mesh.py::process_cell` gives a `render_error` cell no `field_disposition`, so such cells also vanish from the F1/F2 fidelity counting entirely.

**Failure scenario:** a `cisco_iosxe_cli` render regression starts crashing on *real* vyos captures (there are 12 committed: pc5-round*, wcni-kind-*, metasploit, scottlaird, houdev, vyos_forum). Every one of those new failures lands in the already-allowlisted `("vyos", "cisco_iosxe_cli")` pair; ~24 cells (12 fixtures × 2 allowlisted targets) can go render-dead with every guard test green — the exact "new render crash on the committed corpus" the docstring promises to catch.

**Fix:** key the allowlist by `(source_codec, target_codec, Path(cell["fixture"]).name)` (the cell record already carries `fixture`), i.e. `("vyos", "cisco_iosxe_cli", "kitchen_sink.conf")` and `("vyos", "fortigate_cli", "kitchen_sink.conf")`. Alternatively pin the *count* of failing cells per pair to the baseline.

---

### F4. `_KNOWN_ROUNDTRIP_GAPS` skips the entire MikroTik kitchen-sink round-trip for a single known field, masking all other regressions in that fixture  [MEDIUM / confirmed]

**File:** `tests/unit/migration/test_synthetic_kitchen_sink_round_trips.py:95` (gap entry) and `:247-249` (whole-test `pytest.skip`).

**Evidence (reproduced):** I ran the parse→render→parse comparison the test would run: the only drift today is `bond1`/`bond2` losing their `description` (the documented gap — still real, so the entry isn't stale). But the skip is keyed to the *fixture*, not the *field*: the whole `test_synthetic_round_trips_stable[mikrotik_routeros::kitchen_sink.rsc]` case skips, so the one harness whose purpose is "every declared-supported surface at once" exercises zero round-trip assertions for this codec.

**Failure scenario:** a future mikrotik render regression on any other kitchen-sink surface (VLANs, VRRP, `/ip route`, the freshly-changed `/system ntp client` block from v0.5.3) round-trips wrong; this harness stays skipped-green, the cross-mesh guard doesn't reconcile same-vendor cells (F1 note), and only a per-surface unit test — if one exists for that exact field — can catch it. Also, because it's a `skip` rather than a strict xfail, the entry will silently rot once the bond-description gap is fixed.

**Fix:** replace the fixture-wide skip with a field-targeted exemption: run the comparison, and for gap-listed fixtures assert equality of `_compare(first)`/`_compare(second)` *after* blanking only the documented field (e.g. `description` on `ianaift:ieee8023adLag` interfaces), so every other surface stays asserted. Minimum viable alternative: `pytest.xfail(strict=True)`-style assertion that the ONLY diff is the documented one (my reproduction shows exactly how to compute the diff set).

---

### F5. Complexity-ratchet marker match is dodgeable by three ruff-legal noqa spellings (empirically verified)  [MINOR / confirmed]

**File:** `tests/unit/test_complexity_ratchet.py:36` (`_MARKER = "# noqa:" + " C901"`), `:44-51` (substring count).

**Evidence (reproduced with the repo's ruff):** a complexity-violating function is suppressed by all of `# noqa: E501, C901` (multi-code, C901 not first), `#noqa:C901` (no spaces), and file-level `# ruff: noqa: C901` — none of which contain the literal `"# noqa: C901"` substring, so `_c901_suppression_count()` counts 0 for each while the CI lint gate stays green. `pyproject.toml` `per-file-ignores` is a fourth door (`test_mccabe_gate_is_configured` checks only `select` + `max-complexity`).

**Failure scenario:** a contributor lands a 40-branch function with `# noqa:C901`; the ruff job passes, `test_complexity_debt_does_not_grow` still sees exactly 25 markers and passes — precisely the "dodge the gate by suppressing" regression the module docstring says this ratchet exists to prevent.

**Fix:** count with a regex over noqa directives instead of a literal (e.g. `re.compile(r"#\s*noqa:?[^\n]*\bC901\b")`), additionally assert no `# ruff:\s*noqa` file-level directive exists in the three trees (or that none mentions C901 / is bare), and assert `per-file-ignores` (if present) contains no C90 entry.

---

### F6. Three junos real-fixture tests read fixtures via CWD-relative paths — false-failure when pytest isn't launched from repo root  [MINOR / confirmed]

**File:** `tests/unit/migration/test_juniper_junos.py:975, 986, 1230` (the third added by #294's `test_ksator_ex4550_trunk_ports_unchanged`).

**Failure scenario:** `pathlib.Path("tests/fixtures/real/junos/…").read_text()` resolves against the process CWD. Run `pytest` from anywhere but the repo root (e.g. `cd tests && py -m pytest unit/migration/test_juniper_junos.py`, or an IDE per-file runner with a different working dir) → `FileNotFoundError` masquerading as a test failure. Every sibling fixture-reading test in the suite uses the `Path(__file__).resolve().parents[2] / "fixtures" / …` anchor; these three are the only strays (the #294 one copied the two pre-existing strays at 975/986).

**Fix:** switch all three to the `Path(__file__).resolve().parents[2] / "fixtures" / "real" / "junos" / <name>` pattern used everywhere else in the file's imports’ siblings.

---

### F7. E2E stored-config compat-warning test depends on alphabetical cross-file test order for its data and self-skips otherwise  [MINOR / confirmed]

**File:** `tests/e2e/test_migrate_page.py:476` (`pytest.skip("no stored configs in this session — can't exercise")`).

**Evidence:** the session-scoped configs dir starts EMPTY (`tests/e2e/conftest.py:113-115` — `tmp_path_factory.mktemp("e2e_configs")`); the stored `.cfg` files the test needs are produced as a side effect of `test_backup_form.py` running first (alphabetical collection order). Nothing seeds them for this test and no vacuous-skip guard exists for this skip (unlike the real-capture/synthetic harnesses, which grew exactly such guards after run3's `data-driven-harness-vacuous-skip` finding).

**Failure scenario:** run the file alone (`py -m pytest tests/e2e/test_migrate_page.py` — the documented "run the relevant e2e file" local workflow), or reorder/rename e2e files, or a future `pytest-randomly` adoption: the extension-mismatch warning path silently loses its only coverage while the suite reports green-with-skips.

**Fix:** seed a `.cfg` into the configs dir directly in the test (or a fixture) via the backups API/FakeCollector before switching to filename mode, then drop the skip; alternatively convert the skip to a hard failure when running under CI (env-gated), mirroring the vacuous-skip-guard pattern already used elsewhere.

---

## Ranking rationale

F1 is the headline: it is the difference between what the cross-mesh guard *appears* to certify (mesh-wide fidelity, "CODEC_BUG=5, cells_total=1224" quoted in every recent commit message as the green light) and what it actually reconciles (the 8-codec sub-mesh). F2/F3 are the two concrete ways the already-covered part of that same guard can silently shrink. F4 is the same masking pattern at unit-harness level on the one codec with a fresh renderer change. F5–F7 are integrity/robustness nits, each verified.

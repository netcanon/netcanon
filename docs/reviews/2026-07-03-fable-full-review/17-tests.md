# 17 — Test quality & coverage (lens report)

Reviewer: test-quality lens, Fable fresh-eyes pass, 2026-07-03.
Scope audited: `tests/{unit,integration,e2e,desktop}`, all conftest layers, the four
guard families (cross-mesh CI guard, changelog guard, complexity ratchet,
ship-before-wire), plus coverage of the v0.3–v0.4 arc code (vyos 12th codec, IPv6
static-route sweep #251–#260, version extraction, mikrotik #261/#262, iosxr #263).

**Verdict: HEALTHY suite with one real dead test and a handful of guard-hardening
gaps.** The suite is unusually honest for its size (~200 test files): guards carry
"guard-the-guard" meta-tests, mocks are patched at use-site, concurrency tests use
barriers instead of sleeps, and the known BackgroundTasks timing gotcha is handled
by documented convention. No blocker.

---

## Findings

### F-1 (MAJOR, test defect): `test_detect_stored_config_end_to_end` permanently self-skips — dead test

`tests/integration/test_migration_api.py:1777-1781`:

```python
backup_resp = client.post("/api/v1/backups", json={"devices": devices})
if backup_resp.status_code != 200:
    pytest.skip("FakeCollector doesn't handle OPNsense here")
```

`POST /api/v1/backups` returns **202** by contract
(`netcanon/api/routes/backups.py:143`, and every other integration test asserts
`== 202`, e.g. `tests/integration/test_backups_api.py:448`). `202 != 200` is always
true, so this test has never executed past line 1781 — it silently skips on every
run, in every environment, with a misleading skip reason.

Impact: this is the **only** test of the `/api/v1/migration/detect` +
`source_filename` happy path (load a stored config from the backup store and
auto-detect its codec — route logic at `netcanon/api/routes/migration.py:655-671`).
The 404/422 branches are covered live
(`test_migration_api.py:1712-1731`), the happy path is not. A regression in the
stored-file detect flow would ship green.

Fix note: changing the check to `!= 202` is necessary but not sufficient — the
shared `client` fixture's `FakeCollector` returns Cisco output for *every*
type_key (`tests/integration/conftest.py:35-39`), so the final
`body[0]["codec"] == "opnsense"` assertion needs an OPNsense-outputting collector
(the `OPNSENSE_FAKE_OUTPUT` constant already exists in `tests/conftest.py:85`).
The layered fallback skips at 1783/1791 would otherwise keep masking it.

### F-2 (MINOR, guard blind spot): cross-mesh ratchet doesn't ratchet per-pair counts

`tests/integration/test_cross_mesh_ci_guard.py:129-161`. The guard enforces
(a) total `CODEC_BUG <= baseline` and (b) no NEW `(source, target)` pair. But the
baseline (`tests/fixtures/real/_phase4_runs/latest.json`) already stores per-pair
counts — verified by probe:

```
pairs: arista_eos→cisco_iosxe_cli:2, cisco_iosxe→cisco_iosxe_cli:1,
       juniper_junos→aruba_aoss:1, juniper_junos→cisco_iosxe_cli:1   (total 5)
```

A regression that raises an *existing* pair (e.g. arista→iosxe_cli 2→3) while an
unrelated pair improves (junos→aoss 1→0) keeps the total at ≤5 and the pair set a
subset — **green**, despite a new codec bug on the committed corpus. The data for a
per-pair `<=` check is already in both the live result and the baseline; the guard
just doesn't compare it. Cheap to close (one extra loop in
`test_codec_bug_count_within_baseline` or a sibling test).

Otherwise this guard is genuinely strong: it runs the real mesh in-process (no
mocks), pins reparse-never-crashes as an absolute invariant, and
`test_mesh_cell_count_matches_baseline` (line 164) prevents a silently-shrunk
corpus from weakening the ratchet. cells_total 1224 matches the committed baseline.

### F-3 (MINOR, guard drift): ship-before-wire invariant frozen at 8 codecs; 4 newest not enforced

`tests/unit/migration/test_canonical_vrrp_anycast_schema.py:405-416` — the
two-sided `_WIRED_UP_BY_CODEC` invariant parametrizes over exactly 8 codecs
(`cisco_iosxe_cli, cisco_iosxe, juniper_junos, arista_eos, aruba_aoss,
fortigate_cli, mikrotik_routeros, opnsense`). The fleet is now 12; `cisco_nxos`,
`cisco_iosxr`, `aruba_aoscx`, `vyos` are absent, so for them the guard enforces
neither direction on the six `_NEW_PATHS` (VRRP groups, v4/v6 anycast VGA,
anycast-gateway-mac, static-route/vrf, GAP-7 dot1q-vlan).

Partial mitigation exists — this is why it's minor, not major:
- The *dangerous* direction (declared `unsupported` yet demonstrably round-trips)
  is covered registry-wide for all 12 by
  `tests/unit/migration/test_registry_capability_honesty.py:463-485`
  (`test_roundtrip_emitted_xpath_not_unsupported`), whose kitchen-sink populates
  `dot1q_vlan`, VRRP and anycast fields (`:159-180`).
- Per-codec functional tests cover the wired paths (nxos dot1q
  `test_cisco_nxos.py:510-539`, iosxr `test_cisco_iosxr.py:348-378`).

What is NOT pinned anywhere: the *must-stay-declared-unsupported-until-wired*
direction for the 4 newer codecs. Concrete example: vyos declares
`/interfaces/interface/vrrp-groups/group` unsupported
(`netcanon/migration/codecs/vyos/codec.py:358`), but `test_vyos.py`'s
unsupported-parametrize (`tests/unit/migration/test_vyos.py:837-846`) pins only
`{vlans/vlan/id, static-route/vrf, l2vni-route-target, bgp, nat, firewall}`.
Deleting the vyos VRRP UnsupportedPath would turn the migrate-page banner off for
a surface the codec drops, and no test fails (classify() defaults undeclared paths
to `supported`). Same exposure for aoscx/nxos/iosxr on their un-wired `_NEW_PATHS`
subsets. Fix: extend `_WIRED_UP_BY_CODEC` + the parametrize list to all 12 codecs
(the docstring's own "two-sided invariant" claim currently overstates coverage).

### F-4 (MINOR, circumventable guard): complexity ratchet counts only one noqa spelling; per-file-ignores unchecked

`tests/unit/test_complexity_ratchet.py:36,44-51` counts lines containing the exact
marker `"# noqa: C901"`. Three dodges keep the ratchet green while adding an
over-25 function:

1. **Blanket `# noqa`** (no code list) — suppresses C901, doesn't match the marker.
   Ruff's blanket-noqa rule (`PGH004`) is NOT in the select list
   (`pyproject.toml:214-226`), and RUF100 only flags *unused* directives.
2. **Reordered code list** — `# noqa: E501, C901` is a valid ruff directive that
   doesn't contain the substring; a *new* suppression written this way is invisible
   to the count (the `==` assertion only trips when the counted spelling changes).
3. **`[tool.ruff.lint.per-file-ignores]` addition** — `"netcanon/foo.py" = ["C901"]`
   disables the gate for a whole file; `test_mccabe_gate_is_configured`
   (`test_complexity_ratchet.py:69-75`) checks only `C90 in select` and
   `max-complexity == 25`, never per-file-ignores (`pyproject.toml:279-292`).

Probe verified the codebase is currently clean: exactly 25 `# noqa: C901`, zero
variant/blanket spellings. So this is hardening, not an active hole. Cheapest
fixes: count with a regex tolerant of code-list ordering, assert no blanket noqa
in the three trees, and assert no `C901` appears in per-file-ignores.

### F-5 (MINOR, acknowledged flake risk): tracemalloc ceiling test self-describes as flaky yet still asserts

`tests/integration/test_load_and_memory.py:334-370` —
`test_tracemalloc_peak_under_load` asserts `total_delta < 5_000_000` while its own
docstring says "Best-effort — flaky in CI envs where allocator state varies;
primary guard is the gc.get_objects test above." A test known to be
environment-sensitive that can fail CI red is the classic intermittent-red pattern
(the sibling `test_backupjob_instance_count_stays_bounded` at `:289-332` is the
robust delta-based version and is sufficient). Suggest a generous-multiplier bump,
a `flaky`/rerun marker, or demoting the assert to a warning-log. Not observed
failing — flagged on pattern, not reproduction.

### F-6 (NIT): cross-mesh render-failure allowlist is one-directional

`tests/integration/test_cross_mesh_ci_guard.py:49-52,112-126` —
`_ALLOWED_RENDER_FAILURES` catches *new* failures (`failing - allowed`), but a
*fixed* pair (vyos→cisco_iosxe_cli starts rendering) leaves a silently-stale
allowlist entry that would mask a later re-regression. `assert failing ==
_ALLOWED_RENDER_FAILURES` would ratchet both ways at zero cost.

### F-7 (NIT): e2e cross-file ordering dependency behind a conditional skip

`tests/e2e/test_migrate_page.py:433-434` skips with "no stored configs in this
session" — stored configs only exist if an earlier e2e file (alphabetically,
`test_backup_form.py`) ran a backup against the session-scoped configs dir
(`tests/e2e/conftest.py:112-115`). Running `pytest tests/e2e/test_migrate_page.py`
alone silently skips the filename-compat-warning coverage. Seeding a config
directly in the test (or a fixture) would remove the ordering coupling. Similar
low-grade TOCTOU exists in `_find_free_port` (`tests/e2e/conftest.py:47-51`) —
standard pattern, never observed failing.

### F-8 (INFO): Windows-only branches never run in CI

`tests/integration/test_configs_api.py:182-207` (`os.startfile` open-in-explorer
paths) are `skipif(sys.platform != "win32")` and every CI job is `ubuntu-latest`
(`.github/workflows/ci.yml:65,102,143`). They run only on the maintainer's Windows
host. The skip reasons declare this honestly and the desktop tier covers the
cross-platform variants — recording it so nobody assumes CI exercises them.

---

## What I checked and found SOUND (positive assurance, no action)

- **v0.3–0.4 new code is genuinely tested, not stub-tested.**
  - vyos (12th codec): 56 tests in `test_vyos.py` including set-form front-end
    (`_setform_to_brace`, probe-rejects-junos at `:114`, detects-vyos at `:187`),
    matrix pins (supported/lossy/unsupported `:790-846`), plus inclusion in the
    dynamic cross-mesh smoke matrix (`test_cross_mesh_overrides.py:321-353` lists
    all 12 sources AND targets, with a meta-guard against list shrinkage in
    `test_bidirectionality_invariants.py`), synthetic kitchen-sink fixture present
    (`tests/fixtures/synthetic/vyos/`).
  - mikrotik #261 has a targeted regression test
    (`test_mikrotik_routeros.py:346-358`: name=vlan202 carrying tag 20 renders
    `vlan-id=20`) and #262 both directions
    (`:372-395` quoted-when-spaced, space-free-stays-bare; plus bridge/hostname
    quoting at `:609,:800`).
  - iosxr #263 version banner: `test_cisco_iosxr.py:146-158` parametrizes banner
    variants.
  - Version extraction (`_extract_version`) has direct per-codec tests for all 12
    codecs including the tricky negatives (vyos ignores the config-schema version
    marker `test_vyos.py:295-300`; opnsense asserts it stays empty
    `test_opnsense.py:59-72`; junos kernel-version false-match guard
    `test_juniper_junos_definition.py:207-214` on the probe side).
  - IPv6 static-route sweep: per-codec render+parse tests exist (e.g. nxos
    `test_cisco_nxos.py:264-281` including the `ip route 2001` negative;
    iosxe_cli `:552-584` incl. per-VRF and `::/0`), on top of the generic
    `test_ipv6_wire_through.py` (36 tests).
- **Changelog guard** (`tests/unit/test_changelog.py`) is sound and NOT trivially
  satisfiable in its domain: tag↔header check, unique/descending/dated headers,
  Unreleased anchor. It skips without tags, but the CI test job checks out
  `fetch-depth: 0` (`ci.yml:78`) which fetches tags, so it runs where it matters.
  (Residual: an empty section body passes — out of scope for a header guard.)
- **BackgroundTasks POST-then-read gotcha**: handled by architecture, not luck.
  `tests/integration/conftest.py:8-11` documents that TestClient runs
  BackgroundTasks before returning; every completed-status assertion on backups is
  made on a GET after the POST (`test_backups_api.py:538-541`,
  `test_load_and_memory.py:135-137`); the `/plan` 200+completed assertions
  (`test_migration_api.py:416` etc.) are on a synchronous endpoint.
- **Concurrency tests are deterministic by design**: barrier-based overlap
  (`test_backup_global_concurrency.py:18,70` — "no flaky sleeps"), fake clock for
  the paramiko deadline tests (`test_paramiko_collector.py:191-253`). The one
  sleep-based overlap test (`test_backups_api.py:413-457`) asserts `peak <= 5` hard
  and `peak >= 2` soft — 50ms GIL-releasing sleeps across a 5-thread pool make
  under-overlap implausible; acceptable.
- **No assert-free tests of concern.** AST probe found 15 test functions without
  assert-like statements; all are legitimate does-not-raise contracts
  (boundary-ok constructions, noop-before-create, swallows-exceptions,
  TOFU-reconnect-succeeds) that fail by raising.
- **Over-mocking is bounded.** Desktop unit tests mock all of PySide6/pystray
  (`tests/desktop/conftest.py`) — but the desktop tier also wires the *real*
  embedded ASGI server in `test_backups_*_desktop.py`, and SSH/host-key behavior is
  tested against an in-process real paramiko server
  (`tests/integration/test_ssh_hostkey.py`), not a mock. `FakeCollector` is patched
  at the exact use-site (`netcanon.api.routes.backups.get_collector`).
- **Guard-the-guard discipline**: `test_marker_dict_covers_every_data_bearing_field`
  and `test_maximal_intent_exercises_every_top_level_field`
  (`test_registry_capability_honesty.py:545-574`) prevent the honesty checks from
  going vacuous when the schema grows; `test_requirements_lock.py` checks lock
  consistency without re-resolving (non-flaky by construction).
- **Certainty-header guard** (`test_codec_header_certainty.py:41-42`) skips codecs
  without a `Certainty:` line — technically dodgeable by deleting the header, but
  the limitation is documented as a deliberate "check where the claim is made"
  scope. No action.

## Summary table

| ID  | Severity | One-liner |
|-----|----------|-----------|
| F-1 | MAJOR    | `test_detect_stored_config_end_to_end` always skips (`!= 200` vs 202 API contract) — detect-from-stored-file happy path untested |
| F-2 | MINOR    | Cross-mesh ratchet ignores per-pair CODEC_BUG counts already in the baseline — intra-pair regression can hide behind an unrelated fix |
| F-3 | MINOR    | Ship-before-wire guard roster frozen at 8/12 codecs; un-wired-path-stays-declared direction unpinned for nxos/iosxr/aoscx/vyos |
| F-4 | MINOR    | Complexity ratchet dodgeable via blanket noqa / reordered code list / per-file-ignores (currently clean: 25/25, no variants) |
| F-5 | MINOR    | tracemalloc ceiling test self-documents as flaky yet asserts hard in CI |
| F-6 | NIT      | Render-failure allowlist one-directional (fixed pairs leave stale entries) |
| F-7 | NIT      | e2e filename-warning test depends on cross-file ordering via conditional skip |
| F-8 | INFO     | win32-only `os.startfile` tests never run in CI (declared, desktop tier compensates) |

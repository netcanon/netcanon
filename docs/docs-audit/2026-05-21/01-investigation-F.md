# Cluster F — Tests, fixture provenance + CHANGELOG accuracy

## Summary

Audited 19 .md files under `tests/`, the `[tool.pytest.ini_options]` block in
`pyproject.toml`, the `_DIR_TO_CODEC_NAME` mapping in
`tests/unit/migration/test_real_captures.py`, the `module_variants.py`
allowlist, and `CHANGELOG.md` for the v0.1.1 + v0.1.2 entries.

Overall the test-layer doc surface is in good shape — NOTICE provenance is
exhaustive (45 / 45 disk fixtures have rows), every `_DIR_TO_CODEC_NAME` key
maps to a real codec, every target-profile with `modules:` is allowlisted,
and every CHANGELOG-cited SHA on v0.1.1 + v0.1.2 resolves.  The drift
surface concentrates in two places:

1. **`tests/testid_reference.md`** — 10 stale rows for an inline schedule
   device-list form that was removed from `schedules.html`, plus 1 missing
   row for the `sanitize-safety-note` testid.
2. **`tests/fixtures/real/RESULTS.md`** — coverage-matrix rows missing for 5
   fixtures that have landed since the matrix was last refreshed (one
   cisco_iosxe, one arista_eos, two opnsense CARP HA, and two Junos QFX
   captures missing from the per-codec matrix tables).  The Summary table
   totals + per-codec counts are correspondingly stale.

Tag-date convention drift in CHANGELOG between v0.1.1 (local-time date) and
v0.1.2 (UTC date) is a STYLE finding.

## Findings table

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| F1 | `tests/testid_reference.md:348-357` | WRONG | 10 rows document a stale "inline device list" subsection of the New-Schedule form (`sched-device-list`, `sched-device-entry`, `sched-device-type-select`, `sched-device-host-input`, `sched-device-username-input`, `sched-device-password-input`, `sched-device-enable-input`, `sched-device-port-input`, `sched-remove-device-btn`, `sched-add-device-btn`).  Grep across `netcanon/templates/` returns zero matches for any of these — `schedules.html` jumps from `sched-custom-interval-input` (L48) directly to the two checkbox grids (`sched-type-keys-section` L62 + `sched-devices-section` L79).  The inline-device list was removed at some point but its testid rows were left behind. | Delete the 10 stale rows.  Add a one-line note explaining the form now uses only the checkbox grids documented in the next subsection. |
| F2 | `tests/testid_reference.md` (absent) | MISSING | `data-testid="sanitize-safety-note"` exists at `netcanon/templates/sanitize.html:64` (`<div class="san-banner-info" data-testid="sanitize-safety-note">`) but is not documented anywhere in testid_reference.md.  This is the only static testid in the entire template tree without a doc row. | Add a row under the `## Sanitize page (/sanitize)` § "Form + result testids" table covering the static safety banner. |
| F3 | `tests/fixtures/real/RESULTS.md:36-48, 169-175, 327-331, 529-534, 567-573, 614-623` | INCOMPLETE | 5 fixtures present on disk + cited in NOTICE.md are missing from the RESULTS.md coverage matrix tables (and the Summary table's per-codec counts): (a) `cisco_iosxe/batfish_iosxe_basic_vrrp.txt` (landed in `8adaefd`/`b85c39c`); (b) `arista_eos/batfish_eos_evpn_vlan_based_leaf.txt` (landed in `8adaefd`); (c) `junos/ksator_labmgmt_qfx5110_junos173.set` (landed in `3858dd3`); (d) `junos/ksator_labmgmt_qfx10k2_junos173.set` (landed in `f52489c`); (e) `opnsense/opnsense_docs_carp_ha_master.xml` + (f) `opnsense/opnsense_docs_carp_ha_backup.xml` (both landed in `4686198`).  Summary table at L614-623 also stale: cisco_iosxe_cli reads "12 (6 grammar-test + 6 real)" vs 13 actual; opnsense reads "5" vs 7 actual; arista_eos reads "4 real" vs 5 actual; juniper_junos reads "5" vs 7 actual; TOTAL reads "39" vs 45 actual. | Add a matrix row for each missing fixture under the right codec section, bump per-codec totals + TOTAL in the Summary table, refresh the "OS versions" claim where the new fixture adds an OS major. |
| F4 | `tests/fixtures/real/WANTED.md:21-27` | INCOMPLETE | "Current corpus snapshot" table — counts for cisco_iosxe (12 → actual 13) and arista_eos (4 → actual 5) are stale.  The fixture-count column for junos / mikrotik / fortigate / aruba_aoss / opnsense already reflects current disk state (7 / 4 / 3 / 6 / 7).  Same root cause as F3 — the fixtures-without-matrix-row also lack a WANTED.md count refresh. | Update the table to (cisco_iosxe = 13, arista_eos = 5).  Refresh "OS versions covered" where the missing fixture's OS major adds a new datapoint. |
| F5 | `pyproject.toml:151` + `tests/README.md:127` | MISSING | The `slow` marker is declared in pyproject and documented in tests/README.md but **zero** tests carry `@pytest.mark.slow` or `pytestmark = pytest.mark.slow` anywhere under `tests/`.  Five other markers (`unit` 138 usages, `integration` 21, `e2e` 11, `desktop` 11, `cross_mesh` 23) are wired into real tests. | Either delete the unused declaration from both files, or wire the slow-test gate into the actual slow tests (the cross-mesh harness is the obvious candidate per its docstring). |
| F6 | `CHANGELOG.md:24,173` | STYLE | Tag-date convention drift: `[0.1.2] - 2026-05-21` uses the UTC date (tag was 2026-05-20 23:05:43 -0700 = 2026-05-21 06:05 UTC); `[0.1.1] - 2026-05-19` uses the local-time date (tag was 2026-05-19 23:33:54 -0700 = 2026-05-20 06:33 UTC).  The audit folder convention is "UTC date" per `docs/docs-audit/README.md`.  Picking one and applying both ways is the fix. | Flip 0.1.1 to `2026-05-20` (UTC) OR flip 0.1.2 to `2026-05-20` (local) — pick one and document the convention in the CHANGELOG preamble. |
| F7 | `CHANGELOG.md:201-202` | STYLE | "Cumulative test delta vs `v0.1.0-rc9`: +180 tests (2,499 → 3,341 unit; +31 schema + +149 codec)."  The internal arithmetic doesn't reconcile: 2,499 + 180 ≠ 3,341 (delta is +842, not +180).  Either the baseline (2,499) or the post-count (3,341) refers to a different measurement than "+180".  Archival per AGENTS.md hard rule "Archival records … exempt — they're timestamps" — so this is STYLE not WRONG, but the numbers are internally inconsistent on the same line. | Either drop the parenthetical totals (keep "+180 tests (+31 schema + +149 codec)") or recompute the totals against `git log v0.1.0-rc9..v0.1.1 --stat` so the math reconciles. |

## tests/README.md audit

* Test-suite layout (L7-53) matches actual `tests/` directory structure
  (verified `unit/`, `integration/`, `e2e/`, `desktop/` sub-trees exist
  with the named conftest + helper files).
* Mocking-strategy description (L90-101) matches conftest behaviour —
  `FakeCollector` class, `test_settings` fixture, and `test_app` fixture
  all defined in `tests/conftest.py`, and root-level conftest does NOT
  patch `ConnectHandler` / `paramiko.SSHClient` (the patch site is
  `netcanon.api.routes.backups.get_collector`, per the doc claim).
* Markers table (L120-128) matches `pyproject.toml` declarations
  (6 markers, all listed) — but see F5 for the `slow` marker's zero
  usage.
* Cross-reference table at L131-141 is consistent — `testid_reference.md`,
  `NOTICE.md`, `RESULTS.md`, `PHASE4_RECONCILIATION.md`,
  `user_smoke_findings.md` all exist at the cited paths.

No findings against `tests/README.md` itself (the marker-usage gap is
shared with pyproject.toml — recorded as F5).

## testid_reference.md audit

* **Templates scanned:** 11 .html files + 13 .js files under
  `netcanon/templates/` (all of `_partials/`).
* **Total static `data-testid="X"` literals found:** 358 unique values.
* **Total dynamic prefix testids found** (via JS `setAttribute('data-testid', 'X-' + var)`):
  13 prefixes (`migrate-rename-row-`, `migrate-rename-section-`,
  `migrate-rename-override-`, `migrate-rename-drop-`,
  `migrate-rename-vlan-row-` and overrides/drops,
  `migrate-rename-local-user-row-` and overrides/drops,
  `migrate-rename-snmpv3-user-row-` and overrides/drops,
  plus literal-string `migrate-parse-failure-detect-suggest`, `job-row`,
  `job-progress-device-row`, `job-progress-device-error`,
  `migrate-rename-snmp-community-row`, `migrate-rename-snmp-community-override`,
  `migrate-rename-snmp-community-drop`, `migrate-rename-snmp-table`,
  `migrate-rename-snmpv3-table`, `migrate-rename-local-users-table`,
  `migrate-rename-vlans-table`, `codec-caps-detail-row`,
  `codec-caps-detail-list-` (lossy / unsupported via concat)).
* **Total testid table rows in testid_reference.md:** ~400 row entries.
* **MISSING (in template but not docs):** 1 — `sanitize-safety-note`
  (F2).
* **WRONG (in docs but not template at all):** 10 — the
  `sched-device-*` cluster from the inline-device-list subsection
  (F1).  All 10 grep zero hits across the entire template tree.
* **EXPECTED-MISSING (RESERVED Phase-2 names per the explicit doc
  callout):** 6 — `migrate-transforms-list`, `migrate-add-transform-btn`,
  `migrate-semantic-delta-banner`, `migrate-semantic-delta-item`,
  `migrate-deploy-btn`, `migrate-confirm-deploy-btn`.  These are
  explicitly flagged "aspirational — not yet shipped" in the doc
  itself (L678-683).  Not a finding.
* All other documented testids either appear as static literals in
  templates OR as dynamically-generated string-concat values in JS
  partials.

## fixtures/real/NOTICE.md audit

* **Fixture files scanned** (`find tests/fixtures/real -mindepth 2 -type f`
  with vendor-native extensions, excluding `_cross_mesh_runs/` and
  `_phase4_runs/` JSON artefacts): **45** across 7 vendor directories:
  * `arista_eos/`: 5
  * `aruba_aoss/`: 6
  * `cisco_iosxe/`: 13
  * `fortigate/`: 3
  * `junos/`: 7
  * `mikrotik/`: 4
  * `opnsense/`: 7
* **Rows in NOTICE.md:** 45 fixture rows (one per disk fixture); other
  filename mentions in NOTICE prose refer to upstream source paths
  (e.g. `samples_hash/csr1_…/show_running-config.txt`,
  `src/opnsense/service/tests/config/config.xml`,
  `source/manual/how-tos/resources/Carp_example_master.xml`,
  `blog_resources/fortigate_ztp/…`) rather than disk fixtures.
* **Per-vendor missing-row count:** 0 / 0 / 0 / 0 / 0 / 0 / 0.  Every
  disk fixture has a NOTICE row.
* **Stale rows (NOTICE cites disk file that no longer exists):** 0.
  Every fixture filename cited as the row's primary entry is on disk.
* **Provenance completeness:** every row has all three required
  columns (origin, license, notes).  CC0-1.0 user-contribution rows
  (cat9300, supergate, crs310, fg100e) each document the sanitisation
  steps in the Origin column.  Forum-share rows
  (`hpe_community_*`, `community.cisco.com`) follow the precedent
  recorded in `AGENTS.md` / `NOTICE.md` itself.

No findings against NOTICE.md.

## fixtures/real/RESULTS.md audit

* **Codecs covered in RESULTS:** 8 (cisco_iosxe_cli, cisco_iosxe
  (NETCONF stub), opnsense, mikrotik_routeros, fortigate_cli,
  aruba_aoss, arista_eos, juniper_junos).  This matches the 8
  codec subdirs under `netcanon/migration/codecs/` (excluding
  `_mock/`).  Note: `00-snapshot.md` says "7 codecs" — minor
  internal inconsistency in the audit snapshot, outside this
  cluster's scope but worth flagging.
* **Certification states:** all 7 production codecs marked
  `certified` (cisco_iosxe_cli, opnsense, mikrotik_routeros,
  fortigate_cli, aruba_aoss, arista_eos, juniper_junos); the
  NETCONF stub `cisco_iosxe` correctly marked `best_effort`
  pending Phase-1 wire-up.
* **Coverage-matrix completeness — FINDING F3:**
  * cisco_iosxe_cli matrix (L36-48) lists 11 fixtures + the row
    `batfish_iosxe_basic_vrrp.txt` is **NOT** in the matrix even
    though it's on disk and described in NOTICE.md.
  * arista_eos matrix (L529-534) lists 4 fixtures + the row
    `batfish_eos_evpn_vlan_based_leaf.txt` is **NOT** in the
    matrix even though it's on disk + has a NOTICE entry + is
    cited later in the cert decision prose at L552.
  * juniper_junos matrix (L567-573) lists 5 fixtures + two are
    missing: `ksator_labmgmt_qfx5110_junos173.set` (landed in
    `3858dd3`) and `ksator_labmgmt_qfx10k2_junos173.set` (landed
    in `f52489c`).  Both on disk + in NOTICE.
  * opnsense matrix (L169-175) lists 5 fixtures + two are
    missing: `opnsense_docs_carp_ha_master.xml` and
    `opnsense_docs_carp_ha_backup.xml` (both landed in
    `4686198`).  Both on disk + in NOTICE.
  * **Summary table (L614-623)** correspondingly stale:
    cisco_iosxe_cli "12" / opnsense "5" / arista_eos "4 real" /
    juniper_junos "5" / TOTAL "39".  Actual on-disk counts:
    13 / 7 / 5 / 7 / 45.

## fixtures/real/WANTED.md audit

* "Current corpus snapshot" table (L19-27) verified row-by-row:
  | Codec | WANTED claims | Actual on disk | Verdict |
  |---|---:|---:|---|
  | cisco_iosxe | 12 | 13 | **STALE — F4** |
  | arista_eos | 4 | 5 | **STALE — F4** |
  | aruba_aoss | 6 | 6 | OK |
  | fortigate | 3 | 3 | OK |
  | junos | 7 | 7 | OK |
  | mikrotik | 4 | 4 | OK |
  | opnsense | 7 | 7 | OK |
* "VRRP / HSRP / anycast-gateway" cross-vendor canonical section
  (L141-173): the closure block at L143-149 cites commits `c5da044`
  (Wave A schema) + `e542b49` (Waves B + C 7-codec wire-up) — both
  verified resolvable via `git show`.  The per-vendor wire-up
  table (L154-163) marks 7 codecs `shipped` + 1 codec (NX-OS)
  `queued` (correctly noted as v0.3.0 with the NX-OS codec).
* "Anycast gateway" subsection (L177-191): cites the same
  `e542b49` commit + closure pointer at
  `docs/v0.2.0-planning/02-anycast-gateway/IMPLEMENTED.md`.
* Tier-D opportunities table (L117-126) makes no closure claims
  that need verification (everything is forward-looking).

Only finding: F4 (corpus-snapshot counts off by 1 each for
cisco_iosxe and arista_eos).

## pyproject.toml markers audit

* Declared markers in `[tool.pytest.ini_options]` (L146-153): 6 —
  `unit`, `integration`, `e2e`, `desktop`, `slow`, `cross_mesh`.
* Documented in `tests/README.md` markers table (L121-128): 6 — all
  match.
* Per-marker usage count across `tests/`:

  | Marker | Usages | Status |
  |---|---:|---|
  | `unit` | 138 | OK |
  | `integration` | 21 | OK |
  | `e2e` | 11 | OK |
  | `desktop` | 11 | OK |
  | `slow` | **0** | **F5 — declared but unused** |
  | `cross_mesh` | 23 | OK |

* `--strict-markers` is set in `addopts` (L155), so the unused
  `slow` marker would NOT silently absorb typos — but no test
  references it.  Either delete the row in both files or wire it
  in (the cross-mesh harness's >5-second tests are the obvious
  candidate per the marker's documented intent).

## _DIR_TO_CODEC_NAME mapping audit

`tests/unit/migration/test_real_captures.py:80-88`:

```python
_DIR_TO_CODEC_NAME: dict[str, str] = {
    "cisco_iosxe":  "cisco_iosxe_cli",
    "aruba_aoss":   "aruba_aoss",
    "fortigate":    "fortigate_cli",
    "opnsense":     "opnsense",
    "mikrotik":     "mikrotik_routeros",
    "arista_eos":   "arista_eos",
    "junos":        "juniper_junos",
}
```

* **Vendor dirs on disk (excluding `_*`):** 7 — `arista_eos`,
  `aruba_aoss`, `cisco_iosxe`, `fortigate`, `junos`, `mikrotik`,
  `opnsense`.
* **Mapping keys:** 7 — all 7 directly correspond.
* **Mapping completeness:** 100%.  Every vendor subdir with ≥1
  fixture file has a row.
* **Guard:** `test_every_fixture_dir_has_codec_mapping` exists
  at L400 of the same file, enforcing this invariant in CI.

No findings.

## module_variants.py allowlist audit

`tests/fixtures/module_variants.py:36-45` declares 8 keys:

* `cisco_iosxe/C9300-24P`, `C9300-24U`, `C9300-24UX`, `C9300-48P`,
  `C9300-48U`, `C9300-48UXM`
* `aruba_aoss/3810M-24G-PoEP`, `3810M-48G-PoEP`

Target profiles under `definitions/target_profiles/*.yaml` that
declare a non-empty `modules:` block:

* `aruba_3810m_24g_poep.yaml` → `aruba_aoss/3810M-24G-PoEP` ✓
* `aruba_3810m_48g_poep.yaml` → `aruba_aoss/3810M-48G-PoEP` ✓
* `cisco_c9300_24p.yaml` → `cisco_iosxe/C9300-24P` ✓
* `cisco_c9300_24u.yaml` → `cisco_iosxe/C9300-24U` ✓
* `cisco_c9300_24ux.yaml` → `cisco_iosxe/C9300-24UX` ✓
* `cisco_c9300_48p.yaml` → `cisco_iosxe/C9300-48P` ✓
* `cisco_c9300_48u.yaml` → `cisco_iosxe/C9300-48U` ✓
* `cisco_c9300_48uxm.yaml` → `cisco_iosxe/C9300-48UXM` ✓

All 8 modules-declaring profiles match an allowlist entry; no
allowlist entries point at a deleted profile.

No findings.

## CHANGELOG.md accuracy audit

* **Releases checked:** `[0.1.2]` (2026-05-21) + `[0.1.1]`
  (2026-05-19) + the pre-launch `[0.1.0] — initial release`
  bullet block.  The 0.1.0-rc1..rc9 entries are deeper in the file
  (header at L8455+); per the Phase-1 SHA caveat at L6-14, those
  are out of audit scope.
* **Date verification:**

  | Release | CHANGELOG date | Tag date (local PT) | Tag date (UTC) | Convention |
  |---|---|---|---|---|
  | `[0.1.2]` | 2026-05-21 | 2026-05-20 23:05:43 -0700 | 2026-05-21 06:05 | UTC |
  | `[0.1.1]` | 2026-05-19 | 2026-05-19 23:33:54 -0700 | 2026-05-20 06:33 | local PT |

  Convention drift between 0.1.1 (local) and 0.1.2 (UTC) — recorded as
  F6.

* **SHA resolution** (all 19 SHAs cited in 0.1.1 + 0.1.2 entries):

  | Release | SHAs | Status |
  |---|---|---|
  | 0.1.2 (security/CI) | `4e37a70`, `dbee8f8`, `538f9e1`, `1f68713`, `d193573`, `69f7259`, `619a353`, `5882fbe`, `7c231c4`, `eb3a046`, `6f36ff8`, `ef1b7d3`, `d5d1099`, `051db83` | All 14 resolve ✓ |
  | 0.1.1 (v0.2.0 + bugfixes) | `f52489c`, `b85c39c`, `c5da044`, `e542b49`, `4ce0cb9` | All 5 resolve ✓ |

* **Range coverage:**
  * `git log v0.1.0-rc9..v0.1.1` → 8 commits.  All 5 SHAs cited in
    the 0.1.1 entry are in the range; the un-cited ones are
    `5adee9b` (v0.2.0 + v0.3.0 design artefacts), `8adaefd` (2
    batfish fixtures + VRRP enrichment plan), `3858dd3` (WANTED.md
    + QFX5110 fixture), plus the release commit `5c928e5` itself.
    Coverage looks deliberate (the 3 docs/fixture commits roll up
    under the "Documentation pass" + fixture-corpus discussion in
    the 0.1.1 prose).
  * `git log v0.1.1..v0.1.2` → 20 commits.  14 cited explicitly in
    the 0.1.2 entry; the remaining 6 are: `04002cd` (zizmor pin
    fix referenced inline in `5a3671e`'s context), `5a3671e`
    (zizmor + Trivy enablement, referenced in "new scanner
    enablement"), `f80c557` / `9e21326` / `4686198` / `06a5ba4`
    (the fixture-research arc + WANTED.md + CARP fixtures
    documented as "no fixture corpus changes" in the 0.1.2
    "What didn't change" block).  Tension: the CARP commit
    `4686198` adds 2 OPNsense fixtures to the corpus but 0.1.2's
    "Real-capture fixture corpus — no additions / removals"
    claim (L155) is therefore narrowly wrong — recorded as a
    secondary note under F3's corpus drift.

* **Diff-vs-claim spot-check on the high-leverage 0.1.2 entries:**
  * `4e37a70 fix(security): switch XML parsing to defusedxml`
    — `git show` confirms the change touches
    `netcanon/migration/codecs/opnsense/parse.py`,
    `netcanon/migration/codecs/cisco_iosxe/codec.py`,
    `pyproject.toml` (+`defusedxml>=0.7.1`), matches the entry.
  * `c5da044 feat(canonical): Wave A — VRRP / anycast / per-VRF
    static-route schema (ship-before-wire)` — confirms 31 new
    schema tests + ship-before-wire pattern, matches the entry's
    very detailed L255-340 description.
  * `e542b49 feat(codecs): Wave B + C — VRRP / HSRP / CARP /
    anycast-gateway wired across 7 codecs` — confirms 7-codec
    wire-up with the +149 codec-test claim.

* **Cross-reference resolution** — every linked file path in the
  0.1.1 + 0.1.2 entries (`docs/v0.2.0-planning/`, `docs/vendors/`,
  `docs/CAPABILITIES.md`, `docs/security-triage/`,
  `AGENTS.md`, `SECURITY.md`, `BUG_REPORTING.md`,
  `tests/unit/migration/test_canonical_vrrp_anycast_schema.py`,
  `tests/unit/migration/test_cisco_iosxe_cli.py`) exists on disk.

Only findings against CHANGELOG: F6 (date-format drift), F7
(arithmetic inconsistency on the cumulative-test-delta line),
plus the F3 secondary note about the "no fixture corpus changes"
claim being incorrect because of the CARP additions.

## Cross-cutting observations

1. **The fixture-corpus → doc drift is concentrated post-v0.1.1.**
   All 5 missing-matrix fixtures (cisco_iosxe VRRP, arista_eos
   EVPN-vlan-based, two QFX Junos, two opnsense CARP) landed
   between mid-May and `2026-05-20`.  The matrix in RESULTS.md
   was apparently last refreshed when the v0.1.1 "Documentation
   pass" (`4ce0cb9`) batch closed — that batch updated
   `docs/CAPABILITIES.md`, per-vendor doc pages, and
   v0.2.0-planning closures, but appears not to have touched the
   RESULTS.md matrix tables.  The cert-decision **prose** at the
   end of each codec section does mention the newly-landed
   fixtures (e.g. RESULTS.md:552 cites
   `batfish_eos_evpn_vlan_based_leaf.txt`), confirming the author
   was aware of them — they just didn't propagate into the
   matrix.

2. **AGENTS.md doc-sync row coverage is mostly working.**  The
   "new real-capture fixture under `tests/fixtures/real/<vendor>/`"
   row says "NOTICE.md — provenance + attribution; RESULTS.md —
   coverage matrix row".  NOTICE.md was kept in sync (45 fixtures
   = 45 rows); RESULTS.md matrix was not (40 rows for 45
   fixtures).  The split suggests the discipline holds for
   NOTICE.md (perhaps because there's a regression-test guard)
   but slips on RESULTS.md (where the matrix is human-readable
   and presumably not invariant-tested).

3. **`slow` marker likely came from a copy-paste of pytest
   conventional markers** rather than reflecting an actual
   project policy.  Either the cross-mesh runtime budget
   (declared at `tests/README.md:128` as ">5-second cases should
   be demoted") should be enforced via `@pytest.mark.slow`, OR
   the marker should be retired to avoid the implication that
   such tests exist.

4. **The two BR1 IOS-VRRP credentials in
   `batfish_iosxe_basic_vrrp.txt` are deliberately retained
   verbatim** (NOTICE.md row at L32 explicitly justifies this as
   "RFC 5737-class test material").  Per the hard rule "Never
   include real password hashes" — these are deliberately-cleartext
   lab credentials, not real device secrets, and the NOTICE row
   makes the provenance defensible.  No finding.

5. **The `00-snapshot.md` "7 codecs" claim** (line 54) is at odds
   with the 8 codec subdirs on disk (cisco_iosxe + cisco_iosxe_cli
   are distinct).  Out of scope for Cluster F (snapshot is the
   audit-orchestrator's own scaffolding), but mentioned here so
   the synthesis step can patch it.

## See also

* [`cluster-F-tests-changelog-scope.md`](cluster-F-tests-changelog-scope.md) — this cluster's scope brief
* [`00-snapshot.md`](00-snapshot.md) — broader-run inventory
* [`README.md`](../README.md) — audit process

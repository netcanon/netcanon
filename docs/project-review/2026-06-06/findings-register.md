# Findings register — 2026-06-06 project review

Every finding from both fleets, **deduped** (findings the same defect
arrived at from multiple lenses are merged) and **prioritized**, with
the adversarial-verification verdict where one was run.  Source
investigation(s) cited so you can drill in.  This pass is **read-only**
— "Direction" is a suggestion, not an executed change.

Status legend: **VERIFIED** (adversarial/deterministic pass confirmed) ·
**MULTI** (independently found by ≥2 lenses) · **SINGLE** (one lens).

---

## P1 — fix before next release

| ID | Status | Finding | Anchor(s) | Direction |
|----|--------|---------|-----------|-----------|
| **R-01** | VERIFIED | **Sanitiser leaks VRRP/CARP auth secrets.** `netcanon sanitize` never redacts `vrrp_groups[].authentication` (cleartext `plain:`/`carp-key:`); 3 renderers emit it verbatim; `--dry-run` gives false assurance; SECURITY.md table omits it. | `tools/sanitize.py:215-236` · `migration/canonical/intent.py:563-566` · `aruba_aoss/render.py:673-677` · `opnsense/render.py:470-473` · `cisco_iosxe_cli/render.py:472-476` · `SECURITY.md:305-315` | Add a redaction rule for the field (and the `md5:` key + CF-04 PII fields in the same pass); add SECURITY.md + BUG_REPORTING.md table rows; add a model-coverage guard test. CF-01. |
| **R-02** | VERIFIED | **`tools/` ships in no artifact** — README hero `docker run … python tools/demo.py` + pip demo broken in wheel AND image. | `pyproject.toml:124` · `Dockerfile:36` · `tools/demo.py:14-15` · `README.md:~24` | Decide: ship `tools/` (add to packages + `COPY` in Dockerfile + a CI smoke that runs the demo) **or** reword the README/ docstring to a source-checkout-only instruction. CF-02 / DA-01. |

## P2 — schedule soon

| ID | Status | Finding | Anchor(s) | Direction |
|----|--------|---------|-----------|-----------|
| **R-03** | VERIFIED·MULTI | **Junos `render_intent` raises `TypeError`** where all 7 peers + the `CodecBase.render` contract raise `RenderError`; pipeline catches it via broad `except` (no 500) but mis-buckets the job error; latent trap on the sanitise call site. | `juniper_junos/render.py:105` · `services/migration_pipeline.py:255` · `tools/sanitize.py:159` | One-line: raise `RenderError`; update the `Raises:` docstring; flip any `pytest.raises(TypeError)`. DD-01/CC-01/CF-03. |
| **R-04** | SINGLE | **`POST /api/v1/sanitize` blocks the event loop** — `async def` calling sync parse→redact→render directly; every other pipeline route is threadpooled. | `api/routes/sanitize.py:42` | Wrap the blocking call in `run_in_threadpool` (or make the route sync `def`). CA-01. |
| **R-05** | SINGLE | **Aruba header says `best_effort`, code says `certified`** — the doc-vs-code contradiction the 2026-05-21 audit fixed on MikroTik but missed here. | `aruba_aoss/__init__.py:52` vs `aruba_aoss/codec.py:70` | Fix the header; add a header-vs-`certainty`-ClassVar guard test (closes the class). DE-01. |
| **R-06** | SINGLE | **Operator-facing capability over-claims** — CAPABILITIES.md Tier-1 blanket "renders fully" but `tunnel_type` lossy + `mtu` matrix-silent on FortiGate; `vendors/fortigate.md` says MTU not emitted, but it is. | `docs/CAPABILITIES.md:54-61` · `docs/vendors/fortigate.md:33-36` · `fortigate_cli/codec.py:172-182` · `fortigate_cli/render.py:632-637` | Soften the summary sentences to match the (honest) per-codec tables; add `mtu` to FortiGate `_CAPS`. DA-02/DA-03. |
| **R-07** | SINGLE | **`RESULTS.md` self-contradicts** — Summary says 17 bugs (`:623`), prose says "10 total … five codecs" (`:639`); now 7 codecs / 17 bugs. | `tests/fixtures/real/RESULTS.md:623,639` | Update prose to current vocabulary/counts. DC-01. |
| **R-08** | SINGLE | **Generated cross-mesh artifacts pinned to a stale corpus** (39 fixtures vs 45 now); CROSS_MESH carries no staleness banner. | `tests/fixtures/real/CROSS_MESH_RESULTS.md` · `PHASE4_RECONCILIATION.md` | Re-run `tools/run_full_mesh.py --matrix` + `tools/run_phase4_reconciliation.py`, recommit. DC-02. |
| **R-09** | SINGLE | **ARCHITECTURE.md never inventories `netcanon/security/`**; AGENTS.md:192 falsely claims `_tier3_detection.py` is documented there. | `ARCHITECTURE.md` · `AGENTS.md:192` | Add a `security/` section (Fernet + 3-tier keys); add `_tier3_detection.py` to the cross-cutting list; fix the false self-claim. DF-02/DF-03. |
| **R-10** | SINGLE | **`AGENTS.md:186` hard-codes "SECURITY.md … (line 385)"** — now at `SECURITY.md:492`; sole surviving drifted line-ref, in the row warning about exactly this. | `AGENTS.md:186` → `SECURITY.md:492` | Swap to a `#updating-this-document` anchor (same fix the audit applied to METHODOLOGY). DF-01. |
| **R-11** | SINGLE | **Frozen pipeline signatures enforced only socially** — no `inspect.signature` guard test; a reordered param/default could pass the suite while breaking positional callers. | `services/migration_pipeline.py` | Add a ~20-line freeze-guard test. CD-03. |
| **R-12** | SINGLE | **`api/routes/ui.py` SPLIT** — ~48% is the `/docs` Swagger dark-mode reskin interleaved with 8 page handlers. | `api/routes/ui.py:447-884` | Extract to `api/routes/docs.py` at the line-447 seam; zero behaviour change. CE-01. |

## P3 — worth doing; low risk

| ID | Status | Finding | Anchor(s) | Direction |
|----|--------|---------|-----------|-----------|
| **R-13** | VERIFIED | `is_secondary` wired asymmetrically (Arista VARP flag vs cisco positional) → `cisco_iosxe_cli → arista_eos` loses classic secondary IPs; dead `(?P<secondary>)` group. | `cisco_iosxe_cli/parse.py:127` · `render.py:287` · `arista_eos/parse.py:960` · `render.py:584` | Decide whether classic secondaries should round-trip cross-vendor; if yes, set/read the flag on the IOS path; drop the dead group. CC-02. |
| **R-14** | VERIFIED | `intent.py` VRRP/anycast docstrings say "ship-before-wire/unsupported" though Wave B/C wired them (docstring-only drift — `_CAPS` are honest); OPNsense lists VRRP path in both `supported[]` + `lossy[]`. | `intent.py:96-108,251,828` · `opnsense/codec.py:165,188` | Update the 4 docstrings to "wired v0.2.0 Wave B/C"; de-dup the OPNsense `_CAPS` entry. CB-01. |
| **R-15** | MULTI | Stale "Phase 0 / Phase 2+ / libyang stub" docstrings (the anti-pattern METHODOLOGY names). | `migration/__init__.py:13-15` · `canonical/__init__.py:5-7` · `canonical/loader.py` · `models/migration.py` header | Reword to current reality (or delete the libyang-stub framing if abandoned — a product call). DD-02/CB-02. |
| **R-16** | SINGLE | Sanitiser misses non-secret PII/network fields: `snmp.contact`, VLAN-SVI IPv4, RADIUS/trap/DHCP hosts. | `tools/sanitize.py` | Fold into the R-01 sanitiser pass; decide which are in-scope for redaction. CF-04. |
| **R-17** | VERIFIED | `PortIdentity.original` required by `classify_port_name` contract but populated on zero return paths in arista_eos + juniper_junos (latent). | `arista_eos/port_names.py` · `juniper_junos/port_names.py` | Populate `original`, or relax the contract; add a contract test. CC-03. |
| **R-18** | SINGLE | Backup orchestration lives in `api/routes/backups.py` (not `services/`); `schedules.py` reaches into the route module. | `api/routes/backups.py:194-521` · `api/routes/schedules.py:115` | Extract a `services/backup_runner.py` (symmetry with migration). CA-02. |
| **R-19** | SINGLE | `models/migration.py` co-locates the codec-contract vocabulary (`CapabilityMatrix`/`LossyPath`/`UnsupportedPath`) that `codecs/base.py` imports — contract type lives outside the migration package. | `models/migration.py` · `codecs/base.py:31` | Consider moving the matrix types nearer the codec layer. CA-03 (CE judged the file KEEP overall). |
| **R-20** | SINGLE | `file_store._parse_filename` host decode isn't a clean inverse (hyphenated hostnames decode hyphens→dots); display-only, never mislocates. | `storage/file_store.py` | Make encode/decode bijective, or document the lossy display. CB-03. |
| **R-21** | SINGLE | `cisco_iosxe` NETCONF inherits port-name no-ops → per-port warnings instead of an up-front "no port-rename" banner when used as target. | `cisco_iosxe/codec.py` | Surface a single up-front notice. CD-06. |
| **R-22** | SINGLE | ARCHITECTURE.md per-pane section names 4 rename categories; code + prose have 5 (`snmpv3` omitted). | `ARCHITECTURE.md:233,249-252` | Add the 5th (`snmpv3_user_names` / `/plan/snmpv3`). CD-doc. |
| **R-23** | SINGLE | `migrate.html` has no top-of-file contents map; AGENTS.md:171 cites it as the exemplar, but `definitions.html:4-19` is the real one. | `migrate.html` · `AGENTS.md:171` | Add a top-of-file map (or repoint the AGENTS exemplar to definitions.html). DE-02. |
| **R-24** | SINGLE | Codec `__init__.py` headers non-uniform (ordinal style word→digit; Direction/Certainty lines in only 3/8). | 8 × `codecs/*/__init__.py` | Normalize to one header template. DE-03/04. |
| **R-25** | SINGLE | `tests/README.md` See-also points only down to children, never up to README/AGENTS (breaks one named reciprocity exemplar). | `tests/README.md:129-139` | Add the upward links. DB-01. |
| **R-26** | SINGLE | nxos-codec planning README lists sub-pages as bare backticks, orphaning 3. | `docs/v0.2.0-planning/03-nxos-codec/README.md:518-531` | Convert to `[label](path)` links. DB-02. |
| **R-27** | SINGLE | Four sub-READMEs/leaf docs have zero inbound links. | `tools/README.md` · `netcanon_desktop/README.md` · `netcanon/definitions/README.md` · `tests/fixtures/real/phase4_spawn_tasks.md` | Add inbound links from their parents. DB-03. |
| **R-28** | SINGLE | Dangling `@pytest.mark.slow` snippet survives in a planning doc (marker removed in v0.1.2; `--strict-markers` would fail anything scaffolded from it). | `docs/v0.2.0-planning/03-nxos-codec/04-test-plan.md:478` | Remove or annotate the snippet. DC-04. |
| **R-29** | SINGLE | `migrate.html` (2477) WATCH→SPLIT — already mid-extraction; ~1090 inline `<script>` lines in 6 further-extractable clusters. | `templates/migrate.html` | Optional: continue the partial-extraction already in progress. CE-02. |
| **R-30** | SINGLE | `juniper_junos/render.py` — single ~1130-line `render_intent()` (14 section banners) asymmetric with its dispatched parse sibling. | `juniper_junos/render.py` | Optional: extract per-section render helpers along the banner seams. CE-03. |

## Observations / positives (not defects — recorded)
- Clean acyclic dependency graph; `canonical→codecs` back-edge `TYPE_CHECKING`-quarantined (CD-01/02).
- Codec layer is the strongest area; `_CAPS` two-sided invariant genuinely holds (CC).
- `api/_errors.py` exemplary exception-taxonomy translator (CB).
- Credential hygiene: SecretStr + Fernet-at-rest + 3-tier key resolution (CB/CF).
- All XML input parse sites on defusedxml; v0.1.2 swap stuck (CF).
- 100% module-docstring coverage (179/179); impeccable `NOTICE.md` provenance; 0 dead links (DC/DB).
- No true god-files; large files are earned-size (CE).

## Dedup / correction notes
- **DD-03 ("`is_secondary` already wired in cisco_iosxe_cli")** was
  *refuted* by the adversarial pass — the field is unwired; the real
  defect is the positional/flag asymmetry, captured accurately as
  **R-13 (CC-02)**. DD-03 is retired in favor of R-13.
- **CB-01** downgraded from a potential P2 matrix-honesty violation to
  **R-14 (P3 docstring-only)** after the 8-codec table proved no
  half-wiring.
- The Junos `TypeError` (R-03) is one finding, not three — DD-01,
  CC-01, CF-03 merged.

# 01 — Investigation DF: Contributor / Architecture / Meta Documentation

*Fleet D, reviewer DF. Read-only review of netcanon at `b08040c` (v0.1.2).*

---

## 1. Scope & method

This chapter audits the contributor-directive, architecture, and
meta-documentation surface — the docs a developer (human or agent)
reads to understand *how to work on netcanon* and *how it is built*,
as distinct from the operator-facing surface (DA) and the code
docstrings (DD/DE).

**Files owned and read in full:**

* `AGENTS.md` (367 lines) — contributor directives + doc-sync table + hard rules
* `ARCHITECTURE.md` (881 lines) — four-layer design + invariants
* `docs/METHODOLOGY.md` (615 lines) — portable matrix-honesty discipline
* `docs/RELEASE_PLAN.md` (421 lines) — pre-launch plan + as-shipped phase record
* `CHANGELOG.md` (preamble + version headers + Wave entries; 430 KB total, sampled)
* `CONTRIBUTING.md` (162 lines)
* `CODE_OF_CONDUCT.md` (86 lines)
* `docs/adding-a-canonical-field.md` (360 lines)
* `docs/adding-a-target-profile.md` (347 lines)
* `docs/feature-parity-walkthrough.md` (282 lines)
* `docs/v0.2.0-planning/README.md` + the two `IMPLEMENTED.md` stubs (structural)
* `docs/fixture-research-2015/README.md` (structural)
* `docs/docs-audit/README.md` + `docs/security-triage/README.md` (the two prior dossiers' READMEs)

**Verification method.** Every load-bearing claim was checked against
the live tree at `b08040c`: `git ls-files` for the 112-file source
inventory; `git log --oneline -1 <sha>` to confirm cited commits
resolve; `grep` for the actual location of cross-referenced sections;
direct `Read` of the modules a doc claims to describe (`netcanon/security/*`,
`netcanon/migration/_tier3_detection.py`, `netcanon/migration/vendors/__init__.py`,
`netcanon/services/migration_pipeline.py`, `netcanon/definitions/schema.py`).
The 2026-05-21 docs-audit fix-plan (`docs/docs-audit/2026-05-21/fix-plan.md`)
was read first so closed items are not re-flagged.

**Special-folder discipline.** Per the docs-audit README's special-folder
table, `docs/v0.2.0-planning/`, `docs/fixture-research-2015/`, and the
dated dossier folders are forward-looking / frozen-evidence artifacts;
I audit them for *honest shipped/deferred marking* and *structural
integrity*, not for drift against present state.

---

## 2. Executive summary

The contributor/meta-doc surface is in **good** shape and materially
better than a typical project of this size. The 2026-05-21 anchor
migration in METHODOLOGY.md **landed cleanly** — every section-name
anchor I checked resolves to a real heading in the target file, and
**zero** hard-coded line references survive in METHODOLOGY.md. The
five new doc-sync rows (M1–M5) the audit promised are present and
concrete. All three AGENTS.md Hard Rules I spot-checked against code
(the `type_key` filename-safety validator, the three frozen
pipeline-stage signatures, the CHANGELOG date convention) are honest.
Both prior dossier READMEs are well-structured and mutually
cross-referenced, and both are reachable from AGENTS.md.

The findings that remain are **narrow and specific**:

* **One surviving hard-coded line reference has drifted** — and it is
  in AGENTS.md, not METHODOLOGY.md. AGENTS.md:186 cites SECURITY.md's
  "Updating This Document" trigger list as `(line 385)`; the section
  actually lives at SECURITY.md:492. The reference is off by ~107
  lines and currently points into the *Supply-Chain Integrity* section
  instead. This is the exact citation-drift class the anchor migration
  was meant to eliminate, ironically surviving in the one row that
  warns about SECURITY.md round-trip drift. (`DF-01`)

* **ARCHITECTURE.md's component inventory omits `netcanon/security/`
  entirely.** The `security/` package (Fernet credential encryption +
  key-resolution policy + a shared credential-migration helper consumed
  by both storage loaders) is a real cross-cutting concern, partly the
  subject of the v0.1.2 release, yet appears nowhere in ARCHITECTURE.md
  as a layer or component — and no AGENTS.md doc-sync row points at it.
  (`DF-02`)

* **AGENTS.md:192 makes a factually-incorrect self-claim**: it states
  that "All three current siblings (`_user_secrets.py`, `_naming.py`,
  `_tier3_detection.py`) ARE documented" in ARCHITECTURE.md's
  "Cross-cutting render-time policies" section. ARCHITECTURE.md
  documents only the first two; `_tier3_detection.py` is absent from
  that section. So both the AGENTS.md claim is wrong *and*
  ARCHITECTURE.md has an undocumented cross-cutting sibling. (`DF-03`)

The remaining items are low-severity: a cross-doc date-convention
inconsistency for v0.1.1 (CHANGELOG vs RELEASE_PLAN), a Layer-1
description in ARCHITECTURE.md that omits the migration-side
`vendors/` package, and a single mildly-misleading "shipped in v0.2.0"
phrasing in the planning README.

**Verdict on currency:** AGENTS.md is current and internally
consistent except for the one drifted SECURITY.md line-ref (DF-01) and
the false self-claim (DF-03). ARCHITECTURE.md is current for the
migration layer it scopes itself to, but its component inventory has a
genuine `security/`-shaped hole (DF-02) and a missing cross-cutting
sibling (DF-03).

---

## 3. Findings (severity-ordered)

Severity scale: **WRONG** (claim contradicts reality) · **MISSING**
(real surface, no doc) · **INCOMPLETE** · **STYLE/LOW**. Each grounds
in `file:line`.

### DF-01 — AGENTS.md hard-coded SECURITY.md line reference has drifted — **WRONG (medium)**

* **File:line:** `AGENTS.md:186`
* **Claim:** the packaging/distribution doc-sync row instructs
  contributors to "verify every item in its own § 'Updating This
  Document' trigger list **(line 385)**".
* **Evidence:** SECURITY.md line 385 is the bullet "**Non-root
  container runtime.** The image runs as `app` (uid=1000); …" inside
  the **Supply-Chain Integrity** section. The actual "## Updating This
  Document" heading is at **SECURITY.md:492** (verified via
  `grep -n "Updating This Document" SECURITY.md`; file is 526 lines).
  The reference is wrong by ~107 lines and lands the reader in the
  wrong section.
* **Why it matters:** this is the single contributor-facing instruction
  that is *most* about keeping a document in sync after a release, and
  it itself drifted — precisely the failure mode METHODOLOGY.md's
  anchor-migration was meant to retire. A contributor following the
  pointer reads the non-root-runtime bullet, not the trigger checklist.
* **Suggested direction:** replace `(line 385)` with a section-name
  anchor — `[SECURITY.md § Updating This Document](SECURITY.md#updating-this-document)` —
  matching the exact pattern the 2026-05-21 audit applied to
  METHODOLOGY.md (fix-plan Commit 7, items M2/M3). This is the same
  remediation, one file over.

### DF-02 — ARCHITECTURE.md component inventory omits `netcanon/security/` — **MISSING (medium)**

* **File:line:** `ARCHITECTURE.md` (whole document; the natural homes
  would be the "Cross-cutting render-time policies" section at :375 or
  a new components paragraph). The only occurrence of "security" in the
  doc is the v0.1.2 *roadmap bullet* at `ARCHITECTURE.md:837`.
* **Claim (by omission):** ARCHITECTURE.md presents itself as "the
  conceptual map" (`ARCHITECTURE.md:3`) and inventories the migration
  layers, the backup layer, cross-cutting policies, target profiles,
  templates, and test architecture.
* **Evidence:** `git ls-files` shows a first-class package
  `netcanon/security/` with three modules:
  `__init__.py` ("Security utilities for Netcanon."),
  `credentials.py` (Fernet symmetric encryption with a documented
  three-tier key-resolution policy: `NETCANON_FERNET_KEY` env var →
  OS keyring → `$NETCANON_DATA_DIR/.fernet_key` file fallback —
  `security/credentials.py:1-39`), and
  `migration.py` (`migrate_credential_fields`, a shared
  legacy-plaintext-credential re-encryption helper that both
  `FileDeviceProfileStore` and `FileScheduleStore` call on first load —
  `security/migration.py:1-35`). This is exactly the kind of
  vendor-agnostic, multiple-consumer cross-cutting concern that the
  "Cross-cutting render-time policies" section enumerates for the
  migration side (`_user_secrets.py`, `_naming.py`).
* **Why it matters:** credential-at-rest encryption is operator-trust
  load-bearing and is partly what v0.1.2 hardening is about. A
  contributor reading ARCHITECTURE.md to understand "where does
  credential encryption live / what's the key-resolution contract" has
  no entry point. There is also **no AGENTS.md doc-sync row** that
  fires when `netcanon/security/*.py` changes — so a change to the
  Fernet key-resolution order would update no doc by rule.
* **Suggested direction:** add a short "Credential encryption at rest"
  paragraph to ARCHITECTURE.md (pointer to
  `netcanon/security/credentials.py`'s key-resolution docstring as the
  source of truth, to respect the no-hard-coded-detail discipline), and
  add an AGENTS.md doc-sync row mapping
  `netcanon/security/credentials.py` key-resolution changes → SECURITY.md
  (which already documents the env-var) + ARCHITECTURE.md.

### DF-03 — AGENTS.md:192 falsely claims `_tier3_detection.py` is documented in ARCHITECTURE.md — **WRONG (medium)**

* **File:line:** `AGENTS.md:192` (the migration-package-sibling
  doc-sync row); the contradicted target is `ARCHITECTURE.md:375-421`.
* **Claim:** "All three current siblings (`_user_secrets.py`,
  `_naming.py`, `_tier3_detection.py`) ARE documented but the row that
  demands it has been absent — close that gap." The row's whole
  rationale is that the three siblings are already documented and only
  the *enforcing row* was missing.
* **Evidence:** ARCHITECTURE.md's "Cross-cutting render-time policies"
  section (`:375-421`) documents exactly two siblings —
  **Hash-portability policy** (`_user_secrets.py`, `:381`) and
  **Naming-value sanitisation** (`_naming.py`, `:390`) — plus two
  *non-sibling* policies (switchport↔VLAN projection in
  `canonical/transforms.py`, and the `kind=mgmt` cascade).
  `grep -n "_tier3_detection|dropped_tier3|Tier-3 stanza" ARCHITECTURE.md`
  returns **no matches**. Yet `_tier3_detection.py` is a genuine
  cross-cutting policy: its module docstring
  (`netcanon/migration/_tier3_detection.py:1-30`) states that *every*
  codec calls a per-vendor `detect_tier3_sections_<vendor>(raw)` before
  returning parsed intent, populating
  `CanonicalIntent.dropped_tier3_sections` for the migrate-page
  "Detected in source but not translated" banner. That is more
  cross-cutting than `_naming.py` (which only two target vendors call).
* **Why it matters:** two defects in one row. (a) The AGENTS.md
  statement is a literal falsehood a future contributor will trust:
  they'll assume ARCHITECTURE.md covers `_tier3_detection.py` and not
  add it. (b) ARCHITECTURE.md is missing a load-bearing cross-cutting
  policy — the *only* doc home for the silent-drop-honesty mechanism
  that METHODOLOGY.md (`docs/METHODOLOGY.md:427-435`, the
  "silent drops" anti-pattern) holds up as a flagship discipline.
* **Suggested direction:** add a fourth bullet to ARCHITECTURE.md's
  "Cross-cutting render-time policies" — "**Tier-3 section detection**
  (`netcanon/migration/_tier3_detection.py`). Every codec calls a
  per-vendor detector before returning intent, populating
  `CanonicalIntent.dropped_tier3_sections`…" — and then the AGENTS.md:192
  claim becomes true. (Fix both halves in the same commit.)

### DF-04 — v0.1.1 release date disagrees between CHANGELOG and RELEASE_PLAN — **LOW (cross-doc consistency)**

* **File:line:** `CHANGELOG.md:182` (`## [0.1.1] - 2026-05-19`) vs
  `docs/RELEASE_PLAN.md:133` (`v0.1.1 (2026-05-20)`).
* **Claim:** both name the v0.1.1 ship date.
* **Evidence:** CHANGELOG's preamble (`CHANGELOG.md:20-23`) documents a
  date convention — "entries below use the maintainer's local authoring
  date (UTC-7 / Pacific). Git tag commits may land on the following UTC
  day." So `2026-05-19` (CHANGELOG) is the *local* date and `2026-05-20`
  (RELEASE_PLAN) is plausibly the *UTC tag* date — the planning README
  provenance (`docs/v0.2.0-planning/README.md:325`) corroborates
  authoring on `2026-05-19`. The two docs are describing the same
  release under two different date conventions, and only CHANGELOG
  states which it uses. (v0.1.2 is consistent at `2026-05-21` in both
  CHANGELOG:29 and RELEASE_PLAN:140.)
* **Why it matters:** minor, but a reader cross-referencing the two
  docs sees two different dates for one tag with no on-page
  reconciliation in RELEASE_PLAN.
* **Suggested direction:** either align RELEASE_PLAN to the CHANGELOG
  local-date convention (→ `v0.1.1 (2026-05-19)`), or add a one-line
  note in RELEASE_PLAN that its dates are UTC-tag dates. Not worth a
  dedicated commit; fold into the next RELEASE_PLAN touch.

### DF-05 — ARCHITECTURE.md Layer 1 omits the migration-side `vendors/` package — **LOW (incomplete)**

* **File:line:** `ARCHITECTURE.md:75-108` (Layer 1 — Vendor Definition).
* **Claim:** "**Where:** `definitions/*.yaml`" is given as the home of
  vendor definitions for the migration layer.
* **Evidence:** the migration layer's *vendor identity* registry is
  actually loaded by `netcanon/migration/vendors/__init__.py`
  (`load_vendors()` scans `netcanon/migration/vendors/*.yaml` and
  validates against `VendorInfo` — `vendors/__init__.py:33-82`,
  surfacing at `GET /api/v1/migration/adapters`). The `definitions/*.yaml`
  tree ARCHITECTURE.md points at is the *backup-side* device-class
  definitions. ARCHITECTURE.md itself later (correctly) separates these
  two concerns in the target-profiles section (`:526-534`), but Layer 1
  conflates them by pointing only at `definitions/`.
* **Why it matters:** small — a contributor adding a migration vendor
  would look in `definitions/` per Layer 1 and miss
  `netcanon/migration/vendors/`. The `vendors/__init__.py` docstring is
  excellent and self-documents the 30-second add path, so the harm is
  bounded.
* **Suggested direction:** add a one-line pointer in Layer 1 — "Vendor
  *identities* for the migration picker live in
  `netcanon/migration/vendors/*.yaml` (loaded by `load_vendors`);
  backup-side device-class definitions live in `definitions/*.yaml`."

### DF-06 — Planning README "shipped in v0.2.0" conflates wave-series name with release tag — **LOW (style/honesty nuance)**

* **File:line:** `docs/v0.2.0-planning/README.md:9` ("**Status: T1 + T2
  shipped in v0.2.0; T3 + T4 queued for v0.3.0+.**").
* **Claim:** the VRRP/anycast work "shipped in v0.2.0".
* **Evidence:** the work shipped under the **v0.1.1** *tag* (CHANGELOG
  `[0.1.1] - 2026-05-19`, whose entries are headed "v0.2.0 Wave A + B +
  C", `CHANGELOG.md:242`). The project uses "v0.2.0" as a *wave-series
  name* and v0.1.1 as the *release tag* that shipped it — a convention
  consistently applied in ARCHITECTURE.md:829
  ("**v0.1.1 (v0.2.0 Wave A+B+C)**") and RELEASE_PLAN.md:133. The
  planning README is the one place that says "shipped in v0.2.0"
  without the v0.1.1-tag anchor, which reads as "shipped in a tag that
  doesn't exist yet."
* **Note:** ARCHITECTURE.md:829's parenthetical and RELEASE_PLAN's
  framing are the *honest* version of this; the planning README is
  mildly out of step. Not WRONG (the IMPLEMENTED.md stubs immediately
  below cite the real commits `c5da044`/`e542b49`), but a first-time
  reader could be confused.
* **Suggested direction:** reword to "shipped under the **v0.1.1** tag
  (the v0.2.0 Wave A+B+C series)" to match the sibling docs.

---

## 4. AGENTS.md / METHODOLOGY.md citation-drift sweep

This was the prompt's headline question: *after the 2026-05-21
anchor-migration, are there remaining hard-coded line-range references
that have since drifted?*

**METHODOLOGY.md: clean.** A targeted sweep
(`grep -nE 'line \d|lines? \d|:\d{2,3}\b|#L\d'`) over METHODOLOGY.md
returns **no matches**. Every cross-file reference in METHODOLOGY.md
now uses a section-name anchor, and I verified the anchors resolve:

| METHODOLOGY.md anchor | Target heading | Resolves? |
|---|---|---|
| `AGENTS.md#documentation-sync-checklist` (×4: lines 76, 124, 501) | `## Documentation Sync Checklist` (AGENTS.md:148) | ✓ |
| `AGENTS.md#cross-reference-discipline` (lines 302, 461) | `## Cross-reference discipline` (AGENTS.md:202) | ✓ |
| `AGENTS.md#hard-rules-never-break` (lines 323, 386, 423, 467) | `## Hard Rules (Never Break)` (AGENTS.md:243) | ✓ |
| `CAPABILITIES.md#notification-mechanisms-operators-see` (lines 152, 166, 305) | `## Notification mechanisms operators see` (CAPABILITIES.md:146) | ✓ |
| `CAPABILITIES.md#translation-tiers` (lines 231, 497) | `## Translation tiers` (CAPABILITIES.md:46) | ✓ |
| `CAPABILITIES.md#see-also` (lines 305, 463) | `## See also` (CAPABILITIES.md:628) | ✓ |
| `ARCHITECTURE.md#see-also` (lines 306, 464) | `## See also` (ARCHITECTURE.md:867) | ✓ |

The migration the fix-plan promised (Commit 7, items M2/M3 — "Replace
hard-coded AGENTS.md / codec line ranges with section-name anchors" at
the ten enumerated METHODOLOGY line numbers) is **fully landed and
correct**. This is a genuine *negative* result: the prompt's hypothesis
that METHODOLOGY drift survived is not borne out.

**AGENTS.md: one drifted line reference (DF-01).** A sweep of AGENTS.md
surfaces exactly one hard-coded line reference: `(line 385)` at
AGENTS.md:186, pointing into SECURITY.md. As detailed in DF-01, it has
drifted (actual location SECURITY.md:492). The five other doc-sync rows
that reference other files (rows touching `tests/testid_reference.md`,
`pyproject.toml`, `tests/README.md`, etc.) all reference *files and
section names*, not line numbers, so they cannot drift this way.

**All other DF-owned docs: clean.** A combined sweep over
ARCHITECTURE.md, RELEASE_PLAN.md, adding-a-canonical-field.md,
adding-a-target-profile.md, feature-parity-walkthrough.md,
CONTRIBUTING.md, and CODE_OF_CONDUCT.md for surviving line-range
references (filtering IPs, version strings, port numbers, and CIDR
masks) returns nothing. The worked-example docs cite *commits* and
*file paths*, not line ranges — and the commits resolve (see §6).

**Bottom line:** the anchor migration succeeded; AGENTS.md:186 is the
sole survivor and the only citation-drift finding in the entire DF
surface.

---

## 5. ARCHITECTURE.md currency check vs. the actual tree

I cross-walked ARCHITECTURE.md against `git ls-files` for the
112-file `netcanon/` tree.

**Codecs — current.** ARCHITECTURE.md correctly describes the
multiple-codecs-per-vendor model (`:130-136`), naming `cisco_iosxe`
(NETCONF) and `cisco_iosxe_cli` as distinct adapters sharing
`vendor_id`. The tree confirms 8 real codec packages + `_mock`. The
roadmap's "across all 7 bidirectional codecs" framing (`:832`) is
accurate: `grep` for `vrrp_groups`/`CanonicalVRRPGroup` in render paths
returns exactly the 7 non-NETCONF render.py files, with the
`cisco_iosxe` NETCONF stub declaring the paths (consistent with its
deferred status). The codec sub-modules the snapshot lists
(`aruba_aoss/_svi_absorption.py`, `fortigate_cli/vlan_heuristics.py`,
per-codec `port_names.py`) exist; ARCHITECTURE.md doesn't enumerate
them, which is *correct* per doc-sync row #14 (prefer pointers over
exhaustive inventories) — it defers to `codecs/README.md`.

**Migration siblings — incomplete (DF-03).** ARCHITECTURE.md's
"Cross-cutting render-time policies" documents `_user_secrets.py` and
`_naming.py` but not `_tier3_detection.py`. All three exist in the tree
(`netcanon/migration/_*.py`). See DF-03.

**`security/` package — missing (DF-02).** Not inventoried anywhere.
See DF-02.

**Top-level app modules — out of scope by design.** `main.py`,
`cli.py`, `config.py`, `logging_config.py`, `models/`, `storage/` are
not inventoried in ARCHITECTURE.md. This is **acceptable**:
ARCHITECTURE.md states at `:40` "The rest of this document is about the
migration layer," and defers the backup layer to
`collectors/README.md` (`:42`) and HTTP routes to
`api/routes/README.md` (`:872`). The doc is honestly scoped as a
migration-centric conceptual map, not a file census. I do not flag
these as gaps — but note that `cli.py` (which exposes `netcanon
sanitize`, a v0.1.2-relevant surface) and `storage/` (which *consumes*
the `security/migration.py` helper) have no architectural entry point.
The `security/` hole (DF-02) is the one that crosses from
"deliberately-deferred" into "genuinely missing" because it's
cross-cutting and undocumented *and* has no sub-README of its own.

**Template / partials inventory — current.** The partials list
(`ARCHITECTURE.md:599-647`) is an *exhaustive enumeration* (12 partials
including `kbd-cheatsheet.js` at :612, which the 2026-05-21 audit added
per fix-plan A2). This technically sits in tension with doc-sync row #14's
"prefer one-line pointers unless the enumeration carries load-bearing
explanation" — but each bullet *does* carry load-bearing explanation
(e.g. the FOUC-prevention note on theme-toggle.js, the scalar-vs-list
note on snmp-rename-table.js), and the section header explicitly says
"contents of `_partials/` is the source of truth" (`:600`). So it's a
defensible application of the rule's escape clause, not a violation. No
finding — but it is the kind of inventory that will need a touch on the
next partial added.

**Per-pane overrides + variance-class taxonomy — current.** The
"Current state" paragraph (`ARCHITECTURE.md:329-344`) correctly
describes only `OpnSenseCodec` and `CiscoIOSXECodec` declaring
`frozenset({"snmpv3"})` — this matches the 2026-05-21 audit's A1 fix
(fix-plan Commit 2) and is confirmed by the feature-parity walkthrough
(`docs/feature-parity-walkthrough.md:55-60`). The 8-class variance
taxonomy (`:740-783`) matches METHODOLOGY.md's enumeration
(`docs/METHODOLOGY.md:272-288`) one-for-one. No drift.

---

## 6. Planning-folder shipped/deferred honesty check

The `docs/v0.2.0-planning/` tree is **honestly marked**.

* **Subfolder index table** (`docs/v0.2.0-planning/README.md:35-40`):
  tasks 1 (VRRP) + 2 (anycast) marked "**Shipped (e542b49)**" with
  links to `IMPLEMENTED.md` stubs; tasks 3 (NX-OS) + 4 (IOS-XR) marked
  "Design complete (implementation queued for v0.3.0[+])". The tree
  confirms only subfolders 01 and 02 carry an `IMPLEMENTED.md` stub
  (`find … -name IMPLEMENTED.md` → exactly those two).
* **IMPLEMENTED.md stubs resolve to real commits.** `01-vrrp-canonical/IMPLEMENTED.md`
  cites Wave A `c5da044` and Wave B `e542b49`; both resolve via
  `git log --oneline -1` with the exact subjects quoted. The stub's
  "What was deferred to a future PR" section
  (`01-vrrp-canonical/IMPLEMENTED.md:76-95`) honestly enumerates the
  carried-forward gaps (NETCONF stub VRRP, modern multi-line AF form
  lossy, IOS-XE IPv6 anycast unsupported, Junos per-VRF static lossy,
  NX-OS/IOS-XR HSRP/VRRP gated on those codecs) — and these match the
  snapshot's "known-honest gaps" list (`00-snapshot.md:125-131`) and
  RELEASE_PLAN's "Open / queued for v0.3.0+" block
  (`docs/RELEASE_PLAN.md:217-238`). Three docs agree on the deferral
  set; that is the matrix-honesty discipline working.
* **`docs/fixture-research-2015/` naming is intentional, not a typo.**
  The "2015" refers to the "2015 January through today (10-year
  window)" version-research scope stated in its own preamble
  (`fixture-research-2015/README.md:1-7, :34`) and is referenced under
  that name from the snapshot, RELEASE_PLAN:153, ARCHITECTURE.md:846,
  and the AGENTS.md "See also". Consistent. The folder honestly labels
  itself "Read-only research … Nothing in this folder modifies
  production code" (`:17-21`).

**One nuance (DF-06):** the planning README's headline "shipped in
v0.2.0" elides the v0.1.1 *tag*. Low severity; the IMPLEMENTED.md
stubs immediately resolve the ambiguity by citing real commits.

**Prior dossiers cross-referenced from AGENTS.md — yes.** The
security-triage and docs-audit processes both appear as doc-sync rows
(`AGENTS.md:188` and `:189` respectively) *and* in the AGENTS.md "See
also" (`:364-365`). The two dossier READMEs cross-reference each other
reciprocally (`docs/security-triage/README.md:145-148` ↔
`docs/docs-audit/README.md:147-153`). The *current* (third) dossier,
`docs/project-review/2026-06-06/`, is **not** yet referenced from
AGENTS.md — but that is expected and correct, since this review is
in-flight and uncommitted (snapshot notes the dossier is uncommitted).
No finding; flagging for the orchestrator's awareness that an AGENTS.md
"See also" + doc-sync row for the project-review process will be the
natural close-out when this cycle lands, mirroring how docs-audit was
added in its own Commit 17.

---

## 7. What's GOOD

A deliberately specific list — these are the things working *well*, so
the orchestrator can weigh them against the findings:

* **The anchor migration is a clean success.** METHODOLOGY.md has zero
  surviving line-refs and every anchor resolves (§4 table). This is the
  hardest doc-hygiene discipline to land and it landed.
* **Hard Rules are code-true.** `type_key_filename_safe` exists as a
  validator (`netcanon/definitions/schema.py:226`); all three frozen
  pipeline-stage functions exist with their exact names
  (`run_plan`:126, `run_plan_with_overrides`:295,
  `run_plan_with_rename`:670 in `migration_pipeline.py`); the CHANGELOG
  date-convention rule has a documented preamble
  (`CHANGELOG.md:20-23`). I found no Hard Rule contradicted by code.
* **CHANGELOG follows its own newly-stated conventions.** The date
  convention is documented (the fix-plan F6 item landed); the
  pre-launch-SHA caveat is honestly stated (`CHANGELOG.md:6-14`); the
  `[Unreleased]` block is empty (proper promotion to `[0.1.2]`).
* **Worked-example docs are commit-grounded and honest about their own
  gaps.** feature-parity-walkthrough.md cites `8c6e493` (resolves,
  exact subject "Add SNMPv3 USM cross-mesh (P2C6)…") and openly flags
  the E2E gap (`:151-157`) and desktop-test gap (`:158-164`) rather
  than over-claiming coverage — and even self-corrects a wrong pointer
  in the prompt that authored it (`:148-150`). That is the
  matrix-honesty discipline applied to a doc about itself.
* **The five promised doc-sync rows (M1–M5) are present and concrete:**
  sanitiser categories (`AGENTS.md:190`), canonical transforms (`:191`),
  migration `_*.py` siblings (`:192`), `unsupported_rename_categories`
  (`:193`), and fixture-research catalogue (`:194`). The "ship-before-wire"
  and per-pane-category patterns are documented in both ARCHITECTURE.md
  and the worked examples.
* **CONTRIBUTING.md + CODE_OF_CONDUCT.md are complete and current.**
  CONTRIBUTING.md points at AGENTS.md as canonical (`:19, :29, :90`),
  has runnable test commands, and the three-path structure is honest.
  CODE_OF_CONDUCT.md:40 has a real contact (the
  `security/advisories/new` URL + SECURITY.md fallback) — the
  `[INSERT CONTACT METHOD]` placeholder the fix-plan C15 flagged is
  resolved.
* **Both dossier READMEs are reusable process docs**, not just
  evidence dumps — stable cluster taxonomies, severity scales, and
  isolation policies that a future reviewer (this one included) can
  follow cold.

---

## 8. Coverage table

| Doc | Read | Verified-against-code | Findings |
|---|---|---|---|
| `AGENTS.md` | full | Hard Rules ×3, doc-sync rows, line-385 ref | DF-01, DF-03 |
| `ARCHITECTURE.md` | full | tree inventory, codecs, siblings, security/, partials | DF-02, DF-03, DF-05 |
| `docs/METHODOLOGY.md` | full | all anchors resolved | none (clean) |
| `docs/RELEASE_PLAN.md` | full | v0.1.1/v0.1.2 dates, deferral set | DF-04 |
| `CHANGELOG.md` | preamble + headers + Wave entries (sampled) | date convention, commit SHAs, Unreleased | none (consistent) |
| `CONTRIBUTING.md` | full | AGENTS.md pointers, test cmds | none |
| `CODE_OF_CONDUCT.md` | full | contact (C15 closed) | none |
| `docs/adding-a-canonical-field.md` | full | MTU pattern, intent.py shape | none |
| `docs/adding-a-target-profile.md` | full | target_profiles.py, module_variants | none |
| `docs/feature-parity-walkthrough.md` | full | commit 8c6e493, snmpv3 modules, gaps | none |
| `docs/v0.2.0-planning/` (README + 2 stubs) | structural | commits c5da044/e542b49, deferral set | DF-06 |
| `docs/fixture-research-2015/README.md` | structural | naming, cross-refs | none |
| `docs/docs-audit/README.md` | full | reciprocity, AGENTS.md linkage | none |
| `docs/security-triage/README.md` | full | reciprocity, AGENTS.md linkage | none |

---

## 9. Open questions

1. **Does the `security/` package warrant its own sub-README** (like
   `collectors/README.md`) rather than just an ARCHITECTURE.md
   paragraph? The credential key-resolution policy is subtle enough
   (three tiers, container-vs-desktop tradeoffs) that a dedicated README
   plus a doc-sync row may be the more durable fix for DF-02. Deferring
   the architecture call to the orchestrator / Fleet C.

2. **Is the partials inventory (ARCHITECTURE.md:599-647) the right
   long-term shape**, or should it convert to a pointer per doc-sync
   row #14 the next time a partial lands? It currently passes the rule's
   "load-bearing explanation" escape clause, but it is the largest
   surviving exhaustive enumeration in the doc. (Cross-check with DE,
   who owns header/contents-map conventions.)

3. **Should RELEASE_PLAN.md adopt the CHANGELOG local-date convention**
   wholesale (DF-04), or is its UTC-tag-date framing intentional? A
   one-line convention note would settle it either way.

4. **Will the project-review process get an AGENTS.md doc-sync row +
   "See also" entry** on close-out (mirroring docs-audit's Commit 17)?
   Flagged in §6 as the expected pattern; confirming it is the
   orchestrator's call.

5. **`netcanon/migration/vendors/` vs `definitions/`** (DF-05): is the
   Layer-1 conflation worth a fix, or is the excellent
   `vendors/__init__.py` docstring sufficient discoverability? Low
   stakes; noting for completeness.

---

*End of DF investigation. All findings ground in `file:line` at
`b08040c`; no claim in this chapter is marked UNVERIFIED — each was
checked against the live tree.*

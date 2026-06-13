# 01 — Investigation DB: Scaffolding / `.md` Interlinking-Graph Integrity

**Reviewer lens:** DB (cross-reference graph across all hand-authored `.md`)
**Commit:** `b08040c` (v0.1.2)
**Mode:** READ-ONLY. No tracked file mutated. Only this output file written.
**Date:** 2026-06-06

---

## 1. Scope & method

### What this lens owns

The cross-reference **graph** across every hand-authored Markdown file in
the repo: top-level (`README`, `AGENTS`, `ARCHITECTURE`, `SECURITY`,
`BUG_REPORTING`, `CHANGELOG`, `CONTRIBUTING`, `CODE_OF_CONDUCT`), the
`docs/*.md` surface, `docs/<subdir>/README.md`, `tests/*.md`,
`netcanon/**/README.md`, and the three dated dossier trees
(security-triage / docs-audit / project-review). The large
`docs/vendor-references/<pair>/` cache (~680 files) is in scope **only** at
the `_INDEX.md` + "is it linked / is the index complete" level, not per
cell.

### Corpus enumerated

`git ls-files "*.md"` minus the per-cell vendor-reference body files
yields the hand-authored surface. Including the 56 vendor-reference
`_INDEX.md` files and the cache's own `README.md`, the link-checker
operated over **190 tracked Markdown files**. The uncommitted
`docs/project-review/2026-06-06/` dossier (this review) is present on disk
but untracked; I excluded it from the committed-corpus orphan/reciprocity
math and only used it to avoid filename collisions with sibling reviewers
(DA/DD/DE/DF outputs already exist in the docs-review folder).

### Method

This lens is mechanically verifiable, so I built tooling rather than
eyeballing:

1. **Heading → anchor extraction** per file, reproducing GitHub's slug
   algorithm exactly: strip HTML tags, lowercase, drop every character
   that is not alphanumeric / space / hyphen / underscore (so periods,
   colons, slashes, parens, backticks, **and em/en-dashes** are removed),
   replace spaces with hyphens, and apply `-1`/`-2` dedupe suffixes for
   repeated headings. Code fences are skipped so fenced `#` lines do not
   masquerade as headings. I sanity-checked the slugger against known
   headings (e.g. `## Theming (dark mode)` → `theming-dark-mode`;
   `### Tier D — entirely…` → `tier-d--entirely-…` with the **doubled
   hyphen** the dropped em-dash produces).
2. **Link extraction** via a regex that tolerates backticks inside link
   *text* (`[`docs/X.md` § See also](X.md#see-also)` is common here) and
   strips optional `"title"` suffixes. Links sitting inside an inline code
   span (odd backtick count before the `[`) are treated as syntax examples
   and skipped — this matters because the docs-audit evidence files quote
   `[label](path)` and `[text](path)` as illustrative templates.
3. **Path resolution** relative to each file's directory, checked against
   the tracked-file set (and tracked directories, for directory-style
   links like `docs/vendors/`).
4. **Anchor resolution** of the fragment against the target file's
   computed anchor set.
5. **Adjacency + reciprocity + orphan** computation over the resulting
   directed graph, with directory-links resolving to the directory's
   `README.md` for reachability purposes.
6. I also separately grepped for `<a href>` HTML links and reference-style
   `[x]: url` definitions to confirm the `[…](…)` regex captures the
   complete navigational link set (it does — see §6).

I cross-read `AGENTS.md` §§ "Documentation Sync Checklist" and
"Cross-reference discipline" (lines 148-219), `docs/METHODOLOGY.md` §
"Cross-reference discipline" (lines 297-306), and the prior
`docs/docs-audit/2026-05-21/fix-plan.md` so as not to re-flag closed items.

### Interpretive stance on reciprocity

`AGENTS.md:204-219` states each doc should carry a "See also" to its **two
or three closest peers**, and that when you add a *new sibling* you add the
reciprocal link in the existing peers. It names three exemplar sets
(`README → ARCHITECTURE/AGENTS/tests`; `ARCHITECTURE →
definitions/codecs/canonical/RESULTS`; `tests → testid/RESULTS/NOTICE`).
Critically, the project's actual peer-sets are **asymmetric by design**:
reference/leaf docs point *up* to orientation docs, and orientation docs
point *across* to topical docs. A naive "every See-also link must be
mutual" rule produces 73 "violations," nearly all of which are intentional
hub-and-spoke. I therefore treat **strict reciprocity as binding only on
the three named exemplar sets** and report the broader asymmetry as a
single low-severity observation rather than 73 findings. This is the same
stance the 2026-05-21 audit's cluster A took.

---

## 2. Executive summary

**The interlinking graph is in excellent health.** Across 190 Markdown
files and **1,161 internal links** (716 of them `.md → .md` navigational
edges), there are **zero broken relative paths and zero broken anchor
fragments**. All **42 anchor-bearing links resolve**, including **23 that
deliberately target em-dash headings** and correctly use the doubled-hyphen
slug (`…#tier-1--auto-translatable-cross-vendor-stable`) — the exact trap
this lens exists to catch. The prior docs-audit's em-dash fix and
reciprocity pass clearly held, and nothing has regressed since.

What remains is a small set of **navigational-reachability gaps** (orphans
and one missing reciprocal), not correctness bugs:

* Four sub-READMEs / leaf docs have **no inbound Markdown link** at all:
  `tools/README.md`, `netcanon_desktop/README.md`,
  `netcanon/definitions/README.md`, and
  `tests/fixtures/real/phase4_spawn_tasks.md`.
* The `tests/README.md` **does not reciprocate** the inbound links from the
  two named exemplar peers (`README.md`, `AGENTS.md`) — the one genuine
  exemplar-set reciprocity gap.
* The `docs/v0.2.0-planning/03-nxos-codec/README.md` document-map uses
  **bare-backtick filenames instead of Markdown links**, leaving three of
  its sub-pages orphaned — the only planning folder of four that breaks the
  clickable-index convention its siblings follow.
* `docs/vendor-references/README.md` is **not an index** of the 56 per-pair
  caches it heads (the YAML files are the designed entry point), and two of
  the six `docs/docs-audit/2026-05-21/cluster-*.md` scope files are reachable
  only by bare name.

No finding rises above **MEDIUM**. The two MEDIUMs are the exemplar-set
reciprocity gap (DB-01) and the nxos planning-index convention break
(DB-02). Everything else is LOW or informational.

Finding counts: **0 HIGH, 2 MEDIUM, 6 LOW, 2 informational** (10 total).
Dead links: **0**. One-way links of consequence: **1** (the tests/README
exemplar reciprocal); broader by-design hub-spoke asymmetry is catalogued
but not counted as defects.

---

## 3. Findings (severity-ordered)

### DB-01 — `tests/README.md` does not reciprocate its two named exemplar peers — MEDIUM

**Where:** `tests/README.md:129-139` ("## See also" table).
**Rule violated:** `AGENTS.md:214` names `README.md → ARCHITECTURE.md,
AGENTS.md, tests/README.md` as a canonical reciprocity set, and
`AGENTS.md:217-218` requires reciprocal links between closest peers.

**Claim:** `README.md:316` links to `tests/README.md`, and `AGENTS.md:366`
links to `tests/README.md`, but `tests/README.md` links back to **neither**
`README.md` nor `AGENTS.md`. Its See-also table points only "downward/
sideways" to `testid_reference.md`, `fixtures/real/{NOTICE,RESULTS,
PHASE4_RECONCILIATION,user_smoke_findings}.md`,
`../netcanon/migration/codecs/README.md`, and `../definitions/README.md`.

**Evidence:**
```
tests/README.md outbound .md links (grep):
133 ](testid_reference.md)
134 ](fixtures/real/NOTICE.md)
135 ](fixtures/real/RESULTS.md)
136 ](fixtures/real/PHASE4_RECONCILIATION.md)
137 ](fixtures/real/user_smoke_findings.md)
138 ](../netcanon/migration/codecs/README.md)
139 ](../definitions/README.md)
```
`grep -nE "\]\((\.\./)?(README|AGENTS)\.md\)" tests/README.md` → no match.
The prior audit's finding M2 (`docs/docs-audit/2026-05-21/01-investigation-A.md:41`)
added the `## See also` heading to `tests/README.md` but populated it with
tests/README's *own* peers, never reciprocating the inbound exemplar links.

**Why it matters:** A contributor landing on `tests/README.md` cannot get
back to the project root or contributor directives in one hop. Of the three
exemplar sets, the other two are fully bidirectional (see §4); this is the
single hole in the named contract.

**Suggested direction:** Add `README.md` and `AGENTS.md` rows to the
`tests/README.md` See-also table (the table form already exists, so this is
two rows). Severity is MEDIUM only because it is the *named* exemplar set;
the navigation still works via every other doc.

---

### DB-02 — nxos-codec planning README uses bare-backtick filenames, orphaning 3 sub-pages — MEDIUM

**Where:** `docs/v0.2.0-planning/03-nxos-codec/README.md:518-531`
("## 10. References + further reading").
**Rule context:** `AGENTS.md:171` (contents-map / file-listing rows) and the
"closest peers / one hop" discipline; the three sibling planning folders all
use clickable Markdown links for their document maps.

**Claim:** The nxos planning README lists its six sub-pages as **bare
backticks**, not links:
```
520 * `01-grammar-survey.md` — full per-stanza grammar inventory …
522 * `02-codec-architecture.md` — module layout, class shape …
524 * `03-canonical-mapping.md` — xpath → NX-OS command table …
526 * `04-test-plan.md` — unit + real-capture + cross-vendor …
528 * `05-fixture-targets.md` — batfish + community corpus …
530 * `06-capabilities-matrix.md` — proposed `CapabilityMatrix` row list …
```
Because these are not links, three sub-pages that are not referenced as
links anywhere else become **orphans** with zero inbound Markdown edges:
`02-codec-architecture.md`, `03-canonical-mapping.md`, `04-test-plan.md`.
(`01`, `05`, `06` happen to be linked elsewhere in the README body, e.g.
`:104`, `:35`, so they escape orphanhood by accident.)

**Contrast — the sibling convention:** the other three planning folders use
real links in their document maps:
* `docs/v0.2.0-planning/01-vrrp-canonical/README.md:214-228` ("## Document
  map") — all six entries `[`NN-….md`](NN-….md)`.
* `docs/v0.2.0-planning/04-iosxr-codec/README.md:262-266` — a Document-map
  *table* with all entries linked.
* `docs/v0.2.0-planning/02-anycast-gateway/README.md` — sub-pages linked
  inline throughout (`:46`, `:64`, `:101`, …).

**Why it matters:** The planning tree is forward-looking design the project
explicitly wants discoverable cold (it survives compaction). nxos is the one
folder where a reader cannot click into half its design pages. It is also a
consistency wart against three siblings that get it right.

**Suggested direction:** Convert the §10 list to the
`[`02-codec-architecture.md`](02-codec-architecture.md)` form (matching
`01-vrrp-canonical`'s "## Document map"). Renaming the heading to "Document
map" for cross-folder consistency is optional polish.

---

### DB-03 — Orphan sub-READMEs with no inbound Markdown link — LOW

**Where (each verified with a precise `]( … target.md )` grep, excluding the
uncommitted project-review dossier):**
* `tools/README.md` — no link resolves to it; the directory `tools/` is also
  not linked as a directory. Referenced only as bare `` `tools/README.md` ``
  text or via `tools/<file>.py` links elsewhere.
* `netcanon_desktop/README.md` — no inbound Markdown link (committed corpus).
* `netcanon/definitions/README.md` — no inbound Markdown link. **Note the
  trap:** the *top-level* `definitions/README.md` is well-linked (ARCHITECTURE,
  CAPABILITIES, tests/README, etc.); the *package-internal*
  `netcanon/definitions/README.md` is a different file and is the orphan.
* `tests/fixtures/real/phase4_spawn_tasks.md` — no inbound Markdown link.

**Evidence:** `grep -rnoE "\]\(([^)]*tools/README\.md[^)]*)\)" --include=*.md`
(and the equivalents for the other three) return empty once the uncommitted
`docs/project-review/` files are excluded.

**Why it matters:** These are genuine dead-ends for a browsing contributor.
`tools/README.md` is the most surprising: `AGENTS.md` and `ARCHITECTURE.md`
both link individual `tools/*.py` files (e.g. `tools/demo.py`,
`tools/run_phase4_reconciliation.py`) but never the directory's own README,
so the overview the README provides is unreachable by clicking.

**Caveat / not over-claiming:** several of these *are* mentioned by bare
backtick (discoverable by a reader who types the path), and
`phase4_spawn_tasks.md` is a frozen Phase-4 work-breakdown artifact whose
audience may be expected to arrive via the directory listing. This is why
the finding is LOW, not MEDIUM.

**Suggested direction:** Give each a single inbound link from its natural
parent — `tools/README.md` from `ARCHITECTURE.md`'s tooling discussion or
the root `README.md` layout section; `netcanon_desktop/README.md` from the
root README's desktop mention; `netcanon/definitions/README.md` from
`ARCHITECTURE.md` Layer-1 or the top-level `definitions/README.md`;
`phase4_spawn_tasks.md` from `tests/README.md` or `RESULTS.md`.

---

### DB-04 — `docs/vendor-references/README.md` is not an index of the 56 per-pair caches — LOW

**Where:** `docs/vendor-references/README.md` (whole file; See-also at
`:86-96`).

**Claim:** The cache README documents *layout* and *conventions* but
contains **no list/index linking the 56 per-pair `_INDEX.md` files**. Its
See-also points outward only — to
`tests/fixtures/cross_vendor_expectations/README.md`,
`tests/fixtures/real/CROSS_MESH_RESULTS.md`, and
`tools/run_phase4_reconciliation.py`. Consequently **none of the 56
`_INDEX.md` files has an inbound Markdown link from any hub doc**; they are
reachable only via the per-pair YAML `meta.references` blocks (path
references in code, not Markdown links) or by guessing the directory name.

**Evidence:** `grep -rln "_INDEX.md" --include=*.md` over the committed
corpus (excluding project-review) matches only two docs-audit investigation
files that cite a handful of indexes as *examples* — not a systematic index.
The orphan pass flagged 40 of the 56 `_INDEX.md` as having no inbound link;
the other 16 are non-orphan only because docs-audit cluster-A/B prose happens
to cite them illustratively.

**Mitigating facts (why LOW, and an explicit GOOD):** The cache is
*designed* to be entered from the YAML expectation files
(`README.md:64-71` "Citation convention"), not browsed. And the indexes
themselves are **complete and accurate** — see DB-09. So this is a
discoverability gap, not a correctness one.

**Suggested direction:** Optionally add a generated "## Pairs" table to
`docs/vendor-references/README.md` linking each `<pair>/_INDEX.md`
(56 rows; a 1-line glob can keep it honest). Lower-effort alternative: a
single sentence stating the YAML files are the entry point and the per-pair
dirs are addressed by name, so a reader stops looking for an index.

---

### DB-05 — Two of six docs-audit cluster scope files reachable only by bare name — LOW

**Where:** `docs/docs-audit/2026-05-21/cluster-B-user-docs-scope.md` and
`…/cluster-E-platform-docstrings-scope.md`.

**Claim:** Of the six `cluster-*.md` scope files in the 2026-05-21 dossier,
**A/C/D/F each receive 4 Markdown-link references** but **B and E receive
zero Markdown links** — they appear only as bare-backtick names (e.g.
`docs/docs-audit/README.md:41,:44` inside the folder-layout code fence, and
`…/00-snapshot.md:80,:83` in a table cell). The orphan pass confirms B and E
have no inbound Markdown edge.

**Evidence:** `grep -rnoE "\]\(([^)]*cluster-[BE]-…\.md…)\)"` over
`docs/docs-audit` → empty. `grep -rnE "cluster-[BE]-…\.md"` → only bare
mentions.

**Why it matters / why LOW:** The docs-audit tree is a **frozen evidence
trail** (the audit's own README §"Treatment of special folders" says don't
flag its content as stale). Self-navigation asymmetry inside a frozen
dossier is cosmetic. Still, four of six being clickable and two not is an
inconsistency a future audit-of-the-audit would notice.

**Suggested direction:** None required (frozen). If touched, make the
`00-snapshot.md` table cells (`:80`, `:83`) link the B/E scope files for
parity with how A/C/D/F are cited elsewhere.

---

### DB-06 — `docs/v0.2.0-planning/README.md` has no "See also" footer — LOW

**Where:** `docs/v0.2.0-planning/README.md` (no `## See also` / `## Related`
heading present).

**Claim:** `AGENTS.md:204-205` says *every* doc in `docs/` should open or
close with a See-also line. The v0.2.0-planning hub README — the parent
index for the whole planning tree — has none. (Two other no-footer files
exist: `docs/archive/README.md` and `tests/fixtures/real/aruba_aoss/README.md`,
both defensible as a retired-content index and a leaf fixture note
respectively; the planning hub is the one worth fixing.)

**Evidence:** `for f in …; grep -qiE "see also|related doc"` reports
`NO-SEEALSO: docs/v0.2.0-planning/README.md`.

**Mitigating fact:** the audit flags `docs/v0.2.0-planning/` as a "special"
forward-looking folder; the footer rule is softer here.

**Suggested direction:** Add a short See-also footer pointing at the four
sub-plan READMEs (or at `ARCHITECTURE.md` Evolution roadmap + the four
sub-folders), matching how the sub-plans themselves carry footers.

---

### DB-07 — `docs/archive/README.md` is orphaned from Markdown navigation — LOW

**Where:** `docs/archive/README.md`.

**Claim:** The archive README has no inbound Markdown link and the
`docs/archive/` directory is not linked as a directory either. The only
references are bare-backtick (`docs/docs-audit/README.md:85` says
"`docs/archive/` … verify only that cross-refs into it from current docs
still resolve").

**Evidence:** `grep -rnoE "\]\(([^)]*docs/archive/?…)\)"` → empty.

**Why it matters / why LOW:** The audit treats archive as retired-citation
material; the requirement on it is only that inbound cross-refs *resolve*
(they do — the corpus has zero broken paths). Whether the archive index
itself is reachable is intentionally not guaranteed. Recorded for
completeness.

**Suggested direction:** None required. If desired, a one-line link from
`CHANGELOG.md` (which already discusses archived material) or the docs-audit
README would close it.

---

### DB-08 — Selective sub-README convention leaves several `netcanon/` layers without a README — LOW (by design; flagged for the brief's explicit question)

**Where:** `netcanon/api/`, `netcanon/migration/`, `netcanon/models/`,
`netcanon/security/`, `netcanon/services/`, `netcanon/storage/`,
`netcanon/tools/`, and top-level `scripts/` have **no `README.md`**, whereas
`netcanon/collectors/`, `netcanon/definitions/`, `netcanon/api/routes/`,
`netcanon/migration/canonical/`, and `netcanon/migration/codecs/` do.

**Claim:** The brief asks "does every directory that should have a README
have one?" The answer is that the project uses a **selective** convention:
cross-cutting layers with authorship guidance get a README; thin
data/model/service layers are documented centrally in `ARCHITECTURE.md`
instead. This is internally coherent, not a defect.

**Evidence:** `for d in …; test -f "$d/README.md"` enumeration (see §7).
`ARCHITECTURE.md` documents the storage/models/services/security layers in
its four-layer narrative; `AGENTS.md` § "Code Organisation" (`:223-231`)
defers layout to `tests/README.md` + root `README.md`.

**Two soft snags worth a sentence (not defects):**
1. `scripts/` contains exactly one tracked file
   (`scripts/render_aruba_central_template.py`) with no orientation and no
   inbound link — a reader has no signpost for what `scripts/` is for vs
   `tools/`.
2. There are now **two** "tools-ish" READMEs in play conceptually: the
   top-level `tools/README.md` (orphaned, DB-03) documents `tools/*.py`,
   while `netcanon/tools/` (the in-package `sanitize.py` etc.) has none. No
   bleed exists, but the naming is a mild trip hazard.

**Suggested direction:** No action needed for the layer READMEs. Optionally
a one-line `scripts/README.md` (or a mention in `tools/README.md`)
clarifying the `scripts/` vs `tools/` split.

---

### DB-09 — Vendor-reference indexes are complete and the mesh is whole — INFORMATIONAL (positive)

**Where:** `docs/vendor-references/<pair>/_INDEX.md` × 56.

**Claim & evidence:** Scripted check across all 56 pair directories: every
`.md` topic file on disk is enumerated in its `_INDEX.md` (allowing both
backtick-filename and Markdown-link forms; underscores and hyphens). Result:
**56/56 complete, 0 incomplete, 0 phantom entries.** The cache is a
**complete 8×7 = 56 ordered-pair full mesh** (8 codecs:
`arista_eos, aruba_aoss, cisco_iosxe, cisco_iosxe_cli, fortigate_cli,
juniper_junos, mikrotik_routeros, opnsense`) — `expected − present = ∅` and
`present − expected = ∅`. (An early run reported false "incomplete" pairs
because my first regex excluded underscore filenames such as
`dhcp_render_gap.md`; corrected.)

**Note:** the topic listings inside each `_INDEX.md` use **bare-backtick
filenames in a table**, not Markdown links (per-cell, so outside strict
scope) — consistent across pairs, so not a drift finding.

---

### DB-10 — Filename-style inconsistency between vendor-reference pairs — INFORMATIONAL

**Where:** vendor-reference topic filenames.

**Claim:** Some pair caches name topics with **hyphens**
(`arista_eos_to_juniper_junos/`: `vtep-source-interface.md`,
`vlan-name-constraints.md`) while others use **underscores**
(`opnsense_to_cisco_iosxe/`: `dhcp_render_gap.md`, `firewall_unsupported.md`;
`fortigate_cli_to_mikrotik_routeros/`: `local_users.md`, `static_routes.md`).
This is cosmetic and per-cell, so out of strict scope, but it is the reason
naive index-completeness tooling misfires and is worth a one-line note for a
future cache-hygiene pass. No links break from it (indexes match disk).

---

## 4. Link-graph adjacency summary (core hand-authored docs)

Directed edges among the **core hub set** (top-level docs + the
operator/contributor `docs/*.md` + tests hubs + the two dated-dossier
READMEs). `→` means "links to" (anywhere in the file, fenced examples
excluded). Edges to non-core docs omitted for readability.

```
README.md            → AGENTS, ARCHITECTURE, BUG_REPORTING, CHANGELOG,
                        CODE_OF_CONDUCT, SECURITY, CAPABILITIES,
                        METHODOLOGY, TROUBLESHOOTING, glossary, tests/README
AGENTS.md            → README, ARCHITECTURE, BUG_REPORTING, CHANGELOG,
                        SECURITY, CAPABILITIES, METHODOLOGY, TROUBLESHOOTING,
                        security-triage/README, docs-audit/README, tests/README
ARCHITECTURE.md      → AGENTS, SECURITY, glossary, tests/testid_reference
                        (+ definitions/README, codecs/README, canonical/README,
                         api/routes/README, RESULTS.md — its named peer set)
SECURITY.md          → AGENTS, README, BUG_REPORTING, CAPABILITIES
                        (+ security-triage tree)
BUG_REPORTING.md     → SECURITY, CONTRIBUTING, CAPABILITIES, TROUBLESHOOTING
CHANGELOG.md         → README, ARCHITECTURE, BUG_REPORTING, CAPABILITIES,
                        TROUBLESHOOTING (+ many topical)
CONTRIBUTING.md      → README, AGENTS, ARCHITECTURE, SECURITY, BUG_REPORTING,
                        CAPABILITIES, METHODOLOGY, tests/README
CODE_OF_CONDUCT.md   → SECURITY
docs/METHODOLOGY.md  → AGENTS, ARCHITECTURE, CHANGELOG, CAPABILITIES
docs/CAPABILITIES.md → README, AGENTS, ARCHITECTURE, SECURITY, CHANGELOG,
                        glossary (+ RESULTS, PHASE4_RECONCILIATION, planning)
docs/TROUBLESHOOTING → BUG_REPORTING, CAPABILITIES
docs/glossary.md     → README, ARCHITECTURE, AGENTS, CAPABILITIES
tests/README.md      → tests/testid_reference (+ NOTICE, RESULTS,
                        PHASE4_RECONCILIATION, user_smoke, codecs/README,
                        definitions/README)   ← see DB-01: no up-link
tests/testid_ref.md  → README(=tests/README), AGENTS, ARCHITECTURE
security-triage/RDME → AGENTS, BUG_REPORTING, SECURITY, docs-audit/
docs-audit/README    → AGENTS, ARCHITECTURE, security-triage/
```

**Bidirectional core pairs (20):**

```
README ↔ AGENTS            README ↔ ARCHITECTURE      README ↔ SECURITY
README ↔ CAPABILITIES      README ↔ CHANGELOG         README ↔ glossary
AGENTS ↔ ARCHITECTURE      AGENTS ↔ SECURITY          AGENTS ↔ CAPABILITIES
AGENTS ↔ METHODOLOGY       AGENTS ↔ security-triage/  AGENTS ↔ docs-audit/
ARCHITECTURE ↔ glossary    ARCHITECTURE ↔ testid_reference
SECURITY ↔ CAPABILITIES    BUG_REPORTING ↔ SECURITY   BUG_REPORTING ↔ CONTRIBUTING
BUG_REPORTING ↔ TROUBLESHOOTING   CHANGELOG ↔ CAPABILITIES
CAPABILITIES ↔ glossary    tests/README ↔ testid_reference
```

**Reading of the topology:** `README`, `AGENTS`, `CAPABILITIES`, and
`ARCHITECTURE` are the four high-degree hubs; nearly every doc reaches a hub
in one hop and the hubs reach each other bidirectionally. The two
exemplar-set reciprocity contracts that *are* satisfied:
* `ARCHITECTURE ↔ {definitions, codecs, canonical}/README` — verified both
  directions (each sub-README links `ARCHITECTURE.md` back: grep counts
  1/1/2 respectively; ARCHITECTURE See-also `:869-872` links all three).
* `tests/README ↔ testid_reference` — `tests/README.md:133` ↔
  `testid_reference.md:758`.
The one **not** satisfied is the `README/AGENTS → tests/README` leg (DB-01).

**Whole-corpus scale:** 716 `.md → .md` edges; 105 of 190 files emit ≥1
outbound `.md` link (the rest are leaf/cell pages, expected).

---

## 5. Dead / one-way-link table

### 5a. Dead links (broken path or broken anchor)

| source:line | target | defect class |
|---|---|---|
| — | — | **NONE FOUND** |

Across 190 files / 1,161 internal links / 42 anchor-bearing links: **0
broken relative paths, 0 broken anchor fragments.** Two near-misses were
investigated and cleared:
* `ARCHITECTURE.md:877` (+ 5 other refs) → `translator-plans.txt` — the file
  is **tracked** (`git ls-files --error-unmatch` succeeds); it merely isn't a
  `.md`, so it didn't appear in an `*.md` listing. Not a defect.
* `_pr-archive-pre-public.md` (root) — **gitignored** (`.gitignore:90`), so
  its many external `<a href>` Dependabot links are out of scope. Not part
  of the published corpus.

### 5b. One-way links of consequence (named exemplar sets only)

| source:line → target | reverse present? | class |
|---|---|---|
| `README.md:316 → tests/README.md` | NO | exemplar reciprocity gap (DB-01) |
| `AGENTS.md:366 → tests/README.md` | NO | exemplar reciprocity gap (DB-01) |

### 5c. By-design hub-spoke asymmetry (catalogued, NOT counted as defects)

The reciprocity script found **73 "one-way" See-also edges among core docs**.
After filtering for the project's intentional asymmetric peer-sets (leaf/
reference docs point up to orientation hubs; hubs point across to topical
docs), all but the two rows in §5b are the expected hub-spoke shape, e.g.:

* `CONTRIBUTING → README/AGENTS/ARCHITECTURE` (child → parents; parents need
  not list every contributor doc).
* `docs/glossary → README/ARCHITECTURE/AGENTS` while `CAPABILITIES →
  glossary` (glossary is a reference sink that points up; many docs point
  into it).
* `docs/RELEASE_PLAN`, `docs/IDENTITY`, `docs/COMPARISON`, `docs/HOW_WE_TEST`
  → orientation hubs (one-directional by design; `AGENTS.md` See-also
  already enumerates them as the discovery surface).

I deliberately do **not** list all 73 as findings — doing so would
contradict `AGENTS.md`'s own asymmetric exemplar peer-sets and bury the one
real gap (DB-01). The full edge list is reproducible from the adjacency in
§4.

### 5d. Orphans (zero inbound Markdown link, committed corpus)

| orphan file | mitigated by | finding |
|---|---|---|
| `tools/README.md` | bare-backtick mentions only | DB-03 |
| `netcanon_desktop/README.md` | — | DB-03 |
| `netcanon/definitions/README.md` | distinct from top-level `definitions/README.md` | DB-03 |
| `tests/fixtures/real/phase4_spawn_tasks.md` | frozen Phase-4 artifact | DB-03 |
| `docs/v0.2.0-planning/03-nxos-codec/{02,03,04}-*.md` | listed bare-backtick in own README | DB-02 |
| `docs/docs-audit/2026-05-21/cluster-{B,E}-*.md` | frozen dossier; bare mentions | DB-05 |
| `docs/archive/README.md` | retired-citation index | DB-07 |
| `docs/vendor-references/*/_INDEX.md` (×56) | YAML is the designed entry point; indexes complete | DB-04 |
| `.github/PULL_REQUEST_TEMPLATE.md` | GitHub auto-surfaces it | not a defect |

---

## 6. What's GOOD

* **Zero broken links and zero broken anchors** across the entire
  hand-authored corpus. For a 190-file, 1,161-link graph this is rare and
  reflects real discipline.
* **Em-dash anchor handling is correct and consistent.** All 23 links that
  target em-dash headings (`CAPABILITIES.md#tier-1--auto-translatable-…`,
  `#tier-3--opaque-carry--not-auto-rendered`, `WANTED.md#tier-d--entirely-…`)
  use the doubled-hyphen slug GitHub actually produces. The 2026-05-21
  audit's em-dash fix (`11-aruba_aoscx.md:363`) held and the pattern
  propagated cleanly to every vendor page.
* **The named exemplar reciprocity sets are 2-of-3 fully bidirectional**
  (`ARCHITECTURE ↔ {definitions,codecs,canonical}/README`;
  `tests/README ↔ testid_reference`), and the high-traffic top-level hubs
  (`README ↔ AGENTS ↔ ARCHITECTURE ↔ CAPABILITIES ↔ SECURITY`) form a fully
  connected bidirectional core.
* **Dated-dossier discoverability is solid.** `security-triage` and
  `docs-audit` are each linked top-down from `AGENTS.md` (`:188-189`,
  `:364-365`), `ARCHITECTURE.md` (`:879-880`), and `SECURITY.md`
  (`:392/518/522`), and they reciprocate each other
  (`security-triage/README.md:145 ↔ docs-audit/README.md:151`) — the
  Commit-17 reciprocal link landed.
* **The vendor-reference cache is structurally complete:** a whole 56-pair
  mesh, every pair indexed, every index matching its on-disk contents.
* **A single, well-maintained link convention** — backtick-wrapped link text
  `[`path`](path)` — is used consistently; there are no stray HTML `<a href>`
  navigational links (the only `<a>` tags are inside CHANGELOG code examples)
  and no reference-style `[x]: url` definitions to drift. This makes the
  graph fully analyzable by one regex pass.
* **Sub-READMEs almost universally carry See-also footers** (only the
  archive, the v0.2.0-planning hub, and one leaf fixture README lack one),
  and `docs/METHODOLOGY.md` even documents the discipline with live
  cross-citations into `AGENTS.md` and `CAPABILITIES.md` that all resolve.

---

## 7. Coverage table

| Surface | How covered | Result |
|---|---|---|
| All hand-authored `.md` (190 files) | Scripted link + anchor verification | 0 dead links / 0 dead anchors |
| Anchor fragments (42 anchor-links) | GitHub-slug reproduction incl. em-dash | 42/42 resolve (23 em-dash-aware) |
| Same-file `#anchor` links | Same pass | all resolve |
| Top-level docs (README/AGENTS/ARCHITECTURE/SECURITY/BUG_REPORTING/CHANGELOG/CONTRIBUTING/CODE_OF_CONDUCT) | Adjacency + reciprocity + read of See-also blocks | core fully connected; DB-01 gap |
| `docs/*.md` operator + contributor docs | Adjacency + See-also footer presence | healthy; DB-06 (planning hub footer) |
| `docs/<subdir>/README.md` (planning, vendors, walkthroughs, templates, dossiers, archive) | Per-folder index-link check | DB-02 (nxos), DB-05, DB-07 |
| `tests/*.md` + `tests/fixtures/real/*.md` | Inbound/outbound link check | DB-03 (phase4_spawn_tasks orphan) |
| `netcanon/**/README.md` (5 present) | Inbound link + ARCHITECTURE reciprocity | DB-03 (2 orphans) |
| Directories lacking a README | `test -f` enumeration over 13 dirs | DB-08 (selective convention; by design) |
| `docs/vendor-references/_INDEX.md` (×56) + cache README | Mesh completeness + index-vs-disk + inbound link | DB-04 (no hub index), DB-09 (complete), DB-10 (filename style) |
| `<a href>` / reference-style links | Targeted grep | none navigational (CHANGELOG examples only) |
| Dated dossiers (security-triage / docs-audit / project-review) | Top-down + reciprocal reachability | reachable + reciprocal; project-review uncommitted (expected) |

**Not exhaustively covered (by scope):** the ~624 per-cell vendor-reference
topic `.md` bodies (audited only at index level per the brief); external
HTTP(S) link liveness (not this lens — and many are deliberately archival
vendor URLs); `docs/project-review/2026-06-06/` sibling reviewer outputs
(uncommitted, not part of the corpus under review).

---

## 8. Open questions

1. **Is the `tools/` vs `netcanon/tools/` split intentional, and which README
   should own the `sanitize.py` narrative?** `tools/README.md` (orphaned,
   DB-03) documents the top-level `tools/*.py`; `netcanon/tools/` has the
   in-package sanitiser and no README. A code/architecture reviewer (Fleet C)
   may have context on whether these should converge.
2. **Should the 56 vendor-reference `_INDEX.md` files be reachable by
   Markdown navigation at all,** or is the YAML-as-entry-point design (DB-04)
   a deliberate "this is a machine-addressed artifact, not a browse target"?
   If the latter, a single clarifying sentence in the cache README would stop
   future audits from re-flagging the orphans.
3. **Does the project want a CI link-checker?** The corpus is large enough
   (1,161 links) that the current zero-defect state is a credit to manual
   discipline; a `lychee`/`markdown-link-check` job (anchors included) would
   make DB-01-class regressions fail loud rather than wait for the next
   hygiene audit. `AGENTS.md` already prefers "guard the number" over prose;
   the same logic argues for guarding the graph.
4. **`scripts/render_aruba_central_template.py`** is a lone tracked script
   with no README and no inbound link (DB-08 snag 1) — is `scripts/` a
   sanctioned location distinct from `tools/`, or vestigial? Out of this
   lens's strict scope but surfaced for whoever owns repo layout.

---

*Methodology note: all counts are reproducible from `git ls-files` at
`b08040c` plus the slug/link algorithm described in §1. Where an early
scripted result proved to be a tooling artifact (the underscore-filename
false "incomplete index"; the `.md`-only listing missing the tracked
`translator-plans.txt`), I re-ran with the corrected matcher and report only
the corrected result. No claim in this chapter rests on an unverified grep.*

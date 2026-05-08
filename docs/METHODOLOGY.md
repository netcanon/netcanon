# Matrix-Honesty Methodology

*A portable discipline for building tools that have to be honest about
their own limits — distilled from the Netcanon multi-vendor config
translator project.*

---

## Why this document exists

This document captures a coherent development discipline that emerged
wave-by-wave through the Netcanon project but never previously got
written down in one place.  Three audiences benefit:

1. **Future contributors to Netcanon** find the rationale behind the
   patterns embedded in `CLAUDE.md`, `ARCHITECTURE.md`, and the
   per-codec capability declarations.
2. **A future self on a different project** can clone this doc and
   adapt it; the discipline transfers, the implementation does not.
3. **Anyone using the sister `docs/templates/` directory** as
   starter material can read this for the *why* behind the shapes the
   templates have.

The discipline is most useful for tools that translate between formats
(compilers, transpilers, importers, config translators), tools whose
correctness has to survive being run against inputs the author never
saw, and tools whose users are skeptical of automation that touches
production state.  It is overkill for tools that ship and run in a
context where their own author is the only operator.

This is not a tutorial.  Read for the patterns, not the syntax.  The
patterns are deliberately demonstrated with file:line citations
into Netcanon's tree so the abstract claims are grounded.

---

## The discipline (what it is)

### Matrix-honesty

A tool is *matrix-honest* when, for every claim it makes about its
own capabilities, three artefacts agree:

* What the **shipped code** actually does (parse, render, validate,
  emit, drop).
* What the **declarations the tool exposes** to its operators say it
  does (capability tables, feature lists, error messages, README
  bullet points, UI banners).
* What the **audit harness** verifies it does against representative
  inputs.

The discipline is violated whenever any two of these drift.  Drift in
either direction matters: over-claiming capabilities (the README
promises X, the code drops X silently) destroys operator trust;
under-claiming (the matrix marks X unsupported but the codec parses
and renders X) hides shipped work and confuses the audit.

Netcanon examples of this discipline being violated and then
corrected:

* `cisco_iosxe_cli` declared `/routing-instances/instance` as
  `UnsupportedPath` with reason "wire-up deferred" — but the parse
  function (`parse._parse_routing_instances`) and the render emit
  loop had been shipping for months.  The codec's own declaration
  contradicted both its code and the cross-vendor expectation YAML.
  Caught and corrected in commit `07086b1`.
* `cisco_iosxe` (NETCONF) target codec emitted only the
  `openconfig-interfaces` subtree but the matrix did not declare the
  16 unrendered surfaces as unsupported — the cross-mesh audit was
  flagging 6,677 cells as "methodology issue" when the answer was
  simply that the target codec didn't render those fields.  Closed
  in Wave 10γ-2 (commit `f81f3a5`).
* "Phase 2 will add a resolver" docstrings: comments referencing
  unshipped future work that becomes a lie the instant Phase 2 ships.
  CLAUDE.md's documentation sync checklist
  ([`CLAUDE.md` lines 110-134](../CLAUDE.md)) explicitly enumerates
  module-docstring inventories as a row that must be touched in the
  same commit as the addition.

### Forensic discipline

The reproduction test goes first.  When investigating a suspected bug,
do not write the fix and a confirming test together — write a test
that **encodes the wrong behaviour** as the assertion, watch it pass,
then flip the assertion to encode the correct behaviour and watch the
fix land.  This is the only reliable way to avoid validation theatre
(tests that pass because they describe the bug instead of the fix).

The discipline catches misdiagnoses.  Three Netcanon waves proved
this:

* **Wave 7c-E** (commit `2d7a7f2`) — a flagged CODEC_BUG cell on
  `fortigate_cli → juniper_junos` initially looked like a Junos render
  bug; the reproduction test surfaced that the actual defect was on
  the FortiGate parse side, mis-classifying interface kinds before
  the canonical tree ever reached Junos.
* **Wave 7c-G** (commit `c344200`) — `opnsense → aruba_aoss` cell
  was first triaged as a missing Aruba codepath; the reproduction
  showed it was a *Phase 4* methodology gap — the per-pair YAML had
  the wrong disposition and Phase 1's drift report was correct.
* **Wave 9γ-A/B/C** (commits ending at `d4956a7`) — over-eager lossy
  declarations on FortiGate / Junos / MikroTik / OPNsense source
  codecs were initially attributed to "real lossy translation" when
  the disciplined per-source investigation showed each declaration
  was contradicted by the codec's own actual round-trip behaviour.
  Re-flipped lossy → good after the reproduction tests demonstrated
  faithful preservation.

In all three cases the first hypothesis was wrong; in all three
cases the discipline of writing the test before the fix surfaced
the right diagnosis.

### Doc-sync in the same commit

Code changes and the docs they invalidate land together.  Follow-up
doc-only commits are acceptable for retroactive audits of pre-existing
drift; they are **not** acceptable for fresh code that ships without
its docs.  The rationale is failure-mode asymmetry: code that compiles
but is wrong fails loudly in CI; docs that are wrong fail silently
until a future contributor wastes a day on a stale claim.

The disciplinary mechanism in Netcanon is a concrete *Documentation
Sync Checklist*: a table mapping "if you change X, then touch Y."
See [`CLAUDE.md` lines 102-138](../CLAUDE.md).  The table is
intentionally exhaustive rather than illustrative — every row in it
exists because someone forgot the corresponding doc and shipped
drift, then went back and audited what they should have updated.

### Capability declarations must match code

Where matrix-honesty (section above) is the abstract contract, the
*capability declaration* is the concrete artefact that makes the
contract enforceable.  Every Netcanon codec declares a
`CapabilityMatrix` of three lists:

```python
supported = [...]   # xpaths the codec can round-trip without loss
lossy = [
    LossyPath(path=..., reason=..., severity=...),
    ...
]
unsupported = [
    UnsupportedPath(path=..., reason=...),
    ...
]
```

See [`cisco_iosxe_cli/codec.py` lines 132-260](../netconfig/migration/codecs/cisco_iosxe_cli/codec.py)
for the canonical authoring shape.  Each declaration has a citation
to the specific drift it acknowledges.  These declarations surface to
operators directly via the UI's Validation panel
([`docs/CAPABILITIES.md` lines 124-229](CAPABILITIES.md)) and gate
the cross-vendor audit-harness's per-cell variance class.

### No active lies in operator-facing messages

Every operator-facing string is a load-bearing contract: the README's
claims, the error messages a user sees when things go wrong, the
banners on the migrate page, the docstrings of public functions, the
text in CAPABILITIES.md.  Stale "future will…" comments are debt;
stale capability claims are bugs.  Active lies in operator-facing
messages destroy trust faster than missing features.

Netcanon's notification mechanisms (Section B "Tier-3 sections
detected banner" + Section C "Render-time review comments" of
[`docs/CAPABILITIES.md` lines 230-318](CAPABILITIES.md)) are the
direct manifestation of this principle: rather than silently
dropping content the tool can't translate, the tool emits a
review comment in the target's native syntax citing exactly what
won't translate and why.  An operator searching for `review:` in
rendered output finds every such site.

---

## The patterns

### Wave-based development

Work in small focused waves; parallelise aggressively when scopes
don't overlap; reserve a coordinator role for the regen step at the
end of a wave.  Each wave is named (Wave 7c, Wave 9γ-A/B/C, Wave
10α/β/γ, Wave 11-A/B), shipped in a small handful of commits, and
followed by a regen + doc-sync commit closing the wave out.

The discipline that makes parallel waves work safely:

1. **File-overlap analysis BEFORE dispatch.**  Identify which files
   each parallel agent will touch.  If two agents touch the same
   file, serialise them or split the file.
2. **Each parallel agent owns a non-overlapping file scope.**
3. **A single coordinator does the final regen.**  After all agents
   land their commits, the coordinator regenerates the audit matrix
   (`tools/run_full_mesh.py --matrix` followed by
   `tools/run_phase4_reconciliation.py`) and commits the artefacts
   in one commit so the diff narrates the wave cleanly.

CHANGELOG entries cite each wave commit with rationale, matrix
delta, and test-suite delta — see the
[Wave 11 entry in `CHANGELOG.md`](../CHANGELOG.md) for a worked
example.

### Race-recovery convention

When parallel agents share a worktree they will collide on
intermediate state (git index, generated artefacts).  The recovery
convention is: `git stash` to set aside any in-progress local work,
then `git commit --only <paths>` to commit a specific known-clean
subset, then `git show HEAD --name-only` to verify exactly which
paths were committed.  No agent should run `git add -A` in a shared
worktree.

### Tier-based classification

Classify every translatable surface by stability tier:

* **Tier 1** — auto-translatable; cross-vendor stable; every shipped
  codec parses and renders cleanly.
* **Tier 2** — translatable with caveats; cross-vendor mappings can
  be lossy where vendors disagree on representation.
* **Tier 3** — opaque carry-through, never auto-rendered.  These
  surfaces are detected for *notification* but the tool deliberately
  doesn't try to translate them.

Worked example: Netcanon's `CanonicalIntent` model classifies every
field by tier (see [`intent.py` lines 31-49](../netconfig/migration/canonical/intent.py)).
Firewall rules, NAT rules, VPN configuration, and routing-protocol
state are explicitly Tier 3 with a documented architectural rationale
("zone-pair vs interface ACL vs table-driven rule sets — semantics
don't translate cleanly").  This is an architectural decision, not
a backlog item, and it is communicated as such to operators in
[`docs/CAPABILITIES.md` lines 91-114](CAPABILITIES.md).

The pattern generalises to any tool with capability boundaries: pick
a small number of tiers, write the criteria for each, and classify
every surface explicitly rather than letting capability boundaries
drift into the codebase by accident.

### Capability matrix declarations

The triad: every supported xpath listed; every lossy declaration
cites the specific drift; every unsupported declaration cites the
rationale.  No silent unsupported.  See
[`cisco_iosxe_cli/codec.py` lines 132-260](../netconfig/migration/codecs/cisco_iosxe_cli/codec.py)
for the canonical declaration shape.  Each `LossyPath` carries a
multiline reason explaining the exact drift; each `UnsupportedPath`
carries a multiline reason explaining either the architectural
deferral or the Tier-3 boundary it sits behind.

The cost of authoring these declarations seems high until the audit
harness runs against them: the matrix-honesty discipline is what
lets a downstream Phase 4 reconciler distinguish a *real* bug
from an *acknowledged* loss.  Without the declarations, every drift
is a candidate bug and the audit drowns in noise.

### Cross-mesh fidelity audit harness (the abstract pattern)

Generalises to any tool that translates between formats and needs
verifiable cross-format honesty:

* **Phase 1 (mechanical drift).**  For each (source, target,
  fixture) cell, parse → render → re-parse → field-by-field
  compare → record drift.  Output: a per-cell drift JSON.  See
  [`tools/run_full_mesh.py` lines 1-70](../tools/run_full_mesh.py).
* **Phase 4 (reconciliation).**  Classify each drift cell against
  per-pair expectation declarations.  Output: a variance class per
  cell with severity tier.  See
  [`tools/run_phase4_reconciliation.py` lines 1-95](../tools/run_phase4_reconciliation.py).

The variance class taxonomy is the load-bearing piece.  Netcanon's
eight classes:

* `ALIGNED` — drift matches expectation; no action.
* `CODEC_BUG` — drifted where expectation says clean; high-severity
  signal the codec author should fix.
* `EXPECTED_LOSSY` — drifted where expectation says lossy
  (acknowledged loss).
* `EXPECTED_UNSUPPORTED` — drifted where expectation says target
  vendor has no equivalent.
* `METHODOLOGY_ISSUE_under` — preserved where expectation says
  lossy/unsupported (over-claiming loss).
* `METHODOLOGY_ISSUE_over` — drifted against `not_applicable`
  expectation.
* `STRUCTURAL_ONLY` — list-row count drift collapsed to a single
  signal per cell-parent rather than amplified across N per-field
  keys.
* `TRIVIAL_EMPTY` — both sides empty/zero on this field; cell
  trivially aligns by absence of data.

See [`tools/run_phase4_reconciliation.py` lines 13-66](../tools/run_phase4_reconciliation.py)
for the authoritative class definitions.  Three of these classes
(`STRUCTURAL_ONLY`, `TRIVIAL_EMPTY`, plus the per-source-vendor
sub-field cascade in Wave 10γ) were added when the audit's signal-
to-noise ratio dropped below the threshold where it could productively
guide investigation.  The taxonomy is not a fixed framework —
it evolves to match the surface area the harness exercises.

### Cross-reference discipline

Every doc has a "See also" footer pointing at 2-3 closest peers.  A
contributor landing on one doc is one hop from the others.  When you
add a new sibling doc, add the reciprocal link in each existing peer
in the same commit.  See [`CLAUDE.md` lines 142-159](../CLAUDE.md)
for the project's explicit statement of this discipline; every doc
in `docs/` ends with a "See also" footer, e.g.
[`docs/CAPABILITIES.md` lines 476-483](CAPABILITIES.md) and
[`ARCHITECTURE.md` lines 837-848](../ARCHITECTURE.md).

The reason this matters: one-way references rot faster than numbers
do.  A doc that's no longer linked to from its peers might as well
not exist; a contributor who lands on its peers won't know it's
there to find.

### Hard-rule structure

The "Never X without Y" pattern.  Each hard rule has a one-line
rationale pointing at the failure mode that motivated it.  The rule
is sticky precisely because the rationale is concrete: a future
contributor who reads "Never author a `type_key` containing `_` or
`.`" sees not just the rule but *why* — the file-store filename
grammar uses these characters as separators, and underscores or dots
inside a `type_key` make the filename parse mathematically ambiguous.

Worked example: see [`CLAUDE.md` lines 191-200](../CLAUDE.md) for
the `type_key` filename-safety rule.  The rule lives in CLAUDE.md
because the failure mode was independently rediscovered by two
separate contributors before the validator existed; once it became
a hard rule with rationale, it stopped being rediscovered.

The pattern generalises: any time a bug surfaces that's actually a
class of bugs masquerading as one instance, promote the lesson to a
hard rule.  The rule's body should explain enough that a contributor
who's never seen the failure can avoid it.

### Pre-flight checklist

Each wave starts with verifying tree state (no in-progress changes),
branch state (rebase clean against main), suite state (the test suite
must be green; a wave doesn't start by adding to a broken suite),
and prior-context state (read the relevant CHANGELOG entries from
the most recent waves so the new wave is grounded in what just
happened).

Each commit follows a body convention:

1. **Rationale-first.**  The commit message body opens with *why*
   the change is happening, not *what* changed.  The diff already
   shows the what.
2. **Matrix delta cited when applicable.**  If the change moves any
   capability declaration, cross-vendor expectation, or audit
   variance class, the body cites the delta numerically.
3. **Test-suite delta cited.**  Body ends with the pass/skip/fail
   numbers before and after.
4. **Co-author trailer.**  Standard footer identifying the
   collaborating model + invocation context.

See commit `07086b1` for the canonical worked example
(`Validation cleanup: cisco_iosxe_cli /routing-instances/instance
lossy (was stale unsupported)`) — the body opens with what surfaced
the bug, lists the three contradicting artefacts, lists the four
specific code edits, cites the matrix delta (zero), and closes with
the suite delta and a footnote identifying which separate-but-
related declarations stay correct.

---

## The artefacts (and what each is for)

The artefact taxonomy is shaped by audience.  Each artefact has a
specific reader and a specific scope; mixing scopes across artefacts
produces docs that are simultaneously too long and too vague.

* **`CLAUDE.md`** — operational rulebook for contributors.  Lives at
  repo root.  Hard rules + doc-sync checklist + cross-reference
  discipline.  Read by every contributor on every session.  *Not*
  a tutorial; *not* a design doc.  Length: tightly bounded — every
  added rule has to earn its line by pointing at a real failure
  mode.
* **`ARCHITECTURE.md`** — design + invariants.  Internal-facing.
  Source of truth for "how this is built."  Read by contributors
  who need to extend a subsystem.  *Not* operator-facing.  *Not* a
  current-state shipping log.
* **`CHANGELOG.md`** — chronological shipping log.  `[Unreleased]`
  block for in-flight; promote to versioned cuts at release.
  Archival; entries are timestamps, not current-state claims, so
  the no-hard-coded-counts rule does not apply (see
  [`CLAUDE.md` lines 209-219](../CLAUDE.md)).  *Not* forward-
  looking.
* **`docs/CAPABILITIES.md`** — operator-facing capabilities + known
  limitations.  Tier 1/2/3 enumeration + capability matrix tables +
  notification mechanisms.  Cross-referenced against in-app
  limitation messages.  *Not* internal architecture.  *Not* a
  roadmap.
* **`docs/RELEASE_PLAN.md`** — forward-looking pre-launch plan.
  Pre-flight checklist + qualitative hardening + packaging tier
  strategy + concrete release sequence.  Becomes
  `docs/RELEASE_NOTES.md` after release.  *Not* shipped work — by
  construction it describes work that hasn't happened yet.
* **`docs/METHODOLOGY.md`** (this document) — portable discipline
  statement.  Distilled from the project's actual development
  trajectory.  *Not* a substitute for the implementation-specific
  artefacts above; rather, the *why* behind their shapes.

Project-specific extensions live alongside these (e.g.
`tests/testid_reference.md`, `tests/fixtures/real/RESULTS.md`,
`docs/glossary.md`).  Add such an extension only when a discipline-
load-bearing surface needs its own doc — not as a default move.

---

## The anti-patterns

For each: what it looks like, why it's bad, how to detect it.

* **Active lies in docstrings.**  "Phase 2 will add a resolver"
  comment, eighteen months after Phase 2 shipped.  Detect via grep
  for "will add" / "future extension" / "TODO" against the commit
  log; any phrase about future work whose specific commit is older
  than 60 days is a candidate.  CLAUDE.md's documentation sync
  checklist row about *module docstrings that enumerate contents*
  is the disciplinary defence.
* **Hard-coded counts in prose without CI guards.**  "The 50+
  hardware models we support."  Detect via the no-hard-coded-counts
  hard rule ([`CLAUDE.md` lines 209-219](../CLAUDE.md)).  Acceptable
  in CHANGELOG (timestamps) and test assertions (fail loudly when
  the number drifts).  Unacceptable in current-state prose, where
  the number rots silently.
* **Silent drops without operator notification.**  Source-side
  parser receives a stanza, doesn't know what to do with it, drops
  it, returns a "successful" parse.  Detect via cross-referencing
  parser dispatch tables + capability matrix + UI banner coverage.
  Netcanon's Wave 11
  ([`CHANGELOG.md` lines 81-130](../CHANGELOG.md)) closed exactly
  this gap by adding parser-level Tier-3 stanza detection +
  population of `CanonicalIntent.dropped_tier3_sections` + a UI
  banner enumerating what was dropped.
* **Capability declarations that contradict shipped code.**  "Wire-
  up deferred" claim while parse + render both shipped.  Detect via
  the validation cross-reference audit — checking every
  `UnsupportedPath` reason against actual codec code paths.  See
  the Wave 11-A → Wave-11-Validation-Cleanup arc
  ([`CHANGELOG.md` lines 14-69](../CHANGELOG.md)) for the worked
  example.
* **"Deferred" comments that mask shipped work.**  Same as the
  preceding row — a `TODO: implement X` comment surviving the
  commit that implemented X.  Same detection.
* **Validation theatre.**  Tests that assert on the bug instead of
  the fix.  Detect via the forensic discipline above: the
  reproduction test must be written FIRST and must encode the BUG
  as the assertion before being flipped to encode the fix.  A
  test landing in the same commit as its corresponding fix without
  ever having existed in the bug-encoding state is suspect.

---

## Worked example: this project as the live demonstration

This section is for the reader who wants to see each pattern as a
real artefact rather than an abstract claim.

> **Pattern:** Cross-reference discipline.
> **Live example:** [`CLAUDE.md` lines 142-159](../CLAUDE.md) (the
> discipline statement); every doc in `docs/` has a "See also"
> footer (e.g. [`docs/CAPABILITIES.md` lines 476-483](CAPABILITIES.md);
> [`ARCHITECTURE.md` lines 837-848](../ARCHITECTURE.md)).

> **Pattern:** Hard-rule structure with rationale.
> **Live example:** [`CLAUDE.md` lines 183-234](../CLAUDE.md) — the
> "Hard Rules" section.  Each rule has a one-line rationale; the
> `type_key` rule (lines 191-200) explicitly cites the two
> independent rediscoveries that motivated promoting it from
> implicit-knowledge to hard-rule.

> **Pattern:** Capability matrix declarations.
> **Live example:** [`cisco_iosxe_cli/codec.py` lines 132-260](../netconfig/migration/codecs/cisco_iosxe_cli/codec.py)
> — every `LossyPath` and `UnsupportedPath` carries a multiline
> reason citing the specific drift or rationale; the
> `/routing-instances/instance` declaration explicitly cites the
> commit (`40de39c`) that confirmed cross-vendor round-trip.

> **Pattern:** Cross-mesh audit harness.
> **Live example:**
> [`tools/run_full_mesh.py`](../tools/run_full_mesh.py) (Phase 1
> mechanical drift) +
> [`tools/run_phase4_reconciliation.py`](../tools/run_phase4_reconciliation.py)
> (Phase 4 reconciliation against per-pair expectation YAMLs).
> Outputs at
> [`tests/fixtures/real/CROSS_MESH_RESULTS.md`](../tests/fixtures/real/CROSS_MESH_RESULTS.md)
> and
> [`tests/fixtures/real/PHASE4_RECONCILIATION.md`](../tests/fixtures/real/PHASE4_RECONCILIATION.md).

> **Pattern:** Tier-based classification.
> **Live example:**
> [`netconfig/migration/canonical/intent.py` lines 31-49](../netconfig/migration/canonical/intent.py)
> — the docstring enumerates Tier 1 / 2 / 3 explicitly with
> per-field assignment;
> [`docs/CAPABILITIES.md` lines 47-114](CAPABILITIES.md) translates
> the same tiering into operator-facing prose.

> **Pattern:** Doc-sync in same commit.
> **Live example:**
> [`CLAUDE.md` lines 102-138](../CLAUDE.md) — the explicit row-by-row
> mapping of "if you change X, then touch Y."

> **Pattern:** Forensic discipline (reproduction test FIRST).
> **Live example:** Wave 7c-E (commit `2d7a7f2`); Wave 7c-G (commit
> `c344200`); Wave 9γ-C (commit `d4956a7`).  Each commit body
> documents the misdiagnosis caught by writing the reproduction
> test before the fix.

> **Anti-pattern:** Active lies in docstrings.
> **Live example (corrected):** Commit `07086b1` —
> `cisco_iosxe_cli` `/routing-instances/instance` declaration's stale
> "wire-up deferred" reason corrected to lossy with a documented
> sub-field-drift rationale.

> **Anti-pattern:** Capability declaration contradicting shipped code.
> **Live example (corrected):** Wave 10γ-2 (commit `f81f3a5`) —
> `cisco_iosxe` (NETCONF) target codec's matrix corrected to declare
> 16 unrendered surfaces as `unsupported`, closing 6,677 spurious
> methodology-issue cells.

---

## Adapting to a new project

The discipline is portable; the implementation is not.

**Portable as-is:**

* The matrix-honesty contract: code, declarations, and audit must
  agree at commit time.
* The forensic discipline of writing reproduction tests FIRST.
* The hard-rule structure: `Never X without Y`, with rationale.
* The cross-reference footer convention.
* The artefact taxonomy: rulebook + design doc + changelog +
  capabilities + release plan + methodology, each with a single
  audience.
* The wave-based development cadence with race-recovery convention
  and coordinator regen at the end.
* The tier-classification framework: pick a small number of
  capability tiers and classify every surface explicitly.
* The cross-mesh audit harness pattern: Phase 1 mechanical drift +
  Phase 4 reconciliation against expectation declarations + variance
  class taxonomy with severity tiers.

**Project-specific:**

* The four-layer migration model (Vendor / Codec / Canonical /
  Transport) is Netcanon's specific architecture.  A different
  translator might have three layers or seven.
* The specific tier definitions are Netcanon-specific.  Another
  project might have Tier 1 / 2 only, or Tier 1 / 2 / 3 / 4 with a
  different boundary.
* The variance class taxonomy started at 6 classes and grew to 8 as
  the audit's surface area exercised more cases.  A different
  project's taxonomy will end up at a different count for the
  same reason.
* The doc-sync checklist categories that generalise (interactive UI
  elements, public functions, configuration schemas, capability
  declarations) vs the rows specific to Netcanon's surface (codec
  authorship, target-profile YAMLs, real-capture fixtures, pytest
  markers).
* The specific test-tier organisation (unit / integration / e2e /
  desktop) depends on the platforms the project ships.

When porting, do not start by copying the implementation artefacts.
Start by re-deriving the artefact taxonomy for the new project's
audience: who reads each doc, what scope each doc covers, what
shape would let each reader find the rationale for the patterns
they encounter.  Then port the disciplines into the artefact shapes
the new project needs.

---

## Pointer to the templates

A sister directory, `docs/templates/`, contains starter-template
versions of each artefact: a skeleton `CLAUDE.md`, a skeleton
`ARCHITECTURE.md`, a skeleton `CAPABILITIES.md`, etc.  The templates
are not authoritative — they are starting points.  This document is
the reference for *why* the templates have their shape; clone from
the templates and read here when a template's structure raises a
"why is this section here?" question.

If the templates and this document drift from each other in a future
edit, the templates are the consumable artefact and this document is
the explanation; the explanation should follow the consumable, not
the other way around.  Either way, both should evolve in the same
commit.

---

## See also

* [`CLAUDE.md`](../CLAUDE.md) — contributor directives (the
  operational rulebook this document distills the discipline behind).
* [`ARCHITECTURE.md`](../ARCHITECTURE.md) — internal four-layer
  design (the structure the discipline operates on).
* [`docs/CAPABILITIES.md`](CAPABILITIES.md) — operator-facing
  capabilities + known limitations (the matrix-honesty discipline's
  outward-facing artefact).
* [`docs/RELEASE_PLAN.md`](RELEASE_PLAN.md) — forward-looking
  pre-launch plan (the methodology applied to the release surface).
* [`CHANGELOG.md`](../CHANGELOG.md) — chronological shipping log
  (the wave-by-wave demonstration of the discipline in practice).
* [`tools/run_full_mesh.py`](../tools/run_full_mesh.py) +
  [`tools/run_phase4_reconciliation.py`](../tools/run_phase4_reconciliation.py)
  — the cross-mesh audit harness implementation.
* [`tests/fixtures/real/PHASE4_RECONCILIATION.md`](../tests/fixtures/real/PHASE4_RECONCILIATION.md)
  — the live audit matrix the harness produces.
* `docs/templates/` — starter-template versions of the artefacts
  this document describes.  Sister directory authored in parallel;
  reader who wants to clone-and-adapt clones from there, then reads
  this document for the rationale behind each template's shape.

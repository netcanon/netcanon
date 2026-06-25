# Blackboard seed — Fail-surfaced defaults (the meta-finding)

**Run:** 2026-06-24 · ultracode blackboard · netcanon
**Main thread:** Claude (synthesizes 99-synthesis.md, then PROTOTYPES + VERIFIES + commits — agents do NOT)

---

## Mission

Design the **durable, structural fix** for the *meta-finding* surfaced by five
successive blind audits of netcanon: the **covered-subset blind spot**. Every
audit round patches the *named instance* of a recurring class of defect, and the
next blind pass finds a **new surface of the same class**. We want to stop
playing whack-a-mole and make the *class* unable to silently recur — i.e.
**fail-surfaced defaults**: a new field should DEFAULT to "surfaced/flagged",
not to "silently fine".

This is a **design + quantify + prototype-readiness** run, not a ship-it run.
Output a concrete, minimal, low-risk, *verified-on-paper* design + blast-radius
numbers + a PR plan the main thread can actuate. Favor the option that converts
the blind spot into a **CI failure** (caught at test time) over a risky runtime
behavior change — but evaluate all options honestly against the user's stated
goal.

## The two recurring classes (the disease, not the symptoms)

1. **Silent capability-loss class.** The migration walker
   `_walk_canonical` (`netcanon/migration/canonical/xpath_walker.py`) yields a
   *subset* of the canonical model's leaves. `classify()`
   (`netcanon/models/migration.py`) treats any xpath that is neither walked nor
   explicitly declared (supported/lossy/unsupported) as **`supported` by
   default**. So any canonical field a codec silently drops on render is
   reported `severity: ok` — a SILENT data loss — until a human notices and adds
   it to the walker + declares it per-codec. Instances fixed across rounds:
   switchport → static-route → VXLAN → VLAN port-membership (#172) → VLAN-SVI
   L3 (#175). Root cause = **default-to-supported on an unwalked leaf.**

2. **Sanitizer-bypass class.** `sanitize_intent`
   (`netcanon/tools/sanitize.py`) redacts secrets/public-IPs via an **explicit
   allow-list of known fields**. Any *new* IP-bearing (or secret-bearing) field
   added to the canonical model leaks verbatim into a shared/sanitised config or
   bug report until a human names it in the sanitizer. Instances fixed across
   rounds: IPv4 → IPv6 → overlay RD/RT → anycast virtual-gateway-address (#174).
   Root cause = **redact-from-an-allow-list (default-to-passthrough).**

Both share the same shape: **a hand-maintained subset + a permissive default.**

## The durable fix the user described (the goal)

> "fail-surfaced defaults — the walker yields EVERY leaf (or the codec must
> declare it); the sanitizer redacts on `ip_address()` of ANY IP-typed field,
> not an allow-list."

The user's explicit caution: this is a big behavior change with
**over-redaction / over-flagging risk** — *prototype against the fixture corpus
first, especially the sanitizer over-redaction risk.*

## The design space to evaluate (be honest about trade-offs)

For EACH class, weigh at least these forms:

- **(A) Runtime behavior change** — walker auto-yields every leaf; sanitizer
  blanket-redacts any `ip_address()`-parseable string field. Maximally durable
  but maximal churn/risk (phase4 reclassification storm; over-redaction of
  private/docs IPs and free-text fields that falsely parse).
- **(B) Structural completeness GUARD (CI meta-test)** — a reflection-driven
  test that enumerates the canonical model's leaves and **FAILS** when a leaf is
  neither walked-and-declared (class 1) / neither redacted-nor-exempt (class 2),
  unless it is in an *explicit, self-justifying exemption set*. No runtime
  change; converts the blind spot into a red CI run the moment someone adds an
  un-handled field. Lower risk; the open question is whether the exemption list
  just *relocates* the blind spot.
- **(C) Fail-surfaced by construction** — annotate IP/secret-bearing model
  fields with a typed marker (e.g. `Annotated[str, IPField]` / pydantic field
  metadata) so the walker AND the sanitizer can MECHANICALLY enumerate "every
  IP-typed leaf" from the model itself. The most intrinsic ("defaults" in the
  truest sense), but assess churn + whether it's over-engineering vs (B).

The recommendation may differ per class (e.g. guard for the walker, typed-marker
for the sanitizer) — say so and justify.

## Hard constraints (load-bearing)

- **Read-only agents.** Each writes ONLY its own report file. The MAIN THREAD
  builds, runs the suites/regen, and commits. Do NOT edit source/tests/fixtures,
  run git, or run the regen tools (`tools/run_full_mesh.py`,
  `tools/run_phase4_reconciliation.py`).
- **Respect the existing partial guards** — don't propose something that
  duplicates or contradicts them; build ON them:
  - `tests/unit/migration/test_silent_loss_list_subfields.py` (value-detail `_CASES`)
  - `tests/unit/migration/test_silent_loss_naming_sensitive.py` (`_NATIVE` map)
  - `tests/unit/migration/test_registry_capability_honesty.py` (reverse-parity)
  - the reverse-parity guard `test_lossy_unsupported_nonwalkable_is_documented_synthetic`
    (PR #149) — ⚠️ it teaches the load-bearing lesson: **Tier-3 routing-protocol
    `unsupported` paths are INTENTIONALLY non-walkable**; a naive "every declared
    path must be walkable" FALSE-FAILS on them. Its `_SYNTHETIC_NONWALKABLE`
    allowlist + 3 structural rules are the precedent for a self-justifying
    exemption mechanism.
  - the per-codec honesty floor `tests/unit/migration/cisco_iosxe_cli/test_walk_canonical_coverage.py`.
- **The sanitizer PRESERVES private / documentation-range IPs by design**
  (RFC-1918 LAN gear is the common case; redacting it would destroy a useful
  shared config). Any class-2 design must NOT over-redact those.
- **phase4 reconciliation is sensitive**: a new walker yield or matrix
  declaration can reclassify cells in `tests/unit/audit/`. Any class-1 design
  that changes walker yields must account for the full-`tests/unit` (incl
  `tests/unit/audit`) impact. QUANTIFY it; do not hand-wave.
- **No secrets / no PII in your report.** Analyze the model/walker/sanitizer
  structure; do NOT paste real device configs. NEVER read or write under
  `docs/codebase-review/`.

## File roster (read these; cite file:line)

- `netcanon/migration/canonical/intent.py` — the canonical model (17 classes,
  root `CanonicalIntent`, ~930 lines). The denominator for both gaps.
- `netcanon/migration/canonical/xpath_walker.py` — `_walk_canonical` (~255 lines).
- `netcanon/models/migration.py` — `classify()` + the capability-matrix types
  (`CapabilityMatrix`, `LossyPath`, `UnsupportedPath`); the default-to-supported
  rule lives here (confirm it).
- `netcanon/tools/sanitize.py` — `sanitize_intent` (~1153 lines); the redaction
  allow-list + the private/docs-preservation logic.
- The 5 guard tests listed above.
- `AGENTS.md` (repo doctrine) + `docs/agent-workflow.md` (blackboard protocol).
- Capability matrices are inline per codec at
  `netcanon/migration/codecs/<name>/codec.py` (`supported`/`lossy`/`unsupported`).

## Deliverable per phase

- **Phase 1 (Census + Gap):** ground truth — the complete model-leaf set; the
  walker's exact yields + the blind-leaf gap (with per-codec population); the
  sanitizer's exact redaction set + the IP/secret leak-candidate gap + a sober
  over-redaction analysis.
- **Phase 2 (Design):** concrete designs (A/B/C) per class, with exact
  test/code shape, exemption mechanism, and **quantified blast radius** (leaves
  to walk/declare, phase4 cells reclassified, fixture-corpus diffs).
- **Phase 3 (Review):** adversarial — does the recommended guard actually catch
  a *synthetic new* unwalked-leaf / unredacted-IP-field? does the exemption list
  relocate the blind spot? over-fire risk? GO / GO-WITH-FIXES / NO-GO + must-fixes.

The main thread will read all reports, write `99-synthesis.md`, then prototype
the recommended design, verify it against the fixture corpus + full `tests/unit`,
and land it (pausing for the user as the risk warrants).

---

## Per-agent assignments

Find your `id` below and execute exactly that brief. Write your long-form report
to your own file; return only the structured summary.

### Phase 1 — Census (parallel; do NOT read peers — you run concurrently)

**`10-model-leaf-census`** — Produce the COMPLETE leaf census of the canonical
model, the shared denominator both gap analyses depend on. Read
`netcanon/migration/canonical/intent.py` end to end; from the root
`CanonicalIntent` walk EVERY nested model (CanonicalInterface, CanonicalIPv4Address,
CanonicalIPv6Address, CanonicalVlan, CanonicalStaticRoute, CanonicalDHCPPool,
CanonicalSNMP, CanonicalSNMPv3User, CanonicalLAG, CanonicalVRRPGroup,
CanonicalLocalUser, CanonicalRADIUSServer, CanonicalVxlan, CanonicalRoutingInstance,
CanonicalEvpnType5Route, and any others). Study `xpath_walker.py` to learn the exact
xpath spelling (e.g. `/interfaces/interface/ipv4/address/ip`), then emit a TABLE of
every leaf as an xpath in that convention. Per leaf: xpath, owning `Class.field`,
python type, default, and booleans `IP_OR_HOST_BEARING` (could hold an
IPv4/IPv6/hostname) and `SECRET_BEARING` (passphrase/hash/community/key).
Distinguish scalar vs list-of-scalar vs nested-model containers. Be exhaustive — a
missed leaf makes both downstream gaps wrong. End with counts (total leaves, #
IP/host-bearing, # secret-bearing).

**`11-walker-gap`** — Quantify the SILENT-LOSS gap (class 1). Read `_walk_canonical`
(`xpath_walker.py`); enumerate EXACTLY the xpaths it yields, quoting each yield site
file:line. Read `classify()` in `netcanon/models/migration.py`; CONFIRM or correct
that an xpath neither walked nor declared defaults to `supported` (quote the branch).
Build your own sufficient leaf list from `intent.py` to compute the gap (you run
parallel to the census agent); flag uncertain leaves. GAP = leaves expressible but
NEVER walked → default `supported` → silent-loss candidates; list them all. For each
gap leaf, grep codec parse paths to see which codecs POPULATE it (separate real risk
from dead leaves). Catalogue the 5 existing partial guards: what slice each covers /
leaves open. Account for the #149 lesson: which `unsupported` paths are INTENTIONALLY
non-walkable (Tier-3 routing protocols) and must be exempt from any walk-everything
rule.

**`12-sanitizer-gap`** — Quantify the SANITIZER-BYPASS gap (class 2) AND the
over-redaction risk. Read `sanitize_intent` (`netcanon/tools/sanitize.py`) fully;
enumerate the EXACT set of fields it redacts (the allow-list), quoting each site
file:line; note the redaction primitives (redact_ipv4/ipv6, secret handling) and the
private/documentation-range PRESERVATION logic (what is deliberately kept). Build your
own IP/host-bearing + secret-bearing field list from `intent.py`; flag uncertainties.
GAP = IP/host/secret-bearing leaves the sanitizer NEVER touches → leak candidates;
classify each (a) realistically public/secret-bearing (true leak) vs (b) structurally
always-private/non-sensitive. CRITICAL over-redaction analysis of the user's proposed
blanket rule (redact any string field whose value parses as `ip_address()`): which
fields are FREE TEXT (description/name/domain_name/banner) that could falsely parse or
contain IP-like substrings and be mangled? Does a blanket rule break the deliberate
private/docs-IP preservation, or can it reuse the same preserve-private predicate?
Roughly what fraction of the real fixture corpus would change vs today (reason from
the census; you MAY sample fixtures READ-ONLY)? Conclude: which class-2 form is safest
(blanket / guard / typed-marker) and why.

### Phase 2 — Design (read ALL phase-1 reports first)

**`20-design-walker-guard`** — Design the durable class-1 fix. Compare (A) walker
auto-yields every leaf vs (B) a reflection-driven COMPLETENESS GUARD test that FAILS
when a model leaf is neither walked-and-declared nor in a documented exemption set.
Recommend one (or hybrid) with reasoning. Provide the EXACT shape: where the test
lives; how it reflects model leaves (pydantic `model_fields` recursion handling
list/nested + `from __future__ import annotations` string types); how it checks
'walked' (run `_walk_canonical` on a kitchen-sink intent, collect yields) and
'declared' (per-codec matrices); the self-justifying exemption design (each exemption
carries a reason; model it on #149's `_SYNTHETIC_NONWALKABLE`). QUANTIFY blast radius
to make the guard GREEN today: blind leaves to walk+declare across how many codecs;
estimated phase4 (`tests/unit/audit`) reclassifications; flag behavior-change vs
pure-declaration. Spell out PR sequencing; note regen-tool needs.

**`21-design-sanitizer-guard`** — Design the durable class-2 fix. Compare (A) blanket
`ip_address()` redaction, (B) reflection-driven completeness guard, (C)
typed-marker-driven enumeration. Recommend one (may differ from the walker
recommendation), grounded in the over-redaction analysis. Provide the EXACT shape: how
IP/secret-bearing fields are identified at test time (type hints / naming heuristic /
typed marker — coordinate with agent 22); redact-vs-exempt classification; exemption
mechanism; how it preserves the existing private/docs-IP behavior. Address
over-redaction head-on. If recommending a guard, SHOW it would have FAILED before #174
(the VGA leak). QUANTIFY: fields to add now; fixture-corpus diff if any runtime change;
test cost.

**`22-design-typed-marker`** — Evaluate fail-surfaced BY CONSTRUCTION: annotate
IP/host-bearing + secret-bearing canonical fields with a typed marker (e.g.
`Annotated[str, IPField()]` / pydantic `Field(json_schema_extra=...)` / a small
metadata class) so the walker AND sanitizer (AND the guards) can MECHANICALLY
enumerate the relevant leaves from the model itself — no hand-maintained list. Show
the exact annotation mechanism that survives pydantic v2 + `from __future__ import
annotations` (introspecting `model_fields[...].metadata` reliably). Assess: churn to
annotate; whether it SUBSUMES or complements the guard tests; maintenance ergonomics;
and HONESTLY whether it is over-engineering vs the lighter guard (B). Verdict: worth it
for class-2, class-1, both, or neither — and the minimal version capturing most value.

### Phase 3 — Review (read ALL phase-1 + phase-2 reports first; use the review schema)

**`30-review-correctness`** — Adversarial CORRECTNESS review: does the recommended fix
kill the CLASS, not today's instances? Decisive test: would the recommended class-1
guard FAIL if a dev adds a NEW unwalked leaf and forgets to walk/declare it? Would the
class-2 design FAIL if a dev adds a NEW IP-bearing field and forgets to redact it? Walk
both synthetic scenarios concretely; if either PASSES (misses the new field) → NO-GO
must-fix. Does the exemption mechanism merely RELOCATE the blind spot? Propose how to
make exemptions self-justifying / costly-to-abuse. Reconcile with the user's literal
goal ('fail-surfaced *defaults*'): is a CI guard faithful, or does the goal demand the
behavior-change/by-construction form? Take a position. Verdict + must_fixes.

**`31-review-pragmatism`** — Adversarial PRAGMATISM / over-engineering / maintenance
review. Is the recommended design the MINIMAL thing that closes the class, or
gold-plated? Flag over-engineering (typed-marker if a 30-line guard suffices).
Over-fire / false-positive risk: would the guard break on legitimate model evolution,
refactors, or the intentional exemptions (#149 Tier-3 non-walkable; sanitizer
private-IP preservation)? Would a blanket sanitizer rule mangle real fixtures?
Maintenance burden: who keeps the exemption list honest; friction on ordinary model
changes; is the failure message actionable? Blast-radius sanity-check: are the phase-2
churn estimates realistic? One PR or several? Anything to stage/defer? Verdict +
must_fixes.

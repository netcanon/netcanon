# 30 — Adversarial CORRECTNESS review: does the fix kill the CLASS?

**Agent:** `30-review-correctness` · Phase 3 (Review) · read-only
**Run:** 2026-06-24 · fail-surfaced-defaults · netcanon
**Scope:** Adversarially test the Phase-2 recommendations (`20-design-walker-guard`,
`21-design-sanitizer-guard`, `22-design-typed-marker`) on ONE question: **does the
recommended fix kill the recurring CLASS, or only today's named instances?** The
decisive tests are concrete synthetic-new-leaf scenarios. If a recommended guard
PASSES (i.e. fails to catch) a synthetic new unhandled field → NO-GO must-fix.
I independently re-verified every load-bearing source claim (citations in §8).

---

## 0. Verdict

**GO-WITH-FIXES.**

The recommended designs are structurally sound and DO kill the class for the
*common* failure mode (a new field added with an indicative shape, forgotten by
its author). I reproduced the decisive synthetic-new-leaf scenarios and the
recommended guards go RED in every one of the cases the five blind audits
actually hit. But the review surfaces **four correctness gaps**, two of them
blockers, where a recommended guard would silently PASS a synthetic new leaf —
i.e. the blind spot is *relocated*, not closed. They are all fixable with small,
additive changes, hence GO-WITH-FIXES rather than NO-GO.

Headline findings (detail + decisive traces below):

- **Class-1 walker guard (agent 20, design B): KILLS the class — with one
  blocker.** The recursive `_model_leaves()` correctly catches a new *scalar*
  leaf added to any nested model (the audit-named pattern). BUT a dev who adds a
  whole **new nested model** (e.g. `CanonicalQoSPolicy`) and hangs it off
  `CanonicalIntent` via a `list[...]` field is NOT caught: the new container
  field is a nested-model field (not a scalar leaf), `_reachable_canonical_models`
  finds the new model, its scalar leaves get enumerated and *would* fail —
  **good** — UNLESS the new model is unreachable because the container field
  itself escapes enumeration. The actual blocker is narrower and concrete (MF-1,
  §2.3): the `_LEAF_TO_WALKER_XPATHS` *spelling map* is a SECOND hand-maintained
  subset, and agent 20's "you can't forget both" claim has a hole when a leaf is
  added to the **exemption** set by a copy-paste author. I show the exact hole and
  the fix.

- **Class-2 sanitizer guard (agent 21, design B, naming-regex form): DOES NOT
  kill the class.** The decisive synthetic-new-leaf test — a dev adds
  `CanonicalBGPNeighbor.peer: str = ""` holding a neighbor IP — **PASSES the
  guard** (the name `peer` matches neither `_IP_HOST_NAME_RE` nor `_MAC_NAME_RE`,
  so it is never even a candidate, so it is never flagged). This is the literal
  covered-subset disease one level up, exactly as agent 22 §4.2 warned and agent
  21 §6 conceded as its "residual honest gap." **For the class-2 goal as stated by
  the user ("a NEW IP-bearing field… forgets to redact it → must fail"), the
  naming-regex guard is NOT faithful.** This is MF-2, a blocker — but the fix is
  agent 22's marker + a cheap *unmarked-string meta-guard*, which I show closes it.

- **The typed marker (agent 22) is the only form that is faithful to the user's
  literal goal for class-2** — but ONLY if paired with the meta-guard agent 22
  itself flagged as its "Achilles heel" (§22.5/§22.8). The marker alone has the
  identical blind spot as the regex (a forgotten marker on a deceptively-named
  field). My position (§4): adopt the marker for class-2 AND ship the
  `_NON_SENSITIVE_TEXT` meta-guard; that combination is the *only* recommended
  configuration that actually fails-red on the `peer:str` scenario. Without the
  meta-guard, neither the regex nor the marker kills the class.

- **The exemption mechanism does NOT merely relocate the blind spot — for the
  walker guard.** The #149 self-justifying precedent + `test_no_stale_walk_exemptions`
  + reason strings make exemption a *visible, reviewable, diff-bearing* act, which
  is strictly better than today's invisible omission. **For the sanitizer regex
  guard the exemption set IS a near-non-issue (2 entries) — but the regex itself
  is the relocation** (the blind spot moved from "the allow-list" to "the regex
  token list"). That distinction is the crux of MF-2.

- **Reconciling with the user's literal goal ("fail-surfaced *defaults*"):** a CI
  guard IS a faithful realization of "defaults to flagged" — *provided* the guard's
  trigger is the field's mere existence (every leaf / every string field), NOT a
  name pattern. Agent 20's walker guard triggers on existence (every `_model_leaves()`
  entry) → faithful. Agent 21's regex guard triggers on a name match → NOT faithful
  (a leaf with a non-matching name never triggers). The marker+meta-guard triggers
  on existence (every string field is marked-or-exempt) → faithful. **Take-away: the
  faithful designs are the ones whose default branch is "unknown field → RED," and
  the regex form fails that test.** §5.

---

## 1. The bar I held each design to

The seed's decisive test (Phase-3 brief): *"Would the recommended class-1 guard
FAIL if a dev adds a NEW unwalked leaf and forgets to walk/declare it? Would the
class-2 design FAIL if a dev adds a NEW IP-bearing field and forgets to redact
it? Walk both synthetic scenarios concretely; if either PASSES (misses the new
field) → NO-GO must-fix."*

I operationalised this as four synthetic scenarios — the same *shapes* the five
blind audits actually exploited (switchport / static-route subfield / VXLAN /
VLAN-port / VLAN-SVI for class-1; IPv4→IPv6→RD/RT→VGA for class-2) plus the
*next* shape an adversary would reach for:

| # | Scenario | Class | The shape the audits exploited |
|---|---|---|---|
| S1 | New **scalar** leaf on an existing nested model: `CanonicalVRRPGroup.tracking_weight: int = 0` | 1 | exactly the VRRP/DHCP-subfield pattern (#172/#175 shape) |
| S2 | New **whole nested model**: `CanonicalQoSPolicy` hung off `CanonicalIntent.qos_policies: list[...]` | 1 | the "new feature surface" pattern (the way VXLAN/EVPN first landed) |
| S3 | New **indicatively-named** IP field: `CanonicalThing.mgmt_ip: str = ""` | 2 | the VGA #174 shape (name ends `_address`/`_ip`) |
| S4 | New **deceptively-named** IP field: `CanonicalBGPNeighbor.peer: str = ""` (a neighbor IP) | 2 | the *next* audit's shape — a real IP behind a non-IP-looking name |

A design that goes RED on S1–S4 kills the class. A design that PASSES (stays
green) on any of them relocates the blind spot. The results:

| Design | S1 | S2 | S3 | S4 |
|---|---|---|---|---|
| 20 walker guard (B, recursive) | **RED** ✓ | **RED** ✓ (with MF-3 caveat) | n/a | n/a |
| 21 sanitizer guard (B, naming-regex) | n/a | n/a | **RED** ✓ | **GREEN** ✗ (MF-2 blocker) |
| 22 marker (alone) | n/a | n/a | **GREEN** ✗ (forgot marker) | **GREEN** ✗ |
| 22 marker + `_NON_SENSITIVE_TEXT` meta-guard | n/a | n/a | **RED** ✓ | **RED** ✓ |

The decisive rows: **S4 is GREEN (a miss) for the recommended sanitizer regex
guard AND for the marker-alone** — that is the relocation. Only the
marker+meta-guard combination catches S4. Detail below.

---

## 2. Class-1 (walker guard, agent 20) — does it kill the class?

### 2.1 S1 (new scalar leaf on a nested model) — RED ✓ (the class kill works)

Trace, against the *actual* mechanism I verified:

1. A dev adds `CanonicalVRRPGroup.tracking_weight: int = 0` and forgets the walker
   yield + the per-codec declaration + the `_LEAF_TO_WALKER_XPATHS` row + the
   `_WALK_EXEMPT` row.
2. `_reachable_canonical_models(CanonicalIntent)` reaches `CanonicalVRRPGroup`
   (it is mounted via `CanonicalInterface.vrrp_groups: list[CanonicalVRRPGroup]`;
   the engine descends through `list[...]` — verified at
   `test_sanitize.py:662-685`, the recursion is real and pydantic resolves the
   future-annotation string to the live class).
3. `_model_leaves()` yields `("CanonicalVRRPGroup", "tracking_weight")` because
   `int ∈ _SCALAR` and the field has no nested model.
4. It is in neither `_LEAF_TO_WALKER_XPATHS` nor `_WALK_EXEMPT` →
   `test_every_model_leaf_is_walked_or_exempt` appends
   `"CanonicalVRRPGroup.tracking_weight (no walker-xpath mapping)"` and **FAILS**.

**This is the precise hole the two existing guards leave open and that agent 20's
recursion fills.** I confirmed both existing guards stop at top level:
`test_marker_dict_covers_every_data_bearing_field` reflects
`set(CanonicalIntent.model_fields)` (`test_registry_capability_honesty.py:534`) —
top level only, no recursion; G5's `_FIELD_TO_EXPECTED_XPATH`
(`test_walk_canonical_coverage.py:165-184`) is a hand-listed 18-entry top-level
dict. **Neither would notice `CanonicalVRRPGroup.tracking_weight`.** Agent 20's
recursive `_model_leaves()` is the genuine fix. **S1 = class killed.** ✓

### 2.2 S2 (new whole nested model) — RED ✓ but with a real caveat (MF-3)

A dev adds a brand-new `CanonicalQoSPolicy(BaseModel)` with scalar fields
(`name`, `dscp`, `rate_limit`) and hangs it off
`CanonicalIntent.qos_policies: list[CanonicalQoSPolicy] = Field(default_factory=list)`.

Trace:
1. `_reachable_canonical_models(CanonicalIntent)` iterates `CanonicalIntent`'s
   fields; for `qos_policies`, `_flatten_annotation(list[CanonicalQoSPolicy])`
   yields `CanonicalQoSPolicy` (a `BaseModel` subclass) → it is added to the
   reachable set and recursed. **Confirmed**: the engine descends into new nested
   models automatically (`test_sanitize.py:681-684`).
2. `_model_leaves()` yields `("CanonicalQoSPolicy", "name")`, `(…, "dscp")`,
   `(…, "rate_limit")` — none mapped, none exempt → **FAILS** naming all three.

**So S2 is caught.** ✓ — *provided* the new field's annotation is a form
`_flatten_annotation` can see through. **MF-3 (major, not a blocker):** the
recursion's coverage of the *container field itself* depends on
`_flatten_annotation`/`get_args` handling the annotation. For `list[X]`,
`dict[str, X]`, `X | None` it does (verified). But three real shapes in this
codebase would be missed by the *leaf* enumerator (not the model-reachability):
- a `dict[str, list[list[str]]]` field (`group_content` is exactly this) — the
  `_model_leaves()` `has_scalar`/`has_nested_model` branches both go false for a
  pure-dict, and agent 20 routes it to the `elif not has_scalar and not
  has_nested_model: yield` arm → it becomes a leaf that must be exempted. Good,
  but agent 20 must verify the dict branch actually yields (the sketch's `elif`
  is correct but the `_SCALAR` membership test on a `dict` type needs care — a
  bare `dict` annotation has no args, so `_flatten_annotation` yields `dict`
  itself, which is not in `_SCALAR` and not a `BaseModel` → the `elif` fires →
  yielded → exemption catches it. OK, but this is subtle enough to need a unit
  test of `_model_leaves()` itself, see MF-3 fix.)
- a `Literal["a","b"]` field (the codebase uses `Literal` for codec metadata) —
  `typing.get_args(Literal["a","b"])` returns `("a","b")` (the *values*, not
  types), so `_flatten_annotation` yields the strings `"a"`,`"b"`, neither in
  `_SCALAR` nor a `BaseModel` → the leaf is routed to the `elif` "dict-like" arm
  and yielded-for-exemption. That is *accidentally* correct (it gets flagged) but
  for the *wrong reason*, and a `Literal[1,2]` int-enum would behave differently.
  The intent model today has no `Literal` field on a walked surface, but the
  guard's `_model_leaves()` MUST be unit-tested against a `Literal` to avoid a
  silent mis-classification when one is added.

**MF-3 fix:** agent 20's `_model_leaves()` needs its own ≥3-case unit test
(scalar / list[scalar] / nested-model / dict / Literal) asserting the exact
`(Class,field)` set it yields on a tiny synthetic model, so the enumerator's
own correctness is guarded. Without it, the guard could silently *under-enumerate*
(miss a leaf) and the whole class-1 fix would have a hole at its foundation. This
is the "guard the guard's enumerator" test, distinct from agent 20's three
"guard the guard" tests (which check staleness/disjointness, not enumeration
correctness).

### 2.3 MF-1 (blocker): the `_LEAF_TO_WALKER_XPATHS` map is a second hand-maintained subset — and agent 20's "can't forget both" claim has a hole

Agent 20 §3.4 design-note asserts: *"The map is NOT a second blind spot because
the guard fails on any leaf missing from BOTH the map and the exemption set."*
That is true for a leaf missing from both. **But it does not cover the case where
a copy-paste author adds the leaf to `_WALK_EXEMPT` with a plausible-but-wrong
reason instead of walking it.** Concretely the S1 author, faced with a red
`test_every_model_leaf_is_walked_or_exempt`, has TWO ways to green it:
(a) walk it + declare it + map it (correct), or (b) drop one line into
`_WALK_EXEMPT`: `("CanonicalVRRPGroup","tracking_weight"): "minor, low stakes"`.
Path (b) is *easier* and turns the guard green while the field silently classifies
`supported` forever. **The guard does not distinguish a legitimate exemption from
a lazy one — it relies entirely on PR review catching the bogus reason string.**

This is the honest residual agent 20 acknowledged (§4 "social-process risk"), but
I rate it a **blocker for the class-kill claim** because the whole run exists to
stop relying on a human noticing. The mitigations as designed are insufficient on
their own:
- `test_no_stale_walk_exemptions` only checks the leaf still *exists* — a lazy
  exemption on a real field passes it.
- The `KNOWN-GAP:` ratchet (§3.7) only constrains the `KNOWN-GAP`-prefixed
  subset; a lazy exemption with reason `"minor"` is not `KNOWN-GAP`-prefixed so
  the ratchet never sees it.

**MF-1 fix (cheap, structural — makes the exemption costly to abuse):** require
every `_WALK_EXEMPT` entry to match one of a small set of **structured reason
codes**, not free text, e.g. `reason: Literal["METADATA","TRANSFORM_HINT",
"DISCRIMINATOR_TRAVELS","ENVELOPE_AUDIT_BACKSTOPPED","KNOWN_GAP_PR2"]` plus a
free-text note. A test asserts (i) every reason is one of the codes and (ii) the
*count per code* is ratcheted (not just `KNOWN_GAP`). Then "I'll just exempt it"
forces the author to pick a category that *visibly does not fit* a real
config-bearing leaf — a reviewer challenging `DISCRIMINATOR_TRAVELS` on
`tracking_weight` is a far sharper signal than challenging free-text `"minor"`.
This converts the social-process risk into a structural one: there is no honest
reason-code for "I didn't feel like walking this," so the lazy path has no green
door. (This is the same move that makes #149's `_is_legitimate_nonwalkable`
robust — it is *predicates*, not free text. Agent 20's free-text reason strings
are weaker than the #149 precedent it cites.)

### 2.4 Does the walker exemption set relocate the blind spot? — NO (net positive)

Setting MF-1 aside (which hardens it further), the walker exemption is genuinely
better than the status quo, for the reason agent 20 §4 gives and I verified:
**today, forgetting a leaf is invisible — no diff, no red CI, silent loss. With
the guard, forgetting a leaf is a red CI naming the exact `(Class,field)`; the
ONLY way to green it is a *diff-bearing* decision (walk-or-exempt) that appears in
PR review.** That asymmetry (invisible omission → visible decision) is the class
kill even before MF-1 hardening. The #149 precedent
(`test_registry_capability_honesty.py:323-346`, `_SYNTHETIC_NONWALKABLE` +
`_is_legitimate_nonwalkable`) is a real, shipped, self-justifying-exemption
mechanism in this exact codebase, so the pattern is proven. **Verdict for
class-1: the guard kills the class; MF-1 + MF-3 harden it from "kills it modulo a
lazy reviewer" to "kills it structurally."**

---

## 3. Class-2 (sanitizer) — the regex guard does NOT kill the class

### 3.1 S3 (indicatively-named new IP field) — RED ✓

Agent 21 §4's #174-regression trace is correct and I re-verified the mechanism. A
new `CanonicalThing.mgmt_ip: str = ""` matches `_IP_HOST_NAME_RE` (ends `_ip`),
is neither registered nor exempt → `test_reverse_no_unregistered_ip_field` FAILS.
The pre-#174 `virtual_gateway_address` trace is sound (name ends `_address`). **S3
= caught.** ✓ The regex guard does kill the *named-instance* class — every audit
instance so far (ip, virtual_gateway_address, RD/RT, …) had an indicative name.

### 3.2 S4 (deceptively-named new IP field) — GREEN ✗ — MF-2, the blocker

This is the decisive test and the recommended class-2 design **fails it.**

Trace against agent 21's `test_reverse_no_unregistered_ip_field`
(`21-design-sanitizer-guard.md` §2.4):
1. A dev adds `CanonicalBGPNeighbor.peer: str = ""` (holds the neighbor's IP) and
   forgets to redact it.
2. `_scan_named_fields(_IP_HOST_NAME_RE)` iterates the model. For field `peer`:
   `_IP_HOST_NAME_RE.search("peer")` → **no match** (`peer` is not in the token
   list `ip|host|gateway|network|destination|prefix|address|…`).
3. So `("CanonicalBGPNeighbor","peer")` is **never added to `found`.**
4. `found - _REGISTERED_IP_FIELDS - _IP_NAME_EXEMPT` does not contain it (it was
   never a candidate). `unregistered` is empty for it. **Test PASSES.** The IP
   leaks verbatim into every shared config / bug report.

**The guard is structurally blind to any IP-bearing field whose name the regex
does not anticipate.** This is the literal covered-subset disease — the blind spot
moved from "the 41-site allow-list" to "the `_IP_HOST_NAME_RE` token list," which
is *also* a hand-maintained subset. The next blind audit finds `peer` /
`endpoint` / `nexthop` / `vtep` / `bfd_source` and we are back to whack-a-mole.
Agent 21 §6.4 concedes this exactly ("the blind spot would only relocate if a
future dev added an IP-bearing field with a deceptive name… that is the one
residual"); agent 22 §4.2 names the same hole as the marker's core argument. **I
escalate it from "residual" to BLOCKER** because the seed's decisive test is
literally "a NEW IP-bearing field … forgets to redact it → must FAIL," and S4 is
the cleanest instance of it. A design that passes S4 has not killed the class; it
has renamed the subset.

> **Why this matters more for class-2 than class-1.** Class-1's `_model_leaves()`
> triggers on a leaf's *existence* (every scalar leaf is enumerated, regardless of
> name) — so a deceptively-named scalar leaf is still enumerated and still must be
> walked-or-exempt. Class-2's regex triggers on a leaf's *name* — so a
> deceptively-named leaf is never even a candidate. **The two recommended guards
> are not symmetric in faithfulness: the walker guard's default branch is
> "unknown leaf → RED"; the sanitizer regex guard's default branch is "unknown
> name → IGNORED."** That asymmetry is the whole finding.

### 3.3 MF-2 fix: the marker (agent 22) + an unmarked-string meta-guard is the only S4-faithful form

Agent 22 already did the work and reached the right shape, then under-sold it.
The fix for MF-2 is exactly agent 22 §8.1 "Risk 1" — but it must be promoted from
"risk to watch" to **required component**:

1. Adopt the `Sensitive(kind=...)` marker (agent 22 §2) on the IP/host/mac/secret
   leaves. The marker rides the field, so it is name-independent.
2. Ship the **unmarked-string meta-guard** (agent 22 §8 rec): *every* `str` /
   `list[str]` leaf reachable from `CanonicalIntent` is EITHER `Sensitive`-marked
   OR in a small, reviewed `_NON_SENSITIVE_TEXT` exemption set. Trace S4 against
   it: `CanonicalBGPNeighbor.peer: str` is unmarked AND not in `_NON_SENSITIVE_TEXT`
   → **meta-guard FAILS** naming `("CanonicalBGPNeighbor","peer")`, forcing the
   author to make a binary decision (mark sensitive, or justify non-sensitive). **S4
   = caught.** ✓

This is the ONLY recommended configuration that goes RED on S4. The marker *alone*
(without the meta-guard) PASSES S4 (a forgotten marker is invisible — agent 22
§5's own "Achilles heel"). The regex guard PASSES S4. So:

> **MF-2 (blocker): the class-2 fix MUST be marker + unmarked-string meta-guard,
> NOT the naming-regex guard (agent 21 form B as written) and NOT the marker
> alone.** Only the combination triggers on field *existence* (the faithful
> default), which is what "fail-surfaced default" means.

### 3.4 Does the meta-guard just relocate the blind spot again?

This is the fair counter-question (agent 22 §5 raises it honestly): the
`_NON_SENSITIVE_TEXT` set is itself a hand-maintained subset, so haven't we just
moved the blind spot to *it*? **No — and the asymmetry is decisive:**

- The dangerous direction is *under-redaction* (a sensitive field leaks). For the
  meta-guard, leaking requires a sensitive field to be (a) unmarked AND (b)
  wrongly placed in `_NON_SENSITIVE_TEXT`. That is a *diff-bearing, reviewable*
  act with a name attached — `("CanonicalBGPNeighbor","peer"): "non-sensitive"`
  is a claim a reviewer rejects (a BGP peer IP is obviously sensitive). Contrast
  the regex: a leak requires only *forgetting* — no diff, no entry, invisible.
- The meta-guard's failure mode is *over-flagging* (a genuinely non-sensitive new
  string field turns CI red until someone adds it to `_NON_SENSITIVE_TEXT`). That
  is a safe failure: it annoys a contributor, it does not leak. **Over-flag-safe
  beats under-redact-unsafe.** The user's own framing ("fail-surfaced") explicitly
  prefers the noisy-but-safe default.
- The `_NON_SENSITIVE_TEXT` set is *closed and enumerable today* (agent 10/12
  listed them: `name`, `description`, `mode`, `interface_type`, `timezone`,
  `tunnel_type`, `dhcp_client_v6`, `scope`, `kind`, `default_name`,
  `instance_type`, `source_interface`, `interface`, …). New free-text fields are
  rare; each is one reviewed line.

So the meta-guard relocates the blind spot from "invisible omission of a redaction"
(unsafe, silent) to "visible mis-classification of a string field" (safe, noisy,
reviewable). That is the relocation we *want* — it is the same move that makes the
walker guard faithful (trigger on existence, fail safe).

### 3.5 The marker's own residual (honest) — and why it's acceptable

Agent 22 §5 is right that the marker+meta-guard is not *perfectly* self-enforcing:
a dev could add `peer: str`, see the meta-guard go red, and *lazily* drop it into
`_NON_SENSITIVE_TEXT` with reason "internal." This is the class-2 twin of MF-1.
**Same fix applies: structured reason codes on `_NON_SENSITIVE_TEXT`** (e.g.
`Literal["ENUM_KEYWORD","OPERATOR_FREE_TEXT","IFACE_NAME","METADATA"]`) so there
is no honest code for "an IP I didn't want to redact." A BGP peer IP fits none of
those codes, so the lazy path again has no green door. With that, the class-2 fix
is structurally faithful to S4, not merely socially.

---

## 4. The two reviewers' designs disagree on class-2 — I take a position

Agent 21 recommends the regex guard and treats the marker as deferrable; agent 22
recommends the marker and concedes it is a "close call." **My adversarial finding
forces the tie-break: the regex guard fails the seed's decisive test (S4), so it
cannot be the recommended class-2 form.** The position:

- **Class-2: adopt the typed marker (agent 22) + the unmarked-string meta-guard +
  structured exemption reason codes.** This is the only form that goes RED on a
  deceptively-named new IP field. Agent 21's guard *test infrastructure* survives
  (the forward sentinel half, the reflection engine, the would-have-caught-#174
  argument) — it just reflects *markers* instead of *names*, exactly as agent 21
  §8.1 itself offers as the alternative branch. So this is not "reject agent 21";
  it is "take agent 21's guard machinery and re-base it onto agent 22's marker,
  and add the meta-guard." The two designs *compose*.

- **Class-1: keep agent 20's walker guard (do NOT use a marker).** Agent 22 §6 is
  correct that a "walkable" marker is the wrong tool (inverted density, no xpath
  spelling, phase4 coupling). Agent 20's `_model_leaves()` already triggers on
  existence, so it is already faithful to S1/S2 — it does NOT have the regex's S4
  problem, because it never used names. Apply MF-1 (structured reason codes) +
  MF-3 (enumerator unit test) to harden it.

This split (marker for class-2, structural-leaf-enumeration for class-1) is
*more* than each Phase-2 agent individually recommended, but it is the minimal
configuration that survives all four synthetic scenarios. Agent 22's own verdict
("class-2 only" for the marker) plus agent 20's walker guard plus the two
meta-guards = the coherent whole.

---

## 5. Reconciling with the user's literal goal: is a CI guard faithful?

The user's goal, verbatim from the seed: *"fail-surfaced defaults — the walker
yields EVERY leaf (or the codec must declare it); the sanitizer redacts on
`ip_address()` of ANY IP-typed field, not an allow-list."*

**My position: a CI guard IS a faithful realization of "fail-surfaced defaults" —
but ONLY when the guard's trigger is field existence, not a heuristic.** The
parse of "fail-surfaced default": *the default state of a newly-added field is
"flagged/surfaced," not "silently fine."* A guard delivers that iff adding the
field (with no other action) flips CI red. Test each design against that literal
criterion:

| Design | Adding a new field, no other action → ? | Faithful? |
|---|---|---|
| Walker guard (20) | new leaf ∉ map ∉ exempt → **RED** | **Yes** — triggers on existence |
| Sanitizer regex (21) | new field, name not in regex → **GREEN** | **No** — triggers on name |
| Marker alone (22) | new field, no marker → **GREEN** (meta-guard absent) | **No** — triggers on marker-presence |
| Marker + meta-guard (22 §8) | new string field, unmarked, ∉ `_NON_SENSITIVE_TEXT` → **RED** | **Yes** — triggers on existence |
| Runtime blanket `ip_address()` (A) | new IP field → silently redacted; new MAC/secret → silently leaked | **No** — no human surfaced |

So the user's literal goal is satisfiable by a CI guard, and the seed's stated
preference ("convert the blind spot into a CI failure over a risky runtime
behavior change") is honored — **but the faithful CI forms are specifically the
existence-triggered ones (walker `_model_leaves`, marker+meta-guard), and the
recommended-by-agent-21 name-triggered form is NOT faithful.** The user's
intuition that pushed toward "ANY IP-typed field, not an allow-list" was
*correct*: the allow-list (and its regex cousin) is the disease; the
existence-triggered guard is the cure. The runtime `ip_address()` form the user
literally proposed is the wrong mechanism (agent 12/21/22 all show it is
insufficient + unsafe), but the *instinct* — "ANY field, not a curated subset" —
is exactly what the marker+meta-guard delivers at test time. **The goal does NOT
demand the runtime behavior-change form; it demands the existence-triggered
default, which the guard provides.** So: faithful, with the MF-2 correction.

---

## 6. Secondary correctness checks (non-blocking but worth landing)

- **C-1 (minor): the walker guard's `_WALKABLE` is built from `_maximal_intent()`,
  which does NOT populate the HIGH gap leaves it claims to detect.** I verified
  `_maximal_intent` (`test_registry_capability_honesty.py:132-221`) sets VRRP
  `group_id` + `virtual_ips`/`virtual_mac`/`track_interfaces` but NOT `mode`/
  `priority`/`preempt`/`advertisement_interval`/`authentication`; sets SNMPv3
  `group`/`auth_protocol`/`priv_protocol`/`priv_passphrase` but the walker yields
  none of them; sets `routing_instances.instance_type="vrf"` (the *default*).
  **This is actually fine for agent 20's guard** — the guard computes "is this
  leaf's xpath in `_WALKABLE`," and these leaves' xpaths are correctly *absent*
  from `_WALKABLE` (the walker never emits them), so the guard correctly flags
  them as un-walked. But it means PR-2's walk-expansion MUST also extend
  `_maximal_intent()` to populate the newly-walked sub-fields with NON-DEFAULT
  values, or the new yields fire vacuously and the reverse-parity guards
  (`test_declared_supported_is_walkable`) could pass without exercising the new
  paths. Flag for the main thread; it's a regen-time detail agent 20 §5.2 gestures
  at but doesn't make explicit.

- **C-2 (minor): `instance_type` default-value trap.** `instance_type="vrf"` is
  the default; if PR-2 walks `/routing-instances/instance/instance-type` only
  `when populated` (truthy), it is ALWAYS truthy (`"vrf"` is truthy) so it always
  walks — unlike `mode="vrrp"` default which is also truthy. Contrast `metric=0`
  which is falsy and correctly skipped. Agent 20 should confirm each HIGH leaf's
  walk-guard truthiness matches the intended "walk only on loss" semantics, or the
  live report gains noise (a `vrf` instance_type that every codec round-trips
  cleanly would still be walked and classified — harmless but not the lossy-only
  intent of the existing VRRP/static-route conditional yields at
  `xpath_walker.py:153-196`).

- **C-3 (confirm): the marker's `from __future__ import annotations` survival.**
  Agent 22 §2.2 claims a prototype confirmed `model_fields[name].metadata` is
  readable under future-annotations. I could not re-run the prototype (read-only),
  but I confirmed the *adjacent* claim it rests on: the existing secret guard does
  `str in _flatten_annotation(fld.annotation)` (`test_sanitize.py:754`) and passes
  in CI, which proves `fld.annotation` is the *resolved* type object (not the raw
  string) under this repo's future-annotations + pydantic 2.x. Marker `.metadata`
  retrieval is the same resolution path. **Low risk, but the main thread must run
  the marker guard under the py3.11 CI leg** (agent 22 §8.4) — `model_fields[...]
  .metadata` semantics are pydantic-version-sensitive and local is py3.14.

- **C-4 (no-op, just confirming agent 21/20's phase4 claim): a pure guard PR is
  zero phase4 churn.** I confirmed `classify()` is the only consumer of walker
  output for the live report (`migration.py:221-228` default-to-supported;
  `migration_validate.py:80-87` walker-is-sole-input) and that phase4 reads
  matrices+YAMLs not the walker. So PR-1 (walker guard, no new yields) and the
  marker/meta-guard PRs (sanitizer side, off the migration-validate path entirely)
  are genuinely zero-phase4. The phase4 risk is real ONLY for agent 20's PR-2
  walk-expansion, which agent 20 correctly stages separately. **No correctness
  issue; the staging is right.**

---

## 7. Summary of must-fixes

| id | severity | target | issue | fix |
|---|---|---|---|---|
| MF-2 | **blocker** | class-2 design (agents 21/22 synthesis) | The recommended naming-regex sanitizer guard PASSES (misses) a deceptively-named new IP field (`peer: str`) — S4. It relocates the blind spot from the allow-list to the regex token list; it does not kill the class. | Adopt the typed marker (agent 22) AND ship the unmarked-string meta-guard (`every str/list[str] leaf is Sensitive-marked OR in `_NON_SENSITIVE_TEXT``). This is the only form that triggers on field existence (the faithful default). Re-base agent 21's guard machinery (forward sentinel, #174 regression argument) onto the marker. |
| MF-1 | **blocker** | class-1 walker guard (agent 20) | The `_WALK_EXEMPT` free-text reason strings let a lazy author green a forgotten leaf by exempting it with a plausible-but-wrong reason; relies on a reviewer catching free text. Same hole in class-2's `_NON_SENSITIVE_TEXT`. | Replace free-text reasons with a small `Literal[...]` set of structured reason codes (METADATA / TRANSFORM_HINT / DISCRIMINATOR_TRAVELS / ENVELOPE_AUDIT_BACKSTOPPED / KNOWN_GAP_PR2), ratchet the count per code, and apply the same to the class-2 meta-guard exemptions. No honest code fits "an IP/leaf I didn't want to handle" → the lazy path has no green door. |
| MF-3 | major | class-1 walker guard (agent 20) | `_model_leaves()` (the enumerator the whole class-1 fix rests on) is itself untested; its dict/`Literal`/union branches could silently UNDER-enumerate (miss a leaf), reopening the gap at the foundation. | Add a unit test of `_model_leaves()` against a tiny synthetic model covering scalar / list[scalar] / nested-model / dict / `Literal`, asserting the exact `(Class,field)` set. Guards the enumerator's own correctness. |
| MF-4 | minor | class-1 PR-2 (agent 20) | If PR-2 walks the HIGH sub-leaves but `_maximal_intent()` leaves them at default/empty, the new yields fire vacuously and reverse-parity passes without exercising them (C-1); and default-truthy leaves like `instance_type="vrf"` would walk-always rather than walk-on-loss (C-2). | PR-2 must extend `_maximal_intent()` to populate each newly-walked sub-field with a non-default value, and confirm each new walk-guard's truthiness matches walk-only-on-loss intent. |

(MF-1 and MF-2 are both blockers for the *class-kill claim*; the underlying
guards are still net-positive and shippable, so the overall verdict is
GO-WITH-FIXES, not NO-GO. The fixes are additive and small.)

---

## 8. Independent verification log (claims I re-checked at source)

- **Default-to-supported CONFIRMED** — `netcanon/models/migration.py:221-228`:
  `for up in self.unsupported … for lp in self.lossy … return "supported"`. Exact
  string match per docstring `:209-219`. (Agents 11/20's central premise.) ✓
- **Walker is sole live-report input** — `migration_validate.py:80-87` iterates
  `_enumerate_xpaths` → `source.iter_xpaths` → `_walk_canonical`; an unwalked leaf
  never reaches `classify()`. ✓
- **Both existing forward-coverage guards are TOP-LEVEL ONLY** —
  `test_marker_dict_covers_every_data_bearing_field` reflects
  `set(CanonicalIntent.model_fields)` (`test_registry_capability_honesty.py:534`),
  no recursion; G5 `_FIELD_TO_EXPECTED_XPATH` is an 18-entry hand-list
  (`test_walk_canonical_coverage.py:165-184`). Agent 20's "must recurse" claim is
  correct — the gap is real. ✓
- **Reflection engine exists + is future-annotations-proven** —
  `_flatten_annotation` + `_reachable_canonical_models` at `test_sanitize.py:662-685`;
  consumed by the passing `test_reverse_no_unregistered_secret_field` (`:743-767`)
  which does `str in _flatten_annotation(fld.annotation)` — proving `.annotation`
  resolves to the live type under this repo's `from __future__ import annotations`
  + pydantic 2.x. ✓ (de-risks both the walker guard recursion and the marker
  retrieval.)
- **#149 self-justifying-exemption precedent is real + predicate-based** —
  `_SYNTHETIC_NONWALKABLE` (`test_registry_capability_honesty.py:323-330`) +
  `_is_legitimate_nonwalkable` (`:333-346`) uses structural *predicates*
  (top-segment, `/routing/` not-static-route, whole-field markers), NOT free text.
  This is why MF-1 (agent 20's free-text reasons are *weaker* than the precedent
  it cites) is well-founded. ✓
- **`_maximal_intent()` does NOT populate the HIGH gap sub-leaves** (VRRP
  mode/priority/preempt/adv-int/auth; SNMPv3 group/auth-proto/priv-proto/
  priv-passphrase) — `test_registry_capability_honesty.py:167-204`. Confirms C-1
  and that `_WALKABLE` correctly lacks those xpaths (the guard's gap-detection is
  sound). ✓
- **VRRP walker conditional yields** — `xpath_walker.py:146-158`: group anchor
  unconditional; `virtual-ips` only `len>1`; `virtual-mac`/`track` only when
  populated; mode/priority/preempt/adv-int/auth NEVER. ✓ (the densest class-1
  gap, agent 11 §3.4.) ✓
- **Existing secret registry** — `_REGISTERED_SECRET_FIELDS` (6 entries) +
  `_SECRET_NAME_RE` (`test_sanitize.py:646-659`): the regex-form guard the marker
  would re-base. Confirms agent 21/22's "extend this" is accurate and that
  `engine_id` is redacted-but-not-secret-NAMED (so the regex misses it — the same
  S4-class hole inside the *existing* guard, reinforcing MF-2). ✓

---

## 9. Bottom line for synthesis

- **Class-1:** agent 20's recursive completeness guard KILLS the class for the
  audit-named pattern (new scalar leaf, new nested model). Land PR-1 as designed,
  PLUS MF-1 (structured reason codes) + MF-3 (enumerator unit test). PR-2
  walk-expansion is correctly staged; add MF-4. Zero phase4 for PR-1 confirmed.
- **Class-2:** the recommended naming-regex guard (agent 21 form B as written)
  does NOT kill the class — it fails S4 (deceptively-named IP field). The fix is
  MF-2: adopt agent 22's marker + an unmarked-string meta-guard + structured
  exemption reason codes (MF-1's twin). This is the only S4-faithful form and the
  truest realization of the user's "fail-surfaced default" goal. Zero phase4
  (sanitizer is off the migration-validate path) confirmed.
- **Faithfulness to the user's literal goal:** a CI guard is faithful iff it
  triggers on field *existence*, not a name heuristic. The walker `_model_leaves`
  guard and the marker+meta-guard both qualify; the regex guard does not. The
  user's "ANY field, not an allow-list" instinct was right — implement it at test
  time via existence-triggered guards, not at runtime via blanket `ip_address()`.

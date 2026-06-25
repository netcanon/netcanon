# 31 — Adversarial PRAGMATISM / over-engineering / maintenance review

**Agent:** `31-review-pragmatism` · Phase 3 (Review) · read-only
**Run:** 2026-06-24 · fail-surfaced-defaults · netcanon
**Scope:** Is the recommended design the MINIMAL thing that closes the class, or
gold-plated? Over-fire / false-positive risk on legitimate model evolution and the
intentional exemptions (#149 Tier-3, sanitizer private-IP preservation). Maintenance
burden: who keeps the exemption list honest, friction on ordinary model changes, is
the failure message actionable. Blast-radius sanity-check: are the phase-2 churn
estimates realistic? One PR or several? What to stage/defer.

I verified the load-bearing structural claims against the live tree (not just the
peer reports): `test_registry_capability_honesty.py:323-346` (#149 exemption),
`:527-541` (the top-level-only marker check), `:225` (`_WALKABLE` frozenset),
`tests/unit/tools/test_sanitize.py:646-767` (the secret guard + reflection engine),
`tests/unit/migration/codecs/cisco_iosxe_cli/test_walk_canonical_coverage.py:165-208`
(the per-codec G5 floor). All six peer reports are internally consistent with the
code. My critique is therefore about *proportion and maintenance*, not factual error.

---

## 0. Verdict + headline

**GO-WITH-FIXES.** The recommended spine is sound and genuinely minimal *if trimmed*:

- **Class-1 (walker):** agent 20's **PR-1 completeness guard is the right minimal
  fix** — but the proposed shape is **moderately over-built** in two places: the
  declared `_LEAF_TO_WALKER_XPATHS` spelling map (~52 hand-typed rows) and the
  `test_known_gap_backlog_does_not_grow` ratchet (§3.7). Both add maintenance
  surface without proportional class-kill value. Trim them (MF-1, MF-2).
- **Class-1 PR-2 (surgical walk-expansion):** correctly staged and deferrable. **My
  recommendation: defer the whole of PR-2 out of this run** — the guard already makes
  every HIGH gap *visible and accounted-for in writing*, which is the class-kill the
  user asked for; the per-instance walk + per-codec declaration + phase4 regen is a
  separate, riskier, behavior-changing exercise that should not ride the same wave
  (MF-3).
- **Class-2 (sanitizer):** agent 21's **regex-driven guard (form B) is the right
  minimal fix**; agent 22's **typed marker is over-engineering for the scope of this
  run** and should be explicitly declined-for-now, not deferred-ambiguously (MF-4).
  The one genuinely valuable nugget in the marker report — the `engine_id`
  not-named-like-a-secret gap and the four un-redacted MAC fields — is capturable
  *without* the marker (MF-5).
- **The single biggest pragmatism risk across both designs is the MAC redaction
  (PR-S1).** It is the only proposal that changes runtime behavior on class-2, it
  invents a new primitive (`redact_mac`) and picks a docs-MAC range, and it is being
  smuggled in as "make the guard green day one." It deserves its own scrutiny and
  arguably its own PR or deferral (MF-6).

Net: the durable fix is **two small CI guards** (one recursive walker-coverage guard,
one IP/MAC sanitizer-coverage half), both reusing the *already-proven* reflection
engine, both zero-runtime-change, both phase4-neutral. Everything beyond that —
the spelling map's full population, the ratchet, the marker, the walk-expansion, the
MAC primitive — is either trimmable or stageable-out. Strip to the spine and this is
~100 net lines of test code that kills the class.

---

## 1. Is each recommended design the MINIMAL thing that closes the class?

### 1.1 Class-1 walker guard — minimal in concept, over-built in artifacts

The *concept* is minimal and correct: the existing forward-coverage checks
(`test_marker_dict_covers_every_data_bearing_field` reflects only
`set(CanonicalIntent.model_fields)` — confirmed top-level-only at
`test_registry_capability_honesty.py:534`; G5's `_FIELD_TO_EXPECTED_XPATH` is 18
hand-listed top-level fields, confirmed at `test_walk_canonical_coverage.py:165-184`)
**both stop at the top level and never recurse into the nested models where the gap
concentrates** (VRRP group, DHCP pool, SNMPv3 user). A recursive reflection guard is
the smallest change that closes that hole. Agreed. This is the spine and it is right.

But agent 20's PR-1 carries **two artifacts that are bigger than the class-kill
needs**:

**(a) The declared `_LEAF_TO_WALKER_XPATHS` spelling map (~52 rows).** Agent 20
argues (§3.4) the map is necessary because xpath spelling is irregular
(`config/` segment present for `mtu`/`vrf` but absent for `switchport-mode`; VXLAN is
`/vxlan-vnis/<leaf>` with no `/vni/`; the VLAN-SVI reuse needs two strings). That
irregularity is real — I confirmed it in the census (`10-model-leaf-census.md` §14.6)
and in the walker. **But the guard does not need the exact xpath spelling to kill the
class.** The class-kill question is binary: *"is this leaf reachable by the live
validator at all?"* — i.e. *"does the walker emit ANY xpath that this `(Class, field)`
contributes to?"* That can be answered without a per-leaf spelling table, by a far
cheaper construction (§2.1 below): partition leaves into "walked" vs "not walked" by
asking whether the field is *touched* during a walk of the kitchen-sink, not by
hand-asserting which string it maps to. The spelling map is a **second
hand-maintained list** — exactly the artifact shape this whole run exists to
eliminate — and it is ~52 rows that a contributor must edit every time they add a
walked leaf. Agent 20's own defense ("the map is itself guarded; a leaf missing from
both map and exemption fails") is true but misses the pragmatism point: *the map's
existence is itself the maintenance tax*, and a leaf that IS walked still forces a map
edit. **MF-1: drop the spelling map; derive walked-ness structurally (§2.1).**

**(b) The `test_known_gap_backlog_does_not_grow` ratchet (§3.7).** Agent 20 flags
this as "possibly gold-plating" — it is. A `_KNOWN_GAP_BASELINE` integer that a PR
must manually decrement is itself a hard-coded count that rots (it directly violates
the AGENTS.md "never hard-code a count unless a guard keeps it honest" rule — here the
count IS the guard, which is circular and brittle). The `KNOWN-GAP:` reason-prefix
convention already makes the backlog `grep`-able; that is sufficient visibility.
**MF-2: drop the ratchet.** (Severity minor — it is opt-in and agent 20 already
flagged it.)

### 1.2 Class-2 sanitizer guard — minimal and correct

Agent 21's form B (extend `TestSecretRedactionCoverage` with an IP/host + MAC half,
reusing `_reachable_canonical_models` / `_flatten_annotation`) is genuinely the
cheapest durable fix. The reflection engine already exists and ships green today
(confirmed `test_sanitize.py:662-685`, used by the passing
`test_reverse_no_unregistered_secret_field`). ~70 lines, one file. No notes on the
guard *shape* — it is the right altitude and the right size. My only class-2 concerns
are (a) the typed marker that agent 22 layers on top (§1.3), and (b) the MAC runtime
change bundled into PR-S1 (§4).

### 1.3 The typed marker (agent 22) — over-engineering for THIS run

Agent 22 is admirably honest: it self-describes the marker as "a *close* call," "not
a clean self-enforcing win," with an "Achilles heel" (a contributor can silently omit
the marker), and concludes the synthesis should *ratify, not ram through*. I will take
the position agent 22 invites: **for the scope of this run, the marker is
over-engineering and should be explicitly declined, not left as an ambiguous
"PR-S3 (optional, only if agent 22 wins)."**

The case against, on pragmatism grounds specifically:

1. **It re-introduces the exact disease it claims to cure.** Agent 22 §5 + §8.1
   admit the marker only becomes self-enforcing if paired with a *meta-guard* that
   asserts "every `str`/`list[str]` leaf is either marked OR in a
   `_NON_SENSITIVE_TEXT` exemption set." That exemption set (agent 22 §8.1 lists
   `name`, `description`, `mode`, `interface_type`, `timezone`, `tunnel_type`,
   `dhcp_client_v6`, `scope`, `kind`, `default_name`, `instance_type`,
   `source_interface`, `interface`, …) is a **hand-maintained subset with a permissive
   default** — the literal definition of the class this run is killing. The regex
   guard's exemption set is *2 entries* (`interface`, `source_interface`); the
   marker's meta-guard exemption set is *~14 and growing with every non-sensitive
   string field added*. The marker makes the exemption surface **larger**, not
   smaller, once you account for the meta-guard it requires to be self-enforcing.
   Without the meta-guard, the marker is strictly *worse* than the regex (silent
   omission, caught by nothing).

2. **It is a new contributor-facing discipline for marginal gain.** Every future
   field author must learn the `Annotated[str, Sensitive("...")]` idiom and remember
   it; forgetting produces *no error* (agent 22 §5 concedes this). The regex requires
   contributors to do nothing — it scans names they already write. The net new
   maintenance burden of the marker (learn idiom + remember + meta-guard + its
   exemption list + doc-sync into `adding-a-canonical-field.md`) exceeds the ~70-line
   regex guard's burden by a wide margin.

3. **The "real" wins agent 22 cites are achievable without the marker.** The three
   nuggets — `engine_id` (redacted but not secret-*named*), the four un-redacted MAC
   fields, and `static_routes[].destination` — are all capturable in the regex guard
   by (a) adding `engine_id` to `_REGISTERED_SECRET_FIELDS` explicitly (it is already
   redacted, just not registered — a one-line registry add), and (b) the MAC half /
   destination wire-up agent 21 already proposes. None require the marker. **MF-5.**

The marker's *one* irreducible advantage is the deceptive-name residual (a future
`peer_endpoint: str` holding an IP that the regex misses). That is a real but
low-probability event, and the honest mitigation is the one agent 21 §6.4 and agent 22
itself land on: the codebase's naming convention is a documented, de-facto-enforced
contributor expectation. **Reserve the marker as a documented escalation IF a
deceptive-name field ever actually ships** — do not pay its cost speculatively now.
**MF-4: decline the marker for this run; record it as a deferred option in
`99-synthesis.md` with the trigger condition "a real IP/secret field ships with a
non-indicative name."**

---

## 2. A cheaper class-1 guard construction (the MF-1 alternative)

To make MF-1 actionable rather than a complaint, here is the minimal construction
that kills the class *without* the spelling map. It answers "is this leaf walked?"
structurally instead of by a hand-asserted string.

### 2.1 Walked-ness by sentinel-difference, not by spelling

The walker yields xpaths conditionally on a field being populated. So "this leaf is
walkable" ≡ "populating this field (and nothing else) on a maximal intent causes
`_walk_canonical` to emit at least one xpath it would not emit on the empty intent."
That is mechanically derivable:

```python
_WALKABLE = frozenset(_walk_canonical(_maximal_intent()))   # reuse the existing one
_EMPTY    = frozenset(_walk_canonical(CanonicalIntent()))

# A leaf is "covered by the walker" if the maximal-intent walk is STRICTLY larger
# than the empty walk *because of* that field's surface. In practice the simpler
# and sufficient check is: every (Class, field) leaf must correspond to at least
# one walked xpath segment, OR be exempt. We do NOT need the exact string — only
# the yes/no.
```

The honest simplification: rather than per-leaf sentinel diffing (which is fiddly for
shared sub-models), keep agent 20's `_model_leaves()` enumerator and the
`_WALK_EXEMPT` set, but **replace the `_LEAF_TO_WALKER_XPATHS` map with a derived
membership test**: a leaf `(Class, field)` is "walked" iff the walker emits an xpath
whose final segment matches the field's kebab spelling *or* whose path contains the
field — using a tolerant `field_name → kebab` transform and substring/suffix match
against `_WALKABLE`, not an exact hand-typed string. The guard then only needs the
**exemption set** (the genuinely-not-walked leaves), which is the information that
actually carries meaning — exactly mirroring how #149's `_is_legitimate_nonwalkable`
works (it is a *predicate*, not a per-path lookup table; confirmed
`test_registry_capability_honesty.py:333-346`).

This is strictly less code (no ~52-row map), and it removes the second
hand-maintained list. The residual risk — a tolerant match could *false-positively*
decide a leaf is walked when a same-named-but-different xpath is what's actually
emitted — is real but narrow, and is itself caught by the existing per-codec
render-reparse survival guards (`test_static_route_subfield_and_secondary_drops_are_declared`,
confirmed `:601-629`) which assert *value* survival independent of spelling. So the
tolerant guard's only job is the *forward coverage* binary, and a rare false-"walked"
is backstopped.

**If the synthesis judges the tolerant match too loose**, the fallback is *not* the
full spelling map but a hybrid: derive walked-ness by tolerant match, and keep a
**small `_SPELLING_OVERRIDE` dict ONLY for the handful of irregular cases** (the
`config/` interface fields, the VXLAN element collapse, the VLAN-SVI reuse) — ~8 rows,
not ~52. The 90% regular cases derive; only the irregulars are declared. That is the
genuinely minimal version and I'd accept it as the GO bar.

### 2.2 The exemption set is the only list worth hand-maintaining

Agent 20's `_WALK_EXEMPT` (§3.5) is correct in spirit — it carries reasons, mirrors
#149, and is guarded by `test_no_stale_walk_exemptions` (a good guard-the-guard). My
only trims:

- The **envelope-covered cluster entries** (DHCP ×8, EVPN-Type5 ×4, RADIUS ports ×2)
  are correctly exempt (cross-mesh audit backstops them — `11-walker-gap.md` §6) but
  their reason strings should *cite the backstop test by name* so a reader can verify
  the claim, not just assert "audit-backstopped."
- The **`KNOWN-GAP:` entries** are fine as exemptions but should NOT carry the ratchet
  (MF-2). The prefix convention alone is the visibility mechanism.

---

## 3. Over-fire / false-positive risk on legitimate evolution + the intentional exemptions

This is the core pragmatism question: *would these guards cry wolf on a normal,
correct change?* I walked the likely evolution scenarios.

### 3.1 Class-1 guard vs #149 Tier-3 non-walkable paths — SAFE, but one trap

The #149 lesson (Tier-3 routing-protocol paths and the 6 `_SYNTHETIC_NONWALKABLE`
markers are *intentionally* non-walkable) is about **declared-but-not-walkable**
matrix paths (`/routing/bgp` etc.) — the *reverse* direction from the class-1 gap. The
new walker-coverage guard reflects over **model leaves**, and the canonical model has
*no BGP/OSPF leaf* (Tier-3 lives only as `raw_sections`/`dropped_tier3_sections`).
**So the new guard never even sees a Tier-3 path** — there is no model field to
enumerate. Confirmed: the model classes are the 17 in the census; none is a routing
protocol. **No false-fire risk from #149's Tier-3 paths.** Agent 20 and 11 both got
this right (`11-walker-gap.md` §7).

**The trap (minor):** agent 20's guard reuses `_WALKABLE` which is built from
`_maximal_intent()` in `test_registry_capability_honesty.py:132-225`. The per-codec G5
floor uses a *different* kitchen-sink `_kitchen_sink()` in
`test_walk_canonical_coverage.py`. If a future leaf is populated in one fixture but
not the other, the guard reading `_WALKABLE` could disagree with G5. This is a
cross-file coupling that will rot silently. **MF-7 (minor): the new guard's
`_maximal_intent` dependency must be asserted to populate every non-exempt leaf**
(agent 20's `test_no_stale_walk_exemptions` checks the exemption set tracks the model,
but nothing checks `_maximal_intent` actually exercises every *walked* leaf — there is
already a `test_maximal_intent_exercises_every_top_level_field` at `:544-556` but it,
too, is top-level-only). Add the recursive sibling, or the guard can pass vacuously if
`_maximal_intent` leaves a nested sub-field empty.

### 3.2 Class-1 guard vs ordinary model evolution — actionable, low friction

Scenario: a contributor adds `CanonicalInterface.poe_enabled: bool = False` and wires
it through two codecs but forgets the walker yield. The guard fails with (agent 20
§3.6 message): *"CanonicalInterface.poe_enabled (no walker-xpath mapping) … add a
yield in `_walk_canonical` + per-codec declaration, OR add a self-justifying
`_WALK_EXEMPT` entry."* **That message is actionable** — it names the exact field and
the two valid resolutions. Friction is one of: (a) one yield line + the field travels
as a walked surface, or (b) one exemption row with a reason. Both are proportionate to
"you added a config surface." This is the *intended* friction and it is correctly
sized. Good.

The friction edge case: a contributor adding a **purely-internal/transform field**
(like the existing `kind`/`default_name`) must now add an exemption row. That is a tiny
tax (one line + reason) and is arguably *correct* — it forces the author to declare
"this is not a config surface," which is exactly the fail-surfaced default. Accept.

### 3.3 Class-2 regex guard vs the private-IP preservation — SAFE (it's a test)

The seed's load-bearing constraint — *the sanitizer PRESERVES private/docs IPs by
design; do not over-redact* — is **untouched by the recommended form B** because form B
changes no runtime redaction behavior; it is a coverage *test*. Confirmed by agent 21
§5: the only runtime changes are PR-S1's destination + MAC wires, which route through
the existing private-preserving primitives. The blanket `ip_address()` rule (form A) —
which *would* have risked the preservation logic — is correctly rejected by both agent
12 and agent 21. **No private-IP over-redaction risk in the recommended path.** The
seed's central fear is fully addressed by *not doing* the thing the user worried
about.

### 3.4 Class-2 regex guard vs legitimate field naming — one real false-fire vector

The regex `_IP_HOST_NAME_RE` (agent 21 §2.2) will match ANY future field whose name
contains `ip`/`host`/`gateway`/`network`/`address`/`prefix`/`destination`/etc. as a
token. Two false-fire vectors:

1. **A non-IP field with an IP-ish name token.** Today there are exactly 2
   (`interface`, `source_interface` — and note `interface` matches via… actually it
   does *not* match `_IP_HOST_NAME_RE` as written; agent 21's exemption comment is
   slightly inconsistent here — `interface` contains no listed token). The real
   matches are `source_interface` (matches nothing in the regex either — it has no
   `ip`/`host`/`address` token) — **so agent 21's `_IP_NAME_EXEMPT` may be solving a
   non-problem.** *This needs the synthesis to actually run the regex against the live
   model field list before trusting the "2 entries" claim.* **MF-8 (minor): verify the
   exemption set empirically — run `_scan_named_fields(_IP_HOST_NAME_RE)` against the
   current model and confirm the false-positive set is exactly what's claimed; the
   peer reports asserted "2 entries" without showing the scan output.**

2. **`prefix_length` (int).** Named with `prefix` but it's an `int`, so it fails the
   `str in _flatten_annotation` filter — correctly NOT flagged. Good, but it shows the
   regex+type-filter interaction is load-bearing and must be tested.

The friction when the regex DOES correctly fire on a new IP field is the right
friction (wire redaction + register, or exempt-with-reason). Actionable message
(agent 21 §2.4). Fine.

### 3.5 Would a blanket sanitizer rule mangle real fixtures? — moot, but confirm the rejection sticks

Agent 12 §5 did the over-redaction homework: whole-string `ip_address()` parsing means
free-text descriptions don't mangle (they `ValueError`), and the corpus diff is <1%.
That analysis is sound and I have no quarrel with it. **But the recommended design
does not adopt the blanket rule at all**, so this is moot — *provided the synthesis
does not quietly resurrect it.* The user's verbatim phrasing ("redacts on
`ip_address()` of ANY IP-typed field") could tempt the main thread to implement form A
to "honor the user's words." **MF-9 (the framing fix): the synthesis must explicitly
tell the user that form A (blanket) is being declined in favor of the guard, with the
one-line reason "blanket is both insufficient (blind to MAC/RD/RT/community/hash) and
the wrong altitude (a coverage problem, not a runtime problem)" — and that this better
serves the stated goal.** This is a communication must-fix, not a code one, but it is
the place a well-meaning actuation could go wrong.

---

## 4. The MAC redaction (PR-S1) — the one runtime change that needs real scrutiny

This is my single largest pragmatism flag, because it is being introduced almost
incidentally ("to make the guard green day one") while being the *only* behavior-change
in the class-2 path and the *only* new redaction primitive in the whole run.

Concerns:

1. **It is a NEW redaction category, which trips a heavy doc-sync chain.** Agent 21 §7
   correctly identifies it: SECURITY.md sanitiser table + BUG_REPORTING.md "what gets
   sanitised" + module docstring, all in the *same commit* (AGENTS.md Hard Rule). That
   is real work and real review surface for what is, today, a *latent* gap (no audit
   ever found a MAC leak; agent 12 §5b.3 classifies MACs as "currently un-redacted"
   but did not show a fixture where a real operator MAC leaks). **Is the MAC gap
   urgent enough to ride this run?** I think not — it is exactly the kind of
   "field N+1" the *guard* is designed to surface, so the principled move is to let
   the guard flag it and fix it deliberately, not pre-empt it.

2. **`redact_mac` makes a non-trivial design choice** (the RFC 7042 `00:00:5E:00:53:NN`
   docs range, avoiding the VRRP `:01:` sub-block — agent 21 §3.2). That is a
   thoughtful choice but it is *a choice*, with a follow-on open question agent 21
   itself flags (should the well-known VRRP vMAC `00:00:5E:00:01:VRID` be *preserved*
   like multicast is?). Unresolved design questions do not belong in a "make the guard
   green" precursor PR.

3. **The "green day one" framing creates a coupling that shouldn't exist.** Agent 21
   structures it as "PR-S1 wires destination + MAC so PR-S2's guard is green." But the
   guard does not *need* MAC to be green — the MAC fields can simply be **registered as
   a documented KNOWN-GAP exemption** in the IP/MAC guard (with reason "MAC redaction
   not yet wired — tracked"), exactly as agent 20 does for the class-1 KNOWN-GAP
   leaves. Then the guard ships green with zero runtime change, and MAC redaction
   becomes a clean, separately-reviewable follow-up with its own doc-sync.

**MF-6: split MAC redaction (and its `redact_mac` primitive + docs-range choice + vMAC
open question) out of the guard PR entirely.** Ship the class-2 guard with the four
MAC fields registered as a documented gap; do MAC redaction as a deliberate follow-up
(or defer it — it is latent, not bleeding). The `static_routes[].destination` wire-up
is genuinely tiny (1-line `redact_cidr`, identical to existing `dhcp.network`) and can
stay in the guard PR or also be deferred-as-documented-gap; I lean keep-it (it is a
real, if marginal, modelled leak and the fix is trivial and uses an existing
primitive).

This trim makes the *entire class-2 fix zero-runtime-change* — which is the safest
possible posture and matches the seed's stated preference.

---

## 5. Maintenance burden — who keeps the exemption lists honest?

The durable-fix story lives or dies on whether the exemption sets stay honest. My
assessment, per list:

| Exemption surface | Size today | Growth rate | Honesty mechanism | Verdict |
|---|---|---|---|---|
| Class-1 `_WALK_EXEMPT` | ~38 (if PR-2 deferred, incl. ~12 KNOWN-GAP) | one row per new non-config field | reason strings + `test_no_stale_walk_exemptions` | **Acceptable** — guarded, reason-carrying, mirrors #149 |
| Class-1 `_LEAF_TO_WALKER_XPATHS` | ~52 | one row per new *walked* leaf | guard-the-guard `test_no_stale_xpath_mappings` | **Too heavy — MF-1 removes it** |
| Class-2 `_REGISTERED_IP_FIELDS` | ~26-30 | one per new IP field | forward sentinel + `stale` check | **Acceptable** (mostly documents existing coverage) |
| Class-2 `_IP_NAME_EXEMPT` | claimed 2 | rare | reason strings | **Acceptable if MF-8 confirms the count** |
| Marker `_NON_SENSITIVE_TEXT` (if marker adopted) | ~14 | one per new non-sensitive *string* field — **frequent** | reason strings | **Unacceptable — this is the disease; MF-4 declines it** |

The decisive maintenance observation: **the marker's required meta-guard exemption set
grows with the most common kind of field change (adding a descriptive string field),
whereas the regex/walker exemption sets grow only on the rare addition of a
non-indicatively-named or non-config field.** Growth-on-common-change is the
maintenance anti-pattern; growth-on-rare-change is acceptable. This is the clearest
pragmatic discriminator and it points away from the marker.

**Who keeps them honest:** PR review, backed by (a) the reason-string requirement
(a reviewer can challenge a bogus reason — the #149 social process, which agent 20 §4
and agent 21 §6 both lean on and which *has held since #149* per MEMORY), and (b) the
`stale`/`no_stale` guard-the-guard tests that force the lists to track the model. This
is the same discipline the project already runs successfully. I am satisfied it
scales for the regex/walker exemption sets; I am NOT satisfied it scales for the
marker meta-guard's free-text exemption set.

**Failure-message actionability:** all three proposed guards name the exact
`Class.field` and give the two valid resolutions (handle-it / exempt-with-reason).
Confirmed in agent 20 §3.6 and agent 21 §2.4. Good — these are not cryptic assertion
failures.

---

## 6. Blast-radius sanity check — are the phase-2 churn estimates realistic?

### 6.1 Class-1 PR-1 (guard) — estimate is realistic, slightly understated on data-entry

- "Zero phase4 reclassification" — **CORRECT and certain.** I confirmed phase4 reads
  matrices + cross-vendor YAMLs, never the walker (`run_full_mesh.py:334-335`,
  `xpath_walker.py:57-60` docstring, and the new guard touches neither). A pure test
  addition cannot move a phase4 cell.
- "~112 leaves to enumerate, ~64 walked + ~38 exempt" — realistic *as a count*, but
  the "mechanically derivable, one-time data entry" framing **understates the
  judgement cost**: deciding the *reason string* for each of ~38 exemptions, and the
  *xpath spelling* for ~52 map rows, is not pure mechanics — it is ~90 small
  decisions. With MF-1 (drop the spelling map) and MF-3 (defer PR-2, shrinking the
  KNOWN-GAP exemptions to documented-deferrals), the real data-entry drops to ~38
  exemption reasons, which is honest one-evening work. **The estimate is realistic
  only after the MF-1/MF-3 trims; as written it's ~1.5× understated.**

### 6.2 Class-1 PR-2 (walk-expansion) — estimate plausible but this is where the risk lives

Agent 20 §5.2 claims each walked HIGH leaf produces "drifted-against-lossy =
EXPECTED_LOSSY (ok), not CODEC_BUG" cells because the declaration lands in the same PR
as the walk. **That is the correct theory and matches the MEMORY St3-anycast
precedent** (which broke exactly one `tests/unit/audit/` reconciliation test when
matrix decl drove a CODEC_BUG→EXPECTED_LOSSY reclass). But:

- The estimate "bounded, per-leaf, not a storm" is **plausible but unverified** — it
  depends on every populating codec correctly declaring lossy/unsupported for every
  newly-walked leaf, across up to 11 codecs and the FHRP-bearing pairs. The St3 lesson
  in MEMORY is precisely that this kind of change *broke a test the author didn't
  expect* and required running FULL `tests/unit` (not just `…/migration`). Agent 20
  flags this (§5.2 "run FULL `tests/unit`") — good — but it means PR-2 is the genuinely
  risky, regen-requiring, behavior-changing part of the run.
- **This is the strongest argument for MF-3 (defer PR-2 out of this run).** The guard
  (PR-1) already converts every HIGH gap into a *written, visible* KNOWN-GAP. The
  user's goal ("fail-surfaced defaults — stop the silent recurrence") is met by the
  guard alone: a new such leaf can no longer be added silently. Actually *walking* the
  existing HIGH leaves is instance-cleanup, not class-kill, and it carries the only
  real phase4 risk in the run. Stage it as a separate, later, per-surface wave (agent
  20 §6 already proposes PR-2a/2b/2c) — but do not make it part of the "land the
  durable fix" deliverable.

### 6.3 Class-2 — estimate realistic and reassuring

- "Phase4 impact: ZERO" — **CORRECT.** The sanitizer is off the migration-validate /
  cross-mesh path entirely (it has its own walk). Confirmed. This is genuinely the
  safer half.
- "Fixture-corpus diff near-zero (<1%)" — sound, *for the guard + destination wire*.
  The MAC redaction's corpus impact is "cosmetic, where a MAC is present" — agent 21
  §9.2 correctly flags the one real risk (a test pinning a MAC literal in a
  sanitizer-output assertion) and says grep `tests/` first. With MF-6 (MAC split out),
  the guard PR's corpus diff is *truly* near-zero.

### 6.4 Reflection-engine relocation — one shared-util coupling to get right

Both agent 20 and 21 want `_reachable_canonical_models` + `_flatten_annotation`
promoted from `test_sanitize.py:662-685` to a shared test-support module. That is the
right DRY move, but it is a **cross-test-file refactor** that both new guards then
depend on. Pragmatism note: do the promotion as a **tiny precursor PR (PR-0)** that
moves the two helpers + updates the one existing import, verified green, *before*
either guard PR — so a bug in the move can't be conflated with a guard bug. **MF-10
(minor): sequence the shared-util extraction as its own precursor commit.** Agent 20
§6.1 gestures at this ("ship the shared util in whichever PR lands first, or a tiny
precursor PR") — make it explicitly the precursor.

---

## 7. One PR or several? Staging recommendation

The peer designs propose, in aggregate, up to **8 PRs** (PR-0 shared util, PR-1 walker
guard, PR-2a/b/c walk-expansion, PR-S1 MAC+dest, PR-S2 sanitizer guard, PR-S3 marker).
That is too many for the class-kill, and several are the riskier instance-cleanup. My
staging, trimmed to the durable spine:

**Ship in this run (the durable fix — all zero-runtime-change, all phase4-neutral):**

1. **PR-0** — promote `_reachable_canonical_models` + `_flatten_annotation` to a shared
   test-support module; update the one secret-guard import. Green, mechanical. (MF-10)
2. **PR-1** — the recursive **walker-coverage guard** + `_WALK_EXEMPT` (with reasons) +
   the guard-the-guard tests (`no_stale_*`, recursive `_maximal_intent` exerciser —
   MF-7). **Without** the spelling map (MF-1, derive walked-ness or use the ~8-row
   override) and **without** the ratchet (MF-2). Every current HIGH gap is a documented
   KNOWN-GAP exemption.
3. **PR-2** — the **sanitizer IP/host + MAC coverage guard** (form B). The four MAC
   fields **registered as a documented gap** (MF-6), the `static_routes[].destination`
   1-line `redact_cidr` wire (its only runtime change; uses existing primitive). Green
   day one. **No marker** (MF-4).

That is **3 small PRs** (+ the trivial PR-0), ~150 net lines of test code total, zero
behavior change beyond one trivial existing-primitive redaction, zero phase4 movement.
That kills both classes (a new unwalked leaf → red CI; a new IP/secret/MAC field → red
CI).

**Defer out of this run (instance-cleanup + speculative, each its own later wave):**

- **The class-1 walk-expansion (PR-2a/b/c)** — behavior-changing, regen-requiring,
  carries the only real phase4 risk. The guard documents every deferral honestly as a
  KNOWN-GAP. (MF-3)
- **MAC redaction** (`redact_mac` primitive + 4 sites + docs-range choice + vMAC
  open question + 3 doc-sync targets) — latent gap, deliberate follow-up. (MF-6)
- **The typed marker** — declined-for-now, with a recorded trigger condition. (MF-4)

---

## 8. Does the recommended design relocate the blind spot? (pragmatism angle)

The correctness review (agent 30) owns the rigorous version of this. My pragmatism
read: **the guards relocate the blind spot from "an invisible silent loss" to "a
visible, reason-carrying exemption line in a guarded test file" — which is a genuine
improvement, not a wash**, for three pragmatic reasons:

1. The exemption is a **diff-visible code change requiring a written reason** — a
   reviewer sees it; the status quo (forgetting a leaf) produces *no diff at all*.
   That asymmetry is the whole value, and it is real.
2. The exemption sets that matter (walker `_WALK_EXEMPT`, sanitizer `_IP_NAME_EXEMPT`)
   grow on *rare* changes (non-config field; non-indicatively-named IP field), not
   common ones — so they don't bloat in practice. (Contrast the marker meta-guard,
   which bloats on common changes — §5.)
3. The reason-string + `no_stale` discipline is **already proven in this codebase**
   (#149 has held). I am not asking the project to invent a new social process; the
   guards reuse one that works.

The honest residual (both reviews should state it): a guard cannot stop a determined
contributor from writing a *plausible-but-wrong* reason string that a reviewer misses.
That is a social-process risk, strictly better than today's no-signal state, and not
fixable by more machinery without diminishing returns. Accept it; do not gold-plate
against it (this is the second reason to drop the ratchet, MF-2 — it is machinery
fighting a social risk).

---

## 9. Must-fixes (consolidated)

| ID | Issue | Fix | Severity | Target |
|---|---|---|---|---|
| MF-1 | Class-1 `_LEAF_TO_WALKER_XPATHS` (~52 hand-typed rows) is a *second hand-maintained list* — the exact artifact this run exists to kill — and forces a map edit even for correctly-walked leaves | Derive walked-ness structurally (sentinel-diff / tolerant kebab-suffix match against `_WALKABLE`); keep at most a ~8-row `_SPELLING_OVERRIDE` for the irregular cases (`config/` iface fields, VXLAN element collapse, VLAN-SVI reuse). The only hand-maintained list should be the *exemption* set | major | `20-design-walker-guard` §3.4 |
| MF-2 | The `test_known_gap_backlog_does_not_grow` ratchet hard-codes a baseline count (rots; circular guard) and is machinery against a social risk | Drop the ratchet; the `KNOWN-GAP:` reason-prefix grep is sufficient visibility | minor | `20-design-walker-guard` §3.7 |
| MF-3 | Class-1 PR-2 (walk-expansion) is behavior-changing, regen-requiring, and carries the run's only real phase4 risk (the St3 precedent broke a `tests/unit/audit` test) — it is instance-cleanup, not class-kill | Defer ALL of PR-2 out of this run; the PR-1 guard already makes every HIGH gap a documented KNOWN-GAP, which satisfies the user's "stop silent recurrence" goal. Stage walk-expansion as a separate later per-surface wave | major | `20-design-walker-guard` §5.2/§6 |
| MF-4 | The typed marker (agent 22) is over-engineering for this run: its self-enforcing form REQUIRES a meta-guard whose `_NON_SENSITIVE_TEXT` exemption set grows on the *common* change (adding a string field) — re-introducing the disease — and it adds a contributor discipline that fails silently when forgotten | Decline the marker for this run; record it in `99-synthesis.md` as a deferred escalation with the explicit trigger "a real IP/secret field ships with a non-indicative name." Ship agent 21's regex guard instead | major | `22-design-typed-marker` §5/§7 |
| MF-5 | The marker's three cited "wins" (`engine_id`, MACs, destination) are used to justify the marker but are all capturable without it | Register `engine_id` explicitly in `_REGISTERED_SECRET_FIELDS` (it is already redacted — one-line add); handle MACs + destination via agent 21's guard. No marker needed to capture them | minor | `21`/`22` |
| MF-6 | MAC redaction is smuggled into PR-S1 as "make the guard green" but is the run's only class-2 runtime change, invents a primitive + docs-range, has an unresolved vMAC-preservation question, and trips a 3-target doc-sync chain — for a *latent* (never-observed) leak | Split MAC redaction entirely out of the guard PR; register the 4 MAC fields as a documented gap so the guard is green with zero runtime change. Do `redact_mac` as a deliberate follow-up (or defer — it's latent) | major | `21-design-sanitizer-guard` §3.2 |
| MF-7 | The class-1 guard reads `_WALKABLE` (built from `_maximal_intent`) but nothing asserts `_maximal_intent` populates every *nested* walked leaf — the existing exerciser `test_maximal_intent_exercises_every_top_level_field` is top-level-only, so the new guard can pass VACUOUSLY if a nested sub-field is left empty in the fixture | Add a recursive sibling that asserts the kitchen-sink populates every non-exempt nested leaf | minor | `20-design-walker-guard` §3.6 |
| MF-8 | Agent 21 asserts `_IP_NAME_EXEMPT` is "2 entries" but the regex as written may not actually match `interface`/`source_interface` (no `ip`/`host`/`address` token) — the false-positive set is unverified | Run `_scan_named_fields(_IP_HOST_NAME_RE)` against the live model and confirm the exemption set empirically before trusting the count; tune the regex/exemptions to the real result | minor | `21-design-sanitizer-guard` §2.3 |
| MF-9 | The user's verbatim goal names the blanket `ip_address()` rule (form A); a well-meaning actuation could resurrect it. The synthesis must close that door explicitly | In `99-synthesis.md`, state plainly that form A is declined (insufficient: blind to MAC/RD/RT/community/hash; wrong altitude: coverage not runtime) and that the guard better serves the stated goal | minor (communication) | synthesis |
| MF-10 | Both guards depend on a shared reflection engine extracted from `test_sanitize.py` — a cross-file refactor that, if bundled into a guard PR, conflates a move-bug with a guard-bug | Do the `_reachable_canonical_models`/`_flatten_annotation` extraction as a tiny green precursor PR-0 before either guard | minor | `20` §6.1 / `21` |

---

## 10. Over-engineering flags (the short list for synthesis)

1. **`_LEAF_TO_WALKER_XPATHS` spelling map** — a second hand-maintained list; the
   class-kill needs only the exemption set. (MF-1)
2. **`test_known_gap_backlog_does_not_grow` ratchet** — hard-coded count + machinery
   vs a social risk. (MF-2)
3. **The typed `Sensitive` marker** — a new contributor discipline + a meta-guard with
   a growing free-text exemption list, to fix a low-probability deceptive-name residual
   that doesn't exist in the current model. (MF-4)
4. **The marker meta-guard's `_NON_SENSITIVE_TEXT` set** — the clearest "relocates the
   blind spot" artifact in the whole design space; grows on the most common field
   change. (folds into MF-4)
5. **Bundling MAC redaction + a new primitive + a docs-range decision into a "green
   the guard" precursor** — scope creep on a latent gap. (MF-6)

## 11. What is correctly minimal (do NOT trim further)

- The recursive **reflection over `model_fields`** to reach nested leaves — this is
  the irreducible core that closes the top-level-only hole; both existing guards stop
  at the top level (confirmed `:534`, `:165-184`). Keep.
- The **`_WALK_EXEMPT` set with reason strings + `test_no_stale_walk_exemptions`** —
  this IS the #149 pattern, proven; it is the right and necessary hand-maintained list.
- Agent 21's **regex IP/host coverage half + forward sentinel** — ~70 lines reusing the
  proven engine; the minimal class-2 fix.
- Reusing **`_WALKABLE`** and the **existing render-reparse survival guards** as
  backstops rather than re-deriving them.

---

## 12. Citations index (independently verified)

- #149 self-justifying exemption (the precedent both designs lean on):
  `tests/unit/migration/test_registry_capability_honesty.py:323-346`
  (`_SYNTHETIC_NONWALKABLE` + `_is_legitimate_nonwalkable` — note it is a *predicate*,
  not a per-path lookup table; the model for MF-1).
- Top-level-only forward coverage (the hole the walker guard fills):
  `:527-541` (`test_marker_dict_covers_every_data_bearing_field` reflects
  `set(CanonicalIntent.model_fields)` — no recursion); top-level-only exerciser
  `:544-556`.
- `_WALKABLE = frozenset(_walk_canonical(_maximal_intent()))`: `:225`.
- Reflection engine (to be promoted, MF-10): `tests/unit/tools/test_sanitize.py:662-685`.
- Secret guard the class-2 fix extends: `test_sanitize.py:646-767`; the explicit
  "IP/PII deliberately scoped out of the secret guard" comment: `:770-782`.
- Render-reparse value-survival backstops (why a tolerant walked-ness match is safe,
  MF-1): `test_registry_capability_honesty.py:601-629`
  (`test_static_route_subfield_and_secondary_drops_are_declared`).
- Per-codec G5 floor (top-level + hand-listed sub-fields; the different kitchen-sink,
  MF-7 coupling): `tests/unit/migration/codecs/cisco_iosxe_cli/test_walk_canonical_coverage.py:165-208`.
- Peer reports: `10-model-leaf-census.md` (~112 leaves), `11-walker-gap.md` (§4 gap,
  §6 two-surface backstop, §7 #149), `12-sanitizer-gap.md` (§5 over-redaction, §6 form
  B), `20-design-walker-guard.md` (§3 guard shape, §5 blast radius), `21-design-
  sanitizer-guard.md` (§2 guard, §3 MAC/dest, §9 blast radius), `22-design-typed-marker.md`
  (§5 over-engineering ledger, §8 meta-guard Achilles heel).

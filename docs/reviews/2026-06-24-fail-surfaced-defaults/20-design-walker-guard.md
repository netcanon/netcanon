# 20 — Design: the durable class-1 (silent capability-loss) fix

**Agent:** `20-design-walker-guard` · Phase 2 (Design) · read-only
**Run:** 2026-06-24 · fail-surfaced-defaults · netcanon
**Scope:** Design the durable structural fix for **class 1** — the
silent-loss-on-an-unwalked-leaf blind spot. Compare **(A)** "walker
auto-yields every leaf" vs **(B)** a reflection-driven **completeness
GUARD** that FAILS at CI time when a model leaf is neither
walked-and-declared nor in a documented exemption set. Recommend one (or
hybrid), give the EXACT test/code shape, the self-justifying exemption
design, and a **quantified blast radius**.

Built on the Phase-1 census (`10-model-leaf-census.md`), the walker-gap
quantification (`11-walker-gap.md`), and the sanitizer-gap report
(`12-sanitizer-gap.md`, whose reflection-engine finding I reuse).

---

## 0. TL;DR / recommendation

- **Recommend a HYBRID, staged: (B) a reflection-driven completeness
  guard as the durable spine + a SMALL, surgical slice of (A)** — walk
  the handful of HIGH-risk nested sub-leaves the census found
  (§4.1 of `11-walker-gap.md`: the VRRP group sub-fields, SNMPv3
  `priv-passphrase`/protocols, IPv6 `scope`, routing-instance
  `instance_type`) **only where doing so is pure-declaration / low
  phase4 risk**. The guard is the thing that kills the *class*; the
  small walk-expansion converts the worst *currently-silent* instances
  into surfaced ones. Reject the full "walk EVERY leaf" form (A) — it is
  a phase4 reclassification storm for marginal benefit on the
  envelope-covered DHCP/EVPN clusters that the offline cross-mesh audit
  already backstops (`11-walker-gap.md` §6).

- **The guard is the literal answer to the user's "fail-surfaced
  *defaults*" goal at the right altitude.** The disease is "a new model
  leaf defaults to silently-fine." The guard flips that default: a new
  leaf defaults to **CI-red** until the author either (a) walks it AND
  declares it per-codec, or (b) adds a one-line self-justifying
  exemption. That IS a fail-surfaced default — surfaced at *test time*,
  which the seed explicitly prefers over a risky runtime behavior
  change.

- **The decisive structural finding** (from `11-walker-gap.md` §5, which
  I re-verified): the gap concentrates in **NESTED model sub-leaves**
  (`CanonicalVRRPGroup`, `CanonicalDHCPPool`, `CanonicalSNMPv3User`,
  `CanonicalEvpnType5Route`, `CanonicalRoutingInstance`). The TWO
  existing forward-coverage guards both stop at **top-level
  `CanonicalIntent` fields** and never recurse:
  - `test_marker_dict_covers_every_data_bearing_field`
    (`test_registry_capability_honesty.py:527-541`) checks
    `set(CanonicalIntent.model_fields)` — top-level only.
  - G5 `_FIELD_TO_EXPECTED_XPATH`
    (`test_walk_canonical_coverage.py:165-184`) — 18 hand-listed
    top-level fields only.
  **The durable guard must recurse through `model_fields` of the nested
  models.** That single change (recurse, not just top-level) is what
  closes the class.

- **The reflection engine already exists and is pydantic-v2 +
  `from __future__ import annotations` proven**:
  `_reachable_canonical_models` + `_flatten_annotation`
  (`tests/unit/tools/test_sanitize.py:662-685`), used by the secret
  coverage guard. The class-1 guard reuses the same machinery — this is
  a ~60-line addition, not a new subsystem. (Promote the two helpers to
  a shared test util so both the sanitizer guard and the walker guard
  import one copy — see §6.)

- **Blast radius to make the guard GREEN today**: with the guard set to
  the *current* walker + an exemption row per current gap leaf, **zero
  code change, zero phase4 reclassification** — the guard ships green
  and every gap is now *accounted-for in writing*. The optional surgical
  walk-expansion of the §4.1 HIGH leaves is a SEPARATE, later PR whose
  phase4 cost I quantify in §5 (it is per-codec-declaration work, not a
  storm — phase4 reads matrices, not the walker).

---

## 1. The two designs, precisely

### Design A — runtime: walker auto-yields every leaf

Make `_walk_canonical` (`xpath_walker.py`) emit an xpath for **every**
populated model leaf, by reflection rather than the current hand-written
`yield` ladder. Maximally durable: a new leaf is walked the instant it is
added, with no human action.

**Why it is the wrong primary tool here** (each point load-bearing):

1. **It forces a phase4 / matrix reclassification storm.** The walker is
   the input to the *live report* only (`xpath_walker.py:57-60`,
   `migration_validate.py:80-87`), BUT the moment a newly-walked leaf is
   one a codec drops, the codec MUST gain a `lossy`/`unsupported`
   declaration or `test_dropped_naming_independent_field_is_declared` /
   `test_static_route_subfield_and_secondary_drops_are_declared`
   (`test_registry_capability_honesty.py:471-505, 601-646`) go red. Each
   newly-walked dropped leaf = up to 11 per-codec declarations. The
   census (`11-walker-gap.md` §4.2) shows DHCP alone expands 1→8 yields,
   EVPN-Type5 1→4. That is dozens of new declarations across the fleet.
2. **The benefit is uneven.** The DHCP/EVPN envelope sub-leaves have a
   backstop: the offline cross-mesh `model_dump()` audit already catches
   them (`11-walker-gap.md` §6; `tools/run_full_mesh.py:334-335`). Only
   the live report is blind to them, and they are option-detail losses,
   not reachability/security losses.
3. **Reflection-walk changes ordering / duplication semantics.** The
   live report counts duplicate xpaths "one leaf per occurrence"
   (`migration_validate.py:80-87` docstring). A reflection walker that
   emits a fixed leaf-order per record would subtly shift the report's
   per-surface counts — a behavior change to verify across every codec
   pair. The current hand-written ladder's emit-order is load-bearing
   for the report and (indirectly) the round-trip tree-order trap noted
   in MEMORY (`_compare` doesn't normalize `routing_instances` order).

A **bounded, surgical** slice of A is still worth doing for the §4.1
HIGH leaves (see §3 recommendation + §5 cost) — but "walk literally
everything by reflection" is over-reach.

### Design B — CI: reflection-driven completeness GUARD

A new test that:

1. **Reflects** every data-bearing leaf reachable from `CanonicalIntent`
   (recursing into nested models, unwrapping `list[...]` / `X | None`).
2. **Computes** the walker's actual yield universe by running
   `_walk_canonical` on the kitchen-sink (reusing the existing
   `_WALKABLE` frozenset = `frozenset(_walk_canonical(_maximal_intent()))`,
   `test_registry_capability_honesty.py:225`).
3. **Maps** each reflected leaf to its expected walker-xpath spelling.
4. **FAILS** if a leaf is neither walked NOR in a self-justifying
   exemption set — with an actionable message naming the exact
   `Class.field`.

Zero runtime change. Converts "a new leaf silently defaults to
supported" into "a new leaf turns CI red until handled-or-exempted." The
open question — *does the exemption set just relocate the blind spot?* —
is answered by the #149 precedent (§4): each exemption carries a written
reason, and adding one is a reviewable, costly-on-purpose act.

---

## 2. Recommendation and rationale

**HYBRID, in two PRs:**

- **PR-1 (the durable spine — guard, GREEN day one, zero behavior
  change):** ship Design B as a recursive completeness guard, seeded
  with the *current* walker coverage + an exemption entry **for every
  current gap leaf**, each carrying a one-line reason (the §4.1 HIGH
  leaves get reason `"KNOWN-GAP: scheduled to walk in PR-2"`; the
  genuinely-non-config leaves get their structural reason). This makes
  the entire class **visible and accounted-for in writing** without
  changing a single yield or matrix. The guard now fails if anyone adds
  a *new* leaf without handling it.

- **PR-2 (surgical walk-expansion of the worst instances — behavior
  change, staged, phase4-quantified):** walk the §4.1 HIGH leaves
  (VRRP `mode`/`priority`/`preempt`/`advertisement-interval`/
  `authentication`/`virtual-ipv6s`; SNMPv3 `priv-passphrase`/
  `auth-protocol`/`priv-protocol`; IPv6 `scope`; routing-instance
  `instance-type`), add the matching per-codec `lossy`/`unsupported`
  declarations, remove those leaves from the guard exemption set, and
  regen the cross-mesh + phase4 artefacts. This converts the
  highest-consequence silent losses into surfaced ones. Each leaf moved
  out of the exemption set is gated by the guard, so PR-2 cannot
  "forget" a declaration.

Rationale for hybrid over pure-B:
- Pure-B leaves every current HIGH gap leaf *documented-but-still-
  silent* in the live report. The user's named instances (switchport →
  static-route → VXLAN → VLAN-ports → VLAN-SVI) were all closed by
  *walking + declaring*, not merely by documenting. Honoring the user's
  intent for the worst surfaces (a dropped HSRP→VRRP conversion, a
  dropped SNMPv3 privacy key) means actually walking them.
- The guard alone is the *class* kill; the walk-expansion is the
  *instance* cleanup of the worst current offenders. Doing both, in that
  order, is the minimal honest answer.

Rationale for B (not A) as the spine: the seed's stated preference
("favor the option that converts the blind spot into a CI failure over a
risky runtime behavior change") plus the asymmetry that the live report
is blind but the cross-mesh audit is not for the bulk
(`11-walker-gap.md` §6).

---

## 3. Exact shape of the guard (Design B, PR-1)

### 3.1 Where it lives

A new module: `tests/unit/migration/test_walker_completeness.py`
(sibling of the silent-loss guards `test_silent_loss_list_subfields.py`
/ `test_silent_loss_naming_sensitive.py`; the seed lists those as the
guards to build *on*, not duplicate). It is a **model-level structural
guard**, not per-codec, so it lives at `tests/unit/migration/` root, not
under `codecs/<vendor>/`. It supersedes the top-level-only
`test_marker_dict_covers_every_data_bearing_field` reflection by
recursing — but keep that test (it guards a *different* dict, the
unsupported-markers); the new test guards *walker coverage*.

### 3.2 The reflection machinery (reuse, don't reinvent)

Promote the two proven helpers from `test_sanitize.py:662-685` to a
shared test-support module (e.g.
`tests/unit/migration/_model_reflection.py` or
`tests/support/canonical_reflection.py`) and import them in BOTH the
sanitizer guard and the new walker guard:

```python
# already proven against pydantic v2 + `from __future__ import annotations`
def _flatten_annotation(ann):
    """Yield ann + every nested type arg (unwraps list[...] / X|None / dict)."""
    args = typing.get_args(ann)
    if not args:
        yield ann
        return
    for a in args:
        yield from _flatten_annotation(a)

def _reachable_canonical_models(root_cls, acc=None):
    """All BaseModel subclasses reachable from root_cls via field annotations."""
    if acc is None:
        acc = set()
    if root_cls in acc:
        return acc
    acc.add(root_cls)
    for fld in root_cls.model_fields.values():
        for t in _flatten_annotation(fld.annotation):
            if isinstance(t, type) and issubclass(t, BaseModel):
                _reachable_canonical_models(t, acc)
    return acc
```

**Critical correctness note on `from __future__ import annotations`:**
`intent.py` uses it (`intent.py:1` region — all type hints are strings).
The helper works **because** pydantic v2 *resolves* `model_fields[...]
.annotation` to the real type object at class-build time (not the raw
string). I confirmed this is the exact path the secret guard already
relies on (`test_sanitize.py:754` does `str in _flatten_annotation(fld
.annotation)` and passes in CI). So `fld.annotation` is the resolved
`list[CanonicalVRRPGroup]`, not the string `"list[CanonicalVRRPGroup]"`
— the recursion finds the nested `BaseModel`s reliably. **Do NOT** use
`typing.get_type_hints` on the raw class (it can choke on forward refs /
needs the module globals); use pydantic's already-resolved
`model_fields[...].annotation`. This is the single most important
implementation gotcha and it is already de-risked by the secret guard.

### 3.3 Enumerating the model's leaves

A "leaf" = a field on a reachable model whose flattened annotation
contains a **scalar** type (`str` / `int` / `bool` / `float`) — i.e. it
is a scalar or a `list[scalar]`, NOT a pure nested-model container.
Nested-model containers (`interfaces: list[CanonicalInterface]`) are
*not* leaves; their child fields are (recursion handles them).

```python
_SCALAR = (str, int, bool, float)

def _model_leaves():
    """Yield (ModelName, field_name) for every data-bearing scalar /
    list-of-scalar leaf reachable from CanonicalIntent."""
    for model in _reachable_canonical_models(CanonicalIntent):
        for fname, fld in model.model_fields.items():
            flat = set(_flatten_annotation(fld.annotation))
            has_scalar = any(t in _SCALAR for t in flat)
            has_nested_model = any(
                isinstance(t, type) and issubclass(t, BaseModel) for t in flat
            )
            # A pure nested-model container is not a leaf (its children are).
            # A scalar / list[scalar] field IS a leaf.
            if has_scalar and not has_nested_model:
                yield (model.__name__, fname)
            # dict fields (raw_sections/group_content) handled via exemption.
            elif not has_scalar and not has_nested_model:
                yield (model.__name__, fname)  # e.g. dict — exemption catches it
```

This yields the full leaf set the census enumerates (`10-model-leaf-
census.md` §13: ~112 structured leaves). Counting by `(Class, field)`
de-duplicates the `CanonicalIPv4Address` reuse (it appears once as a
model, but the walker emits it under two xpaths — the guard handles that
in the mapping, §3.4).

### 3.4 Mapping a `(Class, field)` leaf to its walker xpath(s)

The walker uses kebab-case xpaths with a `container/element` shape, and
some leaves carry a `config/` segment while others don't
(`10-model-leaf-census.md` §14.6 spelling caveats). A **declared
mapping dict** `_LEAF_TO_WALKER_XPATHS: dict[tuple[str,str], tuple[str,
...]]` makes the spelling explicit and reviewable, e.g.:

```python
_LEAF_TO_WALKER_XPATHS: dict[tuple[str, str], tuple[str, ...]] = {
    ("CanonicalIntent", "hostname"):       ("/system/hostname",),
    ("CanonicalIntent", "anycast_gateway_mac"): ("/anycast-gateway-mac",),
    ("CanonicalInterface", "mtu"):         ("/interfaces/interface/config/mtu",),
    ("CanonicalInterface", "switchport_mode"): ("/interfaces/interface/switchport-mode",),
    ("CanonicalIPv4Address", "ip"): (
        "/interfaces/interface/ipv4/address/ip",
        "/vlans/vlan/ipv4/address/ip",          # the reused-on-VLAN xpath (#175)
    ),
    ("CanonicalVRRPGroup", "virtual_ips"): (
        "/interfaces/interface/vrrp-groups/group/virtual-ips",),
    # ... one row per leaf
}
```

The reused `CanonicalIPv4Address` (interface + VLAN-SVI) is the reason
the value is a **tuple** of xpaths: a leaf "is walked" if **ANY** of its
mapped xpaths is in `_WALKABLE`. This faithfully models the asymmetry
the census flagged (`10-model-leaf-census.md` §2a: interface copy walks
the full set, VLAN copy walks only `ip`).

> Design choice — declared map vs. derived spelling. I deliberately use
> a **declared** `_LEAF_TO_WALKER_XPATHS` rather than algorithmically
> deriving the xpath from the field name. Derivation is brittle: the
> `config/` segment is present for `mtu`/`vrf`/`type`/`description`/
> `enabled` but absent for `switchport-mode`/`access-vlan`; VXLAN is
> `/vxlan-vnis/<leaf>` with no `/vni/` element; the VLAN-SVI reuse needs
> two strings. A declared map is honest about these and is itself
> guarded (a leaf with no map entry and no exemption → fail). **The map
> is NOT a second blind spot** because the guard fails on any leaf
> *missing from both* the map and the exemption set — you cannot add a
> leaf and forget both. (Contrast `30-review`'s concern: the map is a
> *spelling* table, not a *coverage decision* table; the coverage
> decision is "walked-or-exempt," enforced separately.)

### 3.5 The self-justifying exemption set (modelled on #149)

```python
#: Leaves the completeness guard does NOT require to be walked, each with
#: a written reason — modelled on #149's _SYNTHETIC_NONWALKABLE
#: (test_registry_capability_honesty.py:323-330). Adding an entry here is a
#: conscious, reviewable act: a bogus reason is challengeable in PR review.
_WALK_EXEMPT: dict[tuple[str, str], str] = {
    # ── Metadata / provenance (never a translatable capability surface;
    #    mirrors _NON_CAPABILITY_FIELDS at test_registry_capability_honesty.py:520) ──
    ("CanonicalIntent", "source_vendor"):   "metadata: codec that produced the tree",
    ("CanonicalIntent", "source_format"):   "metadata: source input_format",
    ("CanonicalIntent", "source_version"):  "metadata: OS version hint",
    ("CanonicalIntent", "raw_sections"):    "Tier-3 verbatim blob; never auto-rendered (dict, not a scalar leaf)",
    ("CanonicalIntent", "dropped_tier3_sections"): "notification-only surface; surfaced via its own banner",
    ("CanonicalIntent", "apply_groups"):    "Junos provenance hint (dict/list, not a config leaf)",
    ("CanonicalIntent", "group_content"):   "Junos provenance hint paired with apply_groups",
    # ── Transform hints / render mechanics (not an operator-visible surface) ──
    ("CanonicalInterface", "kind"):         "rename-mesh transform hint, not a render fidelity surface (11-walker-gap.md §4.3 #27)",
    ("CanonicalInterface", "default_name"): "MikroTik factory-name render mechanism; same-vendor round-trip only (#28)",
    # ── Discriminators that always travel with their walked identity leaf ──
    ("CanonicalIPv6Address", "scope"):      "KNOWN-GAP: link-local discriminator — scheduled to walk in PR-2",
    ("CanonicalIPv4Address", "prefix_length"): "always travels with /…/ip; lost-prefix-without-IP not observed",
    ("CanonicalIPv4Address", "is_secondary"): "walked conditionally as /…/secondary-ip when secondary",
    # ── KNOWN-GAP: the §4.1 HIGH leaves PR-2 will walk (each removed there) ──
    ("CanonicalVRRPGroup", "mode"):         "KNOWN-GAP: FHRP discriminator — PR-2",
    ("CanonicalVRRPGroup", "priority"):     "KNOWN-GAP: master-election — PR-2",
    ("CanonicalVRRPGroup", "preempt"):      "KNOWN-GAP: failover behavior — PR-2",
    ("CanonicalVRRPGroup", "advertisement_interval"): "KNOWN-GAP: timer — PR-2",
    ("CanonicalVRRPGroup", "authentication"): "KNOWN-GAP: secret-adjacent — PR-2",
    ("CanonicalVRRPGroup", "virtual_ipv6s"): "KNOWN-GAP: v6 VIP — PR-2",
    ("CanonicalVRRPGroup", "description"):  "operator free text; low fidelity stakes",
    ("CanonicalSNMPv3User", "priv_passphrase"): "KNOWN-GAP: privacy key (auth twin IS walked) — PR-2",
    ("CanonicalSNMPv3User", "auth_protocol"):   "KNOWN-GAP: algorithm downgrade — PR-2",
    ("CanonicalSNMPv3User", "priv_protocol"):   "KNOWN-GAP: cipher downgrade — PR-2",
    ("CanonicalSNMPv3User", "group"):           "KNOWN-GAP: VACM group — PR-2 (lower)",
    ("CanonicalRoutingInstance", "instance_type"): "KNOWN-GAP: mac-vrf↔vrf — PR-2",
    # ── Envelope-covered clusters (cross-mesh audit backstops these;
    #    live-report-only gap, lower urgency — 11-walker-gap.md §6) ──
    ("CanonicalDHCPPool", "interface"):     "envelope /dhcp-servers/pool walked; option detail backstopped by cross-mesh audit",
    ("CanonicalDHCPPool", "network"):       "same; redact_cidr-class IP, audit-backstopped",
    ("CanonicalDHCPPool", "start_ip"):      "same",
    ("CanonicalDHCPPool", "end_ip"):        "same",
    ("CanonicalDHCPPool", "gateway"):       "same",
    ("CanonicalDHCPPool", "dns_servers"):   "same",
    ("CanonicalDHCPPool", "lease_time"):    "same",
    ("CanonicalDHCPPool", "domain_name"):   "same",
    ("CanonicalEvpnType5Route", "vrf"):     "envelope /evpn-type5-routes/route walked; no codec populates today (dead leaf)",
    ("CanonicalEvpnType5Route", "prefix"):  "same (dead leaf; audit-backstopped)",
    ("CanonicalEvpnType5Route", "rt_imports"): "same",
    ("CanonicalEvpnType5Route", "rt_exports"): "same",
    ("CanonicalRADIUSServer", "auth_port"): "defaulted port (1812); non-default audit-backstopped",
    ("CanonicalRADIUSServer", "acct_port"): "defaulted port (1813); audit-backstopped",
    ("CanonicalStaticRoute", "destination"): "the route anchor /routing/static-route IS the destination record",
    ("CanonicalStaticRoute", "gateway"):    "covered implicitly: a dropped gateway usually drops the whole route (11-walker-gap.md §4.3 #29)",
}
```

Each entry is a `(Class, field) -> reason`. The **`KNOWN-GAP:` prefix
convention** makes the PR-2 worklist greppable and makes the
"documented-but-still-silent" leaves visually distinct from the
structurally-correct exemptions. (A reviewer can `grep KNOWN-GAP` to see
the entire deferred backlog at a glance — and a stretch guard, §3.7,
can even assert the count only ever *decreases*.)

### 3.6 The test body

```python
def test_every_model_leaf_is_walked_or_exempt():
    """Every data-bearing CanonicalIntent leaf (recursing into nested
    models) must either be emitted by _walk_canonical (so the live
    validation report can classify it) OR carry a written exemption.

    This is the FORWARD completeness guard the project lacked: the two
    prior coverage checks (test_marker_dict_covers_every_data_bearing_field,
    G5's _FIELD_TO_EXPECTED_XPATH) stop at top-level CanonicalIntent
    fields and never recurse into CanonicalVRRPGroup / CanonicalDHCPPool /
    CanonicalSNMPv3User — exactly where the silent-loss gap concentrates
    (run3 walker-gap §4). A NEW nested leaf added without a walker yield
    + per-codec declaration now turns this red instead of defaulting to
    'supported' (the class kill)."""
    walkable = _WALKABLE  # frozenset(_walk_canonical(_maximal_intent()))
    unhandled = []
    for (cls, field) in _model_leaves():
        if (cls, field) in _WALK_EXEMPT:
            continue
        xpaths = _LEAF_TO_WALKER_XPATHS.get((cls, field))
        if xpaths is None:
            unhandled.append(f"{cls}.{field} (no walker-xpath mapping)")
            continue
        if not any(xp in walkable for xp in xpaths):
            unhandled.append(
                f"{cls}.{field} -> {xpaths} (mapped but walker never emits it)"
            )
    assert not unhandled, (
        "Canonical model leaf/leaves are neither walked by _walk_canonical "
        "nor exempt — they would silently classify 'supported' and any codec "
        "dropping them reports severity:ok (the silent-loss class).  For each: "
        "(1) add a yield in _walk_canonical + per-codec lossy/unsupported "
        "declaration + a _LEAF_TO_WALKER_XPATHS row, OR (2) add a "
        "self-justifying _WALK_EXEMPT entry with a written reason "
        f"(see #149 _SYNTHETIC_NONWALKABLE precedent): {unhandled}"
    )
```

Plus three **"guard the guard"** companions (mirroring the existing
`test_maximal_intent_exercises_every_top_level_field` /
`test_marker_dict_covers_every_data_bearing_field` discipline at
`test_registry_capability_honesty.py:527-557`):

```python
def test_no_stale_walk_exemptions():
    """Every _WALK_EXEMPT key must still be a real model leaf — a leaf
    removed/renamed from the model must drop out of the exemption set,
    else the exemption rots into a lie."""
    real = set(_model_leaves())
    stale = sorted(k for k in _WALK_EXEMPT if k not in real)
    assert not stale, f"_WALK_EXEMPT references non-existent leaves: {stale}"

def test_no_stale_xpath_mappings():
    """Every _LEAF_TO_WALKER_XPATHS key must still be a real model leaf."""
    real = set(_model_leaves())
    stale = sorted(k for k in _LEAF_TO_WALKER_XPATHS if k not in real)
    assert not stale, f"_LEAF_TO_WALKER_XPATHS references dead leaves: {stale}"

def test_exempt_and_mapped_are_disjoint():
    """A leaf is EITHER walked-and-mapped OR exempt, never both — an
    exemption on a walked leaf is dead weight that hides intent."""
    both = sorted(set(_WALK_EXEMPT) & set(_LEAF_TO_WALKER_XPATHS))
    assert not both, f"leaves both mapped AND exempt (pick one): {both}"
```

`test_no_stale_walk_exemptions` is the antidote to the "exemption set
rots" failure mode — it forces the exemption list to track the model.

### 3.7 Optional stretch guard: the backlog only shrinks

```python
def test_known_gap_backlog_does_not_grow():
    """Soft ratchet: the count of KNOWN-GAP exemptions (deferred silent
    losses) must never EXCEED the recorded baseline.  A new KNOWN-GAP
    deferral requires bumping this number in a PR — a visible, reviewable
    act — so the deferred backlog can only be paid down, not quietly
    grown."""
    known_gaps = [k for k, r in _WALK_EXEMPT.items() if r.startswith("KNOWN-GAP")]
    assert len(known_gaps) <= _KNOWN_GAP_BASELINE  # PR-2 lowers this as it walks each
```

This directly answers the seed's "does the exemption list just relocate
the blind spot?" — the `KNOWN-GAP` sub-class is ratcheted-down-only, so
it is a *paydown queue*, not a dumping ground. (Pragmatism review may
judge this gold-plating; I flag it as optional, not load-bearing.)

---

## 4. Why the exemption set does NOT merely relocate the blind spot

This is the crux the reviewers will probe. The #149 precedent
(`test_registry_capability_honesty.py:323-346`,
`_SYNTHETIC_NONWALKABLE` + `_is_legitimate_nonwalkable`) is the proof
that a self-justifying exemption mechanism works in this codebase:

1. **Adding an exemption is a code change in a guarded file**, visible in
   the PR diff, requiring a written reason string. Contrast the status
   quo: adding a leaf and *forgetting* it is **invisible** — no diff in
   the guard, no red CI, silent loss. The guard converts an invisible
   omission into a visible, reviewable decision. That asymmetry IS the
   class kill, even though exemptions exist.
2. **The reason string is challengeable.** A reviewer reading
   `("X","mgmt_ip"): "internal-only, never lost"` can reject a bogus
   justification. #149's entries each carry a `# comment` rationale; the
   project already runs this discipline.
3. **`test_no_stale_walk_exemptions` keeps the set honest** — a leaf
   removed from the model can't leave a zombie exemption behind.
4. **The `KNOWN-GAP:` sub-class is ratcheted** (§3.7) so deferred losses
   are a shrinking queue, not a permanent hiding place.
5. **The exemption set is SMALL and CLOSED in shape**: metadata (7),
   transform-hints (2), discriminators-that-travel (3), envelope-covered
   clusters (audit-backstopped, ~14), and the KNOWN-GAP paydown queue
   (~12). None is an open "I didn't feel like walking this IP" hatch —
   each is a *category* with a structural reason.

The honest residual weakness (for the review agents): a contributor
*could* write a plausible-but-wrong reason and a reviewer *could* miss
it. That is a social-process risk, not a structural one, and it is
strictly better than today (no signal at all). The mitigation is reason
strings + ratchet + the `KNOWN-GAP` paydown queue.

---

## 5. Quantified blast radius

### 5.1 PR-1 (the guard) — to make it GREEN today

- **Code changes to `_walk_canonical`:** ZERO.
- **Matrix changes:** ZERO.
- **phase4 (`tests/unit/audit/`) reclassifications:** ZERO. This is the
  load-bearing quantification, and it is *certain*, not estimated:
  phase4 `reconcile_cell` reads (a) the codec `unsupported`/`lossy`
  declarations and (b) the per-pair `cross_vendor_expectations` YAMLs
  (`test_run_phase4_reconciliation.py:288-308`, the runner at
  `run_phase4_reconciliation.py`). **It never consumes `_walk_canonical`**
  (confirmed: `11-walker-gap.md` §6; `xpath_walker.py:57-60`;
  `run_full_mesh.py:334-335`). PR-1 changes neither matrices nor YAMLs,
  so not a single phase4 cell moves.
- **New test cost:** one new module (~150 lines incl. the two declared
  dicts), the two reflection helpers promoted to a shared util (moved,
  not duplicated). Runs in milliseconds (reflection + one `_walk_canonical`
  call already cached as `_WALKABLE`).
- **Leaves to enumerate in the dicts to go green:** ~112 leaves total
  (`10-model-leaf-census.md` §13). Of these:
  - ~64 are already-walked → `_LEAF_TO_WALKER_XPATHS` rows
    (`11-walker-gap.md` §1: 64 walker xpaths, mapping to ~52 distinct
    `(Class,field)` leaves after de-duping the multi-xpath/reused ones).
  - ~38 go into `_WALK_EXEMPT` (the §3.5 set: metadata 7 + transform 2 +
    discriminators 3 + envelope-clusters ~14 + KNOWN-GAP ~12).
  This is one-time data entry, mechanically derivable from the census +
  walker. **Behavior-change classification: PURE-DECLARATION.** No code
  path changes; no operator-visible output changes.

### 5.2 PR-2 (surgical walk-expansion of §4.1 HIGH leaves) — staged later

Walking each HIGH leaf is the only *behavior-changing* work, and its
phase4 cost is bounded and per-leaf, NOT a storm — because phase4 only
moves when a **matrix declaration** changes, and the walk-expansion adds
declarations deliberately:

| HIGH leaf to walk | populating codecs (from `11-walker-gap.md` §9) | new declarations needed | phase4 effect |
|---|---|---|---|
| VRRP `mode` | nxos(hsrp), opnsense(carp), arista | codecs that flatten mode→vrrp declare `lossy` on `/…/vrrp-groups/group/mode` | the affected pair cells reclassify drifted→EXPECTED_LOSSY (ok), not CODEC_BUG — same pattern as the St3 anycast demotion in MEMORY |
| VRRP `priority`/`preempt`/`advertisement-interval` | junos, mikrotik, opnsense | per-codec `lossy` where dropped | bounded to FHRP-bearing pairs |
| VRRP `authentication` | junos, mikrotik, opnsense | `lossy`/`unsupported` (secret-adjacent → arguably `unsupported`) | bounded |
| VRRP `virtual_ipv6s` | junos, mikrotik, opnsense | `lossy` where dropped | bounded |
| SNMPv3 `priv-passphrase` | arista/aoss/fortigate/mikrotik/junos | the auth twin is ALREADY walked+declared; mirror its declarations | reuses existing per-codec SNMPv3 dispositions; near-zero new |
| SNMPv3 `auth-protocol`/`priv-protocol` | same v3 codecs | `lossy` where downgraded/dropped | bounded |
| IPv6 `scope` | arista | `lossy`/`unsupported` on droppers | single-codec-narrow |
| routing-instance `instance-type` | arista(mac-vrf) | `lossy` where mac-vrf→vrf | single-codec-narrow |

**phase4 reclassification character:** every one of these, when walked +
declared, produces *drifted-against-lossy = EXPECTED_LOSSY (severity ok)*
cells — NOT new CODEC_BUGs — because the declaration is added in the same
PR as the walk. The dangerous direction (CODEC_BUG inflation) only
happens if you walk a leaf WITHOUT declaring it, which the new guard
*prevents* (the leaf can't leave `_WALK_EXEMPT` until it's both walked
and the per-codec declarations exist, or
`test_dropped_naming_independent_field_is_declared` /
`test_static_route_subfield_and_secondary_drops_are_declared` already
fail). **MEMORY precedent:** the St3 anycast `supported→lossy` demotion
broke ONE `tests/unit/audit/` reconciliation test (reconciler reads
matrix anycast decl → drift reclassifies CODEC_BUG→EXPECTED_LOSSY) — so
each HIGH leaf walked in PR-2 needs a regen of `CROSS_MESH_RESULTS.md` +
`PHASE4_RECONCILIATION.md` and a re-run of the FULL `tests/unit` (incl.
`tests/unit/audit`), not just `…/migration`. **LESSON (from MEMORY):
run FULL `tests/unit`, not just `…/migration`.**

**Recommendation: split PR-2 by surface** (one PR for the VRRP cluster,
one for SNMPv3, one for the two single-codec leaves) so each regen diff
is small and narrates one capability delta cleanly (per AGENTS.md
doc-sync row: "a capability-matrix change … regen `CROSS_MESH_RESULTS.md`
+ `PHASE4_RECONCILIATION.md`").

### 5.3 Doc-sync obligations (AGENTS.md)

- PR-1: a new pytest module — `tests/README.md` only if it introduces a
  new marker (it doesn't; it's `pytestmark = pytest.mark.unit`). No
  capability/matrix/operator-doc change. Minimal.
- PR-2: each capability-matrix flip triggers the AGENTS.md rows for
  cross-vendor expectation YAMLs + `CROSS_MESH_RESULTS.md` +
  `PHASE4_RECONCILIATION.md` regen, plus `docs/CAPABILITIES.md` /
  per-vendor `docs/vendors/<vendor>.md` for the surfaced caveat, plus
  `docs/adding-a-canonical-field.md` is unaffected (no new field).

---

## 6. PR sequencing + regen-tool needs

1. **PR-1 — completeness guard (no behavior change, green day one).**
   - Promote `_flatten_annotation` + `_reachable_canonical_models` from
     `test_sanitize.py:662-685` into a shared test-support module; update
     the sanitizer guard import (1-line). (Coordinate with agent 21 —
     the sanitizer IP/host guard wants the SAME helpers; ship the shared
     util in whichever PR lands first, or a tiny precursor PR.)
   - Add `tests/unit/migration/test_walker_completeness.py` with
     `_model_leaves`, `_LEAF_TO_WALKER_XPATHS`, `_WALK_EXEMPT`, the main
     test + the three guard-the-guard tests (+ optional ratchet).
   - **Regen:** none. No matrix/YAML/walker change.
   - **Verify:** `pytest tests/unit/migration/test_walker_completeness.py`
     + the full `tests/unit/migration` (the guard must not perturb peers).
2. **PR-2a — VRRP sub-field walk + declarations.** Walk the 6 VRRP HIGH
   leaves, add per-codec `lossy`/`unsupported`, remove them from
   `_WALK_EXEMPT` + add `_LEAF_TO_WALKER_XPATHS` rows. **Regen:**
   `python tools/run_full_mesh.py --matrix` then
   `python tools/run_phase4_reconciliation.py` (a separate "matrix delta"
   commit per AGENTS.md). **Verify:** FULL `tests/unit` (incl.
   `tests/unit/audit`).
3. **PR-2b — SNMPv3 `priv-passphrase`/protocols.** Same recipe; lower
   phase4 churn (auth twin already declared).
4. **PR-2c — IPv6 `scope` + routing-instance `instance-type`.** Two
   single-codec-narrow walks; smallest regen.

The main thread (not agents) runs the regen tools and commits — per the
seed's hard constraints. Agents propose; the main thread actuates +
verifies against the fixture corpus + full `tests/unit`.

---

## 7. How the recommended fix would have caught the audit-named instances

Decisive scenario test (for `30-review-correctness`): a dev adds
`CanonicalThing.mgmt_ip: str = ""` to a nested model and forgets to walk
it. `_model_leaves()` yields `("CanonicalThing","mgmt_ip")`; it is not in
`_LEAF_TO_WALKER_XPATHS` and not in `_WALK_EXEMPT` →
`test_every_model_leaf_is_walked_or_exempt` FAILS with
`"CanonicalThing.mgmt_ip (no walker-xpath mapping)"`. **Class killed.**

Retrospective: every audit-named instance was a leaf that existed on the
model but wasn't walked — switchport, static-route sub-fields, VXLAN
mcast/flood, VLAN port-membership (#172), VLAN-SVI L3 (#175). For each,
the recursive guard would have flagged the `(Class, field)` the moment it
was added without a yield, *before* the blind audit found it — because it
recurses into nested models, which the two existing top-level-only guards
never did. (The VLAN-SVI #175 case is the cleanest proof: the leaf is
`CanonicalIPv4Address.ip` reused on the VLAN — the guard's tuple-mapping
`("CanonicalIPv4Address","ip") -> ("/interfaces/.../ip", "/vlans/.../ip")`
makes "is the VLAN copy walked?" an explicit, guarded question.)

---

## 8. Coordination notes

- **Agent 21 (sanitizer guard):** we both reuse
  `_reachable_canonical_models` + `_flatten_annotation`. Recommend ONE
  shared test-support module (`tests/support/canonical_reflection.py` or
  `tests/unit/migration/_model_reflection.py`); pick the home in
  synthesis. The class-1 leaf-enumeration (`_model_leaves`,
  scalar-vs-nested) is identical machinery to your IP/host field
  enumeration — only the *predicate* differs (walked-or-exempt vs
  redacted-or-exempt). Consider a single `_model_leaves()` consumed by
  both guards.
- **Agent 22 (typed-marker):** if a typed marker (`Annotated[str,
  IPField()]`) is adopted, the class-1 guard does NOT need it — the
  walker-coverage question is "is the leaf walked," which is
  field-name-independent, so the marker buys class-1 nothing the
  `(Class,field)` map doesn't already give. Class-1's case for a marker
  is weak; the `_LEAF_TO_WALKER_XPATHS` declared map is the natural shape
  because xpath spelling is irregular (config/ segment, VXLAN element
  collapse, VLAN reuse) and no marker encodes spelling. Recommend the
  marker (if any) be scoped to class-2 (sanitizer) where the predicate is
  "is this IP/secret-bearing," which a marker answers cleanly.
- **`30-review-correctness`:** the decisive synthetic-new-leaf test is
  §7. Probe whether `_LEAF_TO_WALKER_XPATHS` is a second blind spot —
  my answer: no, because a leaf missing from BOTH map and exemption
  fails (§3.4 design note).
- **`31-review-pragmatism`:** the minimal version is PR-1 alone (~150
  lines, zero behavior change, zero phase4). PR-2 is the
  honor-the-user-intent cleanup of the worst instances and is
  *stageable/deferrable* — the guard documents every deferral as a
  `KNOWN-GAP` exemption, so deferring PR-2 is honest, not a hidden gap.
  The optional `KNOWN-GAP` ratchet (§3.7) is the one piece I flag as
  possibly gold-plating.

---

## 9. Citations index (file:line)

- Walker yields + the gap: `netcanon/migration/canonical/xpath_walker.py:62-256`.
- Default-to-supported: `netcanon/models/migration.py:221-228`;
  unwalked-leaf-never-classified: `netcanon/services/migration_validate.py:28-45, 80-87`.
- Reflection engine (reuse): `tests/unit/tools/test_sanitize.py:662-685`
  (`_flatten_annotation`, `_reachable_canonical_models`), proven against
  pydantic v2 + `from __future__ import annotations` by the passing
  `test_reverse_no_unregistered_secret_field` (`:743-767`).
- `_WALKABLE` kitchen-sink universe: `tests/unit/migration/test_registry_capability_honesty.py:132-225`.
- The #149 self-justifying-exemption precedent: same file `:323-346`
  (`_SYNTHETIC_NONWALKABLE`, `_is_legitimate_nonwalkable`).
- The two existing TOP-LEVEL-ONLY forward checks (the hole this fills):
  `test_marker_dict_covers_every_data_bearing_field` (same file `:527-541`,
  reflects `set(CanonicalIntent.model_fields)` — no recursion);
  G5 `_FIELD_TO_EXPECTED_XPATH` (`tests/unit/migration/codecs/cisco_iosxe_cli/test_walk_canonical_coverage.py:165-208`).
- phase4 reads matrices+YAMLs, NOT the walker (PR-1 = zero phase4 churn):
  `tests/unit/audit/test_run_phase4_reconciliation.py:288-308`;
  `tools/run_full_mesh.py:334-335`.
- The HIGH gap-leaf population (grep-confirmed): see `11-walker-gap.md`
  §9 (VRRP/SNMPv3/IPv6-scope/instance-type populating codecs + parse.py
  line cites).
- The full leaf census denominator (~112 leaves): `10-model-leaf-census.md` §13.

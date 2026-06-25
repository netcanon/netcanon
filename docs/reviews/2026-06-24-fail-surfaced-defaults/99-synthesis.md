# 99 — Synthesis + decision (main thread)

**Run:** 2026-06-24 · fail-surfaced-defaults · netcanon
**Author:** main thread (Claude), after reading all 8 agent reports.
**Both reviews:** GO-WITH-FIXES. No NO-GO.

---

## The decision in one paragraph

Kill both recurring classes with **two reflection-driven completeness GUARDS**
(CI tests, **zero runtime change, zero phase4 movement**), plus a tiny shared
reflection module. Each guard triggers on **field existence** — the only
mechanism faithful to "fail-surfaced *defaults*" (a newly-added field defaults
to CI-red until consciously handled-or-exempted). **Decline** the runtime
blanket `ip_address()` rule (form A) and the typed marker (form C). **Defer**
all instance-cleanup (walking the HIGH gap leaves; wiring MAC + static-route
redaction) — the guards make every current gap a *visible, tracked* exemption,
which is the class-kill the user asked for; the cleanups are safe follow-ups the
guards now force.

## Why not form A (runtime blanket `ip_address()`) — MF-9, stated for the user

The user's verbatim goal named "redact on `ip_address()` of ANY IP-typed field,
not an allow-list." We are **declining the literal runtime form** because both
the sanitizer-gap analysis (12) and both designs (21/22) show it is
(a) **insufficient** — `ip_address()` is blind to MACs, RD/RT (`64496:N`),
multicast, communities, hashes, hostnames, and CIDR fields (which raise on bare
`ip_address()`); it would have to be bolted onto the existing 41 redaction sites,
not replace them; and (b) **the wrong altitude** — the leak class is "a new field
is forgotten" (a *coverage* defect caught best at test time), not a runtime
behavior defect. The user's *instinct* — "ANY field, not a curated subset" — is
exactly right and is delivered by the existence-triggered guard, which fails-RED
on any unhandled field rather than silently redacting only the bare-IP subset.

## Class-1 (silent capability-loss) — walker completeness guard

Adopt agent 20's **design B** (recursive reflection guard). The gap concentrates
in *nested* model sub-leaves (VRRP group, DHCP pool, SNMPv3 user, EVPN-Type5);
the two existing forward-coverage checks both stop at top-level `CanonicalIntent`
fields and never recurse — that is the precise hole. The guard recurses through
`model_fields` into nested models and FAILS when a scalar leaf is neither walked
(emits an xpath in `_WALKABLE`) nor in a self-justifying exemption set.

Applied fixes from review:
- **MF-1 (pragmatism): drop the ~52-row `_LEAF_TO_WALKER_XPATHS` spelling map.**
  Derive walked-ness by a tolerant kebab/suffix match of the field name against
  `_WALKABLE`, keeping only a *small* `_SPELLING_OVERRIDE` for the genuine
  irregulars (the reused VLAN-SVI `ip`, VXLAN element collapse). The only
  hand-maintained list is the *exemption* set (the meaningful one). Tolerant
  false-"walked" is backstopped by the existing render-reparse value-survival
  guards.
- **MF-1 (correctness): structured exemption reason CODES**, not free text — a
  small `Literal[...]` (`METADATA`, `TRANSFORM_HINT`, `DISCRIMINATOR_TRAVELS`,
  `ENVELOPE_AUDIT_BACKSTOPPED`, `KNOWN_GAP`) + a free-text note. No honest code
  fits "a leaf I didn't want to walk," so the lazy-exempt path has no green door.
- **MF-3 (correctness): unit-test the leaf enumerator itself** against a tiny
  synthetic model (scalar / list[scalar] / nested-model / dict / `Literal`).
- **MF-2 (pragmatism): drop the KNOWN-GAP ratchet** (hard-coded count; machinery
  vs a social risk). The `KNOWN_GAP` reason code is greppable; that suffices.
- **MF-3 (pragmatism) / PR-2 deferral:** do **not** walk the HIGH gap leaves in
  this run — that is behavior-changing + phase4-sensitive (the St3 precedent). The
  ~11 HIGH leaves ship as `KNOWN_GAP` exemptions (visible, tracked). Walk-expansion
  is a separate later per-surface wave.

## Class-2 (sanitizer-bypass) — existence-partition guard (the fork, resolved)

The reviewers split: correctness (30) showed agent 21's **name-regex** guard
PASSES a deceptively-named new IP field (`peer: str`) — it relocates the blind
spot to the regex token list, so it does **not** kill the class; it demanded
agent 22's **typed marker + unmarked-string meta-guard**. Pragmatism (31) showed
the typed marker is over-engineering — a new contributor discipline that fails
silently when forgotten, whose required meta-guard exemption set grows on the
*common* change (adding a descriptive string field).

**Resolution (a HYBRID neither stated outright):** adopt correctness's
*existence trigger* without pragmatism's-objected *typed marker*. The guard
partitions **every `str`/`list[str]` leaf** reachable from `CanonicalIntent` into
exactly one of three reason-coded sets:

1. `_SENSITIVE_REDACTED` — redacted by `sanitize_intent` today (verified by the
   forward sentinel; reuses the existing `_REGISTERED_SECRET_FIELDS` + an IP set).
2. `_SENSITIVE_GAP` — sensitive but redaction not yet wired (the 4 MAC fields +
   `static_routes[].destination`); reason `KNOWN_GAP`, tracked.
3. `_NON_SENSITIVE` — genuinely non-sensitive free-text/enum/identifier
   (`description`, `mode`, `interface_type`, …); structured reason code.

The class-killer: a NEW `str` leaf (e.g. `peer: str` holding an IP) is in **none**
of the three → guard FAILS naming `(Class, field)`. This triggers on *existence*
(faithful; catches the S4 deceptive-name case the regex misses) and needs **no
typed marker** (no `Annotated[str, Sensitive(...)]`, no new contributor idiom — a
field is classified by adding it to one of three reviewed sets, the binary
decision the goal demands). The registries double as documentation of what the
sanitizer covers.

Why this beats both standalone recommendations:
- vs regex (21): regex triggers on *name* → blind to `peer: str`. Existence
  partition triggers on *name-independent existence* → catches it. (correctness)
- vs marker (22): no per-field annotation discipline; the "is this sensitive?"
  decision lives in three small reviewed sets, not a marker a contributor forgets
  silently. The `_NON_SENSITIVE` set growth is the *accepted, safe* cost of
  existence-triggering (over-flag-safe ≫ under-redact-unsafe) — and it is the
  unavoidable price of catching S4, which the user's goal demands. (pragmatism's
  marker objection addressed; its growth objection accepted as the cost of
  faithfulness.)
- **MF-1 (correctness): structured reason codes** on the exemption/gap sets, so a
  sensitive field cannot be lazily dumped into `_NON_SENSITIVE`.
- Keep the existing secret guard untouched (it ships green); the new partition
  guard subsumes its coverage as a superset and is additive.

Deferred (MF-4/MF-6): the typed marker (declined; reserved escalation **if** a
real IP/secret field ever ships with a non-indicative name); `redact_mac` +
docs-MAC-range + the vMAC-preservation question; the `static_routes[].destination`
`redact_cidr` wire. All three are documented `KNOWN_GAP`s the guard now surfaces.

## Shared util (MF-10)

Extract `_flatten_annotation` + `_reachable_canonical_models` from
`test_sanitize.py` to `tests/support/canonical_reflection.py` (+ the leaf
enumerators + the MF-3 enumerator unit test). Both guards + the existing secret
guard import it. Folded into the class-1 PR (the full suite verifies the move did
not break the secret guard — the move is two functions).

## What ships this run (PRs)

- **PR-A (class-1 + shared util):** `tests/support/canonical_reflection.py`
  (reflection + leaf enumerators + enumerator unit test) + update
  `test_sanitize.py` imports + `tests/unit/migration/test_walker_completeness.py`
  (the walker completeness guard + guard-the-guard tests + KNOWN_GAP exemptions).
  Zero runtime change, zero phase4.
- **PR-B (class-2):** the existence-partition sanitizer guard added to
  `test_sanitize.py`. Zero runtime change, zero phase4.

Both are test-only ⇒ merge-on-green autonomous (not release-pipeline). Each is
verified by (1) full `tests/unit` green and (2) a **synthetic-leaf-injection
proof** — temporarily add an unhandled leaf and confirm the guard goes RED — to
demonstrate the class-kill (not just that it is green today).

## Deferred follow-ups (the guards now force/track these)

| Item | Why deferred | Tracked as |
|---|---|---|
| Walk the ~11 HIGH gap leaves (VRRP mode/priority/preempt/adv-int/auth/v6-VIP; SNMPv3 priv-passphrase/protocols; IPv6 scope; routing-instance instance-type) | behavior-changing + phase4 regen (St3 precedent) | class-1 `KNOWN_GAP` exemptions |
| `redact_mac` + 4 MAC sites | new primitive + docs-range + vMAC-preservation design Q + 3-target doc-sync; latent (never-observed) leak | class-2 `_SENSITIVE_GAP` |
| `static_routes[].destination` `redact_cidr` wire | trivial but a runtime change; keep the guard PRs zero-runtime | class-2 `_SENSITIVE_GAP` |
| Typed marker | over-engineering for the current model's naming discipline | reserved escalation |

# 22 — Fail-surfaced BY CONSTRUCTION: the typed-marker design

**Agent:** `22-design-typed-marker` · Phase 2 (Design) · read-only
**Run:** 2026-06-24 · fail-surfaced-defaults · netcanon
**Question I own:** annotate IP/host-bearing + secret-bearing canonical fields
with a *typed marker* so the walker, the sanitizer, AND the guards can
**mechanically enumerate** the relevant leaves from the model itself — no
hand-maintained list. Show the exact annotation mechanism that survives
pydantic v2 + `from __future__ import annotations`; assess churn; decide whether
it SUBSUMES or merely complements the guard tests (`20`/`21`); and give an
HONEST over-engineering verdict vs. the lighter reflection guard (form B).

---

## 0. TL;DR / verdict

- **The mechanism works and is reliable.** I prototyped it against the installed
  pydantic (2.13.0) under `from __future__ import annotations`: a frozen
  dataclass placed inside `Annotated[...]` is retrievable at runtime via
  `Model.model_fields[name].metadata` (filter by `isinstance`). It coexists
  cleanly with `Field(ge=, le=, default_factory=)` constraints, with `str | None`
  unions, and with `list[str]` containers; it does **not** alter
  `model_dump`, `model_dump_json`, or `model_json_schema`. So "introspect the
  marker reliably" — the load-bearing risk in my brief — is **confirmed, not
  hypothetical** (§2, with the prototype transcript).

- **For class-2 (sanitizer): the marker is a real improvement but NOT
  required.** Agent `12` is right that the naming heuristic (`_IP_HOST_NAME_RE` /
  `_SECRET_NAME_RE`) already works because every IP/secret field in *this* model
  happens to have an IP-ish / secret-ish name. The marker's payoff over the
  heuristic is narrow: it removes the false-positive exemption list
  (`source_interface`, `interface`) and the false-negative risk (a future field
  named e.g. `peer` or `endpoint` that the regex misses). That risk is the SAME
  covered-subset disease one level up — **the regex is itself a hand-maintained
  pattern that the next blind audit could find a hole in.** That is the honest
  case FOR the marker. But it is a *medium*-strength case, not decisive.

- **For class-1 (walker): the marker does NOT solve the actual problem and is
  the wrong tool.** The walker gap (agents `10`/`11`) is about *structural
  coverage* of EVERY data-bearing leaf — VRRP `priority`/`preempt`, DHCP
  `lease-time`, SNMPv3 `auth-protocol`, routing-instance `instance-type` — most
  of which are **neither IP nor secret**. An IP/secret marker enumerates the
  wrong subset. A walker completeness guard (agent `20`'s form B) needs to reflect
  over *all* leaves and check each is walked-or-exempt; a marker keyed to
  IP/secret semantics is orthogonal to that. (A *different* marker — "walkable /
  declared / exempt" — would just be a more verbose spelling of the exemption
  list the guard already needs. §6.)

- **RECOMMENDED minimal version (the "most value, least churn" cut):** introduce
  **ONE** marker family, `Sensitive(...)`, with a `kind` discriminator
  (`"ipv4"` / `"ipv6"` / `"cidr"` / `"host"` / `"mac"` / `"secret"`), annotate
  the **~31 IP/host + ~7 secret leaves** the census found, and let BOTH
  sanitizer-side guards (agent `21`) enumerate covered leaves from the marker
  set instead of from a `_REGISTERED_*` literal + a naming regex. This **subsumes
  the existing secret guard** (`TestSecretRedactionCoverage`) and the proposed IP
  half into one model-derived source of truth, and it makes the sanitizer's
  *redaction-primitive dispatch* derivable from the `kind` too (a bonus the
  heuristic can't give). It is ~38 one-line annotation edits + a ~25-line
  `markers.py` module + a rewrite of the two coverage guards to read the marker
  set. **It does NOT touch the walker** — class-1 stays with agent `20`'s
  completeness guard.

- **Net verdict: WORTH IT for class-2 (sanitizer) in the minimal form above;
  NOT worth it for class-1 (walker); so "both" is wrong and "neither" is wrong —
  the answer is class-2 only.** Whether even class-2 should adopt the marker vs.
  the lighter agent-`21` guard is a genuine judgement call that I lay out
  explicitly in §7 with the decisive tie-breaker: **the marker eliminates the
  naming-regex blind spot (the disease itself), the guard does not.** I lean
  marker, but flag it as the kind of decision the main thread / reviewers
  (`30`/`31`) should ratify, not something to ram through.

---

## 1. What "by construction" means here, and the bar it must clear

The user's literal goal: *"the sanitizer redacts on `ip_address()` of ANY
IP-typed field, not an allow-list."* The marker design is the principled
realisation of "IP-**typed** field": instead of inferring IP-ness from the
*value* at runtime (`ip_address()`, which agent `12` shows is both insufficient —
blind to MAC/RD/RT/community/hash — and the wrong altitude) or from the *name* at
test time (the regex, which is a hand-maintained pattern), we declare IP-ness /
secret-ness **on the field, in the model**, once. Every consumer that needs "the
set of sensitive leaves" then derives it mechanically.

For this to count as a genuine *fail-surfaced default* (and not just a
prettier allow-list), it must clear three bars:

1. **Enumerable at runtime/test-time** from the model with no parallel list to
   keep in sync. ✅ confirmed §2.
2. **A new sensitive field is RED by default** — i.e. forgetting the marker, OR
   adding the marker but forgetting the redaction, FAILS CI. This is where the
   marker *needs a companion guard* — the marker alone does not fail anything;
   it is the guard reading the marker that fails. So the marker does not
   *replace* the guard, it *re-bases* the guard onto a sounder source of truth.
   (This is the single most important nuance and the reason "marker subsumes the
   guard" is half-true — §4.)
3. **The exemption set must not relocate the blind spot.** The marker's headline
   advantage is that for class-2 it *shrinks the exemption set to near-zero*
   (§4.3), which is a real answer to the `30`/`31` "does the exemption list just
   move the problem" critique.

---

## 2. The exact mechanism (pydantic v2 + `from __future__ import annotations`)

### 2.1 The marker class

A frozen dataclass is the right carrier: it is hashable (usable in sets), cheap,
introspectable by `isinstance`, and (unlike a pydantic `Field(json_schema_extra=)`
hack) does not leak into the JSON schema or serialization. Proposed
`netcanon/migration/canonical/markers.py`:

```python
"""Typed field markers — make IP/secret-bearing canonical leaves
mechanically enumerable from the model itself (fail-surfaced by
construction).  A marker placed inside ``Annotated[...]`` is invisible
to pydantic validation/serialisation/JSON-schema and is read back at
test time via ``Model.model_fields[name].metadata``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SensitiveKind = Literal["ipv4", "ipv6", "cidr", "host", "mac", "secret"]


@dataclass(frozen=True)
class Sensitive:
    """Marks a canonical leaf as carrying network-identifying or secret
    data, so the sanitiser-coverage guards can enumerate the complete
    set from the model (no hand-maintained allow-list) and — optionally —
    the sanitiser can dispatch the right redaction primitive from ``kind``.

    kind:
      "ipv4"   – bare IPv4 literal           → redact_ipv4 / redact_ip_string
      "ipv6"   – bare IPv6 literal           → redact_ipv6 / redact_ip_string
      "cidr"   – addr/prefix                 → redact_cidr
      "host"   – IP **or** DNS host/domain   → redact_ip_string (host passes through, by design)
      "mac"    – MAC / network id            → (future) redact_mac
      "secret" – passphrase/hash/community/key → redact_secret / redact_hash / ...
    """
    kind: SensitiveKind
```

I deliberately use **one** marker class with a `kind` discriminator rather than
six marker classes (`IPField`, `SecretField`, …). Reasons: (a) the guards do a
single `isinstance(x, Sensitive)` filter; (b) the `kind` carries the
redaction-primitive choice, which is information the naming regex can NEVER give
(the regex can't tell `network` should use `redact_cidr` while `gateway` uses
`redact_ip_string`); (c) it is one import, one symbol, one doc paragraph.

### 2.2 Proof it is introspectable (prototype transcript)

I ran this against the repo's pydantic (2.13.0) with `from __future__ import
annotations` active — the exact conditions the real model runs under:

```
Root.gateway:     annotation=str        metadata=[IPField(kind='ip')]      markers=[IPField...]
Root.dns_servers: annotation=list[str]  metadata=[IPField(kind='ip')]      markers=[IPField...]
Root.community:   annotation=str        metadata=[SecretField(kind='...')] markers=[SecretField...]
Root.subs:        annotation=list[Sub]  metadata=[]                        markers=[]
Root.name:        annotation=str        metadata=[]                        markers=[]
Sub.ip:           annotation=str        metadata=[IPField(kind='ip')]      markers=[IPField...]
```

Key confirmations from the four prototype runs I executed:

- **`metadata` is populated even under `from __future__ import annotations`.**
  Pydantic resolves the `Annotated[...]` form at class-build time and stashes the
  non-type args in `FieldInfo.metadata`. The string-ised annotation does NOT
  defeat this (pydantic resolves it; we never call `get_type_hints` ourselves).
- **`list[str]` carries the marker at the FIELD level** while `.annotation`
  resolves to `list[str]`. So `dns_servers: Annotated[list[str], Sensitive("host")]`
  is enumerable as a host-bearing leaf with one annotation — no need to descend
  into the list arg.
- **Coexists with pydantic constraints**: `Annotated[int, Field(ge=1, le=255)]`
  shows `metadata=[Ge(1), Le(255)]`; adding `Sensitive(...)` alongside leaves
  both present and **the `ge/le` validation is still enforced** (I confirmed a
  `ValidationError` on out-of-range). So markers and constraints compose.
- **Unions work**: `Annotated[str | None, Sensitive("host")]` keeps the marker
  and `.annotation == str | None`.
- **Reused models collapse correctly**: `CanonicalIPv4Address.ip` marked once is
  enumerated as ONE `(Class, field)` pair even though it appears on both
  `CanonicalInterface` and `CanonicalVlan`. This is *exactly right* — the marker
  rides the model, so it covers every xpath the model is mounted at with a
  single edit. (Contrast the per-xpath naming regex, which is xpath-agnostic and
  also gets this right, but contrast the per-xpath `_REGISTERED_*` literals which
  must list both surfaces.)
- **Zero serialization/schema impact**: `model_json_schema()` properties
  unchanged; `model_dump_json()` byte-identical. So **no existing serialization
  test, API contract, or fixture can break from adding markers** — a critical
  property for a low-risk change.

### 2.3 The enumeration helper (reuses the existing reflection engine)

The reflection machinery already exists in `tests/unit/tools/test_sanitize.py`
(`_reachable_canonical_models` + `_flatten_annotation`,
`test_sanitize.py:662–685`) and is *already proven* to handle pydantic v2 +
future-annotations + `list[...]` + unions + nested models. The marker enumerator
is a ~10-line addition on top of it (test-side, or promoted to a small shared
helper so the sanitiser can reuse it too):

```python
from netcanon.migration.canonical.markers import Sensitive

def iter_sensitive_leaves(root_cls):
    """Yield (Class.__name__, field_name, kind) for every Sensitive-marked
    leaf reachable from root_cls."""
    for model in _reachable_canonical_models(root_cls):
        for fname, fld in model.model_fields.items():
            for m in fld.metadata:
                if isinstance(m, Sensitive):
                    yield (model.__name__, fname, m.kind)
```

That is the entire "enumerate every IP-typed leaf from the model itself"
capability the seed asked for, in 10 lines, with a build-time-proven engine.

---

## 3. What gets annotated (the churn, exactly)

Grounded in agent `10`'s census (≈31 IP/host leaves, ≈7 secret leaves) and
`12`'s allow-list. The annotation is a one-token edit per field. Below is the
complete annotation roster — this IS the churn estimate (38 field edits across
12 model classes in one file, `intent.py`).

### 3.1 Secret leaves (kind="secret") — 7 edits

| `Class.field` | current | becomes |
|---|---|---|
| `CanonicalLocalUser.hashed_password` | `str = ""` | `Annotated[str, Sensitive("secret")] = ""` |
| `CanonicalSNMP.community` | `str = ""` | `Annotated[str, Sensitive("secret")] = ""` |
| `CanonicalSNMPv3User.auth_passphrase` | `str = ""` | `Annotated[str, Sensitive("secret")] = ""` |
| `CanonicalSNMPv3User.priv_passphrase` | `str = ""` | `Annotated[str, Sensitive("secret")] = ""` |
| `CanonicalSNMPv3User.engine_id` | `str = ""` | `Annotated[str, Sensitive("secret")] = ""` |
| `CanonicalRADIUSServer.key` | `str = ""` | `Annotated[str, Sensitive("secret")] = ""` |
| `CanonicalVRRPGroup.authentication` | `str = ""` | `Annotated[str, Sensitive("secret")] = ""` |

Note `engine_id` is marked `secret` here even though the existing secret guard
does NOT register it (it isn't *named* like a secret — agent `12` §6). **This is
the marker's first concrete win: it captures `engine_id` that the naming regex
structurally cannot**, because IP/secret-ness is now declared, not inferred from
the name.

### 3.2 IP / host / cidr / mac leaves — ~31 edits

| `Class.field` | kind | redaction primitive (today) |
|---|---|---|
| `CanonicalIntent.domain` | `host` | `redact_domain` |
| `CanonicalIntent.dns_servers[]` | `host` | `redact_ip_string` |
| `CanonicalIntent.ntp_servers[]` | `host` | `redact_ip_string` |
| `CanonicalIntent.syslog_servers[]` | `host` | `redact_ip_string` |
| `CanonicalIntent.anycast_gateway_mac` | `mac` | (not redacted today — latent) |
| `CanonicalIPv4Address.ip` | `ipv4` | `redact_ipv4` |
| `CanonicalIPv4Address.virtual_gateway_address` | `ipv4` | `redact_ipv4` |
| `CanonicalIPv4Address.virtual_gateway_mac` | `mac` | (not redacted today — latent) |
| `CanonicalIPv6Address.ip` | `ipv6` | `redact_ipv6` |
| `CanonicalIPv6Address.virtual_gateway_address` | `ipv6` | `redact_ipv6` |
| `CanonicalIPv6Address.virtual_gateway_mac` | `mac` | (not redacted today — latent) |
| `CanonicalStaticRoute.destination` | `cidr` | (NOT redacted today — the one real modelled leak, `12` §4b) |
| `CanonicalStaticRoute.gateway` | `host` | `redact_ip_string` |
| `CanonicalDHCPPool.network` | `cidr` | `redact_cidr` |
| `CanonicalDHCPPool.start_ip` | `ipv4` | `redact_ip_string` |
| `CanonicalDHCPPool.end_ip` | `ipv4` | `redact_ip_string` |
| `CanonicalDHCPPool.gateway` | `host` | `redact_ip_string` |
| `CanonicalDHCPPool.dns_servers[]` | `host` | `redact_ip_string` |
| `CanonicalDHCPPool.domain_name` | `host` | `redact_domain` |
| `CanonicalSNMP.trap_hosts[]` | `host` | `redact_ip_string` |
| `CanonicalRADIUSServer.host` | `host` | `redact_ip_string` |
| `CanonicalVRRPGroup.virtual_ips[]` | `ipv4` | `redact_ip_string` |
| `CanonicalVRRPGroup.virtual_ipv6s[]` | `ipv6` | `redact_ip_string` |
| `CanonicalVRRPGroup.virtual_mac` | `mac` | (not redacted today — latent) |
| `CanonicalVxlan.mcast_group` | `ipv4` | `redact_mcast_group` |
| `CanonicalVxlan.flood_list[]` | `ipv4` | `redact_ip_string` |
| `CanonicalRoutingInstance.route_distinguisher` | `host` | `redact_route_target` |
| `CanonicalRoutingInstance.rt_imports[]` | `host` | `redact_route_target` |
| `CanonicalRoutingInstance.rt_exports[]` | `host` | `redact_route_target` |
| `CanonicalEvpnType5Route.prefix` | `cidr` | `redact_cidr` |
| `CanonicalEvpnType5Route.rt_imports[]` / `.rt_exports[]` | `host` | `redact_route_target` |

The roster surfaces **three latent gaps the naming regex would also have to
hand-handle, but the marker handles for free** by forcing a decision at
annotation time:

1. **MAC fields** (`anycast_gateway_mac`, `virtual_gateway_mac` ×3,
   `virtual_mac`) are network-identifying and **not redacted today** (agent `12`
   §5b.3). The marker forces them into the covered set with `kind="mac"`; the
   blanket `ip_address()` rule is structurally blind to them.
2. **`static_routes[].destination`** — the one genuinely-unredacted modelled IP
   leaf (`12` §4b). Marking it `cidr` makes the guard demand a redaction, which
   is a 1-line `redact_cidr` wire-up (identical to `dhcp.network`).
3. **`engine_id`** — secret-redacted but not secret-*named* (§3.1).

The `kind` for RD/RT is `host` (not `cidr`/`ipv4`) because RD/RT have their own
stable-correlation primitive `redact_route_target`; the marker's `kind` is a
*hint*, and the guard's dispatch table maps `("CanonicalRoutingInstance",
"route_distinguisher")` to `redact_route_target` explicitly where the kind is
insufficient. (See §4.2 — the marker does NOT try to fully encode the primitive;
it encodes the *category* and the guard owns the dispatch.)

**Total churn: ~38 one-line field annotations in one file + one ~25-line
`markers.py` + import line. Zero behaviour change at the model layer.**

---

## 4. Does it SUBSUME the guards, or only complement them?

This is the crux of my brief. Honest answer: **it re-bases (improves the source
of truth of) the class-2 guards and lets one guard family replace two; it does
NOT eliminate the need for a guard.**

### 4.1 The marker alone fails nothing

Adding `Sensitive("secret")` to a field does not, by itself, make CI red if the
sanitiser forgets to redact it. *A guard reading the marker* is what fails. So
the marker is necessary-but-not-sufficient; it must be paired with:

- **Forward guard** (sentinel round-trip): populate every marked leaf with a
  unique sentinel, sanitise, assert no sentinel survives. This is the existing
  `test_forward_no_registered_secret_survives` (`test_sanitize.py:691`)
  generalised to iterate the marker set instead of the literal
  `_REGISTERED_SECRET_FIELDS`.
- **Reverse guard** (coverage): every marked leaf must have a redaction
  dispatch entry. With markers this becomes "every `Sensitive`-marked leaf is in
  the sanitiser's dispatch map," which is mechanical and exemption-free.

### 4.2 How the marker re-bases agent `21`'s guard (the win)

Agent `12`/`21`'s form-B guard has THREE hand-maintained artefacts:
`_REGISTERED_SECRET_FIELDS` (literal set), `_SECRET_NAME_RE` + the proposed
`_IP_HOST_NAME_RE` (naming regexes), and `_IP_NAME_EXEMPT` (false-positive
exemptions for IP-ish names that aren't IPs). The marker design **collapses all
three into one**: the marker set on the model. The guard becomes:

```python
def test_every_sensitive_leaf_is_redacted_and_no_unmarked_leaf_leaks():
    # 1. coverage: every marked leaf must have a dispatch entry (no exemption list)
    marked = {(c, f) for c, f, _ in iter_sensitive_leaves(CanonicalIntent)}
    undispatched = marked - set(_REDACTION_DISPATCH)
    assert not undispatched, (
        f"Sensitive-marked canonical leaf with no redaction primitive — "
        f"wire it into sanitize_intent + add to _REDACTION_DISPATCH: {undispatched}")
    # 2. forward: sentinel round-trip over the marked set (unchanged in spirit)
    ...
```

This is strictly better than the regex form on the dimension the WHOLE RUN is
about: **the regex is itself a covered-subset (a hand-maintained pattern), so a
future field named in a way the regex doesn't anticipate (`peer_address`?
`endpoint`? `vtep`? `nexthop`?) re-opens the exact blind spot.** The marker
cannot have that failure mode because IP/secret-ness is *declared on the field*,
not *guessed from the field name*.

### 4.3 The exemption-relocation answer (decisive for `30`/`31`)

The single sharpest critique reviewers `30`/`31` will raise about ANY guard is
"the exemption list just relocates the blind spot." The marker's answer is the
strongest available:

- **Naming-heuristic guard (agent `21` form B):** needs `_IP_NAME_EXEMPT`
  (`source_interface`, `interface`, … — fields that *look* IP-ish but aren't).
  This exemption set GROWS as the model grows and is an open escape hatch ("I
  didn't want to redact this").
- **Marker guard:** the only "exemption" is *not putting a marker on a field*,
  which is the default. There is no exemption LIST. The reverse direction is
  inverted: instead of "this IP-named field is exempt because it's not really an
  IP," the dangerous direction would be "someone forgot to mark a real IP
  field." That residual risk is real (§5) but it is the SAME residual the regex
  has (a regex also misses an un-anticipated name), and the marker at least makes
  the omission a *reviewable single-line decision at the field* ("why is this
  `str` field unmarked?") rather than buried in a regex token list.

So: **the marker shrinks class-2's hand-maintained surface from {literal set +
regex + exemption list} to {markers on the model}.** That is a genuine reduction
of the covered-subset disease for class-2, not a relocation. This is the
strongest single argument in the marker's favour and the one the synthesis should
weigh.

### 4.4 It does NOT subsume the walker guard (class-1)

The walker completeness guard (agent `20`) must check *every data-bearing leaf*
is walked-or-exempt — `priority`, `preempt`, `lease_time`, `instance_type`,
`auth_protocol`, etc., which are not IP/secret. The `Sensitive` marker
enumerates a *different, smaller* subset. So the marker contributes **nothing**
to closing the walker gap. (You could imagine a second marker `Walkable`/
`NonWalkable`, but that just re-spells the exemption list agent `20`'s guard
needs anyway — and would mean marking ~100+ leaves, most as "yes walk me," which
is pure noise. §6.)

---

## 5. Honest assessment: over-engineering vs. agent `21`'s lighter guard

I was asked to be honest about whether this is gold-plating. Here is the
two-sided ledger.

### Arguments it IS over-engineering (the `12`/`21` position)
- The naming heuristic **already works** for every field in the current model;
  agent `12` verified every IP/secret leaf has an IP-ish/secret-ish name.
- The exemption set for naming false-positives is **tiny** (2 entries).
- A ~40-line guard reusing the existing reflection engine is the cheapest
  durable fix and ships with zero model churn.
- Markers add a new concept (`markers.py`, the `Annotated` idiom) that every
  future contributor adding a field must learn and remember — a *new* discipline
  to keep honest, which is itself a maintenance tax.
- The `from __future__ import annotations` + `Annotated` interaction, while
  proven to work, is subtle; a contributor who writes `gateway: str = ""` and
  forgets the `Annotated` wrapper gets NO error from pydantic (the field just
  isn't marked) — so the marker can be silently *omitted*, which is the very
  failure mode we're trying to kill.

### Arguments it is NOT over-engineering (the case FOR)
- **The naming regex is itself an instance of the disease.** This run exists
  because hand-maintained subsets keep springing leaks. `_IP_HOST_NAME_RE` is a
  hand-maintained subset of *name patterns*. The marker is the only form that
  removes the heuristic entirely. If the synthesis takes the meta-finding
  seriously ("durable fix = fail-surfaced defaults, NOT a covered subset"), the
  regex guard is philosophically the *same shape* as the bug.
- **The marker carries the redaction-primitive category** (`kind`), enabling the
  sanitiser dispatch to be model-derived too — the regex cannot do this. (This
  is optional but it means `static_routes[].destination` and any future `cidr`
  field auto-route to `redact_cidr` instead of needing a hand-coded branch.)
- **It captures `engine_id`, the MACs, and `destination`** — three things the
  naming regex / blanket rule structurally miss — *for free*, by forcing the
  decision at the field.
- **Zero serialization/schema/fixture risk** (proven §2.2), so the change is
  low-blast-radius despite touching the model file.

### The tie-breaker
The decisive question is **whether the contributor-forgets-the-marker failure
mode is worse than the regex-doesn't-match-the-name failure mode.** They are
symmetric in one sense (both rely on the author doing the right thing), but they
differ in *catchability*:

- **Marker omitted:** caught ONLY if a *separate* "every `str` field is either
  marked or in a tiny structurally-non-sensitive exemption set" meta-guard
  exists. That meta-guard would itself need an exemption list (for genuinely
  non-sensitive strings like `name`, `description`, `mode`, `interface_type`) —
  re-introducing exactly the exemption-list relocation problem the marker was
  supposed to solve. **This is the marker's Achilles heel and I will not
  pretend otherwise.**
- **Regex misses a name:** caught never, until the next blind audit.

So neither is strictly self-enforcing. **My honest read: the marker is modestly
better than the regex (removes the heuristic, captures 3 extra latent leaks,
enables dispatch-by-kind, shrinks the exemption surface) but it is NOT the
qualitative leap to "self-enforcing" that the framing might suggest** — because
the "did you remember to mark it" gap is real and closing IT requires a
meta-guard with its own exemption list. The marker moves the blind spot from
"the regex token list" to "the unmarked-string meta-exemption list," which is a
*smaller and more reviewable* surface but not a vanished one.

---

## 6. Why a "walkable" marker for class-1 is the wrong idea (explicit)

For completeness, the symmetric idea — annotate every leaf with whether the
walker should yield it — fails on three counts:

1. **Inverted density.** ~100+ leaves should be walked and only a handful are
   legitimately non-walkable (Tier-3, `kind`, `default_name`, provenance). You'd
   annotate the overwhelming majority "yes walk me," which is noise; the
   *exceptions* are the information, and they are exactly agent `20`'s exemption
   set. A marker would just relocate that exemption set onto the model with no
   gain.
2. **The walker is hand-written and ordered.** A marker says "this leaf is
   walkable" but not *what xpath string to yield* — and the xpath spelling
   (`/interfaces/interface/config/mtu` vs `/interfaces/interface/switchport-mode`,
   the `config/` inconsistency agent `10` §6 flagged) is irregular and
   hand-mapped. A marker can't generate the right string; agent `20`'s guard
   reflects-and-maps, which is the right tool.
3. **phase4 sensitivity.** Walking a new leaf forces per-codec matrix
   declarations and reclassifies `tests/unit/audit` cells (agent `11` §6, the
   St3-demotion lesson in MEMORY). A marker that *implies* walking would couple
   model edits to phase4 churn — exactly the runtime-behaviour-change risk the
   seed wants to avoid. Agent `20`'s pure-declaration guard keeps the model edit
   and the walk decision separable.

**Conclusion: class-1 is agent `20`'s completeness guard, full stop. The marker
adds nothing there.**

---

## 7. Recommendation + minimal version

### Verdict
- **Class-2 (sanitizer): adopt the `Sensitive` marker in the minimal form
  (§2–§3), re-basing agent `21`'s guard onto the marker set.** WORTH IT — it is
  the only form that removes the naming heuristic (the in-class disease), it
  captures three latent leaks for free, and it enables model-derived primitive
  dispatch. Net cost is low (~38 one-line annotations + 25-line module + guard
  rewrite, zero behaviour/serialization risk).
- **Class-1 (walker): do NOT use a marker.** Use agent `20`'s reflection-driven
  completeness guard. (§6.)
- **So the answer to "both / class-1 / class-2 / neither" is: class-2 only.**

### The honest hedge for the synthesis
This is a *close* call against agent `12`/`21`'s lighter regex guard, and the
marker's Achilles heel (a contributor can silently omit the marker, §5) means it
is not a clean "self-enforcing by construction" win. If the main thread wants the
**absolute lowest-risk** ship, agent `21`'s ~40-line guard is defensible and I
would not block it. If the main thread takes the meta-finding's spirit literally
(*stop hand-maintaining subsets*), the marker is the philosophically-correct
class-2 form and the extra cost is genuinely small. **I lean marker, but flag
this as a decision for `30`/`31` to ratify, not a slam-dunk.**

### The minimal version that captures most of the value
If even the full marker roster feels like too much for one PR, the
**value-maximising minimal cut** is:

1. Ship `markers.py` with the single `Sensitive` class.
2. Annotate ONLY the **7 secret leaves + the 3 latent-gap leaves** (`engine_id`
   already covered, `static_routes[].destination`, and the 5 MAC fields) — the
   ones where the marker captures something the regex/blanket CANNOT. Leave the
   already-covered IP leaves on the existing naming guard for now.
3. Re-base ONLY the *secret* guard (`TestSecretRedactionCoverage`) onto the
   marker set, deleting `_REGISTERED_SECRET_FIELDS` + `_SECRET_NAME_RE`.

That proves the mechanism, kills the `engine_id`-not-named-like-a-secret gap and
the MAC/`destination` latent leaks, and defers the larger IP-leaf annotation
sweep — while leaving a clean path to complete it later. ~12 annotations + module
+ one guard rewrite.

### Coordination with peers
- **Agent `21`** (sanitizer guard) is the consumer that decides regex-vs-marker.
  My input: if you adopt the marker, your guard loses the regex and the
  `_IP_NAME_EXEMPT` list entirely and gains a `_REDACTION_DISPATCH` table keyed
  by `(Class, field)`; the "would have failed before #174" regression argument
  still holds (an unmarked `virtual_gateway_address` → not in dispatch → RED).
- **Agent `20`** (walker guard): the marker does NOT help you; keep the
  completeness-guard design. But note the *reflection engine*
  (`_reachable_canonical_models`) is shared infrastructure — if it gets promoted
  out of the test file into a small `canonical/_reflect.py`, both your guard and
  the marker enumerator can import it (one engine, two consumers).

---

## 8. Risks / must-watch for the main thread (if marker is chosen)

1. **The silent-omission failure mode (§5).** Adding a sensitive field WITHOUT
   the marker is not caught unless an "unmarked-string meta-guard" exists, and
   that guard needs its own non-sensitive-string exemption list. Decide
   explicitly whether to ship that meta-guard (and accept its small exemption
   list) or accept the residual. My rec: ship a *lightweight* version — every
   `str`/`list[str]` leaf is either `Sensitive`-marked OR in a small, reviewed
   `_NON_SENSITIVE_TEXT` set (`name`, `description`, `mode`, `interface_type`,
   `timezone`, `tunnel_type`, `dhcp_client_v6`, `scope`, `kind`, `default_name`,
   `instance_type`, `source_interface`, `interface`, …). This makes "new string
   field" a forced binary decision (sensitive or not) — which is the actual
   fail-surfaced default. It DOES re-introduce a small exemption list, but for
   *non-sensitive free text*, which is a closed, low-churn, reviewable set
   (these are the §5 free-text fields agent `10` and `12` both enumerated).
2. **`AGENTS.md` doc-sync.** Adding a redaction category / changing the
   sanitiser's coverage mechanism trips the doc-sync rows for
   `SECURITY.md` § Sanitiser, `BUG_REPORTING.md`, and
   `docs/adding-a-canonical-field.md` (the marker becomes part of "how to add a
   field"). The marker also wants a row in `netcanon/migration/codecs/README.md`
   or `ARCHITECTURE.md` cross-cutting section. Budget those edits into the PR.
3. **`get_args` vs `.metadata` for list element kinds.** I mark the *field*
   (`Annotated[list[str], Sensitive(...)]`), NOT the element
   (`list[Annotated[str, Sensitive(...)]]`). Both work, but field-level is
   simpler to enumerate (no descent into list args) and is what my prototype
   validated. Keep it field-level; do not mix the two conventions.
4. **No CI floor surprise.** The repo's CI floor is py3.11 (MEMORY). `Annotated`,
   frozen dataclasses, and `FieldInfo.metadata` are all 3.9+/pydantic-2.x stable;
   nothing here is 3.12+-only. Low risk, but the main thread should run the guard
   under the 3.11 matrix leg, not just local 3.14.

---

## 9. Citations index (file:line)

- Model (annotation targets): `netcanon/migration/canonical/intent.py` — IP/host
  leaves and secret leaves enumerated in §3 with their line homes
  (`CanonicalIPv4Address` :120–124, `CanonicalIPv6Address` :160–165,
  `CanonicalSNMPv3User` :441–447, `CanonicalVRRPGroup` :587–597,
  `CanonicalDHCPPool` :354–361, `CanonicalRADIUSServer` :635–638,
  `CanonicalStaticRoute` :326–331, `CanonicalVxlan` :687–692,
  `CanonicalRoutingInstance` :731–742, `CanonicalEvpnType5Route` :779–782, root
  scalars :894–917).
- Reusable reflection engine (the marker enumerator builds on it):
  `tests/unit/tools/test_sanitize.py:662–685` (`_flatten_annotation`,
  `_reachable_canonical_models`).
- Existing secret guard the marker re-bases: `tests/unit/tools/test_sanitize.py:646–767`
  (`_REGISTERED_SECRET_FIELDS`, `_SECRET_NAME_RE`, `TestSecretRedactionCoverage`).
- Self-justifying-exemption precedent (#149): `tests/unit/migration/test_registry_capability_honesty.py:317–346`
  (`_SYNTHETIC_NONWALKABLE`, `_is_legitimate_nonwalkable`) and the top-level
  marker-coverage guard `:527–541` (`test_marker_dict_covers_every_data_bearing_field`)
  — the pattern the §8.1 meta-guard mirrors.
- Walker (why class-1 needs structural coverage, not an IP marker):
  `netcanon/migration/canonical/xpath_walker.py:23–256`.
- pydantic version + no existing `Annotated`-metadata usage: verified
  `pydantic 2.13.0`; repo grep for `Annotated|json_schema_extra|FieldInfo|.metadata`
  hits only `importlib.metadata` imports (none in the canonical model).
- Mechanism proof: four prototype runs (this session) confirming
  `Annotated[...]` metadata is readable via `model_fields[...].metadata` under
  `from __future__ import annotations`, coexists with `Field(ge/le)` +
  unions + `list[str]`, collapses reused models to one `(Class, field)`, and
  leaves `model_dump`/`model_json_schema` byte-unchanged (§2.2).
```
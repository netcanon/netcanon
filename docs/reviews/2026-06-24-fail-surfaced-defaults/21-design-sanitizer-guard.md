# 21 — Durable class-2 fix design: sanitizer completeness guard

**Agent:** `21-design-sanitizer-guard` · Phase 2 (Design) · read-only
**Run:** 2026-06-24 · ultracode blackboard · netcanon
**Scope:** the durable structural fix for the **sanitizer-bypass class** (class 2):
any new IP/host/secret-bearing canonical field leaks verbatim until a human names
it in `sanitize_intent`'s allow-list. Compare (A) blanket `ip_address()` redaction,
(B) reflection-driven completeness GUARD, (C) typed-marker enumeration; recommend
one; give the EXACT test/code shape, exemption mechanism, over-redaction handling,
the would-have-failed-before-#174 proof, and quantified blast radius.

**Peers read first:** `10-model-leaf-census.md`, `11-walker-gap.md`,
`12-sanitizer-gap.md`. I build directly on agent 12's §6 recommendation and §7
catalogue; I do NOT re-derive the leaf census (I cite agent 10/12 as authoritative).

---

## 0. TL;DR / recommendation

**Recommend form (B): extend the existing two-sided reflection guard
`TestSecretRedactionCoverage` (`tests/unit/tools/test_sanitize.py:688-767`) with a
parallel IP/host coverage half + a MAC coverage half.** NOT the runtime blanket
`ip_address()` rule (A). Defer the typed-marker (C) to agent 22's verdict — my read
matches agent 12's: marker is over-engineering *for class-2 alone* because the model
already obeys a reliable naming convention (every IP/host/secret leaf has an IP/host/
secret-shaped name), and the only marker payoff is cross-class reuse with the walker.

The fix is **three commits**, all low-risk:

1. **PR-S1 (runtime, tiny):** wire the *two genuine current leaks* the guard would
   otherwise have to register-as-known-gap: `CanonicalStaticRoute.destination` (1-line
   `redact_cidr`, identical to `dhcp.network`/`evpn.prefix`) and the **four MAC fields**
   (`virtual_gateway_mac` ×2, `virtual_mac`, `anycast_gateway_mac`) via a new
   `redact_mac` primitive. This makes the guard GREEN from day one and is itself the
   first instance of "the guard works" (agent 12 §4b/§5b.3 + this report §3).
2. **PR-S2 (the guard, zero runtime change):** add `_REGISTERED_IP_FIELDS`,
   `_REGISTERED_MAC_FIELDS`, `_IP_HOST_NAME_RE`, `_MAC_NAME_RE`, the self-justifying
   `_IP_NAME_EXEMPT` set, and `test_reverse_no_unregistered_ip_field` /
   `test_reverse_no_unregistered_mac_field` + the forward sentinel halves. ~70 lines,
   reuses the existing `_reachable_canonical_models` + `_flatten_annotation` engine.
3. **PR-S3 (docs, mandatory under AGENTS.md):** SECURITY.md sanitiser table +
   BUG_REPORTING.md "what gets sanitised" + the sanitize.py module docstring get the
   new `mac` / static-route-destination categories (the AGENTS.md doc-sync row for "a
   new redaction category lands in sanitize.py" — §7).

**Blast radius:** fixture-corpus diff is **near-zero** (agent 12 §5c: only public
static-route destinations newly redact, vanishingly rare in the corpus; MAC redaction
adds substitutions only where a MAC is present — cosmetic, not breaking). Zero phase4
reconciliation impact (the sanitizer is NOT in the migration-validate / cross-mesh
path). Test cost: ~70 new lines in one existing file + 2 forward sentinel tests.

---

## 1. Why not (A) the runtime blanket `ip_address()` rule — settled by agent 12

Agent 12 §5 did the over-redaction homework and the verdict is decisive; I restate
the load-bearing points because they directly drive my recommendation, then add two
the census surfaced that sharpen the case against (A):

1. **It is the WRONG ALTITUDE.** The leak class is "a new field is forgotten" — a
   *coverage* defect, best caught at **test time**, not a runtime *behaviour* defect.
   The seed itself says: favour "convert the blind spot into a CI failure over a risky
   runtime behavior change." A guard does exactly that; a blanket rule does not (a
   blanket rule still silently does *something* for the new field — possibly the wrong
   something — but never tells a human a decision was skipped).

2. **It is INSUFFICIENT.** `ip_address()` only matches string leaves whose *entire*
   value parses as a bare IPv4/IPv6 literal. It is structurally **blind** to every
   non-bare-IP category the sanitizer already handles (agent 12 §5b.3, §6):
   - **MACs** — `00:1c:73:00:dc:01` is not a valid `IPv4Address`/`IPv6Address`
     (wrong group count) → a blanket IP rule **misses all four MAC fields entirely**
     (and MACs are currently un-redacted — §3 — so a blanket-IP rule would NOT close
     that real gap, while it would *masquerade* as a complete fix).
   - **CIDR fields** (`network`, `prefix`, `destination`) — `IPv4Address("10.0.0.0/24")`
     raises `ValueError`; they need `redact_cidr`. A uniform `redact_ip_string` blanket
     would *under*-redact these (agent 12 §5b.2).
   - **RD/RT** `64496:N`, **mcast** `233.252.0.N` (preserved by `redact_ipv4`),
     **communities**, **hashes**, **hostnames**, **free-text PII** — none are bare IPs.
   So a blanket-IP rule would have to be *bolted onto* the existing 41 hand-written
   redaction sites anyway, not replace them — gaining a partial redundant cover for the
   IP slice while leaving the actual "field N+1" class only half-closed.

3. **It introduces real (small) over-redaction edges for negligible benefit** —
   `timezone` could in principle hold an IP-shaped string and get mangled; the current
   allow-list is already empirically complete (agent 12 §0). The benefit/cost of (A)
   is poor when the allow-list has no *current* leak to plug.

**One nuance against the seed's framing.** The seed states the durable fix the user
described as: "the sanitizer redacts on `ip_address()` of ANY IP-typed field, not an
allow-list." Agent 12 §5a shows the *over-redaction fear* behind that caution is
largely unfounded (whole-string parsing, not substring) — but the deeper finding is
that `ip_address()`-blanket is **not the right primitive at all** because it cannot see
MACs/RD/RT/secrets. The faithful reading of the user's GOAL ("fail-surfaced defaults")
is better served by a guard that fails-RED on *any* unhandled IP/host/MAC/secret-named
field than by a runtime rule that silently handles only the bare-IP subset. I take a
position on goal-fidelity in §8.

---

## 2. Recommended design (B) — the exact shape

The recommendation extends the **existing, proven** two-sided guard rather than
inventing a subsystem. The reusable engine (`_reachable_canonical_models` +
`_flatten_annotation`, `test_sanitize.py:662-685`) is already battle-tested against
pydantic v2 + `from __future__ import annotations` string annotations (it powers the
secret half today, and `_flatten_annotation` already unwraps `list[...]` / `Optional` /
`dict` / unions). The IP/host and MAC halves are *peers* of `test_reverse_no_
unregistered_secret_field`, dropped into the same file (`TestSecretRedactionCoverage`
becomes the umbrella for all three categories, or a sibling `TestSanitizerFieldCoverage`
class — naming is a synthesis-thread call; the mechanism is identical).

### 2.1 The registries (lockstep with the sanitizer allow-list)

```python
# IP/host-bearing canonical fields that MUST be redacted by sanitize_intent.
# (ClassName, field_name). Keep in lockstep with the sanitiser walk — both
# directions enforced below. Source of truth: agent-12 §2 allow-list table.
_REGISTERED_IP_FIELDS = {
    ("CanonicalIntent", "dns_servers"),
    ("CanonicalIntent", "ntp_servers"),
    ("CanonicalIntent", "syslog_servers"),
    ("CanonicalIPv4Address", "ip"),
    ("CanonicalIPv4Address", "virtual_gateway_address"),
    ("CanonicalIPv6Address", "ip"),
    ("CanonicalIPv6Address", "virtual_gateway_address"),
    ("CanonicalVRRPGroup", "virtual_ips"),
    ("CanonicalVRRPGroup", "virtual_ipv6s"),
    ("CanonicalVlan", "ipv4_addresses"),       # nested IPv4Address.ip covered above
    ("CanonicalStaticRoute", "destination"),   # wired in PR-S1
    ("CanonicalStaticRoute", "gateway"),
    ("CanonicalDHCPPool", "network"),
    ("CanonicalDHCPPool", "start_ip"),
    ("CanonicalDHCPPool", "end_ip"),
    ("CanonicalDHCPPool", "gateway"),
    ("CanonicalDHCPPool", "dns_servers"),
    ("CanonicalSNMP", "trap_hosts"),
    ("CanonicalRADIUSServer", "host"),
    ("CanonicalVxlan", "mcast_group"),
    ("CanonicalVxlan", "flood_list"),
    ("CanonicalRoutingInstance", "route_distinguisher"),
    ("CanonicalRoutingInstance", "rt_imports"),
    ("CanonicalRoutingInstance", "rt_exports"),
    ("CanonicalEvpnType5Route", "prefix"),
    ("CanonicalEvpnType5Route", "rt_imports"),
    ("CanonicalEvpnType5Route", "rt_exports"),
}

# MAC-bearing canonical fields (network-identifying; class twin of IP).
# Wired in PR-S1 (currently UN-redacted — see §3).
_REGISTERED_MAC_FIELDS = {
    ("CanonicalIPv4Address", "virtual_gateway_mac"),
    ("CanonicalIPv6Address", "virtual_gateway_mac"),
    ("CanonicalVRRPGroup", "virtual_mac"),
    ("CanonicalIntent", "anycast_gateway_mac"),
}
```

### 2.2 The name heuristics (what the reverse test *scans for*)

The reverse test must find *candidate* IP/host/MAC fields by name, then assert each is
registered-or-exempt. The regex is the trigger; the registry+exemption is the bless.

```python
# A field name that looks like it holds an IP, a CIDR, a host, or an
# IP-bearing list. Tuned against the live model field names (agent-10 census).
_IP_HOST_NAME_RE = re.compile(
    r"(^|_)("
    r"ip|ips|ipv4|ipv6|"
    r"host|hosts|"
    r"gateway|"
    r"network|destination|prefix|"
    r"address|addresses|"
    r"dns_servers|ntp_servers|syslog_servers|trap_hosts|flood_list|"
    r"start_ip|end_ip|"
    r"route_distinguisher|rt_imports|rt_exports|mcast_group"
    r")$",
    re.IGNORECASE,
)

# A field name that looks like it holds a MAC address.
_MAC_NAME_RE = re.compile(r"(^|_)mac$", re.IGNORECASE)
```

> **Heuristic-reliability evidence (this is the crux of why (B) beats (C) for class-2).**
> Walk agent-10's full leaf table: *every* IP/host-bearing leaf has an IP/host-shaped
> name (`ip`, `*_address`, `*_addresses`, `gateway`, `network`, `prefix`,
> `destination`, `*_servers`, `host`, `trap_hosts`, `flood_list`, `mcast_group`,
> `route_distinguisher`, `rt_*`, `start_ip`/`end_ip`, `virtual_ips`/`virtual_ipv6s`).
> *Every* MAC leaf ends in `_mac`. *Every* secret leaf already matches the proven
> `_SECRET_NAME_RE`. There is **no IP/MAC/secret leaf in the model that hides behind a
> non-indicative name**, and there is **no non-IP leaf whose name falsely matches**
> except the two structural-name false-positives in §2.3. The naming convention is a
> de-facto invariant of this codebase — which is exactly the condition under which a
> naming-heuristic guard is *sufficient* and a typed marker is *redundant ceremony*.

### 2.3 The self-justifying exemption set (modelled on #149 `_SYNTHETIC_NONWALKABLE`)

The exemption set exists ONLY to silence *naming false-positives* — fields whose name
matches `_IP_HOST_NAME_RE` but which structurally cannot carry an IP. It is NOT an
escape hatch for "this is an IP I chose not to redact" (those must go through the
forward sentinel, which is non-exemptable — §2.5). Each entry carries a human-readable
reason string, exactly like #149's precedent (`test_registry_capability_honesty.py:
317-330`):

```python
# Fields whose NAME matches _IP_HOST_NAME_RE but which are NOT IP-bearing.
# Each carries the reason it is exempt — a reviewer reading a PR that adds an
# entry can challenge a bogus reason (the #149 self-justifying-exemption pattern).
_IP_NAME_EXEMPT = {
    ("CanonicalStaticRoute", "interface"): "outgoing iface name, not an IP",
    ("CanonicalVxlan", "source_interface"): "loopback/SVI iface NAME, not an IP literal",
    # NOTE: `prefix_length` (int) does not match the regex; no exemption needed.
    # NOTE: `interface` on DHCP pool — same iface-name rationale if regex ever widens.
}
```

Today this set is **2 entries** (agent 12 §4b/§5b: `source_interface` and route
`interface` are the only IP-named-but-not-IP leaves). The exemption set is therefore a
*closed, small, reviewable* surface — not the open dumping-ground that would re-create
the blind spot (the §30/§31 reviewers must stress this; I argue its boundedness in §6).

MAC has **zero** false-positives (`_MAC_NAME_RE` = exactly `*_mac`; all four matches
are real MAC fields), so `_MAC_NAME_EXEMPT` starts empty — but I still declare it (as
an empty set with a comment) so the mechanism is symmetric and the next `*_mac` field
that is somehow not a MAC has an obvious home.

### 2.4 The reverse (coverage) tests — the class-kill

```python
def _scan_named_fields(name_re):
    """All (ClassName, field) reachable from CanonicalIntent whose name
    matches name_re AND whose annotation contains `str` (scalar or list[str])."""
    found = set()
    for model in _reachable_canonical_models(CanonicalIntent):
        for fname, fld in model.model_fields.items():
            if not name_re.search(fname):
                continue
            flat = list(_flatten_annotation(fld.annotation))
            # str scalar, list[str], Optional[str] all flatten to include `str`;
            # nested-model fields (list[CanonicalIPv4Address]) include the model
            # class, which the registry covers via the child leaves, so we also
            # accept a field whose annotation reaches a registered child model.
            if str in flat or any(
                isinstance(t, type) and issubclass(t, BaseModel) for t in flat
            ):
                found.add((model.__name__, fname))
    return found


def test_reverse_no_unregistered_ip_field():
    found = _scan_named_fields(_IP_HOST_NAME_RE)
    unregistered = found - _REGISTERED_IP_FIELDS - set(_IP_NAME_EXEMPT)
    stale = _REGISTERED_IP_FIELDS - found
    assert not unregistered, (
        "IP/host-bearing canonical field(s) with no known redaction rule — "
        "add a redaction in sanitize_intent AND register in _REGISTERED_IP_FIELDS, "
        "or add a justified exemption to _IP_NAME_EXEMPT: " + repr(sorted(unregistered))
    )
    assert not stale, (
        "Registered IP field(s) no longer on the model — remove from "
        "_REGISTERED_IP_FIELDS: " + repr(sorted(stale))
    )


def test_reverse_no_unregistered_mac_field():
    found = _scan_named_fields(_MAC_NAME_RE)
    unregistered = found - _REGISTERED_MAC_FIELDS  # _MAC_NAME_EXEMPT empty today
    stale = _REGISTERED_MAC_FIELDS - found
    assert not unregistered, (
        "MAC-bearing canonical field(s) with no redaction rule — redact in "
        "sanitize_intent AND register in _REGISTERED_MAC_FIELDS: "
        + repr(sorted(unregistered))
    )
    assert not stale, ("Stale _REGISTERED_MAC_FIELDS: " + repr(sorted(stale)))
```

> **Annotation-reach subtlety (important for correctness).** Container fields like
> `CanonicalInterface.ipv4_addresses: list[CanonicalIPv4Address]` and
> `CanonicalVlan.ipv4_addresses` match `_IP_HOST_NAME_RE` (`addresses$`) but their
> *value* is a nested model, not a string — the actual IP lives on the child's `.ip`.
> The `_scan_named_fields` helper above accepts a name-matching field if its annotation
> reaches *either* a `str` *or* a registered child `BaseModel`. I register
> `("CanonicalVlan", "ipv4_addresses")` (the container) because the SVI-L3 leak (#175)
> was precisely this container's nested `.ip`; the child `CanonicalIPv4Address.ip` is
> *also* registered, so the nested address is doubly accounted. The reviewers should
> confirm this dual-accounting reads cleanly (alternative: scan only `str`-typed leaves
> and rely on the child registration — simpler, drops the two `ipv4_addresses`
> container rows from `_REGISTERED_IP_FIELDS`. I lean toward the str-only scan for
> minimality; documented as an option for synthesis in §9.)

### 2.5 The forward (sentinel) tests — proves the registered redaction actually fires

Mirrors `test_forward_no_registered_secret_survives`: populate every registered IP/MAC
field with a *public, unique sentinel* (public so the private-preservation predicate
does not legitimately keep it), sanitize, assert the sentinel does not survive into the
output JSON. This half is **non-exemptable** — you cannot "exempt" your way out of
redacting a *registered* field, closing the "register-and-forget-to-actually-wire"
hole.

```python
def test_forward_no_registered_ip_survives():
    # Public sentinels (so private-preservation doesn't legitimately keep them).
    intent = CanonicalIntent(
        dns_servers=["8.8.8.8"], ntp_servers=["9.9.9.9"], syslog_servers=["1.1.1.1"],
        interfaces=[CanonicalInterface(
            name="Vlan10",
            ipv4_addresses=[CanonicalIPv4Address(
                ip="203.0.0.7", prefix_length=24,
                virtual_gateway_address="203.0.0.8",
            )],
            vrrp_groups=[CanonicalVRRPGroup(
                group_id=1, virtual_ips=["203.0.0.9", "203.0.0.10"],
            )],
        )],
        static_routes=[CanonicalStaticRoute(
            destination="203.0.0.0/24", gateway="9.9.9.1",
        )],
        dhcp_servers=[CanonicalDHCPPool(
            network="203.0.0.0/24", start_ip="203.0.0.20", end_ip="203.0.0.40",
            gateway="203.0.0.1", dns_servers=["8.8.4.4"],
        )],
        radius_servers=[CanonicalRADIUSServer(host="9.9.9.2", key="k")],
        snmp=CanonicalSNMP(community="", trap_hosts=["9.9.9.3"]),
    )
    sanitized, _ = sanitize_intent(intent)
    blob = sanitized.model_dump_json()
    # No public sentinel octet-string should survive (allowing docs-range output).
    for leak in ("8.8.8.8", "9.9.9.9", "1.1.1.1", "203.0.0.7", "203.0.0.8",
                 "9.9.9.1", "203.0.0.20", "9.9.9.2", "9.9.9.3"):
        assert leak not in blob, f"public IP sentinel survived: {leak}"
```

> Caveat the author of this test must heed: pick sentinels that are unambiguously
> *public* but do NOT collide with the docs ranges the redactor *emits* (`192.0.2.x`,
> `198.51.100.x`, `203.0.113.x`, `2001:db8::`). I used `203.0.0.x`/`8.8.x`/`9.9.x`/
> `1.1.1.1` above precisely to avoid the `203.0.113.x` docs block. The MAC forward test
> populates each MAC field with a recognizable OUI sentinel and asserts it is gone.

---

## 3. The two genuine current leaks PR-S1 must wire (so the guard is green day one)

The guard is only honest if it is GREEN against the *current* model. Two registrations
in §2.1 are **not redacted today** and must be wired in PR-S1 before the guard lands:

### 3.1 `CanonicalStaticRoute.destination` (agent 12 §4b.2)

The route's destination CIDR is never redacted — only `.gateway` is
(`sanitize.py:659-669`). A static route to a public destination leaks that prefix. The
fix is a 1-line `redact_cidr` in the existing static-route loop, identical to
`dhcp.network` (`sanitize.py:633`) and `evpn.prefix` (`sanitize.py:755`):

```python
# inside the `for i, route in enumerate(sanitized.static_routes):` loop
if route.destination:
    new_dest = table.redact_cidr(route.destination)
    if new_dest != route.destination:
        subs.append(Substitution(
            category="ipv4-public",   # or a dedicated "static-route-destination"
            field=f"static_routes[{i}].destination",
            original=route.destination, redacted=new_dest,
        ))
        route.destination = new_dest
```

`redact_cidr` preserves the prefix length and (via `redact_ip_string` → `redact_ipv4`)
**preserves RFC-1918 / default-route `0.0.0.0/0`** — so the overwhelmingly-common LAN
and default routes are untouched (agent 12 §4b.2). Corpus impact: only *public*
static-route destinations change, which agent 12's read-only fixture sampling found to
be near-absent (< 1% of redaction sites, §5c).

### 3.2 The four MAC fields (agent 12 §5b.3 — currently un-redacted)

Confirmed by grep: `sanitize.py` has **no** MAC handling, and the model has four
MAC-bearing leaves (`CanonicalIPv4Address.virtual_gateway_mac`,
`CanonicalIPv6Address.virtual_gateway_mac`, `CanonicalVRRPGroup.virtual_mac`,
`CanonicalIntent.anycast_gateway_mac` — `intent.py:124,165,591,917`). A MAC is
operator-traceable network-identifying data (AGENTS.md Hard Rules class it with
"real MAC addresses" under the never-push-PII review) and several codecs render it
verbatim (Arista VARP `mac-address`, NX-OS `fabric forwarding anycast-gateway-mac`,
Aruba/Junos virtual-MAC). This is the **single most defensible new redaction** the run
surfaces — it is a real (if narrow) class-2 leak that NONE of the five prior audits
named, exactly the "field N+1" the guard is meant to catch *prospectively*.

A new stable primitive on `_SubstitutionTable`:

```python
def redact_mac(self, value: str) -> str:
    """Cross-reference-stable MAC redaction. Maps each distinct MAC to a
    stable address in the IANA documentation OUI 00:00:5E (RFC 7042 /
    locally-administered space), preserving the separator style so the
    renderer still emits valid syntax. Non-MAC strings returned verbatim."""
    # parse-validate as 6 hex groups (`:`/`-`/`.`-separated); if not a MAC,
    # return verbatim (don't mangle). Stable map -> `00:00:5e:00:53:NN`
    ...
```

> **Design choice — which docs MAC range.** RFC 7042 §2.1.2 reserves
> `00:00:5E:00:53:00–FF` as a *documentation* unicast MAC block (the IPv6-doc-MAC
> twin), the cleanest analogue to RFC-5737 docs-IP redaction. Note `00:00:5E` is also
> the IANA VRRP virtual-MAC OUI (`00:00:5E:00:01:VRID`) and the doc block `…:53:NN`
> avoids the `…:01:` VRRP and `…:02:` IPv6-anycast sub-blocks, so a redacted MAC is
> visibly a documentation MAC and won't be mistaken for a live VRRP vMAC. Synthesis can
> pick a different placeholder; the *guard* doesn't care which, only that the field is
> redacted-and-registered.

Wire it at all four sites (the two address loops, the VRRP loop, and the top-level
scalar). New `Substitution.category = "mac"`.

> **Open micro-decision (for synthesis, not blocking):** VRRP `virtual_mac` for a
> *standard* VRID is the well-known deterministic `00:00:5E:00:01:VRID` and is NOT
> operator-identifying (it's derivable from the group id, which is itself walked). One
> could argue to *preserve* a well-known VRRP vMAC the way `redact_ipv4` preserves
> well-known multicast. I lean toward redacting all four uniformly for simplicity and
> because `virtual_mac` is frequently an *override* (operator-chosen) on Junos/Aruba;
> the well-known-vMAC-preservation is a possible later refinement, not a launch
> requirement. Either way the field stays *registered* (redacted), so the guard is
> satisfied — this decision lives entirely in the primitive, not the guard.

---

## 4. Would the guard have FAILED before #174 (the VGA leak)? — the regression proof

**Yes.** This is the headline argument that the guard kills the historical instance
*prospectively*, and it generalises to the whole class.

Before #174, `CanonicalIPv4Address.virtual_gateway_address` (and the IPv6 twin) was a
model field with **no redaction rule** in `sanitize_intent`. Trace the reverse test
against the *pre-#174* model:

1. `_reachable_canonical_models(CanonicalIntent)` reaches `CanonicalIPv4Address`.
2. Its field `virtual_gateway_address` matches `_IP_HOST_NAME_RE` (the name ends in
   `_address` → matches the `address$` alternative). Its annotation is `str`.
3. So `("CanonicalIPv4Address", "virtual_gateway_address") ∈ found`.
4. Pre-#174, it is **not** in `_REGISTERED_IP_FIELDS` (no redaction existed to register)
   and **not** in `_IP_NAME_EXEMPT` (it IS an IP).
5. ⇒ `unregistered` is non-empty ⇒ **`test_reverse_no_unregistered_ip_field` FAILS**
   with: *"IP/host-bearing canonical field(s) with no known redaction rule … :
   [('CanonicalIPv4Address', 'virtual_gateway_address'), ('CanonicalIPv6Address',
   'virtual_gateway_address')]"*.

The PR that *added* `virtual_gateway_address` to the model (well before the audit found
it) would have turned CI red the moment it landed, forcing the author to either wire the
redaction (which is what #174 eventually did, reactively) or consciously exempt it with
a reason a reviewer could challenge. **The five-rounds-of-whack-a-mole pattern is
exactly the absence of this guard.** The same trace works for the *next* unforeseen
field: any `*_ip`, `*_address`, `*_gateway`, `*_mac`, `*_host`, `…_servers` leaf added
without a redaction → red CI naming the exact `Class.field`.

(Symmetric proof for the secret half already exists and ships today — this run only
adds the IP/host + MAC halves the secret guard's author deliberately scoped out, see
the comment at `test_sanitize.py:778-782`.)

---

## 5. Over-redaction — addressed head-on (the user's explicit caution)

The user's caution was about *over-redaction risk*. The guard form (B) has **essentially
zero over-redaction risk** because **it changes no runtime behaviour** — it is a test.
The only runtime change is PR-S1's two narrow redactions, whose over-redaction surface
is:

| Runtime change | Over-redaction risk | Mitigation already in the primitive |
|---|---|---|
| static-route `destination` via `redact_cidr` | Only *public* destinations redact; RFC-1918 + `0.0.0.0/0` preserved | `redact_cidr` → `redact_ip_string` → `redact_ipv4` inherits private/docs preservation (`sanitize.py:857-871`) |
| four MAC fields via `redact_mac` | A non-MAC string in a `*_mac` field would be left verbatim (parse-validate-first); well-known VRRP vMAC arguably over-redacted (cosmetic) | `redact_mac` validates 6-hex-group shape before substituting; §3.2 open-decision on vMAC preservation |

Crucially, the guard does **not** push the project toward the blanket `ip_address()`
rule the user worried about — it does the opposite: it lets the sanitizer keep its
carefully-tuned per-field primitives (CIDR vs bare-address, mcast-preservation,
RD/RT-correlation, format-preserving hashes, private/docs preservation) and simply
*proves the set is complete*. Agent 12's §5d hard-must-fix ("a blanket rule must reuse
the private-preserving predicate") is **moot** under (B) because there is no blanket
rule. The deliberate private/docs-IP preservation is untouched.

The one residual the guard deliberately does **not** force-close is the **hostname-form
passthrough** (`ntp_servers=["nms.corp.example"]` etc., agent 12 §4a) — those fields
ARE registered (they go through `redact_ip_string`, which returns non-IP strings
verbatim by design, asserted at `test_sanitize.py:837-843`). The guard treats
"registered" as "has a redaction rule," and the rule for these is "redact IP form,
preserve name form" — a *conscious* documented decision, not a silent gap. If the
project later decides to redact DNS-name hosts, that is a new redaction primitive, not a
guard change. (I flag this so §30/§31 don't read the passthrough as a guard false-pass.)

---

## 6. Does the exemption set relocate the blind spot? — the honest weakness, bounded

This is the central adversarial question (the seed flags it; §30/§31 will press it). My
position: the exemption set does NOT meaningfully relocate the blind spot for class-2,
because of four structural properties:

1. **It is for naming false-positives only, not redaction opt-outs.** The only way into
   `_IP_NAME_EXEMPT` is "this field's NAME looks IP-ish but it structurally is not an
   IP." You cannot use it to say "this IS an IP but I don't want to redact it" —
   because the *forward sentinel* (§2.5) is non-exemptable and would fail if a registered
   field isn't actually redacted, and the *only* alternative to registering is exempting,
   which a reviewer can reject on the reason string. The two escape routes (register =
   must-actually-redact; exempt = must-not-be-an-IP) are both costly to abuse.

2. **It is tiny and closed.** Today 2 entries (`interface`, `source_interface`). The set
   grows only when a *new* IP-named-but-not-IP field is added — a rare event, and each
   addition is a reviewable PR line with a reason string. Contrast the *original* blind
   spot (the entire 41-site allow-list, hand-maintained, with no forcing function): the
   exemption set is two orders of magnitude smaller and self-documenting.

3. **The reason string makes abuse visible.** `("X", "management_ip"): "internal-only,
   never public"` is a *claim a reviewer can challenge* — internal IPs are still
   operator-traceable, so that reason is bogus and a reviewer rejects it. The #149
   precedent (each `_SYNTHETIC_NONWALKABLE` entry self-justifies) is the proven pattern;
   it has held since PR #149 without the set ballooning.

4. **Belt-and-suspenders for class-2 specifically:** because every IP/host/MAC leaf in
   *this* model truly does have an indicative name (§2.2 evidence), the regex catches
   the real field and the exemption only ever needs to silence the handful of
   iface-name fields. The blind spot would only "relocate" if a future dev added an
   IP-bearing field with a deceptive name (e.g. `peer_endpoint` holding an IP) — that is
   the *one* residual, and it is addressable by (a) the secret/IP naming-convention being
   a documented contributor expectation (it already is, de-facto), and (b) the
   typed-marker (C) as a belt for the deceptive-name case — see §8 / agent 22.

**Residual honest gap (state it plainly):** a name-heuristic guard cannot catch an
IP-bearing field given a *non-indicative* name. That residual is the strongest argument
for the typed marker (C), and the only place (C) buys something (B) cannot. I judge it a
low-probability event for class-2 (the codebase's naming discipline is strong and
contributor-visible) and recommend (B) now, with (C) reserved as a documented escalation
if a deceptive-name field ever ships — see agent 22's verdict.

---

## 7. Doc-sync obligations (AGENTS.md — mandatory, not optional)

PR-S1 lands new redaction behaviour, so the AGENTS.md doc-sync table fires. Two rows
apply directly (the main thread MUST honour these in the *same commit* as the runtime
change, per the Hard Rule "Never land a code change without updating the docs it
renders stale"):

- **Row "A new redaction category lands in `netcanon/tools/sanitize.py`"** →
  (1) `SECURITY.md` § "Sanitiser (Bug-Reporting Workflow)" redaction-rule table — add
  `mac` and (if a dedicated category) `static-route-destination`;
  (2) `BUG_REPORTING.md` § "What gets sanitised" — operator-facing rule list + the
  per-category counter scheme;
  (3) `docs/CAPABILITIES.md` only if the new category surfaces in a migrate-page banner
  (the sanitizer categories do not, so this sub-item is likely N/A — confirm).
- **The `sanitize.py` module docstring** (`sanitize.py:16-72` field-typed-rules list) —
  add the `virtual_gateway_mac`/`virtual_mac`/`anycast_gateway_mac` → docs-MAC line and
  the `static_routes[].destination` → docs-range line. (Module-docstring-inventory row.)
- **`docs/METHODOLOGY.md`** is a *candidate* but optional — the "completeness guard"
  pattern is already exemplified by the secret half; adding the IP/MAC halves is more of
  the same, not a new pattern. Synthesis can add a one-line pointer if it wants the
  pattern discoverable, but it's not a Hard-Rule obligation.

PR-S2 (the guard test itself) is test-only and triggers no doc-sync row (it adds no
marker to `pyproject.toml` and changes no operator-facing surface).

---

## 8. Reconciling with the user's literal goal ("fail-surfaced *defaults*")

The seed asks each design agent to take a position on whether a CI guard is *faithful*
to "fail-surfaced defaults," or whether the goal demands the behaviour-change /
by-construction form.

**My position: the guard (B) IS faithful to the goal for class-2, and is the *better*
realization of it than the runtime blanket.** Parse the goal: "a new field should
DEFAULT to surfaced/flagged, not to silently fine." Under (B), the literal default for a
newly-added IP/host/MAC-named field is **CI-red** — the developer is *forced* to make a
conscious redact-or-exempt decision before the field can merge. That is precisely
"defaults to flagged." The runtime blanket (A), by contrast, makes a new bare-IP field
default to *silently redacted* (and a new MAC/RD/RT/secret field default to *silently
leaked*) — which is *less* surfaced, not more: no human is told a decision was made.
"Fail-surfaced" means a human is *surfaced the failure*; a guard does that, a silent
runtime transform does not.

The one place the guard is *less* than the by-construction ideal is the deceptive-name
residual (§6). That is real, and it is the honest seam where the typed marker (C) would
make the default truly *intrinsic* (the field carries `Annotated[str, IPField()]` so no
name guessing is needed). My recommendation is therefore: **(B) now as the faithful,
minimal, zero-risk realization of the goal; (C) as a documented escalation** if agent 22
shows it cheaply subsumes both classes — see §8.1.

### 8.1 Coordination with agent 22 (typed marker)

If agent 22 recommends the typed marker for class-1 (the walker, where there is *no*
naming convention to lean on and the heuristic is unreliable), then class-2 should
**reuse the same marker** rather than maintain a parallel naming heuristic — at that
point the marginal cost of marking the ~31 IP + 4 MAC + 6 secret leaves is small and the
deceptive-name residual disappears for free. The decision rule for synthesis:

- If agent 22 = "marker worth it for class-1" → adopt the marker for class-2 too
  (the guard then enumerates from `model_fields[...].metadata`, not the regex; the
  `_REGISTERED_*` sets collapse into the annotations). The guard *test* survives —
  it just reflects markers instead of names.
- If agent 22 = "marker is over-engineering for both" → ship (B) exactly as in §2.

Either way the **guard test is the durable artifact**; the only question is whether it
reflects *names* (B) or *markers* (C). That decoupling is deliberate — it means the
class-1/class-2 marker decision can change later without touching the guard's contract.

---

## 9. Blast radius (quantified) + PR sequencing

### 9.1 Fields to add now

| Category | New runtime redactions (PR-S1) | New registry entries (PR-S2) |
|---|---|---|
| IP/host | 1 (`static_routes[].destination`) | 0 new fields *leaking* beyond that — the other 26 IP rows are already redacted; they are merely *registered* (documentation of existing coverage) |
| MAC | 4 (the two vMAC, VRRP vMAC, anycast-gateway-mac) + 1 new `redact_mac` primitive | 4 |
| **Total new redaction sites** | **5** | 30 IP-registry + 4 MAC-registry rows (mostly documenting existing coverage) |

### 9.2 Fixture-corpus diff (reasoned, from agent 12 §5c + this report)

- **Static-route destination:** only public destinations change. Agent 12's read-only
  sampling of the MikroTik/Cisco fixtures found destinations are overwhelmingly RFC-1918
  / default-route → **< 1% of redaction sites**, likely zero in most fixtures.
- **MAC:** adds substitutions only where a fixture carries a virtual/anycast MAC (Arista
  VARP, NX-OS anycast-gateway, Junos/Aruba). Cosmetic (new `mac` substitutions in the
  audit log); not a *breaking* diff for any existing assertion unless a test pins a MAC
  value verbatim — the main thread must grep `tests/` for a MAC literal in a
  sanitizer-output assertion before landing (low probability; the existing sanitizer
  never touched MACs so no test should pin a *redacted* MAC).
- **Net:** near-zero corpus diff, no prose mangling (the runtime changes are CIDR + MAC,
  neither touches free-text). The main thread should still run the end-to-end
  `sanitize_text` over the corpus as a confirmation (agent 12 §5c rec), but the reasoned
  answer is "negligible."

### 9.3 Phase4 / cross-mesh reconciliation impact: **ZERO**

The sanitizer is NOT in the migration-validate / `_walk_canonical` / `classify()` path
(it has its own walk in `sanitize_intent`). It is NOT consumed by `tools/run_full_mesh.py`
or `tools/run_phase4_reconciliation.py`. So unlike the class-1 walker fix (agent 20,
which CAN reclassify `tests/unit/audit` cells), the class-2 fix touches **no** matrix,
**no** cross-mesh artifact, and **no** phase4 cell. This is a major reason class-2 is the
*safer, ship-first* half of this run. (Contrast MEMORY's St3 lesson where a walker/matrix
change broke a `tests/unit/audit/` reconciliation test — that hazard does not exist
here.)

### 9.4 Test cost

~70 lines added to one existing file (`tests/unit/tools/test_sanitize.py`): two registry
sets, two name regexes, two exemption sets, `_scan_named_fields` helper (~12 lines), and
4 tests (2 reverse + 2 forward). Reuses the existing `_reachable_canonical_models` +
`_flatten_annotation` (no new reflection engine). Runs in the existing `tests/unit` tier;
no new marker, no conftest change, no CI job change.

### 9.5 PR sequencing

1. **PR-S1** — runtime: `redact_mac` primitive + 4 MAC sites + 1 static-route-destination
   site + the 5 new `Substitution` rows + the 3 doc-sync targets (§7). Self-contained,
   behaviour-additive, near-zero corpus diff. *Land first* so the model is fully covered.
2. **PR-S2** — the guard: the IP/host + MAC reverse+forward tests. Green from day one
   *because* PR-S1 closed the two real gaps. Pure test addition, zero runtime change.
3. **PR-S3** — (optional, only if agent 22 wins) migrate the registries to typed-marker
   reflection. Defer until the agent-22 verdict + §30/§31 review.

PR-S1 and PR-S2 *could* be one PR (the doc-sync rules want the redaction + its docs in
one commit anyway, and the guard naturally accompanies the redaction); I split them only
to keep the "runtime change" and "the guard" reviewable separately. Synthesis decides.

---

## 10. Decision summary

| Question | Answer |
|---|---|
| Recommended form | **(B) reflection-driven completeness guard**, extending `TestSecretRedactionCoverage` with IP/host + MAC halves |
| Differs from walker rec? | Possibly — class-2's naming convention is reliable so (B) suffices without a marker; class-1 (agent 20) may need more because nested sub-leaves lack a naming convention. Coordinate via §8.1. |
| Runtime behaviour change? | Only PR-S1's 5 narrow redactions (static-route dest + 4 MACs). The guard itself is test-only. |
| Over-redaction risk | Essentially zero (no blanket rule; CIDR + MAC reuse private/docs preservation). |
| Would catch #174 prospectively? | **Yes** (§4 trace). |
| Exemption relocates blind spot? | Bounded — naming-false-positives only, non-exemptable forward half, reason strings, 2 entries today (§6). |
| phase4 / cross-mesh impact | **Zero** (sanitizer is off that path — §9.3). |
| Fixture-corpus diff | Near-zero (< 1% sites; no prose mangling — §9.2). |
| Doc-sync obligations | SECURITY.md + BUG_REPORTING.md + module docstring for the new `mac` / static-route-dest categories (§7). |
| Faithful to "fail-surfaced defaults"? | **Yes** — a new IP/host/MAC-named field defaults to CI-red, the truest "default-to-flagged" (§8). |

---

## 11. Citations index (file:line)

- Existing secret guard skeleton (the thing I extend): `tests/unit/tools/test_sanitize.py:646-767` (`_REGISTERED_SECRET_FIELDS`, `_SECRET_NAME_RE`, `_flatten_annotation`, `_reachable_canonical_models`, `test_forward_no_registered_secret_survives`, `test_reverse_no_unregistered_secret_field`).
- Secret guard deliberately scopes out IP/PII: `tests/unit/tools/test_sanitize.py:770-782` (the R-16/CF-04 comment).
- Documented hostname-passthrough residual: `tests/unit/tools/test_sanitize.py:837-843`.
- Sanitizer allow-list walk: `netcanon/tools/sanitize.py:200-793`.
- Static-route loop (where `destination` wiring lands, next to existing `gateway`): `netcanon/tools/sanitize.py:658-677`.
- `redact_cidr` / `redact_ip_string` primitives + private/docs preservation: `netcanon/tools/sanitize.py:849-941` (preservation logic 857-871, 904-913).
- No MAC handling in sanitizer (grep confirmed empty): `netcanon/tools/sanitize.py` (no `mac`/`MAC` token).
- MAC-bearing model fields: `netcanon/migration/canonical/intent.py:124` (IPv4 vMAC), `:165` (IPv6 vMAC), `:591` (VRRP virtual_mac), `:917` (anycast_gateway_mac).
- `CanonicalStaticRoute.destination` (the un-redacted CIDR leaf): `netcanon/migration/canonical/intent.py:326`.
- #149 self-justifying-exemption precedent: `tests/unit/migration/test_registry_capability_honesty.py:317-346` (`_SYNTHETIC_NONWALKABLE` + `_is_legitimate_nonwalkable`).
- AGENTS.md doc-sync row for new redaction category: `AGENTS.md` "A new redaction category lands in `netcanon/tools/sanitize.py`" row (SECURITY.md + BUG_REPORTING.md + CAPABILITIES.md targets).
- Peer reports: `docs/reviews/2026-06-24-fail-surfaced-defaults/12-sanitizer-gap.md` §2 (allow-list), §4 (gap), §5 (over-redaction), §6 (form-B rec + #174 proof sketch), §7 (guard catalogue); `…/10-model-leaf-census.md` §13 (IP/host=31, secret=6 counts, +4 MAC); `…/11-walker-gap.md` §5 (reusable reflection engine note).

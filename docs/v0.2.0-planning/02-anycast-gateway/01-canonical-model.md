# 01 — Canonical model design

Schema design for the anycast-gateway surface. Lays out the
merge-vs-independent decision with concrete trade-offs and a
recommended Python schema sketch.

---

## The decision

**Two paths, mutually exclusive:**

(a) **Merge with T1 (VRRP).** Extend `CanonicalVRRPGroup` (proposed
in sibling task `01-vrrp-canonical/`) with a
`mode: Literal["vrrp", "hsrp", "anycast"]` discriminator. Anycast
records would have group_id / priority / preempt fields with
sentinel / default values.

(b) **Independent surface.** Add two new optional fields directly
on `CanonicalIPv4Address` and `CanonicalIPv6Address` — the
`virtual_gateway_address` and `virtual_gateway_v{4,6}_mac`
companions — plus a system-wide `anycast_gateway_mac` on
`CanonicalIntent`.

### Concrete trade-offs

| Dimension | (a) Merged with VRRP | (b) Independent surface |
|---|---|---|
| **Source-shape fidelity (Junos)** | Lossy — `set interfaces irb unit N family inet address X virtual-gateway-address Y` is one line in source; merged model splits into two records (one address, one VRRP-mode group) that re-emit on round-trip in indeterminate order | Lossless — both halves live on the same `CanonicalIPv4Address` and round-trip together |
| **Source-shape fidelity (EOS)** | Lossy — `ip address virtual X/Y` has no group identifier; merged model must invent `group_id=0` (collision risk with a real VRRP group 0 if the source ever uses one) | Native — `virtual_gateway_address="X"` on the IP record (no IP value), no synthesis |
| **Cross-vendor migration (Junos → EOS)** | Awkward — Junos's per-IP virtual-gateway-address translates to N synthetic `CanonicalVRRPGroup(mode="anycast", group_id=N)` records, which the EOS renderer has to unbundle back into `ip address virtual` lines (drops the synthetic group_id) | Clean — Junos parse populates `virtual_gateway_address` on each `CanonicalIPv{4,6}Address`; EOS renderer reads the same field and emits `ip address virtual X/Y` |
| **VRRP + anycast on same SVI** | Single records list with two `mode` values per interface — works but the SVI's L3 surface is no longer "look at the address records on the interface" but "look at addresses AND look at anycast-mode VRRP records" | Both surfaces live next to each other naturally: `ipv4_addresses` carries the IPs (and their optional virtual-gateway companions) and a sibling `vrrp_groups` list carries the classic VRRP records |
| **Capability-matrix granularity** | Single xpath `/vrrp-groups/group` covers everything; codecs that support only VRRP-not-anycast (FortiGate) can't easily declare partial support | Distinct xpaths: `/interfaces/interface/ipv4/address/virtual-gateway-address` is anycast-specific; FortiGate declares it `unsupported` while supporting classic VRRP elsewhere |
| **Schema bloat** | One canonical record type covers all redundancy primitives | Two extra fields per address record (~6 schema lines total) plus one top-level field |
| **Symmetry with existing model** | Mirrors `CanonicalSNMP.v3_users` pattern: one container with mode discriminator | Mirrors `CanonicalEvpnType5Route` ↔ `CanonicalVxlan` pattern: two related-but-distinct shapes the maintainers chose to keep separate |
| **EOS system-wide MAC modelling** | Awkward — MAC is system-wide but VRRP records are per-interface; would need a global `default_mac` on every `CanonicalVRRPGroup` (redundant) OR a separate field anyway | Natural — system-wide MAC lives on `CanonicalIntent.anycast_gateway_mac`, per-IP override lives on the IP record |
| **Junos per-IP MAC override modelling** | Awkward — VRRP groups have one MAC per group; Junos's `virtual-gateway-v4-mac` is per-unit (per SVI IP family) so the merged record's MAC field would need IPv4/IPv6 doubling | Natural — IPv4 mac on `CanonicalIPv4Address.virtual_gateway_mac`, IPv6 mac on `CanonicalIPv6Address.virtual_gateway_mac` |

### Recommendation: **independent surface**

The merged approach (a) loses on every fidelity axis. The
maintainers have a clear precedent for keeping cross-vendor-stable
but semantically-distinct primitives separate
(`CanonicalVxlan` vs `CanonicalEvpnType5Route`,
`CanonicalRoutingInstance` vs `CanonicalEvpnType5Route.vrf` back-
pointer, `CanonicalSNMP.community` vs `CanonicalSNMP.v3_users`).
Anycast-vs-VRRP is the same shape: cross-vendor stable as
**properties of an IP address that has a virtual companion**, not
as **a group of routers with a shared address**.

The schema cost is six additional optional fields with empty
defaults; the legibility win is substantial.

---

## Recommended Python schema sketch

```python
# netcanon/migration/canonical/intent.py

class CanonicalIPv4Address(BaseModel):
    """A single IPv4 address + prefix on an interface or SVI."""

    ip: str
    prefix_length: int = Field(ge=0, le=32)
    is_secondary: bool = False
    """``True`` when the source declared this address as a secondary
    (Cisco / Arista ``secondary`` trailer).  Most renderers ignore;
    Arista EOS render emits ``secondary`` trailer when ``True``.
    Junos has no secondary keyword (each address line is independent
    on its own ``unit``)."""

    virtual_gateway_address: str = ""
    """The L3 anycast / VARP virtual-gateway-address companion to
    this address.  Empty string means no anycast intent on this IP.
    Stored as dotted-quad (e.g. ``"10.221.0.1"``) — same shape as
    :attr:`ip` minus the prefix-length.  When non-empty, the
    address-record models an anycast gateway: the source operator
    wants this virtual IP present and identical on every leaf SVI
    that carries this segment.

    Vendor-native source shapes mapped here:

    * Junos: ``set interfaces irb unit N family inet address X/M
      virtual-gateway-address Y`` — both halves on the same line;
      both halves materialise on the same canonical record.
    * Arista EOS VARP: ``interface VlanN / ip address virtual X/Y``
      — the line carries ONLY the virtual address (no separate
      per-leaf primary); parser emits the address with
      ``ip=""`` (or the SVI's existing primary) and
      ``virtual_gateway_address="X"`` + ``prefix_length=Y``.
      See :doc:`02-per-vendor-grammar` § "Arista EOS" for the
      mixed-primary-and-virtual edge cases.
    * Cisco NX-OS DAG (Tier-D, depends on NX-OS codec): ``interface
      VlanN / ip address X/Y anycast`` — the ``anycast`` trailer
      marks the address as the anycast gateway IP; both ``ip`` and
      ``virtual_gateway_address`` carry the same value (or the
      latter mirrors the former; see :doc:`01-canonical-model`
      § "NX-OS shape" for the rationale).
    * Cisco IOS-XE SD-Access: address is the anycast gateway when
      the SVI also carries ``fabric forwarding mode anycast-gateway``
      — see :doc:`02-per-vendor-grammar` § "Cisco IOS-XE
      SD-Access" for the discriminator mechanics.
    """

    virtual_gateway_mac: str = ""
    """Optional per-address virtual-gateway MAC override.  Empty
    string means inherit from :attr:`CanonicalIntent.anycast_gateway_mac`
    (the system-wide default).  Stored in colon-hex form
    (e.g. ``"02:00:21:00:00:01"``); renderers re-emit in the
    vendor's native format (NX-OS uses ``0001.c73a.0000`` dotted-
    triplet form).

    Today only Junos has the per-unit override grammar
    (``set interfaces irb unit N virtual-gateway-v4-mac M``); Arista
    EOS / NX-OS / IOS-XE only model a system-wide MAC.  Cross-vendor
    migration from Junos to a system-only-MAC vendor surfaces a
    review-required banner when multiple IPv4 addresses carry
    *different* per-unit MACs (impossible to express on the target
    without re-emitting as system-wide AND triggering the operator
    to pick one; the renderer emits a comment-form review line and
    uses the FIRST observed MAC for the system-wide field)."""


class CanonicalIPv6Address(BaseModel):
    """Single IPv6 address declaration on a CanonicalInterface."""

    ip: str
    prefix_length: int = Field(ge=0, le=128)
    scope: str = "global"

    virtual_gateway_address: str = ""
    """IPv6 anycast gateway companion to this address.  Empty means
    no anycast intent.  Stored as RFC 4291 colon-hex form (e.g.
    ``"fd20:2021::1"``).  Mirror semantic of
    :attr:`CanonicalIPv4Address.virtual_gateway_address`.

    Vendor sources:

    * Junos: ``set interfaces irb unit N family inet6 address X/M
      virtual-gateway-address Y``.  The ``fe80::/10`` link-local
      address that Junos auto-emits alongside (the QFX10K2 fixture
      lines like ``set interfaces irb unit 2021 family inet6 address
      fe80:2021::1/64``) lives on its OWN address record with
      ``scope="link-local"`` and ``virtual_gateway_address=""`` —
      anycast is only on the global address.
    * Arista EOS: ``interface VlanN / ipv6 address virtual X/Y``
      (parallel grammar to v4; appears in 4.30+ EOS).
    """

    virtual_gateway_mac: str = ""
    """Per-address IPv6 virtual-gateway MAC override.  Only Junos
    has the per-unit grammar (``set interfaces irb unit N
    virtual-gateway-v6-mac M``).  Other vendors share a single
    system-wide MAC for both IPv4 and IPv6 anycast (Arista
    ``ip virtual-router mac-address`` covers both)."""


class CanonicalIntent(BaseModel):
    # … existing fields …

    anycast_gateway_mac: str = ""
    """System-wide anycast-gateway / virtual-router MAC.  Empty
    string means the source config didn't declare one (target
    renderers fall back to the vendor default; some — NX-OS — will
    refuse to commit anycast SVIs without one and emit a review
    line).  Stored in colon-hex form.

    Vendor sources:

    * Arista EOS: ``ip virtual-router mac-address 00:1c:73:00:dc:01``
      (top-level line, post-interface stanzas).
    * Cisco NX-OS DAG (Tier-D): ``fabric forwarding
      anycast-gateway-mac 0001.c73a.0000``.
    * Cisco IOS-XE SD-Access: ``fabric forwarding
      anycast-gateway-mac MAC`` (same grammar as NX-OS).
    * Juniper Junos: no system-wide MAC; per-unit
      ``virtual-gateway-v4-mac`` / ``virtual-gateway-v6-mac`` on
      each IRB.  When Junos is the source, this field stays
      empty; per-IP MACs land on the
      :attr:`CanonicalIPv{4,6}Address.virtual_gateway_mac`
      fields instead.

    Cross-vendor render policy: when the canonical tree has both
    per-IP overrides AND a system-wide field set (e.g. an EOS
    source that an operator hand-edited to add Junos-style per-
    unit overrides via the Tier-3 modal), the per-IP override
    wins for any vendor that supports per-IP MACs (Junos); the
    system-wide field wins for any vendor that doesn't (EOS,
    NX-OS, IOS-XE).  Same-vendor round-trip is lossless on the
    common case (system-wide-only source → system-wide field
    populated, per-IP fields empty)."""
```

Six new fields. All have empty-string defaults so existing
canonical trees parse-and-construct unchanged.

---

## Field semantics

### `CanonicalIPv4Address.virtual_gateway_address`

* **Empty string (default)** — no anycast on this address. Codecs
  emit the address with the standard `ip address X/Y` shape.
* **Non-empty** — this address has a virtual-gateway companion.
  Render emits both halves per vendor-native grammar (see
  [`02-per-vendor-grammar.md`](02-per-vendor-grammar.md)).

The field is **NOT** a YES/NO flag — it carries the actual virtual
IP, which is different from the per-leaf primary IP (`ip`) on
Junos (every leaf has its own primary, all share the same virtual)
and the same as `ip` on NX-OS (`ip address X/Y anycast` re-uses
the primary slot as the anycast).

### `CanonicalIPv4Address.virtual_gateway_mac`

* **Empty string (default)** — inherit from system-wide field. The
  common case across every vendor.
* **Non-empty** — per-address override. Today only Junos has the
  grammar to express this; cross-vendor migration into a
  system-only-MAC vendor surfaces a review banner when the
  per-address fields disagree on the same `CanonicalInterface`.

### `CanonicalIntent.anycast_gateway_mac`

* **Empty string (default)** — system source didn't declare a
  system-wide MAC. Vendor renderers fall back to vendor default
  (or emit a review line for vendors that require one to commit).
* **Non-empty** — colon-hex MAC. Renderers re-emit in vendor-
  native format.

---

## How operators express "this is anycast not VRRP"

The expression is **structural**, not a discriminator field:

* If a `CanonicalIPv4Address` has a non-empty
  `virtual_gateway_address` → the operator is expressing anycast
  intent on that IP.
* If a `CanonicalInterface` carries a `CanonicalVRRPGroup` record
  (T1's surface) → the operator is expressing VRRP intent on that
  interface.

Both can co-exist on the same interface — an SVI may carry classic
VRRP for the legacy underlay segment *and* an anycast gateway on a
secondary address for the EVPN overlay. Each surface stays in its
own structural slot; no discriminator needed.

For the Tier-3 rename modal, the per-pane category list gains a
sixth entry (after ports / vlans / local_users / snmp_community /
snmpv3_user): `anycast_gateway` — covers the system-wide MAC and
the virtual-gateway-address values, lets operators clear or rewrite
them. (T1 introduces a separate `vrrp` pane.)

---

## Fold interaction (project_svi_to_vlan)

The existing transform
`netcanon/migration/canonical/transforms.py:310-370` folds an
SVI interface's `ipv4_addresses` onto the matching
`CanonicalVlan.ipv4_addresses`. The current copy is:

```python
# transforms.py:352
ipv4_addresses=[
    CanonicalIPv4Address(
        ip=a.ip,
        prefix_length=a.prefix_length,
    )
    for a in iface.ipv4_addresses
],
```

This copy DROPS any other field on the source record. For the
anycast surface to round-trip cleanly through the fold, the copy
needs to preserve `virtual_gateway_address` and `virtual_gateway_mac`
(and, while we're at it, `is_secondary`):

```python
ipv4_addresses=[
    CanonicalIPv4Address(
        ip=a.ip,
        prefix_length=a.prefix_length,
        is_secondary=a.is_secondary,
        virtual_gateway_address=a.virtual_gateway_address,
        virtual_gateway_mac=a.virtual_gateway_mac,
    )
    for a in iface.ipv4_addresses
],
```

The `model_copy` pydantic helper would also work:
`a.model_copy()`. Either pattern preserves all current and future
fields automatically. The implementation should use
`model_copy(deep=True)` to future-proof against any field
additions (and to match the
[`netcanon/migration/canonical/transforms.py`](../../../netcanon/migration/canonical/transforms.py)
convention used elsewhere in the file). Same change applies to
the IPv6 fold path further down (lines 365-368 area).

For the Junos parser, the IRB-fold loop in `parse.py:566` also
drops fields:

```python
# parse.py:570 — current code:
vlan.ipv4_addresses.append(
    CanonicalIPv4Address(ip=ip, prefix_length=prefix)
)
```

This loop only sees `(ip, prefix)` tuples because `irb_state[vid]`
stores tuples. Fix is to widen `irb_state[vid]["ipv4"]` to store
dicts (or named-tuples) carrying the optional anycast fields, and
unpack in the fold loop. See
[`03-parse-render-touchpoints.md`](03-parse-render-touchpoints.md)
§ "Junos parse touchpoints" for the concrete sketch.

---

## Alternative designs considered + why rejected

### Alt 1: a top-level `CanonicalAnycastGateway` list

```python
class CanonicalAnycastGateway(BaseModel):
    interface: str            # back-pointer
    ipv4: str = ""
    ipv4_prefix: int = 0
    ipv6: str = ""
    ipv6_prefix: int = 0
    mac: str = ""

class CanonicalIntent(BaseModel):
    anycast_gateways: list[CanonicalAnycastGateway] = ...
```

**Rejected because:** the back-pointer is fragile (interfaces get
renamed between vendors by the rename mesh; the
`CanonicalAnycastGateway.interface` field would have to be updated
in lockstep), the data is *intrinsically* a property of an IP
address (not of an interface), and it produces awkward shape on
the Junos source where the virtual-gateway-address is literally
on the same line as the primary address. The
`CanonicalVRRPGroup` proposal (T1) carries the same back-pointer
trade-off because VRRP IS a per-interface group; anycast is per-
IP and should follow per-IP semantics.

### Alt 2: discriminated union on `CanonicalIPv4Address`

```python
class CanonicalIPv4Address(BaseModel):
    ip: str
    prefix_length: int
    kind: Literal["primary", "secondary", "anycast"] = "primary"
    virtual_companion_ip: str = ""  # only set when kind == "anycast"
```

**Rejected because:** discriminated unions in pydantic require
explicit serialisation logic, and the `kind="anycast"` value
duplicates information already implicit in
`virtual_gateway_address != ""`. Also makes `is_secondary` (which
needs to be expressible alongside anycast — an EOS VARP secondary
address from
`batfish_eos_evpn_vlan_based_leaf.txt:153`) impossible to model.

### Alt 3: two separate address-record lists per interface

```python
class CanonicalInterface(BaseModel):
    ipv4_addresses: list[CanonicalIPv4Address] = ...
    virtual_ipv4_addresses: list[CanonicalIPv4Address] = ...
```

**Rejected because:** Junos's source-shape ties the virtual IP to a
specific primary IP (same `set interfaces irb unit N family inet
address X/M virtual-gateway-address Y` line), and the split-list
shape loses that pairing. Cross-vendor migrations would need
heuristics to pair up entries; the unified-record shape preserves
the source intent unambiguously.

### Alt 4: merge with T1's `CanonicalVRRPGroup`

Covered in § "Decision" above. Loses on every fidelity axis;
keeping anycast separate matches the maintainers' precedent.

---

## NX-OS shape note

NX-OS's `ip address 10.10.10.1/24 anycast` is the canonical
oddity: the single line declares BOTH the primary IP and the
anycast IP (they're the same value). Other vendors split the two
(Junos: primary `10.10.10.5/24` + virtual `10.10.10.1`; EOS:
no per-leaf primary, just `ip address virtual 10.10.10.1/24`).

Three possible canonical mappings:

1. `ip="10.10.10.1"`, `virtual_gateway_address=""` — treat NX-OS as
   if it had no anycast at all. Lossy on round-trip (loses the
   `anycast` trailer; the SVI commits but doesn't act as anycast).
2. `ip=""`, `virtual_gateway_address="10.10.10.1"`,
   `prefix_length=24` — treat as EOS-shape. Lossy on same-vendor
   round-trip (would re-emit as EOS-style without primary).
3. **`ip="10.10.10.1"`, `virtual_gateway_address="10.10.10.1"`,
   `prefix_length=24`** — mirror both slots. Same-vendor
   round-trip: render-side detects `ip == virtual_gateway_address`
   and emits NX-OS's combined form. Cross-vendor to EOS: render
   sees `virtual_gateway_address` and emits VARP; suppresses the
   primary (no per-leaf primary on EOS VARP). Cross-vendor to
   Junos: render emits primary + virtual on the same line.

**Recommendation:** option 3, codified as a NX-OS render policy
once the codec lands. The mirror is detectable on render
(`addr.ip == addr.virtual_gateway_address`) so no schema-level
flag needed. The implementing agent for the NX-OS codec (T3) will
confirm or override.

---

## Summary

* **Surface:** `virtual_gateway_address` + `virtual_gateway_mac` on
  `CanonicalIPv4Address` and `CanonicalIPv6Address`; system-wide
  `anycast_gateway_mac` on `CanonicalIntent`; `is_secondary` flag
  on `CanonicalIPv4Address` for EOS VARP secondaries.
* **Decision:** independent surface (not merged with VRRP).
* **Rationale:** anycast is a property of an IP, not a group;
  matches the maintainers' precedent of keeping cross-vendor-
  stable distinct primitives separate.
* **Costs:** ~15 LOC of schema, transform extension on
  `project_svi_to_vlan` and the Junos IRB fold, ~6 new fields with
  empty defaults (backward-compatible).

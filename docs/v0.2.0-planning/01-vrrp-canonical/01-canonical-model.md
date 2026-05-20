# 01 — Canonical model design for VRRP / HSRP / Anycast / CARP

This file proposes the new pydantic models and field placement.
**All code blocks are sketches** — they document the eventual shape;
they are not edits to `netcanon/migration/canonical/intent.py`.

The existing model lives at
[`netcanon/migration/canonical/intent.py:85`](../../../netcanon/migration/canonical/intent.py)
(`CanonicalIPv4Address`),
[`:119`](../../../netcanon/migration/canonical/intent.py) (`CanonicalInterface`),
[`:572`](../../../netcanon/migration/canonical/intent.py) (`CanonicalIntent`).

---

## Proposed `CanonicalVRRPGroup` (field-by-field)

```python
# Sketch only — to land in intent.py after Tier 2 models, near
# CanonicalVxlan (currently line 423).

class CanonicalVRRPGroup(BaseModel):
    """A single VRRP / HSRP / VARP / virtual-gateway / CARP group.

    Cross-vendor L3 redundancy primitive.  Vendors diverge sharply
    on grammar but converge on the same operational shape: a
    *virtual address* shared by 2+ routers, with election driven
    by a *priority* and tie-broken by IP.

    The model spans three distinct redundancy protocols collapsed
    onto one canonical surface via the ``mode`` discriminator:

    * ``"vrrp"`` — IETF VRRP v2 (RFC 3768) or v3 (RFC 5798).
      Cisco IOS-XE / Arista EOS (modern) / Juniper Junos (classic
      vrrp-group form) / Aruba AOS-S / FortiGate / MikroTik
      RouterOS.  HSRP-only configs (Cisco proprietary) are NOT
      modelled in this surface — see "Out of scope" below.
    * ``"anycast"`` — DC-fabric anycast-gateway: a stable IP
      present on every leaf, never moves on host migration.  No
      election, no group concept on the wire, but the
      ``group_id`` field carries the VLAN/IRB unit number for
      vendor symmetry.  Arista ``ip address virtual``, Juniper
      ``virtual-gateway-address``, Cisco NX-OS / IOS-XE
      ``fabric forwarding mode anycast-gateway``.
    * ``"carp"`` — BSD Common Address Redundancy Protocol.
      OPNsense / pfSense.  Wire-incompatible with VRRP (different
      multicast group + frame format) but semantically equivalent
      from the operator's standpoint.

    Bound to a :class:`CanonicalInterface` via
    :attr:`CanonicalInterface.vrrp_groups`.  Same model used for
    SVI-mounted groups (Aruba ``vlan N`` body, Cisco
    ``interface Vlan10`` body) and routed-port groups (Cisco
    ``interface GigabitEthernet0/2`` body).

    Attributes:
        group_id: VRRP VRID (1-255) or CARP VHID (1-255) or the
            anycast-gateway's VLAN/unit number for vendor
            symmetry.  Same numeric range across all three modes.
        mode: Discriminator — ``"vrrp"`` | ``"anycast"`` |
            ``"carp"``.  String literal (not enum) so codecs can
            extend without a schema change.  Render-side codecs
            select the wire grammar based on this value.
        virtual_ips: IPv4 virtual address(es) the group owns.
            Length >= 1 except for Junos virtual-gateway-v4-mac
            sub-statements that arrive before the address line —
            those parse into an empty list which the post-pass
            merges with the address record.  IOS-XE supports
            multiple ``vrrp N ip X`` lines (primary + secondary
            virtuals); Junos accepts a bracket-list
            ``virtual-address [ X Y ]``.  Aruba AOS-S accepts a
            single ``virtual-ip-address`` — render emits a Lossy
            comment when len > 1.
        virtual_ipv6s: IPv6 virtual address(es).  VRRPv3 only;
            unused for ``mode="vrrp"`` carrying VRRPv2.  Junos
            anycast populates this via
            ``family inet6 address X virtual-gateway-address Y``.
            Same shape as :class:`CanonicalIPv6Address.ip` (RFC
            4291 colon-hex form, no prefix suffix — prefix lives
            on the address record this group is bound to).
        virtual_mac: Vendor override for the virtual MAC.  Empty
            string = use vendor default (00:00:5e:00:01:VRID for
            VRRP; CARP derives from VHID + advskew).  Junos
            ``virtual-gateway-v4-mac`` populates this; Arista
            global ``ip virtual-router mac-address`` cascades
            into every record on the device (see "Decision
            points" below).
        priority: 1-254.  Higher wins the election.  Default 100
            matches IETF VRRP default + most vendor defaults.
            Arista VARP and Junos anycast have no concept of
            priority (no election); codecs ignore this field for
            ``mode="anycast"``.
        preempt: Whether a higher-priority router preempts a
            lower-priority master.  Default ``True`` matches IOS-XE
            / EOS / Junos default.  Aruba AOS-S default is also
            true.  FortiGate default is false.  CARP has no
            preempt knob — codecs ignore for ``mode="carp"``.
        advertisement_interval: Hello-message interval in
            seconds.  VRRPv2 default 1; VRRPv3 supports
            sub-second values but the canonical field stays
            integer (lossy-by-default for VRRPv3 fractional
            intervals).
        authentication: Opaque tag + token.  Format
            ``"<scheme>:<value>"`` where scheme is one of
            ``plain`` / ``md5`` / ``carp-key`` / ``ah`` (Junos).
            Empty string = no authentication.  Cross-vendor
            renders surface a review comment because
            authentication tokens are NOT salt-portable; same-
            vendor round-trip is lossless.  Mirrors the
            :class:`CanonicalLocalUser.hashed_password`
            pass-through policy.
        track_interfaces: Names of interfaces whose status
            decrements priority when down.  Opaque (vendor-
            native names).  Empty list = no tracking.  The
            per-interface priority decrement is NOT modelled —
            it surfaces as Lossy on every codec that supports it
            (IOS-XE ``decrement N``, Arista same, Junos
            ``track interface X priority-cost N``).
        description: Free-text label.  Junos accepts
            ``description "<text>"`` on the vrrp-group;
            FortiGate doesn't.  Preserved on same-vendor
            round-trip.
    """

    group_id: int = Field(ge=1, le=255)
    mode: str = "vrrp"                          # "vrrp" | "anycast" | "carp"
    virtual_ips: list[str] = Field(default_factory=list)
    virtual_ipv6s: list[str] = Field(default_factory=list)
    virtual_mac: str = ""
    priority: int = Field(default=100, ge=1, le=254)
    preempt: bool = True
    advertisement_interval: int = 1
    authentication: str = ""                    # "<scheme>:<value>"
    track_interfaces: list[str] = Field(default_factory=list)
    description: str = ""
```

---

## Where it attaches: per-interface list

```python
# Sketch — add to CanonicalInterface near line 215 (next to vrf field).
class CanonicalInterface(BaseModel):
    # ... existing fields ...
    vrrp_groups: list[CanonicalVRRPGroup] = Field(default_factory=list)
    """L3 redundancy groups mounted on this interface.

    Each group is an independent record — a single interface can
    carry multiple groups (Cisco IOS-XE allows ``vrrp 10 ip X`` +
    ``vrrp 20 ip Y`` on the same port for HA pair separation per
    subnet).  Aruba SVIs typically have one; Junos IRB units carry
    one virtual-gateway-address per unit.

    Empty list = no L3 redundancy on this interface.  Render-side
    codecs emit nothing extra in that case.

    Codecs that populate this from a VLAN-centric grammar (Aruba
    ``vlan N / ip vrrp vrid ...``, OPNsense ``<virtualip>``
    children that reference an interface by name) attach to the
    corresponding ``Vlan<N>`` / interface entry, NOT to a
    parallel ``CanonicalVlan.vrrp_groups`` list.  Single-source-
    of-truth: VRRP state belongs to the L3 interface that owns
    the primary address, never to the L2 VLAN object.
    """
```

### Why per-interface, not per-`CanonicalIPv4Address`?

* Junos models VRRP under each `family inet address` (the address
  is the parent), but it also accepts MULTIPLE addresses per unit
  each with their own vrrp-group. Modelling as per-address would
  match Junos but mismatch Cisco/Arista (where the group is
  port-scoped, not address-scoped).
* Aruba `ip vrrp vrid N` sits at the VLAN-stanza level and
  applies to whatever L3 address(es) the VLAN holds. The VLAN
  has at most one primary IP in practice, so address-scoping
  would have no semantic gain.
* Cisco IOS-XE `vrrp 10 ip X` ties the group to the port stanza,
  not to any specific `ip address` line. Per-port scoping is the
  natural mental model for the most-deployed grammar.
* FortiGate `config vrrp / edit N` lives inside
  `config system interface / edit "name"` — exactly per-interface.

### Why not a top-level `CanonicalIntent.vrrp_groups: list[...]`?

* Every vendor wire-form binds a group to an interface — there is
  no first-class "free-floating group" concept anywhere. A top-
  level list would force every render-side codec to walk both
  the interface list AND the group list and reconcile membership.
* Mirrors the existing `CanonicalInterface.ipv4_addresses`
  pattern. The same "back-pointer is on the interface, parent-
  side renderer walks `tree.interfaces`" convention used for
  `lag_member_of` (line 146) and `vrf` (line 212).
* Cross-vendor port-rename: when the rename mesh rewrites
  `interface 1/1` → `GigabitEthernet0/0`, the VRRP group naturally
  follows because it's stored on the renamed object. A top-level
  list would need to be patched in lock-step.

---

## Anycast-gateway overlap question

The new model deliberately collapses VRRP / anycast / CARP onto
one canonical type via the `mode` discriminator. The case for
splitting them into two models (`CanonicalVRRPGroup` and
`CanonicalAnycastGateway`):

| Argument for split | Counter |
|---|---|
| Anycast has no group, no priority, no election — bolting them onto a VRRP record carries dead fields | The `group_id` field's value is the VLAN/IRB unit number for anycast — non-empty and meaningful. Priority + preempt being ignored for `mode="anycast"` is documented in the docstring; same pattern as `CanonicalDHCPPool.start_ip` being ignored for `mode="relay"` (proposed but not landed). |
| Render-side codecs need a switch on `mode` anyway; might as well dispatch on type | Same number of branches either way; one model is cheaper for the transform/rename layer to walk. |
| Anycast may grow vendor-specific fields (Arista shared-router fields, Junos community tags) that don't belong on VRRP | Add them only when a real fixture demands them; until then, the shared shape is right-sized. |
| Two types make the capability matrix cleaner (`/vrrp/group` separate from `/anycast/gateway`) | Two xpaths off one model: `/interfaces/interface/vrrp_groups[mode='vrrp']` vs `[mode='anycast']`. Phase-1 xpath classifier doesn't support predicates today, so two paths it is — but that's just two strings in the matrix, not two models. |

**Recommendation:** ship one model with `mode` discriminator.
Re-evaluate after the first real-fixture round-trip surfaces
anycast-only fields (Arista shared-router state, Junos
community-tags). If split is needed, it's a strictly-additive
change — the new `CanonicalAnycastGateway` type can live alongside
`CanonicalVRRPGroup`; existing renders continue working because
`mode="anycast"` records on `vrrp_groups` simply become empty
once the migration transform moves them.

---

## Decision points

### D1. Virtual-MAC: per-group or per-device?

Arista `ip virtual-router mac-address 00:1c:73:00:dc:01` is a
**global** statement — every VARP IP on the device uses the same
MAC. Junos `virtual-gateway-v4-mac` is **per-IRB-unit** (one MAC
per IRB).

**Options:**

* (A) `virtual_mac` on every group, copy the global value into
  each group on Arista parse. Simple, idempotent, and matches
  Junos directly. Cost: redundant data on Arista round-trip
  (the global line gets re-emitted from the first group with a
  populated virtual_mac).
* (B) `virtual_mac_default` on `CanonicalIntent` for the Arista
  global; per-group `virtual_mac` overrides. Closer to Arista
  wire form. Cost: extra surface on `CanonicalIntent`; render-side
  has to walk twice.

**Recommendation:** option A. The Arista parser populates
`virtual_mac` on every record; render-side hoists the first
non-empty value to a single global line (Phase 4 follow-up).
Cross-vendor stays lossless.

### D2. CARP advskew / advbase

OPNsense CARP supports advskew (election bias) and advbase
(advertisement frequency). VRRP has no advskew (priority
subsumes the role) and has advertisement_interval (analogous
to advbase). Decision: surface advertisement_interval (works
for VRRP); store advskew as part of priority (CARP master gets
priority=255-advskew, others get priority=128); document the
collision in the codec's lossy declaration.

### D3. Authentication

Three protocols, three different schemes:

* VRRPv2 `text` password — plaintext on the wire.
* VRRPv2 `md5` — IPsec AH-based (Junos only).
* VRRPv3 — no authentication (RFC 5798 removed it).
* CARP — required password, derives HMAC-SHA1 key.

Decision: opaque `<scheme>:<value>` tagged token. Same-vendor
round-trips losslessly. Cross-vendor surfaces a review comment
in the rendered output (analogous to the hash-portability policy
in `netcanon/migration/_user_secrets.py`).

### D4. Tracking

* Cisco IOS-XE: `vrrp 10 track 1 decrement 20` (track-object based)
* Arista EOS: `vrrp 10 track Ethernet1 decrement 10` (interface based)
* Junos: `vrrp-group 10 track interface ge-0/0/0 priority-cost 20`

Sketch carries `track_interfaces: list[str]` (opaque names). The
priority-decrement value is NOT modelled — IOS-XE's
`track-object` is too vendor-specific (the underlying tracked
condition can be SLA, route, prefix-list, etc.) and the
canonical surface is "list of interfaces this group depends on".

Decrement values surface as `lossy` on every codec that supports
them.

---

## Alternatives considered + why rejected

### A1. Single string-blob field on `CanonicalInterface`

```python
# REJECTED
class CanonicalInterface(BaseModel):
    redundancy_state: str = ""  # opaque vendor-native snippet
```

Mirror of `CanonicalIntent.raw_sections`. Fails because:

* Cross-vendor migration requires *structured* data — the
  Arista→Junos rename pass needs to know the VRID number to map
  IRB units correctly.
* The capability matrix can't classify a single field as both
  supported + lossy; we'd lose the per-feature granularity.
* The rename pane would have no surface for VRRP group-ID
  rewriting (e.g. operator merging two HA pairs).

### A2. Per-IPv4Address group binding

```python
# REJECTED
class CanonicalIPv4Address(BaseModel):
    ip: str
    prefix_length: int
    vrrp_group: CanonicalVRRPGroup | None = None  # NEW
```

Matches Junos directly but mismatches every other vendor (group
is port-scoped, not address-scoped). The cross-vendor codecs
would have to materialise a phantom `CanonicalIPv4Address` for
every group when the wire form has no primary address yet (rare
but legal — `vrrp 10 ip X` with no `ip address Y` line is valid
on IOS-XE since IOS-XE 17.12).

### A3. Tier-3 dropped section

Treat VRRP as Tier 3 (informational only, never auto-rendered).
Rejected because:

* Every shipped codec parses-and-ignores TODAY. Promoting to
  Tier 3 just makes the silent drop visible in the banner; it
  doesn't translate. The fixture round-trip stays lossy.
* VRRP semantics are *more* portable than firewall ACLs (the
  current Tier-3 paradigm case) — every vendor accepts a VRID +
  priority + virtual IP. There is no equivalent of "stateful zone
  pair semantics" that doesn't translate.
* Operator value is the cross-vendor translation, not the
  notification. Tier 3 trades behaviour for visibility; here we
  want behaviour.

### A4. Top-level `CanonicalIntent.vrrp_groups: list[...]` with `interface_name` back-pointer

```python
# REJECTED
class CanonicalVRRPGroup(BaseModel):
    interface_name: str  # back-pointer
    # ... rest as proposed
class CanonicalIntent(BaseModel):
    vrrp_groups: list[CanonicalVRRPGroup] = Field(default_factory=list)
```

Mirror of the rejected pattern for `lags` (which lives top-level
but binds via `members: list[str]`, not via a back-pointer on
the interface). Rejected because:

* No vendor wire form has free-floating groups. Aruba and Cisco
  bind to the interface stanza; Junos binds to the address;
  FortiGate to the system interface edit; MikroTik's top-level
  section still uses `interface=ether1`. The interface IS the
  group's container.
* The rename mesh would have to patch back-pointers in lock-step
  with interface renames — already-fragile code.

---

## Out of scope

### Cisco HSRP

Cisco's `standby` / `hsrp` grammar is proprietary, not
interoperable with VRRP on the wire, and out of v0.2.0 scope.
A future canonical extension could add `mode="hsrp"` to the same
model when an NX-OS or IOS-classic codec ships (Tier-D in
`tests/fixtures/real/WANTED.md`).

### GLBP / VRRP load balancing

Cisco GLBP is HSRP++ with active-active load balancing — even
more vendor-specific. Not in v0.2.0.

### Multicast group selection

VRRP uses 224.0.0.18, CARP uses 224.0.0.18 (collision: same
multicast group, different protocol number).  Operators rarely
override.  Not in v0.2.0 scope.

### Cluster-internal heartbeat (Aruba ClearPass, FortiGate cluster sync)

Distinct from L3 redundancy; out of scope.

---

## Sample model — complete file shape (markdown only)

```python
"""SKETCH ONLY — would land in intent.py at the position indicated.

Below is the proposed CanonicalVRRPGroup integrated with the
existing CanonicalInterface and CanonicalIntent shapes.  Field
order and docstring style match the existing file.
"""

# Tier 2 — auto-translate with review banner
# (placed after CanonicalLAG, before CanonicalLocalUser, ~line 397
# in current intent.py)

class CanonicalVRRPGroup(BaseModel):
    """[full docstring as proposed above — omitted here for brevity]"""

    group_id: int = Field(ge=1, le=255)
    mode: str = "vrrp"
    virtual_ips: list[str] = Field(default_factory=list)
    virtual_ipv6s: list[str] = Field(default_factory=list)
    virtual_mac: str = ""
    priority: int = Field(default=100, ge=1, le=254)
    preempt: bool = True
    advertisement_interval: int = 1
    authentication: str = ""
    track_interfaces: list[str] = Field(default_factory=list)
    description: str = ""


# Add to CanonicalInterface (around line 215, next to vrf):

class CanonicalInterface(BaseModel):
    # ... existing fields up through line 241 ...
    kind: str = ""
    #: L3 redundancy groups mounted on this interface.
    vrrp_groups: list[CanonicalVRRPGroup] = Field(default_factory=list)
```

Validation tests for the model itself live in
`tests/unit/canonical/test_intent_vrrp.py` (new file — see
`04-test-plan.md`).

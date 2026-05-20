# Task 2 — Anycast-gateway canonical surface

> **Read-only research.** This subfolder contains design artifacts only.
> No production source code was modified by the agent that authored
> these files. When the implementation lands, the merge commit will
> cite these documents by relative path and an `IMPLEMENTED.md` stub
> will be added pointing at the merge commit.

---

## Executive summary

Anycast gateway is the **DC-fabric L3 hop-redundancy primitive**.
Unlike VRRP / HSRP it has *no group ID, no priority, no preempt*: the
same virtual IP (and optionally the same virtual MAC) is present on
*every* leaf SVI and never moves on host migration. Modern
EVPN-VXLAN fabrics use it instead of classic FHRP because the ARP /
ND resolution stays local to the leaf the host is attached to.

Three of Netcanon's seven shipped bidirectional codecs (Arista EOS,
Juniper Junos, and — to a small extent — Cisco IOS-XE) have native
grammar for the primitive. Two more (Cisco NX-OS, Aruba AOS-CX) will
gain it as their codecs land in v0.3.0+. The remaining three
(FortiGate, MikroTik, OPNsense) have no native anycast grammar and
declare it `unsupported`.

Today the surface **parses-and-ignores on every codec** — the QFX10K2
real-capture fixture
(`tests/fixtures/real/junos/ksator_labmgmt_qfx10k2_junos173.set`)
exercises 7 IRB units × `virtual-gateway-address` + per-unit
`virtual-gateway-v4-mac` / `virtual-gateway-v6-mac` overrides; the
Batfish EOS leaf fixtures
(`tests/fixtures/real/arista_eos/batfish_eos_evpn_vlan_based_leaf.txt`
and `batfish_labval_dc1_leaf2a_eos4230.txt`) exercise `ip address
virtual` on 14 combined Vlan SVIs plus the system-level
`ip virtual-router mac-address`. Every byte is currently dropped on
parse and silently disappears on round-trip.

**Scope:** wire the canonical anycast surface across the three
codecs with grammar today (Junos, EOS, IOS-XE SD-Access mode) and
declare the v4/v6 virtual-gateway-address fields `unsupported` on
the four codecs without native grammar. NX-OS / AOS-CX wiring is
out of scope until those codecs land (Tier-D in
[`tests/fixtures/real/WANTED.md`](../../../tests/fixtures/real/WANTED.md));
their eventual touchpoints are sketched in
[`03-parse-render-touchpoints.md`](03-parse-render-touchpoints.md).

---

## Cross-vendor grammar matrix

| Vendor | Per-SVI virtual IP grammar | System-wide MAC | Per-SVI MAC override | In corpus? |
|---|---|---|---|---|
| **Arista EOS (VARP)** | `interface Vlan10 / ip address virtual X/Y` (`secondary` trailer permitted) | `ip virtual-router mac-address MAC` | none (one MAC per chassis) | yes — 2 fixtures, 14 SVIs |
| **Juniper Junos** | `set interfaces irb unit N family inet address X/M virtual-gateway-address Y` | none (per-unit only) | `set interfaces irb unit N virtual-gateway-v4-mac M` / `virtual-gateway-v6-mac M` | yes — `qfx10k2`, 7 units |
| **Cisco IOS-XE SD-Access** | `interface Vlan10 / fabric forwarding mode anycast-gateway` (binds the SVI's primary IP) | `fabric forwarding anycast-gateway-mac MAC` | none | no — Catalyst-9k in fabric mode rare in public corpora |
| **Cisco NX-OS DAG** *(Tier-D)* | `interface Vlan10 / ip address X/Y anycast` + `fabric forwarding mode anycast-gateway` | `fabric forwarding anycast-gateway-mac MAC` | none | no — depends on NX-OS codec |
| **Aruba AOS-CX** *(Tier-D)* | `interface vlan10 / ip address X/Y virtual` | none documented in 10.x | none | no — depends on AOS-CX codec |
| **FortiGate** | none native (uses VRRP — feeds task T1) | n/a | n/a | n/a |
| **MikroTik RouterOS** | none native | n/a | n/a | n/a |
| **OPNsense** | none native (uses CARP for HA — distinct semantics) | n/a | n/a | n/a |

Per-vendor grammar deep-dive with citations:
[`02-per-vendor-grammar.md`](02-per-vendor-grammar.md).

---

## Proposed canonical surface

```python
# On CanonicalIPv4Address and CanonicalIPv6Address:
class CanonicalIPv4Address(BaseModel):
    ip: str
    prefix_length: int = Field(ge=0, le=32)
    virtual_gateway_address: str = ""   # NEW
    virtual_gateway_mac: str = ""       # NEW (per-address override)

class CanonicalIPv6Address(BaseModel):
    ip: str
    prefix_length: int = Field(ge=0, le=128)
    scope: str = "global"
    virtual_gateway_address: str = ""   # NEW
    virtual_gateway_mac: str = ""       # NEW (per-address override)


# On CanonicalIntent (system-wide anycast MAC):
class CanonicalIntent(BaseModel):
    ...
    anycast_gateway_mac: str = ""       # NEW
    """System-wide virtual-router / anycast-gateway MAC. Empty means
    the vendor's default (Arista: 00:00:00:00:00:00 implicit until
    operator sets one; NX-OS / IOS-XE SD-Access: required by commit-
    time validator before any SVI can use anycast). Per-address
    overrides on CanonicalIPv{4,6}Address.virtual_gateway_mac take
    precedence (Junos per-unit override pattern)."""
```

### Decision recommendation: **independent surface**, not merged with VRRP

After laying out concrete trade-offs (see
[`01-canonical-model.md`](01-canonical-model.md) § "Decision"), this
plan recommends the **independent surface** (option b in the brief):
add `virtual_gateway_address` + `virtual_gateway_mac` directly on
`CanonicalIPv4Address` / `CanonicalIPv6Address`, plus a system-wide
`anycast_gateway_mac` on `CanonicalIntent`.

Rationale in one sentence: **anycast is a property of the IP
address, not a group of routers**, and forcing it through a
`CanonicalVRRPGroup` with `mode="anycast"` would require synthesising
fake `group_id` / `priority` / `preempt` fields with no source, no
target, and no semantic — exactly the "kitchen-sink discriminator"
anti-pattern the canonical model has carefully avoided elsewhere
(see `CanonicalVxlan` vs `CanonicalEvpnType5Route` split, where the
maintainers chose two distinct shapes over a single discriminated
record).

Concretely, the independent surface lets:

* **Junos** parse `family inet address X virtual-gateway-address Y`
  in one place (on the same line, same dispatcher) and store both
  pieces on the same `CanonicalIPv4Address` record — preserving the
  source's "this IP has a virtual gateway companion" structure.
* **Arista EOS** parse `ip address virtual X/Y` directly into a
  `CanonicalIPv4Address(ip="", virtual_gateway_address="X",
  prefix_length=Y)` (or onto the SVI's existing primary address)
  without round-tripping through a synthetic VRRP group.
* **NX-OS DAG** when the codec lands, emit
  `ip address X/Y anycast` as a single line per IP, matching the
  source-as-written shape.
* **FortiGate** declare `unsupported` on the anycast paths without
  affecting the eventual VRRP wire-up.

The merged approach (option a — `CanonicalVRRPGroup.mode="anycast"`)
loses on every one of these. See § "Decision rationale" in
[`01-canonical-model.md`](01-canonical-model.md) for the full
trade-off table.

---

## Open design questions

1. **Anycast on a `CanonicalVlan.ipv4_addresses`?** EOS's
   `ip address virtual` on `interface Vlan10` parses into the
   SVI-fold path (`project_svi_to_vlan` in
   `netcanon/migration/canonical/transforms.py:310`). When that fold
   happens, *both* the primary IP and the virtual-gateway-address
   need to survive onto `CanonicalVlan.ipv4_addresses`. The transform
   currently copies `ip` + `prefix_length` only — extending the
   transform to also copy `virtual_gateway_address` /
   `virtual_gateway_mac` is a one-line patch but needs explicit
   coverage in the test plan. Resolved in
   [`01-canonical-model.md`](01-canonical-model.md) § "Fold
   interaction".

2. **EOS `secondary` trailer.** Lines like `ip address virtual
   10.1.100.1/24 secondary` are present in the Batfish fixture
   (`batfish_eos_evpn_vlan_based_leaf.txt:153`). The current EOS
   parser ignores the `secondary` trailer on regular `ip address`
   lines (`netcanon/migration/codecs/arista_eos/parse.py:884` —
   "first address wins"). For VARP we need to preserve the
   trailer because secondary VARP addresses are a legitimate
   operator pattern (per-tenant overlapping subnets). Recommendation:
   add an `is_secondary: bool = False` to the address records as
   part of this work, or store all VARP IPs flat and let the
   renderer emit the second+ as `secondary`. See
   [`02-per-vendor-grammar.md`](02-per-vendor-grammar.md)
   § "Arista EOS edge cases".

3. **Junos IRB-fold interaction.** Junos's parser folds IRB SVI L3
   onto `CanonicalVlan.ipv4_addresses` via the `_apply_interfaces`
   IRB walker (`netcanon/migration/codecs/juniper_junos/parse.py`
   lines 543-621). The fold copies `ip` + `prefix_length` only —
   `virtual-gateway-address` lives on the same line in the source
   and must survive the fold to the same `CanonicalVlan` record.
   Per-unit `virtual-gateway-v4-mac` / `virtual-gateway-v6-mac` are
   sibling lines, NOT on the address line, and need their own
   parse path that attaches them to the latest address in
   `irb_state[vid]`. Solution sketched in
   [`03-parse-render-touchpoints.md`](03-parse-render-touchpoints.md)
   § "Junos parse touchpoints".

4. **System-wide MAC parsing under `routing-instances`?** Arista's
   `ip virtual-router mac-address` appears at the top level (line
   201 / 286 in the fixtures); Junos's per-unit MAC overrides
   appear inside `set interfaces irb unit N`. NX-OS's `fabric
   forwarding anycast-gateway-mac` is also top-level. The
   canonical `anycast_gateway_mac` field on `CanonicalIntent`
   covers the top-level grammar; Junos's per-unit MACs go on the
   address record. **No cross-vendor inconsistency** — both
   patterns are representable.

5. **Cross-vendor MAC normalization.** Vendors disagree on MAC
   format: Arista wants `00:1c:73:00:dc:01`, NX-OS wants
   `0001.c73a.0000`, Junos wants `02:00:21:00:00:01`. The canonical
   surface stores MACs as colon-hex (the OUI-database canonical
   form); per-vendor renderers re-emit in their native format. See
   [`02-per-vendor-grammar.md`](02-per-vendor-grammar.md)
   § "MAC format normalisation".

6. **VRRP-anycast interplay on FortiGate.** FortiGate doesn't have
   native anycast; an Arista-source-to-FortiGate-target migration
   would silently drop the virtual-gateway-address. The `unsupported`
   declaration plus the existing migration validation banner
   (CAPABILITIES.md § D) already cover this; no additional code
   needed.

---

## Estimated total LOC + test count

**LOC budget: ~350-500.** Pydantic schema additions ~15 LOC;
parse-side additions ~80 LOC total across Junos / EOS / IOS-XE;
render-side additions ~80 LOC; transforms (project_svi_to_vlan
extension) ~10 LOC; capabilities-matrix updates ~50 LOC across all
seven codecs; CAPABILITIES.md edits ~50 LOC; misc reorganisation
~30-50 LOC.

**Test budget: ~70 tests.** Per supporting codec (Junos / EOS /
IOS-XE SD-Access): 4-5 unit tests for parse, 4-5 for render, 2
round-trip → ~33. Cross-vendor migration tests (5 vendor pairs ×
3 scenarios): ~15. Real-capture round-trip (QFX10K2, EOS Batfish
leaves): ~6. Determinism: ~5. Unsupported-target migration tests
(4 codecs × 1 banner check): ~4. Plus the existing real-fixture
harness (`tests/unit/migration/test_real_captures.py`) gains ~6
new assertions for the anycast field round-tripping.

**Implementation order: schema → Junos → EOS → IOS-XE → cross-vendor →
capabilities**, mirroring the T1 (VRRP) implementation order so the
two efforts can be reviewed back-to-back. Wave granularity:

* Wave 1: pydantic schema + tests for the empty default (~15 LOC, 5 tests).
* Wave 2: Junos parse + render + capabilities row (~140 LOC, 18 tests).
* Wave 3: EOS parse + render + system-MAC field + capabilities row (~120 LOC, 15 tests).
* Wave 4: IOS-XE SD-Access parse + render (best-effort) + capabilities (~80 LOC, 10 tests).
* Wave 5: Cross-vendor migrations + unsupported-target banner tests + CAPABILITIES.md edits (~80 LOC, 22 tests).

NX-OS DAG (Tier-D) is scoped under sibling task `03-nxos-codec/`;
this task's documents only sketch the eventual NX-OS touchpoints so
the schema choices don't lock NX-OS out.

---

## Dependency note vs T1 (VRRP)

T1 (VRRP/HSRP) and T2 (anycast) are independent design efforts but
**share `CanonicalInterface` and `CanonicalVlan` as the binding
point**. The two surfaces co-exist on the same SVI: an operator may
configure both classic VRRP *and* anycast on the same interface
(e.g. dual-stack EVPN-VXLAN fabric with VRRP-providing default-
gateway redundancy for the legacy underlay segment alongside
anycast for the EVPN-tenant overlay segment). The independent-surface
recommendation here keeps T1's `CanonicalVRRPGroup` cleanly
separate from T2's per-address `virtual_gateway_address`; merging
them would force an awkward "which mode am I" discriminator on
records that could legitimately carry both.

Implementation order, per the parent `README.md` § "Dependency
graph": T1 → T2. T2 should NOT block on T1 landing first because
the surfaces are non-overlapping; if T1 slips, T2 can land first
and T1's `CanonicalVRRPGroup` can be added as a sibling without
schema churn. Reviewers should still skim both folders together
because the test fixtures overlap (the QFX10K2 anycast capture
also exercises Junos's `vrrp-group` indirectly through context).

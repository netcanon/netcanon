# VRRP / HSRP / Anycast-Gateway canonical-model design

**Status:** design artifact, no code committed yet.
**Target release:** v0.2.0.
**Scope:** add a cross-vendor L3-redundancy canonical surface and wire
every shipped bidirectional codec to parse + render it.
**Aligns with:** `tests/fixtures/real/WANTED.md` § "VRRP / HSRP /
anycast-gateway (highest leverage)".

This folder is the design output. It does NOT modify production code.
Every code example is a sketch in a markdown fenced block and exists
only to be cited from the eventual implementation PRs.

---

## Why this is the highest-leverage v0.2.0 task

L3 redundancy is the **only** Tier-1 enterprise primitive that every
shipped codec parses-and-ignores. Every fixture in the corpus that
exercises VRRP / HSRP / VARP / virtual-gateway-address / CARP today
round-trips with the VRRP state **silently dropped** — operators have
no signal that the data was lost, because the canonical tree carries
no field for it. The migrate UI's "Unsupported path" banner cannot
fire for a path the tree doesn't model.

Wiring this surface unblocks four downstream wins:

1. Real-fixture round-trip on `batfish_iosxe_basic_vrrp.txt` (the
   new fixture added with this design pass) flips from
   "data-loss-on-round-trip" to "clean".
2. The DC-fabric audience (Arista EOS + Junos QFX users) gets
   first-class anycast-gateway translation — currently their
   `ip address virtual` / `virtual-gateway-address` lines parse and
   evaporate.
3. The HA-pair operator workflow (campus Aruba ↔ FortiGate or
   ISR ↔ MikroTik) gains its first cross-vendor primitive beyond
   plain L3 addressing.
4. CAPABILITIES.md per-codec rows pick up a row that was previously
   absent — operators see what the tool *can* do, not just what it
   can't.

---

## Cross-vendor grammar matrix (1 line per vendor)

| Vendor | Native grammar (canonical example) | Locus |
|---|---|---|
| Cisco IOS-XE CLI | `interface ... / vrrp 10 ip 192.168.1.254 / vrrp 10 priority 110 / vrrp 10 preempt` | inside `interface` stanza |
| Cisco IOS-XE NETCONF | OpenConfig `openconfig-if-ip:vrrp` augment under `interfaces/interface/subinterfaces/subinterface/ipv4/addresses/address` | XML augment |
| Arista EOS | classic VRRP: `interface Vlan10 / vrrp 10 ipv4 192.168.1.254 / vrrp 10 priority 110` — modern VARP (anycast): `ip address virtual 10.1.10.1/24` + global `ip virtual-router mac-address X` | inside `interface` stanza |
| Juniper Junos | classic: `set interfaces irb unit 10 family inet address X vrrp-group 10 virtual-address Y / priority P / preempt` — anycast: `set interfaces irb unit 10 family inet address X virtual-gateway-address Y` + `virtual-gateway-v4-mac Z` | per-`family inet address` sub-statement |
| Aruba AOS-S | inside `vlan N`: `ip vrrp vrid 10 / virtual-ip-address 10.1.10.254 / priority 110 / preempt / enable` | nested inside `vlan N` stanza |
| FortiGate CLI | `config system interface / edit "vlan10" / config vrrp / edit 10 / set vrip 10.1.10.254 / set priority 110 / set preempt enable / next / end` | nested `config vrrp / edit N` inside `system interface` edit |
| MikroTik RouterOS | `/interface vrrp add interface=ether1 vrid=10 priority=110 v3-protocol=ipv4` + `/ip address add address=10.1.10.254/24 interface=vrrp1` | top-level `/interface vrrp` section |
| OPNsense (BSD CARP) | `<virtualip><vip><mode>carp</mode><vhid>10</vhid><advskew>0</advskew><password>...</password><interface>vlan10</interface><subnet>10.1.10.254</subnet><subnet_bits>24</subnet_bits></vip></virtualip>` | `<virtualip>` root child |

See `02-per-vendor-grammar.md` for source citations + edge cases.

---

## Proposed canonical surface (schema sketch only)

```python
# Sketch. Real edits land in netcanon/migration/canonical/intent.py
# in the implementation PR, NOT in this design folder.
class CanonicalVRRPGroup(BaseModel):
    group_id: int                  # 1..255 VRID (or CARP VHID)
    mode: str = "vrrp"             # "vrrp" | "anycast" | "carp"
    virtual_ips: list[str]         # IPv4 virtual addresses (>= 1)
    virtual_ipv6s: list[str]       # IPv6 virtual addresses (anycast / VRRPv3)
    virtual_mac: str = ""          # Junos virtual-gateway-v4-mac /
                                   # Arista global ip virtual-router mac;
                                   # empty = vendor default (00:00:5e:00:01:VRID)
    priority: int = 100            # 1..254 — higher wins
    preempt: bool = True           # most vendors default true
    advertisement_interval: int = 1   # seconds (VRRPv2 default)
    authentication: str = ""       # opaque token: "plain:secret" /
                                   # "md5:hash" / "" — passed through
    track_interfaces: list[str] = []  # interface-tracking names (opaque)
    description: str = ""
```

The model attaches to `CanonicalInterface` via a new list field —
NOT to a single `CanonicalIPv4Address` and NOT to a top-level
`vrrp_groups` collection. Rationale + alternatives in
`01-canonical-model.md`.

Anycast / VARP / CARP are modelled with `mode` discriminator on the
same record rather than a separate `CanonicalAnycastGateway` — they
share enough fields (virtual_ips, virtual_mac) that splitting them
costs more than it gains. The `mode` field is a string literal (not
an enum) so codecs can extend it without a schema change.

---

## Implementation order recommendation

Ship in this order — each step is independently testable and each
target codec unblocks one new real-fixture round-trip:

1. **Schema landing PR.** Add `CanonicalVRRPGroup`,
   `CanonicalInterface.vrrp_groups: list[...]`, and declare every
   codec's capability matrix to mark
   `/interfaces/interface/vrrp/group` as `unsupported` until wired.
   Pure addition; no behavioural change. ~80 LOC.
2. **cisco_iosxe_cli parse + render.** Highest-value pairing —
   `batfish_iosxe_basic_vrrp.txt` exists. ~120 LOC. Round-trip the
   fixture; flip capability matrix to `supported`.
3. **juniper_junos parse + render.** Already-exercised in
   `ksator_labmgmt_qfx10k2_junos173.set` (anycast form). Both
   anycast and classic. ~150 LOC.
4. **arista_eos parse + render.** Both classic and VARP modes.
   Exercised inline in `batfish_labval_dc1_leaf2a_eos4230.txt`.
   ~140 LOC.
5. **aruba_aoss parse + render.** Inside `vlan N` stanza, attach
   to canonical via VLAN-SVI absorbtion rules. ~100 LOC. Needs
   a new fixture (see `06-fixture-targets.md`).
6. **fortigate_cli parse + render.** Nested-edit grammar — adds
   sub-block handling to `_apply_system_interface`. ~110 LOC. Needs
   a new fixture.
7. **mikrotik_routeros parse + render.** Top-level
   `/interface vrrp` section — new section dispatcher. ~90 LOC.
   Needs a new fixture.
8. **opnsense parse + render.** BSD CARP — `<virtualip>` root
   element walker; `mode="carp"` discriminator. ~80 LOC. Needs a
   new HA-deployment fixture.
9. **cisco_iosxe (NETCONF stub).** Declare unsupported (matches the
   sibling stub's "interfaces-only" policy). ~5 LOC change to the
   capability matrix.

Total: ~875 LOC + the schema PR's 80 = **~955 LOC**, slightly above
the WANTED.md estimate (400–600) once edge cases (IPv6, tracking,
authentication) and round-trip tests are counted.

---

## Open design questions

1. **Anycast vs classic — one model or two?**  Current proposal
   discriminates via `mode`. Alternative: two distinct canonical
   types (`CanonicalVRRPGroup` and `CanonicalAnycastGateway`).
   The discriminator approach wins if and only if anycast doesn't
   accrete enough vendor-specific fields to bloat the shared
   shape. Decision blocker is whether Junos
   `virtual-gateway-v4-mac` and Arista global
   `ip virtual-router mac-address` should be per-group (current
   sketch) or top-level intent state. See
   `01-canonical-model.md` "Decision points".
2. **OPNsense CARP — same model or separate?**  CARP shares the
   "virtual IP with a group ID" semantics but uses a DIFFERENT
   wire protocol (BSD-native, not IETF VRRP).  Cross-vendor
   migration *toward* OPNsense from VRRP devices is meaningful
   (operator wants the same redundancy); migration *away from*
   OPNsense to VRRP devices is meaningful for the same reason.
   The `mode="carp"` flag carries enough information to flip
   between the two on render.  Alternative: declare OPNsense
   `unsupported` for /vrrp/group and ship CARP as `/carp/group`
   instead.  Recommended approach: `mode="carp"` discriminator;
   lossy-by-default on cross-vendor renders (authentication
   semantics differ).
3. **Multiple virtual IPs per group.**  IOS-XE supports
   `vrrp N ip X` repeated (secondary virtual IPs).  Junos accepts
   `virtual-address [ X Y Z ]`.  Aruba's `virtual-ip-address`
   takes one IP. Sketch uses `list[str]` for flexibility but
   AOS-S render must surface a Lossy declaration if length > 1.
4. **IPv6.** VRRPv3 (RFC 5798) merges v4 + v6 into one protocol;
   classic VRRPv2 is v4-only. Junos models v6 anycast via
   `family inet6 address X virtual-gateway-address Y`. Sketch
   separates `virtual_ips` / `virtual_ipv6s` to match Junos and
   to keep prefix-length consistency with `CanonicalIPv4Address`
   / `CanonicalIPv6Address`.
5. **Interface tracking.**  IOS-XE
   `vrrp N track <object>`, Junos `track interface`, Arista
   `vrrp N track Ethernet1 decrement 10` — vendors disagree on
   what's tracked (objects vs interfaces) and how priority
   reduces. Current sketch carries `track_interfaces: list[str]`
   as opaque; the priority-decrement value drops to
   per-vendor-Lossy.
6. **Authentication.**  IOS-XE / Junos / Aruba support text
   passwords; CARP requires one; modern security advice says
   never use VRRP auth in production. Carry as opaque
   `authentication` string with prefix tag (`plain:` /
   `md5:` / `carp-key:`); render paths pass through on
   same-vendor and surface a review comment cross-vendor.
7. **Where on `CanonicalInterface`?**  Proposal:
   `vrrp_groups: list[CanonicalVRRPGroup]` on the interface.
   Alternative: nested under each `CanonicalIPv4Address` (since
   VRRP groups are address-scoped on Junos). Discussion in
   `01-canonical-model.md`.

---

## Estimated total LOC + test count

| Item | LOC | Tests |
|---|---|---|
| Schema (canonical model + matrix) | 80 | 5 (model validation, defaults) |
| cisco_iosxe_cli parse + render | 120 | 12 (parse + render + round-trip + edge cases) |
| juniper_junos parse + render | 150 | 16 (anycast + classic + v6 + virtual-mac) |
| arista_eos parse + render | 140 | 14 (classic + VARP + global mac) |
| aruba_aoss parse + render | 100 | 10 |
| fortigate_cli parse + render | 110 | 11 |
| mikrotik_routeros parse + render | 90 | 9 |
| opnsense parse + render | 80 | 8 |
| cisco_iosxe (NETCONF) capability matrix only | 5 | 1 |
| Cross-vendor migration matrix (V→V tests) | 0 | 28 (4 high-value pairs × 7 scenarios) |
| Real-fixture round-trip tests | 0 | 8 (1 per codec, post-feature) |
| `docs/CAPABILITIES.md` row edits | 30 | 0 |
| `_tier3_detection.py` (if any new patterns needed) | 0 | 0 — VRRP is Tier-1, not Tier-3 |
| **TOTAL** | **~905** | **~122** |

---

## Document map

* [`01-canonical-model.md`](01-canonical-model.md) — schema design
  (field justifications, alternatives, sample model).
* [`02-per-vendor-grammar.md`](02-per-vendor-grammar.md) — for
  each of 7 codecs, vendor grammar + field mapping + edge cases.
* [`03-parse-render-touchpoints.md`](03-parse-render-touchpoints.md)
  — exact `file:line` for parse + render insertions; regex shapes
  + code sketches.
* [`04-test-plan.md`](04-test-plan.md) — unit / round-trip /
  cross-vendor test inventory.
* [`05-capabilities-matrix-updates.md`](05-capabilities-matrix-updates.md)
  — proposed `CapabilityMatrix` rows + `docs/CAPABILITIES.md`
  edits.
* [`06-fixture-targets.md`](06-fixture-targets.md) — concrete
  public fixture URLs for codecs lacking VRRP coverage.

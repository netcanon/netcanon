# VLAN configuration: FortiGate FortiOS versus MikroTik RouterOS

## FortiGate FortiOS CLI

Sources:
- [FortiGate / FortiOS 7.4 Cookbook — VLAN sub-interfaces](https://docs.fortinet.com/document/fortigate/7.4.0/cookbook/) — VLAN child interface recipe.
- [FortiGate / FortiOS 7.4 Administration Guide — Interface settings (VLAN)](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/954635/interface-settings) — `set type vlan / set vlanid / set interface "<parent>"`.

Retrieved: 2026-04-30

```
config system interface
    edit "agg1.100"
        set alias "data-vlan-100"
        set type vlan
        set vlanid 100
        set interface "agg1"
        set ip 10.100.0.1 255.255.255.0
        set ip6-address 2001:db8:100::1/64
        set status up
    next
    edit "VL_200"
        set vlanid 200
        set interface "agg1"
        set ip 10.200.0.1 255.255.255.0
        set status up
    next
end
```

FortiGate has **no first-class `vlan <N>` global object**.  VLAN membership is expressed as **child interfaces** hanging off a parent (`set type vlan / set vlanid <id> / set interface "<parent>"`).  Naming is operator-driven: a popular convention is `<parent>.<vlanid>` (e.g. `agg1.100`, `port4.300`) but `VL_<id>` and other flat-name patterns are equally valid.

The VLAN's name is the interface edit-id itself (no separate name attribute).  Per-VLAN description lives on the alias field of the child interface (25-char cap).  IP addresses, MTU, and admin status are all attached to the child interface.

There is no notion of a tagged-port-list per VLAN — each VLAN child interface attaches to exactly one parent.  Multi-port VLAN membership is achieved by creating multiple child interfaces (one per parent) sharing the same `vlanid` value, which is uncommon in firewall-edge deployments.

## MikroTik RouterOS

Sources:
- [VLAN — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/88014957/VLAN) — `/interface vlan add name=<NAME> interface=<PARENT> vlan-id=<ID>` (Plane 1: router-on-a-stick).
- [Basic VLAN switching — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/103841826/Basic+VLAN+switching) — bridge VLAN filtering (Plane 2).

Retrieved: 2026-04-30

RouterOS has **two parallel VLAN models**:

**Plane 1 — `/interface vlan` (router-on-a-stick)** — dominant for L3-only VLANs:

```
/interface vlan
add name=vlan100 interface=bridge1 vlan-id=100
add name=vlan200 interface=bridge1 vlan-id=200

/ip address
add address=10.100.0.1/24 interface=vlan100
```

**Plane 2 — bridge VLAN filtering** — required for switch-style multi-port tagged/untagged membership:

```
/interface bridge
add name=bridge1 vlan-filtering=yes pvid=1

/interface bridge port
add bridge=bridge1 interface=ether2 pvid=10
add bridge=bridge1 interface=ether3 pvid=20

/interface bridge vlan
add bridge=bridge1 vlan-ids=10 tagged=ether1 untagged=ether2
add bridge=bridge1 vlan-ids=20 tagged=ether1 untagged=ether3
```

The MikroTik codec parses Plane 1 fully and Plane 2 partially in v1 — `/interface bridge vlan` lines populate `CanonicalVlan.tagged_ports` / `untagged_ports` when present, but bridge VLAN filtering setup ceremony (`vlan-filtering=yes`, per-port `pvid`) is not synthesised on render.

VLAN names in Plane 1 are **conflated with the L3 interface name** — operators commonly use `vlan10`, `vlan100` so the RouterOS codec emits the canonical name as the interface name and re-parses it back.

## Cross-vendor mapping (FortiGate → RouterOS)

Canonical surface (per-VLAN):

```
CanonicalVlan.id: int
CanonicalVlan.name: str
CanonicalVlan.description: str
CanonicalVlan.tagged_ports: list[str]
CanonicalVlan.untagged_ports: list[str]
CanonicalVlan.ipv4_addresses: list[CanonicalIPv4Address]
```

The fundamental issue: **FortiGate models VLAN as a child interface, not as a global object**.  The FortiGate codec does not populate `CanonicalIntent.vlans` from the VLAN child interfaces it parses (those land on `CanonicalIntent.interfaces` instead).

- **id / name** — `lossy`.  FortiGate's child-interface model means each VLAN appears in `CanonicalIntent.interfaces` (with the interface-name prefix encoding the VLAN id, e.g. `agg1.100`).  The RouterOS render path sees a `vlan100` interface and emits `/interface vlan add name=vlan100 interface=<parent> vlan-id=100` — but the parent attachment may not match (FortiGate's `agg1` parent must rename-mesh to `bond1` or similar on RouterOS).  The MikroTik codec's `LossyPath` entry on `/vlans/vlan/name` flags the conflation between L3-interface name and descriptive VLAN name.
- **description** — `unsupported`.  RouterOS Plane-1 `/interface vlan` does not have a separate description / comment-as-VLAN field beyond the interface comment; FortiGate-side alias on the VLAN child interface lands on the RouterOS interface comment, but descriptive context per VLAN-id (the global concept) has nowhere to land.
- **tagged_ports / untagged_ports** — `unsupported`.  FortiGate has no port-list-per-VLAN concept (each child interface attaches to exactly one parent), so the canonical lists are structurally empty on this direction.  Operators wanting RouterOS bridge VLAN filtering with multi-port tagged/untagged membership must reconstruct it manually after migration.
- **ipv4_addresses** — `good`.  IP addresses on FortiGate VLAN child interfaces (`set ip ADDR MASK` on the `agg1.100` edit) parse through to canonical, and RouterOS render attaches `/ip address add address=<CIDR> interface=vlan100` correctly via SVI absorption (the canonical layer owns the address; the codec emits the `/ip address` line on render).

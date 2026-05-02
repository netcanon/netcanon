# VLAN configuration: MikroTik RouterOS versus FortiGate FortiOS

## MikroTik RouterOS

Sources:
- [VLAN — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/88014957/VLAN) — Plane 1, `/interface vlan`.
- [Basic VLAN switching — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/103841826/Basic+VLAN+switching) — Plane 2, bridge VLAN filtering.

Retrieved: 2026-04-30

RouterOS has **two parallel VLAN models**:

**Plane 1 — `/interface vlan` (router-on-a-stick / sub-interface for L3)**:

```
/interface vlan
add name=vlan100 interface=bridge1 vlan-id=100
add name=vlan200 interface=bridge1 vlan-id=200

/ip address
add address=10.100.0.1/24 interface=vlan100
```

Each VLAN is a child interface hanging off a parent (bridge or ethernet).  IP addresses attach to the child via `/ip address`.

**Plane 2 — bridge VLAN filtering (L2 multi-port tagged/untagged)**:

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

The MikroTik codec parses Plane 1 fully and Plane 2 partially in v1 — `/interface bridge vlan` lines populate `CanonicalVlan.tagged_ports` / `untagged_ports`; bridge VLAN filtering setup ceremony is not synthesised on render.

VLAN names in Plane 1 are conflated with the L3 interface name (e.g. `vlan10`).  The codec's `LossyPath` flags this explicitly.

## FortiGate FortiOS CLI

Sources:
- [FortiGate / FortiOS 7.4 Cookbook — VLAN sub-interfaces](https://docs.fortinet.com/document/fortigate/7.4.0/cookbook/) — VLAN child interface recipe.

Retrieved: 2026-04-30

```
config system interface
    edit "agg1.100"
        set type vlan
        set vlanid 100
        set interface "agg1"
        set ip 10.100.0.1 255.255.255.0
        set status up
    next
end
```

FortiGate has **no global `vlan <N>` object**.  VLAN membership is expressed as child interfaces hanging off a parent — exactly the same model as RouterOS Plane 1.

Each VLAN child interface attaches to exactly one parent.  Multi-port VLAN membership is achieved by creating multiple child interfaces sharing the same `vlanid` value, but this is uncommon in firewall-edge deployments.

There is no first-class L2-multi-port surface — the FortiGate hardware-switch sub-feature on a few low-end models supports it but it is FortiGate-specific and not in canonical scope.

## Cross-vendor mapping (RouterOS → FortiGate)

Canonical surface (per-VLAN):

```
CanonicalVlan.id: int
CanonicalVlan.name: str
CanonicalVlan.description: str
CanonicalVlan.tagged_ports: list[str]
CanonicalVlan.untagged_ports: list[str]
CanonicalVlan.ipv4_addresses: list[CanonicalIPv4Address]
```

- **id** — `good`.  RouterOS `vlan-id=100` populates the canonical VLAN id; FortiOS render synthesises a child interface (`edit "agg1.100" / set type vlan / set vlanid 100 / set interface "<parent>"`).
- **name** — `lossy`.  RouterOS conflates the VLAN's name with the L3 interface name (`vlan100`); FortiOS render emits the synthesised child-interface name (e.g. `agg1.100`) which differs from the canonical name.  The MikroTik codec's LossyPath on `/vlans/vlan/name` flags this explicitly.
- **description** — `unsupported`.  Neither vendor has a per-VLAN-id description field beyond per-interface comments / aliases.
- **tagged_ports / untagged_ports** — `unsupported`.  RouterOS bridge VLAN filtering populates the canonical port lists when the codec parses them, but FortiGate has no port-list-per-VLAN concept (each child interface attaches to exactly one parent).  Cross-vendor render would require synthesising multiple FortiGate VLAN child interfaces (one per parent) which the v1 render does not do.  Operators carrying multi-port VLAN membership from RouterOS to FortiGate must rely on FortiGate's hardware-switch sub-feature (low-end models only) and reconstruct manually.
- **ipv4_addresses** — `good`.  RouterOS `/ip address add address=10.100.0.1/24 interface=vlan100` populates the canonical SVI address list; FortiOS render emits `set ip 10.100.0.1 255.255.255.0` on the synthesised child interface via SVI absorption.

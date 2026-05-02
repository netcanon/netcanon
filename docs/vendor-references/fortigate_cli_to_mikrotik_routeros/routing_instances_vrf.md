# VRF / VDOM / routing instances: FortiGate FortiOS versus MikroTik RouterOS

## FortiGate FortiOS CLI

Sources:
- [FortiGate / FortiOS 7.4 Administration Guide — VDOMs](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/) — `config vdom`.
- [FortiGate / FortiOS 7.4 Administration Guide — Per-interface VRF](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/) — `set vrf <0-251>` on `config system interface`.

Retrieved: 2026-04-30

FortiGate has two parallel multi-routing-table primitives:

**VDOMs** (heavyweight, since FortiOS 5.x):

```
config vdom
    edit root
    next
    edit dmz
    next
end
```

Each VDOM is an independent virtual firewall instance with its own routing table, firewall policy table, address objects, and admin sessions.  Resources are partitioned at runtime.  Not analogous to Cisco named-VRFs.

**Per-interface integer VRF** (lightweight, since FortiOS 7.0):

```
config system interface
    edit "port1"
        set vrf 10
    next
end
```

`set vrf <0-251>` selects a VRF id within a VDOM.  This is closer in spirit to Cisco VRF-Lite but uses an integer identifier (0 = main VRF) rather than a named VRF.  No RD/RT.  No address-family multiplexing.

The FortiGate codec does not parse either VDOMs or per-interface VRF in v1.

## MikroTik RouterOS

Sources:
- [VRF — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/95584418/VRF) — `/ip vrf` (RouterOS 7+).

Retrieved: 2026-04-30

RouterOS 7 introduced `/ip vrf`:

```
/ip vrf
add name=customer-A interfaces=ether2,ether3
add name=customer-B interfaces=ether4
```

`name=` is an arbitrary identifier; `interfaces=` is the comma-list of bound interfaces.  Routes inherit the interface's VRF; static routes can carry `routing-mark=<MARK>` or `vrf=<NAME>` to override.

RouterOS's pre-VRF mechanism was `routing-mark=` on routes plus `/ip route rule` (policy routing) — still present and orthogonal to `/ip vrf`.

RD/RT are configured under BGP (`/routing bgp template`) not under `/ip vrf` itself; RouterOS keeps the L3VPN signalling separate from the VRF declaration.

The MikroTik codec does not parse `/ip vrf` in v1.

## Cross-vendor mapping (FortiGate → RouterOS)

Canonical surface:

```
CanonicalIntent.routing_instances: list[CanonicalRoutingInstance]
CanonicalRoutingInstance.name: str
CanonicalRoutingInstance.instance_type: str
CanonicalRoutingInstance.route_distinguisher: str
CanonicalRoutingInstance.rt_imports: list[str]
CanonicalRoutingInstance.rt_exports: list[str]
CanonicalRoutingInstance.l3_vni: int | None
```

- **routing_instances** — `unsupported`.  Neither codec parses VRF / VDOM in v1.  Even when both codecs land their parsers, FortiGate VDOMs do not map 1:1 to RouterOS `/ip vrf` (VDOMs are firewall-tenancy primitives carrying independent policy tables; RouterOS VRFs are routing-only).  Per-interface integer VRF on FortiOS 7.x maps closer in spirit to RouterOS named VRFs, but the integer-vs-name identity gap requires operator-curated mapping.
- **route_distinguisher / rt_imports / rt_exports** — `unsupported`.  RouterOS keeps RD/RT under `/routing bgp template`, not under the VRF itself; canonical's per-VRF RD/RT model maps imperfectly.  FortiGate has no native L3VPN concept (no BGP-VPNv4 signalling exposure).
- **l3_vni** — `unsupported`.  Neither vendor models EVPN-VXLAN L3VNIs in canonical scope.

The cross-pair status will follow when both codec parsers wire up.

## VXLAN-VNIs and EVPN Type-5

```
CanonicalIntent.vxlan_vnis: list[CanonicalVxlan]
CanonicalIntent.evpn_type5_routes: list[CanonicalEvpnType5Route]
```

Both fields are `unsupported` on this direction:

- FortiGate codec capability matrix lists `/vxlan-vnis/vni` as unsupported with rationale "VXLAN not modelled — FortiGate is a firewall codec".
- MikroTik codec capability matrix lists `/vxlan-vnis/vni` as unsupported with rationale "RouterOS VXLAN exists but is rare in canonical scope and not modelled in v1".

EVPN Type-5 routes have no representation in either codec.

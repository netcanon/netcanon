# VRF / VDOM / routing instances: MikroTik RouterOS versus FortiGate FortiOS

## MikroTik RouterOS

Sources:
- [VRF — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/95584418/VRF) — `/ip vrf` (RouterOS 7+).

Retrieved: 2026-04-30

```
/ip vrf
add name=customer-A interfaces=ether2,ether3
add name=customer-B interfaces=ether4
```

`name=` is an arbitrary identifier; `interfaces=` is the comma-list of bound interfaces.  Routes inherit the interface's VRF; static routes carry `routing-mark=` or `vrf=` to override.

RD/RT for L3VPN signalling are configured under BGP (`/routing bgp template`), not under `/ip vrf` itself.

The MikroTik codec does not parse `/ip vrf` in v1.

## FortiGate FortiOS CLI

Sources:
- [FortiGate / FortiOS 7.4 Administration Guide — VDOMs](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/) — `config vdom`.
- [FortiGate / FortiOS 7.4 Administration Guide — Per-interface VRF](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/) — `set vrf <0-251>` on `config system interface`.

Retrieved: 2026-04-30

FortiGate has two parallel multi-routing-table primitives:

**VDOMs** (heavyweight, since FortiOS 5.x) — independent virtual firewall instances with their own routing table, firewall policy, address objects, admin sessions.

```
config vdom
    edit dmz
    next
end
```

**Per-interface integer VRF** (lightweight, since FortiOS 7.0) — VRF id 0-251 selected per interface inside a VDOM.

```
config system interface
    edit "port1"
        set vrf 10
    next
end
```

Per-interface VRF is closer in spirit to RouterOS named VRFs, but with integer identification (no name).  The FortiGate codec does not parse either form in v1.

## Cross-vendor mapping (RouterOS → FortiGate)

Canonical surface:

```
CanonicalIntent.routing_instances: list[CanonicalRoutingInstance]
CanonicalRoutingInstance.name: str
CanonicalRoutingInstance.instance_type: str
CanonicalRoutingInstance.route_distinguisher: str
CanonicalRoutingInstance.rt_imports: list[str]
CanonicalRoutingInstance.rt_exports: list[str]
```

- **routing_instances** — `unsupported`.  Neither codec parses VRF in v1.  Even when both codecs land their parsers, RouterOS named VRF maps imperfectly to FortiOS per-interface integer VRF — operators would need a curated mapping table from RouterOS VRF names (e.g. `customer-A`) to FortiOS integer ids (e.g. `vrf 10`).  FortiGate VDOMs are heavyweight tenancy that does not map to RouterOS at all.
- **route_distinguisher / rt_imports / rt_exports** — `unsupported`.  RouterOS keeps RD/RT under `/routing bgp template`, not under `/ip vrf` itself.  FortiGate has no native L3VPN concept (no BGP-VPNv4 signalling exposure).

The cross-pair status will follow when both codec parsers wire up.

## VXLAN-VNIs and EVPN Type-5

```
CanonicalIntent.vxlan_vnis: list[CanonicalVxlan]
CanonicalIntent.evpn_type5_routes: list[CanonicalEvpnType5Route]
```

Both fields are `unsupported` on this direction:

- MikroTik codec capability matrix lists `/vxlan-vnis/vni` as unsupported with rationale "RouterOS VXLAN exists but is rare in canonical scope and not modelled in v1".
- FortiGate codec capability matrix lists `/vxlan-vnis/vni` as unsupported with rationale "VXLAN not modelled — FortiGate is a firewall codec".

EVPN Type-5 routes have no representation in either codec.

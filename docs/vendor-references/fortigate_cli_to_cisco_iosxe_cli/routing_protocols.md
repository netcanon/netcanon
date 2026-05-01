# Routing protocols (BGP / OSPF / static): FortiGate FortiOS versus Cisco IOS-XE

Reverse-direction sibling of
[`../cisco_iosxe_cli_to_fortigate_cli/routing_protocols.md`](../cisco_iosxe_cli_to_fortigate_cli/routing_protocols.md).
Source URLs unchanged.

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide — Routing](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/) — `config router bgp`, `config router ospf`.
Retrieved: 2026-04-30

FortiOS routing engine (FRR-based fork) supports BGP, OSPF (v2 and
v3), RIP, IS-IS:

```
config router bgp
    set as 65000
    set router-id 10.0.0.1
    config neighbor
        edit "10.0.0.2"
            set remote-as 65001
        next
    end
end

config router ospf
    set router-id 10.0.0.1
    config area
        edit 0.0.0.0
        next
    end
end
```

## Cisco IOS-XE

Source: Cisco IOS XE IP Routing Configuration Guide — BGP, OSPF,
EIGRP.

```
router bgp 65000
 bgp router-id 10.0.0.1
 neighbor 10.0.0.2 remote-as 65001
!
router ospf 1
 router-id 10.0.0.1
 network 10.0.0.0 0.0.0.255 area 0
```

## Cross-vendor mapping (FortiGate -> Cisco)

The canonical schema **does not model** dynamic routing protocols
in v1.  Both codecs handle dynamic-routing intent as `raw_sections`
(Tier 3) parse-and-ignore.

Cross-vendor migration of FortiGate routing-protocol intent to
Cisco is therefore **out of scope**.  Operators migrating between
platforms should manually recreate routing-protocol intent on the
target.

The reverse-direction observation: even though FortiGate's routing
engine is FRR-based and shares much of the Cisco-flavoured CLI
grammar (`config router bgp / set as / config neighbor / set
remote-as`), the canonical model has no dynamic-routing fields to
land on, so the surface similarity does not translate to actual
cross-vendor support.

Disposition: **unsupported** in both directions.  Reason: canonical
schema gap.

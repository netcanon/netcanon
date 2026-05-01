# Routing instances / VRF: Cisco IOS-XE versus MikroTik RouterOS

## Cisco IOS-XE

Source: Cisco IOS XE MPLS L3 VPN Configuration Guide.

```
vrf definition TENANT-A
 rd 65000:100
 address-family ipv4
  route-target export 65000:100
  route-target import 65000:100

interface GigabitEthernet0/0/3
 vrf forwarding TENANT-A
 ip address 10.20.0.1 255.255.255.0

ip route vrf TENANT-A 0.0.0.0 0.0.0.0 10.20.0.254
```

Cisco IOS-XE uses `vrf definition <name>` plus an `address-family
ipv4 / route-target import|export` block.  Per-interface membership
is the `vrf forwarding <name>` line on the interface stanza.

## MikroTik RouterOS

Source: [VRF — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/95584418/VRF)

Retrieved: 2026-04-30

```
/ip vrf
add name=TENANT-A interfaces=ether3,vlan20

/ip route
add dst-address=0.0.0.0/0 gateway=10.20.0.254 routing-table=TENANT-A

/routing bgp connection
add name=tenant-a-peer remote.address=192.0.2.5 \
    remote.as=64512 vrf=TENANT-A
```

RouterOS 7+ models VRFs as `/ip vrf` records that own a list of
member interfaces.  Per-VRF static routes use the `routing-table=`
parameter on `/ip route`; per-VRF BGP / OSPF lives under `/routing
bgp connection` / `/routing ospf instance` with a `vrf=` parameter.

Crucially, RouterOS's `/ip vrf` does NOT carry RD or RT attributes
directly — those are BGP-side concepts and live under `/routing bgp
template` for the address-family that announces the VRF's prefixes.
This is structurally similar to Arista's "RD/RT under router bgp"
model and unlike Cisco's "RD/RT inside the vrf definition" model.

## Cross-vendor mapping

The canonical surface is

```
CanonicalRoutingInstance(name, instance_type, route_distinguisher,
                         rt_imports[], rt_exports[], description, l3_vni)
CanonicalInterface(vrf: str)            # back-pointer
```

### Codec status

The Cisco IOS-XE codec lists `/routing-instances/instance` as
**unsupported** — `vrf definition` blocks parse-and-ignore in v1
(per the codec's `CapabilityMatrix`).  The MikroTik codec also
does not yet wire up `/ip vrf` — the canonical
`routing_instances` list is empty after parsing either side.

This means the cross-pair disposition for the entire VRF surface
is **unsupported** today regardless of structural compatibility.
When wire-up lands on either side, the cross-pair surface upgrades
to lossy (RD/RT carry, `instance_type` is always `vrf`, no L3 VNI
on RouterOS today).

### Disposition (today, with caveats for future wire-up)

| Field | Disposition |
|---|---|
| `routing_instances` (whole list) | unsupported (Cisco IOS-XE codec parse-and-ignores VRF stanzas) |
| `routing_instances[].name` | unsupported (codec gap) |
| `routing_instances[].instance_type` | unsupported (codec gap; both vendors implicitly support `vrf`) |
| `routing_instances[].route_distinguisher` | unsupported (codec gap; structurally lossy when wired) |
| `routing_instances[].rt_imports` | unsupported (codec gap) |
| `routing_instances[].rt_exports` | unsupported (codec gap) |
| `routing_instances[].l3_vni` | unsupported (RouterOS does not model EVPN L3 VNI) |
| `interfaces[].vrf` (back-pointer) | unsupported (interface-side parse-and-ignore mirrors the routing-instance side) |

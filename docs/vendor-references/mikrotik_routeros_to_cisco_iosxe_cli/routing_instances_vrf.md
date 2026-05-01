# Routing instances / VRF: MikroTik RouterOS versus Cisco IOS-XE

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

RouterOS 7+ models VRFs as `/ip vrf` records owning a list of
member interfaces.  RD/RT live under `/routing bgp template` for
the address-family announcing the VRF.

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
```

Cisco IOS-XE bundles RD + RT inside the `vrf definition` block;
per-interface membership is `vrf forwarding <name>`.

## Cross-vendor mapping

The canonical surface is

```
CanonicalRoutingInstance(name, instance_type, route_distinguisher,
                         rt_imports[], rt_exports[], description, l3_vni)
CanonicalInterface(vrf: str)
```

### Codec status

The MikroTik codec does not yet wire up `/ip vrf` parsing — the
canonical `routing_instances` list is empty after parsing.  The
Cisco IOS-XE codec lists `/routing-instances/instance` as
**unsupported** in its capability matrix (parse-and-ignores `vrf
definition` blocks in v1).  Both sides currently produce no
canonical VRF records; the entire surface is unsupported on the
cross-pair regardless of structural compatibility.

When the MikroTik codec gains `/ip vrf` parsing, the canonical
record will populate `name` + `interfaces` (via the back-pointer
on `CanonicalInterface.vrf`).  The RD/RT fields would still be
empty — RouterOS keeps those on the BGP side, and the canonical
model would need a richer wire-up to bridge them across.

### Disposition (today, with caveats for future wire-up)

| Field | Disposition (MikroTik -> Cisco) |
|---|---|
| `routing_instances` (whole list) | unsupported (neither codec wires up VRF parse in v1) |
| `routing_instances[].name` | unsupported (codec gap on both sides) |
| `routing_instances[].instance_type` | unsupported (codec gap; RouterOS does not model the variant) |
| `routing_instances[].route_distinguisher` | unsupported (codec gap; RouterOS keeps RD under BGP) |
| `routing_instances[].rt_imports` / `rt_exports` | unsupported (codec gap) |
| `routing_instances[].l3_vni` | unsupported (RouterOS does not model EVPN) |
| `interfaces[].vrf` (back-pointer) | unsupported (codec gap on both sides) |

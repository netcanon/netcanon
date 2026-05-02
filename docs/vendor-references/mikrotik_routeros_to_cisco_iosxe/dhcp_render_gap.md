# DHCP server render gap — RouterOS source to cisco_iosxe NETCONF target

Source: [openconfig-system YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-system.html)
Retrieved: 2026-05-01

Source: [DHCP — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/24805500/DHCP)
Retrieved: 2026-05-01

## RouterOS DHCP server source

RouterOS DHCP server is a three-section structure:

```
/ip pool
add name=pool-lan ranges=192.168.10.100-192.168.10.200

/ip dhcp-server
add address-pool=pool-lan disabled=no interface=ether1 lease-time=1d \
    name=dhcp-lan

/ip dhcp-server network
add address=192.168.10.0/24 dns-server=8.8.8.8 gateway=192.168.10.1
```

The MikroTik parser joins the three sections by network-address /
pool-name reference and emits a `CanonicalDHCPPool` record per
network with start_ip, end_ip, gateway, dns_servers, lease_time,
and the parent interface for serving.

Static DHCP reservations (`/ip dhcp-server lease`) and DHCP option
codes are not modelled canonically and drop to raw_sections on parse.

## What the cisco_iosxe target render emits

Nothing for DHCP.  Two layers of absence:

1. The `_render_canonical()` method walks `intent.interfaces` only —
   it never reads `intent.dhcp_servers`.
2. OpenConfig has no first-class DHCP-server model.  Cisco IOS-XE
   exposes DHCP server configuration via the `Cisco-IOS-XE-dhcp.yang`
   native YANG module rather than through OpenConfig.  The
   cisco_iosxe codec is OpenConfig-only and does not bridge native
   YANG modules.  Even if the codec grew render coverage for
   `intent.dhcp_servers`, the output XML would have to leave the
   OpenConfig namespace to express DHCP server pools — a substantial
   scope change for a stub codec.

## Disposition

`dhcp_servers`: `unsupported` with reason citing the render-side
wire-up gap (and the upstream OpenConfig modelling gap).

This will not change until either:

* The cisco_iosxe codec gains native-YANG support for
  `Cisco-IOS-XE-dhcp.yang` (substantial scope creep — the codec
  would no longer be "OpenConfig-only"), OR
* OpenConfig grows a DHCP-server augment and Cisco devices implement
  it (currently no such model in `openconfig/public`).

Operators migrating RouterOS DHCP server pools to Cisco IOS-XE via
this codec pair must capture the result via the
`mikrotik_routeros__cisco_iosxe_cli` sibling pair instead — that
pair's target render walks `intent.dhcp_servers` and emits
`ip dhcp pool <name>` stanzas.

## Reference: what the sibling CLI target does emit

For comparison, the `cisco_iosxe_cli` render of the same canonical
record produces:

```
ip dhcp excluded-address 192.168.10.1 192.168.10.99
ip dhcp pool LAN
 network 192.168.10.0 255.255.255.0
 default-router 192.168.10.1
 dns-server 8.8.8.8
 lease 1
```

None of this lands via the cisco_iosxe NETCONF render.

## Direction-specific note

This is the first "structurally `unsupported`" disposition where
upstream OpenConfig modelling is the blocker rather than codec wire-
up alone.  Even a fully-featured OpenConfig-only render of the
cisco_iosxe codec would still have to emit DHCP-server config
through native-YANG bridging, which is outside the codec's
declared scope.

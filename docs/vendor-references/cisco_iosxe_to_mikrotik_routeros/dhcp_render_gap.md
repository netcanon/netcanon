# DHCP server render gap — cisco_iosxe NETCONF source to RouterOS target

Source: [openconfig-system YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-system.html)
Retrieved: 2026-05-01

Source: [DHCP — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/24805500/DHCP)
Retrieved: 2026-05-01

## OpenConfig DHCP scope

OpenConfig has no first-class DHCP-server model.  Cisco IOS-XE
exposes DHCP server configuration via the
`Cisco-IOS-XE-dhcp.yang` native YANG module rather than through
OpenConfig.  The cisco_iosxe codec is OpenConfig-only and does not
bridge native YANG modules; its capability matrix does not declare
any `/dhcp/...` paths and its `parse()` ignores any DHCP elements
that might appear in the source XML.

The canonical `intent.dhcp_servers` list is always empty after a
cisco_iosxe NETCONF parse.

## RouterOS DHCP server form

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

If `intent.dhcp_servers` were populated, the MikroTik codec would
emit the three-section form on render.  Because the source codec
never populates it, the cross-pair render emits no `/ip pool` /
`/ip dhcp-server` / `/ip dhcp-server network` lines.

## Disposition

`dhcp_servers`: `not_applicable` — source codec produces no DHCP
intent on parse.  This will not change until either:

* The cisco_iosxe codec gains native-YANG support for
  `Cisco-IOS-XE-dhcp.yang` (substantial scope creep — the codec
  would no longer be "OpenConfig-only"), OR
* OpenConfig grows a DHCP-server augment and Cisco devices implement
  it (currently no such model in `openconfig/public`).

Operators migrating Cisco IOS-XE DHCP server pools to RouterOS via
this codec pair must capture the source via the
`cisco_iosxe_cli` codec instead — that codec parses `ip dhcp pool`
stanzas and populates `intent.dhcp_servers`, which the MikroTik
render then emits with documented losses (see the sibling
`cisco_iosxe_cli__mikrotik_routeros` pair's `dhcp_server.md` for
the full disposition).

## Reference: parsed shape

For comparison, the sibling `cisco_iosxe_cli` codec parses:

```
ip dhcp pool LAN
 network 192.168.10.0 255.255.255.0
 default-router 192.168.10.1
 dns-server 8.8.8.8
 lease 1
ip dhcp excluded-address 192.168.10.1 192.168.10.99
```

into a `CanonicalDHCPPool` record with network=192.168.10.0/24,
gateway=192.168.10.1, dns_servers=[8.8.8.8], start_ip=192.168.10.100,
end_ip=192.168.10.254.  None of this lands via the cisco_iosxe
NETCONF codec.

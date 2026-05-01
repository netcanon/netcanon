# DHCP: Aruba AOS-S versus MikroTik RouterOS

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 IPv4 Configuration Guide for
2930F / 2930M / 3810 / 5400R — DHCP relay chapter](https://www.arubanetworks.com/techdocs/AOS-S/16.10/IPv4/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

Aruba AOS-S is **primarily a DHCP relay platform**, not a server.
On the 2930F / 2930M / 3810 / 5400R class of switches, DHCP server
pool configuration was added later in 16.x but is not widely used in
campus deployments — operators relay to a centralised server using
`ip helper-address <ip>` on a VLAN SVI.

The aruba_aoss codec does not advertise `/dhcp/pool` in its
supported set — `CanonicalIntent.dhcp_servers` is always empty
when the source vendor is Aruba AOS-S.  `ip helper-address`
directives are NOT modelled canonically (no
`CanonicalInterface.helper_addresses` field) so they drop on
parse.

## MikroTik RouterOS

Source: [DHCP — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/24805500/DHCP)
Retrieved: 2026-04-30

```
/ip pool
add name=lan_pool ranges=10.0.0.100-10.0.0.200

/ip dhcp-server
add address-pool=lan_pool authoritative=yes disabled=no \
    interface=bridge1 lease-time=1h name=lan-dhcp

/ip dhcp-server network
add address=10.0.0.0/24 gateway=10.0.0.1 \
    dns-server=10.0.0.1,1.1.1.1 domain=lab.example.net
```

RouterOS splits DHCP server config across **three sections**:
- `/ip pool` — defines the address range
- `/ip dhcp-server` — declares the server (interface, lease time,
  authoritative flag)
- `/ip dhcp-server network` — declares the gateway / DNS / domain
  options for clients on a given subnet

The MikroTik codec joins these on parse into a single
`CanonicalDHCPPool` per network and emits all three on render.

Static reservations live on `/ip dhcp-server lease`; DHCP options
(`option-set` / per-class options) live on `/ip dhcp-server option`
and `/ip dhcp-server option sets`.  Neither is modelled canonically.

DHCP relay on RouterOS uses `/ip dhcp-relay add` (independent
configuration block).  Aruba's `ip helper-address` model has no
direct canonical translation.

## Cross-vendor mapping

The canonical surface is

```
CanonicalDHCPPool(interface, network, start_ip, end_ip, gateway,
                  dns_servers[], lease_time, domain_name)
```

Aruba source -> RouterOS target: `dhcp_servers` is always empty on
the source side because the aruba_aoss codec does not parse DHCP
pools.  Cross-vendor render emits no DHCP server config on the
RouterOS target.

RouterOS source -> Aruba target: `dhcp_servers` populates from the
three-section RouterOS form.  Aruba target render drops the pool
config (the aruba_aoss codec does not advertise `/dhcp/pool` in its
supported set); the RouterOS-rich pool plumbing falls off the
canonical Aruba target with a banner directing the operator to
configure a relay-and-central-server topology.

### Disposition

| Field | Disposition |
|---|---|
| `dhcp_servers[].interface` | not_applicable (Aruba source) / unsupported on Aruba target |
| `dhcp_servers[].network` | not_applicable (Aruba source) / unsupported on Aruba target |
| `dhcp_servers[].start_ip` | same |
| `dhcp_servers[].end_ip` | same |
| `dhcp_servers[].gateway` | same |
| `dhcp_servers[].dns_servers` | same |
| `dhcp_servers[].lease_time` | same |
| `dhcp_servers[].domain_name` | same |
| Aruba `ip helper-address` (relay) | unsupported (canonical schema gap) |
| RouterOS `/ip dhcp-server lease` (static reservations) | unsupported (canonical schema gap) |
| RouterOS DHCP option codes | unsupported (canonical schema gap) |

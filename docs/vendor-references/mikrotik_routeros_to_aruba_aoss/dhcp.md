# DHCP: MikroTik RouterOS versus Aruba AOS-S

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
- `/ip dhcp-server network` — declares gateway / DNS / domain
  options for clients on a given subnet

The MikroTik codec joins these on parse into a single
`CanonicalDHCPPool` per network.  Static reservations
(`/ip dhcp-server lease`) and per-subnet option sets
(`/ip dhcp-server option`) are NOT modelled canonically and drop
to `raw_sections`.

DHCP relay uses `/ip dhcp-relay add` — a separate configuration
block.

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 IPv4 Configuration Guide for
2930F / 2930M / 3810 / 5400R — DHCP relay chapter](https://www.arubanetworks.com/techdocs/AOS-S/16.10/IPv4/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

Aruba AOS-S is **primarily a DHCP relay platform**, not a server.
DHCP server pool support exists in 16.x but is not widely used;
campus deployments relay to a centralised server using
`ip helper-address <ip>` on a VLAN SVI.

The aruba_aoss codec does not advertise `/dhcp/pool` in its
supported set — Aruba target render drops the pool config with a
relay-comment banner.  `ip helper-address` is NOT modelled
canonically.

## Cross-vendor mapping

The canonical surface is

```
CanonicalDHCPPool(interface, network, start_ip, end_ip, gateway,
                  dns_servers[], lease_time, domain_name)
```

RouterOS source -> Aruba target: `dhcp_servers` populates from the
three-section RouterOS form.  Aruba target render drops the pool
config (the aruba_aoss codec does not render `/dhcp/pool`); the
codec emits a banner directing the operator to configure relay-and-
central-server topology instead.

### Specific lossy points

- **RouterOS pools with multiple `ranges=` segments** — the codec
  collapses to a single start_ip/end_ip range on canonical; the
  gap surfaces in `raw_sections` for operator review.
- **Static reservations** (`/ip dhcp-server lease`) — not
  modelled; drop to `raw_sections`.
- **DHCP options** (`option-set`, `dhcp-option-set`) — not
  modelled.
- **Whole-pool drop on Aruba target** — Aruba does not
  auto-render server pools; entire `dhcp_servers` list emits as a
  relay-comment banner on Aruba target.

### Disposition

| Field | Disposition |
|---|---|
| `dhcp_servers[].interface` | unsupported on Aruba target (no DHCP server pools) |
| `dhcp_servers[].network` | unsupported |
| `dhcp_servers[].start_ip` | unsupported |
| `dhcp_servers[].end_ip` | unsupported |
| `dhcp_servers[].gateway` | unsupported |
| `dhcp_servers[].dns_servers` | unsupported |
| `dhcp_servers[].lease_time` | unsupported |
| `dhcp_servers[].domain_name` | unsupported |
| RouterOS `/ip dhcp-server lease` (static reservations) | unsupported (canonical schema gap) |
| RouterOS DHCP option codes | unsupported (canonical schema gap) |
| Aruba `ip helper-address` (relay) | unsupported (canonical schema gap) |

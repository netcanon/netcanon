# DHCP: MikroTik RouterOS versus Aruba AOS-S

> **Update 2026-11-10 — the codec writes the pool.**  This page describes AOS-S as a relay platform.  AOS-S 16.x switches run a DHCP server of their own (HPE's AOS-S Management and Configuration Guide: a `dhcp-server pool`, served on a VLAN that states `dhcp-server`, once `dhcp-server enable` is set), the aruba_aoss parser reads one, and the renderer now writes one as the switch prints it: a `dhcp-server pool` stanza after the VLANs (`default-router`, `dns-server`, `domain-name`, `lease DD:HH:MM`, `network`, `range`), `dhcp-server` in the stanza of the VLAN that serves it, and `dhcp-server enable` last.  A pool is served where the output's VLAN stanza for its interface holds an address of its network; where none does, it is written with a `; review:` line, and the switch serves it only to clients a DHCP relay forwards to it.  A RouterOS pool on a VLAN interface whose address the output writes in a VLAN stanza is served there; one on a bridge or a port is written with its review line.  The disposition is now `lossy`, for where a pool is served, and the table below, written when every field was `unsupported`, is kept as it was.

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
`CanonicalDHCPPool` per enabled `/ip dhcp-server`.  Static
reservations (`/ip dhcp-server lease`) and per-subnet option sets
(`/ip dhcp-server option`) are NOT modelled canonically and are not
translated; nothing in the job says so yet.

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

- **RouterOS pools with multiple `ranges=` segments** — the tree
  holds one run of a pool: the parser keeps the largest (the lower
  of two as large), and the others are a row of the sections not
  translated.  Up to 0.7.7 it kept the first, and nothing said so.
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

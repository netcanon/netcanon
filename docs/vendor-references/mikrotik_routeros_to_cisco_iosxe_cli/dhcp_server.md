# DHCP server: MikroTik RouterOS versus Cisco IOS-XE

> **Update 2026-11-06 — the IOS-XE CLI codec reads and writes a pool's range.**  This page was written when `cisco_iosxe_cli` read a pool's `network` alone and wrote no `ip dhcp excluded-address`, so a pool's range and the interface it was served on were lost both ways.  The parser now reads a pool as the server hands it out (Cisco's "Configuring the Cisco IOS XE DHCP Server": every address of the network but those `ip dhcp excluded-address` names and the device's own) and puts it on the interface whose subnet is the pool's network; the renderer writes a range as the exclusions on either side of it.  What the tree has no place for (a pool an exclusion cuts in two, a manual binding, an option) is a row of the sections not translated.  See `docs/vendors/cisco_iosxe.md` § "Lossy paths".

## MikroTik RouterOS

Source: [DHCP — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/24805500/DHCP)

Retrieved: 2026-04-30

```
/ip pool
add name=dhcp_users ranges=192.168.10.11-192.168.10.254

/ip dhcp-server network
add address=192.168.10.0/24 \
    gateway=192.168.10.1 \
    dns-server=1.1.1.1,8.8.8.8 \
    domain=example.com

/ip dhcp-server
add address-pool=dhcp_users disabled=no interface=bridge1 \
    lease-time=1d name=dhcp1
```

Three sections:

- `/ip pool` — handout range.
- `/ip dhcp-server network` — per-subnet client options
  (gateway, DNS, domain, NTP).
- `/ip dhcp-server` — binds pool + network to a serving interface.

Static reservations live under `/ip dhcp-server lease`:

```
/ip dhcp-server lease
add address=192.168.10.5 mac-address=AA:BB:CC:DD:EE:FF \
    server=dhcp1
```

## Cisco IOS-XE

Source: Cisco IOS XE IP Addressing Configuration Guide.

```
ip dhcp pool USERS
 network 192.168.10.0 /24
 default-router 192.168.10.1
 dns-server 1.1.1.1 8.8.8.8
 lease 1 0 0
 domain-name example.com

ip dhcp excluded-address 192.168.10.1 192.168.10.10
```

## Cross-vendor mapping

The canonical surface is

```
CanonicalDHCPPool(interface, network, start_ip, end_ip,
                  gateway, dns_servers[], lease_time, domain_name)
```

The MikroTik codec parses the three RouterOS sections into a
single `CanonicalDHCPPool` per enabled `/ip dhcp-server` (joining
via `address-pool` <-> `/ip pool name`, and the network that holds
the pool's range).  Cross-vendor render to
Cisco emits a single `ip dhcp pool` block.

### MikroTik -> Cisco round-trip

- **interface / network / gateway / DNS / lease / domain** —
  good; field-by-field map.
- **start_ip / end_ip** — RouterOS encodes via `/ip pool ranges=`
  which can be a comma-separated list of ranges; the canonical
  model carries a single range.  Multi-range pools collapse.
- **Static reservations**: RouterOS's `/ip dhcp-server lease`
  records have no canonical field; both codecs leave them in
  `raw_sections`.

### Disposition

| Field | Disposition (MikroTik -> Cisco) |
|---|---|
| `dhcp_servers[].interface` | good |
| `dhcp_servers[].network` | good |
| `dhcp_servers[].start_ip / .end_ip` | lossy (multi-range pool collapses) |
| `dhcp_servers[].gateway` | good |
| `dhcp_servers[].dns_servers` | good |
| `dhcp_servers[].lease_time` | good |
| `dhcp_servers[].domain_name` | good |
| Static reservations | unsupported (no canonical field) |

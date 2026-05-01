# DHCP server: Cisco IOS-XE versus MikroTik RouterOS

## Cisco IOS-XE

Source: Cisco IOS XE IP Addressing Configuration Guide.

Cisco bundles the DHCP scope into a single `ip dhcp pool` stanza:

```
ip dhcp pool USERS
 network 192.168.10.0 /24
 default-router 192.168.10.1
 dns-server 1.1.1.1 8.8.8.8
 lease 1 0 0
 domain-name example.com

ip dhcp excluded-address 192.168.10.1 192.168.10.10
```

`network` defines the subnet, `default-router` the gateway, `dns-
server` the DNS list, `lease <days> <hours> <minutes>` the lease
time, and `excluded-address` carves out reserved ranges.

## MikroTik RouterOS

Source: [DHCP — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/24805500/DHCP)

Retrieved: 2026-04-30

RouterOS splits the same intent across **three** sections:

```
/ip pool
add name=dhcp_users ranges=192.168.10.11-192.168.10.254

/ip dhcp-server network
add address=192.168.10.0/24 \
  gateway=192.168.10.1 \
  dns-server=1.1.1.1,8.8.8.8 \
  domain=example.com

/ip dhcp-server
add address-pool=dhcp_users \
  disabled=no \
  interface=bridge1 \
  lease-time=1d \
  name=dhcp1
```

- `/ip pool` declares the address range available for handout.
- `/ip dhcp-server network` declares per-subnet client options
  (gateway, DNS, domain, NTP servers, lease).
- `/ip dhcp-server` binds the pool and network to a serving
  interface.

The split exists so a single pool can back multiple DHCP servers
or relay agents and so per-subnet options can vary independently
of the address range.

## Cross-vendor mapping

The canonical surface is

```
CanonicalDHCPPool(interface, network, start_ip, end_ip,
                  gateway, dns_servers[], lease_time, domain_name)
```

The Cisco codec's capability matrix lists `/dhcp/pool` paths under
its supported set; the MikroTik codec parses the three RouterOS
sections into a single `CanonicalDHCPPool` per network.  Cross-
vendor render reconstructs the three-section RouterOS form from
the canonical record.

### Lossy points

- **Excluded-address ranges**: Cisco's `ip dhcp excluded-address`
  carves out reserved ranges within the network; RouterOS expresses
  the same intent via the `/ip pool` `ranges=` parameter, which
  enumerates available ranges instead of excluded ones.  The
  canonical model carries `start_ip` / `end_ip` as a single range,
  so multi-fragment exclusion sets land partially.  Operators with
  complex exclusion lists need to review.
- **Reservation entries**: Cisco's `host` / `client-identifier` /
  `hardware-address` static reservations have no field on
  `CanonicalDHCPPool` — neither codec lifts them into the canonical
  model.  Both render paths drop them; landed under
  `raw_sections` for operator review.
- **Option codes**: Cisco's `option <code> ...` (e.g. option 43
  for vendor-specific data) is not modelled canonically; drops
  on round-trip.

### Disposition

| Field | Disposition |
|---|---|
| `dhcp_servers[].interface` | good |
| `dhcp_servers[].network` | good |
| `dhcp_servers[].start_ip / .end_ip` | lossy (multi-fragment exclusion sets compress) |
| `dhcp_servers[].gateway` | good |
| `dhcp_servers[].dns_servers` | good |
| `dhcp_servers[].lease_time` | good |
| `dhcp_servers[].domain_name` | good |
| Static reservations (`host` / `client-identifier`) | unsupported (no canonical field) |
| Option codes (option 43, etc.) | unsupported (no canonical field) |

# DHCP server: Juniper Junos versus MikroTik RouterOS

How DHCP server pools are declared on each platform.

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/dhcp/topics/topic-map/dhcp-server.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/dhcp/topics/concept/dhcp-local-server-overview.html (retrieved 2026-05-01)
- MikroTik: https://help.mikrotik.com/docs/spaces/ROS/pages/24805500/DHCP (retrieved 2026-05-01)

Citation ids: `junos-dhcp-server`, `junos-dhcp-local-server`,
`mikrotik-dhcp`.

## Junos form

```
set system services dhcp-local-server group SERVER-GROUP interface ge-0/0/1.0

set access address-assignment pool LAN_POOL family inet network 10.0.0.0/24
set access address-assignment pool LAN_POOL family inet range R1 low 10.0.0.100
set access address-assignment pool LAN_POOL family inet range R1 high 10.0.0.200
set access address-assignment pool LAN_POOL family inet dhcp-attributes \
    router 10.0.0.1
set access address-assignment pool LAN_POOL family inet dhcp-attributes \
    name-server 10.0.0.53
set access address-assignment pool LAN_POOL family inet dhcp-attributes \
    domain-name lab.example.net
set access address-assignment pool LAN_POOL family inet dhcp-attributes \
    maximum-lease-time 3600
```

Junos splits DHCP server config across two top-level sections:
`system services dhcp-local-server` (which interfaces serve which
pool group) and `access address-assignment pool` (the pool's network,
range, gateway, DNS, lease).  This split is non-trivial to round-trip
because the binding between the two sections is by group name.

## RouterOS form

```
/ip pool
add name=lan_pool ranges=10.0.0.100-10.0.0.200

/ip dhcp-server
add address-pool=lan_pool authoritative=yes disabled=no interface=bridge1 \
    lease-time=1h name=lan-dhcp

/ip dhcp-server network
add address=10.0.0.0/24 gateway=10.0.0.1 dns-server=10.0.0.1,1.1.1.1 \
    domain=lab.example.net
```

RouterOS splits DHCP server config across THREE sections: `/ip pool`
(the address range), `/ip dhcp-server` (the server instance binding
the pool to an interface, with lease time and authoritative flag),
and `/ip dhcp-server network` (the per-network gateway / DNS /
domain options).  The MikroTik codec joins the three on parse and
emits the three on render.  Static reservations live under
`/ip dhcp-server lease`.

## Cross-vendor mapping

* `dhcp_servers[].network`: Junos `pool ... family inet network X/N` ->
  RouterOS `/ip dhcp-server network add address=X/N`.
* `dhcp_servers[].start_ip` / `end_ip`: Junos `range R1 low / high` ->
  RouterOS `/ip pool add ranges=X-Y`.  Direct mapping for single-
  range pools.
* `dhcp_servers[].gateway`: Junos `dhcp-attributes router` ->
  RouterOS `/ip dhcp-server network add gateway=`.
* `dhcp_servers[].dns_servers`: Junos's per-line `name-server` ->
  RouterOS comma-separated `dns-server=A,B,C`.
* `dhcp_servers[].lease_time` (seconds): Junos `maximum-lease-time
  <secs>` -> RouterOS `lease-time=<duration>`.  RouterOS accepts
  human-readable durations (`1h`, `8h`, `1d`); the codec normalises
  on round-trip.
* `dhcp_servers[].domain_name`: Junos `dhcp-attributes domain-name X`
  -> RouterOS `/ip dhcp-server network add domain=X`.
* `dhcp_servers[].interface`: Junos's `dhcp-local-server group ...
  interface ge-0/0/1.0` binding -> RouterOS `/ip dhcp-server add
  interface=bridge1`.  Lossy because the Junos binding is via group
  name (one group can serve many interfaces) while RouterOS binds
  one server per interface.
* Static reservations: Junos `set access address-assignment pool X
  family inet host <name> hardware-address <mac> ip-address <ip>`
  -> RouterOS `/ip dhcp-server lease add address=<ip> mac-address=
  <mac>`.  Not modelled canonically — drops to raw_sections.
* DHCP options (option 43 / 60 / 66 / 150) — not modelled
  canonically.

Disposition: **lossy** — basic pool fields round-trip; per-section
binding model differs (Junos two-stage vs RouterOS three-stage);
static reservations + advanced options not canonically modelled.

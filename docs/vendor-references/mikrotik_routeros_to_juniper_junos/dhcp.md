# DHCP server: MikroTik RouterOS versus Juniper Junos

How DHCP server pools are declared on each platform.

Sources:
- MikroTik: https://help.mikrotik.com/docs/spaces/ROS/pages/24805500/DHCP (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/dhcp/topics/topic-map/dhcp-server.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/dhcp/topics/concept/dhcp-local-server-overview.html (retrieved 2026-05-01)

Citation ids: `mikrotik-dhcp`, `junos-dhcp-server`,
`junos-dhcp-local-server`.

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
and `/ip dhcp-server network` (the per-network gateway / DNS / domain
options).  The mikrotik_routeros codec joins the three on parse and
emits the three on render.  Static reservations live under
`/ip dhcp-server lease`.

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
range, gateway, DNS, lease).

## Cross-vendor mapping

* `dhcp_servers[].network`: RouterOS `/ip dhcp-server network add
  address=X/N` -> Junos `pool ... family inet network X/N`.
* `dhcp_servers[].start_ip` / `end_ip`: RouterOS `/ip pool add
  ranges=X-Y` -> Junos `range R1 low / high`.  Direct mapping for
  single-range pools.
* `dhcp_servers[].gateway`: RouterOS `gateway=` -> Junos
  `dhcp-attributes router`.
* `dhcp_servers[].dns_servers`: RouterOS comma-separated
  `dns-server=A,B,C` -> Junos per-line `dhcp-attributes name-server`.
* `dhcp_servers[].lease_time` (seconds): RouterOS `lease-time=1h`
  (human-readable duration) -> canonical seconds (3600) -> Junos
  `maximum-lease-time 3600`.  Round-trip clean for typical units.
* `dhcp_servers[].domain_name`: RouterOS `domain=` -> Junos
  `dhcp-attributes domain-name`.
* `dhcp_servers[].interface`: RouterOS `/ip dhcp-server add
  interface=X` -> Junos's `dhcp-local-server group ... interface X.0`
  (Junos requires the unit suffix on the interface binding).  The
  group-name binding is synthesised on Junos render.
* Static reservations: RouterOS `/ip dhcp-server lease add address=X
  mac-address=Y` -> Junos `pool X family inet host <name>
  hardware-address <mac> ip-address <ip>`.  Not modelled canonically
  — drops to raw_sections.
* DHCP options (option 43 / 60 / 66 / 150) — not modelled
  canonically.

Disposition: **lossy** — basic pool fields round-trip; per-section
binding model differs (RouterOS three-stage vs Junos two-stage);
static reservations + advanced options not canonically modelled.

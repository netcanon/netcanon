# DHCP server: MikroTik RouterOS three-section form versus Arista EOS pool block

## MikroTik RouterOS

Source: [DHCP — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/24805500/DHCP)
Retrieved: 2026-05-01

RouterOS splits DHCP server configuration across **three
sections**:

```
/ip pool
add name=lan_pool ranges=10.0.0.100-10.0.0.200
add name=users_pool ranges=10.100.0.100-10.100.0.200

/ip dhcp-server
add address-pool=lan_pool authoritative=yes disabled=no interface=bridge1 \
    lease-time=1h name=lan-dhcp
add address-pool=users_pool authoritative=yes disabled=no interface=vlan100 \
    lease-time=8h name=users-dhcp

/ip dhcp-server network
add address=10.0.0.0/24 gateway=10.0.0.1 dns-server=10.0.0.1,1.1.1.1 \
    domain=lab.example.net
add address=10.100.0.0/24 gateway=10.100.0.1 dns-server=10.100.0.1 \
    domain=users.example.net

/ip dhcp-server lease
add address=10.0.0.50 mac-address=AA:BB:CC:DD:EE:01
add address=10.0.0.51 mac-address=AA:BB:CC:DD:EE:02 server=lan-dhcp
```

The three sections work together:

* `/ip pool` — defines IP address pools (range or list of
  ranges).  The pool can have multiple `ranges=` segments.
* `/ip dhcp-server` — binds a pool to an interface, sets lease
  time, and names the DHCP server instance.
* `/ip dhcp-server network` — declares per-network options
  (gateway, DNS, domain, NTP, custom options).
* `/ip dhcp-server lease` — static reservations (MAC-IP
  bindings).

The `mikrotik_routeros` codec parses the three sections and
joins them into `CanonicalDHCPPool` records on the canonical
side.

## Arista EOS

Sources: [Arista EOS User Manual — DHCP Server](https://www.arista.com/en/um-eos/eos-dhcp-overview),
and the `dhcp-servers` template of Arista's config generator, AVD
(`eos_cli_config_gen`).
Retrieved: 2026-11-09

```
dhcp server
   !
   subnet 10.0.0.0/24
      !
      range 10.0.0.100 10.0.0.200
      dns server 10.0.0.1 1.1.1.1
      lease time 0 days 1 hours 0 minutes
      default-gateway 10.0.0.1
   !
   subnet 10.100.0.0/24
      !
      range 10.100.0.100 10.100.0.200
      dns server 10.100.0.1
      lease time 0 days 8 hours 0 minutes
      default-gateway 10.100.0.1
!
interface Vlan100
   ip address 10.100.0.1/24
   dhcp server ipv4
```

EOS keeps one server a VRF (`dhcp server [vrf <name>]`), a `subnet
<prefix>` for each pool with its ranges, DNS servers (up to two),
lease (days, hours and minutes) and default gateway, and
`dhcp server ipv4` under each interface that serves.  A domain is a
setting of the whole server.  Reservations are a `reservations`
block of the subnet.  See
[`../arista_eos_to_opnsense/dhcp.md`](../arista_eos_to_opnsense/dhcp.md)
for the grammar in full.

## Cross-vendor mapping

The canonical surface is `CanonicalIntent.dhcp_servers:
list[CanonicalDHCPPool]` with fields `interface` / `network` /
`start_ip` / `end_ip` / `gateway` / `dns_servers: list[str]` /
`lease_time` (seconds) / `domain_name`.

RouterOS -> Arista:

* The RouterOS parser joins the three sections (see
  [`../../vendors/mikrotik_routeros.md`](../../vendors/mikrotik_routeros.md)):
  `/ip dhcp-server` → `interface` + `lease_time`, its
  `address-pool=` → `start_ip` / `end_ip`, the `/ip dhcp-server
  network` that holds the range → `network` + `gateway` +
  `dns_servers` + `domain_name`.
* The EOS output writes each pool as a `subnet` of the server of its
  interface's VRF, and `dhcp server ipv4` under the interface where
  it holds an address of the pool's network.  Where it does not, or
  the output has no such interface, a `! review:` line in the subnet
  and a warning of the job say so.  The EOS parser reads the pool's
  interface back from that line.

Lossy bits:

* **Multiple ranges per pool:** the tree holds one run a pool, so of
  a `ranges=` of several the largest is kept and the others are a row
  of the sections not translated.  EOS writes one `range` line.

* **Static reservations, custom options and the keys the tree has no
  place for:** RouterOS `/ip dhcp-server lease`, `/ip dhcp-server
  option`, `ntp-server=`, `next-server=` and the like have no
  canonical field and are not written.

* **What EOS cannot be given as the tree has it:** a domain that not
  every subnet of the server has, DNS servers past two, a lease that
  does not end, a range outside the network.  Each is a `! review:`
  line and a warning of the job.

* **Lease-time format:** RouterOS uses `1h` / `8h` / `1d` time-unit
  form; EOS uses days / hours / minutes, a minute at the finest.
  Converted through the canonical `lease_time` integer seconds.

* **DC leaf typical:** Arista DC leafs usually delegate DHCP to an
  external service rather than running on-device pools, so the
  cross-pair lift may produce a config the operator doesn't want.

The MikroTik synthetic kitchen-sink carries two pools (`lan_pool`
+ `users_pool`) bound to `bridge1` / `vlan100` respectively.  Each
is a `subnet` of the EOS output's `dhcp server`, served on the
interface each becomes; their two domains differ, so neither is
written and each subnet has a review line.

Disposition: **lossy** — a pool and where it is served round-trip;
several ranges, static reservations and option codes do not.

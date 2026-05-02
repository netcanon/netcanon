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

Source: [Arista EOS — DHCP Server / DHCP Relay](https://www.arista.com/en/um-eos/eos-dhcpv4-server)
Retrieved: 2026-05-01

```
ip dhcp pool LAN_POOL
   network 10.0.0.0/24
   default-router 10.0.0.1
   dns-server 10.0.0.1 1.1.1.1
   domain-name lab.example.net
   lease 0 1 0
   range 10.0.0.100 10.0.0.200
!
ip dhcp pool USERS_POOL
   network 10.100.0.0/24
   default-router 10.100.0.1
   dns-server 10.100.0.1
   domain-name users.example.net
   lease 0 8 0
   range 10.100.0.100 10.100.0.200
!
```

Arista's `ip dhcp pool` is a single block — the pool name plus
network / default-router / dns-server / domain-name / lease /
range parameters live together.  Lease time uses
`<days> <hours> <minutes>` form (Cisco-derived).

Static reservations use a separate per-host syntax:

```
ip dhcp pool RESERVATIONS
   host 10.0.0.50
   client-identifier 01aa.bbcc.ddee.01
```

(Less common; Arista DC leafs typically delegate DHCP to an
external service.)

## Cross-vendor mapping

The canonical surface is `CanonicalIntent.dhcp_servers:
list[CanonicalDHCPPool]` with fields `interface` / `network` /
`start_ip` / `end_ip` / `gateway` / `dns_servers: list[str]` /
`lease_time` (seconds) / `domain_name`.

RouterOS -> Arista round-trip:

* RouterOS three-section form joins on parse: `/ip pool` →
  `start_ip` / `end_ip`, `/ip dhcp-server` → `interface` +
  `lease_time`, `/ip dhcp-server network` → `network` +
  `gateway` + `dns_servers` + `domain_name`.
* Arista render emits a single `ip dhcp pool <name>` block with
  the joined attributes.

Lossy bits:

* **Multiple ranges per pool:** RouterOS pools with multiple
  `ranges=10.0.0.100-10.0.0.150,10.0.0.180-10.0.0.200` segments
  collapse to a single start_ip/end_ip range on canonical (the
  union of the segments).  Arista render emits one `range` line.

* **Static reservations:** RouterOS `/ip dhcp-server lease`
  rows have no canonical field and drop to raw_sections.
  Arista render emits no reservations.

* **Custom DHCP options:** RouterOS supports custom options via
  `/ip dhcp-server option` (option 43 vendor-specific data,
  option 82 relay agent info, etc.) — not modelled canonically.
  Drops on render.

* **Lease-time format:** RouterOS uses `1h` / `8h` / `1d` time-
  unit form; Arista uses `<days> <hours> <minutes>`.  Codec
  converts via the canonical `lease_time` integer-seconds field.

* **DC leaf typical:** Arista DC leafs usually delegate DHCP to
  an external service rather than running on-device pools, so
  the cross-pair lift may produce a config the operator doesn't
  want.  Review banner is appropriate.

The MikroTik synthetic kitchen-sink carries two pools (`lan_pool`
+ `users_pool`) bound to `bridge1` / `vlan100` respectively.
Both lift to `CanonicalDHCPPool` and render to Arista as `ip
dhcp pool LAN_POOL` / `ip dhcp pool USERS_POOL` blocks.

Disposition: **lossy** — basic pool round-trips with documented
caveats; static reservations and option codes drop.

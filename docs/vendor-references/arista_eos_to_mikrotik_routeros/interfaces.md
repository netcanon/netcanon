# Interfaces and IP addressing: Arista EOS versus MikroTik RouterOS

## Arista EOS

Source: [Arista EOS — Interface Configuration](https://www.arista.com/en/um-eos/eos-interface-configuration)
Retrieved: 2026-05-01

```
interface Ethernet1
   description "Spine uplink (L3 routed)"
   no switchport
   mtu 9214
   ip address 10.0.0.1/31
   ipv6 address 2001:db8:0:1::1/64
   ipv6 address fe80::1 link-local
!
interface Ethernet2
   description "Access port for end-host"
   switchport mode access
   switchport access vlan 10
!
interface Loopback0
   description "VTEP / router-id"
   ip address 10.255.0.1/32
   ipv6 address 2001:db8:ffff::1/128
!
interface Management1
   description "Out-of-band management"
   ip address 192.168.100.10/24
!
interface Vlan100
   description "Tenant A data SVI"
   vrf TENANT_A
   ip address 10.100.0.1/24
   ipv6 address 2001:db8:100:100::1/64
!
```

Arista interface naming is **flat without a speed prefix**:
`Ethernet1` is the bare wire name, regardless of whether the
underlying port is 1G, 10G, 25G, 40G, 100G or 400G.  Stack /
chassis members use `Ethernet<unit>/<slot>/<port>` form
(`Ethernet2/1`, `Ethernet1/0/1`).  Loopback, Management and SVI
interfaces are first-class with explicit role-bearing names
(`Loopback<N>`, `Management<N>`, `Vlan<N>`).

L3 routed mode is opt-in via `no switchport` — a port defaults to
L2 access mode unless explicitly converted.  The `mtu` directive
takes a single integer (jumbo support up to 9214 on most
platforms).

IPv4 uses CIDR notation (`ip address 10.0.0.1/31`) directly on the
interface.  IPv6 uses `ipv6 address X/N` for global addresses and
`ipv6 address X link-local` for explicit link-local addresses.
Multiple v6 addresses per interface are supported and each is
parsed into a separate `CanonicalIPv6Address` record with its
`scope` discriminator preserved.

The `arista_eos` codec capability matrix lists
`/interfaces/interface/name`, `description`, `enabled`, `ipv4/
address/ip`, `ipv4/address/prefix-length`, `ipv6/address/ip`,
`ipv6/address/prefix-length`, and `config/vrf` under
**supported**.  `config/type` is listed under **lossy** with the
rationale that EOS interface names don't encode speed.

## MikroTik RouterOS

Sources:
- [Ethernet — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/41746442/Ethernet)
- [IP Addressing — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/328084/IP+Routing)
- [Bridge — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/47579231/Bridging+and+Switching)

Retrieved: 2026-05-01

```
/interface ethernet
set [ find default-name=ether1 ] comment="WAN uplink to ISP" disabled=no mtu=1500
set [ find default-name=ether2 ] comment="LAN trunk - bridge member" disabled=no mtu=1500

/interface bridge
add comment="Primary LAN bridge" name=bridge1

/interface vlan
add comment="Users VLAN" interface=bridge1 name=vlan100 vlan-id=100

/ip address
add address=198.51.100.2/30 interface=ether1
add address=10.100.0.1/24 interface=vlan100

/ipv6 address
add address=2001:db8:0:1::2/64 interface=ether1
add address=fe80::1/64 interface=ether1 advertise=no
```

RouterOS interface naming is **flat without a speed prefix**:
`ether1` / `ether2` for copper, `sfp-sfpplus1` for SFP+, `qsfp1`
for QSFP, etc.  The `default-name=` lookup uses the factory
binding to address ports without affecting their operator-
renamed name.

L3 routed mode is the default — every Ethernet port is a routed
port unless added to a `/interface bridge`.  The `mtu` directive
takes a single integer per interface.

IPv4 / IPv6 addressing is **decoupled** from the interface
declaration — addresses live in `/ip address` / `/ipv6 address`
sections with `interface=<name>` foreign keys.  Multiple
addresses per interface are supported.

Loopback emulation: RouterOS has no first-class loopback concept.
The conventional form is an empty `/interface bridge` with no
ports, plus `/ip address add address=10.255.0.1/32
interface=lo-bridge`.

VLAN sub-interfaces use `/interface vlan name=vlanN
interface=<parent> vlan-id=N` — the operator name (`vlanN`) is
the L3 interface name and is conflated with the VLAN's symbolic
name in the canonical model (per the MikroTik codec's
`LossyPath` on `/vlans/vlan/name`).

The `mikrotik_routeros` codec capability matrix lists
`/interfaces/interface/name`, `description`, `enabled`, `ipv4/
address/ip`, `ipv4/address/prefix-length`, `ipv6/address/ip`,
`ipv6/address/prefix-length` under **supported**.  `config/type`
is listed under **lossy**.

## Cross-vendor mapping

The canonical surface is `CanonicalIntent.interfaces:
list[CanonicalInterface]` where `CanonicalInterface` carries
name / default_name / description / enabled / interface_type /
mtu / ipv4_addresses / ipv6_addresses / switchport_* / vrf etc.

Arista -> RouterOS round-trip:

* Arista `interface Ethernet1` parse: populates `name="Ethernet1"`,
  `default_name=""` (Arista has no factory-default-name concept).
  Cross-vendor port-name mesh maps `Ethernet1` -> `ether1`; the
  codec emits `/interface ethernet / set [ find default-name=
  ether1 ] comment="<description>" disabled=no`.
* Arista `description "<text>"` -> RouterOS `comment="<text>"` on
  the `/interface ethernet` row.
* Arista `mtu 9214` -> RouterOS `mtu=9214` on the same row.  Both
  accept integer MTU.
* Arista `ip address 10.0.0.1/31` -> RouterOS `/ip address add
  address=10.0.0.1/31 interface=ether1`.  CIDR form preserved
  both sides.
* Arista `ipv6 address fe80::1 link-local` -> RouterOS `/ipv6
  address add address=fe80::1/64 interface=ether1 advertise=no`.
  The `scope=link-local` discriminator is preserved through the
  canonical model; RouterOS render annotates with `advertise=no`
  to match the link-local-only semantic.
* Arista `interface Loopback0 / ip address 10.255.0.1/32` ->
  RouterOS empty-bridge form: `/interface bridge add
  name=loopback-bridge comment="Loopback emulation"` plus
  `/ip address add address=10.255.0.1/32 interface=loopback-
  bridge`.  `interface_type` inference handles the role bit.
* Arista `interface Management1` (out-of-band port) has no
  RouterOS analogue — typical RouterOS form is to use a regular
  `etherN` for management; the codec emits the management
  address on the rename-mesh-chosen ether port with a banner.
* Arista `interface Vlan100 / ip address 10.100.0.1/24` ->
  RouterOS `/interface vlan add name=vlan100 interface=bridge1
  vlan-id=100` plus `/ip address add address=10.100.0.1/24
  interface=vlan100`.  SVI VRF binding (`vrf TENANT_A`) drops
  on RouterOS render.
* Arista's `no switchport` indicator (routed mode) maps to
  RouterOS's default routed mode (no bridge membership) — direct
  semantic.

Disposition: **good** for description / enabled / mtu /
ipv4_addresses / ipv6_addresses on physical Ethernet / loopback;
**lossy** for the structural bits — name remap, switchport mode
(see `vlans.md`), Loopback emulation, Management1 fallback, SVI
VRF binding.

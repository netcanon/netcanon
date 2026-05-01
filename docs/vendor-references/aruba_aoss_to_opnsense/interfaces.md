# Interfaces: Aruba AOS-S versus OPNsense

## Aruba AOS-S

Source: [Aruba AOS-S 16.10 Basic Operation Guide — Interface
naming](https://www.arubanetworks.com/techdocs/AOS-S/16.10/BOG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
interface 1
   name "user-desk-01"
   enable
   exit
interface A1
   name "router-uplink-A"
   routing
   ip address 10.0.0.2/30
   ipv6 address 2001:db8:0:a::2/64
   exit
interface Trk1
   name "to-core"
   exit
```

Aruba AOS-S interface naming notes:

- Physical access ports use a bare numeric (`1`, `13`, `24`) for
  fixed-port standalone switches and slot/port numbering for stack
  members.
- Letter-uplink ports (`A1`, `A2`, `B1`) appear on platforms with
  module bays (5400R chassis, 3810 stacks).
- LAGs are named `Trk<N>` (one-based).
- VLAN SVIs are accessed via `vlan <id>` stanzas (not a separate
  `interface vlan` form).
- The `routing` keyword inside an interface stanza promotes a port
  to L3 (analogous to Cisco `no switchport`).
- IPv4 addresses use CIDR (`10.0.0.2/30`) or dotted mask
  (`10.0.0.2 255.255.255.252`) — both parse.

## OPNsense

Source: [OPNsense Interfaces manual](https://docs.opnsense.org/manual/interfaces.html)
Retrieved: 2026-04-30

OPNsense identifies interfaces in two layers:

1. The BSD device — `em0`, `em1`, `igb0`, `vtnet0`, `mvneta0`, etc.
   This is the kernel-side name and lives in `<if>` elements.
2. The OPNsense **zone label** — `<wan>`, `<lan>`, `<opt1>`, `<opt2>`,
   …  This is the operator-facing identifier; firewall rules,
   gateways, DHCP scopes all reference the zone label rather than the
   BSD name.

```xml
<opnsense>
  <interfaces>
    <wan>
      <if>em0</if>
      <descr>Internet</descr>
      <enable>1</enable>
      <ipaddr>198.51.100.10</ipaddr>
      <subnet>30</subnet>
      <ipaddrv6>2001:db8::10</ipaddrv6>
      <subnetv6>64</subnetv6>
      <mtu>1500</mtu>
    </wan>
    <lan>
      <if>em1</if>
      <descr>Lab</descr>
      <enable>1</enable>
      <ipaddr>10.0.10.1</ipaddr>
      <subnet>24</subnet>
    </lan>
    <opt2>
      <if>em1_vlan20</if>
      <descr>Voice</descr>
      <enable>1</enable>
      <ipaddr>10.10.20.1</ipaddr>
      <subnet>24</subnet>
    </opt2>
  </interfaces>
</opnsense>
```

Key shape differences from Aruba:

- The XML tag IS the operator-facing name (no separate `<name>`
  child).
- `<enable>1</enable>` (or absent / `<enable/>`) replaces the
  `enable` / `disable` keyword.
- IPv4 address + mask use `<ipaddr>` + `<subnet>` (CIDR length).
- MTU is an explicit `<mtu>` child element (range 576-9000 on
  recent OPNsense).
- No `routing` keyword equivalent — every OPNsense interface is L3
  by definition (firewall is L3-only).
- VLAN sub-interfaces use the synthesised `<if>em1_vlan20</if>`
  device name; the parent `<vlan>` declaration in `<vlans>` carries
  the 802.1Q tag.

## Cross-vendor mapping

Canonical fields covered:

```
CanonicalInterface:
  name, description, enabled, interface_type, mtu,
  ipv4_addresses, ipv6_addresses,
  switchport_mode, access_vlan, trunk_allowed_vlans,
  trunk_native_vlan, voice_vlan, lag_member_of,
  dhcp_client, vrf
```

Aruba -> OPNsense:

- `name`: **lossy** — Aruba `1` / `A1` / `Trk1` does not survive on
  OPNsense.  The port-rename mesh maps each source name to a zone
  label.  Canonical preserves the source string verbatim.
- `description`: **good** — Aruba `name "<x>"` ↔ OPNsense `<descr>`.
  Aruba truncates to 64 characters; OPNsense imposes no length
  limit.
- `enabled`: **good** — Aruba `enable` / `disable` ↔ OPNsense
  `<enable>` element presence.
- `interface_type`: **lossy** — Aruba infers from name shape (bare
  number → ethernetCsmacd, `Trk` → port-channel, `Vlan` → l3ipvlan).
  OPNsense does not surface a type field; cross-pair drops the hint.
- `mtu`: **lossy** — Aruba codec does not parse/render MTU
  (capability matrix gap); cross-pair render emits no `<mtu>`.
- `ipv4_addresses`: **good** — Aruba CIDR ↔ OPNsense
  `<ipaddr>`+`<subnet>` is a mechanical conversion.  Canonical takes
  one address per interface (matching both vendors' typical wire
  shape).
- `ipv6_addresses`: **good** — Aruba `ipv6 address X/N` ↔ OPNsense
  `<ipaddrv6>` + `<subnetv6>`.  `scope` discriminator preserved.
- `switchport_mode` / `access_vlan` / `trunk_allowed_vlans` /
  `trunk_native_vlan` / `voice_vlan`: **unsupported** on the
  OPNsense target — see `switchport_unsupported.md`.
- `lag_member_of`: **lossy** — Aruba `trunk 1-4 trk1 lacp` declares
  membership outside the per-port stanza; canonical back-points to
  `Trk1`.  OPNsense `<laggs>/<lagg>/<members>` lists members in a
  comma-separated string under a `lagg<N>` parent.  Both round-trip
  the back-pointer but the LAG name itself differs.
- `dhcp_client`: **lossy** — Aruba `ip address dhcp` is rare in
  campus deployments; canonical field would map to OPNsense
  `<ipaddr>dhcp</ipaddr>` but neither codec currently wires
  `dhcp_client` through.
- `vrf`: **unsupported** — Aruba has no VRF, OPNsense has no VRF;
  field always empty.

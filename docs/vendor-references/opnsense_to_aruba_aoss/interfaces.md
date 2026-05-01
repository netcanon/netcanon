# Interfaces: OPNsense versus Aruba AOS-S

## OPNsense

Source: [OPNsense Interfaces manual](https://docs.opnsense.org/manual/interfaces.html)
Retrieved: 2026-04-30

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
  </interfaces>
</opnsense>
```

OPNsense interface model:

- The XML tag is the operator-facing zone label (`<wan>`, `<lan>`,
  `<opt1>`, …).  The BSD device name lives in `<if>`.
- Every interface is L3 by definition (firewall has no switching).
- IPv4 uses `<ipaddr>` + `<subnet>` (CIDR length).
- MTU is an explicit `<mtu>` child.
- IPv6 uses `<ipaddrv6>` + `<subnetv6>`.
- Additional non-static IPv4 keywords (`dhcp`, `pppoe`) replace
  `<ipaddr>` for DHCP-client / PPP modes.
- VLAN sub-interfaces use the synthesised device name
  (`<if>em1_vlan10</if>`); the parent VLAN tag lives in `<vlans>`.

## Aruba AOS-S

Source: [Aruba AOS-S 16.10 IPv6 Configuration Guide / Basic
Operation Guide](https://www.arubanetworks.com/techdocs/AOS-S/16.10/IPv6/2930F-3810-5400/index.htm)
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
```

Aruba AOS-S notes:

- Physical port names are bare numerics or letter-uplinks
  (`A1`/`A2`).  LAGs are `Trk<N>`.
- L2 ports are the default; `routing` keyword promotes to L3.
- IPv4 supports CIDR or dotted-mask.

## Cross-vendor mapping

OPNsense -> Aruba:

- `interfaces[].name`: **lossy** — OPNsense zone labels (`<wan>`,
  `<lan>`, `<opt2>`) versus Aruba bare-numeric / letter-uplink ports.
  Port-rename mesh handles via the codec's `classify_port_name` /
  `format_port_identity` delegates.  The mapping is operator-driven
  (which OPNsense zone becomes which Aruba port).
- `interfaces[].description`: **good** — OPNsense `<descr>` (no
  length limit) ↔ Aruba `name "<x>"` (64-character limit).  Cross-
  pair may truncate when OPNsense description exceeds Aruba's
  limit.
- `interfaces[].enabled`: **good** — `<enable>1</enable>` /
  absence ↔ Aruba `enable` / `disable`.
- `interfaces[].interface_type`: **lossy** — OPNsense doesn't
  surface a type field; Aruba infers from name shape.  Cross-pair
  degrades the inference.
- `interfaces[].mtu`: **lossy** — OPNsense parses `<mtu>` (declared
  supported); Aruba codec does not parse / render MTU.  Field
  drops on the Aruba target.
- `interfaces[].ipv4_addresses`: **good** — OPNsense `<ipaddr>` +
  `<subnet>` ↔ Aruba CIDR.  Mechanical conversion.
- `interfaces[].ipv6_addresses`: **good** — same shape on both
  sides.
- `interfaces[].switchport_mode` / `access_vlan` /
  `trunk_allowed_vlans` / `trunk_native_vlan` / `voice_vlan`:
  **not_applicable** on this direction — OPNsense never populates
  switchport state on parse (no switching fabric).
- `interfaces[].lag_member_of`: **lossy** — OPNsense
  `<laggs>/<lagg>/<members>` membership maps to Aruba's `trunk
  <ports> trk<N> <mode>` declaration.  Both round-trip the back-
  pointer but the LAG name itself differs (`lagg0` ↔ `Trk1`).
- `interfaces[].dhcp_client`: **lossy** — OPNsense
  `<ipaddr>dhcp</ipaddr>` is common on the WAN zone; Aruba accepts
  `ip address dhcp` on a routed port but neither codec wires
  `dhcp_client` through the canonical surface.
- `interfaces[].vrf`: **not_applicable** — neither vendor models
  VRFs.

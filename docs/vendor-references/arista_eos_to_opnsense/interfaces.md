# Interfaces: Arista EOS versus OPNsense

## Arista EOS

Source: [Arista EOS User Manual — Ethernet Ports](https://www.arista.com/en/um-eos/eos-ethernet-ports)
and [Interface Configuration](https://www.arista.com/en/um-eos/eos-interface-configuration)
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
interface Ethernet3
   description "Trunk to downstream switch"
   switchport mode trunk
   switchport trunk native vlan 1
   switchport trunk allowed vlan 10,20,100,200
!
interface Loopback0
   description "VTEP / router-id"
   ip address 10.255.0.1/32
!
interface Port-Channel10
   description "Bonded uplink to core"
   no switchport
   ip address 10.0.1.1/31
!
interface Vlan100
   description "Tenant A data SVI"
   vrf TENANT_A
   ip address 10.100.0.1/24
```

Arista EOS naming notes:

- Physical: `Ethernet1`, `Ethernet48` (flat, no speed prefix);
  `Ethernet50/1` for QSFP breakout child lanes.
- Logical: `Loopback0`, `Vlan100` (SVI), `Port-Channel10` (LAG;
  capital-C `Port-Channel`, distinguishing from Cisco's
  `Port-channel`), `Management1`, `Vxlan1`.
- `no switchport` promotes a port to L3 (analogous to Aruba's
  `routing` keyword).
- Per-interface `vrf <name>` declares VRF membership; the canonical
  surface stores it on `CanonicalInterface.vrf`.

## OPNsense

Source: [OPNsense Interfaces manual](https://docs.opnsense.org/manual/interfaces.html)
Retrieved: 2026-04-30

OPNsense identifies interfaces in two layers: the BSD device name
(`em0`, `igb0`, `vtnet0`) lives in `<if>`, and the operator-facing
zone tag (`<wan>` / `<lan>` / `<optN>`) is the XML element name.

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
      <if>em1_vlan100</if>
      <descr>Tenant-A data</descr>
      <enable>1</enable>
      <ipaddr>10.100.0.1</ipaddr>
      <subnet>24</subnet>
    </opt2>
  </interfaces>
</opnsense>
```

Key shape differences from Arista:

- The XML tag IS the operator-facing name (no separate `<name>`
  child).
- `<enable>1</enable>` / absent replaces `no shutdown` /
  `shutdown`.
- IPv4 address + mask use `<ipaddr>` + `<subnet>` (CIDR length).
- MTU is an explicit `<mtu>` child (range 576-9000).
- No `no switchport` equivalent — every OPNsense interface is L3
  by definition (firewall is L3-only).
- VLAN sub-interfaces use the synthesised
  `<if>em1_vlan100</if>` device name; the parent `<vlan>`
  declaration in `<vlans>` carries the 802.1Q tag.

## Cross-vendor mapping (Arista -> OPNsense)

Canonical fields covered:

```
CanonicalInterface:
  name, description, enabled, interface_type, mtu,
  ipv4_addresses, ipv6_addresses,
  switchport_mode, access_vlan, trunk_allowed_vlans,
  trunk_native_vlan, voice_vlan, lag_member_of,
  dhcp_client, vrf
```

- `name`: **lossy** — Arista `Ethernet1` / `Loopback0` /
  `Port-Channel10` / `Vlan100` does not survive on OPNsense.
  Port-rename mesh maps each source name to a zone label.
- `description`: **good** — Arista `description` (240-char limit
  via underlying CLI) ↔ OPNsense `<descr>` (no length limit).
- `enabled`: **good** — Arista `no shutdown` / `shutdown` ↔
  OPNsense `<enable>` element presence.
- `interface_type`: **lossy** — Arista codec defaults to a `gig`
  speed-hint for unknown speeds (capability matrix declares this
  lossy); OPNsense doesn't surface a type field.
- `mtu`: **good** — Arista `mtu N` ↔ OPNsense `<mtu>N</mtu>`.
- `ipv4_addresses`: **good** — mechanical CIDR-to-`<ipaddr>` /
  `<subnet>` conversion.
- `ipv6_addresses`: **good** — Arista `ipv6 address X/N` (with
  optional `link-local`) ↔ OPNsense `<ipaddrv6>` + `<subnetv6>`.
  `scope` discriminator (global / link-local) preserved.
- `switchport_mode` / `access_vlan` / `trunk_allowed_vlans` /
  `trunk_native_vlan` / `voice_vlan`: **unsupported** — OPNsense
  has no switching fabric; see `switchport_unsupported.md`.
- `lag_member_of`: **lossy** — Arista `channel-group N mode active`
  back-points to `Port-Channel<N>`; OPNsense `<laggs>` carries
  member lists by NIC name under `<laggif>laggN</laggif>`.  Both
  round-trip the back-pointer but the LAG name itself differs;
  port-rename mesh canonicalises.
- `dhcp_client`: **lossy** — Arista `ip address dhcp` ↔ OPNsense
  `<ipaddr>dhcp</ipaddr>`; neither codec currently wires
  `dhcp_client` through.
- `vrf`: **unsupported** — OPNsense `config.xml` has no VRF model;
  see `vxlan_evpn_unsupported.md` and `vrf_unsupported.md` for
  rationale.

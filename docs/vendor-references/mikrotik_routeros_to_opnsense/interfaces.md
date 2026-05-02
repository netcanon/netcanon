# Interfaces (naming, IP, MTU, enabled): MikroTik RouterOS versus OPNsense

## MikroTik RouterOS

Sources:
- [Ethernet — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/41746442/Ethernet)
- [IP Routing — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/328084/IP+Routing)

Retrieved: 2026-04-30

```
/interface ethernet
set [ find default-name=ether1 ] comment="WAN uplink to ISP" disabled=no mtu=1500
set [ find default-name=ether2 ] comment="LAN trunk - bridge member" disabled=no mtu=1500

/ip address
add address=198.51.100.2/30 interface=ether1
add address=10.0.0.1/24 interface=bridge1

/ipv6 address
add address=2001:db8:0:1::2/64 interface=ether1
add address=fe80::1/64 interface=ether1 advertise=no
```

RouterOS uses a flat factory-default interface naming scheme:
``etherN`` (copper RJ45), ``sfp-sfpplus<N>`` (10G SFP+),
``wlan<N>`` (radio), ``cap<N>`` (CAPsMAN), etc.  Each port is
identified by its ``default-name=`` even after operator rename
(``set [ find default-name=ether2 ]`` is the canonical handle).
``comment=`` is the operator-friendly description.

IP addressing is decoupled from the interface stanza — ``/ip address
add address=A.B.C.D/N interface=etherN`` is its own section.  ``mtu=``
is per-interface; default is 1500.

## OPNsense

Source: [OPNsense Interfaces manual](https://docs.opnsense.org/manual/interfaces.html)

Retrieved: 2026-04-30

```xml
<interfaces>
  <wan>
    <enable>1</enable>
    <if>em0</if>
    <descr>WAN uplink to upstream carrier</descr>
    <mtu>1500</mtu>
    <ipaddr>198.51.100.2</ipaddr>
    <subnet>30</subnet>
  </wan>
  <lan>
    <enable>1</enable>
    <if>em1</if>
    <descr>Internal LAN segment</descr>
    <ipaddr>192.168.10.1</ipaddr>
    <subnet>24</subnet>
    <ipaddrv6>2001:db8:10::1</ipaddrv6>
    <subnetv6>64</subnetv6>
  </lan>
  <opt1>
    <enable>1</enable>
    <if>vlan0.20</if>
    <descr>Voice VLAN gateway</descr>
    <ipaddr>192.168.20.1</ipaddr>
    <subnet>24</subnet>
  </opt1>
</interfaces>
```

OPNsense identifies physical and virtual interfaces with TWO distinct
labels:

- The **zone tag** (``<wan>``, ``<lan>``, ``<opt1>``, …) is the
  operator-facing label and the key under ``<interfaces>``.  These
  zone tags are how OPNsense's firewall rules, DHCP server and
  other plumbing reference the interface.
- The **BSD device name** lives in ``<if>`` (``em0``, ``igb1``,
  ``vlan0.20``, ``lagg0``).  This is the FreeBSD kernel-level
  device.

IP addressing lives directly inside the zone element (``<ipaddr>`` +
``<subnet>``, ``<ipaddrv6>`` + ``<subnetv6>``).  ``<enable>`` is an
empty element (``<enable/>``) — present means enabled, absent means
disabled.

## Cross-vendor mapping

Canonical fields covered:

```
CanonicalInterface(name, default_name, description, enabled,
                   interface_type, mtu, ipv4_addresses[],
                   ipv6_addresses[], dhcp_client, lag_member_of, vrf)
```

### name / default_name

RouterOS ``etherN`` does not survive on OPNsense.  The operator-facing
label on OPNsense is the zone tag (``<wan>`` / ``<lan>`` / ``<optN>``);
the BSD device name lives in ``<if>``.  Port-rename mesh handles the
conversion via the codec's ``classify_port_name`` /
``format_port_identity`` delegates.  Canonical preserves the source
RouterOS string verbatim.

The ``default_name`` discriminator (RouterOS factory binding form
``set [ find default-name=etherN ]``) is meaningless to OPNsense and
drops on render.

### description

RouterOS ``comment="..."`` ↔ OPNsense ``<descr>...</descr>``.
Round-trips text content cleanly; OPNsense imposes no length limit.

### enabled

RouterOS ``disabled=no`` (default) ↔ OPNsense ``<enable/>`` element
(present = enabled).  RouterOS ``disabled=yes`` ↔ OPNsense omitted
``<enable/>`` element.  Round-trips cleanly.

### interface_type

RouterOS does not expose IANA ifType — the codec infers it from the
default-name prefix (``etherN`` → ``ethernetCsmacd``,
``vlan<N>`` → ``l3ipvlan``, etc.).  OPNsense doesn't surface an
ifType field in ``config.xml``; the cross-pair drops the type hint.
Documented as lossy in both codecs' capability matrices.

### mtu

RouterOS ``mtu=1500`` ↔ OPNsense ``<mtu>1500</mtu>``.  Both render
explicitly when set.  Default-MTU values (1500) round-trip but may
or may not appear in the stored config depending on codec policy.

### ipv4_addresses

RouterOS ``/ip address add address=A.B.C.D/N interface=etherN``
maps to OPNsense ``<ipaddr>A.B.C.D</ipaddr><subnet>N</subnet>``.
OPNsense splits the CIDR into address + prefix-length scalars
on the wire.  Multiple RouterOS addresses on the same interface
collapse to the primary on canonical (single CanonicalIPv4Address
per interface) — OPNsense's ``<ipaddr>`` is single-valued.

### ipv6_addresses

RouterOS ``/ipv6 address add address=2001:db8::1/64 interface=etherN``
↔ OPNsense ``<ipaddrv6>2001:db8::1</ipaddrv6><subnetv6>64</subnetv6>``.
``scope`` discriminator (global / link-local) preserved — RouterOS
addresses in ``fe80::/10`` are normalised to ``scope="link-local"``
on parse.  OPNsense's non-static IPv6 keywords (``dhcp6``,
``track6``, ``slaac``, ``6rd``, ``6to4``) are not generated by a
RouterOS source.

### dhcp_client

RouterOS ``/ip dhcp-client add interface=etherN`` ↔ OPNsense
``<ipaddr>dhcp</ipaddr>``.  Neither codec currently wires this into
``CanonicalInterface.dhcp_client``; cross-pair drops pending wire-up.

### lag_member_of

RouterOS ``/interface bonding add slaves=ether3,ether4 name=bond1``
back-points each member to ``bond1``.  OPNsense ``<laggs>/<lagg>/
<members>opt3,opt4</members>`` carries the back-pointer in a
comma-separated string under ``<members>``.  Both codecs round-trip
the back-pointer but the LAG name itself differs (``bond1`` ↔
``lagg0``); port-rename mesh canonicalises.

### vrf

RouterOS 7+ has ``/ip vrf`` but the MikroTik codec does not yet wire
up the parser; canonical interface ``vrf`` field is empty after a
RouterOS parse.  OPNsense has no VRF model in ``config.xml``.
Field structurally absent on this direction.

### Disposition

| Field | Disposition |
|---|---|
| `interfaces[].name` | lossy (rename mesh canonicalises) |
| `interfaces[].default_name` | lossy (RouterOS-only concept; drops) |
| `interfaces[].description` | good |
| `interfaces[].enabled` | good |
| `interfaces[].interface_type` | lossy (no OPNsense ifType field) |
| `interfaces[].mtu` | good |
| `interfaces[].ipv4_addresses` | good |
| `interfaces[].ipv6_addresses` | good |
| `interfaces[].dhcp_client` | lossy (neither codec wires it through) |
| `interfaces[].lag_member_of` | lossy (LAG-name rename) |
| `interfaces[].vrf` | not_applicable (RouterOS parser gap; OPNsense has no VRF) |

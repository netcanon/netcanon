# Interfaces (naming, IP, MTU, enabled): OPNsense versus MikroTik RouterOS

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
</interfaces>
```

OPNsense identifies physical and virtual interfaces with TWO labels:

- The **zone tag** (``<wan>``, ``<lan>``, ``<optN>``) — operator-
  facing label and key under ``<interfaces>``.
- The **BSD device name** in ``<if>`` (``em0``, ``igb1``,
  ``vlan0.20``, ``lagg0``).

IP addressing lives directly in the zone element.  ``<enable/>`` is
an empty element (presence = enabled).

## MikroTik RouterOS

Sources:
- [Ethernet — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/41746442/Ethernet)
- [IP Routing — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/328084/IP+Routing)

Retrieved: 2026-04-30

```
/interface ethernet
set [ find default-name=ether1 ] comment="WAN uplink" disabled=no mtu=1500
set [ find default-name=ether2 ] comment="LAN" disabled=no mtu=1500

/ip address
add address=198.51.100.2/30 interface=ether1
add address=192.168.10.1/24 interface=ether2

/ipv6 address
add address=2001:db8:10::1/64 interface=ether2
```

RouterOS uses a flat factory-default naming scheme (``etherN``,
``sfp-sfpplus<N>``, ``wlan<N>``, etc.).  Each port is identified by
its ``default-name=`` even after rename.  ``comment=`` is the
operator-friendly description.  IP addressing is a separate section
(``/ip address``).

## Cross-vendor mapping

Canonical fields covered:

```
CanonicalInterface(name, default_name, description, enabled,
                   interface_type, mtu, ipv4_addresses[],
                   ipv6_addresses[], dhcp_client, lag_member_of, vrf)
```

### name / default_name

OPNsense's zone label (``wan`` / ``lan`` / ``opt1``) doesn't match
any RouterOS interface form.  The BSD device name (``em0``) doesn't
either.  Port-rename mesh handles the conversion via the codec's
``classify_port_name`` / ``format_port_identity`` delegates.
Canonical preserves the source string verbatim.

The ``default_name`` discriminator is RouterOS-only and arrives
EMPTY from an OPNsense source — the RouterOS render falls back to
the rename-mesh-chosen name with no ``set [ find default-name=X ]``
lookup form.

### description

OPNsense ``<descr>`` (no length limit) ↔ RouterOS ``comment="..."``.
Round-trip preserves text content.

### enabled

OPNsense ``<enable/>`` element (present = enabled) ↔ RouterOS
``disabled=no``.  Round-trip cleanly.

### interface_type

OPNsense doesn't surface an ifType field — canonical ``interface_type``
hint is empty after an OPNsense parse.  RouterOS codec also lossy
on type (infers from default-name prefix).

### mtu

OPNsense ``<mtu>1500</mtu>`` ↔ RouterOS ``mtu=1500``.  Both render
explicitly when set.

### ipv4_addresses

OPNsense ``<ipaddr>192.168.10.1</ipaddr><subnet>24</subnet>`` ↔
RouterOS ``/ip address add address=192.168.10.1/24 interface=ether2``.
Conversion is mechanical.

### ipv6_addresses

OPNsense ``<ipaddrv6>`` + ``<subnetv6>`` ↔ RouterOS ``/ipv6 address
add address=X/N``.  ``scope`` discriminator (global / link-local)
preserved — OPNsense addresses in ``fe80::/10`` are normalised to
``scope="link-local"`` on parse.  OPNsense's non-static IPv6
keywords (``dhcp6`` / ``track6`` / ``slaac`` / ``6rd`` / ``6to4``)
are parse-and-ignored on the OPNsense side (no canonical record).

### dhcp_client

OPNsense ``<ipaddr>dhcp</ipaddr>`` ↔ RouterOS ``/ip dhcp-client add
interface=etherN``.  Neither codec currently wires this into
``CanonicalInterface.dhcp_client``; cross-pair drops pending wire-up.

### lag_member_of

OPNsense ``<laggs>/<lagg>/<members>opt3,opt4</members>`` parsing
back-links each member to its parent ``<laggif>`` name.  RouterOS
``/interface bonding name=bond1 slaves=ether3,ether4`` carries the
back-pointer in a different shape (``slaves=`` parameter on the
parent rather than ``<members>`` element).  Both codecs round-trip
the back-pointer; LAG name and member identities differ
(``lagg0`` ↔ ``bond1``); port-rename mesh canonicalises.

### vrf

OPNsense interfaces have no VRF-membership concept; the canonical
``vrf`` field is empty after an OPNsense parse.  RouterOS 7+ has
``/ip vrf`` but the MikroTik codec does not yet wire up the parser
either; field structurally absent.

### Disposition

| Field | Disposition |
|---|---|
| `interfaces[].name` | lossy (rename mesh canonicalises) |
| `interfaces[].default_name` | lossy (RouterOS-only concept; arrives empty) |
| `interfaces[].description` | good |
| `interfaces[].enabled` | good |
| `interfaces[].interface_type` | lossy (no OPNsense ifType field) |
| `interfaces[].mtu` | good |
| `interfaces[].ipv4_addresses` | good |
| `interfaces[].ipv6_addresses` | good |
| `interfaces[].dhcp_client` | lossy (neither codec wires it through) |
| `interfaces[].lag_member_of` | lossy (LAG-name rename) |
| `interfaces[].vrf` | not_applicable (OPNsense never populates) |

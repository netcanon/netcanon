# Interfaces (zone labels, BSD device names, IPv4/IPv6, MTU): OPNsense versus Cisco IOS-XE

## OPNsense

Source: [OPNsense Interfaces manual](https://docs.opnsense.org/manual/interfaces.html)
Retrieved: 2026-04-30

OPNsense models interfaces as zone-keyed elements:

```xml
<opnsense>
  <interfaces>
    <wan>
      <if>em0</if>
      <descr>Upstream</descr>
      <enable/>
      <ipaddr>198.51.100.2</ipaddr>
      <subnet>30</subnet>
      <mtu>1500</mtu>
      <ipaddrv6>2001:db8::2</ipaddrv6>
      <subnetv6>64</subnetv6>
    </wan>
    <lan>
      <if>em1</if>
      <descr>Internal</descr>
      <enable/>
      <ipaddr>10.10.10.1</ipaddr>
      <subnet>24</subnet>
    </lan>
  </interfaces>
</opnsense>
```

- The CHILD TAG (``<wan>``, ``<lan>``, ``<optN>``) is the
  operator-facing zone label.  ``<if>`` carries the BSD device
  name (``em0``, ``igb0``, ``ix0``).
- ``<enable/>`` is an empty boolean tag.
- IPv4 lives in ``<ipaddr>`` + ``<subnet>`` (CIDR prefix length).
- IPv6 lives in ``<ipaddrv6>`` + ``<subnetv6>``; non-static keywords
  (``dhcp6``, ``track6``, ``slaac``) are not static records and
  parse-and-ignore.
- ``<mtu>`` is a simple integer.

The OPNsense codec emits ``CanonicalInterface`` with ``name`` set to
the zone label (``"wan"``, ``"lan"``, ``"opt1"``).  Switchport state
is never populated (OPNsense isn't a switch).  ``vrf`` is never
populated (OPNsense has no VRF model).  ``lag_member_of`` is
back-linked from ``<laggs>/<lagg>/<members>`` parsing.

## Cisco IOS-XE

Source: [Cisco IOS Interface and Hardware Component Command Reference](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/interface/command/ir-cr-book/ir-s7.html)
Retrieved: 2026-04-30

Cisco encodes speed and slot/sub-slot/port:

```
interface GigabitEthernet0/0/0
 description Upstream
 ip address 198.51.100.2 255.255.255.252
 mtu 1500
 ipv6 address 2001:DB8::2/64
 no shutdown
!
```

Each interface is its own stanza, terminated by ``!``.  IP addresses
use dotted-mask form on Cisco for IPv4 (``255.255.255.0`` rather than
``/24``); IPv6 uses CIDR.

## Cross-vendor mapping

Canonical fields (see ``CanonicalInterface``):

```
name, description, enabled, interface_type, mtu,
ipv4_addresses, ipv6_addresses,
switchport_mode, access_vlan, trunk_allowed_vlans, trunk_native_vlan,
voice_vlan, lag_member_of, dhcp_client, vrf
```

OPNsense -> Cisco:

- ``name``: **lossy** — OPNsense's zone label (``wan`` / ``lan`` /
  ``opt1``) doesn't match any Cisco interface form
  (``GigabitEthernetX/Y/Z`` / ``Loopback<N>`` / ``Vlan<N>``).  The
  port-rename mesh handles the conversion.  Note: the BSD device
  name (``em0``) is also non-Cisco; either label is opaque from the
  Cisco renderer's perspective.
- ``description``: **good** — both vendors round-trip free-form
  descriptions; OPNsense imposes no length limit so descriptions
  longer than 240 chars are truncated on Cisco render.
- ``enabled``: **good** — OPNsense empty ``<enable/>`` element ↔
  Cisco ``no shutdown``.
- ``interface_type``: **lossy** — OPNsense doesn't surface a type
  field; Cisco infers from name prefix on parse.  The cross-pair
  drops the type hint.
- ``mtu``: **good** — both render explicitly when set.
- ``ipv4_addresses``: **good** — CIDR prefix length ↔ dotted-mask
  conversion is mechanical.
- ``ipv6_addresses``: **good** for static addresses with the
  ``scope`` discriminator preserved.  ``dhcp6`` / ``track6`` /
  ``slaac`` keywords on the OPNsense source drop on parse (no
  canonical record).
- ``switchport_mode`` / ``access_vlan`` / ``trunk_allowed_vlans`` /
  ``trunk_native_vlan`` / ``voice_vlan``: **not_applicable** —
  OPNsense never populates these fields on parse (no switching
  fabric).  The Cisco target render emits routed-port stanzas
  (no ``switchport`` lines).
- ``lag_member_of``: **lossy** — OPNsense parses ``<laggs>`` and
  back-links members, but the Cisco renderer's ``Port-channel``
  membership emits via ``channel-group N mode active`` on the member
  side.  Member name translation runs through port-rename mesh.
- ``dhcp_client``: **lossy** — OPNsense's ``<ipaddr>dhcp</ipaddr>``
  shape is not currently wired into ``CanonicalInterface.dhcp_client``.
- ``vrf``: **not_applicable** — OPNsense has no VRF model; the
  field is always empty on OPNsense-source intent.

OPNsense's ``<spoofmac>`` (MAC override) and ``<media>`` (link-speed
hint) elements are not modelled in the canonical schema.

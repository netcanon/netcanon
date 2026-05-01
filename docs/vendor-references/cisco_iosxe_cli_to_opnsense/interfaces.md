# Interfaces (naming, IP addressing, MTU, enable/descr): Cisco IOS-XE versus OPNsense

## Cisco IOS-XE

Source: [Cisco IOS Interface and Hardware Component Command Reference (IOS XE Gibraltar 16.10.1)](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/interface/command/ir-cr-book/ir-s7.html)
Retrieved: 2026-04-30

Cisco encodes speed and slot/sub-slot/port in the interface name:

```
interface GigabitEthernet0/0/0
 description WAN uplink
 ip address 198.51.100.1 255.255.255.252
 mtu 1500
 no shutdown
!
interface Loopback0
 description Router-ID
 ip address 10.255.0.1 255.255.255.255
!
interface Vlan10
 description Users
 ip address 10.10.10.1 255.255.255.0
!
```

Each interface gets its own stanza terminated by ``!``.  IP addresses
use the dotted-mask form (``255.255.255.0`` rather than ``/24``).
Cisco supports multiple ``ip address`` lines per interface (primary
plus ``secondary``); the canonical model takes only the primary.
``shutdown`` / ``no shutdown`` toggles administrative state.

## OPNsense

Source: [OPNsense Interfaces manual](https://docs.opnsense.org/manual/interfaces.html)
Retrieved: 2026-04-30
Source: [OPNsense Devices (VLAN tab) manual](https://docs.opnsense.org/manual/other-interfaces.html)
Retrieved: 2026-04-30

OPNsense models interfaces as zone-keyed elements inside
``<interfaces>``:

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
    </wan>
    <lan>
      <if>em1</if>
      <descr>Internal</descr>
      <enable/>
      <ipaddr>10.10.10.1</ipaddr>
      <subnet>24</subnet>
    </lan>
    <opt1>
      <if>em2</if>
      <descr>DMZ</descr>
      <enable/>
      <ipaddr>192.0.2.1</ipaddr>
      <subnet>24</subnet>
      <ipaddrv6>2001:db8::1</ipaddrv6>
      <subnetv6>64</subnetv6>
    </opt1>
  </interfaces>
</opnsense>
```

Key shape differences from Cisco:

- The CHILD TAG (``<wan>``, ``<lan>``, ``<optN>``) is the operator-
  facing zone label.  The ``<if>`` element carries the BSD device
  name (``em0``, ``igb0``, ``ix0``, ``vlan0.10``) — the actual NIC.
- ``<descr>`` is free-form, no length constraint.
- ``<enable/>`` is an empty boolean tag; absent means disabled.
  No "shutdown" word.
- IPv4 lives in ``<ipaddr>`` plus ``<subnet>`` (CIDR prefix length,
  not dotted mask).
- IPv6 lives in ``<ipaddrv6>`` plus ``<subnetv6>``.  The
  ``<ipaddrv6>`` element can also carry keywords ``dhcp6``, ``track6``,
  ``slaac``, ``6rd``, ``6to4`` for non-static configurations — these
  are NOT a static address record and do not fit the canonical
  ``CanonicalIPv6Address`` shape.  The OPNsense codec parse-and-
  ignores those.
- MTU is a simple ``<mtu>`` integer (when explicitly set).
- Loopbacks: OPNsense has ``lo0`` as the system loopback but does
  not surface secondary loopbacks inside ``<interfaces>`` — they live
  in ``<virtualip>`` if needed.
- SVIs in the Cisco sense (``interface Vlan10`` with an L3 address)
  do not exist on OPNsense.  VLAN sub-interfaces are physical-parent
  trunked devices that get assigned to a zone; the L3 address sits
  on the assigned zone (e.g. ``opt1`` whose ``<if>`` is
  ``em1_vlan10``).

## Cross-vendor mapping

Canonical fields covered (see ``CanonicalInterface``):

```
name, description, enabled, interface_type, mtu,
ipv4_addresses, ipv6_addresses,
switchport_mode, access_vlan, trunk_allowed_vlans, trunk_native_vlan,
voice_vlan, lag_member_of, dhcp_client, vrf
```

Disposition by sub-field:

- ``name``: **lossy** — Cisco ``GigabitEthernet0/0/0`` cannot be
  rendered as-is on OPNsense (the operator-facing label is
  ``wan`` / ``lan`` / ``opt<N>``; the BSD device name slot is for
  FreeBSD driver names).  The port-rename mesh handles this; canonical
  carries whatever the source emitted.
- ``description``: **good** — both vendors round-trip free-form
  descriptions.  Cisco truncates at 240 chars; OPNsense imposes no
  length limit.
- ``enabled``: **good** — Cisco ``no shutdown`` ↔ OPNsense empty
  ``<enable/>`` element.
- ``interface_type``: **lossy** — Cisco infers from name prefix; the
  OPNsense codec doesn't surface a type field.
- ``mtu``: **good** — both render explicitly when set.
- ``ipv4_addresses``: **good** — dotted-mask ↔ CIDR conversion is
  mechanical; both codecs handle.  Multiple IPv4 addresses per Cisco
  interface degrade to the primary only (canonical takes one).
- ``ipv6_addresses``: **good** for static addresses;
  ``dhcp6``/``track6``/``slaac`` keywords on OPNsense are dropped on
  parse (no canonical shape).
- ``switchport_mode`` / ``access_vlan`` / ``trunk_allowed_vlans`` /
  ``trunk_native_vlan`` / ``voice_vlan``: **unsupported** — OPNsense
  is a router/firewall, not a switch.  No native ``switchport``
  concept; the cross-pair drops switchport state.  See
  ``switchport_unsupported.md`` for the full discussion.
- ``lag_member_of``: **lossy** — OPNsense has ``<laggs>/<lagg>``
  blocks, but the Cisco codec emits Port-channel members on the
  member interface side via ``channel-group N mode active``.  Both
  parse but the cross-pair render of LAGs is incomplete.
- ``dhcp_client``: **lossy** — Cisco ``ip address dhcp`` ↔ OPNsense
  ``<ipaddr>dhcp</ipaddr>`` — neither codec wires this through to
  canonical today.
- ``vrf``: **unsupported** — Cisco IOS-XE codec parse-and-ignores VRF
  declarations (per its capability matrix); OPNsense has no
  canonical-portable VRF model in v1.

The fundamental router/switch versus router/firewall mismatch means
many Cisco-side fields are simply not modelled on OPNsense.  See
``switchport_unsupported.md`` and ``vrf_unsupported.md`` for the
full disposition rationale.

# Switchport modes / spanning-tree / VTP: Cisco IOS-XE versus OPNsense

## Cisco IOS-XE

Source: [Cisco IOS XE Layer 2 Configuration Guide — Configuring VLANs (Catalyst 9400)](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9400/software/release/17-14/configuration_guide/vlan/b_1714_vlan_9400_cg/configuring_vlans.html)

Cisco IOS-XE on a Catalyst-class platform models per-port switchport
state extensively:

```
interface GigabitEthernet1/0/10
 description Office workstation
 switchport mode access
 switchport access vlan 10
 switchport voice vlan 100
 spanning-tree portfast
!
interface GigabitEthernet1/0/24
 description Trunk to dist-sw
 switchport trunk encapsulation dot1q
 switchport mode trunk
 switchport trunk native vlan 99
 switchport trunk allowed vlan 10,20,30,100
!
spanning-tree mode rapid-pvst
spanning-tree extend system-id
vtp mode transparent
vtp domain corp
```

Switchport directives on the interface, plus global ``spanning-tree``
and ``vtp`` configuration.  Each is a switching-fabric construct.

## OPNsense

Source: [OPNsense Interface Configuration manual](https://docs.opnsense.org/manual/interfaces.html)
Retrieved: 2026-04-30

OPNsense is a FreeBSD-based router/firewall.  It has no switching
fabric, no spanning-tree process for switching frames, and no VTP /
GVRP equivalent.  An OPNsense device does carry tagged 802.1Q frames
on its physical NICs (via the ``<vlans>`` block — see ``vlans.md``),
but each ``<vlan>`` element rides on a single physical parent NIC.
There is no concept of:

- ``switchport mode`` (access / trunk) — OPNsense interfaces are
  always L3 (or bridge members; bridges are a separate ``<bridges>``
  block with very different semantics from a Cisco trunk).
- ``switchport voice vlan`` — no LLDP-MED voice-VLAN signalling in
  the base OS.
- ``switchport trunk allowed vlan <list>`` — every ``<vlan>`` whose
  ``<if>`` matches a parent rides that parent; the "allowed" surface
  is implicit, not a per-port allow-list.
- ``spanning-tree`` — OPNsense bridges support STP/RSTP via
  ``ifconfig bridge0 stp`` but it's bridge-scoped, not interface-
  scoped, and not modelled in the canonical schema.
- ``vtp`` — no equivalent.

## Cross-vendor mapping

Canonical interface fields impacted:

- ``CanonicalInterface.switchport_mode``: **unsupported** on OPNsense
  target.  Render path emits no switchport XML; the canonical value
  is preserved on the source side and surfaces in the validation
  report.
- ``CanonicalInterface.access_vlan``: **unsupported** — see above.
- ``CanonicalInterface.trunk_allowed_vlans``: **unsupported**.
- ``CanonicalInterface.trunk_native_vlan``: **unsupported**.
- ``CanonicalInterface.voice_vlan``: **unsupported**.

Spanning-tree / VTP / DTP / 802.1ad-on-switching are out of canonical
scope on both vendors; never rendered.

Disposition: **unsupported** for the entire switchport-mode surface.
The Cisco-source / OPNsense-target migration is fundamentally a
router/firewall-only translation; the source's switching topology
must be reconstructed manually on OPNsense (typically by replacing
the L2 fabric with a separate switch and pointing OPNsense at it as
a router).

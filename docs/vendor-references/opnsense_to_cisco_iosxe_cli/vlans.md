# VLAN configuration: OPNsense versus Cisco IOS-XE

## OPNsense

Source: [OPNsense Devices manual — VLAN tab](https://docs.opnsense.org/manual/other-interfaces.html)
Retrieved: 2026-04-30

OPNsense VLANs live in the top-level ``<vlans>`` element:

```xml
<opnsense>
  <vlans>
    <vlan>
      <if>em1</if>
      <tag>10</tag>
      <pcp>0</pcp>
      <descr>Users</descr>
      <vlanif>em1_vlan10</vlanif>
    </vlan>
  </vlans>
</opnsense>
```

Each ``<vlan>`` carries:

- ``<if>`` — parent physical (or aggregated) device the tag rides on
- ``<tag>`` — 802.1Q VLAN ID (1-4094)
- ``<pcp>`` — priority code point
- ``<descr>`` — free-form description
- ``<vlanif>`` — synthesised device name used by zone assignment

OPNsense has NO concept of a VLAN-centric port-membership list.  A
VLAN is a tagged sub-interface on ONE parent NIC; trunking is
implicit (every ``<vlan>`` whose ``<if>`` matches a parent rides
that parent).  No SVI / interface-Vlan equivalent — the L3 face of
the tag is the ZONE that owns the ``<vlanif>`` device.

The OPNsense codec parses ``<vlan>/<tag>`` into ``CanonicalVlan.id``
and ``<vlan>/<descr>`` into ``CanonicalVlan.name`` (per ``parse.py``).

## Cisco IOS-XE

Source: [Cisco IOS XE 17.14 VLAN Configuration Guide](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9400/software/release/17-14/configuration_guide/vlan/b_1714_vlan_9400_cg/configuring_vlans.html)
Retrieved: 2026-04-30

```
vlan 10
 name Users
!
interface Vlan10
 description Users
 ip address 10.10.10.1 255.255.255.0
!
interface GigabitEthernet1/0/24
 switchport mode trunk
 switchport trunk allowed vlan 10,20,30
!
```

Cisco models VLANs with explicit per-port membership (via
``switchport`` directives on each interface) and explicit SVIs
(``interface Vlan<N>``).

## Cross-vendor mapping

Canonical fields (see ``CanonicalVlan``):

```
id, name, description,
tagged_ports: list[str],
untagged_ports: list[str],
ipv4_addresses: list[CanonicalIPv4Address],
```

OPNsense -> Cisco:

- ``id``: **good** — OPNsense ``<tag>`` ↔ Cisco ``vlan N``.
- ``name``: **lossy** — OPNsense's ``<descr>`` lands in the
  canonical ``name`` field via ``parse.py``; Cisco's separate
  ``name`` and ``description`` distinction is collapsed.  Round-trip
  to Cisco emits the description into the ``name`` line.
- ``description``: **lossy** — same source field as ``name``;
  OPNsense doesn't model a separate description.
- ``tagged_ports`` / ``untagged_ports``: **not_applicable** —
  OPNsense never populates these lists on parse (no VLAN-centric
  port-membership concept).  The Cisco renderer can emit
  ``switchport trunk allowed vlan`` / ``switchport access vlan``
  stanzas but only when the canonical lists carry data, which they
  don't from an OPNsense source.
- ``ipv4_addresses`` (SVI): **lossy** — OPNsense's L3 face of a tag
  is the zone (``<opt2>``) that owns the ``<vlanif>``; the canonical
  ``CanonicalVlan.ipv4_addresses`` list is not populated by the
  OPNsense parser today.  Cisco render therefore emits no
  ``interface Vlan<N>`` stanza on the cross-pair.

Disposition: ``id`` round-trips cleanly; ``name`` / ``description``
collapse; port-membership and SVI sub-fields are
``not_applicable`` from an OPNsense source.

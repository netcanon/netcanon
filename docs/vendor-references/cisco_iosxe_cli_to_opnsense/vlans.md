# VLAN configuration: Cisco IOS-XE versus OPNsense

## Cisco IOS-XE

Source: [Cisco IOS XE 17.14 VLAN Configuration Guide — Configuring VLANs (Catalyst 9400)](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9400/software/release/17-14/configuration_guide/vlan/b_1714_vlan_9400_cg/configuring_vlans.html)
Retrieved: 2026-04-30

VLAN definition syntax (global config):

```
Switch(config)# vlan 100
Switch(config-vlan)# name engineering
Switch(config-vlan)# state active
Switch(config-vlan)# exit
```

VLAN ID range 1-4094 (1 reserved as default; 1002-1005 historically
reserved for Token Ring / FDDI on legacy IOS).  Names truncated to 32
characters.

Per-port VLAN membership lives on the interface side via
``switchport access vlan N`` / ``switchport trunk allowed vlan N,M``.
SVIs (the L3 face of a VLAN) live as ``interface Vlan100`` stanzas.

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
    <vlan>
      <if>em1</if>
      <tag>20</tag>
      <pcp>0</pcp>
      <descr>Servers</descr>
      <vlanif>em1_vlan20</vlanif>
    </vlan>
  </vlans>
</opnsense>
```

The OPNsense docs describe each entry as carrying:

- ``<if>`` — parent physical (or aggregated) device the tag rides on
- ``<tag>`` — 802.1Q VLAN ID (1-4094)
- ``<pcp>`` — 802.1Q priority code point (defaults to 0)
- ``<descr>`` — free-form description
- ``<vlanif>`` — the synthesised device name (e.g. ``em1_vlan10``)
  used by zone-assigned interfaces (``<wan>`` / ``<lan>`` /
  ``<optN>``) when they reference this VLAN sub-interface

Crucially: OPNsense has NO concept of "VLAN-centric port-membership
list" the way a Cisco switch does.  A VLAN exists only as a tagged
sub-interface on ONE parent NIC (the ``<if>`` element).  There is no
trunk port that selects "vlan members 10,20,30 tagged" — the trunk is
always the physical parent NIC and every ``<vlan>`` element with a
matching ``<if>`` rides it.  Untagged traffic is the parent NIC's
native frames.

QinQ (802.1ad) is supported by stacking ``<vlan>`` over a
``<vlan>``-suffixed parent ``<if>``.

## Cross-vendor mapping

Canonical fields covered (see ``CanonicalVlan``):

```
id, name, description,
tagged_ports: list[str],
untagged_ports: list[str],
ipv4_addresses: list[CanonicalIPv4Address],   # SVI L3 config
```

The Cisco -> OPNsense direction maps:

- ``CanonicalVlan.id``: **good** — Cisco ``vlan N`` ↔ OPNsense ``<tag>N</tag>``.
- ``CanonicalVlan.name``: **lossy** — the name does not come back.
  An OPNsense ``<vlan>`` has no name of its own: the render writes
  each VLAN as a ``<vlan>`` device, under the name of the source's
  VLAN interface where there is one (``Vlan111``), otherwise as
  ``<parent>_vlan<id>`` on a port that carries the VLAN or a default
  one (``Port-channel1_vlan10``), and writes the Cisco ``name`` as
  the device's ``<descr>``.  The OPNsense parser names a VLAN after
  its device (``<vlanif>``) and reads ``<descr>`` as its description,
  so a VLAN comes back named after its device, with its IOS name as
  its description.  A device name OPNsense's VLAN form would refuse
  (``Vlan111``) gets a ``<!-- review: -->`` comment beside it.
- ``CanonicalVlan.description``: **lossy** — IOS states no VLAN
  description; the round trip gives each named VLAN one, its name
  (see above).  Drift by gaining the name, never by losing a value.
- ``CanonicalVlan.tagged_ports`` / ``untagged_ports``: **unsupported**
  — OPNsense has no VLAN-centric port-membership model.  A trunk
  port carries "every vlan whose ``<if>`` matches this NIC"; there is
  no per-VLAN list of allowed ports.  Cross-vendor render emits no
  port-membership XML; operators must re-create the trunk topology by
  assigning each ``<vlan>`` element to a zone.
- ``CanonicalVlan.ipv4_addresses`` (SVI): **lossy** — Cisco's
  ``interface Vlan100 / ip address X Y`` is the L3 face of the VLAN.
  OPNsense doesn't have first-class SVIs; the equivalent is to assign
  the VLAN sub-interface (``em1_vlan100``) to an OPNsense zone
  (``<opt2>``) and put the address on that zone.  The render writes
  the SVI as a zone whose ``<if>`` is the VLAN device written under
  the SVI's name (``Vlan10``), with the address on the zone; read
  back, the address is on that interface record, not on the VLAN.

Disposition (see YAML for granular per-sub-field):

- ``vlans[].id``: **good**.
- ``vlans[].name`` / ``description``: **lossy** (a VLAN comes back
  named after its OPNsense device, its IOS name as its description).
- ``vlans[].tagged_ports`` / ``untagged_ports``: **unsupported**
  (router/firewall has no VLAN-centric port lists).
- ``vlans[].ipv4_addresses`` (SVI): **lossy** — the address is
  written on the SVI's zone and comes back on that interface, not on
  the VLAN.

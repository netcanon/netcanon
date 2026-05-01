"""
Juniper Junos codec — 7th shipped vendor, first hierarchical-config
grammar family in the portfolio.

Scope
-----
Bidirectional codec.  Accepts Junos ``set``-form configuration text
— the flat command-style output of ``show configuration | display
set`` — as the canonical paste form.  Block-form (``{ ... ; }``
hierarchical) input is auto-detected and converted to set-form
ahead of the normal parser, so operators with block-form exports
can paste either grammar.

Direction: ``bidirectional``.  Render emits set-form Junos that
round-trips through the parser; apply-groups statements + group
content are preserved end-to-end (GAP 9b) so the rendered output
matches the operator-paste shape rather than dumping every
inherited statement inline.

Supported grammar (Tier 1 + Tier 2):
    * ``set system host-name <name>`` /
      ``set system domain-name <domain>`` /
      ``set system name-server <ip>`` /
      ``set system ntp server <ip>`` /
      ``set system syslog host <ip> any any``
    * ``set system login user <name> class <class>``
    * ``set system login user <name> authentication encrypted-password "<hash>"``
    * ``set interfaces <iface> description "<desc>"`` /
      ``set interfaces <iface> mtu <N>`` /
      ``set interfaces <iface> disable``
    * ``set interfaces <iface> unit <N> family inet|inet6 address <ip>/<prefix>``
    * ``set interfaces <iface> unit <N> vlan-id <tag>`` (per-unit 802.1Q)
    * ``set interfaces interface-range <name> ...`` (members + shared attrs;
      structural collapse on parse + auto-synthesis on render)
    * ``set vlans <name> vlan-id <N>`` /
      ``set vlans <name> vxlan vni <VNI>``
    * ``set switch-options vtep-source-interface <iface>`` /
      ``set switch-options vxlan-port <N>`` (VXLAN switch-level globals)
    * ``set routing-instances <name> instance-type <t>`` /
      ``... route-distinguisher <rd>`` /
      ``... vrf-target [import|export] target:<rt>`` /
      ``... interface <iface>`` /
      ``... protocols evpn ip-prefix-routes vni <N>`` (EVPN Type-5 L3 VNI)
    * ``set routing-options static route <dest> next-hop <gw>``
    * ``set snmp community <name> authorization read-only|read-write``
    * ``set snmp location "<loc>"`` / ``set snmp contact "<contact>"``
    * ``set snmp trap-group <g> targets <ip>``
    * ``set snmp v3 usm local-engine user <n> authentication-<proto>
       authentication-key "<key>"`` /
      ``... privacy-<proto> privacy-key "<key>"`` /
      ``set snmp v3 vacm security-to-group security-model usm
       security-name <n> group <g>`` (SNMPv3 USM + VACM)
    * ``set groups <g> ...`` / ``set apply-groups <g>`` (two-pass
      inheritance + round-trip preservation)

Tier-3 parse-and-ignore:
    * ``set protocols bgp ...`` / ``set protocols isis ...`` /
      ``set protocols ospf ...`` / ``set protocols mpls ...``
    * ``set firewall ...`` / ``set policy-options ...`` /
      ``set security ...`` / ``set forwarding-options ...`` /
      ``set chassis ...`` / ``set services ...``

Module layout:
    * codec.py — ``JunosCodec`` class (metadata, delegation,
                 probe, port-name bridges, iter_xpaths)
    * parse.py — set-form + block-form parser; two-pass groups-
                 then-top-level dispatch + per-stanza appliers
    * render.py — canonical tree → Junos ``set``-form text
    * port_names.py — cross-vendor port-name bridge

Strategic value:
    Junos is the dominant service-provider OS (~25% SP market share
    per Omdia 2024) and widely used in mixed-vendor enterprise
    fabrics.  Bidirectional support unlocks **cross-vendor
    migration BOTH WAYS** between Junos and the Cisco / Arista /
    Aruba / OPNsense / FortiGate / MikroTik portfolio.
"""

from .codec import JunosCodec

__all__ = ["JunosCodec"]

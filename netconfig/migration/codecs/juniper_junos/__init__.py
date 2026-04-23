"""
Juniper Junos codec — 7th shipped vendor, first hierarchical-config
grammar family in the portfolio.

Scope (v1)
----------
Parse-only.  Accepts Junos ``set``-form configuration text — the
flat command-style output of ``show configuration | display set``.
Block-form (``{ ... ; }`` hierarchical) is **not** parsed in v1;
operators with block-form exports can run ``| display set`` on the
device to produce compatible input, or wait for a follow-up commit
that adds block-form parsing.

Direction: ``parse_only`` — render() raises NotImplementedError.
Rendering Junos requires careful handling of hierarchical
inheritance, apply-groups, and commit semantics that warrant a
dedicated follow-up commit rather than cramming into v1.

Supported grammar (Tier 1 + Tier 2):
    * ``set system host-name <name>``
    * ``set system login user <name> class <class>``
    * ``set system login user <name> authentication encrypted-password "<hash>"``
    * ``set interfaces <iface> unit <N> description "<desc>"``
    * ``set interfaces <iface> unit <N> family inet address <ip>/<prefix>``
    * ``set interfaces <iface> disable``
    * ``set vlans <name> vlan-id <N>``
    * ``set routing-options static route <dest> next-hop <gw>``
    * ``set snmp community <name> authorization read-only|read-write``
    * ``set snmp location "<loc>"`` / ``set snmp contact "<contact>"``

Tier-3 parse-and-ignore:
    * ``set protocols bgp ...`` / ``set protocols isis ...`` /
      ``set protocols ospf ...`` / ``set protocols mpls ...``
    * ``set routing-instances ...``
    * ``set groups ...`` / ``apply-groups``
    * ``set firewall ...``
    * ``set policy-options ...``

Module layout:
    * codec.py — parse / probe / capability matrix
    * port_names.py — cross-vendor port-name bridge

Strategic value:
    Junos is the dominant service-provider OS (~25% SP market share
    per Omdia 2024) and widely used in mixed-vendor enterprise
    fabrics.  Adding Junos parse-only unlocks **cross-vendor
    migration FROM Junos** (e.g. Juniper-core → Cisco/Arista
    replacement in a data-center refresh) — the direction of
    customer demand.  Render direction (migrate TO Junos) is
    rarer and correctly deferred to v2.
"""

from .codec import JunosCodec

__all__ = ["JunosCodec"]

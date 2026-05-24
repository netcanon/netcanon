"""
Aruba AOS-S codec — 4th real vendor, Session C of the
vendor-config-research plan.

Scope
-----
Parses / renders ``show running-config`` from the ArubaOS-Switch
family (2530 / 2540 / 2930 running 16.x firmware, formerly ProCurve).
This is NOT the same as AOS-CX (the newer switching OS running on
CX 6200/6300/8320 hardware).

Architecturally interesting because AOS-S is **natively VLAN-centric**
— VLAN port membership is declared *inside* the ``vlan`` stanza
(``untagged 1-24`` / ``tagged 25-26``), not per-interface like Cisco.
This is the model the :class:`CanonicalVlan` tagged_ports /
untagged_ports design was built around, so Aruba is the first codec
where those fields round-trip without a transpose.

Supported / lossy / unsupported xpaths: see ``_CAPS`` on
:class:`.codec.ArubaAOSSCodec`.  Tier 1 coverage spans hostname,
VLAN-centric stanzas (id / name / ``untagged`` + ``tagged`` port
lists / SVI), interfaces, static routes, SNMP community + SNMPv3
users + groups, NTP, local users, RADIUS, LAG trunks.

Structural quirks handled:
    * ``;`` is the comment character (not ``!``)
    * Stanza delimiter is ``exit`` at the outdented position, or the
      next unindented line
    * Port names are bare: ``1``, ``1/1``, ``A1``, ``Trk1``
    * ``routing`` on an interface enables L3 (replaces ``no switchport``)
    * IP addresses support BOTH ``A.B.C.D M.M.M.M`` and ``A.B.C.D/N``
    * VLAN port lists: ``untagged 1-24``, ``untagged 1,3,5``,
      ``tagged 25-26,A1``

Out of scope (declared unsupported in matrix):
    * STP per-port (``spanning-tree 1-24 priority 4``)
    * 802.1X, MAC auth (RADIUS-bind/AAA policy)
    * ACLs (``access-list``)

Module layout (post-split per the codecs/README.md split-codec
convention):
    * ``codec.py``           — ``ArubaAOSSCodec`` class (metadata,
                               delegation, probe, port-name bridges)
    * ``parse.py``           — line-walker + per-stanza parsers
                               (``_parse_vlan_stanza`` /
                               ``_parse_interface_stanza``)
    * ``render.py``          — canonical tree → AOS-S CLI text
    * ``port_names.py``      — cross-vendor port-name identity bridge
    * ``_svi_absorption.py`` — SVI-into-VLAN absorption flag (single
                               source of truth for ``absorbs_svi_into_vlan``)

Certainty: ``best_effort`` — validated against synthetic fixtures
modelled on Aruba docs + community configs.
"""

from .codec import ArubaAOSSCodec

__all__ = ["ArubaAOSSCodec"]

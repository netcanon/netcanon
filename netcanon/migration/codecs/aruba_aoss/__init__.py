"""
Aruba AOS-S codec — 4th shipped codec; campus L2/L3 switching.

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
    * A stanza ends where the switch ends a context: at its ``exit``
      or an ``end`` (in any letter case), or at a line in column 0
      that enters another context or that the top of the config
      reads.  A line that has only lost its indentation is still the
      stanza's, so a config pasted without it is read as the one it
      was.  ``oobm`` is a stanza whose lines are the management
      port's, and none of them is read; its own words never end it
    * A port's VLANs stated from the port's side (``tagged vlan
      <list>`` / ``untagged vlan <id>`` in an ``interface`` stanza, or
      ``interface <ports> tagged vlan <list>`` on one line) are read
      as the VLAN's own lines of the same meaning, the later line
      winning; the renderer writes them under ``vlan N``.  A stanza
      for several ports (``interface 1,3``, ``interface 1-4``) gives
      its VLAN lines to each, and says what else it sets
    * Port names are bare: ``1``, ``1/1``, ``A1``, ``Trk1``
    * ``routing`` on an interface enables L3 (replaces ``no switchport``)
    * IP addresses support BOTH ``A.B.C.D M.M.M.M`` and ``A.B.C.D/N``
    * VLAN port lists: ``untagged 1-24``, ``untagged 1,3,5``,
      ``tagged 25-26,A1``
    * A port has an ``interface`` stanza only if it has a setting of
      its own; the others are named by the VLAN lists and ``trunk``
      lines alone.  The parser gives each of those a record too, and
      the renderer writes no stanza that would say ``enable`` and
      nothing else for a port one of those lines gives back when the
      parser reads it

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
                               ``_parse_interface_stanza``), and the one
                               rule for where a stanza ends
                               (``_ends_the_stanza``)
    * ``render.py``          — canonical tree → AOS-S CLI text
    * ``port_names.py``      — cross-vendor port-name identity bridge
    * ``_svi_absorption.py`` — SVI-into-VLAN absorption flag (single
                               source of truth for ``absorbs_svi_into_vlan``)

Direction: ``bidirectional``.
Certainty: ``certified`` — validated against real-capture fixtures
    under ``tests/fixtures/real/aruba_aoss/`` (HPE community captures
    spanning WC.16.07 / WB.16.08 / WC.16.10 / WC.16.11 / KB.15.15);
    see ``tests/fixtures/real/RESULTS.md`` for the per-fixture matrix.
"""

from __future__ import annotations

from .codec import ArubaAOSSCodec

__all__ = ["ArubaAOSSCodec"]

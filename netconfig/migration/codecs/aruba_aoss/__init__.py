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

Current scope (Tier 1):
    * hostname
    * VLANs: id, name, ``untagged``/``tagged`` port lists,
      ``ip address A.B.C.D M.M.M.M`` and ``ip address A.B.C.D/N`` SVI
    * Interfaces (ports): name, ``enable``/``disable``, ``routing``
      (routed port), per-port ``ip address``
    * Static routes: ``ip route``, ``ip default-gateway``
    * SNMP community (``snmp-server community``)
    * NTP server (``timesync sntp`` / ``sntp server``)

Structural quirks handled:
    * ``;`` is the comment character (not ``!``)
    * Stanza delimiter is ``exit`` at the outdented position, or the
      next unindented line
    * Port names are bare: ``1``, ``1/1``, ``A1``, ``Trk1``
    * ``routing`` on an interface enables L3 (replaces ``no switchport``)
    * IP addresses support BOTH ``A.B.C.D M.M.M.M`` and ``A.B.C.D/N``
    * VLAN port lists: ``untagged 1-24``, ``untagged 1,3,5``,
      ``tagged 25-26,A1``

Out of scope (future):
    * STP per-port (``spanning-tree 1-24 priority 4``)
    * 802.1X, RADIUS, MAC auth
    * LACP / trunk (``trunk A1-A2 trk1 lacp``)
    * ACLs (``access-list``)

Certainty: ``best_effort`` — validated against synthetic fixtures
modelled on Aruba docs + community configs.
"""

from .codec import ArubaAOSSCodec

__all__ = ["ArubaAOSSCodec"]

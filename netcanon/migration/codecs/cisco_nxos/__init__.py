"""
Cisco NX-OS codec — bidirectional ``show running-config`` translator for
the Nexus 3000 / 5000 / 7000 / 9000 series.

Distinct vendor identity (``vendor_id=cisco_nxos``) from the IOS-XE
codecs: a different CLI grammar, a different ``CapabilityMatrix``, and a
different render path.  Use ``cisco_iosxe_cli`` for Catalyst / ASR / ISR
captures.

Module layout (mirrors ``cisco_iosxe_cli`` post-split):
    * codec.py      — ``CiscoNXOSCodec`` class (metadata, delegation,
                      probe, port-name bridges).
    * parse.py      — line-scan over NX-OS text.  Entry: :func:`parse_intent`.
    * render.py     — canonical tree → NX-OS text.  Entry: :func:`render_intent`.
    * port_names.py — cross-vendor port-name bridge.

Direction: ``bidirectional``.
Certainty: ``best_effort`` — Phase 2 of a four-phase build is complete
    (L1/L3 basics + L2 switchport/LAG + SNMP/users + HSRP).  Per-VRF
    static + VRF RD-RT (Phase 3) and VXLAN-EVPN (Phase 4) are still
    declared unsupported.  See ``docs/v0.2.0-planning/03-nxos-codec/``
    for the phase plan.
"""

from .codec import CiscoNXOSCodec

__all__ = ["CiscoNXOSCodec"]

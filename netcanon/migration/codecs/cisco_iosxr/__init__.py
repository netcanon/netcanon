"""
Cisco IOS-XR codec — bidirectional ``show running-config`` translator for
the ASR 9000 / NCS 5500 / 540 / 8000 / CRS service-provider routers.

Distinct vendor identity (``vendor_id=cisco_iosxr``) from the IOS-XE /
NX-OS codecs: a different CLI grammar (4-segment port names, top-level
``vrf`` stanzas, ``route-policy`` instead of ``route-map``, ``ipv4
address`` inside interfaces), a different ``CapabilityMatrix``, and a
different render path.  Use ``cisco_iosxe_cli`` for Catalyst / ASR1k /
ISR captures.

Module layout (mirrors ``cisco_iosxe_cli`` / ``cisco_nxos`` post-split):
    * codec.py      — ``CiscoIOSXRCodec`` class (metadata, delegation,
                      probe, port-name bridges).
    * parse.py      — line-scan over IOS-XR text.  Entry: :func:`parse_intent`.
    * render.py     — canonical tree → IOS-XR text.  Entry: :func:`render_intent`.
    * port_names.py — cross-vendor 4-segment port-name bridge.

Direction: ``bidirectional``.
Certainty: ``experimental`` — Phase 1 of a four-phase build is complete
    (hostname / domain / interfaces / default-VRF static routes).  VRF +
    RD-from-BGP (Phase 2), SP-routing Tier-3 harvest (Phase 3), and the
    certified-tier real-capture corpus (Phase 4) remain.  See
    ``docs/v0.2.0-planning/04-iosxr-codec/`` for the phase plan.
"""

from .codec import CiscoIOSXRCodec

__all__ = ["CiscoIOSXRCodec"]

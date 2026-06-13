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
Certainty: ``best_effort`` — Phases 1-3 of a four-phase build are
    complete: interfaces + default-VRF static (P1); VRF + RT +
    RD-from-``router bgp`` + per-iface VRF + Bundle-Ether LAGs + local
    users + per-VRF static + dot1q→VLAN (P2); the 7-config
    ``batfish/lab-validation`` real-capture corpus + SP-routing
    parse-and-display via ``dropped_tier3_sections`` (P3).  The
    ``certified`` flip + 1-2 grammar-diverse non-batfish captures remain
    (Phase 4).  See ``docs/v0.2.0-planning/04-iosxr-codec/`` for the
    phase plan.
"""

from .codec import CiscoIOSXRCodec

__all__ = ["CiscoIOSXRCodec"]

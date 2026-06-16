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
Certainty: ``certified`` — all four phases complete: interfaces +
    default-VRF static (P1); VRF + RT + RD-from-``router bgp`` +
    per-iface VRF + Bundle-Ether LAGs + local users + per-VRF static +
    dot1q→VLAN (P2); SP-routing parse-and-display via
    ``dropped_tier3_sections`` + the 7-config ``batfish/lab-validation``
    corpus (P3); the ``certified`` flip + 3 grammar-diverse
    ``ios-xr/xrd-tools`` captures (IS-IS / SR-MPLS / SRv6-L3VPN) (P4).
    The 10-config corpus from two independent sources all parses +
    round-trips cleanly.  See ``docs/v0.2.0-planning/04-iosxr-codec/``.
"""

from __future__ import annotations

from .codec import CiscoIOSXRCodec

__all__ = ["CiscoIOSXRCodec"]

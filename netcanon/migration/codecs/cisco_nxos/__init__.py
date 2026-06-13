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
Certainty: ``experimental`` — Phase 1 of a four-phase build (hostname /
    basic-L3 interfaces / VLANs / vrf-context / default-VRF static).  See
    ``docs/v0.2.0-planning/03-nxos-codec/`` for the phase plan.
"""

from .codec import CiscoNXOSCodec

__all__ = ["CiscoNXOSCodec"]

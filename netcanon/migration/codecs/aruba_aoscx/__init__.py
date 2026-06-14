"""
Aruba AOS-CX codec — bidirectional ``show running-config`` translator
for the modern Aruba switch portfolio (6000 / 6100 / 6200 / 6300 / 6400
/ 8100 / 8320 / 8325 / 8360 / 8400 / 9300 / CX-10000 series).

Distinct vendor identity (``vendor_id=aruba_aoscx``) from the legacy
``aruba_aoss`` codec: AOS-CX is a ground-up redesign (inspired by Arista
EOS), with multi-token interface names (``interface vlan 11`` /
``interface lag 1`` / ``interface 1/1/1``), CIDR addressing, bare ``vrf
<name>`` declarations + ``vrf attach`` interface binds, and an
admin-down default.  Use ``aruba_aoss`` for ArubaOS-Switch / ProVision
(16.x) captures.

Module layout (mirrors ``cisco_nxos`` post-split):
    * codec.py      — ``ArubaAOSCXCodec`` class (metadata, delegation,
                      probe, port-name bridges).
    * parse.py      — line-scan over AOS-CX text.  Entry: :func:`parse_intent`.
    * render.py     — canonical tree → AOS-CX text.  Entry: :func:`render_intent`.
    * port_names.py — cross-vendor port-name bridge (multi-token names).

Direction: ``bidirectional``.
Certainty: ``experimental`` — Phase 1 (Tier-1: hostname, basic-L3
    interfaces, VLANs, top-level ``vrf`` name, default-VRF static routes)
    + Phase 2 (L2 switchport + VLAN port projection, LAGs, local users).
    No real-capture corpus is wired yet; SNMP / active-gateway anycast /
    VXLAN-EVPN and the certified tier follow in later phases.  See
    ``docs/fixture-research-2015/11-aruba_aoscx.md``.
"""

from .codec import ArubaAOSCXCodec

__all__ = ["ArubaAOSCXCodec"]

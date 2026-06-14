"""
VyOS codec — bidirectional ``config.boot`` (curly-brace) translator for
the VyOS router/firewall NOS (the OSS Vyatta successor; VyOS 1.3 / 1.4 /
rolling).

VyOS stores its configuration as a JunOS-style curly-brace tree.  It is
a **distinct codec from ``juniper_junos``** (which consumes Junos
``set``-form): a VyOS ``config.boot`` has no ``set `` lines, uses
Linux-style ``ethN`` / ``lo`` / ``bondN`` device names, and terminates
leaves with bare newlines (no ``;``).  See ``VyOSCodec.probe`` for the
disambiguation.

Module layout (mirrors ``aruba_aoscx`` post-split):
    * codec.py      — ``VyOSCodec`` class (metadata, delegation, probe,
                      port-name bridges).
    * parse.py      — brace-stack walker.  Entry: :func:`parse_intent`.
    * render.py     — canonical tree → VyOS text.  Entry: :func:`render_intent`.
    * port_names.py — cross-vendor port-name bridge (Linux device names).

Direction: ``bidirectional``.
Certainty: ``experimental`` — Phase 1 (Tier-1: ``system host-name``;
    ethernet / loopback / dummy interfaces with address (IPv4+IPv6 CIDR /
    dhcp) / description / disable / mtu; ``vif`` VLAN sub-interfaces;
    ``protocols static`` routes).  Synthetically round-trip-validated; no
    real-capture corpus is wired yet — ``bonding`` LAGs, ``system login``
    users, ``service`` (SSH/NTP/SNMP), VRF, and the certified tier follow
    in later phases.
"""

from .codec import VyOSCodec

__all__ = ["VyOSCodec"]

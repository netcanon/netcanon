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
Certainty: ``certified`` — Phase 1 (Tier-1: ``system host-name``;
    ethernet / loopback / dummy interfaces with address (IPv4+IPv6 CIDR /
    dhcp) / description / disable / mtu; ``vif`` VLAN sub-interfaces;
    ``protocols static`` routes) + Phase 2 (``system login`` local users;
    ``system`` / ``service`` ntp servers; ``bonding`` LAGs) + Phase 3
    (``service snmp`` v1/v2c + v3 USM; VRF ``vrf name`` routing-instances
    + per-interface binding).  Round-trip-validated against a real-capture
    corpus of VyOS 1.4 ``config.boot`` files from the MIT-licensed
    ``cisagov/prescup-challenges`` source (Phase 4).  VXLAN + ``set``-form
    input follow in later phases.
"""

from .codec import VyOSCodec

__all__ = ["VyOSCodec"]

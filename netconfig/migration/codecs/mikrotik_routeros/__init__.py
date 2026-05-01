"""
MikroTik RouterOS codec — third real adapter (Session 2 of vendor-config-
research).

RouterOS stores its configuration as a line-oriented command script
produced by ``/export verbose``.  Structure is section-oriented: a
``/section path`` line sets the context, and subsequent ``add``/``set``
commands operate on that section.  The codec parses the Tier 1
canonical-intent surface (hostname, interfaces, VLANs, static routes,
DNS/NTP servers) and renders it back for cross-vendor translation.

Scope (current):
    * System identity (hostname).
    * Ethernet-port tweaks (description via ``comment``, enable flag).
    * VLAN interfaces on a parent (id, name, parent).
    * IPv4 addresses bound to interfaces.
    * Static routes (``/ip route``).
    * DNS and NTP servers (``/system dns``, ``/system ntp client``).

Out of scope (future):
    * Bridge VLAN filtering (VLAN-centric port membership).
    * Firewall filter/NAT rules (Tier 3 — informational only).
    * Wireless, CAPsMAN, MPLS, routing protocols.
    * ``set [ find ... ]`` predicates richer than ``default-name``.

Module layout (post-split per the codecs/README.md split-codec
convention):
    * ``codec.py``      — ``MikroTikRouterOSCodec`` class (metadata,
                          delegation, probe, port-name bridges)
    * ``parse.py``      — section dispatcher + per-section parsers;
                          hosts shared name/type helpers re-imported
                          by render
    * ``render.py``     — canonical tree → RouterOS ``/export`` text
    * ``port_names.py`` — cross-vendor port-name identity bridge

Certainty: ``best_effort`` — validated against synthetic fixtures; not
yet tested against a real device capture (RouterOS emits a lot of
default-value boilerplate via ``verbose`` that we filter out).
"""

from .codec import MikroTikRouterOSCodec

__all__ = ["MikroTikRouterOSCodec"]

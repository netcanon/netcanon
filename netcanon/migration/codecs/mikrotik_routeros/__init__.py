"""
MikroTik RouterOS codec — third real adapter (Session 2 of vendor-config-
research).

RouterOS stores its configuration as a line-oriented command script
produced by ``/export verbose``.  Structure is section-oriented: a
``/section path`` line sets the context, and subsequent ``add``/``set``
commands operate on that section.  The codec parses the Tier 1
canonical-intent surface (hostname, interfaces, VLANs, static routes,
DNS/NTP servers) and renders it back for cross-vendor translation.

Supported / lossy / unsupported xpaths: see ``_CAPS`` on
:class:`.codec.MikroTikRouterOSCodec`.  Coverage spans Tier 1
(hostname, interfaces, VLANs, static routes, DNS/NTP) with bridge
VLAN filtering, firewall, wireless / CAPsMAN / MPLS / routing
protocols declared unsupported.

Module layout (post-split per the codecs/README.md split-codec
convention):
    * ``codec.py``      — ``MikroTikRouterOSCodec`` class (metadata,
                          delegation, probe, port-name bridges)
    * ``parse.py``      — section dispatcher + per-section parsers;
                          hosts shared name/type helpers re-imported
                          by render
    * ``render.py``     — canonical tree → RouterOS ``/export`` text
    * ``port_names.py`` — cross-vendor port-name identity bridge

Certainty: ``certified`` — validated against real-capture fixtures
under ``tests/fixtures/real/mikrotik_routeros/``; the codec ships
filters for the default-value boilerplate RouterOS emits via
``/export verbose`` so the canonical round-trip is stable.  See
``tests/fixtures/real/RESULTS.md`` for the per-fixture matrix.
"""

from .codec import MikroTikRouterOSCodec

__all__ = ["MikroTikRouterOSCodec"]

"""
Cisco IOS-XE CLI codec — parses + renders ``show running-config`` text.

Shares ``vendor_id=cisco_iosxe`` with the NETCONF codec — both
target the same vendor YAML.  This means a stored
``show running-config`` backup (captured by the existing Netmiko
collector) can be fed directly into the translator pipeline via the
``source_filename`` shorthand on ``POST /api/v1/migration/plan``.

Direction: ``bidirectional``.
Certainty: ``certified``.

Module layout:
    * codec.py — ``CiscoIOSXECLICodec`` class (metadata, delegation,
                 probe, port-name bridges) + ``_walk_canonical``
                 (kept at module level so cross-codec ``iter_xpaths``
                 imports remain stable).
    * parse.py — line-scan + per-stanza dispatch over IOS-XE
                 ``show running-config`` text.  Public entry:
                 :func:`parse_intent`.
    * render.py — canonical tree → IOS-XE running-config text.
                 Public entry: :func:`render_intent`.
    * port_names.py — cross-vendor port-name bridge.
"""

from .codec import CiscoIOSXECLICodec

__all__ = ["CiscoIOSXECLICodec"]

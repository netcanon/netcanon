"""
FortiGate CLI codec — 5th real codec, Session D of vendor-config-
research.

Scope
-----
Parses / renders FortiOS CLI text.  FortiOS uses a recursive
``config/edit/set/next/end`` grammar — 5 keywords, arbitrary nesting
up to 3 levels in practice (``config > edit > config-subtable > edit``).

Current scope (Tier 1):
    * ``config system global`` — hostname, timezone
    * ``config system dns`` — primary + secondary DNS
    * ``config system ntp`` — ntpserver sub-table
    * ``config system interface`` — physical + VLAN interfaces,
      including ``ip`` (``A.B.C.D MASK`` form), ``alias``,
      ``status enable/disable``, ``type vlan`` + ``vlanid`` + parent
      ``interface`` for VLAN interfaces
    * ``config router static`` — static routes with dst + gateway

Structural quirks handled:
    * ``#config-version=`` banner on export (strong probe signal)
    * Quoted string values with spaces (``set alias "WAN uplink"``)
    * Multi-token set values (``set allowaccess ping https ssh``)
    * Integer ``edit`` IDs (static routes) + quoted ``edit`` IDs (ifaces)
    * ``set ip A.B.C.D M.M.M.M`` dotted-decimal mask form

Out of scope (future):
    * ``config firewall policy`` — Tier 3, informational only
    * ``config firewall address`` / ``addrgrp`` — needs address-object
      model in canonical intent
    * SD-WAN, IPSec, SSL-VPN, UTM profiles — specialised subsystems
    * Replacement messages / default profiles — the 80% boilerplate

Certainty: ``best_effort`` — validated against synthetic fixtures
modelled on FortiOS 7.x CLI references + community configs.
"""

from .codec import FortiGateCLICodec

__all__ = ["FortiGateCLICodec"]

"""
FortiGate CLI codec — 5th real codec.

Scope
-----
Parses / renders FortiOS CLI text.  FortiOS uses a recursive
``config/edit/set/next/end`` grammar — 5 keywords, arbitrary nesting
up to 3 levels in practice (``config > edit > config-subtable > edit``).

Supported blocks (Tier 1 + Tier 2):
    * ``config system global`` — hostname, timezone
    * ``config system dns`` — primary + secondary DNS
    * ``config system ntp`` — ntpserver sub-table
    * ``config system interface`` — physical + VLAN + LAG interfaces,
      including ``ip`` (``A.B.C.D MASK`` form), ``alias``,
      ``status enable/disable``, ``type vlan`` / ``type aggregate``
    * ``config router static`` — static routes with dst + gateway
    * ``config system snmp sysinfo`` + ``config system snmp community``
      — Tier-2 SNMP v1/v2c (community / location / contact /
      trap-hosts).  SNMPv3 users are NOT modelled.
    * ``config system admin`` — local admin users (hashed password +
      accprofile → CanonicalLocalUser)
    * ``config user radius`` — RADIUS servers (Tier 2)
    * ``config system dhcp server`` — DHCP pools (Tier 2)

Structural quirks handled:
    * ``#config-version=`` banner on export (strong probe signal)
    * Quoted string values with spaces (``set alias "WAN uplink"``)
    * Multi-token set values (``set allowaccess ping https ssh``)
    * Integer ``edit`` IDs (static routes) + quoted ``edit`` IDs (ifaces)
    * ``set ip A.B.C.D M.M.M.M`` dotted-decimal mask form
    * ``set radius-port 0`` idiom meaning "use default 1812" —
      canonicalised to 1812 at parse time so round-trip stays stable

Out of scope (future):
    * ``config firewall policy`` — Tier 3, informational only
    * ``config firewall address`` / ``addrgrp`` — needs address-object
      model in canonical intent
    * SD-WAN, IPSec, SSL-VPN, UTM profiles — specialised subsystems
    * Multi-VDOM (``config vdom``) — no fixture coverage yet;
      single-VDOM exports assumed
    * Replacement messages / default profiles — the 80% boilerplate

Module layout:
    * ``codec.py``            — ``FortiGateCLICodec`` class (metadata,
                                delegation, probe, port-name bridges)
    * ``parse.py``            — block-model tokeniser + per-stanza
                                dispatchers (``_apply_<path>``)
    * ``render.py``           — canonical tree → FortiOS CLI text
    * ``vlan_heuristics.py``  — ifType inference + VLAN-naming helpers
    * ``port_names.py``       — cross-vendor port-name identity bridge

Certainty: ``certified`` — three real captures across FortiOS 7.2.13
(physical FG-100E, ~35K lines) and 7.6.6 (FGT-70G branch + FGT-VM hub,
26K+ combined) all round-trip clean after the implicit-VLAN-typing +
radius-port-0 grammar fixes.  See ``tests/fixtures/real/RESULTS.md``.
"""

from .codec import FortiGateCLICodec

__all__ = ["FortiGateCLICodec"]

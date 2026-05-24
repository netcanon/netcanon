"""
FortiGate CLI codec — 5th real codec.

Scope
-----
Parses / renders FortiOS CLI text.  FortiOS uses a recursive
``config/edit/set/next/end`` grammar — 5 keywords, arbitrary nesting
up to 3 levels in practice (``config > edit > config-subtable > edit``).

Supported / lossy / unsupported xpaths: see ``_CAPS`` on
:class:`.codec.FortiGateCLICodec`.  Top-level coverage spans
``config system {global,dns,ntp,interface,snmp,admin,dhcp}`` plus
``config router static`` and ``config user radius``.  SNMPv3 users
are NOT modelled — the codec declares ``unsupported`` for that xpath.

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

"""
OPNsense adapter — second real adapter, Phase 1.

OPNsense stores its running config in a single ``config.xml`` file
whose hierarchy is already tree-shaped, so the parse/render work is
straightforward XML-to-dict-and-back.  What's interesting is the
cross-class story: OPNsense declares ``[firewall, router]`` while
``CiscoIOSXECodec`` declares ``[router, switch]``.  The
intersection is ``{router}`` so the class guard PERMITS the
migration — but the per-xpath capability matrices honestly flag
firewall rules and pf-specific bits as unsupported on the iosxe side,
so a real migration attempt surfaces the gaps via the
ValidationReport (not the class guard).  That's the intended layering.

Scope (Phase 1):
    * Hostname / system section.
    * Interface list — name, IP, subnet.
    * LAN/WAN zone membership.

Deliberately NOT in scope (Phase 2+):
    * Firewall rules, NAT, gateways (need the netconfig-ext YANG augment).
    * FRR BGP/OSPF packages (plugin-dependent, out of base config.xml).
    * Aliases, dashboards, dashboard widgets.
"""

from .codec import OPNsenseCodec

__all__ = ["OPNsenseCodec"]

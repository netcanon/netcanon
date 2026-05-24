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

Supported / lossy / unsupported xpaths: see ``_CAPS`` on
:class:`.codec.OPNsenseCodec`.  Coverage spans hostname / system
section, interface list (name + IP + subnet), LAN/WAN zone
membership, SNMPv3 (parser-side; see
``unsupported_rename_categories``).  Firewall rules / NAT /
gateways / FRR BGP-OSPF packages / aliases / dashboards are
declared unsupported (Tier 3 — would need the netcanon-ext YANG
augment).

Module layout:
    * ``codec.py``       — ``OPNsenseCodec`` class (metadata, delegation,
                           probe, port-name bridges, iter_xpaths)
    * ``parse.py``       — ``config.xml`` to ``CanonicalIntent``; owns
                           the bounded envelope-trim helper that rescues
                           legacy paramiko-shell backups
    * ``render.py``      — ``CanonicalIntent`` (or legacy dict) to
                           ``config.xml`` text
    * ``port_names.py``  — cross-vendor port-name identity bridge
"""

from .codec import OPNsenseCodec

__all__ = ["OPNsenseCodec"]

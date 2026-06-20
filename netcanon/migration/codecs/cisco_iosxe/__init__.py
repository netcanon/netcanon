"""
Cisco IOS-XE NETCONF adapter — 1st shipped codec; OpenConfig wire format.

Scope
-----
Operates against captured OpenConfig NETCONF ``<get-config>`` responses
(and produces ``<edit-config>``-ready output).  Live ncclient transport
is the embedded server's responsibility — the same split as the backup
collectors vs. collectors-consumers in the existing app.

Shares ``vendor_id=cisco_iosxe`` with the CLI codec (``cisco_iosxe_cli``)
— both target the same vendor YAML.  Distinguished by
``INPUT_FORMATS`` (``netconf-xml`` vs ``cli``).

Supported / lossy / unsupported xpaths: see ``_CAPS`` on
:class:`.codec.CiscoIOSXECodec`.  The render path emits the
``openconfig-interfaces`` subtree only; other surfaces are explicitly
declared unsupported in the matrix.  IPv4 and IPv6 addresses on
sub-interfaces are both shipped.

Declares ``unsupported_rename_categories = {'snmpv3', 'ports'}`` —
SNMPv3 round-trip is parser-side only (render emits no SNMPv3
container), and the NETCONF/OpenConfig stub has no port-name
translation (classify/format are inherited no-ops), so the rename
rail flips amber for both categories.

Module layout:
    * codec.py — ``CiscoIOSXECodec`` class (metadata, delegation,
                 probe, iter_xpaths) + inline parse + render helpers.
                 Parse/render are kept inline (not split to sibling
                 modules) because the XML-tree traversal differs
                 enough from the CLI-text codec pattern that a split
                 offered no clarity win; see ``codecs/README.md``.

Direction: ``bidirectional``.
Certainty: ``best_effort`` — Phase-0.5 NETCONF stub; render covers
    the ``openconfig-interfaces`` subtree only.  See
    ``tests/fixtures/real/RESULTS.md`` for the under-development matrix.
"""

from __future__ import annotations

from .codec import CiscoIOSXECodec

__all__ = ["CiscoIOSXECodec"]

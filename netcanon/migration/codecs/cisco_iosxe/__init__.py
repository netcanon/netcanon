"""
Cisco IOS-XE NETCONF adapter — first real adapter.

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

Declares ``unsupported_rename_categories = {'snmpv3'}`` — Tier-2
SNMPv3 round-trip is parser-side only; render emits no SNMPv3
container, so the rename rail flips amber for this category.

Direction: ``bidirectional``.
Certainty: ``best_effort`` — NETCONF stub; see
``tests/fixtures/real/RESULTS.md`` for the under-development matrix.
"""

from .codec import CiscoIOSXECodec

__all__ = ["CiscoIOSXECodec"]

"""OPNsense ``<dhcpd>`` zones for a tree's DHCP pools.

OPNsense's ISC DHCP server (the ``isc-dhcp`` plugin,
``src/etc/inc/plugins.inc.d/dhcpd.inc``) serves a zone that is
enabled and whose interface has an IPv4 address (it skips any other),
and writes a ``range`` line into ``dhcpd.conf`` for the pool of each
zone it serves, with no condition on the zone stating one; the one
file serves every interface.  The GUI will not save a zone without a
range ("A valid range must be specified.", ``services_dhcp.php``).  A
zone takes one range.

So a pool of the tree that states no range, or one end of one, is
written with what it hands out (:mod:`.._dhcp_pools`): its network's
hosts less the addresses this output gives its own interfaces, and of
the runs that leaves, the largest (the lower of two as large), since a
zone takes one.  A pool OPNsense can be given no range for -- no
network to take it from, an end outside its network, nothing left once
the output's own addresses are taken out -- is not written as a zone
that OPNsense would serve, since such a zone with no range is a
``range`` line with no addresses in a file every interface's server
reads; a comment says so in its place.  On a zone OPNsense does not
serve (its interface has no IPv4 address in the output, as an OPNsense
zone on a DHCP client has none) it is written as it stands.  Each is a
``review:`` comment of the output and a warning of the job
(``OPNsenseCodec.render_warnings``), read from the same function.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from xml.etree import ElementTree as ET

from ..._comments import comment_text
from ...canonical.intent import CanonicalDHCPPool, CanonicalInterface
from ...limits import ticked
from .._dhcp_pools import Handed, OwnAddresses, as_int, as_text, what_it_hands_out

#: What OPNsense does with a zone written with no range.
_NO_RANGE = "and OPNsense takes no DHCP zone without its range"


def _comment(text: str) -> ET.Element:
    """An XML comment of *text*, a space either side."""
    return ET.Comment(f" {comment_text(text, 'xml')} ")


def _range_of(
    pool: CanonicalDHCPPool, handed: Handed | str | None, label: str,
    zone_el: ET.Element, warnings: list[str],
) -> None:
    """The zone's ``<range>``: what a pool that states no whole range
    hands out, with a review comment above it, and otherwise the ends
    the pool states (none, on a zone OPNsense does not serve, for a
    pool that can be given no range)."""
    if not isinstance(handed, Handed):
        low, high = pool.start_ip, pool.end_ip
        if not (low or high):
            return
    else:
        first, last = handed.largest()
        low, high = as_text(first), as_text(last)
        said = (
            f"review: the source states {handed.stated} for this pool, which "
            f"hands out its network's addresses; written as {low}-{high}, "
            f"of {handed.span} less this output's own addresses"
        )
        if len(handed.free) > 1:
            said += (
                "; a zone takes one range, so the other runs of it are not "
                "handed out"
            )
        zone_el.append(_comment(said))
        warnings.append(
            f"OPNsense DHCP pool {label}: the source states no whole range for "
            f"it, {_NO_RANGE}; it is written as {low}-{high}, of {handed.span} "
            "less this output's own addresses; a review line in the output "
            "says so.",
        )
    range_el = ET.SubElement(zone_el, "range")
    if low:
        ET.SubElement(range_el, "from").text = low
    if high:
        ET.SubElement(range_el, "to").text = high


def render_pools(
    root: ET.Element,
    pools: Sequence[CanonicalDHCPPool],
    interfaces: Sequence[CanonicalInterface],
    zone_tag_for: Callable[[str], str],
) -> list[str]:
    """Write the ``<dhcpd>`` element of *pools* under *root*.

    Args:
        root: The document's root element.
        pools: The tree's DHCP pools.
        interfaces: The tree's interfaces, whose addresses a pool that
            states no whole range is not given; a zone whose interface
            has no IPv4 address among them is one OPNsense does not
            serve.
        zone_tag_for: The zone tag of an interface name
            (``render._zone_tag_for``); a pool that names no interface
            is under ``lan``.

    Returns:
        One warning for each review comment written.
    """
    warnings: list[str] = []
    if not pools:
        return warnings
    own = OwnAddresses(interfaces)
    served = {
        zone_tag_for(iface.name) for iface in ticked(interfaces)
        if any(as_int(address.ip) is not None for address in iface.ipv4_addresses)
    }
    dhcpd_el = ET.SubElement(root, "dhcpd")
    for pool in ticked(pools):
        label = pool.interface or pool.network or "with no interface and no network"
        handed = what_it_hands_out(pool, own)
        zone_tag = zone_tag_for(pool.interface) if pool.interface else "lan"
        if isinstance(handed, str) and zone_tag in served:
            dhcpd_el.append(_comment(
                f"review: a DHCP pool of the source ({label}) is not written: "
                f"{handed}, {_NO_RANGE}",
            ))
            warnings.append(
                f"OPNsense DHCP pool {label}: it is not written: {handed}, "
                f"{_NO_RANGE}; a review line in the output says so.",
            )
            continue
        zone_el = ET.SubElement(dhcpd_el, zone_tag)
        ET.SubElement(zone_el, "enable")
        _range_of(pool, handed, label, zone_el, warnings)
        if pool.gateway:
            ET.SubElement(zone_el, "gateway").text = pool.gateway
        if pool.dns_servers:
            ET.SubElement(zone_el, "dnsserver").text = ",".join(pool.dns_servers)
        if pool.domain_name:
            ET.SubElement(zone_el, "domain").text = pool.domain_name
        if pool.lease_time:
            ET.SubElement(zone_el, "defaultleasetime").text = str(pool.lease_time)
    return warnings

"""What a DHCP pool that states no range hands out, for a target that
has to be told.

The tree holds a pool as ONE run of addresses, and a pool that states
no range hands out its network: Junos's "will use all available
addresses within the subnet specified", except the broadcast address,
the interface's own and what is excluded; and Cisco's IOS DHCP server
"assumes that all IP addresses in a DHCP address pool subnet are
available for assigning", less ``ip dhcp excluded-address``.  A target that
takes a pool only with its range has to be told those addresses: a
FortiOS server with no ``config ip-range`` hands out none, RouterOS
takes no ``/ip pool`` without its ``ranges`` (the manual: "mandatory"),
and OPNsense will not save a zone with no range ("A valid range must be
specified.") and writes a ``range`` line for each pool of a zone it
serves.  Junos hands out a pool with no range itself, and is told a
pool that states one end of one: its reference of ``range`` does not
say what a range with one end is.

So a pool that states no range, or one end of one, is given its
network's hosts (all of a /31 or a /32), from the end it states to the
one it does not, less the addresses the output gives its own
interfaces.  A pool that can be given none -- no network to take it
from, an end outside its network, nothing left once the output's own
addresses are taken out -- has a reason instead, which the target says.
The words of each target's review line and warning are the target's:
this module holds what the addresses ARE.  It also names the tree's
lease that does not end (:data:`INFINITE_LEASE`).

Nothing here reads config text; a loop over what the tree holds is
ticked all the same, since a pasted config can give an output many
interfaces.
"""

from __future__ import annotations

import bisect
import ipaddress
from collections.abc import Sequence
from dataclasses import dataclass

from ..canonical.intent import CanonicalDHCPPool, CanonicalInterface
from ..limits import tick, ticked

#: The tree's lease for one that does not end: DHCP's "infinity"
#: (RFC 2131, 0xffffffff), as the FortiOS and IOS-XE CLI parsers read
#: one.
INFINITE_LEASE = 0xFFFFFFFF


class OwnAddresses:
    """The IPv4 addresses of the output's interfaces, sorted, so that
    the ones in a network are found without reading the others."""

    def __init__(self, interfaces: Sequence[CanonicalInterface]) -> None:
        found: set[int] = set()
        for iface in ticked(interfaces):
            for address in iface.ipv4_addresses:
                value = as_int(address.ip)
                if value is not None:
                    found.add(value)
        self._sorted = sorted(found)

    def spans_within(self, low: int, high: int) -> list[tuple[int, int]]:
        """The own addresses from *low* to *high*, as merged spans."""
        at = bisect.bisect_left(self._sorted, low)
        spans: list[tuple[int, int]] = []
        while at < len(self._sorted) and self._sorted[at] <= high:
            tick()
            value = self._sorted[at]
            if spans and spans[-1][1] + 1 == value:
                spans[-1] = (spans[-1][0], value)
            else:
                spans.append((value, value))
            at += 1
        return spans


def as_int(address: str) -> int | None:
    """*address* as an integer, or ``None`` for one that is not IPv4."""
    try:
        return int(ipaddress.IPv4Address(address))
    except ValueError:
        return None


def as_text(value: int) -> str:
    """The IPv4 address *value*, written."""
    return str(ipaddress.IPv4Address(value))


def hosts(network: ipaddress.IPv4Network) -> tuple[int, int]:
    """The first and the last address of *network* a client can be
    given: all of it for a /31 or a /32."""
    first, last = int(network.network_address), int(network.broadcast_address)
    return (first, last) if network.prefixlen >= 31 else (first + 1, last - 1)


def network_of(pool: CanonicalDHCPPool) -> ipaddress.IPv4Network | None:
    """The pool's network, or ``None`` where it states none (or one
    that is not an IPv4 network)."""
    if not pool.network:
        return None
    try:
        return ipaddress.IPv4Network(pool.network, strict=False)
    except ValueError:
        return None


@dataclass(frozen=True)
class Handed:
    """What a pool that states no whole range hands out.

    Attributes:
        low: The first address of the run, as an integer.
        high: The last.
        excluded: The output's own addresses from *low* to *high*, as
            merged spans, in order.
        free: The runs from *low* to *high* that *excluded* leaves, in
            order; never empty.
        stated: ``"no range"`` or ``"one end of its range"``, for the
            target's review line.
    """

    low: int
    high: int
    excluded: tuple[tuple[int, int], ...]
    free: tuple[tuple[int, int], ...]
    stated: str

    @property
    def span(self) -> str:
        """The run, written ``<low>-<high>``."""
        return f"{as_text(self.low)}-{as_text(self.high)}"

    def largest(self) -> tuple[int, int]:
        """The largest free run, the lower of two as large: what a
        target that takes one run of a pool is given."""
        return max(self.free, key=lambda run: (run[1] - run[0], -run[0]))


def what_it_hands_out(
    pool: CanonicalDHCPPool, own: OwnAddresses,
) -> Handed | str | None:
    """What *pool* hands out, for a target that has to be told.

    Returns:
        ``None`` where the pool states both ends of its range (it is
        written as it stands); a :class:`Handed` where it states no
        range, or one end; and where no address can be given, the
        reason, which begins "it" (``"it states no range and no
        network"``) so that a target can say it after the pool.
    """
    if pool.start_ip and pool.end_ip:
        return None
    stated = "one end of its range" if pool.start_ip or pool.end_ip else "no range"
    network = network_of(pool)
    if network is None:
        return f"it states {stated} and no network"
    first, last = hosts(network)
    low = as_int(pool.start_ip) if pool.start_ip else first
    high = as_int(pool.end_ip) if pool.end_ip else last
    if low is None or high is None or not (first <= low <= high <= last):
        return "its range is not in its network"
    excluded = own.spans_within(low, high)
    free: list[tuple[int, int]] = []
    at = low
    for span_low, span_high in ticked(excluded):
        if span_low > at:
            free.append((at, span_low - 1))
        at = span_high + 1
    if at <= high:
        free.append((at, high))
    if not free:
        return "every address of its range is this output's own"
    return Handed(low, high, tuple(excluded), tuple(free), stated)

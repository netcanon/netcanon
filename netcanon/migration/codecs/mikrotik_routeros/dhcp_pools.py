"""RouterOS ``/ip pool`` and ``/ip dhcp-server network`` for a tree's
DHCP pools.

MikroTik, *RouterOS manual*, "IP Pools" (``/ip pool``): ``ranges`` is
"IP address list of non-overlapping IP address ranges in the form of:
``from1-to1,from2-to2,...,fromN-toN``", and it is "( mandatory )".
So RouterOS takes no pool without its ranges, and a pool of the tree
that states no range, or one end of one, has to be written with the
addresses it hands out (:mod:`.._dhcp_pools`): its network's hosts,
less the addresses this output gives its own interfaces, which
``ranges`` states run by run.  A pool RouterOS can be given no range
for -- no network to take it from, an end outside its network, nothing
left once the output's own addresses are taken out -- is a
``# review:`` line in place of its ``add``.  Each is also a warning of
the job (``MikroTikRouterOSCodec.render_warnings``), read from the
same function.

The renderer writes no ``/ip dhcp-server`` (the server that binds a
pool to its interface); the codec's capability matrix says so.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from ...canonical.intent import CanonicalDHCPPool, CanonicalInterface
from ...limits import ticked
from .._dhcp_pools import OwnAddresses, as_text, what_it_hands_out

#: What RouterOS does with a pool written with no ``ranges``.
_NO_RANGES = "and RouterOS takes no /ip pool without its ranges"


def _pool_lines(
    pools: Sequence[CanonicalDHCPPool], own: OwnAddresses,
    quote: Callable[[str], str], warnings: list[str],
) -> list[str]:
    """The ``/ip pool`` section, one ``add`` a pool (or a review line
    in its place), the pools named ``dhcp_pool<N>`` in tree order."""
    lines = ["/ip pool"]
    for index, pool in enumerate(ticked(pools), start=1):
        label = pool.interface or pool.network or "with no interface and no network"
        handed = what_it_hands_out(pool, own)
        if isinstance(handed, str):
            lines.append(
                f"# review: a DHCP pool of the source ({label}) is not written: "
                f"{handed}, {_NO_RANGES}",
            )
            warnings.append(
                f"RouterOS DHCP pool {label}: it is not written: {handed}, "
                f"{_NO_RANGES}; a review line in the output says so.",
            )
            continue
        if handed is None:
            ranges = f"{pool.start_ip}-{pool.end_ip}"
        else:
            ranges = ",".join(
                f"{as_text(low)}-{as_text(high)}" for low, high in ticked(handed.free)
            )
            lines.append(
                f"# review: the source states {handed.stated} for the pool of "
                f"{label}, which hands out its network's addresses; written as "
                f"{handed.span}, less this output's own addresses",
            )
            warnings.append(
                f"RouterOS DHCP pool {label}: the source states no whole range "
                f"for it, {_NO_RANGES}; it is written as {handed.span}, less this "
                "output's own addresses; a review line in the output says so.",
            )
        lines.append(f"add name=dhcp_pool{index} ranges={quote(ranges)}")
    lines.append("")
    return lines


def _network_lines(
    pools: Sequence[CanonicalDHCPPool], quote: Callable[[str], str],
) -> list[str]:
    """The ``/ip dhcp-server network`` section: a pool's network-scoped
    options, for each pool that states its network."""
    lines = ["/ip dhcp-server network"]
    for pool in ticked(pools):
        if not pool.network:
            continue
        parts = ["add", f"address={quote(pool.network)}"]
        if pool.gateway:
            parts.append(f"gateway={quote(pool.gateway)}")
        if pool.dns_servers:
            parts.append(f"dns-server={quote(','.join(pool.dns_servers))}")
        if pool.domain_name:
            parts.append(f"domain={quote(pool.domain_name)}")
        lines.append(" ".join(parts))
    lines.append("")
    return lines


def render_pools(
    pools: Sequence[CanonicalDHCPPool],
    interfaces: Sequence[CanonicalInterface],
    quote: Callable[[str], str],
) -> tuple[list[str], list[str]]:
    """The DHCP sections of the output, and the job's warnings for them.

    Args:
        pools: The tree's DHCP pools.
        interfaces: The tree's interfaces, whose addresses a pool that
            states no whole range is not given.
        quote: Writes a value of the tree into a ``key=value``
            (``render._quote_if_needed``).

    Returns:
        The lines -- nothing where the tree has no pool -- and one
        warning for each review line among them.
    """
    if not pools:
        return [], []
    warnings: list[str] = []
    lines = _pool_lines(pools, OwnAddresses(interfaces), quote, warnings)
    return lines + _network_lines(pools, quote), warnings

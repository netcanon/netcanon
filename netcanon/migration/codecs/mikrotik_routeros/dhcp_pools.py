"""RouterOS ``/ip pool``, ``/ip dhcp-server`` and ``/ip dhcp-server
network`` for a tree's DHCP pools.

RouterOS spreads a DHCP server over three sections: the server
(``/ip dhcp-server``: the interface it runs on, the pool it takes
addresses from, its lease time), the pool (``/ip pool``: its ranges)
and the network (``/ip dhcp-server network``: the options given with an
address of it).  Each pool of the tree is written as all three, the
pool named ``dhcp_pool<N>`` and its server ``dhcp<N>``, in the tree's
order.

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
``# review:`` line in place of its ``add``, and has no server.

The CLI reference of ``/ip dhcp-server``: ``interface`` is
"(mandatory)", "Interface the DHCP server listens on", so a pool of the
tree that names no interface is written with no server, which a
``# review:`` line says in its place; and ``lease-time`` is "How long a
lease lasts", "Default: 30m".  The manual's own examples write
``disabled=no`` on a server they add, and so does this one.  Neither
that reference nor the manual's "DHCP" page states a lease that does
not end, so a pool whose lease does not end (DHCP's "infinity") is
written with no ``lease-time``, RouterOS's default, under a
``# review:`` line.

The options of a pool are an ``/ip dhcp-server network``, whose
``address`` is "the network DHCP server(s) will lease addresses from"
(the manual's "DHCP" page), so a pool of the tree that states a
gateway, DNS servers or a domain and no network is written without
them, under a ``# review:`` line.

Each review line is also a warning of the job
(``MikroTikRouterOSCodec.render_warnings``), read from the same
function.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from ...canonical.intent import CanonicalDHCPPool, CanonicalInterface
from ...limits import ticked
from .._dhcp_pools import INFINITE_LEASE, OwnAddresses, as_text, what_it_hands_out

#: What RouterOS does with a pool written with no ``ranges``.
_NO_RANGES = "and RouterOS takes no /ip pool without its ranges"


def _label(pool: CanonicalDHCPPool) -> str:
    """How a review line and a warning name *pool*."""
    return pool.interface or pool.network or "with no interface and no network"


def _pool_lines(
    pools: Sequence[CanonicalDHCPPool], own: OwnAddresses,
    quote: Callable[[str], str], warnings: list[str],
) -> tuple[list[str], list[int]]:
    """The ``/ip pool`` section, one ``add`` a pool (or a review line
    in its place), the pools named ``dhcp_pool<N>`` in tree order; and
    the numbers of the pools written."""
    lines = ["/ip pool"]
    written: list[int] = []
    for index, pool in enumerate(ticked(pools), start=1):
        label = _label(pool)
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
        written.append(index)
    lines.append("")
    return lines, written


def as_time(seconds: int) -> str:
    """*seconds* as a RouterOS time, in days, hours, minutes and
    seconds, the units it holds none of left out: ``1d``, ``1d12h``,
    ``30m``, ``1m30s``; ``0s`` for none."""
    if seconds <= 0:
        return "0s"
    parts = []
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        count, seconds = divmod(seconds, size)
        if count:
            parts.append(f"{count}{unit}")
    return "".join(parts)


def _server_lines(
    pools: Sequence[CanonicalDHCPPool], written: list[int],
    quote: Callable[[str], str], warnings: list[str],
) -> list[str]:
    """The ``/ip dhcp-server`` section: a server ``dhcp<N>`` on its
    interface for each pool written (or a review line in its place, for
    a pool that names no interface)."""
    lines = ["/ip dhcp-server"]
    for index in ticked(written):
        pool = pools[index - 1]
        label = _label(pool)
        if not pool.interface:
            lines.append(
                f"# review: the DHCP pool dhcp_pool{index} ({label}) names no "
                "interface, and a RouterOS DHCP server runs on one: no "
                "/ip dhcp-server is written for it, so it serves nothing until "
                "one is added",
            )
            warnings.append(
                f"RouterOS DHCP pool {label}: it names no interface, and a "
                "RouterOS DHCP server runs on one, so no /ip dhcp-server is "
                "written for it; a review line in the output says so.",
            )
            continue
        lease = ""
        if pool.lease_time == INFINITE_LEASE:
            lines.append(
                f"# review: the lease of the DHCP pool of {label} does not end "
                "in the source; RouterOS's manual states no lease-time for a "
                "lease that does not end, so none is written and RouterOS's "
                "default (30m) applies",
            )
            warnings.append(
                f"RouterOS DHCP pool {label}: its lease does not end in the "
                "source, and RouterOS's manual states no lease-time for one "
                "that does not end; it is written with RouterOS's default "
                "(30m); a review line in the output says so.",
            )
        else:
            lease = f" lease-time={as_time(pool.lease_time)}"
        lines.append(
            f"add address-pool=dhcp_pool{index} disabled=no "
            f"interface={quote(pool.interface)}{lease} name=dhcp{index}",
        )
    lines.append("")
    return lines


def _network_lines(
    pools: Sequence[CanonicalDHCPPool], written: list[int],
    quote: Callable[[str], str], warnings: list[str],
) -> list[str]:
    """The ``/ip dhcp-server network`` section: a pool's network-scoped
    options, for each pool that states its network (or a review line in
    its place, for a pool written that states options and no
    network)."""
    lines = ["/ip dhcp-server network"]
    shown = set(written)
    for index, pool in enumerate(ticked(pools), start=1):
        if not pool.network:
            if index in shown and (pool.gateway or pool.dns_servers or pool.domain_name):
                label = _label(pool)
                lines.append(
                    f"# review: the DHCP pool of {label} states no network, and "
                    "RouterOS gives a client its gateway, DNS servers and domain "
                    "from the /ip dhcp-server network that holds its address: "
                    "they are not written",
                )
                warnings.append(
                    f"RouterOS DHCP pool {label}: it states no network, and "
                    "RouterOS gives a client its gateway, DNS servers and domain "
                    "from an /ip dhcp-server network, so they are not written; "
                    "a review line in the output says so.",
                )
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
    lines, written = _pool_lines(pools, OwnAddresses(interfaces), quote, warnings)
    if written:
        lines += _server_lines(pools, written, quote, warnings)
    return lines + _network_lines(pools, written, quote, warnings), warnings

"""The switch's own DHCP server, written for a tree's DHCP pools.

HPE, ArubaOS-Switch Management and Configuration Guide ("DHCPv4
server"): ``dhcp-server pool <POOL-NAME>`` configures a pool, whose
statements are ``default-router``, ``dns-server``, ``domain-name``,
``lease [DD:HH:MM | infinite]`` ("The default lease period is one
day"), ``network`` and ``range``; ``dhcp-server enable`` enables the
server, which "Defaults to disabled".  HPE's DHCP white paper: a
dynamic pool is "a network address, subnet mask and IP range(s)", and
"The DHCP server will discard the invalid and incomplete pools".  Its
examples serve a pool on a VLAN whose stanza states ``dhcp-server`` and
whose subnet is the pool's network, and a pool whose network is no
VLAN of the switch to clients a DHCP relay forwards to it.  The switch
refuses to change the server's configuration while it is enabled.

So each pool of the tree is written as a ``dhcp-server pool`` stanza
in the form the switch prints one (a committed capture of a 2930F):
the name quoted, then ``default-router``, ``dns-server``,
``domain-name``, ``lease``, ``network <address> <mask>`` and ``range``
lines, indented, and ``exit``.  The tree holds no name for a pool, so
each is named ``pool-<N>``, in the tree's order.  The pools come after
every VLAN, and ``dhcp-server enable`` after the last pool, as the
switch prints them.  A VLAN serves a pool where the source serves it
on that VLAN's interface (``Vlan<id>``, the interface the stanza's
addresses are taken from, or a name that encodes the VLAN's id, such
as a Junos ``irb.<id>``) and the VLAN's stanza holds an address whose
subnet is the pool's network: its stanza is given ``dhcp-server``,
which the parser reads the pool's interface from.

What AOS-S cannot be given as the tree has it is a ``; review:`` line
and a warning of the job (``ArubaAOSSCodec.render_warnings``), read
from the same function:

* a pool with no network, or with a range outside it, or one no range
  can be given (:mod:`.._dhcp_pools`), is not written: the switch
  discards a pool with no network and range;
* a pool that states no range, or one end of one, is written the
  addresses it hands out, in as many ``range`` lines as that takes;
* a pool the source serves on an interface that is no VLAN of this
  output, or on a VLAN whose stanza holds no address of the pool's
  network, is written with no VLAN to serve it: it serves only
  clients a relay forwards to it;
* a gateway or DNS server that is not an IPv4 address, DNS servers
  after the eighth, and a domain that cannot stand between AOS-S's
  quotes, are not written;
* a lease that is not a whole number of minutes is written in minutes,
  and one longer than the 99 days of HPE's ``DD`` is not written (the
  switch's default of one day applies).

Nothing here reads config text; a loop over what the tree holds is
ticked all the same.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Sequence
from dataclasses import dataclass, field

from ..._one_value import breaks_its_quotes
from ...canonical.intent import CanonicalDHCPPool
from ...limits import ticked
from .._dhcp_pools import INFINITE_LEASE, OwnAddresses, as_int, as_text, network_of, what_it_hands_out

#: HPE: "The default lease period is one day"; the tree's default too.
DEFAULT_LEASE = 86400

#: The most days HPE's ``lease DD:HH:MM`` states.
MOST_DAYS = 99

#: HPE: ``default-router`` and ``dns-server`` each take up to eight
#: addresses.
MOST_ADDRESSES = 8

#: Why a pool AOS-S is not given is not written.
_DISCARDS = "and AOS-S discards a pool with no network and range"


@dataclass(frozen=True)
class Stanza:
    """A ``vlan`` stanza of the output, and the IPv4 subnets it holds.

    Attributes:
        index: The VLAN's place in the tree's ``vlans``.
        vlan_id: Its id.
        subnets: The subnet of each IPv4 address the stanza writes
            (none, for a stanza that writes no address).
        names: The interface names the stanza stands for, in lower
            case: ``vlan<id>``, the interface its addresses are taken
            from, and a pool's interface whose name encodes the id.
    """

    index: int
    vlan_id: int
    subnets: tuple[ipaddress.IPv4Network, ...]
    names: frozenset[str]


@dataclass
class Rendered:
    """An AOS-S output's DHCP server.

    Attributes:
        lines: The ``dhcp-server pool`` stanzas and ``dhcp-server
            enable``, and a review line for each pool not written.
        serving: The :attr:`Stanza.index` of each VLAN whose stanza
            takes ``dhcp-server``.
        warnings: One for each review line among *lines*.
    """

    lines: list[str] = field(default_factory=list)
    serving: set[int] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)


def _label(pool: CanonicalDHCPPool) -> str:
    """How a review line and a warning name *pool*."""
    return pool.network or pool.interface or "with no network"


def _review(rendered: Rendered, depth: str, pool: CanonicalDHCPPool, line: str, warning: str) -> None:
    rendered.lines.append(f"{depth}; review: {line}")
    rendered.warnings.append(
        f"AOS-S DHCP pool {_label(pool)}: {warning}; a review line in the output says so.",
    )


def lease_line(lease_time: int) -> tuple[str | None, str | None]:
    """The ``lease`` line for *lease_time* (``None`` for the switch's
    default of one day, or where none is written), and why it is not
    the tree's lease (``None`` where it is)."""
    if lease_time == INFINITE_LEASE:
        return "lease infinite", None
    seconds = lease_time or DEFAULT_LEASE
    if seconds < 0:
        return None, "is not a lease AOS-S takes: none is written, and its default of one day applies"
    if seconds == DEFAULT_LEASE:
        return None, None
    days, rest = divmod(seconds, 86400)
    if days > MOST_DAYS:
        return None, (
            f"is longer than the {MOST_DAYS} days of HPE's lease DD:HH:MM: none is written, "
            "and AOS-S's default of one day applies"
        )
    hours, rest = divmod(rest, 3600)
    minutes, extra = divmod(rest, 60)
    why = None
    if extra:
        # A lease shorter than a minute is one minute, never 00:00:00.
        minutes = minutes or (0 if days or hours else 1)
        why = (
            f"is {seconds} seconds, which is not a whole number of minutes; AOS-S states a "
            f"lease in minutes, so it is written as {days:02d}:{hours:02d}:{minutes:02d}"
        )
    return f"lease {days:02d}:{hours:02d}:{minutes:02d}", why


class _Vlans:
    """The output's VLAN stanzas, by the names they stand for and the
    subnets they hold, so that a pool's VLAN is found without reading
    the others."""

    def __init__(self, stanzas: Sequence[Stanza]) -> None:
        self._first: dict[str, Stanza] = {}
        self._held: dict[tuple[str, ipaddress.IPv4Network], Stanza] = {}
        for stanza in ticked(stanzas):
            for name in stanza.names:
                self._first.setdefault(name, stanza)
                for subnet in stanza.subnets:
                    self._held.setdefault((name, subnet), stanza)

    def serving(self, name: str, network: ipaddress.IPv4Network) -> tuple[Stanza | None, str]:
        """The stanza that serves a pool of *network* on *name*, or
        ``None`` and why none does."""
        lowered = name.lower()
        found = self._held.get((lowered, network))
        if found is not None:
            return found, ""
        first = self._first.get(lowered)
        if first is None:
            return None, f"this output has no VLAN stanza for {name}"
        return None, f"VLAN {first.vlan_id} holds no address whose subnet is {network} in this output"


def _range_lines(
    rendered: Rendered, pool: CanonicalDHCPPool, network: ipaddress.IPv4Network, own: OwnAddresses,
) -> list[str] | None:
    """The ``range`` lines of *pool*, or ``None`` where it is given no
    range (and so is not written), with the review line that says why."""
    handed = what_it_hands_out(pool, own)
    if handed is None:
        start, end = as_int(pool.start_ip), as_int(pool.end_ip)
        if start is not None and end is not None and (
            int(network.network_address) <= start <= end <= int(network.broadcast_address)
        ):
            return [f"   range {as_text(start)} {as_text(end)}"]
        _review(
            rendered, "", pool,
            f"a DHCP pool of the source ({_label(pool)}) is not written: its range is not "
            f"a run of addresses of its network {network}, {_DISCARDS}",
            f"it is not written, since its range is not a run of addresses of its network, "
            f"{_DISCARDS}",
        )
        return None
    if isinstance(handed, str):
        _review(
            rendered, "", pool,
            f"a DHCP pool of the source ({_label(pool)}) is not written: {handed}, {_DISCARDS}",
            f"it is not written: {handed}, {_DISCARDS}",
        )
        return None
    _review(
        rendered, "   ", pool,
        f"the source states {handed.stated} for the DHCP pool of {_label(pool)}, which hands "
        f"out its network's addresses; written as {handed.span}, less this output's own addresses",
        f"the source states {handed.stated} for it, and AOS-S takes a pool with its range; it "
        f"is written as {handed.span}, less this output's own addresses",
    )
    return [f"   range {as_text(low)} {as_text(high)}" for low, high in ticked(handed.free)]


def _option_lines(rendered: Rendered, pool: CanonicalDHCPPool) -> list[str]:
    """The ``default-router``, ``dns-server`` and ``domain-name`` lines
    of *pool*, with a review line for what is not written."""
    lines: list[str] = []
    if pool.gateway:
        if as_int(pool.gateway) is not None:
            lines.append(f'   default-router "{pool.gateway}"')
        else:
            _review(
                rendered, "   ", pool,
                "the gateway of this pool is not written: it is not an IPv4 address",
                "its gateway is not written, since it is not an IPv4 address",
            )
    servers = [server for server in pool.dns_servers if as_int(server) is not None]
    if len(servers) < len(pool.dns_servers):
        _review(
            rendered, "   ", pool,
            "a DNS server of this pool that is not an IPv4 address is not written",
            "a DNS server of it that is not an IPv4 address is not written",
        )
    if servers:
        lines.append(f'   dns-server "{",".join(servers[:MOST_ADDRESSES])}"')
    if len(servers) > MOST_ADDRESSES:
        _review(
            rendered, "   ", pool,
            f"the DNS servers of this pool after the first {MOST_ADDRESSES} are not "
            f"written: a pool takes {MOST_ADDRESSES}",
            f"its DNS servers after the first {MOST_ADDRESSES} are not written, since a "
            f"pool takes {MOST_ADDRESSES}",
        )
    if pool.domain_name:
        if breaks_its_quotes(pool.domain_name):
            _review(
                rendered, "   ", pool,
                "the domain of this pool is not written: it holds a quote or white space "
                "other than a space, which AOS-S does not read as one value between its quotes",
                "its domain is not written, since it holds a quote or white space other than "
                "a space, which AOS-S does not read between its quotes",
            )
        else:
            lines.append(f'   domain-name "{pool.domain_name}"')
    return lines


def render_pools(
    pools: Sequence[CanonicalDHCPPool], stanzas: Sequence[Stanza], own: OwnAddresses,
) -> Rendered:
    """The ``dhcp-server pool`` stanzas of an AOS-S output for *pools*,
    which VLAN stanzas take ``dhcp-server``, and the job's warnings.

    Args:
        pools: The tree's pools.
        stanzas: The output's VLAN stanzas.
        own: The output's own addresses, which a pool that states no
            whole range is not given.

    Returns:
        The lines (nothing where the tree has no pool), the VLANs that
        serve, and a warning for each review line.
    """
    rendered = Rendered()
    vlans = _Vlans(stanzas)
    written = 0
    for number, pool in enumerate(ticked(pools), start=1):
        network = network_of(pool)
        if network is None:
            _review(
                rendered, "", pool,
                f"a DHCP pool of the source ({_label(pool)}) is not written: it states no "
                f"IPv4 network, {_DISCARDS}",
                f"it is not written, since it states no IPv4 network, {_DISCARDS}",
            )
            continue
        # The header goes above the review line a range may be given.
        opens_at = len(rendered.lines)
        ranges = _range_lines(rendered, pool, network, own)
        if ranges is None:
            continue
        rendered.lines.insert(opens_at, f'dhcp-server pool "pool-{number}"')
        rendered.lines += _option_lines(rendered, pool)
        lease, why = lease_line(pool.lease_time)
        if why is not None:
            _review(
                rendered, "   ", pool,
                f"the lease of this pool {why}",
                f"its lease {why}",
            )
        if lease is not None:
            rendered.lines.append(f"   {lease}")
        rendered.lines.append(f"   network {network.network_address} {network.netmask}")
        rendered.lines += ranges
        if pool.interface:
            stanza, why_not = vlans.serving(pool.interface, network)
            if stanza is not None:
                rendered.serving.add(stanza.index)
            else:
                _review(
                    rendered, "   ", pool,
                    f"the source serves this pool on {pool.interface}; AOS-S serves a pool on a "
                    "VLAN whose stanza states dhcp-server and holds an address of its network, "
                    f"and {why_not}: it serves only clients a DHCP relay forwards to it",
                    f"the source serves it on {pool.interface}, and {why_not}, so AOS-S serves "
                    "it only to clients a DHCP relay forwards to it",
                )
        rendered.lines.append("   exit")
        written += 1
    if written:
        rendered.lines.append("dhcp-server enable")
    return rendered

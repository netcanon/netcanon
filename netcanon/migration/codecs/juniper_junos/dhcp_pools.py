"""The Junos lines of a tree's DHCP pools, and the job's warnings; and
the one range the parser reads a pool as.

A pool is an address-assignment pool and, where it names its
interface, a ``dhcp-local-server`` group of the same name that binds
it there:

* ``set access address-assignment pool <P> family inet network <CIDR>``
* ``set access address-assignment pool <P> family inet range <R> low <ip>``
  and ``... high <ip>``
* ``set access address-assignment pool <P> family inet dhcp-attributes
  router|name-server|maximum-lease-time|domain-name <value>``
* ``set system services dhcp-local-server group <P> interface <iface>``

Juniper, *Junos OS DHCP User Guide*, of a pool of the DHCP local
server: "If no range is specified, the pool will use all available
addresses within the subnet specified.  (Broadcast addresses,
interface addresses, and excluded addresses are not available.)"  The
CLI reference of ``range`` names its ``low`` ("Lower limit of an
address range") and its ``high`` ("Upper limit") and does not say what
a range with one of them is.

So a pool of the tree that states no range is written as its network,
which Junos hands out itself.  A pool that states one end of its range
hands out its network's hosts from that end (:mod:`.._dhcp_pools`), and
is written as one whole range: from the end it states to the other end
of the hosts, less the addresses this output gives its own interfaces
-- where those leave several runs, the largest, since the parser reads
one range of a pool back -- under a ``# review:`` line.  A pool that
can be given no address (one that states no network and not both ends
of a range, an end outside its network, nothing left once the output's
own addresses are taken out) is a ``# review:`` line in place of its
lines, and has no group.  Each review line is also a warning of the job
(``JunosCodec.render_warnings``), read from the same function.

A pool can state several ranges (``range <R> low|high``), and Juniper's
subscriber-management pages say every range of a pool is searched for
an address to hand out; the tree holds one run of a pool.  The parser
reads a pool's ranges by name and keeps the largest run their addresses
make (:func:`one_range`), and a row of the sections not translated
says the rest (:func:`pool_rows`), as it does a pool that states
neither a network nor a range, which the tree has no addresses of.

A pool can also exclude addresses from what it hands out:
``excluded-address <ip>`` and ``excluded-range <R> low|high <ip>``
under ``family inet`` (Juniper: from Junos 18.1R1, "to prevent them
from being allocated from an address pool"), and ``exclude-address
<ip>`` in the older ``system services dhcp pool <CIDR>``.  The tree has
no place for an exclusion, so the parser takes the excluded addresses
out of what the pool hands out (:func:`pool_reading`): where they take
out none of it, the pool is read as it was; otherwise it is read as the
largest run left once the excluded addresses and the device's own
interface addresses (which Junos does not hand out either) are taken
out, with both its ends stated, and a row says the runs left out, a
pool that is left with no address, and an exclusion that cannot be
read (:func:`exclusion_rows`).

Nothing here reads config text; a loop over what the tree holds is
ticked all the same, since a pasted config can give an output many
pools and interfaces.
"""

from __future__ import annotations

import bisect
import functools
import ipaddress
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ...canonical.intent import CanonicalDHCPPool, CanonicalIntent, CanonicalInterface
from ...canonical.transforms import synthesize_svis_from_vlan_l3
from ...limits import tick, ticked
from .._dhcp_pools import Handed, OwnAddresses, as_int, as_text, hosts, what_it_hands_out
from .._helpers import a_few_named

#: How many characters of a pool's name a row shows.
_NAME_SHOWN = 40

#: The head of a row for a pool, and the words of its exclusions, by
#: whether the pool is of the older ``system services dhcp`` form.
_EXCLUSION_HEADS = (
    (False, "access address-assignment pool", "family inet excluded-address or excluded-range"),
    (True, "system services dhcp pool", "exclude-address"),
)


def one_range(ranges: Mapping[str, Mapping[str, str]], network: str) -> tuple[str, str, bool]:
    """The range the tree holds of a pool whose ranges are *ranges* (by
    name, each its ``low`` and its ``high`` where it states them), and
    whether the pool hands out addresses outside it.

    A pool of one range is that range as it stands: an end it does not
    state is left unstated, which the tree reads as the edge of the
    network's hosts (:mod:`.._dhcp_pools`).  Of several, the ranges are
    read as the tree reads one -- an end a range does not state is the
    edge of the hosts of *network* -- those that meet or overlap are one
    run, and the largest run is kept (the lower of two as large).  An
    end of the kept run that no range states is left unstated, so that
    a renderer reads it as the tree reads such an end (less the output's
    own addresses), and not as an address the source wrote.  A range
    that cannot be read (an end that is not an address, a low above its
    high, one end and no network) hands out nothing the tree can count.

    Returns:
        The low and the high the tree holds (``""`` for one not
        stated), and ``True`` where some of the pool's ranges are not
        among them, which a row says (:func:`pool_rows`).
    """
    if len(ranges) <= 1:
        bounds = next(iter(ranges.values()), {})
        return bounds.get("low", ""), bounds.get("high", ""), False
    runs, unread = _runs(ranges, _edge(network))
    if not runs:
        bounds = next(iter(ranges.values()))
        return bounds.get("low", ""), bounds.get("high", ""), True
    low, high, low_stated, high_stated = max(runs, key=lambda run: (run[1] - run[0], -run[0]))
    return (
        as_text(low) if low_stated else "",
        as_text(high) if high_stated else "",
        len(runs) > 1 or unread,
    )


def _edge(network: str) -> tuple[int, int] | None:
    """The first and the last host of *network*, or ``None`` where it
    is not stated or is not an IPv4 network."""
    try:
        return hosts(ipaddress.IPv4Network(network, strict=False)) if network else None
    except ValueError:
        return None


def _runs(
    ranges: Mapping[str, Mapping[str, str]], edge: tuple[int, int] | None,
) -> tuple[list[list[Any]], bool]:
    """The runs a pool's *ranges* make, in order, each ``[low, high,
    low stated, high stated]`` (an end a range does not state is the
    *edge* of the network's hosts), and whether some range cannot be
    read."""
    spans: list[tuple[int, int, bool, bool]] = []
    for bounds in ticked(ranges.values()):
        low = as_int(bounds["low"]) if "low" in bounds else (edge[0] if edge else None)
        high = as_int(bounds["high"]) if "high" in bounds else (edge[1] if edge else None)
        if low is not None and high is not None and low <= high:
            spans.append((low, high, "low" in bounds, "high" in bounds))
    runs: list[list[Any]] = []
    for low, high, low_stated, high_stated in ticked(sorted(spans)):
        if runs and low <= runs[-1][1] + 1:
            run = runs[-1]
            if low == run[0]:
                run[2] = run[2] or low_stated
            if high > run[1]:
                run[1], run[3] = high, high_stated
            elif high == run[1]:
                run[3] = run[3] or high_stated
        else:
            runs.append([low, high, low_stated, high_stated])
    return runs, len(spans) < len(ranges)


def _merged(spans: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    """*spans* in order, those that meet or overlap made one."""
    merged: list[tuple[int, int]] = []
    for low, high in ticked(sorted(spans)):
        if merged and low <= merged[-1][1] + 1:
            if high > merged[-1][1]:
                merged[-1] = (merged[-1][0], high)
        else:
            merged.append((low, high))
    return merged


def _less(runs: Sequence[tuple[int, int]], taken: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    """What is left of *runs* once *taken* is taken out of them: both
    in order, neither with two spans that meet."""
    left: list[tuple[int, int]] = []
    first = 0
    for low, high in ticked(runs):
        while first < len(taken) and taken[first][1] < low:
            tick()
            first += 1
        at = low
        each = first
        while each < len(taken) and taken[each][0] <= high:
            tick()
            if taken[each][0] > at:
                left.append((at, taken[each][0] - 1))
            at = max(at, taken[each][1] + 1)
            each += 1
        if at <= high:
            left.append((at, high))
    return left


def excluded_spans(
    addresses: Iterable[str], ranges: Mapping[str, Mapping[str, str]],
) -> tuple[list[tuple[int, int]], bool]:
    """The addresses a pool excludes -- each of *addresses*, and each of
    *ranges* (by name, its ``low`` and its ``high``) -- as spans in
    order, and whether one of them cannot be read: an address that is
    not one, or a range that does not state both ends or states a low
    above its high (Juniper's reference names both ends, and does not
    say what a range with one of them excludes)."""
    spans: list[tuple[int, int]] = []
    unread = False
    for address in ticked(addresses):
        value = as_int(address)
        if value is None:
            unread = True
        else:
            spans.append((value, value))
    for bounds in ticked(ranges.values()):
        low, high = as_int(bounds.get("low", "")), as_int(bounds.get("high", ""))
        if low is None or high is None or low > high:
            unread = True
        else:
            spans.append((low, high))
    return _merged(spans), unread


@dataclass(frozen=True)
class Reading:
    """What the tree holds of a pool, and what the rows say of it.

    Attributes:
        start_ip: The low end of the range the tree holds, ``""`` where
            it is not stated.
        end_ip: The high end.
        several: Some of the pool's ranges are not in that range
            (:func:`pool_rows`).
        split: The addresses it excludes leave more than one run of
            what it hands out, and the others are not in that range.
        none_left: It excludes every address it hands out that is not
            the device's own; the tree holds no pool of it.
        unread: It states an exclusion that cannot be read
            (:func:`excluded_spans`), which is not taken out.
    """

    start_ip: str
    end_ip: str
    several: bool
    split: bool = False
    none_left: bool = False
    unread: bool = False


def own_addresses_of(tree: CanonicalIntent) -> Callable[[], OwnAddresses]:
    """The addresses of *tree*'s own interfaces, read the first time
    they are asked for: only a pool that excludes an address needs
    them."""
    return functools.cache(lambda: OwnAddresses(pool_interfaces(tree)))


def pool_reading(
    ranges: Mapping[str, Mapping[str, str]],
    network: str,
    excluded_addresses: Iterable[str],
    excluded_ranges: Mapping[str, Mapping[str, str]],
    own: Callable[[], OwnAddresses],
) -> Reading:
    """What the tree holds of a pool whose network is *network*, whose
    ranges are *ranges* (:func:`one_range`), and which excludes
    *excluded_addresses* and *excluded_ranges* (:func:`excluded_spans`).

    The tree has no place for an exclusion.  Where the excluded
    addresses take out nothing the pool hands out, the pool is read as
    :func:`one_range` reads it, its ends as stated.  Otherwise what it
    hands out is its ranges -- or, with none, its network's hosts --
    less the excluded addresses and *own*, the device's own interface
    addresses (Junos's DHCP guide: "Broadcast addresses, interface
    addresses, and excluded addresses are not available"); the largest
    run of that is kept, the lower of two as large, with both its ends
    stated, since an end no range states would be read as the edge of
    the hosts, which an excluded address can be.  An address that is
    the device's own is taken out of what the pool hands out before an
    exclusion is weighed, so that a pool that excludes only its
    router's address is read as it was.

    Returns:
        The reading, with what a row says of the pool.
    """
    start_ip, end_ip, several = one_range(ranges, network)
    excluded, unread = excluded_spans(excluded_addresses, excluded_ranges)
    as_read = Reading(start_ip, end_ip, several, unread=unread)
    if not excluded:
        return as_read
    edge = _edge(network)
    if ranges:
        before = [(run[0], run[1]) for run in _runs(ranges, edge)[0]]
    else:
        before = [edge] if edge else []
    addresses = own()
    taken: list[tuple[int, int]] = []
    for low, high in ticked(before):
        taken.extend(addresses.spans_within(low, high))
    handed = _less(before, taken)
    left = _less(handed, excluded)
    if left == handed:
        return as_read
    if not left:
        return Reading("", "", several, none_left=True, unread=unread)
    low, high = max(left, key=lambda run: (run[1] - run[0], -run[0]))
    # A run of the ranges that holds two runs of what is left is split
    # by what is taken out; the other runs are a row of their own.
    starts = [run_low for run_low, _ in before]
    holders = [bisect.bisect_right(starts, run_low) - 1 for run_low, _ in left]
    return Reading(
        as_text(low), as_text(high), several,
        split=len(set(holders)) < len(holders), unread=unread,
    )


def _shown(name: str) -> str:
    """*name* as a row shows it: its first characters, on one line."""
    name = " ".join(name.split()) or "with no name"
    return name if len(name) <= _NAME_SHOWN else name[: _NAME_SHOWN - 1] + "…"


def pool_rows(several: Sequence[str], no_addresses: Sequence[str]) -> list[str]:
    """The rows of ``dropped_tier3_sections`` for the pools *several*,
    some of whose ranges the tree does not hold (:func:`one_range`), and
    *no_addresses*, which state neither a network nor a range: a few
    named and the rest counted."""
    rows: list[str] = []
    if several:
        rows.append(
            f"access address-assignment pool {a_few_named([_shown(n) for n in several])}: "
            "family inet range -- more than one range; the tree holds one run of a pool, "
            "so the largest is kept and the others are not translated",
        )
    if no_addresses:
        rows.append(
            f"access address-assignment pool {a_few_named([_shown(n) for n in no_addresses])}: "
            "family inet with no network and no range -- no address of it the tree can "
            "hold; not translated",
        )
    return rows


def exclusion_rows(
    split: Sequence[tuple[bool, str]],
    none_left: Sequence[tuple[bool, str]],
    unread: Sequence[tuple[bool, str]],
) -> list[str]:
    """The rows of ``dropped_tier3_sections`` for the exclusions of the
    pools (:class:`Reading`): each pool is ``(older form, name)``, and a
    few are named in a row and the rest counted.

    Args:
        split: The pools whose excluded addresses leave more than one
            run, the largest of which is kept.
        none_left: The pools left with no address.
        unread: The pools with an exclusion that cannot be read.
    """
    reasons = (
        (split, "what the pool hands out, less the addresses it excludes and this "
                "device's own, is more than one run; the tree holds one run of a pool, "
                "so the largest is kept and the others are not translated"),
        (none_left, "every address the pool hands out is excluded or this device's "
                    "own, so it hands out none; not translated"),
        (unread, "an exclusion this parser cannot read (an address that is not one, a "
                 "range without both ends or with its low above its high) is not "
                 "translated, so the target may hand out an address the source does not"),
    )
    rows: list[str] = []
    for pools, reason in reasons:
        for older, head, words in _EXCLUSION_HEADS:
            names = [_shown(name) for is_older, name in ticked(pools) if is_older == older]
            if names:
                rows.append(f"{head} {a_few_named(names)}: {words} -- {reason}")
    return rows


def pool_interfaces(tree: CanonicalIntent) -> list[CanonicalInterface]:
    """Every interface the output holds an address on: the tree's, and
    the VLAN interfaces the renderer makes of a VLAN's addresses."""
    return [*tree.interfaces, *synthesize_svis_from_vlan_l3(tree)]


def _label(pool: CanonicalDHCPPool) -> str:
    """How a review line and a warning name *pool*."""
    return pool.interface or pool.network or "with no interface and no network"


def _how(pool: CanonicalDHCPPool, own: OwnAddresses) -> Handed | str | None:
    """How *pool* is written: ``None`` as it stands (both ends of its
    range, or a network and no range, which Junos hands out itself); a
    :class:`.._dhcp_pools.Handed` where it states one end of its range;
    and where it can be given no address, the reason."""
    if bool(pool.start_ip) == bool(pool.end_ip) and (pool.network or pool.start_ip):
        return None
    return what_it_hands_out(pool, own)


def _one_end(label: str, handed: Handed, lines: list[str], warnings: list[str]) -> tuple[str, str]:
    """The review line and the warning of a pool that states one end of
    its range, and the range it is written with."""
    low, high = handed.largest()
    written = f"{as_text(low)}-{as_text(high)}"
    if len(handed.free) > 1:
        written += f", the largest run of {handed.span} that holds none of this output's own addresses"
    elif handed.excluded:
        written += f", which is {handed.span} less this output's own addresses"
    lines.append(
        f"# review: the source states one end of the range of the DHCP pool of {label}, "
        f"and Junos's reference does not say what a range with one end is: written as {written}",
    )
    warnings.append(
        f"Junos DHCP pool {label}: the source states one end of its range; it is written "
        f"as {written}; a review line in the output says so.",
    )
    return as_text(low), as_text(high)


def render_pools(
    pools: Sequence[CanonicalDHCPPool], interfaces: Sequence[CanonicalInterface],
    name_of: Callable[[CanonicalDHCPPool, int], str],
    quote: Callable[[str], str], quote_always: Callable[[str], str],
) -> tuple[list[str], list[str]]:
    """The lines of a Junos output for *pools*, and the job's warnings.

    Args:
        pools: The tree's pools.
        interfaces: Every interface the output holds an address on
            (:func:`pool_interfaces`).
        name_of: The name of a pool and of its group, from the pool and
            its place in *pools*.
        quote: How the renderer writes a name that may need quotes.
        quote_always: How it writes free text.

    Returns:
        The lines, and one warning for each review line among them.
    """
    own = OwnAddresses(interfaces)
    lines: list[str] = []
    warnings: list[str] = []
    for idx, pool in enumerate(ticked(pools)):
        label = _label(pool)
        how = _how(pool, own)
        if isinstance(how, str):
            lines.append(
                f"# review: a DHCP pool of the source ({label}) is not written: {how}, "
                "so there is no address of it to write",
            )
            warnings.append(
                f"Junos DHCP pool {label}: it is not written: {how}; a review line in "
                "the output says so.",
            )
            continue
        start, end = (pool.start_ip, pool.end_ip) if how is None else _one_end(label, how, lines, warnings)
        name = name_of(pool, idx)
        path = f"set access address-assignment pool {quote(name)} family inet"
        if pool.network:
            lines.append(f"{path} network {pool.network}")
        if start:
            lines.append(f"{path} range r1 low {start}")
        if end:
            lines.append(f"{path} range r1 high {end}")
        if pool.gateway:
            lines.append(f"{path} dhcp-attributes router {pool.gateway}")
        for dns in pool.dns_servers:
            lines.append(f"{path} dhcp-attributes name-server {dns}")
        # Junos's default lease is a day; the value is written all the
        # same, so that a tree's lease reads back as it stands.
        if pool.lease_time:
            lines.append(f"{path} dhcp-attributes maximum-lease-time {pool.lease_time}")
        if pool.domain_name:
            lines.append(f"{path} dhcp-attributes domain-name {quote_always(pool.domain_name)}")
        # A group binds at least one interface (a group with none is a
        # commit error), so a pool that names none has no group.
        if pool.interface:
            lines.append(
                f"set system services dhcp-local-server group {quote(name)} interface {pool.interface}",
            )
    return lines, warnings

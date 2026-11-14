"""An IOS-XE DHCP pool as the server hands it out.

Cisco, *IP Addressing Configuration Guide, Cisco IOS XE 17.x*,
"Configuring the Cisco IOS XE DHCP Server":

* "The DHCP server assumes that all other IP addresses in a DHCP
  address pool subnet are available for assigning to DHCP clients";
  ``ip dhcp excluded-address low-address [high-address]`` names the
  addresses it must not assign.
* "The IP address configured on a device interface is automatically
  excluded from the DHCP address pool."
* Before it assigns an address the server pings it, and an address
  that answers is a conflict and is not assigned.
* A directly connected client is given the pool whose subnet is
  configured on the interface the request arrived on; a request a
  relay forwards, the pool whose subnet holds the relay's address.
* ``network network-number [mask | /prefix-length] [secondary]``,
  with the network's natural mask where neither is given.
* ``no service dhcp`` turns the server (and the relay) off; it is on
  by default.
* ``dns-server address [address2 ... address8]`` and ``default-router``
  take up to eight addresses on one line, in order of preference (the
  command reference); a second line replaces the first (Cisco's
  community answers), so the renderer writes the servers on one line.

The tree holds a pool as ONE run of addresses (``start_ip`` ..
``end_ip``) served on ONE interface.  So the parser reads what the
server would hand out -- the pool's network less what is excluded,
the device's own addresses and the addresses that answer for a router
of the subnet (its default router, a virtual router: an inference
from the ping above, which the chapter does not spell out) -- and
which interface's subnet the pool is; and the renderer writes a run
as the exclusions on either side of it.  What the tree has no place
for is a row of the sections not translated, one a kind, naming a few
pools and never a value.

``ip dhcp excluded-address vrf <name> ...`` excludes addresses of the
pools of a VRF (a pool states its VRF with ``vrf <name>``, Cisco's
SD-WAN DHCP server example); a line without ``vrf`` excludes them from
the pools of no VRF.  The ``vrf`` form of the exclusion is not in the
chapter above -- Cisco's community answers give it for IOS XE 17.6 and
later -- so the renderer writes it under a review line.
"""

from __future__ import annotations

import bisect
import ipaddress
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from ...canonical.intent import CanonicalDHCPPool, CanonicalInterface
from ...limits import tick, ticked
from .._helpers import a_few_named

#: ``ip dhcp excluded-address [vrf <name>] <low> [<high>]``, matched on a
#: line of the top with the white space at its ends taken off.
_EXCLUDED_RE = re.compile(
    r"^ip[ \t]+dhcp[ \t]+excluded-address(?:[ \t]+vrf[ \t]+(\S+))?"
    r"[ \t]+(\d{1,3}(?:\.\d{1,3}){3})(?:[ \t]+(\d{1,3}(?:\.\d{1,3}){3}))?$",
    re.IGNORECASE,
)
#: The first words of such a line, whatever form the rest has.
_EXCLUDED_HEAD_RE = re.compile(r"^ip[ \t]+dhcp[ \t]+excluded-address(?:[ \t]|$)", re.IGNORECASE)
#: ``[no] service dhcp``.
_SERVICE_RE = re.compile(r"^(no[ \t]+)?service[ \t]+dhcp$", re.IGNORECASE)
#: ``network <address> [<mask> | /<length>] [secondary]``.
_NETWORK_RE = re.compile(
    r"^network[ \t]+(\d{1,3}(?:\.\d{1,3}){3})"
    r"(?:[ \t]+(\d{1,3}(?:\.\d{1,3}){3})|[ \t]*/(\d{1,2}))?"
    r"([ \t]+secondary)?$",
    re.IGNORECASE,
)
#: ``lease {<days> [<hours> [<minutes>]] | infinite}``.
_LEASE_RE = re.compile(
    r"^lease[ \t]+(?:(\d{1,5})(?:[ \t]+(\d{1,2})(?:[ \t]+(\d{1,2}))?)?|(infinite))$",
    re.IGNORECASE,
)

#: Lease time Cisco calls ``infinite``: DHCP's own "infinity" (RFC 2131).
INFINITE_LEASE = 0xFFFFFFFF
#: The lease a pool has where it states none (Cisco: one day).
DEFAULT_LEASE = 86400
#: The most addresses one ``default-router`` or ``dns-server`` line takes.
_ADDRESSES_A_LINE = 8
#: The most characters of a pool's name a row shows.
_NAME_SHOWN = 40

#: The statements of a pool, by their first word, that the tree has no
#: place for, and what a row of each kind says it stands for.  Each is
#: said by its word alone: an ``option`` holds what a vendor's client is
#: given, a key among it often enough.
_STATEMENTS: dict[str, str] = {
    "option": "a DHCP option",
    "host": "a manual binding of an address to a client",
    "hardware-address": "a manual binding of an address to a client",
    "client-identifier": "a manual binding of an address to a client",
    "client-name": "the name of a client of a manual binding",
    "address": "an address reserved for a client",
    "reserved-only": "a pool that hands out its reserved addresses only",
    "netbios-name-server": "a NetBIOS name server",
    "netbios-node-type": "a NetBIOS node type",
    "bootfile": "a boot file",
    "next-server": "a boot server",
    "import": "options imported from another DHCP server",
    "origin": "a subnet given by another server",
    "subnet": "the size of the subnets of an on-demand pool",
    "class": "a DHCP class",
    "relay": "a relay destination",
    "update": "a DNS or ARP update",
    "utilization": "a mark of the pool's utilization",
    "accounting": "accounting",
    "renew": "a renewal setting",
}

#: The kinds of what a pool states that are said of the pool as a whole,
#: and a line of a pool in a form this parser does not read (``""``).
_POOL_KINDS: dict[str, str] = {
    "": "a line in a form this parser does not read",
    "network secondary": "a secondary subnet of the pool",
    "default-router": "a default router after the pool's first",
    "range": "addresses the pool hands out outside the largest run of them",
    "interface": (
        "a subnet of the pool on more than one interface "
        "(the pool is put on the first)"
    ),
    "vrf": "the VRF of a pool that no interface of the VRF serves",
    "network": "a pool with no network, which hands out no address of a subnet",
    "excluded-address": "a pool whose every address is excluded or taken",
}


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


@dataclass
class PoolLines:
    """What an ``ip dhcp pool`` states, from every stanza of its name (a
    pool entered again is the same pool)."""

    name: str
    network: str = ""
    vrf: str = ""
    routers: list[str] = field(default_factory=list)
    dns_servers: list[str] = field(default_factory=list)
    domain_name: str = ""
    lease_time: int = DEFAULT_LEASE
    #: The kinds of statement not read, in the order they were met.
    unread: dict[str, None] = field(default_factory=dict)


class Pools:
    """The pools of a config, by name, in the order they were named."""

    def __init__(self) -> None:
        self._by_name: dict[str, PoolLines] = {}

    def pool(self, name: str) -> PoolLines:
        """The pool of *name*, made the first time it is named."""
        found = self._by_name.get(name)
        if found is None:
            found = self._by_name[name] = PoolLines(name)
        return found

    def stated(self) -> list[PoolLines]:
        """Every pool, once, in the order it was first named."""
        return list(self._by_name.values())


@dataclass
class Top:
    """The lines of the top of a config that what a pool hands out
    depends on."""

    #: ``service dhcp`` (the default) or ``no service dhcp``: the last
    #: such line is the device's.
    enabled: bool = True
    #: The excluded spans of each VRF (``""``: no VRF), as integers.
    excluded: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    #: ``ip dhcp excluded-address`` lines in a form not read.
    unread_exclusions: int = 0


def _natural_length(address: str) -> int:
    """The prefix length of *address*'s natural (class) mask.

    Raises:
        ValueError: For an address of class D or E.
    """
    first = int(address.split(".", 1)[0])
    if first < 128:
        return 8
    if first < 192:
        return 16
    if first < 224:
        return 24
    raise ValueError(address)


def _read_network(pool: PoolLines, statement: str) -> bool:
    found = _NETWORK_RE.match(statement)
    if not found:
        return False
    address, mask, length, secondary = found.groups()
    try:
        if mask is not None:
            prefix = ipaddress.IPv4Network(f"0.0.0.0/{mask}").prefixlen
        elif length is not None:
            prefix = int(length)
        else:
            prefix = _natural_length(address)
        network = ipaddress.IPv4Network(f"{address}/{prefix}", strict=False)
    except ValueError:
        return False
    if secondary:
        pool.unread.setdefault("network secondary", None)
    else:
        pool.network = str(network)
    return True


def _addresses(statement: str) -> list[str]:
    """The IPv4 addresses after the first word of *statement*; none if
    there are none, too many, or one of them is no address."""
    words = statement.split()[1:]
    if not words or len(words) > _ADDRESSES_A_LINE:
        return []
    try:
        return [str(ipaddress.IPv4Address(word)) for word in words]
    except ValueError:
        return []


def _read_routers(pool: PoolLines, statement: str) -> bool:
    found = _addresses(statement)
    if found:
        pool.routers = found
    return bool(found)


def _read_dns_servers(pool: PoolLines, statement: str) -> bool:
    found = _addresses(statement)
    if found:
        pool.dns_servers = found
    return bool(found)


def _read_domain_name(pool: PoolLines, statement: str) -> bool:
    words = statement.split()
    if len(words) != 2:
        return False
    pool.domain_name = words[1]
    return True


def _read_lease(pool: PoolLines, statement: str) -> bool:
    found = _LEASE_RE.match(statement)
    if not found:
        return False
    days, hours, minutes, infinite = found.groups()
    pool.lease_time = (
        INFINITE_LEASE if infinite
        else int(days) * 86400 + int(hours or 0) * 3600 + int(minutes or 0) * 60
    )
    return True


def _read_vrf(pool: PoolLines, statement: str) -> bool:
    words = statement.split()
    if len(words) != 2:
        return False
    pool.vrf = words[1]
    return True


_READERS: dict[str, Callable[[PoolLines, str], bool]] = {
    "network": _read_network,
    "default-router": _read_routers,
    "dns-server": _read_dns_servers,
    "domain-name": _read_domain_name,
    "lease": _read_lease,
    "vrf": _read_vrf,
}


def read_pool_line(line: str, pool: PoolLines) -> None:
    """Read *line*, a line of *pool*'s stanza, into *pool*.  A statement
    the tree has no place for, or in a form this parser does not read,
    is noted by its kind and nothing of its value."""
    statement = line.strip()
    if not statement or statement.startswith("!"):
        return
    word = statement.split(None, 1)[0].lower()
    reader = _READERS.get(word)
    if reader is not None:
        if reader(pool, statement):
            return
        pool.unread.setdefault("", None)
        return
    pool.unread.setdefault(word if word in _STATEMENTS else "", None)


def _span(found: re.Match[str]) -> tuple[int, int] | None:
    """The excluded span of an ``ip dhcp excluded-address`` line, or
    ``None`` where its addresses are no addresses or out of order."""
    try:
        low = int(ipaddress.IPv4Address(found.group(2)))
        high = int(ipaddress.IPv4Address(found.group(3) or found.group(2)))
    except ValueError:
        return None
    return (low, high) if low <= high else None


def read_top(lines: Iterable[str]) -> Top:
    """The lines of the top of a config (column 0) that a pool depends
    on: the exclusions, and whether the server is on."""
    top = Top()
    for line in ticked(lines):
        if not line or line[0] in " \t":
            continue
        statement = line.strip()
        if _EXCLUDED_HEAD_RE.match(statement):
            found = _EXCLUDED_RE.match(statement)
            span = _span(found) if found else None
            if found is None or span is None:
                top.unread_exclusions += 1
            else:
                top.excluded.setdefault(found.group(1) or "", []).append(span)
            continue
        found = _SERVICE_RE.match(statement)
        if found:
            top.enabled = found.group(1) is None
    return top


def a_top_line(line: str) -> bool:
    """Whether :func:`read_top` reads *line*, a line of the top: an
    ``ip dhcp excluded-address`` line, read or counted in a row of its
    own, or ``[no] service dhcp``."""
    if not line or line[0] in " \t":
        return False
    statement = line.strip()
    return bool(_EXCLUDED_HEAD_RE.match(statement) or _SERVICE_RE.match(statement))


def _merged(spans: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    """*spans* sorted, with spans that overlap or touch made one."""
    merged: list[tuple[int, int]] = []
    for low, high in ticked(sorted(spans)):
        if merged and low <= merged[-1][1] + 1:
            if high > merged[-1][1]:
                merged[-1] = (merged[-1][0], high)
        else:
            merged.append((low, high))
    return merged


def _int(address: str) -> int | None:
    try:
        return int(ipaddress.IPv4Address(address))
    except ValueError:
        return None


def _hosts(network: ipaddress.IPv4Network) -> tuple[int, int]:
    """The first and last address of *network* a client can be given:
    all of it for a /31 or a /32."""
    first, last = int(network.network_address), int(network.broadcast_address)
    return (first, last) if network.prefixlen >= 31 else (first + 1, last - 1)


def _free_runs(first: int, last: int, taken: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """The runs of ``first`` .. ``last`` that no span of *taken* (merged,
    each meeting that span) covers."""
    runs: list[tuple[int, int]] = []
    at = first
    for low, high in ticked(taken):
        if low > at:
            runs.append((at, min(low - 1, last)))
        at = max(at, high + 1)
    if at <= last:
        runs.append((at, last))
    return runs


class _Spans:
    """Merged spans of addresses, by VRF, that can be asked which of
    them meet a network without reading the others."""

    def __init__(self, spans: dict[str, list[tuple[int, int]]]) -> None:
        self._spans = {vrf: _merged(found) for vrf, found in spans.items()}
        self._ends = {vrf: [high for _, high in found] for vrf, found in self._spans.items()}

    def meeting(self, vrf: str, first: int, last: int) -> list[tuple[int, int]]:
        """The spans of *vrf* that meet ``first`` .. ``last``."""
        spans = self._spans.get(vrf, [])
        at = bisect.bisect_left(self._ends.get(vrf, []), first)
        found: list[tuple[int, int]] = []
        while at < len(spans) and spans[at][0] <= last:
            tick()
            found.append(spans[at])
            at += 1
        return found


def _own_addresses(
    interfaces: Sequence[CanonicalInterface], virtual: bool,
) -> dict[str, list[tuple[int, int]]]:
    """The addresses of the device in each VRF: those of its interfaces
    and, where *virtual*, those that answer for a router (an anycast
    gateway, a VRRP or HSRP virtual address)."""
    own: dict[str, list[tuple[int, int]]] = {}
    for iface in ticked(interfaces):
        found = own.setdefault(iface.vrf, [])
        addresses = [a.ip for a in iface.ipv4_addresses]
        if virtual:
            addresses += [a.virtual_gateway_address for a in iface.ipv4_addresses]
            for group in iface.vrrp_groups:
                addresses += list(group.virtual_ips)
        for address in addresses:
            value = _int(address) if address else None
            if value is not None:
                found.append((value, value))
    return own


class _Served:
    """Which interface's subnet each network is, by VRF: an interface
    with an address in the network."""

    def __init__(self, interfaces: Sequence[CanonicalInterface]) -> None:
        entries: dict[str, list[tuple[int, int, str]]] = {}
        for order, iface in enumerate(ticked(interfaces)):
            for address in iface.ipv4_addresses:
                value = _int(address.ip)
                if value is not None:
                    entries.setdefault(iface.vrf, []).append((value, order, iface.name))
        self._entries = {vrf: sorted(found) for vrf, found in entries.items()}
        self._keys = {vrf: [value for value, _, _ in found] for vrf, found in self._entries.items()}

    def on(self, vrf: str, network: ipaddress.IPv4Network) -> list[str]:
        """The interfaces of *vrf* with an address in *network*, each
        once, in the order of the config."""
        first, last = int(network.network_address), int(network.broadcast_address)
        entries = self._entries.get(vrf, [])
        at = bisect.bisect_left(self._keys.get(vrf, []), first)
        found: dict[int, str] = {}
        while at < len(entries) and entries[at][0] <= last:
            tick()
            _, order, name = entries[at]
            found.setdefault(order, name)
            at += 1
        return list(dict.fromkeys(found[order] for order in sorted(found)))


def _shown(name: str) -> str:
    return name if len(name) <= _NAME_SHOWN else name[: _NAME_SHOWN - 1] + "…"


def _row(kind: str, names: Sequence[str]) -> str:
    """The row for the statements of a kind that the pools *names*
    hold and the tree has no place for."""
    head = f"ip dhcp pool {kind}" if kind else "ip dhcp pool"
    what = _STATEMENTS.get(kind) or _POOL_KINDS.get(kind, _POOL_KINDS[""])
    pools = "pool" if len(names) == 1 else "pools"
    return f"{head} (in {pools} {a_few_named(names)}: {what}; not translated)"


def _record(
    pool: PoolLines, taken: _Spans, served: _Served, kinds: list[str],
) -> CanonicalDHCPPool | None:
    """The tree's pool for *pool*, or ``None`` where it hands out no
    address of a subnet; what the tree has no place for is added to
    *kinds*."""
    if not pool.network:
        kinds.append("network")
        return None
    network = ipaddress.IPv4Network(pool.network)
    first, last = _hosts(network)
    routers = [(value, value) for value in map(_int, pool.routers) if value is not None]
    meeting = [
        *taken.meeting(pool.vrf, first, last),
        *((low, high) for low, high in routers if first <= low <= last),
    ]
    runs = _free_runs(first, last, _merged(meeting))
    if not runs:
        kinds.append("excluded-address")
        return None
    if len(runs) > 1:
        kinds.append("range")
    # The largest run, the first of two as large.
    low, high = max(runs, key=lambda run: run[1] - run[0])
    if len(pool.routers) > 1:
        kinds.append("default-router")
    names = served.on(pool.vrf, network)
    if len(names) > 1:
        kinds.append("interface")
    if pool.vrf and not names:
        kinds.append("vrf")
    return CanonicalDHCPPool(
        interface=names[0] if names else "",
        network=pool.network,
        start_ip=str(ipaddress.IPv4Address(low)),
        end_ip=str(ipaddress.IPv4Address(high)),
        gateway=pool.routers[0] if pool.routers else "",
        dns_servers=list(pool.dns_servers),
        lease_time=pool.lease_time,
        domain_name=pool.domain_name,
    )


def pools_of(
    stated: Sequence[PoolLines], top: Top, interfaces: Sequence[CanonicalInterface],
) -> tuple[list[CanonicalDHCPPool], list[str], list[tuple[str, list[str]]]]:
    """The tree's pools for the pools a config states.

    Args:
        stated: The pools, as their stanzas state them.
        top: What the top of the config states of them.
        interfaces: The config's interfaces, as parsed.

    Returns:
        The pools; the rows of what the tree has no place for (one a
        kind, naming a few pools); and the statements left out because
        they are not in force, for
        :func:`netcanon.migration._tier3_detection.left_out_rows`.
    """
    if not top.enabled:
        return [], [], [
            ("disabled", ["ip", "dhcp", "pool", _shown(pool.name)]) for pool in ticked(stated)
        ]
    excluded = {vrf: list(spans) for vrf, spans in top.excluded.items()}
    for vrf, own in _own_addresses(interfaces, virtual=True).items():
        excluded.setdefault(vrf, []).extend(own)
    taken = _Spans(excluded)
    served = _Served(interfaces)
    pools: list[CanonicalDHCPPool] = []
    unread: dict[str, list[str]] = {}
    for pool in ticked(stated):
        kinds = list(pool.unread)
        record = _record(pool, taken, served, kinds)
        if record is not None:
            pools.append(record)
        for kind in kinds:
            unread.setdefault(kind, []).append(_shown(pool.name))
    rows = [_row(kind, names) for kind, names in unread.items()]
    if top.unread_exclusions:
        lines = "line" if top.unread_exclusions == 1 else "lines"
        rows.append(
            f"ip dhcp excluded-address ({top.unread_exclusions} {lines} in a form "
            "this parser does not read, so a pool's range may hold addresses "
            "the source does not hand out; not translated)",
        )
    return pools, rows, []


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


@dataclass
class _Written:
    exclusions: list[str] = field(default_factory=list)
    stanzas: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _lease_line(lease_time: int) -> str | None:
    """The ``lease`` line of a pool, or ``None`` for the default."""
    if not lease_time or lease_time == DEFAULT_LEASE:
        return None
    if lease_time == INFINITE_LEASE:
        return " lease infinite"
    # The full day/hour/minute triple, so that multi-day and sub-hour
    # leases round-trip.  IOS-XE's finest grain is one minute: a lease
    # shorter than that is written as one minute, never ``lease 0 0 0``,
    # which reads back as no lease and then as the default.
    days = lease_time // 86400
    rest = lease_time - days * 86400
    hours = rest // 3600
    minutes = (rest - hours * 3600) // 60
    if days == 0 and hours == 0 and minutes == 0:
        minutes = 1
    return f" lease {days} {hours} {minutes}"


def _exclusion_lines(
    vrf: str, gaps: list[tuple[int, int]], own: _Spans,
) -> list[str]:
    """The ``ip dhcp excluded-address`` lines for *gaps*, less the
    device's own addresses, which the server excludes itself."""
    lead = f"ip dhcp excluded-address vrf {vrf}" if vrf else "ip dhcp excluded-address"
    lines: list[str] = []
    for gap_low, gap_high in gaps:
        for low, high in _free_runs(gap_low, gap_high, own.meeting(vrf, gap_low, gap_high)):
            low_text = ipaddress.IPv4Address(low)
            lines.append(
                f"{lead} {low_text}" if low == high
                else f"{lead} {low_text} {ipaddress.IPv4Address(high)}",
            )
    return lines


def _range_gaps(
    pool: CanonicalDHCPPool, network: ipaddress.IPv4Network,
) -> list[tuple[int, int]] | None:
    """The addresses of *network* a client can be given that lie outside
    *pool*'s range; ``None`` where the range is not inside the network."""
    first, last = _hosts(network)
    start = _int(pool.start_ip) if pool.start_ip else first
    end = _int(pool.end_ip) if pool.end_ip else last
    if start is None or end is None or not first <= start <= end <= last:
        return None
    return [gap for gap in ((first, start - 1), (end + 1, last)) if gap[0] <= gap[1]]


def _bound_here(
    pool: CanonicalDHCPPool, iface: CanonicalInterface | None,
    network: ipaddress.IPv4Network | None,
) -> str | None:
    """Why IOS-XE does not serve *pool* on the interface the source
    serves it on, or ``None`` where it does (or the pool names none)."""
    if not pool.interface or network is None:
        return None
    if iface is None:
        return f"this output has no interface {pool.interface}"
    for address in iface.ipv4_addresses:
        value = _int(address.ip)
        if value is not None and ipaddress.IPv4Address(value) in network:
            return None
    return f"{iface.name} has no address in {network} in this output"


def _write_pool(
    pool: CanonicalDHCPPool, by_name: dict[str, CanonicalInterface], own: _Spans,
    dest_mask: Callable[[str], tuple[str, str]], written: _Written,
) -> None:
    iface = by_name.get(pool.interface.lower()) if pool.interface else None
    vrf = iface.vrf if iface is not None else ""
    try:
        network = ipaddress.IPv4Network(pool.network, strict=False) if pool.network else None
    except ValueError:
        network = None
    label = pool.network or pool.interface or "POOL"
    if not pool.network:
        # A pool hands out the addresses of its network (the
        # chapter above), and the parser makes no pool of one that
        # states none: its options alone would be a pool that hands
        # out nothing.
        written.stanzas.append(
            f"! review: a DHCP pool of the source ({label}) is not written: it "
            "states no network, and an IOS-XE pool hands out the addresses of its network",
        )
        written.warnings.append(
            f"IOS-XE DHCP pool {label}: it is not written, since it states no "
            "network; a review line in the output says so.",
        )
        return
    name = (pool.interface or pool.network).replace("/", "_")
    stanza = [f"ip dhcp pool {name}"]
    if vrf:
        stanza.append(f" vrf {vrf}")
    net, mask = dest_mask(pool.network)
    stanza.append(f" network {net} {mask}")
    why = _bound_here(pool, iface, network)
    if why is not None:
        stanza.append(
            f" ! review: the source serves this pool on {pool.interface}; IOS-XE "
            f"serves a pool on an interface with an address in its network, and {why}",
        )
        written.warnings.append(
            f"IOS-XE DHCP pool {label}: the source serves it on {pool.interface}, "
            f"and {why}, so IOS-XE does not serve it there; a review line in the pool "
            "says so.",
        )
    if pool.start_ip or pool.end_ip:
        gaps = _range_gaps(pool, network) if network is not None else None
        if gaps is None:
            reason = (
                "its network is not an IPv4 network" if network is None
                else f"it is not inside the network {network}"
            )
            stanza.append(
                f" ! review: the range {pool.start_ip or '?'}-{pool.end_ip or '?'} is not "
                f"written: {reason}; IOS-XE hands out every address of the network "
                "that is not excluded",
            )
            written.warnings.append(
                f"IOS-XE DHCP pool {label}: its range is not written ({reason}); "
                "a review line in the pool says so.",
            )
        else:
            lines = _exclusion_lines(vrf, gaps, own)
            if lines and vrf:
                written.exclusions.append(
                    f"! ip dhcp excluded-address vrf {vrf} -- review: check that this "
                    "release takes the vrf form (Cisco's community answers give it for "
                    "IOS XE 17.6 and later; the configuration guide does not)",
                )
            written.exclusions.extend(lines)
    if pool.gateway:
        stanza.append(f" default-router {pool.gateway}")
    if pool.dns_servers:
        # One line: a second ``dns-server`` line replaces the first.
        stanza.append(f" dns-server {' '.join(pool.dns_servers[:_ADDRESSES_A_LINE])}")
        if len(pool.dns_servers) > _ADDRESSES_A_LINE:
            rest = len(pool.dns_servers) - _ADDRESSES_A_LINE
            stanza.append(
                f" ! review: {rest} more DNS servers are not written: a pool takes "
                f"{_ADDRESSES_A_LINE}",
            )
            written.warnings.append(
                f"IOS-XE DHCP pool {label}: {rest} of its DNS servers are not written, "
                f"since a pool takes {_ADDRESSES_A_LINE}; a review line in the pool says so.",
            )
    if pool.domain_name:
        stanza.append(f" domain-name {pool.domain_name}")
    lease = _lease_line(pool.lease_time)
    if lease is not None:
        stanza.append(lease)
    stanza.append("!")
    written.stanzas.extend(stanza)


def render_pools(
    pools: Sequence[CanonicalDHCPPool], interfaces: Sequence[CanonicalInterface],
    dest_mask: Callable[[str], tuple[str, str]],
) -> tuple[list[str], list[str]]:
    """The lines of an IOS-XE output for *pools*, and the job's warnings.

    A pool's range is written as the ``ip dhcp excluded-address`` lines
    on either side of it, before the first pool; the server excludes
    the device's own addresses itself, so none is written for one.  A
    pool on an interface in a VRF states the VRF.  A pool the output
    does not serve on the interface the source serves it on, or whose
    range is not inside its network, has a review line, and a warning
    says so.  A pool that states no network is not written (a pool
    hands out the addresses of its network): a review line stands in
    its place, and a warning says so.

    Args:
        pools: The tree's pools.
        interfaces: Every interface the output holds (the VLAN
            interfaces the renderer makes among them).
        dest_mask: How the renderer writes a network as an address and
            a mask.

    Returns:
        The lines, and one warning for each review line among them.
    """
    by_name: dict[str, CanonicalInterface] = {}
    for iface in ticked(interfaces):
        by_name.setdefault(iface.name.lower(), iface)
    own = _Spans(_own_addresses(interfaces, virtual=False))
    written = _Written()
    for pool in ticked(pools):
        _write_pool(pool, by_name, own, dest_mask, written)
    return [*written.exclusions, *written.stanzas], written.warnings

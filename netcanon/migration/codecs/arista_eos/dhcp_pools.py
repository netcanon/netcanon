"""An EOS DHCP server's IPv4 subnets as the tree's pools, and the
tree's pools as an EOS DHCP server.

Arista, *EOS User Manual*, "DHCP Server" (``eos-dhcp-overview``), and
Arista's own config generator, AVD (``eos_cli_config_gen``: the
``dhcp-servers`` template and the interface templates, which print a
config as the switch prints it):

* The server is ``dhcp server`` (the default VRF) or ``dhcp server vrf
  <name>``, in column 0.  One level in are the server's own settings
  -- ``disabled``, ``lease time ipv4 D days H hours M minutes``, ``dns
  domain name ipv4 <domain>``, ``dns server ipv4 <a> [<b>]``, the same
  for ``ipv6``, TFTP, vendor options and client classes -- and
  ``subnet <prefix>``, whose settings are a level deeper: ``range
  <start> <end>`` (several), ``name``, ``dns server <a> [<b>]``,
  ``lease time D days H hours M minutes`` (AVD; the manual's example
  writes ``lease time ipv4``, and both are read), ``default-gateway``,
  ``reservations`` and ``tftp server``.  An indented ``!`` only
  separates.
* "dhcp Server settings can also be configured per subnet and
  overrides the dhcp Server global mode configurations": a subnet has
  the server's DNS servers and lease where it states none of its own.
* "Configure up to 2 servers per subnet" (DNS), and "Only two servers
  can be configured globally per address family".
* "The range must be within the subnet mask, otherwise the subnet
  becomes disabled"; subnets "must not overlap.  EOS disables
  overlapping subnets"; and ``show dhcp server`` shows a subnet
  disabled for a range that overlaps another and for an address
  reserved more than once.
* An interface takes part with ``dhcp server ipv4`` under it (AVD), and
  ``show dhcp server`` shows an interface "Inactive (Not in default
  VRF)".  Which subnet an interface serves is not stated:
  ``show dhcp server`` shows each subnet's "Direct" and "Relay" state,
  so a subnet is taken to be served directly on the interface with
  ``dhcp server ipv4``, in the server's VRF, that holds an address of
  it (an inference), and a subnet no such interface holds an address
  of to be served to relayed clients only.  Arista shows a DHCPv6
  subnet that several interfaces match not served directly ("Multiple
  interfaces match this subnet"); for IPv4 it does not say.
* No default lease is stated.

The tree holds a pool as ONE run of addresses on ONE interface, with
no name and no VRF.  What it has no place for is a row of the sections
not translated, one a kind, naming a few subnets by their prefix and
never a value; a subnet that is not in force (one of a ``disabled``
server, one EOS disables) is left out and said.  ``ip dhcp pool`` is no
form of EOS's DHCP server as Arista documents it, and is not read as
one: a row says so.

The renderer writes the server that way: a ``dhcp server`` for each VRF
of the output's pools (the VRF of the interface that serves the pool),
a ``subnet`` for each pool, and ``dhcp server ipv4`` under each
interface that serves one.  What it cannot write as the tree has it is
a ``! review:`` line in the server and a warning of the job
(``AristaEOSCodec.render_warnings``), read from the same function.
"""

from __future__ import annotations

import bisect
import ipaddress
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from ...canonical.intent import CanonicalDHCPPool, CanonicalInterface
from ...limits import tick, ticked
from .._dhcp_pools import (
    INFINITE_LEASE,
    OwnAddresses,
    as_int,
    as_text,
    network_of,
    what_it_hands_out,
)
from .._helpers import a_few_named

#: ``dhcp server [vrf <name>]``, a line in column 0: the header of the
#: server's block, which the parser's check for a text with no
#: indentation asks after too.
SERVER_HEADER_RE = re.compile(r"^dhcp[ \t]+server(?:[ \t]+vrf[ \t]+(\S+))?[ \t]*$", re.IGNORECASE)
#: ``ip dhcp pool <name>``, the same.
IP_DHCP_POOL_RE = re.compile(r"^ip[ \t]+dhcp[ \t]+pool[ \t]+(\S+)[ \t]*$", re.IGNORECASE)

#: The lease a subnet is given where neither it nor its server states
#: one: the tree's default (one day).  EOS's own is not established.
DEFAULT_LEASE = 86400
#: The most days a lease of EOS's server takes (AVD's schema: 0-2000).
_MOST_DAYS = 2000
#: The most DNS servers a subnet takes ("up to 2 servers per subnet").
_DNS_A_SUBNET = 2

#: What a row of each kind stands for, said of a subnet.
_SUBNET_KINDS: dict[str, str] = {
    "": "a line in a form this parser does not read",
    "range": "addresses the subnet hands out outside the largest run of them",
    "no range": (
        "a subnet that states no range, from which this parser takes no run "
        "of addresses to hand out"
    ),
    "reservations": "addresses reserved for clients",
    "tftp server": "a TFTP server or boot file",
    "lease time": (
        "a subnet whose server states no lease either, given one day: the "
        "default lease of EOS's DHCP server is not established"
    ),
    "interface": (
        "a subnet that more than one interface with `dhcp server ipv4` holds "
        "an address of (the pool is put on the first; Arista shows such a "
        "DHCPv6 subnet not served directly, and of IPv4 does not say)"
    ),
    "vrf": "the VRF of a subnet that no interface of the VRF serves",
}
#: What a row of each kind stands for, said of a server.
_SERVER_KINDS: dict[str, str] = {
    "": "a line in a form this parser does not read",
    "ipv6": "DHCPv6 (an IPv6 subnet or setting)",
    "tftp server": "a TFTP server or boot file",
    "vendor-option": "a vendor-specific option",
    "client class": "a client class",
}


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


@dataclass
class _Subnet:
    """What one ``subnet`` of a server states."""

    network: ipaddress.IPv4Network
    ranges: list[tuple[int, int]] = field(default_factory=list)
    #: A range that is not an IPv4 run of the subnet: EOS disables it.
    range_outside: bool = False
    dns_servers: list[str] | None = None
    lease: int | None = None
    gateway: str = ""
    reserved: set[str] = field(default_factory=set)
    reserved_twice: bool = False
    unread: list[str] = field(default_factory=list)


@dataclass
class _Server:
    """What one ``dhcp server [vrf <name>]`` states."""

    vrf: str
    disabled: bool = False
    lease: int | None = None
    dns_servers: list[str] | None = None
    domain: str = ""
    subnets: dict[str, _Subnet] = field(default_factory=dict)
    unread: list[str] = field(default_factory=list)


@dataclass
class Read:
    """What a config states of its DHCP server.

    Attributes:
        servers: The servers, by VRF (``""`` for the default), in the
            order of the config; one entered again is the same server.
        serving: The interfaces with ``dhcp server ipv4`` under them,
            by the name their header gives.
        ip_dhcp_pools: The names of the ``ip dhcp pool`` stanzas.
    """

    servers: dict[str, _Server] = field(default_factory=dict)
    serving: set[str] = field(default_factory=set)
    ip_dhcp_pools: list[str] = field(default_factory=list)


def _vrf(name: str) -> str:
    """The VRF *name*, ``""`` for the default."""
    return "" if name.lower() == "default" else name


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def _lease(words: Sequence[str]) -> int | None:
    """The seconds of ``D days H hours M minutes``, or ``None`` for
    another form."""
    if len(words) != 6:
        return None
    days, day_word, hours, hour_word, minutes, minute_word = words
    if (
        not (days.isdigit() and hours.isdigit() and minutes.isdigit())
        or day_word not in ("day", "days")
        or hour_word not in ("hour", "hours")
        or minute_word not in ("minute", "minutes")
        or len(days) > 5 or int(hours) > 23 or int(minutes) > 59
    ):
        return None
    seconds = int(days) * 86400 + int(hours) * 3600 + int(minutes) * 60
    return seconds or None


def _addresses(words: Sequence[str]) -> list[str] | None:
    """*words* where each is an IPv4 address, or ``None``."""
    if not words or any(as_int(word) is None for word in words):
        return None
    return list(words)


def _read_subnet_line(subnet: _Subnet, words: list[str]) -> bool:
    """Read one statement of a subnet into *subnet*.

    Returns:
        Whether the statement holds lines of its own a level deeper
        (``reservations``, or a statement this parser does not read).
    """
    low = [word.lower() for word in words[:3]]
    if low[0] == "range":
        start = as_int(words[1]) if len(words) == 3 else None
        end = as_int(words[2]) if len(words) == 3 else None
        first, last = int(subnet.network.network_address), int(subnet.network.broadcast_address)
        if start is None or end is None:
            subnet.unread.append("")
        elif not first <= start <= end <= last:
            subnet.range_outside = True
        else:
            subnet.ranges.append((start, end))
        return False
    if low[0] == "name":
        # A name "improves readability of the subnet list": the tree has
        # no place for it, and it changes nothing the server does.
        return False
    if low[:2] == ["dns", "server"]:
        rest = words[2:]
        if rest and rest[0].lower() == "ipv4":
            rest = rest[1:]
        servers = _addresses(rest)
        if servers is None:
            subnet.unread.append("")
        else:
            subnet.dns_servers = servers
        return False
    if low[:2] == ["lease", "time"]:
        rest = words[2:]
        if rest and rest[0].lower() == "ipv4":
            rest = rest[1:]
        lease = _lease([word.lower() for word in rest])
        if lease is None:
            subnet.unread.append("")
        else:
            subnet.lease = lease
        return False
    if low[0] == "default-gateway" and len(words) == 2 and as_int(words[1]) is not None:
        subnet.gateway = words[1]
        return False
    if low[0] == "reservations" and len(words) == 1:
        subnet.unread.append("reservations")
        return True
    if low[:2] == ["tftp", "server"]:
        subnet.unread.append("tftp server")
        return False
    subnet.unread.append("")
    return True


def _read_server_line(server: _Server, words: list[str]) -> bool:
    """Read one statement of a server into *server*; returns whether
    it holds lines of its own a level deeper."""
    low = [word.lower() for word in words[:5]]
    if low == ["disabled"]:
        server.disabled = True
        return False
    if low[:2] == ["lease", "time"] and len(low) > 2 and low[2] in ("ipv4", "ipv6"):
        if low[2] == "ipv6":
            server.unread.append("ipv6")
            return False
        lease = _lease([word.lower() for word in words[3:]])
        if lease is None:
            server.unread.append("")
        else:
            server.lease = lease
        return False
    if low[:3] == ["dns", "domain", "name"] and len(words) == 5 and low[3] in ("ipv4", "ipv6"):
        if low[3] == "ipv6":
            server.unread.append("ipv6")
        else:
            server.domain = words[4]
        return False
    if low[:2] == ["dns", "server"] and len(low) > 2 and low[2] in ("ipv4", "ipv6"):
        if low[2] == "ipv6":
            server.unread.append("ipv6")
            return False
        servers = _addresses(words[3:])
        if servers is None:
            server.unread.append("")
        else:
            server.dns_servers = servers
        return False
    if low[:2] == ["tftp", "server"]:
        server.unread.append("tftp server")
        return False
    if low[0] == "vendor-option":
        server.unread.append("vendor-option")
        return True
    if low[:2] == ["client", "class"]:
        server.unread.append("client class")
        return True
    server.unread.append("")
    return True


def _open_subnet(server: _Server, words: list[str]) -> _Subnet | None:
    """The subnet a ``subnet`` line opens, or ``None`` where it is not
    an IPv4 subnet (an IPv6 one, or a form this parser does not read,
    which the server's rows count)."""
    if len(words) != 2:
        server.unread.append("")
        return None
    try:
        network = ipaddress.ip_network(words[1], strict=False)
    except ValueError:
        server.unread.append("")
        return None
    if not isinstance(network, ipaddress.IPv4Network):
        server.unread.append("ipv6")
        return None
    # A subnet entered again is the same subnet.
    return server.subnets.setdefault(str(network), _Subnet(network))


@dataclass
class _Block:
    """Where a line of a ``dhcp server`` block is read."""

    server: _Server
    subnet: _Subnet | None = None
    subnet_depth: int = 0
    #: Lines deeper than this belong to a statement whose lines this
    #: parser does not read one by one.
    skip_deeper_than: int | None = None
    #: Lines deeper than this are a subnet's reservations.
    reservations_deeper_than: int | None = None


def _read_block_line(block: _Block, line: str) -> None:
    depth = _indent(line)
    words = line.split()
    if block.reservations_deeper_than is not None and block.subnet is not None:
        if depth > block.reservations_deeper_than:
            if len(words) == 2 and words[0].lower() == "ipv4-address":
                if words[1] in block.subnet.reserved:
                    block.subnet.reserved_twice = True
                block.subnet.reserved.add(words[1])
            return
        block.reservations_deeper_than = None
    if block.skip_deeper_than is not None:
        if depth > block.skip_deeper_than:
            return
        block.skip_deeper_than = None
    if block.subnet is not None and depth > block.subnet_depth:
        deeper = _read_subnet_line(block.subnet, words)
        if deeper and words[0].lower() == "reservations":
            block.reservations_deeper_than = depth
        elif deeper:
            block.skip_deeper_than = depth
        return
    block.subnet = None
    if words[0].lower() == "subnet":
        block.subnet = _open_subnet(block.server, words)
        block.subnet_depth = depth
        if block.subnet is None:
            block.skip_deeper_than = depth
        return
    if _read_server_line(block.server, words):
        block.skip_deeper_than = depth


def read_dhcp(lines: Sequence[str], interface_header: re.Pattern[str]) -> Read:
    """What *lines* state of the DHCP server.

    Args:
        lines: The config's lines, bodies of text emptied.
        interface_header: The parser's pattern for an ``interface``
            line, whose first group is the name it keys the interface
            by: an interface is found by the same name.

    Returns:
        The servers, the interfaces that serve, and the ``ip dhcp
        pool`` stanzas.
    """
    read = Read()
    block: _Block | None = None
    interface: str | None = None
    for raw_line in ticked(lines):
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if not line.startswith((" ", "\t")):
            # A line in column 0 ends the block it is in, and may open one.
            block = None
            interface = None
            header = interface_header.match(line)
            if header:
                interface = header.group(1)
                continue
            server = SERVER_HEADER_RE.match(line)
            if server:
                vrf = _vrf(server.group(1) or "")
                block = _Block(read.servers.setdefault(vrf, _Server(vrf)))
                continue
            pool = IP_DHCP_POOL_RE.match(line)
            if pool:
                read.ip_dhcp_pools.append(pool.group(1))
            continue
        if stripped.startswith("!"):
            # An indented ``!`` separates; it ends nothing.
            continue
        if block is not None:
            _read_block_line(block, line)
        elif interface is not None and [word.lower() for word in stripped.split()] == [
            "dhcp", "server", "ipv4",
        ]:
            read.serving.add(interface)
    return read


class _Served:
    """Which interfaces that serve DHCP hold an address of each network,
    by VRF."""

    def __init__(self, interfaces: Sequence[CanonicalInterface]) -> None:
        entries: dict[str, list[tuple[int, int, str]]] = {}
        for order, iface in enumerate(ticked(interfaces)):
            for address in iface.ipv4_addresses:
                value = as_int(address.ip) if address.ip else None
                if value is not None:
                    entries.setdefault(_vrf(iface.vrf), []).append((value, order, iface.name))
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
        return [found[order] for order in sorted(found)]


def _overlapping(subnets: Sequence[_Subnet]) -> set[str]:
    """The subnets of one server that overlap another of it: EOS
    disables them.  Prefixes either nest or do not meet, so a sweep in
    address order meets each overlap at the subnet that holds it."""
    order = sorted(
        subnets,
        key=lambda s: (int(s.network.network_address), s.network.prefixlen),
    )
    found: set[str] = set()
    cover: _Subnet | None = None
    for subnet in ticked(order):
        if cover is not None and int(subnet.network.network_address) <= int(
            cover.network.broadcast_address,
        ):
            found.add(str(cover.network))
            found.add(str(subnet.network))
            if subnet.network.broadcast_address <= cover.network.broadcast_address:
                continue
        cover = subnet
    return found


def _runs(ranges: list[tuple[int, int]]) -> list[tuple[int, int]] | None:
    """The runs *ranges* hand out, those that meet end to end joined;
    ``None`` where two of them overlap (EOS disables the subnet)."""
    runs: list[tuple[int, int]] = []
    for low, high in ticked(sorted(ranges)):
        if runs and low <= runs[-1][1]:
            return None
        if runs and low == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], high)
        else:
            runs.append((low, high))
    return runs


def _row(kind: str, what: str, where: str, names: Sequence[str]) -> str:
    head = f"dhcp server {kind}" if kind else "dhcp server"
    return f"{head} (in {where} {a_few_named(names)}: {what}; not translated)"


def _server_label(vrf: str) -> str:
    return f"VRF {vrf}" if vrf else "the default VRF"


def pools_of(
    read: Read, interfaces: Sequence[CanonicalInterface],
) -> tuple[list[CanonicalDHCPPool], list[str], list[tuple[str, list[str]]]]:
    """The tree's pools for the subnets a config's DHCP server states.

    Args:
        read: What the config states (:func:`read_dhcp`).
        interfaces: The config's interfaces, as parsed.

    Returns:
        The pools; the rows of what the tree has no place for (one a
        kind, naming a few subnets or servers); and the statements left
        out because they are not in force, for
        :func:`netcanon.migration._tier3_detection.left_out_rows`.
    """
    served = _Served([iface for iface in ticked(interfaces) if iface.name in read.serving])
    pools: list[CanonicalDHCPPool] = []
    subnet_rows: dict[str, list[str]] = {}
    server_rows: dict[str, list[str]] = {}
    left_out: list[tuple[str, list[str]]] = []
    for server in ticked(read.servers.values()):
        path = ["dhcp", "server", *(["vrf", server.vrf] if server.vrf else [])]
        if server.disabled:
            left_out.extend(
                ("disabled", [*path, "subnet", prefix]) for prefix in ticked(server.subnets)
            )
            if not server.subnets:
                left_out.append(("disabled", path))
            continue
        for kind in dict.fromkeys(server.unread):
            server_rows.setdefault(kind, []).append(_server_label(server.vrf))
        overlapping = _overlapping(list(server.subnets.values()))
        for prefix, subnet in ticked(server.subnets.items()):
            runs = _runs(subnet.ranges)
            if (
                prefix in overlapping or subnet.range_outside or runs is None
                or subnet.reserved_twice
            ):
                left_out.append(("disabled-subnet", [*path, "subnet", prefix]))
                continue
            kinds = list(subnet.unread)
            lease = subnet.lease if subnet.lease is not None else server.lease
            if lease is None:
                kinds.append("lease time")
            names = served.on(server.vrf, subnet.network)
            if len(names) > 1:
                kinds.append("interface")
            if server.vrf and not names:
                kinds.append("vrf")
            if not runs:
                kinds.append("no range")
            else:
                if len(runs) > 1:
                    kinds.append("range")
                # The largest run, the first of two as large.
                low, high = max(runs, key=lambda run: (run[1] - run[0], -run[0]))
                dns = subnet.dns_servers if subnet.dns_servers is not None else server.dns_servers
                pools.append(CanonicalDHCPPool(
                    interface=names[0] if names else "",
                    network=prefix,
                    start_ip=as_text(low),
                    end_ip=as_text(high),
                    gateway=subnet.gateway,
                    dns_servers=list(dns or []),
                    lease_time=lease if lease is not None else DEFAULT_LEASE,
                    domain_name=server.domain,
                ))
            # Two servers can hold one prefix: a VRF's subnet is named
            # with its VRF.
            named = f"{prefix} of VRF {server.vrf}" if server.vrf else prefix
            for kind in dict.fromkeys(kinds):
                subnet_rows.setdefault(kind, []).append(named)
    rows = [
        *(
            _row(f"subnet {kind}" if kind else "subnet", _SUBNET_KINDS[kind],
                 "subnet" if len(names) == 1 else "subnets", names)
            for kind, names in subnet_rows.items()
        ),
        *(
            _row(kind, _SERVER_KINDS[kind],
                 "the server of" if len(names) == 1 else "the servers of", names)
            for kind, names in server_rows.items()
        ),
    ]
    if read.ip_dhcp_pools:
        pools_word = "pool" if len(read.ip_dhcp_pools) == 1 else "pools"
        rows.append(
            f"ip dhcp pool (in {pools_word} {a_few_named(read.ip_dhcp_pools)}: no form of "
            "EOS's DHCP server as Arista documents it, whose subnets are under "
            "`dhcp server`; not translated)",
        )
    return pools, rows, left_out


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


@dataclass
class Rendered:
    """An EOS output's DHCP server.

    Attributes:
        lines: The ``dhcp server`` blocks.
        serving: The interfaces that take ``dhcp server ipv4``, by
            their names in lower case.
        warnings: One for each review line among *lines*.
    """

    lines: list[str] = field(default_factory=list)
    serving: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)


def _label(pool: CanonicalDHCPPool) -> str:
    return pool.network or pool.interface or "with no network"


def _lease_words(lease_time: int) -> str | None:
    """``D days H hours M minutes`` for *lease_time*, or ``None`` where
    EOS takes no such lease (one that does not end, or of more days
    than it takes)."""
    if lease_time == INFINITE_LEASE:
        return None
    # No lease is the tree's default, as an IOS-XE output writes it.
    days, rest = divmod(lease_time or DEFAULT_LEASE, 86400)
    if days > _MOST_DAYS:
        return None
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days == 0 and hours == 0 and minutes == 0:
        # EOS's finest grain is a minute: a shorter lease is one minute,
        # never ``0 days 0 hours 0 minutes``.
        minutes = 1
    return f"{days} days {hours} hours {minutes} minutes"


#: The mask of each prefix length, 0 to 32.
_MASKS = tuple(((1 << 32) - 1) ^ ((1 << (32 - length)) - 1) for length in range(33))


class _Written:
    """The networks written in one server, so that one that meets
    another is found without reading the rest.  Two prefixes meet only
    where one holds the other, so a network meets a written one where
    one of its own prefixes is written, or where it is a prefix of a
    written one: at most 33 lookups either way."""

    def __init__(self) -> None:
        self._written: set[tuple[int, int]] = set()
        self._held: set[tuple[int, int]] = set()

    def meets(self, network: ipaddress.IPv4Network) -> bool:
        value, length = int(network.network_address), network.prefixlen
        if (value, length) in self._held:
            return True
        return any(
            (value & mask, shorter) in self._written
            for shorter, mask in enumerate(_MASKS[: length + 1])
        )

    def add(self, network: ipaddress.IPv4Network) -> None:
        value, length = int(network.network_address), network.prefixlen
        self._written.add((value, length))
        self._held.update(
            (value & mask, shorter) for shorter, mask in enumerate(_MASKS[: length + 1])
        )


class _Named:
    """The output's interfaces by name, for finding the one a pool is
    served on.  A translation can put two source interfaces under one
    name (a job that is then ``partial`` for it), and the output writes
    both under that name: a pool is on the record of the name that holds
    an address of its network, and on the first of the name where none
    does.  The addresses of each name are kept sorted, so that a pool
    is looked up without reading every record of its name."""

    def __init__(self, interfaces: Sequence[CanonicalInterface]) -> None:
        self._first: dict[str, CanonicalInterface] = {}
        self._held: dict[str, list[tuple[int, int]]] = {}
        self._records: list[CanonicalInterface] = []
        for iface in ticked(interfaces):
            name = iface.name.lower()
            self._first.setdefault(name, iface)
            for address in iface.ipv4_addresses:
                value = as_int(address.ip) if address.ip else None
                if value is not None:
                    self._held.setdefault(name, []).append((value, len(self._records)))
            self._records.append(iface)
        for held in self._held.values():
            held.sort()

    def of(self, pool: CanonicalDHCPPool) -> CanonicalInterface | None:
        """The record *pool* is served on, or ``None`` where the output
        has no interface of its name."""
        name = pool.interface.lower()
        first = self._first.get(name)
        network = network_of(pool)
        held = self._held.get(name)
        if first is None or network is None or not held:
            return first
        at = bisect.bisect_left(held, (int(network.network_address), -1))
        if at < len(held) and held[at][0] <= int(network.broadcast_address):
            return self._records[held[at][1]]
        return first


def _bound_here(
    pool: CanonicalDHCPPool, iface: CanonicalInterface | None,
    network: ipaddress.IPv4Network,
) -> str | None:
    """Why EOS does not serve *pool* directly on the interface the
    source serves it on, or ``None`` where it does."""
    if iface is None:
        return f"this output has no interface {pool.interface}"
    for address in iface.ipv4_addresses:
        value = as_int(address.ip) if address.ip else None
        if value is not None and ipaddress.IPv4Address(value) in network:
            return None
    return f"{iface.name} has no address in {network} in this output"


def _review(rendered: Rendered, depth: str, pool: CanonicalDHCPPool, line: str, warning: str) -> None:
    rendered.lines.append(f"{depth}! review: {line}")
    rendered.warnings.append(
        f"EOS DHCP pool {_label(pool)}: {warning}; a review line in the output says so.",
    )


def _write_range(
    rendered: Rendered, pool: CanonicalDHCPPool, network: ipaddress.IPv4Network,
    own: OwnAddresses,
) -> None:
    handed = what_it_hands_out(pool, own)
    if handed is None:
        start, end = as_int(pool.start_ip), as_int(pool.end_ip)
        if start is not None and end is not None and (
            int(network.network_address) <= start <= end <= int(network.broadcast_address)
        ):
            rendered.lines += ["      !", f"      range {pool.start_ip} {pool.end_ip}"]
            return
        _review(
            rendered, "      ", pool,
            f"the range {pool.start_ip}-{pool.end_ip} is not written: it is not inside "
            f"the subnet {network}, and EOS disables a subnet whose range is outside it",
            "its range is not written, since it is not inside its network",
        )
        return
    if isinstance(handed, str):
        _review(
            rendered, "      ", pool,
            f"no range is written for this subnet: {handed}",
            f"no range is written for it ({handed})",
        )
        return
    _review(
        rendered, "      ", pool,
        f"the source states {handed.stated} for this pool, which hands out its "
        f"network's addresses; written as {handed.span}, less this output's own addresses",
        f"the source states {handed.stated} for it; it is written as {handed.span}, "
        "less this output's own addresses",
    )
    for low, high in ticked(handed.free):
        rendered.lines += ["      !", f"      range {as_text(low)} {as_text(high)}"]


def _write_subnet(
    rendered: Rendered, pool: CanonicalDHCPPool, network: ipaddress.IPv4Network,
    iface: CanonicalInterface | None, own: OwnAddresses, domain_written: bool,
) -> None:
    rendered.lines += ["   !", f"   subnet {network}"]
    _write_range(rendered, pool, network, own)
    if pool.dns_servers:
        rendered.lines.append(f"      dns server {' '.join(pool.dns_servers[:_DNS_A_SUBNET])}")
        if len(pool.dns_servers) > _DNS_A_SUBNET:
            _review(
                rendered, "      ", pool,
                f"the DNS servers after the first {_DNS_A_SUBNET} are not written: a "
                f"subnet takes {_DNS_A_SUBNET}",
                f"its DNS servers after the first {_DNS_A_SUBNET} are not written, since "
                f"a subnet takes {_DNS_A_SUBNET}",
            )
    lease = _lease_words(pool.lease_time)
    if lease is not None:
        rendered.lines.append(f"      lease time {lease}")
    else:
        why = (
            "does not end in the source, and Arista states no lease that does not end"
            if pool.lease_time == INFINITE_LEASE
            else f"is longer than the {_MOST_DAYS} days EOS takes"
        )
        _review(
            rendered, "      ", pool,
            f"the lease of this subnet {why}: none is written",
            f"its lease {why}, so none is written",
        )
    if pool.gateway:
        rendered.lines.append(f"      default-gateway {pool.gateway}")
    if pool.domain_name and not domain_written:
        _review(
            rendered, "      ", pool,
            f"the domain {pool.domain_name} is not written: EOS states a domain for "
            "its whole server, whose subnets do not all have this one",
            "its domain is not written, since EOS states one for the whole server "
            "and its other subnets do not all have it",
        )
    if pool.interface:
        why = _bound_here(pool, iface, network)
        if why is None and iface is not None:
            rendered.serving.add(iface.name.lower())
        elif why is not None:
            _review(
                rendered, "      ", pool,
                f"the source serves this subnet on {pool.interface}; EOS serves a subnet "
                "on an interface with `dhcp server ipv4` that holds an address of it, "
                f"and {why}",
                f"the source serves it on {pool.interface}, and {why}, so EOS does not "
                "serve it there",
            )


def render_pools(
    pools: Sequence[CanonicalDHCPPool], interfaces: Sequence[CanonicalInterface],
) -> Rendered:
    """The ``dhcp server`` blocks of an EOS output for *pools*, which
    interfaces take ``dhcp server ipv4``, and the job's warnings.

    A pool is a ``subnet`` of the server of its interface's VRF (the
    default VRF for a pool that names none); a pool that states no
    whole range is written as the hosts of its network less the
    output's own addresses (:func:`.._dhcp_pools.what_it_hands_out`),
    in as many ranges as that takes.  A domain is written for the
    server where every subnet written in it has that one.  A pool with
    no network, or whose network meets one written before it in the
    same server (EOS disables both), is not written.

    Args:
        pools: The tree's pools.
        interfaces: Every interface the output holds (the VLAN
            interfaces the renderer makes among them).

    Returns:
        The lines, the interfaces that serve, and a warning for each
        review line.
    """
    named = _Named(interfaces)
    own = OwnAddresses(interfaces)
    servers: dict[str, list[tuple[CanonicalDHCPPool, CanonicalInterface | None]]] = {}
    for pool in ticked(pools):
        iface = named.of(pool) if pool.interface else None
        servers.setdefault(_vrf(iface.vrf) if iface is not None else "", []).append((pool, iface))
    rendered = Rendered()
    for vrf, members in ticked(servers.items()):
        rendered.lines += ["!", f"dhcp server vrf {vrf}" if vrf else "dhcp server"]
        written = _Written()
        subnets: list[tuple[CanonicalDHCPPool, ipaddress.IPv4Network, CanonicalInterface | None]] = []
        for pool, iface in ticked(members):
            network = network_of(pool)
            if network is None:
                _review(
                    rendered, "   ", pool,
                    f"a DHCP pool of the source ({_label(pool)}) is not written: it "
                    "states no IPv4 network, and EOS's DHCP server serves a subnet",
                    "it is not written, since it states no IPv4 network",
                )
                continue
            if written.meets(network):
                _review(
                    rendered, "   ", pool,
                    f"a DHCP pool of the source ({network}) is not written: its network "
                    "meets one written above, and EOS disables subnets that overlap",
                    "it is not written, since its network meets one written before it "
                    "and EOS disables subnets that overlap",
                )
                continue
            written.add(network)
            subnets.append((pool, network, iface))
        domains = {pool.domain_name for pool, _, _ in subnets}
        domain = next(iter(domains)) if len(domains) == 1 else ""
        if domain:
            rendered.lines.append(f"   dns domain name ipv4 {domain}")
        for pool, network, iface in ticked(subnets):
            _write_subnet(rendered, pool, network, iface, own, bool(domain))
    if rendered.lines:
        rendered.lines.append("!")
    return rendered

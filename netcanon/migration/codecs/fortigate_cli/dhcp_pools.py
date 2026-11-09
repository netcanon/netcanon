"""A FortiOS DHCP server as it hands addresses out.

Fortinet, *FortiOS CLI Reference*, ``config system dhcp server`` (6.2,
7.0, 7.4), and the *Administration Guide*, "DHCP servers and relays":

* ``config ip-range`` holds one range or more -- the guide's own
  example states two, one on either side of the default gateway -- and
  ``config exclude-range`` blocks "a range of addresses that will not
  be included in the available addresses".
* ``lease-time``: "Lease time in seconds, 0 means unlimited", 604800
  where it is not stated.  A range's own ``lease-time`` of 0 is the
  server's.
* ``dns-service``: ``local`` -- "IP address of the interface the DHCP
  server is added to becomes the client's DNS server IP address";
  ``default`` -- "Clients are assigned the FortiGate's configured DNS
  servers", which ``config system dns`` does not print where one is
  the factory's own; ``specify``, where it is not stated -- the servers of
  ``dns-server1`` to ``dns-server3`` (and ``dns-server4`` from 7.0,
  which the renderer writes as well).
* ``status disable``: "Do not use this DHCP server configuration."
* An address the CLI does not set is printed ``0.0.0.0``: a server
  states no DNS server, gateway or netmask that way.  What a client is
  given as its gateway where the server states ``0.0.0.0`` is not
  established: the guide's GUI offers "Same as Interface IP", and no
  page says how the CLI keeps it.

The tree holds a pool as ONE run of addresses.  So the parser reads
what the server hands out -- every range, less every excluded range --
and keeps the largest run, the lower of two as large; ``0.0.0.0`` is
never an address a client is given; and the pool's network is the
subnet of its netmask around the run.  What the tree has no place for
is a row of the sections not translated, one a kind, naming a few
pools by their ``edit`` and never a value.  A pool that is not in
force is left out and said (``disabled``).  A pool that hands out no
address from a range -- none is stated, every one is excluded, or it
assigns addresses by user group -- is not translated, since a target
given a pool with no range hands out its whole network.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable, Mapping, Sequence
from typing import TYPE_CHECKING

from ...canonical.intent import CanonicalDHCPPool, CanonicalInterface
from ...limits import tick, ticked
from .._helpers import a_few_named

if TYPE_CHECKING:
    from .parse import _ConfigBlock, _EditBlock

#: The lease FortiOS gives a pool that states none.
DEFAULT_LEASE = 604800
#: The tree's lease for one that does not end (DHCP's "infinity", RFC
#: 2131), which FortiOS writes ``lease-time 0``.
INFINITE_LEASE = 0xFFFFFFFF
#: The servers ``dns-service specify`` hands out, in order.
_DNS_KEYS = ("dns-server1", "dns-server2", "dns-server3", "dns-server4")
_NTP_KEYS = ("ntp-server1", "ntp-server2", "ntp-server3")
_WIFI_KEYS = ("wifi-ac1", "wifi-ac2", "wifi-ac3")
#: The most characters of an ``edit`` or a word a row shows.
_SHOWN = 40

#: What the tree has no place for, by kind: the words a row names it
#: by, what it stands for, and whether the pool is left out with it.
_KINDS: dict[str, tuple[str, str, bool]] = {
    "range": (
        "config ip-range", "addresses the pool hands out outside the largest run of them", False,
    ),
    "range form": ("config ip-range", "a range in a form this parser does not read", False),
    "exclude form": (
        "config exclude-range",
        "an excluded range in a form this parser does not read, so the pool's "
        "range may hold addresses the source does not hand out",
        False,
    ),
    "no range": (
        "config ip-range",
        "a pool that hands out no address from a range: none is stated, or every one is excluded",
        True,
    ),
    "usrgrp": (
        "set ip-mode usrgrp", "a pool that assigns addresses by user group, not from a range", True,
    ),
    "netmask": ("set netmask", "a pool that states no netmask, so its network is not known", False),
    "gateway": (
        "set default-gateway",
        "a pool that states no default gateway (0.0.0.0), so what its clients "
        "are given as one is not established",
        False,
    ),
    "dns local": (
        "set dns-service local",
        "the DNS server of a pool that gives its clients the address of an "
        "interface the config states none for",
        False,
    ),
    "dns default": (
        "set dns-service default",
        "the DNS servers of a pool that gives its clients the FortiGate's own, "
        "where the config does not state both (a FortiGate does not print a "
        "DNS server it has by default)",
        False,
    ),
    "vci-match": (
        "set vci-match enable", "a pool or range served only to clients of a vendor class", False,
    ),
    "uci-match": (
        "set uci-match enable", "a pool or range served only to clients of a user class", False,
    ),
    "range lease": ("config ip-range set lease-time", "a lease time of a range of its own", False),
    "reserved-address": (
        "config reserved-address", "an address reserved for a client, or a client the pool refuses",
        False,
    ),
    "options": ("config options", "a DHCP option", False),
    "ntp": ("set ntp-service", "an NTP server the pool hands out", False),
    "wins": ("set wins-server", "a NetBIOS name server", False),
    "boot": ("set next-server, filename or tftp-server", "a boot server or a boot file", False),
    "timezone": ("set timezone-option", "a time zone the pool hands out", False),
    "wifi-ac": ("set wifi-ac-service", "a wireless controller the pool hands out", False),
    "mac-acl": (
        "set mac-acl-default-action block",
        "a pool that refuses a client it reserves no address for",
        False,
    ),
    "ddns": ("set ddns-update enable", "a DNS update", False),
    "fortiipam": (
        "set dhcp-settings-from-fortiipam enable",
        "settings the pool takes from FortiIPAM, which the config does not state",
        False,
    ),
    "relay": ("set relay-agent", "a pool for the clients of one relay", False),
    "shared": ("set shared-subnet enable", "a pool on a subnet shared with another", False),
    "ipsec": ("set server-type ipsec", "a pool served over IPsec", False),
}

#: ``set <key> <keyword>`` that the tree has no place for, as the kind.
_SWITCHES = (
    ("mac-acl-default-action", "block", "mac-acl"),
    ("ddns-update", "enable", "ddns"),
    ("dhcp-settings-from-fortiipam", "enable", "fortiipam"),
    ("shared-subnet", "enable", "shared"),
    ("vci-match", "enable", "vci-match"),
    ("uci-match", "enable", "uci-match"),
    ("server-type", "ipsec", "ipsec"),
)

#: The settings of a pool this module reads.
_READ = frozenset({
    "interface", "default-gateway", "netmask", "dns-service", *_DNS_KEYS,
    "domain", "lease-time", "status", "ip-mode", "server-type",
})
#: The settings a row is made from where their value says so.
_RAISE_A_ROW = frozenset({
    "ntp-service", *_NTP_KEYS, "wins-server1", "wins-server2", "next-server",
    "filename", "tftp-server", "timezone-option", "wifi-ac-service", *_WIFI_KEYS,
    "relay-agent", *(key for key, _value, _kind in _SWITCHES),
})
#: The settings that change nothing a client is given, or nothing
#: beside a setting above that a row is made from: a time a lease or an
#: address is held, a FortiClient or FortiIPAM state, the strings a
#: class match takes, the time zone a ``timezone-option`` names, the
#: server and key of a DNS update.
_NOTHING_TO_TRANSLATE = frozenset({
    "auto-configuration", "conflicted-ip-timeout", "forticlient-on-net-status",
    "ipsec-lease-hold", "auto-managed-status", "vci-string", "uci-string",
    "timezone", "ddns-update-override", "ddns-server-ip", "ddns-zone",
    "ddns-auth", "ddns-keyname", "ddns-key", "ddns-ttl",
})
_KNOWN = _READ | _RAISE_A_ROW | _NOTHING_TO_TRANSLATE
#: The settings of an ``ip-range`` or ``exclude-range`` entry.
_RANGE_KEYS = frozenset({
    "id", "start-ip", "end-ip", "lease-time", "vci-match", "vci-string", "uci-match", "uci-string",
})
#: The tables of a pool, beside its ranges, that a row is made from.
_TABLES = ("reserved-address", "options")


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------


def _word(settings: Mapping[str, list[str]], key: str) -> str:
    """The first word of *key*, in lower case; ``""`` where none."""
    tokens = settings.get(key)
    return tokens[0].lower() if tokens else ""


def _stated(settings: Mapping[str, list[str]], key: str) -> bool:
    """Whether *key* states something: a word that is not empty and
    not FortiOS's unset address."""
    tokens = settings.get(key)
    return bool(tokens) and tokens[0] not in ("", "0.0.0.0")


def _address(settings: Mapping[str, list[str]], key: str) -> str | None:
    """The address *key* states; ``""`` where it states none (no line,
    or ``0.0.0.0``), and ``None`` where its value is no address."""
    if not _stated(settings, key):
        return ""
    try:
        return str(ipaddress.IPv4Address(settings[key][0]))
    except ValueError:
        return None


def _shown(word: str) -> str:
    """*word* as a row shows it: its first characters, on one line."""
    word = " ".join(word.split())
    return word if len(word) <= _SHOWN else word[: _SHOWN - 1] + "…"


# ---------------------------------------------------------------------------
# Ranges
# ---------------------------------------------------------------------------


def _span(settings: Mapping[str, list[str]]) -> tuple[int, int] | None:
    """The addresses of an ``ip-range`` or ``exclude-range`` entry, or
    ``None`` where its ends are missing, no addresses, or out of order."""
    start, end = _address(settings, "start-ip"), _address(settings, "end-ip")
    if not start or not end:
        return None
    low, high = int(ipaddress.IPv4Address(start)), int(ipaddress.IPv4Address(end))
    return (low, high) if low <= high else None


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


def _runs(ranges: list[tuple[int, int]], excluded: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """The runs of the merged *ranges* that no span of the merged
    *excluded* covers.  One walk over both: an excluded span is met
    again only by the next range it may reach into."""
    runs: list[tuple[int, int]] = []
    at_excluded = 0
    for low, high in ticked(ranges):
        while at_excluded < len(excluded) and excluded[at_excluded][1] < low:
            tick()
            at_excluded += 1
        at = low
        meeting = at_excluded
        while meeting < len(excluded) and excluded[meeting][0] <= high:
            tick()
            if excluded[meeting][0] > at:
                runs.append((at, excluded[meeting][0] - 1))
            at = max(at, excluded[meeting][1] + 1)
            meeting += 1
        if at <= high:
            runs.append((at, high))
    return runs


def _note_range_entry(
    settings: Mapping[str, list[str]], kinds: dict[str, None], unread: dict[str, None],
) -> None:
    """What an entry of a range table states beside its ends."""
    if _word(settings, "vci-match") == "enable":
        kinds["vci-match"] = None
    if _word(settings, "uci-match") == "enable":
        kinds["uci-match"] = None
    if _stated(settings, "lease-time") and settings["lease-time"][0] != "0":
        kinds["range lease"] = None
    for key in ticked(settings):
        if key not in _RANGE_KEYS:
            unread[_shown(key)] = None


def _ranges(
    sub_blocks: Sequence[_ConfigBlock],
    kinds: dict[str, None],
    unread: dict[str, None],
    tables: dict[str, None],
) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """The ranges and the excluded ranges of a pool, as integers; what
    its other tables state is noted."""
    ranges: list[tuple[int, int]] = []
    excluded: list[tuple[int, int]] = []
    for sub in ticked(sub_blocks):
        if sub.config_path in ("ip-range", "exclude-range"):
            into = ranges if sub.config_path == "ip-range" else excluded
            for entry in ticked(sub.edits):
                span = _span(entry.settings)
                if span is None:
                    kinds["range form" if into is ranges else "exclude form"] = None
                    continue
                into.append(span)
                _note_range_entry(entry.settings, kinds, unread)
        elif sub.config_path in _TABLES:
            if sub.edits:
                kinds[sub.config_path] = None
        else:
            tables[_shown(sub.config_path)] = None
    return ranges, excluded


# ---------------------------------------------------------------------------
# A pool
# ---------------------------------------------------------------------------


def _note_settings(
    settings: Mapping[str, list[str]], kinds: dict[str, None], unread: dict[str, None],
) -> None:
    """What a pool's settings hand out that the tree has no place for,
    and the settings this module does not know."""
    ntp = _word(settings, "ntp-service")
    if ntp in ("local", "default") or (
        ntp in ("", "specify") and any(_stated(settings, key) for key in _NTP_KEYS)
    ):
        kinds["ntp"] = None
    if _stated(settings, "wins-server1") or _stated(settings, "wins-server2"):
        kinds["wins"] = None
    if any(_stated(settings, key) for key in ("next-server", "filename", "tftp-server")):
        kinds["boot"] = None
    if _word(settings, "timezone-option") not in ("", "disable"):
        kinds["timezone"] = None
    wifi = _word(settings, "wifi-ac-service")
    if wifi in ("local", "default") or (
        wifi in ("", "specify") and any(_stated(settings, key) for key in _WIFI_KEYS)
    ):
        kinds["wifi-ac"] = None
    if _stated(settings, "relay-agent"):
        kinds["relay"] = None
    for key, value, kind in _SWITCHES:
        if _word(settings, key) == value:
            kinds[kind] = None
    for key in ticked(settings):
        if key not in _KNOWN:
            unread[_shown(key)] = None


def _network(
    settings: Mapping[str, list[str]], first: int, kinds: dict[str, None], unread: dict[str, None],
) -> str:
    """The subnet the pool's netmask makes around its first address."""
    mask = _address(settings, "netmask")
    if mask == "":
        kinds["netmask"] = None
        return ""
    try:
        if mask is None:
            raise ValueError(mask)
        prefix = ipaddress.IPv4Network(f"0.0.0.0/{mask}").prefixlen
    except ValueError:
        unread["netmask"] = None
        return ""
    return str(ipaddress.IPv4Network(f"{ipaddress.IPv4Address(first)}/{prefix}", strict=False))


def _dns_servers(
    settings: Mapping[str, list[str]],
    own: str,
    system_dns: tuple[list[str], bool],
    kinds: dict[str, None],
    unread: dict[str, None],
) -> list[str]:
    """The DNS servers the pool gives its clients; *own* is the address
    of the interface it serves, *system_dns* the FortiGate's own and
    whether the config states both of them."""
    service = _word(settings, "dns-service") or "specify"
    if service == "local":
        if not own:
            kinds["dns local"] = None
        return [own] if own else []
    if service == "default":
        servers, both_stated = system_dns
        if not both_stated:
            kinds["dns default"] = None
        return list(servers)
    if service != "specify":
        unread["dns-service"] = None
        return []
    servers: list[str] = []
    for key in _DNS_KEYS:
        found = _address(settings, key)
        if found is None:
            unread[key] = None
        elif found:
            servers.append(found)
    return servers


def _lease(settings: Mapping[str, list[str]], unread: dict[str, None]) -> int:
    """The pool's lease, in seconds."""
    if "lease-time" not in settings:
        return DEFAULT_LEASE
    word = _word(settings, "lease-time")
    if not word.isdecimal() or not word.isascii():
        unread["lease-time"] = None
        return DEFAULT_LEASE
    return int(word) or INFINITE_LEASE


def _gateway(
    settings: Mapping[str, list[str]], kinds: dict[str, None], unread: dict[str, None],
) -> str:
    found = _address(settings, "default-gateway")
    if found is None:
        unread["default-gateway"] = None
        return ""
    if not found:
        kinds["gateway"] = None
    return found


def _pool(
    edit: _EditBlock,
    addresses: Mapping[str, str],
    system_dns: tuple[list[str], bool],
    kinds: dict[str, None],
    unread: dict[str, None],
    tables: dict[str, None],
) -> CanonicalDHCPPool | None:
    """The tree's pool for the ``edit`` *edit*, or ``None`` where it
    hands out no address from a range; what the tree has no place for
    is added to *kinds*, *unread* and *tables*."""
    settings = edit.settings
    _note_settings(settings, kinds, unread)
    ranges, excluded = _ranges(edit.sub_blocks, kinds, unread, tables)
    mode = _word(settings, "ip-mode")
    if mode == "usrgrp":
        kinds["usrgrp"] = None
        return None
    if mode not in ("", "range"):
        unread["ip-mode"] = None
    runs = _runs(_merged(ranges), _merged(excluded))
    if not runs:
        kinds["no range"] = None
        return None
    if len(runs) > 1:
        kinds["range"] = None
    # The largest run; of two as large, the one of the lower addresses.
    low, high = max(runs, key=lambda run: run[1] - run[0])
    interface = settings["interface"][0] if settings.get("interface") else ""
    return CanonicalDHCPPool(
        interface=interface,
        network=_network(settings, low, kinds, unread),
        start_ip=str(ipaddress.IPv4Address(low)),
        end_ip=str(ipaddress.IPv4Address(high)),
        gateway=_gateway(settings, kinds, unread),
        dns_servers=_dns_servers(settings, addresses.get(interface, ""), system_dns, kinds, unread),
        lease_time=_lease(settings, unread),
        domain_name=settings["domain"][0] if settings.get("domain") else "",
    )


# ---------------------------------------------------------------------------
# Every pool
# ---------------------------------------------------------------------------


def _system_dns(blocks: Sequence[_ConfigBlock]) -> tuple[list[str], bool]:
    """The DNS servers ``config system dns`` states, the last of each,
    and whether it has a line for both ``primary`` and ``secondary``
    (``0.0.0.0`` states that there is none)."""
    found: dict[str, str] = {}
    for block in ticked(blocks):
        if block.config_path != "system dns":
            continue
        for key in ("primary", "secondary"):
            if key in block.settings:
                found[key] = _address(block.settings, key) or ""
    servers = [found[key] for key in ("primary", "secondary") if found.get(key)]
    return servers, len(found) == 2


def _first_addresses(interfaces: Sequence[CanonicalInterface]) -> dict[str, str]:
    """The first IPv4 address of each interface, by name."""
    addresses: dict[str, str] = {}
    for iface in ticked(interfaces):
        if iface.ipv4_addresses:
            addresses.setdefault(iface.name, iface.ipv4_addresses[0].ip)
    return addresses


def _row(kind: str, edits: Sequence[str]) -> str:
    head, what, drops = _KINDS[kind]
    rest = "so the pool is not translated" if drops else "not translated"
    return f"config system dhcp server edit {a_few_named(edits)}: {head} -- {what}; {rest}"


def pools_of(
    blocks: Sequence[_ConfigBlock], interfaces: Sequence[CanonicalInterface],
) -> tuple[list[CanonicalDHCPPool], list[str], list[tuple[str, list[str]]]]:
    """The tree's pools for the ``config system dhcp server`` blocks.

    Args:
        blocks: Every block of the config.
        interfaces: The config's interfaces, as parsed: a pool of
            ``dns-service local`` gives its clients the address of its
            own.

    Returns:
        The pools; the rows of what the tree has no place for (one a
        kind, naming a few pools); and the pools left out because they
        are not in force, for
        :func:`netcanon.migration._tier3_detection.left_out_rows`.
    """
    addresses = _first_addresses(interfaces)
    system_dns = _system_dns(blocks)
    pools: list[CanonicalDHCPPool] = []
    by_kind: dict[str, list[str]] = {}
    unread_settings: dict[str, None] = {}
    unread_tables: dict[str, None] = {}
    with_settings: list[str] = []
    with_tables: list[str] = []
    left_out: list[tuple[str, list[str]]] = []
    for block in ticked(blocks):
        if block.config_path != "system dhcp server":
            continue
        for edit in ticked(block.edits):
            shown = _shown(edit.edit_id)
            if _word(edit.settings, "status") == "disable":
                left_out.append(("disabled", ["config", "system", "dhcp", "server", "edit", shown]))
                continue
            kinds: dict[str, None] = {}
            unread: dict[str, None] = {}
            tables: dict[str, None] = {}
            record = _pool(edit, addresses, system_dns, kinds, unread, tables)
            if record is not None:
                pools.append(record)
            for kind in kinds:
                by_kind.setdefault(kind, []).append(shown)
            if unread:
                with_settings.append(shown)
                unread_settings.update(unread)
            if tables:
                with_tables.append(shown)
                unread_tables.update(tables)
    rows = [_row(kind, edits) for kind, edits in by_kind.items()]
    if with_settings:
        rows.append(
            f"config system dhcp server edit {a_few_named(with_settings)}: "
            f"set {a_few_named(list(unread_settings))} -- a setting this parser "
            "does not read, or a value in a form it does not read; not translated",
        )
    if with_tables:
        rows.append(
            f"config system dhcp server edit {a_few_named(with_tables)}: "
            f"config {a_few_named(list(unread_tables))} -- a table this parser "
            "does not read; not translated",
        )
    return pools, rows, left_out

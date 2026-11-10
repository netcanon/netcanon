"""A DHCP pool that states no range hands out its network, on every target.

The tree holds a pool that states no range as one that hands out its
network's addresses (``codecs/_dhcp_pools.py``: Junos's and Cisco's own
reading of such a pool).  A target that takes a pool only with its
range has to be told them, and three renderers were not: FortiOS wrote
a server with no ``ip-range`` (it hands out no address), RouterOS left
the ``/ip pool`` out, and OPNsense wrote an enabled zone with no range,
each with nothing said.

This module renders such a pool onto every public codec and reads the
output back with that codec's own parser, and its text.  Each codec is
in one table, and each table is compared for EQUALITY with what is
measured, so that a codec which changes what it does fails until it is
moved:

* :data:`TOLD` -- the target is written the addresses: the pool reads
  back with a run of its network's hosts, from the end it states, that
  holds none of the output's own addresses; a ``review`` line and a
  warning of the job say so.  A pool that can be given no range reads
  back as no pool, with a review line and a warning.
* :data:`NATIVE` -- the platform itself hands out the network of a pool
  with no range, so the pool reads back with its network and nothing
  else need be said.
* :data:`NO_POOLS` -- the renderer writes no pool, which its capability
  matrix declares.
* :data:`OPEN` -- what the output does is not established, or is not
  mended, each with the shape it is measured as and the reason; each
  is a known limitation, not a pass.

Each check is also handed the defect it is for, and has to fail.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Callable

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalDHCPPool,
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
)
from netcanon.migration.codecs._dhcp_pools import (
    Handed,
    OwnAddresses,
    hosts,
    what_it_hands_out,
)
from netcanon.migration.codecs.registry import get_codec, list_public_codecs

pytestmark = pytest.mark.unit

_NETWORK = ipaddress.IPv4Network("192.0.2.0/24")
_OWN = "192.0.2.1"
_STATED_START = "192.0.2.50"

#: The pools, by case: no range; its first address alone; neither a
#: range nor a network.
CASES: dict[str, dict[str, str]] = {
    "no range": {"network": str(_NETWORK)},
    "one end": {"network": str(_NETWORK), "start_ip": _STATED_START},
    "no network": {},
}

#: Written the addresses the pool hands out (each module's docstring
#: cites the vendor: FortiOS hands out none from a server with no
#: ``ip-range``; RouterOS's ``ranges`` is "( mandatory )"; OPNsense
#: will not save a zone with no range; Arista states nothing a subnet
#: with no ``range`` hands out).
TOLD = {"arista_eos", "fortigate_cli", "mikrotik_routeros", "opnsense"}

#: The platform hands out the network of a pool with no range: Junos
#: "will use all available addresses within the subnet specified";
#: Cisco's IOS DHCP server "assumes that all IP addresses in a DHCP
#: address pool subnet are available for assigning".
NATIVE = {("cisco_iosxe_cli", "no range"), ("cisco_iosxe_cli", "one end"),
          ("juniper_junos", "no range")}

#: The renderer writes no DHCP pool; the matrix says so.
NO_POOLS = {
    "aruba_aoscx", "aruba_aoss", "cisco_iosxe", "cisco_iosxr", "cisco_nxos",
    "dell_os10", "vyos",
}

#: Not established, or not mended, with the shape each is measured as
#: (``"network only"``: the pool reads back with its network and no
#: whole range; ``"other"``: no table fits), and in the CHANGELOG's
#: known limitations.
_NEITHER = (
    "a pool with neither a range nor a network is written with its "
    "options alone, and nothing is said"
)
OPEN: dict[tuple[str, str], tuple[str, str]] = {
    ("juniper_junos", "one end"): ("network only", (
        "the output writes a range with a low and no high; what Junos "
        "does with one is not established"
    )),
    ("cisco_iosxe_cli", "no network"): ("other", _NEITHER),
    ("juniper_junos", "no network"): ("other", _NEITHER),
}

#: How a comment line of each target's grammar begins.
_COMMENT_STARTS = (";", "!", "#", "//", "/*", "<!--", "*")


def _tree(**pool: str) -> CanonicalIntent:
    iface = CanonicalInterface(
        name="port2", ipv4_addresses=[CanonicalIPv4Address(ip=_OWN, prefix_length=24)],
    )
    return CanonicalIntent(
        source_vendor="test", source_format="test", hostname="r1", interfaces=[iface],
        dhcp_servers=[CanonicalDHCPPool(interface="port2", gateway=_OWN, **pool)],
    )


class _Measured:
    """One target's output for one case: its text, the job's DHCP
    warnings, and the pools its own parser reads back."""

    def __init__(self, codec_name: str, case: str) -> None:
        codec = get_codec(codec_name)
        tree = _tree(**CASES[case])
        self.case = case
        self.text = codec.render(tree)
        self.warnings = [w for w in codec.render_warnings(tree) if "DHCP pool" in w]
        self.pools = [
            (p.network, p.start_ip, p.end_ip) for p in codec.parse(self.text).dhcp_servers
        ]

    @property
    def review_lines(self) -> list[str]:
        return [
            line for line in self.text.splitlines()
            if "review:" in line and "pool" in line
        ]


def _told_faults(measured: _Measured) -> list[str]:
    """Why *measured* is not a target told what its pool hands out."""
    faults = []
    if not measured.review_lines:
        faults.append("no review line")
    if len(measured.warnings) != 1:
        faults.append(f"{len(measured.warnings)} DHCP warnings, not one")
    if measured.case == "no network":
        if measured.pools:
            faults.append("a pool that can be given no range is read back")
        return faults
    if len(measured.pools) != 1:
        return [*faults, f"{len(measured.pools)} pools read back"]
    network, start, end = measured.pools[0]
    if network != str(_NETWORK):
        faults.append("its network is not read back")
    if not (start and end):
        return [*faults, "no whole range read back"]
    first, last = hosts(_NETWORK)
    low, high = int(ipaddress.IPv4Address(start)), int(ipaddress.IPv4Address(end))
    if not first <= low <= high <= last:
        faults.append("the range is not of the network's hosts")
    if low <= int(ipaddress.IPv4Address(_OWN)) <= high:
        faults.append("the range holds the output's own address")
    stated = CASES[measured.case].get("start_ip")
    if stated and start != stated:
        faults.append("the stated end is not kept")
    return faults


def _native_faults(measured: _Measured) -> list[str]:
    """Why *measured* is not a target that hands out the network
    itself: the pool reads back with its network, and any range it
    reads back is of the network's hosts and keeps the stated end."""
    if len(measured.pools) != 1:
        return [f"{len(measured.pools)} pools read back"]
    network, start, end = measured.pools[0]
    faults = []
    if network != str(_NETWORK):
        faults.append("its network is not read back")
    first, last = hosts(_NETWORK)
    for value in (start, end):
        if value and not first <= int(ipaddress.IPv4Address(value)) <= last:
            faults.append("a range end outside the network's hosts")
    stated = CASES[measured.case].get("start_ip")
    if stated and start != stated:
        faults.append("the stated end is not kept")
    return faults


def _no_pool_faults(codec_name: str, measured: _Measured) -> list[str]:
    """Why *measured* is not a target that writes no pool and says so:
    no pool reads back, no line but a comment names the pool's network,
    and the capability matrix declares pools unsupported."""
    faults = []
    if measured.pools:
        faults.append("a pool is read back")
    written = [
        line for line in measured.text.splitlines()
        if not line.strip().startswith(_COMMENT_STARTS)
    ]
    if any("192.0.2.0" in line or "192.0.2.254" in line for line in written):
        faults.append("the output names the pool's network")
    if get_codec(codec_name).capabilities.classify("/dhcp-servers/pool") != "unsupported":
        faults.append("the matrix does not declare pools unsupported")
    return faults


def _shape(codec_name: str, case: str) -> str:
    """The table the output of *codec_name* for *case* fits."""
    measured = _Measured(codec_name, case)
    if not _told_faults(measured):
        return "told"
    if not _native_faults(measured):
        return "network only"
    if not _no_pool_faults(codec_name, measured):
        return "no pool"
    return "other"


@pytest.fixture(scope="module")
def measured_shapes() -> dict[str, set]:
    found: dict[str, set] = {"told": set(), "network only": set(), "no pool": set(), "other": set()}
    for codec_name in list_public_codecs():
        for case in CASES:
            found[_shape(codec_name, case)].add((codec_name, case))
    return found


def _open(shape: str) -> set[tuple[str, str]]:
    return {key for key, (measured, _) in OPEN.items() if measured == shape}


class TestEveryTarget:

    def test_every_cell_is_in_one_table(self) -> None:
        tables = [
            {(name, case) for name in TOLD for case in CASES},
            NATIVE,
            {(name, case) for name in NO_POOLS for case in CASES},
            set(OPEN),
        ]
        every = {(name, case) for name in list_public_codecs() for case in CASES}
        assert set().union(*tables) == every
        assert sum(len(table) for table in tables) == len(every)

    def test_the_told_are_told(self, measured_shapes: dict[str, set]) -> None:
        assert measured_shapes["told"] == {(name, case) for name in TOLD for case in CASES}

    def test_the_native_read_back_as_their_network(
        self, measured_shapes: dict[str, set],
    ) -> None:
        assert measured_shapes["network only"] == NATIVE | _open("network only")

    def test_the_rest_write_no_pool(self, measured_shapes: dict[str, set]) -> None:
        assert measured_shapes["no pool"] == (
            {(name, case) for name in NO_POOLS for case in CASES} | _open("no pool")
        )

    def test_what_is_open_is_what_is_measured(self, measured_shapes: dict[str, set]) -> None:
        assert measured_shapes["other"] == _open("other"), (
            "a target's output fits no table; mend it, or pin it in OPEN "
            f"with its reason: {sorted(measured_shapes['other'] ^ _open('other'))}"
        )


class TestEachCheckFailsOnItsDefect:
    """Each check is handed a measurement with the defect it is for."""

    @staticmethod
    def _told(**fields) -> _Measured:
        measured = _Measured("fortigate_cli", fields.pop("case", "no range"))
        for key, value in fields.items():
            setattr(measured, key, value)
        return measured

    def test_a_told_target_as_measured_passes(self) -> None:
        assert _told_faults(self._told()) == []

    @pytest.mark.parametrize(
        ("change", "fault"),
        [
            ({"pools": [("192.0.2.0/24", "", "")]}, "no whole range read back"),
            ({"pools": [("192.0.2.0/24", "192.0.2.1", "192.0.2.254")]},
             "the range holds the output's own address"),
            ({"pools": [("192.0.2.0/24", "192.0.2.2", "192.0.2.255")]},
             "the range is not of the network's hosts"),
            ({"pools": []}, "0 pools read back"),
            ({"pools": [("", "192.0.2.2", "192.0.2.254")]}, "its network is not read back"),
            ({"warnings": []}, "0 DHCP warnings, not one"),
            ({"text": "config system dhcp server\nend\n"}, "no review line"),
            ({"case": "one end", "pools": [("192.0.2.0/24", "192.0.2.2", "192.0.2.254")]},
             "the stated end is not kept"),
            ({"case": "no network", "pools": [("", "192.0.2.2", "192.0.2.254")]},
             "a pool that can be given no range is read back"),
        ],
    )
    def test_the_told_check(self, change: dict, fault: str) -> None:
        assert fault in _told_faults(self._told(**change))

    def test_the_native_check(self) -> None:
        measured = _Measured("juniper_junos", "no range")
        assert _native_faults(measured) == []
        measured.pools = [("192.0.2.0/24", "192.0.2.0", "")]
        assert "a range end outside the network's hosts" in _native_faults(measured)
        measured.pools = []
        assert _native_faults(measured) == ["0 pools read back"]

    def test_the_no_pool_check(self) -> None:
        measured = _Measured("vyos", "no range")
        assert _no_pool_faults("vyos", measured) == []
        measured.pools = [("192.0.2.0/24", "", "")]
        assert "a pool is read back" in _no_pool_faults("vyos", measured)
        measured.text += "\nsubnet 192.0.2.0/24\n"
        assert "the output names the pool's network" in _no_pool_faults("vyos", measured)
        assert "the matrix does not declare pools unsupported" in _no_pool_faults(
            "fortigate_cli", measured,
        )


def _handed(pool: dict[str, str], *own: str) -> Handed | str | None:
    interfaces = [
        CanonicalInterface(
            name=f"if{index}", ipv4_addresses=[CanonicalIPv4Address(ip=ip, prefix_length=24)],
        )
        for index, ip in enumerate(own)
    ]
    return what_it_hands_out(CanonicalDHCPPool(**pool), OwnAddresses(interfaces))


class TestWhatAPoolHandsOut:
    """``codecs/_dhcp_pools.py``, the reading every told target shares."""

    @pytest.mark.parametrize(
        ("network", "expected"),
        [
            ("192.0.2.0/24", ("192.0.2.1", "192.0.2.254")),
            ("192.0.2.0/30", ("192.0.2.1", "192.0.2.2")),
            ("192.0.2.0/31", ("192.0.2.0", "192.0.2.1")),
            ("192.0.2.7/32", ("192.0.2.7", "192.0.2.7")),
            ("192.0.2.9/24", ("192.0.2.1", "192.0.2.254")),
        ],
    )
    def test_no_range_is_the_networks_hosts(
        self, network: str, expected: tuple[str, str],
    ) -> None:
        handed = _handed({"network": network})
        assert isinstance(handed, Handed)
        assert handed.span == "-".join(expected)
        assert handed.stated == "no range"

    def test_a_pool_with_both_ends_is_none(self) -> None:
        assert _handed({"network": "192.0.2.0/24", "start_ip": "192.0.2.5",
                        "end_ip": "192.0.2.9"}) is None

    def test_own_addresses_are_runs_left_out(self) -> None:
        handed = _handed({"network": "192.0.2.0/24"}, "192.0.2.1", "192.0.2.100",
                         "192.0.2.101", "198.51.100.1")
        assert isinstance(handed, Handed)
        as_ints: Callable[[str], int] = lambda a: int(ipaddress.IPv4Address(a))  # noqa: E731
        assert handed.excluded == (
            (as_ints("192.0.2.1"), as_ints("192.0.2.1")),
            (as_ints("192.0.2.100"), as_ints("192.0.2.101")),
        )
        assert handed.free == (
            (as_ints("192.0.2.2"), as_ints("192.0.2.99")),
            (as_ints("192.0.2.102"), as_ints("192.0.2.254")),
        )
        assert handed.largest() == (as_ints("192.0.2.102"), as_ints("192.0.2.254"))

    def test_the_lower_of_two_runs_as_large(self) -> None:
        # Hosts .1 to .14; .1 and .8 own: .2-.7 and .9-.14, six each.
        handed = _handed({"network": "192.0.2.0/28"}, "192.0.2.1", "192.0.2.8")
        assert isinstance(handed, Handed)
        assert handed.largest() == (
            int(ipaddress.IPv4Address("192.0.2.2")), int(ipaddress.IPv4Address("192.0.2.7")),
        )

    @pytest.mark.parametrize(
        ("pool", "why"),
        [
            ({}, "it states no range and no network"),
            ({"start_ip": "192.0.2.5"}, "it states one end of its range and no network"),
            ({"network": "not a network"}, "it states no range and no network"),
            ({"network": "192.0.2.0/24", "start_ip": "198.51.100.1"},
             "its range is not in its network"),
            ({"network": "192.0.2.0/24", "end_ip": "192.0.2.255"},
             "its range is not in its network"),
            ({"network": "192.0.2.0/24", "start_ip": "not an address"},
             "its range is not in its network"),
        ],
    )
    def test_a_pool_that_can_be_given_no_range_says_why(
        self, pool: dict[str, str], why: str,
    ) -> None:
        assert _handed(pool) == why

    def test_every_address_its_own(self) -> None:
        assert _handed({"network": "192.0.2.0/30"}, "192.0.2.1", "192.0.2.2") == (
            "every address of its range is this output's own"
        )

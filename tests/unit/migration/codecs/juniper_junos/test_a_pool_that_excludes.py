"""What a Junos pool excludes is taken out of what the tree holds, and said.

A Junos address-assignment pool can exclude addresses from what it
hands out: ``excluded-address <ip>`` and ``excluded-range <R> low|high
<ip>`` under ``family inet`` (Juniper: from Junos 18.1R1, "to prevent
them from being allocated from an address pool"), and ``exclude-address
<ip>`` in the older ``system services dhcp pool <CIDR>``.  The parser
read none of them and said nothing, so every target was given a range
that holds the addresses the source keeps back.

The tree has no place for an exclusion.  The parser now takes the
excluded addresses, and the device's own, out of what the pool hands out
and keeps the largest run left, both its ends stated; a pool whose
exclusions take out nothing it hands out is read as it was; and rows say
the runs left out, a pool left with no address, and an exclusion that
cannot be read (:mod:`netcanon.migration.codecs.juniper_junos.dhcp_pools`).
Every config here is typed by hand.
"""

from __future__ import annotations

import ipaddress

import pytest

from netcanon.migration.codecs._dhcp_pools import OwnAddresses
from netcanon.migration.codecs.juniper_junos.dhcp_pools import exclusion_rows, pool_reading
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

JUNOS = get_codec("juniper_junos")
_POOL = "set access address-assignment pool {name} family inet"
_OWN = "set interfaces ge-0/0/1 unit 0 family inet address 192.0.2.1/24"
_NETWORK = "{pool} network 192.0.2.0/24"

_SPLIT = (
    "{head} {names}: {words} -- what the pool hands out, less the addresses it "
    "excludes and this device's own, is more than one run; the tree holds one run "
    "of a pool, so the largest is kept and the others are not translated"
)
_NONE_LEFT = (
    "{head} {names}: {words} -- every address the pool hands out is excluded or "
    "this device's own, so it hands out none; not translated"
)
_UNREAD = (
    "{head} {names}: {words} -- an exclusion this parser cannot read (an address "
    "that is not one, a range without both ends or with its low above its high) is "
    "not translated, so the target may hand out an address the source does not"
)
_SEVERAL = (
    "access address-assignment pool {names}: family inet range -- more than one "
    "range; the tree holds one run of a pool, so the largest is kept and the "
    "others are not translated"
)
_MODERN = {"head": "access address-assignment pool", "words": "family inet excluded-address or excluded-range"}
_OLDER = {"head": "system services dhcp pool", "words": "exclude-address"}


def _config(*lines: str, name: str = "P") -> str:
    return "\n".join(
        ["set system host-name r1", _OWN, *(line.format(pool=_POOL.format(name=name)) for line in lines), ""],
    )


def _pools(text: str) -> list[tuple[str, str, str]]:
    return [(p.network, p.start_ip, p.end_ip) for p in JUNOS.parse(text).dhcp_servers]


def _rows(text: str) -> list[str]:
    return [row for row in JUNOS.parse(text).dropped_tier3_sections if "pool" in row]


class TestReadAsItWas:
    """An exclusion that takes out nothing the pool hands out changes
    nothing: no end is stated that the source did not state."""

    def test_the_routers_own_address(self) -> None:
        text = _config(_NETWORK, "{pool} excluded-address 192.0.2.1")
        assert _pools(text) == [("192.0.2.0/24", "", "")]
        assert _rows(text) == []

    def test_an_address_outside_the_range(self) -> None:
        text = _config(_NETWORK, "{pool} range r1 low 192.0.2.50 high 192.0.2.60", "{pool} excluded-address 192.0.2.70")
        assert _pools(text) == [("192.0.2.0/24", "192.0.2.50", "192.0.2.60")]
        assert _rows(text) == []

    def test_a_range_outside_the_network(self) -> None:
        text = _config(_NETWORK, "{pool} excluded-range e1 low 198.51.100.1 high 198.51.100.9")
        assert _pools(text) == [("192.0.2.0/24", "", "")]
        assert _rows(text) == []

    def test_the_broadcast_address(self) -> None:
        text = _config(_NETWORK, "{pool} excluded-address 192.0.2.255")
        assert _pools(text) == [("192.0.2.0/24", "", "")]


class TestTakenOut:
    def test_a_range_at_the_low_edge(self) -> None:
        # The router's own .1 is not handed out either.
        text = _config(_NETWORK, "{pool} excluded-range e1 low 192.0.2.2 high 192.0.2.10")
        assert _pools(text) == [("192.0.2.0/24", "192.0.2.11", "192.0.2.254")]
        assert _rows(text) == []

    def test_a_range_at_the_high_edge(self) -> None:
        text = _config(_NETWORK, "{pool} excluded-range e1 low 192.0.2.200 high 192.0.2.254")
        assert _pools(text) == [("192.0.2.0/24", "192.0.2.2", "192.0.2.199")]
        assert _rows(text) == []

    def test_both_ends_of_the_excluded_range_on_two_lines(self) -> None:
        text = _config(
            _NETWORK, "{pool} excluded-range e1 low 192.0.2.2", "{pool} excluded-range e1 high 192.0.2.10",
        )
        assert _pools(text) == [("192.0.2.0/24", "192.0.2.11", "192.0.2.254")]

    def test_an_end_set_again_replaces_the_one_before(self) -> None:
        text = _config(
            _NETWORK, "{pool} excluded-range e1 low 192.0.2.2 high 192.0.2.10",
            "{pool} excluded-range e1 high 192.0.2.20",
        )
        assert _pools(text) == [("192.0.2.0/24", "192.0.2.21", "192.0.2.254")]

    def test_addresses_one_a_line(self) -> None:
        text = _config(
            _NETWORK, "{pool} range r1 low 192.0.2.10 high 192.0.2.50",
            "{pool} excluded-address 192.0.2.10", "{pool} excluded-address 192.0.2.11",
            "{pool} excluded-address 192.0.2.11",
        )
        assert _pools(text) == [("192.0.2.0/24", "192.0.2.12", "192.0.2.50")]
        assert _rows(text) == []

    def test_a_split_keeps_the_largest_run_and_says_the_other(self) -> None:
        text = _config(_NETWORK, "{pool} excluded-range e1 low 192.0.2.100 high 192.0.2.110")
        assert _pools(text) == [("192.0.2.0/24", "192.0.2.111", "192.0.2.254")]
        assert _rows(text) == [_SPLIT.format(names="P", **_MODERN)]

    def test_of_two_runs_as_large_the_lower(self) -> None:
        text = _config(_NETWORK, "{pool} range r1 low 192.0.2.10 high 192.0.2.20", "{pool} excluded-address 192.0.2.15")
        assert _pools(text) == [("192.0.2.0/24", "192.0.2.10", "192.0.2.14")]
        assert _rows(text) == [_SPLIT.format(names="P", **_MODERN)]

    def test_an_end_the_range_does_not_state(self) -> None:
        text = _config(_NETWORK, "{pool} range r1 low 192.0.2.100", "{pool} excluded-address 192.0.2.254")
        assert _pools(text) == [("192.0.2.0/24", "192.0.2.100", "192.0.2.253")]

    def test_the_devices_own_address_in_a_stated_range(self) -> None:
        # Once an exclusion takes something out, the device's own
        # address is not in the run kept either.
        text = _config(_NETWORK, "{pool} range r1 low 192.0.2.1 high 192.0.2.50", "{pool} excluded-address 192.0.2.50")
        assert _pools(text) == [("192.0.2.0/24", "192.0.2.2", "192.0.2.49")]
        assert _rows(text) == []

    def test_several_ranges_and_an_exclusion(self) -> None:
        text = _config(
            _NETWORK, "{pool} range a low 192.0.2.10 high 192.0.2.20",
            "{pool} range b low 192.0.2.100 high 192.0.2.150",
            "{pool} excluded-range e1 low 192.0.2.100 high 192.0.2.140",
        )
        assert _pools(text) == [("192.0.2.0/24", "192.0.2.10", "192.0.2.20")]
        assert _rows(text) == [_SEVERAL.format(names="P")]

    def test_the_older_form(self) -> None:
        text = "\n".join([
            "set system host-name r1",
            "set system services dhcp pool 198.51.100.0/24 address-range low 198.51.100.10 high 198.51.100.100",
            "set system services dhcp pool 198.51.100.0/24 exclude-address 198.51.100.50",
            "",
        ])
        assert _pools(text) == [("198.51.100.0/24", "198.51.100.51", "198.51.100.100")]
        assert _rows(text) == [_SPLIT.format(names="198.51.100.0/24", **_OLDER)]

    def test_the_older_form_with_no_range(self) -> None:
        text = "\n".join([
            "set system host-name r1",
            "set system services dhcp pool 198.51.100.0/24 exclude-address 198.51.100.1",
            "set system services dhcp pool 198.51.100.0/24 exclude-address 198.51.100.2",
            "",
        ])
        assert _pools(text) == [("198.51.100.0/24", "198.51.100.3", "198.51.100.254")]
        assert _rows(text) == []

    def test_an_exclusion_from_an_applied_group(self) -> None:
        text = _config(
            _NETWORK,
            "set groups G access address-assignment pool P family inet excluded-address 192.0.2.254",
            "set apply-groups G",
        )
        assert _pools(text) == [("192.0.2.0/24", "192.0.2.2", "192.0.2.253")]

    def test_the_hierarchical_form(self) -> None:
        text = "\n".join([
            "system {",
            "    host-name r1;",
            "}",
            "access {",
            "    address-assignment {",
            "        pool P {",
            "            family inet {",
            "                network 192.0.2.0/24;",
            "                excluded-address 192.0.2.254;",
            "                excluded-range e1 {",
            "                    low 192.0.2.1;",
            "                    high 192.0.2.9;",
            "                }",
            "            }",
            "        }",
            "    }",
            "}",
            "",
        ])
        assert _pools(text) == [("192.0.2.0/24", "192.0.2.10", "192.0.2.253")]


class TestNoneLeft:
    def test_every_address_of_the_range(self) -> None:
        text = _config(
            _NETWORK, "{pool} range r1 low 192.0.2.50 high 192.0.2.60",
            "{pool} excluded-range e1 low 192.0.2.40 high 192.0.2.65",
        )
        assert _pools(text) == []
        assert _rows(text) == [_NONE_LEFT.format(names="P", **_MODERN)]

    def test_every_address_but_the_devices_own(self) -> None:
        text = _config(
            "{pool} network 192.0.2.0/30", "{pool} excluded-address 192.0.2.2",
        )
        assert _pools(text) == []
        assert _rows(text) == [_NONE_LEFT.format(names="P", **_MODERN)]


class TestUnread:
    @pytest.mark.parametrize("line", [
        "{pool} excluded-range e1 low 192.0.2.2",
        "{pool} excluded-range e1 high 192.0.2.9",
        "{pool} excluded-range e1 low 192.0.2.9 high 192.0.2.2",
        "{pool} excluded-address not-an-address",
        "{pool} excluded-range e1 low 192.0.2.2 high not-an-address",
    ])
    def test_said_and_left_out(self, line: str) -> None:
        text = _config(_NETWORK, line)
        assert _pools(text) == [("192.0.2.0/24", "", "")]
        assert _rows(text) == [_UNREAD.format(names="P", **_MODERN)]

    def test_the_others_are_still_taken_out(self) -> None:
        text = _config(_NETWORK, "{pool} excluded-range e1 low 192.0.2.2", "{pool} excluded-address 192.0.2.254")
        assert _pools(text) == [("192.0.2.0/24", "192.0.2.2", "192.0.2.253")]
        assert _rows(text) == [_UNREAD.format(names="P", **_MODERN)]


class TestTheRows:
    def test_a_few_named_and_the_rest_counted(self) -> None:
        rows = exclusion_rows([(False, f"p{n}") for n in range(8)], [], [])
        assert rows == [_SPLIT.format(names="p0, p1, p2 and 5 more", **_MODERN)]

    def test_each_form_has_its_row(self) -> None:
        rows = exclusion_rows([], [(False, "P"), (True, "198.51.100.0/24")], [])
        assert rows == [
            _NONE_LEFT.format(names="P", **_MODERN),
            _NONE_LEFT.format(names="198.51.100.0/24", **_OLDER),
        ]

    def test_a_long_name_is_cut(self) -> None:
        (row,) = exclusion_rows([], [], [(False, "x" * 100)])
        assert "x" * 39 + "…" in row
        assert "x" * 40 not in row

    def test_no_address_is_shown(self) -> None:
        text = _config(_NETWORK, "{pool} excluded-range e1 low 192.0.2.100 high 192.0.2.110")
        for row in _rows(text):
            assert "192.0.2" not in row


def test_no_exclusion_reads_no_own_address() -> None:
    """Only a pool that excludes something needs the device's own
    addresses."""
    asked: list[int] = []

    def own() -> OwnAddresses:
        asked.append(1)
        return OwnAddresses([])

    reading = pool_reading({"r": {"low": "192.0.2.10", "high": "192.0.2.20"}}, "192.0.2.0/24", {}, {}, own)
    assert (reading.start_ip, reading.end_ip, asked) == ("192.0.2.10", "192.0.2.20", [])


_SOURCE = _config(
    _NETWORK,
    "{pool} excluded-range e1 low 192.0.2.2 high 192.0.2.10",
    "{pool} excluded-address 192.0.2.200",
    "{pool} dhcp-attributes router 192.0.2.1",
    "set system services dhcp-local-server group P interface ge-0/0/1.0",
)
_EXCLUDED = [
    int(ipaddress.IPv4Address("192.0.2.200")),
    *range(int(ipaddress.IPv4Address("192.0.2.2")), int(ipaddress.IPv4Address("192.0.2.10")) + 1),
]

#: The targets whose own parser reads a pool back from the output.
_READ_BACK = {
    "arista_eos", "aruba_aoss", "cisco_iosxe_cli", "fortigate_cli", "juniper_junos",
    "mikrotik_routeros",
}


@pytest.mark.parametrize("target", sorted(list_public_codecs()))
def test_every_job_says_the_run_left_out(target: str) -> None:
    job = run_plan_with_checked_names(JUNOS, get_codec(target), _SOURCE)
    assert _SPLIT.format(names="P", **_MODERN) in job.dropped_tier3_sections


def test_no_target_hands_out_an_excluded_address() -> None:
    read_back: set[str] = set()
    for target in sorted(list_public_codecs()):
        job = run_plan_with_checked_names(JUNOS, get_codec(target), _SOURCE)
        pools = get_codec(target).parse(job.rendered).dhcp_servers if job.rendered else []
        for pool in pools:
            read_back.add(target)
            low, high = ipaddress.IPv4Address(pool.start_ip), ipaddress.IPv4Address(pool.end_ip)
            assert (str(low), str(high)) == ("192.0.2.11", "192.0.2.199"), target
            assert not [a for a in _EXCLUDED if int(low) <= a <= int(high)], target
    assert read_back == _READ_BACK

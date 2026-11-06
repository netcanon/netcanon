"""Aruba AOS-S: the switch's own DHCP server is read, and what it does
not serve is said.

An AOS-S switch has a DHCPv4 server of its own.  The parser used to
skip every ``dhcp-server pool`` stanza without a word: a switch that
served its VLANs came out on every target with no pool, in jobs that
said ``completed``, and no row said a pool had been there.

What HPE says, and the tests below are typed from (ArubaOS-Switch
Management and Configuration Guide, "DHCPv4 server"; HPE's DHCP white
paper):

* ``dhcp-server pool <POOL-NAME>`` enters a pool's context; its
  statements are ``network``, ``range``, ``default-router``,
  ``dns-server``, ``domain-name``, ``lease``, ``static-bind``,
  ``option`` and a few more.  The default lease is one day.
* The server "Defaults to disabled"; ``dhcp-server enable`` turns it
  on, and the switch prints that line after the pools.
* A pool is valid as a dynamic pool (a network and a range) or a
  static one (a static binding); "The DHCP server will discard the
  invalid and incomplete pools".
* ``dhcp-server`` in a VLAN's stanza enables the server on that VLAN,
  and a pool whose network is no VLAN of the switch serves clients a
  relay forwards to it.

So a pool of a server that is not enabled is LEFT OUT AND SAID
(``disabled:``), and so is a pool the server discards
(``incomplete:``).  A dynamic pool is on ``Vlan<N>`` only where its
network is the subnet of a VLAN that states ``dhcp-server``, and on no
interface otherwise.  What the tree has no place for (a second range,
a static binding, an option) is said by its kind, never by its value.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration._tier3_detection import is_left_out_row
from netcanon.migration.canonical.intent import CanonicalIntent
from netcanon.migration.codecs.aruba_aoss.codec import ArubaAOSSCodec
from netcanon.migration.codecs.registry import get_codec
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

CAPTURE = (
    Path(__file__).resolve().parents[4]
    / "fixtures" / "real" / "aruba_aoss" / "hpe_community_2930f_wc1610_dhcp_server.cfg"
)

_HEAD = '; JL256A Configuration Editor; Created on release #WC.16.10.0001\nhostname "sw"\n'

#: A VLAN the server serves on, a pool for it, and the server enabled,
#: as the switch prints them.
_SERVED = (
    "vlan 10\n"
    '   name "USERS"\n'
    "   untagged 1-4\n"
    "   ip address 10.0.10.1 255.255.255.0\n"
    "   dhcp-server\n"
    "   exit\n"
    'dhcp-server pool "USERS"\n'
    '   default-router "10.0.10.1"\n'
    '   dns-server "10.0.10.53,10.0.10.54"\n'
    '   domain-name "example.net"\n'
    "   lease 02:03:04\n"
    "   network 10.0.10.0 255.255.255.0\n"
    "   range 10.0.10.100 10.0.10.200\n"
    "   exit\n"
)

_ENABLE = "dhcp-server enable\n"

_DISABLED_WHY = "the source's DHCP server is not enabled, so it serves nothing; not translated"
_INCOMPLETE_WHY = (
    "a DHCP pool with neither a network and a range nor a static binding, "
    "which the source's server discards; not translated"
)


def _parse(text: str) -> CanonicalIntent:
    return ArubaAOSSCodec().parse(_HEAD + text)


def _flat(text: str) -> str:
    return "\n".join(line.lstrip() for line in text.splitlines()) + "\n"


def _pools(tree: CanonicalIntent) -> list[tuple]:
    return [
        (p.interface, p.network, p.start_ip, p.end_ip, p.gateway, p.dns_servers, p.lease_time, p.domain_name)
        for p in tree.dhcp_servers
    ]


def _dhcp_rows(tree: CanonicalIntent) -> list[str]:
    return [row for row in tree.dropped_tier3_sections if "dhcp-server" in row]


# ---------------------------------------------------------------------------
# (a) A pool of an enabled server
# ---------------------------------------------------------------------------


def test_a_pool_of_an_enabled_server_is_on_its_vlan() -> None:
    tree = _parse(_SERVED + _ENABLE)
    assert _pools(tree) == [(
        "Vlan10", "10.0.10.0/24", "10.0.10.100", "10.0.10.200", "10.0.10.1",
        ["10.0.10.53", "10.0.10.54"], 2 * 86400 + 3 * 3600 + 4 * 60, "example.net",
    )]
    assert _dhcp_rows(tree) == []


def test_the_same_config_with_no_indentation_is_the_same_tree() -> None:
    tree = _parse(_SERVED + _ENABLE)
    assert _parse(_flat(_SERVED + _ENABLE)).model_dump(mode="json") == tree.model_dump(mode="json")


def test_the_network_in_hpes_own_syntax() -> None:
    """HPE's syntax is ``network <address>/<length>``; the switch prints
    a mask.  Either is the same network, and an address inside it is
    read as the network it is in."""
    for line in ("network 10.0.10.0/24", "network 10.0.10.0 255.255.255.0", "network 10.0.10.7/24"):
        text = _SERVED.replace("network 10.0.10.0 255.255.255.0", line) + _ENABLE
        assert [p.network for p in _parse(text).dhcp_servers] == ["10.0.10.0/24"], line


@pytest.mark.parametrize(("line", "seconds"), [
    ("lease 01:00:00", 86400),
    ("lease 00:00:30", 30 * 60),
    ("lease infinite", 0xFFFFFFFF),
    (None, 86400),
])
def test_a_lease(line: str | None, seconds: int) -> None:
    """``lease [DD:HH:MM | infinite]``; with no line, HPE's default of
    one day."""
    text = _SERVED.replace("   lease 02:03:04\n", f"   {line}\n" if line else "") + _ENABLE
    assert [p.lease_time for p in _parse(text).dhcp_servers] == [seconds]


def test_addresses_typed_with_spaces() -> None:
    text = _SERVED.replace('"10.0.10.53,10.0.10.54"', "10.0.10.53 10.0.10.54") + _ENABLE
    assert [p.dns_servers for p in _parse(text).dhcp_servers] == [["10.0.10.53", "10.0.10.54"]]


def test_a_range_of_one_address() -> None:
    text = _SERVED.replace("range 10.0.10.100 10.0.10.200", "range 10.0.10.100") + _ENABLE
    assert [(p.start_ip, p.end_ip) for p in _parse(text).dhcp_servers] == [("10.0.10.100", "10.0.10.100")]


def test_a_pool_met_twice_is_one_pool() -> None:
    """A context entered again is the same pool: what each stanza states
    is the pool's."""
    text = (
        "vlan 10\n   ip address 10.0.10.1 255.255.255.0\n   dhcp-server\n   exit\n"
        'dhcp-server pool "P"\n   network 10.0.10.0 255.255.255.0\n   exit\n'
        'dhcp-server pool "P"\n   range 10.0.10.100 10.0.10.200\n   exit\n'
        + _ENABLE
    )
    tree = _parse(text)
    assert [(p.interface, p.start_ip) for p in tree.dhcp_servers] == [("Vlan10", "10.0.10.100")]
    assert _dhcp_rows(tree) == []


def test_a_statement_on_the_headers_line_is_the_pools() -> None:
    text = (
        "vlan 10\n   ip address 10.0.10.1 255.255.255.0\n   dhcp-server\n   exit\n"
        'dhcp-server pool "P" network 10.0.10.0 255.255.255.0\n'
        'dhcp-server pool "P" range 10.0.10.100 10.0.10.200\n'
        + _ENABLE
    )
    assert [(p.network, p.start_ip) for p in _parse(text).dhcp_servers] == [("10.0.10.0/24", "10.0.10.100")]


# ---------------------------------------------------------------------------
# (b) Which interface a pool is on
# ---------------------------------------------------------------------------


def test_a_vlan_that_does_not_state_dhcp_server_is_not_the_pools() -> None:
    text = _SERVED.replace("   dhcp-server\n", "") + _ENABLE
    assert [p.interface for p in _parse(text).dhcp_servers] == [""]


def test_a_pool_for_relayed_clients_is_on_no_interface() -> None:
    """A network that is no VLAN's own serves clients a relay forwards:
    the pool is on no interface of this switch."""
    text = (
        _SERVED
        + 'dhcp-server pool "REMOTE"\n   network 10.0.99.0 255.255.255.0\n'
        "   range 10.0.99.10 10.0.99.20\n   default-router \"10.0.99.1\"\n   exit\n"
        + _ENABLE
    )
    assert [(p.interface, p.network) for p in _parse(text).dhcp_servers] == [
        ("Vlan10", "10.0.10.0/24"), ("", "10.0.99.0/24"),
    ]


def test_a_pool_is_on_the_vlan_whose_subnet_it_is_not_one_it_overlaps() -> None:
    text = _SERVED.replace("network 10.0.10.0 255.255.255.0", "network 10.0.10.0 255.255.255.128") + _ENABLE
    assert [(p.interface, p.network) for p in _parse(text).dhcp_servers] == [("", "10.0.10.0/25")]


def test_the_vlans_dhcp_server_line_in_a_flat_vlan() -> None:
    text = (
        "vlan 10\nip address 10.0.10.1 255.255.255.0\ndhcp-server\nuntagged 3\nexit\n"
        'dhcp-server pool "P"\nnetwork 10.0.10.0 255.255.255.0\nrange 10.0.10.100 10.0.10.200\nexit\n'
        + _ENABLE
    )
    tree = _parse(text)
    assert [p.interface for p in tree.dhcp_servers] == ["Vlan10"]
    assert [(v.id, v.untagged_ports) for v in tree.vlans] == [(10, ["3"])]


# ---------------------------------------------------------------------------
# (c) A server that is not enabled serves nothing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("lines", "enabled"), [
    ("", False),
    ("dhcp-server enable\n", True),
    ("dhcp-server enable\ndhcp-server disable\n", False),
    ("dhcp-server disable\ndhcp-server enable\n", True),
    ("dhcp-server enable\nno dhcp-server enable\n", False),
    ("no dhcp-server disable\n", True),
    ("DHCP-SERVER ENABLE\n", True),
])
def test_the_last_line_that_turns_the_server_on_or_off(lines: str, enabled: bool) -> None:
    tree = _parse(_SERVED + lines)
    assert bool(tree.dhcp_servers) is enabled, lines
    rows = _dhcp_rows(tree)
    if enabled:
        assert rows == []
    else:
        assert rows == [f"disabled: dhcp-server pool USERS ({_DISABLED_WHY})"]
        assert all(is_left_out_row(row) for row in rows)


def test_the_enable_line_before_the_pools_counts_too() -> None:
    """The switch prints it after the pools; a config typed the other
    way round is the same server."""
    assert len(_parse(_ENABLE + _SERVED).dhcp_servers) == 1


def test_a_setting_of_the_server_is_said_by_its_words() -> None:
    settings = "dhcp-server ping packets 3\nno dhcp-server conflict-logging\n"
    on = _dhcp_rows(_parse(_SERVED + settings + _ENABLE))
    assert on == [
        "dhcp-server ping (a setting of the DHCP server; not translated)",
        "no dhcp-server conflict-logging (a setting of the DHCP server; not translated)",
    ]
    off = _dhcp_rows(_parse(_SERVED + settings))
    assert off == [
        f"disabled: dhcp-server pool USERS ({_DISABLED_WHY})",
        f"disabled: dhcp-server ping ({_DISABLED_WHY})",
        f"disabled: no dhcp-server conflict-logging ({_DISABLED_WHY})",
    ]
    assert not [row for row in on + off if "3" in row]


def test_a_database_setting_shows_no_location() -> None:
    """A database file is a URL, and a URL can hold a password."""
    rows = _dhcp_rows(_parse(_SERVED + 'dhcp-server database file "tftp://10.0.0.9/db.txt" delay 30\n' + _ENABLE))
    assert rows == ["dhcp-server database (a setting of the DHCP server; not translated)"]


# ---------------------------------------------------------------------------
# (d) A pool the server discards, a static pool, and what has no place
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("body", [
    "   network 10.0.20.0 255.255.255.0\n",
    "   range 10.0.20.10 10.0.20.20\n",
    '   default-router "10.0.20.1"\n',
    "",
])
def test_an_incomplete_pool_is_left_out_and_said(body: str) -> None:
    tree = _parse(_SERVED + f'dhcp-server pool "HALF"\n{body}   exit\n' + _ENABLE)
    assert [p.network for p in tree.dhcp_servers] == ["10.0.10.0/24"]
    rows = _dhcp_rows(tree)
    assert rows == [f"incomplete: dhcp-server pool HALF ({_INCOMPLETE_WHY})"]
    assert is_left_out_row(rows[0])


def test_a_static_pool_is_said_and_shows_no_binding() -> None:
    tree = _parse(
        _SERVED
        + 'dhcp-server pool "PRINTER"\n   static-bind ip 10.0.10.5/24 mac 00005e-005301\n'
        '   default-router "10.0.10.1"\n   exit\n'
        + _ENABLE
    )
    assert [p.network for p in tree.dhcp_servers] == ["10.0.10.0/24"]
    rows = _dhcp_rows(tree)
    assert rows == [
        'dhcp-server pool static-bind (in pool "PRINTER": a static binding of an address '
        "to a MAC address; not translated)"
    ]
    assert not is_left_out_row(rows[0])
    assert "005301" not in rows[0] and "10.0.10.5" not in rows[0]


def test_what_a_dynamic_pool_holds_that_the_tree_has_no_place_for() -> None:
    """A second range or router, a binding and an option are said, one
    row a kind; the record keeps the first range and the first
    router.  No value is in a row: an option holds what a vendor's
    client is given, a key among it often enough."""
    body = (
        "   range 10.0.10.210 10.0.10.220\n"
        '   default-router "10.0.10.1,10.0.10.2"\n'
        "   static-bind ip 10.0.10.5/24 mac 00005e-005301\n"
        '   option 43 ascii "notshown"\n'
        '   tftp-server server-name "boot"\n'
    )
    tree = _parse(_SERVED.replace(
        "   range 10.0.10.100 10.0.10.200\n", "   range 10.0.10.100 10.0.10.200\n" + body,
    ) + _ENABLE)
    assert [(p.start_ip, p.end_ip, p.gateway) for p in tree.dhcp_servers] == [
        ("10.0.10.100", "10.0.10.200", "10.0.10.1"),
    ]
    rows = _dhcp_rows(tree)
    assert rows == [
        'dhcp-server pool option (in pool "USERS": a statement of a DHCP pool; not translated)',
        'dhcp-server pool tftp-server (in pool "USERS": a statement of a DHCP pool; not translated)',
        "dhcp-server pool range (in pool \"USERS\": a range after the pool's first; not translated)",
        "dhcp-server pool default-router (in pool \"USERS\": a default router after the pool's first; "
        "not translated)",
        'dhcp-server pool static-bind (in pool "USERS": a static binding of an address to a MAC address; '
        "not translated)",
    ]
    for value in ("notshown", "boot", "43", "005301", "10.0.10.2", "10.0.10.210"):
        assert not [row for row in rows if value in row], value


@pytest.mark.parametrize("line", [
    "no dns-server",
    "range 10.0.10.300 10.0.10.310",
    "network 10.0.10.0 255.255.255.0 extra",
    "lease forever",
    'dns-server "10.0.10.53,nameserver"',
])
def test_a_line_in_a_form_the_parser_does_not_read(line: str) -> None:
    tree = _parse(_SERVED.replace(
        "   range 10.0.10.100 10.0.10.200\n", f"   range 10.0.10.100 10.0.10.200\n   {line}\n",
    ) + _ENABLE)
    assert len(tree.dhcp_servers) == 1
    assert _dhcp_rows(tree) == [
        'dhcp-server pool (in pool "USERS": a line in a form this parser does not read; not translated)'
    ]


def test_many_pools_are_one_row_a_kind() -> None:
    """A row names a few pools and counts the rest, so that a config of
    thousands of them is a few lines of a job."""
    pools = "".join(
        f'dhcp-server pool "P{n}"\n   network 10.1.{n}.0 255.255.255.0\n   range 10.1.{n}.10 10.1.{n}.20\n'
        f'   option 66 ascii "x"\n   exit\n'
        for n in range(40)
    )
    tree = _parse(pools + _ENABLE)
    assert len(tree.dhcp_servers) == 40
    assert _dhcp_rows(tree) == [
        'dhcp-server pool option (in pools "P0", "P1", "P2" and 37 more: a statement of a DHCP pool; '
        "not translated)"
    ]


def test_a_pool_name_with_spaces_and_a_long_one() -> None:
    long_name = "N" * 300
    tree = _parse(f'dhcp-server pool "my pool"\n   exit\ndhcp-server pool "{long_name}"\n   exit\n')
    rows = _dhcp_rows(tree)
    assert rows[0] == f'disabled: dhcp-server pool "my pool" ({_DISABLED_WHY})'
    assert len(rows) == 2 and long_name not in rows[1] and "…" in rows[1]


# ---------------------------------------------------------------------------
# (e) Where the stanza ends
# ---------------------------------------------------------------------------


def test_a_pool_with_no_exit_ends_at_the_next_header() -> None:
    text = (
        "vlan 10\n   ip address 10.0.10.1 255.255.255.0\n   dhcp-server\n   exit\n"
        'dhcp-server pool "P"\n   network 10.0.10.0 255.255.255.0\n   range 10.0.10.100 10.0.10.200\n'
        "vlan 20\n   untagged 7\n   exit\n"
        + _ENABLE
    )
    tree = _parse(text)
    assert [p.interface for p in tree.dhcp_servers] == ["Vlan10"]
    assert [(v.id, v.untagged_ports) for v in tree.vlans] == [(10, []), (20, ["7"])]


def test_the_enable_line_ends_a_pool_with_no_exit() -> None:
    text = (
        "vlan 10\n   ip address 10.0.10.1 255.255.255.0\n   dhcp-server\n   exit\n"
        'dhcp-server pool "P"\n   network 10.0.10.0 255.255.255.0\n   range 10.0.10.100 10.0.10.200\n'
        + _ENABLE
    )
    tree = _parse(text)
    assert len(tree.dhcp_servers) == 1 and _dhcp_rows(tree) == []


# ---------------------------------------------------------------------------
# (f) The committed capture, and the output
# ---------------------------------------------------------------------------


def test_the_committed_capture_serves_three_vlans() -> None:
    tree = ArubaAOSSCodec().parse(CAPTURE.read_text(encoding="utf-8"))
    assert len(tree.dhcp_servers) == 3
    vlans_with_an_address = {f"Vlan{v.id}" for v in tree.vlans if v.ipv4_addresses}
    for pool in tree.dhcp_servers:
        assert pool.interface in vlans_with_an_address
        assert pool.network and pool.start_ip and pool.end_ip and pool.gateway and pool.dns_servers
    assert _dhcp_rows(tree) == []


def test_the_pool_reaches_another_vendors_output() -> None:
    job = run_plan_with_checked_names(
        get_codec("aruba_aoss"), get_codec("cisco_iosxe_cli"), _HEAD + _SERVED + _ENABLE, port_rename_map={},
    )
    assert job.rendered is not None
    lines = [line.strip() for line in job.rendered.splitlines()]
    assert "ip dhcp pool Vlan10" in lines
    assert "network 10.0.10.0 255.255.255.0" in lines
    assert "default-router 10.0.10.1" in lines


def test_a_pool_of_a_server_that_is_not_enabled_reaches_no_output() -> None:
    job = run_plan_with_checked_names(
        get_codec("aruba_aoss"), get_codec("cisco_iosxe_cli"), _HEAD + _SERVED, port_rename_map={},
    )
    assert job.rendered is not None
    assert "ip dhcp pool" not in job.rendered
    assert f"disabled: dhcp-server pool USERS ({_DISABLED_WHY})" in job.dropped_tier3_sections

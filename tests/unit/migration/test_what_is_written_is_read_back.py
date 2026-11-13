"""Four lines a renderer wrote and its own parser did not read.

``test_a_supported_path_is_written.py`` holds every ``supported`` path
of every codec to what the codec's parser reads back from its render,
and pinned four paths whose line was written and not read:

* IOS-XE CLI ``ip address dhcp`` (``CanonicalInterface.dhcp_client``);
* FortiOS ``set mode dhcp`` (the same field);
* a RouterOS ``/user`` line's ``password=``, read as no password;
* a RouterOS route whose ``gateway=`` is an interface name, read with the
  name as its gateway rather than its interface -- an address no target
  can reach, and a port name the port translator does not rewrite.

Each parser reads its line now.  These tests hold each form the vendor
writes, and the forms near it that must NOT be read so; the round trip
itself is that module's.
"""
from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalLocalUser,
    CanonicalStaticRoute,
)
from netcanon.migration.codecs.registry import get_codec


def _iface(tree: CanonicalIntent, name: str):
    return next(i for i in tree.interfaces if i.name == name)


# --- IOS-XE CLI: ip address dhcp -------------------------------------------


@pytest.mark.parametrize("line", [
    " ip address dhcp",
    " ip address dhcp client-id GigabitEthernet0/0",
    " ip address dhcp hostname edge1",
    " IP ADDRESS DHCP",
])
def test_iosxe_reads_ip_address_dhcp(line: str) -> None:
    text = f"hostname r1\n!\ninterface GigabitEthernet0/0\n{line}\n no shutdown\n!\nend\n"
    iface = _iface(get_codec("cisco_iosxe_cli").parse(text), "GigabitEthernet0/0")
    assert iface.dhcp_client is True
    assert iface.ipv4_addresses == []


@pytest.mark.parametrize("line", [
    " ip address 192.0.2.1 255.255.255.0",
    " ipv6 address dhcp",
    " no ip address",
    " ip address dhcpx",
])
def test_iosxe_reads_no_dhcp_client_from_another_line(line: str) -> None:
    text = f"hostname r1\n!\ninterface GigabitEthernet0/0\n{line}\n!\nend\n"
    iface = _iface(get_codec("cisco_iosxe_cli").parse(text), "GigabitEthernet0/0")
    assert iface.dhcp_client is False


# --- FortiOS: set mode dhcp --------------------------------------------------


def _fortios(mode_line: str) -> str:
    return (
        "config system interface\n"
        '    edit "port1"\n'
        '        set vdom "root"\n'
        f"{mode_line}"
        "        set type physical\n"
        "    next\n"
        "end\n"
    )


def test_fortios_reads_set_mode_dhcp() -> None:
    iface = _iface(get_codec("fortigate_cli").parse(_fortios("        set mode dhcp\n")), "port1")
    assert iface.dhcp_client is True


@pytest.mark.parametrize("mode_line", [
    "",
    "        set mode static\n",
    "        set mode pppoe\n",
])
def test_fortios_reads_no_dhcp_client_from_another_mode(mode_line: str) -> None:
    iface = _iface(get_codec("fortigate_cli").parse(_fortios(mode_line)), "port1")
    assert iface.dhcp_client is False


def test_fortios_reads_no_dhcp_client_from_an_ipv6_mode() -> None:
    text = _fortios("        config ipv6\n            set ip6-mode dhcp\n        end\n")
    iface = _iface(get_codec("fortigate_cli").parse(text), "port1")
    assert iface.dhcp_client is False
    assert iface.dhcp_client_v6 == "dhcp6"


# --- RouterOS: /user password= ---------------------------------------------


def test_routeros_reads_a_users_password_as_typed() -> None:
    text = "/user\nadd group=full name=ops password=Typed-Pass-1\n"
    (user,) = get_codec("mikrotik_routeros").parse(text).local_users
    assert user.name == "ops"
    assert user.hashed_password == "Typed-Pass-1"


def test_routeros_reads_a_quoted_password_whole() -> None:
    text = '/user\nadd group=read name=ops password="two words"\n'
    (user,) = get_codec("mikrotik_routeros").parse(text).local_users
    assert user.hashed_password == "two words"


def test_routeros_reads_no_password_where_the_line_has_none() -> None:
    text = "/user\nadd group=full name=ops\n"
    (user,) = get_codec("mikrotik_routeros").parse(text).local_users
    assert user.hashed_password == ""


def test_routeros_writes_and_reads_back_a_typed_password() -> None:
    codec = get_codec("mikrotik_routeros")
    tree = CanonicalIntent(local_users=[
        CanonicalLocalUser(name="ops", privilege_level=15, hashed_password="Typed-Pass-1"),
    ])
    (user,) = codec.parse(codec.render(tree)).local_users
    assert user.hashed_password == "Typed-Pass-1"


# --- RouterOS: a route whose gateway is an interface ------------------------


def _route(gateway: str) -> CanonicalStaticRoute:
    text = f"/ip route\nadd dst-address=198.51.100.0/24 gateway={gateway}\n"
    (route,) = get_codec("mikrotik_routeros").parse(text).static_routes
    return route


@pytest.mark.parametrize("gateway", ["ether1", "pppoe-out1", '"my port"'])
def test_routeros_reads_an_interface_gateway_as_the_routes_interface(gateway: str) -> None:
    route = _route(gateway)
    assert route.interface == gateway.strip('"')
    assert route.gateway == ""


@pytest.mark.parametrize("gateway", ["192.0.2.1", "2001:db8::1"])
def test_routeros_reads_an_address_gateway_as_the_gateway(gateway: str) -> None:
    route = _route(gateway)
    assert (route.gateway, route.interface) == (gateway, "")


def test_routeros_splits_an_address_pinned_to_an_interface() -> None:
    route = _route("192.0.2.1%ether1")
    assert (route.gateway, route.interface) == ("192.0.2.1", "ether1")


def test_routeros_reads_a_list_of_gateways_as_a_route_each() -> None:
    """A list is ECMP: the tree has a route for each gateway, in the
    order written, an address as its gateway and a name as its
    interface (``mikrotik_routeros/test_a_list_of_gateways.py`` has
    the rest)."""
    text = "/ip route\nadd dst-address=198.51.100.0/24 gateway=192.0.2.1,ether2\n"
    routes = get_codec("mikrotik_routeros").parse(text).static_routes
    assert [(r.destination, r.gateway, r.interface) for r in routes] == [
        ("198.51.100.0/24", "192.0.2.1", ""),
        ("198.51.100.0/24", "", "ether2"),
    ]


@pytest.mark.parametrize(
    ("gateway", "read"),
    [("192.0.2.1@main", ("192.0.2.1", "")), ("ether1@main", ("", "ether1"))],
)
def test_routeros_takes_the_main_table_off_a_gateway(gateway: str, read: tuple[str, str]) -> None:
    """``main`` is where a gateway that names no table is resolved."""
    route = _route(gateway)
    assert (route.gateway, route.interface) == read

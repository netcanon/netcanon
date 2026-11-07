"""An IOS-XE DHCP pool is read as the server hands it out, and a range
is written as the exclusions on either side of it.

Cisco, "Configuring the Cisco IOS XE DHCP Server": a pool hands out
every address of its network but those ``ip dhcp excluded-address``
names and the device's own; a directly connected client is given the
pool whose subnet is on the interface it arrived on.  The parser read
the network alone and left the range empty, so a pool that served
part of its subnet served all of it on every target that writes a
range; and the renderer wrote no exclusion, so a range from another
vendor came out as the whole subnet on IOS-XE, in jobs that said
``completed``.

Every config here is typed by hand from Cisco's syntax
(:mod:`netcanon.migration.codecs.cisco_iosxe_cli.dhcp_pools`); no
committed capture of IOS-XE has a pool.
"""

from __future__ import annotations

import time

import pytest

from netcanon.migration._tier3_detection import is_left_out_row
from netcanon.migration.canonical.intent import (
    CanonicalDHCPPool,
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalVRRPGroup,
)
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.services.migration_pipeline import run_plan

IOS = get_codec("cisco_iosxe_cli")


def _config(*stanzas: str) -> str:
    return "hostname R1\n!\n" + "!\n".join(stanzas) + "!\nend\n"


VLAN10 = "interface Vlan10\n ip address 10.0.10.1 255.255.255.0\n"
POOL10 = "ip dhcp pool USERS\n network 10.0.10.0 255.255.255.0\n default-router 10.0.10.1\n"


def _pools(text: str) -> list[tuple[str, str, str, str]]:
    return [
        (pool.interface, pool.network, pool.start_ip, pool.end_ip)
        for pool in IOS.parse(text).dhcp_servers
    ]


def _rows(text: str) -> list[str]:
    return [row for row in IOS.parse(text).dropped_tier3_sections if "dhcp" in row]


def _iface(name: str, ip: str, length: int = 24, vrf: str = "", **kw) -> CanonicalInterface:
    return CanonicalInterface(
        name=name, vrf=vrf,
        ipv4_addresses=[CanonicalIPv4Address(ip=ip, prefix_length=length)], **kw,
    )


def _tree(pools: list[CanonicalDHCPPool], interfaces: list[CanonicalInterface]) -> CanonicalIntent:
    return CanonicalIntent(
        source_vendor="juniper_junos", hostname="r1",
        interfaces=interfaces, dhcp_servers=pools,
    )


# --- the parser ---------------------------------------------------------------


class TestWhatAPoolHandsOut:
    def test_the_whole_subnet_but_the_devices_own_address(self) -> None:
        # "The IP address configured on a device interface is
        # automatically excluded from the DHCP address pool."
        assert _pools(_config(VLAN10, POOL10)) == [
            ("Vlan10", "10.0.10.0/24", "10.0.10.2", "10.0.10.254"),
        ]

    def test_what_is_excluded_is_not_handed_out(self) -> None:
        text = _config(
            "ip dhcp excluded-address 10.0.10.1 10.0.10.99\n"
            "ip dhcp excluded-address 10.0.10.201 10.0.10.254\n",
            VLAN10, POOL10,
        )
        assert _pools(text) == [("Vlan10", "10.0.10.0/24", "10.0.10.100", "10.0.10.200")]
        assert _rows(text) == []

    def test_one_excluded_address(self) -> None:
        text = _config("ip dhcp excluded-address 10.0.10.2\n", VLAN10, POOL10)
        assert _pools(text)[0][2:] == ("10.0.10.3", "10.0.10.254")

    def test_an_address_that_answers_for_a_router_is_not_handed_out(self) -> None:
        # The server pings an address before it assigns it: the default
        # router and a virtual router answer for theirs.
        text = _config(
            "interface Vlan10\n ip address 10.0.10.2 255.255.255.0\n"
            " vrrp 1 ip 10.0.10.3\n",
            "ip dhcp pool USERS\n network 10.0.10.0 255.255.255.0\n default-router 10.0.10.1\n",
        )
        assert _pools(text)[0][2:] == ("10.0.10.4", "10.0.10.254")

    def test_a_relayed_pool_is_on_no_interface(self) -> None:
        # A pool whose subnet is on none of the device's interfaces
        # serves clients a relay forwards.
        text = _config(VLAN10, "ip dhcp pool FAR\n network 192.168.50.0 255.255.255.0\n")
        assert _pools(text) == [("", "192.168.50.0/24", "192.168.50.1", "192.168.50.254")]

    @pytest.mark.parametrize(("line", "network"), [
        (" network 10.0.10.0 /24", "10.0.10.0/24"),
        (" network 10.0.10.0/24", "10.0.10.0/24"),
        (" network 10.0.0.0", "10.0.0.0/8"),          # the natural mask
        (" network 172.16.0.0", "172.16.0.0/16"),
        (" network 192.168.1.0", "192.168.1.0/24"),
    ])
    def test_every_form_of_the_network(self, line: str, network: str) -> None:
        assert _pools(_config(f"ip dhcp pool P\n{line}\n"))[0][1] == network

    def test_the_vrf_of_a_pool(self) -> None:
        # A global exclusion is not an exclusion of a pool of a VRF.
        text = _config(
            "ip dhcp excluded-address 172.16.0.1 172.16.0.200\n"
            "ip dhcp excluded-address vrf GUEST 172.16.0.1 172.16.0.9\n",
            "interface Vlan20\n vrf forwarding GUEST\n ip address 172.16.0.1 255.255.255.0\n",
            "interface Vlan21\n ip address 172.16.0.1 255.255.255.0\n",
            "ip dhcp pool GUESTS\n vrf GUEST\n network 172.16.0.0 255.255.255.0\n",
        )
        assert _pools(text) == [("Vlan20", "172.16.0.0/24", "172.16.0.10", "172.16.0.254")]

    def test_a_pool_of_a_vrf_no_interface_serves_is_said(self) -> None:
        text = _config(VLAN10, "ip dhcp pool G\n vrf GUEST\n network 10.0.10.0 255.255.255.0\n")
        assert _pools(text)[0][0] == ""
        assert any(row.startswith("ip dhcp pool vrf (in pool G:") for row in _rows(text))


class TestWhatTheTreeHasNoPlaceFor:
    def test_a_pool_split_in_two_keeps_the_larger_run(self) -> None:
        text = _config("ip dhcp excluded-address 10.0.10.100 10.0.10.109\n", VLAN10, POOL10)
        assert _pools(text)[0][2:] == ("10.0.10.110", "10.0.10.254")
        assert _rows(text) == [
            "ip dhcp pool range (in pool USERS: addresses the pool hands out outside "
            "the largest run of them; not translated)",
        ]

    def test_a_pool_with_nothing_to_hand_out_is_not_a_pool(self) -> None:
        text = _config("ip dhcp excluded-address 10.0.10.1 10.0.10.254\n", VLAN10, POOL10)
        assert _pools(text) == []
        assert [row.split(" (")[0] for row in _rows(text)] == ["ip dhcp pool excluded-address"]

    def test_a_manual_binding_is_not_a_pool(self) -> None:
        text = _config(
            VLAN10,
            "ip dhcp pool PHONE\n host 10.0.10.150 255.255.255.0\n"
            " client-identifier 0100.1122.3344.55\n",
        )
        assert _pools(text) == []
        assert [row.split(" (")[0] for row in _rows(text)] == [
            "ip dhcp pool host", "ip dhcp pool client-identifier", "ip dhcp pool network",
        ]

    def test_a_secondary_subnet_and_a_second_router(self) -> None:
        text = _config(
            VLAN10,
            "ip dhcp pool USERS\n network 10.0.10.0 255.255.255.0\n"
            " network 10.0.11.0 255.255.255.0 secondary\n"
            " default-router 10.0.10.1 10.0.10.2\n",
        )
        tree = IOS.parse(text)
        assert tree.dhcp_servers[0].network == "10.0.10.0/24"
        assert tree.dhcp_servers[0].gateway == "10.0.10.1"
        assert [row.split(" (")[0] for row in _rows(text)] == [
            "ip dhcp pool network secondary", "ip dhcp pool default-router",
        ]

    def test_a_row_names_the_kind_and_never_a_value(self) -> None:
        text = _config(VLAN10, POOL10.replace("USERS", "P1"), (
            "ip dhcp pool P2\n network 10.0.20.0 255.255.255.0\n"
            " option 150 ip 192.0.2.10\n"
        ), "ip dhcp pool P3\n network 10.0.30.0 255.255.255.0\n option 43 hex f104c0000201\n")
        rows = _rows(text)
        assert rows == ["ip dhcp pool option (in pools P2, P3: a DHCP option; not translated)"]
        assert "192.0.2.10" not in " ".join(rows) and "f104" not in " ".join(rows)

    def test_an_exclusion_in_a_form_not_read_is_said(self) -> None:
        text = _config("ip dhcp excluded-address 10.0.10.9 10.0.10.1\n", VLAN10, POOL10)
        assert any(row.startswith("ip dhcp excluded-address (1 line ") for row in _rows(text))

    def test_the_last_dns_server_line_is_the_pools(self) -> None:
        # A second ``dns-server`` line replaces the first.
        text = _config(VLAN10, POOL10 + " dns-server 198.51.100.1 198.51.100.2\n"
                       " dns-server 198.51.100.3\n")
        assert IOS.parse(text).dhcp_servers[0].dns_servers == ["198.51.100.3"]


class TestAServerThatIsOff:
    def test_no_pool_is_in_force(self) -> None:
        text = _config("no service dhcp\n", VLAN10, POOL10)
        tree = IOS.parse(text)
        assert tree.dhcp_servers == []
        rows = [row for row in tree.dropped_tier3_sections if is_left_out_row(row)]
        assert rows and all(row.startswith("disabled: ip dhcp pool USERS") for row in rows)

    def test_the_last_line_is_the_devices(self) -> None:
        text = _config("no service dhcp\nservice dhcp\n", VLAN10, POOL10)
        assert len(IOS.parse(text).dhcp_servers) == 1


# --- the renderer -------------------------------------------------------------


class TestARangeIsWrittenAsItsExclusions:
    def test_a_range_from_another_vendor(self) -> None:
        tree = _tree(
            [CanonicalDHCPPool(interface="Vlan10", network="10.0.10.0/24",
                               start_ip="10.0.10.100", end_ip="10.0.10.200",
                               gateway="10.0.10.1")],
            [_iface("Vlan10", "10.0.10.1")],
        )
        out = IOS.render(tree)
        assert [line for line in out.splitlines() if "excluded-address" in line] == [
            # The interface's own .1 is excluded by the server itself.
            "ip dhcp excluded-address 10.0.10.2 10.0.10.99",
            "ip dhcp excluded-address 10.0.10.201 10.0.10.254",
        ]
        back = IOS.parse(out).dhcp_servers[0]
        assert (back.interface, back.start_ip, back.end_ip) == ("Vlan10", "10.0.10.100", "10.0.10.200")
        assert IOS.render_warnings(tree) == []

    def test_a_pool_of_a_vrf(self) -> None:
        tree = _tree(
            [CanonicalDHCPPool(interface="Vlan20", network="172.16.0.0/24",
                               start_ip="172.16.0.10", end_ip="172.16.0.254")],
            [_iface("Vlan20", "172.16.0.1", vrf="GUEST")],
        )
        lines = IOS.render(tree).splitlines()
        stanza = lines[lines.index("ip dhcp pool Vlan20"):][:3]
        assert stanza == ["ip dhcp pool Vlan20", " vrf GUEST", " network 172.16.0.0 255.255.255.0"]
        excluded = [line for line in lines if "excluded-address" in line]
        assert excluded[0].startswith("! ip dhcp excluded-address vrf GUEST -- review:")
        assert excluded[1:] == ["ip dhcp excluded-address vrf GUEST 172.16.0.2 172.16.0.9"]
        back = IOS.parse("\n".join(lines)).dhcp_servers[0]
        assert (back.interface, back.start_ip, back.end_ip) == ("Vlan20", "172.16.0.10", "172.16.0.254")

    def test_dns_servers_go_on_one_line(self) -> None:
        tree = _tree(
            [CanonicalDHCPPool(network="10.0.10.0/24", dns_servers=["198.51.100.1", "198.51.100.2"])],
            [],
        )
        out = IOS.render(tree)
        assert " dns-server 198.51.100.1 198.51.100.2" in out.splitlines()
        assert IOS.parse(out).dhcp_servers[0].dns_servers == ["198.51.100.1", "198.51.100.2"]

    def test_a_pool_not_served_where_the_source_serves_it_is_said(self) -> None:
        tree = _tree(
            [CanonicalDHCPPool(interface="Vlan10", network="10.0.10.0/24")],
            [_iface("Vlan10", "10.9.9.1")],
        )
        assert " ! review: the source serves this pool on Vlan10;" in IOS.render(tree)
        assert len(IOS.render_warnings(tree)) == 1

    def test_a_range_outside_its_network_is_said(self) -> None:
        tree = _tree(
            [CanonicalDHCPPool(interface="Vlan10", network="10.0.10.0/24",
                               start_ip="10.0.11.1", end_ip="10.0.11.9")],
            [_iface("Vlan10", "10.0.10.1")],
        )
        out = IOS.render(tree)
        assert "excluded-address" not in out
        assert " ! review: the range 10.0.11.1-10.0.11.9 is not written:" in out
        assert len(IOS.render_warnings(tree)) == 1

    def test_a_virtual_router_is_written_as_an_exclusion(self) -> None:
        # Not the interface's own: the server does not leave it out by
        # itself, so the output says it.
        tree = _tree(
            [CanonicalDHCPPool(interface="Vlan10", network="10.0.10.0/24",
                               start_ip="10.0.10.4", end_ip="10.0.10.254")],
            [_iface("Vlan10", "10.0.10.2", vrrp_groups=[
                CanonicalVRRPGroup(group_id=1, virtual_ips=["10.0.10.1"])])],
        )
        excluded = [line for line in IOS.render(tree).splitlines() if "excluded-address" in line]
        assert excluded == ["ip dhcp excluded-address 10.0.10.1", "ip dhcp excluded-address 10.0.10.3"]


# --- through the pipeline -----------------------------------------------------


SOURCE = _config(
    "ip dhcp excluded-address 10.0.10.1 10.0.10.99\n",
    "interface GigabitEthernet1/0/1\n no switchport\n ip address 10.0.10.1 255.255.255.0\n",
    "ip dhcp pool USERS\n network 10.0.10.0 255.255.255.0\n default-router 10.0.10.1\n",
)


@pytest.mark.parametrize("target", [
    name for name in ("juniper_junos", "fortigate_cli", "opnsense", "arista_eos", "mikrotik_routeros")
    if name in list_public_codecs()
])
def test_the_range_reaches_every_target_that_writes_one(target: str) -> None:
    codec = get_codec(target)
    job = run_plan(IOS, codec, SOURCE, force=True)
    assert job.status in ("completed", "partial"), job.error
    pools = codec.parse(job.rendered or "").dhcp_servers
    assert [(p.start_ip, p.end_ip) for p in pools] == [("10.0.10.100", "10.0.10.254")]


def test_a_pool_is_read_in_time_however_many_there_are() -> None:
    # One pass over the lines, and one look at the spans of a network:
    # a config of thousands of pools and exclusions is read in time
    # that grows with its length.
    lines = []
    for n in range(2000):
        a, b = divmod(n, 250)
        lines.append(f"ip dhcp excluded-address 10.{a}.{b}.1 10.{a}.{b}.9")
    for n in range(2000):
        a, b = divmod(n, 250)
        lines += [f"ip dhcp pool P{n}", f" network 10.{a}.{b}.0 255.255.255.0", "!"]
    started = time.perf_counter()
    tree = IOS.parse("hostname R1\n" + "\n".join(lines) + "\nend\n")
    assert len(tree.dhcp_servers) == 2000
    assert time.perf_counter() - started < 20

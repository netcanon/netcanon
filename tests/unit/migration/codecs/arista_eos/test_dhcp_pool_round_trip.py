"""The EOS DHCP server, read and written in its own grammar.

Arista, *EOS User Manual*, "DHCP Server" (``eos-dhcp-overview``), and
AVD's ``dhcp-servers`` template: a ``dhcp server [vrf <name>]`` block
in column 0, its settings one level in, ``subnet <prefix>`` and the
subnet's settings a level deeper, and ``dhcp server ipv4`` under each
interface that takes part.  What the tree has no place for is a row of
the sections not translated; a subnet EOS disables is left out and
said (``netcanon/migration/codecs/arista_eos/dhcp_pools.py``).

The parser had read ``ip dhcp pool <name>``, a form no Arista page
gives, and made the pool's NAME its interface: an EOS pool reached a
RouterOS output as ``interface=<name>``, a port no device has.

Each output is read twice: by the parser, and as text by a reader of
this module's own (:func:`_blocks`), so that what the parser reads its
own way is not the only witness.
"""

from __future__ import annotations

import pytest

from netcanon.migration._tier3_detection import is_left_out_row, left_out_row
from netcanon.migration.canonical.intent import (
    CanonicalDHCPPool,
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
)
from netcanon.migration.codecs.arista_eos import AristaEOSCodec
from netcanon.migration.codecs.registry import get_codec
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

EOS = AristaEOSCodec()


def _blocks(text: str) -> dict[str, list[str]]:
    """Each line of an EOS text in column 0 and the lines indented
    under it, by the header; a header met twice keeps both bodies."""
    blocks: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in text.splitlines():
        if not line.strip():
            continue
        if line[0] not in " \t":
            current = blocks.setdefault(line.rstrip(), [])
            continue
        if current is not None:
            current.append(line.rstrip())
    return blocks


def _dhcp_rows(intent: CanonicalIntent) -> list[str]:
    return [row for row in intent.dropped_tier3_sections if "dhcp" in row.lower()]


def _iface(name: str, ip: str, length: int, vrf: str = "") -> CanonicalInterface:
    return CanonicalInterface(
        name=name, vrf=vrf, ipv4_addresses=[CanonicalIPv4Address(ip=ip, prefix_length=length)],
    )


#: A server as AVD prints it, and the interface that serves it.
SERVED = (
    "hostname sw1\n"
    "!\n"
    "dhcp server\n"
    "   dns domain name ipv4 example.net\n"
    "   !\n"
    "   subnet 192.168.10.0/24\n"
    "      !\n"
    "      range 192.168.10.100 192.168.10.200\n"
    "      dns server 192.168.10.4 192.0.2.8\n"
    "      lease time 0 days 12 hours 0 minutes\n"
    "      default-gateway 192.168.10.1\n"
    "!\n"
    "interface Ethernet1\n"
    "   no switchport\n"
    "   ip address 192.168.10.1/24\n"
    "   dhcp server ipv4\n"
    "!\n"
)

SERVED_POOL = CanonicalDHCPPool(
    interface="Ethernet1",
    network="192.168.10.0/24",
    start_ip="192.168.10.100",
    end_ip="192.168.10.200",
    gateway="192.168.10.1",
    dns_servers=["192.168.10.4", "192.0.2.8"],
    lease_time=12 * 3600,
    domain_name="example.net",
)


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


class TestParse:
    def test_a_subnet_is_a_pool_on_the_interface_that_serves_it(self):
        intent = EOS.parse(SERVED)
        assert intent.dhcp_servers == [SERVED_POOL]
        assert _dhcp_rows(intent) == []

    def test_the_manuals_lease_form_is_read_too(self):
        """The manual's subnet example writes ``lease time ipv4``; AVD
        writes ``lease time``."""
        raw = SERVED.replace(
            "lease time 0 days 12 hours 0 minutes", "lease time ipv4 3 days 0 hours 0 minutes",
        )
        assert EOS.parse(raw).dhcp_servers[0].lease_time == 3 * 86400

    def test_a_subnet_has_the_servers_settings_where_it_states_none(self):
        """"dhcp Server settings can also be configured per subnet and
        overrides the dhcp Server global mode configurations"."""
        raw = (
            "dhcp server\n"
            "   lease time ipv4 2 days 0 hours 0 minutes\n"
            "   dns server ipv4 192.0.2.53\n"
            "   !\n"
            "   subnet 10.0.1.0/24\n"
            "      range 10.0.1.10 10.0.1.20\n"
            "   !\n"
            "   subnet 10.0.2.0/24\n"
            "      range 10.0.2.10 10.0.2.20\n"
            "      dns server 192.0.2.54\n"
            "      lease time 0 days 1 hours 0 minutes\n"
            "!\n"
        )
        first, second = EOS.parse(raw).dhcp_servers
        assert (first.dns_servers, first.lease_time) == (["192.0.2.53"], 2 * 86400)
        assert (second.dns_servers, second.lease_time) == (["192.0.2.54"], 3600)

    def test_no_lease_anywhere_is_one_day_and_said(self):
        raw = "dhcp server\n   subnet 10.0.1.0/24\n      range 10.0.1.10 10.0.1.20\n!\n"
        intent = EOS.parse(raw)
        assert intent.dhcp_servers[0].lease_time == 86400
        rows = _dhcp_rows(intent)
        assert len(rows) == 1 and rows[0].startswith("dhcp server subnet lease time (in subnet 10.0.1.0/24")
        assert "not established" in rows[0]

    def test_an_interface_without_the_line_serves_nothing(self):
        """A subnet no interface with ``dhcp server ipv4`` holds an
        address of is served to relayed clients only: the pool has no
        interface."""
        raw = SERVED.replace("   dhcp server ipv4\n", "")
        assert EOS.parse(raw).dhcp_servers == [SERVED_POOL.model_copy(update={"interface": ""})]

    def test_a_vrf_server_is_served_in_its_vrf(self):
        raw = (
            "vrf instance RED\n"
            "!\n"
            "dhcp server vrf RED\n"
            "   lease time ipv4 1 days 0 hours 0 minutes\n"
            "   subnet 10.1.0.0/24\n"
            "      range 10.1.0.10 10.1.0.20\n"
            "!\n"
            "dhcp server\n"
            "   lease time ipv4 1 days 0 hours 0 minutes\n"
            "   subnet 10.1.0.0/24\n"
            "      range 10.1.0.30 10.1.0.40\n"
            "!\n"
            "interface Vlan10\n"
            "   vrf RED\n"
            "   ip address 10.1.0.1/24\n"
            "   dhcp server ipv4\n"
            "!\n"
        )
        intent = EOS.parse(raw)
        red, default = intent.dhcp_servers
        assert (red.start_ip, red.interface) == ("10.1.0.10", "Vlan10")
        # An interface in another VRF does not serve the default VRF's subnet.
        assert (default.start_ip, default.interface) == ("10.1.0.30", "")
        assert _dhcp_rows(intent) == []

    def test_a_vrf_subnet_that_no_interface_of_the_vrf_serves_is_said(self):
        raw = "dhcp server vrf BLUE\n   subnet 10.2.0.0/24\n      range 10.2.0.10 10.2.0.20\n" \
              "      lease time 1 days 0 hours 0 minutes\n!\n"
        intent = EOS.parse(raw)
        assert intent.dhcp_servers[0].interface == ""
        rows = _dhcp_rows(intent)
        assert len(rows) == 1
        assert rows[0].startswith("dhcp server subnet vrf (in subnet 10.2.0.0/24 of VRF BLUE:")

    def test_one_prefix_in_two_servers_is_named_with_its_vrf(self):
        raw = (
            "dhcp server vrf RED\n   subnet 10.1.0.0/24\n      range 10.1.0.10 10.1.0.20\n!\n"
            "dhcp server\n   subnet 10.1.0.0/24\n      range 10.1.0.30 10.1.0.40\n!\n"
        )
        rows = [row for row in _dhcp_rows(EOS.parse(raw)) if row.startswith("dhcp server subnet lease time")]
        assert len(rows) == 1 and "(in subnets 10.1.0.0/24 of VRF RED, 10.1.0.0/24:" in rows[0]

    def test_ranges_that_meet_are_one_run(self):
        raw = (
            "dhcp server\n   subnet 10.3.0.0/24\n"
            "      !\n      range 10.3.0.10 10.3.0.20\n"
            "      !\n      range 10.3.0.21 10.3.0.30\n"
            "      lease time 1 days 0 hours 0 minutes\n!\n"
        )
        intent = EOS.parse(raw)
        pool = intent.dhcp_servers[0]
        assert (pool.start_ip, pool.end_ip) == ("10.3.0.10", "10.3.0.30")
        assert _dhcp_rows(intent) == []

    def test_a_run_apart_is_said_and_the_largest_is_kept(self):
        raw = (
            "dhcp server\n   subnet 10.3.0.0/24\n"
            "      !\n      range 10.3.0.50 10.3.0.55\n"
            "      !\n      range 10.3.0.10 10.3.0.30\n"
            "      lease time 1 days 0 hours 0 minutes\n!\n"
        )
        intent = EOS.parse(raw)
        pool = intent.dhcp_servers[0]
        assert (pool.start_ip, pool.end_ip) == ("10.3.0.10", "10.3.0.30")
        rows = _dhcp_rows(intent)
        assert len(rows) == 1 and rows[0].startswith("dhcp server subnet range (in subnet 10.3.0.0/24")

    def test_a_subnet_two_interfaces_serve_is_put_on_the_first_and_said(self):
        raw = (
            "dhcp server\n   subnet 10.4.0.0/16\n      range 10.4.0.10 10.4.0.20\n"
            "      lease time 1 days 0 hours 0 minutes\n!\n"
            "interface Ethernet2\n   no switchport\n   ip address 10.4.1.1/24\n   dhcp server ipv4\n!\n"
            "interface Ethernet1\n   no switchport\n   ip address 10.4.0.1/24\n   dhcp server ipv4\n!\n"
        )
        intent = EOS.parse(raw)
        assert intent.dhcp_servers[0].interface == "Ethernet2"
        rows = _dhcp_rows(intent)
        assert len(rows) == 1 and rows[0].startswith("dhcp server subnet interface (in subnet 10.4.0.0/16")

    def test_a_subnet_with_no_range_is_no_pool_and_said(self):
        raw = "dhcp server\n   subnet 10.5.0.0/24\n      default-gateway 10.5.0.1\n!\n"
        intent = EOS.parse(raw)
        assert intent.dhcp_servers == []
        assert any(row.startswith("dhcp server subnet no range (in subnet 10.5.0.0/24") for row in _dhcp_rows(intent))

    def test_a_server_or_a_subnet_entered_again_is_the_same_one(self):
        raw = (
            "dhcp server\n   subnet 10.6.0.0/24\n      range 10.6.0.10 10.6.0.20\n!\n"
            "dhcp server\n   lease time ipv4 1 days 0 hours 0 minutes\n"
            "   subnet 10.6.0.0/24\n      default-gateway 10.6.0.1\n!\n"
        )
        (pool,) = EOS.parse(raw).dhcp_servers
        assert (pool.start_ip, pool.gateway, pool.lease_time) == ("10.6.0.10", "10.6.0.1", 86400)

    def test_what_the_tree_has_no_place_for_is_a_row_that_quotes_no_value(self):
        raw = (
            "dhcp server\n"
            "   tftp server option 66 ipv4 192.0.2.9\n"
            "   dns server ipv6 2001:db8::53\n"
            "   !\n"
            "   subnet 10.7.0.0/24\n"
            "      reservations\n"
            "         mac-address 0000.5e00.5301\n"
            "            ipv4-address 10.7.0.7\n"
            "      !\n"
            "      range 10.7.0.10 10.7.0.20\n"
            "      tftp server file bootfile.bin\n"
            "      lease time 1 days 0 hours 0 minutes\n"
            "   !\n"
            "   subnet 2001:db8:1::/64\n"
            "      range 2001:db8:1::10 2001:db8:1::20\n"
            "   !\n"
            "   vendor-option ipv4 VENDORX\n"
            "      sub-option 1 type string data \"vendorvalue\"\n"
            "!\n"
        )
        intent = EOS.parse(raw)
        (pool,) = intent.dhcp_servers
        assert (pool.start_ip, pool.end_ip) == ("10.7.0.10", "10.7.0.20")
        rows = _dhcp_rows(intent)
        heads = sorted(row.split(" (", 1)[0] for row in rows)
        assert heads == [
            "dhcp server ipv6", "dhcp server subnet reservations", "dhcp server subnet tftp server",
            "dhcp server tftp server", "dhcp server vendor-option",
        ]
        for value in ("10.7.0.7", "0000.5e00", "192.0.2.9", "bootfile", "VENDORX", "vendorvalue", "2001:db8"):
            assert not any(value in row for row in rows), value
        assert not any(is_left_out_row(row) for row in rows)

    def test_ip_dhcp_pool_is_not_read_as_a_pool(self):
        """No Arista page gives ``ip dhcp pool``; its name was once
        taken for the pool's interface."""
        raw = (
            "ip dhcp pool OLD\n   network 10.8.0.0 255.255.255.0\n   default-router 10.8.0.1\n!\n"
            "interface Vlan8\n   ip address 10.8.0.1/24\n!\n"
        )
        intent = EOS.parse(raw)
        assert intent.dhcp_servers == []
        rows = _dhcp_rows(intent)
        assert len(rows) == 1 and rows[0].startswith("ip dhcp pool (in pool OLD: no form of EOS's DHCP server")


class TestLeftOut:
    """A subnet that is not in force is left out and said."""

    def test_a_disabled_server(self):
        raw = (
            "dhcp server\n   disabled\n   subnet 10.9.0.0/24\n      range 10.9.0.10 10.9.0.20\n!\n"
            "dhcp server vrf RED\n   disabled\n!\n"
        )
        intent = EOS.parse(raw)
        assert intent.dhcp_servers == []
        rows = _dhcp_rows(intent)
        assert left_out_row("disabled", ["dhcp", "server", "subnet", "10.9.0.0/24"]) in rows
        assert left_out_row("disabled", ["dhcp", "server", "vrf", "RED"]) in rows
        assert all(is_left_out_row(row) for row in rows)

    @pytest.mark.parametrize(
        "body",
        [
            # "The range must be within the subnet mask, otherwise the
            # subnet becomes disabled".
            "      range 10.9.0.10 10.9.1.20\n",
            # A range over another.
            "      !\n      range 10.9.0.10 10.9.0.20\n      !\n      range 10.9.0.15 10.9.0.30\n",
            # An address reserved twice.
            "      reservations\n"
            "         mac-address 0000.5e00.5301\n            ipv4-address 10.9.0.7\n"
            "         !\n"
            "         mac-address 0000.5e00.5302\n            ipv4-address 10.9.0.7\n"
            "      !\n      range 10.9.0.10 10.9.0.20\n",
        ],
        ids=["range outside", "ranges overlap", "reserved twice"],
    )
    def test_a_subnet_eos_disables(self, body: str):
        raw = f"dhcp server\n   subnet 10.9.0.0/24\n{body}!\n"
        intent = EOS.parse(raw)
        assert intent.dhcp_servers == []
        assert _dhcp_rows(intent) == [
            left_out_row("disabled-subnet", ["dhcp", "server", "subnet", "10.9.0.0/24"]),
        ]

    def test_subnets_that_overlap(self):
        """"EOS disables overlapping subnets": both, and the one beside
        them is a pool."""
        raw = (
            "dhcp server\n"
            "   subnet 10.9.0.0/24\n      range 10.9.0.10 10.9.0.20\n"
            "   subnet 10.9.0.0/25\n      range 10.9.0.30 10.9.0.40\n"
            "   subnet 10.9.1.0/24\n      range 10.9.1.10 10.9.1.20\n"
            "      lease time 1 days 0 hours 0 minutes\n"
            "!\n"
        )
        intent = EOS.parse(raw)
        assert [pool.network for pool in intent.dhcp_servers] == ["10.9.1.0/24"]
        rows = _dhcp_rows(intent)
        for prefix in ("10.9.0.0/24", "10.9.0.0/25"):
            assert left_out_row("disabled-subnet", ["dhcp", "server", "subnet", prefix]) in rows


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def _render(pools: list[CanonicalDHCPPool], interfaces: list[CanonicalInterface]) -> tuple[str, list[str]]:
    tree = CanonicalIntent(source_vendor="test", source_format="test", dhcp_servers=pools, interfaces=interfaces)
    warnings = [w for w in EOS.render_warnings(tree) if w.startswith("EOS DHCP pool")]
    return EOS.render(tree), warnings


def _reviews(text: str) -> list[str]:
    return [line.strip() for header, body in _blocks(text).items() if header.startswith("dhcp server")
            for line in body if line.strip().startswith("! review:")]


class TestRender:
    def test_the_server_is_written_as_avd_prints_it(self):
        text = EOS.render(EOS.parse(SERVED))
        blocks = _blocks(text)
        assert blocks["dhcp server"] == [
            line.rstrip() for line in SERVED.splitlines()[3:11]
        ]
        assert "   dhcp server ipv4" in blocks["interface Ethernet1"]

    def test_a_pool_is_a_subnet_of_the_server_of_its_interfaces_vrf(self):
        pool = CanonicalDHCPPool(
            interface="Vlan100", network="10.100.0.0/24", start_ip="10.100.0.100",
            end_ip="10.100.0.200", lease_time=86400,
        )
        text, warnings = _render([pool], [_iface("Vlan100", "10.100.0.1", 24, vrf="TENANT_A")])
        blocks = _blocks(text)
        assert "dhcp server" not in blocks
        assert "   subnet 10.100.0.0/24" in blocks["dhcp server vrf TENANT_A"]
        assert "   dhcp server ipv4" in blocks["interface Vlan100"]
        assert warnings == []

    def test_a_domain_is_written_for_the_server_where_every_subnet_has_it(self):
        pools = [
            CanonicalDHCPPool(network=f"10.0.{n}.0/24", start_ip=f"10.0.{n}.10", end_ip=f"10.0.{n}.20",
                              domain_name="example.net")
            for n in (1, 2)
        ]
        text, warnings = _render(pools, [])
        assert _blocks(text)["dhcp server"][0] == "   dns domain name ipv4 example.net"
        assert warnings == []

    def test_a_domain_not_every_subnet_has_is_a_review(self):
        pools = [
            CanonicalDHCPPool(network="10.0.1.0/24", start_ip="10.0.1.10", end_ip="10.0.1.20",
                              domain_name="example.net"),
            CanonicalDHCPPool(network="10.0.2.0/24", start_ip="10.0.2.10", end_ip="10.0.2.20"),
        ]
        text, warnings = _render(pools, [])
        assert not any("dns domain name" in line for line in _blocks(text)["dhcp server"])
        reviews = _reviews(text)
        assert len(reviews) == 1 and "the domain example.net is not written" in reviews[0]
        assert len(warnings) == 1

    def test_dns_servers_past_two_are_a_review(self):
        pool = CanonicalDHCPPool(network="10.0.1.0/24", start_ip="10.0.1.10", end_ip="10.0.1.20",
                                 dns_servers=["192.0.2.1", "192.0.2.2", "192.0.2.3"])
        text, warnings = _render([pool], [])
        assert "      dns server 192.0.2.1 192.0.2.2" in _blocks(text)["dhcp server"]
        assert "192.0.2.3" not in text
        assert len(_reviews(text)) == len(warnings) == 1

    @pytest.mark.parametrize("lease", [0xFFFFFFFF, 2001 * 86400], ids=["infinite", "too long"])
    def test_a_lease_eos_takes_no_form_of_is_a_review(self, lease: int):
        pool = CanonicalDHCPPool(network="10.0.1.0/24", start_ip="10.0.1.10", end_ip="10.0.1.20",
                                 lease_time=lease)
        text, warnings = _render([pool], [])
        assert not any(line.strip().startswith("lease time") for line in _blocks(text)["dhcp server"])
        assert len(_reviews(text)) == len(warnings) == 1

    def test_a_lease_under_a_minute_is_one_minute_and_stable(self):
        pool = CanonicalDHCPPool(network="10.0.1.0/24", start_ip="10.0.1.10", end_ip="10.0.1.20",
                                 lease_time=30)
        text, _ = _render([pool], [])
        assert "      lease time 0 days 0 hours 1 minutes" in _blocks(text)["dhcp server"]
        again = EOS.parse(text)
        assert again.dhcp_servers[0].lease_time == 60
        assert EOS.render(again) == text

    def test_a_pool_that_states_no_range_hands_out_the_hosts_less_the_outputs_own(self):
        pool = CanonicalDHCPPool(interface="Vlan10", network="10.0.0.0/24")
        text, warnings = _render([pool], [_iface("Vlan10", "10.0.0.1", 24)])
        body = _blocks(text)["dhcp server"]
        assert "      range 10.0.0.2 10.0.0.254" in body
        assert len(_reviews(text)) == len(warnings) == 1
        assert "   dhcp server ipv4" in _blocks(text)["interface Vlan10"]

    def test_a_range_outside_its_network_is_a_review(self):
        pool = CanonicalDHCPPool(network="10.0.1.0/24", start_ip="10.0.1.10", end_ip="10.0.2.20")
        text, warnings = _render([pool], [])
        assert not any(line.strip().startswith("range") for line in _blocks(text)["dhcp server"])
        assert len(_reviews(text)) == len(warnings) == 1

    @pytest.mark.parametrize(
        "interfaces, why",
        [([], "this output has no interface Vlan10"),
         ([_iface("Vlan10", "10.9.9.1", 24)], "Vlan10 has no address in 10.0.0.0/24")],
        ids=["no such interface", "no address in it"],
    )
    def test_an_interface_that_cannot_serve_the_pool_is_a_review(self, interfaces, why):
        pool = CanonicalDHCPPool(interface="Vlan10", network="10.0.0.0/24", start_ip="10.0.0.10",
                                 end_ip="10.0.0.20")
        text, warnings = _render([pool], interfaces)
        assert not any(line.strip() == "dhcp server ipv4" for body in _blocks(text).values() for line in body)
        reviews = _reviews(text)
        assert len(reviews) == len(warnings) == 1 and why in reviews[0]

    @pytest.mark.parametrize("holder_first", [True, False])
    def test_a_name_two_interfaces_were_put_under_is_served_where_the_address_is(self, holder_first):
        # A translation can put two source interfaces under one name (the
        # job is ``partial`` for it); the pool is on the one of them that
        # holds an address of its network, whichever comes first.
        holder = _iface("Ethernet1", "10.0.0.1", 24)
        other = _iface("Ethernet1", "10.9.0.1", 24)
        pool = CanonicalDHCPPool(interface="Ethernet1", network="10.0.0.0/24", start_ip="10.0.0.10",
                                 end_ip="10.0.0.20")
        text, warnings = _render([pool], [holder, other] if holder_first else [other, holder])
        assert any(line == "   dhcp server ipv4" for line in text.splitlines())
        assert _reviews(text) == [] and warnings == []
        back = EOS.parse(text)
        assert [(p.network, p.interface) for p in back.dhcp_servers] == [("10.0.0.0/24", "Ethernet1")]

    def test_a_pool_with_no_network_or_over_another_is_not_written(self):
        pools = [
            CanonicalDHCPPool(interface="Vlan10"),
            CanonicalDHCPPool(network="10.0.0.0/24", start_ip="10.0.0.10", end_ip="10.0.0.20"),
            CanonicalDHCPPool(network="10.0.0.0/25", start_ip="10.0.0.30", end_ip="10.0.0.40"),
        ]
        text, warnings = _render(pools, [])
        subnets = [line for line in _blocks(text)["dhcp server"] if line.strip().startswith("subnet")]
        assert subnets == ["   subnet 10.0.0.0/24"]
        assert len(_reviews(text)) == len(warnings) == 2


# ---------------------------------------------------------------------------
# Round trips
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_eos_to_eos_keeps_every_field(self):
        first = EOS.parse(SERVED)
        assert EOS.parse(EOS.render(first)).dhcp_servers == first.dhcp_servers == [SERVED_POOL]

    def test_an_ios_xe_pool_is_a_subnet_served_on_its_interface(self):
        source = (
            "hostname r1\n!\n"
            "interface Vlan10\n ip address 10.0.0.1 255.255.255.0\n!\n"
            "ip dhcp pool USERS\n network 10.0.0.0 255.255.255.0\n default-router 10.0.0.1\n"
            " dns-server 10.0.0.4\n domain-name corp.local\n lease 1\n!\n"
        )
        job = run_plan_with_checked_names(
            get_codec("cisco_iosxe_cli"), EOS, source, port_rename_map={},
        )
        assert job.status.value == "completed"
        blocks = _blocks(job.rendered)
        assert "   subnet 10.0.0.0/24" in blocks["dhcp server"]
        assert "   dhcp server ipv4" in blocks["interface Vlan10"]
        assert "USERS" not in job.rendered
        (pool,) = EOS.parse(job.rendered).dhcp_servers
        assert (pool.interface, pool.gateway, pool.dns_servers, pool.domain_name, pool.lease_time) == (
            "Vlan10", "10.0.0.1", ["10.0.0.4"], "corp.local", 86400,
        )

    def test_an_eos_pool_reaches_routeros_on_the_port_that_holds_its_address(self):
        """The RouterOS server's ``interface=`` is the port the output
        puts the source's address on, read from the text."""
        job = run_plan_with_checked_names(EOS, get_codec("mikrotik_routeros"), SERVED, port_rename_map={})
        lines = job.rendered.splitlines()
        (address,) = [line for line in lines if "address=192.168.10.1/24" in line]
        port = address.split("interface=", 1)[1].split()[0]
        (server,) = [line for line in lines if "address-pool=" in line]
        assert f"interface={port}" in server.split()

    def test_a_range_that_begins_at_the_gateway_comes_back_from_ios_xe_without_it(self):
        """IOS-XE hands out a pool's network less its default router, so an
        EOS range that begins at the gateway comes back one address
        shorter: the loss the ``arista_eos__cisco_iosxe_cli`` expectation
        names, which no committed capture shows."""
        source = (
            "hostname sw1\n!\n"
            "dhcp server\n"
            "   subnet 10.0.0.0/24\n"
            "      range 10.0.0.1 10.0.0.100\n"
            "      default-gateway 10.0.0.1\n"
            "!\n"
            "interface Ethernet1\n"
            "   no switchport\n"
            "   ip address 10.0.0.254/24\n"
            "   dhcp server ipv4\n"
            "!\n"
        )
        ios = get_codec("cisco_iosxe_cli")
        (pool,) = EOS.parse(source).dhcp_servers
        assert (pool.start_ip, pool.end_ip) == ("10.0.0.1", "10.0.0.100")
        (back,) = ios.parse(ios.render(EOS.parse(source))).dhcp_servers
        assert (back.interface, back.gateway, back.start_ip, back.end_ip) == (
            "Ethernet1", "10.0.0.1", "10.0.0.2", "10.0.0.100",
        )

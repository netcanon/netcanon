"""A FortiOS DHCP server is read as it hands addresses out.

The parser kept the first ``ip-range`` of a pool and nothing else: a
second range, every ``exclude-range`` and the pool's ``dns-service``
were read as nothing, a pool that is not in force was translated as
live, a ``dns-server`` of ``0.0.0.0`` was a DNS server, and none of it
was said.  Each test states what Fortinet's CLI reference and
administration guide say the server does (see the docstring of
``fortigate_cli/dhcp_pools.py``) and asks the tree for it.
"""

from __future__ import annotations

import textwrap

import pytest

from netcanon.migration._tier3_detection import is_left_out_row
from netcanon.migration.canonical.intent import (
    CanonicalDHCPPool,
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
)
from netcanon.migration.codecs.fortigate_cli import FortiGateCLICodec
from netcanon.migration.codecs.fortigate_cli.dhcp_pools import DEFAULT_LEASE, INFINITE_LEASE

pytestmark = pytest.mark.unit

_INTERFACE = """\
config system interface
    edit "port2"
        set ip 192.0.2.1 255.255.255.0
    next
    edit "port3"
    next
end
"""


def _parse(pool_body: str, *, before: str = _INTERFACE, after: str = "") -> CanonicalIntent:
    """A config of *before*, one DHCP server whose ``edit 1`` holds
    *pool_body*, and *after*."""
    body = textwrap.indent(textwrap.dedent(pool_body).strip("\n"), " " * 8)
    raw = (
        before
        + "config system dhcp server\n    edit 1\n"
        + body
        + "\n    next\nend\n"
        + after
    )
    return FortiGateCLICodec().parse(raw)


def _pool_rows(tree: CanonicalIntent) -> list[str]:
    return [row for row in tree.dropped_tier3_sections if "dhcp server" in row]


def _ranges(*spans: tuple[str, str], table: str = "ip-range") -> str:
    entries = "".join(
        f"    edit {n}\n        set start-ip {low}\n        set end-ip {high}\n    next\n"
        for n, (low, high) in enumerate(spans, start=1)
    )
    return f"config {table}\n{entries}end\n"


_HEAD = """\
set default-gateway 192.0.2.1
set netmask 255.255.255.0
set interface "port2"
"""


class TestTheAddressesItHandsOut:
    def test_two_ranges_keep_the_larger_and_say_the_other(self) -> None:
        # The administration guide's own shape: a range on either side
        # of the default gateway.
        tree = _parse(
            _HEAD + _ranges(("192.0.2.2", "192.0.2.99"), ("192.0.2.101", "192.0.2.200"))
        )
        (pool,) = tree.dhcp_servers
        assert (pool.start_ip, pool.end_ip) == ("192.0.2.101", "192.0.2.200")
        assert pool.network == "192.0.2.0/24"
        (row,) = _pool_rows(tree)
        assert row.startswith("config system dhcp server edit 1: config ip-range -- ")
        assert "outside the largest run" in row
        assert row.endswith("; not translated")

    def test_of_two_as_large_the_lower_is_kept(self) -> None:
        tree = _parse(
            _HEAD + _ranges(("192.0.2.151", "192.0.2.200"), ("192.0.2.51", "192.0.2.100"))
        )
        (pool,) = tree.dhcp_servers
        assert (pool.start_ip, pool.end_ip) == ("192.0.2.51", "192.0.2.100")

    def test_ranges_that_overlap_or_touch_are_one_run(self) -> None:
        tree = _parse(
            _HEAD
            + _ranges(
                ("192.0.2.10", "192.0.2.50"), ("192.0.2.40", "192.0.2.80"),
                ("192.0.2.81", "192.0.2.90"),
            )
        )
        (pool,) = tree.dhcp_servers
        assert (pool.start_ip, pool.end_ip) == ("192.0.2.10", "192.0.2.90")
        assert _pool_rows(tree) == []

    def test_an_excluded_range_inside_splits_the_run(self) -> None:
        tree = _parse(
            _HEAD
            + _ranges(("192.0.2.10", "192.0.2.200"))
            + _ranges(("192.0.2.50", "192.0.2.59"), table="exclude-range")
        )
        (pool,) = tree.dhcp_servers
        assert (pool.start_ip, pool.end_ip) == ("192.0.2.60", "192.0.2.200")
        assert len(_pool_rows(tree)) == 1

    def test_an_excluded_range_at_an_end_shortens_it(self) -> None:
        tree = _parse(
            _HEAD
            + _ranges(("192.0.2.10", "192.0.2.200"))
            + _ranges(("192.0.2.5", "192.0.2.19"), ("192.0.2.190", "192.0.2.250"),
                      table="exclude-range")
        )
        (pool,) = tree.dhcp_servers
        assert (pool.start_ip, pool.end_ip) == ("192.0.2.20", "192.0.2.189")
        assert _pool_rows(tree) == []

    def test_one_excluded_range_over_two_ranges(self) -> None:
        tree = _parse(
            _HEAD
            + _ranges(("192.0.2.10", "192.0.2.40"), ("192.0.2.60", "192.0.2.200"))
            + _ranges(("192.0.2.30", "192.0.2.70"), table="exclude-range")
        )
        (pool,) = tree.dhcp_servers
        assert (pool.start_ip, pool.end_ip) == ("192.0.2.71", "192.0.2.200")

    @pytest.mark.parametrize(
        "ranges",
        [
            pytest.param("", id="no range"),
            pytest.param(
                _ranges(("192.0.2.10", "192.0.2.200"))
                + _ranges(("192.0.2.1", "192.0.2.254"), table="exclude-range"),
                id="every address excluded",
            ),
            pytest.param(_ranges(("0.0.0.0", "0.0.0.0")), id="a range of no address"),
        ],
    )
    def test_a_pool_that_hands_out_nothing_from_a_range_is_said(self, ranges: str) -> None:
        # A target given a pool with no range hands out its whole
        # network, so such a pool is not translated.
        tree = _parse(_HEAD + ranges)
        assert tree.dhcp_servers == []
        assert any(
            "config ip-range -- a pool that hands out no address from a range" in row
            and row.endswith("so the pool is not translated")
            for row in _pool_rows(tree)
        )

    def test_a_pool_by_user_group_is_said(self) -> None:
        tree = _parse(_HEAD + "set ip-mode usrgrp\n")
        assert tree.dhcp_servers == []
        (row,) = _pool_rows(tree)
        assert "set ip-mode usrgrp -- " in row
        assert row.endswith("so the pool is not translated")

    def test_a_pool_not_in_force_is_left_out_and_said(self) -> None:
        tree = _parse(_HEAD + "set status disable\n" + _ranges(("192.0.2.10", "192.0.2.20")))
        assert tree.dhcp_servers == []
        (row,) = _pool_rows(tree)
        assert is_left_out_row(row)
        assert row.startswith("disabled: config system dhcp server edit 1 (")


class TestWhatItGivesAClient:
    def test_dns_service_local_is_the_interfaces_address(self) -> None:
        tree = _parse(_HEAD + "set dns-service local\n" + _ranges(("192.0.2.10", "192.0.2.20")))
        assert tree.dhcp_servers[0].dns_servers == ["192.0.2.1"]
        assert _pool_rows(tree) == []

    def test_dns_service_local_on_an_interface_with_no_address_is_said(self) -> None:
        tree = _parse(
            'set interface "port3"\nset netmask 255.255.255.0\nset default-gateway 192.0.2.1\n'
            "set dns-service local\n" + _ranges(("192.0.2.10", "192.0.2.20"))
        )
        assert tree.dhcp_servers[0].dns_servers == []
        assert any("set dns-service local -- " in row for row in _pool_rows(tree))

    def test_dns_service_default_is_the_fortigates_own_stated_after_it(self) -> None:
        tree = _parse(
            _HEAD + "set dns-service default\n" + _ranges(("192.0.2.10", "192.0.2.20")),
            after="config system dns\n    set primary 198.51.100.53\n"
            "    set secondary 203.0.113.53\nend\n",
        )
        assert tree.dhcp_servers[0].dns_servers == ["198.51.100.53", "203.0.113.53"]
        assert _pool_rows(tree) == []

    @pytest.mark.parametrize(
        "system_dns",
        [
            pytest.param("", id="none stated"),
            pytest.param("config system dns\n    set primary 198.51.100.53\nend\n", id="one stated"),
        ],
    )
    def test_dns_service_default_the_config_does_not_state_is_said(self, system_dns: str) -> None:
        # A FortiGate does not print a DNS server it has by default.
        tree = _parse(
            _HEAD + "set dns-service default\n" + _ranges(("192.0.2.10", "192.0.2.20")),
            before=_INTERFACE + system_dns,
        )
        assert tree.dhcp_servers[0].dns_servers == (["198.51.100.53"] if system_dns else [])
        assert any("set dns-service default -- " in row for row in _pool_rows(tree))

    def test_specify_skips_an_unset_server(self) -> None:
        tree = _parse(
            _HEAD
            + "set dns-server1 0.0.0.0\nset dns-server2 198.51.100.53\nset dns-server3 0.0.0.0\n"
            + _ranges(("192.0.2.10", "192.0.2.20"))
        )
        assert tree.dhcp_servers[0].dns_servers == ["198.51.100.53"]

    def test_specify_reads_a_fourth_server(self) -> None:
        tree = _parse(
            _HEAD
            + "".join(f"set dns-server{n} 198.51.100.{n}\n" for n in range(1, 5))
            + _ranges(("192.0.2.10", "192.0.2.20"))
        )
        assert tree.dhcp_servers[0].dns_servers == [f"198.51.100.{n}" for n in range(1, 5)]

    @pytest.mark.parametrize(
        ("line", "lease"),
        [
            pytest.param("", DEFAULT_LEASE, id="not stated"),
            pytest.param("set lease-time 0\n", INFINITE_LEASE, id="0 is unlimited"),
            pytest.param("set lease-time 3600\n", 3600, id="stated"),
        ],
    )
    def test_the_lease(self, line: str, lease: int) -> None:
        tree = _parse(_HEAD + line + _ranges(("192.0.2.10", "192.0.2.20")))
        assert tree.dhcp_servers[0].lease_time == lease

    def test_no_gateway_and_no_netmask_are_said(self) -> None:
        tree = _parse(
            'set interface "port2"\nset default-gateway 0.0.0.0\n'
            + _ranges(("192.0.2.10", "192.0.2.20"))
        )
        (pool,) = tree.dhcp_servers
        assert (pool.gateway, pool.network) == ("", "")
        rows = _pool_rows(tree)
        assert any("set default-gateway -- " in row for row in rows)
        assert any("set netmask -- " in row for row in rows)


class TestWhatTheTreeHasNoPlaceFor:
    @pytest.mark.parametrize(
        ("lines", "head"),
        [
            pytest.param(
                "config reserved-address\n    edit 1\n        set ip 192.0.2.15\n"
                "        set mac 00:00:5e:00:53:01\n    next\nend\n",
                "config reserved-address",
                id="reserved-address",
            ),
            pytest.param(
                "config options\n    edit 1\n        set code 66\n"
                '        set type string\n        set value "boot.example"\n    next\nend\n',
                "config options",
                id="options",
            ),
            pytest.param(
                'set vci-match enable\nset vci-string "vendor-class"\n',
                "set vci-match enable",
                id="vci-match",
            ),
            pytest.param("set ntp-service local\n", "set ntp-service", id="ntp local"),
            pytest.param("set ntp-server1 198.51.100.123\n", "set ntp-service", id="ntp specify"),
            pytest.param("set wins-server1 198.51.100.137\n", "set wins-server", id="wins"),
            pytest.param("set next-server 198.51.100.69\n", "set next-server", id="boot"),
            pytest.param("set mac-acl-default-action block\n", "set mac-acl-default-action",
                         id="mac-acl"),
        ],
    )
    def test_a_row_names_the_kind_and_the_pool_is_kept(self, lines: str, head: str) -> None:
        tree = _parse(_HEAD + lines + _ranges(("192.0.2.10", "192.0.2.200")))
        assert len(tree.dhcp_servers) == 1
        (row,) = _pool_rows(tree)
        assert row.startswith(f"config system dhcp server edit 1: {head}")
        assert row.endswith("; not translated")
        assert "192.0.2.15" not in row
        assert "198.51.100" not in row
        assert "vendor-class" not in row
        assert "boot.example" not in row

    def test_what_changes_nothing_a_client_is_given_raises_no_row(self) -> None:
        tree = _parse(
            _HEAD
            + "set ntp-service specify\nset ntp-server1 0.0.0.0\nset vci-match disable\n"
            + "set mac-acl-default-action assign\nset timezone-option disable\n"
            + "set auto-configuration enable\nset conflicted-ip-timeout 1800\n"
            + _ranges(("192.0.2.10", "192.0.2.200"))
        )
        assert len(tree.dhcp_servers) == 1
        assert _pool_rows(tree) == []

    def test_a_setting_it_does_not_know_is_named_by_its_key_never_its_value(self) -> None:
        tree = _parse(
            _HEAD
            + 'set made-up-setting "do-not-show-me"\nset lease-time forever\n'
            + "config made-up-table\n    edit 1\n        set word quiet-please\n    next\nend\n"
            + _ranges(("192.0.2.10", "192.0.2.200"))
        )
        (pool,) = tree.dhcp_servers
        assert pool.lease_time == DEFAULT_LEASE
        rows = _pool_rows(tree)
        settings = [row for row in rows if "a setting this parser does not read" in row]
        tables = [row for row in rows if "a table this parser does not read" in row]
        assert len(settings) == 1 and len(tables) == 1
        assert "made-up-setting" in settings[0] and "lease-time" in settings[0]
        assert "made-up-table" in tables[0]
        for row in rows:
            assert "do-not-show-me" not in row
            assert "forever" not in row
            assert "quiet-please" not in row

    def test_many_pools_share_one_row_a_kind(self) -> None:
        edits = "".join(
            f"    edit {n}\n"
            f"        set interface \"port2\"\n        set netmask 255.255.255.0\n"
            f"        set default-gateway 192.0.2.1\n        set ntp-service local\n"
            f"        config ip-range\n            edit 1\n"
            f"                set start-ip 192.0.2.{n}\n                set end-ip 192.0.2.{n}\n"
            f"            next\n        end\n    next\n"
            for n in range(10, 40)
        )
        tree = FortiGateCLICodec().parse(_INTERFACE + f"config system dhcp server\n{edits}end\n")
        assert len(tree.dhcp_servers) == 30
        (row,) = _pool_rows(tree)
        assert row.startswith("config system dhcp server edit 10, 11, 12")
        assert "\n" not in row


class TestWhatTheRendererWrites:
    def _render(self, **fields: object) -> str:
        pool = CanonicalDHCPPool(
            interface="port2", network="192.0.2.0/24", start_ip="192.0.2.10",
            end_ip="192.0.2.20", gateway="192.0.2.1", **fields,
        )
        tree = CanonicalIntent(
            source_vendor="test", source_format="test", hostname="fg", dhcp_servers=[pool],
        )
        return FortiGateCLICodec().render(tree)

    def test_a_lease_that_does_not_end_is_written_0_and_read_back(self) -> None:
        text = self._render(lease_time=INFINITE_LEASE)
        assert "        set lease-time 0\n" in text
        assert str(INFINITE_LEASE) not in text
        assert FortiGateCLICodec().parse(text).dhcp_servers[0].lease_time == INFINITE_LEASE

    def test_four_servers_are_written_and_a_fifth_is_said(self) -> None:
        servers = [f"198.51.100.{n}" for n in range(1, 7)]
        text = self._render(dns_servers=servers)
        assert "        set dns-server4 198.51.100.4\n" in text
        assert "set dns-server5" not in text
        (review,) = [line for line in text.splitlines() if "# review: DNS servers" in line]
        assert review.endswith(
            "not written: 198.51.100.5, 198.51.100.6 (a FortiOS DHCP server takes four)"
        )
        assert FortiGateCLICodec().parse(text).dhcp_servers[0].dns_servers == servers[:4]

    def test_four_servers_need_no_review_line(self) -> None:
        servers = [f"198.51.100.{n}" for n in range(1, 5)]
        text = self._render(dns_servers=servers)
        assert "# review: DNS" not in text
        assert FortiGateCLICodec().parse(text).dhcp_servers[0].dns_servers == servers

    def test_a_pool_comes_back_as_it_was_written(self) -> None:
        text = self._render(
            dns_servers=["198.51.100.53"], lease_time=3600, domain_name="pool.example",
        )
        (pool,) = FortiGateCLICodec().parse(text).dhcp_servers
        assert pool.model_dump() == CanonicalDHCPPool(
            interface="port2", network="192.0.2.0/24", start_ip="192.0.2.10",
            end_ip="192.0.2.20", gateway="192.0.2.1", dns_servers=["198.51.100.53"],
            lease_time=3600, domain_name="pool.example",
        ).model_dump()


def _tree(*pools: CanonicalDHCPPool, own: str = "192.0.2.1") -> CanonicalIntent:
    """A tree whose one interface has the address *own* in a /24."""
    port = CanonicalInterface(
        name="port2", ipv4_addresses=[CanonicalIPv4Address(ip=own, prefix_length=24)],
    )
    return CanonicalIntent(
        source_vendor="test", source_format="test", hostname="fg",
        interfaces=[port], dhcp_servers=list(pools),
    )


def _dhcp_block(text: str) -> list[str]:
    lines = text.splitlines()
    start = lines.index("config system dhcp server")
    return lines[start:lines.index("end", start) + 1]


def _reviews(text: str) -> list[str]:
    return [line for line in _dhcp_block(text) if "# review:" in line]


class TestWhatFortiOSIsToldOtherwise:
    """A pool the renderer cannot write as it stands is written as
    FortiOS takes it, or not at all, and every such pool has a review
    line in the output and a warning on the job."""

    def test_a_pool_with_no_range_is_given_its_networks_addresses(self) -> None:
        tree = _tree(CanonicalDHCPPool(
            interface="port2", network="192.0.2.0/24", gateway="192.0.2.1",
        ))
        codec = FortiGateCLICodec()
        text = codec.render(tree)
        block = "\n".join(_dhcp_block(text))
        assert (
            "        config ip-range\n            edit 1\n"
            "                set start-ip 192.0.2.1\n                set end-ip 192.0.2.254\n"
        ) in block
        assert (
            "        config exclude-range\n            edit 1\n"
            "                set start-ip 192.0.2.1\n                set end-ip 192.0.2.1\n"
        ) in block
        (review,) = _reviews(text)
        assert "states no range" in review
        (warning,) = codec.render_warnings(tree)
        assert warning.startswith("FortiOS DHCP pool port2: the source states no whole range")
        (pool,) = codec.parse(text).dhcp_servers
        assert (pool.start_ip, pool.end_ip, pool.network) == (
            "192.0.2.2", "192.0.2.254", "192.0.2.0/24",
        )

    def test_one_end_of_a_range_is_given_the_other(self) -> None:
        tree = _tree(CanonicalDHCPPool(
            interface="port2", network="192.0.2.0/24", start_ip="192.0.2.100",
        ), own="192.0.2.1")
        text = FortiGateCLICodec().render(tree)
        (pool,) = FortiGateCLICodec().parse(text).dhcp_servers
        assert (pool.start_ip, pool.end_ip) == ("192.0.2.100", "192.0.2.254")
        assert "config exclude-range" not in text
        (review,) = _reviews(text)
        assert "one end of its range" in review

    @pytest.mark.parametrize(
        ("pool", "why"),
        [
            (CanonicalDHCPPool(interface="port2"), "it states no range and no network"),
            (
                CanonicalDHCPPool(interface="port2", end_ip="192.0.2.9"),
                "it states one end of its range and no network",
            ),
            (
                CanonicalDHCPPool(interface="port2", network="192.0.2.1/32"),
                "every address of its range is this output's own",
            ),
        ],
    )
    def test_a_pool_given_no_range_is_not_written(self, pool: CanonicalDHCPPool, why: str) -> None:
        kept = CanonicalDHCPPool(
            interface="port3", network="198.51.100.0/24", start_ip="198.51.100.10",
            end_ip="198.51.100.20", gateway="198.51.100.1",
        )
        tree = _tree(pool, kept)
        codec = FortiGateCLICodec()
        text = codec.render(tree)
        block = _dhcp_block(text)
        # A server with no range hands out nothing, and (before 7.4.5)
        # one ahead of another on its interface ends the search there.
        edits = [n for n, line in enumerate(block) if line.startswith("    edit ")]
        assert [block[n] for n in edits] == ["    edit 1"]
        assert "        config ip-range" in block[edits[0]:]
        (review,) = _reviews(text)
        assert review.startswith("    # review: a DHCP pool of the source (port2) is not written: ")
        assert why in review
        (warning,) = codec.render_warnings(tree)
        assert why in warning
        back = codec.parse(text)
        assert [p.interface for p in back.dhcp_servers] == ["port3"]
        assert not _pool_rows(back)

    @pytest.mark.parametrize(
        ("lease", "written"), [(60, 300), (299, 300), (8640001, 8640000), (31536000, 8640000)],
    )
    def test_a_lease_fortios_does_not_take_is_the_nearest_one_it_does(
        self, lease: int, written: int,
    ) -> None:
        tree = _tree(CanonicalDHCPPool(
            interface="port2", network="192.0.2.0/24", start_ip="192.0.2.10",
            end_ip="192.0.2.20", lease_time=lease,
        ))
        codec = FortiGateCLICodec()
        text = codec.render(tree)
        assert f"        set lease-time {written}\n" in text
        assert f"set lease-time {lease}\n" not in text
        (review,) = _reviews(text)
        assert f"the source's lease is {lease} seconds" in review
        (warning,) = codec.render_warnings(tree)
        assert f"its lease of {lease} seconds is written as {written}" in warning
        assert codec.parse(text).dhcp_servers[0].lease_time == written

    @pytest.mark.parametrize("lease", [300, 8640000])
    def test_a_lease_at_a_bound_is_written_as_it_is(self, lease: int) -> None:
        tree = _tree(CanonicalDHCPPool(
            interface="port2", network="192.0.2.0/24", start_ip="192.0.2.10",
            end_ip="192.0.2.20", lease_time=lease,
        ))
        text = FortiGateCLICodec().render(tree)
        assert f"        set lease-time {lease}\n" in text
        assert not _reviews(text)
        assert FortiGateCLICodec().render_warnings(tree) == []

    def test_a_pool_with_no_interface_is_said(self) -> None:
        tree = _tree(CanonicalDHCPPool(
            network="198.51.100.0/24", start_ip="198.51.100.10", end_ip="198.51.100.20",
        ))
        codec = FortiGateCLICodec()
        text = codec.render(tree)
        assert "set interface" not in "\n".join(_dhcp_block(text))
        (review,) = _reviews(text)
        assert "names no interface for this pool" in review
        (warning,) = codec.render_warnings(tree)
        assert warning.startswith("FortiOS DHCP pool 198.51.100.0/24: the source names no interface")

    def test_each_review_line_has_its_warning(self) -> None:
        tree = _tree(
            CanonicalDHCPPool(network="203.0.113.0/24", lease_time=60),
            CanonicalDHCPPool(interface="port2"),
            CanonicalDHCPPool(
                interface="port2", network="192.0.2.0/24", start_ip="192.0.2.10",
                end_ip="192.0.2.20", dns_servers=[f"198.51.100.{n}" for n in range(1, 7)],
            ),
        )
        codec = FortiGateCLICodec()
        text = codec.render(tree)
        assert len(_reviews(text)) == len(codec.render_warnings(tree)) == 5

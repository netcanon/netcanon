"""A RouterOS route the tree cannot hold as the router holds it is left
out and said, never written as another route.

Up to 0.7.7 the ``/ip route`` parser read ``dst-address``,
``gateway``, ``distance`` and ``comment`` and nothing else, so:

* a route of another routing table (``routing-table=`` on RouterOS 7,
  ``routing-mark=`` on 6) or with a gateway resolved in one
  (``192.0.2.9@vrf1``) -- a VRF's route -- was a route of the one table
  of the output, carrying traffic the source keeps apart; on every
  target, RouterOS included;
* a route held ``disabled=yes`` was written as a route in force;
* a ``blackhole`` route, and RouterOS 6's ``type=blackhole``,
  ``unreachable`` and ``prohibit``, was a route with no next hop, or,
  with a gateway, a route that forwards;
* ``192.0.2.9@main`` -- a gateway resolved in the main table, where one
  that names no table is resolved -- was a next hop of that spelling.

What a route of each form means is from MikroTik's manual: IP Routing
(https://help.mikrotik.com/docs/spaces/ROS/pages/328084/IP+Routing) and
VRF (https://manual.mikrotik.com/docs/7.25/user-guides/routing-and-networking-protocols/vrf/).

The output is read against an output of the same config written
without those forms -- each left-out line taken away, each ``@main``
taken off -- on every public codec: the two are the same text.  That
reading asks nothing of the parser it checks.
"""

from __future__ import annotations

import pytest

from netcanon.migration._tier3_detection import LEFT_OUT_ROWS_SHOWN, is_left_out_row
from netcanon.migration.codecs.mikrotik_routeros import parse as ros_parse
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.models.migration import MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan_with_checked_names

_HEAD = [
    "# 2026-01-01 00:00:00 by RouterOS 7.18.2",
    "/interface ethernet",
    "set [ find default-name=ether3 ] name=ether3",
    "/ip address",
    "add address=192.0.2.1/24 interface=ether3",
    "/ip route",
]

#: Routes the output has, each written as the output of
#: :data:`_PLAIN` writes it.
_KEPT = [
    "add dst-address=10.202.0.0/16 gateway=192.0.2.9@main",
    "add dst-address=10.208.0.0/16 gateway=ether3@main",
    "add dst-address=10.210.0.0/16 gateway=192.0.2.9 routing-table=main",
    'add comment="via blackhole box" dst-address=10.209.0.0/16 gateway=192.0.2.9',
    "add dst-address=10.211.0.0/16 gateway=192.0.2.9 disabled=no",
]

#: The same routes, as a config with none of the forms writes them.
_PLAIN = [
    "add dst-address=10.202.0.0/16 gateway=192.0.2.9",
    "add dst-address=10.208.0.0/16 gateway=ether3",
    "add dst-address=10.210.0.0/16 gateway=192.0.2.9",
    'add comment="via blackhole box" dst-address=10.209.0.0/16 gateway=192.0.2.9',
    "add dst-address=10.211.0.0/16 gateway=192.0.2.9",
]

#: Routes no output has: of another table, held disabled, discarding.
_LEFT_OUT = {
    "routing-table": "add dst-address=10.203.0.0/16 gateway=192.0.2.9@vrf1 routing-table=vrf1",
    "routing-table, @main": "add dst-address=10.204.0.0/16 gateway=192.0.2.9 routing-table=vrf1",
    "routing-mark": "add dst-address=10.212.0.0/16 gateway=192.0.2.9 routing-mark=to-isp2",
    "gateway in vrf2": "add dst-address=10.207.0.0/16 gateway=192.0.2.9@vrf2",
    "disabled": "add dst-address=10.205.0.0/16 gateway=192.0.2.9 disabled=yes",
    "blackhole": "add dst-address=10.206.0.0/16 blackhole",
    "blackhole=yes": "add blackhole=yes dst-address=10.213.0.0/16",
    "type=blackhole": "add dst-address=10.214.0.0/16 type=blackhole",
    "type=unreachable": "add dst-address=10.215.0.0/16 type=unreachable",
    "type=prohibit": "add dst-address=10.216.0.0/16 type=prohibit",
}


def _text(routes: list[str]) -> str:
    return "\n".join([*_HEAD, *routes, ""])


_WITH_THE_FORMS = _text([*_KEPT, *_LEFT_OUT.values()])
_WITHOUT_THEM = _text(_PLAIN)


def _rendered(text: str, target: str) -> str:
    job = run_plan_with_checked_names(
        get_codec("mikrotik_routeros"), get_codec(target), text, {},
    )
    return job.rendered or ""


def _routes(text: str):
    return get_codec("mikrotik_routeros").parse(text).static_routes


class TestTheOutput:
    @pytest.mark.parametrize("target", list_public_codecs())
    def test_is_the_output_of_the_config_without_the_forms(self, target: str) -> None:
        assert _rendered(_WITH_THE_FORMS, target) == _rendered(_WITHOUT_THEM, target)

    def test_the_reading_can_fail(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A parser that took ``vrf1`` for the main table writes the
        VRF's routes, and the two outputs differ."""
        monkeypatch.setattr(ros_parse, "_MAIN_TABLE", "vrf1")
        assert _rendered(_WITH_THE_FORMS, "cisco_iosxe_cli") != _rendered(
            _WITHOUT_THEM, "cisco_iosxe_cli",
        )

    def test_the_reading_reads_a_route(self) -> None:
        """The compared outputs hold the routes: a comparison of two
        empty outputs would pass whatever the parser did."""
        out = _rendered(_WITHOUT_THEM, "cisco_iosxe_cli")
        assert "ip route 10.202.0.0 255.255.0.0 192.0.2.9" in out
        assert "ip route 10.208.0.0 255.255.0.0 GigabitEthernet0/3" in out


class TestTheTree:
    def test_a_gateway_resolved_in_main_is_the_gateway(self) -> None:
        routes = {r.destination: r for r in _routes(_text(_KEPT))}
        assert routes["10.202.0.0/16"].gateway == "192.0.2.9"
        assert (routes["10.208.0.0/16"].gateway, routes["10.208.0.0/16"].interface) == (
            "", "ether3",
        )
        assert routes["10.210.0.0/16"].gateway == "192.0.2.9"

    @pytest.mark.parametrize("form", list(_LEFT_OUT))
    def test_each_form_makes_no_route(self, form: str) -> None:
        assert _routes(_text([_LEFT_OUT[form]])) == []

    def test_a_comment_is_not_a_flag(self) -> None:
        (route,) = _routes(_text([_KEPT[3]]))
        assert route.description == "via blackhole box"

    def test_a_list_of_gateways_is_one_route_as_written(self) -> None:
        """An ECMP list stays one route, each gateway once and without
        ``@main``: a route a gateway is many routes from few bytes, and
        no limit counts them yet."""
        routes = _routes(_text([
            "add dst-address=10.220.0.0/16 gateway=192.0.2.9@main,192.0.2.10,192.0.2.9",
            "add dst-address=10.221.0.0/16 gateway=ether3,ether3",
        ]))
        assert [(r.gateway, r.interface) for r in routes] == [
            ("192.0.2.9,192.0.2.10", ""), ("", "ether3"),
        ]

    def test_a_list_with_a_gateway_in_another_table_is_left_out(self) -> None:
        tree = get_codec("mikrotik_routeros").parse(_text([
            "add dst-address=10.222.0.0/16 gateway=192.0.2.9,192.0.2.10@vrf1",
        ]))
        assert tree.static_routes == []
        assert len(tree.dropped_tier3_sections) == 1


class TestTheRows:
    def _rows(self, routes: list[str]) -> list[str]:
        return get_codec("mikrotik_routeros").parse(_text(routes)).dropped_tier3_sections

    def test_one_row_a_kind_and_a_row_a_disabled_route(self) -> None:
        rows = self._rows([*_KEPT, *_LEFT_OUT.values()])
        disabled = [row for row in rows if is_left_out_row(row)]
        others = [row for row in rows if not is_left_out_row(row)]
        assert disabled == [
            "disabled: ip route 10.205.0.0/16 (a route the source holds disabled, "
            "so it installs nothing; not translated)",
        ]
        assert [row.split(":", 2)[1].split()[0] for row in others] == ["4", "5"]
        assert "routing table other than main" in others[0]
        assert "blackhole, unreachable or prohibit" in others[1]

    def test_a_route_that_is_in_force_has_no_row(self) -> None:
        assert self._rows(_KEPT) == []

    def test_the_rows_are_bounded(self) -> None:
        many = [
            f"add dst-address=10.{n // 256}.{n % 256}.0/24 gateway=192.0.2.9 disabled=yes"
            for n in range(LEFT_OUT_ROWS_SHOWN + 50)
        ]
        rows = self._rows(many)
        assert len(rows) == LEFT_OUT_ROWS_SHOWN + 1
        assert all(is_left_out_row(row) for row in rows)

    def test_every_job_says_them(self) -> None:
        job = run_plan_with_checked_names(
            get_codec("mikrotik_routeros"), get_codec("juniper_junos"), _WITH_THE_FORMS, {},
        )
        assert len(job.dropped_tier3_sections) == 3

    def test_a_config_of_disabled_routes_alone_is_not_completed(self) -> None:
        text = "\n".join([
            "# 2026-01-01 00:00:00 by RouterOS 7.18.2",
            "/ip route",
            "add dst-address=10.205.0.0/16 gateway=192.0.2.9 disabled=yes",
            "",
        ])
        job = run_plan_with_checked_names(
            get_codec("mikrotik_routeros"), get_codec("cisco_iosxe_cli"), text, {},
        )
        assert job.status != MigrationJobStatus.completed

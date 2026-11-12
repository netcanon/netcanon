"""A FortiOS static route printed with no ``set dst`` is a default
route, and a route the tree cannot hold as the FortiGate holds it is
left out and said, never written as another route.

Up to 0.7.7 the ``config router static`` parser read ``dst``,
``gateway``, ``device``, ``distance`` and ``comment`` and nothing
else, so:

* a route with no ``set dst`` line -- a default route as ``show``
  prints it, the default being left out -- was no route at all, with
  nothing said;
* a route to an address object (``set dstaddr``) was no route either,
  with nothing said;
* a ``blackhole`` route was a route with no next hop on every target
  (``ip route <prefix> distance 254`` onto AOS-CX);
* a route held ``set status disable`` was written as a route in force;
* a route of a VRF other than 0 (``set vrf <id>``) was a route of the
  global table of the output, carrying traffic the source keeps apart;
* a route whose gateway is learned from DHCP or PPP (``set
  dynamic-gateway enable``) was an interface route, and an SD-WAN route
  (neither a gateway nor a device) a route to nowhere;
* ``set gateway 0.0.0.0``, which ``show full-configuration`` prints for
  a route with none, was a next hop of that spelling.

The defaults and the meaning of each setting are from Fortinet's
FortiOS 7.4 CLI reference, "config router static"
(https://docs.fortinet.com/document/fortigate/7.4.0/cli-reference/522620/config-router-static)
and "config router static6"
(https://docs.fortinet.com/document/fortigate/7.4.0/cli-reference/525620/config-router-static6).

The output is read against an output of the same config written
without those forms -- each left-out route taken away, each default
written out -- on every public codec: the two are the same text.  That
reading asks nothing of the parser it checks.
"""

from __future__ import annotations

import pytest

from netcanon.migration._tier3_detection import LEFT_OUT_ROWS_SHOWN, is_left_out_row
from netcanon.migration.codecs.fortigate_cli import parse as fgt_parse
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.models.migration import MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan_with_checked_names

_HEAD = [
    "config system interface",
    '    edit "port1"',
    "        set ip 192.0.2.1 255.255.255.0",
    "    next",
    "end",
]


def _edit(n: int, *settings: str) -> list[str]:
    return [f"    edit {n}", *(f"        set {s}" for s in settings), "    next"]


def _block(head: str, edits: list[list[str]]) -> list[str]:
    return [f"config {head}", *(line for edit in edits for line in edit), "end"]


#: Routes the output has, each written as the output of :data:`_PLAIN`
#: writes it.
_KEPT = [
    _edit(1, "gateway 192.0.2.9", 'device "port1"'),
    _edit(2, "dst 10.208.0.0 255.255.0.0", "gateway 0.0.0.0", 'device "port1"'),
    _edit(3, "dst 10.210.0.0 255.255.0.0", "gateway 192.0.2.9", 'device "port1"', "vrf 0"),
    _edit(4, "dst 10.209.0.0 255.255.0.0", "gateway 192.0.2.9", 'device "port1"',
          'comment "via blackhole box"'),
    _edit(5, "dst 10.211.0.0/16", "gateway 192.0.2.9", 'device "port1"'),
    _edit(6, "status enable", "dst 10.212.0.0 255.255.0.0", "gateway 192.0.2.9",
          "distance 10", 'device "port1"', "blackhole disable", "dynamic-gateway disable",
          "dstaddr ''", "internet-service 0", "vrf 0"),
]

#: The same routes, as a config with none of the forms writes them.
_PLAIN = [
    _edit(1, "dst 0.0.0.0 0.0.0.0", "gateway 192.0.2.9", 'device "port1"'),
    _edit(2, "dst 10.208.0.0 255.255.0.0", 'device "port1"'),
    _edit(3, "dst 10.210.0.0 255.255.0.0", "gateway 192.0.2.9", 'device "port1"'),
    _edit(4, "dst 10.209.0.0 255.255.0.0", "gateway 192.0.2.9", 'device "port1"',
          'comment "via blackhole box"'),
    _edit(5, "dst 10.211.0.0 255.255.0.0", "gateway 192.0.2.9", 'device "port1"'),
    _edit(6, "dst 10.212.0.0 255.255.0.0", "gateway 192.0.2.9", "distance 10",
          'device "port1"'),
]

#: Routes no output has, by the row that counts them.
_LEFT_OUT = {
    "disabled": _edit(20, "status disable", "dst 10.205.0.0 255.255.0.0",
                      "gateway 192.0.2.9", 'device "port1"'),
    "vrf": _edit(21, "dst 10.203.0.0 255.255.0.0", "gateway 192.0.2.9",
                 'device "port1"', "vrf 5"),
    "blackhole": _edit(22, "dst 10.206.0.0 255.255.0.0", "blackhole enable",
                       "distance 254", "vrf 0"),
    "blackhole to an object": _edit(23, 'dstaddr "bogons"', "blackhole enable", "vrf 0"),
    "dstaddr": _edit(24, 'dstaddr "branch-nets"', "gateway 192.0.2.9", 'device "port1"'),
    "internet-service": _edit(25, "internet-service 327682", "gateway 192.0.2.9",
                              'device "port1"'),
    "dynamic-gateway": _edit(26, "dst 10.207.0.0 255.255.0.0", 'device "port1"',
                             "dynamic-gateway enable"),
    "sdwan-zone": _edit(27, "dst 10.213.0.0 255.255.0.0", 'sdwan-zone "virtual-wan-link"'),
    "dst not a prefix": _edit(28, "dst 10.214.0.0", "gateway 192.0.2.9", 'device "port1"'),
}

#: IPv6: kept, as the plain config writes it, and left out.
_KEPT6 = [_edit(1, "gateway 2001:db8::9", 'device "port1"'),
          _edit(2, "dst 2001:db8:8::/48", "gateway ::", 'device "port1"')]
_PLAIN6 = [_edit(1, "dst ::/0", "gateway 2001:db8::9", 'device "port1"'),
           _edit(2, "dst 2001:db8:8::/48", 'device "port1"')]
_LEFT_OUT6 = [_edit(3, "dst 2001:db8:6::/48", "blackhole enable")]


def _text(routes: list[list[str]], routes6: list[list[str]] = ()) -> str:
    lines = [*_HEAD, *_block("router static", routes)]
    if routes6:
        lines += _block("router static6", list(routes6))
    return "\n".join([*lines, ""])


_WITH_THE_FORMS = _text([*_KEPT, *_LEFT_OUT.values()], [*_KEPT6, *_LEFT_OUT6])
_WITHOUT_THEM = _text(_PLAIN, _PLAIN6)


def _rendered(text: str, target: str) -> str:
    job = run_plan_with_checked_names(
        get_codec("fortigate_cli"), get_codec(target), text, {},
    )
    return job.rendered or ""


def _routes(text: str):
    return get_codec("fortigate_cli").parse(text).static_routes


class TestTheOutput:
    @pytest.mark.parametrize("target", list_public_codecs())
    def test_is_the_output_of_the_config_without_the_forms(self, target: str) -> None:
        assert _rendered(_WITH_THE_FORMS, target) == _rendered(_WITHOUT_THEM, target)

    def test_the_reading_can_fail(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A parser that took ``set gateway 0.0.0.0`` for a next hop
        writes one, and the two outputs differ."""
        monkeypatch.setattr(fgt_parse, "_NO_GATEWAY", frozenset())
        assert _rendered(_WITH_THE_FORMS, "cisco_iosxe_cli") != _rendered(
            _WITHOUT_THEM, "cisco_iosxe_cli",
        )

    def test_the_reading_reads_a_route(self) -> None:
        """The compared outputs hold the routes: a comparison of two
        empty outputs would pass whatever the parser did."""
        out = _rendered(_WITHOUT_THEM, "cisco_iosxe_cli")
        assert "ip route 0.0.0.0 0.0.0.0 GigabitEthernet0/1 192.0.2.9" in out
        assert "ip route 10.212.0.0 255.255.0.0 GigabitEthernet0/1 192.0.2.9 10" in out


class TestTheTree:
    def test_a_route_with_no_dst_is_a_default_route(self) -> None:
        routes = _routes(_text(_KEPT, _KEPT6))
        defaults = [(r.destination, r.gateway) for r in routes if r.destination in ("0.0.0.0/0", "::/0")]
        assert defaults == [("0.0.0.0/0", "192.0.2.9"), ("::/0", "2001:db8::9")]

    def test_a_gateway_of_zeros_is_no_gateway(self) -> None:
        routes = {r.destination: r for r in _routes(_text(_KEPT, _KEPT6))}
        assert (routes["10.208.0.0/16"].gateway, routes["10.208.0.0/16"].interface) == (
            "", "port1",
        )
        assert routes["2001:db8:8::/48"].gateway == ""

    def test_a_prefix_is_read_as_written(self) -> None:
        assert "10.211.0.0/16" in {r.destination for r in _routes(_text(_KEPT))}

    def test_every_default_printed_is_the_route_it_is(self) -> None:
        (route,) = _routes(_text([_KEPT[5]]))
        assert (route.destination, route.gateway, route.interface, route.metric) == (
            "10.212.0.0/16", "192.0.2.9", "port1", 10,
        )

    @pytest.mark.parametrize("form", list(_LEFT_OUT))
    def test_each_form_makes_no_route(self, form: str) -> None:
        assert _routes(_text([_LEFT_OUT[form]])) == []

    def test_an_ipv6_blackhole_makes_no_route(self) -> None:
        assert _routes(_text([], _LEFT_OUT6)) == []

    def test_a_comment_is_not_a_flag(self) -> None:
        (route,) = _routes(_text([_KEPT[3]]))
        assert route.description == "via blackhole box"


class TestTheRows:
    def _rows(self, routes: list[list[str]], routes6: list[list[str]] = ()) -> list[str]:
        return get_codec("fortigate_cli").parse(_text(routes, routes6)).dropped_tier3_sections

    def test_one_row_a_kind_and_a_row_a_disabled_route(self) -> None:
        rows = self._rows([*_KEPT, *_LEFT_OUT.values()], [*_KEPT6, *_LEFT_OUT6])
        disabled = [row for row in rows if is_left_out_row(row)]
        others = [row for row in rows if not is_left_out_row(row)]
        assert disabled == [
            "disabled: config router static edit 20 (a route the source holds disabled, "
            "so it installs nothing; not translated)",
        ]
        assert [(row.split(":", 1)[0], row.split(":", 2)[1].split()[0]) for row in others] == [
            ("router static", "1"), ("router static", "2"), ("router static", "2"),
            ("router static", "1"), ("router static", "1"), ("router static", "1"),
            ("router static6", "1"),
        ]
        assert "VRF other than 0" in others[0]
        assert "blackhole route(s)" in others[1]
        assert "address object" in others[2]
        assert "DHCP or PPP" in others[3]
        assert "neither a gateway nor a device" in others[4]
        assert "destination is not read" in others[5]
        assert "blackhole route(s)" in others[6]

    def test_a_route_that_is_in_force_has_no_row(self) -> None:
        assert self._rows(_KEPT, _KEPT6) == []

    def test_a_row_names_no_value(self) -> None:
        """A row counts the routes; it quotes no destination, gateway,
        object or zone of them."""
        rows = self._rows(list(_LEFT_OUT.values()), _LEFT_OUT6)
        for value in ("10.2", "192.0.2.9", "bogons", "branch-nets", "virtual-wan-link",
                      "327682", "2001:db8"):
            assert not [row for row in rows if value in row], value

    def test_the_rows_are_bounded(self) -> None:
        many = [
            _edit(100 + n, "status disable", f"dst 10.{n // 256}.{n % 256}.0 255.255.255.0",
                  "gateway 192.0.2.9", 'device "port1"')
            for n in range(LEFT_OUT_ROWS_SHOWN + 50)
        ]
        rows = self._rows(many)
        assert len(rows) == LEFT_OUT_ROWS_SHOWN + 1
        assert all(is_left_out_row(row) for row in rows)

    def test_every_job_says_them(self) -> None:
        job = run_plan_with_checked_names(
            get_codec("fortigate_cli"), get_codec("juniper_junos"), _WITH_THE_FORMS, {},
        )
        assert len(job.dropped_tier3_sections) == 8

    def test_a_config_of_disabled_routes_alone_is_not_completed(self) -> None:
        text = "\n".join([*_block("router static", [_LEFT_OUT["disabled"]]), ""])
        job = run_plan_with_checked_names(
            get_codec("fortigate_cli"), get_codec("cisco_iosxe_cli"), text, {},
        )
        assert job.status != MigrationJobStatus.completed

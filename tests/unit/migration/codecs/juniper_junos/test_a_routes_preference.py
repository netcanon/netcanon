"""A Junos static route's preference is its distance, read and written.

A static route's preference is what another platform calls its
administrative distance (Juniper, "preference (Routing Options)":
"Preference value for a static, aggregate, or generated route", 0 to
4,294,967,295, "Default: 5 (for static routes)").  The parser read no
``preference`` line, and left a ``qualified-next-hop`` out -- a next hop
at a preference of its own, the form a floating static route takes on
Junos -- so a backup route came out on no target; and the renderer
wrote no preference, so a floating route from another platform came out
on Junos as two next hops of one preference, the backup carrying
traffic beside the route it backs up, in a job that said ``completed``.

What a next hop's preference is: its own, as a qualified next hop
states it ("The qualified next-hop preference and metric override the
route preference and metric", Juniper, "Static Route Preferences and
Qualified Next Hops"), else the route's ``preference``, else the
``preference`` of the block's ``defaults`` ("default attributes
inherited by all newly created static routes", Juniper, "static
(Routing Options)").  Where no next hop
of a route states one, the tree holds "not stated" (0), which each
target writes as its own default; where some do, the others are given
Junos's default, 5, so that the backup is the backup on every target.

Left out and said: a next hop at a preference the tree does not hold
(0, or 255 and above -- 255 is a route a Cisco router does not install,
and IOS XR takes 254 at most), and a qualified next hop with a metric of
its own at the preference of another next hop of the route: the tree
holds no such metric, and no Juniper page says whether it decides which
of them is used (the metric is "used when the route is exported into an
IGP", Juniper, "qualified-next-hop (Static Routes)").
"""

from __future__ import annotations

import functools

import pytest

from netcanon.migration._tier3_detection import is_left_out_row
from netcanon.migration.canonical.intent import CanonicalIntent, CanonicalStaticRoute
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.models.migration import MigrationJob
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

PUBLIC = list_public_codecs()

_HEAD = (
    "set system host-name r1\n"
    "set interfaces ge-0/0/0 unit 0 family inet address 192.0.2.2/24\n"
    "set routing-instances RED instance-type virtual-router\n"
)
_R = "set routing-options static route 10.0.0.0/8"
_RED = "set routing-instances RED routing-options static route 10.0.0.0/8"


def _qualified_row(count: int) -> str:
    return (
        f"routing-options static: {count} qualified next hop(s) with a metric "
        "of their own at the preference of another next hop of the route "
        "(qualified-next-hop <address> metric <n>): the tree holds no such "
        "metric, and whether it decides which of them Junos uses is not "
        "established; not translated"
    )


def _preference_row(count: int) -> str:
    return (
        f"routing-options static: {count} next hop(s) at a preference the tree "
        "does not hold (preference 0, or 255 and above): the tree holds a "
        "distance of 1 to 254; not translated"
    )


def _parse(*lines: str) -> CanonicalIntent:
    return get_codec("juniper_junos").parse(_HEAD + "".join(f"{line}\n" for line in lines))


def _read(*lines: str) -> tuple[list[tuple[str, str, str, int]], list[str]]:
    """(vrf, destination, gateway, metric) of each route the parser keeps,
    and its rows."""
    tree = _parse(*lines)
    routes = sorted((r.vrf, r.destination, r.gateway, r.metric) for r in tree.static_routes)
    return routes, tree.dropped_tier3_sections


def _route(gateway: str, metric: int = 0, vrf: str = "", destination: str = "10.0.0.0/8"):
    return (vrf, destination, gateway, metric)


class TestWhatIsRead:
    def test_a_route_that_states_none_is_not_stated(self) -> None:
        assert _read(f"{_R} next-hop 192.0.2.1") == ([_route("192.0.2.1")], [])

    def test_the_routes_own(self) -> None:
        assert _read(f"{_R} next-hop 192.0.2.1", f"{_R} preference 20") == (
            [_route("192.0.2.1", 20)], [],
        )

    def test_it_is_the_preference_of_every_next_hop_of_the_route(self) -> None:
        assert _read(
            f"{_R} preference 20", f"{_R} next-hop 192.0.2.1", f"{_R} next-hop 192.0.2.3",
        ) == ([_route("192.0.2.1", 20), _route("192.0.2.3", 20)], [])

    def test_the_blocks_defaults(self) -> None:
        assert _read(
            "set routing-options static defaults preference 30", f"{_R} next-hop 192.0.2.1",
        ) == ([_route("192.0.2.1", 30)], [])

    def test_the_routes_own_before_the_defaults(self) -> None:
        assert _read(
            "set routing-options static defaults preference 30",
            f"{_R} next-hop 192.0.2.1", f"{_R} preference 20",
        ) == ([_route("192.0.2.1", 20)], [])

    def test_the_defaults_of_a_table_are_for_its_routes_alone(self) -> None:
        """``static defaults`` are the IPv4 routes'; ``rib inet6.0 static
        defaults`` the IPv6 routes'; an instance's, the instance's."""
        assert _read(
            "set routing-options static defaults preference 30",
            "set routing-options rib inet6.0 static defaults preference 40",
            "set routing-instances RED routing-options static defaults preference 50",
            f"{_R} next-hop 192.0.2.1",
            "set routing-options rib inet6.0 static route ::/0 next-hop 2001:db8::1",
            f"{_RED} next-hop 192.0.2.7",
            "set routing-instances RED routing-options rib RED.inet6.0 static route ::/0 next-hop 2001:db8::7",
        )[0] == [
            ("", "10.0.0.0/8", "192.0.2.1", 30),
            ("", "::/0", "2001:db8::1", 40),
            ("RED", "10.0.0.0/8", "192.0.2.7", 50),
            ("RED", "::/0", "2001:db8::7", 0),
        ]

    def test_a_floating_route(self) -> None:
        """The usual backup: the route's own next hop at the default, a
        qualified next hop at a preference of its own."""
        assert _read(
            f"{_R} next-hop 192.0.2.1", f"{_R} qualified-next-hop 192.0.2.9 preference 200",
        ) == ([_route("192.0.2.1", 5), _route("192.0.2.9", 200)], [])

    def test_a_qualified_next_hop_that_states_none_has_the_routes(self) -> None:
        assert _read(
            f"{_R} next-hop 192.0.2.1", f"{_R} preference 20", f"{_R} qualified-next-hop 192.0.2.9",
        ) == ([_route("192.0.2.1", 20), _route("192.0.2.9", 20)], [])
        assert _read(f"{_R} qualified-next-hop 192.0.2.9") == ([_route("192.0.2.9")], [])

    def test_a_qualified_next_hop_in_an_instance(self) -> None:
        assert _read(
            f"{_RED} next-hop 192.0.2.1", f"{_RED} qualified-next-hop 192.0.2.9 preference 9",
        ) == ([_route("192.0.2.1", 5, "RED"), _route("192.0.2.9", 9, "RED")], [])

    def test_an_instance_is_not_made_of_a_route(self) -> None:
        """A route's lines say nothing of the instance itself: an
        instance named only by them is no instance of the tree."""
        tree = get_codec("juniper_junos").parse(
            "set routing-instances BLUE routing-options static route 10.0.0.0/8 "
            "qualified-next-hop 192.0.2.9 preference 9\n"
            "set routing-instances BLUE routing-options static route 10.0.0.0/8 preference 20\n"
            "set routing-instances BLUE routing-options static defaults preference 30\n"
        )
        assert not tree.routing_instances
        assert [(r.vrf, r.metric) for r in tree.static_routes] == [("BLUE", 9)]

    def test_the_block_form_says_the_same(self) -> None:
        tree = get_codec("juniper_junos").parse(
            "system {\n    host-name r1;\n}\n"
            "routing-options {\n    static {\n"
            "        defaults {\n            preference 30;\n        }\n"
            "        route 10.1.0.0/16 next-hop 192.0.2.1;\n"
            "        route 10.0.0.0/8 {\n"
            "            next-hop 192.0.2.1;\n"
            "            qualified-next-hop 192.0.2.9 {\n"
            "                preference 200;\n"
            "            }\n"
            "            preference 20;\n"
            "        }\n"
            "    }\n}\n"
        )
        assert sorted((r.destination, r.gateway, r.metric) for r in tree.static_routes) == [
            ("10.0.0.0/8", "192.0.2.1", 20), ("10.0.0.0/8", "192.0.2.9", 200),
            ("10.1.0.0/16", "192.0.2.1", 30),
        ]

    def test_a_groups_preference_and_the_configs_own(self) -> None:
        group = "set groups G routing-options static route 10.0.0.0/8 preference 20"
        assert _read(group, "set apply-groups G", f"{_R} next-hop 192.0.2.1")[0] == [
            _route("192.0.2.1", 20),
        ]
        assert _read(
            group, "set apply-groups G", f"{_R} next-hop 192.0.2.1", f"{_R} preference 30",
        )[0] == [_route("192.0.2.1", 30)]

    def test_a_deactivated_preference_is_not_in_force(self) -> None:
        routes, rows = _read(
            f"{_R} next-hop 192.0.2.1", f"{_R} preference 20",
            "deactivate routing-options static route 10.0.0.0/8 preference",
        )
        assert routes == [_route("192.0.2.1")]
        assert len(rows) == 1 and is_left_out_row(rows[0])

    @pytest.mark.parametrize("value", ["1", "254"])
    def test_the_ends_of_what_the_tree_holds(self, value: str) -> None:
        assert _read(f"{_R} next-hop 192.0.2.1", f"{_R} preference {value}") == (
            [_route("192.0.2.1", int(value))], [],
        )


class TestWhatIsLeftOut:
    @pytest.mark.parametrize("value", ["0", "255", "300", "4294967295", "x", "\u0667", "1" * 30])
    def test_a_preference_the_tree_does_not_hold(self, value: str) -> None:
        """0 is "not stated" in the tree; 255 and above no Cisco router
        installs alike; a word that is no number, or a digit of another
        script, is no preference Junos takes."""
        routes, rows = _read(f"{_R} next-hop 192.0.2.1", f"{_R} preference {value}")
        assert routes == []
        assert rows == [_preference_row(1)]

    def test_only_the_next_hop_at_it(self) -> None:
        routes, rows = _read(
            f"{_R} next-hop 192.0.2.1", f"{_R} qualified-next-hop 192.0.2.9 preference 300",
        )
        assert routes == [_route("192.0.2.1", 5)]
        assert rows == [_preference_row(1)]

    def test_a_metric_beside_another_next_hop_of_its_preference(self) -> None:
        routes, rows = _read(
            f"{_R} next-hop 192.0.2.1", f"{_R} qualified-next-hop 192.0.2.9 metric 3",
        )
        assert routes == [_route("192.0.2.1")]
        assert rows == [_qualified_row(1)]
        routes, rows = _read(
            f"{_R} qualified-next-hop 192.0.2.8 preference 7",
            f"{_R} qualified-next-hop 192.0.2.9 preference 7",
            f"{_R} qualified-next-hop 192.0.2.9 metric 3",
        )
        assert routes == [_route("192.0.2.8", 7)]
        assert rows == [_qualified_row(1)]

    def test_a_metric_that_decides_nothing_is_read(self) -> None:
        """A qualified next hop alone at its preference is the one Junos
        uses at that preference, whatever its metric."""
        assert _read(
            f"{_R} next-hop 192.0.2.1",
            f"{_R} qualified-next-hop 192.0.2.9 preference 200",
            f"{_R} qualified-next-hop 192.0.2.9 metric 3",
        ) == ([_route("192.0.2.1", 5), _route("192.0.2.9", 200)], [])

    def test_two_next_hops_of_one_preference_are_both_read(self) -> None:
        """With no metric of their own, two next hops at one preference
        are two next hops of the route, as two ``next-hop`` lines are."""
        assert _read(f"{_R} next-hop 192.0.2.1", f"{_R} qualified-next-hop 192.0.2.9") == (
            [_route("192.0.2.1"), _route("192.0.2.9")], [],
        )

    def test_each_next_hop_is_counted_once(self) -> None:
        _, rows = _read(
            f"{_R} next-hop 192.0.2.1",
            f"{_R} qualified-next-hop 192.0.2.8 preference 0",
            f"{_R} qualified-next-hop 192.0.2.8 metric 4",
            f"{_R} qualified-next-hop 192.0.2.9 preference 300",
            f"{_RED} next-hop 192.0.2.1",
            f"{_RED} qualified-next-hop 192.0.2.8 metric 3",
            f"{_RED} qualified-next-hop 192.0.2.8 tag 3",
            "set routing-options rib inet6.0 static route ::/0 next-hop 2001:db8::1",
            "set routing-options rib inet6.0 static route ::/0 preference 255",
        )
        assert rows == [_qualified_row(1), _preference_row(3)]

    def test_the_rows_are_sections(self) -> None:
        """Each next hop is in force on the device."""
        assert not is_left_out_row(_qualified_row(2))
        assert not is_left_out_row(_preference_row(2))


def _tree(*routes: tuple[str, str, int, str]) -> CanonicalIntent:
    return CanonicalIntent(hostname="r1", static_routes=[
        CanonicalStaticRoute(destination=dest, gateway=gw, metric=metric, vrf=vrf)
        for dest, gw, metric, vrf in routes
    ])


def _route_lines(tree: CanonicalIntent) -> list[str]:
    return [line for line in get_codec("juniper_junos").render(tree).splitlines() if " route " in line]


class TestWhatIsWritten:
    def test_a_route_that_states_none(self) -> None:
        assert _route_lines(_tree(("10.0.0.0/8", "192.0.2.1", 0, ""))) == [
            "set routing-options static route 10.0.0.0/8 next-hop 192.0.2.1",
        ]

    def test_a_distance(self) -> None:
        assert _route_lines(_tree(("10.0.0.0/8", "192.0.2.1", 20, ""))) == [
            "set routing-options static route 10.0.0.0/8 next-hop 192.0.2.1",
            "set routing-options static route 10.0.0.0/8 preference 20",
        ]

    def test_a_floating_route(self) -> None:
        assert _route_lines(_tree(
            ("0.0.0.0/0", "192.0.2.1", 0, ""), ("0.0.0.0/0", "192.0.2.9", 200, ""),
        )) == [
            "set routing-options static route 0.0.0.0/0 next-hop 192.0.2.1",
            "set routing-options static route 0.0.0.0/0 qualified-next-hop 192.0.2.9 preference 200",
        ]

    def test_the_least_distance_is_the_routes(self) -> None:
        """Whichever next hop comes first in the tree."""
        assert _route_lines(_tree(
            ("0.0.0.0/0", "192.0.2.9", 200, ""), ("0.0.0.0/0", "192.0.2.1", 10, ""),
            ("0.0.0.0/0", "192.0.2.3", 10, ""),
        )) == [
            "set routing-options static route 0.0.0.0/0 qualified-next-hop 192.0.2.9 preference 200",
            "set routing-options static route 0.0.0.0/0 preference 10",
            "set routing-options static route 0.0.0.0/0 next-hop 192.0.2.1",
            "set routing-options static route 0.0.0.0/0 next-hop 192.0.2.3",
        ]

    def test_in_an_instance_and_in_inet6(self) -> None:
        assert _route_lines(_tree(
            ("10.0.0.0/8", "192.0.2.1", 0, "RED"), ("10.0.0.0/8", "192.0.2.9", 9, "RED"),
            ("::/0", "2001:db8::1", 40, ""), ("10.0.0.0/8", "192.0.2.1", 30, ""),
        )) == [
            "set routing-instances RED routing-options static route 10.0.0.0/8 next-hop 192.0.2.1",
            "set routing-instances RED routing-options static route 10.0.0.0/8 "
            "qualified-next-hop 192.0.2.9 preference 9",
            "set routing-options rib inet6.0 static route ::/0 next-hop 2001:db8::1",
            "set routing-options rib inet6.0 static route ::/0 preference 40",
            "set routing-options static route 10.0.0.0/8 next-hop 192.0.2.1",
            "set routing-options static route 10.0.0.0/8 preference 30",
        ]

    @pytest.mark.parametrize("metrics", [(0,), (20,), (1, 254), (10, 200, 10), (7, 3)])
    def test_it_is_read_back(self, metrics: tuple[int, ...]) -> None:
        tree = _tree(*(("10.0.0.0/8", f"192.0.2.{n + 1}", m, "") for n, m in enumerate(metrics)))
        back = get_codec("juniper_junos").parse(get_codec("juniper_junos").render(tree))
        assert sorted((r.gateway, r.metric) for r in back.static_routes) == sorted(
            (r.gateway, r.metric) for r in tree.static_routes
        )


_FLOATING = (
    "set routing-options static route 0.0.0.0/0 next-hop 192.0.2.1\n"
    "set routing-options static route 0.0.0.0/0 qualified-next-hop 192.0.2.9 preference 200\n"
    "set routing-options static route 10.0.0.0/8 next-hop 192.0.2.1\n"
    "set routing-options static route 10.0.0.0/8 preference 20\n"
)

#: What each next hop is meant to be on the target, written out by hand:
#: (destination, gateway, distance).
_MEANT = [
    ("0.0.0.0/0", "192.0.2.1", 5),
    ("0.0.0.0/0", "192.0.2.9", 200),
    ("10.0.0.0/8", "192.0.2.1", 20),
]

#: The public codecs that hold no static route: their matrix says so.
_HOLD_NO_ROUTE = {"cisco_iosxe", "opnsense"}


@functools.cache
def _job(target: str) -> MigrationJob:
    job = run_plan_with_checked_names(
        get_codec("juniper_junos"), get_codec(target), _HEAD + _FLOATING, port_rename_map={},
    )
    assert job.rendered, f"juniper_junos -> {target}: {job.error}"
    return job


def _check_the_distances(target: str, rendered: str) -> None:
    """The target's own parser reads each next hop back at its distance
    (:data:`_MEANT`, where the backup's is above the route's): the
    backup is the backup there."""
    back = sorted(
        (r.destination, r.gateway, r.metric)
        for r in get_codec(target).parse(rendered).static_routes
    )
    assert back == _MEANT, target


class TestEveryTarget:
    @pytest.mark.parametrize("target", sorted(set(PUBLIC) - _HOLD_NO_ROUTE))
    def test_the_backup_is_the_backup(self, target: str) -> None:
        _check_the_distances(target, _job(target).rendered)

    @pytest.mark.parametrize("target", sorted(_HOLD_NO_ROUTE))
    def test_a_target_that_holds_no_route_says_so(self, target: str) -> None:
        assert get_codec(target).capabilities.classify("/routing/static-route") == "unsupported"
        assert _job(target).status.value == "partial"

    def test_the_metric_is_a_supported_path_of_junos(self) -> None:
        assert get_codec("juniper_junos").capabilities.classify("/routing/static-route/metric") == "supported"


class TestTheCheckCanFail:
    """Each check of :class:`TestEveryTarget`, handed the defect it is for."""

    @pytest.mark.parametrize("target", ["cisco_iosxe_cli", "juniper_junos", "vyos"])
    def test_a_distance_that_did_not_come(self, target: str) -> None:
        """The two next hops written at one distance, as before."""
        tree = get_codec("juniper_junos").parse(_HEAD + _FLOATING)
        for route in tree.static_routes:
            route.metric = 0
        with pytest.raises(AssertionError):
            _check_the_distances(target, get_codec(target).render(tree))

    @pytest.mark.parametrize("target", ["cisco_iosxe_cli", "juniper_junos"])
    def test_a_backup_that_did_not_come(self, target: str) -> None:
        """The qualified next hop left out, as before."""
        tree = get_codec("juniper_junos").parse(_HEAD + _FLOATING)
        tree.static_routes = [r for r in tree.static_routes if r.gateway != "192.0.2.9"]
        with pytest.raises(AssertionError):
            _check_the_distances(target, get_codec(target).render(tree))

    def test_the_backup_in_front(self) -> None:
        """The two distances the wrong way round."""
        tree = get_codec("juniper_junos").parse(_HEAD + _FLOATING)
        for route in tree.static_routes:
            if route.destination == "0.0.0.0/0":
                route.metric = 205 - route.metric
        with pytest.raises(AssertionError):
            _check_the_distances("cisco_iosxe_cli", get_codec("cisco_iosxe_cli").render(tree))

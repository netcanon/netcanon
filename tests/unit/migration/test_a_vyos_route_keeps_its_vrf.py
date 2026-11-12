"""A VyOS route keeps its VRF.

VyOS writes a route of a VRF under the VRF: ``set vrf name <name>
protocols static ...`` (VyOS, "VRF").  The parser matched a route by the
last frames of its path alone, so a route under ``vrf name <X>`` was a
route of the global table onto every target, VyOS itself included, in a
job that said ``completed``; and the renderer wrote every route into
the global ``protocols static``, a route of another vendor's VRF
included.  Two more forms were read as ordinary routes as well: a next
hop looked up in another VRF (``next-hop <address> vrf <name>``, as the
route-leaking and NAT examples of the same page write it) and a next hop
VyOS holds disabled (``next-hop <address> disable``: "Disable the route
via the specified next-hop IP address", VyOS, "Static").  The first is
left out, as the tree has no form for it, and one row counts such
routes; the second is not in force, so it is left out with a row of
its own.

Each is read here from the parse, in both forms VyOS prints, and from
the OUTPUT of the plan path the API uses onto every public codec, read
back with the target's own parser and as text.
"""

from __future__ import annotations

import functools
import re

import pytest

from netcanon.migration._tier3_detection import is_left_out_row
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.models.migration import MigrationJob, MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

PUBLIC = list_public_codecs()

_IFACES = """interfaces {
    ethernet eth1 {
        address 192.0.2.1/24
    }
    ethernet eth2 {
        address 198.51.100.1/24
        vrf red
    }
}
"""


def _brace(global_routes: str = "", vrf_routes: str = "") -> str:
    """A ``config.boot`` with *global_routes* under ``protocols static``
    and *vrf_routes* under ``vrf name red protocols static`` (each the
    lines inside ``static { }``), and a second VRF ``blue``."""
    out = _IFACES
    if global_routes:
        out += "protocols {\n    static {\n" + global_routes + "    }\n}\n"
    out += "system {\n    host-name r1\n}\nvrf {\n    name blue {\n        table 201\n    }\n"
    out += "    name red {\n"
    if vrf_routes:
        out += "        protocols {\n            static {\n" + vrf_routes
        out += "            }\n        }\n"
    out += "        table 200\n    }\n}\n"
    return out


def _route(dest: str, nh: str, *leaves: str, kw: str = "route") -> str:
    body = "".join(f"            {leaf}\n" for leaf in leaves)
    return f"        {kw} {dest} {{\n            next-hop {nh} {{\n{body}            }}\n        }}\n"


def _parse(text: str):
    return get_codec("vyos").parse(text)


def _routes(text: str) -> list[tuple[str, str, str, int]]:
    """(vrf, destination, gateway, distance) of each route."""
    return sorted(
        (r.vrf, r.destination, r.gateway, r.metric) for r in _parse(text).static_routes
    )


_SET = """set interfaces ethernet eth1 address '192.0.2.1/24'
set interfaces ethernet eth2 address '198.51.100.1/24'
set interfaces ethernet eth2 vrf 'red'
set protocols static route 0.0.0.0/0 next-hop 192.0.2.254 distance '5'
set protocols static route 10.6.0.0/16 next-hop 192.0.2.251 vrf 'default'
set protocols static route 10.7.0.0/16 next-hop 198.51.100.7 vrf 'red'
set protocols static route 10.8.0.0/16 next-hop 192.0.2.250 disable
set system host-name 'r1'
set vrf name blue table '201'
set vrf name red protocols static route 10.9.0.0/16 next-hop 198.51.100.254
set vrf name red protocols static route 10.5.0.0/16 next-hop 198.51.100.253 distance '4'
set vrf name red protocols static route 10.4.0.0/16 next-hop 198.51.100.252 vrf 'red'
set vrf name red protocols static route 10.3.0.0/16 next-hop 192.0.2.249 vrf 'default'
set vrf name red protocols static route6 2001:db8:9::/48 next-hop 2001:db8::fe
set vrf name red table '200'
"""

#: What the parser reads of ``_SET`` and of its brace form.
_READ_OF_IT = [
    ("", "0.0.0.0/0", "192.0.2.254", 5),
    ("", "10.6.0.0/16", "192.0.2.251", 0),
    ("red", "10.4.0.0/16", "198.51.100.252", 0),
    ("red", "10.5.0.0/16", "198.51.100.253", 4),
    ("red", "10.9.0.0/16", "198.51.100.254", 0),
    ("red", "2001:db8:9::/48", "2001:db8::fe", 0),
]

_BRACE = _brace(
    _route("0.0.0.0/0", "192.0.2.254", "distance 5")
    + _route("10.6.0.0/16", "192.0.2.251", "vrf default")
    + _route("10.7.0.0/16", "198.51.100.7", "vrf red")
    + _route("10.8.0.0/16", "192.0.2.250", "disable"),
    "".join(
        "        " + line
        for line in (
            _route("10.9.0.0/16", "198.51.100.254")
            + _route("10.5.0.0/16", "198.51.100.253", "distance 4")
            + _route("10.4.0.0/16", "198.51.100.252", "vrf red")
            + _route("10.3.0.0/16", "192.0.2.249", "vrf default")
            + _route("2001:db8:9::/48", "2001:db8::fe", kw="route6")
        ).splitlines(keepends=True)
    ),
)


class TestTheParser:
    @pytest.mark.parametrize("text", [_SET, _BRACE], ids=["set", "brace"])
    def test_each_route_is_read_in_its_own_table(self, text) -> None:
        assert _routes(text) == _READ_OF_IT

    @pytest.mark.parametrize("text", [_SET, _BRACE], ids=["set", "brace"])
    def test_a_next_hop_in_another_vrf_is_left_out_and_counted(self, text) -> None:
        """``10.7.0.0/16`` leaks from the global table to ``red``, and
        ``10.3.0.0/16`` from ``red`` to the global table: one row counts
        both, and it is a section (the routes are in force)."""
        rows = [r for r in _parse(text).dropped_tier3_sections if "another VRF" in r]
        assert len(rows) == 1
        assert rows[0].startswith("protocols static: 2 route(s) ")
        assert "next-hop <address> vrf <name>" in rows[0]
        assert not is_left_out_row(rows[0])

    @pytest.mark.parametrize("text", [_SET, _BRACE], ids=["set", "brace"])
    def test_a_disabled_next_hop_is_left_out_and_said(self, text) -> None:
        rows = [r for r in _parse(text).dropped_tier3_sections if is_left_out_row(r)]
        assert rows == [
            "disabled: protocols static route 10.8.0.0/16 next-hop 192.0.2.250 "
            "(a route the source holds disabled, so it installs nothing; not translated)"
        ]

    def test_a_disabled_next_hop_of_a_vrf_names_its_vrf(self) -> None:
        rows = _parse(_brace(vrf_routes=_route("10.2.0.0/16", "198.51.100.9", "disable")))
        assert [r for r in rows.dropped_tier3_sections if is_left_out_row(r)] == [
            "disabled: vrf name red protocols static route 10.2.0.0/16 next-hop "
            "198.51.100.9 (a route the source holds disabled, so it installs nothing; "
            "not translated)"
        ]
        assert rows.static_routes == []

    def test_a_route_disabled_and_leaked_is_said_once_as_disabled(self) -> None:
        tree = _parse(_brace(_route("10.2.0.0/16", "198.51.100.9", "vrf red", "disable")))
        assert tree.static_routes == []
        assert [r for r in tree.dropped_tier3_sections if "another VRF" in r] == []
        assert len([r for r in tree.dropped_tier3_sections if is_left_out_row(r)]) == 1

    def test_a_route_under_another_block_is_not_read_as_one_of_the_global_table(self) -> None:
        """Only the top of the config and ``vrf name <X>`` hold a route:
        a ``protocols static`` block somewhere else is no table of
        either."""
        text = _IFACES + (
            "service {\n    other {\n        protocols {\n            static {\n"
            "                route 10.1.0.0/16 {\n                    next-hop 192.0.2.9 {\n"
            "                    }\n                }\n            }\n        }\n    }\n}\n"
            "system {\n    host-name r1\n}\n"
        )
        assert _routes(text) == []

    def test_no_instance_is_made_for_a_vrf_a_next_hop_names(self) -> None:
        tree = _parse(_brace(_route("10.2.0.0/16", "198.51.100.9", "vrf green")))
        assert sorted(ri.name for ri in tree.routing_instances) == ["blue", "red"]


def _job(text: str, target: str, source: str = "vyos") -> MigrationJob:
    """*text* onto *target*, as the plan endpoints run it."""
    job = run_plan_with_checked_names(
        get_codec(source), get_codec(target), text, port_rename_map={},
    )
    assert job.rendered is not None, f"{source} -> {target}: {job.error}"
    return job


class TestTheRenderer:
    def test_a_route_of_a_vrf_is_written_under_its_vrf(self) -> None:
        out = _job(_BRACE, "vyos").rendered
        block = out[out.index("\nvrf {"):]
        red = block[block.index("    name red {"):]
        red = red[:red.index("\n    }\n")]
        assert "        protocols {\n            static {\n" in red
        assert "                route 10.9.0.0/16 {\n                    next-hop 198.51.100.254 {" in red
        assert "                    next-hop 198.51.100.253 {\n                        distance 4" in red
        assert red.index("protocols {") < red.index("table ")
        top = out[:out.index("\nvrf {")]
        assert "10.9.0.0/16" not in top and "0.0.0.0/0" in top

    def test_every_route_read_comes_back_as_it_was_read(self) -> None:
        assert _routes(_job(_BRACE, "vyos").rendered) == _READ_OF_IT

    def test_a_vrf_a_route_names_and_no_instance_declares_is_written_last(self) -> None:
        """An OS10 ``management route`` (in a VRF the platform has with
        no line of its own for it unless ``ip vrf management`` is
        written) needs a VRF to be in; the VRFs that are declared keep
        their table ids."""
        from netcanon.migration.canonical.intent import (
            CanonicalIntent,
            CanonicalRoutingInstance,
            CanonicalStaticRoute,
        )

        tree = CanonicalIntent(source_vendor="dell_os10", source_format="cli-dellos10")
        tree.hostname = "r1"
        tree.routing_instances = [CanonicalRoutingInstance(name="red")]
        tree.static_routes = [
            CanonicalStaticRoute(destination="0.0.0.0/0", gateway="192.0.2.1", vrf="management"),
            CanonicalStaticRoute(destination="10.9.0.0/16", gateway="192.0.2.2", vrf="red"),
        ]
        out = get_codec("vyos").render(tree)
        names = re.findall(r"^    name (\S+) \{\n(?:.*\n)*?        table (\d+)$", out, re.MULTILINE)
        assert names == [("red", "100"), ("management", "101")]
        back = _parse(out)
        assert sorted((r.vrf, r.destination) for r in back.static_routes) == [
            ("management", "0.0.0.0/0"), ("red", "10.9.0.0/16"),
        ]


_SOURCE = _brace(
    _route("203.0.113.0/24", "192.0.2.250"),
    "".join(
        "        " + line
        for line in (
            _route("10.9.0.0/16", "198.51.100.254") + _route("0.0.0.0/0", "198.51.100.77")
        ).splitlines(keepends=True)
    ),
)


@functools.cache
def _onto(target: str) -> tuple[MigrationJobStatus, list[tuple[str, str]]]:
    """The job's status, and (vrf, destination) of each route the target's
    own parser reads back of its output."""
    job = _job(_SOURCE, target)
    back = get_codec(target).parse(job.rendered)
    return job.status, sorted((r.vrf, r.destination) for r in back.static_routes)


#: The targets that write a route of another vendor's VRF into their one
#: table.  Each says it: the validation report holds the job for
#: ``/routing/static-route/vrf``, which its matrix declares unsupported.
#: Still open; the change that mends one takes it out of this set.
_INTO_THE_GLOBAL_TABLE = {"fortigate_cli", "mikrotik_routeros"}

#: The targets whose renderer writes no static route of any table (each
#: says so: the job is not ``completed``).
_NO_ROUTE_AT_ALL = {"cisco_iosxe", "opnsense"}

#: AOS-S has no VRF: a route of one is left out under a review line.
_LEFT_OUT = {"aruba_aoss"}

_HOLDS_IT = sorted(set(PUBLIC) - _INTO_THE_GLOBAL_TABLE - _NO_ROUTE_AT_ALL - _LEFT_OUT)


class TestOntoEveryTarget:
    @pytest.mark.parametrize("target", PUBLIC)
    def test_no_route_of_a_vrf_is_a_route_of_the_global_table_unsaid(self, target) -> None:
        status, routes = _onto(target)
        if status == MigrationJobStatus.completed:
            assert ("", "10.9.0.0/16") not in routes
            assert ("", "0.0.0.0/0") not in routes

    @pytest.mark.parametrize("target", _HOLDS_IT)
    def test_the_target_holds_each_route_in_its_vrf(self, target) -> None:
        status, routes = _onto(target)
        assert routes == [("", "203.0.113.0/24"), ("red", "0.0.0.0/0"), ("red", "10.9.0.0/16")]
        assert status == MigrationJobStatus.completed

    def test_aoss_leaves_each_route_of_a_vrf_out(self) -> None:
        status, routes = _onto("aruba_aoss")
        assert routes == [("", "203.0.113.0/24")]
        assert status != MigrationJobStatus.completed

    def test_which_targets_write_it_into_their_one_table(self) -> None:
        measured = {
            t for t in PUBLIC
            if ("", "10.9.0.0/16") in _onto(t)[1] and ("", "0.0.0.0/0") in _onto(t)[1]
        }
        assert measured == _INTO_THE_GLOBAL_TABLE
        assert all(_onto(t)[0] != MigrationJobStatus.completed for t in measured)

    def test_which_targets_write_no_route(self) -> None:
        measured = {t for t in PUBLIC if _onto(t)[1] == []}
        assert measured == _NO_ROUTE_AT_ALL
        assert all(_onto(t)[0] != MigrationJobStatus.completed for t in measured)

    @pytest.mark.parametrize("target", _HOLDS_IT)
    def test_the_text_of_each_target_that_holds_a_vrf_names_it(self, target) -> None:
        """Read as text as well as with the target's parser: a parser that
        reads its own global route as a route of the VRF would agree with
        itself.  The VRF is on the route's line or on a line of a block
        the route is in."""
        out = _job(_SOURCE, target).rendered
        for address in ("10.9.0.0", "198.51.100.77"):
            found = _in_context(out, address)
            assert found, (target, address)
            assert all(re.search(r"\bred\b", c) for c in found), (target, address)
        found = _in_context(out, "203.0.113.0")
        assert found and not any(re.search(r"\bred\b", c) for c in found), target


class TestOntoVyOS:
    """A route of a VRF from another vendor is written under its VRF."""

    _IOSXE = (
        "hostname r1\nvrf definition red\n address-family ipv4\n exit-address-family\n!\n"
        "interface GigabitEthernet2\n vrf forwarding red\n"
        " ip address 198.51.100.1 255.255.255.0\n!\n"
        "ip route 203.0.113.0 255.255.255.0 192.0.2.250\n"
        "ip route vrf red 10.9.0.0 255.255.0.0 198.51.100.254\n!\nend\n"
    )

    def test_the_route_is_in_its_vrf_and_the_matrix_says_supported(self) -> None:
        job = _job(self._IOSXE, "vyos", source="cisco_iosxe_cli")
        back = _parse(job.rendered)
        assert sorted((r.vrf, r.destination) for r in back.static_routes) == [
            ("", "203.0.113.0/24"), ("red", "10.9.0.0/16"),
        ]
        unsupported = [u.path for u in job.validation.unsupported_paths]
        assert "/routing/static-route/vrf" not in unsupported
        assert "/routing/static-route/vrf" in job.validation.supported_paths
        found = _in_context(job.rendered, "10.9.0.0")
        assert found and all(re.search(r"\bname red\b", c) for c in found)


def _in_context(text: str, needle: str) -> list[str]:
    """For each line that holds *needle*: the line, with every line of a
    block it is in (each line above it that is less indented, back to
    column 0)."""
    found: list[str] = []
    stack: list[tuple[int, str]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        depth = len(line) - len(line.lstrip())
        while stack and stack[-1][0] >= depth:
            stack.pop()
        if needle in line:
            found.append(" ".join([s for _, s in stack] + [line]))
        stack.append((depth, line))
    return found

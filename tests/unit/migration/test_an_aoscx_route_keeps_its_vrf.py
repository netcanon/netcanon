"""An AOS-CX route keeps its VRF, and its distance.

AOS-CX prints a route of a VRF ``ip route <dest> <gw> vrf <name>``, and
the VRF is the route's own: "If no VRF name is specified, the route is
applied to the default VRF" (HPE, AOS-CX IP Routing Guide).  The parser
read past the word, so every such route was a route of the global table
onto every target, AOS-CX itself included, in a job that said
``completed``; the management default route (``ip route 0.0.0.0/0
<gw> vrf mgmt``) was the GLOBAL default route.  A distance written as
HPE documents it (``distance 4``) was lost the same way, and the
renderer wrote a distance as a bare number, a form no AOS-CX printout
or guide shows.

Each is read here from the parse, and from the OUTPUT of the plan path
the API uses onto every public codec, read back with the target's own
parser and as text.
"""

from __future__ import annotations

import functools
import re

import pytest

from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.models.migration import MigrationJob, MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

PUBLIC = list_public_codecs()

_HEAD = (
    "!Version ArubaOS-CX GL.10.13.1000\nhostname sw1\nvrf red\n!\n"
    "interface 1/1/1\n    no shutdown\n    vrf attach red\n    ip address 192.0.2.1/24\n!\n"
)


def _cx(*lines: str) -> str:
    return _HEAD + "\n".join(lines) + "\n!\n"


def _routes(text: str) -> list[tuple[str, str, str, str, int]]:
    """(vrf, destination, gateway, interface, distance) of each route."""
    tree = get_codec("aruba_aoscx").parse(text)
    return sorted(
        (r.vrf, r.destination, r.gateway, r.interface, r.metric) for r in tree.static_routes
    )


#: A line, and the route the parser reads of it.
_READ = [
    ("ip route 10.9.0.0/16 192.0.2.254 vrf red",
     ("red", "10.9.0.0/16", "192.0.2.254", "", 0)),
    ("ip route 0.0.0.0/0 198.51.100.1 vrf mgmt",
     ("mgmt", "0.0.0.0/0", "198.51.100.1", "", 0)),
    ("ipv6 route 2001:db8:9::/48 2001:db8::fe vrf red",
     ("red", "2001:db8:9::/48", "2001:db8::fe", "", 0)),
    # ``vrf default`` is the global table.
    ("ip route 10.6.0.0/16 192.0.2.251 vrf default",
     ("", "10.6.0.0/16", "192.0.2.251", "", 0)),
    ("ip route 10.8.0.0/16 192.0.2.253 distance 4",
     ("", "10.8.0.0/16", "192.0.2.253", "", 4)),
    # The bare number the renderer wrote up to 0.7.7 is still read.
    ("ip route 10.7.0.0/16 192.0.2.252 5",
     ("", "10.7.0.0/16", "192.0.2.252", "", 5)),
    ("ip route 10.5.0.0/16 192.0.2.250 distance 4 vrf red",
     ("red", "10.5.0.0/16", "192.0.2.250", "", 4)),
    ("ip route 10.5.0.0/16 192.0.2.250 vrf red distance 4",
     ("red", "10.5.0.0/16", "192.0.2.250", "", 4)),
    ("ipv6 route 2001:db8:8::/48 2001:db8::fd distance 7 vrf red",
     ("red", "2001:db8:8::/48", "2001:db8::fd", "", 7)),
    ("ip route 10.4.0.0/16 1/1/1 vrf red",
     ("red", "10.4.0.0/16", "", "1/1/1", 0)),
    ("ip route 10.3.0.0/16 1/1/1 192.0.2.249 vrf red",
     ("red", "10.3.0.0/16", "192.0.2.249", "1/1/1", 0)),
    # A word HPE documents is passed over with what it takes ...
    ("ip route 10.2.0.0/16 192.0.2.248 tag 7 bfd vrf red",
     ("red", "10.2.0.0/16", "192.0.2.248", "", 0)),
    # ... so that what it takes is never read as a VRF or a distance.
    ("ip route 10.1.0.0/16 192.0.2.247 name vrf",
     ("", "10.1.0.0/16", "192.0.2.247", "", 0)),
    ("ip route 10.1.0.0/16 192.0.2.247 tag distance",
     ("", "10.1.0.0/16", "192.0.2.247", "", 0)),
    # The keywords in any letter case; the name as it is written.
    ("ip route 10.0.0.0/16 192.0.2.246 VRF Red DISTANCE 9",
     ("Red", "10.0.0.0/16", "192.0.2.246", "", 9)),
]


class TestTheParser:
    @pytest.mark.parametrize(("line", "route"), _READ, ids=[line for line, _ in _READ])
    def test_the_route_is_read_with_its_vrf_and_its_distance(self, line, route) -> None:
        assert _routes(_cx(line)) == [route]

    @pytest.mark.parametrize("number", ["²", "٣", "9" * 11, "-4", "4x"])
    def test_a_number_that_is_no_distance_is_not_read_as_one(self, number) -> None:
        """A digit of another script, or a run no ``int`` takes, is no
        distance of the switch's: the route is read without one, and the
        parse does not fail."""
        for line in (
            f"ip route 10.9.0.0/16 192.0.2.254 {number} vrf red",
            f"ip route 10.9.0.0/16 192.0.2.254 distance {number} vrf red",
        ):
            assert _routes(_cx(line)) == [("red", "10.9.0.0/16", "192.0.2.254", "", 0)]


class TestTheRenderer:
    def test_a_route_of_a_vrf_ends_with_its_vrf(self) -> None:
        out = _job(_cx("ip route 10.9.0.0/16 192.0.2.254 vrf red"), "aruba_aoscx").rendered
        assert "ip route 10.9.0.0/16 192.0.2.254 vrf red" in out.splitlines()

    def test_a_distance_is_written_as_hpe_documents_it(self) -> None:
        out = _job(_cx(
            "ip route 10.8.0.0/16 192.0.2.253 5",
            "ip route 10.5.0.0/16 192.0.2.250 distance 4 vrf red",
        ), "aruba_aoscx").rendered.splitlines()
        assert "ip route 10.8.0.0/16 192.0.2.253 distance 5" in out
        assert "ip route 10.5.0.0/16 192.0.2.250 distance 4 vrf red" in out
        bare = re.compile(r"^ipv?6? ?route \S+ \S+ \d+(\s|$)")
        assert [line for line in out if bare.match(line)] == []

    def test_every_line_read_comes_back_as_it_was_read(self) -> None:
        text = _cx(*[line for line, _ in _READ])
        assert _routes(_job(text, "aruba_aoscx").rendered) == _routes(text)


def _job(text: str, target: str) -> MigrationJob:
    """*text* onto *target*, as the plan endpoints run it."""
    job = run_plan_with_checked_names(
        get_codec("aruba_aoscx"), get_codec(target), text, port_rename_map={},
    )
    assert job.rendered is not None, f"aruba_aoscx -> {target}: {job.error}"
    return job


_SOURCE = _cx(
    "ip route 10.9.0.0/16 192.0.2.254 vrf red",
    "ip route 0.0.0.0/0 198.51.100.1 vrf mgmt",
    "ip route 203.0.113.0/24 192.0.2.250",
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


class TestOntoEveryTarget:
    @pytest.mark.parametrize("target", PUBLIC)
    def test_no_route_of_a_vrf_is_a_route_of_the_global_table_unsaid(self, target) -> None:
        status, routes = _onto(target)
        if status == MigrationJobStatus.completed:
            assert ("", "10.9.0.0/16") not in routes
            assert ("", "0.0.0.0/0") not in routes

    @pytest.mark.parametrize(
        "target",
        sorted(set(PUBLIC) - _INTO_THE_GLOBAL_TABLE - _NO_ROUTE_AT_ALL - _LEFT_OUT),
    )
    def test_the_target_holds_each_route_in_its_vrf(self, target) -> None:
        status, routes = _onto(target)
        assert routes == [("", "203.0.113.0/24"), ("mgmt", "0.0.0.0/0"), ("red", "10.9.0.0/16")]
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

    def test_the_text_of_each_target_that_holds_a_vrf_names_it(self) -> None:
        """Read as text as well as with the target's parser: a parser that
        reads its own global route as a route of the VRF would agree with
        itself.  The VRF is on the route's line or on a line of a block
        the route is in (IOS XR ``vrf red``, NX-OS ``vrf context red``)."""
        for target in sorted(set(PUBLIC) - _INTO_THE_GLOBAL_TABLE - _NO_ROUTE_AT_ALL - _LEFT_OUT):
            out = _job(_SOURCE, target).rendered
            for address, vrf in (("10.9.0.0", "red"), ("198.51.100.1", "mgmt")):
                found = _in_context(out, address)
                assert found, (target, address)
                assert all(re.search(rf"\b{vrf}\b", c) for c in found), (target, address)


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

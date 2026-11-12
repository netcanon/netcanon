"""A route of a VRF is never written into a target's one table.

A target that writes a VRF writes a route of one into it; a target whose
output puts nothing in a VRF leaves such a route out, and says so where
the route would have been.  FortiOS and RouterOS wrote it as a route of
the global (main) table -- an ``edit`` of ``config router static``, an
``add`` of ``/ip route`` -- where it routed traffic the source routed in
another VRF, in a job that was ``partial`` for the route's VRF and said
nothing more.  AOS-S, which has no VRF, already left it out under a
review line, and now so do they.  (FortiOS names a VRF by a number,
``set vrf <0-251>``, "Virtual Routing Forwarding ID": FortiOS 7.4 CLI
reference, "config router static",
https://docs.fortinet.com/document/fortigate/7.4.0/cli-reference/522620/config-router-static.)

Each public codec is a target here, from two sources that state a VRF
route in their own grammar, and the OUTPUT of the plan path the API
uses is read twice: with the target's own parser (no route of the VRF
is read back as a route of the global table) and as text (on a target
that leaves the route out, every line that names its destination is a
review line).  Which targets leave it out is a set compared for
EQUALITY with what is measured.
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

_IOSXE = """hostname r1
!
vrf definition BLUE
 rd 65000:1
 address-family ipv4
 exit-address-family
 address-family ipv6
 exit-address-family
!
interface GigabitEthernet1
 ip address 192.0.2.1 255.255.255.0
 ipv6 address 2001:db8:1::1/64
!
interface GigabitEthernet2
 vrf forwarding BLUE
 ip address 198.51.100.1 255.255.255.0
 ipv6 address 2001:db8:5::1/64
!
ip route 10.10.0.0 255.255.0.0 192.0.2.254
ip route vrf BLUE 10.20.0.0 255.255.0.0 198.51.100.254
ip route 10.30.0.0 255.255.0.0 192.0.2.253
ipv6 route 2001:db8:10::/48 2001:db8:1::fe
ipv6 route vrf BLUE 2001:db8:20::/48 2001:db8:5::fe
!
end
"""

_JUNOS = """set system host-name r1
set interfaces ge-0/0/1 unit 0 family inet address 192.0.2.1/24
set interfaces ge-0/0/2 unit 0 family inet address 198.51.100.1/24
set routing-options static route 10.10.0.0/16 next-hop 192.0.2.254
set routing-instances BLUE instance-type vrf
set routing-instances BLUE interface ge-0/0/2.0
set routing-instances BLUE route-distinguisher 65000:1
set routing-instances BLUE vrf-target target:65000:1
set routing-instances BLUE routing-options static route 10.20.0.0/16 next-hop 198.51.100.254
"""

#: Each source, and the destinations of its routes of VRF ``BLUE``.
_SOURCES = {
    "cisco_iosxe_cli": (_IOSXE, ("10.20.0.0/16", "2001:db8:20::/48")),
    "juniper_junos": (_JUNOS, ("10.20.0.0/16",)),
}

#: The targets whose output does not hold a route of a VRF, and why.
#: Every other public codec writes the route in its VRF and reads it
#: back there.
_NOT_WRITTEN = {
    "aruba_aoss": "review line: AOS-S has no VRF",
    "cisco_iosxe": "the OpenConfig render holds no static route at all",
    "fortigate_cli": "review line: the output puts nothing in a VRF",
    "mikrotik_routeros": "review line: the output puts nothing in a VRF",
    "opnsense": "the output holds no static route at all",
}

#: The targets of :data:`_NOT_WRITTEN` that say so in a review line.
_SAID = {"aruba_aoss", "fortigate_cli", "mikrotik_routeros"}


@functools.cache
def _job(source: str, target: str) -> MigrationJob:
    text, _ = _SOURCES[source]
    return run_plan_with_checked_names(get_codec(source), get_codec(target), text, {})


def _read_back(target: str, rendered: str) -> list[tuple[str, str]]:
    """(vrf, destination) of each route the target's parser reads."""
    return [(r.vrf, r.destination) for r in get_codec(target).parse(rendered).static_routes]


def _in_the_one_table(target: str, rendered: str, destinations: tuple[str, ...]) -> list[str]:
    """The destinations of *destinations* the target's parser reads back
    as routes of the global table."""
    return [d for vrf, d in _read_back(target, rendered) if d in destinations and not vrf]


def _forms(destination: str) -> tuple[str, ...]:
    """The ways an output spells *destination*: as a prefix, and as an
    address and dotted mask."""
    address, length = destination.split("/")
    if ":" in address:
        return (destination,)
    bits = (0xFFFFFFFF << (32 - int(length))) & 0xFFFFFFFF
    mask = ".".join(str((bits >> s) & 0xFF) for s in (24, 16, 8, 0))
    return (destination, f"{address} {mask}")


def _lines_naming(rendered: str, destination: str) -> list[str]:
    forms = _forms(destination)
    return [
        line for line in rendered.splitlines()
        if any(re.search(rf"(?<![\w.:]){re.escape(f)}(?![\w.:/])", line) for f in forms)
    ]


class TestEveryTarget:
    @pytest.mark.parametrize("target", PUBLIC)
    @pytest.mark.parametrize("source", sorted(_SOURCES))
    def test_no_route_of_a_vrf_is_read_back_in_the_global_table(
        self, source: str, target: str,
    ) -> None:
        _, vrf_routes = _SOURCES[source]
        rendered = _job(source, target).rendered or ""
        assert not _in_the_one_table(target, rendered, vrf_routes)

    def test_which_targets_leave_it_out(self) -> None:
        """Measured: a target leaves the route out when its parser reads
        no route of that destination back from the output at all."""
        left_out = set()
        for target in PUBLIC:
            rendered = _job("cisco_iosxe_cli", target).rendered or ""
            back = {d for _, d in _read_back(target, rendered)}
            if "10.20.0.0/16" not in back:
                left_out.add(target)
        assert left_out == set(_NOT_WRITTEN)

    @pytest.mark.parametrize("target", sorted(_NOT_WRITTEN))
    @pytest.mark.parametrize("source", sorted(_SOURCES))
    def test_a_target_that_leaves_it_out_writes_it_nowhere(
        self, source: str, target: str,
    ) -> None:
        """Read as text: every line that names the destination of a
        route of the VRF is a review line."""
        _, vrf_routes = _SOURCES[source]
        rendered = _job(source, target).rendered or ""
        for destination in vrf_routes:
            lines = _lines_naming(rendered, destination)
            assert all("review:" in line for line in lines), (target, lines)
            if target in _SAID:
                assert any("is in VRF BLUE" in line for line in lines), (target, destination)

    @pytest.mark.parametrize("target", sorted(_NOT_WRITTEN))
    @pytest.mark.parametrize("source", sorted(_SOURCES))
    def test_and_its_job_is_not_completed(self, source: str, target: str) -> None:
        assert _job(source, target).status != MigrationJobStatus.completed

    @pytest.mark.parametrize("target", sorted(_SAID - {"aruba_aoss"}))
    def test_the_routes_of_the_global_table_are_still_written(self, target: str) -> None:
        back = set(_read_back(target, _job("cisco_iosxe_cli", target).rendered or ""))
        assert {("", "10.10.0.0/16"), ("", "10.30.0.0/16")} <= back


class TestFortiOS:
    def test_the_edits_are_numbered_without_a_gap(self) -> None:
        rendered = _job("cisco_iosxe_cli", "fortigate_cli").rendered or ""
        static = rendered.split("config router static\n", 1)[1].split("\nend", 1)[0]
        assert re.findall(r"^    edit (\d+)$", static, re.MULTILINE) == ["1", "2"]

    def test_a_route_of_ipv6_is_left_out_of_static6(self) -> None:
        rendered = _job("cisco_iosxe_cli", "fortigate_cli").rendered or ""
        static6 = rendered.split("config router static6\n", 1)[1].split("\nend", 1)[0]
        assert "    # review: static route 2001:db8:20::/48 is in VRF BLUE" in static6
        assert "set dst 2001:db8:10::/48" in static6


class TestTheChecksCanFail:
    """Each check is handed an output with the defect it is for."""

    _FORTIOS_AS_IT_WAS = (
        "config router static\n"
        "    edit 1\n"
        "        set dst 10.20.0.0 255.255.0.0\n"
        "        set gateway 198.51.100.254\n"
        "    next\n"
        "end\n"
    )
    _ROUTEROS_AS_IT_WAS = "/ip route\nadd dst-address=10.20.0.0/16 gateway=198.51.100.254\n"

    def test_the_parse_check_sees_a_route_in_the_global_table(self) -> None:
        assert _in_the_one_table("fortigate_cli", self._FORTIOS_AS_IT_WAS, ("10.20.0.0/16",))
        assert _in_the_one_table("mikrotik_routeros", self._ROUTEROS_AS_IT_WAS, ("10.20.0.0/16",))

    def test_the_text_check_sees_a_line_that_is_no_review(self) -> None:
        for rendered in (self._FORTIOS_AS_IT_WAS, self._ROUTEROS_AS_IT_WAS):
            lines = _lines_naming(rendered, "10.20.0.0/16")
            assert lines and not all("review:" in line for line in lines)

    def test_the_text_check_does_not_take_a_longer_prefix(self) -> None:
        assert not _lines_naming("ip route 10.20.0.0/160 x\n10.20.0.0.5\n", "10.20.0.0/16")

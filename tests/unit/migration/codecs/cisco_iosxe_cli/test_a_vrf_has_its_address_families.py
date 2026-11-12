"""An IOS-XE VRF is written with the address families its addresses need.

An address on an interface bound to a VRF "requires that the address
family corresponding to the address type is active for that VRF.
Otherwise, an error message is issued stating that the address family
must be activated first in the VRF" (Cisco, "MPLS VPN VRF CLI for IPv4
and IPv6 VPNs").  The renderer wrote ``address-family ipv4`` only
where it had a route target to put in it, and ``address-family ipv6``
nowhere, so an output of a VRF with no route target was a config whose
every address in that VRF IOS-XE refuses -- from every source, IOS-XE
itself included.  And a VRF an interface or a route named and no
instance declared was named (``vrf forwarding <name>``) and not
defined, which IOS-XE refuses as well.

The output is read as TEXT here, by a reader of this module's own: the
codec's parser does not read the ``address-family`` lines at all, so it
cannot say whether they are there.
"""

from __future__ import annotations

import functools
import re

import pytest

from netcanon.migration.codecs.registry import get_codec
from netcanon.models.migration import MigrationJob
from netcanon.services.migration_pipeline import run_plan_with_checked_names
from tests.unit.migration.test_vlan_members_reach_the_output import CAPTURES

pytestmark = pytest.mark.unit

TARGET = "cisco_iosxe_cli"


# ---------------------------------------------------------------------------
# Reading the output
# ---------------------------------------------------------------------------


def _stanzas(text: str) -> list[tuple[str, list[str]]]:
    """(header, indented lines) of each stanza of an IOS-XE text."""
    found: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        if line.startswith(" "):
            if found:
                found[-1][1].append(line)
        elif line and line != "!":
            found.append((line, []))
    return found


_FAMILY_LINE = re.compile(r" address-family (ipv4|ipv6)")
_V4_ADDRESS = re.compile(r" ip address \S")
_V6_ADDRESS = re.compile(r" ipv6 address \S")
_VRF_ROUTE = re.compile(r"(ip|ipv6) route vrf (\S+) ")


def _read(text: str) -> tuple[dict[str, set[str]], list[tuple[str, str, str]]]:
    """The families each ``vrf definition`` of *text* has, and what the
    rest of *text* needs: (VRF, family or ``""`` for "defined", where)."""
    defined: dict[str, set[str]] = {}
    needs: list[tuple[str, str, str]] = []
    for head, body in _stanzas(text):
        definition = re.fullmatch(r"vrf definition (\S+)", head)
        if definition:
            defined[definition.group(1)] = {
                m.group(1) for line in body if (m := _FAMILY_LINE.fullmatch(line))
            }
            continue
        route = _VRF_ROUTE.match(head)
        if route:
            family = "ipv6" if route.group(1) == "ipv6" else "ipv4"
            needs.append((route.group(2), family, head.split()[0]))
            continue
        if not head.startswith("interface "):
            continue
        vrf = next(
            (line.split()[2] for line in body if line.startswith(" vrf forwarding ")), "",
        )
        if not vrf:
            continue
        needs.append((vrf, "", head))
        if any(_V4_ADDRESS.match(line) for line in body):
            needs.append((vrf, "ipv4", head))
        if any(_V6_ADDRESS.match(line) for line in body):
            needs.append((vrf, "ipv6", head))
    return defined, needs


def _problems(text: str) -> list[str]:
    defined, needs = _read(text)
    problems = []
    for vrf, family, where in needs:
        if vrf not in defined:
            problems.append(f"{where}: VRF {vrf} is not defined")
        elif family and family not in defined[vrf]:
            problems.append(f"{where}: VRF {vrf} has no address-family {family}")
    return sorted(set(problems))


class TestTheReader:
    """The reader is handed each defect it is for, and finds it."""

    def test_a_missing_family_is_found(self) -> None:
        text = (
            "vrf definition RED\n rd 65000:1\n!\n"
            "interface GigabitEthernet1\n vrf forwarding RED\n"
            " ip address 192.0.2.2 255.255.255.0\n ipv6 address 2001:db8::2/64\n!\n"
        )
        assert _problems(text) == [
            "interface GigabitEthernet1: VRF RED has no address-family ipv4",
            "interface GigabitEthernet1: VRF RED has no address-family ipv6",
        ]

    def test_an_undefined_vrf_is_found(self) -> None:
        text = (
            "interface GigabitEthernet1\n vrf forwarding GREEN\n!\n"
            "ip route vrf BLUE 10.0.0.0 255.0.0.0 192.0.2.1\n"
        )
        assert _problems(text) == [
            "interface GigabitEthernet1: VRF GREEN is not defined",
            "ip: VRF BLUE is not defined",
        ]

    def test_a_route_needs_its_family(self) -> None:
        text = (
            "vrf definition RED\n address-family ipv4\n exit-address-family\n!\n"
            "ipv6 route vrf RED 2001:db8:9::/48 2001:db8::1\n"
        )
        assert _problems(text) == ["ipv6: VRF RED has no address-family ipv6"]

    def test_a_right_text_has_none(self) -> None:
        text = (
            "vrf definition RED\n address-family ipv4\n exit-address-family\n"
            " address-family ipv6\n exit-address-family\n!\n"
            "interface GigabitEthernet1\n vrf forwarding RED\n"
            " ip address 192.0.2.2 255.255.255.0\n ipv6 address 2001:db8::2/64\n!\n"
        )
        assert _problems(text) == []


# ---------------------------------------------------------------------------
# A VRF from each grammar
# ---------------------------------------------------------------------------

#: A VRF ``RED`` with one interface, which has an IPv4 and an IPv6
#: address, in each grammar that binds an interface to a VRF.
_SOURCES = {
    "cisco_iosxe_cli": (
        "hostname r1\n"
        "vrf definition RED\n address-family ipv4\n exit-address-family\n"
        " address-family ipv6\n exit-address-family\n!\n"
        "interface GigabitEthernet1\n vrf forwarding RED\n"
        " ip address 192.0.2.2 255.255.255.0\n ipv6 address 2001:db8::2/64\n!\n"
    ),
    "cisco_nxos": (
        "hostname n1\n"
        "vrf context RED\n"
        "interface Ethernet1/1\n  no switchport\n  vrf member RED\n"
        "  ip address 192.0.2.2/24\n  ipv6 address 2001:db8::2/64\n"
    ),
    "arista_eos": (
        "hostname e1\n"
        "vrf instance RED\n!\n"
        "interface Ethernet1\n   no switchport\n   vrf RED\n"
        "   ip address 192.0.2.2/24\n   ipv6 address 2001:db8::2/64\n!\n"
    ),
    "juniper_junos": (
        "set system host-name j1\n"
        "set interfaces ge-0/0/1 unit 0 family inet address 192.0.2.2/24\n"
        "set interfaces ge-0/0/1 unit 0 family inet6 address 2001:db8::2/64\n"
        "set routing-instances RED instance-type virtual-router\n"
        "set routing-instances RED interface ge-0/0/1.0\n"
    ),
    "dell_os10": (
        "hostname s1\n"
        "ip vrf RED\n"
        "interface ethernet1/1/1\n no switchport\n ip vrf forwarding RED\n"
        " ip address 192.0.2.2/24\n ipv6 address 2001:db8::2/64\n"
    ),
    "aruba_aoscx": (
        "hostname c1\n"
        "vrf RED\n"
        "interface 1/1/1\n    no shutdown\n    routing\n    vrf attach RED\n"
        "    ip address 192.0.2.2/24\n    ipv6 address 2001:db8::2/64\n"
    ),
    "vyos": (
        "set system host-name v1\n"
        "set vrf name RED table 100\n"
        "set interfaces ethernet eth1 vrf RED\n"
        "set interfaces ethernet eth1 address 192.0.2.2/24\n"
        "set interfaces ethernet eth1 address 2001:db8::2/64\n"
    ),
    "cisco_iosxr": (
        "hostname x1\n"
        "vrf RED\n!\n"
        "interface GigabitEthernet0/0/0/1\n vrf RED\n"
        " ipv4 address 192.0.2.2 255.255.255.0\n ipv6 address 2001:db8::2/64\n!\n"
    ),
}


@functools.cache
def _job(source: str, text: str) -> MigrationJob:
    job = run_plan_with_checked_names(
        get_codec(source), get_codec(TARGET), text, port_rename_map={},
    )
    assert job.rendered, f"{source} -> {TARGET}: {job.error}"
    return job


class TestFromEachGrammar:
    @pytest.mark.parametrize("source", sorted(_SOURCES))
    def test_the_vrf_has_both_families(self, source: str) -> None:
        defined, needs = _read(_job(source, _SOURCES[source]).rendered)
        # The interface reached the output in its VRF with both
        # addresses, so the check below has something to check.
        assert {(vrf, family) for vrf, family, _ in needs} == {
            ("RED", ""), ("RED", "ipv4"), ("RED", "ipv6"),
        }, source
        assert defined["RED"] == {"ipv4", "ipv6"}, source
        assert _problems(_job(source, _SOURCES[source]).rendered) == [], source


# ---------------------------------------------------------------------------
# What is written, and the round trip
# ---------------------------------------------------------------------------

_IOSXE = (
    "hostname r1\n"
    "vrf definition RT\n rd 65000:1\n address-family ipv4\n"
    "  route-target import 65000:1\n exit-address-family\n!\n"
    "vrf definition V4\n address-family ipv4\n exit-address-family\n!\n"
    "vrf definition V6ONLY\n address-family ipv6\n exit-address-family\n!\n"
    "vrf definition EMPTY\n!\n"
    "vrf definition ROUTES\n!\n"
    "interface GigabitEthernet1\n vrf forwarding V4\n ip address dhcp\n!\n"
    "interface GigabitEthernet2\n vrf forwarding V6ONLY\n ipv6 address autoconfig\n!\n"
    "interface GigabitEthernet3\n vrf forwarding UNDECLARED\n"
    " ip address 203.0.113.2 255.255.255.0\n!\n"
    "ipv6 route vrf ROUTES 2001:db8:9::/48 2001:db8::1\n"
    "ip route vrf ROUTES 10.9.0.0 255.255.0.0 192.0.2.1\n"
    "ip route vrf ELSEWHERE 10.8.0.0 255.255.0.0 192.0.2.1\n"
)


class TestWhatIsWritten:
    def test_each_vrf_has_the_families_it_uses(self) -> None:
        defined, _ = _read(_job("cisco_iosxe_cli", _IOSXE).rendered)
        assert defined == {
            "RT": {"ipv4"},            # its route target is under ipv4
            "V4": {"ipv4"},            # ip address dhcp
            "V6ONLY": {"ipv6"},        # nothing in it is IPv4
            "EMPTY": {"ipv4"},         # nothing says IPv6
            "ROUTES": {"ipv4", "ipv6"},
            "UNDECLARED": {"ipv4"},
            "ELSEWHERE": {"ipv4"},
        }

    def test_an_undeclared_vrf_is_defined_after_the_declared_ones(self) -> None:
        heads = [
            head for head, _ in _stanzas(_job("cisco_iosxe_cli", _IOSXE).rendered)
            if head.startswith("vrf definition ")
        ]
        assert heads == [
            "vrf definition RT", "vrf definition V4", "vrf definition V6ONLY",
            "vrf definition EMPTY", "vrf definition ROUTES",
            "vrf definition UNDECLARED", "vrf definition ELSEWHERE",
        ]

    def test_the_route_targets_stay_in_the_ipv4_block(self) -> None:
        out = _job("cisco_iosxe_cli", _IOSXE).rendered
        assert (
            "vrf definition RT\n rd 65000:1\n address-family ipv4\n"
            "  route-target import 65000:1\n exit-address-family\n!\n"
        ) in out

    def test_the_output_parses_and_renders_again_as_it_is(self) -> None:
        codec = get_codec(TARGET)
        out = _job("cisco_iosxe_cli", _IOSXE).rendered
        assert codec.render(codec.parse(out)) == out


# ---------------------------------------------------------------------------
# Every committed input
# ---------------------------------------------------------------------------


@functools.cache
def _committed(index: int) -> str:
    """The IOS-XE output of a committed input ("" where it is refused)."""
    codec, _rel, path = CAPTURES[index]
    job = run_plan_with_checked_names(
        get_codec(codec), get_codec(TARGET), path.read_text(encoding="utf-8"),
        port_rename_map={},
    )
    return job.rendered or ""


class TestEveryCommittedInput:
    @pytest.mark.parametrize(
        "index", range(len(CAPTURES)), ids=[rel for _codec, rel, _path in CAPTURES],
    )
    def test_no_vrf_is_missing_or_without_a_family(self, index: int) -> None:
        assert _problems(_committed(index)) == []

    def test_the_check_reads_the_vrfs_of_the_inputs(self) -> None:
        """A reader that finds nothing passes every input: the committed
        inputs put an interface into a VRF onto IOS-XE many times over."""
        bound = sum(
            1 for index in range(len(CAPTURES))
            for _vrf, family, _where in _read(_committed(index))[1] if family == ""
        )
        assert bound >= 150, bound

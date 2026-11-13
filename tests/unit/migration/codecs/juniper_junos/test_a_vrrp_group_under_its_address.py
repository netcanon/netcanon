"""A VRRP group is written under ONE address of its unit on Junos: the
one whose subnet holds its virtual address.

Junos configures ``vrrp-group`` under a ``family inet address``
(Juniper, "Configuring Basic VRRP Support"); the tree keeps a unit's
groups beside its addresses, with nothing that says which address each
was under.  Up to 0.7.7 every group was written under every address of
its unit, so a unit of two subnets and a group for each came out with
each group configured twice, once under an address of the other
subnet, Junos to Junos included, in jobs that said ``completed``.

The output is read here as TEXT, by a reader this module owns: the
Junos parser keys a unit's groups by group id and keeps no address, so
it reads the defect and the mend alike.  Which subnet holds an address
is asked of :mod:`ipaddress`, not of the renderer.
"""

from __future__ import annotations

import ipaddress
import re

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalVRRPGroup,
)
from netcanon.migration.codecs.juniper_junos import codec as junos_codec
from netcanon.migration.codecs.juniper_junos import render as junos_render
from netcanon.migration.codecs.registry import get_codec
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

#: ``set interfaces <device> unit <n> family inet address <a/len>
#: vrrp-group <id> virtual-address <vip>``
_VIP_LINE = re.compile(
    r"^set interfaces (\S+) unit (\d+) family inet address (\S+) "
    r"vrrp-group (\d+) virtual-address (\S+)$"
)
_GROUP_LINE = re.compile(
    r"^set interfaces (\S+) unit (\d+) family inet address (\S+) vrrp-group (\d+) "
)
_REVIEW = re.compile(r"^# review: vrrp-group (\d+) of (\S+) unit (\d+) is written under (\S+),")


def _under(text: str) -> dict[tuple[str, str, str], set[str]]:
    """(device, unit, group id) -> every address a line of the group is
    under."""
    found: dict[tuple[str, str, str], set[str]] = {}
    for line in text.splitlines():
        hit = _GROUP_LINE.match(line)
        if hit:
            found.setdefault((hit.group(1), hit.group(2), hit.group(4)), set()).add(hit.group(3))
    return found


def _vips(text: str) -> dict[tuple[str, str, str], list[str]]:
    """(device, unit, group id) -> the group's virtual addresses."""
    found: dict[tuple[str, str, str], list[str]] = {}
    for line in text.splitlines():
        hit = _VIP_LINE.match(line)
        if hit:
            found.setdefault((hit.group(1), hit.group(2), hit.group(4)), []).append(hit.group(5))
    return found


def _addresses(text: str) -> dict[tuple[str, str], list[str]]:
    """(device, unit) -> its IPv4 addresses, in the order written."""
    found: dict[tuple[str, str], list[str]] = {}
    for line in text.splitlines():
        hit = re.match(r"^set interfaces (\S+) unit (\d+) family inet address (\S+)$", line)
        if hit:
            found.setdefault((hit.group(1), hit.group(2)), []).append(hit.group(3))
    return found


def _holds(address: str, vip: str) -> bool:
    return ipaddress.IPv4Address(vip) in ipaddress.IPv4Interface(address).network


def check_each_group_under_one_address(text: str) -> int:
    """Every group of *text* is under one address: the first of its
    unit whose subnet holds one of the group's virtual addresses, taken
    in the order the group lists them, else the unit's first.  Returns
    how many groups it read."""
    under = _under(text)
    vips = _vips(text)
    addresses = _addresses(text)
    for key, where in under.items():
        assert len(where) == 1, f"group {key} is under {sorted(where)}"
        (address,) = where
        unit = addresses[key[:2]]
        holders = [a for vip in vips[key] for a in unit if _holds(a, vip)]
        want = holders[0] if holders else unit[0]
        assert address == want, f"group {key} is under {address}, not {want}"
    return len(under)


def _job(source: str, text: str):
    return run_plan_with_checked_names(
        get_codec(source), get_codec("juniper_junos"), text, port_rename_map={},
    )


#: A unit of two subnets and a group for each, in each grammar whose
#: parser reads two addresses and two groups on one interface.
SOURCES: dict[str, str] = {
    "juniper_junos": "\n".join([
        "set system host-name r1",
        "set interfaces ge-0/0/1 unit 0 family inet address 10.1.0.2/24 vrrp-group 1 virtual-address 10.1.0.1",
        "set interfaces ge-0/0/1 unit 0 family inet address 10.1.0.2/24 vrrp-group 1 priority 200",
        "set interfaces ge-0/0/1 unit 0 family inet address 10.2.0.2/24 vrrp-group 2 virtual-address 10.2.0.1",
        "set interfaces ge-0/0/1 unit 0 family inet address 10.2.0.2/24 vrrp-group 2 priority 150",
        "set interfaces ge-0/0/2 vlan-tagging",
        "set interfaces ge-0/0/2 unit 100 vlan-id 100",
        "set interfaces ge-0/0/2 unit 100 family inet address 10.3.0.2/24 vrrp-group 3 virtual-address 10.3.0.1",
        "set interfaces ge-0/0/2 unit 100 family inet address 10.4.0.2/24 vrrp-group 4 virtual-address 10.4.0.1",
        "",
    ]),
    "cisco_iosxe_cli": "\n".join([
        "hostname r1", "!", "interface GigabitEthernet1",
        " ip address 10.1.0.2 255.255.255.0",
        " ip address 10.2.0.2 255.255.255.0 secondary",
        " vrrp 1 ip 10.1.0.1", " vrrp 1 priority 200",
        " vrrp 2 ip 10.2.0.1", " vrrp 2 priority 150", "!", "end", "",
    ]),
    "arista_eos": "\n".join([
        "hostname r1", "!", "interface Ethernet1", "   no switchport",
        "   ip address 10.1.0.2/24", "   ip address 10.2.0.2/24 secondary",
        "   vrrp 1 ipv4 10.1.0.1", "   vrrp 1 priority-level 200",
        "   vrrp 2 ipv4 10.2.0.1", "   vrrp 2 priority-level 150", "!", "end", "",
    ]),
    "aruba_aoss": "\n".join([
        'hostname "r1"', "vlan 10", '   name "v10"',
        "   ip address 10.1.0.2 255.255.255.0", "   ip address 10.2.0.2 255.255.255.0",
        "   vrrp vrid 1", "      virtual-ip-address 10.1.0.1", "      priority 200",
        "      enable", "      exit",
        "   vrrp vrid 2", "      virtual-ip-address 10.2.0.1", "      priority 150",
        "      enable", "      exit",
        "   exit", "",
    ]),
}

#: How many groups each source's job writes.
GROUPS = {"juniper_junos": 4, "cisco_iosxe_cli": 2, "arista_eos": 2, "aruba_aoss": 2}


class TestEachGroupUnderItsAddress:
    @pytest.mark.parametrize("source", sorted(SOURCES))
    def test_from_each_source(self, source):
        job = _job(source, SOURCES[source])
        assert check_each_group_under_one_address(job.rendered) == GROUPS[source]
        assert "# review: vrrp-group" not in job.rendered
        assert not [w for w in job.warnings if w.startswith("VRRP group")]

    def test_a_junos_config_comes_back_as_it_was(self):
        """Junos to Junos, each group's lines are the source's own."""
        text = SOURCES["juniper_junos"]
        job = _job("juniper_junos", text)
        assert job.status.value == "completed"
        wanted = {line for line in text.splitlines() if " vrrp-group " in line}
        written = {line for line in job.rendered.splitlines() if " vrrp-group " in line}
        assert wanted <= written
        assert {(k[0], k[2]): v for k, v in _under(job.rendered).items()} == {
            ("ge-0/0/1", "1"): {"10.1.0.2/24"},
            ("ge-0/0/1", "2"): {"10.2.0.2/24"},
            ("ge-0/0/2", "3"): {"10.3.0.2/24"},
            ("ge-0/0/2", "4"): {"10.4.0.2/24"},
        }


def _tree(addresses: list[str], groups: list[tuple[int, list[str]]], name: str = "ge-0/0/1"):
    return CanonicalIntent(interfaces=[
        CanonicalInterface(
            name=name,
            ipv4_addresses=[
                CanonicalIPv4Address(ip=a.split("/")[0], prefix_length=int(a.split("/")[1]))
                for a in addresses
            ],
            vrrp_groups=[CanonicalVRRPGroup(group_id=g, virtual_ips=v) for g, v in groups],
        ),
    ])


class TestWhereNoAddressHoldsIt:
    """A group whose virtual address is in no subnet of its unit, or a
    group whose virtual addresses are in two."""

    TREE = (
        ["10.1.0.2/24", "10.2.0.2/24"],
        [
            (1, ["10.1.0.1"]),
            (2, ["10.2.0.1"]),
            (3, ["10.9.0.1"]),               # in no subnet of the unit
            (4, ["10.2.0.5", "10.1.0.5"]),   # one in each
        ],
    )

    def test_each_is_written_once_and_said(self):
        tree = _tree(*self.TREE)
        out = get_codec("juniper_junos").render(tree)
        assert check_each_group_under_one_address(out) == 4
        assert {k[2]: v for k, v in _under(out).items()} == {
            "1": {"10.1.0.2/24"}, "2": {"10.2.0.2/24"},
            "3": {"10.1.0.2/24"}, "4": {"10.2.0.2/24"},
        }
        reviews = [_REVIEW.match(line).groups() for line in out.splitlines() if _REVIEW.match(line)]
        assert reviews == [
            ("3", "ge-0/0/1", "0", "10.1.0.2/24"),
            ("4", "ge-0/0/1", "0", "10.2.0.2/24"),
        ]
        assert "does not hold its virtual address 10.9.0.1;" in out
        assert "does not hold its virtual address 10.1.0.5;" in out
        assert "not established" in out

    def test_one_warning_for_each_review_line(self):
        tree = _tree(*self.TREE)
        warnings = [w for w in get_codec("juniper_junos").render_warnings(tree) if w.startswith("VRRP group")]
        assert len(warnings) == 2
        assert warnings[0].startswith("VRRP group 3 of ge-0/0/1 is written under address 10.1.0.2/24")
        assert warnings[1].startswith("VRRP group 4 of ge-0/0/1 is written under address 10.2.0.2/24")

    def test_a_unit_of_one_address_is_as_it_was(self):
        """With one address there is nothing to choose: the group is
        under it, whatever its subnet, and no line is added."""
        tree = _tree(["10.1.0.2/24"], [(1, ["10.9.0.1"])])
        out = get_codec("juniper_junos").render(tree)
        assert _under(out) == {("ge-0/0/1", "0", "1"): {"10.1.0.2/24"}}
        assert "# review: vrrp-group" not in out
        assert not [w for w in get_codec("juniper_junos").render_warnings(tree) if w.startswith("VRRP group")]

    def test_a_sub_interface_too(self):
        tree = _tree(["10.3.0.2/24", "10.4.0.2/24"], [(3, ["10.4.0.1"]), (4, ["10.8.0.1"])], name="ge-0/0/2.100")
        tree.interfaces[0].dot1q_vlan = 100
        out = get_codec("juniper_junos").render(tree)
        assert _under(out) == {
            ("ge-0/0/2", "100", "3"): {"10.4.0.2/24"},
            ("ge-0/0/2", "100", "4"): {"10.3.0.2/24"},
        }
        assert [_REVIEW.match(line).groups() for line in out.splitlines() if _REVIEW.match(line)] == [
            ("4", "ge-0/0/2", "100", "10.3.0.2/24"),
        ]

    def test_a_group_junos_does_not_write_is_still_not_written(self):
        tree = _tree(["10.1.0.2/24", "10.2.0.2/24"], [(5, ["10.1.0.1"])])
        tree.interfaces[0].vrrp_groups[0].mode = "hsrp"
        tree.interfaces[0].vrrp_groups.append(
            CanonicalVRRPGroup(group_id=6, virtual_ips=[], virtual_ipv6s=["2001:db8::1"]),
        )
        out = get_codec("juniper_junos").render(tree)
        assert "vrrp-group" not in out


# ---------------------------------------------------------------------------
# Each check is handed the defect it is for
# ---------------------------------------------------------------------------


def _every_group_under_every_address(addresses, groups):
    """The renderer as it was: each group under each address."""
    written = [g for g in groups if g.mode == "vrrp" and g.virtual_ips]
    return [[junos_render._Placed(g, []) for g in written] for _ in addresses]


def _every_group_under_the_first(addresses, groups):
    """A renderer that writes each group once, under the first address."""
    written = [g for g in groups if g.mode == "vrrp" and g.virtual_ips]
    placed = [[] for _ in addresses]
    if addresses:
        placed[0] = [junos_render._Placed(g, []) for g in written]
    return placed


class TestTheChecksCanFail:
    @pytest.mark.parametrize("defect", [_every_group_under_every_address, _every_group_under_the_first])
    @pytest.mark.parametrize("source", sorted(SOURCES))
    def test_the_text_check(self, monkeypatch, source, defect):
        monkeypatch.setattr(junos_render, "_vrrp_placement", defect)
        job = _job(source, SOURCES[source])
        with pytest.raises(AssertionError):
            check_each_group_under_one_address(job.rendered)

    def test_the_review_lines(self, monkeypatch):
        def no_review(addresses, groups):
            return [
                [junos_render._Placed(e.group, []) for e in entries]
                for entries in real(addresses, groups)
            ]

        real = junos_render._vrrp_placement
        monkeypatch.setattr(junos_render, "_vrrp_placement", no_review)
        with pytest.raises(AssertionError):
            TestWhereNoAddressHoldsIt().test_each_is_written_once_and_said()
        with pytest.raises(AssertionError):
            TestWhereNoAddressHoldsIt().test_one_warning_for_each_review_line()

    def test_the_warnings(self, monkeypatch):
        monkeypatch.setattr(junos_codec, "vrrp_placement_warnings", lambda tree: [])
        with pytest.raises(AssertionError):
            TestWhereNoAddressHoldsIt().test_one_warning_for_each_review_line()

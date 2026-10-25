"""A Junos unit the tree has no form for is left out, and said.

A unit is not always a routed sub-interface.  Under ``encapsulation
flexible-ethernet-services`` a port takes units of several kinds (the
statement "allows the ethernet-switching family to be configured on
any logical interface unit number instead of only unit 0", Juniper,
Flexible Ethernet Services); a ``vlan-bridge`` unit is a bridge
domain's, a ``vlan-ccc`` unit a cross-connect's ("you can configure the
``ccc`` family only", Juniper, ``encapsulation (Logical Interface)``),
a ``vlan-vpls`` unit a VPLS circuit's, and a ``family bridge`` unit 0
a bridge domain's port.  Each was read as a routed sub-interface with its
tag, or as an empty one, in a job that said ``completed`` with nothing
to report; and a port's own ``encapsulation`` was not read at all.

Now a unit that states a family other than ``inet``, ``inet6``,
``iso`` and ``mpls`` (``ethernet-switching`` above unit 0 among them),
or an ``encapsulation`` and no inet family, is left out with a row of
the Tier-3 banner; a routed unit's ``encapsulation`` and a port's are
said in another.  The job's status is the Tier-3 banner's, as for any
section that is not translated.

What is read here is the rendered output of every public target, as
text by a reader of this module's own (no line holds the tag or the
number of a unit left out) and with the target's own parser (no
interface carries such a tag; the routed unit's address is on one
interface, with its tag), and the rows of the tree, typed by hand.
Each check is handed the defect it is for: every unit read as before,
and unit 0 read as before.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from netcanon.migration.codecs.juniper_junos import parse as junos_parse
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.models.migration import MigrationJob, MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan_with_checked_names
from tests.unit.migration.test_units_follow_their_port import _holders, _tags

JUNOS = "juniper_junos"
REAL = Path(__file__).resolve().parents[4] / "fixtures" / "real" / "junos"

_ROUTED_IP = "198.51.100.1"
_ROUTED_TAG = 3200

#: A port under flexible-ethernet-services with a unit of each kind
#: Juniper documents for it and a routed unit; a port of a
#: cross-connect; a port of a VPLS circuit, in an instance; and a
#: tagged unit 0 that bridges.  Each unit left out is numbered and
#: tagged 3101 to 3106, which nothing else in the config is.
_UNITS = "\n".join([
    "set system host-name r1",
    "set interfaces xe-0/0/1 flexible-vlan-tagging",
    "set interfaces xe-0/0/1 encapsulation flexible-ethernet-services",
    "set interfaces xe-0/0/1 unit 3101 encapsulation vlan-bridge",
    "set interfaces xe-0/0/1 unit 3101 vlan-id 3101",
    "set interfaces xe-0/0/1 unit 3102 family ethernet-switching interface-mode trunk",
    "set interfaces xe-0/0/1 unit 3102 family ethernet-switching vlan members v10",
    "set interfaces xe-0/0/1 unit 3103 vlan-id 3103",
    "set interfaces xe-0/0/1 unit 3103 family ethernet-switching vlan members v20",
    "set interfaces xe-0/0/1 unit 3200 vlan-id 3200",
    f"set interfaces xe-0/0/1 unit 3200 family inet address {_ROUTED_IP}/24",
    "set interfaces xe-0/0/2 vlan-tagging",
    "set interfaces xe-0/0/2 encapsulation vlan-ccc",
    "set interfaces xe-0/0/2 unit 3104 encapsulation vlan-ccc",
    "set interfaces xe-0/0/2 unit 3104 vlan-id 3104",
    "set interfaces xe-0/0/3 vlan-tagging",
    "set interfaces xe-0/0/3 encapsulation vlan-vpls",
    "set interfaces xe-0/0/3 unit 3105 encapsulation vlan-vpls",
    "set interfaces xe-0/0/3 unit 3105 vlan-id 3105",
    "set interfaces xe-0/0/3 unit 3105 family vpls",
    "set interfaces xe-0/0/4 vlan-tagging",
    "set interfaces xe-0/0/4 encapsulation flexible-ethernet-services",
    "set interfaces xe-0/0/4 unit 0 encapsulation vlan-bridge",
    "set interfaces xe-0/0/4 unit 0 vlan-id 3106",
    "set routing-instances V instance-type vpls",
    "set routing-instances V interface xe-0/0/3.3105",
    "",
])

#: The tags and the numbers of the units left out.
_LEFT_OUT = re.compile(r"(?<!\d)310[1-6](?!\d)")
_LEFT_OUT_TAGS = {3101, 3103, 3104, 3105, 3106}

#: The rows the parse of ``_UNITS`` has, typed here.
_UNITS_ROWS = [
    "interfaces xe-0/0/4.0, xe-0/0/1.3101, xe-0/0/1.3102 and 3 more: a "
    "unit that states a family other than inet, inet6, iso and mpls "
    "(ethernet-switching above unit 0 among them), or an encapsulation "
    "and no inet family -- a bridge, a cross-connect, a VPLS circuit or a "
    "switching unit, which the tree has no form for, so the unit is not "
    "translated",
    "interfaces xe-0/0/1, xe-0/0/2, xe-0/0/3 and 1 more: encapsulation -- "
    "the tree has no form for an interface's encapsulation, so the "
    "statement is not translated",
]

_UNIT_ROW_TAIL = (
    ": a unit that states a family other than inet, inet6, iso and mpls "
    "(ethernet-switching above unit 0 among them), or an encapsulation "
    "and no inet family -- a bridge, a cross-connect, a VPLS circuit or a "
    "switching unit, which the tree has no form for, so the unit is not "
    "translated"
)
_ENCAPSULATION_ROW_TAIL = (
    ": encapsulation -- the tree has no form for an interface's "
    "encapsulation, so the statement is not translated"
)


def _job(text: str, target_name: str) -> MigrationJob:
    job = run_plan_with_checked_names(
        get_codec(JUNOS), get_codec(target_name), text, port_rename_map={},
    )
    assert job.rendered, job.error
    return job


def _problems(job: MigrationJob, target_name: str) -> list[str]:
    """What the output for *target_name* holds of a unit left out, where
    the job says such a unit went, and where the routed unit is not as
    the source states it.  (A target that writes no line for a
    sub-interface with no address -- AOS-S -- shows the old reading
    only in what the job says.)"""
    problems = [
        f"line {number}: {line.strip()!r}"
        for number, line in enumerate(job.rendered.splitlines(), 1)
        if _LEFT_OUT.search(line)
    ]
    problems += [
        f"the job sends {name!r} to {where!r}"
        for name, where in job.port_renames.items()
        if _LEFT_OUT.search(name) or _LEFT_OUT.search(where or "")
    ]
    out = get_codec(target_name).parse(job.rendered)
    for iface in out.interfaces:
        carried = _tags(target_name, out, iface, job.rendered) & _LEFT_OUT_TAGS
        if carried:
            problems.append(f"{iface.name!r} carries {sorted(carried)}")
    holders = _holders(out, _ROUTED_IP)
    if len(holders) != 1:
        problems.append(f"{_ROUTED_IP} is on {[h.name for h in holders]}")
    elif (
        _ROUTED_TAG not in _tags(target_name, out, holders[0], job.rendered)
        and job.status == MigrationJobStatus.completed
    ):
        # A target whose parser reads no tag of a sub-interface
        # (AOS-CX, OS10) holds the job instead.
        problems.append(
            f"{holders[0].name!r} does not carry {_ROUTED_TAG}, and the job is completed"
        )
    return problems


def _every_unit_as_before(state, *, unit_0):
    """The parser's old reading: every unit a routed one."""
    return True


class TestTheParse:
    def test_the_records(self) -> None:
        tree = get_codec(JUNOS).parse(_UNITS)
        assert sorted(
            (i.name, i.dot1q_vlan, [a.ip for a in i.ipv4_addresses])
            for i in tree.interfaces
        ) == [
            ("xe-0/0/1", None, []),
            ("xe-0/0/1.3200", 3200, [_ROUTED_IP]),
            ("xe-0/0/2", None, []),
            ("xe-0/0/3", None, []),
            ("xe-0/0/4", None, []),
        ]
        # The instance names a unit left out, and binds nothing.
        assert [i.name for i in tree.interfaces if i.vrf] == []

    def test_the_rows(self) -> None:
        assert get_codec(JUNOS).parse(_UNITS).dropped_tier3_sections == _UNITS_ROWS

    @pytest.mark.parametrize(
        ("lines", "rows"),
        [
            pytest.param(
                [
                    "set interfaces ge-1/0/0 description UPLINK",
                    "set interfaces ge-1/0/0 unit 0 family bridge interface-mode trunk",
                    "set interfaces ge-1/0/0 unit 0 family bridge vlan-id-list 100-200",
                ],
                ["interfaces ge-1/0/0.0" + _UNIT_ROW_TAIL],
                id="a bridge port",
            ),
            pytest.param(
                [
                    "set interfaces ge-0/0/0 unit 0 encapsulation ppp-over-ether",
                    "set interfaces pp0 unit 0 pppoe-options underlying-interface ge-0/0/0.0",
                    "set interfaces pp0 unit 0 family inet negotiate-address",
                ],
                ["interfaces ge-0/0/0.0" + _UNIT_ROW_TAIL],
                id="the port under PPPoE",
            ),
            pytest.param(
                [
                    "set interfaces ge-0/0/5 unit 7 vlan-id 7",
                    "set interfaces ge-0/0/5 unit 7 family ccc",
                ],
                ["interfaces ge-0/0/5.7" + _UNIT_ROW_TAIL],
                id="a cross-connect unit by its family",
            ),
            pytest.param(
                [
                    "set interfaces ge-0/0/5 unit 7 vlan-id 7",
                    "set interfaces ge-0/0/5 unit 7 family frobnicate",
                    "set interfaces ge-0/0/5 unit 7 family inet address 192.0.2.1/24",
                ],
                ["interfaces ge-0/0/5.7" + _UNIT_ROW_TAIL],
                id="a family nobody knows, beside inet",
            ),
            pytest.param(
                [
                    "set interfaces lt-0/0/0 unit 1 encapsulation ethernet",
                    "set interfaces lt-0/0/0 unit 1 peer-unit 2",
                    "set interfaces lt-0/0/0 unit 1 family inet address 192.0.2.1/30",
                ],
                ["interfaces lt-0/0/0.1" + _ENCAPSULATION_ROW_TAIL],
                id="a routed unit that states an encapsulation",
            ),
            pytest.param(
                [
                    "set interfaces ge-0/0/6 unit 0 family inet address 192.0.2.1/24",
                    "set interfaces ge-0/0/6 unit 0 family inet6 address 2001:db8::1/64",
                    "set interfaces ge-0/0/6 unit 0 family iso",
                    "set interfaces ge-0/0/6 unit 0 family mpls",
                    "set interfaces ge-0/0/7 unit 0 family ethernet-switching interface-mode access",
                    "set interfaces ge-0/0/7 unit 0 family ethernet-switching vlan members v10",
                    "set vlans v10 vlan-id 10",
                ],
                [],
                id="a routed port and a switchport",
            ),
        ],
    )
    def test_each_form(self, lines: list[str], rows: list[str]) -> None:
        tree = get_codec(JUNOS).parse("\n".join(["set system host-name r1", *lines, ""]))
        assert tree.dropped_tier3_sections == rows

    _OWN = (
        "set system host-name r1",
        "set interfaces ge-1/0/0 mtu 9192",
    )
    _UNIT_0 = (
        "set interfaces ge-1/0/0 unit 0 description BRIDGE",
        "set interfaces ge-1/0/0 unit 0 disable",
        "set interfaces ge-1/0/0 unit 0 family bridge interface-mode access",
        "set interfaces ge-1/0/0 unit 0 family bridge vlan-id 100",
    )

    def _ports(self) -> tuple:
        junos = get_codec(JUNOS)
        (port,) = junos.parse("\n".join([*self._OWN, *self._UNIT_0, ""])).interfaces
        (alone,) = junos.parse("\n".join([*self._OWN, ""])).interfaces
        return port, alone

    def test_a_unit_0_left_out_leaves_its_port(self) -> None:
        """The port of a unit 0 left out keeps what its own lines
        state, and nothing of the unit: it is the port of the same
        config with the unit's lines taken out."""
        port, alone = self._ports()
        assert port == alone
        assert (port.name, port.description, port.enabled) == ("ge-1/0/0", "", True)

    def test_the_check_sees_unit_0_read_as_before(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Read as before, the unit's description and ``disable`` were
        the port's.  (A tagged unit 0 is a record of its own, and is
        left out where every unit is.)"""
        monkeypatch.setattr(junos_parse, "_units_0_the_tree_does_not_hold", lambda state: [])
        port, alone = self._ports()
        assert (port.description, port.enabled) == ("BRIDGE", False)
        assert port != alone

    def test_many_units_are_one_row(self) -> None:
        lines = ["set system host-name r1"]
        for unit in range(1, 1001):
            lines += [
                f"set interfaces xe-0/0/1 unit {unit} encapsulation vlan-bridge",
                f"set interfaces xe-0/0/1 unit {unit} vlan-id {unit}",
            ]
        tree = get_codec(JUNOS).parse("\n".join([*lines, ""]))
        assert tree.dropped_tier3_sections == [
            "interfaces xe-0/0/1.1, xe-0/0/1.2, xe-0/0/1.3 and 997 more" + _UNIT_ROW_TAIL,
        ]

    def test_the_committed_captures_lose_no_unit(self) -> None:
        """Every unit of every committed Junos capture is one the tree
        holds: its records are what the old reading made, and no row
        of these is in its parse."""
        captures = sorted(REAL.glob("*.set"))
        assert captures
        junos = get_codec(JUNOS)
        for capture in captures:
            text = capture.read_text(encoding="utf-8")
            tree = junos.parse(text)
            rows = [
                row for row in tree.dropped_tier3_sections
                if row.endswith((_UNIT_ROW_TAIL, _ENCAPSULATION_ROW_TAIL))
            ]
            assert rows == [], capture.name
            with pytest.MonkeyPatch.context() as patched:
                patched.setattr(junos_parse, "_a_unit_the_tree_holds", _every_unit_as_before)
                before = junos.parse(text)
            assert [i.name for i in tree.interfaces] == [
                i.name for i in before.interfaces
            ], capture.name


class TestEveryTarget:
    @pytest.mark.parametrize("target_name", list_public_codecs())
    def test_no_unit_left_out_is_in_the_output(self, target_name: str) -> None:
        job = _job(_UNITS, target_name)
        assert _problems(job, target_name) == []
        assert job.dropped_tier3_sections[:2] == _UNITS_ROWS

    @pytest.mark.parametrize("target_name", list_public_codecs())
    def test_the_check_sees_the_old_reading(
        self, target_name: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(junos_parse, "_a_unit_the_tree_holds", _every_unit_as_before)
        assert _problems(_job(_UNITS, target_name), target_name) != []


def test_the_reader_sees_each_defect() -> None:
    good = _job(_UNITS, "cisco_iosxe_cli")
    assert _problems(good, "cisco_iosxe_cli") == []
    broken = {
        "a unit left out, by its name": good.rendered.replace(
            "interface TenGigabitEthernet0/0/1.3200",
            "interface TenGigabitEthernet0/0/1.3101\n"
            "!\ninterface TenGigabitEthernet0/0/1.3200",
        ),
        "the routed unit's tag": good.rendered.replace(
            "encapsulation dot1Q 3200", "encapsulation dot1Q 3201",
        ),
        "the routed unit": good.rendered.replace(
            f"ip address {_ROUTED_IP} 255.255.255.0", "",
        ),
    }
    for what, text in broken.items():
        assert text != good.rendered, what
        assert _problems(good.model_copy(update={"rendered": text}), "cisco_iosxe_cli"), what
    said = {**good.port_renames, "xe-0/0/1.3101": "TenGigabitEthernet0/0/1.3101"}
    assert _problems(good.model_copy(update={"port_renames": said}), "cisco_iosxe_cli")

"""A RouterOS VLAN interface that states no ``vlan-id=`` is VLAN 1.

"vlan-id (integer: 1..4094; Default: 1)" (MikroTik, "VLAN"), and "By
default, the export command writes only user-edited configuration,
RouterOS defaults are omitted" (MikroTik, "Configuration Management"):
an export of a VLAN interface of VLAN 1 has no ``vlan-id=``.  The parser
passed such a line over.  The VLAN interface was in no output, its
addresses were written on its name -- a name the output defines
nowhere -- and a RouterOS config translated to RouterOS said
``completed``.

The export form is held to the verbose one (``vlan-id=1`` written out),
typed by hand; a ``vlan-id=`` with no number after it is held to
``vlan-id=0``, a VLAN id that is none; every public codec is a target,
its output read back by address with its own parser; and the check is
handed the old reading, which is the config with the line taken out.
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.models.migration import MigrationJob, MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan_with_checked_names
from tests.unit.migration.test_units_follow_their_port import _holders, _tags

ROUTEROS = "mikrotik_routeros"

_DEFAULTED_IP = "192.0.2.1"
_TAGGED_IP = "198.51.100.1"


def _config(vlan_line: str) -> str:
    """A VLAN interface ``vlan-mgmt`` on ``ether2`` written as
    *vlan_line* (the ``add`` line, or nothing), beside one of VLAN 20."""
    lines = ["/interface vlan"]
    if vlan_line:
        lines.append(vlan_line)
    lines += [
        "add interface=ether2 name=vlan20 vlan-id=20",
        "/ip address",
        f"add address={_DEFAULTED_IP}/24 interface=vlan-mgmt network=192.0.2.0",
        f"add address={_TAGGED_IP}/24 interface=vlan20 network=198.51.100.0",
        "/system identity",
        "set name=r1",
    ]
    return "\n".join(lines) + "\n"


#: As ``/export`` prints it: the default left out.
_EXPORT = _config("add interface=ether2 name=vlan-mgmt")
#: As ``/export verbose`` prints it, typed by hand.
_VERBOSE = _config("add interface=ether2 name=vlan-mgmt vlan-id=1")
#: The reading before the change: the line passed over.
_OLD_READING = _config("")


def _parse(text: str):
    return get_codec(ROUTEROS).parse(text)


class TestTheParse:
    @pytest.mark.parametrize(
        ("export", "verbose"),
        [
            pytest.param(_EXPORT, _VERBOSE, id="on a port"),
            pytest.param(
                "/interface bridge\nadd name=bridge1\n/interface vlan\n"
                "add interface=bridge1 name=mgmt\n/ip address\n"
                "add address=192.0.2.1/24 interface=mgmt\n",
                "/interface bridge\nadd name=bridge1\n/interface vlan\n"
                "add interface=bridge1 name=mgmt vlan-id=1\n/ip address\n"
                "add address=192.0.2.1/24 interface=mgmt\n",
                id="on a bridge",
            ),
            pytest.param(
                '/interface vlan\nadd comment="the vlan-id= of it" '
                "interface=ether2 name=v\n",
                '/interface vlan\nadd comment="the vlan-id= of it" '
                "interface=ether2 name=v vlan-id=1\n",
                id="a comment that names vlan-id=",
            ),
        ],
    )
    def test_the_export_form_is_the_verbose_form(self, export: str, verbose: str) -> None:
        assert _parse(export).model_dump() == _parse(verbose).model_dump()

    def test_it_is_vlan_1_on_its_port(self) -> None:
        tree = _parse(_EXPORT)
        [iface] = _holders(tree, _DEFAULTED_IP)
        assert (iface.name, iface.dot1q_vlan, iface.vlan_parent) == (
            "vlan-mgmt", 1, "ether2",
        )
        assert tree.dropped_tier3_sections == []

    @pytest.mark.parametrize("stated", ["vlan-id=", 'vlan-id=""'])
    def test_a_vlan_id_with_no_number_is_no_vlan_id(self, stated: str) -> None:
        """Stated and given no number: as ``vlan-id=0`` is, left out
        with a row -- never the default."""
        base = "/interface vlan\nadd interface=ether2 name=v {}\n/ip address\nadd address=192.0.2.1/24 interface=v\n"
        tree = _parse(base.format(stated))
        assert tree.model_dump() == _parse(base.format("vlan-id=0")).model_dump()
        assert not _holders(tree, _DEFAULTED_IP)
        assert len(tree.dropped_tier3_sections) == 1


def _job(text: str, target: str) -> MigrationJob:
    return run_plan_with_checked_names(
        get_codec(ROUTEROS), get_codec(target), text, port_rename_map={},
    )


def _problems(job: MigrationJob, target: str) -> list[str]:
    """What the output of *job* gets wrong about the two VLAN
    interfaces, read back with *target*'s own parser: an address not in
    the text, and -- where the job says ``completed`` -- an address on
    no interface, on two, or on one that does not carry its tag.  A
    target whose parser reads no tag makes the job ``partial`` (the
    sub-interface rules), and is held to the text."""
    out = job.rendered or ""
    problems = [
        f"{ip} is not in the output"
        for ip in (_DEFAULTED_IP, _TAGGED_IP) if ip not in out
    ]
    if job.status is not MigrationJobStatus.completed:
        return problems
    back = get_codec(target).parse(out)
    for ip, tag in ((_DEFAULTED_IP, 1), (_TAGGED_IP, 20)):
        holders = _holders(back, ip)
        if len(holders) != 1:
            problems.append(f"{ip} is on {[i.name for i in holders]}")
            continue
        carried = _tags(target, back, holders[0], out)
        if carried != {tag}:
            problems.append(f"{ip} is on {holders[0].name}, which carries {carried}")
    return problems


@pytest.mark.parametrize("target", list_public_codecs())
def test_vlan_1_reaches_every_target(target: str) -> None:
    job = _job(_EXPORT, target)
    assert _problems(job, target) == []
    verbose = _job(_VERBOSE, target)
    assert (job.status, job.rendered) == (verbose.status, verbose.rendered)


def test_the_check_sees_the_old_reading() -> None:
    """The line passed over: RouterOS to RouterOS said ``completed``
    with the address on a name the output defines nowhere."""
    job = _job(_OLD_READING, ROUTEROS)
    assert job.status is MigrationJobStatus.completed
    assert _problems(job, ROUTEROS) == [
        f"{_DEFAULTED_IP} is on vlan-mgmt, which carries set()"
    ]

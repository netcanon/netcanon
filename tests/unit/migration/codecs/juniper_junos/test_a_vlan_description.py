"""A Junos VLAN's description is read and written.

``set vlans <NAME> description <TEXT>`` was a line the parser read
nothing of and the renderer wrote nothing for: a description from
Junos was gone on every target, and one from another platform -- an
AOS-CX ``description`` beside a ``name`` of the VLAN's own -- was gone
on Junos, which has a line for it.  A set-form config may state the
description ahead of ``vlan-id``, the line that makes the VLAN, so
the parser keeps it by the VLAN's name until the whole config has
been read.

What is written is read here as text, by a reader typed for the
grammar, and with the parser.
"""

from __future__ import annotations

import re

import pytest

from netcanon.migration.codecs.registry import get_codec
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

JUNOS = get_codec("juniper_junos")


def _descriptions(text: str) -> dict[str, str]:
    """``{VLAN name: description}`` of each ``set vlans <name>
    description "<text>"`` line, the last one read."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        found = re.fullmatch(r'set vlans ("[^"]*"|\S+) description "((?:[^"\\]|\\.)*)"', line.strip())
        if found:
            out[found.group(1).strip('"')] = re.sub(r"\\(.)", r"\1", found.group(2))
    return out


def _parsed(text: str) -> dict[int, tuple[str, str]]:
    return {vlan.id: (vlan.name, vlan.description) for vlan in JUNOS.parse(text).vlans}


@pytest.mark.parametrize(
    "text",
    [
        'set vlans VOICE description "Voice handsets"\nset vlans VOICE vlan-id 20\n',
        'set vlans VOICE vlan-id 20\nset vlans VOICE description "Voice handsets"\n',
        'vlans {\n    VOICE {\n        description "Voice handsets";\n        vlan-id 20;\n    }\n}\n',
    ],
    ids=["description-first", "vlan-id-first", "block-form"],
)
def test_the_description_is_read_in_either_order(text: str) -> None:
    assert _parsed(text) == {20: ("VOICE", "Voice handsets")}


def test_the_last_description_is_the_one() -> None:
    text = (
        "set vlans VOICE description first\n"
        "set vlans VOICE vlan-id 20\n"
        "set vlans VOICE description second\n"
    )
    assert _parsed(text) == {20: ("VOICE", "second")}


def test_a_description_is_given_to_its_own_vlan_only() -> None:
    text = (
        "set vlans DATA vlan-id 10\n"
        "set vlans VOICE description Phones\n"
        "set vlans VOICE vlan-id 20\n"
        "set vlans NOID description Orphan\n"
    )
    assert _parsed(text) == {10: ("DATA", ""), 20: ("VOICE", "Phones")}


def test_the_description_is_written_and_read_back() -> None:
    text = 'set vlans VOICE vlan-id 20\nset vlans VOICE description "Voice \\"desk\\" sets"\n'
    out = JUNOS.render(JUNOS.parse(text))
    assert _descriptions(out) == {"VOICE": 'Voice "desk" sets'}
    assert _parsed(out) == {20: ("VOICE", 'Voice "desk" sets')}


def test_no_line_for_a_vlan_with_no_description() -> None:
    out = JUNOS.render(JUNOS.parse("set vlans DATA vlan-id 10\n"))
    assert "description" not in out


AOSCX = """hostname sw1
vlan 1
vlan 60
    name OFFICE
    description Second-floor
vlan 70
    description Lab
interface 1/1/1
    no shutdown
    vlan access 60
interface 1/1/2
    no shutdown
    vlan access 70
"""


def test_a_description_beside_a_name_reaches_junos() -> None:
    """VLAN 60 has a name of its own and a description: both are
    written.  VLAN 70 has only a description, which is its name
    (``_vlan_labels``) and is not written a second time."""
    job = run_plan_with_checked_names(
        get_codec("aruba_aoscx"), JUNOS, AOSCX, port_rename_map={},
    )
    assert job.rendered, (job.status, job.error)
    assert _descriptions(job.rendered) == {"OFFICE": "Second-floor"}
    back = _parsed(job.rendered)
    assert back[60] == ("OFFICE", "Second-floor")
    assert back[70] == ("Lab", "")
    assert "/vlans/vlan/description" not in {i.path for i in job.validation.lossy_paths}


#: ``True`` where the target writes a VLAN's description beside a name
#: of the VLAN's own; ``False`` where it has no line for it, and the job
#: says the description is lost.
WRITES_IT = {
    "aruba_aoscx": True, "opnsense": True, "juniper_junos": True,
    "arista_eos": False, "aruba_aoss": False, "cisco_iosxe_cli": False,
    "cisco_nxos": False, "dell_os10": False,
}

#: Targets that write it and declare the path lossy all the same, for
#: a VLAN other than this one: an OPNsense VLAN on a port is read back
#: as a sub-interface of the port, the ``<descr>`` its description.
#: This VLAN is on no port, and is read back with its description.
LOSSY_FOR_A_VLAN_ON_A_PORT = {"opnsense"}


@pytest.mark.parametrize("target", sorted(WRITES_IT))
def test_a_junos_description_is_written_or_said_lost(target: str) -> None:
    """Before the parser read it, the description was lost on every
    target and no job said so."""
    text = "set vlans OFFICE vlan-id 60\nset vlans OFFICE description Second-floor\n"
    job = run_plan_with_checked_names(JUNOS, get_codec(target), text, port_rename_map={})
    assert job.rendered, (job.status, job.error)
    lossy = {issue.path for issue in job.validation.lossy_paths}
    assert ("Second-floor" in job.rendered) is WRITES_IT[target]
    said = "/vlans/vlan/description" in lossy
    if target in LOSSY_FOR_A_VLAN_ON_A_PORT:
        assert said
        back = {vlan.id: vlan.description for vlan in get_codec(target).parse(job.rendered).vlans}
        assert back.get(60) == "Second-floor"
    else:
        assert said is not WRITES_IT[target]

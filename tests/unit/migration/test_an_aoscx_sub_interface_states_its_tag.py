"""An AOS-CX sub-interface is the tag its ``encapsulation dot1q`` states.

HPE documents routed sub-interfaces on AOS-CX: ``interface 1/1/1.201``
enters the sub-interface context, and ``encapsulation dot1q <VLAN-ID>``
(1 to 4094) gives it its 802.1Q tag -- in HPE's own example, tag 10 on
sub-interface 201 (AOS-CX Fundamentals Guide, 6300/6400 from 10.08 and
the 8100, 83xx and 10000 series).  The parser read no such line: every
AOS-CX sub-interface went onto another vendor with no tag (EOS, IOS-XE,
NX-OS, IOS XR, Junos), or with its number as its tag (VyOS ``vif 201``,
FortiOS ``set vlanid 201``), in jobs that said ``completed`` with one
warning each.  Onto AOS-CX itself the tag was lost the same way, and
nothing said so.

The source is HPE's example, typed by hand.  Each output is read as text
by a reader of the test's own per target, since a target's parser can
read a VLAN interface back where the output wrote a sub-interface
(FortiOS, for a parent whose name is not a FortiGate's), and with the
target's parser where it reads the sub-interface back as one.  Each
check is handed the defect it is for.
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs.aruba_aoscx import parse as aoscx_parse
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.models.migration import MigrationJob, MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

TAG = "/interfaces/interface/dot1q-vlan"

#: HPE's example: sub-interface 201 of port 1/1/1, tag 10, beside a
#: routed port.
SOURCE = (
    "hostname sw1\n"
    "interface 1/1/1\n    no shutdown\n    routing\n"
    "interface 1/1/1.201\n    no shutdown\n    encapsulation dot1q 10\n"
    "    ip address 198.51.100.1/24\n"
    "interface 1/1/2\n    no shutdown\n    routing\n    ip address 192.0.2.1/24\n"
)

#: How each target that writes a sub-interface's tag writes tag 10 of
#: sub-interface 201, typed from the vendor's grammar, and how it would
#: write the NUMBER as the tag -- which none may.
WRITES_THE_TAG: dict[str, tuple[str, str]] = {
    "arista_eos": ("   encapsulation dot1q vlan 10\n", "encapsulation dot1q vlan 201"),
    "cisco_iosxe_cli": (" encapsulation dot1Q 10\n", "encapsulation dot1Q 201"),
    "cisco_iosxr": (" encapsulation dot1q 10\n", "encapsulation dot1q 201"),
    "cisco_nxos": ("  encapsulation dot1q 10\n", "encapsulation dot1q 201"),
    "fortigate_cli": ("        set vlanid 10\n", "set vlanid 201"),
    "juniper_junos": (" unit 201 vlan-id 10\n", "vlan-id 201"),
    "mikrotik_routeros": (" vlan-id=10\n", "vlan-id=201"),
    "opnsense": ("<tag>10</tag>", "<tag>201</tag>"),
    # A vif's number IS its tag (VyOS): the unit number is not kept.
    "vyos": ("        vif 10 {\n", "vif 201"),
}

#: The public codecs that write no sub-interface's tag, typed by hand:
#: a job onto one of them is held, and its validation lists the tag.
#: AOS-S, which writes the VLAN of the tag, has no name for an AOS-CX
#: port without a map and is held for that, before any tag; its own
#: tests send a sub-interface after a mapped port
#: (``tests/unit/migration/codecs/aruba_aoss/test_an_interface_that_stands_for_a_vlan.py``).
HOLDS_THE_JOB = {"aruba_aoscx", "cisco_iosxe", "dell_os10"}

#: The warning a unit that went after its port with no tag is given.
NO_TAG = "with no 802.1Q tag"


def _job(target: str, text: str = SOURCE) -> MigrationJob:
    return run_plan_with_checked_names(
        get_codec("aruba_aoscx"), get_codec(target), text, port_rename_map={},
    )


def tree_problems(text: str = SOURCE) -> list[str]:
    """What is wrong with the parse of *text*: the sub-interface's tag
    is 10, and nothing else in the tree has a tag."""
    tree = get_codec("aruba_aoscx").parse(text)
    tags = {i.name: i.dot1q_vlan for i in tree.interfaces}
    problems = []
    if tags.get("1/1/1.201") != 10:
        problems.append(f"the sub-interface's tag is {tags.get('1/1/1.201')}")
    others = {n: t for n, t in tags.items() if n != "1/1/1.201" and t is not None}
    if others:
        problems.append(f"another interface has a tag: {others}")
    return problems


def output_problems(target: str, job: MigrationJob) -> list[str]:
    """What is wrong with the output of a job onto *target*, which
    writes the tag."""
    out = job.rendered or ""
    line, number_as_tag = WRITES_THE_TAG[target]
    problems = []
    if job.status != MigrationJobStatus.completed:
        problems.append(f"the job is {job.status.value}: {job.error}")
    if line not in out:
        problems.append(f"no {line.strip()!r} in the output")
    if number_as_tag in out:
        problems.append(f"the number is written as the tag: {number_as_tag!r}")
    if "198.51.100.1" not in out:
        problems.append("the sub-interface's address is not in the output")
    if [w for w in job.warnings if NO_TAG in w]:
        problems.append("a warning says the unit has no tag")
    # Where the target's parser reads the sub-interface back as one,
    # it reads tag 10.
    back = get_codec(target).parse(out)
    read = {
        i.dot1q_vlan for i in back.interfaces
        if any(a.ip == "198.51.100.1" for a in i.ipv4_addresses)
    } - {None}
    if read and read != {10}:
        problems.append(f"read back as tag {sorted(read)}")
    return problems


def test_the_tree_holds_the_tag() -> None:
    assert tree_problems() == []


@pytest.mark.parametrize("target", sorted(WRITES_THE_TAG))
def test_each_target_that_has_a_form_writes_it(target: str) -> None:
    assert output_problems(target, _job(target)) == []


@pytest.mark.parametrize("target", sorted(HOLDS_THE_JOB))
def test_a_target_with_no_form_holds_the_job(target: str) -> None:
    """AOS-CX itself among them: its renderer writes the sub-interface
    and its address and no ``encapsulation dot1q`` yet, and the job
    says so."""
    job = _job(target)
    assert job.status == MigrationJobStatus.partial
    assert TAG in [u.path for u in job.validation.unsupported_paths]
    assert not [w for w in job.warnings if NO_TAG in w]


def test_the_matrices_say_which() -> None:
    """The two tables above are the public codecs whose matrix names the
    tag (AOS-S apart, which is tested in its own module)."""
    classes = {c: get_codec(c).capabilities.classify(TAG) for c in list_public_codecs()}
    assert {c for c, k in classes.items() if k == "unsupported"} == HOLDS_THE_JOB
    assert set(WRITES_THE_TAG) | HOLDS_THE_JOB | {"aruba_aoss"} == set(classes)


#: Stanzas the tag is not read from: a port's own, and a LAG's, whose
#: sub-interface HPE does not document (the header reader takes
#: ``interface lag 1.10`` for ``lag 1``).
NOT_A_SUB_INTERFACE = {
    "a port": (
        "interface 1/1/1\n    no shutdown\n    routing\n    encapsulation dot1q 10\n"
        "    ip address 198.51.100.1/24\n",
        "1/1/1",
    ),
    "a LAG": (
        "interface lag 1\n    no shutdown\n    routing\n"
        "interface lag 1.10\n    encapsulation dot1q 10\n",
        "lag 1",
    ),
}


@pytest.mark.parametrize("case", sorted(NOT_A_SUB_INTERFACE))
def test_the_tag_of_no_sub_interface_is_not_read(case: str) -> None:
    text, name = NOT_A_SUB_INTERFACE[case]
    tree = get_codec("aruba_aoscx").parse("hostname sw1\n" + text)
    assert {i.name: i.dot1q_vlan for i in tree.interfaces}[name] is None


#: Tag statements that are not one VLAN id, with nothing after it.
NOT_READ_WHOLE = ["encapsulation dot1q 10 20", "encapsulation dot1q 1-10", "encapsulation dot1q"]


@pytest.mark.parametrize("statement", NOT_READ_WHOLE)
def test_a_statement_not_read_whole_leaves_it_out(statement: str) -> None:
    """(A tag that is no VLAN id -- 0, 4095 -- is in
    ``test_a_tag_is_a_vlan_id.py``.)"""
    tree = get_codec("aruba_aoscx").parse(SOURCE.replace("encapsulation dot1q 10", statement))
    addresses = {a.ip for i in tree.interfaces for a in i.ipv4_addresses}
    assert addresses == {"192.0.2.1"}
    assert (
        f"interface 1/1/1.201: {statement} -- not one 802.1Q tag and at most one "
        f"inner tag, so the sub-interface is not translated"
    ) in tree.dropped_tier3_sections


# -- Each check is handed the defect it is for ---------------------------


def test_the_checks_see_the_tag_unread(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the tag statement not recognised, the sub-interface is in the
    tree with no tag, as it was: each check fails."""
    monkeypatch.setattr(aoscx_parse, "_is_tag_statement", lambda _statement: False)
    assert tree_problems() != []
    for target in sorted(WRITES_THE_TAG):
        assert output_problems(target, _job(target)) != [], target


def test_the_tree_check_sees_a_port_given_the_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aoscx_parse, "_is_a_sub_interface", lambda _name: True)
    text, _name = NOT_A_SUB_INTERFACE["a port"]
    assert tree_problems(SOURCE + text.replace("1/1/1", "1/1/3")) != []


def test_the_output_check_sees_the_number_as_the_tag() -> None:
    job = _job("vyos")
    job.rendered = job.rendered.replace("vif 10 {", "vif 201 {")
    assert output_problems("vyos", job) != []

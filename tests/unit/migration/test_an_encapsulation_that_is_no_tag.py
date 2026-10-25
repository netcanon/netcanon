"""An IOS XR sub-interface whose encapsulation is no 802.1Q tag is left out.

``encapsulation untagged`` defines "the matching criteria to map
untagged frames on an interface" (Cisco, "Interface and Hardware
Component Command Reference for Cisco 8000 Series Routers", VLAN
Subinterface Commands); ``encapsulation default`` matches "any tagged or
untagged traffic that has not been matched by another subinterface"
(Cisco, "Understand IOS XR L2VPN Services and Features").  The parser
read neither, and kept the sub-interface -- an ``l2transport``
attachment circuit, as a rule -- as one of no tag: VyOS wrote ``vif
7``, every other target a sub-interface of no tag, in jobs that said
``completed``.

The tree has no form for either, so the sub-interface is left out with
the row of a tag statement not read whole, as ``encapsulation dot1ad``
is.  A port's own ``encapsulation`` (a serial line's ``ppp``) is not a
sub-interface's, and is read as before.
"""

from __future__ import annotations

import pytest

from netcanon.migration._tier3_detection import is_left_out_row
from netcanon.migration.codecs.cisco_iosxr import port_names as xr_port_names
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.models.migration import MigrationJob
from netcanon.services.migration_pipeline import run_plan_with_checked_names

XR = "cisco_iosxr"

#: The description of the sub-interface that matches no tag, and of the
#: tagged one beside it.
_NO_TAG = "ac-no-tag"
_TAGGED = "ac-tagged"


def _text(header: str, statement: str) -> str:
    return (
        "hostname r1\ninterface GigabitEthernet0/0/0/1\n no shutdown\n!\n"
        f"interface {header}\n description {_NO_TAG}\n {statement}\n!\n"
        f"interface GigabitEthernet0/0/0/1.100 l2transport\n description {_TAGGED}\n"
        " encapsulation dot1q 100\n!\n"
        "end\n"
    )


def _row(header: str, statement: str) -> str:
    return (
        f"interface {header}: {statement} -- not one 802.1Q tag and at most "
        "one inner tag, so the sub-interface is not translated"
    )


#: (header, statement, the name the parser would have made of it).
_FORMS = [
    pytest.param(
        "GigabitEthernet0/0/0/1.7 l2transport", "encapsulation untagged",
        "GigabitEthernet0/0/0/1.7", id="untagged",
    ),
    pytest.param(
        "GigabitEthernet0/0/0/1.8 l2transport", "encapsulation default",
        "GigabitEthernet0/0/0/1.8", id="default",
    ),
    pytest.param(
        "Bundle-Ether10.7 l2transport", "encapsulation untagged",
        "Bundle-Ether10.7", id="untagged on a bundle",
    ),
    pytest.param(
        "GigabitEthernet0/0/0/1.7", "encapsulation untagged",
        "GigabitEthernet0/0/0/1.7", id="untagged, no l2transport",
    ),
]


def _parse(text: str):
    return get_codec(XR).parse(text)


@pytest.mark.parametrize(("header", "statement", "name"), _FORMS)
def test_it_is_left_out_with_its_row(header: str, statement: str, name: str) -> None:
    tree = _parse(_text(header, statement))
    names = {i.name for i in tree.interfaces}
    assert name not in names
    assert "GigabitEthernet0/0/0/1.100" in names
    assert _row(header, statement) in tree.dropped_tier3_sections
    # In force on the router: a section, not a statement it held.
    assert not is_left_out_row(_row(header, statement))


def test_a_ports_own_encapsulation_is_not_asked_about() -> None:
    """A serial line's ``encapsulation ppp`` is the port's, not a
    sub-interface's tag: the port is read as before."""
    tree = _parse(
        "hostname r1\ninterface Serial0/1/0/0\n encapsulation ppp\n"
        " ipv4 address 192.0.2.1 255.255.255.252\n!\nend\n"
    )
    [port] = [i for i in tree.interfaces if i.name == "Serial0/1/0/0"]
    assert [str(a.ip) for a in port.ipv4_addresses] == ["192.0.2.1"]
    assert tree.dropped_tier3_sections == []


def _job(target: str, text: str) -> MigrationJob:
    return run_plan_with_checked_names(
        get_codec(XR), get_codec(target), text, port_rename_map={},
    )


def _problems(job: MigrationJob, row: str) -> list[str]:
    out = job.rendered or ""
    problems: list[str] = []
    if _NO_TAG in out:
        problems.append(f"{_NO_TAG} is in the output")
    if _TAGGED not in out:
        problems.append(f"{_TAGGED} is not in the output")
    if row not in job.dropped_tier3_sections:
        problems.append("no row says it was left out")
    return problems


@pytest.mark.parametrize("target", list_public_codecs())
@pytest.mark.parametrize("statement", ["encapsulation untagged", "encapsulation default"])
def test_no_target_is_given_it(statement: str, target: str) -> None:
    header = "GigabitEthernet0/0/0/1.7 l2transport"
    job = _job(target, _text(header, statement))
    assert _problems(job, _row(header, statement)) == []


def test_the_check_sees_the_old_reading(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no sub-interface taken for one that needs a tag, the parse
    is the old one: onto VyOS the sub-interface came out as ``vif 7``."""
    monkeypatch.setattr(xr_port_names, "a_sub_interface_needs_a_tag", lambda name: False)
    header, statement = "GigabitEthernet0/0/0/1.7 l2transport", "encapsulation untagged"
    job = _job("vyos", _text(header, statement))
    assert "vif 7" in (job.rendered or "")
    assert _problems(job, _row(header, statement)) == [
        f"{_NO_TAG} is in the output",
        "no row says it was left out",
    ]

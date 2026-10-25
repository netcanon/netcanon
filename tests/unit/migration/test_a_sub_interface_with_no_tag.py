"""A sub-interface that states no tag is held and not run, on IOS XR and EOS.

"An 802.1Q VLAN subinterface must have a configured VLAN ID to send and
receive traffic; without a VLAN ID, the subinterface remains in the down
state" (Cisco, "IOS XR Interface and Hardware Component Command
Reference", ``dot1q vlan``); and on EOS, for a subinterface to be
operational, "a VLAN must be configured on the subinterface" (Arista,
EOS User Manual, "Ethernet Ports").  The two parsers kept such a
sub-interface, with no tag.  Written out it was a sub-interface of no
tag on every target: VyOS wrote ``vif 7``, its number taken for the
tag, and RouterOS, FortiOS and OPNsense an address on an interface the
output defines nowhere, in jobs that said ``completed``.

Each parser now leaves it out under a left-out row.  IOS XR's older tag
statement, ``dot1q vlan``, is read as a tag; a stanza that states an
encapsulation of another kind, or whose parent is no 802.1Q port, is
read as before.  What an IOS-XE or NX-OS sub-interface with no tag does
is not established, and those parsers are not asked: the last test pins
that, and the change that mends it empties it.
"""

from __future__ import annotations

import pytest

from netcanon.migration._tier3_detection import is_left_out_row
from netcanon.migration.codecs.arista_eos import port_names as eos_port_names
from netcanon.migration.codecs.cisco_iosxr import port_names as xr_port_names
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.models.migration import MigrationJob, MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan_with_checked_names
from tests.unit.migration.test_units_follow_their_port import _holders

XR = "cisco_iosxr"
EOS = "arista_eos"

_UNTAGGED_IP = "192.0.2.1"
_TAGGED_IP = "198.51.100.1"

#: Each source: a sub-interface of no tag beside one of tag 20, the
#: name of the first, and the text with nothing but the first.
_SOURCES = {
    XR: (
        "hostname r1\n"
        "interface GigabitEthernet0/0/0/1\n no shutdown\n!\n"
        "interface GigabitEthernet0/0/0/1.7\n"
        f" ipv4 address {_UNTAGGED_IP} 255.255.255.0\n!\n"
        "interface GigabitEthernet0/0/0/1.20\n"
        f" ipv4 address {_TAGGED_IP} 255.255.255.0\n encapsulation dot1q 20\n!\n"
        "end\n",
        "GigabitEthernet0/0/0/1.7",
        "interface GigabitEthernet0/0/0/1.7\n"
        f" ipv4 address {_UNTAGGED_IP} 255.255.255.0\n!\n",
    ),
    EOS: (
        "hostname r1\n"
        "interface Ethernet1\n   no switchport\n!\n"
        "interface Ethernet1.7\n"
        f"   ip address {_UNTAGGED_IP}/24\n!\n"
        "interface Ethernet1.20\n"
        f"   encapsulation dot1q vlan 20\n   ip address {_TAGGED_IP}/24\n!\n"
        "end\n",
        "Ethernet1.7",
        f"interface Ethernet1.7\n   ip address {_UNTAGGED_IP}/24\n!\n",
    ),
}


def _row(name: str) -> str:
    return (
        f"untagged: interface {name} "
        "(states no 802.1Q tag, so the source passes no traffic on it; not translated)"
    )


def _parse(source: str, text: str):
    return get_codec(source).parse(text)


class TestTheParse:
    @pytest.mark.parametrize("source", sorted(_SOURCES))
    def test_it_is_left_out_under_a_left_out_row(self, source: str) -> None:
        text, name, _alone = _SOURCES[source]
        tree = _parse(source, text)
        assert not _holders(tree, _UNTAGGED_IP)
        assert name not in {i.name for i in tree.interfaces}
        assert tree.dropped_tier3_sections == [_row(name)]
        assert is_left_out_row(_row(name))
        [tagged] = _holders(tree, _TAGGED_IP)
        assert tagged.dot1q_vlan == 20

    @pytest.mark.parametrize(
        ("source", "text", "name"),
        [
            pytest.param(
                XR, "interface Bundle-Ether1.7\n ipv4 address 192.0.2.1 255.255.255.0\n!\n",
                "Bundle-Ether1.7", id="xr bundle",
            ),
            pytest.param(
                XR, "interface GigabitEthernet 0/0/0/1.7\n ipv4 address 192.0.2.1 255.255.255.0\n!\n",
                "GigabitEthernet0/0/0/1.7", id="xr type and number apart",
            ),
            pytest.param(
                XR, "interface GigabitEthernet0/0/0/1.7\n!\n",
                "GigabitEthernet0/0/0/1.7", id="xr nothing in it",
            ),
            pytest.param(
                EOS, "interface Ethernet1.0\n   ip address 192.0.2.1/24\n!\n",
                "Ethernet1.0", id="eos unit 0",
            ),
            pytest.param(
                EOS, "interface Port-Channel1.7\n   ip address 192.0.2.1/24\n!\n",
                "Port-Channel1.7", id="eos port channel",
            ),
            pytest.param(
                EOS, "interface Ethernet1/1.7\n   ip address 192.0.2.1/24\n!\n",
                "Ethernet1/1.7", id="eos two-part port",
            ),
        ],
    )
    def test_each_form(self, source: str, text: str, name: str) -> None:
        tree = _parse(source, "hostname r1\n" + text + "end\n")
        assert not _holders(tree, _UNTAGGED_IP)
        assert tree.dropped_tier3_sections == [_row(name)]

    @pytest.mark.parametrize(
        ("older", "newer"),
        [
            ("dot1q vlan 20", "encapsulation dot1q 20"),
            ("dot1q vlan 20 30", "encapsulation dot1q 20 second-dot1q 30"),
        ],
    )
    def test_the_older_xr_tag_statement_is_a_tag(self, older: str, newer: str) -> None:
        """"dot1q vlan vlan-id [ vlan-id2 | any ]" (Cisco, ``dot1q vlan``):
        read as ``encapsulation dot1q`` is.  Read by that form alone it
        was no tag."""
        base = (
            "hostname r1\ninterface GigabitEthernet0/0/0/1.7\n"
            " ipv4 address 192.0.2.1 255.255.255.0\n {}\n!\nend\n"
        )
        assert (
            _parse(XR, base.format(older)).model_dump()
            == _parse(XR, base.format(newer)).model_dump()
        )

    def test_an_older_statement_not_read_whole(self) -> None:
        """``any`` for the inner tag has no form in the tree: the stanza
        is taken out with the row of a statement not read whole, as
        ``second-dot1q any`` is -- not the row of one that states none."""
        tree = _parse(
            XR,
            "hostname r1\ninterface GigabitEthernet0/0/0/1.7\n"
            " ipv4 address 192.0.2.1 255.255.255.0\n dot1q vlan 20 any\n!\nend\n",
        )
        assert not _holders(tree, _UNTAGGED_IP)
        [row] = tree.dropped_tier3_sections
        assert "dot1q vlan 20 any" in row
        assert not is_left_out_row(row)

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param(
                "interface GigabitEthernet0/0/0/1.7 l2transport\n encapsulation untagged\n!\n",
                id="another encapsulation",
            ),
            pytest.param(
                "interface Serial0/1/0/0.1 point-to-point\n"
                " ipv4 address 192.0.2.1 255.255.255.252\n!\n",
                id="no 802.1Q parent",
            ),
        ],
    )
    def test_what_the_rule_does_not_reach(self, text: str) -> None:
        """A stanza that states an encapsulation states something; a
        sub-interface of a serial line is not an 802.1Q one.  Neither is
        given the row, and each is read as before."""
        tree = _parse(XR, "hostname r1\n" + text + "end\n")
        assert not any(row.startswith("untagged: ") for row in tree.dropped_tier3_sections)
        assert any("." in i.name for i in tree.interfaces)


def _job(source: str, target: str, text: str) -> MigrationJob:
    return run_plan_with_checked_names(
        get_codec(source), get_codec(target), text, port_rename_map={},
    )


def _problems(job: MigrationJob, name: str) -> list[str]:
    """What *job* gets wrong about the sub-interface *name* of no tag:
    its address in the output, the tagged one's missing, and no row
    that says it was left out."""
    out = job.rendered or ""
    problems: list[str] = []
    if _UNTAGGED_IP in out:
        problems.append(f"{_UNTAGGED_IP} is in the output")
    if _TAGGED_IP not in out:
        problems.append(f"{_TAGGED_IP} is not in the output")
    if _row(name) not in job.dropped_tier3_sections:
        problems.append(f"no row says {name} was left out")
    return problems


@pytest.mark.parametrize("target", list_public_codecs())
@pytest.mark.parametrize("source", sorted(_SOURCES))
def test_no_target_is_given_it(source: str, target: str) -> None:
    text, name, _alone = _SOURCES[source]
    assert _problems(_job(source, target, text), name) == []


@pytest.mark.parametrize("source", sorted(_SOURCES))
def test_a_text_of_nothing_else_is_not_completed(source: str) -> None:
    """The row is a left-out row: a text with nothing else in it
    translated nothing."""
    _text, name, alone = _SOURCES[source]
    job = _job(source, "vyos", alone)
    assert job.status is MigrationJobStatus.partial
    assert (job.error or "").startswith("No source constructs were recognized")
    assert job.dropped_tier3_sections == [_row(name)]


@pytest.mark.parametrize("source", sorted(_SOURCES))
def test_the_check_sees_the_old_reading(
    source: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no sub-interface taken for one that needs a tag, the parse
    is the old one: onto VyOS the sub-interface came out as ``vif 7``,
    in a job that said ``completed`` (from EOS)."""
    for module in (xr_port_names, eos_port_names):
        monkeypatch.setattr(module, "a_sub_interface_needs_a_tag", lambda name: False)
    text, name, _alone = _SOURCES[source]
    job = _job(source, "vyos", text)
    assert "vif 7" in (job.rendered or "")
    assert _problems(job, name) == [
        f"{_UNTAGGED_IP} is in the output",
        f"no row says {name} was left out",
    ]


@pytest.mark.parametrize(
    ("source", "text"),
    [
        pytest.param(
            "cisco_iosxe_cli",
            "interface GigabitEthernet1.7\n ip address 192.0.2.1 255.255.255.0\n!\n",
            id="iosxe",
        ),
        pytest.param(
            "cisco_nxos",
            "interface Ethernet1/1.7\n  ip address 192.0.2.1/24\n",
            id="nxos",
        ),
    ],
)
def test_iosxe_and_nxos_are_not_asked(source: str, text: str) -> None:
    """Open: what such a sub-interface does on IOS-XE or NX-OS is not
    established, and their parsers keep it, with no tag."""
    tree = _parse(source, "hostname r1\n" + text)
    [held] = _holders(tree, _UNTAGGED_IP)
    assert held.dot1q_vlan is None

"""HSRP is read from both Cisco grammars, and what is not read is said.

IOS-XE writes an HSRP group as ``standby [<group>] <statement>`` lines of
its interface, NX-OS as an ``hsrp <group>`` block; both are read by
``netcanon/migration/codecs/_hsrp.py``.  Before it the IOS-XE parser read
no ``standby`` line, so every HSRP group of an IOS-XE config went without
a word, and the NX-OS parser read ``authentication md5 key-string 7
<key>`` as the key ``7``.

What each form means is typed here by hand from Cisco's HSRP guides
(the IOS "Configuring HSRP" guide; the Nexus "Configuring HSRP" guide),
never from the reader: the group is 0 where no number is given,
priority 100, preemption off and version 1 where nothing is stated, and
version 2 is what a group above 255 or an IPv6 address needs.  Every
key and name below is synthetic.
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalVRRPGroup,
)
from netcanon.migration.codecs._helpers import NAMES_SHOWN
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.services.migration_pipeline import run_plan

IOSXE = get_codec("cisco_iosxe_cli")
NXOS = get_codec("cisco_nxos")

#: A key the device printed encrypted.  Not the key: it must reach no
#: output, of any codec.
TYPE_7 = "fakeType7Blob"


def _iosxe(lines: str) -> str:
    return (
        "hostname r1\n!\ninterface Vlan10\n"
        " ip address 10.0.10.2 255.255.255.0\n"
        f"{lines}!\nend\n"
    )


def _nxos(lines: str) -> str:
    return (
        "hostname n1\nfeature hsrp\nfeature interface-vlan\n"
        "interface Vlan10\n  no shutdown\n  ip address 10.0.10.2/24\n"
        f"{lines}"
    )


def _groups(tree: CanonicalIntent) -> dict[int, dict]:
    (iface,) = [i for i in tree.interfaces if i.name == "Vlan10"]
    return {
        g.group_id: {
            "mode": g.mode,
            "virtual_ips": g.virtual_ips,
            "virtual_ipv6s": g.virtual_ipv6s,
            "virtual_mac": g.virtual_mac,
            "priority": g.priority,
            "preempt": g.preempt,
            "authentication": g.authentication,
        }
        for g in iface.vrrp_groups
    }


def _kinds(tree: CanonicalIntent, keyword: str) -> set[str]:
    """The kind of each row: the words between *keyword* and the colon."""
    kinds = set()
    for row in tree.dropped_tier3_sections:
        assert row.startswith(f"{keyword} "), row
        kinds.add(row[len(keyword) + 1:].split(": ", 1)[0])
    return kinds


def _group(**fields) -> dict:
    """A group as Cisco defines one that states only *fields*."""
    return {
        "mode": "hsrp", "virtual_ips": [], "virtual_ipv6s": [],
        "virtual_mac": "", "priority": 100, "preempt": False,
        "authentication": "", **fields,
    }


P, S = "10.0.10.1", "10.0.10.254"

#: ``(lines of the interface, groups, kinds of row)``, typed from the guide.
IOSXE_FORMS = [
    (f" standby 10 ip {P}\n", {10: _group(virtual_ips=[P])}, set()),
    # "If you do not configure a group number, the default group number is 0."
    (f" standby ip {P}\n", {0: _group(virtual_ips=[P])}, set()),
    (f" standby 10 ip {P}\n standby 10 ip {S} secondary\n",
     {10: _group(virtual_ips=[P, S])}, set()),
    # The primary is the primary wherever its line is.
    (f" standby 10 ip {S} secondary\n standby 10 ip {P}\n",
     {10: _group(virtual_ips=[P, S])}, set()),
    (" standby 10 priority 110\n standby 10 preempt\n",
     {10: _group(priority=110, preempt=True)}, set()),
    (" standby 10 preempt delay minimum 30\n",
     {10: _group(preempt=True)}, {"preempt delay"}),
    (" standby 10 preempt\n no standby 10 preempt\n", {10: _group()}, set()),
    (" standby 10 priority 300\n", {10: _group()}, {"priority"}),
    (" standby 10 authentication text fakeTextKey\n",
     {10: _group(authentication="plain:fakeTextKey")}, set()),
    # The text form with no ``text`` before the key.
    (" standby 10 authentication fakeTextKey\n",
     {10: _group(authentication="plain:fakeTextKey")}, set()),
    (" standby 10 authentication md5 key-string fakeMd5Key\n",
     {10: _group(authentication="md5:fakeMd5Key")}, set()),
    (" standby 10 authentication md5 key-string 0 fakeMd5Key\n",
     {10: _group(authentication="md5:fakeMd5Key")}, set()),
    (f" standby 10 authentication md5 key-string 7 {TYPE_7}\n",
     {10: _group()}, {"authentication md5 key-string 7"}),
    (" standby 10 authentication md5 key-chain FAKECHAIN\n",
     {10: _group()}, {"authentication md5 key-chain"}),
    (" standby 10 authentication md5 key-string fakeMd5Key timeout 30\n",
     {10: _group(authentication="md5:fakeMd5Key")},
     {"authentication md5 key-string timeout"}),
    (" standby 10 mac-address 0000.0C9F.F00A\n",
     {10: _group(virtual_mac="00:00:0c:9f:f0:0a")}, set()),
    (" standby 10 timers 1 3\n", {10: _group()}, {"timers"}),
    (" standby 10 track 1 decrement 20\n", {10: _group()}, {"track"}),
    (" standby 10 name FAKEGROUP\n", {10: _group()}, {"name"}),
    (" standby 10 follow FAKEGROUP\n", {10: _group()}, {"follow"}),
    # A group with no address learns it from the group's other routers.
    (" standby 10 ip\n", {10: _group()}, {"ip (no address)"}),
    (" standby 10 ipv6 2001:db8::1/64\n", {10: _group()}, {"ipv6"}),
    (" standby 10 ipv6 autoconfig\n", {10: _group()}, {"ipv6 autoconfig"}),
    (" standby version 2\n standby 10 ipv6 FE80::1\n",
     {10: _group(virtual_ipv6s=["FE80::1"])}, set()),
    (f" standby version 2\n standby 300 ip {P}\n",
     {300: _group(virtual_ips=[P])}, set()),
    (f" standby version 2\n standby 10 ip {P}\n",
     {10: _group(virtual_ips=[P])}, {"version 2"}),
    (f" standby 4095 ip {P}\n", {4095: _group(virtual_ips=[P])}, set()),
    (f" standby 010 ip {P}\n", {10: _group(virtual_ips=[P])}, set()),
    (f" standby 4096 ip {P}\n", {}, {"a group number above 4095"}),
    (f" standby 99999999999999999999 ip {P}\n", {}, {"a group number above 4095"}),
    (" standby use-bia\n", {}, {"use-bia"}),
    (" standby redirect\n", {}, {"redirect"}),
    (" standby fakeword\n", {}, {"another statement"}),
]


@pytest.mark.parametrize(("lines", "groups", "kinds"), IOSXE_FORMS)
def test_an_iosxe_standby_line_is_read_or_said(lines, groups, kinds) -> None:
    tree = IOSXE.parse(_iosxe(lines))
    assert _groups(tree) == groups
    assert _kinds(tree, "standby") == kinds


#: ``(lines of the interface, groups, kinds of row)`` for NX-OS's block.
NXOS_FORMS = [
    (f"  hsrp 10\n    ip {P}\n    ip {S} secondary\n    priority 110\n    preempt\n",
     {10: _group(virtual_ips=[P, S], priority=110, preempt=True)}, set()),
    (f"  hsrp 10 ipv4\n    ip {P}\n", {10: _group(virtual_ips=[P])}, set()),
    (f"  hsrp 10\n    authentication md5 key-string 7 {TYPE_7}\n    ip {P}\n",
     {10: _group(virtual_ips=[P])}, {"authentication md5 key-string 7"}),
    ("  hsrp 10\n    authentication md5 key-string 0 fakeMd5Key\n",
     {10: _group(authentication="md5:fakeMd5Key")}, set()),
    ("  hsrp 10\n    authentication text fakeTextKey\n",
     {10: _group(authentication="plain:fakeTextKey")}, set()),
    # An IPv6 group's lines are its own: none reaches group 10.
    (f"  hsrp 10\n    ip {P}\n  hsrp 11 ipv6\n    ip autoconfig\n    priority 120\n",
     {10: _group(virtual_ips=[P])}, {"ipv6 group"}),
    (f"  hsrp version 2\n  hsrp 10\n    ip {P}\n",
     {10: _group(virtual_ips=[P])}, {"version 2"}),
    (f"  hsrp version 2\n  hsrp 300\n    ip {P}\n",
     {300: _group(virtual_ips=[P])}, set()),
    (f"  hsrp 5000\n    ip {P}\n    priority 120\n", {}, {"a group number above 4095"}),
    ("  hsrp 10\n    timers 1 3\n    preempt delay minimum 60\n",
     {10: _group(preempt=True)}, {"timers", "preempt delay"}),
    # A comment among a group's lines is no statement of it.
    (f"  hsrp 10\n    ip {P}\n    ! a comment\n", {10: _group(virtual_ips=[P])}, set()),
]


@pytest.mark.parametrize(("lines", "groups", "kinds"), NXOS_FORMS)
def test_an_nxos_hsrp_block_is_read_or_said(lines, groups, kinds) -> None:
    tree = NXOS.parse(_nxos(lines))
    assert _groups(tree) == groups
    assert _kinds(tree, "hsrp") == kinds


def test_an_nxos_block_ends_where_its_indentation_does() -> None:
    tree = NXOS.parse(_nxos(f"  hsrp 10\n    ip {P}\n  description after-the-group\n"))
    (iface,) = [i for i in tree.interfaces if i.name == "Vlan10"]
    assert iface.description == "after-the-group"
    assert _groups(tree) == {10: _group(virtual_ips=[P])}


_UNREAD_VALUES = (TYPE_7, "FAKECHAIN", "FAKEGROUP", "fakeMd5Key", "2001:db8::1", P)


@pytest.mark.parametrize(("source", "parse_with"), [
    (_iosxe(
        f" standby 10 ip {P}\n"
        f" standby 10 authentication md5 key-string 7 {TYPE_7}\n"
        " standby 11 authentication md5 key-chain FAKECHAIN\n"
        " standby 12 name FAKEGROUP\n standby 13 follow FAKEGROUP\n"
        " standby 14 authentication md5 key-string fakeMd5Key timeout 30\n"
        " standby 15 ipv6 2001:db8::1/64\n"
        f" standby 99999 ip {P}\n"
    ), IOSXE),
    (_nxos(
        f"  hsrp 10\n    ip {P}\n    authentication md5 key-string 7 {TYPE_7}\n"
        f"  hsrp 5000\n    ip {P}\n"
    ), NXOS),
])
def test_a_row_names_the_place_and_never_a_value(source, parse_with) -> None:
    rows = parse_with.parse(source).dropped_tier3_sections
    assert rows
    for row in rows:
        for value in _UNREAD_VALUES:
            assert value not in row, row


def test_a_row_names_a_few_places_and_counts_the_rest() -> None:
    many = 10
    text = "hostname r1\n!\n" + "".join(
        f"interface Vlan{n}\n ip address 10.0.{n}.2 255.255.255.0\n"
        f" standby 1 ip 10.0.{n}.1\n standby 1 timers 1 3\n!\n"
        for n in range(1, many + 1)
    ) + "end\n"
    rows = IOSXE.parse(text).dropped_tier3_sections
    assert rows == [
        "standby timers: "
        + ", ".join(f"Vlan{n} group 1" for n in range(1, NAMES_SHOWN + 1))
        + f" and {many - NAMES_SHOWN} more -- the hello and hold times are "
        "not translated: the group uses its target's own"
    ]


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def _tree(*groups: CanonicalVRRPGroup) -> CanonicalIntent:
    return CanonicalIntent(
        hostname="r1",
        interfaces=[CanonicalInterface(
            name="Vlan10",
            ipv4_addresses=[CanonicalIPv4Address(ip="10.0.10.2", prefix_length=24)],
            vrrp_groups=list(groups),
        )],
    )


def _lines_with(text: str, *words: str) -> list[str]:
    return [ln for ln in text.splitlines() if any(w in ln for w in words)]


def test_iosxe_writes_a_group_a_line_a_statement() -> None:
    out = IOSXE.render(_tree(CanonicalVRRPGroup(
        group_id=10, mode="hsrp", virtual_ips=[P, S], priority=110,
        preempt=True, authentication="md5:fakeMd5Key",
        virtual_mac="00:00:0c:9f:f0:0a",
    )))
    assert _lines_with(out, "standby") == [
        f" standby 10 ip {P}",
        f" standby 10 ip {S} secondary",
        " standby 10 priority 110",
        " standby 10 preempt",
        " standby 10 authentication md5 key-string fakeMd5Key",
        " standby 10 mac-address 0000.0c9f.f00a",
    ]


def test_iosxe_writes_a_text_key_as_text() -> None:
    out = IOSXE.render(_tree(CanonicalVRRPGroup(
        group_id=10, mode="hsrp", virtual_ips=[P], preempt=False,
        authentication="plain:fakeTextKey",
    )))
    assert _lines_with(out, "standby") == [
        f" standby 10 ip {P}",
        " standby 10 authentication text fakeTextKey",
    ]


@pytest.mark.parametrize(("codec", "version_line"), [
    (IOSXE, " standby version 2"), (NXOS, "  hsrp version 2"),
])
def test_version_2_is_written_where_a_group_needs_it(codec, version_line) -> None:
    v1 = codec.render(_tree(CanonicalVRRPGroup(group_id=255, mode="hsrp", virtual_ips=[P])))
    v2 = codec.render(_tree(
        CanonicalVRRPGroup(group_id=10, mode="hsrp", virtual_ips=[P]),
        CanonicalVRRPGroup(group_id=256, mode="hsrp", virtual_ips=[S]),
    ))
    assert version_line not in v1.splitlines()
    lines = v2.splitlines()
    assert lines.count(version_line) == 1
    first_group = next(
        n for n, ln in enumerate(lines)
        if ln.strip().startswith(("standby 10", "hsrp 10"))
    )
    assert lines.index(version_line) < first_group


def test_iosxe_writes_version_2_for_an_ipv6_address() -> None:
    out = IOSXE.render(_tree(CanonicalVRRPGroup(
        group_id=10, mode="hsrp", virtual_ips=[P], virtual_ipv6s=["fe80::1"],
    )))
    assert _lines_with(out, "standby")[:3] == [
        " standby version 2", f" standby 10 ip {P}", " standby 10 ipv6 fe80::1",
    ]


@pytest.mark.parametrize("codec", [IOSXE, NXOS])
def test_a_key_that_is_not_one_the_target_takes_is_said(codec) -> None:
    out = codec.render(_tree(
        CanonicalVRRPGroup(group_id=10, mode="hsrp", virtual_ips=[P],
                           authentication="carp-key:fakeCarpKey"),
        CanonicalVRRPGroup(group_id=11, mode="hsrp", virtual_ips=[S],
                           authentication="md5:two words"),
    ))
    assert "fakeCarpKey" not in out
    assert "two words" not in out
    assert len([ln for ln in out.splitlines() if "authentication" in ln and "!" in ln]) == 2
    # The review lines are no statement of the group when read back.
    assert codec.parse(out).dropped_tier3_sections == []


def test_iosxe_says_what_an_hsrp_group_has_no_statement_for() -> None:
    out = IOSXE.render(_tree(CanonicalVRRPGroup(
        group_id=10, mode="hsrp", virtual_ips=[P], description="fake description",
        track_interfaces=["GigabitEthernet1"], advertisement_interval=5,
    )))
    (review,) = [ln for ln in out.splitlines() if "review: vrrp_groups[10]" in ln]
    assert "description" in review and "track_interfaces" in review
    assert "advertisement_interval" in review
    assert "fake description" not in out


def test_iosxe_says_a_group_it_has_no_line_for() -> None:
    out = IOSXE.render(_tree(CanonicalVRRPGroup(group_id=10, mode="hsrp", preempt=False)))
    assert _lines_with(out, "standby", "HSRP") == [
        " ! review: HSRP group 10 has no virtual address and no other statement "
        "to write, so it is not written",
    ]


def test_iosxe_still_says_a_carp_group() -> None:
    out = IOSXE.render(_tree(CanonicalVRRPGroup(group_id=10, mode="carp", virtual_ips=[P])))
    assert "standby" not in out
    assert " ! review: vrrp_groups[10].mode='carp' has no IOS-XE equivalent" in out


# ---------------------------------------------------------------------------
# Round trips, and every target
# ---------------------------------------------------------------------------

_IOSXE_SOURCE = _iosxe(
    " standby version 2\n"
    f" standby 10 ip {P}\n standby 10 ip {S} secondary\n"
    " standby 10 priority 110\n standby 10 preempt\n"
    " standby 10 authentication md5 key-string fakeMd5Key\n"
    " standby 300 ip 10.0.10.3\n standby 300 authentication text fakeTextKey\n"
)
_NXOS_SOURCE = _nxos(
    f"  hsrp 10\n    ip {P}\n    ip {S} secondary\n    priority 110\n    preempt\n"
    "    authentication md5 key-string 0 fakeMd5Key\n"
    "  hsrp 300\n    ip 10.0.10.3\n    authentication text fakeTextKey\n"
)
_BOTH_WRITE = ("virtual_ips", "priority", "preempt", "authentication", "mode")


def _what_both_write(tree: CanonicalIntent) -> dict[int, dict]:
    return {
        gid: {k: v for k, v in g.items() if k in _BOTH_WRITE}
        for gid, g in _groups(tree).items()
    }


@pytest.mark.parametrize(("source_text", "source"), [
    (_IOSXE_SOURCE, IOSXE), (_NXOS_SOURCE, NXOS),
])
@pytest.mark.parametrize("target", [IOSXE, NXOS])
def test_a_group_comes_back_from_either_cisco_target(source_text, source, target) -> None:
    tree = source.parse(source_text)
    assert tree.dropped_tier3_sections == []
    expected = {
        10: {"mode": "hsrp", "virtual_ips": [P, S], "priority": 110,
             "preempt": True, "authentication": "md5:fakeMd5Key"},
        300: {"mode": "hsrp", "virtual_ips": ["10.0.10.3"], "priority": 100,
              "preempt": False, "authentication": "plain:fakeTextKey"},
    }
    assert _what_both_write(tree) == expected
    back = target.parse(target.render(tree))
    assert _what_both_write(back) == expected
    assert back.dropped_tier3_sections == []


@pytest.mark.parametrize(("source_text", "source"), [
    (_iosxe(f" standby 10 ip {P}\n standby 10 authentication md5 key-string 7 {TYPE_7}\n"),
     IOSXE),
    (_nxos(f"  hsrp 10\n    ip {P}\n    authentication md5 key-string 7 {TYPE_7}\n"), NXOS),
])
@pytest.mark.parametrize("target", list_public_codecs())
def test_a_type_7_key_reaches_no_output(source_text, source, target) -> None:
    job = run_plan(source, get_codec(target), source_text)
    assert job.rendered is not None, job.error
    assert TYPE_7 not in job.rendered
    # Nor is the ``7`` read as the key, as the NX-OS parser once did.
    assert _groups(source.parse(source_text))[10]["authentication"] == ""

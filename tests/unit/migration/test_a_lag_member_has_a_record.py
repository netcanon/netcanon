"""A port a LAG names has a record of its own, and OPNsense assigns none.

The tree states a port's LAG twice -- in the LAG's ``members`` and in
the port's ``lag_member_of`` -- and most renderers write a member from
its interface record and never read the list.  OPNsense adds only an
UNASSIGNED interface to a LAGG ("Only unassigned interfaces can be
added to LAGG", docs.opnsense.org, Other Types), so a member is named
in ``<laggs>`` alone, and the parser made a record only for a zone of
``<interfaces>``: a LAGG's members came out on EOS as no LAG at all,
and on IOS-XE, IOS XR, NX-OS, Junos, AOS-CX and OS10 as a LAG with no
member, in jobs that said ``completed`` onto five of them.  A FortiOS
aggregate whose members no ``edit`` of their own configures (a pasted
fragment: FortiOS prints every port) lost them the same way.  And the
OPNsense renderer wrote a zone for every interface, a member included:
a config OPNsense refuses.

Here every parser that names members in a list is held to a record for
each; each LAG is followed onto every public codec and found in the
output with the target's own parser; the OPNsense output is read as
XML for a member it assigns; and what a member held that OPNsense has
no place for is said in the output, by element name and never by
value.  Each check is handed the defect it is for.

See also: ``tests/unit/migration/test_vlan_members_reach_the_output.py``
(the same rule for a VLAN's members), ``docs/vendors/opnsense.md``.
"""

from __future__ import annotations

import functools
from xml.etree import ElementTree as ET

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalLAG,
)
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.models.migration import MigrationJob
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

PUBLIC = list_public_codecs()

#: One LAG of two members, in the grammar of each parser that names a
#: LAG's members in a list of the LAG's own, and no member with a
#: stanza of its own.
SOURCES = {
    # The only form OPNsense allows: the members are in no zone.
    "opnsense": """\
<?xml version="1.0"?>
<opnsense>
  <system>
    <hostname>r1</hostname>
  </system>
  <interfaces>
    <lan>
      <enable>1</enable>
      <if>lagg0</if>
      <descr>LAN</descr>
      <ipaddr>10.0.0.1</ipaddr>
      <subnet>24</subnet>
    </lan>
  </interfaces>
  <laggs>
    <lagg>
      <members>igb1,igb2</members>
      <laggif>lagg0</laggif>
      <proto>lacp</proto>
    </lagg>
  </laggs>
</opnsense>
""",
    # A fragment: FortiOS prints an ``edit`` for every port.
    "fortigate_cli": """\
config system global
    set hostname "r1"
end
config system interface
    edit "agg1"
        set vdom "root"
        set type aggregate
        set member "port1" "port2"
    next
end
""",
    # A ``trunk`` line names the members; no port has a stanza.
    "aruba_aoss": """\
hostname "r1"
trunk 1-2 trk1 lacp
vlan 1
   name "DEFAULT_VLAN"
   untagged 3-24,Trk1
   exit
""",
    # ``slaves=`` names the members; no ``/interface ethernet`` line.
    "mikrotik_routeros": """\
/interface bonding
add mode=802.3ad name=bond1 slaves=ether1,ether2
/system identity
set name=r1
""",
}

#: Targets with no LAG in their output at all.
WRITES_NO_LAG = {"cisco_iosxe"}

#: Jobs whose LAG the port-name translator cannot read: FortiOS
#: ``agg1`` keeps its name on a target that has no LAG of that name,
#: which writes none.  The job says so (``untranslated_ports``), and it
#: is pinned here by equality, so a translator that comes to read the
#: name fails until the pin is taken out.
NAME_NOT_READ = {
    ("fortigate_cli", "arista_eos"),
    ("fortigate_cli", "dell_os10"),
    ("fortigate_cli", "vyos"),
}

#: Targets that write a member from its interface record, measured by
#: handing them a tree with the records taken out (below): the targets
#: a missing record empties a LAG on.
WRITES_MEMBERS_FROM_RECORDS = {
    "arista_eos",
    "aruba_aoscx",
    "cisco_iosxe_cli",
    "cisco_iosxr",
    "cisco_nxos",
    "dell_os10",
    "juniper_junos",
}


def _members_without_record(tree: CanonicalIntent) -> list[str]:
    """Each member of a LAG with no interface record that names it."""
    records = {i.name: i for i in tree.interfaces}
    return [
        f"{m} of {lag.name}"
        for lag in tree.lags
        for m in lag.members
        if m not in records or records[m].lag_member_of != lag.name
    ]


@pytest.mark.parametrize("source", sorted(SOURCES))
def test_each_member_has_a_record_of_its_own(source: str) -> None:
    tree = get_codec(source).parse(SOURCES[source])
    assert [len(lag.members) for lag in tree.lags] == [2]
    assert _members_without_record(tree) == []


class _OldParse(type(get_codec("opnsense"))):
    """The OPNsense parser as it was: no record for a member no zone
    assigns."""

    def parse(self, text, *args, **kwargs):
        tree = super().parse(text, *args, **kwargs)
        tree.interfaces = [
            i for i in tree.interfaces
            if i != CanonicalInterface(name=i.name, lag_member_of=i.lag_member_of)
        ]
        return tree


def test_the_check_finds_a_member_with_no_record() -> None:
    tree = _OldParse().parse(SOURCES["opnsense"])
    assert _members_without_record(tree) == ["igb1 of lagg0", "igb2 of lagg0"]


@functools.cache
def _job(source: str, target: str, parse=None) -> MigrationJob:
    return run_plan_with_checked_names(
        parse or get_codec(source), get_codec(target), SOURCES[source], port_rename_map={},
    )


def _lag_lost(job: MigrationJob, target: str) -> list[str]:
    """Whether the target's own parser finds a LAG of two members in the
    output, each named in the text."""
    tree = get_codec(target).parse(job.rendered or "")
    full = [lag for lag in tree.lags if len(lag.members) == 2]
    if not full:
        return [f"no LAG of two members in {[(lag.name, lag.members) for lag in tree.lags]}"]
    return [f"{m} not in the text" for m in full[0].members if m not in (job.rendered or "")]


@pytest.mark.parametrize("target", sorted(set(PUBLIC) - WRITES_NO_LAG))
@pytest.mark.parametrize("source", sorted(SOURCES))
def test_the_lag_reaches_every_target(source: str, target: str) -> None:
    job = _job(source, target)
    if (source, target) in NAME_NOT_READ:
        assert job.status.value == "partial"
        assert "agg1" in job.untranslated_ports
        return
    assert _lag_lost(job, target) == []


def test_the_pin_of_names_not_read_is_what_is_measured() -> None:
    measured = {
        (source, target)
        for source in SOURCES
        for target in set(PUBLIC) - WRITES_NO_LAG
        if _lag_lost(_job(source, target), target)
    }
    assert measured == NAME_NOT_READ


def test_the_check_finds_the_old_parse() -> None:
    """With no record for a member, the check finds the LAG empty, or
    gone, on exactly the targets that write a member from its record."""
    measured = {
        target
        for target in set(PUBLIC) - WRITES_NO_LAG
        if _lag_lost(_job("opnsense", target, _OldParse()), target)
    }
    assert measured == WRITES_MEMBERS_FROM_RECORDS


def _assigned_members(xml: str) -> list[str]:
    """Each member of a LAGG that a zone of ``<interfaces>`` assigns,
    read from the XML."""
    root = ET.fromstring(xml)
    members = {
        m
        for lagg in root.iterfind("laggs/lagg")
        for m in (lagg.findtext("members") or "").split(",")
        if m
    }
    return sorted(
        zone.findtext("if")
        for zone in root.iterfind("interfaces/*")
        if zone.findtext("if") in members
    )


@pytest.mark.parametrize("source", sorted(SOURCES))
def test_opnsense_assigns_no_member(source: str) -> None:
    job = _job(source, "opnsense")
    assert _assigned_members(job.rendered or "") == []
    lagg = ET.fromstring(job.rendered or "").find("laggs/lagg")
    assert lagg is not None
    assert len((lagg.findtext("members") or "").split(",")) == 2


def test_the_check_finds_an_assigned_member() -> None:
    old = """\
<opnsense>
  <interfaces>
    <opt1><if>igb1</if><enable/></opt1>
    <lan><if>lagg0</if></lan>
  </interfaces>
  <laggs><lagg><laggif>lagg0</laggif><members>igb1,igb2</members></lagg></laggs>
</opnsense>
"""
    assert _assigned_members(old) == ["igb1"]


def _comments(xml: str) -> list[str]:
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    root = ET.fromstring(xml, parser=parser)
    lagg = root.find("laggs/lagg")
    assert lagg is not None
    return [node.text or "" for node in lagg if node.tag is ET.Comment]


def _member_tree(**member) -> CanonicalIntent:
    return CanonicalIntent(
        hostname="r1",
        interfaces=[
            CanonicalInterface(name="lagg0"),
            CanonicalInterface(name="x--1", lag_member_of="lagg0", **member),
            CanonicalInterface(name="x2", lag_member_of="lagg0"),
        ],
        lags=[CanonicalLAG(name="lagg0", members=["x--1", "x2"])],
    )


def test_what_a_member_held_is_said_by_name_not_value() -> None:
    xml = get_codec("opnsense").render(_member_tree(
        description="words of the member", mtu=9000, enabled=False,
    ))
    assert _comments(xml) == [
        " review: x- -1 is a member of this LAGG, and OPNsense assigns no"
        " member of a LAGG: not written: descr, mtu, disabled ",
    ]
    assert "words of the member" not in xml
    assert "9000" not in xml
    assert _assigned_members(xml) == []
    back = get_codec("opnsense").parse(xml)
    assert [lag.members for lag in back.lags] == [["x--1", "x2"]]


def test_a_member_that_held_nothing_has_no_comment() -> None:
    assert _comments(get_codec("opnsense").render(_member_tree())) == []


def test_a_record_under_a_members_name_that_is_no_member_keeps_its_zone() -> None:
    """Two source ports a port map put on one name (a FortiGate's
    ``dmz`` and its aggregate's ``port1``, both on ``igb1``): the
    record that names the LAG is the member, and the other keeps its
    zone and its address, which is not said of the member.  The job is
    ``partial`` for the fused name; matched by name, the address went
    with the member and the comment put it on the member."""
    tree = CanonicalIntent(
        hostname="r1",
        interfaces=[
            CanonicalInterface(
                name="igb1",
                ipv4_addresses=[CanonicalIPv4Address(ip="10.0.0.1", prefix_length=24)],
            ),
            CanonicalInterface(name="lagg0"),
            CanonicalInterface(name="igb1", lag_member_of="lagg0"),
            CanonicalInterface(name="igb2", lag_member_of="lagg0"),
        ],
        lags=[CanonicalLAG(name="lagg0", members=["igb1", "igb2"])],
    )
    xml = get_codec("opnsense").render(tree)
    root = ET.fromstring(xml)
    addressed = [
        (zone.findtext("if"), zone.findtext("ipaddr"))
        for zone in root.iterfind("interfaces/*")
        if zone.findtext("ipaddr")
    ]
    assert addressed == [("igb1", "10.0.0.1")]
    assert _comments(xml) == []

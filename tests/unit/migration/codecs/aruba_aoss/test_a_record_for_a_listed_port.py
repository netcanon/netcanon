"""Aruba AOS-S parse: every port the config names has a record.

The device prints an ``interface`` stanza only for a port that has a
setting of its own.  Every other port is in the config all the same --
in the ``untagged`` / ``tagged`` lists of its VLANs, or on a ``trunk``
line as a member of a LAG -- and a switch's own config can have no
``interface`` stanza at all.

The parser used to make a record only for a stanza.  A target that
writes a port's VLANs and its LAG on the port's own stanza writes them
from the port's record, so such a port was in no line of that output:
a standalone switch's access ports came out on NX-OS with no stanza
and no VLAN, in a job that said ``completed``.

What every capture onto every target makes of this is read in
``tests/unit/migration/test_vlan_members_reach_the_output.py``; here is
the record itself.
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs.aruba_aoss.codec import ArubaAOSSCodec

pytestmark = pytest.mark.unit

_HEAD = '; J9727A Configuration Editor; Created on release #WB.16.08.0001\nhostname "sw"\n'

#: No ``interface`` stanza: two access ports, a tagged-only port, a
#: port with both, and a LAG of two ports that a VLAN lists.
_LISTS_ONLY = (
    _HEAD
    + "trunk 23-24 trk1 lacp\n"
    + 'vlan 1\n   name "DEFAULT_VLAN"\n   untagged 1-2,A1\n   no untagged 23-24\n   exit\n'
    + 'vlan 10\n   name "V10"\n   untagged 3\n   tagged 2,4,Trk1\n   exit\n'
)


def _records(text: str) -> dict[str, dict]:
    return {iface.name: iface.model_dump() for iface in ArubaAOSSCodec().parse(text).interfaces}


def test_a_port_a_vlan_names_has_a_record() -> None:
    got = {
        iface.name: (iface.switchport_mode, iface.access_vlan, iface.trunk_native_vlan, iface.trunk_allowed_vlans)
        for iface in ArubaAOSSCodec().parse(_LISTS_ONLY).interfaces
    }
    assert got == {
        "1": ("access", 1, None, []),
        "A1": ("access", 1, None, []),
        # Untagged in VLAN 1 and tagged in VLAN 10: the list is what
        # the port carries, the VLAN it carries untagged among them.
        "2": ("trunk", None, 1, [1, 10]),
        "3": ("access", 10, None, []),
        "4": ("trunk", None, None, [10]),
        "23": (None, None, None, []),
        "24": (None, None, None, []),
        "trk1": ("trunk", None, None, [10]),
    }


def test_the_record_an_empty_stanza_makes() -> None:
    """A config and its own rendering parse alike only if the record
    made for a listed port is the one a stanza with no lines makes:
    enabled, and typed from its name."""
    stanzas = "".join(
        f"interface {name}\n   exit\n" for name in ("1", "2", "3", "4", "23", "24", "A1", "Trk1")
    )
    assert _records(_LISTS_ONLY) == _records(_LISTS_ONLY + stanzas)


def test_a_member_only_a_trunk_line_names() -> None:
    tree = ArubaAOSSCodec().parse(_HEAD + "trunk 23-24 trk1 lacp\n")
    assert [(lag.name, lag.members) for lag in tree.lags] == [("trk1", ["23", "24"])]
    assert [(iface.name, iface.lag_member_of, iface.interface_type) for iface in tree.interfaces] == [
        ("23", "trk1", "ianaift:ethernetCsmacd"),
        ("24", "trk1", "ianaift:ethernetCsmacd"),
    ]


def test_a_lag_a_vlan_names_is_one_record() -> None:
    """``Trk1`` in a VLAN's list and ``trk1`` on the ``trunk`` line are
    one LAG: one record, under the tree's one spelling, typed a LAG."""
    lags = [
        (iface.name, iface.interface_type)
        for iface in ArubaAOSSCodec().parse(_LISTS_ONLY).interfaces
        if iface.name.lower().startswith("trk")
    ]
    assert lags == [("trk1", "ianaift:ieee8023adLag")]


def test_a_stanza_keeps_what_it_says() -> None:
    """A port with a stanza has the stanza's record and no second one."""
    text = _LISTS_ONLY + 'interface 2\n   name "uplink"\n   disable\n   exit\n'
    tree = ArubaAOSSCodec().parse(text)
    (two,) = [iface for iface in tree.interfaces if iface.name == "2"]
    assert (two.enabled, two.description) == (False, "uplink")
    assert (two.switchport_mode, two.trunk_native_vlan, two.trunk_allowed_vlans) == ("trunk", 1, [1, 10])
    assert len({iface.name for iface in tree.interfaces}) == len(tree.interfaces)


def test_the_made_records_follow_the_stanzas() -> None:
    """Records for stanzas keep their places; the rest go on the end in
    the order an operator counts the ports."""
    text = (
        _HEAD
        + "interface 12\n   disable\n   exit\n"
        + 'vlan 20\n   name "V20"\n   untagged 12,10,2,A2,1\n'
        + "   ip address 10.0.20.1 255.255.255.0\n   exit\n"
    )
    names = [iface.name for iface in ArubaAOSSCodec().parse(text).interfaces]
    assert names == ["12", "Vlan20", "1", "2", "10", "A2"]


def test_no_port_named_no_record_made() -> None:
    assert ArubaAOSSCodec().parse(_HEAD + 'vlan 30\n   name "V30"\n   exit\n').interfaces == []


def test_a_port_on_two_trunk_lines() -> None:
    """A text that names one port on two ``trunk`` lines is read as
    it stands -- each LAG lists the port -- and the port's record
    names the LAG of the first line, with a stanza of its own or
    without one: the one LAG a target that writes a member on its
    own stanza can put it in."""
    two = "trunk 1-2 trk1 lacp\ntrunk 2-3 trk2 trunk\n"
    for stanza in ("", 'interface 2\n   name "x"\n   exit\n'):
        tree = ArubaAOSSCodec().parse(_HEAD + two + stanza)
        assert [(lag.name, lag.members) for lag in tree.lags] == [("trk1", ["1", "2"]), ("trk2", ["2", "3"])]
        assert {iface.name: iface.lag_member_of for iface in tree.interfaces} == {"1": "trk1", "2": "trk1", "3": "trk2"}
    # ... and the first line is the first in the text, whatever its number.
    tree = ArubaAOSSCodec().parse(_HEAD + "trunk 2-3 trk2 trunk\ntrunk 1-2 trk1 lacp\n")
    assert {iface.name: iface.lag_member_of for iface in tree.interfaces} == {"1": "trk1", "2": "trk2", "3": "trk2"}

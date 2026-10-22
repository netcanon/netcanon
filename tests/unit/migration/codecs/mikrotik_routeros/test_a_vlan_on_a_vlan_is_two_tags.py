"""A RouterOS VLAN interface on a sub-interface of a port is a
sub-interface of that port with two 802.1Q tags.

"In RouterOS, Q-in-Q can be configured by adding one VLAN interface
over another" (MikroTik, "VLAN"): ``add interface=ether1 name=vlan1
vlan-id=11`` and ``add interface=vlan1 name=vlan2 vlan-id=12`` send
both tags on ``ether1``.  The parser read the second as a VLAN
interface of one tag, an SVI of tag 12 with a VLAN no port carried.
Now it is typed as its port, ``dot1q_vlan`` the outer tag and
``dot1q_inner_vlan`` its own, on the PORT, and the renderer writes it
back on the VLAN interface of its port with its outer tag.

What each line means is typed here by hand; the cross-codec reading of
the output, as text, is in ``tests/unit/migration/
test_a_tag_statement_is_read_whole.py``.
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs import get_codec

pytestmark = pytest.mark.unit

ROS = get_codec("mikrotik_routeros")

#: Two tags on ether1, in the order an export prints them, and a
#: VLAN of the bridge beside them.
TEXT = """/interface bridge
add name=bridge1
/interface vlan
add interface=ether1 name=provider100 vlan-id=100
add interface=bridge1 name=vlan10 vlan-id=10
add interface=provider100 name=customer200 vlan-id=200
/ip address
add address=198.51.100.1/24 interface=provider100
add address=192.0.2.1/24 interface=customer200
add address=203.0.113.1/24 interface=vlan10
"""


def _tags(tree):
    return {
        i.name: (i.interface_type, i.vlan_parent, i.dot1q_vlan, i.dot1q_inner_vlan)
        for i in tree.interfaces if i.name != "bridge1"
    }


#: What each line states, typed by hand.
EXPECTED = {
    "provider100": ("ianaift:ethernetCsmacd", "ether1", 100, None),
    "customer200": ("ianaift:ethernetCsmacd", "ether1", 100, 200),
    "vlan10": ("ianaift:l3ipvlan", "bridge1", None, None),
}


def test_the_second_tag_is_an_inner_tag_on_the_port() -> None:
    tree = ROS.parse(TEXT)
    assert _tags(tree) == EXPECTED
    # Two sub-interfaces make no VLAN: the bridge's VLAN alone is one.
    assert [(v.id, v.name) for v in tree.vlans] == [(10, "vlan10")]
    assert tree.dropped_tier3_sections == []


def test_the_order_of_the_lines_decides_nothing() -> None:
    lines = TEXT.splitlines()
    outer = "add interface=ether1 name=provider100 vlan-id=100"
    inner = "add interface=provider100 name=customer200 vlan-id=200"
    swapped = "\n".join(
        inner if line == outer else outer if line == inner else line
        for line in lines
    ) + "\n"
    assert _tags(ROS.parse(swapped)) == EXPECTED


def test_it_is_written_back_as_it_was() -> None:
    rendered = ROS.render(ROS.parse(TEXT))
    vlan_lines = [line for line in rendered.splitlines() if " vlan-id=" in line]
    outer = "add interface=ether1 name=provider100 vlan-id=100"
    inner = "add interface=provider100 name=customer200 vlan-id=200"
    assert sorted(vlan_lines) == sorted(
        [outer, inner, "add interface=bridge1 name=vlan10 vlan-id=10"]
    )
    # A VLAN interface is written after the one it rides on.
    assert vlan_lines.index(outer) < vlan_lines.index(inner)
    assert _tags(ROS.parse(rendered)) == EXPECTED
    # The VLAN interface of the outer tag is the source's own, and no
    # other is made.
    assert "the outer tag" not in rendered


def test_a_bond_carries_two_tags_too() -> None:
    text = (
        "/interface bonding\nadd name=bond1 slaves=ether5,ether6 mode=802.3ad\n"
        "/interface vlan\nadd interface=bond1 name=p100 vlan-id=100\n"
        "add interface=p100 name=c200 vlan-id=200\n"
    )
    tags = _tags(ROS.parse(text))
    assert tags["c200"] == ("ianaift:ieee8023adLag", "bond1", 100, 200)

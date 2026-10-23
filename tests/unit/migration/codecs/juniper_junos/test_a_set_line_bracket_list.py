"""A set line's bracket list is one statement a value.

The Junos CLI takes ``set ... vlan members [ DATA VOICE ]``, and
``show configuration | display set`` prints it back one value a line.
The block form's list was written out so (``_leaf_lines``); a set
line's was read as it stood, the value ``[``: the port was in no VLAN
(a trunk of none, before Junos's access default), a name server was
``[``, in jobs that said nothing.  Several of the repository's own
vendor-reference pages write the form.

Each list here is held to the same config written one value a line,
typed by hand -- the form the parser always read -- tree for tree.
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs.registry import get_codec
from netcanon.migration.limits import LimitExceeded, Limits, limits_scope

pytestmark = pytest.mark.unit

JUNOS = get_codec("juniper_junos")

HEAD = "set system host-name T\nset vlans DATA vlan-id 10\nset vlans VOICE vlan-id 20\nset vlans MGMT vlan-id 30\n"

#: (a config that writes a list on one line, the same config one value a line)
SAME = {
    "trunk-members": (
        "set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode trunk\n"
        "set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members [ DATA VOICE MGMT ]\n",
        "set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode trunk\n"
        "set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members DATA\n"
        "set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members VOICE\n"
        "set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members MGMT\n",
    ),
    "ids-and-a-range": (
        "set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode trunk\n"
        "set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members [ 10 20-30 ]\n",
        "set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode trunk\n"
        "set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members 10\n"
        "set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members 20-30\n",
    ),
    "access-members": (
        "set interfaces ge-0/0/2 unit 0 family ethernet-switching vlan members [ DATA VOICE ]\n",
        "set interfaces ge-0/0/2 unit 0 family ethernet-switching vlan members DATA\n"
        "set interfaces ge-0/0/2 unit 0 family ethernet-switching vlan members VOICE\n",
    ),
    "name-servers": (
        "set system name-server [ 192.0.2.53 198.51.100.53 ]\n",
        "set system name-server 192.0.2.53\nset system name-server 198.51.100.53\n",
    ),
    "a-list-with-no-end": (
        "set system name-server [ 192.0.2.53 198.51.100.53\n",
        "set system name-server 192.0.2.53\nset system name-server 198.51.100.53\n",
    ),
    "apply-groups": (
        "set groups G1 system name-server 192.0.2.53\n"
        "set groups G2 system ntp server 192.0.2.123\n"
        "set apply-groups [ G1 G2 ]\n",
        "set groups G1 system name-server 192.0.2.53\n"
        "set groups G2 system ntp server 192.0.2.123\n"
        "set apply-groups G1\nset apply-groups G2\n",
    ),
    "inside-a-group": (
        "set groups G interfaces ge-0/0/3 unit 0 family ethernet-switching interface-mode trunk\n"
        "set groups G interfaces ge-0/0/3 unit 0 family ethernet-switching vlan members [ DATA MGMT ]\n"
        "set apply-groups G\n",
        "set groups G interfaces ge-0/0/3 unit 0 family ethernet-switching interface-mode trunk\n"
        "set groups G interfaces ge-0/0/3 unit 0 family ethernet-switching vlan members DATA\n"
        "set groups G interfaces ge-0/0/3 unit 0 family ethernet-switching vlan members MGMT\n"
        "set apply-groups G\n",
    ),
    "one-value-deactivated": (
        "set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode trunk\n"
        "set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members [ DATA VOICE ]\n"
        "deactivate interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members VOICE\n",
        "set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode trunk\n"
        "set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members DATA\n"
        "set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members VOICE\n"
        "deactivate interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members VOICE\n",
    ),
}


@pytest.mark.parametrize("case", sorted(SAME))
def test_a_list_is_its_values_one_a_line(case: str) -> None:
    listed, one_a_line = SAME[case]
    assert JUNOS.parse(HEAD + listed).model_dump() == JUNOS.parse(HEAD + one_a_line).model_dump()


def test_the_trunk_carries_the_list() -> None:
    """Not only equal to the other form: what the list says."""
    port = next(i for i in JUNOS.parse(HEAD + SAME["trunk-members"][0]).interfaces if i.name == "ge-0/0/1")
    assert (port.switchport_mode, port.trunk_allowed_vlans) == ("trunk", [10, 20, 30])


def test_the_set_form_is_the_block_form() -> None:
    block = (
        "system {\n    host-name T;\n}\n"
        "interfaces {\n    ge-0/0/1 {\n        unit 0 {\n            family ethernet-switching {\n"
        "                interface-mode trunk;\n"
        "                vlan {\n                    members [ DATA VOICE MGMT ];\n                }\n"
        "            }\n        }\n    }\n}\n"
        "vlans {\n    DATA {\n        vlan-id 10;\n    }\n    VOICE {\n        vlan-id 20;\n    }\n"
        "    MGMT {\n        vlan-id 30;\n    }\n}\n"
    )
    by_block = next(i for i in JUNOS.parse(block).interfaces if i.name == "ge-0/0/1")
    by_set = next(i for i in JUNOS.parse(HEAD + SAME["trunk-members"][0]).interfaces if i.name == "ge-0/0/1")
    assert by_block.model_dump() == by_set.model_dump()


@pytest.mark.parametrize(
    "line",
    [
        "set system name-server [ ]\n",
        "set system name-server [\n",
        "set [ system ]\n",
    ],
    ids=["empty", "open-and-empty", "nothing-before-it"],
)
def test_a_list_with_nothing_to_write_out_is_as_it_was(line: str) -> None:
    """Nothing is made of it, as the block form makes nothing of it."""
    JUNOS.parse(HEAD + line)


def test_a_list_is_counted_in_words_before_it_is_made() -> None:
    values = " ".join(f"v{n}" for n in range(40))
    text = HEAD + f"set system name-server [ {values} ]\n"
    tiny = Limits(name="tiny", vlan_ids=None, memberships=None, ports=None, interfaces=None,
                  copies=None, words=40 * 3 - 1, text=None, seconds=None)
    with limits_scope(tiny), pytest.raises(LimitExceeded) as caught:
        JUNOS.parse(text)
    assert (caught.value.kind, caught.value.asked) == ("words", 40 * 3)
    said = str(caught.value)
    assert "words of set commands written out from a bracket list" in said
    assert "system name-server" in said and "v0" not in said

"""The VLAN a trunk carries untagged is carried untagged in the output.

A trunk states two things about its untagged VLAN: which VLAN it is, and
the VLANs the trunk carries.  Whether the second statement has to name
the first is not one grammar.  On IOS-XE, EOS, NX-OS, AOS-CX and Junos
(the ELS grammar, which is the one its codec writes) the native VLAN is
a line of its own and the allowed line (``vlan members``) may name it
or leave it out.  On OS10 the untagged VLAN is
the trunk's access VLAN and the allowed line names tagged VLANs only.
On AOS-S a VLAN lists its ``untagged`` ports apart from its ``tagged``
ones.  The tree held each as its text had it and every renderer wrote
the list as it stood, so every AOS-S and OS10 trunk with an untagged
VLAN was written for the first five as a native line beside an allowed
line that left the VLAN out -- which, where the list decides what a
trunk carries, is a port that carries no untagged VLAN -- in jobs that
said ``completed``.  The other way a native VLAN the source left out of
its list was written ``untagged`` on AOS-S and as the access VLAN on
OS10.

The tree has one convention now (a trunk's list is what it carries, its
native VLAN among them), and this module does not read it by that
convention: a check that reads both trees the tree's way agrees with
whatever the code does.  It reads what a DEVICE carries untagged on a
port, each side by its own platform's grammar, written out here by hand
(:data:`HOW_IT_IS_STATED`, :data:`VLAN_BY_VLAN`) and compared with the
table the codecs read in a test of its own:

* where the list decides, the native VLAN is carried if the allowed
  line names it (no allowed line is every VLAN on four of the five, and
  no VLAN on Junos), and is *stated and not carried* if it does not;
* beside the list (OS10), the access VLAN of a trunk is carried
  whatever the allowed line says;
* VLAN by VLAN (AOS-S), the port is untagged in the VLAN that lists it
  so.

Which of these a device in fact does is the vendor's to say, and not
every vendor says it for every case: the sentences, their sources and
what is not established are in
``docs/vendor-references/cisco_iosxe_cli_to_juniper_junos/vlans.md``.
The rows below are how each platform's TEXT is written.  That a native
VLAN outside the list is not carried is the vendor's own sentence for
AOS-CX, and for IOS-XE and NX-OS when the VLAN is 1; for another VLAN
there it is an inference from the vendor's rule, for the Junos grammar
written here it is a stated requirement to receive, and for EOS it is
not established.  So "lost by the list" is a defect where the vendor
says so and a risk where nobody has: an output that leaves its native
VLAN out of its list is in neither case what the source stated.

The SOURCE is read from its tree, by its platform's row.  The OUTPUT is
read twice, by the target's row: parsed again with the target's parser,
and as text, by a reader this module owns for each of the seven
grammars.  The two have to agree.

A trunk that states no native VLAN
----------------------------------
What a platform does with a native line that is not there is its own
default, and the platforms differ: VLAN 1 on IOS-XE, EOS, NX-OS and
AOS-CX, and none on Junos (:data:`WITH_NO_NATIVE_LINE`, by hand, from
the same vendor reference).  A trunk of those four that states none
has native VLAN 1, and is read as carrying VLAN 1 untagged where its
list holds VLAN 1.  Where the list leaves VLAN 1 out nothing is
filled in, by a parser or by a reader: that is a native VLAN outside
its list, and what a switch does with one is each vendor's to say
(for EOS it is not established).  The tree did not say so: such a
trunk had no native VLAN, VLAN 1 was a tagged membership like any
other, and it was written TAGGED on Junos, OS10 and AOS-S, in jobs
that said nothing.  Each of the four parsers now puts its platform's
default, so that in a tree a parser made "no native VLAN" is no
untagged VLAN as far as the text AND the default go.

The default is a TRUNK's.  It is put for a port that SAYS it is a
trunk (``switchport mode trunk``; on AOS-CX a ``vlan trunk`` line,
which is how a trunk is stated there) and for no other: not for a
port that keeps trunk lines in another mode, and not for one a
parser took for a trunk from a trunk line alone.  This module holds
every tree to that BOTH ways -- a trunk of the four that says it is
one, with a list that holds VLAN 1 and no native VLAN, is a tree the
default was left out of; a port that does not say it is a trunk and
has the default all the same, with no native line of its own, is a
tree it was put into -- and its readers of TEXT apply the default
themselves, to a port that says it is a trunk, because a text states
less than its device does.  Which ports say so is read from the
text, here, and from no parser.  The words that say a native VLAN is
sent tagged are read as text here as well, each platform's by its
own grammar (:func:`says_tagged`): ``vlan dot1q tag native``, with
``exclude control`` after it or without; ``switchport trunk native
vlan tag``; ``no switchport trunk native vlan tag``, by which an
IOS-XE or NX-OS port leaves the first; and on AOS-CX ``vlan trunk
native N tag``.  A trunk under them carries no VLAN untagged:
nothing is filled in, by a parser or by a reader, and a native VLAN
it states is one it sends tagged, which no tree keeps.

The other half: a port that carries no VLAN untagged on its source,
written for one of the four with no native line beside a list that
holds VLAN 1, would carry VLAN 1 untagged THERE, by the target's own
default.  So it is written each target's form for "this trunk
carries no VLAN untagged": on AOS-CX ``vlan trunk native 1 tag``, on
EOS ``switchport trunk native vlan tag``, and on IOS-XE and NX-OS
``vlan dot1q tag native`` -- a line for EVERY trunk of the switch,
written where no port the check reads blocks it.  It reads the
ports in trunk mode, the ports with trunk lines and no mode, and the
ports in a mode no mode line is written for (dynamic, private-vlan,
dot1q-tunnel, fex-fabric and the like): none may carry a VLAN
untagged, be in such a mode, or hold trunk lines in no mode.  A port
with no mode and no trunk line is not counted: on a Catalyst such a
port is in dynamic auto by default, and should it become a trunk the
line tags its native VLAN as well.  Where a port blocks it, the port
is left to the default and its stanza has a review line that says so
(:data:`SAID_OF_NO_UNTAGGED`, held whole); those cells are pinned
(:data:`BY_THE_TARGETS_DEFAULT`), and on any other target such a
port is a fault.

OS10 and AOS-S have a default of their own, and their readers of
text apply it.  An OS10 trunk with neither an access line nor ``no
switchport access vlan`` is an untagged member of its switch's
default VLAN, whose id no text gives (:data:`THE_SWITCHS_DEFAULT`);
OS10 is written ``no switchport access vlan`` for such a trunk,
under a review line held whole (:data:`SAID_OF_NONE_ON_OS10`), which
says that Dell's pages disagree on what the line leaves it with.  An
AOS-S port that a VLAN tags, that no VLAN lists untagged, and that is
on no line of VLAN 1 is in VLAN 1 by default; AOS-S is written ``no
untagged`` in VLAN 1's stanza for it, and a trunk that carries VLAN 1
tagged on VLAN 1's ``tagged`` line.  What remains is a trunk that
carries nothing, which AOS-S has no form for: pinned cell by cell
(:data:`ON_NO_VLAN_LINE_OF_AOSS`).

What may not be
---------------
* **a VLAN on both lines of an OS10 trunk**: its access line and its
  allowed line;
* **lost by the list**: the source carries a VLAN untagged, and the
  output states it as the port's native VLAN beside a list that leaves
  it out;
* **gained by the list**: the source states a native VLAN its list
  leaves out, and the output carries that VLAN untagged;
* **a tag in its place**, or the other way: untagged on one side and
  tagged on the other;
* **another VLAN**, or none, on a port the output does state;
* **the default left out of a tree**: a trunk of a platform whose
  trunk has a default native VLAN, that says it is a trunk, with
  that VLAN on its list and no native VLAN in the tree, in a text
  that does not say the native VLAN is tagged -- on the source's
  tree, or on the output parsed again;
* **the default put where no trunk is stated**: a port of such a
  platform that does not say it is a trunk and states no native
  VLAN, with the platform's default for one in the tree;
* **a native VLAN sent tagged, kept**: a trunk whose text says its
  native VLAN is sent tagged, with a native VLAN in the tree -- on
  the source's tree, or on the output parsed again;
* **left to a default, and not said**: a port that carries no VLAN
  untagged on its source and VLAN 1 untagged in the output by the
  target's own default -- on IOS-XE or NX-OS without the review
  line in its stanza, whole, and on any other target at all; and a
  review line on a port that is not such a port;
* **left out, and not said**, onto AOS-S: the source states a native
  VLAN its list leaves out, the output writes no ``untagged`` line
  for the port, and no ``; review:`` line in that VLAN's stanza says
  so.  (By HPE's sentences an AOS-S port is in the default VLAN until
  it is removed from it, so an output that says nothing is not known
  to be one that carries nothing.)  The line is held WHOLE, in the
  three forms typed below (:data:`SAID_TAKEN_OUT`,
  :data:`SAID_OF_A_PORT`, :data:`SAID_OF_A_GROUP`): a line that says
  a word more is not the line, and neither is the form for a port on
  a trunk group or on a port the output's own ``trunk`` line names,
  nor the form for a name VLAN 1's ``no untagged`` line takes out on
  one it does not, or the other way;
* **an OS10 ``no switchport access vlan`` under no review line,
  whole**.

A port the output states nothing for is not judged here: every
membership of every port is accounted for, one by one, in
``test_vlan_members_reach_the_output.py``.

Small configs carry each shape through every pair -- the native VLAN
in the list, outside it, not stated, stated with no list, VLAN 1 on
the list of a trunk that states no native VLAN, a trunk that states
nothing at all, the words that tag a native VLAN, and what an AOS-S
port can be -- and what each source carries is written beside it by
hand.  And ports that keep a trunk line without saying they are
trunks, with what each parser makes of one beside it
(:data:`WITH_A_TRUNK_LINE`): none is given the default, and none is
written VLAN 1 untagged.

What this cannot see
--------------------
The default VLAN of an OS10 switch is a setting no trunk states: no
parser fills it in, so a SOURCE trunk that states no access VLAN is
read from its tree as carrying none (the reading that carries fewer);
the reader of text names it, with no id, and the shapes that have it
are pinned (:data:`BY_THE_SWITCHS_DEFAULT`).  An AOS-S source port
on no line of VLAN 1 is read from its tree the same way.
What a trunk under the words that tag its native VLAN does with its
control traffic, and which id it sends tagged, is read by nobody
here: the tree keeps no such id, and the readers keep none either.
Whether a target ACCEPTS a line is nobody's to say
from here, and neither is what ``no switchport access vlan`` leaves
an OS10 trunk with: it is read as no untagged VLAN, and Dell's pages
do not agree that it is.  A Junos trunk in the older grammar
(``port-mode trunk``) is read as an ELS one.  And a VLAN device on
FortiOS, RouterOS or OPNsense is read by no reader of this module:
those targets write the untagged VLAN as a tagged device.
"""

from __future__ import annotations

import collections
import re
from pathlib import Path
from typing import Any, NamedTuple

import pytest

from netcanon.migration.codecs._helpers import (
    BESIDE_THE_LIST,
    LIST_DECIDES,
    NATIVE_NONE,
    NATIVE_OF_THE_SWITCH,
    NATIVE_VLAN_AND_THE_LIST,
    TRUNK_THAT_STATES_NO_LIST,
    TRUNK_THAT_STATES_NO_NATIVE,
    switchport_trunk_native_value,
    trunk_list_read,
    trunk_list_written,
    unstated_native_vlan,
)
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.migration.fixture_dirs import DIR_TO_CODEC_NAME
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"

# ---------------------------------------------------------------------------
# How each platform states it, written here by hand
# ---------------------------------------------------------------------------

LIST, BESIDE = "the list decides", "beside the list"

#: How the text of each platform states the VLAN a trunk carries
#: untagged.  By hand, from each vendor's grammar; the codecs read
#: their own table, and ``test_the_table_is_the_one_written_here``
#: holds the two to each other.  (Junos is its ELS grammar here --
#: ``interface-mode trunk``, ``native-vlan-id`` on the physical
#: interface -- which is what the codec writes.  The older grammar
#: states the native VLAN beside its members and is not this row.)
HOW_IT_IS_STATED = {
    "arista_eos": LIST,
    "aruba_aoscx": LIST,
    "cisco_iosxe_cli": LIST,
    "cisco_nxos": LIST,
    "juniper_junos": LIST,
    "dell_os10": BESIDE,
}

#: The one platform that states it VLAN by VLAN: a VLAN's ``untagged``
#: list names the port.  It has no allowed list, and is in neither
#: table of the codecs.
VLAN_BY_VLAN = frozenset({"aruba_aoss"})

#: The codecs whose parser states which VLANs a port carries: the
#: targets of this module, and the sources that have anything to lose.
SWITCHES = sorted(set(HOW_IT_IS_STATED) | VLAN_BY_VLAN)

#: Where a trunk with no allowed line carries every VLAN (on AOS-CX: a
#: native line and no allowed line).  On Junos it carries none; on OS10
#: no tagged one.
_NO_LINE_IS_EVERY_VLAN = frozenset({"arista_eos", "aruba_aoscx", "cisco_iosxe_cli", "cisco_nxos"})

NO_ID = "the default VLAN of the switch: no id in the text"

#: The native VLAN of a trunk whose text states NONE.  By hand, from
#: each vendor's own sentence (the vendor reference's table "And when
#: the config states no untagged VLAN at all"); the codecs read their
#: own table, and ``test_the_table_is_the_one_written_here`` holds the
#: two to each other.  An OS10 trunk has its switch's default VLAN,
#: which is a setting no trunk states: nothing is filled in for it,
#: by the codecs or here.  (AOS-S has no trunk line to leave out.)
WITH_NO_NATIVE_LINE: dict[str, Any] = {
    "arista_eos": 1,
    "aruba_aoscx": 1,
    "cisco_iosxe_cli": 1,
    "cisco_nxos": 1,
    "juniper_junos": None,
    "dell_os10": NO_ID,
}

#: The platforms whose trunk has a default native VLAN with an id.
HAVE_A_DEFAULT = sorted(codec for codec, vid in WITH_NO_NATIVE_LINE.items() if isinstance(vid, int))


def _default_native(codec: str) -> int | None:
    """The id a trunk of *codec* has for a native VLAN when its text
    states none, or ``None`` where there is none to name."""
    vid = WITH_NO_NATIVE_LINE.get(codec)
    return vid if isinstance(vid, int) else None


ALL = "all"


class Port(NamedTuple):
    """What a device carries on one port, as its text states it."""

    untagged: int | None        # the VLAN it carries untagged
    left_out: int | None        # a native VLAN it states and its list leaves out
    tagged: Any                 # ``ALL``, or the ids it carries tagged
    by_default: bool = False    # no line states the untagged VLAN: it is the platform's own

    def carries_tagged(self, vid: int) -> bool:
        return vid != self.untagged and (self.tagged == ALL or vid in self.tagged)


def _port(
    how: str, mode: str | None, access: int | None, native: int | None, allowed: Any, default: Any = None,
) -> Port | None:
    """One port's statements, read by its platform's row.  *allowed* is
    ``ALL`` or a set of ids: what the allowed line names, or what the
    platform's trunk carries with no such line.  *default* is the
    native VLAN of a trunk that states none, for a reader of TEXT: a
    tree is read with none, because its parser has put it (or, on
    OS10, because no id can be put: :data:`THE_SWITCHS_DEFAULT`)."""
    if mode == "access":
        return Port(access, None, frozenset())
    if mode != "trunk":
        return None
    by_default = native is None and default is not None
    if by_default:
        native = default
    held = native is not None and (how == BESIDE or allowed == ALL or native in allowed)
    untagged = native if held else None
    # A default the list leaves out is no statement: nothing is "left out".
    left_out = native if native is not None and not held and not by_default else None
    return Port(
        untagged, left_out, allowed if allowed == ALL else frozenset(allowed) - {untagged}, by_default and held,
    )


def _listed(ids: Any) -> Any:
    ids = set(ids)
    return ALL if len(ids) >= 4094 else frozenset(ids)


# ---------------------------------------------------------------------------
# Reading a tree
# ---------------------------------------------------------------------------


def read_tree(tree: Any, codec: str) -> dict[str, Port]:
    """Port name -> what the device of *codec* carries on it, from a
    tree its parser made."""
    if codec in VLAN_BY_VLAN:
        untagged: dict[str, int] = {}
        tagged: dict[str, set[int]] = collections.defaultdict(set)
        for vlan in tree.vlans:
            for name in vlan.untagged_ports:
                untagged[name] = vlan.id
            for name in vlan.tagged_ports:
                tagged[name].add(vlan.id)
        return {
            name: Port(untagged.get(name), None, frozenset(tagged.get(name, ())))
            for name in set(untagged) | set(tagged)
        }
    # A text can hold the stanza of one interface more than once (an
    # output does, for source ports the job lists as fused under one
    # name), and four parsers make a record of each.  The device has
    # ONE interface: what a later stanza does not state stands as an
    # earlier one left it.
    stated: dict[str, tuple[Any, Any, Any, Any]] = {}
    for iface in tree.interfaces:
        mode, access, native, allowed = stated.get(iface.name, (None, None, None, []))
        stated[iface.name] = (
            iface.switchport_mode or mode,
            iface.access_vlan if iface.access_vlan is not None else access,
            iface.trunk_native_vlan if iface.trunk_native_vlan is not None else native,
            iface.trunk_allowed_vlans if iface.switchport_mode == "trunk" else iface.trunk_allowed_vlans or allowed,
        )
    out: dict[str, Port] = {}
    for name, (mode, access, native, allowed) in stated.items():
        port = _port(HOW_IT_IS_STATED[codec], mode, access, native, _listed(allowed))
        if port is not None:
            out[name] = port
    return out


def _squeezed(name: str) -> str:
    """An interface's name as a stanza's header or a tree has it,
    made one: white space out, lower case, and without the word
    AOS-CX writes after a LAG's name."""
    return re.sub(r"\s+", "", re.sub(r"\s+multi-chassis.*$", "", name)).casefold()


_A_NATIVE_LINE = re.compile(r"(?:switchport trunk native vlan|vlan trunk native) \d+(?: tag)?")


def says_it_is_a_trunk(text: str, codec: str) -> set[str]:
    """The interfaces of a text of *codec* that SAY they are trunks,
    in any stanza of their name: ``switchport mode trunk``; on
    AOS-CX a ``vlan trunk`` line, which is how a trunk is stated
    there.  Read from the text.  A trunk line alone -- ``switchport
    trunk allowed vlan``, ``switchport trunk native vlan`` -- is not
    that statement."""
    said: set[str] = set()
    for name, body in _stanzas(text, "interface "):
        if codec == "aruba_aoscx":
            is_one = any(line.startswith("vlan trunk ") for line in body)
        else:
            is_one = "switchport mode trunk" in body
        if is_one:
            said.add(_squeezed(name))
    return said


def states_a_native_vlan(text: str) -> set[str]:
    """The interfaces of a text that state a native VLAN in a line
    of their own, in any stanza of their name."""
    return {
        _squeezed(name) for name, body in _stanzas(text, "interface ")
        if any(_A_NATIVE_LINE.fullmatch(line) for line in body)
    }


def left_unfilled(tree: Any, codec: str, text: str) -> list[str]:
    """The trunks of a tree of *codec* that the platform's default
    native VLAN was left out of: a record that is a trunk, of an
    interface that SAYS it is one, with a list that holds the
    default and no native VLAN.  *text* is what the tree was parsed
    from: who says it is a trunk is read from it, under the words
    that tag a native VLAN nothing is owed, and neither is it to a
    record of an interface that states its native VLAN in another
    stanza."""
    default = _default_native(codec)
    if default is None:
        return []
    every_tagged, own_tagged = says_tagged(text, codec)
    said = says_it_is_a_trunk(text, codec)
    states_one = {iface.name for iface in tree.interfaces if iface.trunk_native_vlan is not None}
    return [
        iface.name for iface in tree.interfaces
        if iface.switchport_mode == "trunk" and _squeezed(iface.name) in said
        and iface.trunk_native_vlan is None and default in iface.trunk_allowed_vlans
        and iface.name not in states_one and not own_tagged.get(_unspaced(iface.name), every_tagged)
    ]


def kept_tagged(tree: Any, codec: str, text: str) -> list[str]:
    """The trunks of a tree of *codec* that have a native VLAN although
    their text says it is sent TAGGED (:func:`says_tagged`).  Such a
    trunk carries no VLAN untagged; a native VLAN in the tree is one
    every target is written as untagged."""
    every_tagged, own_tagged = says_tagged(text, codec)
    return [
        iface.name for iface in tree.interfaces
        if iface.switchport_mode == "trunk" and iface.trunk_native_vlan is not None
        and own_tagged.get(_unspaced(iface.name), every_tagged)
    ]


def put_unasked(tree: Any, codec: str, text: str) -> list[str]:
    """The ports of a tree of *codec* that HAVE the platform's
    default native VLAN and are owed none: the interface does not
    say it is a trunk, and no line of its own states that VLAN.
    The default is a trunk's.  A port given it without saying so
    is written an untagged VLAN that its text does not state, on
    every target that states the untagged VLAN in a line."""
    default = _default_native(codec)
    if default is None:
        return []
    said, stated = says_it_is_a_trunk(text, codec), states_a_native_vlan(text)
    return [
        iface.name for iface in tree.interfaces
        if iface.trunk_native_vlan == default
        and _squeezed(iface.name) not in said and _squeezed(iface.name) not in stated
    ]


def _defaults_misplaced(
    checked: tuple[tuple[str, Any, str, str], ...],
) -> tuple[list[str], list[str], list[str]]:
    """A sentence for every port :func:`left_unfilled` names, one for
    every port :func:`put_unasked` names, and one for every port
    :func:`kept_tagged` names, of every ``(whose tree it is, the tree,
    its text, its codec)``."""
    left_out = [
        f"{name!r} of {where}, read as {codec}: {NOT_FILLED}"
        for where, tree, text, codec in checked for name in left_unfilled(tree, codec, text)
    ]
    put = [
        f"{name!r} of {where}, read as {codec}: {NOT_OWED}"
        for where, tree, text, codec in checked for name in put_unasked(tree, codec, text)
    ]
    kept = [
        f"{name!r} of {where}, read as {codec}: {KEPT_TAGGED}"
        for where, tree, text, codec in checked for name in kept_tagged(tree, codec, text)
    ]
    return left_out, put, kept


# ---------------------------------------------------------------------------
# Reading a text: one small reader a grammar, owing nothing to the codec
# ---------------------------------------------------------------------------


def _ids(text: str) -> set[int]:
    ids: set[int] = set()
    for part in text.replace(" ", "").split(","):
        low, _, high = part.partition("-")
        if low.isdigit() and (high.isdigit() or not high):
            ids.update(range(int(low), int(high or low) + 1))
    return ids


def _stanzas(text: str, opener: str):
    """(what follows *opener*, the indented lines under it) for every
    stanza a line at column 0 opens with *opener*."""
    name, body = None, []
    for line in text.splitlines():
        if line.startswith(opener):
            if name is not None:
                yield name, body
            name, body = line[len(opener):].strip(), []
        elif name is not None:
            if line[:1] in (" ", "\t"):
                body.append(line.strip())
            else:
                yield name, body
                name, body = None, []
    if name is not None:
        yield name, body


#: The words that say whether a native VLAN is sent TAGGED, in the
#: ``switchport`` grammar: one line for every trunk of the config, at
#: the left margin, with ``exclude control`` after it or without; and
#: under an interface, one that says it of that trunk and one that
#: says it is not.
_EVERY_NATIVE_IS_TAGGED = re.compile(r"(?m)^vlan dot1q tag native(?: exclude control)?[ \t]*$")
_ITS_NATIVE_IS_TAGGED = "switchport trunk native vlan tag"
_ITS_NATIVE_IS_NOT = "no switchport trunk native vlan tag"
#: The platforms whose text has such words.
_SAYS_IT = frozenset({"cisco_iosxe_cli", "cisco_nxos", "arista_eos", "aruba_aoscx"})


def _unspaced(name: str) -> str:
    """An interface's name with its white space taken out, and the
    word AOS-CX writes after a LAG's name."""
    return re.sub(r"\s+", "", re.sub(r"\s+multi-chassis.*$", "", name))


def says_tagged(text: str, codec: str) -> tuple[bool, dict[str, bool]]:
    """(the text says every native VLAN is tagged, {interface: what
    its own lines say of its native VLAN, the last of them}), from a
    text of *codec*.  Names with their white space taken out.  An
    interface the dict does not name goes by the line for every
    trunk.

    By each platform's grammar, written here:

    * IOS-XE and NX-OS: ``switchport trunk native vlan tag`` says it
      of the port, and ``no switchport trunk native vlan tag`` says
      the port's native VLAN is NOT tagged, whatever the line for
      every trunk says.  A native VLAN's id is another statement, and
      says neither.
    * EOS: the id and ``tag`` are one argument of one line, and the
      line met last stands: an id says the port's native VLAN is not
      sent tagged.  (No line for every trunk is in EOS's VLAN pages;
      its parser reads the Cisco one as words, and so does this.  The
      ``no`` line is not read.)
    * AOS-CX: ``vlan trunk native N tag``.  What a later line
      without the word does to the tagging is not established: it is
      read as leaving the tagging on, because HPE documents the ``no``
      form as the way tagging is removed.  There is no line for every
      trunk.
    * Any other platform: none of it.
    """
    own: dict[str, bool] = {}
    if codec not in _SAYS_IT:
        return False, own
    for name, body in _stanzas(text, "interface "):
        key = _unspaced(name)
        for line in body:
            if codec == "aruba_aoscx":
                if re.fullmatch(r"vlan trunk native \d+ tag", line):
                    own[key] = True
            elif line == _ITS_NATIVE_IS_TAGGED:
                own[key] = True
            elif (line == _ITS_NATIVE_IS_NOT and codec != "arista_eos") or (
                codec == "arista_eos" and re.fullmatch(r"switchport trunk native vlan \d+", line)
            ):
                own[key] = False
    every = codec != "aruba_aoscx" and _EVERY_NATIVE_IS_TAGGED.search(text) is not None
    return every, own


#: What a reader of OS10 TEXT gives a trunk that has neither an access
#: line nor ``no switchport access vlan``: its switch's default VLAN,
#: untagged, by default ("By default, native VLAN of a port is the
#: default VLAN ID of the switch."; the vendor reference).  Which id
#: that is no text gives: the reader names it so, and no tree holds it.
THE_SWITCHS_DEFAULT = NO_ID


def _read_switchport(text: str, codec: str) -> dict[str, Port]:
    """IOS-XE, EOS, NX-OS and OS10.  On OS10 the untagged VLAN of a
    trunk is its ``switchport access vlan``, which ``no switchport
    access vlan`` takes back; a trunk with neither line is an untagged
    member of the switch's default VLAN (:data:`THE_SWITCHS_DEFAULT`,
    by default).  On the other three a trunk with no native line has
    the platform's own, unless the text says the native VLAN is
    tagged.  A stanza that is in the text twice is one interface: its
    lines are applied in the order they are met.  A trunk whose
    native VLAN is sent tagged (:func:`says_tagged`) carries none
    untagged, the one it states included."""
    every_tagged, own_tagged = says_tagged(text, codec)
    stated: dict[str, tuple[Any, Any, Any, Any, bool]] = {}
    for name, body in _stanzas(text, "interface "):
        mode, access, native, allowed, taken_back = stated.get(name, (None, None, None, None, False))
        for line in body:
            if line in ("switchport mode trunk", "switchport mode access"):
                mode = line.rsplit(" ", 1)[1]
            elif m := re.fullmatch(r"switchport access vlan (\d+)", line):
                access, taken_back = int(m.group(1)), False
            elif line == "no switchport access vlan":
                access, taken_back = None, True
            elif m := re.fullmatch(r"switchport trunk native vlan (\d+)", line):
                native = int(m.group(1))
            elif m := re.fullmatch(r"switchport trunk allowed vlan (add )?(\S+)", line):
                word = m.group(2)
                more = frozenset() if word == "none" else ALL if word == "all" else _ids(word)
                if ALL in (more, allowed):
                    allowed = ALL
                else:
                    allowed = _listed(more | (allowed or set()) if m.group(1) else more)
        stated[name] = (mode, access, native, allowed, taken_back)
    out: dict[str, Port] = {}
    for name, (mode, access, native, allowed, taken_back) in stated.items():
        if mode is None and access is not None:
            mode = "access"            # EOS, NX-OS and OS10 print no mode line for one
        default = _default_native(codec)
        if codec == "dell_os10":
            if mode == "trunk":
                native, allowed = access, allowed if allowed is not None else frozenset()
                default = None if taken_back else THE_SWITCHS_DEFAULT
        elif allowed is None:
            allowed = ALL
        tagged = own_tagged.get(_unspaced(name), every_tagged)
        if tagged and mode == "trunk":
            native = None
        port = _port(HOW_IT_IS_STATED[codec], mode, access, native, allowed, None if tagged else default)
        if port is not None:
            out[name] = port
    return out


def _read_aoscx(text: str) -> dict[str, Port]:
    """AOS-CX: a ``vlan trunk`` line says the port is a trunk, and a
    trunk with no native line has VLAN 1.  ``vlan trunk native N tag``
    sends the native VLAN tagged: the trunk carries none untagged."""
    _every, tagged = says_tagged(text, "aruba_aoscx")
    out: dict[str, Port] = {}
    for name, body in _stanzas(text, "interface "):
        name = re.sub(r"\s+multi-chassis.*$", "", name)
        access = native = None
        allowed: Any = None
        trunk = False
        for line in body:
            if m := re.fullmatch(r"vlan access (\d+)", line):
                access = int(m.group(1))
            elif m := re.fullmatch(r"vlan trunk native (\d+)(?: tag)?", line):
                native, trunk = int(m.group(1)), True
            elif m := re.fullmatch(r"vlan trunk allowed (\S+)", line):
                trunk = True
                allowed = ALL if m.group(1) == "all" else _listed(_ids(m.group(1)))
        mode = "trunk" if trunk else "access" if access is not None else None
        sent_tagged = tagged.get(_unspaced(name), False)
        port = _port(
            LIST, mode, access, None if sent_tagged else native, allowed if allowed is not None else ALL,
            None if sent_tagged else _default_native("aruba_aoscx"),
        )
        if port is not None:
            out[name] = port
    return out


def _read_junos(text: str) -> dict[str, Port]:
    vlan_id: dict[str, int] = {}
    mode: dict[str, str] = {}
    members: dict[str, list[str]] = collections.defaultdict(list)
    native: dict[str, int] = {}
    switching = r"set interfaces (\S+) unit 0 family ethernet-switching "
    for line in text.splitlines():
        if m := re.fullmatch(r'set vlans ("[^"]*"|\S+) vlan-id (\d+)', line):
            vlan_id[m.group(1).strip('"')] = int(m.group(2))
        elif m := re.fullmatch(switching + r"(?:interface-mode|port-mode) (\S+)", line):
            mode[m.group(1)] = m.group(2)
        elif m := re.fullmatch(switching + r"vlan members (.+)", line):
            words = re.findall(r'"[^"]*"|\S+', m.group(2).strip("[] "))
            members[m.group(1)].extend(word.strip('"') for word in words)
        elif m := re.fullmatch(r"set interfaces (\S+) native-vlan-id (\d+)", line):
            native[m.group(1)] = int(m.group(2))
    out: dict[str, Port] = {}
    for name in set(mode) | set(members):
        ids: set[int] = set()
        every = False
        for word in members.get(name, []):
            if word == "all":
                every = True
            elif re.fullmatch(r"\d+(-\d+)?", word):
                ids |= _ids(word)
            else:
                ids.add(vlan_id.get(word, -1))    # -1: a name the output declares no VLAN for
        if mode.get(name) == "trunk":
            port = _port(LIST, "trunk", None, native.get(name), ALL if every else _listed(ids))
        else:
            port = _port(LIST, "access", next(iter(ids), None), None, frozenset())
        if port is not None:
            out[name] = port
    return out


def _aoss_ports(listed: str) -> list[str]:
    """``1-3,1/1-1/4,A1-A2,Trk1``: a range runs over the last number of
    its two ends, which share everything before it."""
    out: list[str] = []
    for part in listed.replace(" ", "").split(","):
        m = re.fullmatch(r"(.*?)(\d+)-(.*?)(\d+)", part)
        if m and m.group(1) == m.group(3):
            out.extend(f"{m.group(1)}{n}" for n in range(int(m.group(2)), int(m.group(4)) + 1))
        elif part:
            out.append(part)
    return out


def _read_aoss(text: str) -> dict[str, Port]:
    """AOS-S, VLAN by VLAN: a port is untagged in the VLAN whose
    ``untagged`` line names it last, and ``no untagged`` takes back an
    ``untagged`` above it in the same VLAN.  A port that is tagged
    somewhere, untagged nowhere, and on no line of VLAN 1 -- not
    ``untagged``, not ``tagged``, not ``no untagged`` -- is in VLAN 1
    by default ("Any ports not specifically removed from the default
    VLAN remain in the DEFAULT_VLAN, regardless of other port
    assignments.").  HPE's sentence says "in", not which way; it is
    read here as untagged, which is where the full configs of HPE's
    guides put a port that is in VLAN 1 and not tagged there.  A name
    in no VLAN's list is no port here."""
    untagged: dict[str, int] = {}     # a port is untagged in ONE VLAN: the last that says so
    tagged: dict[str, set[int]] = collections.defaultdict(set)
    on_vlan_1: set[str] = set()       # on a line of VLAN 1, any of the three
    for name, body in _stanzas(text, "vlan "):
        if not name.isdigit():
            continue
        vid = int(name)
        for line in body:
            if m := re.fullmatch(r"(tagged|untagged) (\S+)", line):
                for port in _aoss_ports(m.group(2)):
                    if m.group(1) == "tagged":
                        tagged[port].add(vid)
                    else:
                        untagged[port] = vid
                    if vid == 1:
                        on_vlan_1.add(port)
            elif m := re.fullmatch(r"no untagged (\S+)", line):
                for port in _aoss_ports(m.group(1)):
                    if untagged.get(port) == vid:
                        del untagged[port]
                    if vid == 1:
                        on_vlan_1.add(port)
    out: dict[str, Port] = {}
    for name in set(untagged) | set(tagged):
        if name not in untagged and name not in on_vlan_1:
            out[name] = Port(1, None, frozenset(tagged[name]), True)
        else:
            out[name] = Port(untagged.get(name), None, frozenset(tagged.get(name, ())))
    return out


def out_of_vlan_1(text: str) -> set[str]:
    """The ports an AOS-S output names on a ``no untagged`` line of
    VLAN 1's stanza, as it writes them.  Read from the text."""
    found: set[str] = set()
    for name, body in _stanzas(text, "vlan "):
        if name == "1":
            for line in body:
                if m := re.fullmatch(r"no untagged (\S+)", line):
                    found.update(_aoss_ports(m.group(1)))
    return found


#: The ``; review:`` line of an AOS-S output for a trunk whose list
#: leaves its native VLAN out, WHOLE, in its three forms.  Typed here
#: and taken from no renderer, so that a line which says a word more
#: is not this line.  Where the output's VLAN 1 stanza takes the name
#: out of VLAN 1 (``no untagged``), the line says so, and no more.
#: Otherwise it says what HPE's sentences say: for a port, that it is
#: in the default VLAN and remains in it until it is removed (neither
#: sentence says "untagged"); for a trunk group and for a port that is
#: in one, that a new trunk group is placed in the default VLAN, a
#: static one is configured for VLAN membership as a port is, and a
#: port in one is configured at the group.  None calls the VLAN the
#: source's: after a VLAN map the id is the output's.
SAID_TAKEN_OUT = (
    "; review: port {port} -- native VLAN {native} is stated for this trunk and its allowed list leaves it out, "
    "so no untagged line is written for this port and it is taken out of the default VLAN -- check what this port "
    "is to carry untagged"
)
SAID_OF_A_PORT = (
    "; review: port {port} -- native VLAN {native} is stated for this trunk and its allowed list leaves it out, "
    "so no untagged line is written for this port; in the factory default configuration an AOS-S port is in the "
    "default VLAN (VID 1), and it remains there until it is removed -- check what this port is to carry untagged"
)
SAID_OF_A_GROUP = (
    "; review: port {port} -- native VLAN {native} is stated for this trunk and its allowed list leaves it out, "
    "so no untagged line is written for this port; a new AOS-S trunk group is placed in the default VLAN (VID 1), "
    "a static one is configured for VLAN membership as a port is, and the VLANs of a port that is in one are the "
    "group's -- check what this port is to carry untagged"
)

#: ...and the line of an OS10 output, which stands above ``no
#: switchport access vlan``.  It says that Dell's pages DISAGREE on
#: what that line leaves a trunk with, and names both readings.
SAID_ON_OS10 = (
    "! review: native VLAN {native} is stated for this trunk and its allowed list leaves it out, so no untagged "
    "VLAN is written for this port; Dell's pages disagree on whether the next line leaves an OS10 trunk with no "
    "untagged VLAN or with VLAN 1 -- check what this port is to carry untagged"
)

#: ...and the line of an OS10 output above ``no switchport access
#: vlan`` for a trunk that has NO native VLAN: it carries none
#: untagged.  WHOLE, typed here: what an OS10 trunk with neither line
#: is (Dell's sentence), that Dell's pages disagree on what the next
#: line leaves it with, and -- where the allowed line written below it
#: holds VLAN 1 -- that no Dell page shows VLAN 1 there.
SAID_OF_NONE_ON_OS10 = (
    "! review: no untagged VLAN is stated for this trunk; an OS10 trunk with neither an access line nor the next "
    "line is an untagged member of the switch's default VLAN, and Dell's pages disagree on whether the next line "
    "leaves it with no untagged VLAN or with VLAN 1{vlan_1} -- check what this port is to carry untagged"
)
_VLAN_1_ON_OS10 = "; no Dell page shows VLAN 1 on an OS10 trunk's allowed line"


def said_of_none_on_os10(vlan_1: bool) -> str:
    """:data:`SAID_OF_NONE_ON_OS10`, for an allowed line that holds
    VLAN 1 (*vlan_1*) or does not."""
    return SAID_OF_NONE_ON_OS10.format(vlan_1=_VLAN_1_ON_OS10 if vlan_1 else "")


PORT_FORM, GROUP_FORM = "a port", "a trunk group or a port of one"
TAKEN_OUT_FORM = "a name the output takes out of VLAN 1"
_FORMS = ((PORT_FORM, SAID_OF_A_PORT), (GROUP_FORM, SAID_OF_A_GROUP), (TAKEN_OUT_FORM, SAID_TAKEN_OUT))

_A_REVIEW_OF_A_PORT = re.compile(r"; review: port (.+?) -- native VLAN (\d+) ")


def said_how(text: str) -> list[tuple[str, int, str, str | None]]:
    """(the stanza it stands in, VLAN, port name as written, form)
    for every ``; review: port`` line in a VLAN stanza of an AOS-S
    output.  The form is :data:`PORT_FORM` or :data:`GROUP_FORM`
    where the WHOLE line is that form's text for that port and VLAN,
    and ``None`` for a line that is neither."""
    found: list[tuple[str, int, str, str | None]] = []
    for name, body in _stanzas(text, "vlan "):
        for line in body:
            m = _A_REVIEW_OF_A_PORT.match(line)
            if m is None:
                continue
            port, native = m.group(1), int(m.group(2))
            form = next((form for form, whole in _FORMS if line == whole.format(port=port, native=native)), None)
            found.append((name, native, port, form))
    return found


def said_on_aoss(text: str) -> dict[tuple[int, str], int]:
    """(VLAN, port name as written) -> how many ``; review:`` lines of
    an AOS-S output say that the port's trunk states that VLAN as its
    native VLAN and leaves it out of its allowed list.  Only a line
    that is WHOLE one of the two forms counts, and only in the stanza
    of THAT VLAN: it is where an operator looks for the port's
    ``untagged`` line."""
    found: collections.Counter[tuple[int, str]] = collections.Counter()
    for name, native, port, form in said_how(text):
        if form is not None and name == str(native):
            found[(native, port)] += 1
    return dict(found)


def in_a_trunk_line(text: str) -> set[str]:
    """The ports an AOS-S output names on its ``trunk`` lines
    (``trunk 1-2 trk1 lacp``): the members of the trunk groups it
    makes.  Read from the text."""
    found: set[str] = set()
    for line in text.splitlines():
        m = re.fullmatch(r"trunk (\S+) \S+(?: \S+)?", line)
        if m:
            found.update(_aoss_ports(m.group(1)))
    return found


#: The review line of an IOS-XE and of an NX-OS output for a trunk
#: that carries no VLAN untagged and whose list holds VLAN 1, in an
#: output that does not say ``vlan dot1q tag native``: WHOLE, typed
#: here and taken from no renderer.  What it says of the switch is
#: Cisco's (the vendor reference): a trunk with no native line has
#: native VLAN 1 (on NX-OS: the default VLAN, which is VLAN1), and the
#: line that would tag it does so for every trunk.  It does not call
#: the port's lack of an untagged VLAN the source's: after a VLAN map
#: it can be the map's.
SAID_OF_NO_UNTAGGED = {
    "cisco_iosxe_cli": (
        "! review: this trunk carries no VLAN untagged in the translated config; on IOS-XE a trunk with no native "
        "line has native VLAN 1, and this one's allowed list holds VLAN 1; vlan dot1q tag native would tag it, and "
        "tags the native VLAN of every 802.1Q trunk of the switch -- check what this port is to carry untagged"
    ),
    "cisco_nxos": (
        "! review: this trunk carries no VLAN untagged in the translated config; on NX-OS a trunk with no native "
        "line uses the default VLAN, VLAN 1, and this one's allowed list holds VLAN 1; vlan dot1q tag native would "
        "tag it, and changes the native VLAN of every trunk of the device -- check what this port is to carry "
        "untagged"
    ),
}
_A_REVIEW_OF_NO_UNTAGGED = "! review: this trunk carries no VLAN untagged"


def said_of_no_untagged(text: str, codec: str) -> dict[str, list[list[bool]]]:
    """Interface (white space out) -> for each of its stanzas, and for
    each line of that stanza that is, or begins as, the review line
    for a trunk that carries no VLAN untagged: whether it is that
    line, WHOLE, for *codec*.  (A name whose stanza is in the output
    twice -- ports a job lists as fused -- has a list for each.)"""
    whole = SAID_OF_NO_UNTAGGED.get(codec)
    found: dict[str, list[list[bool]]] = {}
    for name, body in _stanzas(text, "interface "):
        found.setdefault(_unspaced(name), []).append(
            [line == whole for line in body if line.startswith(_A_REVIEW_OF_NO_UNTAGGED)],
        )
    return found


_A_NATIVE_LEFT_OUT_ON_OS10 = re.compile(r"! review: native VLAN (\d+) is stated for this trunk ")


def unsaid_on_os10(text: str) -> tuple[int, list[str]]:
    """(how many ``no switchport access vlan`` lines of an OS10 output
    stand under their review line, whole; the interfaces of those that
    do not).  The line above is :data:`SAID_ON_OS10` for the native
    VLAN it names, or :func:`said_of_none_on_os10` for an allowed line
    of the stanza that holds VLAN 1 or does not."""
    said, unsaid = 0, []
    for name, body in _stanzas(text, "interface "):
        holds_1 = any(
            1 in _ids(line.rsplit(" ", 1)[1]) for line in body if line.startswith("switchport trunk allowed vlan ")
        )
        for at, line in enumerate(body):
            if line != "no switchport access vlan":
                continue
            above = body[at - 1] if at else ""
            native = _A_NATIVE_LEFT_OUT_ON_OS10.match(above)
            whole = (
                SAID_ON_OS10.format(native=native.group(1)) if native else said_of_none_on_os10(holds_1)
            )
            if above == whole:
                said += 1
            else:
                unsaid.append(name)
    return said, unsaid


def is_a_trunk_group(name: str) -> bool:
    """``Trk1``, in any letter case: the name AOS-S has for a LAG."""
    return re.fullmatch(r"trk\d+", name, re.IGNORECASE) is not None


def on_both_lines(text: str) -> list[str]:
    """The trunks of an OS10 text that name one VLAN on the access
    line and on the allowed line.  An OS10 allowed line names tagged
    VLANs: the two memberships are not one port's at once."""
    found: list[str] = []
    for name, body in _stanzas(text, "interface "):
        if "switchport mode trunk" not in body:
            continue
        access = [int(line.rsplit(" ", 1)[1]) for line in body if re.fullmatch(r"switchport access vlan \d+", line)]
        allowed = set().union(*(
            _ids(line.rsplit(" ", 1)[1]) for line in body if line.startswith("switchport trunk allowed vlan ")
        ))
        if set(access) & allowed:
            found.append(name)
    return found


def read_text(text: str, codec: str) -> dict[str, Port]:
    """Port name -> what the device of *codec* carries on it, from the
    text of an output."""
    if codec == "aruba_aoscx":
        return _read_aoscx(text)
    if codec == "aruba_aoss":
        return _read_aoss(text)
    if codec == "juniper_junos":
        return _read_junos(text)
    return _read_switchport(text, codec)


# ---------------------------------------------------------------------------
# One job, judged
# ---------------------------------------------------------------------------

LOST = "lost by the list"
GAINED = "gained by the list"
TAGGED_INSTEAD = "tagged in the output"
WAS_TAGGED = "was tagged on the source"
ANOTHER = "another untagged VLAN, or none"
NOT_THE_SAME = (LOST, GAINED, TAGGED_INSTEAD, WAS_TAGGED, ANOTHER)
NOT_FILLED = "the platform's default native VLAN is not in the tree"
NOT_OWED = "the platform's default native VLAN is in the tree, and the port does not say it is a trunk"
KEPT_TAGGED = "the text says the port's native VLAN is sent tagged, and the tree has a native VLAN"
TARGETS_DEFAULT = "untagged by the target's own default"
DEFAULT_SAID = "left to the target's default, and said"
DEFAULT_NOT_SAID = "untagged by the target's own default, and no review line, whole, says so"
NO_FORM_WRITTEN = "untagged by the target's own default, on a target that has a form for none"
SAID_OF_ANOTHER = "a review line for no untagged VLAN on a port that is not left to the default"
BOTH_LINES = "a VLAN on the access line and on the allowed line"
SAID_ON_OS10_WHOLE = "`no switchport access vlan` under its review line, whole"
UNSAID_ON_OS10 = "`no switchport access vlan` under no review line, whole"
ON_NO_VLAN_LINE = "a trunk that carries no VLAN untagged, on no VLAN line of the AOS-S output"
NONE_ON_BOTH = "a trunk that states no native VLAN, and carries none untagged on both sides"
SAID = "left out, and said on AOS-S"
NOT_SAID = "left out of its list, and the AOS-S output does not say so"
NOT_THE_LINE = "a review line that is neither form of the line, whole"
WRONG_FORM = "the output makes it"


def judge(source: Any, target: Any, raw: str, job: Any) -> dict[str, Any]:
    """What became, in *job*'s output, of the untagged VLAN of every
    port the source tree of *raw* states.  Counts, and a sentence for
    each thing that may not be."""
    assert job.rendered is not None, f"nothing rendered: {job.error}"
    fold = not target.port_names_case_sensitive

    def key(name: str) -> str:
        name = re.sub(r"\s+", "", name)
        return name.casefold() if fold else name

    source_tree, output_tree = source.parse(raw), target.parse(job.rendered)
    src = read_tree(source_tree, source.name)
    by_parser = {key(name): port for name, port in read_tree(output_tree, target.name).items()}
    by_text = {key(name): port for name, port in read_text(job.rendered, target.name).items()}
    tally: collections.Counter[str] = collections.Counter()
    wrong: list[str] = []
    # A tree a parser made holds its platform's default for a trunk
    # that says it is one, and for no other port: the source's, and
    # the output's when it is parsed again.
    unfilled, unowed, kept = _defaults_misplaced((
        ("the source", source_tree, raw, source.name), ("the output", output_tree, job.rendered, target.name),
    ))
    tally += collections.Counter({   # (adds nothing for none)
        NOT_FILLED: len(unfilled), NOT_OWED: len(unowed), KEPT_TAGGED: len(kept),
    })
    wrong.extend(unfilled + unowed + kept)
    both = on_both_lines(job.rendered) if target.name == "dell_os10" else []
    tally += collections.Counter({BOTH_LINES: len(both)})
    wrong.extend(f"interface {name}: {BOTH_LINES}" for name in both)
    if target.name == "dell_os10":
        # Every `no switchport access vlan` of an OS10 output stands
        # under its review line, whole: Dell's pages disagree on what
        # it leaves a trunk with.
        said_os10, unsaid = unsaid_on_os10(job.rendered)
        tally += collections.Counter({SAID_ON_OS10_WHOLE: said_os10})
        wrong.extend(f"interface {name}: {UNSAID_ON_OS10}" for name in unsaid)
    for name in sorted(set(by_parser) | set(by_text)):
        one, two = by_parser.get(name), by_text.get(name)
        if (one and (one.untagged, one.left_out)) != (two and (two.untagged, two.left_out)):
            tally["readings disagree"] += 1
            wrong.append(f"{name!r}: the parser reads {one} and the text {two}")

    dropped = set(job.port_drops)
    fused = {name for names in job.fused_ports.values() for name in names}
    if target.name in VLAN_BY_VLAN:
        _said_on_aoss_as_it_should_be(src, job, key, dropped, tally, wrong)
    # On IOS-XE and NX-OS a port left to the default has a review line
    # in its stanza, whole, and no other port has one.
    reviewed = {key(name): lines for name, lines in said_of_no_untagged(job.rendered, target.name).items()}
    left_to_it: set[str] = set()
    trunks = {iface.name for iface in source_tree.interfaces if iface.switchport_mode == "trunk"}
    for name, had in sorted(src.items()):
        if name in dropped:
            tally["dropped by the job"] += 1
            continue
        final = job.port_renames.get(name, name)
        has = by_text.get(key(final))
        if has is None:
            tally["nothing stated for the port"] += 1
            if target.name in VLAN_BY_VLAN and name in trunks and had.untagged is None:
                # A trunk that carries no VLAN untagged, on no VLAN line
                # of an AOS-S output: AOS-S has no form for a port in
                # no VLAN.  Counted, and pinned cell by cell.
                tally[ON_NO_VLAN_LINE] += 1
            continue
        if had.untagged == has.untagged:
            tally["the same"] += 1
            if had.untagged is not None:
                tally["carried by both"] += 1
            elif had.left_out is not None:
                tally["left out, and not carried"] += 1
            elif name in trunks:
                tally[NONE_ON_BOTH] += 1
            continue
        if had.untagged is None and has.by_default:
            # The source carries no VLAN untagged on this port; the
            # output states none either, and its platform's default
            # makes one of a VLAN its list holds.  On IOS-XE and NX-OS,
            # in an output that cannot say so of every trunk, that is
            # what is written -- under a review line in the port's own
            # stanza.  Counted, and pinned cell by cell.  On a target
            # with a form for "no VLAN untagged", it is a fault.
            tally[TARGETS_DEFAULT] += 1
            left_to_it.add(key(final))
            fault = _left_to_the_default(target.name, reviewed.get(key(final), []), tally)
            if fault:
                wrong.append(f"VLAN {has.untagged} untagged on {name!r} ({final!r}){fault}")
            continue
        kinds: list[tuple[str, int]] = []
        if had.untagged is not None:
            vid = had.untagged
            kinds.append((
                LOST if has.left_out == vid else TAGGED_INSTEAD if has.carries_tagged(vid) else ANOTHER, vid,
            ))
        if has.untagged is not None:
            vid = has.untagged
            kinds.append((
                GAINED if had.left_out == vid else WAS_TAGGED if had.carries_tagged(vid) else ANOTHER, vid,
            ))
        for kind, vid in kinds:
            tally[kind] += 1
            if name in fused:
                tally["on a fused port"] += 1
            else:
                wrong.append(f"VLAN {vid} untagged on {name!r} ({final!r}): {kind}")
    wrong.extend(
        f"{port!r}: {SAID_OF_ANOTHER}" for port, stanzas in sorted(reviewed.items())
        if any(stanzas) and port not in left_to_it
    )
    return {"tally": tally, "wrong": wrong, "status": job.status.value}


def _said_on_aoss_as_it_should_be(
    src: dict[str, Port], job: Any, key: Any, dropped: set[str], tally: collections.Counter[str], wrong: list[str],
) -> None:
    """Onto AOS-S, a native VLAN the source's list leaves out is said:
    one line, in that VLAN's stanza, for each port the output has.  (A
    port the job dropped for want of a name is not in the output, and
    the job lists it.)  *key* folds a name as the judgement does."""
    said = {(vid, key(port)): count for (vid, port), count in said_on_aoss(job.rendered).items()}
    asked: set[tuple[int, str]] = set()
    for name, had in sorted(src.items()):
        if had.left_out is None or name in dropped or name in job.unresolved_ports:
            continue
        where = (had.left_out, key(job.port_renames.get(name, name)))
        asked.add(where)
        if said.get(where, 0) == 1:
            tally[SAID] += 1
        else:
            wrong.append(f"native VLAN {had.left_out} of {name!r}, {said.get(where, 0)} lines: {NOT_SAID}")
    for vid, port in sorted(set(said) - asked):
        wrong.append(
            f"VLAN {vid}, port {port!r}: {said[(vid, port)]} review lines for a port whose source left nothing out"
        )
    # ... and each line is one of the three forms, whole, and the form
    # for what the OUTPUT makes of the name: one its VLAN 1 stanza
    # takes out of VLAN 1, by that stanza's `no untagged` line; a trunk
    # group by its name, a port of one by the output's own `trunk`
    # lines.  (The renderer decides it from the tree.)
    grouped = {key(port) for port in in_a_trunk_line(job.rendered)}
    taken_out = {key(port) for port in out_of_vlan_1(job.rendered)}
    for _stanza, vid, port, form in said_how(job.rendered):
        want = (
            TAKEN_OUT_FORM if key(port) in taken_out
            else GROUP_FORM if is_a_trunk_group(port) or key(port) in grouped else PORT_FORM
        )
        if form is None:
            wrong.append(f"VLAN {vid}, port {port!r}: {NOT_THE_LINE}")
        elif form != want:
            wrong.append(f"VLAN {vid}, port {port!r}: the line is the one for {form}, and {WRONG_FORM} {want}")
        else:
            tally[f"said in the form for {form}"] += 1


def _left_to_the_default(target: str, stanzas: list[list[bool]], tally: collections.Counter[str]) -> str:
    """What is wrong with a port of an output of *target* that is left
    to the target's default, where its source carries no VLAN untagged:
    ``""`` for nothing.  *stanzas* is the port's in that output
    (:func:`said_of_no_untagged`).  On IOS-XE and NX-OS each stanza of
    it has the review line, once and whole; on another target, that
    has a form for no VLAN untagged, there is no such port."""
    if target not in SAID_OF_NO_UNTAGGED:
        return f": {NO_FORM_WRITTEN}"
    if stanzas and all(lines == [True] for lines in stanzas):
        tally[DEFAULT_SAID] += 1
        return ""
    return f", {sum(len(lines) for lines in stanzas)} lines: {DEFAULT_NOT_SAID}"


def _run(source: str, target: str, raw: str, port_map: dict | None = None) -> Any:
    return run_plan_with_checked_names(
        get_codec(source), get_codec(target), raw, port_rename_map=dict(port_map or {}),
    )


# ---------------------------------------------------------------------------
# 1. Every committed capture onto every target that states memberships
# ---------------------------------------------------------------------------

_NOT_A_CAPTURE = {".md", ".json", ".yaml", ".yml", ".py"}


def _captures() -> list[tuple[str, str, Path]]:
    """(codec, path under tests/fixtures, path) for every committed
    capture of a public codec."""
    found: list[tuple[str, str, Path]] = []
    for root in ("real", "synthetic", "iosxe", "opnsense"):
        for path in sorted(p for p in (FIXTURES / root).rglob("*") if p.is_file()):
            if path.suffix.lower() in _NOT_A_CAPTURE:
                continue
            parts = path.relative_to(FIXTURES).parts
            label = parts[1] if root in ("real", "synthetic") else {"iosxe": "cisco_iosxe"}.get(root, root)
            codec = DIR_TO_CODEC_NAME.get(label, label)
            if label == "cisco_iosxe" and path.suffix.lower() == ".xml":
                codec = "cisco_iosxe"   # the NETCONF codec shares the directory
            if codec in list_public_codecs():
                found.append((codec, "/".join(parts), path))
    return found


EVERY_CAPTURE = _captures()
#: The captures of the codecs whose parser states memberships: a
#: capture of any other has no untagged VLAN to lose.
CAPTURES = [capture for capture in EVERY_CAPTURE if capture[0] in SWITCHES]

#: (capture, target) -> the differences found on ports the job LISTS
#: as fused: several source ports written under one name of the
#: output, which is then one port with one untagged VLAN and cannot be
#: each of them.  Such a job is ``partial`` and names the ports.
#:
#: One capture has them.  A Catalyst's ``TenGigabitEthernet1/0/1`` is
#: a trunk that states no native VLAN and names VLANs 1 and 11 on its
#: list, so it carries VLAN 1 untagged and VLAN 11 tagged; its
#: ``FortyGigabitEthernet1/1/1`` is a trunk whose native VLAN is 11.
#: Three targets have one name for the two (and for ``1/0/2`` and
#: ``1/1/2``), and the port read back under it carries VLAN 11
#: untagged.  For the first of each pair that is two differences: its
#: own untagged VLAN 1 is tagged there or not stated, and VLAN 11
#: "was tagged on the source".  A naming fault the job reports, and
#: not the list's: no VLAN is lost or gained BY THE LIST on these
#: ports either (the first test below).  Not excused wholesale:
#: compared for EQUALITY with what is measured, so the change that
#: settles those names empties this.
ON_A_FUSED_PORT: dict[tuple[str, str], int] = {
    ("real/cisco_iosxe/user_contrib_cat9300_iosxe1712.txt", "arista_eos"): 4,
    ("real/cisco_iosxe/user_contrib_cat9300_iosxe1712.txt", "aruba_aoscx"): 4,
    ("real/cisco_iosxe/user_contrib_cat9300_iosxe1712.txt", "dell_os10"): 4,
}


#: (capture, target) -> the ports that carry NO VLAN untagged on the
#: source and carry VLAN 1 untagged in the output, by the target's own
#: default: a trunk written with no native line beside a list that
#: holds VLAN 1, for a platform whose trunk then has native VLAN 1.
#:
#: Only on IOS-XE and NX-OS, and only under the review line, which
#: the judgement holds whole.  Their one form for such a trunk on the
#: Catalyst 9300 and the Nexus 9000 is ``vlan dot1q tag native``, a
#: line for every trunk of the switch, and these outputs have another
#: trunk that carries a VLAN untagged.  Each is an AOS-CX LAG of
#: ``vlan trunk native 1 tag`` beside ``vlan trunk allowed all``, in
#: a config whose other trunks state ``vlan trunk native 1``.  (The
#: two Junos captures with trunks of ``vlan members all`` and no
#: ``native-vlan-id``, and the two other AOS-CX ones, have no such
#: trunk: they are written the line.)  Compared for EQUALITY with
#: what is measured.
BY_THE_TARGETS_DEFAULT: dict[tuple[str, str], int] = {
    ("real/aruba_aoscx/canu_csm17_spine001_ipv6_vrf.cfg", "cisco_iosxe_cli"): 1,
    ("real/aruba_aoscx/canu_csm17_spine001_ipv6_vrf.cfg", "cisco_nxos"): 1,
    ("real/aruba_aoscx/netutils_aoscx_snmpv3_glcx1009.cfg", "cisco_iosxe_cli"): 1,
    ("real/aruba_aoscx/netutils_aoscx_snmpv3_glcx1009.cfg", "cisco_nxos"): 1,
}

#: (capture, target) -> the source trunks that carry no VLAN untagged
#: and that the AOS-S output names on no VLAN line at all: a trunk
#: that carries nothing.  AOS-S has no form for a port in no VLAN (a
#: port is a member of at least one), so the output leaves it as it
#: is, and by HPE's sentence it stays in the DEFAULT_VLAN -- the one
#: cell of that class this target still has.  None on the committed
#: captures; a small config has one
#: (``TestTheCheckItself.test_a_trunk_of_nothing_onto_aoss``).
#: Compared for EQUALITY with what is measured.  (Onto OS10 every
#: trunk with no native VLAN is written ``no switchport access vlan``:
#: no cell, and the readers' default there counts zero.)
ON_NO_VLAN_LINE_OF_AOSS: dict[tuple[str, str], int] = {}


@pytest.fixture(scope="module")
def every_job() -> dict[tuple[str, str, str], dict[str, Any]]:
    """(source, capture, target) -> the judgement.  Made once in a
    process: under ``-n`` each worker that runs one of the tests below
    makes its own."""
    out: dict[tuple[str, str, str], dict[str, Any]] = {}
    for codec, label, path in CAPTURES:
        raw = path.read_text(encoding="utf-8")
        for target in SWITCHES:
            out[(codec, label, target)] = judge(get_codec(codec), get_codec(target), raw, _run(codec, target, raw))
    return out


def _shown(every_job: dict, limit: int = 10) -> str:
    """How many complaints there are, by pair and status, and the first."""
    by_pair: collections.Counter[tuple[str, str, str]] = collections.Counter()
    first: list[str] = []
    for (source, label, target), verdict in every_job.items():
        if verdict["wrong"]:
            by_pair[(source, target, verdict["status"])] += len(verdict["wrong"])
            if len(first) < limit:
                first.append(f"  {label} -> {target}: {verdict['wrong'][0]}")
    pairs = "\n".join(f"  {n:5d}  {s} -> {t} [{status}]" for (s, t, status), n in sorted(by_pair.items()))
    return f"{sum(by_pair.values())} in all\nby pair and status:\n{pairs}\nthe first:\n" + "\n".join(first)


def _total(every_job: dict, what: str, source: str | None = None, target: str | None = None) -> int:
    return sum(
        verdict["tally"][what] for (s, _label, t), verdict in every_job.items()
        if source in (None, s) and target in (None, t)
    )


def test_no_untagged_vlan_is_lost_or_gained(every_job: dict) -> None:
    assert not any(verdict["wrong"] for verdict in every_job.values()), _shown(every_job)
    # By the list, none at all: not on a fused port either.
    assert _total(every_job, LOST) == 0 and _total(every_job, GAINED) == 0


def test_what_a_targets_default_makes_is_pinned(every_job: dict) -> None:
    made = {
        (label, target): verdict["tally"][TARGETS_DEFAULT]
        for (_source, label, target), verdict in every_job.items()
        if verdict["tally"][TARGETS_DEFAULT]
    }
    assert made == BY_THE_TARGETS_DEFAULT
    # Only on the two targets whose one form is a line for every trunk,
    # each under its review line, and from AOS-CX alone.
    assert {target for _label, target in made} <= set(SAID_OF_NO_UNTAGGED)
    said = {
        (label, target): verdict["tally"][DEFAULT_SAID]
        for (_source, label, target), verdict in every_job.items() if verdict["tally"][DEFAULT_SAID]
    }
    assert said == made
    assert {
        source for (source, _label, _target), verdict in every_job.items() if verdict["tally"][TARGETS_DEFAULT]
    } == {"aruba_aoscx"}


def test_what_aoss_leaves_on_no_vlan_line_is_pinned(every_job: dict) -> None:
    """Onto OS10 and AOS-S the readers of text give a trunk with no
    form for "no VLAN untagged" its switch's default VLAN, and none is
    left to it (above).  What remains of the class is a trunk that
    carries nothing, which AOS-S has no form for."""
    left = {
        (label, target): verdict["tally"][ON_NO_VLAN_LINE]
        for (_source, label, target), verdict in every_job.items() if verdict["tally"][ON_NO_VLAN_LINE]
    }
    assert left == ON_NO_VLAN_LINE_OF_AOSS
    assert {target for _label, target in left} <= {"aruba_aoss"}


def test_no_tree_leaves_its_default_out(every_job: dict) -> None:
    """Not the source's tree and not the output's, parsed again: on
    every capture, onto every target.  And none has the default on
    a port that does not say it is a trunk."""
    assert _total(every_job, NOT_FILLED) == 0, _shown(every_job)
    assert _total(every_job, NOT_OWED) == 0, _shown(every_job)


def test_what_is_on_a_fused_port_is_pinned(every_job: dict) -> None:
    fused = {
        (label, target): verdict["tally"]["on a fused port"]
        for (_source, label, target), verdict in every_job.items()
        if verdict["tally"]["on a fused port"]
    }
    assert fused == ON_A_FUSED_PORT
    # ... and nowhere else does a port's untagged VLAN differ.
    assert sum(_total(every_job, kind) for kind in NOT_THE_SAME) == sum(ON_A_FUSED_PORT.values())


def test_os10_has_no_vlan_on_both_lines(every_job: dict) -> None:
    """From any source: the trunks whose list names their native VLAN
    are most of the trunks there are."""
    assert _total(every_job, BOTH_LINES) == 0
    assert _total(every_job, "carried by both", None, "dell_os10") > 200


def test_it_read_what_it_says_it_read(every_job: dict) -> None:
    """A loop that reads nothing passes every test above.  Each kind
    of trunk this module is for is among the captures, and reaches
    every target where the list decides -- carried by both."""
    assert len(every_job) == len(CAPTURES) * len(SWITCHES)
    assert {source for source, _label, _path in CAPTURES} == set(SWITCHES)
    assert _total(every_job, "the same") > 2_000
    where_the_list_decides = sorted(codec for codec, how in HOW_IT_IS_STATED.items() if how == LIST)
    for target in where_the_list_decides:
        for source in ("aruba_aoss", "dell_os10"):
            # (An access port is carried by both as well: these are
            # counts of ports, and each source has trunks among them.)
            assert _total(every_job, "carried by both", source, target) > 20, (source, target)
    # ... and a native VLAN the source leaves out of its list reaches
    # every target, the two that state it apart among them, and is
    # carried by none.
    for target in SWITCHES:
        assert _total(every_job, "left out, and not carried", None, target) >= 9, target
    # ... and onto AOS-S each of them is said, in the output, in
    # the form for what it is.  (Nine names of four outputs -- one
    # port, and eight trunk groups whose members AOS-S has no name
    # for, so that the output makes none of them; two more are ports
    # AOS-S has no name for, which the job drops and lists.  Each is
    # tagged in some VLAN, and the output takes it out of VLAN 1: the
    # forms that say it stays there are held on the shapes below.)
    assert _total(every_job, SAID) == _total(every_job, SAID, None, "aruba_aoss") >= 9
    assert _total(every_job, f"said in the form for {TAKEN_OUT_FORM}") >= 9
    # ... and the class the readers of OS10 and AOS-S text give their
    # switch's default VLAN to: trunks that carry no VLAN untagged,
    # which reach both, and none of which is left to that default.
    for target in ("dell_os10", "aruba_aoss"):
        assert _total(every_job, NONE_ON_BOTH, None, target) >= 50, target
        assert _total(every_job, TARGETS_DEFAULT, None, target) == 0, target
    # ... each written onto OS10 the line that takes its access VLAN
    # away, under its review line, whole.
    assert _total(every_job, SAID_ON_OS10_WHOLE, None, "dell_os10") >= 50


def test_the_captures_have_such_trunks() -> None:
    """Counted from the source trees, by each platform's row: trunks
    that carry an untagged VLAN on the two platforms that state it
    apart, and trunks that state a native VLAN their list leaves out
    on the others."""
    carried: collections.Counter[str] = collections.Counter()
    left_out: collections.Counter[str] = collections.Counter()
    for codec, _label, path in CAPTURES:
        tree = get_codec(codec).parse(path.read_text(encoding="utf-8"))
        trunks = {iface.name for iface in tree.interfaces if iface.switchport_mode == "trunk"}
        for name, port in read_tree(tree, codec).items():
            if name in trunks:
                carried[codec] += port.untagged is not None
                left_out[codec] += port.left_out is not None
    assert carried["aruba_aoss"] >= 8 and carried["dell_os10"] >= 29, dict(carried)
    assert left_out["aruba_aoscx"] >= 9 and left_out["arista_eos"] and left_out["cisco_nxos"], dict(left_out)
    assert not left_out["aruba_aoss"] and not left_out["dell_os10"], dict(left_out)


def _native_lines(codec: str, vid: int) -> list[tuple[str, str]]:
    """(capture, the line) for every line of a capture of *codec*
    that states *vid* as a trunk's native VLAN, read as text."""
    lead = "vlan trunk native" if codec == "aruba_aoscx" else "switchport trunk native vlan"
    return [
        (label, line.strip())
        for source, label, path in CAPTURES if source == codec
        for line in path.read_text(encoding="utf-8").splitlines()
        if re.fullmatch(rf"\s+{lead} {vid}(?: tag)?\s*", line)
    ]


def test_the_captures_state_no_native_vlan_too() -> None:
    """Counted from the TEXT of the captures, by a reader that knows no
    default, and held against the trees: trunks of the four platforms
    that state no native VLAN, with VLAN 1 on their list and without.
    Each of the first is a port its parser gives native VLAN 1, and
    each of the second is left with none.  Every one of them SAYS it
    is a trunk: no capture has a trunk its parser inferred, so the
    default reaches every trunk of the captures that is owed it."""
    with_one: collections.Counter[str] = collections.Counter()
    without: collections.Counter[str] = collections.Counter()
    trunks = said = 0
    for codec, _label, path in CAPTURES:
        if codec not in HAVE_A_DEFAULT:
            continue
        text = path.read_text(encoding="utf-8")
        # No capture has the Cisco words; four AOS-CX ones have `vlan
        # trunk native 1 tag`, a native line, which is skipped below.
        every, own = says_tagged(text, codec)
        assert not every and (codec == "aruba_aoscx" or not any(own.values())), path.name
        tree = get_codec(codec).parse(text)
        says = says_it_is_a_trunk(text, codec)
        for iface in tree.interfaces:
            if iface.switchport_mode != "trunk":
                continue
            trunks += 1
            said += _squeezed(iface.name) in says
            stanza = [body for name, body in _stanzas(text, "interface ") if "".join(name.split()) == iface.name]
            states = any(
                re.fullmatch(r"(switchport trunk native vlan|vlan trunk native) \d+( tag)?", line)
                for body in stanza for line in body
            )
            if not stanza or states:
                continue
            holds = 1 in iface.trunk_allowed_vlans
            (with_one if holds else without)[codec] += 1
            assert iface.trunk_native_vlan == (1 if holds else None), (path.name, iface.name)
    assert with_one["cisco_iosxe_cli"] >= 9 and with_one["cisco_nxos"] >= 3, dict(with_one)
    assert without["arista_eos"] >= 8 and without["cisco_nxos"] >= 9 and without["cisco_iosxe_cli"] >= 3, dict(without)
    # Every AOS-CX trunk of the captures states its native VLAN: none is among these.
    assert with_one["aruba_aoscx"] == without["aruba_aoscx"] == 0, (dict(with_one), dict(without))
    # (Found by its name in the text, every one: a name this module
    # read otherwise than the parser would be a trunk that "does not
    # say so", and the tree would be held to nothing for it.)
    assert trunks == said >= 90, (trunks, said)


def test_no_os10_capture_has_a_trunk_without_one() -> None:
    """What an OS10 trunk carries untagged when it states no access
    VLAN is the default VLAN of its switch, which nothing here fills
    in.  No committed capture has such a trunk: the day one does,
    this fails, and what it is read as has to be looked at."""
    trunks = bare = 0
    for codec, _label, path in CAPTURES:
        if codec != "dell_os10":
            continue
        for iface in get_codec(codec).parse(path.read_text(encoding="utf-8")).interfaces:
            if iface.switchport_mode == "trunk":
                trunks += 1
                bare += iface.trunk_native_vlan is None
    assert trunks >= 27 and bare == 0, (trunks, bare)


def test_who_prints_its_default_native_vlan() -> None:
    """What the renderers do with native VLAN 1 rests on this, and on
    nothing recalled.  No real capture of IOS-XE, NX-OS or EOS has a
    ``switchport trunk native vlan 1`` line (the two made-up fixtures
    that have one state it beside a list that leaves VLAN 1 out,
    which is a statement and no default); the AOS-CX captures print
    ``vlan trunk native 1`` on their trunks -- some ``vlan trunk native
    1 tag``, which sends it tagged and leaves the trunk no native VLAN
    in the tree.  And no real capture of
    IOS-XE or EOS has a ``vlan`` line that names VLAN 1, where every
    capture of NX-OS and of AOS-CX has one."""
    for codec in ("cisco_iosxe_cli", "cisco_nxos", "arista_eos"):
        stated = _native_lines(codec, 1)
        assert not [label for label, _line in stated if label.startswith("real/")], (codec, stated)
        for label, _line in stated:
            tree = get_codec(codec).parse((FIXTURES / label).read_text(encoding="utf-8"))
            assert [
                iface.name for iface in tree.interfaces
                if iface.trunk_native_vlan == 1 and 1 not in iface.trunk_allowed_vlans
            ], label
    assert len(_native_lines("aruba_aoscx", 1)) >= 28
    aoscx_trunks = [
        iface.trunk_native_vlan
        for codec, _label, path in CAPTURES if codec == "aruba_aoscx"
        for iface in get_codec(codec).parse(path.read_text(encoding="utf-8")).interfaces
        if iface.switchport_mode == "trunk"
    ]
    sent_tagged = [line for _label, line in _native_lines("aruba_aoscx", 1) if line.endswith(" tag")]
    assert len(aoscx_trunks) >= 30 and len(sent_tagged) >= 4, (len(aoscx_trunks), sent_tagged)
    assert collections.Counter(aoscx_trunks) == {
        1: len(aoscx_trunks) - len(sent_tagged), None: len(sent_tagged),
    }, collections.Counter(aoscx_trunks)
    names_one: collections.Counter[str] = collections.Counter()
    captures: collections.Counter[str] = collections.Counter()
    for codec, label, path in CAPTURES:
        if codec in HAVE_A_DEFAULT and label.startswith("real/"):
            captures[codec] += 1
            names_one[codec] += any(
                1 in _ids(m.group(1))
                for m in re.finditer(r"(?m)^vlan ([0-9,\- ]+?)\s*$", path.read_text(encoding="utf-8"))
            )
    assert names_one["cisco_iosxe_cli"] == names_one["arista_eos"] == 0, dict(names_one)
    for codec in ("cisco_nxos", "aruba_aoscx"):
        assert names_one[codec] == captures[codec] >= 6, (codec, dict(names_one), dict(captures))


# ---------------------------------------------------------------------------
# 2. Each shape, through every pair
# ---------------------------------------------------------------------------
#
# One trunk, one access port in VLAN 20, VLANs 10, 20 and 30 declared.
# Shapes of the six port-centric grammars: (a) native 10, and the list
# names it; (b) native 10, and the list leaves it out; (c) a list and
# no native VLAN; (d) native 10 and no list.  Of AOS-S: (e1) untagged
# in 10 and tagged in 20 and 30; (e2) tagged in 20 and 30; (e3)
# untagged in 10 alone.
#
# And the shapes of a trunk that states NO native VLAN, where the
# platform has a default (VLAN 1 is declared by none of them): (f) a
# list that names VLAN 1; (g) no trunk line at all, which is every
# VLAN -- on AOS-CX the one line `vlan trunk allowed all`; (h) the
# default written out, `native vlan 1` beside a list that names it;
# (i) native VLAN 1 beside a list that leaves it out; (t) the list
# of (f) under `switchport trunk native vlan tag`; (u) the same under
# `vlan dot1q tag native`; (x) under `vlan dot1q tag native exclude
# control`; (o) under `vlan dot1q tag native`, with the trunk's own
# `no switchport trunk native vlan tag`; (y) the lines of (a) under
# `vlan dot1q tag native`; (z) the lines of (a) and `switchport trunk
# native vlan tag`.  AOS-CX has (t) as `vlan trunk native 1 tag`
# beside the list of (f), (v) as `vlan trunk native 20 tag` beside
# it, and (w) as the same beside a list that leaves VLAN 1 out.
# Junos has (f) and (g) too, with VLAN 1 declared for (f), and AOS-S
# (e4), tagged in 1, 20 and 30: neither has a default, and each
# carries VLAN 1 TAGGED.


def _iosxe(*trunk: str) -> str:
    return "\n".join([
        "hostname sw1", "!",
        "vlan 10", " name ten", "!", "vlan 20", " name twenty", "!", "vlan 30", " name thirty", "!",
        "interface GigabitEthernet1/0/1", " switchport mode trunk", *(f" {line}" for line in trunk), "!",
        "interface GigabitEthernet1/0/2", " switchport mode access", " switchport access vlan 20", "!",
        "end", "",
    ])


def _eos(*trunk: str) -> str:
    return "\n".join([
        "hostname sw1", "!",
        "vlan 10", "   name ten", "!", "vlan 20", "   name twenty", "!", "vlan 30", "   name thirty", "!",
        "interface Ethernet1", "   switchport mode trunk", *(f"   {line}" for line in trunk), "!",
        "interface Ethernet2", "   switchport access vlan 20", "!",
        "end", "",
    ])


def _nxos(*trunk: str) -> str:
    return "\n".join([
        "hostname sw1", "",
        "vlan 10", "  name ten", "vlan 20", "  name twenty", "vlan 30", "  name thirty", "",
        "interface Ethernet1/1", "  switchport mode trunk", *(f"  {line}" for line in trunk), "",
        "interface Ethernet1/2", "  switchport access vlan 20", "",
    ])


def _os10(*trunk: str) -> str:
    return "\n".join([
        "hostname sw1", "!",
        "interface vlan10", " description ten", " no shutdown", "!",
        "interface vlan20", " description twenty", " no shutdown", "!",
        "interface vlan30", " description thirty", " no shutdown", "!",
        "interface ethernet1/1/1", " no shutdown", " switchport mode trunk", *(f" {line}" for line in trunk), "!",
        "interface ethernet1/1/2", " no shutdown", " switchport access vlan 20", "!",
        "",
    ])


def _aoscx(*trunk: str) -> str:
    return "\n".join([
        "hostname sw1",
        "vlan 10", "    name ten", "vlan 20", "    name twenty", "vlan 30", "    name thirty",
        "interface 1/1/1", "    no shutdown", "    no routing", *(f"    {line}" for line in trunk),
        "interface 1/1/2", "    no shutdown", "    no routing", "    vlan access 20",
        "",
    ])


def _junos(*trunk: str) -> str:
    return "\n".join([
        "set system host-name sw1",
        "set vlans ten vlan-id 10", "set vlans twenty vlan-id 20", "set vlans thirty vlan-id 30",
        "set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode trunk",
        *(f"set interfaces ge-0/0/1 {line}" for line in trunk),
        "set interfaces ge-0/0/2 unit 0 family ethernet-switching interface-mode access",
        "set interfaces ge-0/0/2 unit 0 family ethernet-switching vlan members twenty",
        "",
    ])


def _aoss(ten: tuple[str, ...], twenty: tuple[str, ...], thirty: tuple[str, ...]) -> str:
    return "\n".join([
        "; J9727A Configuration Editor; Created on release #WB.16.08.0001",
        'hostname "sw1"',
        "vlan 1", '   name "DEFAULT_VLAN"', "   no untagged 1-2", "   exit",
        "vlan 10", '   name "ten"', *(f"   {line}" for line in ten), "   exit",
        "vlan 20", '   name "twenty"', "   untagged 2", *(f"   {line}" for line in twenty), "   exit",
        "vlan 30", '   name "thirty"', *(f"   {line}" for line in thirty), "   exit",
        "",
    ])


_MEMBERS = "unit 0 family ethernet-switching vlan members"
_SWITCHPORT = {
    "a": ("switchport trunk native vlan 10", "switchport trunk allowed vlan 10,20,30"),
    "b": ("switchport trunk native vlan 10", "switchport trunk allowed vlan 20,30"),
    "c": ("switchport trunk allowed vlan 20,30",),
    "d": ("switchport trunk native vlan 10",),
    "f": ("switchport trunk allowed vlan 1,20,30",),
    "g": (),
    "h": ("switchport trunk native vlan 1", "switchport trunk allowed vlan 1,20,30"),
    "i": ("switchport trunk native vlan 1", "switchport trunk allowed vlan 20,30"),
    "t": ("switchport trunk native vlan tag", "switchport trunk allowed vlan 1,20,30"),
    "z": (
        "switchport trunk native vlan 10", "switchport trunk native vlan tag", "switchport trunk allowed vlan 10,20,30",
    ),
}

#: Shapes under a line for every trunk: (that line, the trunk's lines).
_UNDER_A_LINE = {
    "u": ("vlan dot1q tag native", _SWITCHPORT["f"]),
    "x": ("vlan dot1q tag native exclude control", _SWITCHPORT["f"]),
    "o": ("vlan dot1q tag native", ("no switchport trunk native vlan tag", *_SWITCHPORT["f"])),
    "y": ("vlan dot1q tag native", _SWITCHPORT["a"]),
}

#: The three whose grammar is ``switchport`` lines and whose trunk
#: has a default native VLAN.
_SWITCHPORT_THREE = (("cisco_iosxe_cli", _iosxe), ("arista_eos", _eos), ("cisco_nxos", _nxos))

#: (source codec, shape) -> the text, in that codec's own grammar.
SHAPES: dict[tuple[str, str], str] = {
    **{
        (codec, shape): write(*lines)
        for codec, write in _SWITCHPORT_THREE
        for shape, lines in _SWITCHPORT.items()
    },
    **{
        (codec, shape): write(*lines).replace("hostname sw1\n", f"hostname sw1\n{line}\n", 1)
        for codec, write in _SWITCHPORT_THREE for shape, (line, lines) in _UNDER_A_LINE.items()
    },
    ("aruba_aoscx", "a"): _aoscx("vlan trunk native 10", "vlan trunk allowed 10,20,30"),
    ("aruba_aoscx", "b"): _aoscx("vlan trunk native 10", "vlan trunk allowed 20,30"),
    ("aruba_aoscx", "c"): _aoscx("vlan trunk allowed 20,30"),
    ("aruba_aoscx", "d"): _aoscx("vlan trunk native 10"),
    ("aruba_aoscx", "f"): _aoscx("vlan trunk allowed 1,20,30"),
    ("aruba_aoscx", "g"): _aoscx("vlan trunk allowed all"),
    ("aruba_aoscx", "h"): _aoscx("vlan trunk native 1", "vlan trunk allowed 1,20,30"),
    ("aruba_aoscx", "i"): _aoscx("vlan trunk native 1", "vlan trunk allowed 20,30"),
    ("aruba_aoscx", "t"): _aoscx("vlan trunk native 1 tag", "vlan trunk allowed 1,20,30"),
    ("aruba_aoscx", "v"): _aoscx("vlan trunk native 20 tag", "vlan trunk allowed 1,20,30"),
    ("aruba_aoscx", "w"): _aoscx("vlan trunk native 20 tag", "vlan trunk allowed 20,30"),
    ("juniper_junos", "f"): _junos(f"{_MEMBERS} one", f"{_MEMBERS} twenty", f"{_MEMBERS} thirty").replace(
        "set vlans ten vlan-id 10\n", "set vlans one vlan-id 1\nset vlans ten vlan-id 10\n", 1,
    ),
    ("juniper_junos", "g"): _junos(f"{_MEMBERS} all"),
    ("juniper_junos", "a"): _junos(
        "native-vlan-id 10", f"{_MEMBERS} ten", f"{_MEMBERS} twenty", f"{_MEMBERS} thirty",
    ),
    ("juniper_junos", "b"): _junos("native-vlan-id 10", f"{_MEMBERS} twenty", f"{_MEMBERS} thirty"),
    ("juniper_junos", "c"): _junos(f"{_MEMBERS} twenty", f"{_MEMBERS} thirty"),
    ("juniper_junos", "d"): _junos("native-vlan-id 10"),
    # OS10 has no native line: the access VLAN of a trunk is its
    # untagged VLAN, and the allowed line names tagged VLANs.  (a) is
    # a text its parser reads; this module holds its renderer to never
    # writing it.
    ("dell_os10", "a"): _os10("switchport access vlan 10", "switchport trunk allowed vlan 10,20,30"),
    ("dell_os10", "b"): _os10("switchport access vlan 10", "switchport trunk allowed vlan 20,30"),
    ("dell_os10", "c"): _os10("switchport trunk allowed vlan 20,30"),
    ("dell_os10", "d"): _os10("switchport access vlan 10"),
    ("aruba_aoss", "e1"): _aoss(("untagged 1",), ("tagged 1",), ("tagged 1",)),
    ("aruba_aoss", "e2"): _aoss((), ("tagged 1",), ("tagged 1",)),
    ("aruba_aoss", "e3"): _aoss(("untagged 1",), (), ()),
    ("aruba_aoss", "e4"): _aoss((), ("tagged 1",), ("tagged 1",)).replace(
        "   no untagged 1-2\n", "   no untagged 1-2\n   tagged 1\n", 1,
    ),
}

#: The trunk of each source, and the access port beside it.
_PORTS = {
    "cisco_iosxe_cli": ("GigabitEthernet1/0/1", "GigabitEthernet1/0/2"),
    "arista_eos": ("Ethernet1", "Ethernet2"),
    "cisco_nxos": ("Ethernet1/1", "Ethernet1/2"),
    "dell_os10": ("ethernet1/1/1", "ethernet1/1/2"),
    "aruba_aoscx": ("1/1/1", "1/1/2"),
    "juniper_junos": ("ge-0/0/1", "ge-0/0/2"),
    "aruba_aoss": ("1", "2"),
}

_EVERY = frozenset({10, 20, 30})

#: (source codec, shape) -> what the SOURCE device carries on the
#: trunk: the VLAN it carries untagged, and which of the three
#: declared VLANs it carries at all.  Written here by hand, from each
#: platform's grammar, and from no parser:
#:
#: * where the list decides, the native VLAN is carried if the list
#:   names it -- and with no allowed line the list is every VLAN on
#:   IOS-XE, EOS, NX-OS and AOS-CX, and no VLAN on Junos;
#: * on OS10 the access VLAN of a trunk is carried, whatever the
#:   allowed line names;
#: * on AOS-S the port is in the VLANs that list it;
#: * a trunk of IOS-XE, EOS, NX-OS or AOS-CX that states no native
#:   VLAN has native VLAN 1: it carries VLAN 1 untagged where its
#:   list names VLAN 1, or is every VLAN -- unless the text says the
#:   native VLAN is tagged, and then VLAN 1 is carried tagged.  A
#:   Junos trunk and an AOS-S port have no such default: VLAN 1 on
#:   their list is a tagged VLAN;
#: * a trunk whose native VLAN is sent tagged carries NONE untagged,
#:   a native VLAN it states included -- read by each platform's
#:   grammar (:func:`says_tagged`): an IOS-XE or NX-OS trunk that
#:   leaves the line for every trunk has its default again, and on
#:   EOS, where the id and ``tag`` are one argument, an id stated
#:   after the line for every trunk is the port's own.
CARRIES: dict[tuple[str, str], tuple[int | None, frozenset[int]]] = {
    **{
        (codec, shape): carried
        for codec in ("cisco_iosxe_cli", "arista_eos", "cisco_nxos", "aruba_aoscx")
        for shape, carried in {
            "a": (10, _EVERY), "b": (None, frozenset({20, 30})), "c": (None, frozenset({20, 30})), "d": (10, _EVERY),
            "f": (1, frozenset({20, 30})), "g": (1, _EVERY),
            "h": (1, frozenset({20, 30})), "i": (None, frozenset({20, 30})),
        }.items()
    },
    **{
        (codec, shape): (None, frozenset({20, 30}))
        for codec, _write in _SWITCHPORT_THREE for shape in ("t", "u", "x")
    },
    **{(codec, "z"): (None, _EVERY) for codec, _write in _SWITCHPORT_THREE},
    **{(codec, "o"): (1, frozenset({20, 30})) for codec in ("cisco_iosxe_cli", "cisco_nxos")},
    **{(codec, "y"): (None, _EVERY) for codec in ("cisco_iosxe_cli", "cisco_nxos")},
    ("arista_eos", "o"): (None, frozenset({20, 30})),
    ("arista_eos", "y"): (10, _EVERY),
    **{("aruba_aoscx", shape): (None, frozenset({20, 30})) for shape in ("t", "v", "w")},
    ("juniper_junos", "f"): (None, frozenset({20, 30})),
    ("juniper_junos", "g"): (None, _EVERY),
    ("aruba_aoss", "e4"): (None, frozenset({20, 30})),
    ("juniper_junos", "a"): (10, _EVERY),
    ("juniper_junos", "b"): (None, frozenset({20, 30})),
    ("juniper_junos", "c"): (None, frozenset({20, 30})),
    ("juniper_junos", "d"): (None, frozenset()),
    ("dell_os10", "a"): (10, _EVERY),
    ("dell_os10", "b"): (10, _EVERY),
    ("dell_os10", "c"): (None, frozenset({20, 30})),
    ("dell_os10", "d"): (10, frozenset({10})),
    ("aruba_aoss", "e1"): (10, _EVERY),
    ("aruba_aoss", "e2"): (None, frozenset({20, 30})),
    ("aruba_aoss", "e3"): (10, frozenset({10})),
}


def _carried(port: Port | None) -> tuple[int | None, frozenset[int]]:
    """The untagged VLAN of *port* and the declared VLANs it carries."""
    if port is None:
        return None, frozenset()
    tagged = _EVERY if port.tagged == ALL else _EVERY & port.tagged
    return port.untagged, frozenset(tagged - {port.untagged}) | ({port.untagged} & _EVERY)


#: (source codec, shape) whose TEXT the reader gives the switch's
#: default VLAN, by default, where the tree has none: an OS10 trunk
#: with neither an access line nor ``no switchport access vlan``.  Its
#: parser reads the fewer -- no untagged VLAN, as it must where the id
#: is not in the text -- and :data:`CARRIES` holds that reading, which
#: every output is held to.  Compared for EQUALITY with the shapes the
#: reader does it for.
BY_THE_SWITCHS_DEFAULT = frozenset({("dell_os10", "c")})


def _as_the_tree_reads(port: Port | None) -> Port | None:
    """*port* as a tree of its text reads it: the switch's default
    VLAN, which has no id, is no untagged VLAN there."""
    if port is None or not (port.by_default and port.untagged == THE_SWITCHS_DEFAULT):
        return port
    return Port(None, port.left_out, port.tagged)


def _shape_job(source: str, shape: str, target: str) -> tuple[Any, str]:
    """The job, and the name its output has for the trunk.  AOS-S has
    no name of its own for the ports of three of the sources, so onto
    AOS-S every source is given one (the gap is pinned where it is
    measured, in ``test_a_trunk_says_none_nothing_or_all.py``)."""
    trunk, access = _PORTS[source]
    port_map = {trunk: "1", access: "2"} if target == "aruba_aoss" and source != "aruba_aoss" else {}
    job = _run(source, target, SHAPES[(source, shape)], port_map)
    assert job.rendered, (source, shape, target, job.error)
    assert not (job.port_drops or job.fused_ports or job.untranslated_ports), (source, shape, target)
    return job, job.port_renames.get(trunk, trunk)


def test_what_each_source_carries_is_written() -> None:
    assert set(CARRIES) == set(SHAPES)
    assert {source for source, _shape in SHAPES} == set(SWITCHES)
    # Every kind is among them: carried, left out, not stated -- and
    # carried by a default, on each platform that has one.
    assert {untagged for untagged, _all in CARRIES.values()} == {1, 10, None}
    for codec in HAVE_A_DEFAULT:
        assert CARRIES[(codec, "f")][0] == CARRIES[(codec, "g")][0] == WITH_NO_NATIVE_LINE[codec] == 1


@pytest.mark.parametrize("source,shape", sorted(SHAPES))
def test_each_source_reads_as_it_is_written(source: str, shape: str) -> None:
    """The source's own tree, by its platform's row, says what the
    hand says the device carries.  (The row a tree is read by is the
    platform's, not the tree's: this passes whether the parser puts a
    trunk's untagged VLAN in its list or beside it.)"""
    tree = get_codec(source).parse(SHAPES[(source, shape)])
    ports = read_tree(tree, source)
    trunk, access = _PORTS[source]
    assert _carried(ports.get(trunk)) == CARRIES[(source, shape)], (source, shape, ports.get(trunk))
    assert ports[access].untagged == 20
    # ... and the text of the source, by this module's own reader of
    # its grammar, says the same: the tree holds what the platform's
    # default adds, and no more -- but for the default that has no id,
    # which the reader names and no tree can hold.
    by_text = read_text(SHAPES[(source, shape)], source).get(trunk)
    assert (by_text is not None and by_text.untagged == THE_SWITCHS_DEFAULT) == (
        (source, shape) in BY_THE_SWITCHS_DEFAULT
    ), (source, shape, by_text)
    assert _carried(_as_the_tree_reads(by_text)) == CARRIES[(source, shape)], (source, shape)
    assert left_unfilled(tree, source, SHAPES[(source, shape)]) == []


@pytest.mark.parametrize("target", SWITCHES)
@pytest.mark.parametrize("source,shape", sorted(SHAPES))
def test_each_shape_onto_each_target(source: str, shape: str, target: str) -> None:
    """What the source device carries on its trunk -- untagged, and at
    all -- the target device carries, by the target's row, read from
    the output both ways."""
    job, final = _shape_job(source, shape, target)
    want = CARRIES[(source, shape)]
    codec = get_codec(target)
    fold = (lambda name: name.casefold()) if not codec.port_names_case_sensitive else (lambda name: name)
    for way, ports in (
        ("the text", read_text(job.rendered, target)),
        ("the parser", read_tree(codec.parse(job.rendered), target)),
    ):
        ports = {fold(re.sub(r"\s+", "", name)): port for name, port in ports.items()}
        have = _carried(ports.get(fold(re.sub(r"\s+", "", final))))
        assert have == want, (
            f"{source} ({shape}) to {target}, by {way}: the source carries untagged VLAN {want[0]} and "
            f"VLANs {sorted(want[1])}; the output, on {final!r}, {have[0]} and {sorted(have[1])}"
        )
    verdict = judge(get_codec(source), codec, SHAPES[(source, shape)], job)
    assert verdict["wrong"] == []
    assert verdict["tally"][TARGETS_DEFAULT] == 0


def test_no_shape_is_left_to_a_default() -> None:
    """Measured over every shape and every target, with no judgement
    read: the trunk of no output carries an untagged VLAN its source
    does not.  A shape has one trunk and an access port, so on IOS-XE
    and NX-OS a trunk that carries no VLAN untagged is written the
    line for every trunk (one line, before the ports), and on EOS and
    AOS-CX its own; the review line is for an output with another
    trunk (:func:`test_beside_a_trunk_that_carries_one`)."""
    measured: set[tuple[str, str, str]] = set()
    for source, shape in sorted(SHAPES):
        for target in SWITCHES:
            job, final = _shape_job(source, shape, target)
            port = {
                re.sub(r"\s+", "", name).casefold(): port for name, port in read_text(job.rendered, target).items()
            }.get(re.sub(r"\s+", "", final).casefold())
            if _carried(port)[0] != CARRIES[(source, shape)][0]:
                measured.add((source, shape, target))
            if target in SAID_OF_NO_UNTAGGED:
                # The line for every trunk, where this one has no VLAN
                # untagged and VLAN 1 on its list, and nowhere else.
                tags_it = port is not None and port.untagged is None and (port.tagged == ALL or 1 in port.tagged)
                assert job.rendered.splitlines().count("vlan dot1q tag native") == tags_it, (source, shape, target)
    assert measured == set()


#: What follows a trunk whose source carries VLAN 1 untagged by its
#: platform's default, on each target: the lines that state VLAN 1
#: untagged, or none where the target's own default does it.
_UNTAGGED_ONE = {
    "arista_eos": [],
    "cisco_iosxe_cli": [],
    "cisco_nxos": [],
    "aruba_aoscx": ["vlan trunk native 1"],
    "dell_os10": ["switchport access vlan 1"],
    "juniper_junos": ["native-vlan-id 1"],
}


@pytest.mark.parametrize("target", SWITCHES)
@pytest.mark.parametrize("shape", ["f", "g"])
@pytest.mark.parametrize("source", HAVE_A_DEFAULT)
def test_vlan_one_is_written_untagged(source: str, shape: str, target: str) -> None:
    """The lines themselves.  A trunk that states no native VLAN, from
    each of the four platforms whose trunk then has native VLAN 1:
    the three ``switchport`` targets are written no native line (it
    is their default as well, and none of their captures prints it),
    AOS-CX its native line, OS10 the access line with VLAN 1 off the
    allowed line, Junos ``native-vlan-id`` and a VLAN to be a member
    of, and AOS-S ``untagged`` in VLAN 1."""
    job, final = _shape_job(source, shape, target)
    if target == "aruba_aoss":
        one = dict(_stanzas(job.rendered, "vlan "))["1"]
        assert [line for line in one if line.startswith(("tagged", "untagged"))] == [f"untagged {final}"], one
        return
    opener = "set interfaces " if target == "juniper_junos" else "interface "
    if target == "juniper_junos":
        stanza = [line.removeprefix(f"set interfaces {final} ") for line in job.rendered.splitlines()
                  if line.startswith(f"set interfaces {final} ")]
        assert "set vlans VLAN-1 vlan-id 1" in job.rendered.splitlines()
        members = [line.rsplit(" ", 1)[1] for line in stanza if _MEMBERS in line]
        assert members == (["all"] if shape == "g" else ["VLAN-1", "twenty", "thirty"]), stanza
    else:
        stanza = dict(_stanzas(job.rendered, opener))[final]
    words = ("native", "access vlan")
    assert [line for line in stanza if any(word in line for word in words)] == _UNTAGGED_ONE[target], stanza
    if target == "dell_os10":
        allowed = [line for line in stanza if line.startswith("switchport trunk allowed vlan ")]
        assert allowed == [f"switchport trunk allowed vlan {'2-4094' if shape == 'g' else '20,30'}"], stanza


@pytest.mark.parametrize("target", SWITCHES)
@pytest.mark.parametrize("shape", ["f", "g"])
@pytest.mark.parametrize("source", HAVE_A_DEFAULT)
def test_a_vlan_map_moves_the_untagged_vlan(source: str, shape: str, target: str) -> None:
    """The VLAN pane's map renumbers VLAN 1 to 40.  The trunk's
    untagged VLAN is in the tree before the map is applied, so it
    goes with it: the output's trunk states VLAN 40 as its untagged
    VLAN, in a line and by no default, and VLAN 1 is untagged
    nowhere.  (On Junos, where the trunk is every VLAN, that line is
    ``native-vlan-id 40`` beside ``vlan members all``: read here as
    carried, and whether ``all`` takes the native VLAN in is not
    established.)"""
    trunk, access = _PORTS[source]
    port_map = {trunk: "1", access: "2"} if target == "aruba_aoss" and source != "aruba_aoss" else {}
    job = run_plan_with_checked_names(
        get_codec(source), get_codec(target), SHAPES[(source, shape)],
        port_rename_map=port_map, vlan_rename_map={1: 40},
    )
    assert job.rendered and not (job.port_drops or job.fused_ports), (source, shape, target, job.error)
    final = re.sub(r"\s+", "", job.port_renames.get(trunk, trunk)).casefold()
    codec = get_codec(target)
    for way, ports in (
        ("the text", read_text(job.rendered, target)),
        ("the parser", read_tree(codec.parse(job.rendered), target)),
    ):
        port = {re.sub(r"\s+", "", name).casefold(): port for name, port in ports.items()}[final]
        assert (port.untagged, port.by_default) == (40, False), (source, shape, target, way, port)
    assert not [port for port in read_text(job.rendered, target).values() if port.untagged == 1]


@pytest.mark.parametrize("target", SWITCHES)
@pytest.mark.parametrize(
    "source,listed", [*((codec, None) for codec in HAVE_A_DEFAULT), ("cisco_iosxe_cli", "1,20,30")],
)
def test_a_cleared_native_vlan_stays_tagged(source: str, listed: str | None, target: str) -> None:
    """Reached through the VLAN pane.  Native VLAN 10 of a trunk of
    every VLAN (shape (d) of each platform whose trunk has a default),
    and a map that drops VLAN 10; and native VLAN 10 outside an IOS-XE
    list of 1, 20 and 30, and a map that merges VLAN 10 into VLAN 20,
    which the trunk carried tagged.  The pass clears the native VLAN
    of both.  The output's trunk carries VLAN 20 tagged and no VLAN
    untagged, on every target -- on the four whose trunk has a
    default, by their form for that, which this output (its one other
    port an access port) has on IOS-XE and NX-OS as the line for
    every trunk.  It was VLAN 1, untagged by the target's default."""
    text = SHAPES[(source, "d")] if listed is None else _iosxe(
        "switchport trunk native vlan 10", f"switchport trunk allowed vlan {listed}",
    )
    trunk, access = _PORTS[source]
    port_map = {trunk: "1", access: "2"} if target == "aruba_aoss" else {}
    job = run_plan_with_checked_names(
        get_codec(source), get_codec(target), text, port_rename_map=port_map,
        vlan_rename_map={10: None} if listed is None else {10: 20},
    )
    assert job.rendered and [w for w in job.warnings if "native VLAN cleared" in str(w)], job.warnings
    final = re.sub(r"\s+", "", job.port_renames.get(trunk, trunk)).casefold()
    codec = get_codec(target)
    for way, ports in (
        ("the text", read_text(job.rendered, target)),
        ("the parser", read_tree(codec.parse(job.rendered), target)),
    ):
        port = {re.sub(r"\s+", "", name).casefold(): port for name, port in ports.items()}[final]
        assert (port.untagged, port.carries_tagged(20)) == (None, True), (target, way, port)
    if target in SAID_OF_NO_UNTAGGED:
        assert job.rendered.splitlines().count("vlan dot1q tag native") == 1, job.rendered


def _no_mode_line(text: str) -> str:
    """*text* without the ``switchport mode trunk`` line the writers
    above put first under the trunk."""
    lines = text.split("\n")
    (at,) = [n for n, line in enumerate(lines) if line.strip() == "switchport mode trunk"]
    return "\n".join(lines[:at] + lines[at + 1:])


_THE_LIST = "switchport trunk allowed vlan 1,10,20"
_AN_ACCESS_VLAN = "switchport access vlan 10"

#: (source codec, what the port's stanza has) -> (the text, what
#: its parser makes of the port: mode, access VLAN, native VLAN).
#: Every one has VLAN 1 on its list and states no native VLAN.
#:
#: The default native VLAN is a trunk's, so the two that SAY they are
#: trunks have it (``switchport mode trunk``; on AOS-CX the ``vlan
#: trunk`` line itself, which is how a trunk is stated there) and no
#: other does.
#:
#: The MODE and the access VLAN of the rest are what the parsers read
#: today, pinned here and not endorsed.  EOS takes such a port for a
#: trunk and keeps no access VLAN, even under ``switchport mode
#: access``; NX-OS takes it for a trunk when the trunk line comes
#: before the access line.  A known limitation, in the CHANGELOG, and
#: older than the default: what is held here is that such a port is
#: not ALSO given an untagged VLAN 1 its text does not state.
WITH_A_TRUNK_LINE: dict[tuple[str, str], tuple[str, tuple[str | None, int | None, int | None]]] = {
    ("arista_eos", "an access VLAN, then the list"): (
        _no_mode_line(_eos(_AN_ACCESS_VLAN, _THE_LIST)), ("trunk", None, None)),
    ("arista_eos", "mode access, an access VLAN, then the list"): (
        _no_mode_line(_eos("switchport mode access", _AN_ACCESS_VLAN, _THE_LIST)), ("trunk", None, None)),
    ("arista_eos", "the list alone"): (_no_mode_line(_eos(_THE_LIST)), ("trunk", None, None)),
    ("arista_eos", "mode trunk, and the list"): (_eos(_THE_LIST), ("trunk", None, 1)),
    ("cisco_nxos", "the list, then an access VLAN"): (
        _no_mode_line(_nxos("switchport", _THE_LIST, _AN_ACCESS_VLAN)), ("trunk", 10, None)),
    ("cisco_nxos", "an access VLAN, then the list"): (
        _no_mode_line(_nxos("switchport", _AN_ACCESS_VLAN, _THE_LIST)), ("access", 10, None)),
    ("cisco_nxos", "mode access, an access VLAN, then the list"): (
        _no_mode_line(_nxos("switchport", "switchport mode access", _AN_ACCESS_VLAN, _THE_LIST)),
        ("access", 10, None)),
    ("cisco_nxos", "the list alone"): (_no_mode_line(_nxos("switchport", _THE_LIST)), ("trunk", None, None)),
    ("cisco_iosxe_cli", "an access VLAN, then the list"): (
        _no_mode_line(_iosxe(_AN_ACCESS_VLAN, _THE_LIST)), (None, 10, None)),
    ("cisco_iosxe_cli", "mode dynamic auto, then the list"): (
        _no_mode_line(_iosxe("switchport mode dynamic auto", _THE_LIST)), ("dynamic", None, None)),
    ("cisco_iosxe_cli", "the list alone"): (_no_mode_line(_iosxe(_THE_LIST)), (None, None, None)),
    ("aruba_aoscx", "`vlan trunk allowed` alone"): (_aoscx("vlan trunk allowed 1,10,20"), ("trunk", None, 1)),
}

#: The targets that state a port's untagged VLAN in a line of their
#: own, with the line that states VLAN 1.
_STATES_ONE_UNTAGGED = {
    "juniper_junos": r"set interfaces \S+ native-vlan-id 1",
    "dell_os10": r"\s+switchport access vlan 1",
    "aruba_aoss": r"\s+untagged \S+",        # (looked for in VLAN 1's stanza)
}


def _job_of_a_port(source: str, text: str, target: str) -> tuple[Any, str]:
    """The job, and the name its output has for the first port."""
    port, other = _PORTS[source]
    port_map = {port: "1", other: "2"} if target == "aruba_aoss" else {}
    job = _run(source, target, text, port_map)
    assert job.rendered and not (job.port_drops or job.fused_ports), (source, target, job.error)
    return job, job.port_renames.get(port, port)


@pytest.mark.parametrize("source,what", sorted(WITH_A_TRUNK_LINE))
def test_the_default_is_for_a_port_that_says_it_is_a_trunk(source: str, what: str) -> None:
    """The tree first: the mode and the access VLAN typed beside each
    port, and a native VLAN for the two that say they are trunks and
    for no other.  Then the three targets that state the untagged
    VLAN in a line.  For a port that does not say it is a trunk no
    output states VLAN 1 untagged, for any port: no ``native-vlan-id
    1`` on Junos, no ``switchport access vlan 1`` on OS10, no
    ``untagged`` in VLAN 1 on AOS-S -- by this module's reader of
    each text, by the target's parser, and by the lines.  For the
    two that say so, each of the three states it, for that port."""
    text, (mode, access, native) = WITH_A_TRUNK_LINE[(source, what)]
    port = _PORTS[source][0]
    tree = get_codec(source).parse(text)
    record = next(iface for iface in tree.interfaces if iface.name == port)
    assert (record.switchport_mode, record.access_vlan, record.trunk_native_vlan) == (mode, access, native)
    assert record.trunk_allowed_vlans == [1, 10, 20]
    assert (_squeezed(port) in says_it_is_a_trunk(text, source)) == (native == 1)
    assert states_a_native_vlan(text) == set()
    assert left_unfilled(tree, source, text) == [] and put_unasked(tree, source, text) == []
    for target, line in _STATES_ONE_UNTAGGED.items():
        job, final = _job_of_a_port(source, text, target)
        want = [_squeezed(final)] if native == 1 else []
        for way, ports in (
            ("the text", read_text(job.rendered, target)),
            ("the parser", read_tree(get_codec(target).parse(job.rendered), target)),
        ):
            assert sorted(_squeezed(name) for name, has in ports.items() if has.untagged == 1) == want, (target, way)
        where = job.rendered.splitlines()
        if target == "aruba_aoss":
            where = [f"   {found}" for found in dict(_stanzas(job.rendered, "vlan ")).get("1", [])]
        assert len([found for found in where if re.fullmatch(line, found)]) == len(want), (target, where)


#: The one cell in which this module's two readings of an output
#: differ, and not by any default.  An IOS-XE port with an access
#: line, a trunk line and no mode line comes back onto IOS-XE as it
#: went.  Its parser makes no access port of it (a port with trunk
#: lines and no mode line is left in no mode), and the reader of text
#: here takes any port with an access line and no mode line for an
#: access port.  Neither reads it as a trunk.
_READ_TWO_WAYS = ("cisco_iosxe_cli", "an access VLAN, then the list", "cisco_iosxe_cli")


@pytest.mark.parametrize("target", SWITCHES)
@pytest.mark.parametrize("source,what", sorted(WITH_A_TRUNK_LINE))
def test_a_port_with_a_trunk_line_onto_each_target(source: str, what: str, target: str) -> None:
    """...and through the judgement, onto every target: nothing is
    lost or gained against what the TREE has, and no tree has a
    default it is not owed.  A port the parser took for a trunk is
    WRITTEN as one, with ``switchport mode trunk`` (on AOS-CX a
    ``vlan trunk`` line), and carries no VLAN untagged there, as in
    the tree: on the four targets whose trunk has a default native
    VLAN it is written their form for that (on IOS-XE and NX-OS the
    line for every trunk, this output having no other), and VLAN 1
    is untagged by no default."""
    text, _made = WITH_A_TRUNK_LINE[(source, what)]
    job, _final = _job_of_a_port(source, text, target)
    verdict = judge(get_codec(source), get_codec(target), text, job)
    if (source, what, target) == _READ_TWO_WAYS:
        assert verdict["tally"]["readings disagree"] == 1 and len(verdict["wrong"]) == 1, verdict["wrong"]
        assert verdict["wrong"][0].startswith("'gigabitethernet1/0/1': the parser reads None and the text Port(")
    else:
        assert verdict["wrong"] == []
    assert not verdict["tally"][NOT_FILLED] and not verdict["tally"][NOT_OWED]
    assert verdict["tally"][TARGETS_DEFAULT] == 0


def test_a_port_that_is_no_trunk_keeps_its_lines() -> None:
    """IOS-XE keeps trunk lines on a port in another mode.  Its record
    has its list and NO native VLAN -- the default is a trunk's -- is
    put on no VLAN's member list, and the same text comes back."""
    text = _iosxe("switchport trunk allowed vlan 1,20,30").replace(
        " switchport mode trunk\n", " switchport mode dynamic auto\n", 1,
    )
    tree = get_codec("cisco_iosxe_cli").parse(text)
    port = next(iface for iface in tree.interfaces if iface.name == "GigabitEthernet1/0/1")
    assert (port.switchport_mode, port.trunk_native_vlan, port.trunk_allowed_vlans) == ("dynamic", None, [1, 20, 30])
    assert not [vlan.id for vlan in tree.vlans if port.name in (*vlan.tagged_ports, *vlan.untagged_ports)]
    assert left_unfilled(tree, "cisco_iosxe_cli", text) == [] == put_unasked(tree, "cisco_iosxe_cli", text)
    job = _run("cisco_iosxe_cli", "cisco_iosxe_cli", text)
    stanza = dict(_stanzas(job.rendered, "interface "))[port.name]
    assert stanza == ["switchport trunk allowed vlan 1,20,30"], stanza
    for target in SWITCHES:
        assert judge(get_codec("cisco_iosxe_cli"), get_codec(target), text, _run("cisco_iosxe_cli", target, text))[
            "wrong"
        ] == [], target


@pytest.mark.parametrize("source,shape", sorted(SHAPES))
def test_the_same_text_comes_back(source: str, shape: str) -> None:
    """Onto its own codec a trunk is written as it was: a native VLAN
    outside its list stays outside it, an access VLAN of an OS10 trunk
    stays off its allowed line, and AOS-S gets its lists back.  (The
    exceptions: the OS10 text that names its access VLAN on the
    allowed line as well, which comes back with the VLAN on one; the
    OS10 trunk with no access line, which comes back with ``no
    switchport access vlan``; and AOS-S's ``no untagged`` in VLAN 1,
    which comes back for the ports it alone takes out of VLAN 1.)
    A trunk that sends its native VLAN tagged comes back saying so
    where its list holds VLAN 1, in its platform's one form for it:
    on IOS-XE and NX-OS the line for every trunk (no other port of
    these texts blocks it; one that leaves the line, (o), carries
    VLAN 1 untagged and comes back as such), on EOS the port's own
    ``tag``, on AOS-CX ``vlan trunk native 1 tag``.  Where its list
    leaves VLAN 1 out it comes back with no native line, on all four
    ((y), (z), (w)).  The id of a native VLAN sent tagged is not
    kept: it says nothing the list does not."""
    job, _final = _shape_job(source, shape, source)

    def lines(text: str) -> list[str]:
        words = ("switchport", "vlan trunk", "vlan access", "tagged", "native-vlan-id", "vlan members")
        found = sorted(line.strip() for line in text.splitlines() if any(word in line for word in words))
        # (EOS prints no mode line for an access port, and is written one.)
        return [line for line in found if line != "switchport mode access"]

    want = lines(SHAPES[(source, shape)])
    if (source, shape) == ("dell_os10", "a"):
        want = lines(SHAPES[(source, "b")])
    if source == "aruba_aoscx" and shape == "d":
        want.append("vlan trunk allowed all")     # the switch adds it, and prints it
    if source == "aruba_aoscx" and shape in ("f", "g"):
        want.append("vlan trunk native 1")        # its captures print the line on every trunk
    if source != "aruba_aoscx" and shape == "h":
        want.remove("switchport trunk native vlan 1")      # the default written out: no capture prints it
    cisco = source in ("cisco_iosxe_cli", "cisco_nxos")
    if (cisco and shape == "t") or shape == "z":
        # (t) the line for every trunk, below; (z) none: its list
        # leaves VLAN 1 out, and the trunk is written as one whose
        # native VLAN is off its list.
        want.remove("switchport trunk native vlan tag")
    if (cisco and shape in ("y", "z")) or (source == "arista_eos" and shape == "z"):
        want.remove("switchport trunk native vlan 10")     # sent tagged: no id is kept (on EOS `tag` came after it)
    if shape == "o":
        want.remove("no switchport trunk native vlan tag")  # a trunk with VLAN 1 untagged has no line for it
    if source == "arista_eos" and shape in ("u", "x", "o"):
        want.append("switchport trunk native vlan tag")    # no line for every trunk on EOS: the port's own
    if source == "aruba_aoscx" and shape == "v":
        want[want.index("vlan trunk native 20 tag")] = "vlan trunk native 1 tag"
    if source == "aruba_aoscx" and shape == "w":
        want.remove("vlan trunk native 20 tag")            # VLAN 1 is off the list, and nothing is untagged
    if source == "aruba_aoss":
        want.remove("no untagged 1-2")            # VLAN 1's line names the ports no other line names untagged:
        if shape == "e2":                         # port 1, tagged in 20 and 30 alone (port 2 is untagged in 20)
            want.append("no untagged 1")
    if (source, shape) == ("dell_os10", "c"):
        # A trunk with no access line is read as one that carries no
        # VLAN untagged, and is written so: the line that takes the
        # access VLAN away, under its review line.  (The OS10 tree has
        # one reading for both texts.)
        want += [said_of_none_on_os10(False), "no switchport access vlan"]
    assert lines(job.rendered) == sorted(want), (source, shape)
    # The line for every trunk: where the trunk sends its native VLAN
    # tagged and its list holds VLAN 1.
    every = cisco and shape in ("t", "u", "x")
    assert job.rendered.splitlines().count("vlan dot1q tag native") == every, (source, shape)
    # One line comes back that the text did not have.  A VLAN of the
    # tree is declared in the output like any other, and a trunk that
    # carries VLAN 1 untagged by its platform's default brings VLAN 1
    # into the tree: so (g), whose text has no word for VLAN 1, comes
    # back with a `vlan 1` line, as (f), (h) and (i) do for the VLAN
    # their lines name.  Nothing decides from the tree whether the
    # text had the line.  Where no line names VLAN 1 and no trunk
    # carries it untagged by default, there is none.
    if source in ("cisco_iosxe_cli", "arista_eos"):
        assert "vlan 1" not in [line.strip() for line in SHAPES[(source, shape)].splitlines()]
        declared = "vlan 1" in [line.strip() for line in job.rendered.splitlines()]
        assert declared == (shape in ("f", "g", "h", "i", "t", "u", "x", "o")), (source, shape)


# ---------------------------------------------------------------------------
# 2b. A trunk that carries no VLAN untagged, beside one that does
# ---------------------------------------------------------------------------

_NATIVE_TEN = ("switchport trunk native vlan 10", "switchport trunk allowed vlan 10,20,30")
_THIRD = {
    "cisco_iosxe_cli": "GigabitEthernet1/0/3", "cisco_nxos": "Ethernet1/3", "arista_eos": "Ethernet3",
    "aruba_aoscx": "1/1/3", "juniper_junos": "ge-0/0/3", "dell_os10": "ethernet1/1/3", "aruba_aoss": "3",
}

#: Source -> a text with three ports: the trunk of the shapes, which
#: carries NO VLAN untagged and VLAN 1 tagged; the access port in
#: VLAN 20; and a third, a trunk that carries VLAN 10 untagged and
#: VLANs 20 and 30 tagged.  An output of one of these cannot say of
#: EVERY trunk that its native VLAN is sent tagged.
TWO_TRUNKS: dict[str, str] = {
    "cisco_iosxe_cli": _iosxe(*_SWITCHPORT["t"]).replace(
        "end\n", "interface GigabitEthernet1/0/3\n switchport mode trunk\n"
        + "".join(f" {line}\n" for line in _NATIVE_TEN) + "!\nend\n", 1,
    ),
    "cisco_nxos": _nxos(*_SWITCHPORT["t"]) + "interface Ethernet1/3\n  switchport mode trunk\n"
    + "".join(f"  {line}\n" for line in _NATIVE_TEN),
    "arista_eos": _eos(*_SWITCHPORT["t"]).replace(
        "end\n", "interface Ethernet3\n   switchport mode trunk\n"
        + "".join(f"   {line}\n" for line in _NATIVE_TEN) + "!\nend\n", 1,
    ),
    "aruba_aoscx": SHAPES[("aruba_aoscx", "t")] + "interface 1/1/3\n    no shutdown\n    no routing\n"
    "    vlan trunk native 10\n    vlan trunk allowed 10,20,30\n",
    "juniper_junos": SHAPES[("juniper_junos", "g")] + "".join(
        f"set interfaces ge-0/0/3 {line}\n" for line in (
            "unit 0 family ethernet-switching interface-mode trunk", "native-vlan-id 10",
            f"{_MEMBERS} ten", f"{_MEMBERS} twenty", f"{_MEMBERS} thirty",
        )
    ),
    "dell_os10": _os10("switchport trunk allowed vlan 1,20,30") + "interface ethernet1/1/3\n no shutdown\n"
    " switchport mode trunk\n switchport access vlan 10\n switchport trunk allowed vlan 20,30\n!\n",
    "aruba_aoss": _aoss(("untagged 3",), ("tagged 1,3",), ("tagged 1,3",)).replace(
        "   no untagged 1-2\n", "   no untagged 1-3\n   tagged 1\n", 1,
    ),
}

#: The form each target writes on the first trunk: a line of its
#: stanza.  Junos, whose trunk has no default, writes none.  AOS-S
#: writes its form in VLAN 1's stanza, not the port's: the trunk
#: carries VLAN 1 tagged, and is on VLAN 1's ``tagged`` line.
_ITS_FORM = {
    "arista_eos": "switchport trunk native vlan tag",
    "aruba_aoscx": "vlan trunk native 1 tag",
    "cisco_iosxe_cli": SAID_OF_NO_UNTAGGED["cisco_iosxe_cli"],
    "cisco_nxos": SAID_OF_NO_UNTAGGED["cisco_nxos"],
    "dell_os10": "no switchport access vlan",
}


def _beside_job(source: str, target: str) -> tuple[Any, str, str]:
    """The job, and the names its output has for the trunk that
    carries no VLAN untagged and for the one that does."""
    trunk, access = _PORTS[source]
    third = _THIRD[source]
    port_map = {trunk: "1", access: "2", third: "3"} if target == "aruba_aoss" and source != "aruba_aoss" else {}
    job = _run(source, target, TWO_TRUNKS[source], port_map)
    assert job.rendered, (source, target, job.error)
    assert not (job.port_drops or job.fused_ports or job.untranslated_ports), (source, target)
    return job, job.port_renames.get(trunk, trunk), job.port_renames.get(third, third)


@pytest.mark.parametrize("source", sorted(TWO_TRUNKS))
def test_the_beside_sources_read_as_written(source: str) -> None:
    """The first trunk carries no VLAN untagged, and of the VLANs the
    shapes look at 20 and 30 tagged (Junos: all three, its trunk being
    `vlan members all`); the third carries VLAN 10 untagged -- by the
    tree, and by the text."""
    trunk, _access = _PORTS[source]
    text = TWO_TRUNKS[source]
    tagged = _EVERY if source == "juniper_junos" else frozenset({20, 30})
    for ports in (read_tree(get_codec(source).parse(text), source), read_text(text, source)):
        # (The OS10 text's first trunk has neither access line: the
        # reader gives it the switch's default VLAN, the tree none.)
        assert _carried(_as_the_tree_reads(ports[trunk])) == (None, tagged), (source, ports[trunk])
        assert _carried(ports[_THIRD[source]]) == (10, _EVERY), (source, ports[_THIRD[source]])
    assert (read_text(text, source)[trunk].untagged == THE_SWITCHS_DEFAULT) == (source == "dell_os10")


@pytest.mark.parametrize("target", SWITCHES)
@pytest.mark.parametrize("source", sorted(TWO_TRUNKS))
def test_beside_a_trunk_that_carries_one(source: str, target: str) -> None:
    """Onto every target.  Nothing is lost or gained.  On IOS-XE and
    NX-OS the line for every trunk is NOT written -- it would send the
    third trunk's VLAN 10 tagged -- and the first trunk is left to the
    target's default, under the review line, whole, in its own stanza
    and in no other: VLAN 1 untagged there, counted.  On EOS and
    AOS-CX the first trunk is written the port's own form, and nothing
    is left to a default."""
    job, first, third = _beside_job(source, target)
    verdict = judge(get_codec(source), get_codec(target), TWO_TRUNKS[source], job)
    assert verdict["wrong"] == [], verdict["wrong"]
    left = 1 if target in SAID_OF_NO_UNTAGGED else 0
    assert verdict["tally"][TARGETS_DEFAULT] == verdict["tally"][DEFAULT_SAID] == left, dict(verdict["tally"])
    assert "vlan dot1q tag native" not in job.rendered.splitlines()
    if target in _ITS_FORM:
        stanzas = dict(_stanzas(job.rendered, "interface "))
        assert stanzas[first].count(_ITS_FORM[target]) == 1, stanzas[first]
        assert _ITS_FORM[target] not in stanzas[third], stanzas[third]
    if target == "aruba_aoss":
        one = dict(_stanzas(job.rendered, "vlan "))["1"]
        on_tagged = [port for line in one if line.startswith("tagged ") for port in _aoss_ports(line.split()[1])]
        assert first in on_tagged and third not in on_tagged, one
        assert first not in out_of_vlan_1(job.rendered) and third not in out_of_vlan_1(job.rendered), one


# ---------------------------------------------------------------------------
# 3. What each side of the defect was written as
# ---------------------------------------------------------------------------

#: What follows the native line where the list decides, for a trunk
#: that carries VLAN 10 untagged and VLANs 20 and 30 tagged.
_BOTH_LINES = {
    "arista_eos": ("switchport trunk native vlan 10", "switchport trunk allowed vlan 10,20,30"),
    "cisco_iosxe_cli": ("switchport trunk native vlan 10", "switchport trunk allowed vlan 10,20,30"),
    "cisco_nxos": ("switchport trunk native vlan 10", "switchport trunk allowed vlan 10,20,30"),
    "aruba_aoscx": ("vlan trunk native 10", "vlan trunk allowed 10,20,30"),
}


@pytest.mark.parametrize("target", sorted(_BOTH_LINES))
@pytest.mark.parametrize("source,shape", [("aruba_aoss", "e1"), ("dell_os10", "b")])
def test_the_list_names_the_native_vlan(source: str, shape: str, target: str) -> None:
    """The lines themselves, where the grammar is two lines: the
    allowed line named 20 and 30 beside a native line for 10."""
    job, _final = _shape_job(source, shape, target)
    written = [line.strip() for line in job.rendered.splitlines()]
    for line in _BOTH_LINES[target]:
        assert written.count(line) == 1, (source, target, line)


@pytest.mark.parametrize("source,shape", [("aruba_aoss", "e1"), ("dell_os10", "b")])
def test_junos_is_a_member_of_the_native(source: str, shape: str) -> None:
    job, final = _shape_job(source, shape, "juniper_junos")
    lead = f"set interfaces {final} "
    written = sorted(line.removeprefix(lead) for line in job.rendered.splitlines() if line.startswith(lead))
    assert "native-vlan-id 10" in written
    assert [line for line in written if _MEMBERS in line] == [
        f"{_MEMBERS} ten", f"{_MEMBERS} thirty", f"{_MEMBERS} twenty",
    ]


@pytest.mark.parametrize("source", sorted(codec for codec, how in HOW_IT_IS_STATED.items() if how == LIST))
def test_a_native_vlan_left_out_stays_out(source: str) -> None:
    """The other way.  Shape (b) onto the two targets that state the
    untagged VLAN apart: AOS-S is written no ``untagged`` for the
    port, ``no untagged`` in VLAN 1's stanza -- written for this tree,
    which has no VLAN 1, first and with no name -- and a line in VLAN
    10's stanza that says both; OS10 the line that takes the access
    VLAN back, under a line that says so."""
    job, final = _shape_job(source, "b", "aruba_aoss")
    assert not [
        line for line in job.rendered.splitlines()
        if line.strip().startswith("untagged") and final in _aoss_ports(line.split(None, 1)[1])
    ], job.rendered
    stanzas = list(_stanzas(job.rendered, "vlan "))
    assert stanzas[0] == ("1", [f"no untagged {final}", "exit"]), stanzas[0]
    ten = dict(stanzas)["10"]
    assert ten == ['name "ten"', SAID_TAKEN_OUT.format(port=final, native=10), "exit"], ten
    job, final = _shape_job(source, "b", "dell_os10")
    stanza = dict(_stanzas(job.rendered, "interface "))[final]
    at = stanza.index("no switchport access vlan")
    assert stanza[at - 1] == SAID_ON_OS10.format(native=10), stanza
    assert "switchport trunk allowed vlan 20,30" in stanza
    assert not [line for line in stanza if line.startswith("switchport access vlan")], stanza


# ---------------------------------------------------------------------------
# 4. The table the codecs read
# ---------------------------------------------------------------------------


def test_the_table_is_the_one_written_here() -> None:
    """Two places, on purpose: a correction to how a platform states
    it is made in the code's table AND here, beside what each shape
    then carries."""
    theirs = {LIST_DECIDES: LIST, BESIDE_THE_LIST: BESIDE}
    assert {codec: theirs[how] for codec, how in NATIVE_VLAN_AND_THE_LIST.items()} == HOW_IT_IS_STATED
    # ... and what a trunk has for a native VLAN when it states none.
    words = {NATIVE_NONE: None, NATIVE_OF_THE_SWITCH: NO_ID}
    assert {
        codec: words.get(vid, vid) for codec, vid in TRUNK_THAT_STATES_NO_NATIVE.items()
    } == WITH_NO_NATIVE_LINE
    assert all(type(vid) is int or vid in words for vid in TRUNK_THAT_STATES_NO_NATIVE.values())


def _in_one_table_only(*tables: dict) -> list[str]:
    """The codecs that are in one of *tables* and not in all of them."""
    everyone = set().union(*tables)
    return sorted(codec for codec in everyone if not all(codec in table for table in tables))


#: The three trunk tables of the codecs.
_TRUNK_TABLES = (NATIVE_VLAN_AND_THE_LIST, TRUNK_THAT_STATES_NO_LIST, TRUNK_THAT_STATES_NO_NATIVE)


def test_a_codec_is_in_every_table_or_none() -> None:
    """A codec whose parser can make a trunk states what a trunk with
    no list carries, how its text states the untagged VLAN, AND what
    a trunk with no native line has for one: the next codec cannot
    join one table without the others."""
    assert _in_one_table_only(*_TRUNK_TABLES) == []


def test_a_codec_in_one_table_is_reported() -> None:
    more = {**NATIVE_VLAN_AND_THE_LIST, "a_codec_nobody_listed": LIST_DECIDES}
    assert _in_one_table_only(more, TRUNK_THAT_STATES_NO_LIST) == ["a_codec_nobody_listed"]
    fewer = {codec: how for codec, how in NATIVE_VLAN_AND_THE_LIST.items() if codec != "dell_os10"}
    assert _in_one_table_only(fewer, TRUNK_THAT_STATES_NO_LIST) == ["dell_os10"]
    # Each of the three, with a codec the other two do not have and
    # without one they do.
    for n, table in enumerate(_TRUNK_TABLES):
        others = [other for m, other in enumerate(_TRUNK_TABLES) if m != n]
        assert _in_one_table_only({**table, "a_codec_nobody_listed": 0}, *others) == ["a_codec_nobody_listed"]
        short = {codec: value for codec, value in table.items() if codec != "juniper_junos"}
        assert _in_one_table_only(short, *others) == ["juniper_junos"]


def test_the_default_goes_where_the_list_is() -> None:
    """The helper the four parsers ask, and the one the three
    renderers ask: by hand."""
    for codec in HAVE_A_DEFAULT:
        assert unstated_native_vlan(codec, [1, 20, 30]) == 1, codec
        assert unstated_native_vlan(codec, list(range(1, 4095))) == 1, codec
        assert unstated_native_vlan(codec, [20, 30]) is None, codec
        assert unstated_native_vlan(codec, list(range(2, 4095))) is None, codec
        assert unstated_native_vlan(codec, []) is None, codec
    for codec in ("juniper_junos", "dell_os10"):
        assert unstated_native_vlan(codec, [1, 20, 30]) is None, codec
        assert unstated_native_vlan(codec, list(range(1, 4095))) is None, codec
    for codec in ("cisco_iosxe_cli", "arista_eos", "cisco_nxos"):
        # No line for the default where the list holds it ...
        assert switchport_trunk_native_value(codec, [1, 20, 30], 1) is None, codec
        assert switchport_trunk_native_value(codec, list(range(1, 4095)), 1) is None, codec
        assert switchport_trunk_native_value(codec, [1, 20, 30], None) is None, codec
        # ... the line for any other VLAN, and for VLAN 1 itself
        # where the list leaves it out (stated, and not carried).
        assert switchport_trunk_native_value(codec, [1, 20, 30], 20) == 20, codec
        assert switchport_trunk_native_value(codec, [20, 30], 1) == 1, codec
        assert switchport_trunk_native_value(codec, [], 1) == 1, codec
        assert switchport_trunk_native_value(codec, [20, 30], 10) == 10, codec
    with pytest.raises(KeyError):
        unstated_native_vlan("a_codec_nobody_listed", [1])
    with pytest.raises(KeyError):
        switchport_trunk_native_value("a_codec_nobody_listed", [1], 1)


def test_the_switches_are_who_makes_trunks() -> None:
    """Measured on the committed captures: the codecs whose parser
    makes a trunk are the six of the table and AOS-S, and no other."""
    makes: set[str] = set()
    for codec, _label, path in EVERY_CAPTURE:
        if codec in makes:
            continue
        tree = get_codec(codec).parse(path.read_text(encoding="utf-8"))
        if any(iface.switchport_mode == "trunk" for iface in tree.interfaces):
            makes.add(codec)
    assert {codec for codec, _label, _path in EVERY_CAPTURE} == set(list_public_codecs())
    assert makes == set(SWITCHES)


def test_beside_the_list_it_is_added() -> None:
    """What the parser of the platform beside adds, its renderer
    takes out, and the text is the same after both."""
    os10 = "dell_os10"
    assert HOW_IT_IS_STATED[os10] == BESIDE
    assert trunk_list_read(os10, [20, 30], 10) == [10, 20, 30]
    assert trunk_list_read(os10, [10, 30], 20) == [10, 20, 30]
    assert trunk_list_read(os10, [10, 20], 30) == [10, 20, 30]
    assert trunk_list_read(os10, [], 10) == [10]
    assert trunk_list_read(os10, list(range(2, 4095)), 1) == list(range(1, 4095))
    stated = [20, 30]
    assert trunk_list_read(os10, stated, None) is stated and trunk_list_read(os10, stated, 30) is stated
    assert list(trunk_list_written(os10, [10, 20, 30], 10)) == [20, 30]
    assert list(trunk_list_written(os10, [10, 20, 10], 10)) == [20]
    carried = [20, 30]
    # A native VLAN the list does not hold is not carried: nothing to take out.
    assert trunk_list_written(os10, carried, 10) is carried and trunk_list_written(os10, carried, None) is carried
    for stated in ([20, 30], [], [5, 20], list(range(11, 400))):
        assert list(trunk_list_written(os10, trunk_list_read(os10, stated, 10), 10)) == stated


def test_where_the_list_decides_as_stated() -> None:
    """The text of these platforms says what the tree says: nothing is
    added to a list that leaves its native VLAN out, and nothing is
    taken out of one that names it."""
    for codec, how in sorted(HOW_IT_IS_STATED.items()):
        if how != LIST:
            continue
        for listed in ([20, 30], [10, 20, 30], []):
            assert trunk_list_read(codec, listed, 10) is listed, codec
            assert trunk_list_written(codec, listed, 10) is listed, codec
    for helper in (trunk_list_read, trunk_list_written):
        with pytest.raises(KeyError):
            helper("a_codec_nobody_listed", [20, 30], 10)


# ---------------------------------------------------------------------------
# 5. The check itself, handed each defect
# ---------------------------------------------------------------------------


class TestTheCheckItself:
    """A check nobody has seen fail is not known to check anything.
    Jobs that are right, and then the same jobs with their output
    altered by hand, once for each thing the judgement is for."""

    def _judge(self, source: str, shape: str, target: Any, job: Any) -> dict[str, Any]:
        codec = target if not isinstance(target, str) else get_codec(target)
        return judge(get_codec(source), codec, SHAPES[(source, shape)], job)

    #: The name NX-OS is given for port 1 of the AOS-S source.
    E1 = "Ethernet0/1"

    @pytest.fixture()
    def onto_nxos(self) -> Any:
        """AOS-S (e1) onto NX-OS: untagged in 10, tagged in 20 and 30."""
        job, final = _shape_job("aruba_aoss", "e1", "cisco_nxos")
        assert final == self.E1
        for line in ("  switchport trunk native vlan 10\n", "  switchport trunk allowed vlan 10,20,30\n"):
            assert job.rendered.count(line) == 1, line
        return job

    def test_a_right_job_passes(self, onto_nxos: Any) -> None:
        verdict = self._judge("aruba_aoss", "e1", "cisco_nxos", onto_nxos)
        assert verdict["wrong"] == []
        assert dict(verdict["tally"]) == {"the same": 2, "carried by both": 2}
        assert not (set(verdict["tally"]) & set(NOT_THE_SAME))

    def test_the_native_vlan_left_off_the_list(self, onto_nxos: Any) -> None:
        """The defect, as it was written."""
        onto_nxos.rendered = onto_nxos.rendered.replace("allowed vlan 10,20,30", "allowed vlan 20,30")
        verdict = self._judge("aruba_aoss", "e1", "cisco_nxos", onto_nxos)
        assert verdict["wrong"] == [f"VLAN 10 untagged on '1' ('{self.E1}'): {LOST}"]

    def test_the_native_line_taken_out(self, onto_nxos: Any) -> None:
        onto_nxos.rendered = onto_nxos.rendered.replace("  switchport trunk native vlan 10\n", "")
        verdict = self._judge("aruba_aoss", "e1", "cisco_nxos", onto_nxos)
        assert verdict["wrong"] == [f"VLAN 10 untagged on '1' ('{self.E1}'): {TAGGED_INSTEAD}"]

    def test_another_native_vlan(self, onto_nxos: Any) -> None:
        onto_nxos.rendered = onto_nxos.rendered.replace("native vlan 10", "native vlan 30")
        verdict = self._judge("aruba_aoss", "e1", "cisco_nxos", onto_nxos)
        assert verdict["wrong"] == [
            f"VLAN 10 untagged on '1' ('{self.E1}'): {TAGGED_INSTEAD}",
            f"VLAN 30 untagged on '1' ('{self.E1}'): {WAS_TAGGED}",
        ]

    def test_no_list_where_that_is_no_vlan(self) -> None:
        """Junos: the native line and no member line is a trunk of no
        VLAN.  The same output read as IOS-XE would be every VLAN."""
        job, final = _shape_job("aruba_aoss", "e1", "juniper_junos")
        job.rendered = "\n".join(line for line in job.rendered.splitlines() if _MEMBERS not in line) + "\n"
        verdict = self._judge("aruba_aoss", "e1", "juniper_junos", job)
        assert f"VLAN 10 untagged on '1' ({final!r}): {LOST}" in verdict["wrong"]

    def test_a_parser_that_reads_a_missing_vlan(self, onto_nxos: Any) -> None:
        """A parser reads its own defaults.  One that put the native
        VLAN into the list it read would make the defect read as
        mended: the text says otherwise."""
        real = get_codec("cisco_nxos")

        class Fills:
            name = real.name
            port_names_case_sensitive = real.port_names_case_sensitive

            def parse(self, text: str) -> Any:
                tree = real.parse(text)
                for iface in tree.interfaces:
                    if iface.trunk_native_vlan is not None and iface.trunk_native_vlan not in iface.trunk_allowed_vlans:
                        iface.trunk_allowed_vlans = [iface.trunk_native_vlan, *iface.trunk_allowed_vlans]
                return tree

        onto_nxos.rendered = onto_nxos.rendered.replace("allowed vlan 10,20,30", "allowed vlan 20,30")
        verdict = self._judge("aruba_aoss", "e1", Fills(), onto_nxos)
        assert verdict["tally"]["readings disagree"] == 1
        assert len(verdict["wrong"]) == 2 and verdict["wrong"][1].endswith(LOST)

    def test_untagged_for_a_vlan_left_out(self) -> None:
        """The other way, onto AOS-S: IOS-XE (b) states native VLAN 10
        outside its list, and the output is given the line it was
        written."""
        job, final = _shape_job("cisco_iosxe_cli", "b", "aruba_aoss")
        assert self._judge("cisco_iosxe_cli", "b", "aruba_aoss", job)["wrong"] == []
        assert job.rendered.count('vlan 10\n   name "ten"\n   ; review: ') == 1, job.rendered
        job.rendered = job.rendered.replace(
            'vlan 10\n   name "ten"\n', f'vlan 10\n   name "ten"\n   untagged {final}\n',
        )
        verdict = self._judge("cisco_iosxe_cli", "b", "aruba_aoss", job)
        assert verdict["wrong"] == [f"VLAN 10 untagged on 'GigabitEthernet1/0/1' ({final!r}): {GAINED}"]

    #: IOS-XE: native VLAN 10 beside a list of NO VLAN.  Onto AOS-S the
    #: port is on no VLAN line, so nothing takes it out of VLAN 1, and
    #: the line in VLAN 10's stanza is the one for a port that stays
    #: there.
    KEPT_IN = _iosxe("switchport trunk native vlan 10", "switchport trunk allowed vlan none")

    def _said_job(self, kept_in: bool = False) -> tuple[Any, str, str]:
        """IOS-XE (b) onto AOS-S -- or :data:`KEPT_IN`, with *kept_in*
        -- and the one line of its output that says native VLAN 10 was
        left out of the trunk's list."""
        text = self.KEPT_IN if kept_in else SHAPES[("cisco_iosxe_cli", "b")]
        job, final = _job_of_a_port("cisco_iosxe_cli", text, "aruba_aoss")
        verdict = judge(get_codec("cisco_iosxe_cli"), get_codec("aruba_aoss"), text, job)
        assert verdict["wrong"] == [] and verdict["tally"][SAID] == 1
        assert verdict["tally"][f"said in the form for {PORT_FORM if kept_in else TAKEN_OUT_FORM}"] == 1
        lines = [line for line in job.rendered.splitlines(keepends=True) if "; review: port " in line]
        assert len(lines) == 1 and lines[0].startswith(f"   ; review: port {final} -- "), lines
        return job, final, lines[0]

    def _judge_said(self, job: Any, kept_in: bool = False) -> dict[str, Any]:
        text = self.KEPT_IN if kept_in else SHAPES[("cisco_iosxe_cli", "b")]
        return judge(get_codec("cisco_iosxe_cli"), get_codec("aruba_aoss"), text, job)

    def test_a_vlan_left_out_and_not_said(self) -> None:
        """The output that was written before the line was: tagged in
        20 and 30, untagged nowhere, and not a word."""
        job, _final, line = self._said_job()
        job.rendered = job.rendered.replace(line, "")
        verdict = self._judge("cisco_iosxe_cli", "b", "aruba_aoss", job)
        assert verdict["wrong"] == [f"native VLAN 10 of 'GigabitEthernet1/0/1', 0 lines: {NOT_SAID}"]

    def test_said_in_another_vlans_stanza(self) -> None:
        """The line under VLAN 20 is not where the port's untagged
        line would stand."""
        job, _final, line = self._said_job()
        job.rendered = job.rendered.replace(line, "").replace(
            'vlan 20\n   name "twenty"\n', 'vlan 20\n   name "twenty"\n' + line,
        )
        verdict = self._judge("cisco_iosxe_cli", "b", "aruba_aoss", job)
        assert verdict["wrong"] == [f"native VLAN 10 of 'GigabitEthernet1/0/1', 0 lines: {NOT_SAID}"]

    def test_said_of_another_port_or_twice(self) -> None:
        job, final, line = self._said_job(kept_in=True)
        other = line.replace(f"port {final} -- ", "port 2 -- ")
        said_of_two = job.rendered.replace(line, line + other)
        job.rendered = said_of_two
        verdict = self._judge_said(job, kept_in=True)
        assert verdict["wrong"] == ["VLAN 10, port '2': 1 review lines for a port whose source left nothing out"]
        job.rendered = said_of_two.replace(other, line)
        verdict = self._judge_said(job, kept_in=True)
        assert verdict["wrong"] == [f"native VLAN 10 of 'GigabitEthernet1/0/1', 2 lines: {NOT_SAID}"]

    @pytest.mark.parametrize("kept_in,old,new", [
        (True, "leaves it out, so no", "leaves it out (the source switch forwards no untagged frame on it), so no"),
        (True, "until it is removed -- ", "until it is removed, and a trunk group does the same -- "),
        (True, "default VLAN (VID 1)", "default VLAN (VID 1), untagged"),
        (False, "leaves it out, so no", "leaves it out (the source switch forwards no untagged frame on it), so no"),
        (False, "default VLAN -- ", "default VLAN, untagged and tagged -- "),
        (False, "taken out of the default VLAN", "taken out of the default VLAN (VID 1)"),
    ])
    def test_a_line_that_says_a_word_more(self, kept_in: bool, old: str, new: str) -> None:
        """The line with a claim added about the source switch, and
        with one added about the AOS-S switch or the output: neither
        is the line, so the VLAN is not said -- in the form for a port
        that stays in VLAN 1 and in the form for one taken out."""
        job, final, line = self._said_job(kept_in)
        assert old in line
        job.rendered = job.rendered.replace(line, line.replace(old, new))
        verdict = self._judge_said(job, kept_in)
        assert verdict["wrong"] == [
            f"native VLAN 10 of 'GigabitEthernet1/0/1', 0 lines: {NOT_SAID}",
            f"VLAN 10, port {final!r}: {NOT_THE_LINE}",
        ], (new, verdict["wrong"])

    def test_the_form_for_another_kind_of_name(self) -> None:
        """The line for a trunk group said of a port, the line for a
        port said of a port that the output's own ``trunk`` line puts
        in a group, and the line for a name taken out of VLAN 1 said of
        one that is not, and the other way."""
        job, final, line = self._said_job(kept_in=True)
        assert line.strip() == SAID_OF_A_PORT.format(port=final, native=10)
        for form, whole in ((GROUP_FORM, SAID_OF_A_GROUP), (TAKEN_OUT_FORM, SAID_TAKEN_OUT)):
            job.rendered = job.rendered.replace(line, "   " + whole.format(port=final, native=10) + "\n")
            verdict = self._judge_said(job, kept_in=True)
            assert verdict["wrong"] == [
                f"VLAN 10, port {final!r}: the line is the one for {form}, and {WRONG_FORM} {PORT_FORM}",
            ]
            job, final, line = self._said_job(kept_in=True)
        assert not in_a_trunk_line(job.rendered) and final == "1"
        job.rendered = job.rendered.replace("vlan 10\n", "trunk 1,7 trk1 lacp\nvlan 10\n", 1)
        assert in_a_trunk_line(job.rendered) == {"1", "7"}
        verdict = self._judge_said(job, kept_in=True)
        assert f"VLAN 10, port '1': the line is the one for {PORT_FORM}, and {WRONG_FORM} {GROUP_FORM}" in (
            verdict["wrong"]
        )
        # Taken out of VLAN 1, by the output's own `no untagged` line.
        job, final, line = self._said_job()
        assert line.strip() == SAID_TAKEN_OUT.format(port=final, native=10)
        assert out_of_vlan_1(job.rendered) == {final}
        job.rendered = job.rendered.replace(line, "   " + SAID_OF_A_PORT.format(port=final, native=10) + "\n")
        verdict = self._judge_said(job)
        assert verdict["wrong"] == [
            f"VLAN 10, port {final!r}: the line is the one for {PORT_FORM}, and {WRONG_FORM} {TAKEN_OUT_FORM}",
        ]

    def test_said_where_the_vlan_is_carried(self) -> None:
        """IOS-XE (a): the list names VLAN 10, the port is untagged
        in it, and a line that said otherwise would be false."""
        job, final = _shape_job("cisco_iosxe_cli", "a", "aruba_aoss")
        verdict = self._judge("cisco_iosxe_cli", "a", "aruba_aoss", job)
        assert verdict["wrong"] == [] and SAID not in verdict["tally"]
        _job, _final, line = self._said_job(kept_in=True)
        job.rendered = job.rendered.replace('vlan 10\n   name "ten"\n', 'vlan 10\n   name "ten"\n' + line)
        verdict = self._judge("cisco_iosxe_cli", "a", "aruba_aoss", job)
        assert verdict["wrong"] == [
            f"VLAN 10, port {final!r}: 1 review lines for a port whose source left nothing out",
        ]

    def test_an_access_vlan_for_a_vlan_left_out(self) -> None:
        """...and onto OS10, where it was written as the access VLAN."""
        job, final = _shape_job("cisco_iosxe_cli", "b", "dell_os10")
        assert self._judge("cisco_iosxe_cli", "b", "dell_os10", job)["wrong"] == []
        assert job.rendered.count(" no switchport access vlan\n") == 1
        job.rendered = job.rendered.replace(" no switchport access vlan\n", " switchport access vlan 10\n")
        verdict = self._judge("cisco_iosxe_cli", "b", "dell_os10", job)
        assert verdict["wrong"] == [f"VLAN 10 untagged on 'GigabitEthernet1/0/1' ({final!r}): {GAINED}"]

    def test_os10_with_a_vlan_on_both_lines(self) -> None:
        """The port still carries VLAN 10 untagged by either reading,
        so nothing else sees it."""
        job, final = _shape_job("aruba_aoss", "e1", "dell_os10")
        assert job.rendered.count(" switchport trunk allowed vlan 20,30\n") == 1
        job.rendered = job.rendered.replace("allowed vlan 20,30", "allowed vlan 10,20,30")
        verdict = self._judge("aruba_aoss", "e1", "dell_os10", job)
        assert verdict["wrong"] == [f"interface {final}: {BOTH_LINES}"]

    # -- a trunk that carries no VLAN untagged, onto OS10 and AOS-S ---

    #: IOS-XE (c): no native line, and a list that leaves VLAN 1 out --
    #: a trunk that carries no VLAN untagged.
    C = ("cisco_iosxe_cli", "c")

    def test_the_os10_line_taken_out(self) -> None:
        """The defect, as it was written onto OS10: the trunk with
        neither access line, which the switch makes an untagged member
        of its default VLAN.  The reader of text says so, the parser
        does not, and the trunk is left to the target's default."""
        job, final = _shape_job(*self.C, "dell_os10")
        verdict = self._judge(*self.C, "dell_os10", job)
        assert verdict["wrong"] == [] and verdict["tally"][SAID_ON_OS10_WHOLE] == 1
        lines = f" {said_of_none_on_os10(False)}\n no switchport access vlan\n"
        assert job.rendered.count(lines) == 1, job.rendered
        job.rendered = job.rendered.replace(lines, "")
        verdict = self._judge(*self.C, "dell_os10", job)
        port = final.casefold()
        assert verdict["wrong"] == [
            f"{port!r}: the parser reads Port(untagged=None, left_out=None, tagged=frozenset({{20, 30}}), "
            f"by_default=False) and the text Port(untagged={THE_SWITCHS_DEFAULT!r}, left_out=None, "
            f"tagged=frozenset({{20, 30}}), by_default=True)",
            f"VLAN {THE_SWITCHS_DEFAULT} untagged on 'GigabitEthernet1/0/1' ({final!r}): {NO_FORM_WRITTEN}",
        ], verdict["wrong"]
        assert verdict["tally"][TARGETS_DEFAULT] == 1

    def test_the_os10_line_without_its_review(self) -> None:
        """...and the line with its review line taken out, with a word
        more, or in the form for an allowed line it does not stand
        beside."""
        job, final = _shape_job(*self.C, "dell_os10")
        review = f" {said_of_none_on_os10(False)}\n"
        for new in (
            "",
            review.replace("disagree on", "disagree (10.5.5 and 10.6.1) on"),
            f" {said_of_none_on_os10(True)}\n",
        ):
            text = job.rendered
            job.rendered = text.replace(review, new)
            verdict = self._judge(*self.C, "dell_os10", job)
            assert verdict["wrong"] == [f"interface {final}: {UNSAID_ON_OS10}"], (new, verdict["wrong"])
            job.rendered = text
        # ... and where the allowed line holds VLAN 1, the form that
        # says so is the line, and the other is not.
        job, final = _shape_job("juniper_junos", "g", "dell_os10")
        assert self._judge("juniper_junos", "g", "dell_os10", job)["wrong"] == []
        assert job.rendered.count(f" {said_of_none_on_os10(True)}\n no switchport access vlan\n") == 1
        job.rendered = job.rendered.replace(said_of_none_on_os10(True), said_of_none_on_os10(False))
        assert self._judge("juniper_junos", "g", "dell_os10", job)["wrong"] == [f"interface {final}: {UNSAID_ON_OS10}"]

    def test_the_aoss_line_taken_out(self) -> None:
        """The defect, as it was written onto AOS-S: tagged in 20 and
        30, untagged nowhere, and no line takes the port out of VLAN 1
        -- in which, by HPE's sentence, it remains."""
        job, final = _shape_job(*self.C, "aruba_aoss")
        assert self._judge(*self.C, "aruba_aoss", job)["wrong"] == []
        stanza = f"vlan 1\n   no untagged {final}\n   exit\n"
        assert job.rendered.count(stanza) == 1, job.rendered
        job.rendered = job.rendered.replace(stanza, "")
        verdict = self._judge(*self.C, "aruba_aoss", job)
        assert verdict["wrong"] == [
            f"{final!r}: the parser reads Port(untagged=None, left_out=None, tagged=frozenset({{20, 30}}), "
            f"by_default=False) and the text Port(untagged=1, left_out=None, tagged=frozenset({{20, 30}}), "
            f"by_default=True)",
            f"VLAN 1 untagged on 'GigabitEthernet1/0/1' ({final!r}): {NO_FORM_WRITTEN}",
        ], verdict["wrong"]

    def test_the_aoss_tagged_line_taken_out(self) -> None:
        """Junos (g), a trunk of every VLAN, onto AOS-S, from a tree
        with no VLAN 1: the output's `vlan 1` stanza has the trunk on
        its `tagged` line.  Without the stanza the trunk is tagged in
        10, 20 and 30, untagged nowhere, and in VLAN 1 by default."""
        job, final = _shape_job("juniper_junos", "g", "aruba_aoss")
        assert self._judge("juniper_junos", "g", "aruba_aoss", job)["wrong"] == []
        stanzas = list(_stanzas(job.rendered, "vlan "))
        assert stanzas[0] == ("1", [f"tagged {final}", "exit"]), stanzas
        job.rendered = job.rendered.replace(f"vlan 1\n   tagged {final}\n   exit\n", "")
        verdict = self._judge("juniper_junos", "g", "aruba_aoss", job)
        assert f"VLAN 1 untagged on 'ge-0/0/1' ({final!r}): {NO_FORM_WRITTEN}" in verdict["wrong"], verdict["wrong"]
        assert verdict["tally"][TARGETS_DEFAULT] == 1

    def test_a_trunk_of_nothing_onto_aoss(self) -> None:
        """Junos (d): native VLAN 10 and no member line, a trunk that
        carries nothing.  AOS-S has no form for a port in no VLAN: the
        port is on no VLAN line, counted apart, and its review line is
        the one for a port that stays in VLAN 1."""
        job, final = _shape_job("juniper_junos", "d", "aruba_aoss")
        verdict = self._judge("juniper_junos", "d", "aruba_aoss", job)
        assert verdict["wrong"] == [] and verdict["tally"][ON_NO_VLAN_LINE] == 1, verdict
        assert verdict["tally"][f"said in the form for {PORT_FORM}"] == 1
        assert not out_of_vlan_1(job.rendered) and "vlan 1" not in job.rendered.splitlines()

    def test_a_fused_port_is_counted_apart(self, onto_nxos: Any) -> None:
        """...and what is counted there is pinned by cell."""
        onto_nxos.rendered = onto_nxos.rendered.replace("native vlan 10", "native vlan 30")
        onto_nxos.fused_ports = {self.E1: ["1", "9"]}
        verdict = self._judge("aruba_aoss", "e1", "cisco_nxos", onto_nxos)
        assert verdict["wrong"] == [] and verdict["tally"]["on a fused port"] == 2

    # -- a trunk that states no native VLAN ---------------------------

    #: IOS-XE (f): no native line, and a list that names VLAN 1.
    F = ("cisco_iosxe_cli", "f")

    def _onto(self, target: str) -> tuple[Any, str]:
        job, final = _shape_job(*self.F, target)
        assert self._judge(*self.F, target, job)["wrong"] == []
        return job, final

    def test_vlan_one_tagged_on_junos(self) -> None:
        """The defect, as it was written: a member of VLAN 1 like any
        other, and no ``native-vlan-id``."""
        job, final = self._onto("juniper_junos")
        line = f"set interfaces {final} native-vlan-id 1\n"
        assert job.rendered.count(line) == 1
        job.rendered = job.rendered.replace(line, "")
        verdict = self._judge(*self.F, "juniper_junos", job)
        assert verdict["wrong"] == [f"VLAN 1 untagged on 'GigabitEthernet1/0/1' ({final!r}): {TAGGED_INSTEAD}"]

    def test_vlan_one_tagged_on_os10(self) -> None:
        """...on OS10: VLAN 1 on the allowed line, and no access line --
        which makes the trunk an untagged member of the switch's
        default VLAN as well, an id no text gives: the parser reads it
        otherwise, and that is another untagged VLAN than the source's."""
        job, final = self._onto("dell_os10")
        was = " switchport access vlan 1\n switchport trunk allowed vlan 20,30\n"
        assert job.rendered.count(was) == 1, job.rendered
        job.rendered = job.rendered.replace(was, " switchport trunk allowed vlan 1,20,30\n")
        verdict = self._judge(*self.F, "dell_os10", job)
        assert verdict["wrong"] == [
            f"{final!r}: the parser reads Port(untagged=None, left_out=None, tagged=frozenset({{1, 20, 30}}), "
            f"by_default=False) and the text Port(untagged={THE_SWITCHS_DEFAULT!r}, left_out=None, "
            f"tagged=frozenset({{1, 20, 30}}), by_default=True)",
            f"VLAN 1 untagged on 'GigabitEthernet1/0/1' ({final!r}): {TAGGED_INSTEAD}",
            f"VLAN {THE_SWITCHS_DEFAULT} untagged on 'GigabitEthernet1/0/1' ({final!r}): {ANOTHER}",
        ], verdict["wrong"]

    def test_vlan_one_tagged_on_aoss(self) -> None:
        """...and on AOS-S: ``tagged`` in VLAN 1."""
        job, final = self._onto("aruba_aoss")
        assert job.rendered.count(f"   untagged {final}\n") == 1, job.rendered
        job.rendered = job.rendered.replace(f"   untagged {final}\n", f"   tagged {final}\n")
        verdict = self._judge(*self.F, "aruba_aoss", job)
        assert verdict["wrong"] == [f"VLAN 1 untagged on 'GigabitEthernet1/0/1' ({final!r}): {TAGGED_INSTEAD}"]

    @staticmethod
    def _forgets(name: str) -> Any:
        """The codec *name*, with a parser that puts no default: the
        native VLAN 1 of every port is taken out again."""
        real = get_codec(name)

        class Forgets:
            port_names_case_sensitive = real.port_names_case_sensitive

            def parse(self, text: str) -> Any:
                tree = real.parse(text)
                for iface in tree.interfaces:
                    if iface.trunk_native_vlan == 1:
                        iface.trunk_native_vlan = None
                for vlan in tree.vlans:
                    vlan.tagged_ports = sorted({*vlan.tagged_ports, *vlan.untagged_ports}) if vlan.id == 1 else (
                        vlan.tagged_ports
                    )
                    vlan.untagged_ports = [] if vlan.id == 1 else vlan.untagged_ports
                return tree

        Forgets.name = name
        return Forgets()

    @staticmethod
    def _fills_any_port(name: str) -> Any:
        """The codec *name*, with a parser that puts the default for
        any port whose list holds VLAN 1, whatever the port says of
        itself: the trunk's default, given to a port that is none."""
        real = get_codec(name)

        class FillsAnyPort:
            port_names_case_sensitive = real.port_names_case_sensitive

            def parse(self, text: str) -> Any:
                tree = real.parse(text)
                for iface in tree.interfaces:
                    if iface.trunk_native_vlan is None and 1 in iface.trunk_allowed_vlans:
                        iface.trunk_native_vlan = 1
                return tree

        FillsAnyPort.name = name
        return FillsAnyPort()

    def test_a_parser_that_fills_a_port_that_is_no_trunk(self) -> None:
        """The default given whatever the port's mode.  An EOS port
        with an access VLAN and a trunk line, which never says it
        is a trunk, would have native VLAN 1 in the tree, and be
        written VLAN 1 untagged wherever that is a line.  The tree
        is held to the text: who says it is a trunk is read there."""
        for source, what, port in (
            ("arista_eos", "an access VLAN, then the list", "Ethernet1"),
            ("cisco_nxos", "an access VLAN, then the list", "Ethernet1/1"),
            ("cisco_iosxe_cli", "mode dynamic auto, then the list", "GigabitEthernet1/0/1"),
        ):
            text, _made = WITH_A_TRUNK_LINE[(source, what)]
            job, _final = _job_of_a_port(source, text, "juniper_junos")
            right = judge(get_codec(source), get_codec("juniper_junos"), text, job)
            assert right["wrong"] == [] and NOT_OWED not in right["tally"], source
            verdict = judge(self._fills_any_port(source), get_codec("juniper_junos"), text, job)
            assert f"{port!r} of the source, read as {source}: {NOT_OWED}" in verdict["wrong"], verdict["wrong"]
            assert verdict["tally"][NOT_OWED] == 1, source
        # A trunk that says it is one is owed it, and a port that
        # states VLAN 1 as its native VLAN has it by its own line.
        text, _made = WITH_A_TRUNK_LINE[("arista_eos", "mode trunk, and the list")]
        tree = self._fills_any_port("arista_eos").parse(text)
        assert put_unasked(tree, "arista_eos", text) == []
        stated = _no_mode_line(_eos("switchport trunk native vlan 1", _THE_LIST))
        tree = get_codec("arista_eos").parse(stated)
        assert [iface.trunk_native_vlan for iface in tree.interfaces if iface.name == "Ethernet1"] == [1]
        assert put_unasked(tree, "arista_eos", stated) == [] == left_unfilled(tree, "arista_eos", stated)

    def test_who_says_it_is_a_trunk_is_read_from_the_text(self) -> None:
        """The two readers the rule above stands on, by hand."""
        text = (
            "interface A 1\n switchport mode trunk\ninterface b\n switchport trunk allowed vlan 1\n"
            "interface C\n description switchport mode trunk\n switchport trunk native vlan 7\n"
            "interface D\n switchport mode access\ninterface D\n switchport mode trunk\n"
        )
        assert says_it_is_a_trunk(text, "cisco_nxos") == {"a1", "d"}
        assert states_a_native_vlan(text) == {"c"}
        cx = (
            "interface 1/1/1\n    vlan trunk allowed 1,10\ninterface lag 1 multi-chassis\n    vlan trunk native 5 tag\n"
            "interface 1/1/2\n    vlan access 10\ninterface 1/1/3\n    description vlan trunk native 5\n"
        )
        assert says_it_is_a_trunk(cx, "aruba_aoscx") == {"1/1/1", "lag1"}
        assert states_a_native_vlan(cx) == {"lag1"}
        # ``switchport mode trunk`` is no AOS-CX line, and a ``vlan
        # trunk`` line no statement on the other three.
        assert says_it_is_a_trunk(text, "aruba_aoscx") == set() == says_it_is_a_trunk(cx, "arista_eos")

    def test_a_source_parser_that_puts_no_default(self) -> None:
        """The parser as it was: the trunk has no native VLAN in the
        tree, and VLAN 1 is a tagged VLAN of it.  The tree is held to
        its platform's default before anything is compared."""
        job, _final = self._onto("juniper_junos")
        verdict = judge(self._forgets("cisco_iosxe_cli"), get_codec("juniper_junos"), SHAPES[self.F], job)
        assert f"'GigabitEthernet1/0/1' of the source, read as cisco_iosxe_cli: {NOT_FILLED}" in verdict["wrong"]
        assert verdict["tally"][NOT_FILLED] == 1

    def test_a_target_parser_that_puts_no_default(self) -> None:
        """...and the output parsed again: a parser that read its own
        trunk with no native line as carrying nothing untagged would
        agree with a renderer that wrote none, and the text says
        otherwise."""
        job, final = self._onto("cisco_nxos")
        verdict = judge(get_codec("cisco_iosxe_cli"), self._forgets("cisco_nxos"), SHAPES[self.F], job)
        assert f"{final!r} of the output, read as cisco_nxos: {NOT_FILLED}" in verdict["wrong"]
        assert verdict["tally"]["readings disagree"] == 1

    def test_under_the_words_nothing_is_owed(self) -> None:
        """A trunk under ``vlan dot1q tag native`` has no native VLAN
        in the tree and VLAN 1 on its list, and that is the tree it
        should have: the same tree without the words is one the
        default was left out of."""
        for shape in ("t", "u", "x"):
            text = SHAPES[("cisco_nxos", shape)]
            tree = get_codec("cisco_nxos").parse(text)
            trunk = next(iface for iface in tree.interfaces if iface.name == "Ethernet1/1")
            assert (trunk.trunk_native_vlan, trunk.trunk_allowed_vlans) == (None, [1, 20, 30]), shape
            assert left_unfilled(tree, "cisco_nxos", text) == [], shape
            assert left_unfilled(tree, "cisco_nxos", SHAPES[("cisco_nxos", "f")]) == ["Ethernet1/1"], shape
        # No default to leave out, whatever the tree: Junos has none,
        # and OS10's is not an id.
        for codec in ("juniper_junos", "dell_os10"):
            assert left_unfilled(tree, codec, "") == []
        assert says_tagged(
            "vlan dot1q tag native\ninterface A 1\n switchport trunk native vlan tag\n", "cisco_nxos",
        ) == (True, {"A1": True})
        assert says_tagged(
            "interface A\n description vlan dot1q tag native\n switchport trunk native vlan 9\n", "cisco_nxos",
        ) == (False, {})
        # Each platform's grammar: a port that leaves the line for every
        # trunk (IOS-XE, NX-OS); on EOS the id after `tag`, which stands,
        # and no `no` line; on AOS-CX the word on the native line, which
        # a later line without it is read as leaving on (what it does
        # is not established; HPE removes tagging by the `no` form).
        text = (
            "vlan dot1q tag native exclude control\ninterface A\n no switchport trunk native vlan tag\n"
            "interface B\n switchport trunk native vlan tag\n switchport trunk native vlan 9\n"
        )
        assert says_tagged(text, "cisco_iosxe_cli") == (True, {"A": False, "B": True})
        assert says_tagged(text, "arista_eos") == (True, {"B": False})
        assert says_tagged(text, "dell_os10") == says_tagged(text, "juniper_junos") == (False, {})
        cx = (
            "vlan dot1q tag native\ninterface lag 1 multi-chassis\n    vlan trunk native 5 tag\n"
            "    vlan trunk native 5\n"
        )
        assert says_tagged(cx, "aruba_aoscx") == (False, {"lag1": True})
        # ... and a trunk that leaves the line is owed its default.
        text = SHAPES[("cisco_nxos", "o")]
        tree = get_codec("cisco_nxos").parse(text)
        trunk = next(iface for iface in tree.interfaces if iface.name == "Ethernet1/1")
        assert trunk.trunk_native_vlan == 1 and left_unfilled(tree, "cisco_nxos", text) == []
        trunk.trunk_native_vlan = None
        assert left_unfilled(tree, "cisco_nxos", text) == ["Ethernet1/1"]

    def test_a_native_line_in_another_stanza(self) -> None:
        """An interface whose stanza is in the text twice states its
        native VLAN once: the record of the other stanza is owed no
        default, and the port carries what the interface states."""
        text = _iosxe("switchport trunk native vlan 30", "switchport trunk allowed vlan 1,20,30").replace(
            "end\n", "interface GigabitEthernet1/0/1\n description again\n!\nend\n",
        )
        tree = get_codec("cisco_iosxe_cli").parse(text)
        records = [iface for iface in tree.interfaces if iface.name == "GigabitEthernet1/0/1"]
        assert [iface.trunk_native_vlan for iface in records] == [30, None]
        assert left_unfilled(tree, "cisco_iosxe_cli", text) == []
        for ports in (read_tree(tree, "cisco_iosxe_cli"), read_text(text, "cisco_iosxe_cli")):
            assert ports["GigabitEthernet1/0/1"].untagged == 30

    def test_the_targets_default_is_no_excuse(self) -> None:
        """Junos (g), a trunk of every VLAN with no native VLAN, onto
        IOS-XE: written the line for every trunk, and the port carries
        VLAN 1 tagged.  Without the line the port is left to the
        target's default, which is a fault unless its stanza says so in
        the review line -- and with that line it is counted, and not
        complained of.  The same output with a native line STATED is
        another thing: a statement the source did not make, and a
        review line on a port that is not left to the default."""
        source = ("juniper_junos", "g")
        job, final = _shape_job(*source, "cisco_iosxe_cli")
        verdict = self._judge(*source, "cisco_iosxe_cli", job)
        assert verdict["wrong"] == [] and TARGETS_DEFAULT not in verdict["tally"]
        every = "vlan dot1q tag native\n"
        assert job.rendered.count(every) == 1
        job.rendered = job.rendered.replace(every, "")
        verdict = self._judge(*source, "cisco_iosxe_cli", job)
        assert verdict["wrong"] == [f"VLAN 1 untagged on 'ge-0/0/1' ({final!r}), 0 lines: {DEFAULT_NOT_SAID}"]
        mode = " switchport mode trunk\n"
        assert job.rendered.count(mode) == 1
        said = job.rendered.replace(mode, f"{mode} {SAID_OF_NO_UNTAGGED['cisco_iosxe_cli']}\n")
        job.rendered = said
        verdict = self._judge(*source, "cisco_iosxe_cli", job)
        assert verdict["wrong"] == [] and verdict["tally"][TARGETS_DEFAULT] == verdict["tally"][DEFAULT_SAID] == 1
        port = final.casefold()
        for native in (1, 30):
            job.rendered = said.replace(mode, f"{mode} switchport trunk native vlan {native}\n")
            verdict = self._judge(*source, "cisco_iosxe_cli", job)
            assert verdict["wrong"] == [
                f"VLAN {native} untagged on 'ge-0/0/1' ({final!r}): {WAS_TAGGED}", f"{port!r}: {SAID_OF_ANOTHER}",
            ], native
            assert TARGETS_DEFAULT not in verdict["tally"]

    def test_a_review_line_that_is_not_the_line(self) -> None:
        """IOS-XE's trunk with no untagged VLAN beside one that carries
        VLAN 10, onto NX-OS: the line with a word more, the line twice,
        and the line in the other trunk's stanza."""
        job, first, third = _beside_job("cisco_iosxe_cli", "cisco_nxos")
        line = f"  {SAID_OF_NO_UNTAGGED['cisco_nxos']}\n"
        assert job.rendered.count(line) == 1
        right = job.rendered
        source = get_codec("cisco_iosxe_cli")

        def judged(text: str) -> list[str]:
            job.rendered = text
            return judge(source, get_codec("cisco_nxos"), TWO_TRUNKS["cisco_iosxe_cli"], job)["wrong"]

        assert judged(right) == []
        one, other = first.casefold(), third.casefold()
        more = line.replace("would tag it,", "would tag it (the source sent VLAN 1 tagged),")
        assert judged(right.replace(line, more)) == [
            f"VLAN 1 untagged on 'GigabitEthernet1/0/1' ({first!r}), 1 lines: {DEFAULT_NOT_SAID}",
        ]
        assert judged(right.replace(line, line + line)) == [
            f"VLAN 1 untagged on 'GigabitEthernet1/0/1' ({first!r}), 2 lines: {DEFAULT_NOT_SAID}",
        ]
        mode = "  switchport mode trunk\n  switchport trunk native vlan 10\n"
        assert right.count(mode) == 1
        moved = right.replace(line, "").replace(mode, mode + line)
        assert judged(moved) == [
            f"VLAN 1 untagged on 'GigabitEthernet1/0/1' ({first!r}), 0 lines: {DEFAULT_NOT_SAID}",
            f"{other!r}: {SAID_OF_ANOTHER}",
        ]
        assert one != other

    def test_the_line_beside_an_untagged_trunk(self) -> None:
        """The same output with ``vlan dot1q tag native`` written: it
        tags the third trunk's native VLAN as well, and the first is
        not left to a default, so its review line is no longer so."""
        job, first, third = _beside_job("cisco_iosxe_cli", "cisco_nxos")
        job.rendered = job.rendered.replace("\ninterface ", "\nvlan dot1q tag native\ninterface ", 1)
        assert job.rendered.count("vlan dot1q tag native\n") == 1
        verdict = judge(get_codec("cisco_iosxe_cli"), get_codec("cisco_nxos"), TWO_TRUNKS["cisco_iosxe_cli"], job)
        assert verdict["wrong"] == [
            f"VLAN 10 untagged on 'GigabitEthernet1/0/3' ({third!r}): {TAGGED_INSTEAD}",
            f"{first.casefold()!r}: {SAID_OF_ANOTHER}",
        ], verdict["wrong"]

    @pytest.mark.parametrize("target,form", [
        ("arista_eos", "   switchport trunk native vlan tag\n"), ("aruba_aoscx", "    vlan trunk native 1 tag\n"),
    ])
    def test_a_form_taken_out(self, target: str, form: str) -> None:
        """Junos (g) onto EOS and AOS-CX, with the port's form for no
        untagged VLAN taken out: VLAN 1 untagged by the target's own
        default, on a target that has a form for none.  And on AOS-CX
        with the word ``tag`` taken out: a statement the source did
        not make."""
        source = ("juniper_junos", "g")
        job, final = _shape_job(*source, target)
        assert self._judge(*source, target, job)["wrong"] == [] and job.rendered.count(form) == 1
        right = job.rendered
        job.rendered = right.replace(form, "")
        assert self._judge(*source, target, job)["wrong"] == [
            f"VLAN 1 untagged on 'ge-0/0/1' ({final!r}): {NO_FORM_WRITTEN}",
        ]
        if target == "aruba_aoscx":
            job.rendered = right.replace(form, form.replace(" tag\n", "\n"))
            assert self._judge(*source, target, job)["wrong"] == [
                f"VLAN 1 untagged on 'ge-0/0/1' ({final!r}): {WAS_TAGGED}",
            ]

    def test_a_parser_keeps_a_tagged_native(self) -> None:
        """An AOS-CX parser that read ``vlan trunk native 1 tag`` as
        native VLAN 1, untagged, as it once did: the source's tree is
        held to its text, which says the VLAN is sent tagged."""
        real = get_codec("aruba_aoscx")

        class Keeps:
            name = real.name
            port_names_case_sensitive = real.port_names_case_sensitive

            def parse(self, text: str) -> Any:
                tree = real.parse(text)
                for iface in tree.interfaces:
                    if iface.switchport_mode == "trunk" and iface.trunk_native_vlan is None:
                        iface.trunk_native_vlan = 1
                return tree

        job, _final = _shape_job("aruba_aoscx", "t", "juniper_junos")
        assert self._judge("aruba_aoscx", "t", "juniper_junos", job)["wrong"] == []
        verdict = judge(Keeps(), get_codec("juniper_junos"), SHAPES[("aruba_aoscx", "t")], job)
        assert f"'1/1/1' of the source, read as aruba_aoscx: {KEPT_TAGGED}" in verdict["wrong"], verdict["wrong"]
        assert verdict["tally"][KEPT_TAGGED] == 1

    def test_the_default_in_place_of_a_native_vlan(self) -> None:
        """...and it is counted apart only for a port whose source
        carries NOTHING untagged.  An output that lost the native line
        of a trunk whose list names VLAN 1 has VLAN 1 untagged by the
        same default -- on a port whose source carries VLAN 10
        untagged.  That is a lost untagged VLAN, and is said."""
        text = _nxos("switchport trunk native vlan 10", "switchport trunk allowed vlan 1,10,20,30")
        source, target = get_codec("cisco_nxos"), get_codec("cisco_iosxe_cli")
        job = _run("cisco_nxos", "cisco_iosxe_cli", text)
        assert judge(source, target, text, job)["wrong"] == []
        line = " switchport trunk native vlan 10\n"
        assert job.rendered.count(line) == 1, job.rendered
        job.rendered = job.rendered.replace(line, "")
        final = job.port_renames.get("Ethernet1/1", "Ethernet1/1")
        verdict = judge(source, target, text, job)
        assert verdict["wrong"] == [
            f"VLAN 10 untagged on 'Ethernet1/1' ({final!r}): {TAGGED_INSTEAD}",
            f"VLAN 1 untagged on 'Ethernet1/1' ({final!r}): {WAS_TAGGED}",
        ]
        assert TARGETS_DEFAULT not in verdict["tally"]

    def test_each_row_reads_its_own_way(self) -> None:
        """One stanza, two platforms: where the list decides, the
        native VLAN beside `20,30` is left out; beside the list, the
        access VLAN beside `20,30` is carried."""
        stanza = "interface X\n switchport mode trunk\n{}\n switchport trunk allowed vlan 20,30\n"
        ios = read_text(stanza.format(" switchport trunk native vlan 10"), "cisco_iosxe_cli")["X"]
        assert (ios.untagged, ios.left_out, ios.tagged) == (None, 10, frozenset({20, 30}))
        os10 = read_text(stanza.format(" switchport access vlan 10"), "dell_os10")["X"]
        assert (os10.untagged, os10.left_out, os10.tagged) == (10, None, frozenset({20, 30}))
        # No allowed line: every VLAN on IOS-XE, no tagged VLAN on OS10.
        bare = "interface X\n switchport mode trunk\n{}\n"
        assert read_text(bare.format(" switchport trunk native vlan 10"), "cisco_iosxe_cli")["X"].untagged == 10
        assert read_text(bare.format(" switchport access vlan 10"), "dell_os10")["X"] == Port(10, None, frozenset())
        # Junos: a native line and no member line is no VLAN at all.
        junos = read_text(
            "set interfaces a unit 0 family ethernet-switching interface-mode trunk\n"
            "set interfaces a native-vlan-id 10\n", "juniper_junos",
        )["a"]
        assert (junos.untagged, junos.left_out) == (None, 10)
        # AOS-CX: a native line alone is every VLAN, and `tag` sends the
        # native VLAN tagged -- none untagged, and no default -- and a
        # later line without the word is read as leaving the tagging on
        # (what it does is not established).
        assert read_text("interface 1/1/1\n    vlan trunk native 10\n", "aruba_aoscx")["1/1/1"].untagged == 10
        for after in ("", "    vlan trunk native 10\n"):
            cx = read_text("interface 1/1/1\n    vlan trunk native 10 tag\n" + after, "aruba_aoscx")["1/1/1"]
            assert (cx.untagged, cx.tagged, cx.by_default) == (None, ALL, False), after
        # No native line: VLAN 1 on four platforms, where the list
        # holds it -- and that it is the platform's own, not a line.
        bare = "interface X\n switchport mode trunk\n"
        for codec in ("cisco_iosxe_cli", "arista_eos", "cisco_nxos"):
            assert read_text(bare, codec)["X"] == Port(1, None, ALL, True), codec
            listed = read_text(bare + " switchport trunk allowed vlan 1,20\n", codec)["X"]
            assert listed == Port(1, None, frozenset({20}), True), codec
            off = read_text(bare + " switchport trunk allowed vlan 20,30\n", codec)["X"]
            assert off == Port(None, None, frozenset({20, 30})), codec
            stated = read_text(bare + " switchport trunk native vlan 1\n", codec)["X"]
            assert stated == Port(1, None, ALL, False), codec
            # ... and not under the words that tag it, of one port or of all.
            assert read_text(bare + " switchport trunk native vlan tag\n", codec)["X"].untagged is None, codec
            assert read_text("vlan dot1q tag native\n" + bare, codec)["X"].untagged is None, codec
            assert read_text("vlan dot1q tag native exclude control\n" + bare, codec)["X"].untagged is None, codec
            # A port that leaves the line for every trunk has its default
            # again (IOS-XE and NX-OS; EOS has no such line).  A native
            # VLAN stated under the line is sent tagged, and on EOS an id
            # stated after `tag` stands.
            out = read_text("vlan dot1q tag native\n" + bare + " no switchport trunk native vlan tag\n", codec)["X"]
            assert (out.untagged, out.by_default) == ((None, False) if codec == "arista_eos" else (1, True)), codec
            under = read_text("vlan dot1q tag native\n" + bare + " switchport trunk native vlan 10\n", codec)["X"]
            assert under.untagged == (10 if codec == "arista_eos" else None), codec
            later = read_text(bare + f" {_ITS_NATIVE_IS_TAGGED}\n switchport trunk native vlan 10\n", codec)["X"]
            assert later.untagged == (10 if codec == "arista_eos" else None), codec
        assert read_text("interface 1/1/1\n    vlan trunk allowed 1,20\n", "aruba_aoscx")["1/1/1"] == Port(
            1, None, frozenset({20}), True,
        )
        assert read_text("interface 1/1/1\n    vlan trunk allowed 20\n", "aruba_aoscx")["1/1/1"].untagged is None
        # Junos has no default, and OS10's has no id: a trunk with
        # neither access line is in the switch's default VLAN, so the
        # reader says, and one that takes the access VLAN back is not
        # -- whichever line came first.
        junos = read_text(
            "set vlans one vlan-id 1\nset interfaces a unit 0 family ethernet-switching interface-mode trunk\n"
            "set interfaces a unit 0 family ethernet-switching vlan members one\n", "juniper_junos",
        )["a"]
        assert junos == Port(None, None, frozenset({1}))
        assert read_text(bare + " switchport trunk allowed vlan 1,20\n", "dell_os10")["X"] == Port(
            THE_SWITCHS_DEFAULT, None, frozenset({1, 20}), True,
        )
        assert read_text(bare, "dell_os10")["X"] == Port(THE_SWITCHS_DEFAULT, None, frozenset(), True)
        taken = read_text(bare + " no switchport access vlan\n switchport trunk allowed vlan 1,20\n", "dell_os10")
        assert taken["X"] == Port(None, None, frozenset({1, 20}))
        again = read_text(bare + " no switchport access vlan\n switchport access vlan 10\n", "dell_os10")
        assert again["X"] == Port(10, None, frozenset())
        # ... and in a second stanza of the interface, as OS10 applies it.
        twice = read_text(bare + " switchport access vlan 10\ninterface X\n no switchport access vlan\n", "dell_os10")
        assert twice["X"] == Port(None, None, frozenset())
        # AOS-S: the last `untagged` stands, and `no untagged` takes it back.
        aoss = read_text(
            "vlan 1\n   untagged 1-3\n   exit\nvlan 10\n   untagged 2\n   tagged 1\n   no untagged 3\n   exit\n"
            "vlan 20\n   tagged 1-2\n   exit\nvlan 1\n   no untagged 3\n   exit\n", "aruba_aoss",
        )
        assert aoss["1"] == Port(1, None, frozenset({10, 20})) and aoss["2"] == Port(10, None, frozenset({20}))
        assert "3" not in aoss
        # ... and a port tagged somewhere, untagged nowhere and on no
        # line of VLAN 1 is in VLAN 1 by default; one VLAN 1 takes out,
        # or tags, is not -- above its other lines or below them, a port
        # or a trunk group -- and a name on no VLAN line is no port here.
        aoss = read_text(
            "vlan 1\n   no untagged 4,Trk1\n   untagged 9\n   tagged 6\n   no untagged 7\n   exit\n"
            "vlan 10\n   tagged 3-8,Trk1-Trk2\n   exit\n", "aruba_aoss",
        )
        tagged = frozenset({10})
        assert {name: aoss[name] for name in ("3", "5", "Trk2")} == {
            name: Port(1, None, tagged, True) for name in ("3", "5", "Trk2")
        }
        assert {name: aoss[name] for name in ("4", "7", "8", "Trk1")} == {
            "4": Port(None, None, tagged), "7": Port(None, None, tagged), "8": Port(1, None, tagged, True),
            "Trk1": Port(None, None, tagged),
        }
        assert aoss["6"] == Port(None, None, frozenset({1, 10})) and aoss["9"] == Port(1, None, frozenset())
        assert "2" not in aoss

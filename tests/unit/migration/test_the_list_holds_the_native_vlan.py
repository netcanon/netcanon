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
* **left out, and not said**, onto AOS-S: the source states a native
  VLAN its list leaves out, the output writes no ``untagged`` line
  for the port, and no ``; review:`` line in that VLAN's stanza says
  so.  (By HPE's sentences an AOS-S port is in the default VLAN until
  it is removed from it, so an output that says nothing is not known
  to be one that carries nothing.)  The line is held WHOLE, in the
  two forms typed below (:data:`SAID_OF_A_PORT`,
  :data:`SAID_OF_A_GROUP`): a line that says a word more is not the
  line, and neither is the form for a port on a trunk group or on a
  port the output's own ``trunk`` line names.

A port the output states nothing for is not judged here: every
membership of every port is accounted for, one by one, in
``test_vlan_members_reach_the_output.py``.

Small configs carry each shape through every pair -- the native VLAN
in the list, outside it, not stated, stated with no list, and the
three an AOS-S port can be -- and what each source carries is written
beside it by hand.

What this cannot see
--------------------
Nothing is filled in that a text does not state.  A trunk that states
no native VLAN carries none here, on either side, and so does a port
whose ``untagged`` line was not written -- though IOS-XE, EOS, NX-OS and
AOS-CX then use VLAN 1, an OS10 trunk its default VLAN, and an AOS-S
port is in the default VLAN, VLAN 1, until it is removed from it.
Whether a target ACCEPTS a line is
nobody's to say from here, and neither is what ``no switchport access
vlan`` leaves an OS10 trunk with: it is read as no untagged VLAN, and
Dell's pages do not agree that it is.  A Junos trunk in the older
grammar (``port-mode trunk``) is read as an ELS one.  And a VLAN
device on FortiOS, RouterOS or OPNsense is read by no reader of this
module: those targets write the untagged VLAN as a tagged device.
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
    NATIVE_VLAN_AND_THE_LIST,
    TRUNK_THAT_STATES_NO_LIST,
    trunk_list_read,
    trunk_list_written,
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

ALL = "all"


class Port(NamedTuple):
    """What a device carries on one port, as its text states it."""

    untagged: int | None        # the VLAN it carries untagged
    left_out: int | None        # a native VLAN it states and its list leaves out
    tagged: Any                 # ``ALL``, or the ids it carries tagged

    def carries_tagged(self, vid: int) -> bool:
        return vid != self.untagged and (self.tagged == ALL or vid in self.tagged)


def _port(how: str, mode: str | None, access: int | None, native: int | None, allowed: Any) -> Port | None:
    """One port's statements, read by its platform's row.  *allowed* is
    ``ALL`` or a set of ids: what the allowed line names, or what the
    platform's trunk carries with no such line."""
    if mode == "access":
        return Port(access, None, frozenset())
    if mode != "trunk":
        return None
    held = native is not None and (how == BESIDE or allowed == ALL or native in allowed)
    untagged = native if held else None
    left_out = native if native is not None and not held else None
    return Port(untagged, left_out, allowed if allowed == ALL else frozenset(allowed) - {untagged})


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
    out: dict[str, Port] = {}
    for iface in tree.interfaces:
        port = _port(
            HOW_IT_IS_STATED[codec], iface.switchport_mode, iface.access_vlan,
            iface.trunk_native_vlan, _listed(iface.trunk_allowed_vlans),
        )
        if port is not None:
            out[iface.name] = port
    return out


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


def _read_switchport(text: str, codec: str) -> dict[str, Port]:
    """IOS-XE, EOS, NX-OS and OS10.  On OS10 the untagged VLAN of a
    trunk is its ``switchport access vlan``, which ``no switchport
    access vlan`` takes back."""
    out: dict[str, Port] = {}
    for name, body in _stanzas(text, "interface "):
        mode = access = native = None
        allowed: Any = None
        for line in body:
            if line in ("switchport mode trunk", "switchport mode access"):
                mode = line.rsplit(" ", 1)[1]
            elif m := re.fullmatch(r"switchport access vlan (\d+)", line):
                access = int(m.group(1))
            elif line == "no switchport access vlan":
                access = None
            elif m := re.fullmatch(r"switchport trunk native vlan (\d+)", line):
                native = int(m.group(1))
            elif m := re.fullmatch(r"switchport trunk allowed vlan (add )?(\S+)", line):
                word = m.group(2)
                more = frozenset() if word == "none" else ALL if word == "all" else _ids(word)
                if ALL in (more, allowed):
                    allowed = ALL
                else:
                    allowed = _listed(more | (allowed or set()) if m.group(1) else more)
        if mode is None and access is not None:
            mode = "access"            # EOS, NX-OS and OS10 print no mode line for one
        if codec == "dell_os10":
            if mode == "trunk":
                native, allowed = access, allowed if allowed is not None else frozenset()
        elif allowed is None:
            allowed = ALL
        port = _port(HOW_IT_IS_STATED[codec], mode, access, native, allowed)
        if port is not None:
            out[name] = port
    return out


def _read_aoscx(text: str) -> dict[str, Port]:
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
        port = _port(LIST, mode, access, native, allowed if allowed is not None else ALL)
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
    untagged: dict[str, int] = {}     # a port is untagged in ONE VLAN: the last that says so
    tagged: dict[str, set[int]] = collections.defaultdict(set)
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
            elif m := re.fullmatch(r"no untagged (\S+)", line):
                for port in _aoss_ports(m.group(1)):
                    if untagged.get(port) == vid:
                        del untagged[port]
    return {
        name: Port(untagged.get(name), None, frozenset(tagged.get(name, ())))
        for name in set(untagged) | set(tagged)
    }


#: The ``; review:`` line of an AOS-S output for a trunk whose list
#: leaves its native VLAN out, WHOLE, in its two forms.  Typed here
#: and taken from no renderer, so that a line which says a word more
#: is not this line.  What they say of the switch is all that was
#: found: for a port, HPE's two sentences (a port is in the default
#: VLAN, and remains in it until it is removed -- neither says
#: "untagged"); for a trunk group and for a port that is in one,
#: nothing, and the line says "not established".  Neither calls the
#: VLAN the source's: after a VLAN map the id is the output's.
SAID_OF_A_PORT = (
    "; review: port {port} -- native VLAN {native} is stated for this trunk and its allowed list leaves it out, "
    "so no untagged line is written for this port; in the factory default configuration an AOS-S port is in the "
    "default VLAN (VID 1), and it remains there until it is removed -- check what this port is to carry untagged"
)
SAID_OF_A_GROUP = (
    "; review: port {port} -- native VLAN {native} is stated for this trunk and its allowed list leaves it out, "
    "so no untagged line is written for this port; which VLAN an AOS-S trunk group, or a port that is in one, is "
    "in by default is not established -- check what this port is to carry untagged"
)

#: ...and the line of an OS10 output, which stands above ``no
#: switchport access vlan``.  It says that Dell's pages DISAGREE on
#: what that line leaves a trunk with, and names both readings.
SAID_ON_OS10 = (
    "! review: native VLAN {native} is stated for this trunk and its allowed list leaves it out, so no untagged "
    "VLAN is written for this port; Dell's pages disagree on whether the next line leaves an OS10 trunk with no "
    "untagged VLAN or with VLAN 1 -- check what this port is to carry untagged"
)

PORT_FORM, GROUP_FORM = "a port", "a trunk group or a port of one"
_FORMS = ((PORT_FORM, SAID_OF_A_PORT), (GROUP_FORM, SAID_OF_A_GROUP))

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
BOTH_LINES = "a VLAN on the access line and on the allowed line"
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

    src = read_tree(source.parse(raw), source.name)
    by_parser = {key(name): port for name, port in read_tree(target.parse(job.rendered), target.name).items()}
    by_text = {key(name): port for name, port in read_text(job.rendered, target.name).items()}
    tally: collections.Counter[str] = collections.Counter()
    wrong: list[str] = []
    if target.name == "dell_os10":
        for name in on_both_lines(job.rendered):
            tally[BOTH_LINES] += 1
            wrong.append(f"interface {name}: {BOTH_LINES}")
    for name in sorted(set(by_parser) | set(by_text)):
        one, two = by_parser.get(name), by_text.get(name)
        if (one and (one.untagged, one.left_out)) != (two and (two.untagged, two.left_out)):
            tally["readings disagree"] += 1
            wrong.append(f"{name!r}: the parser reads {one} and the text {two}")

    dropped = set(job.port_drops)
    fused = {name for names in job.fused_ports.values() for name in names}
    # Onto AOS-S, a native VLAN the source's list leaves out is said:
    # one line, in that VLAN's stanza, for each port the output has.
    # (A port the job dropped for want of a name is not in the output,
    # and the job lists it.)
    if target.name in VLAN_BY_VLAN:
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
        # ... and each line is one of the two forms, whole, and the
        # form for what the OUTPUT makes of the name: a trunk group
        # by its name, a port of one by the output's own `trunk`
        # lines.  (The renderer decides it from the tree.)
        grouped = {key(port) for port in in_a_trunk_line(job.rendered)}
        for _stanza, vid, port, form in said_how(job.rendered):
            want = GROUP_FORM if is_a_trunk_group(port) or key(port) in grouped else PORT_FORM
            if form is None:
                wrong.append(f"VLAN {vid}, port {port!r}: {NOT_THE_LINE}")
            elif form != want:
                wrong.append(f"VLAN {vid}, port {port!r}: the line is the one for {form}, and {WRONG_FORM} {want}")
            else:
                tally[f"said in the form for {form}"] += 1
    for name, had in sorted(src.items()):
        if name in dropped:
            tally["dropped by the job"] += 1
            continue
        final = job.port_renames.get(name, name)
        has = by_text.get(key(final))
        if has is None:
            tally["nothing stated for the port"] += 1
            continue
        if had.untagged == has.untagged:
            tally["the same"] += 1
            if had.untagged is not None:
                tally["carried by both"] += 1
            elif had.left_out is not None:
                tally["left out, and not carried"] += 1
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
    return {"tally": tally, "wrong": wrong, "status": job.status.value}


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
#: a trunk that carries VLAN 11 tagged, and its
#: ``FortyGigabitEthernet1/1/1`` a trunk whose native VLAN is 11.
#: Three targets have one name for the two (and for ``1/0/2`` and
#: ``1/1/2``), and the port read back under it carries VLAN 11
#: untagged: for the first of each pair that VLAN "was tagged on the
#: source".  A naming fault the job reports, and not the list's: no
#: VLAN is lost or gained BY THE LIST on these ports either (the first
#: test below).  Not excused wholesale: compared for EQUALITY with
#: what is measured, so the change that settles those names empties
#: this.
ON_A_FUSED_PORT: dict[tuple[str, str], int] = {
    ("real/cisco_iosxe/user_contrib_cat9300_iosxe1712.txt", "arista_eos"): 2,
    ("real/cisco_iosxe/user_contrib_cat9300_iosxe1712.txt", "aruba_aoscx"): 2,
    ("real/cisco_iosxe/user_contrib_cat9300_iosxe1712.txt", "dell_os10"): 2,
}


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


def test_what_is_on_a_fused_port_is_pinned(every_job: dict) -> None:
    fused = {
        (label, target): verdict["tally"]["on a fused port"]
        for (_source, label, target), verdict in every_job.items()
        if verdict["tally"]["on a fused port"]
    }
    assert fused == ON_A_FUSED_PORT
    assert _total(every_job, WAS_TAGGED) == sum(ON_A_FUSED_PORT.values())
    assert _total(every_job, TAGGED_INSTEAD) == _total(every_job, ANOTHER) == 0


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
    # AOS-S has no name for, which the job drops and lists.)
    assert _total(every_job, SAID) == _total(every_job, SAID, None, "aruba_aoss") >= 9
    assert _total(every_job, f"said in the form for {PORT_FORM}") >= 1
    assert _total(every_job, f"said in the form for {GROUP_FORM}") >= 8


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
}

#: (source codec, shape) -> the text, in that codec's own grammar.
SHAPES: dict[tuple[str, str], str] = {
    **{
        (codec, shape): write(*lines)
        for codec, write in (("cisco_iosxe_cli", _iosxe), ("arista_eos", _eos), ("cisco_nxos", _nxos))
        for shape, lines in _SWITCHPORT.items()
    },
    ("aruba_aoscx", "a"): _aoscx("vlan trunk native 10", "vlan trunk allowed 10,20,30"),
    ("aruba_aoscx", "b"): _aoscx("vlan trunk native 10", "vlan trunk allowed 20,30"),
    ("aruba_aoscx", "c"): _aoscx("vlan trunk allowed 20,30"),
    ("aruba_aoscx", "d"): _aoscx("vlan trunk native 10"),
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
#: * on AOS-S the port is in the VLANs that list it.
CARRIES: dict[tuple[str, str], tuple[int | None, frozenset[int]]] = {
    **{
        (codec, shape): carried
        for codec in ("cisco_iosxe_cli", "arista_eos", "cisco_nxos", "aruba_aoscx")
        for shape, carried in {
            "a": (10, _EVERY), "b": (None, frozenset({20, 30})), "c": (None, frozenset({20, 30})), "d": (10, _EVERY),
        }.items()
    },
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
    # Every kind is among them: carried, left out, not stated.
    assert {untagged for untagged, _all in CARRIES.values()} == {10, None}


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
    assert judge(get_codec(source), codec, SHAPES[(source, shape)], job)["wrong"] == []


@pytest.mark.parametrize("source,shape", sorted(SHAPES))
def test_the_same_text_comes_back(source: str, shape: str) -> None:
    """Onto its own codec a trunk is written as it was: a native VLAN
    outside its list stays outside it, an access VLAN of an OS10 trunk
    stays off its allowed line, and AOS-S gets its lists back.  (The
    one exception is the OS10 text that names its access VLAN on the
    allowed line as well, which comes back with the VLAN on one.)"""
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
    if source == "aruba_aoss":
        want.remove("no untagged 1-2")            # nothing lists the ports there: no line
    assert lines(job.rendered) == sorted(want), (source, shape)


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
    port, and a line in VLAN 10's stanza that says so; OS10 the line
    that takes the access VLAN back, under a line that says so."""
    job, final = _shape_job(source, "b", "aruba_aoss")
    assert not [
        line for line in job.rendered.splitlines()
        if line.strip().startswith("untagged") and final in _aoss_ports(line.split(None, 1)[1])
    ], job.rendered
    ten = dict(_stanzas(job.rendered, "vlan "))["10"]
    assert ten == ['name "ten"', SAID_OF_A_PORT.format(port=final, native=10), "exit"], ten
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


def _in_one_table_only(native: dict, unstated: dict) -> list[str]:
    return sorted(set(native) ^ set(unstated))


def test_a_codec_is_in_both_tables_or_none() -> None:
    """A codec whose parser can make a trunk states what a trunk with
    no list carries AND how its text states the untagged VLAN: the
    next codec cannot join one table without the other."""
    assert _in_one_table_only(NATIVE_VLAN_AND_THE_LIST, TRUNK_THAT_STATES_NO_LIST) == []


def test_a_codec_in_one_table_is_reported() -> None:
    more = {**NATIVE_VLAN_AND_THE_LIST, "a_codec_nobody_listed": LIST_DECIDES}
    assert _in_one_table_only(more, TRUNK_THAT_STATES_NO_LIST) == ["a_codec_nobody_listed"]
    fewer = {codec: how for codec, how in NATIVE_VLAN_AND_THE_LIST.items() if codec != "dell_os10"}
    assert _in_one_table_only(fewer, TRUNK_THAT_STATES_NO_LIST) == ["dell_os10"]


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

    def _said_job(self) -> tuple[Any, str, str]:
        """IOS-XE (b) onto AOS-S, and the one line of its output that
        says native VLAN 10 was left out of the trunk's list."""
        job, final = _shape_job("cisco_iosxe_cli", "b", "aruba_aoss")
        verdict = self._judge("cisco_iosxe_cli", "b", "aruba_aoss", job)
        assert verdict["wrong"] == [] and verdict["tally"][SAID] == 1
        lines = [line for line in job.rendered.splitlines(keepends=True) if "; review: port " in line]
        assert len(lines) == 1 and lines[0].startswith(f"   ; review: port {final} -- "), lines
        return job, final, lines[0]

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
        job, final, line = self._said_job()
        other = line.replace(f"port {final} -- ", "port 2 -- ")
        said_of_two = job.rendered.replace(line, line + other)
        job.rendered = said_of_two
        verdict = self._judge("cisco_iosxe_cli", "b", "aruba_aoss", job)
        assert verdict["wrong"] == ["VLAN 10, port '2': 1 review lines for a port whose source left nothing out"]
        job.rendered = said_of_two.replace(other, line)
        verdict = self._judge("cisco_iosxe_cli", "b", "aruba_aoss", job)
        assert verdict["wrong"] == [f"native VLAN 10 of 'GigabitEthernet1/0/1', 2 lines: {NOT_SAID}"]

    def test_a_line_that_says_a_word_more(self) -> None:
        """The line with a claim added about the source switch, and
        with one added about the AOS-S switch: neither is the line,
        so the VLAN is not said."""
        for old, new in (
            ("leaves it out, so no", "leaves it out (the source switch forwards no untagged frame on it), so no"),
            ("until it is removed -- ", "until it is removed, and a trunk group does the same -- "),
            ("default VLAN (VID 1)", "default VLAN (VID 1), untagged"),
        ):
            job, final, line = self._said_job()
            assert old in line
            job.rendered = job.rendered.replace(line, line.replace(old, new))
            verdict = self._judge("cisco_iosxe_cli", "b", "aruba_aoss", job)
            assert verdict["wrong"] == [
                f"native VLAN 10 of 'GigabitEthernet1/0/1', 0 lines: {NOT_SAID}",
                f"VLAN 10, port {final!r}: {NOT_THE_LINE}",
            ], (new, verdict["wrong"])

    def test_the_form_for_another_kind_of_name(self) -> None:
        """The line for a trunk group said of a port, and the line
        for a port said of a port that the output's own ``trunk``
        line puts in a group."""
        job, final, line = self._said_job()
        assert line.strip() == SAID_OF_A_PORT.format(port=final, native=10)
        job.rendered = job.rendered.replace(line, "   " + SAID_OF_A_GROUP.format(port=final, native=10) + "\n")
        verdict = self._judge("cisco_iosxe_cli", "b", "aruba_aoss", job)
        assert verdict["wrong"] == [
            f"VLAN 10, port {final!r}: the line is the one for {GROUP_FORM}, and {WRONG_FORM} {PORT_FORM}",
        ]
        job, final, line = self._said_job()
        assert not in_a_trunk_line(job.rendered) and final == "1"
        job.rendered = job.rendered.replace("vlan 10\n", "trunk 1,7 trk1 lacp\nvlan 10\n", 1)
        assert in_a_trunk_line(job.rendered) == {"1", "7"}
        verdict = self._judge("cisco_iosxe_cli", "b", "aruba_aoss", job)
        assert f"VLAN 10, port '1': the line is the one for {PORT_FORM}, and {WRONG_FORM} {GROUP_FORM}" in (
            verdict["wrong"]
        )

    def test_said_where_the_vlan_is_carried(self) -> None:
        """IOS-XE (a): the list names VLAN 10, the port is untagged
        in it, and a line that said otherwise would be false."""
        job, final = _shape_job("cisco_iosxe_cli", "a", "aruba_aoss")
        verdict = self._judge("cisco_iosxe_cli", "a", "aruba_aoss", job)
        assert verdict["wrong"] == [] and SAID not in verdict["tally"]
        _job, _final, line = self._said_job()
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

    def test_a_fused_port_is_counted_apart(self, onto_nxos: Any) -> None:
        """...and what is counted there is pinned by cell."""
        onto_nxos.rendered = onto_nxos.rendered.replace("native vlan 10", "native vlan 30")
        onto_nxos.fused_ports = {self.E1: ["1", "9"]}
        verdict = self._judge("aruba_aoss", "e1", "cisco_nxos", onto_nxos)
        assert verdict["wrong"] == [] and verdict["tally"]["on a fused port"] == 2

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
        # AOS-CX: a native line alone is every VLAN, and `tag` is no other VLAN.
        assert read_text("interface 1/1/1\n    vlan trunk native 10 tag\n", "aruba_aoscx")["1/1/1"].untagged == 10
        # AOS-S: the last `untagged` stands, and `no untagged` takes it back.
        aoss = read_text(
            "vlan 1\n   untagged 1-3\n   exit\nvlan 10\n   untagged 2\n   tagged 1\n   no untagged 3\n   exit\n"
            "vlan 20\n   tagged 1-2\n   exit\nvlan 1\n   no untagged 3\n   exit\n", "aruba_aoss",
        )
        assert aoss["1"] == Port(1, None, frozenset({10, 20})) and aoss["2"] == Port(10, None, frozenset({20}))
        assert "3" not in aoss

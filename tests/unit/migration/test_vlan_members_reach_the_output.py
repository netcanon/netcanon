"""A port's VLANs are in the output, or the job says why they are not.

Every committed capture of every public codec, onto every public codec
(its own among them), through the entry the API uses when no devices
are declared::

    run_plan_with_checked_names(source, target, text, port_rename_map={})

The memberships the SOURCE tree holds are then looked for in the OUTPUT,
read back.  The defect this is for: a port that AOS-S names only in a
VLAN's member list had no interface record, most renderers write a
port's VLANs from its record alone, and so a switch's access ports
came out on NX-OS, AOS-CX and OS10 with no line at all, in jobs that
said ``completed`` -- with the validation report counting every one of
those memberships as ``supported``.

What a membership is, said once and used for both trees
-------------------------------------------------------
``(vlan id, port, "u" | "t")``.  A tree states one in two places and the
two are united: a VLAN's ``untagged_ports`` / ``tagged_ports``, and an
interface's ``access_vlan`` (mode ``access``) or ``trunk_native_vlan``
and ``trunk_allowed_vlans`` (mode ``trunk``).  A trunk's list is what
it carries: its native VLAN is an untagged membership where the list
holds it, and no membership at all where the list leaves it out (a
native VLAN stated and not carried).  Untagged stands where a tree
says both.  Nothing is filled in that a tree does not state.  A
trunk of every id, and a list longer than 128 ids, are a statement and
not thousands of memberships: they are compared over the VLAN ids the
SOURCE tree knows (declared, or named by a membership), the same ids
for both trees.  What such a list says of an id the source does not
know -- a trunk of every VLAN narrowed to the declared ones, a list a
target cannot state -- is not this module's to judge; the trunk-list
guards read lists whole (``test_a_trunk_says_none_nothing_or_all.py``,
``test_a_vlan_left_out_stays_out.py``).

What may become of a source membership
--------------------------------------
* it is in the output under the name the job gives the port;
* the job LISTS the port: dropped (``port_drops``), one of several on
  one name (``fused_ports``), or left under a source name
  (``untranslated_ports``).  Such a job is ``partial`` and says which;
* the port's own stanza of the output says so, in a ``review:`` line
  (the cells that do are pinned, :data:`SAID_IN_THE_STANZA`);
* on a target that writes no port VLANs at all
  (:data:`WRITES_NO_PORT_VLANS`), the validation report lists as
  unsupported or lossy a path that states THIS membership in the
  source tree.  A report that lists only ``/vlans/vlan/id`` has not
  said it, and neither has one on a target that writes port VLANs.
  What such a report accounts for is the membership, not the port:
  the port is still looked for in the output (the third reading).

Anything else fails.  So does a membership of the output that no source
membership accounts for, and one that changed between tagged and
untagged.

How the output is read
----------------------
Three ways, because each has a blind spot of its own.

1. The target's parser.  It reads its own defaults: what it says is
   there may be a line that is not.
2. The text, by a reader this module owns for each of the seven
   grammars that put a VLAN on a port.  The two readings must agree.
3. The text again, asking no grammar: a port that has a VLAN and that
   the job reports under a name has that name in a line.  Held on
   every target but one (:data:`NAME_STANDS_IN_A_RANGE`) -- the six
   that write no port VLANs among them, where no other reading sees a
   port at all: its memberships are declared lost, the report that
   declares them is made before a line is written, and a renderer
   that wrote no stanza for such a port would leave nothing to find.

And the source parser is held to the shape the renderers rely on: every
port one of its lists names has a record (:func:`test_every_listed_port_has_a_record`).

What this cannot see
--------------------
A membership the source parser never put in the tree is missing from
both sides (Dell OS10 ``interface range`` is one such; it needs the
source TEXT read against the source tree, which is another test).  The
port a FortiOS, OPNsense or RouterOS VLAN interface is put on is read by
no parser and by no reader here.  And whether a target ACCEPTS a line is
nobody's to say from here.
"""

from __future__ import annotations

import collections
import re
from pathlib import Path
from typing import Any

import pytest

from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.migration.fixture_dirs import DIR_TO_CODEC_NAME
from netcanon.models.migration import MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "tests" / "fixtures"
PUBLIC = list_public_codecs()

EVERY = 4094
#: A list longer than this is compared whole, not id by id (the bound
#: ``TRUNK_ALLOWED_SPECIFICITY_BOUND`` draws the same line).
SPECIFIC = 128

X_UNTAGGED = "/vlans/vlan/untagged-ports"
X_TAGGED = "/vlans/vlan/tagged-ports"
X_MODE = "/interfaces/interface/switchport-mode"
X_ACCESS = "/interfaces/interface/access-vlan"
X_ALLOWED = "/interfaces/interface/trunk-allowed-vlans"
X_NATIVE = "/interfaces/interface/trunk-native-vlan"

# ---------------------------------------------------------------------------
# What is known, and why each is not the defect
# ---------------------------------------------------------------------------

#: Targets whose output puts no VLAN on any port: a router, three
#: firewalls, and two that model interfaces only.  On these -- and only
#: on these -- a membership may be lost with its own path listed by the
#: validation report.  Compared for EQUALITY with what is measured: a
#: target that starts to write port VLANs leaves this set in the same
#: change, and one that stops is a failure, not a new entry.
WRITES_NO_PORT_VLANS = frozenset({
    "cisco_iosxr", "cisco_iosxe", "vyos",
    "fortigate_cli", "mikrotik_routeros", "opnsense",
})

#: The seven grammars that put a VLAN on a port, each read as text below.
READ_AS_TEXT = frozenset({
    "cisco_nxos", "cisco_iosxe_cli", "arista_eos", "dell_os10",
    "aruba_aoscx", "aruba_aoss", "juniper_junos",
})

#: Targets on which a port's name need not stand in a line of the
#: output.  AOS-S writes a port inside a range (``untagged 1-48``):
#: its text reader expands the ranges, and a look for the name cannot.
#: On every other target the name of every port that has a VLAN is in
#: a line of the output, on every committed capture -- the six that
#: write no port VLANs as much as the switches.  Compared for EQUALITY
#: with the targets on which the look in fact comes back empty, so
#: this is no place to put a target that has started to lose ports.
NAME_STANDS_IN_A_RANGE = frozenset({"aruba_aoss"})

#: (capture, target) -> memberships not in the output that the port's own
#: stanza speaks for in a ``review:`` line.  None today.  Two were here:
#: an OS10 trunk with an access VLAN and no allowed line was read as a
#: trunk of no VLAN, which AOS-CX cannot be told, and its untagged VLAN
#: went unwritten under the line that said so.  Such a trunk carries
#: its access VLAN, its list now holds it, and AOS-CX is written both
#: of its ``vlan trunk`` lines.  Compared for equality.
SAID_IN_THE_STANZA: dict[tuple[str, str], int] = {}

#: Targets on which a port under a name the OPERATOR chose (an entry of
#: the port map that is no port name of the target) is written with no
#: VLAN line and nothing said.  AOS-CX writes a port's VLANs only where
#: its classifier reads the name as a port or a LAG.  Not this module's
#: defect -- the port has a record and a stanza -- but the same loss, and
#: found by the same reading.  Compared for equality: the change that
#: mends it empties this.
NO_VLAN_FOR_A_NAME_IT_CANNOT_READ = frozenset({"aruba_aoscx"})

#: Targets whose output names no member for any LAG, whatever the
#: source: the IOS-XE NETCONF codec renders interfaces and no bundle
#: membership, and its report does not list the path.  Another defect
#: than this module's (the members there have records), pinned so that
#: the LAG test below can say "everywhere else".  Compared for equality.
WRITES_NO_LAG_MEMBERS = frozenset({"cisco_iosxe"})

#: Parsers that read a LAG's members from a list and give a member no
#: record when the config has no stanza for it.  The same shape as the
#: defect this module is for, in two parsers it was not found in: a
#: FortiOS config prints an ``edit`` stanza for every physical port, so
#: a device's own config has the record; an OPNsense lagg's members
#: are as a rule NICs assigned to nothing, and the committed captures
#: assign theirs.  Such a member is in no line of a port-centric
#: target's output.  Typed configs show it (:data:`_LAG_IN_A_LIST`);
#: compared for equality, so the change that gives these members a
#: record empties this -- and re-homes the tests that use an OPNsense
#: lagg for "a port the config has no interface for"
#: (``test_run_plan_with_models.py``).
LAG_MEMBERS_WITH_NO_RECORD = frozenset({"fortigate_cli", "opnsense"})


# ---------------------------------------------------------------------------
# The captures
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
            if codec in PUBLIC:
                found.append((codec, "/".join(parts), path))
    return found


CAPTURES = _captures()


# ---------------------------------------------------------------------------
# Reading a tree
# ---------------------------------------------------------------------------


class Reading:
    """What one tree, or one text, states of memberships."""

    def __init__(self) -> None:
        #: (vid, port, mode) -> the xpaths that state it in a tree
        self.stated: dict[tuple[int, str, str], set[str]] = {}
        self.every: set[str] = set()
        self.wide: dict[str, frozenset[int]] = {}
        self.declared: set[int] = set()

    def say(self, vid: int, port: str, mode: str, *xpaths: str) -> None:
        self.stated.setdefault((vid, port, mode), set()).update(xpaths)

    def trunk(self, name: str, allowed: Any, native: int | None, *xpaths: str) -> None:
        """A trunk: *allowed* is the word ``"all"`` or a list of ids,
        and it is what the trunk carries.  The native VLAN is untagged
        where the list holds it; where the list leaves it out it is
        stated and not carried, and is no membership."""
        if native is not None and (allowed == "all" or native in allowed):
            self.say(native, name, "u", *xpaths)
        if allowed == "all" or len(set(allowed)) >= EVERY:
            self.every.add(name)
        elif len(allowed) > SPECIFIC:
            self.wide[name] = frozenset(allowed)
        else:
            for vid in allowed:
                self.say(vid, name, "t", *(x for x in xpaths if x != X_NATIVE))

    def universe(self) -> set[int]:
        return self.declared | {vid for vid, _port, _mode in self.stated}

    def memberships(self, universe: set[int]) -> dict[tuple[int, str, str], set[str]]:
        out = {k: set(v) for k, v in self.stated.items()}
        for port in self.every:
            for vid in universe:
                out.setdefault((vid, port, "t"), set()).update((X_MODE, X_ALLOWED))
        for port, ids in self.wide.items():
            for vid in ids & universe:
                out.setdefault((vid, port, "t"), set()).update((X_MODE, X_ALLOWED))
        for vid, port, mode in list(out):
            if mode == "t" and (vid, port, "u") in out:
                out[(vid, port, "u")].update(out.pop((vid, port, "t")))
        return out


def read_tree(tree: Any) -> Reading:
    r = Reading()
    r.declared = {v.id for v in tree.vlans}
    for vlan in tree.vlans:
        for port in vlan.untagged_ports:
            r.say(vlan.id, port, "u", X_UNTAGGED)
        for port in vlan.tagged_ports:
            r.say(vlan.id, port, "t", X_TAGGED)
    for iface in tree.interfaces:
        if iface.switchport_mode == "access":
            if iface.access_vlan is not None:
                r.say(iface.access_vlan, iface.name, "u", X_MODE, X_ACCESS)
        elif iface.switchport_mode == "trunk":
            r.trunk(iface.name, iface.trunk_allowed_vlans, iface.trunk_native_vlan, X_MODE, X_ALLOWED, X_NATIVE)
    return r


# ---------------------------------------------------------------------------
# Reading a text: one small reader a grammar, owing nothing to the codec
# ---------------------------------------------------------------------------


def _ids(text: str) -> list[int]:
    out: list[int] = []
    for part in text.replace(" ", "").split(","):
        if "-" in part:
            low, high = part.split("-", 1)
            out.extend(range(int(low), int(high) + 1))
        elif part:
            out.append(int(part))
    return out


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


def _read_ios_like(text: str, codec: str) -> Reading:
    """NX-OS, IOS-XE, EOS, OS10.  A trunk with no allowed line is every
    VLAN -- none on OS10, where a trunk's untagged VLAN is its
    ``switchport access vlan``: a statement beside the allowed line,
    which names tagged VLANs only, so the trunk carries it whatever
    that line says (and ``no switchport access vlan`` takes it
    back)."""
    r = Reading()
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
            elif m := re.fullmatch(r"switchport trunk allowed vlan (?:add )?(\S+)", line):
                word = m.group(1)
                more: Any = [] if word == "none" else "all" if word == "all" else _ids(word)
                allowed = "all" if "all" in (more, allowed) else (allowed or []) + more
        if mode == "trunk":
            if codec == "dell_os10":
                tagged = allowed if allowed is not None else []
                carried = tagged if tagged == "all" or access is None else [*tagged, access]
                r.trunk(name, carried, access)
            else:
                r.trunk(name, allowed if allowed is not None else "all", native)
        elif access is not None:
            r.say(access, name, "u")
    return r


def _read_aoscx(text: str) -> Reading:
    r = Reading()
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
                allowed = "all" if m.group(1) == "all" else _ids(m.group(1))
        if trunk:
            r.trunk(name, allowed if allowed is not None else "all", native)
        elif access is not None:
            r.say(access, name, "u")
    return r


def _aoss_ports(text: str) -> list[str]:
    """``1-3,1/1-1/4,A1-A2,Trk1``: a range runs over the last number of
    its two ends, which share everything before it."""
    out: list[str] = []
    for part in text.replace(" ", "").split(","):
        m = re.fullmatch(r"(.*?)(\d+)-(.*?)(\d+)", part)
        if m and m.group(1) == m.group(3):
            out.extend(f"{m.group(1)}{n}" for n in range(int(m.group(2)), int(m.group(4)) + 1))
        elif part:
            out.append(part)
    return out


def _read_aoss(text: str) -> Reading:
    r = Reading()
    untagged_in: dict[str, int] = {}   # a port is untagged in ONE VLAN: the last that says so
    for name, body in _stanzas(text, "vlan "):
        if not name.isdigit():
            continue
        vid = int(name)
        for line in body:
            if m := re.fullmatch(r"(tagged|untagged) (\S+)", line):
                for port in _aoss_ports(m.group(2)):
                    if m.group(1) == "tagged":
                        r.say(vid, port, "t")
                    else:
                        untagged_in[port] = vid
            elif m := re.fullmatch(r"no untagged (\S+)", line):
                for port in _aoss_ports(m.group(1)):
                    if untagged_in.get(port) == vid:
                        del untagged_in[port]
    for port, vid in untagged_in.items():
        r.say(vid, port, "u")
    return r


def _read_junos(text: str) -> Reading:
    r = Reading()
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
            members[m.group(1)].extend(w.strip('"') for w in words)
        elif m := re.fullmatch(r"set interfaces (\S+) native-vlan-id (\d+)", line):
            native[m.group(1)] = int(m.group(2))
    for name in set(mode) | set(members) | set(native):
        ids: list[int] = []
        every = False
        for word in members.get(name, []):
            if word == "all":
                every = True
            elif re.fullmatch(r"\d+(-\d+)?", word):
                ids.extend(_ids(word))
            else:
                ids.append(vlan_id.get(word, -1))   # -1: a name the output declares no VLAN for
        if mode.get(name) == "trunk":
            r.trunk(name, "all" if every else ids, native.get(name))
        else:
            for vid in ids:
                r.say(vid, name, "u")
    return r


def read_text(text: str, codec: str) -> Reading:
    if codec == "aruba_aoscx":
        return _read_aoscx(text)
    if codec == "aruba_aoss":
        return _read_aoss(text)
    if codec == "juniper_junos":
        return _read_junos(text)
    return _read_ios_like(text, codec)


# ---------------------------------------------------------------------------
# One job, judged
# ---------------------------------------------------------------------------

_READ = {"jobs": 0, "memberships": 0, "by_text": 0, "lines": 0}


def _review_stanzas(text: str) -> list[str]:
    """What opens the stanza of every ``review:`` line, its first word off."""
    out: list[str] = []
    lines = text.splitlines()
    for n, line in enumerate(lines):
        if "review:" not in line.lower():
            continue
        indent = len(line) - len(line.lstrip())
        for back in range(n - 1, -1, -1):
            head = lines[back]
            if head.strip() and len(head) - len(head.lstrip()) < indent:
                out.append(head.split(None, 1)[-1])
                break
    return out


def _in_a_line(name: str, text: str) -> bool:
    """*name* stands in a line of *text* as a whole name (``lag 1`` is
    ``lag1``; ``Ethernet1/1`` is not in ``Ethernet1/10``)."""
    spelled = r"\s*".join(re.escape(piece) for piece in re.split(r"\s+|(?<=[A-Za-z])(?=\d)", name) if piece)
    return re.search(r"(?<![\w/.:-])" + spelled + r"(?![\w/.:-])", text) is not None


def judge(source: Any, target: Any, raw: str, job: Any) -> dict[str, Any]:
    """What became of every membership the source tree of *raw* holds,
    in *job*'s output.  Counts, and a sentence for each thing that may
    not be."""
    src = read_tree(source.parse(raw))
    universe = src.universe()
    want = src.memberships(universe)
    fold = not target.port_names_case_sensitive

    def key(name: str) -> str:
        name = re.sub(r"\s+", "", name)
        return name.casefold() if fold else name

    tally: collections.Counter[str] = collections.Counter()
    wrong: list[str] = []
    assert job.rendered is not None, f"nothing rendered: {job.error}"
    out = read_tree(target.parse(job.rendered))
    have = {(vid, key(port), mode): port for (vid, port, mode) in out.memberships(universe)}
    _READ["jobs"] += 1
    _READ["memberships"] += len(want)

    if target.name in READ_AS_TEXT:
        text = read_text(job.rendered, target.name)
        by_text = {(vid, key(port), mode) for (vid, port, mode) in text.memberships(universe)}
        _READ["by_text"] += len(by_text)
        for vid, port, mode in sorted(set(have) ^ by_text):
            where = "the parser" if (vid, port, mode) in have else "the text"
            wrong.append(f"VLAN {vid} {mode} on {port!r}: only {where} reads it")
            tally["readings disagree"] += 1

    validation = job.validation
    listed_by_report = (
        {p.path for p in validation.unsupported_paths} | {p.path for p in validation.lossy_paths}
    ) if validation else set()
    dropped = set(job.port_drops)
    set_apart = (
        dropped | set(job.untranslated_ports)
        | {name for names in job.fused_ports.values() for name in names}
    )
    if set_apart:
        assert job.status != MigrationJobStatus.completed, "a job that lists a port says completed"
    reviewed = {key(head) for head in _review_stanzas(job.rendered)}

    matched: set[tuple[int, str, str]] = set()
    in_a_line: dict[str, str] = {}
    for (vid, port, mode), xpaths in sorted(want.items()):
        final = None if port in dropped else job.port_renames.get(port, port)
        other = "t" if mode == "u" else "u"
        if final is not None:
            for m in (mode, other):
                if (vid, key(final), m) in have:
                    matched.add((vid, key(final), m))
        if port in set_apart:
            tally["listed by the job"] += 1
            continue
        assert final is not None
        in_a_line[port] = final
        if (vid, key(final), mode) in have:
            tally["kept"] += 1
        elif (vid, key(final), other) in have:
            tally["mode changed"] += 1
            wrong.append(f"VLAN {vid} on {port!r} ({final!r}) was {mode} and is {other}")
        elif key(final) in reviewed:
            tally["said in the stanza"] += 1
        elif target.name in WRITES_NO_PORT_VLANS and xpaths & listed_by_report:
            tally["declared"] += 1
        else:
            tally["lost"] += 1
            why = "the report lists none of " + ", ".join(sorted(x.rsplit("/", 1)[1] for x in xpaths))
            if target.name not in WRITES_NO_PORT_VLANS:
                why = "nothing on the job or in the output says so"
            wrong.append(f"VLAN {vid} {mode} on {port!r} ({final!r}) is not in the output: {why}")
    for (vid, port, mode), name in sorted(have.items()):
        if (vid, port, mode) not in matched:
            tally["gained"] += 1
            wrong.append(f"VLAN {vid} {mode} on {name!r} is in the output and in no source membership")

    for port, final in sorted(in_a_line.items()):
        _READ["lines"] += 1
        tally["looked for by name"] += 1
        if not _in_a_line(final, job.rendered):
            tally["in no line"] += 1
            if target.name not in NAME_STANDS_IN_A_RANGE:
                wrong.append(f"port {port!r} has a VLAN and its name {final!r} is in no line of the output")
    return {"tally": tally, "wrong": wrong, "status": job.status.value}


def _run(source_name: str, target_name: str, raw: str, port_map: dict | None = None) -> Any:
    return run_plan_with_checked_names(
        get_codec(source_name), get_codec(target_name), raw, port_rename_map=dict(port_map or {}),
    )


@pytest.fixture(scope="module")
def every_job() -> dict[tuple[str, str, str], dict[str, Any]]:
    """(source, capture, target) -> the judgement, for every capture onto
    every public codec.  Made once in a process: under ``-n`` each
    worker that runs one of the tests below makes its own."""
    out: dict[tuple[str, str, str], dict[str, Any]] = {}
    for codec, label, path in CAPTURES:
        raw = path.read_text(encoding="utf-8")
        for target_name in PUBLIC:
            job = _run(codec, target_name, raw)
            out[(codec, label, target_name)] = judge(get_codec(codec), get_codec(target_name), raw, job)
    return out


def _by_target(every_job: dict, what: str) -> dict[str, int]:
    out: collections.Counter[str] = collections.Counter()
    for (_source, _label, target), verdict in every_job.items():
        out[target] += verdict["tally"][what]
    return {target: n for target, n in sorted(out.items()) if n}


def _shown(every_job: dict, limit: int = 12) -> str:
    """The first complaints, by job, and how many there are."""
    lines: list[str] = []
    jobs = total = 0
    by_pair: collections.Counter[tuple[str, str, str]] = collections.Counter()
    for (source, label, target), verdict in every_job.items():
        if verdict["wrong"]:
            jobs += 1
            total += len(verdict["wrong"])
            by_pair[(source, target, verdict["status"])] += len(verdict["wrong"])
            if len(lines) < limit:
                lines.append(f"  {source} -> {target} [{verdict['status']}] {label}: "
                             f"{len(verdict['wrong'])}, the first: {verdict['wrong'][0]}")
    pairs = "\n".join(f"  {n:5d}  {s} -> {t} [{status}]" for (s, t, status), n in sorted(by_pair.items()))
    return f"{total} in {jobs} job(s)\nby pair and status:\n{pairs}\nthe first jobs:\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# 1. The shape the renderers rely on
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("codec", PUBLIC)
def test_every_listed_port_has_a_record(codec: str) -> None:
    """A port a parser names in a VLAN's member list, or as a member of
    a LAG, has an interface record in the same tree.  Most renderers
    write a port's VLANs and its LAG from the port's own record and
    never read the lists, so a port that only a list names is a port in
    no line of their output."""
    bare: dict[str, list[str]] = {}
    for source, label, path in CAPTURES:
        if source != codec:
            continue
        tree = get_codec(codec).parse(path.read_text(encoding="utf-8"))
        named: set[str] = set()
        for vlan in tree.vlans:
            named.update(vlan.untagged_ports)
            named.update(vlan.tagged_ports)
        for lag in tree.lags:
            named.update(lag.members)
        missing = sorted(named - {iface.name for iface in tree.interfaces})
        if missing:
            bare[label] = missing
    assert not bare, (
        f"{codec}: ports that a VLAN's or a LAG's list names and no interface record holds -- "
        + "; ".join(f"{label}: {len(names)} ({', '.join(names[:6])}...)" for label, names in bare.items())
    )


# ---------------------------------------------------------------------------
# 2. Every capture onto every codec
# ---------------------------------------------------------------------------


def test_no_membership_goes_unaccounted(every_job: dict) -> None:
    assert not any(v["wrong"] for v in every_job.values()), _shown(every_job)


def test_what_a_stanza_says_is_as_pinned(every_job: dict) -> None:
    said = {
        (label, target): verdict["tally"]["said in the stanza"]
        for (_source, label, target), verdict in every_job.items()
        if verdict["tally"]["said in the stanza"]
    }
    assert said == SAID_IN_THE_STANZA


def test_who_writes_no_port_vlans_is_pinned(every_job: dict) -> None:
    """A loss the report declares is taken only from a target that
    writes no port VLANs at all -- and each of those in fact keeps
    none, and loses some: the set is what is measured, not a licence."""
    assert set(_by_target(every_job, "declared")) == set(WRITES_NO_PORT_VLANS)
    keeps = set(_by_target(every_job, "kept"))
    assert keeps == set(PUBLIC) - WRITES_NO_PORT_VLANS
    assert keeps == READ_AS_TEXT


def test_it_read_what_it_says_it_read(every_job: dict) -> None:
    """A loop that reads nothing back passes every test above."""
    assert len(every_job) == len(CAPTURES) * len(PUBLIC)
    held = sum(sum(v["tally"][k] for k in ("kept", "listed by the job", "said in the stanza",
                                           "declared", "lost", "mode changed"))
               for v in every_job.values())
    assert held > 10_000, held
    kept = _by_target(every_job, "kept")
    # Every source codec whose trees hold memberships is kept somewhere,
    # and every target that writes port VLANs keeps hundreds.
    assert all(kept[target] > 500 for target in READ_AS_TEXT), kept
    sources = {source for (source, _label, _target), v in every_job.items() if v["tally"]["kept"]}
    assert sources >= READ_AS_TEXT, sorted(READ_AS_TEXT - sources)
    assert _READ["by_text"] > 5_000 and _READ["lines"] > 1_000, _READ
    # A port's name is looked for on every target, for hundreds of
    # ports each, and is missing from a line where the pin says and
    # nowhere else.
    looked = _by_target(every_job, "looked for by name")
    assert set(looked) == set(PUBLIC) and all(n > 300 for n in looked.values()), looked
    assert set(_by_target(every_job, "in no line")) == set(NAME_STANDS_IN_A_RANGE)


# ---------------------------------------------------------------------------
# 3. A port the operator names
# ---------------------------------------------------------------------------


def _first_port_with_a_vlan(tree: Any) -> str | None:
    lags = {lag.name for lag in tree.lags} | {m for lag in tree.lags for m in lag.members}
    for iface in tree.interfaces:
        if iface.name in lags or iface.lag_member_of:
            continue
        if iface.switchport_mode == "access" and iface.access_vlan is not None:
            return iface.name
    return None


def test_an_operators_name_keeps_its_vlan() -> None:
    """One entry of the port map gives an access port a name that is no
    port name anywhere.  The port is then in the output under that
    name, on its VLAN -- on every target that writes port VLANs but the
    pinned ones."""
    loses: collections.Counter[str] = collections.Counter()
    asked = 0
    for codec, _label, path in CAPTURES:
        raw = path.read_text(encoding="utf-8")
        port = _first_port_with_a_vlan(get_codec(codec).parse(raw))
        if port is None:
            continue
        for target_name in sorted(READ_AS_TEXT - {codec}):
            job = _run(codec, target_name, raw, {port: "uplink-x"})
            verdict = judge(get_codec(codec), get_codec(target_name), raw, job)
            asked += 1
            mine = [w for w in verdict["wrong"] if f"on {port!r} ('uplink-x')" in w or "'uplink-x' is in no line" in w]
            loses[target_name] += bool(mine)
    assert asked > 100, asked
    assert {t for t, n in loses.items() if n} == set(NO_VLAN_FOR_A_NAME_IT_CANNOT_READ), dict(loses)


# ---------------------------------------------------------------------------
# 4. A LAG whose members have no stanza
# ---------------------------------------------------------------------------

#: What the device prints for a LAG of two ports that have no setting of
#: their own: a ``trunk`` line, and the LAG in a VLAN's list.  No
#: ``interface 23`` stanza, and none for ``Trk1``.
_AOSS_LAG = (
    '; J9727A Configuration Editor; Created on release #WB.16.08.0001\n'
    'hostname "sw"\n'
    "trunk 23-24 trk1 lacp\n"
    'vlan 1\n   name "DEFAULT_VLAN"\n   untagged 1-22\n   no untagged 23-24\n   exit\n'
    'vlan 10\n   name "V10"\n   tagged Trk1\n   exit\n'
)


def _squeezed(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


def _lag_members(tree: Any) -> set[tuple[str, str]]:
    """(LAG, member), from either place a tree states one."""
    pairs = {(lag.name, member) for lag in tree.lags for member in lag.members}
    pairs |= {(iface.lag_member_of, iface.name) for iface in tree.interfaces if iface.lag_member_of}
    return pairs


def test_a_lag_member_with_no_stanza_stays() -> None:
    """The same shape one list over: a port that only a ``trunk`` line
    names.  A port-centric renderer writes a port's LAG on the port's
    own stanza, from its record; with no record the LAG came out with
    no member, in a job that said ``completed``.  No committed capture
    shows it under names every target reads, so the config is typed
    here."""
    aoss = get_codec("aruba_aoss")
    assert _lag_members(aoss.parse(_AOSS_LAG)) == {("trk1", "23"), ("trk1", "24")}
    without: set[str] = set()
    for name in PUBLIC:
        target = get_codec(name)
        job = _run("aruba_aoss", name, _AOSS_LAG)
        assert not (job.fused_ports or job.port_drops or job.untranslated_ports), (name, job.error)
        have = {(_squeezed(lag), _squeezed(member)) for lag, member in _lag_members(target.parse(job.rendered))}
        lag = job.port_renames.get("trk1", "trk1")
        members = [job.port_renames.get(port, port) for port in ("23", "24")]
        found = [member for member in members if (_squeezed(lag), _squeezed(member)) in have]
        if len(found) < 2:
            without.add(name)
            continue
        # ... and each member's name is in a line, whoever read it back
        # (AOS-S writes its members inside a range, ``trunk 23-24``).
        if name != "aruba_aoss":
            assert all(_in_a_line(member, job.rendered) for member in members), (name, members)
    assert without == set(WRITES_NO_LAG_MEMBERS), sorted(without)


#: A LAG whose members the config states in a LIST and gives no stanza
#: of their own, as each grammar that has such a list writes it.  (A
#: port-centric grammar states the LAG on the member's own stanza, so
#: there the member has a record by construction.)
_LAG_IN_A_LIST: dict[str, tuple[str, set[str]]] = {
    "aruba_aoss": (_AOSS_LAG, {"23", "24"}),
    "mikrotik_routeros": (
        "/interface bonding\nadd mode=802.3ad name=bond1 slaves=ether2,ether3\n"
        "/ip address\nadd address=10.0.0.2/24 interface=bond1\n",
        {"ether2", "ether3"},
    ),
    "fortigate_cli": (
        'config system interface\n    edit "agg1"\n        set vdom "root"\n'
        '        set type aggregate\n        set member "port1" "port2"\n'
        "        set ip 10.0.0.2 255.255.255.0\n    next\nend\n",
        {"port1", "port2"},
    ),
    "opnsense": (
        '<?xml version="1.0"?>\n<opnsense>\n  <system><hostname>fw</hostname></system>\n'
        "  <interfaces><lan><if>lagg0</if><enable>1</enable>"
        "<ipaddr>10.0.0.2</ipaddr><subnet>24</subnet></lan></interfaces>\n"
        "  <laggs><lagg><members>igb0,igb1</members><laggif>lagg0</laggif>"
        "<proto>lacp</proto></lagg></laggs>\n</opnsense>\n",
        {"igb0", "igb1"},
    ),
}


def test_a_listed_lag_member_has_a_record() -> None:
    """The first test of this module holds every parser to "a port one
    of your lists names has a record" on the committed captures, and a
    capture shows only what it happens to hold.  Here each grammar
    that states a LAG's members in a list is given one whose members
    have no stanza."""
    bare: set[str] = set()
    for codec, (text, members) in _LAG_IN_A_LIST.items():
        tree = get_codec(codec).parse(text)
        assert {member for lag in tree.lags for member in lag.members} == members, codec
        if members - {iface.name for iface in tree.interfaces}:
            bare.add(codec)
    assert bare == set(LAG_MEMBERS_WITH_NO_RECORD)


# ---------------------------------------------------------------------------
# 5. The check itself, handed each defect
# ---------------------------------------------------------------------------

_EOS = """hostname sw1
!
vlan 10
   name USERS
!
vlan 20
   name VOICE
!
vlan 30
   name SPARE
!
interface Ethernet1
   switchport access vlan 10
!
interface Ethernet2
   switchport mode trunk
   switchport trunk native vlan 10
   switchport trunk allowed vlan 10,20
!
end
"""


class TestTheCheckItself:
    """A check nobody has seen fail is not known to check anything.
    One job that is right (EOS ``Ethernet1`` and ``Ethernet2`` are
    written ``Ethernet0/1`` and ``Ethernet0/2`` by this translation),
    and then the same job with its output or its report altered by
    hand, once for each thing the judgement is for."""

    E1, E2 = "Ethernet0/1", "Ethernet0/2"

    @pytest.fixture()
    def job(self) -> Any:
        job = _run("arista_eos", "cisco_nxos", _EOS)
        assert job.port_renames == {"Ethernet1": self.E1, "Ethernet2": self.E2}
        for line in (f"interface {self.E1}\n", "  switchport access vlan 10\n",
                     "  switchport trunk native vlan 10\n", "  switchport trunk allowed vlan 10,20\n"):
            assert job.rendered.count(line) == 1, line
        return job

    def _judge(self, job: Any, target: Any = None) -> dict[str, Any]:
        return judge(get_codec("arista_eos"), target or get_codec("cisco_nxos"), _EOS, job)

    def test_a_right_job_passes(self, job: Any) -> None:
        verdict = self._judge(job)
        assert verdict["wrong"] == [] and dict(verdict["tally"]) == {"kept": 3, "looked for by name": 2}

    def test_a_line_taken_out(self, job: Any) -> None:
        job.rendered = job.rendered.replace("  switchport access vlan 10\n", "")
        (said,) = self._judge(job)["wrong"]
        assert said == (
            f"VLAN 10 u on 'Ethernet1' ('{self.E1}') is not in the output: "
            "nothing on the job or in the output says so"
        )

    def test_a_stanza_taken_out(self, job: Any) -> None:
        text = job.rendered
        job.rendered = text[:text.index(f"interface {self.E1}\n")] + text[text.index(f"interface {self.E2}\n"):]
        wrong = self._judge(job)["wrong"]
        assert len(wrong) == 2
        assert "is not in the output" in wrong[0]
        assert wrong[1] == f"port 'Ethernet1' has a VLAN and its name '{self.E1}' is in no line of the output"

    def test_a_vlan_added(self, job: Any) -> None:
        job.rendered = job.rendered.replace("allowed vlan 10,20", "allowed vlan 10,20,30")
        (said,) = self._judge(job)["wrong"]
        assert said == f"VLAN 30 t on '{self.E2}' is in the output and in no source membership"

    def test_a_native_vlan_taken_out(self, job: Any) -> None:
        job.rendered = job.rendered.replace("  switchport trunk native vlan 10\n", "")
        (said,) = self._judge(job)["wrong"]
        assert said == f"VLAN 10 on 'Ethernet2' ('{self.E2}') was u and is t"

    def test_a_native_vlan_left_out_of_the_list(self, job: Any) -> None:
        """The native line stands and the allowed line does not name
        its VLAN: stated, and not carried.  Read as carried whatever
        the list says, this output passed -- and so did every trunk of
        AOS-S and OS10 written that way."""
        job.rendered = job.rendered.replace("allowed vlan 10,20", "allowed vlan 20")
        (said,) = self._judge(job)["wrong"]
        assert said == (
            f"VLAN 10 u on 'Ethernet2' ('{self.E2}') is not in the output: "
            "nothing on the job or in the output says so"
        )

    def test_a_stanza_under_another_name(self, job: Any) -> None:
        job.rendered = job.rendered.replace(f"interface {self.E1}\n", "interface Ethernet0/9\n")
        wrong = self._judge(job)["wrong"]
        assert any(f"on 'Ethernet1' ('{self.E1}') is not in the output" in w for w in wrong)
        assert any("on 'Ethernet0/9' is in the output and in no source membership" in w for w in wrong)
        assert any(f"its name '{self.E1}' is in no line" in w for w in wrong)

    def test_a_parser_that_reads_a_missing_line(self, job: Any) -> None:
        """A parser reads its own defaults.  One that gives a port with
        no VLAN line the VLAN the source had would make the lost line
        read as kept: the text says otherwise."""
        real = get_codec("cisco_nxos")
        first = self.E1

        class Fills:
            name = real.name
            port_names_case_sensitive = real.port_names_case_sensitive

            def parse(self, text: str) -> Any:
                tree = real.parse(text)
                for iface in tree.interfaces:
                    if iface.name == first and iface.access_vlan is None:
                        iface.switchport_mode, iface.access_vlan = "access", 10
                return tree

        job.rendered = job.rendered.replace("  switchport access vlan 10\n", "")
        verdict = self._judge(job, Fills())
        assert verdict["tally"]["kept"] == 3, "the stand-in parser did not fill the line in"
        assert len(verdict["wrong"]) == 1 and verdict["wrong"][0].endswith("only the parser reads it")

    def test_a_port_the_job_lists_is_set_apart(self, job: Any) -> None:
        job.rendered = job.rendered.replace("  switchport access vlan 10\n", "")
        job.rendered = job.rendered.replace(f"interface {self.E1}\n", "interface Ethernet1\n")
        job.status = MigrationJobStatus.partial
        job.untranslated_ports = ["Ethernet1"]
        job.port_renames = {"Ethernet2": self.E2}
        verdict = self._judge(job)
        assert verdict["wrong"] == [] and verdict["tally"]["listed by the job"] == 1

    def test_a_listed_port_in_a_completed_job(self, job: Any) -> None:
        job.untranslated_ports = ["Ethernet1"]
        with pytest.raises(AssertionError, match="says completed"):
            self._judge(job)

    def test_a_review_line_is_counted_apart(self, job: Any) -> None:
        """...and what is counted there is pinned by cell, so that a
        renderer cannot excuse itself wholesale."""
        job.rendered = job.rendered.replace(
            "  switchport access vlan 10\n", "  ! review: the access VLAN was not written\n",
        )
        verdict = self._judge(job)
        assert verdict["wrong"] == [] and verdict["tally"]["said in the stanza"] == 1

    def test_a_report_excuses_no_switch_target(self, job: Any) -> None:
        """NX-OS writes port VLANs.  A report line for the path is no
        account of a membership that is not in its output."""
        job.rendered = job.rendered.replace("  switchport access vlan 10\n", "")
        donor = _run("arista_eos", "cisco_iosxr", _EOS).validation
        listed = [p for p in donor.unsupported_paths if p.path == X_ACCESS]
        assert listed, "the donor report no longer lists the path"
        job.validation.unsupported_paths = listed
        assert len(self._judge(job)["wrong"]) == 1

    def test_the_vlan_declared_is_not_enough(self) -> None:
        """On a target that writes no port VLANs the report has to list
        a path that states the membership; one that lists other paths
        only -- ``/vlans/vlan/id`` among them -- has not said it."""
        job = _run("arista_eos", "cisco_iosxr", _EOS)
        target = get_codec("cisco_iosxr")
        verdict = self._judge(job, target)
        assert verdict["wrong"] == [] and verdict["tally"]["declared"] == 3
        donor = _run("arista_eos", "cisco_iosxe", _EOS).validation
        vlan_only = [p for p in donor.unsupported_paths if p.path == "/vlans/vlan/id"]
        assert vlan_only, "the donor report no longer lists /vlans/vlan/id"
        job.validation.unsupported_paths = vlan_only
        job.validation.lossy_paths = []
        verdict = self._judge(job, target)
        assert len(verdict["wrong"]) == 3 and all("the report lists none of" in w for w in verdict["wrong"])

    @pytest.mark.parametrize("target_name", sorted(WRITES_NO_PORT_VLANS))
    def test_a_port_gone_with_its_vlans_declared(self, target_name: str) -> None:
        """On these targets the report accounts for every membership,
        and so for nothing that can be seen to fail: the port's name
        in a line is the one thing looked for.  The same job, with the
        port in the output under another name than the job reports."""
        target = get_codec(target_name)
        job = _run("arista_eos", target_name, _EOS)
        verdict = self._judge(job, target)
        assert verdict["wrong"] == [], verdict["wrong"]
        assert dict(verdict["tally"]) == {"declared": 3, "looked for by name": 2}
        final = job.port_renames["Ethernet1"]
        other = final[:-1] + "9"
        assert final.endswith("1") and final in job.rendered and other not in job.rendered
        job.rendered = job.rendered.replace(final, other)
        verdict = self._judge(job, target)
        assert verdict["wrong"] == [
            f"port 'Ethernet1' has a VLAN and its name '{final}' is in no line of the output",
        ]
        assert verdict["tally"]["declared"] == 3

    def test_a_stanza_not_written_at_all(self) -> None:
        """IOS-XR has no form for a switch port's VLANs, so such a
        port's stanza is its header and nothing under it.  A renderer
        that left those out would lose the port in a job whose report
        is as it was."""
        target = get_codec("cisco_iosxr")
        job = _run("arista_eos", "cisco_iosxr", _EOS)
        final = job.port_renames["Ethernet2"]
        stanza = f"interface {final}\n!\n"
        assert job.rendered.count(stanza) == 1
        job.rendered = job.rendered.replace(stanza, "")
        assert self._judge(job, target)["wrong"] == [
            f"port 'Ethernet2' has a VLAN and its name '{final}' is in no line of the output",
        ]


# What each text reader makes of a stanza typed by hand, so that neither
# reading of an output is the oracle for the other.
_TYPED = {
    "cisco_nxos": (
        "interface Ethernet1/1\n  switchport access vlan 10\n"
        "interface Ethernet1/2\n  switchport mode trunk\n  switchport trunk native vlan 10\n"
        "  switchport trunk allowed vlan 10,20-21\n"
        "interface Ethernet1/3\n  switchport mode trunk\n"
        # A native VLAN the list leaves out is no membership.
        "interface Ethernet1/4\n  switchport mode trunk\n  switchport trunk native vlan 10\n"
        "  switchport trunk allowed vlan 20\n"
        # ... and beside no list (every VLAN) it is one.
        "interface Ethernet1/5\n  switchport mode trunk\n  switchport trunk native vlan 21\n",
        {(10, "Ethernet1/1", "u"), (10, "Ethernet1/2", "u"), (20, "Ethernet1/2", "t"), (21, "Ethernet1/2", "t"),
         (10, "Ethernet1/3", "t"), (20, "Ethernet1/3", "t"), (21, "Ethernet1/3", "t"),
         (20, "Ethernet1/4", "t"),
         (10, "Ethernet1/5", "t"), (20, "Ethernet1/5", "t"), (21, "Ethernet1/5", "u")},
    ),
    "dell_os10": (
        "interface ethernet1/1/1\n switchport access vlan 10\n"
        "interface ethernet1/1/2\n switchport mode trunk\n switchport access vlan 10\n"
        " switchport trunk allowed vlan 20-21\n"
        "interface ethernet1/1/3\n switchport mode trunk\n"
        # The access VLAN of a trunk is carried with no allowed line,
        "interface ethernet1/1/4\n switchport mode trunk\n switchport access vlan 21\n"
        # and not once it is taken back.
        "interface ethernet1/1/5\n switchport mode trunk\n switchport access vlan 10\n"
        " no switchport access vlan\n switchport trunk allowed vlan 20\n",
        {(10, "ethernet1/1/1", "u"), (10, "ethernet1/1/2", "u"), (20, "ethernet1/1/2", "t"),
         (21, "ethernet1/1/2", "t"), (21, "ethernet1/1/4", "u"), (20, "ethernet1/1/5", "t")},
    ),
    "aruba_aoscx": (
        "interface 1/1/1\n    no routing\n    vlan access 10\n"
        "interface lag 1\n    no routing\n    vlan trunk native 10\n    vlan trunk allowed 10,20-21\n"
        "interface 1/1/3\n    no routing\n    vlan trunk allowed all\n"
        "interface 1/1/4\n    no routing\n    vlan trunk native 10\n    vlan trunk allowed 20\n",
        {(10, "1/1/1", "u"), (10, "lag 1", "u"), (20, "lag 1", "t"), (21, "lag 1", "t"),
         (10, "1/1/3", "t"), (20, "1/1/3", "t"), (21, "1/1/3", "t"), (20, "1/1/4", "t")},
    ),
    "aruba_aoss": (
        "vlan 10\n   untagged 1-2,A1\n   exit\nvlan 20\n   tagged 2,Trk1\n   untagged A1\n   exit\n"
        "vlan 21\n   tagged 1/1-1/2\n   exit\n",
        {(10, "1", "u"), (10, "2", "u"), (20, "A1", "u"), (20, "2", "t"), (20, "Trk1", "t"),
         (21, "1/1", "t"), (21, "1/2", "t")},
    ),
    "juniper_junos": (
        'set vlans USERS vlan-id 10\nset vlans "V 20" vlan-id 20\nset vlans V21 vlan-id 21\n'
        "set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode access\n"
        "set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members USERS\n"
        "set interfaces ge-0/0/2 unit 0 family ethernet-switching interface-mode trunk\n"
        "set interfaces ge-0/0/2 unit 0 family ethernet-switching vlan members USERS\n"
        'set interfaces ge-0/0/2 unit 0 family ethernet-switching vlan members "V 20"\n'
        "set interfaces ge-0/0/2 unit 0 family ethernet-switching vlan members 21\n"
        "set interfaces ge-0/0/2 native-vlan-id 10\n"
        "set interfaces ge-0/0/3 unit 0 family ethernet-switching interface-mode trunk\n"
        "set interfaces ge-0/0/3 unit 0 family ethernet-switching vlan members all\n"
        "set interfaces ge-0/0/4 unit 0 family ethernet-switching interface-mode trunk\n"
        'set interfaces ge-0/0/4 unit 0 family ethernet-switching vlan members "V 20"\n'
        "set interfaces ge-0/0/4 native-vlan-id 10\n",
        {(10, "ge-0/0/1", "u"), (10, "ge-0/0/2", "u"), (20, "ge-0/0/2", "t"), (21, "ge-0/0/2", "t"),
         (10, "ge-0/0/3", "t"), (20, "ge-0/0/3", "t"), (21, "ge-0/0/3", "t"), (20, "ge-0/0/4", "t")},
    ),
}
_TYPED["cisco_iosxe_cli"] = (_TYPED["cisco_nxos"][0].replace("  ", " "), _TYPED["cisco_nxos"][1])
_TYPED["arista_eos"] = (_TYPED["cisco_nxos"][0].replace("  ", "   "), _TYPED["cisco_nxos"][1])


@pytest.mark.parametrize("codec", sorted(READ_AS_TEXT))
def test_each_text_reader_on_typed_stanzas(codec: str) -> None:
    text, expected = _TYPED[codec]
    assert set(read_text(text, codec).memberships({10, 20, 21})) == expected


def test_a_name_in_a_line() -> None:
    assert _in_a_line("Ethernet1/1", "interface Ethernet1/1\n")
    assert not _in_a_line("Ethernet1/1", "interface Ethernet1/10\n")
    assert not _in_a_line("1/1/1", "interface 1/1/11\ninterface 2/1/1/1\n")
    assert _in_a_line("lag1", "interface lag 1\n") and _in_a_line("lag 1", "interface lag 1\n")
    assert _in_a_line("ge-0/0/1", "set interfaces ge-0/0/1 unit 0 family ethernet-switching\n")
    # ... and as the targets that write no port VLANs name a port.
    assert _in_a_line("igb1", "    <igb1>\n      <if>igb1</if>\n")
    assert not _in_a_line("igb1", "<vlanif>igb1_vlan30</vlanif>\n")
    assert _in_a_line("port1", '    edit "port1"\n') and not _in_a_line("port1", '    edit "port10"\n')
    assert _in_a_line("ether1", "set [ find default-name=ether1 ] disabled=no\n")
    assert _in_a_line("eth1", "    ethernet eth1 {\n") and not _in_a_line("eth1", "    ethernet eth1.5 {\n")
    assert _in_a_line("GigabitEthernet0/1", "    <name>GigabitEthernet0/1</name>\n")
    assert not _in_a_line("ge-0/0/1", "set interfaces ge-0/0/1.5 vlan-id 5\nset interfaces xe-0/0/1 mtu 9000\n")

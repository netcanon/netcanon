"""Aruba AOS-S: a stanza ends where the switch ends a context, and a
port's VLANs can be stated from the port's side.

The switch reads a configuration as CLI commands.  HPE describes a
context by the commands that enter and leave it -- ``exit`` returns to
the previous context, ``end`` to the Manager level, and a command that
enters another context leaves the open one -- and no HPE switch guide
says that indentation plays a part.  The parser used to end a
``vlan``, ``interface`` or ``vrrp vrid`` stanza at the first line that
was not indented as well, and to skip every indented line after it.
A config committed with its indentation lost (a forum capture,
KB.15.15) was read as three VLANs with nothing in them, in jobs that
said ``completed`` onto most targets (AOS-S itself among them), and no
job said a line was not read.

The rule now (``parse._ends_the_stanza``): a stanza ends at its
``exit`` or an ``end`` (in any letter case), at a line in column 0
that enters another context, or at a line in column 0 that the top of
the config reads.  Any other line in column 0 is the stanza's.  An
``oobm`` stanza is the management port's: nothing in it is read, and
the words it shares with the top (``ip default-gateway``) do not end
it; any other line of the top does.  ``tagged vlan <list>`` /
``untagged vlan <id>`` in an ``interface`` stanza, and ``interface
<ports> tagged|untagged vlan <list>`` on one line, are the VLAN's own
lines of the same meaning, and the later line wins.  A stanza for
several ports (``interface 1,3``, ``interface 1-4``) gives its VLAN
lines to each port it names, and says what else it sets.

Each check here is also handed the defect it is for -- the old rule,
put back in process -- and has to fail (the last section).  Two things
the rule does not mend are pinned as they are: a stanza header that is
indented is no header, and a line of the top inside a stanza that lost
its indentation ends the stanza.
"""

from __future__ import annotations

import ast
import inspect
import ipaddress
import re
import textwrap
from pathlib import Path

import pytest

from netcanon.migration.canonical.intent import CanonicalIntent
from netcanon.migration.codecs.aruba_aoss import deployment_detect
from netcanon.migration.codecs.aruba_aoss import parse as aoss_parse
from netcanon.migration.codecs.aruba_aoss.codec import ArubaAOSSCodec
from netcanon.migration.codecs.registry import get_codec
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures"
#: Every AOS-S input under ``tests/fixtures``: the real captures, the
#: synthetic config and the codec's own sample.
INPUTS = sorted(
    list((FIXTURES / "real" / "aruba_aoss").glob("*.cfg"))
    + list((FIXTURES / "synthetic" / "aruba_aoss").glob("*.cfg"))
    + list((FIXTURES / "aruba_aoss").glob("*.txt"))
)
KB1515 = FIXTURES / "real" / "aruba_aoss" / "hpe_community_5406rzl2_kb1515.cfg"
STACK = FIXTURES / "real" / "aruba_aoss" / "user_contrib_2930m_wc1611.cfg"

_HEAD = '; J9727A Configuration Editor; Created on release #WB.16.08.0001\nhostname "sw"\n'
_NEVER = re.compile(r"(?!)")


def _flat(text: str) -> str:
    """*text* with every line's leading white space removed."""
    return "\n".join(line.lstrip() for line in text.splitlines()) + "\n"


def _parse(text: str) -> CanonicalIntent:
    return ArubaAOSSCodec().parse(text)


def _summary(tree: CanonicalIntent) -> tuple:
    """What a shape is judged by: the VLANs (id, name, untagged, tagged,
    how many addresses), the interfaces (name, enabled, how many
    addresses), the routes, the LAGs and the hostname."""
    return (
        [(v.id, v.name, sorted(v.untagged_ports), sorted(v.tagged_ports), len(v.ipv4_addresses))
         for v in tree.vlans],
        [(i.name, i.enabled, len(i.ipv4_addresses)) for i in tree.interfaces],
        [r.destination for r in tree.static_routes],
        [lag.name for lag in tree.lags],
        tree.hostname,
    )


def _memberships(tree: CanonicalIntent) -> dict[int, tuple[list[str], list[str]]]:
    return {v.id: (sorted(v.untagged_ports), sorted(v.tagged_ports)) for v in tree.vlans}


def _run(prefix: str, low: int, high: int) -> list[str]:
    """``A2-A6`` typed out by hand, not by the parser's expander."""
    return [f"{prefix}{n}" for n in range(low, high + 1)]


# ---------------------------------------------------------------------------
# (a) A config without its indentation is the config
# ---------------------------------------------------------------------------


def _check_flat(path: Path) -> None:
    raw = path.read_text(encoding="utf-8")
    as_committed = _parse(raw).model_dump(mode="json")
    assert _parse(_flat(raw)).model_dump(mode="json") == as_committed, path.name


@pytest.mark.parametrize("path", INPUTS, ids=[p.name for p in INPUTS])
def test_a_config_without_its_indentation_is_the_config(path: Path) -> None:
    """Every AOS-S input, every line's leading white space removed,
    parses to the tree of the text as committed: every field, the
    Tier-3 rows included."""
    _check_flat(path)


def test_the_inputs_are_found() -> None:
    """The test above passes on an empty list, and on inputs that have
    no indentation to lose."""
    names = {path.name for path in INPUTS}
    assert {KB1515.name, STACK.name, "aruba_central_5memberstack_rendered.cfg", "kitchen_sink.cfg",
            "show_run_simple.txt"} <= names
    assert len(INPUTS) >= 8
    indented = [p for p in INPUTS if _flat(p.read_text(encoding="utf-8")) != p.read_text(encoding="utf-8")]
    assert len(indented) >= 7


# ---------------------------------------------------------------------------
# (b) kb1515, written out by hand from its text
# ---------------------------------------------------------------------------

#: id -> (name, untagged, tagged, how many addresses).  VLAN 1's ``no
#: untagged A1`` takes out a port the stanza had not put there: the tree
#: does not record a removal.  ``no ip address`` and ``ip
#: helper-address`` are not modelled.  The addresses themselves are read
#: from the capture's own lines (:func:`_kb1515_addresses`), not typed
#: here.
_KB1515_VLANS = {
    1: ("VLAN1", [], _run("A", 2, 24) + _run("B", 1, 24), 0),
    2: ("VLAN2", ["A1"], _run("A", 2, 6) + _run("A", 8, 10) + _run("A", 12, 24) + _run("B", 1, 24), 1),
    3: ("VLAN3", [], _run("A", 2, 9) + _run("A", 11, 12) + _run("A", 14, 24) + _run("B", 1, 24), 1),
}


def _kb1515_addresses(raw: str) -> dict[int, list[tuple[str, int]]]:
    """The ``ip address <address> <mask>`` lines of each ``vlan N`` block
    of the capture, from its header to its ``exit``, read by this test
    and not by the parser."""
    found: dict[int, list[tuple[str, int]]] = {}
    for vid, body in re.findall(r"^vlan (\d+)\n(.*?)^exit$", raw, flags=re.M | re.S):
        found[int(vid)] = [
            (address, ipaddress.IPv4Network(f"0.0.0.0/{mask}").prefixlen)
            for address, mask in re.findall(r"^ip address (\S+) (\S+)$", body, flags=re.M)
        ]
    return found


def _check_kb1515() -> None:
    raw = KB1515.read_text(encoding="utf-8")
    assert _flat(raw) == raw.replace("\r\n", "\n"), "kb1515 is committed with every line in column 0"
    addresses = _kb1515_addresses(raw)
    assert {vid: len(found) for vid, found in addresses.items()} == {
        vid: count for vid, (_name, _u, _t, count) in _KB1515_VLANS.items()
    }
    tree = _parse(raw)
    assert tree.hostname == "HP-5406Rzl2"
    assert tree.snmp is not None
    assert {
        v.id: (v.name, sorted(v.untagged_ports), sorted(v.tagged_ports),
               [(a.ip, a.prefix_length) for a in v.ipv4_addresses])
        for v in tree.vlans
    } == {vid: (name, sorted(u), sorted(t), addresses[vid]) for vid, (name, u, t, _n) in _KB1515_VLANS.items()}
    ports = set(_run("A", 1, 24) + _run("B", 1, 24))
    names = {i.name for i in tree.interfaces}
    assert names == ports | {"Vlan2", "Vlan3"}
    svis = {i.name: (i.description, [(a.ip, a.prefix_length) for a in i.ipv4_addresses])
            for i in tree.interfaces if i.name.startswith("Vlan")}
    assert svis == {"Vlan2": ("VLAN2", addresses[2]), "Vlan3": ("VLAN3", addresses[3])}
    # The oobm's ``no ip address`` is the management port's; nothing else
    # in the text is a route or a LAG.
    assert tree.static_routes == [] and tree.lags == []


def test_kb1515_by_hand() -> None:
    _check_kb1515()


def test_kb1515_reaches_its_own_platform() -> None:
    """AOS-S onto AOS-S: the job carries the VLANs' lists and both
    addresses, where it used to carry three empty VLANs."""
    aoss = get_codec("aruba_aoss")
    raw = KB1515.read_text(encoding="utf-8")
    job = run_plan_with_checked_names(aoss, aoss, raw, port_rename_map={})
    assert job.status == "completed", (job.status, job.error)
    out = job.rendered
    assert re.search(r"^vlan 2\n(?:   .*\n)*?   untagged A1\n", out, flags=re.M), out
    stated = [address for found in _kb1515_addresses(raw).values() for address, _prefix in found]
    assert len(stated) == 2 and all(out.count(f"ip address {address}") == 1 for address in stated), out
    assert _memberships(aoss.parse(out)) == _memberships(_parse(raw))


# ---------------------------------------------------------------------------
# (c) Shapes, each with the tree written out
# ---------------------------------------------------------------------------

#: label -> (text, the tree's summary).  Addresses are synthetic.
SHAPES: dict[str, tuple[str, tuple]] = {
    "a VLAN with no exit, then an interface": (
        'hostname "x"\nvlan 10\n   name "TEN"\n   untagged 1\n'
        "interface 2\n   disable\n   exit\nvlan 20\n   untagged 3\n   exit\n",
        ([(10, "TEN", ["1"], [], 0), (20, "", ["3"], [], 0)],
         [("2", False, 0), ("1", True, 0), ("3", True, 0)], [], [], "x"),
    ),
    "a vrrp vrid with no exit takes the VLAN's": (
        "vlan 10\n   ip address 10.0.10.1 255.255.255.0\n   vrrp vrid 1\n"
        "      virtual-ip-address 10.0.10.254\n      enable\n   exit\n"
        "vlan 20\n   untagged 5\n   exit\ninterface 6\n   disable\n   exit\n",
        ([(10, "", [], [], 1), (20, "", ["5"], [], 0)],
         [("Vlan10", True, 1), ("6", False, 0), ("5", True, 0)], [], [], ""),
    ),
    "a vrrp vrid and its VLAN, both closed": (
        "vlan 10\n   ip address 10.0.10.1 255.255.255.0\n   vrrp vrid 1\n"
        "      virtual-ip-address 10.0.10.254\n      exit\n   exit\n"
        "vlan 20\n   untagged 5\n   exit\n",
        ([(10, "", [], [], 1), (20, "", ["5"], [], 0)], [("Vlan10", True, 1), ("5", True, 0)], [], [], ""),
    ),
    "a router ospf block between two stanzas": (
        "vlan 10\n   untagged 1\n   ip address 10.0.10.1 255.255.255.0\n   ip ospf 1 area backbone\n   exit\n"
        "router ospf\n   area backbone\n   redistribute connected\n   enable\n   exit\n"
        "vlan 20\n   untagged 2\n   exit\n",
        ([(10, "", ["1"], [], 1), (20, "", ["2"], [], 0)],
         [("Vlan10", True, 1), ("1", True, 0), ("2", True, 0)], [], [], ""),
    ),
    "a flat router ospf after a VLAN with no exit": (
        "vlan 10\n   untagged 1\nrouter ospf\narea backbone\nenable\nexit\n"
        "ip route 0.0.0.0/0 10.0.10.254\nvlan 20\n   untagged 2\n   exit\n",
        ([(10, "", ["1"], [], 0), (20, "", ["2"], [], 0)], [("1", True, 0), ("2", True, 0)],
         ["0.0.0.0/0"], [], ""),
    ),
    "a VLAN that never ends, then lines of the top": (
        'vlan 10\n   untagged 1\nip route 10.9.0.0/16 10.0.10.254\ntrunk 7-8 trk1 lacp\nhostname "late"\n',
        ([(10, "", ["1"], [], 0)], [("1", True, 0), ("7", True, 0), ("8", True, 0)],
         ["10.9.0.0/16"], ["trk1"], "late"),
    ),
    "an oobm with an address after a VLAN with no exit": (
        "vlan 10\n   untagged 1\noobm\n   ip address 192.0.2.10 255.255.255.0\n   exit\n"
        "interface 4\n   disable\n   exit\n",
        ([(10, "", ["1"], [], 0)], [("4", False, 0), ("1", True, 0)], [], [], ""),
    ),
    "a flat oobm, then a flat VLAN": (
        'oobm\nip address 192.0.2.10 255.255.255.0\nexit\nvlan 1\nname "V1"\nuntagged 1-2\n'
        "ip address 10.0.1.1 255.255.255.0\nexit\n",
        ([(1, "V1", ["1", "2"], [], 1)], [("Vlan1", True, 1), ("1", True, 0), ("2", True, 0)], [], [], ""),
    ),
    "a dhcp-server pool with its exit after a VLAN with no exit": (
        'vlan 10\n   untagged 1\ndhcp-server pool "p"\n   range 10.0.10.10 10.0.10.20\n   exit\n'
        "vlan 20\n   untagged 2\n   exit\n",
        ([(10, "", ["1"], [], 0), (20, "", ["2"], [], 0)], [("1", True, 0), ("2", True, 0)], [], [], ""),
    ),
    "a VLAN name with a line break in it": (
        'vlan 10\n   name "first\nsecond"\n   untagged 1\n   tagged 2\n   exit\n'
        "vlan 20\n   untagged 3\n   exit\n",
        ([(10, '"first', ["1"], ["2"], 0), (20, "", ["3"], [], 0)],
         [("1", True, 0), ("2", True, 0), ("3", True, 0)], [], [], ""),
    ),
    "two interfaces, the first with no exit": (
        'interface 1\n   name "up"\ninterface 2\n   disable\n   exit\n',
        ([], [("1", True, 0), ("2", False, 0)], [], [], ""),
    ),
    "a flat interface with a line the parser does not read": (
        'interface 5\nname "x"\nspeed-duplex auto\ndisable\nexit\ninterface 6\nexit\n',
        ([], [("5", False, 0), ("6", True, 0)], [], [], ""),
    ),
    "a line of the top inside a flat VLAN ends it": (
        'vlan 10\nname "TEN"\nuntagged 1\nip route 10.9.0.0/16 10.0.10.254\ntagged 2\nexit\n',
        ([(10, "TEN", ["1"], [], 0)], [("1", True, 0)], ["10.9.0.0/16"], [], ""),
    ),
    "a flat vrrp vrid inside a flat VLAN": (
        "vlan 10\nip address 10.0.10.1 255.255.255.0\nvrrp vrid 1\nvirtual-ip-address 10.0.10.254\n"
        "priority 200\nenable\nexit\nuntagged 3\nexit\nvlan 20\nuntagged 4\nexit\n",
        ([(10, "", ["3"], [], 1), (20, "", ["4"], [], 0)],
         [("Vlan10", True, 1), ("3", True, 0), ("4", True, 0)], [], [], ""),
    ),
    "a body line in column 0 between indented ones": (
        'vlan 20\n   name "USERS"\nip address 10.0.20.1 255.255.255.0\n   untagged 1-2\n   tagged 3\n   exit\n',
        ([(20, "USERS", ["1", "2"], ["3"], 1)],
         [("Vlan20", True, 1), ("1", True, 0), ("2", True, 0), ("3", True, 0)], [], [], ""),
    ),
    # A vrrp vrid with no ``exit`` ends at the next VLAN's header, and so
    # does the VLAN it is in: the next VLAN is read.
    "a vrrp vrid with no exit, then the next VLAN": (
        "vlan 10\n   ip address 10.0.10.1 255.255.255.0\n   vrrp vrid 1\n"
        "      virtual-ip-address 10.0.10.254\nvlan 20\n   untagged 4\n   exit\n",
        ([(10, "", [], [], 1), (20, "", ["4"], [], 0)], [("Vlan10", True, 1), ("4", True, 0)], [], [], ""),
    ),
    # ``end`` leaves every context (HPE), and ``exit`` is a command in
    # any letter case.
    "an end closes a flat VLAN": (
        'vlan 10\nname "TEN"\nuntagged 1\nend\ntagged 2\nexit\n',
        ([(10, "TEN", ["1"], [], 0)], [("1", True, 0)], [], [], ""),
    ),
    "an EXIT in capitals closes a flat VLAN": (
        'vlan 10\nname "TEN"\nuntagged 1\nEXIT\nspanning-tree\ntagged 2\nexit\n',
        ([(10, "TEN", ["1"], [], 0)], [("1", True, 0)], [], [], ""),
    ),
    "an end in a flat vrrp vrid closes its VLAN too": (
        "vlan 10\nip address 10.0.10.1 255.255.255.0\nvrrp vrid 1\nvirtual-ip-address 10.0.10.254\n"
        "end\nexit\nuntagged 3\nexit\n",
        ([(10, "", [], [], 1)], [("Vlan10", True, 1)], [], [], ""),
    ),
    "an end in a flat interface": (
        "interface 5\ndisable\nEnd\nenable\nexit\n",
        ([], [("5", False, 0)], [], [], ""),
    ),
    # Not mended: the top of the config skips an indented line, so an
    # indented header is no header and its stanza is read as nothing.
    "indented headers (pinned: read as nothing)": (
        " vlan 10\n   untagged 1\n   exit\n interface 2\n   disable\n   exit\n",
        ([], [], [], [], ""),
    ),
}

#: The shapes the old rule (a line in column 0 ends the stanza) read
#: otherwise.  The line of the top inside a flat VLAN is among them: the
#: old rule lost the VLAN's name and its untagged port as well.
_THE_OLD_RULE_READS_OTHERWISE = {
    "a flat oobm, then a flat VLAN",
    "a VLAN name with a line break in it",
    "a flat interface with a line the parser does not read",
    "a line of the top inside a flat VLAN ends it",
    "a flat vrrp vrid inside a flat VLAN",
    "a body line in column 0 between indented ones",
    "an end closes a flat VLAN",
    "an EXIT in capitals closes a flat VLAN",
    "an end in a flat vrrp vrid closes its VLAN too",
    "an end in a flat interface",
}
#: The shapes for ``end`` and a capital ``EXIT``.
_LEAVING = {
    "an end closes a flat VLAN", "an EXIT in capitals closes a flat VLAN",
    "an end in a flat vrrp vrid closes its VLAN too", "an end in a flat interface",
}
_VRRP_WITH_NO_EXIT = "a vrrp vrid with no exit, then the next VLAN"


def _check_shape(label: str) -> None:
    text, want = SHAPES[label]
    assert _summary(_parse(text)) == want, label


@pytest.mark.parametrize("label", list(SHAPES))
def test_a_shape(label: str) -> None:
    _check_shape(label)


def test_a_flat_vrrp_group_is_read_whole() -> None:
    """The flat group's lines are the group's, on the VLAN's SVI."""
    tree = _parse(SHAPES["a flat vrrp vrid inside a flat VLAN"][0])
    svi = next(i for i in tree.interfaces if i.name == "Vlan10")
    assert [(g.group_id, g.virtual_ips, g.priority) for g in svi.vrrp_groups] == [(1, ["10.0.10.254"], 200)]


#: The first word of each context :data:`~parse._OPENS_A_CONTEXT_RE`
#: names, and a header of it.  Each is met in column 0 inside an
#: ``interface`` stanza that has no ``exit``, followed by a line the
#: interface's reader would take for its own (``enable``).
OPENERS = {
    "interface": "interface x:1",
    "router": "router ospf",
    "stacking": "stacking",
    "vsf": "vsf",
    "dhcp-server": 'dhcp-server pool "p"',
    "device-profile": 'device-profile name "d"',
}


def _check_opener(word: str) -> None:
    tree = _parse(f"interface 1\n   disable\n{OPENERS[word]}\nenable\nexit\n")
    assert [(i.name, i.enabled) for i in tree.interfaces] == [("1", False)], word


@pytest.mark.parametrize("word", list(OPENERS))
def test_a_context_the_top_does_not_read_ends_a_stanza(word: str) -> None:
    """The context's header ends the port's stanza: the line after it
    is the context's, not the port's."""
    _check_opener(word)


def test_every_context_the_rule_names_has_a_shape() -> None:
    pattern = aoss_parse._OPENS_A_CONTEXT_RE.pattern
    assert pattern.startswith("^(?:") and pattern.endswith(")[ \\t]*$"), pattern
    alternatives = pattern[len("^(?:"):-len(")[ \\t]*$")].split("|")
    assert {alternative.split("[")[0] for alternative in alternatives} == set(OPENERS)


#: A stanza for several ports.  ``interface 1,3`` is no header
#: :data:`~parse._IFACE_HEADER_RE` takes; ``interface 1-2`` is one.
#: Neither makes a record named after its list.
_SEVERAL = (
    "vlan 1\n   untagged 1-4\n   exit\nvlan 10\n   exit\n"
    "interface 1,3\n   tagged vlan 10\n   exit\n"
    "interface 2-4\n   untagged vlan 10\n   disable\n   exit\n"
)


def _check_several() -> None:
    tree = _parse(_HEAD + _SEVERAL)
    assert _memberships(tree) == {1: (["1"], []), 10: (["2", "3", "4"], ["1", "3"])}
    assert sorted(i.name for i in tree.interfaces) == ["1", "2", "3", "4"]
    assert all(i.enabled for i in tree.interfaces)
    assert tree.dropped_tier3_sections == [
        "interface 2-4 (a context for several ports: what it sets other than their VLANs is not translated)"
    ]
    # Flat, it is the same config.
    assert _parse(_HEAD + _flat(_SEVERAL)).model_dump(mode="json") == tree.model_dump(mode="json")


def test_a_stanza_for_several_ports() -> None:
    """Its VLAN lines are each port's; what else it sets is said, and
    not given to a record named ``2-4``."""
    _check_several()


# ---------------------------------------------------------------------------
# What the five column-0 body lines of the committed render are
# ---------------------------------------------------------------------------

RENDERED = FIXTURES / "real" / "aruba_aoss" / "aruba_central_5memberstack_rendered.cfg"


#: The provenance of the fixture names its five body lines in column 0.
_THE_OLD_SCRIPTS_FIVE = [
    ("interface 1/3", "no power-over-ethernet"), ("interface 1/4", "no power-over-ethernet"),
    ("vlan 1", "ip address"), ("vlan 20", "ip address"), ("vlan 30", "ip address"),
]


def _flush_body_lines(text: str) -> list[tuple[str, str]]:
    """Each body line in column 0, from header to ``exit``, under its
    header: the first two words of it.  A walk this test owns."""
    flush: list[tuple[str, str]] = []
    header = ""
    for line in text.splitlines():
        stripped = line.strip()
        if not header:
            if re.fullmatch(r"(?:vlan \d+|interface \S+|device-profile .+)", line):
                header = line
            continue
        if stripped == "exit":
            header = ""
        elif stripped and not line[0].isspace():
            flush.append((header, " ".join(stripped.split()[:2])))
    return flush


def _check_rendered(text: str) -> None:
    assert _flush_body_lines(text) == _THE_OLD_SCRIPTS_FIVE


def test_the_committed_renders_flat_body_lines_are_the_old_scripts_five() -> None:
    """The fixture's provenance says that five body lines are in column
    0 (the render script of the time dedented them) and names them."""
    _check_rendered(RENDERED.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# (d) A port's VLAN lines
# ---------------------------------------------------------------------------

_VLANS = "vlan 1\n   untagged 1-6\n   exit\nvlan 10\n   exit\nvlan 20\n   exit\nvlan 30\n   exit\n"

#: label -> (a text that states memberships from the ports' side, the
#: same memberships stated under ``vlan N``).
EQUIVALENT: dict[str, tuple[str, str]] = {
    "in interface stanzas": (
        _VLANS
        + "interface 3\n   tagged vlan 10,20\n   no untagged vlan 1\n   exit\n"
        "interface 4\n   untagged vlan 20\n   exit\n"
        "interface 5\n   tagged vlan 10\n   forbid vlan 30\n   exit\n"
        "interface 6\n   no tagged vlan 10\n   exit\n",
        "vlan 1\n   untagged 1-6\n   no untagged 3\n   exit\nvlan 10\n   tagged 3,5\n   exit\n"
        "vlan 20\n   untagged 4\n   tagged 3\n   exit\nvlan 30\n   exit\n"
        "interface 3\n   exit\ninterface 4\n   exit\ninterface 5\n   exit\ninterface 6\n   exit\n",
    ),
    "in interface stanzas, flat": (
        _flat(
            _VLANS
            + "interface 3\n   tagged vlan 10,20\n   no untagged vlan 1\n   exit\n"
            "interface 4\n   untagged vlan 20\n   exit\n"
        ),
        "vlan 1\n   untagged 1-6\n   no untagged 3\n   exit\nvlan 10\n   tagged 3\n   exit\n"
        "vlan 20\n   untagged 4\n   tagged 3\n   exit\nvlan 30\n   exit\n"
        "interface 3\n   exit\ninterface 4\n   exit\n",
    ),
    "on one line": (
        _VLANS
        + "interface 3 tagged vlan 10,20\nno interface 3 untagged vlan 1\ninterface 4 untagged vlan 20\n"
        "interface 5 tagged vlan 10\nno interface 6 tagged vlan 10\n",
        "vlan 1\n   untagged 1-6\n   no untagged 3\n   exit\nvlan 10\n   tagged 3,5\n   exit\n"
        "vlan 20\n   untagged 4\n   tagged 3\n   exit\nvlan 30\n   exit\n",
    ),
    "on one line, for a list of ports": (
        _VLANS + "interface 1-2,5 tagged vlan 10,20,30-30\n",
        "vlan 1\n   untagged 1-6\n   exit\nvlan 10\n   tagged 1-2,5\n   exit\n"
        "vlan 20\n   tagged 1-2,5\n   exit\nvlan 30\n   tagged 1-2,5\n   exit\n",
    ),
    "for a LAG": (
        "trunk 7-8 trk1 lacp\n" + _VLANS + "interface Trk1\n   tagged vlan 10\n   exit\n",
        "trunk 7-8 trk1 lacp\nvlan 1\n   untagged 1-6\n   exit\nvlan 10\n   tagged Trk1\n   exit\n"
        "vlan 20\n   exit\nvlan 30\n   exit\ninterface Trk1\n   exit\n",
    ),
    "the later line wins: the port's": (
        "vlan 1\n   untagged 1-6\n   exit\nvlan 20\n   untagged 4\n   exit\nvlan 30\n   exit\n"
        "interface 4\n   untagged vlan 30\n   exit\n",
        "vlan 1\n   untagged 1-6\n   exit\nvlan 20\n   exit\nvlan 30\n   untagged 4\n   exit\n"
        "interface 4\n   exit\n",
    ),
    "the later line wins: the VLAN's": (
        "vlan 1\n   untagged 1-6\n   exit\nvlan 30\n   exit\ninterface 4\n   untagged vlan 30\n   exit\n"
        "vlan 20\n   untagged 4\n   exit\n",
        "vlan 1\n   untagged 1-6\n   exit\nvlan 30\n   exit\ninterface 4\n   exit\n"
        "vlan 20\n   untagged 4\n   exit\n",
    ),
    # A port moved out of VLAN 1 and back into it is in VLAN 1: what a
    # later line takes out is what the list held when that line was read.
    "moved out and back": (
        "vlan 1\n   untagged 1-6\n   exit\nvlan 20\n   untagged 4\n   exit\n"
        "interface 4\n   untagged vlan 1\n   exit\n",
        "vlan 1\n   untagged 1-6\n   exit\nvlan 20\n   exit\ninterface 4\n   exit\n",
    ),
}

_TRAP = "moved out and back"
_VLANS_LATER = "the later line wins: the VLAN's"


def _check_equivalent(label: str) -> None:
    ports_side, vlans_side = EQUIVALENT[label]
    got = _parse(_HEAD + ports_side).model_dump(mode="json")
    want = _parse(_HEAD + vlans_side).model_dump(mode="json")
    assert got == want, label


@pytest.mark.parametrize("label", list(EQUIVALENT))
def test_a_ports_line_is_the_vlans_line(label: str) -> None:
    """The tree of a text that states a port's VLANs from the port's
    side is the tree of the same memberships stated under ``vlan N``:
    every field, the records and their order included."""
    _check_equivalent(label)


def test_the_memberships_are_the_ones_the_lines_state() -> None:
    """The first case above, written out: the two texts could agree on
    something wrong."""
    tree = _parse(_HEAD + EQUIVALENT["in interface stanzas"][0])
    assert _memberships(tree) == {
        1: (["1", "2", "5", "6"], []), 10: ([], ["3", "5"]), 20: (["4"], ["3"]), 30: ([], []),
    }
    assert _memberships(_parse(_HEAD + EQUIVALENT[_TRAP][0]))[1] == (["1", "2", "3", "4", "5", "6"], [])


#: The memberships of the first case, as the AOS-S output must give
#: them back.
_ROUND_TRIP = {1: (["1", "2", "5", "6"], []), 10: ([], ["3", "5"]), 20: (["4"], ["3"]), 30: ([], [])}


def _check_round_trip() -> None:
    codec = ArubaAOSSCodec()
    out = codec.render(codec.parse(_HEAD + EQUIVALENT["in interface stanzas"][0]))
    assert not any(aoss_parse._PORT_VLAN_LINE_RE.match(line.strip()) for line in out.splitlines()), out
    assert _memberships(codec.parse(out)) == _ROUND_TRIP, out


def test_the_renderer_writes_them_under_the_vlan() -> None:
    """The output states a port's VLANs as a full ``show
    running-config`` does, under ``vlan N``, and reads back to the
    memberships the port's lines stated."""
    _check_round_trip()


def _check_undeclared() -> None:
    text = (
        "interface 3\n   tagged vlan 10,20\n   exit\n" + _VLANS
        + "interface 4 untagged vlan 99\ninterface 5\n   tagged vlan 10,40-42\n   exit\n"
    )
    tree = _parse(_HEAD + text)
    assert sorted(v.id for v in tree.vlans) == [1, 10, 20, 30]
    assert _memberships(tree) == {1: (["1", "2", "3", "4", "5", "6"], []), 10: ([], ["5"]), 20: ([], []),
                                  30: ([], [])}
    assert tree.dropped_tier3_sections == [
        "interface 3 tagged vlan 10,20 (VLANs 10,20: declared by no vlan stanza above the line; not translated)",
        "interface 4 untagged vlan 99 (VLAN 99: declared by no vlan stanza above the line; not translated)",
        "interface 5 tagged vlan 10,40-42 (VLANs 40-42: declared by no vlan stanza above the line; "
        "not translated)",
    ]


def test_a_vlan_the_config_does_not_declare() -> None:
    """A port's line applies to a VLAN a stanza above it declares.  One
    that names another makes no VLAN, and is said -- including the
    lines that come before the VLAN stanzas, as ``show running-config``
    orders the two kinds."""
    _check_undeclared()


def test_the_rows_are_bounded() -> None:
    lines = "".join(f"interface 1 tagged vlan {vid}\n" for vid in range(100, 400))
    rows = _parse(_HEAD + "vlan 1\n   untagged 1\n   exit\n" + lines).dropped_tier3_sections
    assert len(rows) == aoss_parse._ROWS_SHOWN + 1
    assert rows[-1] == "250 more lines left out as the rows above say (not translated; not listed)"
    alike = _parse(_HEAD + "interface 1 tagged vlan 9\n" * 3).dropped_tier3_sections
    assert alike == [
        "interface 1 tagged vlan 9 (VLAN 9: declared by no vlan stanza above the line; not translated; 3 lines)"
    ]
    # A ``no`` line of a stanza is quoted as the vendor writes it on one line.
    removed = _parse(_HEAD + "interface 3\n   no tagged vlan 30\n   exit\n").dropped_tier3_sections
    assert removed == [
        "no interface 3 tagged vlan 30 (VLAN 30: declared by no vlan stanza above the line; not translated)"
    ]


def _check_row_text() -> None:
    evens = ",".join(str(vid) for vid in range(2, 42, 2))
    rows = _parse(_HEAD + f"interface 1 tagged vlan {evens}\n").dropped_tier3_sections
    assert rows == [
        f"interface 1 tagged vlan {evens} (VLANs 2,4,6,8,10,12,14,16 and 12 more: declared by no vlan "
        f"stanza above the line; not translated)"
    ]
    ports = ",".join(str(n) for n in range(1, 400))
    (row,) = _parse(_HEAD + f"interface {ports} tagged vlan 9\n").dropped_tier3_sections
    assert len(row) < 200 and row.startswith(f"interface {ports[:100]}") and "\u2026 (VLAN 9:" in row, row


def test_a_row_is_bounded_too() -> None:
    """A row quotes the first characters of its line and the first few
    of the ids it names, and counts the rest: a line of a few bytes
    names thousands of ids, and a port list is as long as it likes."""
    _check_row_text()


def test_a_line_of_the_top_names_no_interface() -> None:
    """``interface 4 untagged vlan 20`` enters no context: it makes no
    record of its own, and none named after a word of it."""
    tree = _parse(_HEAD + "vlan 20\n   exit\ninterface 4 untagged vlan 20\ninterface 5 tagged vlan 99\n")
    assert [i.name for i in tree.interfaces] == ["4"]
    assert _memberships(tree) == {20: (["4"], [])}


def test_forbid_is_not_read() -> None:
    _check_forbid()


def _check_forbid() -> None:
    """``forbid`` makes no membership in either context, as under ``vlan
    N``: GVRP is not modelled."""
    text = (
        _VLANS + "interface 5\n   forbid vlan 10\n   exit\ninterface 6 forbid vlan 20\n"
        "vlan 40\n   forbid 2\n   exit\n"
    )
    without = _VLANS + "interface 5\n   exit\nvlan 40\n   exit\n"
    assert _parse(_HEAD + text).model_dump(mode="json") == _parse(_HEAD + without).model_dump(mode="json")


# ---------------------------------------------------------------------------
# (e) The oobm stanza
# ---------------------------------------------------------------------------

_OOBM = (
    "oobm\n   ip address 192.0.2.10 255.255.255.0\n   ip default-gateway 192.0.2.1\n"
    "   member 1\n      ip address 192.0.2.11 255.255.255.0\n      ip default-gateway 192.0.2.1\n"
    "      exit\n   interface enable\n   enable\n   exit\n"
    "ip default-gateway 10.0.0.1\nvlan 1\n   untagged 1-2\n   exit\n"
)


def _check_oobm() -> None:
    indented = _parse(_HEAD + _OOBM)
    flat = _parse(_HEAD + _flat(_OOBM))
    assert flat.model_dump(mode="json") == indented.model_dump(mode="json")
    assert [(r.destination, r.gateway) for r in flat.static_routes] == [("0.0.0.0/0", "10.0.0.1")]
    assert [i.name for i in flat.interfaces] == ["1", "2"]


def test_a_flat_oobm_reads_as_the_indented_one() -> None:
    """The management port's ``ip default-gateway`` is not the switch's
    default route, with its indentation or without; ``interface
    enable`` there makes no interface; the global gateway after the
    stanza's ``exit`` is the route."""
    _check_oobm()


def test_an_oobm_with_no_exit_ends_at_another_context() -> None:
    tree = _parse(_HEAD + "oobm\nip default-gateway 192.0.2.1\nvlan 1\nuntagged 1-2\nexit\n")
    assert tree.static_routes == []
    assert _memberships(tree) == {1: (["1", "2"], [])}


#: An ``oobm`` with no ``exit``, its words in it, and lines of the top
#: after it: the words are the management port's, the rest the switch's.
_OOBM_WITH_NO_EXIT = (
    "oobm\n   ip address 192.0.2.10 255.255.255.0\n   ip default-gateway 192.0.2.1\n"
    "   interface enable\n   member 1\n      ip address 192.0.2.11 255.255.255.0\n      exit\n"
    'hostname "after"\nip route 10.9.0.0/16 10.0.10.254\n'
)


def _check_oobm_with_no_exit() -> None:
    for text in (_OOBM_WITH_NO_EXIT, _flat(_OOBM_WITH_NO_EXIT)):
        tree = _parse(text)
        assert (tree.hostname, [(r.destination, r.gateway) for r in tree.static_routes], tree.interfaces) == (
            "after", [("10.9.0.0/16", "10.0.10.254")], [],
        ), text


def test_an_oobm_with_no_exit_ends_at_a_line_of_the_top() -> None:
    """A line the top reads that is no word of the context ends the
    ``oobm`` stanza: ``hostname`` is the switch's.  The words of the
    context never end it: its ``ip default-gateway`` is no route, and
    ``interface enable`` no interface, indented or not."""
    _check_oobm_with_no_exit()


# ---------------------------------------------------------------------------
# (f) Deployment detection reads a stanza by the same rule
# ---------------------------------------------------------------------------

_VSF = (
    "; hpStack_WC Configuration Editor; Created on release #WC.16.11.0025\n"
    "vsf\n   enable domain 1\n   member 1\n      type \"JL557A\" mac-address 000000-000000\n"
    "      priority 255\n      exit\n   member 2\n      type \"JL558A\" mac-address 000000-000000\n"
    "      exit\n   exit\nhostname \"sw\"\n"
)


def _members(text: str) -> list[tuple]:
    detection = deployment_detect.detect_deployment(text)
    assert detection is not None
    return [(m.id, m.part, m.modules) for m in detection.members]


def _check_detection() -> None:
    raw = STACK.read_text(encoding="utf-8")
    assert _members(raw) == [(1, "JL323A", {"A": "JL083A"})]
    assert _members(_flat(raw)) == _members(raw)
    assert _members(_VSF) == [(1, "JL557A", {}), (2, "JL558A", {})]
    assert _members(_flat(_VSF)) == _members(_VSF)


def test_detection_of_a_stack_without_its_indentation() -> None:
    _check_detection()


#: A ``stacking`` stanza with no ``exit``, then lines of the top the
#: parser does not read, then a ``flexible-module`` line of the top.
_STACK_WITH_NO_EXIT = (
    "; hpStack_WC Configuration Editor; Created on release #WC.16.11.0025\n"
    'stacking\n   member 1 type "JL323A" mac-address 000000-000000\n'
    '   member 2 type "JL322A" mac-address 000000-000000\n'
    "include-credentials\nno telnet-server\nflexible-module A type JL083A\nhostname \"x\"\n"
)


def _check_stack_with_no_exit() -> None:
    detection = deployment_detect.detect_deployment(_STACK_WITH_NO_EXIT)
    assert detection is not None
    assert [(m.id, m.part, m.modules) for m in detection.members] == [(1, "JL323A", {}), (2, "JL322A", {})]
    assert detection.notes == [deployment_detect._NOTE_MEMBER], detection.notes


def test_a_stacking_stanza_ends_at_a_module_line_of_the_top() -> None:
    """A ``flexible-module`` line in column 0 is the top's, which the
    detector reads there: the stanza's own begin ``member N``.  Taken
    for the stanza's, it gave a note that a module line of the stanza
    could not be read."""
    _check_stack_with_no_exit()


# ---------------------------------------------------------------------------
# One predicate, built from the top's own patterns
# ---------------------------------------------------------------------------


def _patterns_the_top_reads(source: str) -> set[str]:
    """The patterns ``parse_intent`` matches a top-level line with:
    every ``<NAME>.match(stripped_line)`` in its source."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(textwrap.dedent(source))):
        if (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "match"
            and isinstance(node.func.value, ast.Name) and node.args
            and isinstance(node.args[0], ast.Name) and node.args[0].id == "stripped_line"
        ):
            found.add(node.func.value.id)
    return found


def _the_tuple() -> set[str]:
    return {
        name for name, value in vars(aoss_parse).items()
        if name.endswith("_RE") and any(value is pattern for pattern in aoss_parse._TOP_LEVEL_LINES)
    }


def _check_one_predicate(source: str) -> None:
    assert _patterns_the_top_reads(source) == _the_tuple()


def test_the_stanza_rule_asks_what_the_top_reads() -> None:
    """A handler added at the top of the config ends a stanza in which
    its line stands: the predicate's tuple is the loop's own patterns,
    no more and no fewer."""
    _check_one_predicate(inspect.getsource(aoss_parse.parse_intent))
    assert len(aoss_parse._TOP_LEVEL_LINES) == len(_the_tuple()) >= 20


def test_the_three_stanza_readers_and_the_renderers_reader_ask_it() -> None:
    for fn in (aoss_parse._parse_vlan_stanza, aoss_parse._parse_vrrp_group_stanza,
               aoss_parse._parse_interface_stanza):
        source = inspect.getsource(fn)
        assert "_ends_the_stanza(line, stripped)" in source, fn.__name__
        assert "isspace" not in source, fn.__name__
    # ``_lists_read_from`` reads a stanza with ``_parse_vlan_stanza``.
    assert aoss_parse._lists_read_from('vlan 10\n   name "first\nsecond"\n   untagged 1\n   tagged 2') == (
        ["1"], ["2"],
    )
    assert aoss_parse._lists_read_from('vlan 10\n   name "first\nhostname x"\n   untagged 1') == ([], [])


# ---------------------------------------------------------------------------
# (g) Each check, handed the defect it is for
# ---------------------------------------------------------------------------


def _old_stanza_body(text: str, start: int) -> list[str]:
    body: list[str] = []
    for line in text[start:].split("\n")[1:]:
        if line.strip() and not line[0].isspace():
            break
        body.append(line)
    return body


@pytest.fixture
def the_old_rule(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """A line in column 0 ends a stanza, as it used to."""
    monkeypatch.setattr(aoss_parse, "_ends_the_stanza", lambda line, stripped: not line[0].isspace())
    return monkeypatch


def test_the_flat_check_fails_under_the_old_rule(the_old_rule: pytest.MonkeyPatch) -> None:
    failed = []
    for path in INPUTS:
        try:
            _check_flat(path)
        except AssertionError:
            failed.append(path.name)
    assert len(failed) >= 7 and KB1515.name not in failed, failed


def test_the_kb1515_check_fails_under_the_old_rule(the_old_rule: pytest.MonkeyPatch) -> None:
    with pytest.raises(AssertionError):
        _check_kb1515()


def test_the_shapes_fail_under_the_old_rule(the_old_rule: pytest.MonkeyPatch) -> None:
    failed = set()
    for label in SHAPES:
        try:
            _check_shape(label)
        except AssertionError:
            failed.add(label)
    assert failed == _THE_OLD_RULE_READS_OTHERWISE


def test_the_oobm_check_fails_with_no_oobm_stanza(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aoss_parse, "_OOBM_HEADER_RE", _NEVER)
    with pytest.raises(AssertionError):
        _check_oobm()


def test_the_oobm_check_fails_when_its_words_end_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """``interface enable`` looks like a header; the words of the
    context must not end it."""
    monkeypatch.setattr(aoss_parse, "_OOBM_WORDS_RE", _NEVER)
    with pytest.raises(AssertionError):
        _check_oobm()


def test_the_port_line_checks_fail_when_the_lines_are_not_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aoss_parse, "_PORT_VLAN_LINE_RE", _NEVER)
    monkeypatch.setattr(aoss_parse, "_GLOBAL_PORT_VLAN_RE", _NEVER)
    failed = set()
    for label in EQUIVALENT:
        try:
            _check_equivalent(label)
        except AssertionError:
            failed.add(label)
    # Where the VLAN's line comes later it wins anyway: the next test
    # is that case's.
    assert failed == set(EQUIVALENT) - {_VLANS_LATER}
    with pytest.raises(AssertionError):
        _check_round_trip()
    with pytest.raises(AssertionError):
        _check_undeclared()


def test_the_order_check_fails_when_a_ports_line_is_applied_last(monkeypatch: pytest.MonkeyPatch) -> None:
    """A port's lines applied once the whole config has been read, and
    not where they stand: the port's line then wins over a later
    VLAN's line."""
    held: list[tuple] = []
    apply, finish = aoss_parse._Memberships.port_line, aoss_parse._Memberships.finish

    def hold(self, *args, **kwargs) -> None:
        held.append((self, args, kwargs))

    def apply_last(self) -> None:
        for owner, args, kwargs in held:
            if owner is self:
                apply(self, *args, **kwargs)
        finish(self)

    monkeypatch.setattr(aoss_parse._Memberships, "port_line", hold)
    monkeypatch.setattr(aoss_parse._Memberships, "finish", apply_last)
    with pytest.raises(AssertionError):
        _check_equivalent(_VLANS_LATER)


def test_the_trap_check_fails_when_a_move_takes_every_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bookkeeping that took a moved port out of every entry of the
    list it left, a later one included: the port ended in no VLAN."""
    monkeypatch.setattr(
        aoss_parse, "_cut", lambda cuts, vlan, port, at: cuts.setdefault(id(vlan), (vlan, {}))[1].__setitem__(
            port, 10**9),
    )
    with pytest.raises(AssertionError):
        _check_equivalent(_TRAP)


def test_the_forbid_check_fails_when_forbid_is_read_as_a_membership(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aoss_parse, "_PORT_VLAN_LINE_RE", re.compile(
        r"^(no[ \t]+)?(tagged|untagged|forbid)[ \t]+vlan[ \t]+(\S+)[ \t]*$", re.IGNORECASE))
    with pytest.raises(AssertionError):
        _check_forbid()


def test_the_rows_check_fails_when_the_rows_are_not_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aoss_parse, "_ROWS_SHOWN", 10**6)
    with pytest.raises(AssertionError):
        test_the_rows_are_bounded()


def test_the_undeclared_check_fails_when_nothing_is_said(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aoss_parse._Memberships, "_say", lambda self, line, absent: None)
    with pytest.raises(AssertionError):
        _check_undeclared()


def test_the_detection_check_fails_under_the_old_body(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deployment_detect, "_stanza_body", _old_stanza_body)
    with pytest.raises(AssertionError):
        _check_detection()


def test_the_detection_check_fails_when_a_member_line_needs_its_indent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deployment_detect, "_MEMBER_TYPE_RE", re.compile(
        r'^[ \t]+member[ \t]+(?P<id>[0-9]{1,6})[ \t]+type[ \t]+"?(?P<part>[A-Za-z0-9]{1,32})"?(?=[ \t]|$)'))
    with pytest.raises(AssertionError):
        _check_detection()


def test_the_one_predicate_check_fails_for_a_handler_it_does_not_ask() -> None:
    source = inspect.getsource(aoss_parse.parse_intent) + "\n    _EXTRA_RE.match(stripped_line)\n"
    with pytest.raises(AssertionError):
        _check_one_predicate(source)



def _as_built_oobm(lines: list[str], start: int) -> int:
    """The ``oobm`` stanza as it was first built: ended by its ``exit``
    or by a line that opens a context, never by another line of the
    top."""
    depth, i = 0, start
    while i < len(lines):
        line, stripped = lines[i], lines[i].strip()
        if stripped == "exit":
            i += 1
            if not depth:
                break
            depth -= 1
            continue
        if stripped and not line[0].isspace() and not aoss_parse._OOBM_WORDS_RE.match(stripped) and (
            re.match(r"^(?:vlan[ \t]+\d+|interface[ \t]+\S+|oobm)[ \t]*$", stripped)
            or aoss_parse._OPENS_A_CONTEXT_RE.match(stripped)
        ):
            break
        if aoss_parse._MEMBER_BLOCK_RE.match(stripped):
            depth += 1
        i += 1
    return i


def test_the_oobm_end_check_fails_when_only_a_context_ends_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """An ``oobm`` with no ``exit`` then took the switch's ``hostname``
    for one of its own lines."""
    monkeypatch.setattr(aoss_parse, "_past_the_oobm_stanza", _as_built_oobm)
    with pytest.raises(AssertionError):
        _check_oobm_with_no_exit()


def test_the_oobm_end_check_fails_when_its_words_end_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """With every line of the top ending it, the management port's
    gateway became the switch's default route."""
    monkeypatch.setattr(aoss_parse, "_OOBM_WORDS_RE", _NEVER)
    with pytest.raises(AssertionError):
        _check_oobm_with_no_exit()


class _Without:
    """:data:`~parse._OPENS_A_CONTEXT_RE` without the context whose
    header begins with *word*."""

    def __init__(self, word: str) -> None:
        self.word, self.real = word, aoss_parse._OPENS_A_CONTEXT_RE

    def match(self, text: str) -> re.Match[str] | None:
        return None if text.split(None, 1)[:1] == [self.word] else self.real.match(text)


@pytest.mark.parametrize("word", list(OPENERS))
def test_the_opener_check_fails_without_that_context(word: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aoss_parse, "_OPENS_A_CONTEXT_RE", _Without(word))
    with pytest.raises(AssertionError):
        _check_opener(word)


def test_the_vrrp_check_fails_when_the_group_reader_does_not_ask_the_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A group with no ``exit`` then read the next VLAN's header and
    lines as its own, and the next VLAN was gone."""
    real = aoss_parse._parse_vrrp_group_stanza

    def not_asking(lines: list[str], start: int, gid: int):
        with monkeypatch.context() as inner:
            inner.setattr(aoss_parse, "_ends_the_stanza", lambda line, stripped: False)
            return real(lines, start, gid)

    monkeypatch.setattr(aoss_parse, "_parse_vrrp_group_stanza", not_asking)
    with pytest.raises(AssertionError):
        _check_shape(_VRRP_WITH_NO_EXIT)


@pytest.mark.parametrize("label", sorted(_LEAVING))
def test_the_leaving_checks_fail_when_only_a_lower_case_exit_leaves(
    label: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(aoss_parse, "_leaves", lambda stripped: stripped if stripped == "exit" else "")
    with pytest.raises(AssertionError):
        _check_shape(label)


def test_the_several_ports_check_fails_when_a_list_opens_no_stanza(monkeypatch: pytest.MonkeyPatch) -> None:
    """``interface 1,3`` then entered no stanza the parser read: its
    VLAN line was dropped, and nothing said so."""
    monkeypatch.setattr(aoss_parse, "_PORT_LIST_HEADER_RE", _NEVER)
    with pytest.raises(AssertionError):
        _check_several()


def test_the_several_ports_check_fails_when_nothing_is_said(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aoss_parse._Memberships, "say", lambda self, row: None)
    with pytest.raises(AssertionError):
        _check_several()


def test_the_row_text_check_fails_when_a_row_quotes_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aoss_parse, "_IDS_SHOWN", 10**6)
    monkeypatch.setattr(aoss_parse, "_LINE_SHOWN", 10**6)
    with pytest.raises(AssertionError):
        _check_row_text()


def test_the_stacking_check_fails_when_a_module_line_of_the_top_is_the_stanzas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(deployment_detect, "_read_at_the_top", lambda line: False)
    with pytest.raises(AssertionError):
        _check_stack_with_no_exit()


def test_the_render_check_fails_on_a_render_with_every_body_line_indented() -> None:
    """What the render script writes now: the five lines indented."""
    text = RENDERED.read_text(encoding="utf-8")
    indented = re.sub(r"^(no power-over-ethernet|ip address )", r"   \1", text, flags=re.M)
    assert indented != text
    with pytest.raises(AssertionError):
        _check_rendered(indented)

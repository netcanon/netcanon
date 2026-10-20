"""AOS-CX, IOS-XE CLI, NX-OS and OS10: a text without its indentation is
refused in words.

Each of these four parsers reads a stanza's lines by their indentation.
Read without it, a stanza's body was lines of the top level: every
committed capture of the four, with each line's leading white space
removed, lost every interface address it has, and with them
descriptions, VLAN names and memberships, LAG members and VNIs (AOS-CX
read every interface as shut), in jobs that said nothing of it; and an
IOSv capture published with every line at column 0 was read so as it
stood.  What each platform's own CLI makes of such a text is not
established here.  A reading by the mode each command leaves open, as
the CLIs are typed into, would need every mode's words, which no vendor
page lists.  So such a text is refused, with the parser's reason, as the
EOS parser refuses one (``test_arista_eos_indentation.py``, which also
holds the shared helper's own shapes: a comment, a bare ``!``, ``exit``
and ``end``).

Tested here, for each of the four:

(a) A text with NO indentation, a stanza's body at the left margin, is
    refused with a sentence that gives the parser's reason, names a
    line, and quotes nothing of the text; the job says ``parse
    failed``; detection keeps the parser's codec first.  A text with
    SOME lines dedented is read by its indentation, and a banner's
    lines are no indentation.
(b) Any white space in front of a line is indentation, a no-break space
    among them, as these readers take it: a capture so indented reads
    as printed.  (The EOS and IOS XR readers take such a line for one at
    the margin, and refuse such a text.)
(c) No committed capture of any codec, as committed, is refused but
    those pinned.  The IOSv capture is kept under ``refused/``, out of
    the walks that read every capture to a tree, and is refused at its
    first interface.
(d) Each check is handed the defect it is for, and has to fail (the last
    section).

The readings of the text here (which lines open a stanza, where a body
is) are typed by hand, never asked of the parser.
"""

from __future__ import annotations

import inspect
import re
import textwrap
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

from netcanon.migration.codecs import _scanner
from netcanon.migration.codecs.aruba_aoscx import parse as aoscx_parse
from netcanon.migration.codecs.base import ParseError
from netcanon.migration.codecs.cisco_iosxe_cli import parse as ios_parse
from netcanon.migration.codecs.cisco_nxos import parse as nxos_parse
from netcanon.migration.codecs.dell_os10 import parse as os10_parse
from netcanon.migration.codecs.registry import get_codec
from netcanon.services.migration_detect import detect_codec
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
MODULES: dict[str, ModuleType] = {
    "aruba_aoscx": aoscx_parse,
    "cisco_iosxe_cli": ios_parse,
    "cisco_nxos": nxos_parse,
    "dell_os10": os10_parse,
}
#: Where each codec's committed captures are.
_DIRS = {
    "aruba_aoscx": ("real/aruba_aoscx", "synthetic/aruba_aoscx"),
    "cisco_iosxe_cli": ("real/cisco_iosxe", "synthetic/cisco_iosxe_cli", "iosxe"),
    "cisco_nxos": ("real/cisco_nxos", "synthetic/cisco_nxos"),
    "dell_os10": ("real/dell_os10", "synthetic/dell_os10"),
}
_NOT_A_CAPTURE = {".md", ".json", ".yaml", ".yml", ".py", ".pyc", ".xml"}
CAPTURES = [
    (codec, path)
    for codec, dirs in _DIRS.items()
    for name in dirs
    for path in sorted((FIXTURES / name).iterdir())
    if path.is_file() and path.suffix.lower() not in _NOT_A_CAPTURE
]
IDS = [f"{codec}:{path.name}" for codec, path in CAPTURES]
KITCHEN_SINKS = {codec: next(p for c, p in CAPTURES if c == codec and p.stem == "kitchen_sink") for codec in MODULES}
#: The IOSv capture published with every line at column 0
#: (``tests/fixtures/real/NOTICE.md`` has its provenance).
IOSV = FIXTURES / "refused" / "cisco_iosxe" / "cml_basic_forwarding_iosv_r1_ospf.txt"
#: A name of an interface on each platform, for the small texts.
PORT = {
    "aruba_aoscx": "1/1/1",
    "cisco_iosxe_cli": "GigabitEthernet1",
    "cisco_nxos": "Ethernet1/1",
    "dell_os10": "ethernet1/1/1",
}


def _parse(codec: str, text: str):
    return get_codec(codec).parse(text)


def _tree(codec: str, text: str) -> dict:
    return _parse(codec, text).model_dump()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _dedent(text: str) -> str:
    """*text* with every line's leading white space removed."""
    return "\n".join(line.lstrip() for line in text.splitlines()) + "\n"


def _without_bangs(text: str) -> tuple[str, dict[int, int]]:
    """*text* dedented and with every bare ``!`` line removed, and the
    line each line of it was in *text* (line numbers from 1)."""
    kept, where = [], {}
    for number, line in enumerate(text.splitlines(), 1):
        if line.strip() == "!":
            continue
        kept.append(line.lstrip())
        where[len(kept)] = number
    return "\n".join(kept) + "\n", where


def _with_no_break_spaces(text: str) -> str:
    """*text* with every space in front of a line a no-break space."""
    return "\n".join(
        "\u00a0" * (len(line) - len(line.lstrip(" "))) + line.lstrip(" ") for line in text.splitlines()
    ) + "\n"


def test_the_captures_are_found() -> None:
    for codec in MODULES:
        assert sum(1 for c, _ in CAPTURES if c == codec) >= 5, codec
    assert IOSV.is_file() and IOSV not in {path for _, path in CAPTURES}


# ---------------------------------------------------------------------------
# (a) A text with no indentation is refused in words
# ---------------------------------------------------------------------------


def _is_vlan_list(word: str) -> bool:
    return bool(re.fullmatch(r"[0-9][0-9,-]*", word))


#: Whether a line's words (in lower case) open a stanza the parser reads
#: by its indentation, typed by hand.  AOS-CX: ``interface``, ``vlan
#: <id>``, ``vrf <name>``.  IOS-XE: ``interface``, ``vlan <id>...``,
#: ``vlan configuration <id>``, ``vrf definition`` / ``ip vrf <name>``,
#: ``ip dhcp pool``, ``radius server``.  NX-OS: ``interface``, ``vlan
#: <ids>``, ``vrf context <name>``.  OS10: ``interface <name>[ <n>]``,
#: but for ``breakout`` and ``range``.
_OPENS: dict[str, Callable[[list[str]], bool]] = {
    "aruba_aoscx": lambda w: (
        (w[0] == "interface" and len(w) >= 2)
        or (w[0] == "vlan" and len(w) == 2 and w[1].isdigit())
        or (w[0] == "vrf" and len(w) == 2)
    ),
    "cisco_iosxe_cli": lambda w: (
        (w[0] == "interface" and len(w) >= 2)
        or (w[0] == "vlan" and len(w) >= 2 and w[1][:1].isdigit())
        or (w[:2] == ["vlan", "configuration"] and len(w) == 3 and w[2].isdigit())
        or (w[:2] in (["vrf", "definition"], ["ip", "vrf"]) and len(w) == 3)
        or (w[:3] == ["ip", "dhcp", "pool"] and len(w) >= 4)
        or (w[:2] == ["radius", "server"] and len(w) >= 3)
    ),
    "cisco_nxos": lambda w: (
        (w[0] == "interface" and len(w) >= 2)
        or (w[0] == "vlan" and len(w) == 2 and _is_vlan_list(w[1]))
        or (w[:2] == ["vrf", "context"] and len(w) == 3)
    ),
    "dell_os10": lambda w: (
        w[0] == "interface" and len(w) in (2, 3) and w[1] not in ("breakout", "range")
        and (len(w) == 2 or w[2].isdigit())
    ),
}


def _is_header(codec: str, line: str) -> bool:
    words = line.lower().split()
    return bool(words) and _OPENS[codec](words)


def _is_comment(line: str) -> bool:
    return line.strip().startswith("!") and line.strip() != "!"


def _is_no_body_line(codec: str, line: str) -> bool:
    """A bare ``!``, ``exit``, ``end``, or a line that opens a stanza."""
    return line.strip().lower() in ("!", "exit", "end") or _is_header(codec, line)


def _first_flat_by_hand(codec: str, flat: str) -> int | None:
    """In a text with no indentation: the first line that opens a stanza
    and has after it (blank lines and comments passed over) a line that
    is no header, no ``!``, no ``exit`` and no ``end`` -- a line the
    text cannot tell from a line of the stanza's body, whether the
    printed config had it indented under the stanza or not (an empty
    ``vrf keepalive`` printed before a line of the top level is one:
    once dedented, nothing says that line is not the VRF's).  ``None``:
    no such line."""
    lines = flat.splitlines()
    for number, line in enumerate(lines, 1):
        if not _is_header(codec, line):
            continue
        after = next((nxt for nxt in lines[number:] if nxt.strip() and not _is_comment(nxt)), "")
        if after and not _is_no_body_line(codec, after):
            return number
    return None


def _refusal(codec: str, text: str) -> ParseError:
    with pytest.raises(ParseError) as caught:
        _parse(codec, text)
    return caught.value


def _message(codec: str, line: int) -> str:
    return MODULES[codec].FLAT_TEXT_MESSAGE.format(line=line)


#: Committed captures in which, dedented, no stanza the parser reads is
#: followed by a line that could be its body: they are the same text to
#: the parser.  Found by hand (:func:`_first_flat_by_hand`), and pinned,
#: so that a reading that finds no stanza anywhere is seen.
NO_BODY = {
    "cisco_iosxe_cli:batfish_cisco_aaa.txt",
    "cisco_iosxe_cli:batfish_cisco_ip_route.txt",
    "cisco_iosxe_cli:batfish_cisco_logging.txt",
    "cisco_iosxe_cli:batfish_cisco_snmp.txt",
}


def _first_flat_dedented(codec: str, path: Path) -> int | None:
    return _first_flat_by_hand(codec, _dedent(_read(path)))


def _check_flat(codec: str, path: Path) -> None:
    raw = _read(path)
    at = _first_flat_dedented(codec, path)
    if at is None:
        assert f"{codec}:{path.name}" in NO_BODY, path.name
        assert _tree(codec, _dedent(raw)) == _tree(codec, raw), path.name
        return
    error = _refusal(codec, _dedent(raw))
    assert str(error) == _message(codec, at), path.name
    assert error.path == f"line {at}", path.name


@pytest.mark.parametrize(("codec", "path"), CAPTURES, ids=IDS)
def test_a_capture_without_its_indentation_is_refused(codec: str, path: Path) -> None:
    """Every committed capture with every line's leading white space
    removed is refused with the sentence, at the first stanza with a
    line after it that could be its body; one with no such stanza is
    read as it was."""
    _check_flat(codec, path)


def test_the_captures_with_no_body_are_the_pinned_ones() -> None:
    found = {f"{c}:{p.name}" for c, p in CAPTURES if _first_flat_dedented(c, p) is None}
    assert found == NO_BODY


def _a_bang_ends_a_banner(text: str) -> bool:
    """Whether a banner of *text* is delimited by ``!`` (AOS-CX prints
    ``banner motd !``): with every bare ``!`` line gone, such a banner has
    lost its end, and is refused as one that runs to the end of the
    text."""
    return any(re.fullmatch(r"banner\s+\S+\s+!", line.strip()) for line in text.splitlines())


def _check_flat_without_bangs(codec: str, path: Path) -> None:
    raw = _read(path)
    if _first_flat_dedented(codec, path) is None or _a_bang_ends_a_banner(raw):
        return
    text, where = _without_bangs(raw)
    error = _refusal(codec, text)
    named = int(error.path.split()[-1])
    assert str(error) == _message(codec, named), path.name
    # The line it names opens a stanza, at or before the one it names
    # with them: a `!` is no body line, so with the `!` lines gone, a text
    # cannot tell an empty stanza from one whose body is at the margin.
    assert _is_header(codec, raw.splitlines()[where[named] - 1])
    assert where[named] <= _first_flat_dedented(codec, path), path.name


@pytest.mark.parametrize(("codec", "path"), CAPTURES, ids=IDS)
def test_a_capture_without_its_indentation_or_its_bangs_is_refused(codec: str, path: Path) -> None:
    _check_flat_without_bangs(codec, path)


_WORD = re.compile(r"[^\s`'\"()]+")


def _quotes_nothing(error: ParseError, sentence: str) -> None:
    number = error.path.split()[-1]
    fixed = set(_WORD.findall(sentence.replace("{line}", "")))
    assert set(_WORD.findall(str(error))) - fixed == {number}
    assert error.snippet == ""


def _check_quotes_nothing(codec: str, path: Path) -> None:
    raw = _read(path)
    if _first_flat_dedented(codec, path) is None:
        return
    _quotes_nothing(_refusal(codec, _dedent(raw)), MODULES[codec].FLAT_TEXT_MESSAGE)


@pytest.mark.parametrize(("codec", "path"), CAPTURES, ids=IDS)
def test_the_sentence_quotes_nothing_of_the_text(codec: str, path: Path) -> None:
    """What a parse failure says is logged; the sentence holds its own
    words and a line number, and nothing else."""
    _check_quotes_nothing(codec, path)


#: What the sentence of each codec names: the command that prints the
#: config, and what prints it.
_PRINTED_BY = {
    "aruba_aoscx": ("`show running-config`", "the switch"),
    "cisco_iosxe_cli": ("`show running-config`", "the device"),
    "cisco_nxos": ("`show running-config`", "the switch"),
    "dell_os10": ("`show running-configuration`", "the switch"),
}


def _check_the_reason(codec: str) -> None:
    sentence = MODULES[codec].FLAT_TEXT_MESSAGE
    assert sentence.startswith(f"{codec}: ")
    assert "this parser tells which lines belong to a stanza by their indentation" in sentence
    command, device = _PRINTED_BY[codec]
    assert f"Paste the output of {command} as {device} prints it" in sentence
    lowered = sentence.lower()
    for claim in ("reads", "places", "misplace", "would load", "would run"):
        assert claim not in lowered, (codec, claim)


@pytest.mark.parametrize("codec", list(MODULES))
def test_the_sentence_gives_the_parsers_reason_not_the_devices(codec: str) -> None:
    """No vendor page says what the device does with a text that lost
    its indentation; the sentence says what the parser cannot do."""
    _check_the_reason(codec)


def _check_jobs(codec: str, path: Path) -> None:
    raw = _read(path)
    at = _first_flat_dedented(codec, path)
    if at is None:
        return
    said = "parse failed: " + _message(codec, at)
    for target in (codec, "juniper_junos"):
        job = run_plan_with_checked_names(get_codec(codec), get_codec(target), _dedent(raw), port_rename_map={})
        assert (job.status.value, job.error) == ("failed", said), (path.name, target)


@pytest.mark.parametrize("codec", list(MODULES))
def test_the_job_says_parse_failed_with_the_sentence(codec: str) -> None:
    _check_jobs(codec, KITCHEN_SINKS[codec])


def _check_detection(codec: str, path: Path) -> None:
    raw = _read(path)
    for text in (_dedent(raw), _without_bangs(raw)[0]):
        ranked = detect_codec(text, min_confidence=40)
        assert ranked and ranked[0].codec == codec, path.name


@pytest.mark.parametrize(("codec", "path"), CAPTURES, ids=IDS)
def test_detection_keeps_the_codec_first(codec: str, path: Path) -> None:
    """The migrate page offers another vendor for a ``parse failed`` job
    only where detection's first codec is not the source: a flat text of
    each of the four is detected as its own codec, so the sentence stands
    alone."""
    _check_detection(codec, path)


def _partly_dedented(codec: str) -> tuple[str, str]:
    """The kitchen sink with the body of its first interface in column 0
    that has an address dedented, and that interface's name (found by
    hand)."""
    lines = _read(KITCHEN_SINKS[codec]).splitlines()

    def _end(start: int) -> int:
        return next((j for j in range(start + 1, len(lines)) if lines[j][:1] and not lines[j][0].isspace()), len(lines))

    start = next(
        i for i, line in enumerate(lines)
        if line.lower().startswith("interface ")
        and any(nxt.strip().startswith("ip address ") for nxt in lines[i + 1:_end(i)])
    )
    end = _end(start)
    lines[start + 1:end] = [line.lstrip() for line in lines[start + 1:end]]
    return "\n".join(lines) + "\n", lines[start]


def _addresses(codec: str, text: str) -> dict[str, int]:
    return {i.name: len(i.ipv4_addresses) for i in _parse(codec, text).interfaces}


def _check_partly_dedented(codec: str) -> None:
    text, header = _partly_dedented(codec)
    read = _addresses(codec, text)
    printed = _addresses(codec, _read(KITCHEN_SINKS[codec]))
    # The dedented lines are lines of the top level, as this parser reads
    # them: the interface has no address, and every other interface is as
    # printed.
    lost = {name for name in printed if printed[name] and not read.get(name)}
    assert len(lost) == 1, (codec, header, lost)
    assert {n: c for n, c in read.items() if n not in lost} == {n: c for n, c in printed.items() if n not in lost}


@pytest.mark.parametrize("codec", list(MODULES))
def test_a_text_with_some_lines_dedented_is_read_by_its_indentation(codec: str) -> None:
    _check_partly_dedented(codec)


def _check_no_body(codec: str) -> None:
    text = "".join(f"interface {PORT[codec][:-1]}{n}\n!\n" for n in range(1, 40))
    _parse(codec, text)


@pytest.mark.parametrize("codec", list(MODULES))
def test_interfaces_with_no_body_are_not_refused(codec: str) -> None:
    """``interface <name>`` / ``!`` lines with nothing in them have no
    body to stand at the margin."""
    _check_no_body(codec)


#: For each kind of stanza each parser reads, typed by hand: its header,
#: then a line of its body at the left margin.  The name of the parser's
#: pattern for the header beside it.
FLAT_PAIRS: dict[str, dict[str, tuple[str, str]]] = {
    "aruba_aoscx": {
        "interface": ("_IFACE_RE", "interface 1/1/1\ndescription uplink\n"),
        "interface lag": ("_IFACE_RE", "interface lag 1\nno shutdown\n"),
        "vlan": ("_VLAN_TOP_RE", "vlan 10\nname users\n"),
        "vrf": ("_VRF_DECL_RE", "vrf RED\nrd 65000:1\n"),
    },
    "cisco_iosxe_cli": {
        "interface": ("_IFACE_RE", "interface GigabitEthernet1\ndescription uplink\n"),
        "interface range": ("_IFACE_RE", "interface range GigabitEthernet1/0/1 - 2\nswitchport mode access\n"),
        "vlan": ("_VLAN_RE", "vlan 10\nname users\n"),
        "vlan configuration": ("_VLAN_CONFIG_RE", "vlan configuration 10\nmember evpn-instance 10 vni 10010\n"),
        "vrf definition": ("_VRF_DEFINITION_RE", "vrf definition RED\nrd 65000:1\n"),
        "ip vrf": ("_VRF_DEFINITION_RE", "ip vrf RED\nrd 65000:1\n"),
        "ip dhcp pool": ("_DHCP_POOL_HEADER_RE", "ip dhcp pool USERS\nnetwork 192.0.2.0 255.255.255.0\n"),
        "radius server": ("_RADIUS_SERVER_HEADER_RE", "radius server RAD1\naddress ipv4 192.0.2.10\n"),
    },
    "cisco_nxos": {
        "interface": ("_IFACE_RE", "interface Ethernet1/1\ndescription uplink\n"),
        "vlan": ("_VLAN_TOP_RE", "vlan 10\nname users\n"),
        "vrf context": ("_VRF_CONTEXT_RE", "vrf context RED\nrd 65000:1\n"),
    },
    "dell_os10": {
        "interface": ("_IFACE_RE", "interface ethernet1/1/1\ndescription uplink\n"),
        "interface vlan": ("_IFACE_RE", "interface vlan10\nip address 192.0.2.1/24\n"),
        "interface port-channel": ("_IFACE_RE", "interface port-channel 10\ndescription lag\n"),
    },
}
PAIRS = [(codec, kind) for codec, kinds in FLAT_PAIRS.items() for kind in kinds]


def _check_flat_pair(codec: str, kind: str) -> None:
    text = FLAT_PAIRS[codec][kind][1]
    assert _first_flat_by_hand(codec, text) == 1, (codec, kind)
    assert str(_refusal(codec, text)) == _message(codec, 1), (codec, kind)


@pytest.mark.parametrize(("codec", "kind"), PAIRS)
def test_each_kind_of_stanza_with_its_body_at_the_margin_is_refused(codec: str, kind: str) -> None:
    _check_flat_pair(codec, kind)


def _shapes(codec: str) -> dict[str, tuple[str, int | None]]:
    """Small texts, typed by hand, and the line the refusal names (None:
    the text is read).  Any white space in front of a line is
    indentation to these readers."""
    port = PORT[codec]
    return {
        "a comment between a header and its body": (f"interface {port}\n!! the uplink\ndescription uplink\n", 1),
        "a header, then its !": (f"interface {port}\n!\nhostname sw1\n", None),
        "a body indented with no-break spaces": (
            f"hostname sw1\n!\ninterface {port}\n\u00a0description up\n\u00a0shutdown\n!\n", None,
        ),
        "a body indented with an ideographic space": (
            f"hostname sw1\n!\ninterface {port}\n\u3000description up\n!\n", None,
        ),
        "a body indented with a tab": (f"hostname sw1\n!\ninterface {port}\n\tdescription up\n!\n", None),
    }


SHAPES = [(codec, name) for codec in MODULES for name in _shapes(codec)]


def _check_shape(codec: str, name: str) -> None:
    text, at = _shapes(codec)[name]
    if at is None:
        _parse(codec, text)
    else:
        assert str(_refusal(codec, text)) == _message(codec, at), (codec, name)


@pytest.mark.parametrize(("codec", "name"), SHAPES)
def test_a_comment_a_bang_and_white_space_in_a_flat_text(codec: str, name: str) -> None:
    _check_shape(codec, name)


#: A text whose only indented lines are a banner's, in each platform's
#: grammar, and the line its first stanza is on: a banner's lines are
#: emptied before the check, so they are no indentation.
FLAT_BUT_A_BANNER = {
    "aruba_aoscx": ("banner motd !\n   Authorised use only\n!\ninterface 1/1/1\ndescription uplink\n", 4),
    "cisco_iosxe_cli": (
        "banner motd ^C\n   Authorised use only\n^C\ninterface GigabitEthernet1\ndescription uplink\n", 4,
    ),
    "cisco_nxos": ("banner motd #\n   Authorised use only\n#\ninterface Ethernet1/1\ndescription uplink\n", 4),
    "dell_os10": ("banner motd ^\n   Authorised use only\n^\ninterface ethernet1/1/1\ndescription uplink\n", 4),
}


def _check_banner(codec: str) -> None:
    text, at = FLAT_BUT_A_BANNER[codec]
    assert str(_refusal(codec, text)) == _message(codec, at), codec


@pytest.mark.parametrize("codec", list(MODULES))
def test_a_banners_lines_are_no_indentation(codec: str) -> None:
    _check_banner(codec)


# ---------------------------------------------------------------------------
# (b) Any white space in front of a line is indentation
# ---------------------------------------------------------------------------


def _check_no_break_spaces(codec: str, path: Path) -> None:
    raw = _read(path)
    assert _tree(codec, _with_no_break_spaces(raw)) == _tree(codec, raw), path.name


@pytest.mark.parametrize(("codec", "path"), CAPTURES, ids=IDS)
def test_a_capture_indented_with_no_break_spaces_reads_as_printed(codec: str, path: Path) -> None:
    """These readers take a no-break space in front of a line (a paste
    out of a web page) for indentation, and read such a capture as it
    was printed: refusing it would refuse a text they read whole."""
    _check_no_break_spaces(codec, path)


# ---------------------------------------------------------------------------
# (c) The committed captures, as committed
# ---------------------------------------------------------------------------

#: Committed texts that ARE the flat shape, as committed, through each
#: parser's checks.  The AOS-S KB.15.15 capture, every line at column 0
#: (the AOS-S parser reads it: an AOS-S stanza ends at its `exit`), is no
#: text of these platforms; its `vlan` stanzas are no stanza OS10 reads.
#: The IOSv capture is IOS-XE CLI's own, and is refused by it.
FLAT_AS_COMMITTED = {
    "aruba_aoscx": {
        "real/aruba_aoss/hpe_community_5406rzl2_kb1515.cfg",
        "refused/cisco_iosxe/cml_basic_forwarding_iosv_r1_ospf.txt",
    },
    "cisco_iosxe_cli": {
        "real/aruba_aoss/hpe_community_5406rzl2_kb1515.cfg",
        "refused/cisco_iosxe/cml_basic_forwarding_iosv_r1_ospf.txt",
    },
    "cisco_nxos": {
        "real/aruba_aoss/hpe_community_5406rzl2_kb1515.cfg",
        "refused/cisco_iosxe/cml_basic_forwarding_iosv_r1_ospf.txt",
    },
    "dell_os10": {"refused/cisco_iosxe/cml_basic_forwarding_iosv_r1_ospf.txt"},
}
_WALKED_NOT_A_CAPTURE = {".md", ".json", ".yaml", ".yml", ".py", ".pyc"}
#: The directories under ``tests/fixtures/`` that hold no capture.
_NOT_CAPTURES = {"cross_vendor_expectations", "model_families", "target_profiles", "__pycache__"}


def _every_committed_capture() -> list[Path]:
    return sorted(
        p for p in FIXTURES.rglob("*")
        if p.is_file() and p.suffix.lower() not in _WALKED_NOT_A_CAPTURE
        and not _NOT_CAPTURES & set(p.relative_to(FIXTURES).parts)
    )


def _the_checks(codec: str, raw: str) -> None:
    """What ``parse_intent`` asks of a text before any reader runs, the
    flat check given the text the banner pass leaves.  A text the banner
    pass refuses (another platform's banner) is given whole: that
    refusal is not this check's."""
    module = MODULES[codec]
    try:
        text = module.without_banner_bodies(raw)
    except ParseError:
        text = raw
    module._refuse_a_flat_text(text)


def _check_the_walk(walk: Callable[[], list[Path]]) -> None:
    walked = {p.relative_to(FIXTURES).as_posix() for p in walk()}
    assert {path for _, path in CAPTURES} <= set(walk())
    assert walked >= set().union(*FLAT_AS_COMMITTED.values())
    assert {name.split("/")[0] for name in walked} >= {"real", "synthetic", "refused", "iosxe", "opnsense"}


def _check_every_capture_as_committed(codec: str) -> None:
    refused = set()
    for path in _every_committed_capture():
        try:
            _the_checks(codec, _read(path))
        except ParseError:
            refused.add(path.relative_to(FIXTURES).as_posix())
    assert refused == FLAT_AS_COMMITTED[codec], codec


@pytest.mark.parametrize("codec", list(MODULES))
def test_no_committed_capture_of_any_codec_is_refused_as_committed(codec: str) -> None:
    """No committed capture of any codec, as committed, is refused by the
    parser's flat check, but those pinned with their reason."""
    _check_the_walk(_every_committed_capture)
    _check_every_capture_as_committed(codec)


def _check_iosv() -> None:
    raw = _read(IOSV)
    assert not any(line[:1].isspace() for line in raw.splitlines())
    at = _first_flat_by_hand("cisco_iosxe_cli", raw)
    assert raw.splitlines()[at - 1] == "interface GigabitEthernet0/0"
    error = _refusal("cisco_iosxe_cli", raw)
    assert (str(error), error.path) == (_message("cisco_iosxe_cli", at), f"line {at}")


def test_the_iosv_capture_is_refused_at_its_first_interface() -> None:
    """Published with every line at column 0, and its three banners
    printed between ``^C``: the banner pass reads them first, and the
    flat check names the first interface, whose lines it had read as
    lines of the top level (no address, no ``shutdown``, no dot1Q tag)."""
    _check_iosv()


# ---------------------------------------------------------------------------
# (d) Each check, handed the defect it is for, fails
# ---------------------------------------------------------------------------


def _with_a_defect(module: ModuleType, name: str, old: str, new: str) -> Callable:
    """*module*'s function *name* with *old*, one fragment of its source,
    written as *new*: a defect put back, in this process only.  A
    fragment that is no longer in the source fails here, not in
    silence."""
    source = textwrap.dedent(inspect.getsource(getattr(module, name)))
    assert source.count(old) == 1, old
    space = dict(vars(module))
    exec(compile(source.replace(old, new), "<a defect put back>", "exec"), space)
    return space[name]


_FAILS = (AssertionError, pytest.fail.Exception)


@pytest.mark.parametrize("codec", list(MODULES))
def test_the_refusal_checks_fail_with_no_refusal(codec: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(MODULES[codec], "_refuse_a_flat_text", lambda raw: None)
    sink = KITCHEN_SINKS[codec]
    for check in (_check_flat, _check_flat_without_bangs, _check_jobs):
        with pytest.raises(_FAILS):
            check(codec, sink)
    for check in (_check_banner, _check_shape_comment):
        with pytest.raises(_FAILS):
            check(codec)
    with pytest.raises(_FAILS):
        _check_every_capture_as_committed(codec)
    if codec == "cisco_iosxe_cli":
        with pytest.raises(_FAILS):
            _check_iosv()


def _check_shape_comment(codec: str) -> None:
    _check_shape(codec, "a comment between a header and its body")


@pytest.mark.parametrize("codec", list(MODULES))
def test_the_flat_check_fails_with_no_headers(codec: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(MODULES[codec], "_STANZA_HEADERS", ())
    with pytest.raises(_FAILS):
        _check_flat(codec, KITCHEN_SINKS[codec])


@pytest.mark.parametrize(("codec", "kind"), PAIRS)
def test_each_kinds_check_fails_without_its_header(codec: str, kind: str, monkeypatch: pytest.MonkeyPatch) -> None:
    module = MODULES[codec]
    pattern = getattr(module, FLAT_PAIRS[codec][kind][0])
    assert pattern in module._STANZA_HEADERS
    monkeypatch.setattr(module, "_STANZA_HEADERS", tuple(h for h in module._STANZA_HEADERS if h is not pattern))
    with pytest.raises(_FAILS):
        _check_flat_pair(codec, kind)


@pytest.mark.parametrize("codec", list(MODULES))
def test_the_partial_and_corpus_checks_fail_when_indentation_is_not_asked(
    codec: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refusal that judged every text as though it had no indentation
    would refuse a printed one."""
    module = MODULES[codec]
    real = module._refuse_a_flat_text
    monkeypatch.setattr(module, "_refuse_a_flat_text", lambda raw: real(_dedent(raw)))
    with pytest.raises((AssertionError, ParseError)):
        _check_partly_dedented(codec)
    with pytest.raises(AssertionError):
        _check_every_capture_as_committed(codec)


@pytest.mark.parametrize("codec", list(MODULES))
def test_the_no_break_space_checks_fail_when_only_a_space_or_a_tab_is_indentation(
    codec: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The EOS and IOS XR notion of indentation, given to these readers,
    refuses a capture they read whole."""
    module = MODULES[codec]
    defect = _with_a_defect(module, "_refuse_a_flat_text", "any_white_space=True", "any_white_space=False")
    monkeypatch.setattr(module, "_refuse_a_flat_text", defect)
    with pytest.raises(ParseError):
        _check_no_break_spaces(codec, KITCHEN_SINKS[codec])
    with pytest.raises(ParseError):
        _check_shape(codec, "a body indented with no-break spaces")


def test_the_no_break_space_checks_fail_when_the_helper_ignores_its_parameter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    defect = _with_a_defect(_scanner, "first_flat_stanza", "if any_white_space and line[0].isspace():", "if False:")
    for module in MODULES.values():
        monkeypatch.setattr(module, "first_flat_stanza", defect)
    for codec in MODULES:
        with pytest.raises(ParseError):
            _check_shape(codec, "a body indented with an ideographic space")


@pytest.mark.parametrize("codec", list(MODULES))
def test_the_banner_check_fails_when_the_flat_check_reads_the_banner(
    codec: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Given the text before the banner pass, the flat check takes a
    banner's indented line for indentation."""
    module = MODULES[codec]
    monkeypatch.setattr(module, "without_banner_bodies", lambda raw: raw)
    with pytest.raises(_FAILS):
        _check_banner(codec)


def test_the_range_check_fails_when_the_keyword_stanzas_go_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """An ``interface range`` stanza is taken out of the text, header and
    indented body, before the IOS-XE readers run: a flat check given what
    that pass leaves would not see a range whose body is at the margin."""
    real = ios_parse._refuse_a_flat_text
    monkeypatch.setattr(
        ios_parse, "_refuse_a_flat_text", lambda raw: real(ios_parse.without_keyword_stanzas(raw)[0]),
    )
    with pytest.raises(_FAILS):
        _check_flat_pair("cisco_iosxe_cli", "interface range")


@pytest.mark.parametrize("codec", list(MODULES))
def test_the_quoting_check_fails_for_a_sentence_that_quotes_a_line(
    codec: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = MODULES[codec]
    real = module._refuse_a_flat_text

    def quoting(raw: str) -> None:
        try:
            real(raw)
        except ParseError as error:
            line = raw.splitlines()[int(error.path.split()[-1])]
            raise ParseError(f"{error} ({line})", path=error.path, snippet="") from None
    monkeypatch.setattr(module, "_refuse_a_flat_text", quoting)
    with pytest.raises(AssertionError):
        _check_quotes_nothing(codec, KITCHEN_SINKS[codec])


@pytest.mark.parametrize("codec", list(MODULES))
def test_the_reason_check_fails_for_a_sentence_that_speaks_for_the_device(
    codec: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = MODULES[codec]
    speaks = module.FLAT_TEXT_MESSAGE.replace("this parser tells", "the switch reads and tells")
    monkeypatch.setattr(module, "FLAT_TEXT_MESSAGE", speaks)
    with pytest.raises(AssertionError):
        _check_the_reason(codec)


@pytest.mark.parametrize("codec", list(MODULES))
def test_the_detection_check_fails_when_the_codec_is_not_proposed(
    codec: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(type(get_codec(codec)), "probe", lambda self, raw: 0)
    with pytest.raises(AssertionError):
        _check_detection(codec, KITCHEN_SINKS[codec])


def test_the_walk_check_fails_for_a_walk_of_some_directories() -> None:
    with pytest.raises(AssertionError):
        _check_the_walk(lambda: sorted((FIXTURES / "real" / "cisco_iosxe").iterdir()))

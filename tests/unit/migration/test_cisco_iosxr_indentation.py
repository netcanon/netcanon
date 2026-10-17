"""Cisco IOS XR: a stanza ends at its own ``!``, and a text the router
would place otherwise than it is written is refused in words.

When IOS XR loads a configuration file it places each line by its
indentation: a line in column 0 is a line of the top level, and a
line indented under another is in that line's submode (inferred:
Cisco's CLI model has "indentation tracking", and a Cisco engineer's
router output shows a file with no indentation loaded with its lines
in the wrong mode; no manual says it in a sentence).  A file whose
indentation was lost loads with its lines in the wrong submode, and
nothing the router reports says which.  ``show running-config`` prints
every submode closed by a ``!`` at its own depth, as every committed
capture and Cisco's examples print it.

Three things follow, each tested here.

(a) A stanza ends at a line in column 0, its own ``!`` among them, and
    never at the indented ``!`` that closes a submode of it (``ptp`` or
    ``lldp`` under an ``interface``).  The interface parser used to end
    the interface there and read none of its lines after the submode:
    two interfaces of a committed capture lost their addresses.  A line
    indented deeper than the stanza's own first body line is the
    submode's, not the stanza's.
(b) A text with NO indentation, a stanza's body at the left margin, is
    refused with a sentence that says why and names a line, and quotes
    nothing of the text.  Read, it was interfaces and VRFs made of
    lines nested under routing protocols, users with no secret and no
    address at all, in jobs that said ``completed``.  A text with SOME
    lines dedented is read by its indentation, as the router reads it.
(c) A line in column 0 that states an interface's setting on the
    ``interface`` line -- the form ``show running-config formal``
    prints, by the shape Cisco shows for class and policy maps, or a
    one-line command typed into a printed text -- is refused the same
    way.  Read, it was a second record of the interface with the
    setting lost.

Each check is also handed the defect it is for, and has to fail (the
last section).  The readings of the text here (where a stanza's body
is, what a formal text looks like) are typed by hand, never asked of
the parser.
"""

from __future__ import annotations

import inspect
import re
import textwrap
from collections.abc import Callable
from pathlib import Path

import pytest

from netcanon.migration.canonical.intent import CanonicalIntent
from netcanon.migration.codecs import _scanner
from netcanon.migration.codecs.base import ParseError
from netcanon.migration.codecs.cisco_iosxr import CiscoIOSXRCodec
from netcanon.migration.codecs.cisco_iosxr import parse as xr_parse
from netcanon.migration.codecs.registry import get_codec
from netcanon.services.migration_detect import detect_codec
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
#: Every committed IOS XR capture: the real ones and the synthetic config.
CAPTURES = sorted(
    [p for p in (FIXTURES / "real" / "cisco_iosxr").iterdir() if p.suffix in (".cfg", ".txt")]
    + [FIXTURES / "synthetic" / "cisco_iosxr" / "kitchen_sink.cfg"]
)
IDS = [p.name for p in CAPTURES]
DESIGN_CST = FIXTURES / "real" / "cisco_iosxr" / "iosxr_design_cst_pa3_xr752.cfg"
KITCHEN_SINK = FIXTURES / "synthetic" / "cisco_iosxr" / "kitchen_sink.cfg"
_NEVER = re.compile(r"(?!)")


def _parse(text: str) -> CanonicalIntent:
    return CiscoIOSXRCodec().parse(text)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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


def test_the_captures_are_found() -> None:
    assert DESIGN_CST in CAPTURES and KITCHEN_SINK in CAPTURES and len(CAPTURES) >= 12


# ---------------------------------------------------------------------------
# (a) A stanza ends at its own `!`; a submode's lines are the submode's
# ---------------------------------------------------------------------------


def _addresses_by_indentation(text: str) -> dict[str, tuple[int, int]]:
    """For each top-level ``interface <name>`` stanza of a printed text,
    read by its indentation here: how many ``ipv4 address A M`` and
    ``ipv6 address X/N`` lines stand at the stanza's own depth (the
    depth of its first body line).  The first stanza of a name only."""
    found: dict[str, tuple[int, int]] = {}
    lines = text.splitlines()
    for number, line in enumerate(lines):
        words = line.split()
        if line[:1].isspace() or len(words) != 2 or words[0] != "interface":
            continue
        own = None
        v4 = v6 = 0
        for body in lines[number + 1:]:
            if body.strip() and not body[0].isspace():
                break
            if not body.strip():
                continue
            if own is None:
                own = _indent(body)
            if _indent(body) != own:
                continue
            said = body.split()
            if said[:2] == ["ipv4", "address"] and len(said) >= 4 and said[2].count(".") == 3:
                v4 += 1
            elif said[:2] == ["ipv6", "address"] and len(said) >= 3 and "/" in said[2]:
                v6 += 1
        found.setdefault(words[1], (v4, v6))
    return found


def _check_addresses(path: Path) -> None:
    by_hand = _addresses_by_indentation(_read(path))
    tree = _parse(_read(path))
    read: dict[str, tuple[int, int]] = {}
    for iface in tree.interfaces:
        read.setdefault(iface.name, (len(iface.ipv4_addresses), len(iface.ipv6_addresses)))
    assert {name: read.get(name) for name in by_hand} == by_hand, path.name


@pytest.mark.parametrize("path", CAPTURES, ids=IDS)
def test_every_address_of_an_interface_is_on_its_record(path: Path) -> None:
    """Every ``ipv4 address`` / ``ipv6 address`` line at a top-level
    interface's own depth is on that interface's record, a submode
    before it or not."""
    _check_addresses(path)


def _check_design_cst() -> None:
    tree = _parse(_read(DESIGN_CST))
    held = {
        i.name: (len(i.ipv4_addresses), len(i.ipv6_addresses))
        for i in tree.interfaces if i.name in ("TenGigE0/0/0/20", "TenGigE0/0/0/21")
    }
    assert held == {"TenGigE0/0/0/20": (1, 1), "TenGigE0/0/0/21": (1, 1)}


def test_the_two_interfaces_after_a_ptp_submode_carry_their_addresses() -> None:
    """``TenGigE0/0/0/20`` and ``/21`` of the design_cst capture each
    hold a ``ptp`` submode, closed by an indented ``!``, and after it
    one IPv4 and one IPv6 address of their own."""
    _check_design_cst()


SUBMODE_THEN_BODY = (
    "interface GigabitEthernet0/0/0/1\n"
    " description to-core\n"
    " lldp\n"
    "  receive disable\n"
    " !\n"
    " mtu 9000\n"
    " ipv4 address 192.0.2.1 255.255.255.252\n"
    " ipv6 address 2001:db8::1/64\n"
    " shutdown\n"
    "!\n"
    "interface GigabitEthernet0/0/0/2\n"
    " description to-edge\n"
    "!\n"
)


def _check_submode_then_body() -> None:
    one, two = _parse(SUBMODE_THEN_BODY).interfaces
    assert (one.name, one.description, one.mtu, one.enabled) == (
        "GigabitEthernet0/0/0/1", "to-core", 9000, False,
    )
    assert [(a.ip, a.prefix_length) for a in one.ipv4_addresses] == [("192.0.2.1", 30)]
    assert [(a.ip, a.prefix_length) for a in one.ipv6_addresses] == [("2001:db8::1", 64)]
    assert (two.name, two.description) == ("GigabitEthernet0/0/0/2", "to-edge")


def test_an_interfaces_lines_after_a_submode_are_its_own() -> None:
    _check_submode_then_body()


#: The words under ``frequency synchronization`` are chosen to be words
#: an interface's own lines begin with.  Indented under the submode,
#: they are the submode's, whatever they say.
NESTED_WORDS = (
    "interface GigabitEthernet0/0/0/1\n"
    " description to-core\n"
    " frequency synchronization\n"
    "  description of the clock\n"
    "  shutdown\n"
    "  mtu 1500\n"
    " !\n"
    " ipv4 address 192.0.2.1 255.255.255.252\n"
    "!\n"
)


def _check_nested_words() -> None:
    (iface,) = _parse(NESTED_WORDS).interfaces
    assert (iface.description, iface.enabled, iface.mtu, len(iface.ipv4_addresses)) == (
        "to-core", True, None, 1,
    )


def test_a_line_under_a_submode_is_not_the_interfaces() -> None:
    _check_nested_words()


NESTED_BUNDLE = (
    "interface GigabitEthernet0/0/0/3\n"
    " description member\n"
    " a-submode\n"
    "  bundle id 7 mode active\n"
    " !\n"
    "!\n"
    "interface GigabitEthernet0/0/0/4\n"
    " bundle id 8 mode active\n"
    "!\n"
)


def _check_nested_bundle() -> None:
    tree = _parse(NESTED_BUNDLE)
    assert [(i.name, i.lag_member_of) for i in tree.interfaces] == [
        ("GigabitEthernet0/0/0/3", None), ("GigabitEthernet0/0/0/4", "Bundle-Ether8"),
    ]
    assert [(lag.name, lag.members) for lag in tree.lags] == [
        ("Bundle-Ether8", ["GigabitEthernet0/0/0/4"]),
    ]


def test_a_bundle_line_under_a_submode_makes_no_member() -> None:
    """The interface's record and the LAG's member list read the stanza
    by the same rule."""
    _check_nested_bundle()


NESTED_USER_LINES = (
    "username netops\n"
    " group root-lr\n"
    " a-submode\n"
    "  secret 10 $6$fake$nested\n"
    " !\n"
    "!\n"
    "username ops2\n"
    " group sysadmin\n"
    " a-submode\n"
    "  group root-lr\n"
    " !\n"
    " secret 10 $6$fake$hash\n"
    "!\n"
)


def _check_nested_user_lines() -> None:
    users = _parse(NESTED_USER_LINES).local_users
    assert [(u.name, u.role, u.privilege_level, u.hashed_password) for u in users] == [
        ("netops", "root-lr", 15, ""),
        ("ops2", "sysadmin", 1, "10 $6$fake$hash"),
    ]


def test_a_users_lines_after_a_submode_are_its_own_and_its_submodes_are_not() -> None:
    _check_nested_user_lines()


# ---------------------------------------------------------------------------
# (b) A text with no indentation is refused in words
# ---------------------------------------------------------------------------

#: The headers of the stanzas the parser reads, typed by hand: their
#: first words, and how many words the line has (None: more than those).
_HEADERS_BY_HAND = (
    (("interface",), None), (("vrf",), 2), (("router", "static"), 2),
    (("router", "bgp"), None), (("username",), 2), (("ntp",), 1),
)


def _is_header(line: str) -> bool:
    words = line.split()
    return any(
        tuple(words[:len(first)]) == first
        and (len(words) == count if count is not None else len(words) > len(first))
        for first, count in _HEADERS_BY_HAND
    )


def _first_stanza_with_a_body(printed: str) -> int:
    """In a printed text: the line number of the first line, at any
    depth, that opens a stanza of a kind the parser reads and has a line
    indented under it.  Dedented, it is the first such header with a line
    after it at the margin (a nested ``interface`` line under a config
    group or a routing protocol is one, once dedented)."""
    lines = printed.splitlines()
    for number, line in enumerate(lines, 1):
        if not _is_header(line.strip()):
            continue
        after = next((nxt for nxt in lines[number:] if nxt.strip()), "")
        if _indent(after) > _indent(line):
            return number
    raise AssertionError("no stanza with a body")


def _refusal(text: str) -> ParseError:
    with pytest.raises(ParseError) as caught:
        _parse(text)
    return caught.value


def _check_flat(path: Path) -> None:
    raw = _read(path)
    error = _refusal(_dedent(raw))
    assert str(error) == xr_parse.FLAT_TEXT_MESSAGE.format(line=_first_stanza_with_a_body(raw)), path.name


@pytest.mark.parametrize("path", CAPTURES, ids=IDS)
def test_a_capture_without_its_indentation_is_refused(path: Path) -> None:
    """Every committed capture with every line's leading white space
    removed is refused with the sentence, at the first stanza whose
    body the capture prints indented."""
    _check_flat(path)


def _check_flat_without_bangs(path: Path) -> None:
    raw = _read(path)
    text, where = _without_bangs(raw)
    error = _refusal(text)
    named = int(error.path.split()[-1])
    assert str(error) == xr_parse.FLAT_TEXT_MESSAGE.format(line=named), path.name
    # The line it names opens a stanza, at or before the first one whose
    # body the capture prints indented: with its `!` lines gone, a text
    # cannot tell an empty stanza from one whose body is at the margin.
    assert _is_header(raw.splitlines()[where[named] - 1].strip())
    assert where[named] <= _first_stanza_with_a_body(raw), path.name


@pytest.mark.parametrize("path", CAPTURES, ids=IDS)
def test_a_capture_without_its_indentation_or_its_bangs_is_refused(path: Path) -> None:
    _check_flat_without_bangs(path)


def _with_no_break_spaces(text: str) -> str:
    """*text* with every space in front of a line a no-break space."""
    return "\n".join(
        "\u00a0" * (len(line) - len(line.lstrip(" "))) + line.lstrip(" ") for line in text.splitlines()
    ) + "\n"


def _is_comment(line: str) -> bool:
    return line.strip().startswith("!") and line.strip() != "!"


def _first_top_stanza_with_a_body(printed: str) -> int:
    """In a printed text: the number of the first line in column 0 that
    opens a stanza of a kind the parser reads and has after it (comments
    passed over) an indented line that is no ``!``.  A no-break space in
    front of a line is no indentation, so a nested header is no header
    there."""
    lines = printed.splitlines()
    for number, line in enumerate(lines, 1):
        if not line[:1] or line[0].isspace() or not _is_header(line):
            continue
        after = next((nxt for nxt in lines[number:] if nxt.strip() and not _is_comment(nxt)), "")
        if after[:1] in (" ", "\t") and after.strip() != "!":
            return number
    raise AssertionError("no stanza with a body")


def _check_no_break_spaces(path: Path) -> None:
    raw = _read(path)
    error = _refusal(_with_no_break_spaces(raw))
    assert str(error) == xr_parse.FLAT_TEXT_MESSAGE.format(line=_first_top_stanza_with_a_body(raw)), path.name


@pytest.mark.parametrize("path", CAPTURES, ids=IDS)
def test_a_capture_indented_with_no_break_spaces_is_refused(path: Path) -> None:
    """A no-break space is no indentation to the flat check: the
    ``ntp`` block reader takes only a space or a tab, so a capture
    indented with no-break spaces (a paste out of a web page) lost its
    NTP servers in a job that said nothing of it.  It is refused in
    words."""
    _check_no_break_spaces(path)


_WORD = re.compile(r"[^\s`'\"()]+")


def _check_quotes_nothing(path: Path) -> None:
    error = _refusal(_dedent(_read(path)))
    number = error.path.split()[-1]
    fixed = set(_WORD.findall(xr_parse.FLAT_TEXT_MESSAGE.replace("{line}", "")))
    assert set(_WORD.findall(str(error))) - fixed == {number}, path.name
    assert error.snippet == "", path.name


@pytest.mark.parametrize("path", CAPTURES, ids=IDS)
def test_the_sentence_quotes_nothing_of_the_text(path: Path) -> None:
    """What a parse failure says is logged; the sentence holds its own
    words and a line number, and nothing else."""
    _check_quotes_nothing(path)


def _check_jobs(path: Path) -> None:
    flat = _dedent(_read(path))
    said = "parse failed: " + xr_parse.FLAT_TEXT_MESSAGE.format(
        line=_first_stanza_with_a_body(_read(path)))
    for target in ("cisco_iosxr", "juniper_junos"):
        job = run_plan_with_checked_names(
            get_codec("cisco_iosxr"), get_codec(target), flat, port_rename_map={},
        )
        assert (job.status.value, job.error) == ("failed", said), (path.name, target)


@pytest.mark.parametrize("path", CAPTURES, ids=IDS)
def test_the_job_says_parse_failed_with_the_sentence(path: Path) -> None:
    _check_jobs(path)


def _check_detection(path: Path) -> None:
    raw = _read(path)
    for text in (_dedent(raw), _without_bangs(raw)[0]):
        ranked = detect_codec(text, min_confidence=40)
        assert ranked and ranked[0].codec == "cisco_iosxr", path.name


@pytest.mark.parametrize("path", CAPTURES, ids=IDS)
def test_detection_keeps_iosxr_first(path: Path) -> None:
    """The migrate page offers another vendor for a ``parse failed`` job
    only where detection's first codec is not the source: a flat IOS XR
    text is detected as IOS XR, so the sentence stands alone."""
    _check_detection(path)


#: Short IOS XR texts, typed by hand, printed as the router prints them.
SHORT_TEXTS = {
    "an interface": (
        "interface GigabitEthernet0/0/0/0\n description uplink\n"
        " ipv4 address 192.0.2.1 255.255.255.252\n!\n"
    ),
    "a LAG and its member": (
        "interface Bundle-Ether1\n mtu 9000\n ipv4 address 192.0.2.5 255.255.255.252\n!\n"
        "interface TenGigE0/0/0/1\n bundle id 1 mode active\n!\n"
    ),
    "a user and a vrf, no interface": (
        "hostname xr1\nusername ops\n group root-lr\n secret 10 $6$fake$hash\n!\n"
        "vrf CUST\n description c\n address-family ipv4 unicast\n  import route-target\n"
        "   65000:1\n  !\n !\n!\n"
    ),
}
#: The short texts detection does not put IOS XR first for, and what it
#: puts first instead -- printed, without indentation, and in the formal
#: shape (None: no codec at all).  A weakness of detection that is older
#: than the refusal: the printed text is not detected as IOS XR either.
#: The flat text is refused with the IOS XR sentence, and the migrate
#: page then offers the codec named here beside it.  Known, and pinned
#: so that a change is seen: compared for equality, so a change to
#: detection that moves one fails until its pin is changed.
DETECTED_OTHERWISE = {
    "a user and a vrf, no interface": ("cisco_iosxe_cli", "cisco_iosxe_cli", None),
}


def _first_detected(text: str) -> str | None:
    ranked = detect_codec(text, min_confidence=40)
    return ranked[0].codec if ranked else None


def _check_short_texts() -> None:
    found = {}
    for name, printed in SHORT_TEXTS.items():
        assert str(_refusal(_dedent(printed))).startswith("cisco_iosxr: this text has no indentation."), name
        tops = tuple(_first_detected(t) for t in (printed, _dedent(printed), _formal(printed)[0]))
        if tops != ("cisco_iosxr",) * 3:
            found[name] = tops
    assert found == DETECTED_OTHERWISE


def test_the_short_texts_not_detected_as_iosxr_are_pinned() -> None:
    """A text with no XR-shaped interface name is detected as IOS-XE,
    printed or not; the refusal makes that reachable on the migrate
    page.  Pinned, not mended here: detection is a change of its own."""
    _check_short_texts()


#: Committed captures that ARE the flat shape, as committed.  An IOSv
#: capture in which every line stands at column 0: the indentation was
#: lost between the device and the repository (inferred: the lab
#: topology file it comes from embeds it), as IOSv prints its interface
#: bodies indented.  It is not an IOS XR text; were it given to the IOS
#: XR parser, the refusal would be right.  Its own codec, IOS-XE CLI,
#: reads it as interfaces with no address, no ``shutdown`` and no dot1Q
#: tag (the CHANGELOG's known limitations).
FLAT_AS_COMMITTED = {"real/cisco_iosxe/cml_basic_forwarding_iosv_r1_ospf.txt"}
_NOT_A_CAPTURE = {".md", ".json", ".yaml", ".yml", ".py", ".pyc"}
#: The directories under ``tests/fixtures/`` that hold no capture: what
#: a translation is expected to give, model families, target profiles.
_NOT_CAPTURES = {"cross_vendor_expectations", "model_families", "target_profiles", "__pycache__"}
#: Captures outside ``real/`` and ``synthetic/``, named so that a walk
#: that misses their directories is seen.
_ELSEWHERE = {
    "aruba_aoss/show_run_simple.txt", "fortigate_cli/fortios_simple.conf",
    "mikrotik_routeros/export_simple.rsc",
}


def _every_committed_capture() -> list[Path]:
    return sorted(
        p for p in FIXTURES.rglob("*")
        if p.is_file() and p.suffix.lower() not in _NOT_A_CAPTURE
        and not _NOT_CAPTURES & set(p.relative_to(FIXTURES).parts)
    )


def _check_the_walk(walk: Callable[[], list[Path]]) -> None:
    walked = {p.relative_to(FIXTURES).as_posix() for p in walk()}
    assert set(CAPTURES) <= set(walk())
    assert walked >= _ELSEWHERE | FLAT_AS_COMMITTED
    assert {name.split("/")[0] for name in walked} >= {"real", "synthetic", "iosxe", "opnsense"}


def _check_every_capture_as_committed() -> None:
    refused = set()
    for path in _every_committed_capture():
        try:
            xr_parse._refuse_a_form_the_router_misplaces(path.read_text(encoding="utf-8", errors="replace"))
        except ParseError:
            refused.add(path.relative_to(FIXTURES).as_posix())
    assert refused == FLAT_AS_COMMITTED


def test_no_committed_capture_of_any_codec_is_refused_as_committed() -> None:
    """Neither shape is a text any device prints: no committed capture
    of any codec, as committed, is either (but the one that lost its
    indentation on the way).  Every directory under ``tests/fixtures/``
    is walked, but those that hold no capture."""
    _check_the_walk(_every_committed_capture)
    _check_every_capture_as_committed()


def _partly_dedented() -> tuple[str, str]:
    """The kitchen sink with the body of its first addressed top-level
    interface dedented, and that interface's name."""
    lines = _read(KITCHEN_SINK).splitlines()
    by_hand = _addresses_by_indentation(_read(KITCHEN_SINK))
    name = next(n for n, (v4, _v6) in by_hand.items() if v4)
    start = lines.index(f"interface {name}")
    end = next(i for i in range(start + 1, len(lines)) if lines[i][:1] and not lines[i][0].isspace())
    lines[start + 1:end] = [line.lstrip() for line in lines[start + 1:end]]
    return "\n".join(lines) + "\n", name


def _check_partly_dedented() -> None:
    text, name = _partly_dedented()
    tree = _parse(text)
    by_hand = _addresses_by_indentation(_read(KITCHEN_SINK))
    read = {i.name: (len(i.ipv4_addresses), len(i.ipv6_addresses)) for i in tree.interfaces}
    # The dedented lines are lines of the top level, as the router
    # reads them; every other interface is as printed.
    assert read[name] == (0, 0)
    assert {n: read[n] for n in by_hand if n != name} == {n: c for n, c in by_hand.items() if n != name}


def test_a_text_with_some_lines_dedented_is_read_by_its_indentation() -> None:
    _check_partly_dedented()


def test_interfaces_with_no_body_are_not_refused() -> None:
    """``interface <name>`` / ``!`` lines with nothing in them have no
    body to stand at the margin."""
    text = "".join(f"interface GigabitEthernet0/0/0/{n}\n!\n" for n in range(1, 90))
    assert len(_parse(text).interfaces) == 89


#: For each kind of stanza the parser reads, typed by hand: its header,
#: then a line of its body at the left margin.  The name of the parser's
#: pattern for the header beside it.
FLAT_PAIRS = {
    "interface": ("_IFACE_RE", "interface GigabitEthernet0/0/0/0\ndescription uplink\n"),
    "vrf": ("_VRF_TOP_RE", "vrf CUST\ndescription c\n"),
    "router static": ("_ROUTER_STATIC_RE", "router static\naddress-family ipv4 unicast\n"),
    "router bgp": ("_ROUTER_BGP_RE", "router bgp 65000\nbgp router-id 192.0.2.1\n"),
    "username": ("_USERNAME_HDR_RE", "username ops\ngroup root-lr\n"),
    "ntp": ("_NTP_HDR_RE", "ntp\nserver 192.0.2.1\n"),
}


def _check_flat_pair(kind: str) -> None:
    error = _refusal(FLAT_PAIRS[kind][1])
    assert str(error) == xr_parse.FLAT_TEXT_MESSAGE.format(line=1), kind


@pytest.mark.parametrize("kind", list(FLAT_PAIRS))
def test_each_kind_of_stanza_with_its_body_at_the_margin_is_refused(kind: str) -> None:
    _check_flat_pair(kind)


#: Flat texts, typed by hand, and the line the refusal names (None: the
#: text is read).  A comment (``!`` and more) belongs to the line after
#: it, and is passed over -- indented or not, it is never indentation; a
#: bare ``!``, ``exit`` and ``end`` are no body line.  Indentation is a
#: space or a tab, never a no-break space.
FLAT_SHAPES = {
    "a header, then exit": (
        "hostname r1\ninterface GigabitEthernet0/0/0/0\nexit\nrouter static\nexit\n", None,
    ),
    "a body indented with no-break spaces": (
        "hostname r1\nntp\n\u00a0server 192.0.2.50\n!\ninterface GigabitEthernet0/0/0/0\n"
        "\u00a0description uplink\n!\n",
        2,
    ),
    "a comment between a header and its body": (
        "interface GigabitEthernet0/0/0/0\n!! the uplink\ndescription uplink\n", 1,
    ),
    "an indented comment between a header and its body": (
        "interface GigabitEthernet0/0/0/0\n !! the uplink\ndescription uplink\n", 1,
    ),
    "a comment, then the stanza's own !": ("interface GigabitEthernet0/0/0/0\n!! the uplink\n!\n", None),
    "a comment, then another header": (
        "interface GigabitEthernet0/0/0/0\n!! the uplink\ninterface GigabitEthernet0/0/0/1\n!\n", None,
    ),
    "a header, then end": ("interface GigabitEthernet0/0/0/0\nend\n", None),
}


def _check_flat_shape(name: str) -> None:
    text, at = FLAT_SHAPES[name]
    if at is None:
        _parse(text)
    else:
        assert str(_refusal(text)) == xr_parse.FLAT_TEXT_MESSAGE.format(line=at), name


@pytest.mark.parametrize("name", list(FLAT_SHAPES))
def test_a_comment_a_bang_and_end_in_a_flat_text(name: str) -> None:
    _check_flat_shape(name)


def _with_tabs(text: str) -> str:
    """*text* with each space of every line's indentation a tab."""
    return "\n".join("\t" * _indent(line) + line.lstrip() for line in text.splitlines()) + "\n"


def _check_tabs(path: Path) -> None:
    raw = _read(path)
    assert _parse(_with_tabs(raw)).model_dump() == _parse(raw).model_dump(), path.name


@pytest.mark.parametrize("path", CAPTURES, ids=IDS)
def test_a_capture_indented_with_tabs_reads_as_it_does_with_spaces(path: Path) -> None:
    """A tab is indentation: a capture whose indentation is tabs is no
    text without indentation."""
    _check_tabs(path)


#: A word that only BEGINS with a setting's word is no setting: the line
#: is an ``interface`` header with a second word, and is read.
NO_SETTING_WORD = "interface GigabitEthernet0/0/0/1 descriptionfoo\n description uplink\n!\n"


def _check_no_setting_word() -> None:
    _parse(NO_SETTING_WORD)


def test_a_word_that_begins_with_a_settings_word_is_no_setting() -> None:
    _check_no_setting_word()


# ---------------------------------------------------------------------------
# (c) A setting on the `interface` line is refused in words
# ---------------------------------------------------------------------------

#: The words an interface's own body lines begin with, typed by hand.
_SETTINGS_BY_HAND = {"description", "ipv4", "ipv6", "shutdown", "mtu", "vrf", "bundle", "encapsulation"}


def _formal(printed: str) -> tuple[str, int]:
    """The ``show running-config formal`` shape of a printed text,
    written here by hand: every line but a ``!`` or a comment, after the
    text of every line it is indented under; and the number of the
    first line that is a top-level interface's own setting."""
    out: list[str] = []
    stack: list[tuple[int, str]] = []
    first = 0
    for line in printed.splitlines():
        text = line.strip()
        if not text:
            continue
        while stack and stack[-1][0] >= _indent(line):
            stack.pop()
        if text.startswith("!"):
            continue
        out.append(" ".join([t for _, t in stack] + [text]))
        if (
            not first and len(stack) == 1 and stack[0][0] == 0
            and stack[0][1].startswith("interface ") and text.split()[0] in _SETTINGS_BY_HAND
        ):
            first = len(out)
        stack.append((_indent(line), text))
    return "\n".join(out) + "\n", first


def _check_formal(path: Path) -> None:
    text, first = _formal(_read(path))
    assert first, path.name
    error = _refusal(text)
    assert str(error) == xr_parse.FORMAL_LINE_MESSAGE.format(line=first), path.name
    assert error.snippet == ""


@pytest.mark.parametrize("path", CAPTURES, ids=IDS)
def test_a_formal_text_is_refused(path: Path) -> None:
    _check_formal(path)


def _with_a_line_typed_in(line: str) -> tuple[str, int]:
    """The kitchen sink with *line* typed in after the ``!`` that closes
    its first interface stanza, and that line's number."""
    lines = _read(KITCHEN_SINK).splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("interface "))
    close = next(i for i in range(start + 1, len(lines)) if lines[i] == "!")
    lines.insert(close + 1, line)
    return "\n".join(lines) + "\n", close + 2


#: ``l2transport`` stands between a name and its settings on the formal
#: line of an L2 sub-interface, as it does on the header the router
#: prints.
TYPED_IN_L2TRANSPORT = "interface TenGigE0/0/0/14.100 l2transport encapsulation dot1q 100"


def _check_typed_in(line: str) -> None:
    text, number = _with_a_line_typed_in(line)
    error = _refusal(text)
    assert str(error) == xr_parse.FORMAL_LINE_MESSAGE.format(line=number)
    assert not any(word in str(error) for word in line.split() if "/" in word or "." in word)


@pytest.mark.parametrize("line", [
    "interface GigabitEthernet0/0/0/9 description typed by hand",
    "interface GigabitEthernet0/0/0/9 shutdown",
    "interface Bundle-Ether 9 mtu 9000",
    "interface preconfigure TenGigE0/0/0/12 ipv4 address 192.0.2.9 255.255.255.0",
    TYPED_IN_L2TRANSPORT,
    "interface preconfigure TenGigE0/0/0/12.100 l2transport encapsulation dot1q 100",
    "interface Bundle-Ether 9.100 l2transport encapsulation dot1q 100",
])
def test_a_one_line_command_in_a_printed_text_is_refused(line: str) -> None:
    """Read, the line was a second record of an interface with its
    setting lost -- an L2 sub-interface's dot1q tag among them -- and an
    ``interface preconfigure`` one-liner a row that carried the
    setting's value."""
    _check_typed_in(line)


@pytest.mark.parametrize("header", [
    "interface GigabitEthernet0/0/0/1.100 l2transport",
    "interface preconfigure TenGigE0/0/0/12",
    "interface preconfigure TenGigE0/0/0/12.100 l2transport",
    "interface Bundle-Ether 10",
    "interface Bundle-Ether 10.100 l2transport",
])
def test_a_header_the_router_prints_is_no_setting(header: str) -> None:
    _parse(f"{header}\n encapsulation dot1q 100\n!\n")


# ---------------------------------------------------------------------------
# (d) Each check, handed the defect it is for
# ---------------------------------------------------------------------------


def _old_terminator(line: str) -> bool:
    return line.strip() == "!" or bool(line and not line[0].isspace())


@pytest.fixture
def the_old_terminator(monkeypatch: pytest.MonkeyPatch) -> None:
    """The interface stanza ends at a ``!`` of any depth, as it used to."""
    def scan(lines, **kw):
        kw.setdefault("is_terminator", _old_terminator)
        return _scanner.scan_stanzas(lines, **kw)
    monkeypatch.setattr(xr_parse, "scan_stanzas", scan)


@pytest.fixture
def no_submodes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every line of a stanza is the stanza's, at whatever depth."""
    monkeypatch.setattr(xr_parse, "_in_a_submode", lambda line, current: not line.strip())


@pytest.fixture
def no_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(xr_parse, "_refuse_a_form_the_router_misplaces", lambda raw: None)


def test_the_address_checks_fail_under_the_old_terminator(the_old_terminator: None) -> None:
    with pytest.raises(AssertionError):
        _check_addresses(DESIGN_CST)
    with pytest.raises(AssertionError):
        _check_design_cst()
    with pytest.raises(AssertionError):
        _check_submode_then_body()


def test_the_user_check_fails_under_the_old_terminator(monkeypatch: pytest.MonkeyPatch) -> None:
    # The user block's own rule, as it used to be: a `!` of any depth.
    real = xr_parse._in_a_submode

    def closes_early(line: str, current: dict) -> bool:
        if line.strip() == "!":
            current["closed"] = True
        return current.get("closed", False) or real(line, current)
    monkeypatch.setattr(xr_parse, "_in_a_submode", closes_early)
    with pytest.raises(AssertionError):
        _check_nested_user_lines()


def test_the_nested_line_checks_fail_with_no_submodes(no_submodes: None) -> None:
    for check in (_check_nested_words, _check_nested_bundle, _check_nested_user_lines):
        with pytest.raises(AssertionError):
            check()


def test_the_refusal_checks_fail_with_no_refusal(no_refusal: None) -> None:
    for check in (_check_flat, _check_flat_without_bangs, _check_jobs, _check_formal):
        with pytest.raises((AssertionError, pytest.fail.Exception)):
            check(KITCHEN_SINK)


def test_the_flat_check_fails_with_no_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(xr_parse, "_STANZA_HEADERS", ())
    with pytest.raises((AssertionError, pytest.fail.Exception)):
        _check_flat(DESIGN_CST)


def test_the_formal_check_fails_with_no_formal_pattern(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(xr_parse, "_SETTING_ON_THE_HEADER_RE", _NEVER)
    with pytest.raises((AssertionError, pytest.fail.Exception)):
        _check_formal(KITCHEN_SINK)


def test_the_partial_and_corpus_checks_fail_when_indentation_is_not_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refusal that judged every text as though it had no indentation
    would refuse a printed one."""
    real = xr_parse._refuse_a_form_the_router_misplaces
    monkeypatch.setattr(xr_parse, "_refuse_a_form_the_router_misplaces", lambda raw: real(_dedent(raw)))
    with pytest.raises((AssertionError, ParseError)):
        _check_partly_dedented()
    with pytest.raises(AssertionError):
        _check_every_capture_as_committed()


def test_the_quoting_check_fails_for_a_sentence_that_quotes_a_line(monkeypatch: pytest.MonkeyPatch) -> None:
    real = xr_parse._refuse_a_form_the_router_misplaces

    def quoting(raw: str) -> None:
        try:
            real(raw)
        except ParseError as error:
            line = raw.splitlines()[int(error.path.split()[-1])]
            raise ParseError(f"{error} ({line})", path=error.path, snippet="") from None
    monkeypatch.setattr(xr_parse, "_refuse_a_form_the_router_misplaces", quoting)
    with pytest.raises(AssertionError):
        _check_quotes_nothing(DESIGN_CST)


def test_the_detection_check_fails_when_iosxr_is_not_proposed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CiscoIOSXRCodec, "probe", lambda self, raw: 0)
    with pytest.raises(AssertionError):
        _check_detection(KITCHEN_SINK)


def _flat_check_with(old: str, new: str) -> Callable[..., int | None]:
    """The shared flat check (:func:`_scanner.first_flat_stanza`, which
    the refusal calls for its flat half) with *old*, one fragment of its
    source, written as *new*: a defect put back, in this process only.
    A fragment that is no longer in the source fails here, not in
    silence."""
    source = textwrap.dedent(inspect.getsource(_scanner.first_flat_stanza))
    assert source.count(old) == 1, old
    space = dict(vars(_scanner))
    exec(compile(source.replace(old, new), "<a defect put back>", "exec"), space)
    return space["first_flat_stanza"]


def test_the_comment_checks_fail_when_a_comment_is_a_body_line(monkeypatch: pytest.MonkeyPatch) -> None:
    defect = _flat_check_with('if stripped.startswith("!") and stripped != "!":', "if False:")
    monkeypatch.setattr(xr_parse, "first_flat_stanza", defect)
    for name in ("a comment, then the stanza's own !", "a comment, then another header"):
        with pytest.raises(ParseError):
            _check_flat_shape(name)


def test_the_indented_comment_check_fails_when_a_comment_is_indentation(monkeypatch: pytest.MonkeyPatch) -> None:
    defect = _flat_check_with(
        'if stripped.startswith("!") and stripped != "!":',
        'if line[0] not in " \\t" and stripped.startswith("!") and stripped != "!":',
    )
    monkeypatch.setattr(xr_parse, "first_flat_stanza", defect)
    with pytest.raises((AssertionError, pytest.fail.Exception)):
        _check_flat_shape("an indented comment between a header and its body")


def test_the_end_check_fails_when_end_is_a_body_line(monkeypatch: pytest.MonkeyPatch) -> None:
    defect = _flat_check_with('not in ("exit", "end")', 'not in ("exit",)')
    monkeypatch.setattr(xr_parse, "first_flat_stanza", defect)
    with pytest.raises(ParseError):
        _check_flat_shape("a header, then end")


def test_the_exit_check_fails_when_exit_is_a_body_line(monkeypatch: pytest.MonkeyPatch) -> None:
    defect = _flat_check_with('not in ("exit", "end")', 'not in ("end",)')
    monkeypatch.setattr(xr_parse, "first_flat_stanza", defect)
    with pytest.raises(ParseError):
        _check_flat_shape("a header, then exit")


def test_the_tab_check_fails_when_only_a_space_is_indentation(monkeypatch: pytest.MonkeyPatch) -> None:
    defect = _flat_check_with('if line[0] in " \\t":', 'if line[0] == " ":')
    monkeypatch.setattr(xr_parse, "first_flat_stanza", defect)
    with pytest.raises(ParseError):
        _check_tabs(KITCHEN_SINK)


def test_the_no_break_space_checks_fail_when_any_white_space_is_indentation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    defect = _flat_check_with('if line[0] in " \\t":', "if line[0].isspace():")
    monkeypatch.setattr(xr_parse, "first_flat_stanza", defect)
    with pytest.raises((AssertionError, pytest.fail.Exception)):
        _check_flat_shape("a body indented with no-break spaces")
    with pytest.raises((AssertionError, pytest.fail.Exception)):
        _check_no_break_spaces(KITCHEN_SINK)


@pytest.mark.parametrize("kind", list(FLAT_PAIRS))
def test_each_kinds_check_fails_without_its_header(kind: str, monkeypatch: pytest.MonkeyPatch) -> None:
    pattern = getattr(xr_parse, FLAT_PAIRS[kind][0])
    assert pattern in xr_parse._STANZA_HEADERS
    monkeypatch.setattr(xr_parse, "_STANZA_HEADERS", tuple(h for h in xr_parse._STANZA_HEADERS if h is not pattern))
    with pytest.raises((AssertionError, pytest.fail.Exception)):
        _check_flat_pair(kind)


def test_the_setting_word_check_fails_without_the_end_of_the_word(monkeypatch: pytest.MonkeyPatch) -> None:
    pattern = xr_parse._SETTING_ON_THE_HEADER_RE
    assert pattern.pattern.count(r"(?![^ \t])") == 1
    monkeypatch.setattr(
        xr_parse, "_SETTING_ON_THE_HEADER_RE", re.compile(pattern.pattern.replace(r"(?![^ \t])", ""), pattern.flags),
    )
    with pytest.raises(ParseError):
        _check_no_setting_word()


def test_the_l2transport_check_fails_without_l2transport(monkeypatch: pytest.MonkeyPatch) -> None:
    pattern = xr_parse._SETTING_ON_THE_HEADER_RE
    assert pattern.pattern.count(r"(?:[ \t]+l2transport)?") == 1
    monkeypatch.setattr(
        xr_parse, "_SETTING_ON_THE_HEADER_RE",
        re.compile(pattern.pattern.replace(r"(?:[ \t]+l2transport)?", ""), pattern.flags),
    )
    with pytest.raises((AssertionError, pytest.fail.Exception)):
        _check_typed_in(TYPED_IN_L2TRANSPORT)


def test_the_short_text_pin_fails_when_detection_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CiscoIOSXRCodec, "probe", lambda self, raw: 100)
    with pytest.raises(AssertionError):
        _check_short_texts()


def test_the_walk_check_fails_for_a_walk_of_some_directories() -> None:
    def some_directories() -> list[Path]:
        return sorted(
            p for root in ("real", "synthetic", "iosxe", "opnsense") for p in (FIXTURES / root).rglob("*")
            if p.is_file() and p.suffix.lower() not in _NOT_A_CAPTURE
        )
    with pytest.raises(AssertionError):
        _check_the_walk(some_directories)

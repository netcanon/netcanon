"""Arista EOS: a text without its indentation is refused in words, a
body that runs to ``EOF`` is text, and ``router bgp`` is read by its own
depth.

What EOS itself makes of a text with no indentation is not stated by
Arista.  Typed or pasted, a line runs in the deepest open mode that
accepts it (Arista's transcripts show it), and Arista's own config
generator deploys a config through eAPI as a flat stream of commands;
so the switch most likely reads such a text by the mode each command
leaves open (inferred).  That reading needs every mode's words -- which
words ``router bgp`` takes, which ``group interface`` takes -- and no
Arista page lists them.  This parser reads a stanza by its indentation,
and read without it, a nested ``vlan <id>`` under ``router bgp`` was a
second VLAN and every address, description, membership, LAG, VNI and
route target was lost, in jobs that said ``completed`` or were
``partial`` for another reason, none saying a line was not read.

Four things follow, each tested here.

(a) A text with NO indentation (a space or a tab; a no-break space is
    none), a stanza's body at the left margin, is refused with a
    sentence that gives this parser's reason, names a line, and quotes
    nothing of the text.  A text with SOME lines dedented is read by its
    indentation.
(b) A body that runs to an ``EOF`` line -- a banner, a comment typed in
    a mode, RCF code, a multi-line ``action bash``, a certificate and
    its key -- is text, never lines of the config.  Read as lines, the
    banner below put an account with privilege 15 and no secret into
    the output of twelve of the thirteen targets, seven of those jobs
    saying ``completed``; its interface into the output of every
    target, its route into eleven and its VLAN into nine; and a Tier-3
    row into the tree.  A body with no ``EOF`` is refused in words.
(c) Every indented line of an interface or a VLAN is the stanza's, at
    any depth, as before; ``router bgp`` is read by relative depth, its
    own lines at the shallowest depth of any of them, so tabs and other
    widths read as EOS's own three spaces do, and a ``!`` closes no
    block; an empty line closes nothing.
(d) Each check is handed the defect it is for, and has to fail (the last
    section).

The readings of the text here (where a stanza's body is, what each
small text holds) are typed by hand, never asked of the parser.
"""

from __future__ import annotations

import inspect
import re
import textwrap
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

from netcanon.migration.canonical.intent import CanonicalIntent
from netcanon.migration.codecs import _scanner
from netcanon.migration.codecs.arista_eos import AristaEOSCodec
from netcanon.migration.codecs.arista_eos import codec as eos_codec
from netcanon.migration.codecs.arista_eos import parse as eos_parse
from netcanon.migration.codecs.base import ParseError
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.services.migration_detect import detect_codec
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
#: Every committed EOS capture: the real ones and the synthetic config.
CAPTURES = sorted(
    [p for p in (FIXTURES / "real" / "arista_eos").iterdir() if p.suffix in (".cfg", ".txt")]
    + [FIXTURES / "synthetic" / "arista_eos" / "kitchen_sink.txt"]
)
IDS = [p.name for p in CAPTURES]
KITCHEN_SINK = FIXTURES / "synthetic" / "arista_eos" / "kitchen_sink.txt"
EVPN_LEAF = FIXTURES / "real" / "arista_eos" / "batfish_eos_evpn_vlan_based_leaf.txt"
_NEVER = re.compile(r"(?!)")


def _parse(text: str) -> CanonicalIntent:
    return AristaEOSCodec().parse(text)


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


def _tree(text: str) -> dict:
    return _parse(text).model_dump()


def test_the_captures_are_found() -> None:
    assert KITCHEN_SINK in CAPTURES and EVPN_LEAF in CAPTURES and len(CAPTURES) >= 6


# ---------------------------------------------------------------------------
# (a) A text with no indentation is refused in words
# ---------------------------------------------------------------------------

#: The headers of the stanzas the parser reads by their indentation,
#: typed by hand: their first words, how many words the line has (None:
#: more than those), and whether the last word is a number.
_HEADERS_BY_HAND = (
    (("interface",), 2, False), (("vlan",), 2, True), (("vrf", "instance"), 3, False),
    (("vrf", "definition"), 3, False), (("ip", "dhcp", "pool"), 4, False), (("router", "bgp"), None, False),
)


def _is_header(line: str) -> bool:
    words = line.split()
    return any(
        tuple(words[:len(first)]) == first
        and (len(words) == count if count is not None else len(words) > len(first))
        and (not number or words[-1].isdigit())
        for first, count, number in _HEADERS_BY_HAND
    )


def _first_stanza_with_a_body(printed: str) -> int:
    """In a printed text: the line number of the first line, at any
    depth, that opens a stanza of a kind the parser reads and has a line
    indented under it.  Dedented, it is the first such header with a line
    after it at the margin (a ``vlan <id>`` block under ``router bgp`` is
    one, once dedented)."""
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
    assert str(error) == eos_parse.FLAT_TEXT_MESSAGE.format(line=_first_stanza_with_a_body(raw)), path.name
    assert error.path == f"line {_first_stanza_with_a_body(raw)}", path.name


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
    assert str(error) == eos_parse.FLAT_TEXT_MESSAGE.format(line=named), path.name
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
    front of a line is no indentation, so a header under ``router bgp``
    is no header there."""
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
    assert str(error) == eos_parse.FLAT_TEXT_MESSAGE.format(line=_first_top_stanza_with_a_body(raw)), path.name


@pytest.mark.parametrize("path", CAPTURES, ids=IDS)
def test_a_capture_indented_with_no_break_spaces_is_refused(path: Path) -> None:
    """The interface, VLAN and ``router bgp`` readers take a line with a
    no-break space in front of it for one at the margin: a capture so
    indented (a paste out of a web page) was read as far less, in jobs
    that said nothing of it, and is refused in words."""
    _check_no_break_spaces(path)


_WORD = re.compile(r"[^\s`'\"()]+")


def _quotes_nothing(error: ParseError, sentence: str) -> None:
    number = error.path.split()[-1]
    fixed = set(_WORD.findall(sentence.replace("{line}", "")))
    assert set(_WORD.findall(str(error))) - fixed == {number}
    assert error.snippet == ""


def _check_quotes_nothing(path: Path) -> None:
    _quotes_nothing(_refusal(_dedent(_read(path))), eos_parse.FLAT_TEXT_MESSAGE)


@pytest.mark.parametrize("path", CAPTURES, ids=IDS)
def test_the_sentence_quotes_nothing_of_the_text(path: Path) -> None:
    """What a parse failure says is logged; the sentence holds its own
    words and a line number, and nothing else."""
    _check_quotes_nothing(path)


def _check_the_reason() -> None:
    sentence = eos_parse.FLAT_TEXT_MESSAGE.lower()
    assert "this parser tells which lines belong to a stanza by their indentation" in sentence
    for claim in ("the switch reads", "the switch places", "misplace", "would load"):
        assert claim not in sentence, claim


def test_the_sentence_gives_the_parsers_reason_not_the_switchs() -> None:
    """Arista does not say what the switch does with a text that lost
    its indentation; the sentence says what this parser cannot do."""
    _check_the_reason()


def _check_jobs(path: Path) -> None:
    flat = _dedent(_read(path))
    said = "parse failed: " + eos_parse.FLAT_TEXT_MESSAGE.format(line=_first_stanza_with_a_body(_read(path)))
    for target in ("arista_eos", "juniper_junos"):
        job = run_plan_with_checked_names(get_codec("arista_eos"), get_codec(target), flat, port_rename_map={})
        assert (job.status.value, job.error) == ("failed", said), (path.name, target)


@pytest.mark.parametrize("path", CAPTURES, ids=IDS)
def test_the_job_says_parse_failed_with_the_sentence(path: Path) -> None:
    _check_jobs(path)


def _check_detection(path: Path) -> None:
    raw = _read(path)
    for text in (_dedent(raw), _without_bangs(raw)[0]):
        ranked = detect_codec(text, min_confidence=40)
        assert ranked and ranked[0].codec == "arista_eos", path.name


@pytest.mark.parametrize("path", CAPTURES, ids=IDS)
def test_detection_keeps_eos_first(path: Path) -> None:
    """The migrate page offers another vendor for a ``parse failed`` job
    only where detection's first codec is not the source: a flat EOS
    text is detected as EOS, so the sentence stands alone."""
    _check_detection(path)


#: Committed captures that ARE the flat shape, as committed, through the
#: EOS checks.  Neither is an EOS text, and were either given to the EOS
#: parser, refusing it would be right: an AOS-S capture and an IOSv
#: capture in which every line stands at column 0, their indentation lost
#: between the device and the repository (the CHANGELOG's AOS-S entry and
#: the AOS-S guard say so of the first; ``RESULTS.md``, ``NOTICE.md`` and
#: the IOS XR guard of the second).
FLAT_AS_COMMITTED = {
    "real/aruba_aoss/hpe_community_5406rzl2_kb1515.cfg",
    "real/cisco_iosxe/cml_basic_forwarding_iosv_r1_ospf.txt",
}
_NOT_A_CAPTURE = {".md", ".json", ".yaml", ".yml", ".py", ".pyc"}
#: The directories under ``tests/fixtures/`` that hold no capture.
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


def _the_checks(raw: str) -> None:
    """What ``parse_intent`` asks of a text before any reader runs."""
    eos_parse._refuse_a_flat_text(eos_parse.without_bodies(raw))


def _check_the_walk(walk: Callable[[], list[Path]]) -> None:
    walked = {p.relative_to(FIXTURES).as_posix() for p in walk()}
    assert set(CAPTURES) <= set(walk())
    assert walked >= _ELSEWHERE | FLAT_AS_COMMITTED
    assert {name.split("/")[0] for name in walked} >= {"real", "synthetic", "iosxe", "opnsense"}


def _check_every_capture_as_committed() -> None:
    refused = set()
    for path in _every_committed_capture():
        try:
            _the_checks(path.read_text(encoding="utf-8", errors="replace"))
        except ParseError:
            refused.add(path.relative_to(FIXTURES).as_posix())
    assert refused == FLAT_AS_COMMITTED


def test_no_committed_capture_of_any_codec_is_refused_as_committed() -> None:
    """No committed capture of any codec, as committed, is refused by
    the EOS checks (but the two that lost their indentation on the
    way), and no committed capture holds a body without its ``EOF``."""
    _check_the_walk(_every_committed_capture)
    _check_every_capture_as_committed()


def _partly_dedented() -> tuple[str, str]:
    """The kitchen sink with the body of its first interface that has an
    address dedented, and that interface's name (found by hand)."""
    lines = _read(KITCHEN_SINK).splitlines()
    start = next(
        i for i, line in enumerate(lines)
        if line.startswith("interface ") and any(
            nxt.strip().startswith("ip address ") for nxt in lines[i + 1:next(
                j for j in range(i + 1, len(lines)) if lines[j][:1] and not lines[j][0].isspace())]
        )
    )
    end = next(i for i in range(start + 1, len(lines)) if lines[i][:1] and not lines[i][0].isspace())
    lines[start + 1:end] = [line.lstrip() for line in lines[start + 1:end]]
    return "\n".join(lines) + "\n", lines[start].split()[1]


def _addresses(tree: CanonicalIntent) -> dict[str, int]:
    return {i.name: len(i.ipv4_addresses) for i in tree.interfaces}


def _check_partly_dedented() -> None:
    text, name = _partly_dedented()
    read = _addresses(_parse(text))
    printed = _addresses(_parse(_read(KITCHEN_SINK)))
    # The dedented lines are lines of the top level, as this parser
    # reads them; every other interface is as printed.
    assert printed[name] >= 1 and read[name] == 0
    assert {n: c for n, c in read.items() if n != name} == {n: c for n, c in printed.items() if n != name}


def test_a_text_with_some_lines_dedented_is_read_by_its_indentation() -> None:
    _check_partly_dedented()


def _check_no_body() -> None:
    text = "".join(f"interface Ethernet{n}\n!\n" for n in range(1, 90))
    assert len(_parse(text).interfaces) == 89


def test_interfaces_with_no_body_are_not_refused() -> None:
    """``interface <name>`` / ``!`` lines with nothing in them have no
    body to stand at the margin."""
    _check_no_body()


#: For each kind of stanza the parser reads, typed by hand: its header,
#: then a line of its body at the left margin.  The name of the parser's
#: pattern for the header beside it.
FLAT_PAIRS = {
    "interface": ("_INTERFACE_HEADER_RE", "interface Ethernet1\ndescription uplink\n"),
    "vlan": ("_VLAN_HEADER_RE", "vlan 10\nname users\n"),
    "vrf instance": ("_VRF_INSTANCE_RE", "vrf instance RED\ndescription red\n"),
    "vrf definition": ("_VRF_INSTANCE_RE", "vrf definition RED\nrd 65000:1\n"),
    "ip dhcp pool": ("_DHCP_POOL_HEADER_RE", "ip dhcp pool USERS\nnetwork 192.0.2.0 255.255.255.0\n"),
    "router bgp": ("_ROUTER_BGP_RE", "router bgp 65000\nrouter-id 192.0.2.1\n"),
}


def _check_flat_pair(kind: str) -> None:
    error = _refusal(FLAT_PAIRS[kind][1])
    assert str(error) == eos_parse.FLAT_TEXT_MESSAGE.format(line=1), kind


@pytest.mark.parametrize("kind", list(FLAT_PAIRS))
def test_each_kind_of_stanza_with_its_body_at_the_margin_is_refused(kind: str) -> None:
    _check_flat_pair(kind)


#: Flat texts, typed by hand, and the line the refusal names (None: the
#: text is read).  A comment (``!`` and more) belongs to the line after
#: it, and is passed over -- indented or not, it is never indentation; a
#: bare ``!``, ``exit`` and ``end`` are no body line.  Indentation is a
#: space or a tab: a line in front of which stands another white space
#: (a no-break space) is at the margin, as the stanza readers read it.
FLAT_SHAPES = {
    "a comment between a header and its body": ("interface Ethernet1\n!! the uplink\ndescription uplink\n", 1),
    "an indented comment between a header and its body": (
        "interface Ethernet1\n   !! the uplink\ndescription uplink\n", 1,
    ),
    "a comment, then the stanza's own !": ("interface Ethernet1\n!! the uplink\n!\n", None),
    "a comment, then another header": ("interface Ethernet1\n!! the uplink\ninterface Ethernet2\n!\n", None),
    "a header, then end": ("interface Ethernet1\nend\n", None),
    "headers, each then exit": ("hostname sw\ninterface Ethernet1\nexit\nvlan 10\nEXIT\nip routing\n", None),
    "headers only, no !": ("interface Ethernet1\ninterface Ethernet2\nvlan 10\n", None),
    "one-line globals only": ("hostname leaf1\nip route 0.0.0.0/0 192.0.2.1\n", None),
    "a body indented with no-break spaces": (
        "hostname sw\n!\ninterface Ethernet1\n\u00a0\u00a0\u00a0description up\n"
        "\u00a0\u00a0\u00a0ip address 192.0.2.1/31\n!\n",
        3,
    ),
    "a body indented with no-break spaces, and one line with spaces": (
        "interface Ethernet1\n\u00a0\u00a0\u00a0description up\n   mtu 9000\n!\n", None,
    ),
}


def _check_flat_shape(name: str) -> None:
    text, at = FLAT_SHAPES[name]
    if at is None:
        _parse(text)
    else:
        assert str(_refusal(text)) == eos_parse.FLAT_TEXT_MESSAGE.format(line=at), name


@pytest.mark.parametrize("name", list(FLAT_SHAPES))
def test_a_comment_a_bang_and_end_in_a_flat_text(name: str) -> None:
    _check_flat_shape(name)


# ---------------------------------------------------------------------------
# (b) A body that runs to `EOF` is text, never lines of the config
# ---------------------------------------------------------------------------

#: A printed config whose banner holds lines shaped like an account, a
#: VLAN, an interface, a route and an ACL, and its first body line begins
#: with ``!``: a printed banner's body is as it was typed, here at column
#: 0, and ends at ``EOF`` in column 0 (as Arista's pyeapi reads it).  Each
#: word of the banner is in ``BANNER_WORDS``.
BANNER_CONFIG = (
    "! Command: show running-config\n"
    "! device: leaf1 (DCS-7050SX3-48YC8, EOS-4.30.1F)\n"
    "!\n"
    "hostname leaf1\n"
    "!\n"
    "banner motd\n"
    "!!! Authorised access only !!!\n"
    "username intruder privilege 15 nopassword\n"
    "vlan 3999\n"
    "interface Ethernet9\n"
    "   description from-the-banner\n"
    "ip route 0.0.0.0/0 198.51.100.66\n"
    "ip access-list standard FROM_BANNER\n"
    "EOF\n"
    "!\n"
    "vlan 10\n"
    "   name users\n"
    "!\n"
    "interface Ethernet1\n"
    "   description uplink\n"
    "   switchport access vlan 10\n"
    "!\n"
    "end\n"
)
BANNER_WORDS = ("intruder", "3999", "Ethernet9", "from-the-banner", "198.51.100.66", "FROM_BANNER")
#: The same config with no banner.
NO_BANNER_CONFIG = re.sub(r"banner motd\n.*?\nEOF\n!\n", "", BANNER_CONFIG, flags=re.DOTALL)


def test_the_two_configs_differ_by_the_banner_alone() -> None:
    assert "banner" not in NO_BANNER_CONFIG and NO_BANNER_CONFIG.count("\n") == BANNER_CONFIG.count("\n") - 10


def _check_banner_tree() -> None:
    tree = _parse(BANNER_CONFIG)
    assert [u.name for u in tree.local_users] == []
    assert [v.id for v in tree.vlans] == [10]
    assert [i.name for i in tree.interfaces] == ["Ethernet1"]
    assert tree.static_routes == []
    assert tree.dropped_tier3_sections == []
    assert tree.hostname == "leaf1"
    assert tree.model_dump() == _parse(NO_BANNER_CONFIG).model_dump()


def test_a_banners_lines_make_no_record() -> None:
    _check_banner_tree()


def _check_banner_outputs() -> None:
    eos = get_codec("arista_eos")
    for target in list_public_codecs():
        job = run_plan_with_checked_names(eos, get_codec(target), BANNER_CONFIG, port_rename_map={})
        bare = run_plan_with_checked_names(eos, get_codec(target), NO_BANNER_CONFIG, port_rename_map={})
        assert job.rendered, (target, job.error)
        assert [w for w in BANNER_WORDS if w.lower() in job.rendered.lower()] == [], target
        # The banner is not translated, and changes nothing that is.
        assert (job.status, job.rendered, job.warnings) == (bare.status, bare.rendered, bare.warnings), target


def test_no_target_writes_a_banners_words() -> None:
    """Read as lines of the config, the banner above was a privilege-15
    account with no secret in the output of twelve of the thirteen
    targets, seven of those jobs saying ``completed``, and an interface,
    a default route and a VLAN in most of them.  The OUTPUT of every
    public codec is read as text for each of its words."""
    _check_banner_outputs()


#: What a small text below holds, read by hand: an interface, a VLAN and
#: a route the parser reads, after whatever comes before them.
_UPLINK = {"Ethernet1": ("uplink", True)}
_AFTER = (
    "vlan 10\n   name users\n!\ninterface Ethernet1\n   description uplink\n!\n"
    "ip route 0.0.0.0/0 192.0.2.254\n!\n"
)
#: Small printed texts with a body of each kind (or an opener with none
#: after it), typed by hand, and what the parser makes of them -- the
#: readings by hand: the interfaces (description, enabled), the VLAN
#: ids, the routes' destinations and the accounts.
BODIES = {
    "a comment typed in an interface": (
        "interface Ethernet1\n   comment\ndescription from the comment\nshutdown\nEOF\n"
        "   description uplink\n!\n",
        (_UPLINK, [], [], []),
    ),
    "RCF code with an indented EOF": (
        "router general\n   control-functions\n      code unit SHAPED\nvlan 3999\n"
        "interface Ethernet9\n   description from-the-code\n      EOF\n   !\n!\n"
        "interface Ethernet1\n   description uplink\n!\n",
        (_UPLINK, [], [], []),
    ),
    "a multi-line action bash": (
        "event-handler SHAPED\n   action bash\ninterface Ethernet9\n   description from-the-script\n"
        "      EOF\n   delay 0\n!\ninterface Ethernet1\n   description uplink\n!\n",
        (_UPLINK, [], [], []),
    ),
    # As Arista's config generator prints it: a certificate, then its
    # key, each PEM text ended by its own `EOF`.
    "a certificate and its key": (
        "management api http-commands\n   protocol https certificate\n   -----BEGIN CERTIFICATE-----\n"
        "interface Ethernet8\n-----END CERTIFICATE-----\n   EOF\n   -----BEGIN PRIVATE KEY-----\n"
        "interface Ethernet9\n   description from-the-key\n-----END PRIVATE KEY-----\n   EOF\n"
        "   no shutdown\n!\ninterface Ethernet1\n   description uplink\n!\n",
        (_UPLINK, [], [], []),
    ),
    # No switch printout of the opener is to hand: one body, or none,
    # and the lines after it are the config's.
    "a certificate printed with one body": (
        "management api http-commands\n   protocol https certificate\n   -----BEGIN CERTIFICATE-----\n"
        "MIIfakefake\n-----END CERTIFICATE-----\n   EOF\n   no shutdown\n!\n" + _AFTER,
        (_UPLINK, [10], ["0.0.0.0/0"], []),
    ),
    "a certificate printed with no body": (
        "management api http-commands\n   protocol https certificate\n   no shutdown\n!\n" + _AFTER,
        (_UPLINK, [10], ["0.0.0.0/0"], []),
    ),
    "a banner login whose body has an eof that is no EOF": (
        "banner login\nWelcome\neof\ninterface Ethernet9\n   description still-the-banner\nEOF\n!\n"
        "interface Ethernet1\n   description uplink\n!\n",
        (_UPLINK, [], [], []),
    ),
    # A banner ends at `EOF` in column 0 (as Arista's pyeapi reads a
    # printed one): an indented `EOF` is the banner's text.
    "a banner whose text holds an indented EOF": (
        "hostname sw\n!\nbanner motd\nTo leave this banner editor type\n   EOF\n"
        "username evil privilege 15 nopassword\nvlan 3999\nEOF\n!\n"
        "interface Ethernet1\n   description uplink\n!\n",
        (_UPLINK, [], [], []),
    ),
    "a banner opened in capitals": (
        "BANNER MOTD\nusername evil privilege 15 nopassword\nvlan 3999\nEOF\n!\n"
        "interface Ethernet1\n   description uplink\n!\n",
        (_UPLINK, [], [], []),
    ),
    # The shape check reads the text with the banner's lines empty.
    "a banner whose text begins as JSON does": (
        'banner motd\n{"motd": "authorised access only"}\nEOF\n!\n' + _AFTER,
        (_UPLINK, [10], ["0.0.0.0/0"], []),
    ),
}


def _interfaces(text: str) -> dict[str, tuple[str, bool]]:
    return {i.name: (i.description, i.enabled) for i in _parse(text).interfaces}


def _holds(text: str) -> tuple:
    tree = _parse(text)
    return (
        {i.name: (i.description, i.enabled) for i in tree.interfaces},
        [v.id for v in tree.vlans],
        [r.destination for r in tree.static_routes],
        [u.name for u in tree.local_users],
    )


def _check_body(name: str) -> None:
    text, expected = BODIES[name]
    assert _holds(text) == expected, name


@pytest.mark.parametrize("name", list(BODIES))
def test_every_body_that_runs_to_eof_is_text(name: str) -> None:
    _check_body(name)


#: Texts whose body has no ``EOF`` before the end, and the line that
#: opens it.
UNENDED = {
    "a banner": ("hostname leaf1\n!\nbanner motd\nWelcome\n!\ninterface Ethernet1\n   description uplink\n!\n", 3),
    "a certificate with no EOF": (
        "management api http-commands\n   protocol https certificate\n   -----BEGIN CERTIFICATE-----\n"
        "MIIfake\n!\ninterface Ethernet1\n   description uplink\n!\n",
        2,
    ),
    "a certificate whose key has no EOF": (
        "management api http-commands\n   protocol https certificate\n   -----BEGIN CERTIFICATE-----\n"
        "MIIfake\n   EOF\n   -----BEGIN PRIVATE KEY-----\nMIIfakekey\n!\n",
        2,
    ),
}


def _check_unended(name: str) -> None:
    text, at = UNENDED[name]
    error = _refusal(text)
    assert str(error) == eos_parse.UNENDED_BODY_MESSAGE.format(line=at), name
    assert error.path == f"line {at}", name
    _quotes_nothing(error, eos_parse.UNENDED_BODY_MESSAGE)
    job = run_plan_with_checked_names(get_codec("arista_eos"), get_codec("juniper_junos"), text, port_rename_map={})
    assert (job.status.value, job.error) == ("failed", "parse failed: " + str(error)), name


@pytest.mark.parametrize("name", list(UNENDED))
def test_a_body_with_no_eof_is_refused_with_its_opening_line(name: str) -> None:
    """Read, everything after it is the body's text, and none of it the
    config: refused in words, naming the line that opens the body."""
    _check_unended(name)


#: A printed text whose banner is shaped like a flat stanza: read, and
#: the banner's stanza is no record.
PRINTED_WITH_A_FLAT_BANNER = (
    "hostname leaf1\n!\nbanner motd\ninterface Ethernet9\ndescription from-the-banner\nEOF\n!\n"
    "interface Ethernet1\n   description uplink\n!\n"
)
#: A flat text whose only indented lines are a banner's, then a flat
#: stanza after it (line 8): refused, at the line the stanza is on.
FLAT_WITH_AN_INDENTED_BANNER = (
    "hostname leaf1\n!\nbanner motd\n   an indented banner line\n      and another\nEOF\n!\n"
    "interface Ethernet1\ndescription uplink\n!\n"
)


def _check_not_fooled() -> None:
    assert _interfaces(PRINTED_WITH_A_FLAT_BANNER) == {"Ethernet1": ("uplink", True)}
    error = _refusal(FLAT_WITH_AN_INDENTED_BANNER)
    assert str(error) == eos_parse.FLAT_TEXT_MESSAGE.format(line=8)


def test_the_flat_check_is_not_fooled_by_a_body_either_way() -> None:
    """A body is no reason to call a text flat, nor to call it
    indented; and the line it names is the line of the whole text."""
    _check_not_fooled()


# ---------------------------------------------------------------------------
# (c) An interface's lines at any depth; ``router bgp`` by its own depth
# ---------------------------------------------------------------------------

#: Interfaces whose own lines do not stand at one depth (a hand edit),
#: and what each holds, read by hand: (description, IPv4 addresses, MTU,
#: enabled).  EOS places a line by its mode, not its indentation, so no
#: depth tells a submode's line from the interface's own: every indented
#: line of the stanza is the stanza's.  The last is what that costs, and
#: a known limitation: a line the reader takes, typed inside a submode,
#: is read as the interface's (no Arista printout shows one there).
UNEVEN = {
    "an own line a space deeper": (
        "interface Ethernet1\n   description up\n    ip address 192.0.2.1/31\n   mtu 9000\n!\n",
        ("up", ["192.0.2.1"], 9000, True),
    ),
    "a tab, then spaces": (
        "interface Ethernet1\n\tdescription up\n   ip address 192.0.2.1/31\n   mtu 9000\n!\n",
        ("up", ["192.0.2.1"], 9000, True),
    ),
    "a first line deeper than the rest": (
        "interface Ethernet1\n      description up\n   ip address 192.0.2.1/31\n!\n",
        ("up", ["192.0.2.1"], None, True),
    ),
    "a line the reader takes, typed in a submode": (
        "interface Ethernet1\n   description uplink\n   tx-queue 0\n      shutdown\n   mtu 9000\n!\n",
        ("uplink", [], 9000, False),
    ),
}


def _check_uneven(name: str) -> None:
    text, expected = UNEVEN[name]
    (iface,) = _parse(text).interfaces
    assert (iface.description, [a.ip for a in iface.ipv4_addresses], iface.mtu, iface.enabled) == expected, name


@pytest.mark.parametrize("name", list(UNEVEN))
def test_every_indented_line_of_an_interface_is_its_own(name: str) -> None:
    _check_uneven(name)


#: ``router bgp`` texts, typed by hand, and the routing instances each
#: holds: (name, type, rd, imports, exports).  The section's own lines
#: are at the shallowest depth of any of them; a block's header stands
#: there, and its lines deeper.
BGP_TEXTS = {
    # A `!` closes no block: a VRF's own line after an address-family.
    "a vrf's line after its address-family": (
        "router bgp 65000\n   router-id 192.0.2.1\n   !\n   vrf RED\n      rd 65000:1\n      !\n"
        "      address-family ipv4\n         neighbor 192.0.2.2 activate\n      !\n"
        "      route-target import evpn 65000:1\n!\n",
        [("RED", "vrf", "65000:1", ["65000:1"], [])],
    ),
    # A `vrf` line deeper than the section's own is no routing instance.
    "a vrf under an address-family": (
        "router bgp 65000\n   address-family ipv4\n      vrf BLUE\n         rd 65000:9\n!\n",
        [],
    ),
    # A `vlan` of a bundle is no MAC-VRF; the section's own `vlan` is.
    "a vlan of a bundle, then a vlan block": (
        "vlan 10\n   name users\n!\nvlan 20\n   name guests\n!\nrouter bgp 65000\n"
        "   vlan-aware-bundle TENANT\n      rd 65000:100\n      route-target both 65000:100\n"
        "      vlan 20\n   !\n   vlan 10\n      rd 65000:10\n      route-target both 65000:10\n!\n",
        [("users", "mac-vrf", "65000:10", ["65000:10"], ["65000:10"])],
    ),
    # Empty lines close nothing.
    "empty lines in a block": (
        "router bgp 65000\n\n   vrf RED\n\n      rd 65000:1\n\n      route-target export evpn 65000:2\n!\n",
        [("RED", "vrf", "65000:1", [], ["65000:2"])],
    ),
    # A comment in column 0 closes nothing, nor ends the section.
    "a column-0 comment between a block's lines": (
        "router bgp 65000\n   router-id 192.0.2.1\n!\n   vrf RED\n      rd 65000:1\n!! a note\n"
        "      route-target import evpn 65000:1\n!\n",
        [("RED", "vrf", "65000:1", ["65000:1"], [])],
    ),
    # The section's depth is its shallowest line, not its first.
    "the section's first line deeper than the rest": (
        "vrf instance RED\n!\nrouter bgp 65000\n      maximum-paths 4\n   vrf RED\n      rd 65000:1\n"
        "      route-target import evpn 65000:1\n!\n",
        [("RED", "vrf", "65000:1", ["65000:1"], [])],
    ),
    # A header deeper than a line of the section's own opens no block:
    # its lines land on nothing (RED is the `vrf instance`'s, bare).
    "a header deeper than a line of the section": (
        "vrf instance RED\n!\nrouter bgp 65000\n  router-id 192.0.2.1\n   vrf RED\n      rd 65000:1\n"
        "      route-target import evpn 65000:1\n!\n",
        [("RED", "vrf", "", [], [])],
    ),
    # A line shallower than the section's other lines is the section's
    # depth: the `vrf` above it is then no block of the section.
    "a line shallower than the section's other lines": (
        "router bgp 65000\n   vrf RED\n      rd 65000:1\n  route-target import evpn 9:9\n!\n",
        [],
    ),
}


def _instances(text: str) -> list[tuple]:
    return [
        (ri.name, ri.instance_type, ri.route_distinguisher, ri.rt_imports, ri.rt_exports)
        for ri in _parse(text).routing_instances
    ]


def _check_bgp(name: str) -> None:
    text, expected = BGP_TEXTS[name]
    assert _instances(text) == expected, name


@pytest.mark.parametrize("name", list(BGP_TEXTS))
def test_router_bgp_is_read_by_relative_depth(name: str) -> None:
    _check_bgp(name)


#: An interface and a VLAN with empty lines inside them.
EMPTY_LINES = (
    "vlan 10\n\n   name users\n!\ninterface Ethernet1\n   description uplink\n\n"
    "   ip address 192.0.2.1/31\n!\n"
)


def _check_empty_lines() -> None:
    tree = _parse(EMPTY_LINES)
    assert [(v.id, v.name) for v in tree.vlans] == [(10, "users")]
    (iface,) = tree.interfaces
    assert (iface.description, [a.ip for a in iface.ipv4_addresses]) == ("uplink", ["192.0.2.1"])


def test_an_empty_line_closes_no_stanza() -> None:
    _check_empty_lines()


def _reindented(text: str, unit: str) -> str:
    """*text* with each level of its indentation (three spaces, as EOS
    prints it) written as *unit*."""
    out = []
    for line in text.splitlines():
        width = len(line) - len(line.lstrip(" "))
        assert width % 3 == 0, line
        out.append(unit * (width // 3) + line.lstrip(" "))
    return "\n".join(out) + "\n"


_UNITS = {"tabs": "\t", "2 spaces": "  ", "4 spaces": "    "}


def _check_reindented(path: Path) -> None:
    raw = _read(path)
    printed = _tree(raw)
    for name, unit in _UNITS.items():
        assert _tree(_reindented(raw, unit)) == printed, (path.name, name)


@pytest.mark.parametrize("path", CAPTURES, ids=IDS)
def test_a_capture_indented_otherwise_reads_as_it_does_as_printed(path: Path) -> None:
    """Indented with tabs, or with two or four spaces a level, every
    committed capture parses to the tree it gives as committed."""
    _check_reindented(path)


def _check_doubled(path: Path) -> None:
    raw = _read(path)
    printed = _tree(raw)
    assert _tree(raw.replace("\n", "\n\n")) == printed, path.name
    assert _tree(raw.replace("\n", "\r\r\n")) == printed, path.name


@pytest.mark.parametrize("path", CAPTURES, ids=IDS)
def test_a_capture_with_its_line_ends_doubled_reads_as_printed(path: Path) -> None:
    """A paste through a tool that doubles every line end (``\\r\\r\\n``
    splits as two lines) parses to the tree the capture gives."""
    _check_doubled(path)


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


@pytest.fixture
def no_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(eos_parse, "_refuse_a_flat_text", lambda raw: None)


def _bodies_by(monkeypatch: pytest.MonkeyPatch, defect: Callable[[str], str]) -> None:
    """The body pass as *defect*, in both places that call it: the
    parser and the Tier-3 rows the codec reads after it."""
    monkeypatch.setattr(eos_parse, "without_bodies", defect)
    monkeypatch.setattr(eos_codec, "without_bodies", defect)


@pytest.fixture
def bodies_read_as_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    _bodies_by(monkeypatch, lambda raw: raw)


def test_the_refusal_checks_fail_with_no_refusal(no_refusal: None) -> None:
    for check in (_check_flat, _check_flat_without_bangs, _check_no_break_spaces, _check_jobs):
        with pytest.raises((AssertionError, pytest.fail.Exception)):
            check(KITCHEN_SINK)
    with pytest.raises((AssertionError, pytest.fail.Exception)):
        _check_not_fooled()


def test_the_flat_check_fails_with_no_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(eos_parse, "_STANZA_HEADERS", ())
    with pytest.raises((AssertionError, pytest.fail.Exception)):
        _check_flat(EVPN_LEAF)


@pytest.mark.parametrize("kind", list(FLAT_PAIRS))
def test_each_kinds_check_fails_without_its_header(kind: str, monkeypatch: pytest.MonkeyPatch) -> None:
    pattern = getattr(eos_parse, FLAT_PAIRS[kind][0])
    assert pattern in eos_parse._STANZA_HEADERS
    monkeypatch.setattr(
        eos_parse, "_STANZA_HEADERS", tuple(h for h in eos_parse._STANZA_HEADERS if h is not pattern),
    )
    with pytest.raises((AssertionError, pytest.fail.Exception)):
        _check_flat_pair(kind)


def test_the_partial_and_corpus_checks_fail_when_indentation_is_not_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refusal that judged every text as though it had no indentation
    would refuse a printed one."""
    real = eos_parse._refuse_a_flat_text
    monkeypatch.setattr(eos_parse, "_refuse_a_flat_text", lambda raw: real(_dedent(raw)))
    with pytest.raises((AssertionError, ParseError)):
        _check_partly_dedented()
    with pytest.raises(AssertionError):
        _check_every_capture_as_committed()


def test_the_quoting_check_fails_for_a_sentence_that_quotes_a_line(monkeypatch: pytest.MonkeyPatch) -> None:
    real = eos_parse._refuse_a_flat_text

    def quoting(raw: str) -> None:
        try:
            real(raw)
        except ParseError as error:
            line = raw.splitlines()[int(error.path.split()[-1])]
            raise ParseError(f"{error} ({line})", path=error.path, snippet="") from None
    monkeypatch.setattr(eos_parse, "_refuse_a_flat_text", quoting)
    with pytest.raises(AssertionError):
        _check_quotes_nothing(EVPN_LEAF)


def test_the_detection_check_fails_when_eos_is_not_proposed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(AristaEOSCodec, "probe", lambda self, raw: 0)
    with pytest.raises(AssertionError):
        _check_detection(KITCHEN_SINK)


def _flat_check_with(old: str, new: str) -> Callable[..., int | None]:
    return _with_a_defect(_scanner, "first_flat_stanza", old, new)


def test_the_comment_checks_fail_when_a_comment_is_a_body_line(monkeypatch: pytest.MonkeyPatch) -> None:
    defect = _flat_check_with('if stripped.startswith("!") and stripped != "!":', "if False:")
    monkeypatch.setattr(eos_parse, "first_flat_stanza", defect)
    for name in ("a comment, then the stanza's own !", "a comment, then another header"):
        with pytest.raises(ParseError):
            _check_flat_shape(name)


def test_the_indented_comment_check_fails_when_a_comment_is_indentation(monkeypatch: pytest.MonkeyPatch) -> None:
    defect = _flat_check_with(
        'if stripped.startswith("!") and stripped != "!":',
        'if line[0] not in " \\t" and stripped.startswith("!") and stripped != "!":',
    )
    monkeypatch.setattr(eos_parse, "first_flat_stanza", defect)
    with pytest.raises((AssertionError, pytest.fail.Exception)):
        _check_flat_shape("an indented comment between a header and its body")


def test_the_end_check_fails_when_end_is_a_body_line(monkeypatch: pytest.MonkeyPatch) -> None:
    defect = _flat_check_with('not in ("exit", "end")', 'not in ("exit",)')
    monkeypatch.setattr(eos_parse, "first_flat_stanza", defect)
    with pytest.raises(ParseError):
        _check_flat_shape("a header, then end")


def test_the_exit_check_fails_when_exit_is_a_body_line(monkeypatch: pytest.MonkeyPatch) -> None:
    defect = _flat_check_with('not in ("exit", "end")', 'not in ("end",)')
    monkeypatch.setattr(eos_parse, "first_flat_stanza", defect)
    with pytest.raises(ParseError):
        _check_flat_shape("headers, each then exit")


def test_the_no_break_space_checks_fail_when_any_white_space_is_indentation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    defect = _flat_check_with('if line[0] in " \\t":', "if line[0].isspace():")
    monkeypatch.setattr(eos_parse, "first_flat_stanza", defect)
    with pytest.raises((AssertionError, pytest.fail.Exception)):
        _check_flat_shape("a body indented with no-break spaces")
    with pytest.raises((AssertionError, pytest.fail.Exception)):
        _check_no_break_spaces(EVPN_LEAF)


def test_the_bang_check_fails_when_a_bang_is_a_body_line(monkeypatch: pytest.MonkeyPatch) -> None:
    defect = _flat_check_with(' and stripped != "!" and', " and")
    monkeypatch.setattr(eos_parse, "first_flat_stanza", defect)
    with pytest.raises(ParseError):
        _check_no_body()


def test_the_header_check_fails_when_a_header_is_a_body_line(monkeypatch: pytest.MonkeyPatch) -> None:
    defect = _flat_check_with(" and not opens", "")
    monkeypatch.setattr(eos_parse, "first_flat_stanza", defect)
    with pytest.raises(ParseError):
        _check_flat_shape("headers only, no !")


def test_the_reason_check_fails_for_a_sentence_that_speaks_for_the_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        eos_parse, "FLAT_TEXT_MESSAGE", eos_parse.FLAT_TEXT_MESSAGE.replace("this parser", "the switch reads and"),
    )
    with pytest.raises(AssertionError):
        _check_the_reason()


def test_the_tab_checks_fail_when_only_a_space_is_indentation(monkeypatch: pytest.MonkeyPatch) -> None:
    defect = _flat_check_with('if line[0] in " \\t":', 'if line[0] == " ":')
    monkeypatch.setattr(eos_parse, "first_flat_stanza", defect)
    with pytest.raises(ParseError):
        _check_reindented(KITCHEN_SINK)


#: The rows of ``BODIES`` in which a body hides nothing a reader takes:
#: read as lines, they hold what they hold read as text.
_HIDES_NOTHING = {"a certificate printed with one body", "a certificate printed with no body"}


def test_the_body_checks_fail_when_a_body_is_read_as_lines(bodies_read_as_lines: None) -> None:
    for check in (_check_banner_tree, _check_banner_outputs, _check_not_fooled):
        with pytest.raises((AssertionError, pytest.fail.Exception)):
            check()
    assert set(BODIES) > _HIDES_NOTHING
    for name in set(BODIES) - _HIDES_NOTHING:
        with pytest.raises((AssertionError, ParseError)):
            _check_body(name)
    for name in UNENDED:
        with pytest.raises((AssertionError, pytest.fail.Exception)):
            _check_unended(name)


def test_the_tier3_check_fails_when_the_detector_reads_the_banner(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Tier-3 rows are read from the text the parser read."""
    monkeypatch.setattr(eos_codec, "without_bodies", lambda raw: raw)
    with pytest.raises(AssertionError):
        _check_banner_tree()


def test_the_key_check_fails_when_a_certificate_opens_one_body(monkeypatch: pytest.MonkeyPatch) -> None:
    _bodies_by(monkeypatch, _with_a_defect(eos_parse, "without_bodies", "pem_owed = 2", "pem_owed = 1"))
    with pytest.raises(AssertionError):
        _check_body("a certificate and its key")


def test_the_one_body_checks_fail_when_a_certificate_opens_on_any_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """A body opened after ``protocol https certificate`` whatever the
    next line is: a printout with one body, or none, lost its lines (or
    was refused, its key or certificate never ended)."""
    _bodies_by(monkeypatch, _with_a_defect(
        eos_parse, "without_bodies", "if line.strip().startswith(_PEM_BEGINS):", "if True:",
    ))
    for name in ("a certificate printed with one body", "a certificate printed with no body"):
        with pytest.raises((AssertionError, ParseError)):
            _check_body(name)


def test_the_banner_end_check_fails_when_an_indented_eof_ends_a_banner(monkeypatch: pytest.MonkeyPatch) -> None:
    _bodies_by(monkeypatch, _with_a_defect(
        eos_parse, "without_bodies", "ends = _eof_in_column_0", "ends = _eof_stripped",
    ))
    with pytest.raises(AssertionError):
        _check_body("a banner whose text holds an indented EOF")


def test_the_capitals_check_fails_when_an_opener_is_matched_by_its_case(monkeypatch: pytest.MonkeyPatch) -> None:
    pattern = eos_parse._OPENS_A_BODY_RE
    assert pattern.flags & re.IGNORECASE
    monkeypatch.setattr(eos_parse, "_OPENS_A_BODY_RE", re.compile(pattern.pattern))
    with pytest.raises(AssertionError):
        _check_body("a banner opened in capitals")


def test_the_json_banner_check_fails_when_the_shape_is_read_before_the_bodies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    defect = _with_a_defect(
        eos_parse, "parse_intent",
        "raw = without_bodies(raw)\n    shape = detect_input_shape(raw)",
        "shape = detect_input_shape(raw)\n    raw = without_bodies(raw)",
    )
    monkeypatch.setattr(eos_codec, "parse_intent", defect)
    with pytest.raises(ParseError):
        _check_body("a banner whose text begins as JSON does")


def test_the_eof_check_fails_when_eof_is_read_without_its_case(monkeypatch: pytest.MonkeyPatch) -> None:
    defect = _with_a_defect(
        eos_parse, "_eof_in_column_0", 'return line.rstrip() == "EOF"', 'return line.rstrip().upper() == "EOF"',
    )
    monkeypatch.setattr(eos_parse, "_eof_in_column_0", defect)
    with pytest.raises(AssertionError):
        _check_body("a banner login whose body has an eof that is no EOF")


def test_the_unended_check_fails_when_a_body_may_run_to_the_end(monkeypatch: pytest.MonkeyPatch) -> None:
    defect = _with_a_defect(
        eos_parse, "without_bodies",
        "if ends is not None:\n        raise ParseError(", "if False:\n        raise ParseError(",
    )
    _bodies_by(monkeypatch, defect)
    for name in UNENDED:
        with pytest.raises(pytest.fail.Exception):
            _check_unended(name)


def test_the_line_number_check_fails_when_a_body_loses_its_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    defect = _with_a_defect(eos_parse, "without_bodies", "lines[index] = _line_end(line)", 'lines[index] = ""')
    _bodies_by(monkeypatch, defect)
    with pytest.raises(AssertionError):
        _check_not_fooled()


def test_the_uneven_checks_fail_when_a_deeper_line_is_a_submodes(monkeypatch: pytest.MonkeyPatch) -> None:
    """A line deeper than EOS's own three spaces read as a submode's,
    not the interface's: each hand edit loses a line, and the limitation
    pinned beside them moves."""
    defect = _with_a_defect(
        eos_parse, "_parse_stanzas",
        "# Indented = sub-command of the currently-open stanza.\n        if current_iface is not None:",
        "# Indented = sub-command of the currently-open stanza.\n"
        "        if current_iface is not None and _indent(line) <= 3:",
    )
    monkeypatch.setattr(eos_parse, "_parse_stanzas", defect)
    for name in ("an own line a space deeper", "a first line deeper than the rest",
                 "a line the reader takes, typed in a submode"):
        with pytest.raises(AssertionError):
            _check_uneven(name)


def test_the_comment_check_fails_when_a_column_0_comment_ends_the_section(monkeypatch: pytest.MonkeyPatch) -> None:
    defect = _with_a_defect(
        eos_parse, "_parse_router_bgp",
        'if stripped.startswith("!"):\n            # A ``!`` (or a comment) closes nothing, at any depth.',
        'if stripped == "!":\n            # A ``!`` (or a comment) closes nothing, at any depth.',
    )
    monkeypatch.setattr(eos_parse, "_parse_router_bgp", defect)
    with pytest.raises(AssertionError):
        _check_bgp("a column-0 comment between a block's lines")


def test_the_shallowest_check_fails_when_the_first_line_is_the_sections_depth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    defect = _with_a_defect(
        eos_parse, "_section_depths",
        "depths[-1] = min(depths[-1], _indent(raw_line))",
        "depths[-1] = _indent(raw_line) if depths[-1] == sys.maxsize else depths[-1]",
    )
    monkeypatch.setattr(eos_parse, "_section_depths", defect)
    for name in ("the section's first line deeper than the rest", "a line shallower than the section's other lines"):
        with pytest.raises(AssertionError):
            _check_bgp(name)


def test_the_bang_check_fails_when_a_bang_closes_a_block(monkeypatch: pytest.MonkeyPatch) -> None:
    defect = _with_a_defect(
        eos_parse, "_parse_router_bgp",
        "# A ``!`` (or a comment) closes nothing, at any depth.\n            continue",
        "current_ri = None\n            continue",
    )
    monkeypatch.setattr(eos_parse, "_parse_router_bgp", defect)
    with pytest.raises(AssertionError):
        _check_bgp("a vrf's line after its address-family")


def test_the_depth_check_fails_when_a_vrf_opens_at_any_depth(monkeypatch: pytest.MonkeyPatch) -> None:
    defect = _with_a_defect(
        eos_parse, "_parse_router_bgp",
        "if width <= section_indent:", 'if width <= section_indent or stripped.startswith("vrf "):',
    )
    monkeypatch.setattr(eos_parse, "_parse_router_bgp", defect)
    with pytest.raises(AssertionError):
        _check_bgp("a vrf under an address-family")


def test_the_bundle_check_fails_when_a_vlan_opens_at_any_depth(monkeypatch: pytest.MonkeyPatch) -> None:
    defect = _with_a_defect(
        eos_parse, "_parse_router_bgp",
        "if width <= section_indent:", "if width <= section_indent or _VLAN_HEADER_RE.match(stripped):",
    )
    monkeypatch.setattr(eos_parse, "_parse_router_bgp", defect)
    with pytest.raises(AssertionError):
        _check_bgp("a vlan of a bundle, then a vlan block")


def test_the_reindent_check_fails_when_only_spaces_are_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    defect = _with_a_defect(
        eos_parse, "_parse_router_bgp",
        "width = _indent(raw_line)", 'width = len(raw_line) - len(raw_line.lstrip(" "))',
    )
    monkeypatch.setattr(eos_parse, "_parse_router_bgp", defect)
    with pytest.raises(AssertionError):
        _check_reindented(EVPN_LEAF)


def test_the_width_check_fails_at_the_old_widths(monkeypatch: pytest.MonkeyPatch) -> None:
    """The section's depth taken as EOS's own three spaces, as it was."""
    defect = _with_a_defect(
        eos_parse, "_parse_router_bgp", "section_indent = depths[sections]\n", "section_indent = 3\n",
    )
    monkeypatch.setattr(eos_parse, "_parse_router_bgp", defect)
    with pytest.raises(AssertionError):
        _check_reindented(EVPN_LEAF)


def test_the_empty_line_checks_fail_when_an_empty_line_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    stanzas = _with_a_defect(
        eos_parse, "_parse_stanzas",
        "# An empty line is no command: it closes nothing.\n            continue",
        "current_iface = None\n            current_vlan = None\n            continue",
    )
    monkeypatch.setattr(eos_parse, "_parse_stanzas", stanzas)
    with pytest.raises(AssertionError):
        _check_empty_lines()
    with pytest.raises(AssertionError):
        _check_doubled(EVPN_LEAF)
    monkeypatch.undo()
    bgp = _with_a_defect(
        eos_parse, "_parse_router_bgp",
        "# An empty line is no command: it closes nothing.\n            continue",
        "in_bgp = False\n            current_ri = None\n            continue",
    )
    monkeypatch.setattr(eos_parse, "_parse_router_bgp", bgp)
    with pytest.raises(AssertionError):
        _check_bgp("empty lines in a block")
    with pytest.raises(AssertionError):
        _check_doubled(EVPN_LEAF)


def test_the_walk_check_fails_for_a_walk_of_some_directories() -> None:
    def some_directories() -> list[Path]:
        return sorted(
            p for root in ("real", "synthetic", "iosxe", "opnsense") for p in (FIXTURES / root).rglob("*")
            if p.is_file() and p.suffix.lower() not in _NOT_A_CAPTURE
        )
    with pytest.raises(AssertionError):
        _check_the_walk(some_directories)

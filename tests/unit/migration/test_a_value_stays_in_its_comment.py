"""A value of the tree written into a comment stays in the comment.

Two targets write a comment that ends at a terminator rather than at the
end of its line: VyOS (``/* ... */``) and OPNsense (``<!-- ... -->``).
A renderer puts the name of what it left out into such a comment as the
tree holds it, and a name that held the terminator ended the comment.
On OPNsense a source account named ``x--><user>...</user><!--``, whose
password the target refused, became an account the source never had,
and one named ``svc--backup`` failed the render (XML allows no ``--`` in
a comment).  On VyOS ``a*/system{...}/*`` left ``system{...}`` on the
line as configuration.

The output is read by readers of our own, typed here, never by the
target's parser: OPNsense by an XML parser, which refuses ``--`` in a
comment and shows every element; VyOS by a reader of its comment grammar
that ends a comment at its first ``*/``, as the device does.

What this does not reach: a comment built from pieces the source rule
below does not see (a ``join``, a list appended a piece at a time), and
a place a value reaches a comment that no tree here fills.

See also ``netcanon/migration/_comments.py`` and
``tests/unit/migration/test_secret_fail_open.py``.
"""

from __future__ import annotations

import ast
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

import netcanon.migration.codecs  # noqa: F401  (registers the codecs)
from netcanon.migration import _comments
from netcanon.migration._comments import comment, comment_text
from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalLocalUser,
    CanonicalSNMP,
    CanonicalSNMPv3User,
)
from netcanon.migration.codecs.registry import get_codec, list_public_codecs

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[3]

#: How each public codec writes a comment, typed by hand from what its
#: renderer writes.  ``line`` ends at the end of its line; ``block`` at a
#: terminator, and is read below.  The NETCONF codec writes no comment.
_COMMENT_FORMS: dict[str, str] = {
    "arista_eos": "line",
    "aruba_aoscx": "line",
    "aruba_aoss": "line",
    "cisco_iosxe": "none",
    "cisco_iosxe_cli": "line",
    "cisco_iosxr": "line",
    "cisco_nxos": "line",
    "dell_os10": "line",
    "fortigate_cli": "line",
    "juniper_junos": "line",
    "mikrotik_routeros": "line",
    "opnsense": "block",
    "vyos": "block",
}

_BLOCK_TARGETS = sorted(t for t, form in _COMMENT_FORMS.items() if form == "block")

#: Texts that end a comment, or hold what XML forbids in one.
_HOSTILE = (
    "a*/system{host-name{netcanon-injected}}/*",
    "x--><netcanon-injected/><!--",
    "svc--backup",
    "tail-",
    "-->",
    "*/",
    "a---b",
)

#: A secret no target takes (yescrypt), so every target writes a review
#: comment that names the account in place of the account.
_REFUSED_EVERYWHERE = "$y$j9T$" + "y" * 43


def _a_user_named(name: str) -> CanonicalIntent:
    return CanonicalIntent(
        hostname="r1",
        source_vendor="cisco_iosxe_cli",
        local_users=[
            CanonicalLocalUser(name=name, privilege_level=15, hashed_password=_REFUSED_EVERYWHERE),
        ],
    )


def _an_snmpv3_user_named(name: str) -> CanonicalIntent:
    """A USM user from another vendor: its key is localised to the source
    agent, and VyOS writes a review comment that names the user."""
    return CanonicalIntent(
        hostname="r1",
        source_vendor="cisco_iosxe_cli",
        snmp=CanonicalSNMP(
            v3_users=[
                CanonicalSNMPv3User(name=name, auth_protocol="sha", auth_passphrase="0x" + "ab" * 20),
            ],
        ),
    )


_PLACES = {"local user": _a_user_named, "snmpv3 user": _an_snmpv3_user_named}

#: A place still open on this branch, mended by another change.  Whichever
#: of the two merges second takes the pin out: the test fails with "take
#: out its pin" once the place is mended.
_MENDED_ELSEWHERE: dict[tuple[str, str], str] = {}


def _outside_quotes(line: str, needle: str) -> int:
    """Where *needle* first stands outside a ``"..."`` value, or -1."""
    quoted = False
    for i, ch in enumerate(line):
        if ch == '"':
            quoted = not quoted
        elif not quoted and line.startswith(needle, i):
            return i
    return -1


def _vyos_defects(out: str) -> list[str]:
    """Each line whose ``/* */`` comment ends before the line does, or
    does not end on it."""
    found = []
    for line in out.splitlines():
        start = _outside_quotes(line, "/*")
        if start < 0:
            continue
        end = line.find("*/", start + 2)
        if end < 0 or line[end + 2:].strip():
            found.append(line.strip())
    return found


def _xml_with_comments(text: str) -> ET.Element:
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    return ET.fromstring(text, parser=parser)


def _opnsense_defects(out: str) -> list[str]:
    """What the output holds that no renderer meant: a document that is
    not XML, or an element that came out of a value."""
    try:
        root = _xml_with_comments(out)
    except ET.ParseError as exc:
        return [f"not well-formed: {exc}"]
    return [f"<{el.tag}>" for el in root.iter() if el.tag == "netcanon-injected"]


_READERS = {"opnsense": _opnsense_defects, "vyos": _vyos_defects}


def _findings(target: str, place: str, name: str) -> list[str]:
    try:
        out = get_codec(target).render(_PLACES[place](name))
    except Exception as exc:  # a render that fails is a finding
        return [f"render raised {type(exc).__name__}: {exc}"]
    return _READERS[target](out)


def test_every_public_codec_has_a_comment_form() -> None:
    assert set(_COMMENT_FORMS) == set(list_public_codecs())


@pytest.mark.parametrize("text", _HOSTILE)
def test_a_text_cannot_end_a_slash_comment(text: str) -> None:
    line = comment(text, "slash")
    assert line.startswith("/* ")
    assert line.find("*/") == len(line) - 2, line


@pytest.mark.parametrize("text", _HOSTILE)
def test_a_text_cannot_end_an_xml_comment(text: str) -> None:
    """Delimited by the helper, and as the text of an ``ET.Comment``,
    which ElementTree writes as it stands."""
    holder = ET.Element("r")
    holder.append(ET.Comment(comment_text(text, "xml")))
    for document in (f"<r>{comment(text, 'xml')}</r>", ET.tostring(holder, encoding="unicode")):
        root = _xml_with_comments(document)
        assert [child.tag for child in root] == [ET.Comment], document


@pytest.mark.parametrize("syntax", ["hash", "semicolon", "exclamation", "plain"])
def test_a_comment_that_ends_with_its_line_is_left_as_it_is(syntax: str) -> None:
    for text in _HOSTILE:
        assert comment_text(text, syntax) == text


@pytest.mark.parametrize("place", sorted(_PLACES))
@pytest.mark.parametrize("target", _BLOCK_TARGETS)
@pytest.mark.parametrize("name", _HOSTILE)
def test_a_name_stays_in_its_comment(target: str, place: str, name: str) -> None:
    found = _findings(target, place, name)
    pin = _MENDED_ELSEWHERE.get((target, place))
    if pin is None:
        assert found == [], found
    elif "*/" in name:
        # The defect the pin is for: still there, until the other change.
        assert found, f"{target} {place} is mended: take out its pin ({pin})"


def test_the_check_sees_the_old_comment(monkeypatch) -> None:
    """With the text written as it stands, as before, the check fails on
    both targets: OPNsense on an element and on a render that raised,
    VyOS on a comment that ended early."""
    monkeypatch.setattr(_comments, "comment_text", lambda text, syntax: text)
    assert _findings("opnsense", "local user", "x--><netcanon-injected/><!--") == ["<netcanon-injected>"]
    assert _findings("opnsense", "local user", "svc--backup")[0].startswith("render raised")
    assert _findings("vyos", "local user", "a*/system{host-name{netcanon-injected}}/*")


# ---------------------------------------------------------------------------
# The source: where a comment is built around a value
# ---------------------------------------------------------------------------

_OPENERS = ("/*", "<!--")

#: Each place in the migration package that builds a block comment around
#: a value without :mod:`netcanon.migration._comments`, with why it may.
#: Compared for equality: a new place fails until it is here or mended.
_BUILT_ELSEWHERE: dict[tuple[str, str], str] = {
    ("netcanon/migration/codecs/opnsense/render.py", "render_canonical"): (
        "an ET.Comment whose text is format_review_comment(..., 'xml'), "
        "which is built by _comments"
    ),
}


def _owner(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    """The function *node* is in, or ``<module>``."""
    while node in parents:
        node = parents[node]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node.name
    return "<module>"


def _places_that_build_a_comment() -> set[tuple[str, str]]:
    """``(module, function)`` for each f-string, ``+`` or ``%`` and
    ``.format`` that puts a value beside a comment opener, and each
    ``Comment(...)`` node."""
    found: set[tuple[str, str]] = set()
    for path in sorted((_REPO / "netcanon" / "migration").rglob("*.py")):
        if path.name == "_comments.py":
            continue
        module = ast.parse(path.read_text(encoding="utf-8"))
        parents = {child: node for node in ast.walk(module) for child in ast.iter_child_nodes(node)}
        where = path.relative_to(_REPO).as_posix()
        for node in ast.walk(module):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                if name == "Comment":
                    found.add((where, _owner(node, parents)))
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if not any(opener in node.value for opener in _OPENERS):
                continue
            parent = parents.get(node)
            if (
                (isinstance(parent, ast.JoinedStr)
                 and any(isinstance(v, ast.FormattedValue) for v in parent.values))
                or isinstance(parent, ast.BinOp)
                or (isinstance(parent, ast.Attribute) and parent.attr == "format")
            ):
                found.add((where, _owner(node, parents)))
    return found


def test_a_comment_is_built_around_a_value_only_by_the_helper() -> None:
    assert _places_that_build_a_comment() == set(_BUILT_ELSEWHERE)

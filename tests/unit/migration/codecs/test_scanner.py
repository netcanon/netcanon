"""Unit tests for the shared ``codecs/_scanner.scan_stanzas`` helper.

Exercises the loop skeleton in isolation with a tiny synthetic grammar
(``item <name>`` headers + indented ``attr <x>`` lines) so the control flow
is pinned independently of any codec: open/accumulate/close-on-terminator,
close-on-dedent, end-of-input flush, pre-header skipping, and a custom
terminator.  And the shared flat check (``first_flat_stanza``) on the same
grammar: which line of a text with no indentation opens a stanza whose
body is at the margin.  And the shared body pass (``without_text_bodies``):
a body's lines emptied, each keeping its number, the lines cut where
``str.splitlines`` cuts them, and a body with no end, or a line of one
that ends in another character than a line feed, refused at its line.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from netcanon.migration.codecs import _scanner
from netcanon.migration.codecs._scanner import (
    LINE_END_MESSAGE,
    Body,
    _default_terminator,
    _lines,
    ends_anywhere,
    first_flat_stanza,
    scan_stanzas,
    without_text_bodies,
)
from netcanon.migration.codecs.base import ParseError

_HEADER = re.compile(r"^item (\w+)")


def _open(m: re.Match[str]) -> dict:
    return {"name": m.group(1), "attrs": []}


def _on_line(line: str, scratch: dict) -> None:
    stripped = line.strip()
    if stripped.startswith("attr "):
        scratch["attrs"].append(stripped.split(None, 1)[1])


def _build(scratch: dict) -> tuple[str, tuple[str, ...]]:
    return (scratch["name"], tuple(scratch["attrs"]))


def _scan(text: str, **kw) -> list[tuple[str, tuple[str, ...]]]:
    return scan_stanzas(
        text.splitlines(),
        is_header=_HEADER.match,
        open_scratch=_open,
        on_line=_on_line,
        build=_build,
        **kw,
    )


@pytest.mark.unit
def test_two_stanzas_closed_by_bang() -> None:
    text = "item a\n  attr x\n  attr y\n!\nitem b\n  attr z\n!\n"
    assert _scan(text) == [("a", ("x", "y")), ("b", ("z",))]


@pytest.mark.unit
def test_close_on_dedent_without_bang() -> None:
    # A non-indented, non-header line closes the open stanza.
    text = "item a\n  attr x\nunrelated top-level\nitem b\n  attr y\n"
    assert _scan(text) == [("a", ("x",)), ("b", ("y",))]


@pytest.mark.unit
def test_flush_at_end_of_input() -> None:
    # Last stanza has no trailing terminator; the final flush still emits it.
    assert _scan("item a\n  attr x\n") == [("a", ("x",))]


@pytest.mark.unit
def test_lines_before_first_header_are_skipped() -> None:
    assert _scan("junk\n  more junk\nitem a\n  attr x\n!\n") == [("a", ("x",))]


@pytest.mark.unit
def test_empty_input() -> None:
    assert _scan("") == []


@pytest.mark.unit
def test_custom_terminator() -> None:
    text = "item a\n  attr x\nEND\nitem b\n  attr y\n"
    out = _scan(text, is_terminator=lambda ln: "END" in ln)
    assert out == [("a", ("x",)), ("b", ("y",))]


@pytest.mark.unit
def test_default_terminator_rules() -> None:
    assert _default_terminator("!") is True
    # An indented ``!`` closes a SUBMODE inside the stanza (IOS XR
    # ``ptp`` under an interface), not the stanza: the stanza's own
    # lines go on after it.
    assert _default_terminator("   !  ") is False
    assert _default_terminator(" !") is False
    assert _default_terminator("interface Gi0/0") is True  # column-0 dedent
    assert _default_terminator("  description x") is False  # indented body
    assert _default_terminator("") is False                # blank line falls through


@pytest.mark.unit
def test_a_submodes_bang_does_not_close_the_stanza() -> None:
    text = "item a\n  attr x\n  sub\n    deep\n  !\n  attr y\n!\nitem b\n  attr z\n!\n"
    assert _scan(text) == [("a", ("x", "y")), ("b", ("z",))]


#: Texts of the tiny grammar, typed by hand, and the line the flat check
#: names (None: the text has indentation, or no stanza's body is at the
#: margin).
FLAT = {
    "a body at the margin": ("item a\nattr x\n", 1),
    "the second stanza's body at the margin": ("item a\n!\nitem b\nattr x\n", 3),
    "an indented line anywhere": ("item a\nattr x\nitem b\n  attr y\n", None),
    "a tab is indentation": ("item a\nattr x\n\tattr y\n", None),
    "a no-break space is no indentation": ("item a\n\u00a0attr x\nitem b\n\u00a0\u00a0attr y\n", 1),
    "an indented bare ! is indentation": ("item a\nattr x\n  !\n", None),
    "a comment between a header and its body": ("item a\n!! note\nattr x\n", 1),
    "an indented comment is no indentation": ("item a\n  !! note\nattr x\n", 1),
    "a comment, then a !": ("item a\n! note\n!\n", None),
    "a header, then end": ("item a\nEND\n", None),
    "a header, then exit": ("item a\nexit\nitem b\nExit\n", None),
    "headers only": ("item a\nitem b\n", None),
    "blank lines are passed over": ("\nitem a\n\n\nattr x\n", 2),
    "no header at all": ("attr x\nattr y\n", None),
}


@pytest.mark.unit
@pytest.mark.parametrize("name", list(FLAT))
def test_the_flat_check_names_the_first_flat_stanza(name: str) -> None:
    text, at = FLAT[name]
    assert first_flat_stanza(text, (_HEADER,)) == at


@pytest.mark.unit
def test_the_flat_check_asks_the_headers_it_is_given() -> None:
    """The caller's tuple is read at the call: no header, no stanza."""
    assert first_flat_stanza("item a\nattr x\n", ()) is None
    assert first_flat_stanza("item a\nattr x\n", (re.compile(r"other"), _HEADER)) == 1


# The shared body pass, on a grammar of its own: ``text <c>`` opens a
# body that ends at the next line holding ``<c>``, or on its own line
# when ``<c>`` is there twice.
_UNENDED = "line {line} opens a text with no end"


def _opens(text: str, number: int) -> Body | None:
    if not text.startswith("text "):
        return None
    mark = text[5]
    return Body(ends_anywhere(mark), ended=mark in text[6:])


def _without_bodies(raw: str) -> str:
    return without_text_bodies(raw, _opens, _UNENDED, codec="test")


@pytest.mark.unit
def test_a_body_is_emptied_and_every_line_keeps_its_number() -> None:
    raw = "item a\r\ntext %\r\nitem b\r\nend%\r\nitem c\r\ntext %one line%\r\nitem d"
    assert _without_bodies(raw) == "item a\r\n\r\n\r\n\r\nitem c\r\n\r\nitem d"


@pytest.mark.unit
def test_a_body_on_the_last_line_with_no_line_end() -> None:
    assert _without_bodies("item a\ntext %\nend%") == "item a\n\n"
    assert _without_bodies("text %one%") == ""
    assert _without_bodies("text %\n\nend%\n") == "\n\n\n"


@pytest.mark.unit
def test_a_text_with_no_body_is_returned_as_it_is() -> None:
    for raw in ("item a\nattr x\n", "", "item a\r\nitem b"):
        assert _without_bodies(raw) is raw


@pytest.mark.unit
def test_a_body_with_no_end_is_refused_at_the_line_that_opens_it() -> None:
    with pytest.raises(ParseError) as caught:
        _without_bodies("item a\ntext %\nitem b\n")
    assert (str(caught.value), caught.value.path, caught.value.snippet) == (
        "line 2 opens a text with no end", "line 2", "",
    )


#: Texts cut at every place ``str.splitlines`` cuts one.
_CUT_TEXTS = (
    "", "\n", "\r\n", "\r", "a", "a\n", "a\nb", "a\r\nb\r\n", "a\rb\r", "a\n\rb", "a\r\r\nb", "\r\n\r\n\n",
    "a\x0bb\x0cc\x1cd\x1de\x1ef\x85g\u2028h\u2029i", "\x0c", "a\x0c\n", "a\u2028\r\nb",
)


def _check_the_cut(raw: str) -> None:
    cut = list(_lines(raw))
    assert [raw[start:end] for start, _, end in cut] == raw.splitlines(keepends=True), repr(raw)
    assert [raw[start:stop] for start, stop, _ in cut] == raw.splitlines(), repr(raw)


@pytest.mark.unit
def test_the_lines_are_cut_where_splitlines_cuts_them() -> None:
    """Where the walk cuts a line, every parser's own loop cuts it: a
    line's number is the same in both."""
    for raw in _CUT_TEXTS:
        _check_the_cut(raw)
    fixtures = Path(__file__).resolve().parents[3] / "fixtures"
    walked = 0
    for path in sorted(fixtures.rglob("*")):
        if path.is_file() and path.suffix.lower() in (".txt", ".cfg", ".conf", ".rsc", ".xml", ".set"):
            _check_the_cut(path.read_text(encoding="utf-8", errors="replace"))
            walked += 1
    assert walked > 100


@pytest.mark.unit
@pytest.mark.parametrize("end", ["\r", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"])
def test_a_line_of_a_body_that_ends_where_a_device_does_not_is_refused(end: str) -> None:
    """A device ends a line at a line feed: a line of a body that ends
    in another of the characters ``str.splitlines`` ends a line at is,
    to the device, one line with the next.  Refused in the line that
    opens the body, a line in it, and the line that ends it."""
    for raw, line in (
        (f"item a\ntext %{end}item b\nend%\n", 2),
        (f"item a\ntext %\nx{end}%\nitem b\nend%\n", 3),
        (f"item a\ntext %\nend%{end}item b\n", 3),
        (f"text %one%{end}item b\n", 1),
    ):
        with pytest.raises(ParseError) as caught:
            _without_bodies(raw)
        assert (str(caught.value), caught.value.path, caught.value.snippet) == (
            LINE_END_MESSAGE.format(codec="test", line=line, command="show running-config"), f"line {line}", "",
        )
    # Outside a body, a line end is the parser's own.
    raw = f"item a{end}item b\n"
    assert _without_bodies(raw) is raw


@pytest.mark.unit
def test_the_cut_check_fails_when_only_a_line_feed_ends_a_line(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_scanner, "_LINE_ENDS_RE", re.compile("\n"))
    with pytest.raises(AssertionError):
        for raw in _CUT_TEXTS:
            _check_the_cut(raw)

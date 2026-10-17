"""Unit tests for the shared ``codecs/_scanner.scan_stanzas`` helper.

Exercises the loop skeleton in isolation with a tiny synthetic grammar
(``item <name>`` headers + indented ``attr <x>`` lines) so the control flow
is pinned independently of any codec: open/accumulate/close-on-terminator,
close-on-dedent, end-of-input flush, pre-header skipping, and a custom
terminator.  And the shared flat check (``first_flat_stanza``) on the same
grammar: which line of a text with no indentation opens a stanza whose
body is at the margin.
"""

from __future__ import annotations

import re

import pytest

from netcanon.migration.codecs._scanner import _default_terminator, first_flat_stanza, scan_stanzas

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

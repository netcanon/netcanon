"""Unit tests for the shared ``codecs/_scanner.scan_stanzas`` helper.

Exercises the loop skeleton in isolation with a tiny synthetic grammar
(``item <name>`` headers + indented ``attr <x>`` lines) so the control flow
is pinned independently of any codec: open/accumulate/close-on-terminator,
close-on-dedent, end-of-input flush, pre-header skipping, and a custom
terminator.
"""

from __future__ import annotations

import re

import pytest

from netcanon.migration.codecs._scanner import _default_terminator, scan_stanzas

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
    assert _default_terminator("   !  ") is True          # stripped bang
    assert _default_terminator("interface Gi0/0") is True  # column-0 dedent
    assert _default_terminator("  description x") is False  # indented body
    assert _default_terminator("") is False                # blank line falls through

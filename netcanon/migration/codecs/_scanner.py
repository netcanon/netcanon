"""Composable stanza-scan helper for the line-scan (CLI) codecs.

Several codecs hand-roll the same control-flow skeleton: a *header* line
opens a scratch accumulator, subsequent indented lines feed a per-attribute
handler cascade, and a ``!`` or column-0 (dedented) line closes the stanza
and materialises a canonical record.  :func:`scan_stanzas` factors out ONLY
that loop; the vendor grammar — header regex, attribute cascade, scratch
shape, and build step — stays in the codec via callables.  The scanner
carries zero canonical-model knowledge, so the records it produces are
identical to the hand-rolled loop it replaces.

This is an OPT-IN utility, not a base class.  Codecs whose grammar does not
fit the flat open/accumulate/close shape (brace-stack ``vyos``, XML
``opnsense`` / ``cisco_iosxe``-NETCONF, set-form ``juniper_junos``, or the
nested sub-blocks like NX-OS HSRP) keep their bespoke loop.

Import as ``from .._scanner import scan_stanzas`` from inside a codec package.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import TypeVar

_Scratch = TypeVar("_Scratch")
_Result = TypeVar("_Result")


def _default_terminator(line: str) -> bool:
    """Close a stanza on a bare ``!`` or any non-indented (column-0) line.

    Replicates the de-facto rule the CLI codecs hand-roll verbatim:
    ``line.strip() == "!" or (line and not line[0].isspace())``.
    """
    return line.strip() == "!" or bool(line and not line[0].isspace())


def scan_stanzas(
    lines: Iterable[str],
    *,
    is_header: Callable[[str], re.Match[str] | None],
    open_scratch: Callable[[re.Match[str]], _Scratch],
    on_line: Callable[[str, _Scratch], None],
    build: Callable[[_Scratch], _Result],
    is_terminator: Callable[[str], bool] = _default_terminator,
) -> list[_Result]:
    """Drive the open/accumulate/close-on-terminator stanza loop.

    For each line, in this order:

    1. If ``is_header`` matches, flush any open stanza, then open a fresh
       scratch via ``open_scratch(match)``.
    2. Else if no stanza is open, skip the line.
    3. Else if ``is_terminator`` says so, flush the open stanza.
    4. Otherwise feed the line to ``on_line(line, scratch)`` to mutate the
       current scratch in place.

    A final flush closes the last stanza if the input ends without a
    terminator.  ``build(scratch)`` turns each completed scratch into a
    result; results are returned in input (stanza) order — the scanner never
    sorts.
    """
    results: list[_Result] = []
    current: _Scratch | None = None

    def _flush() -> None:
        nonlocal current
        if current is not None:
            results.append(build(current))
            current = None

    for line in lines:
        match = is_header(line)
        if match is not None:
            _flush()
            current = open_scratch(match)
            continue
        if current is None:
            continue
        if is_terminator(line):
            _flush()
            continue
        on_line(line, current)

    _flush()
    return results

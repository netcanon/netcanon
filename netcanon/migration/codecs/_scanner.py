"""Composable stanza-scan helper for the line-scan (CLI) codecs.

Several codecs hand-roll the same control-flow skeleton: a *header* line
opens a scratch accumulator, subsequent indented lines feed a per-attribute
handler cascade, and a column-0 line (a ``!`` in column 0 among them)
closes the stanza and materialises a canonical record.
:func:`scan_stanzas` factors out ONLY that loop; the vendor grammar —
header regex, attribute cascade, scratch shape, and build step — stays
in the codec via callables.  The scanner
carries zero canonical-model knowledge, so the records it produces are
identical to the hand-rolled loop it replaces.

This is an OPT-IN utility, not a base class.  Codecs whose grammar does not
fit the flat open/accumulate/close shape (brace-stack ``vyos``, XML
``opnsense`` / ``cisco_iosxe``-NETCONF, set-form ``juniper_junos``, or the
nested sub-blocks like NX-OS HSRP) keep their bespoke loop.

:func:`first_flat_stanza` is the other half of a parser that reads its
stanzas by their indentation: it finds a text that has none, which such
a parser cannot read (each parser says why, and refuses it in words).

Import as ``from .._scanner import scan_stanzas`` from inside a codec package.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from typing import TypeVar

from ..limits import ticked

_Scratch = TypeVar("_Scratch")
_Result = TypeVar("_Result")


def _default_terminator(line: str) -> bool:
    """Close a stanza on a line in column 0 (its closing ``!`` is one).

    An INDENTED ``!`` does not close it.  Inside a stanza, a submode
    (IOS XR ``ptp`` / ``lldp`` under an ``interface``, an OS10 VRRP
    group under an SVI) is closed by a ``!`` at the submode's own depth,
    one level in, and the stanza's own lines go on after it: a rule that
    closed the stanza at that ``!`` dropped every line after the
    submode.  The stanza's own ``!`` is printed in column 0, so the one
    rule covers both.  What a submode's own lines are is the codec's to
    say (the scanner hands every line in the stanza to ``on_line``).
    """
    return bool(line) and not line[0].isspace()


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

    for line in ticked(lines):
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


def first_flat_stanza(raw: str, headers: Sequence[re.Pattern[str]]) -> int | None:
    """The line that opens the first stanza whose body stands at the
    left margin of a text with no indentation, or ``None``.

    *headers* are the patterns of the stanzas the caller reads, each
    matched against a whole line; the caller passes its own at the call,
    so that a test that changes the caller's tuple changes what is
    asked.  A text is this shape when no line of it but a comment is
    indented and a line that opens a stanza is followed by a line that
    opens none and is no ``!``, no ``exit`` and no ``end``: that line
    is the stanza's body, at the margin.

    * Indentation is a space or a tab.  Any other white space in front
      of a line (a no-break space, as a paste out of a web page can
      carry) is none: readers of the parsers that call this take such
      a line for one at the margin (the EOS stanza readers, the IOS XR
      ``ntp`` reader), so a text indented with it is not read whole.
    * Blank lines are passed over.
    * A comment (a line that begins with ``!`` and is more than ``!``,
      such as ``!!`` or ``! text``) is passed over at any depth: it
      belongs to the line after it, and it is never indentation -- an
      indented comment does not make a text whose stanza bodies are at
      the margin a text with indentation.
    * A bare ``!`` is the end of a stanza as a device prints it,
      ``exit`` the end of a mode, and ``end`` the end of the config;
      none of them is a body line.
    * A text with SOME lines indented is not this shape (``None``): it
      is read by its indentation.  The answer is ``None`` as soon as an
      indented line is met.

    Line numbers are counted as ``str.splitlines`` counts them, from 1.
    """
    flat_at: int | None = None
    waiting: int | None = None
    for number, line in enumerate(ticked(raw.splitlines()), 1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("!") and stripped != "!":
            # A comment belongs to the line after it, at any depth.
            continue
        if line[0] in " \t":
            return None
        opens = any(header.match(line) for header in headers)
        if (
            waiting is not None and flat_at is None and not opens
            and stripped != "!" and stripped.lower() not in ("exit", "end")
        ):
            flat_at = waiting
        waiting = number if opens else None
    return flat_at

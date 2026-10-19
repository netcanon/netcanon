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

:func:`without_text_bodies` empties the lines of every body of text in
a config -- a banner, a macro -- before any reader of the parse sees
them, and refuses a line of a body that ends where a device would not
end it: the loop is shared, and where a body opens and ends is each
parser's own, from its vendor (:func:`ends_anywhere` is one such rule).

Import as ``from .._scanner import scan_stanzas`` from inside a codec package.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator, Sequence
from typing import NamedTuple, TypeVar

from ..limits import ticked
from .base import ParseError

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


class Body(NamedTuple):
    """A body of text that a line opens (:func:`without_text_bodies`).

    ``ends(text, number)`` is asked of each later line -- its text
    without its line end, and its number from 1 -- and says whether the
    body ends WITH that line.  ``ended`` is ``True`` when the body ends
    on the line that opens it (``banner motd ^Ctext^C``): ``ends`` is
    then asked of no line.  What may raise :class:`.base.ParseError` is
    the parser's: its ``opens``, which makes the ``Body``, and the
    body's ``ends``, each for a line whose end cannot be told from the
    text.  The message names the line and quotes nothing of it.
    """

    ends: Callable[[str, int], bool]
    ended: bool = False


def ends_anywhere(delimiter: str) -> Callable[[str, int], bool]:
    """``Body.ends`` of a body that ends at the next occurrence of
    *delimiter*, anywhere in a line, compared by its case.  The whole
    of that line is the body's: what follows the delimiter on it is
    discarded by the devices whose rule this is (IOS, NX-OS, and AOS-S
    for a banner as it is typed)."""

    def ends(text: str, number: int) -> bool:
        return delimiter in text

    return ends


#: Where ``str.splitlines`` ends a line: the cut every parser's own loop
#: makes, so that a line's number here is its number there.
_LINE_ENDS_RE = re.compile(r"\r\n|[\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029]")
#: What a line of a body may end with: a device ends a line at a line
#: feed (printed ``\r\n`` too), and the last line of a text may have no
#: end.  Indexed by its length: the walk keeps the end of a line it
#: empties, and nothing else of it.
_DEVICE_LINE_ENDS = ("", "\n", "\r\n")

#: Said of a line of a body that ends in another of the characters
#: ``str.splitlines`` ends a line at.  It quotes nothing of the text.
LINE_END_MESSAGE = (
    "{codec}: line {line} is a line of a banner, or of another block of "
    "text, and ends in a character other than a line feed that this "
    "parser takes for the end of a line (a form feed, a vertical tab, a "
    "carriage return on its own, or another of the kind), which the "
    "device need not: where the block ends, and where the configuration "
    "goes on, cannot be told.  Paste the output of `{command}` whole, as "
    "the device prints it."
)


def _lines(raw: str) -> Iterator[tuple[int, int, int]]:
    """Each line of *raw*, one at a time, as ``(start, end of its text,
    end of its line end)``: cut where ``str.splitlines`` cuts it, and
    with no list of the lines made."""
    start = 0
    for match in _LINE_ENDS_RE.finditer(raw):
        yield start, match.start(), match.end()
        start = match.end()
    if start < len(raw):
        yield start, len(raw), len(raw)


def _ends_as_a_device_ends(
    raw: str, stop: int, end: int, number: int, codec: str, command: str,
) -> None:
    """Refuse the line of a body numbered *number* when it ends in
    another character than a line feed (:data:`LINE_END_MESSAGE`)."""
    if raw[stop:end] not in _DEVICE_LINE_ENDS:
        raise ParseError(
            LINE_END_MESSAGE.format(codec=codec, line=number, command=command),
            path=f"line {number}", snippet="",
        )


def without_text_bodies(
    raw: str,
    opens: Callable[[str, int], Body | None],
    unended: str,
    *,
    codec: str,
    command: str = "show running-config",
) -> str:
    """*raw* with every line of each body of text made empty.

    A banner is text the device shows, not configuration: read as lines
    of the config, a banner's words were accounts, VLANs, routes and
    interfaces.  ``opens(text, number)`` is asked of each line outside a
    body (its text without its line end, its number from 1, as
    ``str.splitlines`` counts) and returns ``None`` or the :class:`Body`
    it opens; inside one, the body's ``ends`` is asked of each later
    line.  Every line of a body -- the line that opens it and the line
    that ends it included, whatever else they hold -- is left as its
    line end only, so every line keeps its number.  The text is walked a
    line at a time, and copied only when a line is emptied: a text with
    no body is returned as it is (the same object).

    A line that opens, is in or ends a body, and ends in another of the
    characters ``str.splitlines`` ends a line at (a form feed, a vertical
    tab, a carriage return on its own ...), is refused: a device ends a
    line at a line feed, so where it ends that body, and so where its
    configuration goes on, is not where the lines cut here say.

    Where a body opens and ends is each parser's own, from its vendor:
    a delimiter anywhere (:func:`ends_anywhere`), a line that ends with
    the delimiter or is the delimiter alone, an unescaped quote, a line
    that is ``@``.  The EOS parser has a loop of its own
    (``arista_eos.parse.without_bodies``), which refuses the same line
    ends: a certificate there opens its body on a LATER line than the
    one that names it, and leaves the naming line as it is, and its
    tests put defects back into that loop's own source.

    Args:
        raw: The configuration text.
        opens: The parser's openers (see above).
        unended: Said of a body that is still open at the end of the
            text, with ``{line}`` for the number of the line that opened
            it.  It quotes nothing of the text: a parse failure is
            logged.
        codec: The parser's name, which begins the sentence for a line
            end (:data:`LINE_END_MESSAGE`).
        command: What prints the device's configuration, which that
            sentence asks for.

    Raises:
        ParseError: A body is still open at the end of the text (the
            message is *unended*); a line of a body ends in another
            character than a line feed; or *opens* or a body's ``ends``
            refused a line.
    """
    # Inside a body: how its last line is told (None: in no body).
    ends: Callable[[str, int], bool] | None = None
    opened_at = 0
    # The text as it is to be, in pieces, once a line is emptied; none
    # while no line is.  ``raw[kept:]`` is not yet among them.
    pieces: list[str] = []
    kept = 0
    for number, (start, stop, end) in enumerate(ticked(_lines(raw)), 1):
        text = raw[start:stop]
        if ends is None:
            body = opens(text, number)
            if body is None:
                continue
            opened_at = number
            _ends_as_a_device_ends(raw, stop, end, number, codec, command)
            if not body.ended:
                ends = body.ends
        else:
            _ends_as_a_device_ends(raw, stop, end, number, codec, command)
            if ends(text, number):
                ends = None
        # The line goes and its line end stays.
        if start > kept:
            pieces.append(raw[kept:start])
        pieces.append(_DEVICE_LINE_ENDS[end - stop])
        kept = end
    if ends is not None:
        raise ParseError(
            unended.format(line=opened_at),
            path=f"line {opened_at}", snippet="",
        )
    if not pieces:
        return raw
    pieces.append(raw[kept:])
    return "".join(pieces)

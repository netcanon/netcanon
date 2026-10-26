"""A run of more digits than a number is read from is refused, in words.

Python converts a string of digits to an ``int`` only up to a limit
(``sys.get_int_max_str_digits()``: 4,300 digits unless the server sets
another), and raises ``ValueError`` past it.  Every parser reads numbers
from the runs of digits its patterns take -- a port's number, a VLAN id,
a prefix length, a unit -- so a config that held a run of 4,400 digits
failed the parse of seven of the public codecs (on one capture of each),
at some two dozen places, each as ``unexpected error in stage parsing``
followed by the interpreter's own advice, ``use
sys.set_int_max_str_digits()``: words
about the server, not the config, and advice no operator can take.  The
renderers read numbers from names the same way (to sort ports, to find a
unit), so an entry of a port map whose target held such a run failed
seven of the targets at render.  Nothing was written wrong; the job
failed, and said why in words that were not its own.

The rule is one for every codec, at the two boundaries every caller
crosses (:class:`~netcanon.migration.codecs.base.CodecBase`):

* ``parse`` refuses a text that holds such a run
  (:func:`first_long_run_line`), with a ``ParseError`` that names the
  line and quotes nothing of it -- a parse failure is logged;
* ``render`` refuses a tree whose value holds one
  (:func:`first_long_run`), naming the field: an operator's map puts
  values into the tree too.

A run is what :func:`int` counts as digits: decimal digits of any script
(``\\d``), which is also what a parser's ``\\d+`` takes.  The limit is
read when the check is made, so a server that sets another is held to
its own, and one that sets none (0) refuses nothing.  No committed input
holds a run of even a hundred digits, and a test reads them all.
"""

from __future__ import annotations

import re
import sys
from typing import Any

from ._one_line import LINE_BREAKS, _Walk
from .limits import ticked

#: A run of digits at least as long as the lowest limit Python allows
#: (``sys.int_info.str_digits_check_threshold``, 640) and one more; a
#: shorter run is read under any limit.  Found from its first digit
#: only (the look-behind), so a text is read once, a run at a time.
_A_LONG_RUN = re.compile(r"(?<!\d)\d{641,}")


def _limit() -> int:
    """How many digits a number may be read from; 0 for no limit."""
    return sys.get_int_max_str_digits()


def _too_long(text: str) -> re.Match[str] | None:
    """The first run of digits in *text* that is longer than a number
    is read from, or ``None``."""
    limit = _limit()
    if not limit:
        return None
    for match in ticked(_A_LONG_RUN.finditer(text)):
        if match.end() - match.start() > limit:
            return match
    return None


def _line_of(text: str, at: int) -> int:
    """The line of *text* that character *at* is on, counted as
    :meth:`str.splitlines` counts lines, from 1."""
    before = text[:at].splitlines(keepends=True)
    if not before:
        return 1
    last = before[-1]
    return len(before) + (1 if last.rstrip(LINE_BREAKS) != last else 0)


def first_long_run_line(text: str) -> int | None:
    """The line of *text* that holds the first run of more digits than
    a number is read from, or ``None``."""
    match = _too_long(text)
    return None if match is None else _line_of(text, match.start())


def first_long_run(tree: Any) -> str | None:
    """The first place in *tree* whose value holds a run of more digits
    than a number is read from, by field and not by record
    (``interfaces[].name``: it is said in an error, and an error is
    logged, so it names nothing of the config), or ``None``."""
    if not _limit():
        return None
    walk = _Walk(mend=False, named=False, first=True, found_in=_too_long)
    walk.value(tree, "")
    return walk.found[0] if walk.found else None


def parse_refused(codec: str, line: int) -> str:
    """What ``parse`` says of a text :func:`first_long_run_line` found
    a run in.  It quotes nothing of the text."""
    return (
        f"{codec}: line {line} holds a run of more than {_limit():,} "
        "digits, more than a number is read from, so the text is not "
        "read"
    )


def render_refused(codec: str, where: str) -> str:
    """What ``render`` says of a tree :func:`first_long_run` found a
    run in."""
    return (
        f"{codec}: a value of the tree ({where}) holds a run of more than "
        f"{_limit():,} digits, more than a number is read from, so no "
        "output is written"
    )

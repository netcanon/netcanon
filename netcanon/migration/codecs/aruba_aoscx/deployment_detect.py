"""
What device an AOS-CX configuration says it came from.

A CX 6200's or CX 6300's ``show running-config`` states the part number
of each member of its VSF stack in a block of its own::

    vsf member 1
        type jl661a
        link 1 1/1/49
    vsf member 2
        type jl662a

HPE's VSF guide for the 6200 and 6300 (AOS-CX 10.18) prints both forms
of the block, with an ``exit`` after each and without, and calls the
``type`` value "The part number of the member being provisioned".  A
switch that is alone is member 1 of a stack of one and prints the block
too: "If the switch is not a member of a VSF stack, then member is 1"
(the same guide), and Aruba's own onboarding template for a standalone
JL728A has ``vsf member 1`` and ``type jl728a``.

This module reads those blocks and nothing else.  It does not decide
what the part numbers ARE -- that is the model registry's job
(:func:`netcanon.migration.deployment_detect.propose_deployment`) -- so
it has no table of models to fall out of date.

What a reader of the result must know, each of which the detection says
in its notes:

* a ``type`` line shows the part number a member is PROVISIONED as;
  the line does not show that the switch is in the stack.

The notes also say where two lines state one member differently and
which was used, how many lines set out to open a member's block
(``vsf member <something>``) and could not be read as one, and how many
blocks state no part number that could be read: a stack that comes
back a member short has to say so.  When no member is read, the FIRST
note is the reason.

The text is whatever was pasted.  The two patterns applied to it are
anchored to a line, matched against each line by itself, and bounded in
what they take (a member number of six digits, a part number of
thirty-two characters), so the work grows with the text and no faster.
A block opens only at the left margin and holds the indented lines
after it, until the next line at the margin; every line is read outside
every banner (the parser's own :func:`.parse.without_banner_bodies`),
since a banner's lines are text.

Pure functions over text -- no I/O, no codec state.
"""

from __future__ import annotations

import re

from ....models.port_inventory import DetectedDeployment, DetectedMember
from ...limits import ticked
from .parse import without_banner_bodies

__all__ = ["detect_deployment"]

#: ``vsf member 2``, at the left margin.  Aruba's template prints a
#: space after the number.  Matched against one line at a time.
_MEMBER_RE = re.compile(r"vsf[ \t]+member[ \t]+(?P<id>[0-9]{1,6})[ \t]*$")

#: ``    type jl661a``, indented under a member's block.  Anchored at the
#: start of the line, so that a search that fails does not start again
#: inside the run of white space it has just crossed.
_TYPE_RE = re.compile(
    r"^[ \t]+type[ \t]+(?P<part>[A-Za-z0-9][A-Za-z0-9-]{0,31})[ \t]*$"
)

#: What the config's blocks are called in a detection's ``fabric``: the
#: word that opens each of them.
FABRIC = "vsf"

_NOTE_MEMBER = (
    "A `type` line under `vsf member <number>` shows the part number the "
    "member is provisioned as (\"The part number of the member being "
    "provisioned\", HPE's VSF guide for the 6200 and 6300); it does not "
    "show that the switch is in the stack."
)

#: The most member numbers one note spells out.  The text is whatever
#: was pasted: a note that listed every number it found was megabytes.
_LISTED = 8


def _opens_a_member(line: str) -> bool:
    """*line* sets out to open a member's block: ``vsf member
    <something>`` at the left margin."""
    if not line.startswith("vsf"):
        return False
    words = line.split(None, 2)
    return len(words) >= 2 and words[0] == "vsf" and words[1] == "member"


def _says_type(line: str) -> bool:
    """*line*, an indented line, sets out to state a part number: its
    first word is ``type``."""
    words = line.split(None, 1)
    return bool(words) and words[0] == "type"


def _listed(numbers: set[int]) -> str:
    """The first few of *numbers*, and how many more there are."""
    ordered = sorted(numbers)
    shown = ", ".join(str(number) for number in ordered[:_LISTED])
    more = len(ordered) - _LISTED
    return f"{shown} and {more} more" if more > 0 else shown


def detect_deployment(raw_text: str) -> DetectedDeployment | None:
    """Read what members an AOS-CX config says its VSF stack has.

    Args:
        raw_text: The configuration text.

    Returns:
        The detection, or ``None`` when the text has no line that opens
        a member's block (no ``vsf member <number>`` line at the left
        margin) -- an AOS-CX switch that is not a 6200 or 6300 prints
        none.  A detection may have NO members: every such block could
        not be read as a member and a part number.  Its FIRST note then
        says why.  ``fabric`` is ``"vsf"``, the word each block begins
        with; the members are in number order.

    Raises:
        ParseError: A banner cannot be told from the configuration
            (:func:`.parse.without_banner_bodies`): its lines are not
            read, and nor is anything after them.
    """
    parts: dict[int, str] = {}
    used: dict[int, str] = {}
    restated: set[int] = set()
    unread = 0
    untyped: set[int] = set()
    opened = False
    member: int | None = None
    typed = False
    for line in ticked(without_banner_bodies(raw_text).splitlines()):
        if not line.strip():
            continue
        if line[:1] not in (" ", "\t"):
            # A line at the margin ends the block that is open.
            if member is not None and not typed:
                untyped.add(member)
            member, typed = None, False
            if not _opens_a_member(line):
                continue
            opened = True
            match = _MEMBER_RE.match(line)
            if match is None:
                unread += 1
                continue
            member = int(match.group("id"))
            continue
        if member is None or not _says_type(line):
            continue
        match = _TYPE_RE.match(line)
        if match is None:
            continue
        part = match.group("part").upper()
        if parts.get(member, part) != part:
            restated.add(member)
        parts[member] = part
        used[member] = f"vsf member {member} / type {match.group('part')}"
        typed = True
    if member is not None and not typed:
        untyped.add(member)
    if not opened:
        return None

    untyped -= set(parts)
    notes: list[str] = []
    if not parts:
        notes.append(
            "The config has `vsf member` lines, but none could be read as a "
            "member's number with a `type` line under it."
        )
    else:
        notes.append(_NOTE_MEMBER)
    if unread:
        notes.append(
            f"{unread} line(s) begin `vsf member` and could not be read as a "
            f"member's number (it is not in a form a switch prints); each "
            f"block was left out."
        )
    if untyped:
        notes.append(
            f"The block of member {_listed(untyped)} has no `type` line that "
            f"could be read as a part number; it was left out."
        )
    if restated:
        notes.append(
            f"More than one line states member {_listed(restated)} with "
            f"different part numbers; the last was used."
        )
    return DetectedDeployment(
        fabric=FABRIC,
        members=[DetectedMember(part=parts[number], id=number) for number in sorted(parts)],
        evidence=[used[number] for number in sorted(parts)],
        notes=notes,
    )

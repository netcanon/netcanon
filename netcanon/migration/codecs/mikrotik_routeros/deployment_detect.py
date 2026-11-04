"""
What device a MikroTik RouterOS export says it came from.

An ``/export`` of a RouterBOARD or a Cloud Router Switch opens with
comment lines, and one of them names the device's model::

    # 2026-01-01 00:00:00 by RouterOS 7.18.2
    # software id = ...
    #
    # model = CRS310-8G+2S+
    # serial number = ...

The model is printed as the device prints it in ``/system routerboard``:
the product code without its ``-RM`` or ``-IN`` suffix
(``CRS310-8G+2S+`` for a CRS310-8G+2S+IN), which is the key a model
family lists it under.  No MikroTik text read describes the header;
every public export read that has the line prints it once, in that
form, between the software id and the serial number.  A text with no
such line names no model, and nothing is proposed.

This module reads that line and nothing else -- never the serial
number nor the software id beside it, which identify one physical
device and say nothing about what the device is.  It does not decide
what the model IS -- that is the model registry's job
(:func:`netcanon.migration.deployment_detect.propose_deployment`) -- so
it has no table of models to fall out of date.  RouterOS names no
member and no slot, so a detection has one member, with no member
number, and no ``fabric``.

What a reader of the result must know, which the detection says in its
notes: the line is a comment.  It names the model of the device that
printed the export; nothing in the configuration depends on it, and a
file can be edited.

The notes also say how many lines set out to state the model (a
comment whose first word is ``model``) and could not be read, and a
text whose lines name two models is proposed as neither: it is the
export of more than one device.  When no model is read, the FIRST note
is the reason.

The text is whatever was pasted.  It is read a line at a time, after
the parser's own joining of continued lines
(:func:`.parse._join_continuations`, which is linear and ticked), so
that a line is what the parser reads as a line.  The one pattern
applied to a line is matched at its start, and its two runs of white
space are kept apart by the ``#``; the model after it is taken whole,
cut of the white space around it, and is read only if it is at most
64 characters of the ones a product code is written in.  So the work
grows with the text and no faster.

Pure functions over text -- no I/O, no codec state.
"""

from __future__ import annotations

import re

from ....models.port_inventory import DetectedDeployment, DetectedMember
from ...limits import ticked
from .parse import _join_continuations

__all__ = ["detect_deployment"]

#: A comment whose first word is ``model``: a line that sets out to
#: state the model.  Anchored at the start of a line (``^``, so that no
#: search of it starts again inside a run of white space); the ``#``
#: keeps the two runs of white space apart.
_OPENS_RE = re.compile(r"^[ \t]*#[ \t]*model\b")

#: ``# model =``, as an export prints it, up to the model.  Anchored as
#: :data:`_OPENS_RE` is.
_MODEL_RE = re.compile(r"^[ \t]*#[ \t]*model[ \t]*=")

#: What a model is written in, as RouterOS prints one
#: (``CRS310-8G+2S+``, ``RB952Ui-5ac2nD``, ``CCR1072-1G-8S+``): letters,
#: digits and the marks a product code uses.  A space is let in as
#: well, though no export read prints one in a model: a model read is
#: looked up, and one no family describes is said to be so.  At most
#: 64 characters.
_PART_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9+\-_.&^ ]{0,63}")

_NOTE_MODEL = (
    "The `# model =` line is a comment: it names the model of the device "
    "that printed the export, as that device printed it.  Nothing in the "
    "configuration depends on it, and a file can be edited; no MikroTik "
    "text read describes the line."
)

#: The most models one note spells out.  The text is whatever was
#: pasted: a note that listed every model it found was megabytes.
_LISTED = 8


def _listed(parts: list[str]) -> str:
    """The first few of *parts*, and how many more there are."""
    shown = ", ".join(parts[:_LISTED])
    more = len(parts) - _LISTED
    return f"{shown} and {more} more" if more > 0 else shown


def _model_of(line: str) -> str | None:
    """The model *line* states, as printed, or ``None`` when it is not a
    ``# model =`` line in the form an export prints."""
    match = _MODEL_RE.match(line)
    if match is None:
        return None
    value = line[match.end():].strip(" \t")
    if len(value) > 64 or _PART_RE.fullmatch(value) is None:
        return None
    return value


def detect_deployment(raw_text: str) -> DetectedDeployment | None:
    """Read what device a RouterOS export says it was printed by.

    Args:
        raw_text: The configuration text.

    Returns:
        The detection, or ``None`` when no comment's first word is
        ``model``.  A detection may have NO member: no such line could
        be read as ``# model =`` and a model, or the lines name more
        than one model.  Its FIRST note then says why.  With a member,
        there is one: the model as printed, upper-cased, with no member
        number; ``fabric`` is ``""``.
    """
    seen: dict[str, str] = {}
    times: dict[str, int] = {}
    unread = 0
    opened = False
    for line in ticked(_join_continuations(raw_text).splitlines()):
        if _OPENS_RE.match(line) is None:
            continue
        opened = True
        model = _model_of(line)
        if model is None:
            unread += 1
            continue
        part = model.upper()
        seen.setdefault(part, f"# model = {model}")
        times[part] = times.get(part, 0) + 1
    if not opened:
        return None

    notes: list[str] = []
    members: list[DetectedMember] = []
    evidence: list[str] = []
    if not seen:
        notes.append(
            "The config has comment lines that begin `# model`, but none "
            "could be read as `# model =` and a model."
        )
    elif len(seen) > 1:
        notes.append(
            f"The config's `# model =` lines name {len(seen)} models "
            f"({_listed(sorted(seen))}): the text is from more than one "
            f"device, and no device is proposed."
        )
    else:
        ((part, line),) = seen.items()
        members.append(DetectedMember(part=part))
        evidence.append(line)
        notes.append(_NOTE_MODEL)
        if times[part] > 1:
            notes.append(
                f"The config has {times[part]} `# model =` lines.  Every "
                f"export read prints it once, so the text may be from more "
                f"than one device of that model."
            )
    if unread:
        notes.append(
            f"{unread} comment line(s) begin `# model` and could not be read "
            f"as `# model =` and a model (they are not in the form an export "
            f"prints); each was left out."
        )
    return DetectedDeployment(members=members, evidence=evidence, notes=notes)

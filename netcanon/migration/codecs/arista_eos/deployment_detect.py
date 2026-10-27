"""
What device an Arista EOS configuration says it came from.

An EOS switch's ``show running-config`` opens with comment lines, and
one of them names the switch, its model and its EOS release::

    ! Command: show running-config
    ! device: leaf1 (DCS-7050SX3-48YC8, EOS-4.32.1F)

The host name, then in brackets the model as the switch prints it -- a
part number, with its ``-F`` or ``-R`` where the part has one
(``DCS-7050TX-64-F``) -- a comma and the release.  Every public EOS
configuration read that has the line prints it in that form, a
release with more after it included (``EOS-4.27.0F-24865015.eostrunk.1
(engineering build)``).  No Arista text read describes the line.

This module reads that line and nothing else.  It does not decide what
the model IS -- that is the model registry's job
(:func:`netcanon.migration.deployment_detect.propose_deployment`) -- so
it has no table of models to fall out of date.  An Arista fixed switch
stands alone: the two switches of an MLAG pair are two devices, each
with a configuration of its own, so a detection has one member, with
no member number, and no ``fabric``.

What a reader of the result must know, which the detection says in its
notes: the line is a comment.  It names the model of the switch that
printed the text; nothing in the configuration depends on it, and a
file can be edited.

The notes also say how many lines set out to state the device (they
begin ``! device:``) and could not be read, and a text whose lines name
two models is proposed as neither: it is the text of more than one
switch.  When no device is read, the FIRST note is the reason.

The text is whatever was pasted.  The one pattern applied to it is
matched at the start of one line at a time, takes nothing that the run
before it can take, and is bounded in what it takes (a host name of
253 characters, a model of 32, a release of 32), so the work grows with
the text and no faster.  The host name is not handed back: evidence is
the line without it.  Every line is read outside every banner and
every other body that runs to ``EOF`` (the parser's own
:func:`.parse.without_bodies`), since a banner's lines are text.

Pure functions over text -- no I/O, no codec state.
"""

from __future__ import annotations

import re

from ....models.port_inventory import DetectedDeployment, DetectedMember
from ...limits import ticked
from .parse import without_bodies

__all__ = ["detect_deployment"]

#: What a line that sets out to state the device begins with.
_OPENS = "! device:"

#: ``! device: leaf1 (DCS-7050SX3-48YC8, EOS-4.32.1F)``, at the start of
#: a line.  A host name has no white space or bracket in it, so the run
#: after it is not one the name can take; the model is a part number's
#: letters, digits and hyphens, up to the comma; the release is taken as
#: far as its number goes (``4.27.0F`` of ``4.27.0F-24865015...``).
_DEVICE_RE = re.compile(
    r"! device:[ \t]+[^ \t(]{1,253}[ \t]+"
    r"\((?P<part>[A-Za-z0-9][A-Za-z0-9-]{0,31}),[ \t]*"
    r"EOS-(?P<release>[0-9][0-9A-Za-z.]{0,31})"
)

_NOTE_DEVICE = (
    "The `! device:` line is a comment: it names the model of the switch "
    "that printed the configuration, as that switch printed it.  Nothing "
    "in the configuration depends on it, and a file can be edited; no "
    "Arista text read describes the line."
)

#: The most models one note spells out.  The text is whatever was
#: pasted: a note that listed every model it found was megabytes.
_LISTED = 8


def _listed(parts: list[str]) -> str:
    """The first few of *parts*, and how many more there are."""
    shown = ", ".join(parts[:_LISTED])
    more = len(parts) - _LISTED
    return f"{shown} and {more} more" if more > 0 else shown


def detect_deployment(raw_text: str) -> DetectedDeployment | None:
    """Read what switch an EOS config says it was printed by.

    Args:
        raw_text: The configuration text.

    Returns:
        The detection, or ``None`` when no line begins ``! device:``.
        A detection may have NO member: no such line could be read as
        a model in brackets after a host name, or the lines name more
        than one model.  Its FIRST note then says why.  With a member,
        there is one: the model as printed, upper-cased, with no member
        number; ``fabric`` is ``""``.

    Raises:
        ParseError: A banner or another body that runs to ``EOF`` cannot
            be told from the configuration
            (:func:`.parse.without_bodies`): its lines are not read, and
            nor is anything after them.
    """
    seen: dict[str, str] = {}
    unread = 0
    opened = False
    for line in ticked(without_bodies(raw_text).splitlines()):
        if not line.startswith(_OPENS):
            continue
        opened = True
        match = _DEVICE_RE.match(line)
        if match is None:
            unread += 1
            continue
        part = match.group("part").upper()
        seen.setdefault(
            part, f"! device: … ({match.group('part')}, EOS-{match.group('release')})",
        )
    if not opened:
        return None

    notes: list[str] = []
    members: list[DetectedMember] = []
    evidence: list[str] = []
    if not seen:
        notes.append(
            "The config has `! device:` lines, but none could be read as a "
            "model in brackets after the switch's host name."
        )
    elif len(seen) > 1:
        notes.append(
            f"The config's `! device:` lines name {len(seen)} models "
            f"({_listed(sorted(seen))}): the text is from more than one "
            f"switch, and no device is proposed."
        )
    else:
        ((part, line),) = seen.items()
        members.append(DetectedMember(part=part))
        evidence.append(line)
        notes.append(_NOTE_DEVICE)
    if unread:
        notes.append(
            f"{unread} line(s) begin `! device:` and could not be read as a "
            f"model in brackets after a host name (they are not in the form "
            f"a switch prints); each was left out."
        )
    return DetectedDeployment(members=members, evidence=evidence, notes=notes)

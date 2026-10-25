"""
What device a Catalyst configuration says it came from.

A Catalyst's ``show running-config`` states the type of each switch of
its stack on a line of its own, at the top of the config::

    switch 1 provision c9300-24ux
    switch 2 provision c9300-48p

A switch that is alone is a stack of one and prints the line too, under
the number it keeps (not always 1).  Cisco calls what the line sets the
switch's provisioned configuration: "The switch type in the provisioned
configuration must match the switch type of the newly added switch",
and the stack keeps it "whether or not the provisioned switch is part
of the stack" (Stack Manager and High Availability Configuration Guide,
Cisco IOS XE 17.12.x, Catalyst 9300 Switches: Managing Switch Stacks,
"Offline Configuration to Provision a Stack Member").

This module reads those lines and nothing else.  It does not decide
what the types ARE -- that is the model registry's job
(:func:`netcanon.migration.deployment_detect.propose_deployment`) -- so
it has no table of models to fall out of date.

What a reader of the result must know, each of which the detection
says in its notes:

* a ``switch N provision`` line shows what the stack is PROVISIONED
  for; the switch need not be in the stack;
* no line read here states a network module, so each switch is
  proposed with its module bay empty.  A C9300 config holds an
  interface for every port of every module the bay can take, fitted or
  not, and the proposal's check then lists those names as names the
  proposed device does not have;
* the XML a NETCONF ``get-config`` answers is not read.

The notes also say where two lines state one switch differently and
which was used, and how many lines set out to state a switch
(``switch <something> provision``) and could not be read as one: a
stack that comes back a switch short has to say so.  When no switch is
read, the FIRST note is the reason.

The text is whatever was pasted.  The one pattern applied to it is
anchored to a line, matched against each line by itself, and bounded
in what it takes (a switch number of six digits, a type of thirty-two
characters), so the work grows with the text and no faster.  A line is
read only at the left margin, outside every banner (the parser's own
:func:`.parse.without_banner_bodies`): an indented line is a line of a
stanza, and a banner's lines are text.

Pure functions over text -- no I/O, no codec state.
"""

from __future__ import annotations

import re

from ....models.port_inventory import DetectedDeployment, DetectedMember
from ...limits import ticked
from .parse import without_banner_bodies

__all__ = ["detect_deployment"]

#: ``switch 1 provision c9300-24ux``: a switch number, and the type a
#: device prints in lower case.  Matched against one line at a time.
_PROVISION_RE = re.compile(
    r"switch[ \t]+(?P<id>[0-9]{1,6})[ \t]+provision[ \t]+"
    r"(?P<part>[A-Za-z0-9][A-Za-z0-9-]{0,31})[ \t]*$"
)

#: What the config's lines are called in a detection's ``fabric``: the
#: word that opens each of them.
FABRIC = "switch"

_NOTE_MEMBER = (
    "A `switch <number> provision` line shows what the stack is "
    "provisioned for; Cisco keeps it whether or not that switch is in "
    "the stack."
)
_NOTE_MODULE = (
    "No line of the config states a network module, so each switch is "
    "proposed with its module bay empty.  A Catalyst config can hold an "
    "interface for every port of every module the bay takes, fitted or "
    "not (a C9300's does): declare the module that is fitted."
)
_NOTE_XML = (
    "The config is XML.  The lines that state a Catalyst's hardware are "
    "read from a `show running-config` (`switch <number> provision`), "
    "not from XML; declare the device yourself."
)

#: The most switch numbers one note spells out.  The text is whatever
#: was pasted: a note that listed every number it found was megabytes.
_LISTED = 8


def _says_provision(line: str) -> bool:
    """*line* sets out to state a switch: ``switch <something>
    provision`` at the left margin."""
    if not line.startswith("switch"):
        return False
    words = line.split(None, 3)
    return len(words) >= 3 and words[0] == "switch" and words[2] == "provision"


def _listed(numbers: set[int]) -> str:
    """The first few of *numbers*, and how many more there are."""
    ordered = sorted(numbers)
    shown = ", ".join(str(number) for number in ordered[:_LISTED])
    more = len(ordered) - _LISTED
    return f"{shown} and {more} more" if more > 0 else shown


def detect_deployment(raw_text: str) -> DetectedDeployment | None:
    """Read what switches a Catalyst config says it came from.

    Args:
        raw_text: The configuration text.

    Returns:
        The detection, or ``None`` when the text has no line that
        states a switch (no ``switch <number> provision`` line at the
        left margin).  A detection may have NO members: the text is
        XML, or every such line could not be read.  Its FIRST note then
        says why.  ``fabric`` is ``"switch"``, the word each line
        begins with; the members are in number order, each with its
        bay empty (no line states a module).

    Raises:
        ParseError: A banner, or another body of text, cannot be told
            from the configuration (:func:`.parse.without_banner_bodies`):
            its lines are not read, and nor is anything after them.
    """
    if raw_text.lstrip()[:1] == "<":
        return DetectedDeployment(fabric="", members=[], evidence=[], notes=[_NOTE_XML])
    # Lines as the parser cuts them (``str.splitlines``), with a
    # banner's lines empty, as the parser reads them.
    parts: dict[int, str] = {}
    used: dict[int, str] = {}
    restated: set[int] = set()
    unread = 0
    for line in ticked(without_banner_bodies(raw_text).splitlines()):
        if not _says_provision(line):
            continue
        match = _PROVISION_RE.match(line)
        if match is None:
            unread += 1
            continue
        switch, part = int(match.group("id")), match.group("part").upper()
        if parts.get(switch, part) != part:
            restated.add(switch)
        parts[switch] = part
        used[switch] = " ".join(match.group(0).split())
    if not parts and not unread:
        return None

    notes: list[str] = []
    if not parts:
        notes.append(
            "The config has `switch <number> provision` lines, but none "
            "could be read as a switch's number and type."
        )
    else:
        notes.extend((_NOTE_MEMBER, _NOTE_MODULE))
    if unread:
        notes.append(
            f"{unread} line(s) begin `switch <number> provision` and could "
            f"not be read as a switch (the number or the type is not in a "
            f"form a device prints); each was left out."
        )
    if restated:
        notes.append(
            f"More than one line states switch {_listed(restated)} with "
            f"different types; the last was used."
        )
    return DetectedDeployment(
        fabric=FABRIC,
        members=[DetectedMember(part=parts[switch], id=switch) for switch in sorted(parts)],
        evidence=[used[switch] for switch in sorted(parts)],
        notes=notes,
    )

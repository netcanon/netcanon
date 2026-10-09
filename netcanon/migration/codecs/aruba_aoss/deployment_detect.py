"""
What device an AOS-S configuration says it came from.

A ``show running-config`` states its own hardware, in a few lines that
have nothing to do with the config that follows them.  Which lines
depends on whether the switch is in a stacking mode:

Not stacked — the banner and a ``module 1`` line carry the chassis
part number, and a module bay is a top-level line::

    ; JL323A Configuration Editor; Created on release #WC.16.07.0003
    module 1 type jl323a
    flexible-module A type JL083A

Backplane stacking (2930M, 3810M) — the banner names no model; each
member's part number and modules are in the ``stacking`` stanza::

    ; hpStack_WC Configuration Editor; Created on release #WC.16.11.0025
    stacking
       member 1 type "JL323A" mac-address <mac>
       member 1 flexible-module A type JL083A
       exit

VSF (2930F, 5400R) — the same, with each member a nested block::

    vsf
       enable domain 1
       member 1
          type "JL557A" mac-address <mac>
          exit

This module reads those lines and nothing else.  It does not decide
what the part numbers ARE — that is the model registry's job
(:func:`netcanon.migration.deployment_detect.propose_deployment`) —
so it has no table of models to fall out of date.

Three things a reader of the result must know, each of which the
detection says in its notes:

* a ``member N type`` line shows what the stack is PROVISIONED for; a
  member can be configured before it is connected;
* a ``flexible-module`` line likewise shows what the bay is provisioned
  for, not that a module is fitted;
* the stack banner carries no model, so a stacked config with its
  ``stacking`` / ``vsf`` stanza cut off says nothing about its hardware.

The notes also say where two lines state one fact differently and
which was used (a member stated twice, a banner and a ``module 1`` line
that disagree, a second stanza), and where a line that set out to
state a member could not be read as one: a stack that comes back one
member short has to say so.

The text is whatever was pasted.  Every pattern here is anchored to a
line and bounded in what it takes (a member number of six digits, a
part of thirty-two characters), so the work grows with the text and no
faster; none is applied to a fragment another pattern matched.  Keep
it so: a detector that is slow on a run of spaces holds the server.

Pure functions over text — no I/O, no codec state.
"""

from __future__ import annotations

import re

from ....models.port_inventory import DetectedDeployment, DetectedMember

__all__ = ["detect_deployment"]

#: ``; JL260A Configuration Editor; ...`` — and the stack forms
#: ``hpStack_WC`` (every real capture) and ``Stack_WC`` (HPE's guides).
_BANNER_RE = re.compile(
    r"^;[ \t]*(?P<id>[A-Za-z0-9_]{1,32})[ \t]+Configuration Editor\b", re.MULTILINE,
)
_STACK_BANNER_RE = re.compile(r"(?:hp)?Stack_\w+", re.IGNORECASE)
#: A chassis part number as a banner prints it: ``JL260A``, ``J9729A``,
#: ``R0M67A``.  Not every one starts with ``J``.
_PART_RE = re.compile(r"[A-Z][A-Z0-9]{4,7}")

_FABRIC_RE = re.compile(r"^(?P<kind>stacking|vsf)[ \t]*$", re.MULTILINE)
_MEMBER_TYPE_RE = re.compile(
    r'^[ \t]+member[ \t]+(?P<id>[0-9]{1,6})[ \t]+type[ \t]+"?(?P<part>[A-Za-z0-9]{1,32})"?(?=[ \t]|$)',
    re.MULTILINE,
)
_MEMBER_MODULE_RE = re.compile(
    r'^[ \t]+member[ \t]+(?P<id>[0-9]{1,6})[ \t]+flexible-module[ \t]+(?P<bay>[A-Za-z])'
    r'[ \t]+type[ \t]+"?(?P<part>[A-Za-z0-9]{1,32})"?(?=[ \t]|$)',
    re.MULTILINE,
)
_NESTED_MEMBER_RE = re.compile(r"^[ \t]+member[ \t]+(?P<id>[0-9]{1,6})[ \t]*$", re.MULTILINE)
_NESTED_TYPE_RE = re.compile(
    r'^[ \t]+type[ \t]+"?(?P<part>[A-Za-z0-9]{1,32})"?(?=[ \t]|$)', re.MULTILINE,
)
_CHASSIS_RE = re.compile(
    r"^module[ \t]+1[ \t]+type[ \t]+(?P<part>[A-Za-z0-9]{1,32})[ \t]*$", re.MULTILINE,
)
_TOP_MODULE_RE = re.compile(
    r'^flexible-module[ \t]+(?P<bay>[A-Za-z])[ \t]+type[ \t]+"?(?P<part>[A-Za-z0-9]{1,32})"?(?=[ \t]|$)',
    re.MULTILINE,
)
#: ``module A type j9534a`` — a line card in a lettered chassis slot.
_LINE_CARD_RE = re.compile(r"^module[ \t]+[A-Za-z][ \t]+type[ \t]+\S+", re.MULTILINE)
# A member's MAC address identifies one physical device and is no part
# of what the device IS.  It never reaches the evidence because every
# pattern above ENDS at the part number, before ``mac-address``: there is
# nothing to scrub, and an unanchored scrub pattern over a matched
# fragment is quadratic on a run of spaces.

_NOTE_MEMBER = (
    "A member line shows what the stack is provisioned for; a member can "
    "be configured before it is connected."
)
_NOTE_MODULE = (
    "A flexible-module line shows what the bay is provisioned for; it "
    "does not show that a module is fitted."
)
_NOTE_LINE_CARDS = (
    "The config lists line cards in lettered slots: this is a modular "
    "chassis, whose ports depend on which card is in which slot."
)


def _says_member_type(line: str) -> bool:
    """*line* sets out to state a member: ``member <something> type``."""
    words = line.split(None, 3)
    return len(words) >= 3 and words[0] == "member" and words[2] == "type"


def _listed(numbers: set[int]) -> str:
    return ", ".join(str(number) for number in sorted(numbers))


def _evidence(line: str) -> str:
    """A matched fragment as one line, runs of space collapsed."""
    return " ".join(line.split())


def _stanza_body(text: str, start: int) -> str:
    """The indented lines of the stanza whose header starts at *start*."""
    body: list[str] = []
    for line in text[start:].split("\n")[1:]:
        if line.strip() and not line[0].isspace():
            break
        body.append(line)
    return "\n".join(body)


def _fabric(kind: str, body: str, evidence: list[str]) -> DetectedDeployment:
    parts: dict[int, str] = {}
    modules: dict[int, dict[str, str]] = {}
    restated: set[int] = set()
    read = 0
    for match in _MEMBER_TYPE_RE.finditer(body):
        member_id = int(match.group("id"))
        part = match.group("part").upper()
        if parts.get(member_id, part) != part:
            restated.add(member_id)
        parts[member_id] = part
        read += 1
        evidence.append(_evidence(match.group(0)))
    untyped: set[int] = set()
    if not parts:
        # VSF nests each member's type under a ``member N`` block.
        blocks = list(_NESTED_MEMBER_RE.finditer(body))
        for at, block in enumerate(blocks):
            end = blocks[at + 1].start() if at + 1 < len(blocks) else len(body)
            typed = _NESTED_TYPE_RE.search(body, block.end(), end)
            member_id = int(block.group("id"))
            if typed is None:
                untyped.add(member_id)
                continue
            part = typed.group("part").upper()
            if parts.get(member_id, part) != part:
                restated.add(member_id)
            parts[member_id] = part
            evidence.append(f"member {member_id}: {_evidence(typed.group(0))}")
    orphaned: set[int] = set()
    for match in _MEMBER_MODULE_RE.finditer(body):
        member_id = int(match.group("id"))
        if member_id in parts:
            modules.setdefault(member_id, {})[match.group("bay").upper()] = (
                match.group("part").upper()
            )
            evidence.append(_evidence(match.group(0)))
        else:
            orphaned.add(member_id)
    notes: list[str] = []
    if not parts:
        notes.append(
            f"The config has a `{kind}` stanza, but no line in it names a "
            f"member's model."
        )
    else:
        notes.append(_NOTE_MEMBER)
        if modules:
            notes.append(_NOTE_MODULE)
    # What was not read is said, so that a stack does not come back a
    # member short with nothing to show for it.
    unread = sum(1 for line in body.split("\n") if _says_member_type(line)) - read
    if unread > 0:
        notes.append(
            f"{unread} line(s) of the stanza begin `member <number> type` "
            f"and could not be read as a member (the number or the part is "
            f"not in a form a device prints); each was left out."
        )
    untyped -= set(parts)
    if untyped:
        notes.append(
            f"The stanza has a `member` block with no `type` line for "
            f"member {_listed(untyped)}; each was left out."
        )
    if orphaned:
        notes.append(
            f"A `flexible-module` line names member {_listed(orphaned)}, "
            f"which has no `type` line that was read; the module was left out."
        )
    if restated:
        notes.append(
            f"More than one line states member {_listed(restated)} with "
            f"different part numbers; the last was used."
        )
    return DetectedDeployment(
        fabric=kind,
        members=[
            DetectedMember(part=parts[member_id], id=member_id,
                           modules=modules.get(member_id, {}))
            for member_id in sorted(parts)
        ],
        evidence=evidence,
        notes=notes,
    )


def detect_deployment(raw_text: str) -> DetectedDeployment | None:
    """Read what device(s) an AOS-S config says it came from.

    Args:
        raw_text: The configuration text.

    Returns:
        The detection, or ``None`` when the text carries none of the
        lines that state a device (no banner, no ``module 1`` line, no
        ``stacking`` / ``vsf`` stanza).  A detection may have NO
        members: the text shows the switch is in a stacking mode but
        not what it is made of (the notes say so).  ``fabric`` is the
        config's own word for the stanza it was read from,
        ``"stacking"`` or ``"vsf"``, and ``""`` when there is no such
        stanza.
    """
    # Lines as the AOS-S parser cuts them (``str.splitlines``), so the
    # two cannot disagree about where a line ends.
    text = "\n".join(raw_text.splitlines())
    evidence: list[str] = []
    banner = _BANNER_RE.search(text)
    banner_id = banner.group("id") if banner else ""
    if banner:
        evidence.append(_evidence(banner.group(0)))

    stanza = _FABRIC_RE.search(text)
    if stanza is not None:
        kind = stanza.group("kind")
        evidence.append(kind)
        detection = _fabric(kind, _stanza_body(text, stanza.start()), evidence)
        if _FABRIC_RE.search(text, stanza.end()) is not None:
            detection.notes.append(
                "The config has more than one `stacking` or `vsf` stanza; "
                "the first was read."
            )
        if _LINE_CARD_RE.search(text):
            detection.notes.append(_NOTE_LINE_CARDS)
        return detection

    if _STACK_BANNER_RE.fullmatch(banner_id):
        return DetectedDeployment(
            fabric="",
            members=[],
            evidence=evidence,
            notes=[
                "The banner is a stack's, which names no model, and the "
                "`stacking` or `vsf` stanza that would name each member is "
                "not in this text."
            ],
        )

    chassis = _CHASSIS_RE.search(text)
    part = ""
    notes: list[str] = []
    if chassis is not None:
        # On the fixed switches the families describe, ``module 1`` is
        # the chassis and agrees with the banner.  On a modular chassis
        # it can be a line card in slot 1, with the chassis in the
        # banner only: the two then disagree, the note below says so,
        # and a family for such a chassis has to settle which line
        # states the device before it ships.
        part = chassis.group("part").upper()
        evidence.append(_evidence(chassis.group(0)))
        if _PART_RE.fullmatch(banner_id.upper()) and banner_id.upper() != part:
            notes.append(
                f"The banner says {banner_id.upper()} and the `module 1` "
                f"line says {part}; the `module 1` line was used."
            )
    elif _PART_RE.fullmatch(banner_id.upper()):
        part = banner_id.upper()
    if not part:
        return None

    modules: dict[str, str] = {}
    for match in _TOP_MODULE_RE.finditer(text):
        modules[match.group("bay").upper()] = match.group("part").upper()
        evidence.append(_evidence(match.group(0)))
    if modules:
        notes.append(_NOTE_MODULE)
    if _LINE_CARD_RE.search(text):
        notes.append(_NOTE_LINE_CARDS)
    return DetectedDeployment(
        fabric="",
        members=[DetectedMember(part=part, id=None, modules=modules)],
        evidence=evidence,
        notes=notes,
    )

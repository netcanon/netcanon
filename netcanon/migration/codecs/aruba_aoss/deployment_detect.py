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

Pure functions over text — no I/O, no codec state.
"""

from __future__ import annotations

import re

from ....models.port_inventory import DetectedDeployment, DetectedMember

__all__ = ["detect_deployment"]

#: ``; JL260A Configuration Editor; ...`` — and the stack forms
#: ``hpStack_WC`` (every real capture) and ``Stack_WC`` (HPE's guides).
_BANNER_RE = re.compile(
    r"^;[ \t]*(?P<id>[A-Za-z0-9_]+)[ \t]+Configuration Editor\b", re.MULTILINE,
)
_STACK_BANNER_RE = re.compile(r"(?:hp)?Stack_\w+", re.IGNORECASE)
#: A chassis part number as a banner prints it: ``JL260A``, ``J9729A``,
#: ``R0M67A``.  Not every one starts with ``J``.
_PART_RE = re.compile(r"[A-Z][A-Z0-9]{4,7}")

_FABRIC_RE = re.compile(r"^(?P<kind>stacking|vsf)[ \t]*$", re.MULTILINE)
_MEMBER_TYPE_RE = re.compile(
    r'^[ \t]+member[ \t]+(?P<id>\d+)[ \t]+type[ \t]+"?(?P<part>[A-Za-z0-9]+)"?',
    re.MULTILINE,
)
_MEMBER_MODULE_RE = re.compile(
    r'^[ \t]+member[ \t]+(?P<id>\d+)[ \t]+flexible-module[ \t]+(?P<bay>[A-Za-z])'
    r'[ \t]+type[ \t]+"?(?P<part>[A-Za-z0-9]+)"?',
    re.MULTILINE,
)
_NESTED_MEMBER_RE = re.compile(r"^[ \t]+member[ \t]+(?P<id>\d+)[ \t]*$", re.MULTILINE)
_NESTED_TYPE_RE = re.compile(
    r'^[ \t]+type[ \t]+"?(?P<part>[A-Za-z0-9]+)"?', re.MULTILINE,
)
_CHASSIS_RE = re.compile(
    r"^module[ \t]+1[ \t]+type[ \t]+(?P<part>[A-Za-z0-9]+)[ \t]*$", re.MULTILINE,
)
_TOP_MODULE_RE = re.compile(
    r'^flexible-module[ \t]+(?P<bay>[A-Za-z])[ \t]+type[ \t]+"?(?P<part>[A-Za-z0-9]+)"?',
    re.MULTILINE,
)
#: ``module A type j9534a`` — a line card in a lettered chassis slot.
_LINE_CARD_RE = re.compile(r"^module[ \t]+[A-Za-z][ \t]+type[ \t]+\S+", re.MULTILINE)
#: A member's MAC address identifies one physical device.  It is no
#: part of what the device IS, so it is kept out of the evidence lines.
_MAC_RE = re.compile(r"[ \t]+mac-address[ \t]+\S+")

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


def _evidence(line: str) -> str:
    return _MAC_RE.sub("", line.strip())


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
    for match in _MEMBER_TYPE_RE.finditer(body):
        parts[int(match.group("id"))] = match.group("part").upper()
        evidence.append(_evidence(match.group(0)))
    if not parts:
        # VSF nests each member's type under a ``member N`` block.
        blocks = list(_NESTED_MEMBER_RE.finditer(body))
        for at, block in enumerate(blocks):
            end = blocks[at + 1].start() if at + 1 < len(blocks) else len(body)
            typed = _NESTED_TYPE_RE.search(body, block.end(), end)
            if typed is not None:
                member_id = int(block.group("id"))
                parts[member_id] = typed.group("part").upper()
                evidence.append(f"member {member_id}: {_evidence(typed.group(0))}")
    for match in _MEMBER_MODULE_RE.finditer(body):
        member_id = int(match.group("id"))
        if member_id in parts:
            modules.setdefault(member_id, {})[match.group("bay").upper()] = (
                match.group("part").upper()
            )
            evidence.append(_evidence(match.group(0)))
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
    text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    evidence: list[str] = []
    banner = _BANNER_RE.search(text)
    banner_id = banner.group("id") if banner else ""
    if banner:
        evidence.append(banner.group(0).strip())

    stanza = _FABRIC_RE.search(text)
    if stanza is not None:
        kind = stanza.group("kind")
        evidence.append(kind)
        return _fabric(kind, _stanza_body(text, stanza.start()), evidence)

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
        part = chassis.group("part").upper()
        evidence.append(chassis.group(0).strip())
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
        evidence.append(match.group(0).strip())
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

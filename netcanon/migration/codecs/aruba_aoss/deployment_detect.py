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
which was used (a member or a bay stated twice, a banner and a
``module 1`` line that disagree, a second banner, ``module 1`` line or
stanza, a part-number banner beside a stanza), and where a line that
set out to state a member, a module or the chassis could not be read
as one: a stack that comes back a member or a module short has to say
so.  A note spells out a few member numbers and counts the rest.

When no member is read, the FIRST note is the reason.  A proposal
with no deployment shows its first note as why; the remarks follow.

The text is whatever was pasted.  Every pattern applied to it is
anchored to a line and bounded in what it takes (a member number of
six digits, a part of thirty-two characters), and each line is matched
by itself, so the work grows with the text and no faster.  The two
patterns applied to the banner's id see at most thirty-two characters;
none is applied to a fragment of unbounded length.  Keep it so: a
detector that is slow on a run of spaces holds the server.

Pure functions over text — no I/O, no codec state.
"""

from __future__ import annotations

import re

from ....models.port_inventory import DetectedDeployment, DetectedMember

__all__ = ["detect_deployment"]

#: ``; JL260A Configuration Editor; ...`` — and the stack forms
#: ``hpStack_WC`` (the committed stacked capture) and ``Stack_WC``
#: (HPE's guides).
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


#: The most member numbers one note spells out.  The text is whatever
#: was pasted: a note that listed every number it found was megabytes.
_LISTED = 8


def _says_member_type(line: str) -> bool:
    """*line* sets out to state a member: ``member <something> type``."""
    words = line.split(None, 3)
    return len(words) >= 3 and words[0] == "member" and words[2] == "type"


def _says_module(line: str) -> bool:
    """*line* sets out to state a module: ``[member <n>]
    flexible-module <bay> type``."""
    words = line.split(None, 5)
    if words[:1] == ["member"]:
        words = words[2:]
    return len(words) >= 3 and words[0] == "flexible-module" and words[2] == "type"


def _says_chassis(line: str) -> bool:
    """*line* sets out to state the chassis: ``module 1 type``."""
    return line.startswith("module") and line.split(None, 3)[:3] == ["module", "1", "type"]


def _heads_a_member_block(line: str) -> bool:
    """*line* is ``member <something>`` and nothing more: the header of
    a nested block, whether or not its number can be read."""
    words = line.split(None, 2)
    return len(words) == 2 and words[0] == "member"


def _listed(numbers: set[int]) -> str:
    """The first few of *numbers*, and how many more there are."""
    ordered = sorted(numbers)
    shown = ", ".join(str(number) for number in ordered[:_LISTED])
    more = len(ordered) - _LISTED
    return f"{shown} and {more} more" if more > 0 else shown


def _evidence(line: str) -> str:
    """A matched fragment as one line, runs of space collapsed."""
    return " ".join(line.split())


def _stanza_body(text: str, start: int) -> list[str]:
    """The indented lines of the stanza whose header starts at *start*."""
    body: list[str] = []
    for line in text[start:].split("\n")[1:]:
        if line.strip() and not line[0].isspace():
            break
        body.append(line)
    return body


def _flat_members(body: list[str]) -> tuple[dict[int, str], dict[int, str], set[int], int]:
    """``member <n> type <part>`` lines: the part of each member, the
    line it was read from, the members stated two ways, and how many
    such lines could not be read."""
    parts: dict[int, str] = {}
    type_line: dict[int, str] = {}
    restated: set[int] = set()
    unread = 0
    for line in body:
        if not _says_member_type(line):
            continue
        match = _MEMBER_TYPE_RE.match(line)
        if match is None:
            unread += 1
            continue
        member_id, part = int(match.group("id")), match.group("part").upper()
        if parts.get(member_id, part) != part:
            restated.add(member_id)
        parts[member_id] = part
        type_line[member_id] = _evidence(match.group(0))
    return parts, type_line, restated, unread


def _nested_members(
    body: list[str],
) -> tuple[dict[int, str], dict[int, str], set[int], set[int], int]:
    """``member <n>`` blocks with a ``type`` line inside (VSF): as
    :func:`_flat_members`, then the blocks that have no ``type`` line
    and how many block headers could not be read.

    A block ends at the next line that heads one, whether or not that
    header can be read: a ``type`` line under a header that could not
    be read is not the member before's.
    """
    parts: dict[int, str] = {}
    type_line: dict[int, str] = {}
    restated: set[int] = set()
    headed: set[int] = set()
    unread_headers = 0
    current: int | None = None
    for line in body:
        if _heads_a_member_block(line):
            header = _NESTED_MEMBER_RE.match(line)
            current = int(header.group("id")) if header else None
            if current is None:
                unread_headers += 1
            else:
                headed.add(current)
            continue
        if current is None:
            continue
        match = _NESTED_TYPE_RE.match(line)
        if match is None:
            continue
        part = match.group("part").upper()
        if parts.get(current, part) != part:
            restated.add(current)
        parts[current] = part
        type_line[current] = f"member {current}: {_evidence(match.group(0))}"
    return parts, type_line, restated, headed - set(parts), unread_headers


def _member_modules(
    body: list[str], parts: dict[int, str],
) -> tuple[dict[int, dict[str, str]], dict[tuple[int, str], str], set[int], set[int], int]:
    """``member <n> flexible-module <bay> type <part>`` lines: each
    member's bays, the line each was read from, the members such a
    line names that no ``type`` line states, the members with a bay
    stated two ways, and how many such lines could not be read."""
    modules: dict[int, dict[str, str]] = {}
    module_line: dict[tuple[int, str], str] = {}
    orphaned: set[int] = set()
    rebayed: set[int] = set()
    unread = 0
    for line in body:
        if not _says_module(line):
            continue
        match = _MEMBER_MODULE_RE.match(line)
        if match is None:
            unread += 1
            continue
        member_id = int(match.group("id"))
        if member_id not in parts:
            orphaned.add(member_id)
            continue
        bay, part = match.group("bay").upper(), match.group("part").upper()
        fitted = modules.setdefault(member_id, {})
        if fitted.get(bay, part) != part:
            rebayed.add(member_id)
        fitted[bay] = part
        module_line[member_id, bay] = _evidence(match.group(0))
    return modules, module_line, orphaned, rebayed, unread


def _fabric(kind: str, body: list[str], evidence: list[str]) -> DetectedDeployment:
    """Read the members of a ``stacking`` or ``vsf`` stanza.

    One pass over the lines for each thing read, each line matched by
    itself: the work is the length of the stanza.
    """
    parts, type_line, restated, unread = _flat_members(body)
    untyped: set[int] = set()
    unread_headers = 0
    if not parts:
        # VSF nests each member's type under a ``member N`` block.
        parts, type_line, restated, untyped, unread_headers = _nested_members(body)
    modules, module_line, orphaned, rebayed, unread_modules = _member_modules(body, parts)

    # The evidence is the lines that were USED, a member at a time: a
    # line a later one replaced is not among them (a note says it was).
    for member_id in sorted(parts):
        evidence.append(type_line[member_id])
        evidence.extend(module_line[member_id, bay] for bay in sorted(modules.get(member_id, {})))

    # The reason goes first when no member was read: it is what a
    # proposal with no deployment shows first.
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
    # member or a module short with nothing to show for it.
    said = (
        (unread,
         f"{unread} line(s) of the stanza begin `member <number> type` "
         f"and could not be read as a member (the number or the part is "
         f"not in a form a device prints); each was left out."),
        (unread_headers,
         f"{unread_headers} line(s) of the stanza begin a `member` block "
         f"whose number could not be read; each block was left out."),
        (untyped,
         f"The stanza has a `member` block with no `type` line that could "
         f"be read for member {_listed(untyped)}; each was left out."),
        (unread_modules,
         f"{unread_modules} line(s) of the stanza begin "
         f"`member <number> flexible-module <bay> type` and could not be "
         f"read as a module; each was left out, so a bay may be proposed "
         f"empty."),
        (orphaned,
         f"A `flexible-module` line names member {_listed(orphaned)}, "
         f"which has no `type` line that was read; the module was left out."),
        (restated,
         f"More than one line states member {_listed(restated)} with "
         f"different part numbers; the last was used."),
        (rebayed,
         f"More than one line states a bay of member {_listed(rebayed)} "
         f"with different modules; the last was used."),
    )
    notes.extend(note for happened, note in said if happened)
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


def _top_modules(text: str) -> tuple[dict[str, str], dict[str, str], bool, int]:
    """``flexible-module <bay> type <part>`` lines of a switch that is
    not stacked: its bays, the line each was read from, whether a bay
    is stated two ways, and how many such lines could not be read."""
    modules: dict[str, str] = {}
    module_line: dict[str, str] = {}
    rebayed = False
    unread = 0
    for line in text.split("\n"):
        if not line.startswith("flexible-module") or not _says_module(line):
            continue
        match = _TOP_MODULE_RE.match(line)
        if match is None:
            unread += 1
            continue
        bay, fitted = match.group("bay").upper(), match.group("part").upper()
        rebayed = rebayed or modules.get(bay, fitted) != fitted
        modules[bay] = fitted
        module_line[bay] = _evidence(match.group(0))
    return modules, module_line, rebayed, unread


def detect_deployment(raw_text: str) -> DetectedDeployment | None:
    """Read what device(s) an AOS-S config says it came from.

    Args:
        raw_text: The configuration text.

    Returns:
        The detection, or ``None`` when the text carries none of the
        lines that state a device (no banner, no ``module 1`` line, no
        ``stacking`` / ``vsf`` stanza).  A detection may have NO
        members: the text shows the switch is in a stacking mode but
        not what it is made of.  Its FIRST note then says why -- that
        is what a proposal with no deployment shows first -- and the
        remarks about what else was or was not read follow it.
        ``fabric`` is the config's own word for the stanza it was read
        from, ``"stacking"`` or ``"vsf"``, and ``""`` when there is no
        such stanza.
    """
    # Lines as the AOS-S parser cuts them (``str.splitlines``), so the
    # two cannot disagree about where a line ends.
    text = "\n".join(raw_text.splitlines())
    evidence: list[str] = []
    said: list[str] = []
    banners = list(dict.fromkeys(match.group("id") for match in _BANNER_RE.finditer(text)))
    banner_id = banners[0] if banners else ""
    if banners:
        evidence.append(_evidence(_BANNER_RE.search(text).group(0)))  # type: ignore[union-attr]
    if len(banners) > 1:
        said.append(
            f"The config has more than one banner ({banners[0]}, then "
            f"{banners[1]}); the first was read."
        )

    stanza = _FABRIC_RE.search(text)
    if stanza is not None:
        kind = stanza.group("kind")
        evidence.append(kind)
        detection = _fabric(kind, _stanza_body(text, stanza.start()), evidence)
        if _PART_RE.fullmatch(banner_id.upper()):
            detection.notes.append(
                f"The banner names one switch ({banner_id.upper()}) and the "
                f"config has a `{kind}` stanza; the stanza was read."
            )
        if any(_says_chassis(line) for line in text.split("\n")):
            detection.notes.append(
                f"The config has a `module 1` line, which a switch that is "
                f"not stacked prints, and a `{kind}` stanza; the stanza was "
                f"read."
            )
        if _FABRIC_RE.search(text, stanza.end()) is not None:
            detection.notes.append(
                "The config has more than one `stacking` or `vsf` stanza; "
                "the first was read."
            )
        if _LINE_CARD_RE.search(text):
            detection.notes.append(_NOTE_LINE_CARDS)
        detection.notes.extend(said)
        return detection

    if _STACK_BANNER_RE.fullmatch(banner_id):
        return DetectedDeployment(
            fabric="",
            members=[],
            evidence=evidence,
            notes=[
                "The banner is a stack's, which names no model, and the "
                "`stacking` or `vsf` stanza that would name each member is "
                "not in this text.",
                *said,
            ],
        )

    chassis = list(dict.fromkeys(match.group("part").upper() for match in _CHASSIS_RE.finditer(text)))
    unread_chassis = sum(
        1 for line in text.split("\n") if _says_chassis(line) and _CHASSIS_RE.match(line) is None
    )
    part = ""
    notes: list[str] = []
    if chassis:
        # On the fixed switches the families describe, ``module 1`` is
        # the chassis and agrees with the banner.  On a modular chassis
        # it can be a line card in slot 1, with the chassis in the
        # banner only: the two then disagree, the note below says so,
        # and a family for such a chassis has to settle which line
        # states the device before it ships.
        part = chassis[0]
        evidence.append(_evidence(_CHASSIS_RE.search(text).group(0)))  # type: ignore[union-attr]
        if _PART_RE.fullmatch(banner_id.upper()) and banner_id.upper() != part:
            notes.append(
                f"The banner says {banner_id.upper()} and the `module 1` "
                f"line says {part}; the `module 1` line was used."
            )
        if len(chassis) > 1:
            notes.append(
                f"The config has more than one `module 1` line ({chassis[0]}, "
                f"then {chassis[1]}); the first was used."
            )
    elif _PART_RE.fullmatch(banner_id.upper()):
        part = banner_id.upper()
    if not part:
        if not unread_chassis:
            return None
        return DetectedDeployment(
            fabric="",
            members=[],
            evidence=evidence,
            notes=[
                "The config has a `module 1` line, but it could not be read "
                "as a chassis part number, and no banner names a model.",
                *said,
            ],
        )
    if unread_chassis:
        notes.append(
            f"{unread_chassis} line(s) begin `module 1 type` and could not be "
            f"read as the chassis line; each was left out."
        )

    modules, module_line, rebayed, unread_modules = _top_modules(text)
    evidence.extend(module_line[bay] for bay in sorted(modules))
    if modules:
        notes.append(_NOTE_MODULE)
    if unread_modules:
        notes.append(
            f"{unread_modules} line(s) begin `flexible-module "
            f"<bay> type` and could not be read as a module; each was left "
            f"out, so a bay may be proposed empty."
        )
    if rebayed:
        notes.append(
            "More than one line states a bay with different modules; the "
            "last was used."
        )
    if _LINE_CARD_RE.search(text):
        notes.append(_NOTE_LINE_CARDS)
    notes.extend(said)
    return DetectedDeployment(
        fabric="",
        members=[DetectedMember(part=part, id=None, modules=modules)],
        evidence=evidence,
        notes=notes,
    )

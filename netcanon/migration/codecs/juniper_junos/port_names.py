"""
Juniper Junos port-name classification + formatting.

Junos port naming is fundamentally different from the Cisco/Arista
family: media-type prefix + slot/PIC/port notation, lowercase, with
logical unit numbers for sub-interfaces.

Recognised port-name forms::

    em0                       — management (virtual/embedded)
    em0.0                     — unit 0 sub-interface
    ge-0/0/0                  — GE slot 0 PIC 0 port 0
    ge-0/0/0.0                — logical unit on above
    xe-0/0/0                  — 10GE
    et-0/0/0                  — 40GE / 100GE (EX/QFX)
    fe-0/0/0                  — FE (legacy M-series)
    me0 / me0.0               — management (SRX/MX)
    fxp0                      — management (legacy)
    lo0 / lo0.<N>             — the loopback, and its unit N, which is
                                the loopback of a routing instance
    ae0 / ae0.0               — aggregated Ethernet (LAG)
    irb.<N>                   — integrated routing and bridging (SVI-ish)

Strategy:
    v1 focuses on the common ``<media>-<fpc>/<pic>/<port>[.unit]``
    form.  Management variants (em0, me0, fxp0) route to kind=``mgmt``.
    ``ae<N>`` → kind=``lag``.  ``lo0`` → kind=``loopback``.
    ``irb.<N>`` → kind=``svi`` with the trailing integer as index.

    A unit is read and not kept: ``ge-0/0/1.54`` classifies exactly
    as ``ge-0/0/1`` does (a ``PortIdentity`` has no place for a unit)
    and the formatter writes none; it also writes ``em<N>`` for every
    management prefix.  So ``format(classify(name))`` is not the
    identity on Junos's own names, and the translator
    (``canonical.port_names.translate_port_names``) does not put them
    to this pair: between two Junos configs a name nobody mapped
    stands as written, and across vendors a unit of a port or of an
    ``ae`` goes where its port goes, with its unit.  What still
    reaches the classifier with a unit on it is a reference to unit 0
    (``lo0.0``, ``ge-0/0/1.0`` -- the interface itself on every other
    platform) and a unit of a loopback.

    The loopback.  Juniper names one loopback interface: "Junos OS
    follows the IP convention of using lo0 as the loopback interface's
    identifier name", and "Only unit 0 is permitted as the master
    loopback interface" (Junos 13.2, *Configuring the Loopback
    Interface*); "You can configure more than just unit 0 for lo0, but
    you must place each additional unit in a separate routing
    instance" (*Loopback Interfaces*, Interfaces Fundamentals).  Where
    another platform has ``Loopback7``, Junos has a unit of ``lo0``,
    so ``lo0.<N>`` reads as loopback N (``lo0`` and ``lo0.0`` as 0):
    read as ``lo0`` itself, every unit of a routing instance came out
    as the one ``Loopback0`` on every other platform.  The other way,
    no name formatted one at a time can place a loopback -- whether
    ``Loopback1`` is ``lo0`` or ``lo0.1`` depends on the config's
    other loopbacks and on its routing instance -- so the translator
    gives this codec every loopback at once (:func:`place_loopbacks`).

    Cross-vendor mesh limitations: Junos's FPC/PIC/port isn't
    structurally equivalent to Cisco's stack/module/port or Arista's
    flat port.  The identity bridge stores all three indices
    (fpc → stack, pic → module, port → port) so Cisco targets can
    partially reconstruct 3-part names.  Flat-naming targets
    (Arista) drop FPC + PIC, keeping only port — may cause
    collisions the rename modal surfaces.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from ...canonical.port_names import LoopbackToPlace, PortIdentity

# ---------------------------------------------------------------------------
# Regex patterns.
# ---------------------------------------------------------------------------

#: Standard media/FPC/PIC/port: ``ge-0/0/24``, ``xe-1/0/0``,
#: ``et-0/0/48``.  Unit suffix ``.0`` is optional.
_STD_RE = re.compile(
    r"^(?P<media>ge|xe|et|fe|mge|xle)-"
    r"(?P<fpc>\d+)/(?P<pic>\d+)/(?P<port>\d+)"
    r"(?:\.(?P<unit>\d+))?$",
    re.IGNORECASE,
)

#: Management/embedded: ``em0``, ``me0``, ``fxp0`` (with optional
#: ``.unit`` suffix).
_MGMT_RE = re.compile(
    r"^(?P<prefix>em|me|fxp)(?P<n>\d+)(?:\.(?P<unit>\d+))?$",
    re.IGNORECASE,
)

#: Logical: ``lo0.0``, ``ae0.0``, ``irb.10``, ``vlan.100``.
_LOOPBACK_RE = re.compile(r"^lo(?P<n>\d+)(?:\.(?P<unit>\d+))?$", re.IGNORECASE)
_LAG_RE = re.compile(r"^ae(?P<n>\d+)(?:\.(?P<unit>\d+))?$", re.IGNORECASE)
_IRB_RE = re.compile(r"^irb\.(?P<n>\d+)$", re.IGNORECASE)

#: A name an entry of the rename map gives a unit of the loopback:
#: ``lo0`` or ``lo0.<N>``.  Five digits: Junos numbers a unit to 16385.
_LO0_UNIT_RE = re.compile(r"^lo0(?:\.0*(?P<unit>\d{1,5}))?$", re.IGNORECASE)

#: The unit of lo0 Junos makes for its internal routing instance: "The
#: internal loopback interface is a particular instance of the loopback
#: interface with the logical unit number 16384" (*Loopback
#: Interfaces*).  No unit from it up is given a loopback here.
_INTERNAL_LOOPBACK_UNIT = 16384

#: The most digits a unit of lo0 is written with.
_UNIT_DIGITS = 5
_VLAN_LOGICAL_RE = re.compile(r"^vlan\.(?P<n>\d+)$", re.IGNORECASE)


#: Media prefix → speed-hint.  Coarse but useful for cross-vendor
#: target prefix selection (Cisco's ``GigabitEthernet`` vs
#: ``TenGigabitEthernet`` etc.).
_MEDIA_TO_SPEED: dict[str, str] = {
    "fe": "fast",
    "ge": "gig",
    "mge": "2.5gig",   # multi-gigabit ethernet (newer EX/QFX)
    # ``xle`` is 40GbE, and only under the QFabric software package on
    # QFX3500 / 3600 / 5100.  It was mapped to 25G here until 2026-10,
    # which made every 25G port translated TO Junos come out as
    # ``xle-...`` -- a name no 25G Junos port has.  25G is ``et-``.
    "xle": "40gig",
    "xe": "10gig",
    "et": "100gig",    # 40G or 100G; Junos uses the same prefix
}


def media_mtu_counts_a_header(device: str) -> bool:
    """Whether the media MTU of the Junos device *device* counts an
    Ethernet header (``MTU_BEYOND_THE_PAYLOAD`` in ``codecs/_helpers.py``).

    A port the classifier reads (``ge-0/0/1``, ``xe-1/0/0``), an
    aggregate (``ae0``), and ``irb``, whose MTU Juniper computes "by
    removing the Ethernet header overhead (6(DMAC)+6(SMAC)+2(EtherType))".
    Not a loopback, a tunnel or a management port: Juniper says "You
    cannot configure an MTU for" ``fxp0``, ``em0``, ``me0`` and loopback
    devices, and a tunnel has no Ethernet header.  Nor a name the
    classifier does not read (``reth0``, ``xe-0/0/6:2``): its number is
    copied as it stands, a known limitation.
    """
    return device == "irb" or media_mtu_counts_a_tag(device)


def media_mtu_counts_a_tag(device: str) -> bool:
    """Whether the media MTU of *device* counts the 802.1Q tag its units
    carry: a port or an aggregate, whose units' ``vlan-id`` needs
    ``vlan-tagging`` on it, for an overhead of "802.1Q/Ethernet version
    2 | 18" (Juniper's encapsulation overhead table).  Not ``irb``: an
    IRB unit routes for a VLAN and is not a tagged unit of the IRB.
    """
    return classify_port_name(device).kind in ("physical", "lag")


#: How many 802.1Q tags a device's media MTU counts, by the tagging
#: statement on the device: one under ``vlan-tagging``, two under
#: ``stacked-vlan-tagging`` ("dual VLAN tags for all logical
#: interfaces"), and two under ``flexible-vlan-tagging``, whose MTU
#: Juniper says to "increase ... to 4 bytes more" than a VLAN-tagged
#: interface's: "The additional 4 bytes accommodates the future
#: addition of a stacked VLAN tag" (Enabling VLAN Tagging).  Four
#: bytes a tag is read from the overhead table (802.1Q/Ethernet
#: version 2, 18, against Ethernet version 2, 14).
TAGGING_STATEMENT_TAGS: dict[str, int] = {
    "vlan-tagging": 1,
    "stacked-vlan-tagging": 2,
    "flexible-vlan-tagging": 2,
}


def classify_port_name(name: str) -> PortIdentity:
    """Parse a Junos port name into a :class:`PortIdentity`."""
    # Standard <media>-<fpc>/<pic>/<port>[.unit]
    m = _STD_RE.match(name)
    if m:
        media = m.group("media").lower()
        return PortIdentity(
            kind="physical",
            stack=int(m.group("fpc")),
            module=int(m.group("pic")),
            port=int(m.group("port")),
            # The literal prefix, for the same-vendor round-trip: the
            # speed hint is lossy (25G / 40G / 100G all share ``et``, and
            # ``xle`` is a QFabric-only spelling of 40G), so re-deriving
            # the prefix from it could rename a Junos port on its way
            # back to Junos.
            meta={"junos_media": media},
            name_speed_hint=_MEDIA_TO_SPEED.get(media, ""),
            original=name,
        )

    # Management (em0 / me0 / fxp0)
    m = _MGMT_RE.match(name)
    if m:
        return PortIdentity(
            kind="mgmt",
            port=int(m.group("n")),
            name_speed_hint="gig",
            original=name,
        )

    # Loopback.  A unit of lo0 is a loopback of its own (see the
    # module docstring); ``lo0.0`` is the loopback ``lo0`` is.
    m = _LOOPBACK_RE.match(name)
    if m:
        number = m.group("n")
        if m.group("unit") is not None and not number.strip("0"):
            number = m.group("unit")
        number = number.lstrip("0") or "0"
        if len(number) > _UNIT_DIGITS:
            # No unit of lo0 (Junos numbers them to 16385), and read
            # as text first: a pasted config can write more digits
            # than ``int`` converts, and that failed the whole job.
            return PortIdentity(kind="unknown", original=name)
        return PortIdentity(
            kind="loopback",
            index=int(number),
            original=name,
        )

    # Aggregated Ethernet = LAG
    m = _LAG_RE.match(name)
    if m:
        return PortIdentity(
            kind="lag",
            index=int(m.group("n")),
            original=name,
        )

    # Integrated Routing and Bridging = SVI-ish
    m = _IRB_RE.match(name)
    if m:
        return PortIdentity(
            kind="svi",
            index=int(m.group("n")),
            original=name,
        )

    # Legacy ``vlan.N`` (older EX platforms).
    m = _VLAN_LOGICAL_RE.match(name)
    if m:
        return PortIdentity(
            kind="svi",
            index=int(m.group("n")),
            original=name,
        )

    return PortIdentity(kind="unknown", original=name)


def format_port_identity(identity: PortIdentity) -> str | None:
    """Render a :class:`PortIdentity` to Junos port-name form.

    Returns None when the identity has no Junos-native representation
    (no media class inferable for the speed hint).
    """
    kind = identity.kind
    if kind == "physical":
        # Speed hint drives media prefix.  Default to ``ge`` when no
        # hint — better than refusing to render altogether.
        speed = identity.name_speed_hint or "gig"
        media = identity.meta.get("junos_media") or {
            "fast": "fe",
            "gig": "ge",
            "2.5gig": "mge",
            "5gig": "mge",     # 5G is less common; folded into mge
            "10gig": "xe",
            "25gig": "et",     # 25G / 40G / 100G / 400G all use et-
            "40gig": "et",
            "100gig": "et",
            "400gig": "et",
        }.get(speed, "ge")
        fpc = identity.stack if identity.stack is not None else 0
        pic = identity.module if identity.module is not None else 0
        port = identity.port
        if port is None:
            return None
        return f"{media}-{fpc}/{pic}/{port}"
    if kind == "breakout":
        # Junos models breakouts as separate physical interfaces
        # (ge-0/0/1:0, ge-0/0/1:1) — not modelled in v1.
        return None
    if kind == "mgmt":
        n = identity.port if identity.port is not None else 0
        return f"em{n}"
    if kind == "loopback":
        # Named one at a time -- a name the config refers to and has
        # no interface for -- a loopback is unit N of the one
        # loopback; the translator places the loopbacks a config HAS
        # with :func:`place_loopbacks`, which knows their routing
        # instances.
        n = identity.index if identity.index is not None else 0
        if n == 0:
            return "lo0"
        if n < _INTERNAL_LOOPBACK_UNIT:
            return f"lo0.{n}"
        return None
    if kind == "lag":
        n = identity.index
        if n is None:
            return None
        return f"ae{n}"
    if kind == "svi":
        n = identity.index
        if n is None:
            return None
        return f"irb.{n}"
    return None


def place_loopbacks(
    loopbacks: Sequence[LoopbackToPlace],
    taken: frozenset[str],
) -> tuple[dict[str, str], dict[str, str]]:
    """Give each loopback of a config its unit of ``lo0``, or a reason.

    Junos has one loopback interface, and the units of it a config may
    use are placed by routing instance (see the module docstring):

    * the global table has one, unit 0 -- ``lo0``.  One loopback there
      is ``lo0`` whatever its number; of several, the one numbered 0
      is, and each of the others is refused.  Of several with none
      numbered 0, every one is refused: which is ``lo0`` is not for a
      translation to choose.
    * a routing instance takes one unit of its own: its one loopback
      numbered N is ``lo0.N``.  Refused: a routing instance's loopbacks
      where it has several, a loopback with no number or numbered 0
      (unit 0 is the global table's), a unit from 16384 up (16384 is
      Junos's internal loopback), and a number two routing instances'
      loopbacks share.

    A name an entry of the rename map gives (*taken*) is not given
    again: a loopback whose unit an entry took is refused.
    """
    taken_units: set[int] = set()
    for target in taken:
        m = _LO0_UNIT_RE.match(target)
        if m:
            taken_units.add(int(m.group("unit") or 0))
    placed: dict[str, str] = {}
    refused: dict[str, str] = {}
    by_instance: dict[str, list[LoopbackToPlace]] = {}
    for loopback in loopbacks:
        by_instance.setdefault(loopback.instance, []).append(loopback)

    in_the_table = by_instance.pop("", [])
    numbered_0 = [lb for lb in in_the_table if lb.number == 0]
    if not in_the_table:
        pass
    elif 0 in taken_units:
        for lb in in_the_table:
            refused[lb.name] = (
                "is in the global routing table, whose one loopback on "
                "Junos, unit 0 of lo0, is the name an entry of the rename "
                "map gives; dropped"
            )
    elif len(in_the_table) == 1:
        placed[in_the_table[0].name] = "lo0"
    elif len(numbered_0) == 1:
        lo0 = numbered_0[0]
        placed[lo0.name] = "lo0"
        for lb in in_the_table:
            if lb is not lo0:
                refused[lb.name] = (
                    f"is a second loopback of the global routing table: "
                    f"Junos has one there, unit 0 of lo0, and {lo0.name!r} "
                    f"is it; dropped -- put its addresses on lo0 unit 0, or "
                    f"its loopback in a routing instance, yourself"
                )
    else:
        for lb in in_the_table:
            refused[lb.name] = (
                f"is one of {len(in_the_table)} loopbacks of the global "
                f"routing table, and Junos has one there, unit 0 of lo0; "
                f"which of them it is is not for the translation to "
                f"choose: dropped -- map that one to lo0"
            )

    alone = [lbs[0] for lbs in by_instance.values() if len(lbs) == 1]
    per_number: dict[int | None, int] = {}
    for lb in alone:
        per_number[lb.number] = per_number.get(lb.number, 0) + 1
    for instance, lbs in by_instance.items():
        if len(lbs) > 1:
            for lb in lbs:
                refused[lb.name] = (
                    f"is one of {len(lbs)} loopbacks of routing instance "
                    f"{instance!r}, and Junos places one unit of lo0 in "
                    f"each routing instance; dropped"
                )
            continue
        lb = lbs[0]
        n = lb.number
        where = f"is in routing instance {instance!r}"
        if n is None:
            refused[lb.name] = (
                f"{where} and has no number to give its unit of lo0; "
                f"dropped -- map it to lo0.<unit>"
            )
        elif n == 0:
            refused[lb.name] = (
                f"{where}, and unit 0 of lo0 is the global table's "
                f"loopback; dropped -- map it to another unit of lo0"
            )
        elif n >= _INTERNAL_LOOPBACK_UNIT:
            refused[lb.name] = (
                f"{where}, and unit {n} of lo0 is not one this "
                f"translation gives ({_INTERNAL_LOOPBACK_UNIT} is Junos's "
                f"internal loopback); dropped -- map it to another unit "
                f"of lo0"
            )
        elif per_number[n] > 1:
            refused[lb.name] = (
                f"{where}, and {per_number[n]} routing instances have a "
                f"loopback numbered {n}, which is one unit of lo0; "
                f"dropped -- map each to a unit of its own"
            )
        elif n in taken_units:
            refused[lb.name] = (
                f"{where}, and lo0.{n} is the name an entry of the "
                f"rename map gives; dropped"
            )
        else:
            placed[lb.name] = f"lo0.{n}"
    return placed, refused

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
    lo0.0                     — loopback (unit form)
    ae0 / ae0.0               — aggregated Ethernet (LAG)
    irb.<N>                   — integrated routing and bridging (SVI-ish)

Strategy:
    v1 focuses on the common ``<media>-<fpc>/<pic>/<port>[.unit]``
    form.  Management variants (em0, me0, fxp0) route to kind=``mgmt``.
    ``ae<N>`` → kind=``lag``.  ``lo0`` → kind=``loopback``.
    ``irb.<N>`` → kind=``svi`` with the trailing integer as index.

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

from ...canonical.port_names import PortIdentity


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
_VLAN_LOGICAL_RE = re.compile(r"^vlan\.(?P<n>\d+)$", re.IGNORECASE)


#: Media prefix → speed-hint.  Coarse but useful for cross-vendor
#: target prefix selection (Cisco's ``GigabitEthernet`` vs
#: ``TenGigabitEthernet`` etc.).
_MEDIA_TO_SPEED: dict[str, str] = {
    "fe": "fast",
    "ge": "gig",
    "mge": "2.5gig",   # multi-gigabit ethernet (newer EX/QFX)
    "xle": "25gig",    # 25G
    "xe": "10gig",
    "et": "100gig",    # 40G or 100G; Junos uses the same prefix
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
            name_speed_hint=_MEDIA_TO_SPEED.get(media, ""),
        )

    # Management (em0 / me0 / fxp0)
    m = _MGMT_RE.match(name)
    if m:
        return PortIdentity(
            kind="mgmt",
            port=int(m.group("n")),
            name_speed_hint="gig",
        )

    # Loopback
    m = _LOOPBACK_RE.match(name)
    if m:
        return PortIdentity(
            kind="loopback",
            index=int(m.group("n")),
        )

    # Aggregated Ethernet = LAG
    m = _LAG_RE.match(name)
    if m:
        return PortIdentity(
            kind="lag",
            index=int(m.group("n")),
        )

    # Integrated Routing and Bridging = SVI-ish
    m = _IRB_RE.match(name)
    if m:
        return PortIdentity(
            kind="svi",
            index=int(m.group("n")),
        )

    # Legacy ``vlan.N`` (older EX platforms).
    m = _VLAN_LOGICAL_RE.match(name)
    if m:
        return PortIdentity(
            kind="svi",
            index=int(m.group("n")),
        )

    return PortIdentity(kind="unknown")


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
        media = {
            "fast": "fe",
            "gig": "ge",
            "2.5gig": "mge",
            "5gig": "mge",     # 5G is less common; folded into mge
            "10gig": "xe",
            "25gig": "xle",
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
        n = identity.index if identity.index is not None else 0
        return f"lo{n}"
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

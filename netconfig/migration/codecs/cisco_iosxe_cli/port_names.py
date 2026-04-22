"""
Cisco IOS-XE CLI port-name classification + formatting.

Pure functions — no parser / renderer state — extracted from
``codec.py`` so the cross-vendor orchestrator in
:mod:`netconfig.migration.canonical.port_names` can import the
translation primitives directly without pulling in the parse/
render machinery.

Recognised port-name forms (all case-insensitive):

Physical interfaces — two, three, or four-part slash notation::

    <Prefix>X/Y         — standalone (module / port),
                          e.g. GigabitEthernet0/1
    <Prefix>X/Y/Z       — stacked (member / module / port),
                          e.g. GigabitEthernet1/0/24
    <Prefix>X/Y/Z/W     — breakout child
                          (member / module / port / lane),
                          e.g. TenGigabitEthernet1/1/1/1 under a
                          FortyGigabitEthernet1/1/1 parent.

Where ``<Prefix>`` encodes speed:

    FastEthernet           → fast
    GigabitEthernet        → gig
    TwoGigabitEthernet     → 2.5gig
    FiveGigabitEthernet    → 5gig
    TenGigabitEthernet     → 10gig
    TwentyFiveGigE         → 25gig
    FortyGigabitEthernet   → 40gig
    HundredGigE            → 100gig
    FourHundredGigE        → 400gig
    AppGigabitEthernet     → gig (Cisco-specific app-hosting virtual)

The speed hint survives cross-vendor translation so target codecs
(MikroTik, Aruba, FortiGate) can pick a speed-appropriate cage
type on their side.

Logical kinds::

    Port-channel<N>     → lag
    Vlan<N>             → svi
    Loopback<N>         → loopback
    Tunnel<N>           → tunnel
    VirtualPortGroup<N> → virtual

Unrecognised names return ``kind="unknown"`` (verbatim fallback
with a warning).
"""

from __future__ import annotations

import re

from ...canonical.port_names import PortIdentity


# ---------------------------------------------------------------------------
# Cisco port-prefix ↔ canonical speed-hint mappings.
# Used by classify_port_name / format_port_identity to round-trip port
# names through the vendor-agnostic PortIdentity without losing the
# speed hint encoded in Cisco's naming scheme.
# Keys are lowercased so the lookup is case-insensitive.
# ---------------------------------------------------------------------------

_CISCO_PREFIX_TO_SPEED: dict[str, str] = {
    "fastethernet": "fast",
    "ethernet": "fast",  # legacy IOS classic; IOS-XE uses FastEthernet
    "gigabitethernet": "gig",
    "twogigabitethernet": "2.5gig",
    "fivegigabitethernet": "5gig",
    "tengigabitethernet": "10gig",
    "twentyfivegige": "25gig",
    "fortygigabitethernet": "40gig",
    "hundredgige": "100gig",
    "fourhundredgige": "400gig",
    "appgigabitethernet": "gig",  # virtual app-hosting, gig-class
}

_CISCO_SPEED_TO_PREFIX: dict[str, str] = {
    "fast": "FastEthernet",
    "gig": "GigabitEthernet",
    "2.5gig": "TwoGigabitEthernet",
    "5gig": "FiveGigabitEthernet",
    "10gig": "TenGigabitEthernet",
    "25gig": "TwentyFiveGigE",
    "40gig": "FortyGigabitEthernet",
    "100gig": "HundredGigE",
    "400gig": "FourHundredGigE",
}


def _breakout_parent_speed(child_speed: str) -> str:
    """Return the parent QSFP speed for a given breakout-lane speed.

    QSFP+ (40G) breaks into 4x10G; QSFP28 (100G) into 4x25G; QSFP56
    (200G) into 4x50G or 2x100G; QSFP-DD (400G) into 4x100G or 8x50G.
    Handles the common cases; unknown child speeds fall back to the
    child speed itself (the parent prefix guess will be approximate).
    """
    return {
        "10gig": "40gig",    # 4x10G → 40G parent
        "25gig": "100gig",   # 4x25G → 100G parent
        "50gig": "200gig",   # 4x50G → 200G parent
        "100gig": "400gig",  # 4x100G → 400G parent
    }.get(child_speed, child_speed)


# ---------------------------------------------------------------------------
# Regex patterns — module-level so they compile once per import
# ---------------------------------------------------------------------------

#: Combined physical-interface pattern.  Matches 2/3/4-part
#: Cisco port names across the full prefix alphabet.  Named groups
#: are (prefix / a / b / c / d) → (speed prefix / stack / module /
#: port / breakout-lane).
_PHYSICAL_RE = re.compile(
    r"^(?P<prefix>FastEthernet|GigabitEthernet|TwoGigabitEthernet|"
    r"FiveGigabitEthernet|TenGigabitEthernet|TwentyFiveGigE|"
    r"FortyGigabitEthernet|HundredGigE|FourHundredGigE|"
    r"AppGigabitEthernet|Ethernet)"
    r"(?P<a>\d+)/(?P<b>\d+)(?:/(?P<c>\d+)(?:/(?P<d>\d+))?)?$",
    re.IGNORECASE,
)

#: Logical-kind patterns — each matches a Cisco logical-interface
#: prefix with a numeric index.  Order is preserved for
#: deterministic classification.
_LOGICAL_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"^Port-channel(\d+)$", "lag"),
    (r"^Vlan(\d+)$", "svi"),
    (r"^Loopback(\d+)$", "loopback"),
    (r"^Tunnel(\d+)$", "tunnel"),
    (r"^VirtualPortGroup(\d+)$", "virtual"),
)
_LOGICAL_RES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p, re.IGNORECASE), k) for p, k in _LOGICAL_PATTERNS
)


def classify_port_name(name: str) -> PortIdentity:
    """Parse a Cisco IOS-XE port name into a :class:`PortIdentity`.

    Pattern dispatch order:
      1. Physical (2/3/4-part slash notation).
      2. Logical kinds (Port-channel / Vlan / Loopback / Tunnel /
         VirtualPortGroup).
      3. Unknown fallback.

    Preserves ``AppGigabitEthernet`` as a meta hint
    (``cisco_app_hosting=1``) so same-vendor round-trip emits the
    correct prefix — cross-vendor targets ignore the hint and fall
    back to their native physical-port formatting.
    """
    # Physical ports — try 4-part (breakout), 3-part (stacked),
    # 2-part (standalone) in that order via the combined regex.
    m = _PHYSICAL_RE.match(name)
    if m:
        speed = _CISCO_PREFIX_TO_SPEED.get(m.group("prefix").lower(), "")
        a = int(m.group("a"))
        b = int(m.group("b"))
        c = int(m.group("c")) if m.group("c") else None
        d = int(m.group("d")) if m.group("d") else None
        # AppGigabitEthernet is a Cisco-specific virtual app-hosting
        # bridge — same coordinates as a physical port but NOT a
        # physical port.  Preserve as meta hint so
        # format_port_identity can restore the Cisco-specific prefix
        # on same-vendor round-trip.  Cross-vendor targets ignore the
        # hint and drop back to their physical-port formatting (or
        # their equivalent virtual concept).
        cisco_meta: dict[str, str] = {}
        if m.group("prefix").lower() == "appgigabitethernet":
            cisco_meta["cisco_app_hosting"] = "1"
        if d is not None:
            # 4-part: breakout child.  a/b/c = parent QSFP, d = lane.
            parent = (
                _CISCO_SPEED_TO_PREFIX.get(
                    _breakout_parent_speed(speed), m.group("prefix")
                )
                + f"{a}/{b}/{c}"
            )
            return PortIdentity(
                kind="breakout",
                stack=a,
                module=b,
                port=c,
                breakout_lane=d,
                breakout_parent=parent,
                name_speed_hint=speed,
                original=name,
                meta=cisco_meta,
            )
        if c is not None:
            # 3-part: stacked (member / module / port).
            return PortIdentity(
                kind="physical",
                stack=a,
                module=b,
                port=c,
                name_speed_hint=speed,
                original=name,
                meta=cisco_meta,
            )
        # 2-part: standalone (module / port).
        return PortIdentity(
            kind="physical",
            module=a,
            port=b,
            name_speed_hint=speed,
            original=name,
            meta=cisco_meta,
        )

    # Logical port kinds.
    for pattern, kind in _LOGICAL_RES:
        m = pattern.match(name)
        if m:
            return PortIdentity(
                kind=kind,  # type: ignore[arg-type]
                index=int(m.group(1)),
                original=name,
            )

    return PortIdentity(kind="unknown", original=name)


def format_port_identity(identity: PortIdentity) -> str | None:
    """Render a :class:`PortIdentity` as a Cisco IOS-XE port name.

    Physical-port prefix selection:
      * ``meta["cisco_app_hosting"]`` forces ``AppGigabitEthernet``
        (same-vendor round-trip of the app-hosting virtual).
      * Otherwise ``name_speed_hint`` → prefix via
        :data:`_CISCO_SPEED_TO_PREFIX`, defaulting to
        ``GigabitEthernet`` when the hint is empty or non-Cisco.

    Breakout children render as the 4-part form using the *lane*
    speed (10G for 4x10G breakout under a 40G parent, 25G for
    4x25G under 100G, etc.).

    Returns None for kinds Cisco IOS-XE can't natively represent
    (``hw_aggregate``, ``mgmt``, ``unknown``).
    """
    if identity.kind == "physical":
        # Cisco-specific meta: app-hosting bridge uses a distinct
        # prefix so same-vendor round-trip preserves it.
        if identity.meta.get("cisco_app_hosting"):
            prefix = "AppGigabitEthernet"
        else:
            prefix = _CISCO_SPEED_TO_PREFIX.get(
                identity.name_speed_hint, "GigabitEthernet"
            )
        if identity.stack is not None:
            return (
                f"{prefix}{identity.stack}/"
                f"{identity.module or 0}/{identity.port or 0}"
            )
        return f"{prefix}{identity.module or 0}/{identity.port or 0}"
    if identity.kind == "breakout":
        # Cisco natively expresses breakout with 4-part notation.
        # Use the *lane* speed prefix (e.g. 10gig for 4x10G under a
        # 40gig parent), falling back to the identity's hint.
        prefix = _CISCO_SPEED_TO_PREFIX.get(
            identity.name_speed_hint, "TenGigabitEthernet"
        )
        return (
            f"{prefix}{identity.stack or 1}/"
            f"{identity.module or 0}/{identity.port or 0}/"
            f"{identity.breakout_lane or 1}"
        )
    if identity.kind == "lag":
        return f"Port-channel{identity.index or 1}"
    if identity.kind == "svi":
        return f"Vlan{identity.index or 1}"
    if identity.kind == "loopback":
        return f"Loopback{identity.index or 0}"
    if identity.kind == "tunnel":
        return f"Tunnel{identity.index or 0}"
    if identity.kind == "virtual":
        return f"VirtualPortGroup{identity.index or 0}"
    # hw_aggregate, mgmt, unknown — no native Cisco representation.
    return None

"""
Arista EOS port-name classification + formatting.

Pure functions — no parser / renderer state — so the cross-vendor
rename orchestrator in :mod:`netcanon.migration.canonical.port_names`
can import the identity bridge directly.

Recognised port-name forms::

    Ethernet<N>              — standalone physical (no speed prefix,
                               speed comes from SFP/transceiver)
    Ethernet<N>/<M>          — QSFP breakout child (M = lane 1-4)
    Management<N>            — management
    Loopback<N>              — loopback
    Vlan<N>                  — SVI
    Port-Channel<N>          — LAG (capitalised, vs Cisco's
                               ``Port-channel``)
    Tunnel<N>                — tunnel

Grammar departures from Cisco IOS-XE:

    * No speed prefix in physical-interface names.  ``GigabitEthernet1/0/1``
      is Cisco; Arista's equivalent is just ``Ethernet1``.  The
      translation path therefore defaults to the generic speed
      class (``gig``) — target codecs that care (Cisco, Aruba) will
      re-derive the actual speed from link-state or default to their
      own conventions.
    * 2-part breakout: ``Ethernet50/1`` maps to a PortIdentity with
      ``port=50`` + ``breakout_lane=1``, kind=``breakout``.
    * ``Port-Channel`` (upper-case C) is distinct from Cisco's
      ``Port-channel``.  The classify path is case-insensitive but the
      format path emits the Arista-canonical capitalisation.
"""

from __future__ import annotations

import re

from ...canonical.port_names import PortIdentity


# ---------------------------------------------------------------------------
# Regex patterns — module-level so they compile once per import.
# ---------------------------------------------------------------------------

#: Physical Ethernet.  Matches ``Ethernet1`` (1-part) and
#: ``Ethernet50/1`` (2-part breakout).  ``Management<N>`` is a
#: physical-but-mgmt subvariant handled via a separate pattern.
_ETHERNET_RE = re.compile(
    r"^Ethernet(?P<a>\d+)(?:/(?P<b>\d+))?$",
    re.IGNORECASE,
)
_MGMT_RE = re.compile(r"^Management(?P<a>\d+)$", re.IGNORECASE)

#: Logical-interface patterns.  Each maps the index-capturing group
#: to the canonical kind string.
_LOGICAL_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"^Port-Channel(\d+)$", "lag"),
    (r"^Vlan(\d+)$", "svi"),
    (r"^Loopback(\d+)$", "loopback"),
    (r"^Tunnel(\d+)$", "tunnel"),
)
_LOGICAL_RES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p, re.IGNORECASE), k) for p, k in _LOGICAL_PATTERNS
)


def classify_port_name(name: str) -> PortIdentity:
    """Parse an Arista EOS port name into a :class:`PortIdentity`.

    Pattern dispatch order:
      1. Ethernet<N> / Ethernet<N>/<M>
      2. Management<N>
      3. Port-Channel<N> / Vlan<N> / Loopback<N> / Tunnel<N>
      4. Unknown fallback (verbatim).
    """
    # Physical Ethernet — 1 or 2-part.
    m = _ETHERNET_RE.match(name)
    if m:
        a = int(m.group("a"))
        b = m.group("b")
        if b is not None:
            # Breakout child — 2-part slash notation.  Parent is the
            # bare ``Ethernet<N>`` name without the lane suffix.
            return PortIdentity(
                kind="breakout",
                port=a,
                breakout_lane=int(b),
                breakout_parent=f"Ethernet{a}",
                name_speed_hint="gig",   # default class; real speed from SFP
            )
        return PortIdentity(
            kind="physical",
            port=a,
            name_speed_hint="gig",
        )

    # Management — physical-but-mgmt.
    m = _MGMT_RE.match(name)
    if m:
        return PortIdentity(
            kind="mgmt",
            port=int(m.group("a")),
            name_speed_hint="gig",
        )

    # Logical interfaces — LAG / SVI / loopback / tunnel.
    for regex, kind in _LOGICAL_RES:
        lm = regex.match(name)
        if lm:
            return PortIdentity(
                kind=kind,
                index=int(lm.group(1)),
            )

    # Unknown — pass through verbatim.  Cross-vendor targets will
    # treat this as "can't represent" and auto-drop with a warning.
    return PortIdentity(kind="unknown")


def format_port_identity(identity: PortIdentity) -> str | None:
    """Render a :class:`PortIdentity` to Arista EOS port-name form.

    Returns None when the identity has no Arista-native representation
    (e.g. a kind EOS doesn't have).  Cross-vendor callers treat None
    as "target can't represent this" and surface a warning via the
    rename orchestrator's auto-drop path.

    Cross-vendor translation simplification: EOS uses flat
    ``Ethernet<N>`` so when a source identity has stack + module +
    port (Cisco-style), we drop the stack + module and use only the
    port.  Operators mapping a 5-member-stack Cisco config to Arista
    will get collisions they'll resolve manually via the rename modal
    — the auto-heuristic surfaces the collisions rather than
    silently overlaying.
    """
    kind = identity.kind
    if kind == "physical":
        # EOS uses flat ``Ethernet<N>``.  Prefer ``port``; if missing,
        # try ``module``; if still missing, identity isn't renderable.
        n = identity.port if identity.port is not None else identity.module
        if n is None:
            return None
        return f"Ethernet{n}"
    if kind == "breakout":
        # 2-part form.  Parent index is the ``port`` or extracted from
        # ``breakout_parent`` (e.g. ``FortyGigabitEthernet1/1/1`` →
        # parent_port=1, lane=breakout_lane).  For EOS the parent is
        # just a number.
        lane = identity.breakout_lane
        if lane is None:
            return None
        parent_port = identity.port
        if parent_port is None:
            # Cross-vendor source (Cisco) had ``breakout_parent``
            # like ``FortyGigabitEthernet1/1/1`` — pull the trailing
            # digit group as the parent port.
            parent = identity.breakout_parent
            m = re.search(r"(\d+)$", parent)
            if m:
                parent_port = int(m.group(1))
        if parent_port is None:
            return None
        return f"Ethernet{parent_port}/{lane}"
    if kind == "mgmt":
        n = identity.port or identity.module or 1
        return f"Management{n}"
    if kind == "lag":
        n = identity.index
        if n is None:
            return None
        return f"Port-Channel{n}"
    if kind == "svi":
        n = identity.index
        if n is None:
            return None
        return f"Vlan{n}"
    if kind == "loopback":
        n = identity.index
        if n is None:
            return None
        return f"Loopback{n}"
    if kind == "tunnel":
        n = identity.index
        if n is None:
            return None
        return f"Tunnel{n}"
    # unknown / unsupported on EOS — let the caller decide (usually
    # auto-drop with a warning).
    return None

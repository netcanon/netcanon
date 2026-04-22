"""
FortiGate port-name classification + formatting.

Pure functions — no parser / renderer state — extracted from
``codec.py`` so the cross-vendor orchestrator in
:mod:`netconfig.migration.canonical.port_names` can import the
translation primitives directly without pulling in the parse/
render machinery.

FortiGate naming is unusual compared with the other vendors in
two ways:

1. **Role-coded prefixes** — ``wan1`` / ``wan2`` / ``lan`` /
   ``lanN`` / ``internal`` / ``internalN`` / ``dmz`` — a given
   port's NAME encodes its intended role, not its physical
   location.  Moving a physical port from ``lan1`` to ``wan2`` is
   a rename, not a jumper re-pin.  The role is carried across
   same-vendor round-trip via the ``fortigate_role`` meta hint on
   :class:`PortIdentity` so it survives translation back to
   FortiGate.

2. **Hardware-switch aggregates** — on small FortiGate appliances
   (40F / 60F / 80F) the ``internal`` interface is a L2 switch
   fabric unifying N physical ports (``internal1..7``).  This is
   classified as ``kind="hw_aggregate"`` — no other vendor has a
   direct equivalent, so cross-vendor translation drops it back
   to ``unknown`` via the target codec's formatter.

User-named VLAN subinterfaces (``VL_100``, ``VLAN-DMZ``) and
user-named LAGs (``LAG_INTERNAL``) classify as ``unknown`` —
there's no deterministic mapping from operator-chosen names to a
cross-vendor convention.  The canonical tree keeps them verbatim;
the Tier 2 rename map lets the operator supply explicit
overrides.
"""

from __future__ import annotations

import re

from ...canonical.port_names import PortIdentity


# ---------------------------------------------------------------------------
# Regex patterns — module-level so they compile once per import
# ---------------------------------------------------------------------------

#: Generic port numbering: ``port1``, ``port2`` (FG100F+ default).
_PORT_NUM_RE = re.compile(r"^port(\d+)$", re.IGNORECASE)

#: Role-coded physical: ``wan1``, ``wan``, ``dmz``, ``mgmt``, ``ha``,
#: ``modem``, ``fortilink`` (numeric suffix optional).
_ROLE_RE = re.compile(
    r"^(wan|dmz|mgmt|ha|modem|fortilink)(\d+)?$", re.IGNORECASE
)

#: Bare single-letter FortiLink default ports.  FG-60F / FG-61F ship
#: with two ports literally named ``a`` and ``b`` — these are the
#: NPU-connected FortiLink defaults documented in Fortinet's fast-path
#: architecture doc (docs.fortinet.com/document/fortigate/7.6.6/
#: hardware-acceleration/758378/fortigate-60f-and-61f-fast-path-
#: architecture).  Classified as physical with ``fortigate_role=fortilink``
#: so cross-vendor targets see them as regular ports; the letter is
#: stashed in ``meta["fortigate_fortilink_letter"]`` so same-vendor
#: round-trip preserves the original name.
_FORTILINK_LETTER_RE = re.compile(r"^([ab])$", re.IGNORECASE)

#: Numbered ``lan``/``internal`` (physical member of hw-switch
#: aggregate or standalone port).  Bare forms (``lan`` / ``internal``)
#: classify as hw_aggregate and are matched via string equality, not
#: these regexes.
_LAN_NUM_RE = re.compile(r"^lan(\d+)$", re.IGNORECASE)
_INTERNAL_NUM_RE = re.compile(r"^internal(\d+)$", re.IGNORECASE)

#: Tunnels: ``gre<n>`` (ssl.root is matched by string equality).
_GRE_RE = re.compile(r"^gre(\d+)$", re.IGNORECASE)

#: Loopback.
_LOOPBACK_RE = re.compile(r"^loopback(\d+)$", re.IGNORECASE)


def classify_port_name(name: str) -> PortIdentity:
    """Parse a FortiGate interface name into a :class:`PortIdentity`.

    Pattern dispatch order:
      1. ``portN`` generic numbering (FG100+).
      2. Role-coded (wan/dmz/mgmt/ha/modem/fortilink).
      3. Bare ``lan`` / ``internal`` → hw_aggregate.
      4. Numbered ``lanN`` / ``internalN`` → physical with role meta.
      5. Tunnels (ssl.root, greN).
      6. Loopback.
      7. Everything else → unknown (operator-named VLANs / LAGs).

    Args:
        name: Source-side FortiGate interface name.

    Returns:
        A populated :class:`PortIdentity` with ``fortigate_role`` /
        ``fortigate_tunnel`` meta hints for same-vendor round-trip.
        ``kind="unknown"`` when no pattern matches.
    """
    stripped = name.strip()

    # Generic port numbering: port1, port2, …
    m = _PORT_NUM_RE.match(stripped)
    if m:
        return PortIdentity(
            kind="physical",
            port=int(m.group(1)),
            meta={"fortigate_role": "port"},
            original=name,
        )

    # Role-coded physical ports: wan1, wan2, dmz, mgmt, etc.
    m = _ROLE_RE.match(stripped)
    if m:
        role = m.group(1).lower()
        port_num = int(m.group(2)) if m.group(2) else 1
        kind = "mgmt" if role == "mgmt" else "physical"
        return PortIdentity(
            kind=kind,
            port=port_num,
            meta={"fortigate_role": role},
            original=name,
        )

    # Bare single-letter FortiLink defaults (FG-60F / FG-61F ship with
    # two ports named ``a`` and ``b``).  Stash the letter so the
    # formatter can reproduce it for same-vendor round-trip; cross-
    # vendor targets see a plain physical port via the fortilink role.
    m = _FORTILINK_LETTER_RE.match(stripped)
    if m:
        return PortIdentity(
            kind="physical",
            port=1 + (ord(m.group(1).lower()) - ord("a")),
            meta={
                "fortigate_role": "fortilink",
                "fortigate_fortilink_letter": m.group(1).lower(),
            },
            original=name,
        )

    # ``lan`` without suffix — hardware-switch aggregate on small
    # FortiGates.  ``lan<N>`` with suffix — physical member of
    # either a hw-switch aggregate or a standalone routed port,
    # depending on chassis.  Classify bare form as hw_aggregate so
    # the warning flags the migration-sensitive case; the numbered
    # form is classified as plain physical.
    if stripped.lower() == "lan":
        return PortIdentity(
            kind="hw_aggregate",
            aggregate_kind="hardware-switch",
            meta={"fortigate_role": "lan"},
            original=name,
        )
    m = _LAN_NUM_RE.match(stripped)
    if m:
        return PortIdentity(
            kind="physical",
            port=int(m.group(1)),
            meta={"fortigate_role": "lan"},
            original=name,
        )

    # ``internal`` bare = hardware-switch aggregate; ``internalN`` =
    # physical member.
    if stripped.lower() == "internal":
        return PortIdentity(
            kind="hw_aggregate",
            aggregate_kind="hardware-switch",
            meta={"fortigate_role": "internal"},
            original=name,
        )
    m = _INTERNAL_NUM_RE.match(stripped)
    if m:
        return PortIdentity(
            kind="physical",
            port=int(m.group(1)),
            meta={"fortigate_role": "internal"},
            original=name,
        )

    # Tunnels: ssl.root, ssl.web, greN.  SSL-VPN root tunnel is a
    # special-case literal.
    if stripped.lower() == "ssl.root":
        return PortIdentity(
            kind="tunnel",
            meta={"fortigate_tunnel": "ssl"},
            original=name,
        )
    m = _GRE_RE.match(stripped)
    if m:
        return PortIdentity(
            kind="tunnel",
            index=int(m.group(1)),
            meta={"fortigate_tunnel": "gre"},
            original=name,
        )

    # Loopback.
    m = _LOOPBACK_RE.match(stripped)
    if m:
        return PortIdentity(
            kind="loopback", index=int(m.group(1)), original=name
        )

    # User-named VLAN subinterfaces (VL_100, VLAN-*, etc.) and
    # user-named LAGs (LAG_*, etc.) fall through as unknown — no
    # deterministic classification possible from the name alone.
    return PortIdentity(kind="unknown", original=name)


def format_port_identity(identity: PortIdentity) -> str | None:
    """Render a :class:`PortIdentity` as a FortiGate interface name.

    For physical ports we prefer the ``fortigate_role`` meta hint
    if the source identity carried one (same-vendor round-trip
    preserves wan/lan/internal/dmz naming).  Cross-vendor
    identities without a role hint fall back to ``port<N>`` which
    is the neutral generic form on FG100+ hardware.

    Returns None for kinds FortiGate can't deterministically emit
    (svi, virtual, breakout, unknown) — user picks the
    ``VL_XXX`` / ``LAG_XXX`` name explicitly and the Tier 2 rename
    map carries that choice.
    """
    if identity.kind == "physical":
        role = identity.meta.get("fortigate_role", "port")
        # Same-vendor round-trip for FG-60F bare ``a``/``b`` FortiLink
        # ports: if the source carried a letter hint, emit it back.
        # Cross-vendor sources won't populate the letter, so the
        # regular numeric path handles the generic ``fortilink1`` /
        # ``fortilink2`` case.
        letter = identity.meta.get("fortigate_fortilink_letter")
        if role == "fortilink" and letter:
            return letter
        if role == "port":
            return f"port{identity.port or 1}"
        if identity.port and identity.port > 1:
            return f"{role}{identity.port}"
        # Role-only bare form (e.g. wan = wan1, lan = lan).
        return role if role in ("lan",) else f"{role}{identity.port or 1}"
    if identity.kind == "hw_aggregate":
        # Only FortiGate has this concept.  Same-vendor target
        # round-trips the role name; cross-vendor targets would
        # have returned None via the other codec's formatter so
        # we never reach here with a foreign identity.
        role = identity.meta.get("fortigate_role", "internal")
        return role
    if identity.kind == "lag":
        # FortiGate LAGs are user-named — no deterministic form.
        # Return a sensible default (``LAG<N>``); operator can
        # override via rename_map.
        return f"LAG{identity.index or 1}"
    if identity.kind == "loopback":
        return f"loopback{identity.index or 0}"
    if identity.kind == "tunnel":
        kind = identity.meta.get("fortigate_tunnel")
        if kind == "ssl":
            return "ssl.root"
        if kind == "gre":
            return f"gre{identity.index or 1}"
        return f"gre{identity.index or 1}"
    if identity.kind == "mgmt":
        return "mgmt"
    # svi, virtual, breakout, unknown — no deterministic FortiGate
    # form (user picks the VL_XXX / LAG_XXX name).
    return None

"""
Aruba AOS-CX port-name classification + formatting.

Pure functions — no parser / renderer state — so the cross-vendor
orchestrator in :mod:`netcanon.migration.canonical.port_names` can import
the translation primitives directly without pulling in the parse/render
machinery.  Mirrors the shape of
:mod:`netcanon.migration.codecs.cisco_nxos.port_names`.

The defining AOS-CX quirk: interface names are **multi-token** — the
type keyword and the numeric index are space-separated (``interface vlan
11``, ``interface lag 1``, ``interface loopback 0``), unlike the
single-token names every other CLI codec uses (NX-OS ``Vlan11`` / Arista
``Ethernet1``).  Physical ports are a ``member/slot/port`` triple
(``1/1/1``).  The canonical interface ``name`` therefore carries the
space (e.g. ``"vlan 11"``); this module is the single place that knows
how to split it back into a :class:`PortIdentity`.

Recognised port-name forms (matching is case-insensitive)::

    <m>/<s>/<p>            — physical (member / slot / port), e.g. 1/1/1
    vlan <N>               → svi
    lag <N>                → lag
    loopback <N>           → loopback
    vxlan <N>              → vtep      (Phase 4 — classified now)
    mgmt                   → mgmt      (the single OOBM port; no index)

Deferred (not classified in v1):

* The ``<m>/<s>/<p>:<lane>`` breakout-lane form — classifies as
  ``unknown`` (verbatim fallback) until a fixture needs it.

Unrecognised names return ``kind="unknown"`` (verbatim fallback with a
warning).
"""

from __future__ import annotations

import re

from ...canonical.port_names import PortIdentity

# ---------------------------------------------------------------------------
# Regex patterns — module-level so they compile once per import
# ---------------------------------------------------------------------------

#: Physical-interface pattern — the AOS-CX ``member/slot/port`` triple.
#: Named groups map to (member, slot, port); member -> PortIdentity.stack,
#: slot -> module, port -> port.
_PHYSICAL_RE = re.compile(
    r"^(?P<member>\d+)/(?P<slot>\d+)/(?P<port>\d+)$",
)

#: Logical-kind patterns — each matches a ``<keyword> <index>`` form with
#: the keyword and index space-separated.  Order preserved for
#: deterministic classification.
_LOGICAL_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"^vlan\s+(\d+)$", "svi"),
    (r"^lag\s+(\d+)$", "lag"),
    (r"^loopback\s+(\d+)$", "loopback"),
    (r"^vxlan\s+(\d+)$", "vtep"),
)
_LOGICAL_RES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p, re.IGNORECASE), k) for p, k in _LOGICAL_PATTERNS
)

#: The single out-of-band management port — no numeric index.
_MGMT_RE = re.compile(r"^mgmt$", re.IGNORECASE)


def classify_port_name(name: str) -> PortIdentity:
    """Parse an Aruba AOS-CX port name into a :class:`PortIdentity`.

    Dispatch order: physical (``m/s/p`` triple) → logical kinds (``vlan``
    / ``lag`` / ``loopback`` / ``vxlan``) → ``mgmt`` → unknown fallback.
    """
    stripped = name.strip()

    m = _PHYSICAL_RE.match(stripped)
    if m:
        return PortIdentity(
            kind="physical",
            stack=int(m.group("member")),
            module=int(m.group("slot")),
            port=int(m.group("port")),
            original=name,
        )

    for pattern, kind in _LOGICAL_RES:
        lm = pattern.match(stripped)
        if lm:
            return PortIdentity(
                kind=kind,  # type: ignore[arg-type]
                index=int(lm.group(1)),
                original=name,
            )

    if _MGMT_RE.match(stripped):
        return PortIdentity(kind="mgmt", original=name)

    return PortIdentity(kind="unknown", original=name)


def format_port_identity(identity: PortIdentity) -> str | None:
    """Render a :class:`PortIdentity` as an Aruba AOS-CX port name.

    Physical ports re-emit the ``member/slot/port`` triple (a
    cross-vendor identity that carries only ``module``/``port`` — e.g. an
    NX-OS ``Ethernet1/1`` — defaults the member to ``1``).  Logical kinds
    re-emit the space-separated ``<keyword> <index>`` form.  ``mgmt`` is
    the constant OOBM port name.

    Returns ``None`` for kinds AOS-CX has no native v1 representation for
    (``breakout`` / ``tunnel`` / ``hw_aggregate`` / ``unknown``) — the
    orchestrator leaves the name verbatim and emits a review warning.
    """
    if identity.kind == "physical":
        member = identity.stack if identity.stack is not None else 1
        return f"{member}/{identity.module or 1}/{identity.port or 0}"
    if identity.kind == "svi":
        return f"vlan {identity.index if identity.index is not None else 1}"
    if identity.kind == "lag":
        return f"lag {identity.index if identity.index is not None else 1}"
    if identity.kind == "loopback":
        return f"loopback {identity.index if identity.index is not None else 0}"
    if identity.kind == "vtep":
        # AOS-CX models the VTEP as ``interface vxlan <N>`` (Phase 4).
        return f"vxlan {identity.index if identity.index is not None else 1}"
    if identity.kind == "mgmt":
        # AOS-CX has exactly one OOBM port, named ``mgmt`` (no index).
        return "mgmt"
    if identity.kind == "virtual":
        # Closest AOS-CX analogue for a vendor-specific virtual port.
        return f"loopback {identity.index or 0}"
    # breakout / tunnel / hw_aggregate / unknown — no native AOS-CX form.
    return None

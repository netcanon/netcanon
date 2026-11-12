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


def is_a_sub_interface(name: str) -> bool:
    """Whether *name* is a sub-interface of a port or a LAG:
    ``<parent>.<n>``, the part before the dot a name the classifier
    reads as a port or a LAG (``1/1/1.201``, ``lag 1.201``).

    HPE documents sub-interfaces of physical ports, of split children
    of physical ports and of L3 LAGs.  A split child's
    (``1/1/1:1.201``) is not read as one: the classifier does not read
    the port's name, so the tag is not read onto it, and the name is
    left to the port translator, which says so.  The parser reads a
    tag, and the renderer writes one, under such a name only.
    """
    port, dot, unit = name.rpartition(".")
    return (
        bool(dot) and unit.isascii() and unit.isdigit()
        and classify_port_name(port).kind in ("physical", "lag")
    )


def format_port_identity(identity: PortIdentity) -> str | None:
    """Render a :class:`PortIdentity` as an Aruba AOS-CX port name.

    Physical ports re-emit the ``member/slot/port`` triple (a
    cross-vendor identity that carries only ``module``/``port`` — e.g. an
    NX-OS ``Ethernet1/1`` — defaults the member to ``1``).  Logical kinds
    re-emit the space-separated ``<keyword> <index>`` form.  ``mgmt`` is
    the constant OOBM port name.

    AOS-CX counts a member, a slot, a port and a LAG from 1
    (:func:`vsf_switch_port_name` refuses a member or a port below 1;
    HPE's link-aggregation guides give a LAG id of "1 to 256"), so a
    number of 0 -- a Junos FPC 0, port 0 or ``ae0``, an IOS XR slot 0,
    an IOS-XE router's slot 0 -- is written as 1, as a slot of 0
    already was.  A port of member 0 beside the same port of member 1
    then has one name, which the run reports as two source names on
    one name of the output (the job is ``partial``).  Up to 0.7.7 such
    a port was written ``0/1/<n>`` or ``<m>/1/0``, and such a LAG
    ``lag 0``: names no AOS-CX switch has, in jobs that said
    ``completed``.

    Returns ``None`` for kinds AOS-CX has no native v1 representation for
    (``breakout`` / ``tunnel`` / ``hw_aggregate`` / ``unknown``) — the
    orchestrator leaves the name verbatim and emits a review warning.
    """
    if identity.kind == "physical":
        return f"{identity.stack or 1}/{identity.module or 1}/{identity.port or 1}"
    if identity.kind == "svi":
        return f"vlan {identity.index if identity.index is not None else 1}"
    if identity.kind == "lag":
        return f"lag {identity.index or 1}"
    if identity.kind == "loopback":
        return f"loopback {identity.index if identity.index is not None else 0}"
    if identity.kind == "vtep":
        # AOS-CX models the VTEP as ``interface vxlan <N>`` (Phase 4).
        return f"vxlan {identity.index if identity.index is not None else 1}"
    if identity.kind == "mgmt":
        # AOS-CX has exactly one OOBM port, named ``mgmt`` (no index).
        return "mgmt"
    # breakout / tunnel / hw_aggregate / unknown — no native AOS-CX form;
    # nor another vendor's virtual interface: a RouterOS bridge or an
    # IOS-XE VirtualPortGroup is no loopback, and the LAN address of
    # one was written on ``loopback 0``.
    return None


def vsf_switch_port_name(*, member: int, port: int) -> str:
    """Compose the name a CX 6200 or CX 6300 gives a physical port.

    This is the naming GRAMMAR of those two series, written down once:
    ``<member>/1/<port>``.  It is used by
    :mod:`netcanon.migration.device_models` to render a model's port
    inventory, and is deliberately separate from
    :func:`format_port_identity`, which guesses a name from the shape
    of another vendor's name and does not know the model.

    HPE's VSF guide for the 6200 and 6300 (AOS-CX 10.18, "Identifying
    switch ports and interfaces") states it: a port is "identified
    using the format: member/slot/port"; "If the switch is not a member
    of a VSF stack, then member is 1"; the slot is "Always 1", since
    the switch is not modular; and the port is the "Physical number of
    a port on the switch" -- "the logical interface 1/1/4 in software
    is associated with physical port 4 on member 1".

    * ``member`` is the VSF member number.  A switch that is in no
      stack is member 1, so the segment is never absent.
    * The slot is always 1.  A modular AOS-CX switch is not described
      here.
    * ``port`` is 1-based.

    Args:
        member: The VSF member number.
        port: The 1-based port number.

    Returns:
        The port name, e.g. ``1/1/4``, ``2/1/25``.

    Raises:
        ValueError: *member* or *port* is below 1.
    """
    if member < 1:
        raise ValueError(f"AOS-CX member numbers are 1-based; got {member}")
    if port < 1:
        raise ValueError(f"AOS-CX port numbers are 1-based; got {port}")
    return f"{member}/1/{port}"

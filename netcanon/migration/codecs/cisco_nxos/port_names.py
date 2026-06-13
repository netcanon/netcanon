"""
Cisco NX-OS port-name classification + formatting.

Pure functions — no parser / renderer state — so the cross-vendor
orchestrator in :mod:`netcanon.migration.canonical.port_names` can import
the translation primitives directly without pulling in the parse/render
machinery.  Mirrors the shape of
:mod:`netcanon.migration.codecs.cisco_iosxe_cli.port_names`.

Recognised port-name forms (NX-OS emits them in the exact case shown;
matching is case-insensitive):

Physical interfaces — two- or three-part slash notation::

    Ethernet<a>/<b>        — standalone (module / port),
                             e.g. Ethernet1/24  (Nexus 9000 standard)
    Ethernet<a>/<b>/<c>    — slot / module / port,
                             e.g. Ethernet101/1/1  (N7K line-card slot)

Unlike Cisco IOS-XE, **NX-OS uses a single ``Ethernet`` prefix for every
speed** (1G/10G/40G/100G), so :attr:`PortIdentity.name_speed_hint` is
always empty on classify and ignored on format.  Cross-vendor inbound
speed hints (IOS-XE ``GigabitEthernet`` etc.) are therefore dropped on
the NX-OS side — the formatter always emits ``Ethernet<a>/<b>``.

Logical kinds::

    port-channel<N>        → lag
    Vlan<N>                → svi
    loopback<N>            → loopback
    mgmt<N>                → mgmt   (always re-emitted as ``mgmt0``)
    nve<N>                 → vtep   (always re-emitted as ``nve1``)

Deferred (not classified in v1):

* ``Ethernet1/1/1`` breakout-lane form — structurally ambiguous with the
  N7K three-part slot form; both classify as ``physical`` here.  A
  dedicated breakout model lands with a fixture that needs it.

Unrecognised names return ``kind="unknown"`` (verbatim fallback with a
warning).
"""

from __future__ import annotations

import re

from ...canonical.port_names import PortIdentity

# ---------------------------------------------------------------------------
# Regex patterns — module-level so they compile once per import
# ---------------------------------------------------------------------------

#: Physical-interface pattern.  Two- or three-part slash notation; NX-OS
#: has no speed prefix alphabet, so the leading token is always
#: ``Ethernet``.  Named groups (a / b / c) map to (module, port) for the
#: two-part form or (stack, module, port) for the three-part form.
_PHYSICAL_RE = re.compile(
    r"^Ethernet(?P<a>\d+)/(?P<b>\d+)(?:/(?P<c>\d+))?$",
    re.IGNORECASE,
)

#: Logical-kind patterns — each matches an NX-OS logical-interface
#: prefix with a numeric index.  Order preserved for deterministic
#: classification.
_LOGICAL_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"^port-channel(\d+)$", "lag"),
    (r"^Vlan(\d+)$", "svi"),
    (r"^loopback(\d+)$", "loopback"),
    (r"^mgmt(\d+)$", "mgmt"),
    (r"^nve(\d+)$", "vtep"),
)
_LOGICAL_RES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p, re.IGNORECASE), k) for p, k in _LOGICAL_PATTERNS
)


def classify_port_name(name: str) -> PortIdentity:
    """Parse a Cisco NX-OS port name into a :class:`PortIdentity`.

    Dispatch order: physical (2/3-part slash) → logical kinds
    (port-channel / Vlan / loopback / mgmt) → unknown fallback.
    """
    m = _PHYSICAL_RE.match(name)
    if m:
        a = int(m.group("a"))
        b = int(m.group("b"))
        c = int(m.group("c")) if m.group("c") else None
        if c is not None:
            # Three-part slot / module / port (N7K line-card form).
            return PortIdentity(
                kind="physical",
                stack=a,
                module=b,
                port=c,
                original=name,
            )
        # Two-part module / port (Nexus 9000 standard).
        return PortIdentity(
            kind="physical",
            module=a,
            port=b,
            original=name,
        )

    for pattern, kind in _LOGICAL_RES:
        lm = pattern.match(name)
        if lm:
            return PortIdentity(
                kind=kind,  # type: ignore[arg-type]
                index=int(lm.group(1)),
                original=name,
            )

    return PortIdentity(kind="unknown", original=name)


def format_port_identity(identity: PortIdentity) -> str | None:
    """Render a :class:`PortIdentity` as a Cisco NX-OS port name.

    NX-OS emits a single ``Ethernet`` prefix regardless of speed, so the
    ``name_speed_hint`` carried by cross-vendor identities is ignored.
    ``mgmt`` always renders as the constant ``mgmt0`` (NX-OS has exactly
    one out-of-band management port).

    Returns ``None`` for kinds NX-OS has no native v1 representation for
    (``breakout`` / ``tunnel`` / ``hw_aggregate`` / ``unknown``) — the
    orchestrator leaves the name verbatim and emits a review warning.
    """
    if identity.kind == "physical":
        if identity.stack is not None:
            return (
                f"Ethernet{identity.stack}/"
                f"{identity.module or 0}/{identity.port or 0}"
            )
        return f"Ethernet{identity.module or 0}/{identity.port or 0}"
    if identity.kind == "lag":
        return f"port-channel{identity.index or 1}"
    if identity.kind == "svi":
        return f"Vlan{identity.index or 1}"
    if identity.kind == "loopback":
        return f"loopback{identity.index or 0}"
    if identity.kind == "mgmt":
        # NX-OS has exactly one mgmt port, always mgmt0.
        return "mgmt0"
    if identity.kind == "vtep":
        # NX-OS has exactly one VTEP, always nve1 (grammar survey § 4.6).
        return "nve1"
    if identity.kind == "virtual":
        # Closest NX-OS analogue for a vendor-specific virtual port.
        return f"loopback{identity.index or 0}"
    # breakout / tunnel / hw_aggregate / unknown — no native NX-OS form.
    return None

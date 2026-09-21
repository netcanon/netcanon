"""
Dell SmartFabric OS10 port-name classification + formatting.

Pure functions — no parser / renderer state — so the cross-vendor
orchestrator in :mod:`netcanon.migration.canonical.port_names` can import
the translation primitives directly without pulling in the parse/render
machinery.  Mirrors the shape of
:mod:`netcanon.migration.codecs.cisco_nxos.port_names`.

Recognised port-name forms (OS10 emits them lower-case; matching is
case-insensitive)::

    ethernet<n>/<s>/<p>      — physical, three-segment node/slot/port
    ethernet<n>/<s>/<p>:<l>  — breakout lane of a broken-out QSFP
    mgmt<n>/<s>/<p>          — out-of-band management port
    port-channel<N>          → lag
    vlan<N>                  → svi
    loopback<N>              → loopback

The three-segment physical form maps onto :class:`PortIdentity` the same
way Aruba AOS-CX's ``member/slot/port`` triple does — node → ``stack``,
slot → ``module``, port → ``port`` — so an OS10 ``ethernet1/1/15`` and an
AOS-CX ``1/1/15`` describe the same physical coordinate and translate
between each other without either codec knowing the other exists.

**Breakout lanes are classified, not deferred.**  NX-OS leaves its
``Ethernet1/1/1`` form ``physical`` because three-part slash notation is
structurally ambiguous there (N7K line-card slot vs breakout lane).  OS10
has no such ambiguity: the lane is a ``:<n>`` suffix on a name that
already carries all three positional segments, so ``ethernet1/1/10:1`` is
unambiguously lane 1 of ``ethernet1/1/10``.  74 subport names appear
across the OS10 capture corpus, so this is a real form, not a
hypothetical.  ``format_port_identity`` still returns ``None`` for
``kind="breakout"`` — the identity is recorded honestly and the
orchestrator raises a review warning rather than inventing a target name.

Unrecognised names return ``kind="unknown"`` (verbatim fallback with a
warning).
"""

from __future__ import annotations

import re

from ...canonical.port_names import PortIdentity

# ---------------------------------------------------------------------------
# Regex patterns — module-level so they compile once per import
# ---------------------------------------------------------------------------

#: Physical / breakout port.  ``ethernet<node>/<slot>/<port>`` with an
#: optional ``:<lane>`` breakout suffix.  The optional lane group is what
#: separates a whole port from one lane of a broken-out QSFP.
_PHYSICAL_RE = re.compile(
    r"^ethernet(?P<node>\d+)/(?P<slot>\d+)/(?P<port>\d+)(?::(?P<lane>\d+))?$",
    re.IGNORECASE,
)

#: Out-of-band management port — same three-segment shape as a physical
#: port but a distinct role, so it classifies ``mgmt`` rather than
#: ``physical`` (OS10 ships exactly one, conventionally ``mgmt1/1/1``).
_MGMT_RE = re.compile(r"^mgmt(\d+)/(\d+)/(\d+)$", re.IGNORECASE)

#: Logical-kind patterns — each matches an OS10 logical-interface prefix
#: with a numeric index.  Order preserved for deterministic
#: classification.  ``port-channel`` precedes nothing that could shadow
#: it, but the tuple order is the contract either way.
_LOGICAL_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"^port-channel(\d+)$", "lag"),
    (r"^vlan(\d+)$", "svi"),
    (r"^loopback(\d+)$", "loopback"),
)
_LOGICAL_RES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p, re.IGNORECASE), k) for p, k in _LOGICAL_PATTERNS
)


def classify_port_name(name: str) -> PortIdentity:
    """Parse a Dell OS10 port name into a :class:`PortIdentity`.

    Dispatch order: physical / breakout (``ethernet<n>/<s>/<p>[:<l>]``) →
    management (``mgmt<n>/<s>/<p>``) → logical kinds (``port-channel`` /
    ``vlan`` / ``loopback``) → unknown fallback.

    The parser normalises SVI names to the device form ``vlan<N>`` before
    they reach the canonical tree (see :mod:`.parse`), so the
    operator-authored ``Vlan 700`` spelling never arrives here.  The
    ``vlan`` pattern is still case-insensitive so a name that bypassed
    the parser (a hand-built tree, a cross-vendor rename) classifies
    rather than falling through to ``unknown``.
    """
    stripped = name.strip()

    m = _PHYSICAL_RE.match(stripped)
    if m:
        node = int(m.group("node"))
        slot = int(m.group("slot"))
        port = int(m.group("port"))
        lane = m.group("lane")
        if lane is not None:
            return PortIdentity(
                kind="breakout",
                stack=node,
                module=slot,
                port=port,
                breakout_lane=int(lane),
                breakout_parent=f"ethernet{node}/{slot}/{port}",
                original=name,
            )
        return PortIdentity(
            kind="physical",
            stack=node,
            module=slot,
            port=port,
            original=name,
        )

    mm = _MGMT_RE.match(stripped)
    if mm:
        return PortIdentity(
            kind="mgmt",
            stack=int(mm.group(1)),
            module=int(mm.group(2)),
            port=int(mm.group(3)),
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

    return PortIdentity(kind="unknown", original=name)


def format_port_identity(identity: PortIdentity) -> str | None:
    """Render a :class:`PortIdentity` as a Dell OS10 port name.

    OS10 uses a single ``ethernet`` prefix for every speed (measured: 262
    of 262 physical headers across the capture corpus), so the
    ``name_speed_hint`` carried by cross-vendor identities is ignored —
    an inbound Cisco ``TenGigabitEthernet`` and an inbound
    ``GigabitEthernet`` both format as ``ethernet<n>/<s>/<p>``.

    A cross-vendor identity carrying only ``module`` / ``port`` (an NX-OS
    ``Ethernet1/1``, say) defaults the node segment to ``1`` — OS10 names
    always carry three segments, so there is no two-segment form to fall
    back to.

    Returns ``None`` for kinds OS10 has no native v1 representation for
    (``breakout`` / ``tunnel`` / ``vtep`` / ``hw_aggregate`` /
    ``unknown``) — the orchestrator leaves the name verbatim and emits a
    review warning.  ``breakout`` is deliberately in that list even
    though :func:`classify_port_name` recognises it: OS10 can only
    receive a lane once the parent port has a matching ``interface
    breakout ... map`` profile, which is physical-layer state this codec
    does not model.  Inventing ``ethernet1/1/1:1`` on a target whose
    parent port is not broken out would emit config the device rejects.
    """
    if identity.kind == "physical":
        node = identity.stack if identity.stack is not None else 1
        return f"ethernet{node}/{identity.module or 1}/{identity.port or 0}"
    if identity.kind == "mgmt":
        # OS10's out-of-band port is conventionally mgmt1/1/1; honour a
        # source identity that carried real coordinates, else emit the
        # convention.
        node = identity.stack if identity.stack is not None else 1
        slot = identity.module if identity.module is not None else 1
        port = identity.port if identity.port is not None else 1
        return f"mgmt{node}/{slot}/{port}"
    if identity.kind == "lag":
        return f"port-channel{identity.index if identity.index is not None else 1}"
    if identity.kind == "svi":
        return f"vlan{identity.index if identity.index is not None else 1}"
    if identity.kind == "loopback":
        return f"loopback{identity.index if identity.index is not None else 0}"
    if identity.kind == "virtual":
        # Closest OS10 analogue for a vendor-specific virtual port.
        return f"loopback{identity.index or 0}"
    # breakout / tunnel / vtep / hw_aggregate / unknown — no native form.
    return None

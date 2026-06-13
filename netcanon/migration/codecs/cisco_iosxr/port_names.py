"""
Cisco IOS-XR port-name classification + formatting.

Pure functions — no parser / renderer state — so the cross-vendor
orchestrator in :mod:`netcanon.migration.canonical.port_names` can import
the translation primitives directly without pulling in the parse/render
machinery.  Mirrors the shape of
:mod:`netcanon.migration.codecs.cisco_iosxe_cli.port_names`.

IOS-XR diverges from IOS-XE in two ways that matter here:

* **4-segment physical port names** — ``GigabitEthernet0/0/0/0``
  (rack / slot / instance / port), not IOS-XE's 3-segment
  ``GigabitEthernet0/0/0``.  The 4th segment has no slot in the
  cross-vendor :class:`PortIdentity` (which models stack / module /
  port), so it is preserved in ``meta["iosxr_port_index"]`` for the
  same-vendor round-trip and drops to ``0`` when renaming to a
  3-segment target (IOS-XE / Arista).  A legacy 3-segment XR form
  (older CRS) is also accepted defensively.
* **``Bundle-Ether<N>`` LAGs** (not ``Port-channel<N>``) and
  **``MgmtEth0/RP0/CPU0/0``** management ports.

Recognised forms (matching is case-insensitive)::

    GigabitEthernet<a>/<b>/<c>[/<d>]   → physical   (also TenGigE,
                                         HundredGigE, FortyGigE, …)
    MgmtEth<rack>/RP<n>/CPU<n>/<port>  → mgmt
    Bundle-Ether<N>                    → lag
    Loopback<N>                        → loopback
    tunnel-ip<N> / tunnel-te<N>        → tunnel

Unrecognised names return ``kind="unknown"`` (verbatim fallback with a
warning).  ``Null0`` is NOT classified here — in the v1 corpus it only
ever appears as a static-route next-hop (``<prefix> Null0``), which the
parser keeps on :attr:`CanonicalStaticRoute.interface`, never as an
``interface`` stanza.
"""

from __future__ import annotations

import re

from ...canonical.port_names import PortIdentity

# ---------------------------------------------------------------------------
# Speed-prefix tables — canonical short form <-> XR-cased name prefix.
# The XR casing is irregular (``TenGigE``, not ``Tengige``), so the
# inverse map stores the exact wire spelling rather than title-casing.
# ---------------------------------------------------------------------------

_SPEED_PREFIXES: tuple[tuple[str, str], ...] = (
    ("FastEthernet", "fast"),
    ("GigabitEthernet", "gig"),
    ("TenGigE", "10gig"),
    ("TwentyFiveGigE", "25gig"),
    ("FortyGigE", "40gig"),
    ("HundredGigE", "100gig"),
    ("TwoHundredGigE", "200gig"),
    ("FourHundredGigE", "400gig"),
)
#: lower-cased XR prefix → canonical speed (used by classify).
_PREFIX_TO_SPEED: dict[str, str] = {p.lower(): s for p, s in _SPEED_PREFIXES}
#: canonical speed → XR-cased prefix (used by format; cross-vendor).
_SPEED_TO_PREFIX: dict[str, str] = {s: p for p, s in _SPEED_PREFIXES}

# ---------------------------------------------------------------------------
# Regex patterns — module-level so they compile once per import.
# ---------------------------------------------------------------------------

#: Physical interface — 4-segment (rack/slot/instance/port) or the legacy
#: 3-segment form.  Longer prefixes are listed first in the alternation so
#: e.g. ``TwentyFiveGigE`` wins over a hypothetical shorter partial match.
_PHYSICAL_RE = re.compile(
    r"^(?P<prefix>FourHundredGigE|TwoHundredGigE|TwentyFiveGigE|"
    r"HundredGigE|FortyGigE|TenGigE|GigabitEthernet|FastEthernet)"
    r"(?P<a>\d+)/(?P<b>\d+)/(?P<c>\d+)(?:/(?P<d>\d+))?$",
    re.IGNORECASE,
)

#: Management port — ``MgmtEth<rack>/RP<n>/CPU<n>/<port>`` (also RSP for
#: ASR9k route-switch processors).
_MGMT_RE = re.compile(
    r"^MgmtEth(\d+)/(?:RP|RSP)\d+/CPU\d+/(\d+)$",
    re.IGNORECASE,
)

#: Logical-kind patterns — each maps an XR prefix + numeric index to a
#: canonical :data:`PortKind`.  Order preserved for deterministic
#: classification.
_LOGICAL_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"^Bundle-Ether(\d+)$", "lag"),
    (r"^Loopback(\d+)$", "loopback"),
    (r"^tunnel-ip(\d+)$", "tunnel"),
    (r"^tunnel-te(\d+)$", "tunnel"),
)
_LOGICAL_RES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p, re.IGNORECASE), k) for p, k in _LOGICAL_PATTERNS
)


def classify_port_name(name: str) -> PortIdentity:
    """Parse a Cisco IOS-XR port name into a :class:`PortIdentity`.

    Dispatch order: physical (4/3-segment) → management → logical kinds
    (Bundle-Ether / Loopback / tunnel) → unknown fallback.
    """
    m = _PHYSICAL_RE.match(name)
    if m:
        speed = _PREFIX_TO_SPEED.get(m.group("prefix").lower(), "")
        a = int(m.group("a"))
        b = int(m.group("b"))
        c = int(m.group("c"))
        d = m.group("d")
        ident = PortIdentity(
            kind="physical",
            stack=a,           # rack
            module=b,          # slot
            port=c,            # instance
            name_speed_hint=speed,
            original=name,
        )
        if d is not None:
            # Preserve the 4th (per-PIC port) segment for same-vendor
            # round-trip; it has no cross-vendor PortIdentity slot.
            ident.meta["iosxr_port_index"] = d
        return ident

    mg = _MGMT_RE.match(name)
    if mg:
        return PortIdentity(
            kind="mgmt",
            stack=int(mg.group(1)),
            port=int(mg.group(2)),
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
    """Render a :class:`PortIdentity` as a Cisco IOS-XR port name.

    Same-vendor round-trip restores the 4th segment from
    ``meta["iosxr_port_index"]``; cross-vendor input from a 3-segment
    naming scheme (IOS-XE / Arista) appends ``/0`` for the missing
    instance segment (a documented lossy translation surfaced via the
    rename modal).

    Returns ``None`` for kinds IOS-XR has no native v1 representation for
    (``tunnel`` / ``svi`` / ``vtep`` / ``breakout`` / ``hw_aggregate`` /
    ``unknown``) — the orchestrator leaves the name verbatim and emits a
    review warning.
    """
    if identity.kind == "physical":
        prefix = _SPEED_TO_PREFIX.get(
            identity.name_speed_hint, "GigabitEthernet",
        )
        idx = identity.meta.get("iosxr_port_index", "0")
        a = identity.stack if identity.stack is not None else 0
        b = identity.module if identity.module is not None else 0
        c = identity.port if identity.port is not None else 0
        return f"{prefix}{a}/{b}/{c}/{idx}"
    if identity.kind == "lag":
        return f"Bundle-Ether{identity.index or 1}"
    if identity.kind == "loopback":
        return f"Loopback{identity.index or 0}"
    if identity.kind == "mgmt":
        # IOS-XR's canonical management port; cross-vendor mgmt cascades
        # here regardless of the source's mgmt naming.
        return "MgmtEth0/RP0/CPU0/0"
    # tunnel / svi / vtep / breakout / hw_aggregate / virtual / unknown —
    # no native IOS-XR form for cross-vendor rename.
    return None

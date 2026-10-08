"""
Cisco IOS-XR port-name classification + formatting.

Pure functions — no parser / renderer state — so the cross-vendor
orchestrator in :mod:`netcanon.migration.canonical.port_names` can import
the translation primitives directly without pulling in the parse/render
machinery.  Mirrors the shape of
:mod:`netcanon.migration.codecs.cisco_iosxe_cli.port_names`.

IOS-XR diverges from IOS-XE in two ways that matter here:

* **4-segment physical port names** — ``GigabitEthernet0/0/0/0``
  (rack / slot / module / port), not IOS-XE's 3-segment
  ``GigabitEthernet0/0/0``.  Four segments do not fit the three-field
  cross-vendor :class:`PortIdentity`, so one is parked in ``meta``:
  the RACK (``meta["iosxr_rack"]``), which is 0 on every non-clustered
  system.  Slot, module and port are carried as stack / module / port.
  (Until 2026-10 it was the PORT that was parked, which collapsed every
  port on a card onto one cross-vendor name.)  A legacy 3-segment XR
  form (older CRS) is also accepted defensively.
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
        if d is None:
            # Three-segment form: no rack segment to park.
            return PortIdentity(
                kind="physical", stack=a, module=b, port=c,
                name_speed_hint=speed, original=name,
            )
        # IOS-XR is rack/slot/module/port -- FOUR segments into a
        # three-field identity, so one must be parked in ``meta``.
        #
        # It used to be the PORT.  The module segment (almost always 0)
        # went into ``PortIdentity.port`` and the real port index into
        # meta, where no other codec looks -- so EVERY port on a card
        # formatted to one cross-vendor name: ``Gi0/0/0/0``, ``/5`` and
        # ``/17`` all became ``ge-0/0/0``.  39 ports collapsed onto one in
        # the single hardware capture in the corpus.
        #
        # Park the RACK instead.  It is 0 on every non-clustered system
        # (nV Edge, the only multi-rack mode, is unsupported from 6.0.1),
        # so it is the segment that carries no information cross-vendor.
        ident = PortIdentity(
            kind="physical",
            stack=b,           # slot (line card; 0 on a fixed chassis)
            module=c,          # module / PIC within the slot
            port=int(d),       # the port -- the segment that must survive
            name_speed_hint=speed,
            original=name,
        )
        ident.meta["iosxr_rack"] = str(a)
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

    Same-vendor round-trip restores the rack from ``meta["iosxr_rack"]``;
    cross-vendor input from a 3-segment naming scheme (IOS-XE / Arista)
    is placed at rack 0 as ``0/<stack>/<module>/<port>``.

    Returns ``None`` for kinds IOS-XR has no native v1 representation for
    (``tunnel`` / ``svi`` / ``vtep`` / ``breakout`` / ``hw_aggregate`` /
    ``unknown``) — the orchestrator leaves the name verbatim and emits a
    review warning.
    """
    if identity.kind == "physical":
        prefix = _SPEED_TO_PREFIX.get(
            identity.name_speed_hint, "GigabitEthernet",
        )
        # rack/slot/module/port.  The rack comes back from meta on a
        # same-vendor round-trip and is 0 for every cross-vendor source.
        rack = identity.meta.get("iosxr_rack", "0")
        slot = identity.stack if identity.stack is not None else 0
        module = identity.module if identity.module is not None else 0
        port = identity.port if identity.port is not None else 0
        return f"{prefix}{rack}/{slot}/{module}/{port}"
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

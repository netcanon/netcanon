"""
Aruba AOS-S port-name classification + formatting.

Pure functions — no parser / renderer state — extracted from
``codec.py`` so the cross-vendor orchestrator in
:mod:`netconfig.migration.canonical.port_names` can import the
translation primitives directly without pulling in the parse/
render machinery.

AOS-S port-name forms handled here:

* ``24``       — standalone switch, port 24.
* ``1/24``     — stacked VSF, member 1, port 24.
* ``1/A1``     — stacked VSF with letter-slot uplink module
                 (A / B / C / ...), member 1, port 1.
* ``Trk1``     — LAG (case-insensitive: forums vary between
                 ``Trk1`` and ``trk1``).

AOS-S does NOT have:
    * Multi-part slot/module/port notation (Cisco's
      ``stack/module/port``).
    * Breakout ports.
    * Loopback interfaces.
    * Tunnel interfaces.
    * Separate SVI interface stanzas — see :mod:`._svi_absorption`.

Unrecognised names return ``kind="unknown"`` so the orchestrator
leaves the source name verbatim with a warning rather than
guessing a target name.
"""

from __future__ import annotations

import re

from ...canonical.port_names import PortIdentity


# ---------------------------------------------------------------------------
# Regex patterns — module-level so they compile once per import
# ---------------------------------------------------------------------------

#: LAG: ``Trk<n>`` or ``trk<n>`` (forum pastes use either case).
_TRUNK_RE = re.compile(r"^[Tt]rk(\d+)$")

#: Stacked VSF with letter-slot uplink module: ``<stack>/<A-Z><port>``
#: (e.g. ``1/A1``, ``2/B24``).  Uplink modules on 2930F/3810M/6300M
#: chassis use letter subslots A through D+.
_STACKED_LETTER_RE = re.compile(r"^(\d+)/([A-Za-z])(\d+)$")

#: Stacked VSF plain: ``<stack>/<port>``.  Order matters — the
#: letter-slot pattern is tried first so ``1/A1`` doesn't greedily
#: match this one.
_STACKED_PLAIN_RE = re.compile(r"^(\d+)/(\d+)$")

#: Standalone switch: bare port number.
_STANDALONE_RE = re.compile(r"^(\d+)$")


def classify_port_name(name: str) -> PortIdentity:
    """Parse an Aruba AOS-S port name into a :class:`PortIdentity`.

    Pattern-match order is significant: trunk / letter-slot /
    stacked-plain / standalone.  Letter-slot must precede
    stacked-plain because ``1/A1`` would otherwise match the plain
    ``<digits>/<digits>`` pattern after anchor consumption if the
    plain pattern allowed letters.

    Args:
        name: Source-side port name as it appears in the AOS-S
            config (``24``, ``1/24``, ``1/A1``, ``Trk1``, ...).

    Returns:
        A populated :class:`PortIdentity`; ``kind="unknown"`` when
        no pattern matches so the orchestrator falls back to
        verbatim + warning.
    """
    stripped = name.strip()

    # Trunk (LAG) — case-insensitive.
    m = _TRUNK_RE.match(stripped)
    if m:
        return PortIdentity(
            kind="lag", index=int(m.group(1)), original=name
        )

    # Stacked VSF with letter-slot uplink module (must precede the
    # plain stacked pattern — see _STACKED_PLAIN_RE docstring).
    m = _STACKED_LETTER_RE.match(stripped)
    if m:
        return PortIdentity(
            kind="physical",
            stack=int(m.group(1)),
            port=int(m.group(3)),
            subslot_letter=m.group(2).upper(),
            original=name,
        )

    # Stacked VSF plain: 1/24.
    m = _STACKED_PLAIN_RE.match(stripped)
    if m:
        return PortIdentity(
            kind="physical",
            stack=int(m.group(1)),
            port=int(m.group(2)),
            original=name,
        )

    # Standalone: bare port number.
    m = _STANDALONE_RE.match(stripped)
    if m:
        return PortIdentity(
            kind="physical",
            port=int(m.group(1)),
            original=name,
        )

    return PortIdentity(kind="unknown", original=name)


def format_port_identity(identity: PortIdentity) -> str | None:
    """Render a :class:`PortIdentity` as an AOS-S port name.

    Collapses Cisco-style three-part notation by DROPPING the
    middle (module) digit when it's 0 — ``Gi1/0/24`` → ``1/24``.
    For non-zero middle digits (typically uplink modules on Cisco
    stack members) the caller gets a ``None`` return so the
    orchestrator emits a "review uplink mapping" warning rather
    than guessing the Aruba letter-slot mapping.

    Returns None for kinds AOS-S can't natively represent
    (loopback, tunnel, breakout, hw_aggregate, mgmt) and for SVIs
    (see :mod:`._svi_absorption` — codepath 3 of 3).
    """
    if identity.kind == "physical":
        # Aruba can't represent a non-zero middle module digit —
        # C9300 ``Gi1/1/1`` is an uplink-module port that maps to
        # Aruba ``1/A1``/``1/B1`` only if the operator tells us
        # which letter; we don't know that from the source config
        # alone.  Bail with a warning.
        if identity.module and identity.module != 0:
            return None
        # Aruba has no port 0.  Cisco's ``GigabitEthernet0/0`` is
        # the dedicated OOBM management port — Aruba's equivalent
        # is the separate OOBM concept (not in the regular port-
        # name space), so leave verbatim + warn instead of
        # collapsing to bogus ``"1"`` via ``port or 1``.
        if identity.port == 0:
            return None
        if identity.subslot_letter:
            # 1/A1 style (uplink module).
            return (
                f"{identity.stack or 1}/"
                f"{identity.subslot_letter}{identity.port or 1}"
            )
        if identity.stack is not None:
            return f"{identity.stack}/{identity.port or 1}"
        return str(identity.port or 1)
    if identity.kind == "lag":
        return f"Trk{identity.index or 1}"
    # SVI absorption — codepath 3 of 3.  See ._svi_absorption for
    # the full rule.  AOS-S has no ``interface Vlan<N>`` name-
    # space; the render path (codepath 2 in codec.py) emits L3
    # inside the VLAN stanza.  Returning None tells the cross-
    # vendor orchestrator "no port-name rewrite needed" —
    # suppressed from the rename modal's warning list via
    # ``ArubaAOSSCodec.absorbs_svi_into_vlan``.
    if identity.kind == "svi":
        return None
    # AOS-S DOES support loopback (verified against Aruba Basic
    # Operation Guide for AOS-S 16.10, "Managing loopback interfaces"
    # chapter): `interface loopback <N>` where N is 0-7.  ``lo-0`` is
    # reserved (auto-assigned ::1/128) so user-creatable IDs are
    # 1-7.  Cisco/Arista/Junos sources commonly use Loopback0; map
    # to AOS-S loopback 1 (the first user-creatable slot) when the
    # source uses 0, otherwise pass the index through if it fits.
    # Above index 7 we can't represent — return None to drop with
    # the standard "no native representation" warning.
    if identity.kind == "loopback":
        idx = identity.index if identity.index is not None else 0
        # Map Loopback0 → loopback1; preserve 1..7 verbatim.
        if idx == 0:
            return "loopback1"
        if 1 <= idx <= 7:
            return f"loopback{idx}"
        return None
    # AOS-S OOBM is a separate top-level configuration block (NOT a
    # numbered interface).  See Aruba Management & Configuration
    # Guide for AOS-S 16.10, "Out-of-Band Management" chapter:
    # `oobm` opens the context, then `ip address <addr>/<mask>` and
    # `ip default-gateway <addr>` configure it.  Return the sentinel
    # "oobm" so the renderer recognises it and emits the top-level
    # block instead of an `interface oobm` stanza (which would be
    # invalid AOS-S syntax).  Stack-aware variants (`oobm / member
    # <id> / ip address ...`) are deferred until a real fixture
    # demands them.
    if identity.kind == "mgmt":
        return "oobm"
    # tunnel / breakout / hw_aggregate / virtual / unknown — AOS-S
    # has no native representation.
    return None

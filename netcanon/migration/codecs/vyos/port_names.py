"""
VyOS port-name classification + formatting.

Pure functions — no parser / renderer state — so the cross-vendor
orchestrator in :mod:`netcanon.migration.canonical.port_names` can import
the translation primitives directly.  Mirrors the shape of
:mod:`netcanon.migration.codecs.aruba_aoscx.port_names`.

VyOS uses Linux-style device names (the OS is Debian-derived):

    eth0, eth1, ...      → physical  (ethernet)
    eth0.100             → physical  (a ``vif`` VLAN sub-interface; the
                                      canonical name carries the ``.<vid>``)
    lo                   → loopback  (the single kernel loopback)
    dum0, dum1, ...      → loopback  (``dummy`` interfaces — loopback-like)
    bond0, bond1, ...    → lag       (``bonding`` link aggregation)

A ``vif`` sub-interface classifies as ``physical`` (it lives on a
physical port); the cross-vendor formatter collapses it to the parent
device name — the ``.<vid>`` tag is a VyOS-specific encoding with no
portable cross-vendor home in v1 (declared lossy).  Same-vendor
round-trips never invoke the cross-vendor bridge — they carry the
canonical ``name`` (e.g. ``"eth0.100"``) verbatim — so the sub-interface
survives a VyOS→VyOS round-trip intact.

Unrecognised names return ``kind="unknown"`` (verbatim fallback).
"""

from __future__ import annotations

import re

from ...canonical.port_names import PortIdentity

# ---------------------------------------------------------------------------
# Regex patterns — module-level so they compile once per import
# ---------------------------------------------------------------------------

#: ``eth0`` / ``eth0.100`` — physical port, optional ``.<vid>`` sub-iface.
_ETH_RE = re.compile(r"^eth(?P<port>\d+)(?:\.(?P<vid>\d+))?$", re.IGNORECASE)
#: ``bond0`` — bonding (LAG).
_BOND_RE = re.compile(r"^bond(?P<idx>\d+)$", re.IGNORECASE)
#: ``dum0`` — dummy interface (loopback-like).
_DUM_RE = re.compile(r"^dum(?P<idx>\d+)$", re.IGNORECASE)
#: ``lo`` — the single kernel loopback.
_LO_RE = re.compile(r"^lo$", re.IGNORECASE)


def classify_port_name(name: str) -> PortIdentity:
    """Parse a VyOS interface name into a :class:`PortIdentity`.

    Dispatch order: ethernet (``ethN`` / ``ethN.vid``) → bonding
    (``bondN``) → dummy (``dumN``) → loopback (``lo``) → unknown.
    """
    stripped = name.strip()

    m = _ETH_RE.match(stripped)
    if m:
        # A ``vif`` sub-interface (``eth0.100``) classifies as physical;
        # the vid is stashed in ``meta`` for advisory use but the
        # cross-vendor formatter collapses to the parent device name.
        meta = {"vif": m.group("vid")} if m.group("vid") else {}
        return PortIdentity(
            kind="physical",
            port=int(m.group("port")),
            original=name,
            meta=meta,
        )

    m = _BOND_RE.match(stripped)
    if m:
        return PortIdentity(
            kind="lag", index=int(m.group("idx")), original=name,
        )

    m = _DUM_RE.match(stripped)
    if m:
        return PortIdentity(
            kind="loopback", index=int(m.group("idx")), original=name,
        )

    if _LO_RE.match(stripped):
        return PortIdentity(kind="loopback", index=0, original=name)

    return PortIdentity(kind="unknown", original=name)


def format_port_identity(identity: PortIdentity) -> str | None:
    """Render a :class:`PortIdentity` as a VyOS interface name.

    Physical → ``eth<port>`` (a cross-vendor port carrying only
    ``module``/``port`` defaults sensibly to the terminal port number).
    LAG → ``bond<index>``.  Loopback index 0 → ``lo`` (the single kernel
    loopback); index N>0 → ``dum<N>`` (VyOS models extra loopbacks as
    ``dummy`` interfaces).  Returns ``None`` for kinds VyOS has no native
    representation for (the orchestrator leaves the name verbatim + warns).
    """
    if identity.kind == "physical":
        return f"eth{identity.port if identity.port is not None else 0}"
    if identity.kind == "lag":
        return f"bond{identity.index if identity.index is not None else 0}"
    if identity.kind == "loopback":
        idx = identity.index if identity.index is not None else 0
        return "lo" if idx == 0 else f"dum{idx}"
    # svi / vtep / tunnel / mgmt / breakout / hw_aggregate / virtual /
    # unknown — no native VyOS v1 form.
    return None

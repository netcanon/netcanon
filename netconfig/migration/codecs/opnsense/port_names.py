"""
OPNsense port-name classification + formatting.

Pure functions — no parser / renderer state — extracted from
``codec.py`` so the cross-vendor orchestrator in
:mod:`netconfig.migration.canonical.port_names` can import the
translation primitives directly without pulling in the parse/
render machinery (and without circular imports).

OPNsense presents interfaces at two levels of naming:

* **BSD device names** — what the FreeBSD kernel assigns to the NIC
  based on its driver: ``igb<N>``, ``em<N>``, ``ix<N>``,
  ``mlxen<N>``, ``lagg<N>``, ``wg<N>``, etc.  The integer suffix is
  the per-driver unit number, not a slot/module index.  These are
  the names we see in the ``<interfaces>/<if>`` element of
  config.xml and the ones operators type when assigning zones.

* **Zone aliases** — ``wan``, ``lan``, ``opt<N>``.  Operator-facing
  aliases that resolve to a specific BSD device via
  ``<interfaces><wan><if>igb0</if>…``.  The codec's parser resolves
  these to BSD form before the canonical tree, so we rarely see
  aliases here; if one leaks through we classify as ``unknown``
  because we can't resolve the alias->device map without the full
  config.xml in hand.

VLAN subinterfaces use the ``<parent>.<vlan_id>`` form (e.g.
``igb0.10``, ``lagg0.100``) and classify as ``svi``.

Speed inference from driver name:
    10gig-class : ix, ixgbe, ixl, cxgbe, bnxt, mlxen
    gig-class   : igb, em, re, bge, fxp, vmx, vtnet, mce
"""

from __future__ import annotations

import re

from ...canonical.port_names import PortIdentity


# ---------------------------------------------------------------------------
# Regex patterns — module-level so they compile once per import
# ---------------------------------------------------------------------------

#: BSD NIC-driver prefixes, ordered so longer prefixes match first
#: (``cxgbe`` before ``ce``; ``mlxen`` before ``m``; ``ixgbe`` /
#: ``ixl`` before ``ix``).  The classifier iterates this list and
#: tries each as ``^<prefix>(\d+)$``.
_NIC_PREFIXES = (
    "cxgbe", "mlxen", "bnxt",
    "ixgbe", "ixl", "igb", "ixl", "em", "re",
    "ix", "vmx", "vtnet", "bge", "mce", "fxp",
)

#: Drivers that imply 10G-class ports.  Everything else in
#: :data:`_NIC_PREFIXES` is treated as 1G.
_TEN_GIG_DRIVERS = frozenset({
    "ix", "ixgbe", "ixl", "cxgbe", "bnxt", "mlxen",
})

_LAGG_RE = re.compile(r"^lagg(\d+)$", re.IGNORECASE)
#: VLAN subinterface: ``<parent>.<vlan_id>``.  The parent can be any
#: BSD iface name (igb0, lagg0, ix1, etc.) — we capture it verbatim.
_VLAN_SUBIFACE_RE = re.compile(
    r"^([a-z][a-z0-9-]*)\.(\d+)$", re.IGNORECASE
)
_LOOPBACK_RE = re.compile(r"^lo(\d+)$", re.IGNORECASE)
#: Tunnel-class interfaces.  WireGuard (``wg``), generic IPv4
#: tunnel (``gif``), GRE (``gre``), OpenVPN server / client
#: (``ovpns`` / ``ovpnc``).
_TUNNEL_RE = re.compile(
    r"^(wg|gif|gre|ovpns|ovpnc)(\d+)$", re.IGNORECASE
)


def classify_port_name(name: str) -> PortIdentity:
    """Parse an OPNsense interface name into a :class:`PortIdentity`.

    Pattern dispatch order:
      1. BSD NIC driver + unit number → physical with
         ``opnsense_driver`` meta + speed hint from driver class.
      2. ``lagg<N>`` → lag.
      3. ``<parent>.<vlan_id>`` → svi with ``opnsense_parent`` meta.
      4. ``lo<N>`` → loopback.
      5. ``(wg|gif|gre|ovpns|ovpnc)<N>`` → tunnel with
         ``opnsense_tunnel_kind`` meta.
      6. Anything else → unknown (zone aliases that leaked through,
         user-named VLANs, etc.).

    Args:
        name: Source-side OPNsense interface name.

    Returns:
        A populated :class:`PortIdentity` with OPNsense-specific meta
        hints so same-vendor round-trip preserves driver / parent /
        tunnel-kind choices.  ``kind="unknown"`` when no pattern
        matches.
    """
    stripped = name.strip()

    # BSD NIC-driver + unit number.
    for prefix in _NIC_PREFIXES:
        m = re.match(rf"^{prefix}(\d+)$", stripped, re.IGNORECASE)
        if m:
            speed = "10gig" if prefix in _TEN_GIG_DRIVERS else "gig"
            return PortIdentity(
                kind="physical",
                port=int(m.group(1)),
                name_speed_hint=speed,
                meta={"opnsense_driver": prefix.lower()},
                original=name,
            )

    # LAG (FreeBSD lagg(4)).
    m = _LAGG_RE.match(stripped)
    if m:
        return PortIdentity(
            kind="lag", index=int(m.group(1)), original=name
        )

    # VLAN subinterface: ``<parent>.<vlan_id>``.
    m = _VLAN_SUBIFACE_RE.match(stripped)
    if m:
        return PortIdentity(
            kind="svi",
            index=int(m.group(2)),
            meta={"opnsense_parent": m.group(1)},
            original=name,
        )

    # Loopback.
    m = _LOOPBACK_RE.match(stripped)
    if m:
        return PortIdentity(
            kind="loopback", index=int(m.group(1)), original=name
        )

    # Tunnels.
    m = _TUNNEL_RE.match(stripped)
    if m:
        return PortIdentity(
            kind="tunnel",
            index=int(m.group(2)),
            meta={"opnsense_tunnel_kind": m.group(1).lower()},
            original=name,
        )

    # Zone alias that leaked through, user-named VLAN, or anything
    # else unrecognised.
    return PortIdentity(kind="unknown", original=name)


def format_port_identity(identity: PortIdentity) -> str | None:
    """Render a :class:`PortIdentity` as an OPNsense BSD-device name.

    Default driver choice is ``igb`` for 1G and ``ix`` for 10G+;
    the source-side ``opnsense_driver`` meta hint wins when
    present (same-vendor round-trip preserves the actual NIC
    type).  SVIs render as ``<parent>.<vlan_id>``; if no parent
    is in the meta hint, default to ``lagg0`` (the typical
    OPNsense LAG parent for VLANs in real deployments).

    Returns None for kinds OPNsense can't deterministically emit
    (hw_aggregate, breakout, mgmt) — OPNsense is a BSD appliance
    with no equivalent concept in config.xml's interface space.
    """
    if identity.kind == "physical":
        driver = identity.meta.get("opnsense_driver")
        if driver:
            return f"{driver}{identity.port or 0}"
        if identity.name_speed_hint in ("10gig", "25gig", "40gig", "100gig"):
            return f"ix{identity.port or 0}"
        return f"igb{identity.port or 0}"
    if identity.kind == "lag":
        return f"lagg{identity.index or 0}"
    if identity.kind == "svi":
        parent = identity.meta.get("opnsense_parent") or "lagg0"
        return f"{parent}.{identity.index}"
    if identity.kind == "loopback":
        return f"lo{identity.index or 0}"
    if identity.kind == "tunnel":
        kind = identity.meta.get("opnsense_tunnel_kind") or "gif"
        return f"{kind}{identity.index or 0}"
    if identity.kind == "mgmt":
        # OPNsense has no native VRF / dedicated OOBM-port concept —
        # all interfaces live in the same flat ``<interfaces>`` zone
        # space, distinguished only by zone name (``wan`` / ``lan`` /
        # ``opt<N>``).  Best-effort cross-vendor mapping for a source-
        # vendor management interface (Cisco Mgmt-vrf-bound port,
        # Arista ``Management1``, Junos ``fxp0``) is a dedicated
        # ``opt_mgmt`` zone — the ``opt_*`` prefix preserves OPNsense
        # zone-naming convention (see OPNsense docs at
        # docs.opnsense.org/manual/interfaces.html, "Optional
        # interfaces are commonly named opt1, opt2, …" — operator-
        # named opt zones are also supported and survive the GUI's
        # zone-assignment workflow).  The renderer pairs this with a
        # ``<descr>Management</descr>`` element so operators see the
        # role at a glance in the OPNsense UI.
        return "opt_mgmt"
    return None

"""
MikroTik RouterOS port-name classification + formatting.

Pure functions — no parser / renderer state — extracted from
``codec.py`` so the cross-vendor orchestrator in
:mod:`netcanon.migration.canonical.port_names` can import the
translation primitives directly without pulling in the parse/
render machinery.

Recognised RouterOS port forms (the factory names among them are
listed, with where each is shown, at :func:`is_factory_port_name`):

    * ``ether<N>``                  — gigabit Ethernet (CRS/CCR).
    * ``sfp-sfpplus<N>`` /
      ``sfpplus<N>``                — 10G SFP+ cage.
    * ``sfp28-<N>``                 — 25G SFP28 cage.
    * ``sfp<N>``                    — 1G SFP cage.
    * ``combo<N>``                  — a combo port (copper or SFP).
    * ``qsfpplus<N>`` /
      ``qsfpplus<N>-<lane>``        — 40G QSFP+, optional breakout.
    * ``qsfp28-<N>-<lane>``         — 100G QSFP28 and its lanes.
    * ``bond<N>`` / ``bonding<N>``  — LAG.
    * ``bridge`` / ``br-<name>``    — bridge (classified as
                                       ``virtual``; no direct cross-
                                       vendor analogue).
    * ``lo`` / ``loopback<N>``      — loopback.
    * ``<parent>.<id>``             — VLAN subinterface (SVI-analog).
    * ``wg<N>`` / ``wireguard<N>``
      ``gre<N>`` / ``ipip<N>``
      ``eoip<N>`` / ``l2tp-out<N>``
      ``pptp-out<N>`` / ``sstp-out<N>``
      ``ovpn-client<N>`` /
      ``ovpn-server<N>``            — tunnels.

RouterOS allows arbitrary user-named interfaces via
``/interface set [find] name="Access Point"``.  The canonical
intent preserves the rename pair (``name`` + ``default_name``)
already; this module's classifier therefore only handles factory-
default forms.  User-renamed interfaces classify as ``unknown``
and fall through verbatim — there's no algorithmic way to map
``"Access Point"`` to an Aruba port number; operators supply the
mapping via Tier 2 rename_map overrides.
"""

from __future__ import annotations

import re

from ...canonical.port_names import PortIdentity

# ---------------------------------------------------------------------------
# Regex patterns — module-level so they compile once per import
# ---------------------------------------------------------------------------

# A port's own name is matched in its own case: RouterOS names are
# free text (the codec states ``port_names_case_sensitive``), and
# every name the vendor shows for a port is lower case, so
# ``SFP-SFPPLUS1`` or ``Ether1`` is a name an operator chose, which no
# shape here says anything about.
_ETHER_RE = re.compile(r"^ether(\d+)$")
#: ``sfp-sfpplus<N>`` / ``sfpplus<N>`` — MUST be tried before the
#: bare ``sfp<N>`` pattern, otherwise the bare form eats it.
_SFPPLUS_RE = re.compile(r"^(?:sfp-sfpplus|sfpplus)(\d+)$")
_SFP28_RE = re.compile(r"^sfp28-(\d+)$")
_SFP_RE = re.compile(r"^sfp(\d+)$")
_COMBO_RE = re.compile(r"^combo(\d+)$")
#: QSFP+ 40G with optional ``-<lane>`` breakout suffix.
_QSFPPLUS_RE = re.compile(r"^qsfpplus(\d+)(?:-(\d+))?$")
#: QSFP28: always a lane, ``-1`` the one a 100G link runs on.
_QSFP28_RE = re.compile(r"^qsfp28-(\d+)-(\d+)$")
#: The names a MikroTik device gives its own Ethernet ports: see
#: :func:`is_factory_port_name`.
_FACTORY_PORT_RE = re.compile(
    r"(?:ether|sfp|combo|sfp-sfpplus|sfp28-)\d+"
    r"|(?:qsfpplus|qsfp28-|qsfp56-|qsfp56-dd-)\d+-\d+"
)
_BOND_RE = re.compile(r"^bond(?:ing)?(\d+)$", re.IGNORECASE)
_LOOPBACK_RE = re.compile(r"^loopback(\d+)$", re.IGNORECASE)
#: Tunnel subtypes — preserved in meta so same-vendor round-trip
#: emits the correct one (``wg`` for WireGuard, ``gre`` for GRE,
#: etc.).
_TUNNEL_RE = re.compile(
    r"^(wg|wireguard|gre|ipip|eoip|l2tp-out|pptp-out|sstp-out|"
    r"ovpn-client|ovpn-server)(\d*)$",
    re.IGNORECASE,
)
#: VLAN subinterface dotted form ``<parent>.<id>``.  User-named
#: VLANs (``VL_100``) don't match and classify as unknown — the
#: canonical preserves the name verbatim.
_VLAN_DOT_RE = re.compile(r"^([A-Za-z][A-Za-z0-9-]*)\.(\d+)$")
#: Bridge virtual interface: named ``br-<label>``.  Bare literal
#: ``bridge`` is matched via string equality.
_BRIDGE_RE = re.compile(r"^br-[A-Za-z0-9-]+$", re.IGNORECASE)


def is_factory_port_name(name: str) -> bool:
    """Is *name* one a MikroTik device gives one of its own ports?

    Such a name is written into a ``set [ find default-name=... ]``
    line, which finds the port whatever it has since been called; a
    name that is not one finds nothing there.  So the shapes are the
    ones the vendor shows, each from its documentation or an export of
    a real device, and nothing near them:

    * ``ether<N>``, ``sfp<N>``, ``combo<N>`` -- "IP address
      192.168.88.1/24 is set on ether1, or combo1, or sfp1" (RouterOS
      manual, "Default configurations"); ``sfp3`` on the "Ethernet"
      page.
    * ``sfp-sfpplus<N>`` -- ``set [ find default-name=sfp-sfpplus1 ]``
      ("Ethernet").
    * ``sfp28-<N>`` -- ``set [ find default-name=sfp28-1 ]`` in an
      export of a CCR2004-1G-12S+2XS (MikroTik forum, thread 266127).
    * ``qsfpplus<N>-<L>``, ``qsfp28-<N>-<L>``, ``qsfp56-<N>-<L>``,
      ``qsfp56-dd-<N>-<L>`` -- ``qsfpplus1-1``, ``qsfp28-2-1``,
      ``qsfp56-1-1``, ``qsfp56-dd-1-1`` ("MikroTik wired interface
      compatibility"); ``default-name=qsfp28-1-1`` ("Ethernet").

    Every one is lower case with nothing after its number.  A name in
    another case, or with more after the number -- ``ether1_ADMIN`` is in
    that same export, ``sfp28-1_UPLINK`` is its kind -- is one the operator
    gave a port, and says nothing of which port it is.  ``sfpplus<N>``
    and a ``qsfpplus<N>`` with no lane are read as ports by
    :func:`classify_port_name`, but no page or export shows a device
    that names a port so, and they are not factory names here.
    """
    return _FACTORY_PORT_RE.fullmatch(name) is not None


def classify_port_name(name: str) -> PortIdentity:
    """Parse a RouterOS port name into a :class:`PortIdentity`.

    Order of pattern matching matters in two places:

      1. ``sfp-sfpplus`` / ``sfpplus`` before bare ``sfp`` so the
         10G form isn't swallowed by the 1G one.
      2. ``qsfpplus<N>-<lane>`` returns ``kind="breakout"`` (not
         ``physical``) so cross-vendor translation knows to warn
         about the breakout constraint.
    """
    stripped = name.strip()

    # Physical: ether / sfp-sfpplus / sfp / qsfpplus.
    m = _ETHER_RE.match(stripped)
    if m:
        return PortIdentity(
            kind="physical",
            port=int(m.group(1)),
            name_speed_hint="gig",
            original=name,
        )
    m = _SFPPLUS_RE.match(stripped)
    if m:
        return PortIdentity(
            kind="physical",
            port=int(m.group(1)),
            name_speed_hint="10gig",
            meta={"mikrotik_cage": "sfpplus"},
            original=name,
        )
    m = _SFP28_RE.match(stripped)
    if m:
        return PortIdentity(
            kind="physical",
            port=int(m.group(1)),
            name_speed_hint="25gig",
            meta={"mikrotik_cage": "sfp28"},
            original=name,
        )
    m = _SFP_RE.match(stripped)
    if m:
        return PortIdentity(
            kind="physical",
            port=int(m.group(1)),
            name_speed_hint="gig",
            meta={"mikrotik_cage": "sfp"},
            original=name,
        )
    m = _COMBO_RE.match(stripped)
    if m:
        # Copper or an SFP, whichever is plugged in: the name says
        # nothing of the speed.
        return PortIdentity(
            kind="physical",
            port=int(m.group(1)),
            meta={"mikrotik_cage": "combo"},
            original=name,
        )
    m = _QSFP28_RE.match(stripped)
    if m:
        port = int(m.group(1))
        return PortIdentity(
            kind="breakout",
            port=port,
            breakout_lane=int(m.group(2)),
            breakout_parent=f"qsfp28-{port}",
            name_speed_hint="25gig",  # 4x25G breakout lanes
            meta={"mikrotik_cage": "qsfp28"},
            original=name,
        )
    m = _QSFPPLUS_RE.match(stripped)
    if m:
        port = int(m.group(1))
        lane = int(m.group(2)) if m.group(2) else None
        if lane is not None:
            return PortIdentity(
                kind="breakout",
                port=port,
                breakout_lane=lane,
                breakout_parent=f"qsfpplus{port}",
                name_speed_hint="10gig",  # 4x10G breakout lanes
                original=name,
            )
        return PortIdentity(
            kind="physical",
            port=port,
            name_speed_hint="40gig",
            original=name,
        )

    # LAG: bond / bonding.
    m = _BOND_RE.match(stripped)
    if m:
        return PortIdentity(
            kind="lag", index=int(m.group(1)), original=name
        )

    # Loopback: lo or loopback<N>.
    if stripped.lower() == "lo":
        return PortIdentity(kind="loopback", index=0, original=name)
    m = _LOOPBACK_RE.match(stripped)
    if m:
        return PortIdentity(
            kind="loopback", index=int(m.group(1)), original=name
        )

    # Tunnels — preserve the subtype in meta so same-vendor round-
    # trip emits the correct one.
    m = _TUNNEL_RE.match(stripped)
    if m:
        subtype = m.group(1).lower()
        idx = int(m.group(2)) if m.group(2) else 0
        return PortIdentity(
            kind="tunnel",
            index=idx,
            meta={"mikrotik_tunnel": subtype},
            original=name,
        )

    # VLAN subinterfaces: dotted ``<parent>.<id>`` form.  User-named
    # VLANs fall through as unknown — conservative behaviour since
    # the canonical preserves the verbatim name.
    m = _VLAN_DOT_RE.match(stripped)
    if m:
        return PortIdentity(
            kind="svi",
            index=int(m.group(2)),
            meta={"mikrotik_parent": m.group(1)},
            original=name,
        )

    # Bridge — virtual (aggregation but not a LAG).  Preserve the
    # specific name in meta so same-vendor round-trip restores
    # ``br-lan`` instead of collapsing to ``bridge``.
    if stripped.lower() == "bridge":
        return PortIdentity(
            kind="virtual", original=name,
            meta={"mikrotik_bridge": "bridge"},
        )
    if _BRIDGE_RE.match(stripped):
        return PortIdentity(
            kind="virtual", original=name,
            meta={"mikrotik_bridge": stripped},
        )

    return PortIdentity(kind="unknown", original=name)


def _flat_port_index(identity: PortIdentity) -> int:
    """Collapse a multi-coordinate physical port into a deterministic
    flat RouterOS port number.

    RouterOS uses **flat numbering** for ``ether<N>`` / ``sfp<N>`` /
    ``sfp-sfpplus<N>`` / ``qsfpplus<N>`` (per
    https://help.mikrotik.com/docs/spaces/ROS/pages/8323191/Ethernet ).
    It does NOT have a concept of per-module slots in the port NAME
    (QSFP sub-interface lanes are the one exception, expressed as
    ``qsfpplus<port>-<lane>``).  The cross-vendor orchestrator can
    therefore receive a :class:`PortIdentity` from a vendor that DOES
    encode hierarchical coordinates (Cisco c9300 stack:
    ``Te1/0/1..24`` plus ``Te1/1/1..8`` plus ``Fo1/1/1..2`` plus
    ``Twe1/1/1..2``) and the only safe single-pass collapse is to
    encode (stack, module, port) into one monotonically-increasing
    integer that is unique across the whole identity space.

    Scheme — chosen to keep the existing single-module ``ether1`` /
    ``sfp-sfpplus1`` numbering UNCHANGED for the common case and to
    spread non-zero-module ports into distinct numeric ranges that
    won't realistically collide with anything an operator would
    type by hand:

        * ``stack`` is 1-or-None and ``module`` is 0-or-None →
          return ``port`` (e.g. Cisco ``Gi1/0/24`` → ``ether24``,
          MikroTik ``ether1`` round-trip → ``ether1``).  Equivalent
          to the pre-fix behaviour for every shape that didn't
          collide.
        * Else → return ``(stack-1)*1000 + module*100 + port``
          (Cisco ``Te1/1/1`` → ``sfp-sfpplus101``, ``Te1/1/8`` →
          ``sfp-sfpplus108``, ``Te2/0/1`` → ``sfp-sfpplus1001``).

    The 100-port / 1000-port spacing leaves ample headroom for
    realistic line-card port counts (line cards top out at ~96
    ports in practice) and for the largest stack switches (16
    members on a c9500-stack).  Two source ports with identical
    (stack, module, port) coordinates would have collided anyway —
    the pre-fix behaviour silently emitted duplicate
    ``[ find name=sfp-sfpplus1 ]`` lines because every
    ``module>0`` port collapsed to the same name.

    User smoke-test issue #7 (``tests/fixtures/real/
    user_smoke_findings.md``) surfaced this on a 41-port Cisco
    c9300 source.
    """
    stack = identity.stack if identity.stack is not None else 1
    module = identity.module if identity.module is not None else 0
    port = identity.port if identity.port is not None else 1
    if stack <= 1 and module == 0:
        return port
    # ``max(..., 0)``: a 0-based source (Junos FPC 0, IOS-XR slot 0) has
    # stack == 0, and ``stack - 1`` made the whole index NEGATIVE --
    # ``xe-0/2/0`` rendered as ``sfp-sfpplus-800``, which is not a name.
    return max(stack - 1, 0) * 1000 + module * 100 + port


def format_port_identity(identity: PortIdentity) -> str | None:
    """Render a :class:`PortIdentity` as a RouterOS port name.

    Physical-port prefix selection uses (in priority order):

      1. ``meta["mikrotik_cage"]`` — exact same-vendor cage type.
      2. ``name_speed_hint`` — 40G/100G → ``qsfpplus<N>``, 25G →
         ``sfp28-<N>``, 10G → ``sfp-sfpplus<N>``.
      3. Falls back to ``ether<N>`` (RJ45 gigabit default).

    The numeric suffix is derived via :func:`_flat_port_index` so
    multi-module / stacked source identities (Cisco
    ``Te1/0/24`` + ``Te1/1/1`` + ``Fo1/1/1``) produce DISTINCT
    RouterOS names — RouterOS's flat ``sfp-sfpplus<N>`` /
    ``qsfpplus<N>`` numbering forces the hierarchical coordinates
    to flatten somewhere, and doing it inside the formatter keeps
    the cross-vendor bridge free of vendor-pair conditionals.  See
    :func:`_flat_port_index` for the collision-free scheme.

    25G and 10G are also separated into distinct cage prefixes
    (``sfp28-`` vs ``sfp-sfpplus``) — RouterOS hardware that ships
    SFP28 cages exposes them as ``sfp28-1`` / ``sfp28-2`` (CCR2004-
    1G-12S+2XS, see the ``sfp28_ids`` invariant in
    ``tests/unit/migration/test_target_profile_shipped.py``).
    Without the split, a Cisco source mixing 10G ``Te1/1/1..8`` and
    25G ``Twe1/1/1..2`` on the same module would still collide
    after flattening because both speeds previously mapped to
    ``sfp-sfpplus``.

    Tunnel formatter defaults to ``gre<N>`` when the source-side
    tunnel subtype is absent — most portable cross-vendor form.

    Returns None for kinds RouterOS can't express (``hw_aggregate``,
    ``mgmt``) and for unnamed ``virtual`` identities.
    """
    if identity.kind == "physical":
        flat = _flat_port_index(identity)
        cage = identity.meta.get("mikrotik_cage")
        if cage == "sfp":
            return f"sfp{flat}"
        if cage == "sfpplus":
            return f"sfp-sfpplus{flat}"
        if cage == "sfp28":
            return f"sfp28-{flat}"
        if cage == "combo":
            return f"combo{flat}"
        if identity.name_speed_hint in ("40gig", "100gig"):
            return f"qsfpplus{flat}"
        if identity.name_speed_hint == "25gig":
            return f"sfp28-{flat}"
        if identity.name_speed_hint == "10gig":
            return f"sfp-sfpplus{flat}"
        return f"ether{flat}"
    if identity.kind == "breakout":
        # MikroTik expresses QSFP+ breakout lanes with the ``-<lane>``
        # suffix on the parent QSFP name.  The QSFP port number itself
        # still goes through the multi-module flatten so cross-vendor
        # breakout parents from non-zero modules don't collide.
        cage = "qsfp28-" if identity.meta.get("mikrotik_cage") == "qsfp28" else "qsfpplus"
        return (
            f"{cage}{_flat_port_index(identity)}"
            f"-{identity.breakout_lane or 1}"
        )
    if identity.kind == "lag":
        return f"bond{identity.index or 1}"
    if identity.kind == "svi":
        parent = identity.meta.get("mikrotik_parent")
        if parent:
            return f"{parent}.{identity.index}"
        # Without a parent-interface hint, fall back to the
        # conventional ``vlanN`` form.  This matches the name the
        # /interface vlan render block emits (``add interface=
        # bridge1 name=vlanN vlan-id=N``); the /ip address loop then
        # emits ``interface=vlanN`` consistently.  Previously we
        # fell back to ``bridge.{index}`` which (a) is not a real
        # RouterOS interface name (the dotted form is reserved for
        # parent.id sub-interface lookups, where ``bridge`` alone
        # would have to exist as a parent — typically the bridge is
        # named ``bridge1`` not bare ``bridge``) and (b) didn't
        # match the ``name=vlan{id}`` convention used elsewhere in
        # the renderer, so the SVI canonical name and the rendered
        # VLAN interface name disagreed.  Surfaced by the user
        # smoke-test on a Cisco c9300-24ux source (issue #4 in
        # ``tests/fixtures/real/user_smoke_findings.md``).  Caller
        # can still override via rename_map.
        return f"vlan{identity.index}"
    if identity.kind == "loopback":
        return "lo" if identity.index in (None, 0) else f"loopback{identity.index}"
    if identity.kind == "tunnel":
        # Prefer the source-side subtype hint (same-vendor round-
        # trip preserves wg/gre/ipip/etc.); fall back to ``gre`` as
        # the most portable default for cross-vendor.
        subtype = identity.meta.get("mikrotik_tunnel", "gre")
        idx = identity.index if identity.index else 1
        return f"{subtype}{idx}" if subtype != "wg" else f"wg{idx}"
    if identity.kind == "virtual":
        bridge_name = identity.meta.get("mikrotik_bridge")
        if bridge_name:
            return bridge_name
        return None
    # hw_aggregate, mgmt, unknown — no RouterOS equivalent.
    return None

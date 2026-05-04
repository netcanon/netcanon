"""
Aruba AOS-S renderer — canonical tree to ``show running-config`` text.

Extracted from ``codec.py`` during the parse/render split per the
``codecs/README.md`` split-codec convention.  Public function
(consumed by ``codec.py::ArubaAOSSCodec.render()``):

* :func:`render_intent` — one-shot render: ``CanonicalIntent`` in,
  AOS-S CLI string out.

Emission order mirrors what AOS-S's own ``show running-config`` puts
on the wire so device round-trips diff cleanly: hostname, DNS, SNTP,
SNMP, RADIUS, DHCP-relay-comment-block, local users, LAG trunks,
VLAN stanzas (with absorbed SVI L3), physical interface stanzas,
static routes / default-gateway.

Internal helper re-exported from ``codec.py`` for tests that pin the
renderer's port-range compression contract:

* :func:`_format_port_list` — flat port list -> AOS-S range syntax,
  collapses contiguous numeric runs (``["1","2","3"] -> "1-3"``).
"""

from __future__ import annotations

import re
from typing import Any

from ..._user_secrets import classify_hash, is_migratable
from ...canonical.intent import CanonicalIntent
from ..base import RenderError


# ---------------------------------------------------------------------------
# Render-only constants and helpers
# ---------------------------------------------------------------------------


_MODE_TO_AOS_TRUNK_TYPE = {
    "active": "lacp",
    "passive": "lacp",    # AOS-S doesn't distinguish active/passive at this layer
    "static": "trunk",
}


#: AOS-S native physical / logical port-name shapes.  Used by the
#: foreign-port-stub elision path (Finding 8 in
#: ``user_smoke_findings.md``).  Names that do NOT match this shape
#: are foreign-vendor source-port leftovers (``igc0`` from OPNsense,
#: ``ge-0/0/0`` from Junos, ``eth0`` from Linux-style sources) — they
#: get elided when the canonical iface has no body content beyond the
#: default ``enabled=True``.  Mirrors the Junos tiered-elision policy
#: from ``juniper_junos/render.py::_IS_JUNOS_PHYSICAL_PORT_RE``.
#:
#: AOS-S native shapes covered (matches what the codec's own
#: :func:`port_names.format_port_identity` emits):
#:
#: * Bare port number — ``24`` (standalone switch).
#: * Stacked port — ``1/24`` (VSF stack member 1, port 24).
#: * Letter-slot uplink — ``1/A1`` (uplink module on chassis).
#: * Loopback — ``loopback0`` through ``loopback7``.
#: * VLAN SVI bare name — ``vlanN`` (rare on AOS-S since L3 absorbs
#:   into the ``vlan N`` block, but tolerate for robustness).
#: * OOBM — ``oobm`` (the dedicated mgmt sentinel).
#: * Trunk — ``trk1`` / ``Trk1`` (LAG names).
_IS_AOS_PHYSICAL_PORT_RE = re.compile(
    r"^(?:"
    r"\d+"                       # bare port: 24
    r"|\d+/\d+"                  # stacked: 1/24
    r"|\d+/[A-Za-z]\d+"          # letter-slot uplink: 1/A1
    r"|loopback\d+"              # loopback: loopback1
    r"|vlan\d+"                  # vlan SVI: vlan10 (rare on AOS-S)
    r"|oobm"                     # OOBM management
    r"|[Tt]rk\d+"                # LAG: trk1 / Trk1
    r")$"
)


#: VLAN-id-encoding interface name patterns.  Used by the SVI-IP
#: lookup (Finding 4) to discover an L3 SVI on a sibling
#: :class:`CanonicalInterface` when the canonical
#: :class:`CanonicalVlan` itself doesn't carry ``ipv4_addresses``.
#:
#: Matched forms (id captured in group 1):
#:
#: * ``Vlan10`` / ``vlan10`` — Cisco / generic factory-default.
#: * ``<svi-parent>.<N>`` — dotted form, RESTRICTED to parent names
#:   that are unambiguously SVI hosts on their source vendor:
#:
#:   * ``vlan<digits?>.<N>`` — OPNsense ``<if>vlan0.10</if>``,
#:     where the parent itself is a VLAN device.
#:   * ``irb.<N>`` — Junos Integrated Routing and Bridging unit
#:     (the literal name ``irb`` is reserved on Junos for VLAN
#:     SVIs).
#:   * ``port<digits>.<N>`` — FortiGate VLAN sub-interface, the
#:     vendor's canonical SVI shape (FortiGate has no separate
#:     ``interface Vlan<N>`` concept; the dot1Q sub-interface IS
#:     the L3 termination for that VLAN).
#:
#:   The earlier broader pattern ``^[A-Za-z][A-Za-z0-9_-]*\.\d+$``
#:   was too permissive — it matched Cisco / Arista routed
#:   sub-interfaces (``Ethernet1.10``, ``Port-Channel10.30``) which
#:   are 802.1Q L3 sub-interfaces on a routed parent, NOT the
#:   absorbed-into-VLAN SVI shape that Aruba consumes.  Stamping a
#:   sub-interface's IP onto an unrelated ``vlan N`` block was the
#:   Phase 4b "SVI absorption over-attribution" bug (see
#:   ``test_svi_absorption_over_attribution.py``).  The fix is the
#:   narrower whitelist below.
_VLAN_ID_BARE_RE = re.compile(r"^[Vv]lan(\d+)$")
_VLAN_ID_DOTTED_RE = re.compile(
    r"^(?:[Vv]lan\d*|irb|port\d+)\.(\d+)$"
)


def _vlan_iface_id(name: str) -> int | None:
    """Extract a VLAN id encoded in an interface name, if any.

    Returns the integer id when *name* matches one of the
    VLAN-id-encoding shapes (see :data:`_VLAN_ID_BARE_RE` /
    :data:`_VLAN_ID_DOTTED_RE`); returns ``None`` for shapes that
    don't carry a VLAN id (physical ports, LAGs, loopbacks).
    """
    m = _VLAN_ID_BARE_RE.match(name)
    if m:
        return int(m.group(1))
    m = _VLAN_ID_DOTTED_RE.match(name)
    if m:
        return int(m.group(1))
    return None


def _has_renderable_body(iface: Any) -> bool:
    """Return True when *iface* has any content worth emitting.

    Foreign-vendor source-port stubs (``igc0`` from OPNsense, ``eth0``
    from Linux-style sources) often appear in the canonical tree with
    only the default ``enabled=True`` flag — no description, no IPs,
    no MTU override, no L2 config.  These add noise to the AOS-S
    output without conveying any operator-actionable state.

    "Body" here = description, ipv4/ipv6 addresses, MTU non-default,
    explicitly disabled, switchport mode set, voice/access/trunk
    VLAN bindings, or LAG membership.  ``enabled=True`` alone (the
    default) is NOT body — it's the implicit admin-up state.

    Mirrors the Junos tiered-elision rule from
    ``juniper_junos/render.py``.
    """
    if iface.description:
        return True
    if iface.ipv4_addresses or iface.ipv6_addresses:
        return True
    if iface.mtu is not None:
        return True
    if not iface.enabled:
        return True
    if iface.switchport_mode is not None:
        return True
    if iface.access_vlan is not None:
        return True
    if iface.trunk_allowed_vlans:
        return True
    if iface.trunk_native_vlan is not None:
        return True
    if iface.voice_vlan is not None:
        return True
    if iface.lag_member_of:
        return True
    return False


#: Hash algorithms AOS-S accepts in the ``password manager user-name
#: <name> <alg> <hash>`` form.  Verified against Aruba's published
#: docs (Aruba 3810M/5400R Access Security Guide for AOS-S 16.11,
#: "Setting passwords and usernames" + the password command-options
#: reference).  AOS-S accepts ``plaintext``, ``sha1`` (40-char hex),
#: ``sha256`` (64-char hex).  ``sha512`` is NOT accepted (this is
#: the cross-vendor migration hazard from Cisco / Arista — operator
#: must reset the password rather than re-use the hash).  Cisco
#: type-5 (md5crypt) and type-9 (scrypt) are also unmigratable.
#:
#: This set expresses Aruba-NATIVE emit forms.  The cross-vendor
#: migratability gate (which algorithms AOS-S literally cannot
#: consume) lives in :mod:`netconfig.migration._user_secrets` and
#: is shared with fortigate_cli, juniper_junos, and opnsense codecs.
_AOS_KNOWN_ALGORITHMS = {"sha1", "sha256", "plaintext"}


def _split_aos_hash(hashed: str) -> tuple[str, str]:
    """Split a canonical ``hashed_password`` into (aos-algorithm, hash).

    Thin wrapper over the shared :func:`classify_hash` /
    :func:`is_migratable` policy in
    :mod:`netconfig.migration._user_secrets`.  Maps the shared
    helper's output to the historical Aruba return shape so the
    upstream caller and the existing unit tests stay unchanged:

        ``sha1:<hex>``        -> ("sha1", "<hex>")        [native]
        ``sha256:<hex>``      -> ("sha256", "<hex>")      [native]
        ``arista:sha512:...`` -> ("__unmigratable__", "sha512")
        ``5 <md5crypt>``      -> ("__unmigratable__", "5")
        ``9 <scrypt>``        -> ("__unmigratable__", "9")
        ``bcrypt:...``        -> ("__unmigratable__", "bcrypt")
        ``fortios:ENC ...``   -> ("__unmigratable__", "fortios")

    The sentinel ``"__unmigratable__"`` triggers comment-form
    emission upstream rather than producing a syntactically-correct
    but operationally-broken ``plaintext "..."`` line.  Operators
    see an explicit "reset this password" reminder.
    """
    alg, payload = classify_hash(hashed)
    # Aruba-native algorithm — emit verbatim using the AOS-S
    # ``password manager <alg> <hash>`` form.  ``_AOS_KNOWN_ALGORITHMS``
    # is the Aruba-local emit-form vocabulary; the shared helper's
    # accepted-set covers exactly the same three for ``aruba_aoss``,
    # but keeping this check local documents the AOS-S CLI grammar
    # that consumes the ``alg`` token verbatim.
    if alg in _AOS_KNOWN_ALGORITHMS:
        return alg, payload
    # Cross-vendor unmigratable hash — surface via comment-form
    # review line.  The shared policy decides; Aruba just adapts.
    if not is_migratable(hashed, "aruba_aoss"):
        return "__unmigratable__", alg
    # Unreachable in practice: every algorithm outside
    # ``_AOS_KNOWN_ALGORITHMS`` should fail the shared helper's
    # migratability gate.  Defensive plaintext wrap of the original
    # preserves Aruba's historical "verbatim under plaintext"
    # fallback for any unforeseen algorithm token.
    return "plaintext", hashed


def _lag_name_to_aos_trunk(name: str) -> str:
    """Translate a canonical LAG name to an AOS-S trunk name (``trk<N>``).

    AOS-S requires trunk names of the form ``trk<digits>``.  Non-native
    names (Cisco ``Port-channel1``, MikroTik ``bond1``, OPNsense ``lagg0``)
    are mapped by extracting their trailing digits.  If already
    ``trk<N>`` or ``Trk<N>`` (AOS-native), it's used as-is in lowercase.
    Names with no trailing digits fall back to ``trk1``.
    """
    if re.match(r"^[Tt]rk\d+$", name):
        return name.lower()
    m = re.search(r"(\d+)$", name)
    if m:
        return f"trk{m.group(1)}"
    return "trk1"


def _lag_mode_to_aos_type(mode: str) -> str:
    """Canonical LAG mode -> AOS-S ``trunk`` line's type field."""
    return _MODE_TO_AOS_TRUNK_TYPE.get(mode, "lacp")


#: AOS-S native port-name shapes that are safe to collapse into a
#: ``prefix<lo>-prefix<hi>`` range token.  These mirror the parse-
#: side ``_AOS_PORT_SHAPE_RE`` (in :mod:`.parse`) — only forms the
#: AOS-S range syntax can legitimately express get folded.  Foreign-
#: vendor names like ``ae0`` / ``ae1`` (Junos LAG) used to collapse
#: into ``ae0-ae1``, which is not valid AOS-S and shredded back into
#: ``["ae", "0", "1"]`` on parse-back; the bracketing prefix here
#: keeps those names verbatim.
_AOS_RANGEABLE_PREFIXES: set[str] = set()  # populated lazily; see below


def _is_collapsible_aos_prefix(prefix: str) -> bool:
    """Decide whether ``prefix<digits>`` is a valid AOS-S port name.

    AOS-S accepts these prefix shapes (per :mod:`.port_names`):

      * empty                 -- bare numeric (``24``)
      * single-letter A-Z     -- letter-prefix uplink (``A1``)
      * ``<digit>/``          -- stacked plain (``1/24``)
      * ``<digit>/<letter>``  -- stacked letter-slot (``1/A1``)
      * ``Trk`` / ``trk``     -- LAG

    Anything else (Junos ``ae``, ``et-``, ``xe-``; Cisco
    ``GigabitEthernet``; Arista ``Ethernet``; etc.) is a foreign-
    vendor name that must NOT be range-collapsed because the AOS-S
    parser would shred ``ae0-ae1`` into ``["ae0", "ae1"]`` (or
    worse) on parse-back.
    """
    if prefix == "":
        return True
    if re.match(r"^[A-Za-z]$", prefix):
        return True
    if re.match(r"^\d+/[A-Za-z]?$", prefix):
        return True
    if prefix.lower() == "trk":
        return True
    return False


def _format_port_list(ports: list[str]) -> str:
    """Render a flat port list back into AOS-S range syntax.

    Contiguous numeric ports with the same AOS-S-native alpha prefix
    collapse into ``prefix<lo>-prefix<hi>``.  Non-contiguous ports
    or ports whose prefix isn't a recognised AOS-S native shape are
    comma-joined verbatim — this guards foreign-vendor port names
    (Junos ``ae0``, ``xe-0/0/0``, Cisco ``GigabitEthernet1``) that
    leak through cross-vendor renders, since AOS-S range syntax
    cannot express them and the parse-side would shred any malformed
    range back into incoherent pieces.
    """
    if not ports:
        return ""
    # Group by alpha prefix preserving order.  Only ports that match
    # the simple ``<alpha>*<digits>$`` shape are eligible for range
    # collapse; anything else (containing ``-``, ``.``, ``/``-mid-
    # name, etc.) bypasses the collapse logic and emits verbatim.
    groups: list[tuple[str, list[int]]] = []
    for p in ports:
        m = re.match(r"^([A-Za-z]*)(\d+)$", p)
        if not m:
            groups.append((p, []))  # non-numeric port — keep as-is
            continue
        prefix, num = m.group(1), int(m.group(2))
        if not _is_collapsible_aos_prefix(prefix):
            # Foreign-vendor name (Junos ``ae0``, ``bond1``, etc.).
            # Emit verbatim — never collapse into a range token that
            # the AOS-S parser would mis-interpret.
            groups.append((p, []))
            continue
        if groups and groups[-1][0] == prefix and groups[-1][1]:
            groups[-1][1].append(num)
        else:
            groups.append((prefix, [num]))

    parts: list[str] = []
    for prefix, nums in groups:
        if not nums:
            parts.append(prefix)
            continue
        # Find runs of consecutive integers.
        run_start = nums[0]
        prev = nums[0]
        run: list[int] = [nums[0]]
        def flush(start: int, end: int) -> str:
            if start == end:
                return f"{prefix}{start}"
            return f"{prefix}{start}-{prefix}{end}"
        for n in nums[1:]:
            if n == prev + 1:
                run.append(n)
                prev = n
            else:
                parts.append(flush(run_start, prev))
                run_start = n
                prev = n
                run = [n]
        parts.append(flush(run_start, prev))
    return ",".join(parts)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def render_intent(tree: Any) -> str:
    """Render a :class:`CanonicalIntent` to AOS-S ``show running-
    config`` text.

    Raises:
        RenderError: If *tree* is not a CanonicalIntent.
    """
    if not isinstance(tree, CanonicalIntent):
        raise RenderError(
            "aruba_aoss: tree must be a CanonicalIntent.",
            yang_path="/",
        )

    lines: list[str] = []
    lines.append(
        "; generated by netconfig translator (aruba_aoss codec)"
    )

    if tree.hostname:
        lines.append(f'hostname "{tree.hostname}"')

    # Domain suffix — AOS-S form is ``ip dns domain-name <name>``,
    # verified against Aruba AOS-S 16.10/16.11 Management &
    # Configuration Guide ("Configuring a DNS entry") and the
    # AOS-S 16.11 IPv6 KB ``ip-dns-dom-nam.htm`` command-reference
    # page.  Finding 12 in ``user_smoke_findings.md``: OPNsense
    # source carries ``<domain>example.test</domain>`` which Aruba
    # was previously dropping silently.
    if tree.domain:
        lines.append(f"ip dns domain-name {tree.domain}")

    for server in tree.dns_servers:
        lines.append(f"ip dns server-address priority 1 {server}")

    for server in tree.ntp_servers:
        lines.append(f"sntp server priority 1 {server}")

    # SNMP (Tier 2)
    if tree.snmp is not None and (
        tree.snmp.community or tree.snmp.location
        or tree.snmp.contact or tree.snmp.trap_hosts
        or tree.snmp.v3_users
    ):
        if tree.snmp.community:
            lines.append(
                f'snmp-server community "{tree.snmp.community}" Operator'
            )
        if tree.snmp.location:
            lines.append(f'snmp-server location "{tree.snmp.location}"')
        if tree.snmp.contact:
            lines.append(f'snmp-server contact "{tree.snmp.contact}"')
        for host in tree.snmp.trap_hosts:
            comm = tree.snmp.community or "public"
            lines.append(
                f'snmp-server host {host} community "{comm}"'
            )
        # SNMPv3 users — emit the user line + (if group bound)
        # the group-binding line.  ``aes128`` canonical → ``aes``
        # on AOS-S wire (platform-natural default when unsuffixed).
        for u in tree.snmp.v3_users:
            parts = [f'snmpv3 user "{u.name}"']
            if u.auth_protocol:
                parts.append(
                    f'auth {u.auth_protocol} "{u.auth_passphrase}"'
                )
            if u.priv_protocol:
                wire_priv = (
                    "aes" if u.priv_protocol == "aes128"
                    else u.priv_protocol
                )
                parts.append(f'priv {wire_priv} "{u.priv_passphrase}"')
            lines.append(" ".join(parts))
            if u.group:
                lines.append(
                    f'snmpv3 group "{u.group}" user "{u.name}" '
                    f'sec-model ver3'
                )

    # RADIUS servers (Tier 2).  Emit one ``radius-server host``
    # line per server, with the inline key form (keeps each
    # server's secret co-located with its host for readability —
    # AOS-S accepts both inline and global-key forms).  When the
    # canonical record carries non-default UDP ports, emit a
    # companion ``radius-server host <ip> auth-port <N> acct-port
    # <N>`` line — AOS-S 16.10 Access Security Guide documents the
    # cumulative-update grammar (each repeated ``radius-server
    # host <ip>`` line refines the same entry).  Default ports
    # (1812 / 1813) are silenced to keep the wire minimal so
    # existing real-capture round-trips don't pick up spurious
    # ``auth-port 1812`` lines.
    for server in tree.radius_servers:
        if server.key:
            lines.append(
                f'radius-server host {server.host} key "{server.key}"'
            )
        else:
            lines.append(f"radius-server host {server.host}")
        if server.auth_port != 1812 or server.acct_port != 1813:
            lines.append(
                f"radius-server host {server.host} "
                f"auth-port {server.auth_port} "
                f"acct-port {server.acct_port}"
            )

    # DHCP pools — AOS-S doesn't run a DHCP server on most
    # platforms (it's a DHCP *relay* platform via
    # `ip helper-address`).  When a canonical carries DHCP pools,
    # emit a comment block so the data isn't silently dropped on
    # the way across — the human reviewer knows something to
    # reconfigure on a sibling DHCP server.
    if tree.dhcp_servers:
        lines.append("; DHCP pools from source codec are not supported")
        lines.append("; by AOS-S (AOS-S is a DHCP relay platform, not a")
        lines.append("; DHCP server).  Reconfigure on a sibling server.")
        for pool in tree.dhcp_servers:
            summary = (
                f";   network={pool.network or '?'} "
                f"gw={pool.gateway or '?'} "
                f"range={pool.start_ip}-{pool.end_ip}"
            )
            lines.append(summary)

    # Local users (Tier 2).  AOS-S form:
    #   password manager user-name "X" sha1 "<hash>"
    #   password operator user-name "Y" sha1 "<hash>"
    # Role derives from privilege: 15 -> manager, anything else ->
    # operator (AOS-S has no "superuser+limited" gradient like
    # Cisco's 1-15 scale; both roles are binary).  Hashes from
    # other codecs that AOS-S cannot consume (Cisco type-5/7/8/9,
    # Arista/Junos sha512, FortiGate ENC, OPNsense bcrypt) surface
    # as comment-form ``review:`` lines per the shared
    # :mod:`netconfig.migration._user_secrets` policy — operator
    # gets an explicit "reset this password" prompt rather than a
    # garbled line AOS-S would reject (or, worse, accept-as-plaintext).
    for user in tree.local_users:
        aos_role = "manager" if user.privilege_level == 15 else "operator"
        hash_alg, hash_val = _split_aos_hash(user.hashed_password)
        if hash_alg == "__unmigratable__":
            # AOS-S can't consume this hash format (sha512 from
            # Arista/Junos $6$, Cisco type-5/9, OPNsense/FortiGate
            # bcrypt).  Emit a comment-form line so operators see an
            # explicit "reset this password" reminder rather than a
            # garbled `plaintext "arista:sha512:$6$..."` line that
            # would either be rejected at deploy or, worse, accepted
            # as a literal plaintext password (severe security bug).
            lines.append(
                f'; password {aos_role} user-name "{user.name}" '
                f'-- review: {hash_val} hash from source vendor cannot '
                f'be re-used on AOS-S; reset this user password manually'
            )
            continue
        lines.append(
            f'password {aos_role} user-name "{user.name}" '
            f'{hash_alg} "{hash_val}"'
        )

    # LAGs — AOS-S uses a single top-level ``trunk <ports> <name>
    # <type>`` line per trunk.  Vendor-native LAG names (e.g.
    # Cisco ``Port-channel1``) are translated to AOS-S trunk names
    # (``trk1``) so the output is syntactically valid.
    for lag in tree.lags:
        if not lag.members:
            # Empty LAG — AOS-S has no syntax for declaring one
            # without members.  Emit a comment so the information
            # doesn't silently vanish.
            lines.append(
                f"; LAG {lag.name} declared without members — "
                f"cannot emit without ports"
            )
            continue
        port_list = _format_port_list(lag.members)
        trunk_name = _lag_name_to_aos_trunk(lag.name)
        trunk_type = _lag_mode_to_aos_type(lag.mode)
        lines.append(f"trunk {port_list} {trunk_name} {trunk_type}")

    # VLANs — the architecturally interesting part.  AOS-S's
    # VLAN-centric port membership is our canonical model's
    # natural form, so this is a direct projection.
    vlan_ifaces_by_name = {
        iface.name: iface for iface in tree.interfaces
        if iface.name.lower().startswith("vlan")
    }
    # Pre-index VLAN-id-encoding interfaces so the SVI-IP lookup
    # below is O(1) per VLAN.  Covers Cisco-style ``Vlan10``, OPNsense
    # ``vlan0.10`` (the ``<if>`` element value the parser carries
    # through verbatim from the ``<optN>`` zone), FortiGate
    # ``port1.10`` dotted form, and any other interface whose name
    # encodes a VLAN id via :func:`_vlan_iface_id`.  Used to recover
    # SVI L3 from cross-vendor sources that keep VLAN-id and
    # SVI-L3 on separate canonical objects (Finding 4 in
    # ``user_smoke_findings.md`` — OPNsense supergate fixture).
    iface_by_vlan_id: dict[int, Any] = {}
    for iface in tree.interfaces:
        vid = _vlan_iface_id(iface.name)
        if vid is not None and iface.ipv4_addresses:
            # VRF-bound IRB / SVI interfaces are NOT absorbable.
            # AOS-S's ``vlan N { ip address ... }`` stanza has no VRF
            # concept — collapsing a VRF-bound IRB into the vlan
            # block would silently strip the routing-instance
            # binding.  The Junos parser preserves these IRBs as
            # standalone interfaces (see ``juniper_junos/parse.py``
            # step 3 — IRBs with VRF bindings are NOT folded onto
            # their CanonicalVlan); the Aruba renderer must respect
            # that decision.  Surfaced by the Phase 4 mesh's
            # batfish_evpntype5_router1 fixture, where TENANT-A and
            # TENANT-B VRFs each carry irb.<vid> instances whose
            # IPs were ghosting onto sibling VLAN blocks.
            if iface.vrf:
                continue
            # First match wins — multiple SVIs for the same VLAN id
            # is a malformed canonical and shouldn't happen in
            # practice; we'd rather emit one SVI line than zero.
            iface_by_vlan_id.setdefault(vid, iface)
    # Track which interfaces were absorbed so the per-iface emission
    # loop skips them (otherwise we'd emit `interface vlan0.10` after
    # the L3 was already rolled into `vlan 10`).
    absorbed_iface_names: set[str] = set()
    for vlan in tree.vlans:
        lines.append(f"vlan {vlan.id}")
        if vlan.name:
            lines.append(f'   name "{vlan.name}"')
        if vlan.untagged_ports:
            lines.append(
                f"   untagged {_format_port_list(vlan.untagged_ports)}"
            )
        if vlan.tagged_ports:
            lines.append(
                f"   tagged {_format_port_list(vlan.tagged_ports)}"
            )
        # SVI absorption — codepath 2 of 3.  See
        # ._svi_absorption for the full rule.  SVI address may live
        # on:
        #   1. the canonical VLAN itself (same-vendor round-trip);
        #   2. a ``Vlan<N>`` CanonicalInterface (Cisco-style cross-
        #      vendor input);
        #   3. ANY CanonicalInterface whose name encodes the VLAN id
        #      via :func:`_vlan_iface_id` (OPNsense ``vlan0.10``,
        #      FortiGate ``port1.10``, generic ``vlan10``).
        # Honour whichever has data so all three input shapes render
        # identically.  The corresponding sibling iface is skipped
        # further down the interface emission loop.
        addrs = list(vlan.ipv4_addresses)
        svi_iface = vlan_ifaces_by_name.get(f"Vlan{vlan.id}")
        if not addrs and svi_iface is not None:
            addrs = list(svi_iface.ipv4_addresses)
            if addrs:
                absorbed_iface_names.add(svi_iface.name)
        if not addrs:
            id_match = iface_by_vlan_id.get(vlan.id)
            if id_match is not None:
                addrs = list(id_match.ipv4_addresses)
                if addrs:
                    absorbed_iface_names.add(id_match.name)
        for addr in addrs:
            lines.append(
                f"   ip address {addr.ip}/{addr.prefix_length}"
            )
        lines.append("   exit")

    # OOBM (out-of-band management) — AOS-S has a top-level `oobm`
    # block that's NOT a regular interface stanza.  When the cross-
    # vendor port-rename mesh maps an mgmt-kind interface (e.g.
    # Cisco GigabitEthernet0/0, Arista Management1) to "oobm",
    # render emits the dedicated block here and the per-iface loop
    # below skips it.  See Aruba Management & Configuration Guide
    # for AOS-S 16.10, "Out-of-Band Management" chapter.
    oobm_iface = next(
        (i for i in tree.interfaces if i.name == "oobm"), None,
    )
    if oobm_iface is not None:
        lines.append("oobm")
        for addr in oobm_iface.ipv4_addresses:
            lines.append(
                f"   ip address {addr.ip}/{addr.prefix_length}"
            )
        # IPv6 on OOBM: the `oobm ipv6 default-gateway` form is
        # documented at the top level.  An `ipv6 address` inside
        # the oobm context is unverified against AOS-S docs as of
        # this writing; we emit a comment flagging it for operator
        # review rather than guessing the syntax.
        for v6 in oobm_iface.ipv6_addresses:
            lines.append(
                f"   ; ipv6 address {v6.ip}/{v6.prefix_length} "
                f"-- review: AOS-S oobm IPv6 syntax not auto-emitted"
            )
        lines.append("   exit")

    # Physical / named interfaces.  Skip Vlan<N> stubs that were
    # already handled inside the VLAN stanza, and skip oobm (handled
    # above as a top-level block).
    #
    # Collision detection: cross-vendor port-rename can map two
    # distinct source interfaces to the same Aruba name (Cisco c9300's
    # ``AppGigabitEthernet1/0/1`` and ``TenGigabitEthernet1/0/1`` both
    # collapse to AOS-S ``1/1`` because they share the same stack/
    # module/port coordinates and Aruba has no dedicated app-hosting
    # virtual concept).  Emitting two ``interface 1/1`` stanzas would
    # be rejected by AOS-S.  Group physical interfaces by name; emit
    # only the FIRST occurrence and surface every collision via a
    # comment-form review block so the operator can decide which
    # source to keep / which to drop manually.  ``description`` is
    # the realistic disambiguator — cross-vendor port-rename rewrites
    # ``iface.name`` but preserves ``description`` from the source
    # config, so operators see the original vendor-name in the
    # collision review block.
    physical_ifaces: list[Any] = []
    for iface in tree.interfaces:
        lname = iface.name.lower()
        if lname.startswith("vlan"):
            continue
        if iface.name == "oobm":
            continue
        # Drop interfaces whose L3 was already absorbed into a VLAN
        # block above (covers OPNsense-style ``vlan0.10`` SVI
        # entries — see SVI-IP lookup in the VLAN render loop).
        if iface.name in absorbed_iface_names:
            continue
        # Foreign-vendor source-port stub elision (Finding 8 in
        # ``user_smoke_findings.md``).  When the canonical name
        # doesn't match an AOS-S native shape AND the iface has no
        # body content beyond default ``enabled=True``, drop it.
        # Mirrors the Junos tiered-elision policy from
        # ``juniper_junos/render.py``.  Foreign names with real body
        # (description, IPs, MTU, disabled) are KEPT so operators
        # see the source content even though the port name will
        # need post-deploy editing.  Native-shape names with empty
        # bodies are KEPT for round-trip stability (matches Junos
        # treatment of ``ge-0/0/0``-shape stubs).
        if not _IS_AOS_PHYSICAL_PORT_RE.match(iface.name):
            if not _has_renderable_body(iface):
                continue
        physical_ifaces.append(iface)
    seen_names: dict[str, list[Any]] = {}
    name_order: list[str] = []
    for iface in physical_ifaces:
        if iface.name not in seen_names:
            seen_names[iface.name] = []
            name_order.append(iface.name)
        seen_names[iface.name].append(iface)
    # Surface collisions up-front so the comment block reads as a
    # contiguous review header rather than getting interleaved with
    # the per-interface stanzas below.
    for nm in name_order:
        group = seen_names[nm]
        if len(group) <= 1:
            continue
        lines.append(
            f"; interface {nm} collides — kept first occurrence, "
            f"skipped {len(group) - 1} duplicate(s) (review)"
        )
        for dup in group:
            descriptor = dup.description or dup.name
            lines.append(f";   collided source: {descriptor}")

    rendered_names: set[str] = set()
    for iface in physical_ifaces:
        lname = iface.name.lower()
        if iface.name in rendered_names:
            # Duplicate canonical name maps to the same Aruba port —
            # already flagged in the comment block above; skip the
            # stanza so AOS-S doesn't see two ``interface <name>``.
            continue
        rendered_names.add(iface.name)
        # Loopback interfaces use AOS-S `interface loopback <N>`
        # syntax; the rest of the body (ip address, ipv6 address,
        # description) is identical to the physical-port form.
        # See Aruba Basic Operation Guide for AOS-S 16.10,
        # "Managing loopback interfaces" chapter.
        if lname.startswith("loopback"):
            lines.append(f"interface {iface.name}")
        else:
            lines.append(f"interface {iface.name}")
        if iface.description:
            lines.append(f'   name "{iface.description}"')
        # Skip enable/disable + routing markers on logical
        # interfaces (loopback is always-up, has no routing toggle).
        is_logical = lname.startswith("loopback")
        if not is_logical:
            if iface.enabled:
                lines.append("   enable")
            else:
                lines.append("   disable")
        if iface.ipv4_addresses or iface.ipv6_addresses:
            if not is_logical:
                lines.append("   routing")
            for addr in iface.ipv4_addresses:
                lines.append(
                    f"   ip address {addr.ip}/{addr.prefix_length}"
                )
            # GAP-EVPN-3: IPv6 addresses.
            for v6 in iface.ipv6_addresses:
                if v6.scope == "link-local":
                    lines.append(
                        f"   ipv6 address {v6.ip}/{v6.prefix_length} link-local"
                    )
                else:
                    lines.append(
                        f"   ipv6 address {v6.ip}/{v6.prefix_length}"
                    )
        lines.append("   exit")

    # Static routes.  Default route (0.0.0.0/0) becomes
    # ``ip default-gateway`` per AOS-S convention.
    for route in tree.static_routes:
        if route.destination in ("0.0.0.0/0", "default"):
            lines.append(f"ip default-gateway {route.gateway}")
        else:
            lines.append(
                f"ip route {route.destination} {route.gateway}"
            )

    return "\n".join(lines) + "\n"

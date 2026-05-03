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


#: Hash algorithms AOS-S accepts in the ``password manager user-name
#: <name> <alg> <hash>`` form.  Verified against Aruba's published
#: docs (Aruba 3810M/5400R Access Security Guide for AOS-S 16.11,
#: "Setting passwords and usernames" + the password command-options
#: reference).  AOS-S accepts ``plaintext``, ``sha1`` (40-char hex),
#: ``sha256`` (64-char hex).  ``sha512`` is NOT accepted (this is
#: the cross-vendor migration hazard from Cisco / Arista — operator
#: must reset the password rather than re-use the hash).  Cisco
#: type-5 (md5crypt) and type-9 (scrypt) are also unmigratable.
_AOS_KNOWN_ALGORITHMS = {"sha1", "sha256", "plaintext"}

#: Algorithms whose hashes AOS-S literally cannot consume — emit a
#: comment-form `; password manager ... -- review:` line and skip
#: the ``password ...`` command, so the rendered config commits
#: clean and the operator gets an explicit reminder rather than a
#: line AOS-S would reject (or worse: accept-as-plaintext garbage).
_AOS_UNMIGRATABLE_ALGORITHMS = {
    "sha512",      # Arista / Junos $6$ hashes
    "5",           # Cisco IOS type-5 (md5crypt with leading "5 ")
    "9",           # Cisco IOS-XE type-9 (scrypt with leading "9 ")
    "8",           # Cisco IOS-XE type-8 (PBKDF2-SHA256)
    "7",           # Cisco IOS type-7 reversible XOR (sometimes leading "7 ")
    "bcrypt",      # OPNsense / pfSense
    "fortios",     # FortiGate ENC-encrypted
}


def _split_aos_hash(hashed: str) -> tuple[str, str]:
    """Split a canonical ``hashed_password`` into (aos-algorithm, hash).

    Canonical entries carry hashes from multiple vendors in a few
    shapes.  Map each to the closest AOS-S algorithm keyword:

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
    # Vendor-tagged form: ``arista:sha512:<...>`` / ``cisco:type9:<...>``
    # Tagged forms have TWO colons; the first segment is the source
    # vendor and the second is the algorithm.
    if ":" in hashed:
        first, _, rest = hashed.partition(":")
        if rest and ":" in rest:
            alg, _, _val = rest.partition(":")
            alg_low = alg.lower()
            if alg_low in _AOS_UNMIGRATABLE_ALGORITHMS:
                return "__unmigratable__", alg_low
            if alg_low in _AOS_KNOWN_ALGORITHMS:
                return alg, _val
        # Single-colon form: ``alg:<value>``
        alg_low = first.lower()
        if alg_low in _AOS_KNOWN_ALGORITHMS:
            return first, rest
        if alg_low in _AOS_UNMIGRATABLE_ALGORITHMS:
            return "__unmigratable__", alg_low
        # Unknown algorithm — preserve verbatim under plaintext.
        return "plaintext", hashed
    # Bare leading-digit Cisco form: ``5 $1$...`` / ``9 $9$...``.
    head, _, _tail = hashed.partition(" ")
    if head in _AOS_UNMIGRATABLE_ALGORITHMS:
        return "__unmigratable__", head
    # No algorithm tag — last-resort plaintext wrap.
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


def _format_port_list(ports: list[str]) -> str:
    """Render a flat port list back into AOS-S range syntax.

    Contiguous numeric ports with the same alpha prefix collapse into
    ``prefix<lo>-prefix<hi>``.  Non-contiguous ports are comma-joined.
    """
    if not ports:
        return ""
    # Group by alpha prefix preserving order.
    groups: list[tuple[str, list[int]]] = []
    for p in ports:
        m = re.match(r"^([A-Za-z]*)(\d+)$", p)
        if not m:
            groups.append((p, []))  # non-numeric port — keep as-is
            continue
        prefix, num = m.group(1), int(m.group(2))
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
    # AOS-S accepts both inline and global-key forms).
    for server in tree.radius_servers:
        if server.key:
            lines.append(
                f'radius-server host {server.host} key "{server.key}"'
            )
        else:
            lines.append(f"radius-server host {server.host}")

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
    # other codecs (Cisco type-5/9, FortiGate bcrypt, OPNsense
    # bcrypt) get emitted verbatim under a best-effort
    # ``plaintext`` algorithm marker — real AOS-S will reject
    # non-sha1 hashes at config-push time, but render is lossless
    # from the canonical's perspective and the lossiness surfaces
    # on deploy rather than silently here.
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
        # ._svi_absorption for the full rule.  SVI address may
        # live on the vlan itself (same-vendor round-trip) OR on
        # a ``Vlan<N>`` CanonicalInterface (cross-vendor input
        # from a codec that keeps VLAN L3 separate) — honour
        # whichever has data so both input shapes render
        # identically.  Corresponding Vlan<N> iface is skipped
        # further down the interface emission loop.
        addrs = list(vlan.ipv4_addresses)
        svi_iface = vlan_ifaces_by_name.get(f"Vlan{vlan.id}")
        if not addrs and svi_iface is not None:
            addrs = list(svi_iface.ipv4_addresses)
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

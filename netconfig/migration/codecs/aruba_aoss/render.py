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


_AOS_KNOWN_ALGORITHMS = {"sha1", "plaintext"}


def _split_aos_hash(hashed: str) -> tuple[str, str]:
    """Split a canonical ``hashed_password`` into (aos-algorithm, hash).

    Canonical entries carry hashes from multiple vendors in a few
    shapes.  Map each to the closest AOS-S algorithm keyword so the
    ``password manager ...`` line is at least syntactically valid:

        ``sha1:<hex>``      -> ("sha1", "<hex>")            [Aruba native]
        ``bcrypt:<...>``    -> ("plaintext", "bcrypt:<...>") [OPNsense/FortiGate]
        ``fortios:ENC ...`` -> ("plaintext", "fortios:ENC ...") [FortiGate]
        ``5 <md5crypt>``    -> ("plaintext", "5 <md5crypt>") [Cisco legacy]
        ``9 <scrypt>``      -> ("plaintext", "9 <scrypt>")   [Cisco IOS-XE]

    AOS-S only understands ``sha1`` and ``plaintext`` at this position.
    Foreign algorithm tags are re-wrapped under ``plaintext`` with the
    original tag preserved inside the value — the line stays
    syntactically valid, and the deploy-time rejection is explicit
    rather than silently-corrupted canonical data.
    """
    if ":" in hashed:
        alg, _, val = hashed.partition(":")
        if alg.lower() in _AOS_KNOWN_ALGORITHMS:
            return alg, val
        # Foreign algorithm — preserve the full original string so a
        # reverse translation can recover it.
        return "plaintext", hashed
    # No algorithm tag — looks like a bare Cisco "5 $1$..." or similar.
    # Wrap as plaintext.
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

    # Physical / named interfaces.  Skip Vlan<N> stubs that were
    # already handled inside the VLAN stanza.
    for iface in tree.interfaces:
        if iface.name.lower().startswith("vlan"):
            continue
        lines.append(f"interface {iface.name}")
        if iface.description:
            lines.append(f'   name "{iface.description}"')
        if iface.enabled:
            lines.append("   enable")
        else:
            lines.append("   disable")
        if iface.ipv4_addresses or iface.ipv6_addresses:
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

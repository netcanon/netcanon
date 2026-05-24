"""
OPNsense ``config.xml`` renderer — CanonicalIntent to XML.

Extracted from ``codec.py`` during the parse/render split.  Public
surface (consumed by codec.py's ``render()`` method):

* :func:`render_intent` — one-shot render: ``CanonicalIntent`` (or
  legacy dict) in, ``config.xml`` body string out.
* :func:`render_canonical` — canonical-tree path used when the input
  is a :class:`CanonicalIntent`.
* :func:`render_legacy` — dict-tree path retained for back-compat
  with older tests that drive the codec via the legacy nested-dict
  shape.

The canonical render emits blocks in a stable order so re-imports
(and textual diffs) stay friendly: ``<system>`` → ``<interfaces>``
→ ``<vlans>`` → ``<dhcpd>`` → ``<laggs>`` → ``<snmpd>`` →
``<virtualip>`` (only when at least one :class:`CanonicalVRRPGroup`
has ``mode="carp"``; non-CARP modes emit XML comments and skip
the ``<vip>`` element entirely — OPNsense has no native VRRP /
HSRP wire grammar).  CARP advskew is the inverted normalisation
of canonical priority (``advskew = 254 - priority``) reflecting
CARP's lower-wins election semantics.

Output is the OPNsense convention: no ``<?xml ...?>`` declaration,
just the top-level ``<opnsense>`` element pretty-printed with
two-space indentation.  Real OPNsense-generated config.xml files
match this shape; consumers that want a prolog can prepend one.

Shares no helpers with :mod:`.parse` directly — the LAG proto map
is duplicated in inverted form here because each module owns the
direction it consumes; this mirrors the fortigate_cli convention
of keeping both directions adjacent to the code that uses them.
"""

from __future__ import annotations

from typing import Any
from xml.etree import ElementTree as ET

from ..._user_secrets import (
    classify_hash,
    format_review_comment,
    is_migratable,
)
from ...canonical.intent import CanonicalIntent
from ..base import RenderError


# ---------------------------------------------------------------------------
# Top-level render entry — codec.render() is a one-line delegator to this.
# ---------------------------------------------------------------------------


def render_intent(tree: Any) -> str:
    """Render a :class:`CanonicalIntent` (or legacy dict) to OPNsense
    ``config.xml`` text.

    Args:
        tree: Either a :class:`CanonicalIntent` (the modern path used
            by all production callers, dispatched to
            :func:`render_canonical`) or a ``dict`` (the legacy
            nested-dict shape preserved for older tests that haven't
            been migrated, dispatched to :func:`render_legacy`).

    Raises:
        RenderError: If *tree* is neither a :class:`CanonicalIntent`
            nor a ``dict``.
    """
    if isinstance(tree, CanonicalIntent):
        return render_canonical(tree)
    if isinstance(tree, dict):
        return render_legacy(tree)
    raise RenderError(
        "opnsense: tree must be a CanonicalIntent or dict",
        yang_path="/",
    )


def render_canonical(intent: CanonicalIntent) -> str:
    """Render from the canonical intent shape."""
    root = ET.Element("opnsense")

    # System — attach hostname/domain/users under a single <system>
    # element so real OPNsense tooling (and our own re-parse) sees
    # a single canonical block.
    has_system_content = (
        intent.hostname or intent.domain or intent.local_users
        or intent.radius_servers or intent.dns_servers
    )
    if has_system_content:
        sys_el = ET.SubElement(root, "system")
        if intent.hostname:
            ET.SubElement(sys_el, "hostname").text = intent.hostname
        if intent.domain:
            ET.SubElement(sys_el, "domain").text = intent.domain
        # System DNS servers — emit one ``<dnsserver>`` per entry to
        # match the real-OPNsense shape (repeated children, NOT a
        # comma-joined single element).  This is the inverse of the
        # parser branch that walks ``<system>/<dnsserver>`` children
        # into ``intent.dns_servers``.  Per-DHCP-pool DNS lists are a
        # different field (``CanonicalDHCPPool.dns_servers``) emitted
        # later under ``<dhcpd>/<zone>/<dnsserver>`` as a comma-joined
        # value — that wire-form is intentionally distinct.
        for dns_ip in intent.dns_servers:
            ET.SubElement(sys_el, "dnsserver").text = dns_ip
        # RADIUS servers (Tier 2).  Emit a <system>/<authserver>
        # element per server, typed "radius", with the canonical
        # host/secret/ports preserved.
        for idx, server in enumerate(intent.radius_servers, start=1):
            auth_el = ET.SubElement(sys_el, "authserver")
            ET.SubElement(auth_el, "name").text = (
                f"radius-{idx}"
            )
            ET.SubElement(auth_el, "type").text = "radius"
            ET.SubElement(auth_el, "host").text = server.host
            if server.key:
                ET.SubElement(auth_el, "radius_secret").text = server.key
            ET.SubElement(auth_el, "radius_auth_port").text = (
                str(server.auth_port)
            )
            ET.SubElement(auth_el, "radius_acct_port").text = (
                str(server.acct_port)
            )

        # Local users (Tier 2).  Map canonical admin -> admins
        # group, anything else -> users.  OPNsense's ``<password>``
        # element only consumes bcrypt (``$2y$10$...``) hashes —
        # FreeBSD's PHP-side password_verify() rejects everything
        # else.  Foreign hashes (Cisco type-5/8/9, Arista sha512,
        # FortiGate ENC, plain md5crypt) cannot be re-used; emitting
        # them as-is leaks the source hash literal as the password
        # element value (CRITICAL security bug — see
        # tests/fixtures/real/user_smoke_findings.md issue #1).
        #
        # Policy lives in :mod:`netcanon.migration._user_secrets`
        # (``_TARGET_ACCEPTS["opnsense"] = {plaintext, bcrypt}``).
        # When the hash is unmigratable, emit a comment-form review
        # line INSIDE the ``<user>`` element naming the source
        # algorithm so the operator knows what to reset from, and
        # skip the ``<password>`` child entirely.  Plaintext is
        # accepted verbatim (operator-supplied).
        for user in intent.local_users:
            user_el = ET.SubElement(sys_el, "user")
            ET.SubElement(user_el, "name").text = user.name
            if user.hashed_password:
                if is_migratable(user.hashed_password, "opnsense"):
                    # Strip the ``alg:`` tag so OPNsense's
                    # <password> element carries the raw value
                    # (e.g. ``$2y$10$...`` for bcrypt; the literal
                    # password for plaintext).
                    algorithm, payload = classify_hash(user.hashed_password)
                    if algorithm == "plaintext":
                        hash_out = payload or user.hashed_password
                    else:
                        hash_out = payload
                    ET.SubElement(user_el, "password").text = hash_out
                else:
                    # Comment-form review line — XML comment syntax
                    # places a sibling <!-- ... --> node inside the
                    # <user> element so the operator sees a clear
                    # "reset this password" reminder rather than a
                    # broken hash literal masquerading as bcrypt.
                    #
                    # The shared helper natively produces an
                    # XML-comment-safe body (single-dash separator
                    # for ``comment_syntax="xml"``) so we can embed
                    # the body directly without local post-processing.
                    algorithm, _payload = classify_hash(user.hashed_password)
                    review = format_review_comment(
                        user.name, algorithm, comment_syntax="xml",
                        target_label="OPNsense",
                    )
                    body = review.removeprefix("<!-- ").removesuffix(" -->")
                    user_el.append(ET.Comment(body))
            # Sub-finding 19 round-trip: emit ``<scope>system</scope>``
            # only for admin-tier users so the parser's new symmetric
            # rule (scope=system OR priv=page-all OR groupname=admins
            # → admin) doesn't mis-elevate non-admin users on
            # re-parse.  Real OPNsense reserves ``system`` scope for
            # built-in privileged accounts (root, operator) and uses
            # ``user`` scope for everything else; this aligns with
            # that convention and keeps within-vendor round-trip
            # stable.  Mirror the priv elevation symmetrically: emit
            # ``<priv>page-all</priv>`` for admin users so a
            # privilege-15 record from any source (including ones
            # that lacked the ``admins`` groupname on parse) survives
            # parse → render → parse.
            is_admin = user.privilege_level == 15
            ET.SubElement(user_el, "scope").text = (
                "system" if is_admin else "user"
            )
            ET.SubElement(user_el, "groupname").text = (
                "admins" if is_admin else "users"
            )
            if is_admin:
                ET.SubElement(user_el, "priv").text = "page-all"

    # Interfaces — render as zone-keyed elements.
    # For canonical intents from OTHER vendors we need to assign zone
    # names.  Use the interface name as the zone if it looks like an
    # OPNsense zone (wan/lan/optN), otherwise sanitise the name into
    # a valid XML tag (must start with a letter; no slashes/spaces).
    #
    # The sanitisation in ``_zone_tag_for`` is non-invertible (it
    # lower-cases, replaces non-alphanumerics with ``_``, prepends
    # ``if_`` for digit-leading names) — ``Ethernet0`` -> ``ethernet0``,
    # ``1/A1`` -> ``if_1_a1``, ``A1`` -> ``a1``.  To keep the round-trip
    # invertible we ALWAYS emit a stable ``<if>`` child carrying the
    # canonical iface name verbatim; the parser prefers ``<if>`` text
    # over the zone tag so the original port-name identity survives
    # parse -> render -> parse cycles.  This mirrors real OPNsense XML,
    # where ``<if>`` carries the underlying physical port name (e.g.
    # ``<lan><if>igb0</if>...</lan>``).
    #
    # Two cooperating defects this addresses:
    #   1. Empty-zone drop — render previously emitted self-closing
    #      ``<optN/>`` for sparse interfaces (no IP, no descr, disabled),
    #      which the parser then dropped via the "no children" rule.
    #      The mandatory ``<if>`` child guarantees the zone is never
    #      empty so disabled / sparse ifaces survive round-trip.
    #   2. Zone-tag mangling — ``_zone_tag_for`` is lossy; the ``<if>``
    #      child carries the unmangled name so reparse can recover it.
    if intent.interfaces:
        ifaces_el = ET.SubElement(root, "interfaces")
        used_tags: dict[str, int] = {}
        for iface in intent.interfaces:
            base_tag = _zone_tag_for(iface.name)
            # Disambiguate collisions: if two distinct canonical names
            # sanitise to the same tag (e.g. ``A1`` and ``a1`` both
            # collapse to ``a1``), append ``_2``, ``_3``, ... so
            # element identity stays unique within ``<interfaces>``.
            seen = used_tags.get(base_tag, 0)
            if seen == 0:
                zone_name = base_tag
            else:
                zone_name = f"{base_tag}_{seen + 1}"
            used_tags[base_tag] = seen + 1
            zone_el = ET.SubElement(ifaces_el, zone_name)
            # Always emit ``<if>`` FIRST carrying the canonical name
            # verbatim — keeps the iface name round-trippable across
            # the lossy zone-tag sanitisation, and ensures sparse /
            # disabled-only interfaces are never empty (so the parser
            # doesn't drop them under the empty-stub rule).
            ET.SubElement(zone_el, "if").text = iface.name
            # kind=mgmt cascade marker — when the canonical interface
            # carries the explicit mgmt role (cisco_iosxe_cli's
            # Mgmt-vrf promotion, arista's Management<N> classifier,
            # junos's fxp0), surface a ``<descr>Management</descr>``
            # so the OPNsense UI labels the zone clearly even when
            # the source had no human-readable description.  An
            # operator-supplied description still wins.  Documented
            # at docs.opnsense.org/manual/interfaces.html — the
            # ``<descr>`` element is the zone label in the GUI.
            if iface.description:
                ET.SubElement(zone_el, "descr").text = iface.description
            elif iface.kind == "mgmt":
                ET.SubElement(zone_el, "descr").text = "Management"
            if iface.enabled:
                ET.SubElement(zone_el, "enable")
            if iface.mtu is not None:
                ET.SubElement(zone_el, "mtu").text = str(iface.mtu)
            # Sub-finding 9a round-trip: a CanonicalInterface with
            # ``dhcp_client=True`` represents the OPNsense WAN-DHCP
            # shape (``<ipaddr>dhcp</ipaddr>``).  Emit the keyword
            # form so parse → render → parse preserves the flag.
            # Static IPs take precedence — a DHCP-client interface
            # with a manually-pinned address shouldn't exist in
            # OPNsense's data model, but if both are set the static
            # wins (matches the parser's IF/ELIF order).
            if iface.ipv4_addresses:
                ET.SubElement(zone_el, "ipaddr").text = iface.ipv4_addresses[0].ip
                ET.SubElement(zone_el, "subnet").text = str(iface.ipv4_addresses[0].prefix_length)
            elif iface.dhcp_client:
                ET.SubElement(zone_el, "ipaddr").text = "dhcp"
            # GAP-EVPN-3: IPv6 emits to ``<ipaddrv6>`` + ``<subnetv6>``.
            # Only one v6 address fits the OPNsense schema.
            #
            # ``dhcp_client_v6`` (dhcp6 / slaac / track6 / 6rd / 6to4)
            # is the keyword form on ``<ipaddrv6>`` — no ``<subnetv6>``
            # accompanies it.  Static address takes precedence (OPNsense
            # doesn't accept both); the parser's IF/ELIF order matches.
            if iface.ipv6_addresses:
                ET.SubElement(zone_el, "ipaddrv6").text = iface.ipv6_addresses[0].ip
                ET.SubElement(zone_el, "subnetv6").text = str(iface.ipv6_addresses[0].prefix_length)
            elif iface.dhcp_client_v6:
                ET.SubElement(zone_el, "ipaddrv6").text = iface.dhcp_client_v6

    # VLANs — emit <vlans><vlan> per CanonicalVlan.  Real OPNsense
    # <vlan> elements REQUIRE a <if> child naming the parent
    # physical / lagg interface; without it the VLAN cannot bind
    # at the kernel level and OPNsense's UI also refuses to save.
    # See real fixtures under tests/fixtures/real/opnsense/ — every
    # <vlan> carries <if>, <tag>, <pcp>, <proto/>, <descr>, <vlanif>
    # in that order, and the OPNsense docs at
    # https://docs.opnsense.org/manual/other-interfaces.html confirm
    # parent-interface + tag are mandatory.  Emitting a <vlan> with
    # only <tag> (the prior bug) leaked invalid XML to operators
    # — see tests/fixtures/real/user_smoke_findings.md issue #5.
    #
    # Parent-interface lookup walks LAGs and physical interfaces in
    # canonical order: prefer a LAG that carries this VLAN on its
    # trunk, then fall back to "first lagg", then "first physical".
    if intent.vlans:
        vlans_el = ET.SubElement(root, "vlans")
        parent_default = _vlan_parent_default(intent)
        for vlan in intent.vlans:
            vlan_el = ET.SubElement(vlans_el, "vlan")
            parent_if = _vlan_parent_for(vlan, intent, parent_default)
            ET.SubElement(vlan_el, "if").text = parent_if
            ET.SubElement(vlan_el, "tag").text = str(vlan.id)
            ET.SubElement(vlan_el, "pcp").text = "0"
            ET.SubElement(vlan_el, "proto")
            if vlan.name:
                ET.SubElement(vlan_el, "descr").text = vlan.name
            # OPNsense convention: <vlanif> carries the synthesised
            # device name "<parent>_vlan<tag>" used by the kernel
            # to instantiate the 802.1Q child interface.  Real
            # exports use both this form and the FreeBSD-historical
            # "vlan0.<tag>" sequential form; the parent_vlan_tag
            # form is unambiguous when multiple parents carry
            # different VLANs.
            ET.SubElement(vlan_el, "vlanif").text = (
                f"{parent_if}_vlan{vlan.id}"
            )

    # DHCP pools (Tier 2).  OPNsense keys DHCP config by interface
    # zone; use the canonical pool's ``interface`` field as the
    # zone tag, falling back to ``lan`` if unset (single-zone
    # default).  Foreign canonical pools (from other vendors that
    # don't carry an OPNsense-style zone name) get a sanitised
    # tag via the same _zone_tag_for helper used for interfaces.
    if intent.dhcp_servers:
        dhcpd_el = ET.SubElement(root, "dhcpd")
        for pool in intent.dhcp_servers:
            zone_tag = _zone_tag_for(pool.interface) if pool.interface else "lan"
            zone_el = ET.SubElement(dhcpd_el, zone_tag)
            ET.SubElement(zone_el, "enable")
            if pool.start_ip or pool.end_ip:
                range_el = ET.SubElement(zone_el, "range")
                if pool.start_ip:
                    ET.SubElement(range_el, "from").text = pool.start_ip
                if pool.end_ip:
                    ET.SubElement(range_el, "to").text = pool.end_ip
            if pool.gateway:
                ET.SubElement(zone_el, "gateway").text = pool.gateway
            if pool.dns_servers:
                ET.SubElement(zone_el, "dnsserver").text = (
                    ",".join(pool.dns_servers)
                )
            if pool.domain_name:
                ET.SubElement(zone_el, "domain").text = pool.domain_name
            if pool.lease_time:
                ET.SubElement(zone_el, "defaultleasetime").text = (
                    str(pool.lease_time)
                )

    # LAGs (Tier 2) — <laggs> element with one <lagg> per LAG.
    if intent.lags:
        laggs_el = ET.SubElement(root, "laggs")
        for lag in intent.lags:
            lagg_el = ET.SubElement(laggs_el, "lagg")
            ET.SubElement(lagg_el, "laggif").text = lag.name
            if lag.members:
                ET.SubElement(lagg_el, "members").text = ",".join(lag.members)
            ET.SubElement(lagg_el, "proto").text = (
                _CANONICAL_MODE_TO_OPNSENSE_PROTO.get(lag.mode, "lacp")
            )

    # SNMP (Tier 2) — OPNsense snmpd plugin element.
    if intent.snmp is not None and (
        intent.snmp.community or intent.snmp.location
        or intent.snmp.contact or intent.snmp.trap_hosts
    ):
        snmpd = ET.SubElement(root, "snmpd")
        if intent.snmp.community:
            ET.SubElement(snmpd, "rocommunity").text = intent.snmp.community
        if intent.snmp.location:
            ET.SubElement(snmpd, "syslocation").text = intent.snmp.location
        if intent.snmp.contact:
            ET.SubElement(snmpd, "syscontact").text = intent.snmp.contact
        for host in intent.snmp.trap_hosts:
            ET.SubElement(snmpd, "traphost").text = host

    # <virtualip> block — emit CARP VIPs from CanonicalVRRPGroup.
    # OPNsense's <virtualip> hosts CARP (and historical pure-VRRP)
    # virtual-IP records.  We render every group with ``mode="carp"``
    # (and ``mode="vrrp"`` as a low-volume secondary form) into a
    # ``<vip>`` child.  Groups in other modes (HSRP, the default
    # IETF VRRP that's actually OPNsense-incompatible) are SKIPPED —
    # OPNsense has no native HSRP/VRRP wire-protocol implementation
    # under <virtualip>, so emitting one would generate XML the
    # OPNsense GUI refuses to ingest.  The cross-vendor capability
    # matrix declares this as Lossy on /interfaces/interface/
    # vrrp-groups/group with a mode-restriction reason.
    _render_virtualip_block(intent, root)

    return _pretty_print(root)


def _render_virtualip_block(intent: CanonicalIntent, root: ET.Element) -> None:
    """Emit ``<virtualip>/<vip>`` children for CARP-mode VRRP groups.

    Walks every :class:`CanonicalInterface` in canonical order and
    flattens its CARP groups into a single ``<virtualip>`` envelope.
    Non-CARP groups are dropped silently (declared Lossy in the
    capability matrix).  No ``<virtualip>`` element is emitted at
    all when the intent has zero CARP groups — keeps the output
    minimal for the common "no HA" case.

    Interface back-pointer resolution:
        OPNsense's ``<interface>`` element names a LOGICAL zone
        ("lan", "opt1", "vlan10"), not the BSD device.  Render
        uses the iface's name verbatim — for canonical intents
        that round-trip from the same vendor this matches the
        zone tag because :func:`_zone_tag_for` lowercases / passes
        through known aliases; for foreign intents the operator
        will need to fix up the back-pointer in the GUI.  See
        docs/v0.2.0-planning/01-vrrp-canonical/02-per-vendor-grammar.md
        § 8 edge cases.

    advskew round-trip:
        Render inverts the parse-time mapping (``priority = 254 -
        advskew``) so ``advskew = 254 - priority``.  Clamped to
        the 0..254 CARP range.  See :func:`_parse_opnsense_vip`
        docstring for the inversion rationale.
    """
    # Collect CARP groups across all interfaces FIRST so we know
    # whether to emit the <virtualip> envelope at all.  Other modes
    # (vrrp / hsrp / future) get dropped here — Lossy declaration
    # in CapabilityMatrix surfaces the drop at validation time.
    pairs: list[tuple[Any, Any]] = []
    for iface in intent.interfaces:
        for group in iface.vrrp_groups:
            if group.mode != "carp":
                # HSRP / pure-VRRP / future modes do NOT round-trip
                # through OPNsense's <virtualip>.  Lossy declaration
                # in CapabilityMatrix surfaces the drop to the
                # operator at validation time.
                continue
            pairs.append((iface, group))
    if not pairs:
        return

    vip_root = ET.SubElement(root, "virtualip")
    for iface, group in pairs:
        vip_el = ET.SubElement(vip_root, "vip")
        ET.SubElement(vip_el, "mode").text = "carp"
        # <interface> is the LOGICAL alias.  Use _zone_tag_for to
        # match the same sanitisation the <interfaces> block applied
        # so the back-pointer resolves through the alias map on
        # re-parse.  For canonical names already shaped as zones
        # ("lan", "opt1", "wan", "vlan10") this is a no-op.
        ET.SubElement(vip_el, "interface").text = _zone_tag_for(iface.name)
        ET.SubElement(vip_el, "vhid").text = str(group.group_id)
        # advskew = 254 - priority (inverse of parse).  Clamp to
        # the CARP 0..254 range.
        advskew = 254 - group.priority
        if advskew < 0:
            advskew = 0
        elif advskew > 254:
            advskew = 254
        ET.SubElement(vip_el, "advskew").text = str(advskew)
        ET.SubElement(vip_el, "advbase").text = str(
            group.advertisement_interval
        )
        # CARP authentication — opaque carp-key.  Plain-mode (vrrp
        # under <virtualip>, rare) doesn't round-trip here because
        # we skipped it above.
        if group.authentication.startswith("carp-key:"):
            ET.SubElement(vip_el, "password").text = (
                group.authentication[len("carp-key:"):]
            )
        # Subnet + bits.  CARP records carry one IP per VHID; we
        # take the first virtual_ip (IPv4) preferentially.
        if group.virtual_ips:
            ET.SubElement(vip_el, "subnet").text = group.virtual_ips[0]
            # Prefix length: borrow from the parent iface's first
            # IPv4 address when present (the realistic case — CARP
            # VIPs live on the same subnet as the iface's real IP).
            # Fall back to /32 for foreign canonical intents that
            # didn't carry an address.
            if iface.ipv4_addresses:
                prefix = iface.ipv4_addresses[0].prefix_length
            else:
                prefix = 32
            ET.SubElement(vip_el, "subnet_bits").text = str(prefix)
        elif group.virtual_ipv6s:
            ET.SubElement(vip_el, "subnet").text = group.virtual_ipv6s[0]
            if iface.ipv6_addresses:
                prefix = iface.ipv6_addresses[0].prefix_length
            else:
                prefix = 128
            ET.SubElement(vip_el, "subnet_bits").text = str(prefix)
        # <type>single</type> is the canonical CARP form — one IP
        # per VHID.  <type>network</type> is the network-address
        # variant (Lossy across vendors); we don't reconstruct it
        # on render — operator will toggle in the GUI if needed.
        ET.SubElement(vip_el, "type").text = "single"
        if group.description:
            ET.SubElement(vip_el, "descr").text = group.description


def render_legacy(tree: dict[str, Any]) -> str:
    """Render from the old dict shape (back-compat for existing tests)."""
    root = ET.Element("opnsense")

    system = tree.get("system")
    if system is not None:
        sys_el = ET.SubElement(root, "system")
        if "hostname" in system:
            ET.SubElement(sys_el, "hostname").text = system["hostname"]
        if "domain" in system:
            ET.SubElement(sys_el, "domain").text = system["domain"]

    ifaces_wrapper = tree.get("interfaces")
    if ifaces_wrapper is not None:
        ifaces_el = ET.SubElement(root, "interfaces")
        for iface in ifaces_wrapper.get("interface", []):
            _render_interface_zone(iface, ifaces_el)

    return _pretty_print(root)


# ---------------------------------------------------------------------------
# Element-level render helpers
# ---------------------------------------------------------------------------


def _render_interface_zone(iface: dict[str, Any], parent: ET.Element) -> None:
    """Render a single interface dict back into its ``<zone>`` element."""
    zone = iface.get("zone")
    if not zone:
        raise RenderError(
            "opnsense: interface entry missing 'zone' key",
            yang_path="/interfaces/interface/zone",
        )
    zone_el = ET.SubElement(parent, zone)
    # Preserve OPNsense's canonical child order for textual-diff stability.
    for xml_tag, py_key, converter in (
        ("if",     "if",     str),
        ("descr",  "descr",  str),
        ("enable", "enable", _render_enable_flag),
        ("ipaddr", "ipaddr", str),
        ("subnet", "subnet", str),
    ):
        if py_key in iface:
            value = converter(iface[py_key])
            # enable -> empty element; others -> text child.
            if py_key == "enable":
                ET.SubElement(zone_el, xml_tag)
            else:
                ET.SubElement(zone_el, xml_tag).text = value


def _render_enable_flag(value: Any) -> str:
    """No-op converter for the ``enable`` flag — empty element, no text."""
    return ""


def _vlan_parent_default(intent: CanonicalIntent) -> str:
    """Pick a deterministic default parent interface for VLAN bindings.

    OPNsense VLANs without an obvious SVI / trunk anchor still need a
    parent ``<if>`` to be valid XML.  We walk the canonical tree in a
    fixed order and pick the first match:

    1. The first LAG (``intent.lags[0].name``) — multi-vendor hardware
       almost always trunks VLANs over a LAG to a downstream switch,
       so this is the right answer for the common case.
    2. The first physical-looking interface (i.e. not a Vlan SVI, not a
       Loopback, not the magic ``oobm`` zone).  Order is canonical
       insertion order — codecs preserve it.
    3. ``"lan"`` as a last-resort literal — mirrors OPNsense's default
       zone name when no hardware is declared.  Operators will need
       to rewire this manually but at least the XML is structurally
       valid.
    """
    if intent.lags:
        return intent.lags[0].name
    for iface in intent.interfaces:
        lname = iface.name.lower()
        if lname.startswith("vlan"):
            continue
        if lname.startswith("loopback") or lname.startswith("lo"):
            continue
        if iface.name == "oobm":
            continue
        return iface.name
    return "lan"


def _vlan_parent_for(
    vlan: Any,
    intent: CanonicalIntent,
    default: str,
) -> str:
    """Resolve the parent physical / lagg interface for a single VLAN.

    Lookup order:

    1. A LAG whose ``trunk_allowed_vlans`` (declared on its members or
       on the LAG-named interface) contains ``vlan.id`` — this is the
       most common cross-vendor binding when the source codec emits
       VLANs on a port-channel trunk.
    2. A physical / non-VLAN interface whose ``trunk_allowed_vlans``
       contains ``vlan.id``.
    3. The deterministic ``default`` (first lagg / first physical /
       ``"lan"``) returned by :func:`_vlan_parent_default`.

    The lookup intentionally does NOT consult the VLAN's own SVI L3
    binding — OPNsense's ``<if>`` is the L2 trunk parent, not the L3
    interface.  Codecs that emit a Vlan-named SVI ``CanonicalInterface``
    are signalling routing intent, not the trunk anchor.
    """
    # Pass 1 — a LAG whose interface row carries this VLAN on its
    # allowed-trunk list, or a LAG whose member is bound on it.
    for lag in intent.lags:
        # Match the LAG-named interface itself (some codecs put the
        # trunk list on the LAG).
        for iface in intent.interfaces:
            if iface.name != lag.name:
                continue
            if vlan.id in iface.trunk_allowed_vlans:
                return lag.name
        # Match any LAG member that carries this VLAN.
        for member in lag.members:
            for iface in intent.interfaces:
                if iface.name == member and vlan.id in iface.trunk_allowed_vlans:
                    return lag.name
    # Pass 2 — a non-LAG, non-VLAN interface carrying this VLAN.
    lag_member_set = {
        m for lag in intent.lags for m in lag.members
    }
    for iface in intent.interfaces:
        lname = iface.name.lower()
        if lname.startswith("vlan"):
            continue
        if iface.name in lag_member_set:
            continue
        if vlan.id in iface.trunk_allowed_vlans:
            return iface.name
    return default


def _zone_tag_for(name: str) -> str:
    """Derive a valid XML element tag from a vendor-native interface name.

    OPNsense's config.xml uses the interface zone ("wan", "lan",
    "opt1") as an element tag, which means the name must be a valid
    XML NCName (start with a letter or ``_``; no slashes, spaces, or
    leading digits).  Foreign interface names like ``GigabitEthernet0/0/0``,
    ``A1``, or plain numerics (``1``, ``25`` — legal on Aruba) violate
    this.  We lowercase, replace invalid characters with ``_``, and
    prepend ``if_`` when the first character would be a digit.
    """
    if name in ("wan", "lan") or name.startswith("opt"):
        return name
    sanitised = "".join(
        c.lower() if (c.isalnum() or c == "_") else "_"
        for c in name
    )
    if not sanitised:
        return "if_unnamed"
    if not (sanitised[0].isalpha() or sanitised[0] == "_"):
        sanitised = "if_" + sanitised
    return sanitised


def _pretty_print(root: ET.Element) -> str:
    """Pretty-print *root* in OPNsense's canonical style.

    Real OPNsense exports omit the ``<?xml ... ?>`` declaration and
    use two-space indentation with no blank lines between siblings.
    Both render paths share this finalisation so output stays
    indistinguishable.
    """
    raw_xml = ET.tostring(root, encoding="unicode")
    from xml.dom.minidom import parseString
    pretty = parseString(raw_xml).toprettyxml(indent="  ")
    lines = pretty.splitlines()
    if lines and lines[0].startswith("<?xml"):
        lines = lines[1:]
    return "\n".join(line for line in lines if line.strip()) + "\n"


# ---------------------------------------------------------------------------
# LAG proto map — render direction (inverse of parse).
# ---------------------------------------------------------------------------

_CANONICAL_MODE_TO_OPNSENSE_PROTO = {
    "active": "lacp",
    "passive": "lacp",   # OPNsense doesn't distinguish active/passive at this layer
    "static": "failover",
}

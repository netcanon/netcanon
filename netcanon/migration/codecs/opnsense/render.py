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

import re
from typing import Any
from xml.etree import ElementTree as ET

from ..._comments import comment_text
from ..._radius_secrets import (
    format_review_comment as format_radius_review_comment,
)
from ..._radius_secrets import (
    radius_secret_is_migratable,
    unwrap_native_secret,
)
from ..._user_secrets import (
    classify_hash,
    format_review_comment,
    is_migratable,
)
from ...canonical.intent import CanonicalIntent, CanonicalInterface
from ...canonical.transforms import is_every_vlan
from ..base import RenderError
from .port_names import classify_port_name

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


def render_canonical(intent: CanonicalIntent) -> str:  # noqa: C901
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
            # (#482) See netcanon/migration/_radius_secrets.py —
            # <radius_secret> is read as the literal shared secret, so a
            # blob encrypted under another device's key is refused.  XML
            # has no line-comment slot in this position, so the refusal
            # is recorded as a sibling element the operator can see in
            # the UI rather than a comment.
            if server.key:
                if radius_secret_is_migratable(
                    server.key, intent.source_vendor, "opnsense",
                ):
                    ET.SubElement(
                        auth_el, "radius_secret",
                    ).text = unwrap_native_secret(server.key)
                else:
                    # A sibling ELEMENT, not an ET.Comment: XML forbids
                    # ``--`` inside a comment and the shared review
                    # wording contains it, so a comment here produces a
                    # document that will not re-parse.  An element also
                    # survives the config round-trip and is visible in
                    # the UI, which a comment is not.
                    ET.SubElement(
                        auth_el, "radius_secret_review",
                    ).text = format_radius_review_comment(
                        server.host,
                        comment_syntax="plain",
                        target_label="OPNsense",
                        secret=server.key,
                    )
            ET.SubElement(auth_el, "radius_auth_port").text = (
                str(server.auth_port)
            )
            ET.SubElement(auth_el, "radius_acct_port").text = (
                str(server.acct_port)
            )

        # Local users (Tier 2).  Map canonical admin -> admins
        # group, anything else -> users.  OPNsense verifies the
        # ``<password>`` element with PHP's password_verify(), and the
        # forms its configs are observed to store are bcrypt
        # (``$2y$10$...``) and SHA-512 crypt (``$6$...``, real HA
        # configs).  Other hashes (Cisco type-5/8/9 wrappers, FortiGate
        # ENC, md5crypt) are not re-used; emitting
        # them as-is leaks the source hash literal as the password
        # element value (CRITICAL security bug — see
        # tests/fixtures/real/user_smoke_findings.md issue #1).
        #
        # Policy lives in :mod:`netcanon.migration._user_secrets`
        # (``_TARGET_ACCEPTS["opnsense"] = {bcrypt, sha512}``; PHP's
        # password_verify() also consumes a ``$6$`` crypt string).
        # When the hash is unmigratable, emit a comment-form review
        # line IN PLACE of the ``<user>`` element, naming the source
        # algorithm so the operator knows what to reset from: a
        # refused secret drops the whole account, never the password
        # alone (the element used to stay, with no ``<password>``).
        # A TYPED password is refused the same way: ``<password>`` is
        # what password_verify() checks a password against, and the
        # typed string written there opened nothing.
        for user in intent.local_users:
            if user.hashed_password and not is_migratable(
                user.hashed_password, "opnsense",
            ):
                # The shared helper natively produces an
                # XML-comment-safe body (single-dash separator for
                # ``comment_syntax="xml"``).
                algorithm, _payload = classify_hash(user.hashed_password)
                review = format_review_comment(
                    user.name, algorithm, comment_syntax="xml",
                    target_label="OPNsense",
                )
                body = review.removeprefix("<!-- ").removesuffix(" -->")
                sys_el.append(ET.Comment(body))
                continue
            user_el = ET.SubElement(sys_el, "user")
            ET.SubElement(user_el, "name").text = user.name
            if user.hashed_password:
                # Strip the ``alg:`` tag so OPNsense's <password>
                # element carries the raw hash (e.g. ``$2y$10$...``).
                _algorithm, payload = classify_hash(user.hashed_password)
                ET.SubElement(user_el, "password").text = payload
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
    #
    # A member of a LAG is not assigned: OPNsense adds only an
    # unassigned interface to a LAGG ("Only unassigned interfaces can
    # be added to LAGG", docs.opnsense.org, Other Types).  It is
    # written in its ``<lagg>``'s ``<members>`` alone, and what it held
    # that a zone would have carried is said there (``_members_of``,
    # ``_held_by``).  A member is a RECORD, not a name: another record
    # under the member's name keeps its zone.
    lagg_members = _members_of(intent)
    member_records = {
        id(record) for _, record in lagg_members.values() if record is not None
    }
    # A VLAN device that holds nothing a zone holds is written in
    # <vlans> alone (see _unassigned_vlan_devices).
    unassigned = _unassigned_vlan_devices(intent)
    zones = [
        i for i in intent.interfaces
        if id(i) not in member_records and id(i) not in unassigned
    ]
    if zones:
        ifaces_el = ET.SubElement(root, "interfaces")
        used_tags: dict[str, int] = {}
        for iface in zones:
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
            _zone_body(zone_el, iface)

    # VLANs.  A <vlan> is a VLAN device (core ``Vlan.xml``): <if> the
    # device it rides on, <tag>, <pcp>, <proto>, <descr>, and <vlanif>
    # the device's name, which a zone's <if> assigns.  OPNsense's
    # model requires <if>, <tag> and <vlanif>
    # (https://docs.opnsense.org/manual/other-interfaces.html).
    #
    # A VLAN interface of the tree is written as the device of that
    # name, so that the zone written for it above names a device this
    # output defines, on the parent the config states.  Before, every
    # VLAN was written as ``<parent>_vlan<tag>`` on a parent chosen
    # here: each zone on a VLAN named a device the output did not
    # have, and the committed capture's five VLANs came out on its
    # WAN port.  A VLAN no interface is for is still written on a
    # parent chosen from what carries it (_vlan_parent_for).
    devices = _vlan_devices(intent)
    if intent.vlans or devices:
        vlans_el = ET.SubElement(root, "vlans")
        parent_default = _vlan_parent_default(intent)
        carriers = _vlan_carriers(intent)
        written: set[tuple[str, int]] = set()
        # Each device's parent, to know which carry another VLAN
        # (whose <proto> must then say 802.1q: blank, OPNsense sends
        # such a device as 802.1ad).
        parents = {
            device.record.vlan_parent for device in devices
            if device.record.vlan_parent
        }

        def write_device(device: _VlanDevice) -> None:
            record = device.record
            if device.tag is None:
                vlans_el.append(ET.Comment(_comment_text(
                    f"review: {record.name} is a VLAN interface whose "
                    f"tag the tree does not state, so no <vlan> defines it"
                )))
                return
            parent = record.vlan_parent or carriers.get(
                device.tag, parent_default,
            )
            vlan_el = ET.SubElement(vlans_el, "vlan")
            ET.SubElement(vlan_el, "if").text = parent
            ET.SubElement(vlan_el, "tag").text = str(device.tag)
            ET.SubElement(vlan_el, "pcp").text = "0"
            proto_el = ET.SubElement(vlan_el, "proto")
            if record.name in parents:
                proto_el.text = "802.1q"
            descr = _vlan_descr(device.vlan, record.name)
            if descr:
                ET.SubElement(vlan_el, "descr").text = descr
            ET.SubElement(vlan_el, "vlanif").text = record.name
            if not _opnsense_takes_device_name(record.name, parent, device.tag):
                vlan_el.append(ET.Comment(_comment_text(
                    f"review: OPNsense's VLAN form refuses the device "
                    f"name {record.name} when this VLAN is saved; it takes "
                    f"{_device_prefix(parent)}0 followed by digits and dots, "
                    f"or {parent}_vlan{device.tag}"
                )))
            written.add((parent, device.tag))

        by_vlan = {id(device.vlan): device for device in devices if device.vlan}
        for vlan in intent.vlans:
            device = by_vlan.get(id(vlan))
            if device is not None:
                write_device(device)
                continue
            parent_if = _vlan_parent_for(vlan, carriers, parent_default)
            if (parent_if, vlan.id) in written:
                # OPNsense keeps one device for a tag on a parent
                # (``Vlan.xml``: the tag is unique with <if>).
                continue
            vlan_el = ET.SubElement(vlans_el, "vlan")
            ET.SubElement(vlan_el, "if").text = parent_if
            ET.SubElement(vlan_el, "tag").text = str(vlan.id)
            ET.SubElement(vlan_el, "pcp").text = "0"
            ET.SubElement(vlan_el, "proto")
            descr = _vlan_descr(vlan, "")
            if descr:
                ET.SubElement(vlan_el, "descr").text = descr
            # The legacy device name, which OPNsense's form takes for
            # any parent and tag (``Vlan.php``) and which no other
            # parent's VLAN can have.
            ET.SubElement(vlan_el, "vlanif").text = (
                f"{parent_if}_vlan{vlan.id}"
            )
            written.add((parent_if, vlan.id))
        for device in devices:
            if device.vlan is None:
                write_device(device)

    # DHCP pools (Tier 2).  OPNsense keys DHCP config by interface
    # zone.  A pool's ``interface`` holds a port name -- this
    # codec's own parser puts the device of the pool's zone there,
    # not the zone -- so the tag is made of it by the same
    # _zone_tag_for helper that makes an interface's, and the pool
    # is under its interface's zone.  A pool that names no
    # interface is written under ``lan``.
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
            members = [m for m, of in lagg_members.items() if of[0] == lag.name]
            if members:
                ET.SubElement(lagg_el, "members").text = ",".join(members)
            ET.SubElement(lagg_el, "proto").text = (
                _CANONICAL_MODE_TO_OPNSENSE_PROTO.get(lag.mode, "lacp")
            )
            for member in members:
                record = lagg_members[member][1]
                held = _held_by(record) if record is not None else []
                if held:
                    lagg_el.append(ET.Comment(
                        f" review: {_dashes_apart(member)} is a member of this"
                        " LAGG, and OPNsense assigns no member of a LAGG:"
                        f" not written: {', '.join(held)} "
                    ))

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


def _members_of(
    intent: CanonicalIntent,
) -> dict[str, tuple[str, CanonicalInterface | None]]:
    """Every member of a LAG the output writes, with its LAG and its
    interface record (``None`` where it has none).

    A member is one the LAG lists or one whose record names the LAG
    (the tree states it twice); the first LAG that claims a port has
    it.  Members of a LAG are in ``<members>``, never in
    ``<interfaces>``.

    A member's record is the one that names a LAG, and only where no
    record of the name does, the first of the name.  Two source ports
    a port map put on one name are two records: the one that is no
    member keeps its zone and what it holds (the job says the names
    are fused), and nothing it holds is said of the member.
    """
    lag_names = {lag.name for lag in intent.lags}
    first: dict[str, CanonicalInterface] = {}
    in_a_lag: dict[str, CanonicalInterface] = {}
    for iface in intent.interfaces:
        first.setdefault(iface.name, iface)
        if iface.lag_member_of in lag_names:
            in_a_lag.setdefault(iface.name, iface)
    members: dict[str, tuple[str, CanonicalInterface | None]] = {}
    for lag in intent.lags:
        for name in lag.members:
            members.setdefault(
                name, (lag.name, in_a_lag.get(name) or first.get(name)),
            )
    for iface in intent.interfaces:
        if iface.lag_member_of in lag_names:
            members.setdefault(iface.name, (iface.lag_member_of, iface))
    return members


def _zone_body(zone_el: ET.Element, iface) -> None:
    """Write one interface's children into its zone element."""
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


def _held_by(iface: CanonicalInterface) -> list[str]:
    """The zone elements *iface* would have been written with, beyond
    its name and its ``<enable>`` -- what a member of a LAGG, which
    OPNsense does not assign, cannot carry -- and ``disabled`` for a
    member that is down.  Element names only: no value of the config
    goes into the comment that says them."""
    scratch = ET.Element("zone")
    _zone_body(scratch, iface)
    held = [child.tag for child in scratch if child.tag not in ("if", "enable")]
    if not iface.enabled:
        held.append("disabled")
    return held


def _dashes_apart(name: str) -> str:
    """*name* with no two dashes together, which an XML comment may not
    hold."""
    return re.sub(r"-(?=-)", "- ", name)


class _VlanDevice:
    """A VLAN interface of the tree, its tag and the VLAN it is for."""

    __slots__ = ("record", "tag", "vlan")

    def __init__(self, record: Any, tag: int | None, vlan: Any) -> None:
        self.record = record
        self.tag = tag
        self.vlan = vlan


#: A name that is the SVI of the VLAN its digits say on the switch
#: platforms (IOS-XE, NX-OS and EOS ``Vlan10``, OS10 ``vlan10``,
#: AOS-CX ``vlan 10`` -- with the space, as every AOS-CX capture
#: writes it).  Read only for an interface the tree links to no VLAN.
_VLAN_N = re.compile(r"vlan ?(\d{1,4})", re.IGNORECASE)


def _tag_in_name(name: str) -> int | None:
    """The VLAN *name* is the interface of, read from the name: this
    codec's own reading of it (``vlan0.10``), or ``vlan<N>``."""
    ident = classify_port_name(name)
    if ident.kind == "svi" and ident.index is not None:
        return ident.index
    m = _VLAN_N.fullmatch(name)
    return int(m.group(1)) if m else None


def _vlan_devices(intent: CanonicalIntent) -> list[_VlanDevice]:
    """Every VLAN interface of *intent*, with its tag and its VLAN.

    A VLAN interface (``ianaift:l3ipvlan``) is linked to the VLAN
    NAMED after it -- how this codec's parser, and the RouterOS and
    FortiOS parsers, say which tag a VLAN interface has -- and
    otherwise to the first VLAN whose id its name says
    (:func:`_tag_in_name`; an SVI from a switch).  Each VLAN is
    linked to one interface at most.

    Returns:
        The VLAN interfaces in the order of ``intent.interfaces``.
        ``tag`` is ``None`` where neither says one.
    """
    by_name: dict[str, list[Any]] = {}
    by_id: dict[int, list[Any]] = {}
    for vlan in intent.vlans:
        by_name.setdefault(vlan.name, []).append(vlan)
        by_id.setdefault(vlan.id, []).append(vlan)
    taken: set[int] = set()

    def first_free(found: list[Any]) -> Any:
        # A list for one name or id is a handful long; each VLAN in
        # it is taken once.
        while found and id(found[0]) in taken:
            found.pop(0)
        return found[0] if found else None

    records = [
        iface for iface in intent.interfaces
        if iface.interface_type == "ianaift:l3ipvlan"
    ]
    devices: list[_VlanDevice] = []
    unnamed: list[_VlanDevice] = []
    for record in records:
        vlan = first_free(by_name.get(record.name, []))
        if vlan is not None:
            taken.add(id(vlan))
            devices.append(_VlanDevice(record, vlan.id, vlan))
        else:
            device = _VlanDevice(record, _tag_in_name(record.name), None)
            devices.append(device)
            unnamed.append(device)
    for device in unnamed:
        if device.tag is None:
            continue
        vlan = first_free(by_id.get(device.tag, []))
        if vlan is not None:
            taken.add(id(vlan))
            device.vlan = vlan
    return devices


def _unassigned_vlan_devices(intent: CanonicalIntent) -> set[int]:
    """The VLAN interfaces of *intent* that are written with no zone.

    OPNsense makes a VLAN device from its <vlan> alone; a zone
    assigns it only to give it something -- an address, a
    description, an MTU, a state.  A VLAN interface that holds none
    of what a zone of this output holds, and that no DHCP pool is on,
    is written in <vlans> alone: the parser makes such a record for a
    device no zone assigns, and written as a zone it would be
    assigned, and enabled, on the target.  A zone that assigned it
    with nothing in it is not written either; nothing else in this
    output names a zone by its tag.

    Returns:
        The ``id()`` of each such record.
    """
    pooled = {pool.interface for pool in intent.dhcp_servers}
    return {
        id(iface) for iface in intent.interfaces
        if iface.interface_type == "ianaift:l3ipvlan"
        and iface.name not in pooled
        and iface.enabled
        and not (
            iface.description or iface.kind or iface.mtu is not None
            or iface.ipv4_addresses or iface.ipv6_addresses
            or iface.dhcp_client or iface.dhcp_client_v6
            or iface.vrrp_groups
        )
    }


def _vlan_descr(vlan: Any, device_name: str) -> str:
    """The <descr> of *vlan*'s device: its description, else its name
    where that is not the device's own (a switch VLAN's ``name``)."""
    if vlan is None:
        return ""
    if vlan.description:
        return vlan.description
    return vlan.name if vlan.name != device_name else ""


#: The device names OPNsense's VLAN form takes besides the legacy
#: ``<parent>_vlan<tag>`` (``Vlan.php``): the prefix, a ``0`` and one to
#: ten digits and dots.
_DEVICE_NAME = {
    "vlan": re.compile(r"vlan0[0-9.]{1,10}"),
    "qinq": re.compile(r"qinq0[0-9.]{1,10}"),
}


def _device_prefix(parent: str) -> str:
    """The prefix OPNsense's form requires of a device on *parent*:
    ``qinq`` on a parent whose name holds ``vlan``, else ``vlan``
    (``Vlan.php``)."""
    return "qinq" if "vlan" in parent else "vlan"


def _opnsense_takes_device_name(name: str, parent: str, tag: int) -> bool:
    """Does OPNsense's VLAN form take *name* for a device on *parent*
    with *tag*?  ``Vlan.php`` takes ``<parent>_vlan<tag>``, and
    otherwise the prefix of :func:`_device_prefix`, a ``0`` and one
    to ten digits and dots."""
    if name == f"{parent}_vlan{tag}":
        return True
    return _DEVICE_NAME[_device_prefix(parent)].fullmatch(name) is not None


def _comment_text(text: str) -> str:
    """*text* as the body of an XML comment, a space either side: XML
    forbids ``--`` in a comment and a ``-`` at its end, and a name from
    a config can hold either (``_comments.comment_text``)."""
    return f" {comment_text(text, 'xml')} "


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
        if lname.startswith(("loopback", "lo")):
            continue
        if iface.name == "oobm":
            continue
        return iface.name
    return "lan"


def _vlan_carriers(intent: CanonicalIntent) -> dict[int, str]:
    """For every VLAN something carries, the LAG or the plain
    interface that is its parent.

    What :func:`_vlan_parent_for` looked for by walking every interface
    for every LAG, and again for every member of it, for every VLAN:
    three kinds that grow together, and 400 VLANs, port-channels and
    member ports took twelve seconds to render.  Read once here
    instead, in the same order, so that the first LAG or interface
    that carries a VLAN is still the one found.

    A trunk that NAMES the VLAN is looked for before a trunk of EVERY
    VLAN (:func:`...canonical.transforms.is_every_vlan`).  A trunk
    that states no allowed list is a trunk of every VLAN on four
    platforms, and such a trunk is in the list of every VLAN there
    is: found first, a vPC peer link is the parent of each VLAN its
    switch has, ahead of the port-channel that lists them.

    Returns:
        For the id of a VLAN of the tree, the name of the first of
        these that there is:

        1. the first LAG, in the order of ``intent.lags``, whose own
           interface or one of whose members names it on its trunk;
        2. the first interface, in the order of ``intent.interfaces``,
           that names it and is neither VLAN-named nor a member of a
           LAG;
        3. the first LAG a trunk of every VLAN belongs to;
        4. the first such interface that is a trunk of every VLAN.

        A VLAN nothing carries is not in it.
    """
    # Only the ids that will be asked about: a trunk that allows every
    # VLAN lists 4,094, and the tree declares a handful.
    wanted = {vlan.id for vlan in intent.vlans}
    named: dict[str, list[Any]] = {}
    for iface in intent.interfaces:
        named.setdefault(iface.name, []).append(iface)
    lag_members: set[str] = set()
    for lag in intent.lags:
        lag_members.update(lag.members)
    # Each interface that allows something, once, with what it is the
    # parent as (a LAG for the LAG's own interface and its members) and
    # whether its list is every VLAN: LAGs first, in their order, then
    # the plain interfaces in theirs.
    carriers: list[tuple[str, Any, bool]] = []
    for lag in intent.lags:
        for name in (lag.name, *lag.members):
            for iface in named.get(name, ()):
                if iface.trunk_allowed_vlans:
                    carriers.append(
                        (lag.name, iface, is_every_vlan(iface.trunk_allowed_vlans))
                    )
    for iface in intent.interfaces:
        if iface.name.lower().startswith("vlan") or iface.name in lag_members:
            continue
        if iface.trunk_allowed_vlans:
            carriers.append(
                (iface.name, iface, is_every_vlan(iface.trunk_allowed_vlans))
            )
    parent: dict[int, str] = {}
    # Two rounds over that one order: the trunks that name their
    # VLANs, then the trunks of every VLAN.  Within a round a LAG is
    # still found before a plain interface.
    for every in (False, True):
        for name, iface, is_every in carriers:
            if is_every is not every:
                continue
            for vid in wanted.intersection(iface.trunk_allowed_vlans):
                parent.setdefault(vid, name)
    return parent


def _vlan_parent_for(
    vlan: Any,
    carriers: dict[int, str],
    default: str,
) -> str:
    """Resolve the parent physical / lagg interface for a single VLAN.

    Lookup order:

    1. A LAG whose ``trunk_allowed_vlans`` (declared on its members or
       on the LAG-named interface) names ``vlan.id`` — this is the
       most common cross-vendor binding when the source codec emits
       VLANs on a port-channel trunk.
    2. A physical / non-VLAN interface whose ``trunk_allowed_vlans``
       names ``vlan.id``.
    3. A LAG, then a physical / non-VLAN interface, whose trunk is a
       trunk of every VLAN.  It carries this one too, and is a better
       parent than a port chosen without looking.
    4. The deterministic ``default`` (first lagg / first physical /
       ``"lan"``) returned by :func:`_vlan_parent_default`.

    The lookup intentionally does NOT consult the VLAN's own SVI L3
    binding — OPNsense's ``<if>`` is the L2 trunk parent, not the L3
    interface.  Codecs that emit a Vlan-named SVI ``CanonicalInterface``
    are signalling routing intent, not the trunk anchor.

    Args:
        vlan: The VLAN.
        carriers: What :func:`_vlan_carriers` read from the tree the
            VLAN is in.
        default: The parent when nothing carries the VLAN.

    Returns:
        The name of the parent interface.
    """
    return carriers.get(vlan.id, default)


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

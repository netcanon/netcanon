"""
``OPNsenseCodec`` — second real adapter.

Tree shape
----------
Nested dict mirroring the OPNsense ``config.xml`` structure, with a
small amount of normalisation::

    {
        "system": {
            "hostname": "fw01",
            "domain": "example.com",
        },
        "interfaces": {
            "interface": [
                {
                    "zone": "wan",
                    "if": "em0",
                    "descr": "Upstream ISP",
                    "enable": True,
                    "ipaddr": "198.51.100.2",
                    "subnet": 30,
                },
                …
            ]
        },
    }

OPNsense's native XML puts interfaces under names like ``<wan>`` and
``<lan>`` rather than using a list idiom — we flip that into a list
of ``{"zone": "wan", …}`` dicts at parse time so the tree walker can
emit schema-style xpaths (no list keys) that match the capability
matrix.  The render step reverses the transformation.

Round-trip invariant: ``parse(render(tree)) == tree``.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar, Iterable
from xml.etree import ElementTree as ET

from ....models.migration import (
    CapabilityMatrix,
    DeviceClass,
    LossyPath,
    UnsupportedPath,
)
from ...canonical.intent import (
    CanonicalDHCPPool,
    CanonicalIPv4Address,
    CanonicalIntent,
    CanonicalInterface,
    CanonicalLAG,
    CanonicalLocalUser,
    CanonicalRADIUSServer,
    CanonicalSNMP,
    CanonicalVlan,
)
from ..base import CodecBase, ParseError, RenderError
from ..registry import register
from . import port_names as _port_names


@register
class OPNsenseCodec(CodecBase):
    """Adapter for OPNsense ``config.xml`` (25.x).

    Declares ``device_classes=[firewall, router]`` — OPNsense's primary
    role is firewalling but it's also a competent L3 router (even
    without FRR installed).
    """

    name: ClassVar[str] = "opnsense"
    version_hint: ClassVar[str | None] = "25.x"
    input_format: ClassVar[str] = "xml-opnsense"
    direction: ClassVar[str] = "bidirectional"
    certainty: ClassVar[str] = "certified"
    canonical_model: ClassVar[str] = "openconfig-lite"
    description: ClassVar[str] = (
        "Paste the contents of an OPNsense config.xml "
        "(root element <opnsense>)."
    )
    sample_input: ClassVar[str] = (
        '<?xml version="1.0"?>\n'
        '<opnsense>\n'
        '  <system>\n'
        '    <hostname>fw01</hostname>\n'
        '    <domain>example.com</domain>\n'
        '  </system>\n'
        '  <interfaces>\n'
        '    <wan>\n'
        '      <if>em0</if>\n'
        '      <descr>Upstream</descr>\n'
        '      <enable/>\n'
        '      <ipaddr>198.51.100.2</ipaddr>\n'
        '      <subnet>30</subnet>\n'
        '    </wan>\n'
        '  </interfaces>\n'
        '</opnsense>\n'
    )
    output_extension: ClassVar[str] = "xml"

    # unsupported_rename_categories is intentionally empty — OPNsense's
    # parse() + render() both round-trip CanonicalLocalUser via
    # ``<system><user>`` blocks (see the ``for user_el in
    # sys_el.findall("user")`` loop in parse() and the matching
    # render() emit path below).  Coverage locked in by
    # ``tests/unit/migration/test_local_users_wire_through.py``
    # (TestOPNsenseLocalUsersParseRender).  A prior pre-Option-A
    # declaration had this list as ``{"local_users"}`` under the
    # incorrect assumption that OPNsense's user handling was
    # Tier-3-only — cleared as part of Option A.

    _CAPS: ClassVar[CapabilityMatrix] = CapabilityMatrix(
        adapter="opnsense",
        vendor_id="opnsense",
        version_range="24.x+",
        device_classes=[DeviceClass.firewall, DeviceClass.router],
        supported=[
            "/system/hostname",
            "/system/domain",
            "/system/dns-server",
            "/system/ntp-server",
            "/interfaces/interface/name",
            "/interfaces/interface/config/description",
            "/interfaces/interface/config/enabled",
            "/interfaces/interface/ipv4/address/ip",
            "/interfaces/interface/ipv4/address/prefix-length",
            "/vlans/vlan/id",
            "/vlans/vlan/name",
            # Tier 2 — SNMP (OPNsense snmpd plugin)
            "/snmp/community",
            "/snmp/location",
            "/snmp/contact",
            "/snmp/trap-host",
            # Tier 2 — local users (OPNsense <system><user> blocks).
            # Parse maps <groupname="admins"> → privilege 15; render
            # emits name / password / scope / groupname.  Hashes are
            # passed through verbatim under a ``bcrypt:`` tag so
            # target renderers can route appropriately.
            "/aaa/authentication/users/user/config/username",
            "/aaa/authentication/users/user/config/password",
            "/aaa/authentication/users/user/config/role",
        ],
        lossy=[
            LossyPath(
                path="/interfaces/interface/config/description",
                reason=(
                    "OPNsense imposes no length limit on description text; "
                    "other vendors (Cisco 240 chars, Juniper 900) may "
                    "truncate on render."
                ),
                severity="warn",
            ),
        ],
        unsupported=[
            UnsupportedPath(
                path="/filter/rule",
                reason=(
                    "Firewall rules require the netconfig-ext YANG module "
                    "(Phase 2) — OpenConfig has no firewall model."
                ),
            ),
            UnsupportedPath(
                path="/nat/outbound",
                reason=(
                    "NAT table translation needs netconfig-ext + careful "
                    "semantic mapping to target stateful engines."
                ),
            ),
        ],
    )

    @property
    def capabilities(self) -> CapabilityMatrix:
        return self._CAPS

    # -----------------------------------------------------------------
    # Parse
    # -----------------------------------------------------------------

    def parse(self, raw: str) -> CanonicalIntent:
        """Parse an OPNsense ``config.xml`` document into a
        :class:`CanonicalIntent`.

        Raises:
            ParseError: On malformed XML or missing ``<opnsense>`` root.
        """
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            raise ParseError(
                f"opnsense: malformed XML: {exc}",
                snippet=raw[:120],
            ) from exc

        if root.tag != "opnsense":
            raise ParseError(
                "opnsense: expected <opnsense> root element, "
                f"got <{root.tag}>",
                snippet=raw[:120],
            )

        intent = CanonicalIntent(
            source_vendor="opnsense",
            source_format="xml-opnsense",
        )

        # ----- <system> block -----
        sys_el = root.find("system")
        if sys_el is not None:
            hn = sys_el.find("hostname")
            if hn is not None and hn.text:
                intent.hostname = hn.text.strip()
            dm = sys_el.find("domain")
            if dm is not None and dm.text:
                intent.domain = dm.text.strip()
            # Local users — <system>/<user> entries.  OPNsense stores
            # users at the same level as <hostname>, each with name,
            # descr, password (bcrypt $2y$), uid, and an optional
            # groupname.  Group "admins" (and descendants) = admin
            # privilege; anything else defaults to operator.
            # RADIUS servers live under <system>/<authserver> with
            # <type>radius</type>.  Other <authserver> types (ldap,
            # local) are ignored here.
            for auth_el in sys_el.findall("authserver"):
                type_el = auth_el.find("type")
                if type_el is None or (type_el.text or "").strip().lower() != "radius":
                    continue
                host_el = auth_el.find("host")
                if host_el is None or not (host_el.text or "").strip():
                    continue
                secret_el = auth_el.find("radius_secret")
                ap_el = auth_el.find("radius_auth_port")
                acctp_el = auth_el.find("radius_acct_port")
                auth_port = 1812
                acct_port = 1813
                if ap_el is not None and ap_el.text:
                    try:
                        auth_port = int(ap_el.text.strip())
                    except ValueError:
                        pass
                if acctp_el is not None and acctp_el.text:
                    try:
                        acct_port = int(acctp_el.text.strip())
                    except ValueError:
                        pass
                intent.radius_servers.append(CanonicalRADIUSServer(
                    host=host_el.text.strip(),
                    key=(secret_el.text or "").strip() if secret_el is not None else "",
                    auth_port=auth_port,
                    acct_port=acct_port,
                ))
            for user_el in sys_el.findall("user"):
                name_el = user_el.find("name")
                if name_el is None or not (name_el.text or "").strip():
                    continue
                name = name_el.text.strip()
                password_el = user_el.find("password")
                password = (
                    password_el.text.strip()
                    if password_el is not None and password_el.text
                    else ""
                )
                groupname_el = user_el.find("groupname")
                groupname = (
                    groupname_el.text.strip().lower()
                    if groupname_el is not None and groupname_el.text
                    else ""
                )
                scope_el = user_el.find("scope")
                scope = (
                    scope_el.text.strip().lower()
                    if scope_el is not None and scope_el.text
                    else ""
                )
                # Admin privilege is determined by group membership,
                # NOT by <scope>.  In OPNsense, <scope> distinguishes
                # system-managed accounts from network/LDAP accounts;
                # both system and user-scope accounts can be admins
                # (via groupname="admins") or regular users.
                is_admin = groupname == "admins"
                _ = scope  # reserved for future use; shape validated
                intent.local_users.append(CanonicalLocalUser(
                    name=name,
                    privilege_level=15 if is_admin else 1,
                    # Tag as bcrypt so target renderers can route.
                    hashed_password=(
                        f"bcrypt:{password}" if password else ""
                    ),
                    role="admin" if is_admin else "user",
                ))

        # ----- <interfaces> block — flatten into list -----
        iface_parent = root.find("interfaces")
        if iface_parent is not None:
            for zone_el in iface_parent:
                iface = _parse_interface_zone_canonical(zone_el)
                if iface is not None:
                    intent.interfaces.append(iface)

        # ----- <vlans> block -----
        vlans_el = root.find("vlans")
        if vlans_el is not None:
            for vlan_el in vlans_el.findall("vlan"):
                tag_el = vlan_el.find("tag")
                if tag_el is not None and tag_el.text:
                    vid = int(tag_el.text.strip())
                    descr_el = vlan_el.find("descr")
                    intent.vlans.append(CanonicalVlan(
                        id=vid,
                        name=(descr_el.text or "").strip() if descr_el is not None else "",
                    ))

        # ----- <dhcpd> block (Tier 2 DHCP) -----
        dhcpd_el = root.find("dhcpd")
        if dhcpd_el is not None:
            for zone_el in dhcpd_el:
                pool = _parse_opnsense_dhcp_zone(zone_el)
                if pool is not None:
                    intent.dhcp_servers.append(pool)

        # ----- <laggs> block (Tier 2 LAGs) -----
        laggs_el = root.find("laggs")
        if laggs_el is not None:
            for lagg_el in laggs_el.findall("lagg"):
                laggif_el = lagg_el.find("laggif")
                if laggif_el is None or not (laggif_el.text or "").strip():
                    continue  # no name = useless record
                name = laggif_el.text.strip()
                members_el = lagg_el.find("members")
                members: list[str] = []
                if members_el is not None and members_el.text:
                    members = [
                        m.strip() for m in members_el.text.split(",") if m.strip()
                    ]
                proto_el = lagg_el.find("proto")
                proto = (proto_el.text.strip().lower()
                         if proto_el is not None and proto_el.text else "lacp")
                mode = _OPNSENSE_PROTO_TO_CANONICAL.get(proto, "active")
                intent.lags.append(CanonicalLAG(
                    name=name, members=members, mode=mode,
                ))
                # Reverse-link members to this LAG.
                for m in members:
                    for iface in intent.interfaces:
                        if iface.name == m and iface.lag_member_of is None:
                            iface.lag_member_of = name

        # ----- <snmpd> block (Tier 2) -----
        snmpd_el = root.find("snmpd")
        if snmpd_el is not None:
            snmp = CanonicalSNMP()
            ro_el = snmpd_el.find("rocommunity")
            if ro_el is not None and ro_el.text:
                snmp.community = ro_el.text.strip()
            loc_el = snmpd_el.find("syslocation")
            if loc_el is not None and loc_el.text:
                snmp.location = loc_el.text.strip()
            contact_el = snmpd_el.find("syscontact")
            if contact_el is not None and contact_el.text:
                snmp.contact = contact_el.text.strip()
            for host_el in snmpd_el.findall("traphost"):
                if host_el.text and host_el.text.strip():
                    snmp.trap_hosts.append(host_el.text.strip())
            if (snmp.community or snmp.location or snmp.contact
                    or snmp.trap_hosts):
                intent.snmp = snmp

        return intent

    # -----------------------------------------------------------------
    # Render
    # -----------------------------------------------------------------

    def render(self, tree: Any) -> str:
        """Render a :class:`CanonicalIntent` to OPNsense config.xml."""
        # Accept both CanonicalIntent and legacy dict for back-compat.
        if isinstance(tree, CanonicalIntent):
            return self._render_canonical(tree)
        if isinstance(tree, dict):
            return self._render_legacy(tree)
        raise RenderError("opnsense: tree must be a CanonicalIntent or dict", yang_path="/")

    def _render_canonical(self, intent: CanonicalIntent) -> str:
        """Render from the canonical intent shape."""
        root = ET.Element("opnsense")

        # System — attach hostname/domain/users under a single <system>
        # element so real OPNsense tooling (and our own re-parse) sees
        # a single canonical block.
        has_system_content = (
            intent.hostname or intent.domain or intent.local_users
            or intent.radius_servers
        )
        if has_system_content:
            sys_el = ET.SubElement(root, "system")
            if intent.hostname:
                ET.SubElement(sys_el, "hostname").text = intent.hostname
            if intent.domain:
                ET.SubElement(sys_el, "domain").text = intent.domain
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
            # group, anything else -> users.  Strip the "bcrypt:" tag
            # from the hash (OPNsense's <password> field carries the
            # raw $2y$... value).  Foreign hashes are emitted verbatim
            # — OPNsense will reject non-bcrypt at auth time but our
            # canonical carries them faithfully.
            for user in intent.local_users:
                user_el = ET.SubElement(sys_el, "user")
                ET.SubElement(user_el, "name").text = user.name
                if user.hashed_password:
                    _alg, _, raw_hash = user.hashed_password.partition(":")
                    # If no "alg:" prefix, use the whole thing verbatim.
                    hash_out = raw_hash if raw_hash else user.hashed_password
                    ET.SubElement(user_el, "password").text = hash_out
                ET.SubElement(user_el, "scope").text = "system"
                ET.SubElement(user_el, "groupname").text = (
                    "admins" if user.privilege_level == 15 else "users"
                )

        # Interfaces — render as zone-keyed elements.
        # For canonical intents from OTHER vendors we need to assign zone
        # names.  Use the interface name as the zone if it looks like an
        # OPNsense zone (wan/lan/optN), otherwise sanitise the name into
        # a valid XML tag (must start with a letter; no slashes/spaces).
        if intent.interfaces:
            ifaces_el = ET.SubElement(root, "interfaces")
            for iface in intent.interfaces:
                zone_name = _zone_tag_for(iface.name)
                zone_el = ET.SubElement(ifaces_el, zone_name)
                if iface.description:
                    ET.SubElement(zone_el, "descr").text = iface.description
                if iface.enabled:
                    ET.SubElement(zone_el, "enable")
                if iface.mtu is not None:
                    ET.SubElement(zone_el, "mtu").text = str(iface.mtu)
                if iface.ipv4_addresses:
                    ET.SubElement(zone_el, "ipaddr").text = iface.ipv4_addresses[0].ip
                    ET.SubElement(zone_el, "subnet").text = str(iface.ipv4_addresses[0].prefix_length)

        # VLANs — emit <vlans><vlan> per CanonicalVlan.  We mirror the
        # minimal shape the parser reads back: <tag> (required) + <descr>
        # (for the human-readable name).  Real OPNsense <vlan> elements
        # carry additional metadata (uuid, if, pcp, vlanif) but those
        # aren't in the canonical — OPNsense happily re-ingests XML
        # without them.  Round-trip stability only needs parser/render
        # symmetry on the fields we canonicalise.
        if intent.vlans:
            vlans_el = ET.SubElement(root, "vlans")
            for vlan in intent.vlans:
                vlan_el = ET.SubElement(vlans_el, "vlan")
                ET.SubElement(vlan_el, "tag").text = str(vlan.id)
                if vlan.name:
                    ET.SubElement(vlan_el, "descr").text = vlan.name

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

        raw_xml = ET.tostring(root, encoding="unicode")
        from xml.dom.minidom import parseString
        pretty = parseString(raw_xml).toprettyxml(indent="  ")
        lines = pretty.splitlines()
        if lines and lines[0].startswith("<?xml"):
            lines = lines[1:]
        return "\n".join(line for line in lines if line.strip()) + "\n"

    def _render_legacy(self, tree: dict[str, Any]) -> str:
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

        # Match the real OPNsense output format: no XML declaration, just
        # the top-level element.  Consumers that need one can prepend it.
        raw_xml = ET.tostring(root, encoding="unicode")
        from xml.dom.minidom import parseString
        pretty = parseString(raw_xml).toprettyxml(indent="  ")
        lines = pretty.splitlines()
        if lines and lines[0].startswith("<?xml"):
            lines = lines[1:]
        return "\n".join(line for line in lines if line.strip()) + "\n"

    # -----------------------------------------------------------------
    # iter_xpaths
    # -----------------------------------------------------------------

    def iter_xpaths(self, tree: Any) -> Iterable[str]:
        """Yield schema xpaths from a :class:`CanonicalIntent` or legacy dict."""
        if isinstance(tree, CanonicalIntent):
            # Reuse the CLI codec's canonical walker.
            from ..cisco_iosxe_cli.codec import _walk_canonical
            yield from _walk_canonical(tree)
            return
        if not isinstance(tree, dict):
            return
        for key, val in tree.items():
            yield from _walk(val, f"/{key}")

    # -----------------------------------------------------------------
    # Cross-vendor port-name translation
    # -----------------------------------------------------------------

    def classify_port_name(self, name: str):  # -> PortIdentity
        """Classify an OPNsense interface name into a :class:`PortIdentity`.

        Thin instance-method wrapper around the module-level
        :func:`port_names.classify_port_name`.  Extracted so the
        cross-vendor orchestrator can import the pure function
        without dragging in the parser / renderer; consistent with
        the other CLI codecs.  See ``port_names.py`` for the full
        pattern inventory and docstring."""
        return _port_names.classify_port_name(name)

    def format_port_identity(self, identity) -> str | None:
        """Render a :class:`PortIdentity` as an OPNsense BSD-device name.

        Thin instance-method wrapper around
        :func:`port_names.format_port_identity`; see that module for
        the rendering rules (driver default, SVI parent fallback,
        kinds OPNsense can't represent)."""
        return _port_names.format_port_identity(identity)

    # -----------------------------------------------------------------
    # Auto-detection probe (R5)
    # -----------------------------------------------------------------

    @classmethod
    def probe(cls, raw_prefix: str) -> tuple[int, str] | None:
        """Detect OPNsense config.xml by its unique ``<opnsense>`` root."""
        lowered = raw_prefix.lower()
        # The <opnsense> tag is nearly unique to this vendor — only
        # false-positive would be a doc about OPNsense, which won't
        # survive the actual parse() anyway.
        if "<opnsense>" in lowered or "<opnsense " in lowered:
            return (98, "root element <opnsense> matches OPNsense config.xml")
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_interface_zone_canonical(el: ET.Element) -> CanonicalInterface | None:
    """Parse one ``<wan>``/``<lan>``/``<optN>`` element into a
    :class:`CanonicalInterface`.  Returns ``None`` for empty stubs."""
    # Zone name = element tag (wan, lan, opt1, etc.)
    zone = el.tag
    if_el = el.find("if")
    if if_el is None or not (if_el.text or "").strip():
        # No physical interface assigned — skip this zone.
        if len(list(el)) == 0:
            return None
    iface = CanonicalInterface(name=zone)
    descr_el = el.find("descr")
    if descr_el is not None and descr_el.text:
        iface.description = descr_el.text.strip()
    enable_el = el.find("enable")
    iface.enabled = enable_el is not None
    # MTU — stored under <mtu> when set; inherits platform default (1500)
    # when absent.  Only populate canonical when explicitly present so
    # round-trips don't introduce spurious mtu fields.
    mtu_el = el.find("mtu")
    if mtu_el is not None and mtu_el.text:
        try:
            iface.mtu = int(mtu_el.text.strip())
        except ValueError:
            pass
    ipaddr_el = el.find("ipaddr")
    subnet_el = el.find("subnet")
    if ipaddr_el is not None and ipaddr_el.text and subnet_el is not None and subnet_el.text:
        try:
            iface.ipv4_addresses.append(CanonicalIPv4Address(
                ip=ipaddr_el.text.strip(),
                prefix_length=int(subnet_el.text.strip()),
            ))
        except ValueError:
            raise ParseError(
                f"opnsense: non-integer <subnet> {subnet_el.text!r}",
                path=f"/interfaces/{el.tag}/subnet",
                snippet=(subnet_el.text or "")[:120],
            )
    return iface


def _parse_interface_zone(el: ET.Element) -> dict[str, Any] | None:
    """Parse one ``<wan>``/``<lan>``/``<optN>`` element.

    Returns ``None`` if the element has no content — OPNsense
    occasionally emits empty zone stubs that aren't worth
    round-tripping.
    """
    iface: dict[str, Any] = {"zone": el.tag}
    # All known single-value children.
    field_map = {
        "if":       "if",
        "descr":    "descr",
        "ipaddr":   "ipaddr",
        "subnet":   "subnet",   # special: coerce to int
        "enable":   "enable",   # special: YANG-ish boolean
    }
    found_any = False
    for xml_tag, py_key in field_map.items():
        child = el.find(xml_tag)
        if child is None:
            continue
        text = (child.text or "").strip()
        if py_key == "subnet":
            if not text:
                continue
            try:
                iface["subnet"] = int(text)
            except ValueError:
                raise ParseError(
                    f"opnsense: non-integer <subnet> {text!r}",
                    path=f"/interfaces/{el.tag}/subnet",
                    snippet=text[:120],
                )
            found_any = True
        elif py_key == "enable":
            # OPNsense uses an empty <enable/> element as a flag (no
            # text content when present, absent when disabled).  Any
            # non-empty text value also counts as enabled.
            iface["enable"] = True
            found_any = True
        else:
            if text:
                iface[py_key] = text
                found_any = True
    if not found_any:
        return None
    return iface


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


def _parse_opnsense_dhcp_zone(zone_el: ET.Element) -> CanonicalDHCPPool | None:
    """Parse a single ``<dhcpd>/<zone>`` element into a CanonicalDHCPPool.

    OPNsense keys DHCP config by interface zone (wan/lan/optN).  We
    preserve the zone name on the pool's ``interface`` field so
    renderers can re-emit under the right zone.  Enabled-flag is
    implicit via the presence of an ``<enable/>`` element; we treat
    a zone block as present-but-disabled as a valid pool, since the
    intent (serve this network) is preserved.
    """
    range_el = zone_el.find("range")
    start_ip = ""
    end_ip = ""
    if range_el is not None:
        from_el = range_el.find("from")
        to_el = range_el.find("to")
        start_ip = (from_el.text or "").strip() if from_el is not None else ""
        end_ip = (to_el.text or "").strip() if to_el is not None else ""

    gateway_el = zone_el.find("gateway")
    dns_el = zone_el.find("dnsserver")
    domain_el = zone_el.find("domain")
    lease_el = zone_el.find("defaultleasetime")

    gateway = (gateway_el.text or "").strip() if gateway_el is not None else ""
    dns_servers: list[str] = []
    if dns_el is not None and dns_el.text:
        dns_servers.extend(s.strip() for s in dns_el.text.split(",") if s.strip())
    domain = (domain_el.text or "").strip() if domain_el is not None else ""
    lease = 86400
    if lease_el is not None and lease_el.text:
        try:
            lease = int(lease_el.text.strip())
        except ValueError:
            pass

    # If nothing useful was captured, skip (empty zone blocks exist
    # in upstream config.xml.sample as reserved-zone scaffolding).
    if not (start_ip or end_ip or gateway or dns_servers or domain):
        return None

    return CanonicalDHCPPool(
        interface=zone_el.tag,
        start_ip=start_ip,
        end_ip=end_ip,
        gateway=gateway,
        dns_servers=dns_servers,
        lease_time=lease,
        domain_name=domain,
    )


# OPNsense LAG proto values -> canonical CanonicalLAG.mode
_OPNSENSE_PROTO_TO_CANONICAL = {
    "lacp": "active",
    "failover": "static",
    "loadbalance": "static",
    "roundrobin": "static",
    "none": "static",
}
_CANONICAL_MODE_TO_OPNSENSE_PROTO = {
    "active": "lacp",
    "passive": "lacp",   # OPNsense doesn't distinguish active/passive at this layer
    "static": "failover",
}


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


def _walk(node: Any, prefix: str) -> Iterable[str]:
    """Recursively yield schema xpaths under *prefix*."""
    if isinstance(node, dict):
        # /interfaces/interface is the only list-wrapper in this adapter.
        if prefix == "/interfaces" and isinstance(
            node.get("interface"), list
        ):
            for item in node["interface"]:
                yield from _walk(item, "/interfaces/interface")
            return
        for key, val in node.items():
            yield from _walk(val, f"{prefix}/{key}")
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item, prefix)
    else:
        # Leaf value.
        yield prefix

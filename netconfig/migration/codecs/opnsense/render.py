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
→ ``<vlans>`` → ``<dhcpd>`` → ``<laggs>`` → ``<snmpd>``.

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

from ...canonical.intent import CanonicalIntent
from ..base import RenderError


# ---------------------------------------------------------------------------
# Top-level render entry — codec.render() is a one-line delegator to this.
# ---------------------------------------------------------------------------


def render_intent(tree: Any) -> str:
    """Render a :class:`CanonicalIntent` (or legacy dict) to OPNsense
    ``config.xml`` text.

    Accepts both shapes for back-compat:

    * :class:`CanonicalIntent` — the modern path used by all
      production callers.  Goes through :func:`render_canonical`.
    * ``dict`` — the legacy nested-dict shape preserved for older
      tests that haven't been migrated.  Goes through
      :func:`render_legacy`.
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
            # GAP-EVPN-3: IPv6 emits to ``<ipaddrv6>`` + ``<subnetv6>``.
            # Only one v6 address fits the OPNsense schema.
            if iface.ipv6_addresses:
                ET.SubElement(zone_el, "ipaddrv6").text = iface.ipv6_addresses[0].ip
                ET.SubElement(zone_el, "subnetv6").text = str(iface.ipv6_addresses[0].prefix_length)

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

    return _pretty_print(root)


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

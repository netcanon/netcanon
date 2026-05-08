"""
OPNsense ``config.xml`` parser — XML-to-CanonicalIntent.

Extracted from ``codec.py`` during the parse/render split.  Everything
that consumes OPNsense XML and produces a :class:`CanonicalIntent`
lives here; ``render.py`` holds the reverse path.  ``codec.py`` is
now a thin class that delegates ``parse()`` and ``render()`` to
module-level functions here and in the sibling render module.

Public surface (consumed by codec.py's ``parse()`` method):

* :func:`parse_intent` — one-shot parse entry: raw XML in, fully-
  populated :class:`CanonicalIntent` out.  Performs the bounded
  envelope-trim before delegating to ``xml.etree.ElementTree``.

Envelope-trim helpers (still importable from
``netcanon.migration.codecs.opnsense.codec`` for tests that pin
the parser's structural contract):

* :func:`_trim_xml_envelope` — bounded head + tail trim that rescues
  legacy paramiko-shell backups whose PTY echo wrapped the XML in
  shell-prompt noise.  See the function docstring for the head-window
  / tail-scan bounds.
* ``_trim_xml_prologue`` — backwards-compat alias for the original
  prologue-only name; kept so external test code referencing the old
  identifier still resolves.

Internal element-level helpers:

* :func:`_parse_interface_zone_canonical` — one
  ``<wan>``/``<lan>``/``<optN>`` element to :class:`CanonicalInterface`.
* :func:`_parse_interface_zone` — legacy dict-shape variant retained
  for the dict-tree round-trip path used by older tests.
* :func:`_parse_opnsense_dhcp_zone` — one ``<dhcpd>/<zone>`` element
  to :class:`CanonicalDHCPPool`.

The constant ``_OPNSENSE_PROTO_TO_CANONICAL`` (LAG proto strings to
canonical mode) lives here; the inverse ``_CANONICAL_MODE_TO_OPNSENSE_PROTO``
lives in :mod:`.render`.  Each module owns the direction it consumes,
mirroring the fortigate_cli convention.

Truly malformed input still raises :class:`ParseError` — the trim is
defensive against KNOWN preamble/postamble noise, not a license to
swallow XML errors silently.
"""

from __future__ import annotations

import logging
from typing import Any
from xml.etree import ElementTree as ET

from ...canonical.intent import (
    CanonicalDHCPPool,
    CanonicalIPv4Address,
    CanonicalIPv6Address,
    CanonicalIntent,
    CanonicalInterface,
    CanonicalLAG,
    CanonicalLocalUser,
    CanonicalRADIUSServer,
    CanonicalSNMP,
    CanonicalVlan,
)
from ..base import ParseError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Envelope-trim — bounded preamble/postamble scrub for legacy backups
# ---------------------------------------------------------------------------


def _trim_xml_envelope(raw: str) -> str:
    """Strip leading + trailing non-XML noise from *raw*.

    Legacy backups captured via the paramiko-shell collector (before
    its echo-strip fix) landed on disk with BOTH:

    * A leading ``cat /conf/config.xml\\r\\r\\n`` preamble before
      the ``<?xml`` prolog (command echo from the PTY).
    * A trailing shell prompt (e.g. ``root@supergate:~ # ``) AFTER
      the ``</opnsense>`` closing tag.

    ``ET.fromstring`` refuses both shapes with cryptic line/column
    errors.  Rather than making operators re-back-up every device,
    the codec tolerates a bounded amount of noise on either end by
    locating the XML prolog/root at the head and the closing tag
    at the tail, slicing between.

    The strip is BOUNDED (head window = 2 KiB, tail scan = last
    ``</opnsense>`` occurrence) so truly malformed input still
    falls through to the parse error — operator visibility for
    genuine failures is preserved.
    """
    if not raw:
        return raw
    # --- Head trim: find first <?xml or <opnsense marker ---
    head_limit = min(len(raw), 2048)
    head = raw[:head_limit]
    prolog_idx = head.find("<?xml")
    root_idx = head.find("<opnsense")
    head_candidates = [idx for idx in (prolog_idx, root_idx) if idx >= 0]
    if head_candidates:
        start = min(head_candidates)
        if start > 0:
            raw = raw[start:]
    # --- Tail trim: find last </opnsense> and slice after it.
    # rfind lets us skip straight to the last occurrence; finding
    # the closing tag alone handles both well-formed close + any
    # trailing whitespace/prompt noise the collector left behind. ---
    close_tag = "</opnsense>"
    close_idx = raw.rfind(close_tag)
    if close_idx >= 0:
        end = close_idx + len(close_tag)
        if end < len(raw):
            raw = raw[:end]
    return raw


# Backwards-compat alias — the tighter prologue-only name was the
# original shape; the envelope rename reflects the extended scope.
_trim_xml_prologue = _trim_xml_envelope


# ---------------------------------------------------------------------------
# Top-level parse entry — codec.parse() is a one-line delegator to this.
# ---------------------------------------------------------------------------


def parse_intent(raw: str) -> CanonicalIntent:
    """Parse an OPNsense ``config.xml`` document into a
    :class:`CanonicalIntent`.

    Defensive envelope-trim: if the input has noise before the
    XML prolog (shell command echo, banner MOTD) or after the
    closing tag (shell prompt residue), locate the XML markers
    and slice.  This rescues legacy backups written by a
    pre-fix ParamikoShellCollector that stripped neither end
    of the PTY buffer.  The strip is bounded — a marker MUST
    be present or the input passes through unchanged so truly
    malformed XML still raises the intended ParseError.

    Raises:
        ParseError: On malformed XML or missing ``<opnsense>`` root.
    """
    raw = _trim_xml_envelope(raw)
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
        # System DNS servers — real OPNsense stores top-level
        # resolver targets as repeated ``<system>/<dnsserver>`` children
        # (one IP per element), distinct from per-DHCP-pool DNS-server
        # lists which live under ``<dhcpd>/<zone>/<dnsserver>``.  See
        # tests/fixtures/real/opnsense/user_contrib_supergate_opn25.xml
        # (lines 221, 223) and the "DNS Servers" section of
        # https://docs.opnsense.org/manual/settings_general.html.
        for dns_el in sys_el.findall("dnsserver"):
            if dns_el.text and dns_el.text.strip():
                intent.dns_servers.append(dns_el.text.strip())
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
            # Per-user <priv> elements grant WebGUI privileges directly.
            # OPNsense's "page-all" privilege is the "WebGUI - All pages"
            # token (operationally equivalent to admin) — when present
            # on a <user> element it elevates regardless of group
            # membership.  Real OPNsense exports may carry multiple
            # <priv> children (one per privilege token) so iterate
            # rather than just .find().  See:
            # https://docs.opnsense.org/manual/firewall_users.html
            # (User privileges section).
            user_privs = {
                (p.text or "").strip().lower()
                for p in user_el.findall("priv")
                if p.text and p.text.strip()
            }
            # Admin privilege detection (sub-finding 19).  Two
            # cooperating sources of truth, with explicit
            # ``<groupname>`` taking precedence so we don't regress
            # the synthetic / legacy shape that uses groupname as
            # the privilege carrier:
            #
            #   * If ``<groupname>`` is present, it is authoritative:
            #     ``admins`` → 15, anything else → 1.  This preserves
            #     ``test_scope_does_not_determine_privilege`` (a
            #     ``<scope>system</scope>`` + ``<groupname>users
            #     </groupname>`` user stays at priv 1) and the
            #     kitchen_sink fixture's per-user groupname semantics.
            #   * If ``<groupname>`` is ABSENT (the real-OPNsense
            #     shape — group membership lives under ``<system>/
            #     <group>/<member>UID,UID</member></group>``, not on
            #     the user), fall back to scope/priv heuristics:
            #         - ``<scope>system</scope>`` → 15.  Real OPNsense
            #           reserves system scope for built-in privileged
            #           accounts (root, operator); non-admin daemon
            #           users don't surface under ``<system>/<user>``.
            #         - ``page-all`` in any per-user ``<priv>`` element
            #           → 15.  Direct "WebGUI - All pages" grant.
            #
            # The supergate real fixture's root (scope=system, no
            # groupname) and api (scope=user, priv=page-all, no
            # groupname) both elevate correctly under this rule.
            # Refs: https://docs.opnsense.org/manual/firewall_users.html
            # (User privileges, Groups).
            if groupname:
                is_admin = groupname == "admins"
            else:
                is_admin = (
                    scope == "system"
                    or "page-all" in user_privs
                )
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

    logger.debug(
        "opnsense parsed: hostname=%r ifaces=%d vlans=%d "
        "routes=%d lags=%d users=%d snmp=%s (input=%d chars)",
        intent.hostname,
        len(intent.interfaces),
        len(intent.vlans),
        len(intent.static_routes),
        len(intent.lags),
        len(intent.local_users),
        "yes" if intent.snmp else "no",
        len(raw),
    )
    return intent


# ---------------------------------------------------------------------------
# Element-level parse helpers
# ---------------------------------------------------------------------------


def _parse_interface_zone_canonical(el: ET.Element) -> CanonicalInterface | None:
    """Parse one ``<wan>``/``<lan>``/``<optN>`` element into a
    :class:`CanonicalInterface`.

    Canonical name resolution: prefer the ``<if>`` child's text when
    present (real OPNsense XML always carries it: ``<lan><if>igb0</if>``;
    our render emits it carrying the canonical name verbatim so the
    round-trip survives ``_zone_tag_for``'s lossy sanitisation).  Fall
    back to the element tag for legacy XML that lacks ``<if>``.

    Empty-zone-stub rule was previously: if ``<if>`` was missing AND
    the element had zero children, return None.  This dropped sparse
    interfaces (disabled-only, no IP, no descr) on round-trip.  The
    rule is now removed — named-but-empty zones round-trip as a
    CanonicalInterface with just the name set.  The truly degenerate
    case (empty tag with no children AND no ``<if>``) is rare in real
    OPNsense output and the resulting CanonicalInterface is harmless.
    """
    if_el = el.find("if")
    if if_el is not None and if_el.text and if_el.text.strip():
        iface_name = if_el.text.strip()
    else:
        # Legacy fallback for XML that lacks <if> — use the zone tag.
        iface_name = el.tag
    iface = CanonicalInterface(name=iface_name)
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
    # Sub-finding 9a: ``<ipaddr>dhcp</ipaddr>`` is the DHCP-client
    # keyword.  Real OPNsense WAN zones carry this when the upstream
    # ISP runs DHCP (``<wan><if>igc0</if><ipaddr>dhcp</ipaddr></wan>``).
    # Treat it as a DHCP-client signal (CanonicalInterface.dhcp_client)
    # and skip the static-IP append — "dhcp" is not a valid IPv4
    # address and previously fell through silently, dropping the
    # WAN-DHCP intent on cross-vendor render paths (Cisco IOS-XE,
    # MikroTik RouterOS, Junos all consume ``iface.dhcp_client`` to
    # emit their respective ``ip address dhcp`` / ``family inet
    # dhcp`` lines).  Case-insensitive — operators occasionally
    # type "DHCP" by hand.  See OPNsense docs:
    # https://docs.opnsense.org/manual/interfaces.html
    # (Configure - IPv4 Configuration Type - DHCP).
    if ipaddr_el is not None and ipaddr_el.text and ipaddr_el.text.strip().lower() == "dhcp":
        iface.dhcp_client = True
    elif ipaddr_el is not None and ipaddr_el.text and subnet_el is not None and subnet_el.text:
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
    # GAP-EVPN-3: ``<ipaddrv6>X</ipaddrv6>`` + ``<subnetv6>N</subnetv6>``.
    # OPNsense uses the same shape as IPv4 but with the v6 suffix.
    # Non-static keywords (``dhcp6``, ``track6``, ``slaac``, ``6rd``,
    # ``6to4``) are NOT static addresses; they populate
    # ``CanonicalInterface.dhcp_client_v6`` instead of
    # ``ipv6_addresses``.  See the field's docstring for the keyword
    # set and cross-vendor mapping.  OPNsense doc reference:
    # https://docs.opnsense.org/manual/interfaces.html
    # (Configure - IPv6 Configuration Type).
    ipaddrv6_el = el.find("ipaddrv6")
    subnetv6_el = el.find("subnetv6")
    if ipaddrv6_el is not None and ipaddrv6_el.text:
        v6_text = ipaddrv6_el.text.strip().lower()
        if v6_text in ("dhcp6", "slaac", "track6", "6rd", "6to4"):
            iface.dhcp_client_v6 = v6_text
    if (
        ipaddrv6_el is not None
        and ipaddrv6_el.text
        and ":" in ipaddrv6_el.text  # filter dhcp6 / track6 / slaac
        and subnetv6_el is not None
        and subnetv6_el.text
    ):
        try:
            ip_v6 = ipaddrv6_el.text.strip()
            lo = ip_v6.lower()
            scope = (
                "link-local"
                if (
                    len(lo) >= 3
                    and lo[:2] == "fe"
                    and lo[2] in ("8", "9", "a", "b")
                )
                else "global"
            )
            iface.ipv6_addresses.append(CanonicalIPv6Address(
                ip=ip_v6,
                prefix_length=int(subnetv6_el.text.strip()),
                scope=scope,
            ))
        except ValueError:
            raise ParseError(
                f"opnsense: non-integer <subnetv6> {subnetv6_el.text!r}",
                path=f"/interfaces/{el.tag}/subnetv6",
                snippet=(subnetv6_el.text or "")[:120],
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


# ---------------------------------------------------------------------------
# LAG proto map — parse direction (forward).  Render owns the inverse.
# ---------------------------------------------------------------------------

# OPNsense LAG proto values -> canonical CanonicalLAG.mode
_OPNSENSE_PROTO_TO_CANONICAL = {
    "lacp": "active",
    "failover": "static",
    "loadbalance": "static",
    "roundrobin": "static",
    "none": "static",
}

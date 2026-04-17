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

from typing import Any, ClassVar, Iterable
from xml.etree import ElementTree as ET

from ....models.migration import (
    CapabilityMatrix,
    DeviceClass,
    LossyPath,
    UnsupportedPath,
)
from ...canonical.intent import (
    CanonicalIPv4Address,
    CanonicalIntent,
    CanonicalInterface,
    CanonicalVlan,
)
from ..base import CodecBase, ParseError, RenderError
from ..registry import register


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
    certainty: ClassVar[str] = "best_effort"
    canonical_model: ClassVar[str] = "openconfig-lite"

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

        # System
        if intent.hostname or intent.domain:
            sys_el = ET.SubElement(root, "system")
            if intent.hostname:
                ET.SubElement(sys_el, "hostname").text = intent.hostname
            if intent.domain:
                ET.SubElement(sys_el, "domain").text = intent.domain

        # Interfaces — render as zone-keyed elements.
        # For canonical intents from OTHER vendors we need to assign zone
        # names.  Use the interface name as the zone if it looks like an
        # OPNsense zone (wan/lan/optN), otherwise use the name as-is.
        if intent.interfaces:
            ifaces_el = ET.SubElement(root, "interfaces")
            for iface in intent.interfaces:
                zone_name = iface.name if iface.name in ("wan", "lan") or iface.name.startswith("opt") else iface.name.lower().replace("/", "_").replace(" ", "_")
                zone_el = ET.SubElement(ifaces_el, zone_name)
                if iface.description:
                    ET.SubElement(zone_el, "descr").text = iface.description
                if iface.enabled:
                    ET.SubElement(zone_el, "enable")
                if iface.ipv4_addresses:
                    ET.SubElement(zone_el, "ipaddr").text = iface.ipv4_addresses[0].ip
                    ET.SubElement(zone_el, "subnet").text = str(iface.ipv4_addresses[0].prefix_length)

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

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

    _CAPS: ClassVar[CapabilityMatrix] = CapabilityMatrix(
        adapter="opnsense",
        vendor_id="opnsense",
        version_range="24.x+",
        device_classes=[DeviceClass.firewall, DeviceClass.router],
        supported=[
            "/system/hostname",
            "/system/domain",
            "/interfaces/interface/zone",
            "/interfaces/interface/if",
            "/interfaces/interface/descr",
            "/interfaces/interface/enable",
            "/interfaces/interface/ipaddr",
            "/interfaces/interface/subnet",
        ],
        lossy=[
            LossyPath(
                path="/interfaces/interface/descr",
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

    def parse(self, raw: str) -> dict[str, Any]:
        """Parse an OPNsense ``config.xml`` document.

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

        tree: dict[str, Any] = {}

        # ----- <system> block -----
        sys_el = root.find("system")
        if sys_el is not None:
            system: dict[str, Any] = {}
            for field in ("hostname", "domain"):
                child = sys_el.find(field)
                if child is not None and child.text:
                    system[field] = child.text.strip()
            if system:
                tree["system"] = system

        # ----- <interfaces> block — flatten into list -----
        iface_parent = root.find("interfaces")
        if iface_parent is not None:
            ifaces: list[dict[str, Any]] = []
            # OPNsense uses <wan>, <lan>, <optN> children keyed by zone.
            for zone_el in iface_parent:
                iface = _parse_interface_zone(zone_el)
                if iface is not None:
                    ifaces.append(iface)
            tree["interfaces"] = {"interface": ifaces}

        return tree

    # -----------------------------------------------------------------
    # Render
    # -----------------------------------------------------------------

    def render(self, tree: dict[str, Any]) -> str:
        """Render the tree back to OPNsense-style ``config.xml`` text."""
        if not isinstance(tree, dict):
            raise RenderError(
                "opnsense: tree must be a dict",
                yang_path="/",
            )
        root = ET.Element("opnsense")

        system = tree.get("system")
        if system is not None:
            sys_el = ET.SubElement(root, "system")
            # Deterministic order for stable textual diffs.
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
        return ET.tostring(root, encoding="unicode")

    # -----------------------------------------------------------------
    # iter_xpaths
    # -----------------------------------------------------------------

    def iter_xpaths(self, tree: Any) -> Iterable[str]:
        """Yield schema xpaths for every leaf in *tree*.

        Same conventions as :class:`CiscoIOSXECodec.iter_xpaths` —
        OpenConfig schema paths, no list-key predicates.  Hand-walks
        the two known structural wrappers (``/interfaces/interface``
        is a list); every other dict nests naturally.
        """
        if not isinstance(tree, dict):
            return
        for key, val in tree.items():
            yield from _walk(val, f"/{key}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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

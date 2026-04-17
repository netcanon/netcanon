"""
``CiscoIOSXECodec`` — first real adapter.

Tree shape
----------
Nested dict mirroring OpenConfig interface structure, namespace-
stripped for readability::

    {
        "interfaces": {
            "interface": [
                {
                    "name": "GigabitEthernet0/0/0",
                    "config": {
                        "name": "GigabitEthernet0/0/0",
                        "description": "WAN uplink",
                        "enabled": True,
                        "type": "ianaift:ethernetCsmacd",
                    },
                    "subinterfaces": {
                        "subinterface": [
                            {
                                "index": 0,
                                "ipv4": {
                                    "addresses": {
                                        "address": [
                                            {
                                                "ip": "10.0.0.1",
                                                "config": {
                                                    "ip": "10.0.0.1",
                                                    "prefix-length": 24,
                                                },
                                            }
                                        ]
                                    }
                                },
                            }
                        ]
                    },
                },
            ]
        }
    }

Why nested rather than flat xpaths?
    Round-trip correctness: element order in lists matters for
    downstream textual diffs, and XML is fundamentally hierarchical.
    A flat xpath map loses the hierarchy.

Why namespace-stripped?
    The parser normalises by stripping Clark-notation prefixes; the
    renderer attaches the canonical OpenConfig namespaces back on
    output.  This keeps the internal tree the same regardless of which
    prefix a given device's response happens to use.

Round-trip invariant (proven in unit tests):
    ``adapter.parse(adapter.render(tree)) == tree``
for every tree in the adapter's supported subset.
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


# ---------------------------------------------------------------------------
# Namespaces — canonical OpenConfig interfaces + IP augment modules.
# ---------------------------------------------------------------------------
# The parser strips these on the way in; the renderer puts the
# ``openconfig-interfaces`` namespace back on the root element and
# leaves the rest unprefixed (XML namespace inheritance).  This is
# enough to round-trip against a real Cisco IOS-XE 17.x response
# without having to track which exact prefix the device used.
_NS_IF = "http://openconfig.net/yang/interfaces"
_NS_IP = "http://openconfig.net/yang/interfaces/ip"


@register
class CiscoIOSXECodec(CodecBase):
    """Adapter for Cisco IOS-XE 17.x OpenConfig NETCONF.

    Declares device_classes=[router, switch] — IOS-XE platforms
    routinely fulfil both roles (ISR, Catalyst 9K).  See
    :class:`DeviceClass` for the taxonomy.
    """

    name: ClassVar[str] = "cisco_iosxe"
    version_hint: ClassVar[str | None] = "17.x"
    input_format: ClassVar[str] = "xml-netconf"
    description: ClassVar[str] = (
        "Paste an OpenConfig <interfaces> fragment or a full NETCONF "
        "<rpc-reply><data>… response.  This is the MACHINE-READABLE "
        "format returned by a device's `netconf get-config`; it is "
        "NOT the same as `show running-config`."
    )
    sample_input: ClassVar[str] = (
        '<?xml version="1.0"?>\n'
        '<interfaces xmlns="http://openconfig.net/yang/interfaces">\n'
        '  <interface>\n'
        '    <name>GigabitEthernet0/0/0</name>\n'
        '    <config>\n'
        '      <name>GigabitEthernet0/0/0</name>\n'
        '      <description>WAN uplink</description>\n'
        '      <enabled>true</enabled>\n'
        '    </config>\n'
        '    <subinterfaces>\n'
        '      <subinterface>\n'
        '        <index>0</index>\n'
        '        <ipv4 xmlns="http://openconfig.net/yang/interfaces/ip">\n'
        '          <addresses><address>\n'
        '            <ip>198.51.100.1</ip>\n'
        '            <config><ip>198.51.100.1</ip><prefix-length>30</prefix-length></config>\n'
        '          </address></addresses>\n'
        '        </ipv4>\n'
        '      </subinterface>\n'
        '    </subinterfaces>\n'
        '  </interface>\n'
        '</interfaces>\n'
    )
    output_extension: ClassVar[str] = "xml"
    direction: ClassVar[str] = "bidirectional"
    certainty: ClassVar[str] = "best_effort"
    canonical_model: ClassVar[str] = "openconfig-lite"

    #: Declared capability matrix.  Paths are canonical schema paths
    #: matching what :meth:`iter_xpaths` yields on a ``CanonicalIntent``
    #: tree.  (After the canonical-bridge migration the NETCONF codec
    #: emits the same tree shape as the CLI codec.)
    _CAPS: ClassVar[CapabilityMatrix] = CapabilityMatrix(
        adapter="cisco_iosxe",
        vendor_id="cisco_iosxe",
        version_range="16.3+",
        device_classes=[DeviceClass.router, DeviceClass.switch],
        supported=[
            "/system/hostname",
            "/system/dns-server",
            "/system/ntp-server",
            "/interfaces/interface/name",
            "/interfaces/interface/config/description",
            "/interfaces/interface/config/enabled",
            "/interfaces/interface/config/type",
            "/interfaces/interface/ipv4/address/ip",
            "/interfaces/interface/ipv4/address/prefix-length",
            "/vlans/vlan/id",
            "/vlans/vlan/name",
            "/routing/static-route",
        ],
        lossy=[
            LossyPath(
                path="/interfaces/interface/config/mtu",
                reason=(
                    "IOS-XE OC model tracks MTU but some platform-specific "
                    "MTU tweaks (IP vs link) are only representable in CLI; "
                    "YANG-only round-trip loses the distinction."
                ),
                severity="warn",
            ),
        ],
        unsupported=[
            UnsupportedPath(
                path="/interfaces/interface/ipv6",
                reason=(
                    "Phase 0.5 covers IPv4 only — IPv6 support is queued "
                    "for Phase 1 once BGP/OSPF models land."
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

    def parse(self, raw: str) -> "CanonicalIntent":
        """Parse a NETCONF ``<get-config>`` response (or bare openconfig
        ``<interfaces>`` fragment) into a :class:`CanonicalIntent`.

        Accepts two input shapes:

        1. Full NETCONF reply::

            <rpc-reply><data><interfaces ...>...</interfaces></data></rpc-reply>

        2. Bare OpenConfig fragment::

            <interfaces xmlns="http://openconfig.net/yang/interfaces">...

        Raises:
            ParseError: If the XML is malformed or the ``<interfaces>``
                root isn't findable.
        """
        from ...canonical.intent import (
            CanonicalIPv4Address,
            CanonicalIntent,
            CanonicalInterface,
        )
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            raise ParseError(
                f"cisco_iosxe: malformed XML: {exc}",
                snippet=raw[:120],
            ) from exc

        # Walk down to the <interfaces> element regardless of envelope.
        interfaces_el = _find_interfaces(root)
        if interfaces_el is None:
            raise ParseError(
                "cisco_iosxe: no <interfaces> element found "
                "(expected at top level or under <rpc-reply>/<data>)",
                snippet=raw[:120],
            )

        intent = CanonicalIntent(
            source_vendor="cisco_iosxe",
            source_format="xml-netconf",
        )
        for idx, iface_el in enumerate(interfaces_el.findall(_q("interface"))):
            raw_iface = _parse_interface(iface_el, idx=idx)
            intent.interfaces.append(_iface_dict_to_canonical(raw_iface))
        return intent

    # -----------------------------------------------------------------
    # Render
    # -----------------------------------------------------------------

    def render(self, tree: dict[str, Any]) -> str:
        """Render *tree* as OpenConfig NETCONF XML.

        Output shape: bare ``<interfaces>`` root with the openconfig
        namespace declared.  Callers wrapping this in a NETCONF
        ``<edit-config>`` envelope (Phase 1) can embed it verbatim.

        The output is deterministic (stable child ordering) — required
        for the textual diff stage downstream.

        Raises:
            RenderError: If *tree* doesn't have the expected top-level
                ``interfaces.interface`` shape.
        """
        # Accept CanonicalIntent (new canonical shape) or legacy dict.
        from ...canonical.intent import CanonicalIntent
        if isinstance(tree, CanonicalIntent):
            return self._render_canonical(tree)
        if not isinstance(tree, dict) or "interfaces" not in tree:
            raise RenderError(
                "cisco_iosxe: tree missing top-level 'interfaces' key",
                yang_path="/interfaces",
            )
        root = ET.Element(f"{{{_NS_IF}}}interfaces")
        iface_list = tree["interfaces"].get("interface", [])
        for iface in iface_list:
            _render_interface(iface, root)
        # ElementTree emits clean short-form namespaced tags; we also
        # add the xmlns declaration manually so the serialised form is
        # human-readable.
        ET.register_namespace("", _NS_IF)
        ET.register_namespace("oc-ip", _NS_IP)
        raw_xml = ET.tostring(root, encoding="unicode")
        # Pretty-print so the output viewer is human-readable.
        from xml.dom.minidom import parseString
        pretty = parseString(raw_xml).toprettyxml(indent="  ")
        # minidom adds an XML declaration; strip it for a clean fragment.
        lines = pretty.splitlines()
        if lines and lines[0].startswith("<?xml"):
            lines = lines[1:]
        return "\n".join(line for line in lines if line.strip()) + "\n"

    def _render_canonical(self, intent) -> str:
        """Render a CanonicalIntent to OpenConfig NETCONF XML."""
        root = ET.Element(f"{{{_NS_IF}}}interfaces")
        for iface in intent.interfaces:
            iface_el = ET.SubElement(root, f"{{{_NS_IF}}}interface")
            ET.SubElement(iface_el, f"{{{_NS_IF}}}name").text = iface.name
            cfg_el = ET.SubElement(iface_el, f"{{{_NS_IF}}}config")
            ET.SubElement(cfg_el, f"{{{_NS_IF}}}name").text = iface.name
            if iface.description:
                ET.SubElement(cfg_el, f"{{{_NS_IF}}}description").text = iface.description
            ET.SubElement(cfg_el, f"{{{_NS_IF}}}enabled").text = (
                "true" if iface.enabled else "false"
            )
            if iface.interface_type:
                ET.SubElement(cfg_el, f"{{{_NS_IF}}}type").text = iface.interface_type
            if iface.ipv4_addresses:
                subs_el = ET.SubElement(iface_el, f"{{{_NS_IF}}}subinterfaces")
                si_el = ET.SubElement(subs_el, f"{{{_NS_IF}}}subinterface")
                ET.SubElement(si_el, f"{{{_NS_IF}}}index").text = "0"
                ipv4_el = ET.SubElement(si_el, f"{{{_NS_IP}}}ipv4")
                addrs_el = ET.SubElement(ipv4_el, f"{{{_NS_IP}}}addresses")
                for addr in iface.ipv4_addresses:
                    a_el = ET.SubElement(addrs_el, f"{{{_NS_IP}}}address")
                    ET.SubElement(a_el, f"{{{_NS_IP}}}ip").text = addr.ip
                    ac_el = ET.SubElement(a_el, f"{{{_NS_IP}}}config")
                    ET.SubElement(ac_el, f"{{{_NS_IP}}}ip").text = addr.ip
                    ET.SubElement(ac_el, f"{{{_NS_IP}}}prefix-length").text = str(addr.prefix_length)
        ET.register_namespace("", _NS_IF)
        ET.register_namespace("oc-ip", _NS_IP)
        raw_xml = ET.tostring(root, encoding="unicode")
        from xml.dom.minidom import parseString
        pretty = parseString(raw_xml).toprettyxml(indent="  ")
        lines = pretty.splitlines()
        if lines and lines[0].startswith("<?xml"):
            lines = lines[1:]
        return "\n".join(line for line in lines if line.strip()) + "\n"

    # -----------------------------------------------------------------
    # iter_xpaths — schema paths, no list-key predicates
    # -----------------------------------------------------------------

    def iter_xpaths(self, tree: Any) -> Iterable[str]:
        """Yield schema xpaths for every leaf in *tree*.

        Accepts both :class:`CanonicalIntent` (what ``parse()`` returns
        after the canonical-bridge migration) and the legacy nested
        dict shape (for back-compat with callers still handing us
        pre-canonical trees).
        """
        from ...canonical.intent import CanonicalIntent
        if isinstance(tree, CanonicalIntent):
            from ..cisco_iosxe_cli.codec import _walk_canonical
            yield from _walk_canonical(tree)
            return
        if not isinstance(tree, dict):
            return
        yield from _walk(tree, "")

    # -----------------------------------------------------------------
    # Auto-detection probe (R5)
    # -----------------------------------------------------------------

    @classmethod
    def probe(cls, raw_prefix: str) -> tuple[int, str] | None:
        """Detect OpenConfig NETCONF XML by its namespace signature."""
        lowered = raw_prefix.lower()
        if "openconfig.net/yang" in lowered:
            return (
                95,
                "OpenConfig YANG namespace found — NETCONF payload",
            )
        # <rpc-reply> is the NETCONF envelope; almost always contains
        # openconfig in practice but we rank it lower just in case.
        if "<rpc-reply" in lowered or "<data>" in lowered:
            return (70, "NETCONF envelope tag present")
        # Bare OpenConfig-shaped <interfaces> with XML namespace.
        if ("<interfaces" in lowered and "xmlns" in lowered
                and "<interface>" in lowered):
            return (75, "OpenConfig-shaped <interfaces> XML fragment")
        return None


# ---------------------------------------------------------------------------
# Helpers — parsing, rendering, walking.  Kept at module level (not
# instance methods) because they are pure and more readable as functions.
# ---------------------------------------------------------------------------


def _q(local: str, ns: str = _NS_IF) -> str:
    """Build a Clark-notation qualified name for ``findall`` / ``find``."""
    return f"{{{ns}}}{local}"


def _strip_ns(tag: str) -> str:
    """Strip the ``{ns}`` prefix from a Clark-notation tag."""
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _find_interfaces(root: ET.Element) -> ET.Element | None:
    """Locate the ``<interfaces>`` element under either a NETCONF
    envelope or a bare fragment.  Namespace-aware."""
    if _strip_ns(root.tag) == "interfaces":
        return root
    # Dig through common NETCONF envelopes.
    for path in ("./data/interfaces", "./{*}data/{*}interfaces"):
        # ElementTree's wildcard `{*}` requires Python 3.8+ for findall,
        # but stability matters — fall back to hand-walk.
        pass
    # Hand-walk to avoid version-specific findall behaviour.
    for child in root.iter():
        if _strip_ns(child.tag) == "interfaces":
            return child
    return None


def _parse_interface(el: ET.Element, idx: int = 0) -> dict[str, Any]:
    """Parse a single ``<interface>`` element into the internal shape.

    Args:
        el: The ``<interface>`` element to parse.
        idx: 0-based index of this element in its ``<interfaces>``
            parent.  Used only to give a useful location string in
            any :class:`ParseError` raised from here.
    """
    out: dict[str, Any] = {}
    # Top-level <name> key of the list — must be present AND non-empty.
    name_el = el.find(_q("name"))
    name_text = (name_el.text or "").strip() if name_el is not None else ""
    if not name_text:
        # Summary of the offending element to help locate it in the
        # original payload; capped so the snippet stays banner-friendly.
        snippet = ET.tostring(el, encoding="unicode")
        if len(snippet) > 200:
            snippet = snippet[:200] + "…"
        raise ParseError(
            f"cisco_iosxe: <interface>[{idx}] missing required non-empty "
            f"<name> element",
            path=f"/interfaces/interface[{idx}]/name",
            snippet=snippet,
        )
    out["name"] = name_text

    # <config> block
    config_el = el.find(_q("config"))
    if config_el is not None:
        out["config"] = _parse_config(config_el, iface_idx=idx)

    # <subinterfaces><subinterface>... block (optional)
    subs_el = el.find(_q("subinterfaces"))
    if subs_el is not None:
        subinterfaces: list[dict[str, Any]] = []
        for si_el in subs_el.findall(_q("subinterface")):
            subinterfaces.append(
                _parse_subinterface(si_el, iface_idx=idx)
            )
        out["subinterfaces"] = {"subinterface": subinterfaces}

    return out


#: Accepted spellings of a YANG boolean per RFC 7950 §9.6.  Anything else
#: is a parser error — "yes"/"no"/"1"/"0" are NOT valid and must fail
#: loudly so operators don't ship a config they thought was enabled but
#: actually ended up disabled (or vice versa).
_YANG_TRUE = {"true"}
_YANG_FALSE = {"false"}


def _parse_config(el: ET.Element, iface_idx: int = 0) -> dict[str, Any]:
    """Parse an interface ``<config>`` block."""
    out: dict[str, Any] = {}
    for child in el:
        tag = _strip_ns(child.tag)
        if tag == "name":
            out["name"] = child.text or ""
        elif tag == "description":
            out["description"] = child.text or ""
        elif tag == "enabled":
            # OC enabled is YANG boolean — STRICT parsing.  Accept
            # "true" / "false" case-insensitively but reject anything
            # else.  Silently coercing "yes" to False (or to True) is
            # the kind of bug that ships a disabled interface to
            # production and wastes a night debugging.
            raw = (child.text or "").strip().lower()
            if raw in _YANG_TRUE:
                out["enabled"] = True
            elif raw in _YANG_FALSE:
                out["enabled"] = False
            else:
                raise ParseError(
                    f"cisco_iosxe: <enabled> must be YANG boolean "
                    f"'true' or 'false', got {child.text!r}",
                    path=(
                        f"/interfaces/interface[{iface_idx}]/config/enabled"
                    ),
                    snippet=(child.text or "")[:120],
                )
        elif tag == "type":
            out["type"] = (child.text or "").strip()
        elif tag == "mtu":
            try:
                out["mtu"] = int((child.text or "0").strip())
            except ValueError:
                raise ParseError(
                    f"cisco_iosxe: non-integer mtu {child.text!r}",
                    path=f"/interfaces/interface[{iface_idx}]/config/mtu",
                    snippet=(child.text or "")[:120],
                )
    return out


def _parse_subinterface(el: ET.Element, iface_idx: int = 0) -> dict[str, Any]:
    """Parse a single ``<subinterface>`` element."""
    out: dict[str, Any] = {}
    idx_el = el.find(_q("index"))
    if idx_el is not None and idx_el.text is not None:
        out["index"] = int(idx_el.text.strip())

    # <ipv4> block — IP augment namespace, but we strip and treat uniformly.
    ipv4_el = None
    for child in el:
        if _strip_ns(child.tag) == "ipv4":
            ipv4_el = child
            break
    if ipv4_el is not None:
        out["ipv4"] = _parse_ipv4(ipv4_el, iface_idx=iface_idx)
    return out


def _parse_ipv4(el: ET.Element, iface_idx: int = 0) -> dict[str, Any]:
    """Parse an ``<ipv4><addresses>`` subtree."""
    addresses: list[dict[str, Any]] = []
    addrs_el = None
    for child in el:
        if _strip_ns(child.tag) == "addresses":
            addrs_el = child
            break
    if addrs_el is not None:
        for addr_el in addrs_el:
            if _strip_ns(addr_el.tag) != "address":
                continue
            addr: dict[str, Any] = {}
            ip_el = _first_child_by_tag(addr_el, "ip")
            if ip_el is not None and ip_el.text:
                addr["ip"] = ip_el.text.strip()
            cfg_el = _first_child_by_tag(addr_el, "config")
            if cfg_el is not None:
                cfg: dict[str, Any] = {}
                for c in cfg_el:
                    tag = _strip_ns(c.tag)
                    if tag == "ip" and c.text:
                        cfg["ip"] = c.text.strip()
                    elif tag == "prefix-length" and c.text:
                        pl_text = c.text.strip()
                        pl_path = (
                            f"/interfaces/interface[{iface_idx}]/"
                            f"subinterfaces/subinterface/ipv4/addresses/"
                            f"address/config/prefix-length"
                        )
                        try:
                            pl = int(pl_text)
                        except ValueError:
                            raise ParseError(
                                f"cisco_iosxe: non-integer prefix-length "
                                f"{c.text!r}",
                                path=pl_path,
                                snippet=pl_text[:120],
                            )
                        # IPv4 prefix length is a YANG inet:ipv4-prefix,
                        # formally 0..32.  Silently accepting 99 or -1
                        # lets a bogus input reach render time where
                        # ElementTree serialises it cleanly and nobody
                        # notices until the device rejects the edit.
                        if not 0 <= pl <= 32:
                            raise ParseError(
                                f"cisco_iosxe: prefix-length {pl} out of "
                                f"range [0, 32] for IPv4",
                                path=pl_path,
                                snippet=pl_text[:120],
                            )
                        cfg["prefix-length"] = pl
                addr["config"] = cfg
            addresses.append(addr)
    return {"addresses": {"address": addresses}}


def _first_child_by_tag(el: ET.Element, local_tag: str) -> ET.Element | None:
    """Return the first child whose local-name equals *local_tag*."""
    for child in el:
        if _strip_ns(child.tag) == local_tag:
            return child
    return None


# ---------------------------------------------------------------------------
# Render — nested dict → ElementTree
# ---------------------------------------------------------------------------


def _render_interface(iface: dict[str, Any], parent: ET.Element) -> None:
    iface_el = ET.SubElement(parent, f"{{{_NS_IF}}}interface")
    name = iface.get("name")
    if name is None:
        raise RenderError(
            "cisco_iosxe: interface dict missing 'name'",
            yang_path="/interfaces/interface/name",
        )
    ET.SubElement(iface_el, f"{{{_NS_IF}}}name").text = name

    cfg = iface.get("config")
    if cfg is not None:
        cfg_el = ET.SubElement(iface_el, f"{{{_NS_IF}}}config")
        if "name" in cfg:
            ET.SubElement(cfg_el, f"{{{_NS_IF}}}name").text = cfg["name"]
        if "description" in cfg:
            ET.SubElement(cfg_el, f"{{{_NS_IF}}}description").text = cfg[
                "description"
            ]
        if "enabled" in cfg:
            ET.SubElement(cfg_el, f"{{{_NS_IF}}}enabled").text = (
                "true" if cfg["enabled"] else "false"
            )
        if "type" in cfg:
            ET.SubElement(cfg_el, f"{{{_NS_IF}}}type").text = cfg["type"]
        if "mtu" in cfg:
            ET.SubElement(cfg_el, f"{{{_NS_IF}}}mtu").text = str(cfg["mtu"])

    subs = iface.get("subinterfaces")
    if subs is not None:
        subs_el = ET.SubElement(iface_el, f"{{{_NS_IF}}}subinterfaces")
        for si in subs.get("subinterface", []):
            _render_subinterface(si, subs_el)


def _render_subinterface(si: dict[str, Any], parent: ET.Element) -> None:
    si_el = ET.SubElement(parent, f"{{{_NS_IF}}}subinterface")
    if "index" in si:
        ET.SubElement(si_el, f"{{{_NS_IF}}}index").text = str(si["index"])
    if "ipv4" in si:
        _render_ipv4(si["ipv4"], si_el)


def _render_ipv4(ipv4: dict[str, Any], parent: ET.Element) -> None:
    ipv4_el = ET.SubElement(parent, f"{{{_NS_IP}}}ipv4")
    addrs = ipv4.get("addresses", {}).get("address", [])
    if addrs:
        addrs_el = ET.SubElement(ipv4_el, f"{{{_NS_IP}}}addresses")
        for a in addrs:
            a_el = ET.SubElement(addrs_el, f"{{{_NS_IP}}}address")
            if "ip" in a:
                ET.SubElement(a_el, f"{{{_NS_IP}}}ip").text = a["ip"]
            cfg = a.get("config")
            if cfg is not None:
                cfg_el = ET.SubElement(a_el, f"{{{_NS_IP}}}config")
                if "ip" in cfg:
                    ET.SubElement(cfg_el, f"{{{_NS_IP}}}ip").text = cfg["ip"]
                if "prefix-length" in cfg:
                    ET.SubElement(
                        cfg_el, f"{{{_NS_IP}}}prefix-length"
                    ).text = str(cfg["prefix-length"])


# ---------------------------------------------------------------------------
# iter_xpaths — nested dict → schema xpath generator
# ---------------------------------------------------------------------------


#: Keys that are LIST-WRAPPER dicts (contain a single list under their
#: singular name).  When walking, we descend into each list element
#: without emitting the wrapper in the xpath.
_LIST_WRAPPERS = {
    "interfaces": "interface",
    "subinterfaces": "subinterface",
    "addresses": "address",
}


def _iface_dict_to_canonical(raw: dict[str, Any]) -> "CanonicalInterface":
    """Convert one parsed-interface dict into a :class:`CanonicalInterface`.

    The NETCONF parser builds a nested dict matching the OpenConfig
    tree shape; the canonical bridge needs a flat :class:`CanonicalInterface`.
    Lives here as a helper so the public ``parse()`` call remains a
    one-liner.
    """
    from ...canonical.intent import CanonicalIPv4Address, CanonicalInterface
    cfg = raw.get("config", {})
    iface = CanonicalInterface(
        name=raw.get("name", ""),
        description=cfg.get("description", ""),
        enabled=bool(cfg.get("enabled", True)),
        interface_type=cfg.get("type", ""),
    )
    subifs = raw.get("subinterfaces", {}).get("subinterface", [])
    for subif in subifs:
        ipv4 = subif.get("ipv4", {})
        addresses = ipv4.get("addresses", {}).get("address", [])
        for addr in addresses:
            addr_cfg = addr.get("config", {})
            ip = addr_cfg.get("ip") or addr.get("ip")
            prefix = addr_cfg.get("prefix-length")
            if ip is None or prefix is None:
                continue
            iface.ipv4_addresses.append(CanonicalIPv4Address(
                ip=ip,
                prefix_length=int(prefix),
            ))
    return iface


def _walk(node: Any, prefix: str) -> Iterable[str]:
    """Yield schema xpaths under *prefix*.

    OpenConfig schema paths contain no list-key predicates — matching
    what's declared in the capability matrix — so a list named
    ``/interfaces/interface/*`` yields a SINGLE path per leaf
    regardless of how many interfaces are present.  Callers that need
    occurrence counts get them via iteration order (e.g. three
    interfaces each with a description yield the same path 3 times).
    """
    if isinstance(node, dict):
        for key, val in node.items():
            child_path = f"{prefix}/{key}"
            if key in _LIST_WRAPPERS and isinstance(val, dict):
                # e.g. "interfaces": {"interface": [...]}
                inner_key = _LIST_WRAPPERS[key]
                items = val.get(inner_key, [])
                if not isinstance(items, list):
                    continue
                for item in items:
                    yield from _walk(item, child_path + f"/{inner_key}")
            elif isinstance(val, (dict, list)):
                yield from _walk(val, child_path)
            else:
                yield child_path
    elif isinstance(node, list):
        # Bare list (shouldn't happen under the canonical tree, but be
        # defensive for forward-compatibility).
        for item in node:
            yield from _walk(item, prefix)

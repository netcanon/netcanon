"""
FortiGate VLAN-naming heuristics — shared between parse and render.

FortiOS names VLAN subinterfaces a few different ways, and unlike
most other vendors the config syntax doesn't always commit to a
single signal:

* ``vlan<N>`` — factory-default naming (uncommon in production).
* ``<parent>.<N>`` — dotted form (``LAG_INTERNAL.100``,
  ``port1.10``) that encodes the parent + id in the name itself.
* User-named forms (``VL_100``, ``DATA``, ``GUEST_WIFI``) — name
  carries no structural hint; the VLAN id + parent interface are
  declared via ``set vlanid`` / ``set interface`` inside the
  ``config system interface`` edit block.

Because FortiOS is permissive, the render path has to detect VLAN
interfaces by BOTH canonical type (``ianaift:l3ipvlan``) AND
native-shape pattern, while the parse path has to accept configs
that declare the VLAN dimension via ``vlanid`` alone (no
``set type vlan`` line) — see the KevinGuenay/fortinet-resources
FGT-70G-BRANCH.conf real capture, where ``VL_100`` is unambiguously
a VLAN interface despite missing an explicit type.

Keeping the heuristics here (rather than inside the parser or
renderer) means both paths share one source of truth for "is this
a VLAN interface?" and "what's its VLAN id?" — matching the
port_names.py / _svi_absorption.py layout established for other
codecs.  Any future FortiGate parse/render split can then extract
``parse.py`` + ``render.py`` without having to cross-import
vlan-detection helpers.
"""

from __future__ import annotations

import re

from ...canonical.intent import CanonicalInterface, CanonicalVlan


# ---------------------------------------------------------------------------
# Regex patterns — module-level so they compile once per import
# ---------------------------------------------------------------------------

#: Factory-default VLAN naming: ``vlan100`` / ``VLAN10``.
_VLAN_NAME_RE = re.compile(r"^vlan(\d+)$", re.IGNORECASE)
#: Dotted form: ``<parent>.<id>`` (``port1.10``, ``LAG_INTERNAL.100``).
_DOTTED_VLAN_RE = re.compile(r"^([A-Za-z0-9_-]+)\.(\d+)$")
#: Ethernet-style names for ifType inference.
_ETHERNET_NAME_RE = re.compile(
    r"^(port|ethernet|internal|wan|lan|dmz)\d*$"
)


def looks_like_vlan_iface(name: str) -> bool:
    """Return True when *name* matches a FortiOS VLAN-interface form.

    Matches:
      * ``vlanN`` / ``VLANN`` — factory-default.
      * ``<parent>.<N>`` — dotted form.

    Does NOT match user-named VLAN interfaces (``VL_100``,
    ``DATA``).  Those rely on the ``set vlanid`` / ``set interface``
    parse-side signal instead; see
    :func:`_looks_like_vlan_from_settings` at the parser call site.
    """
    if _VLAN_NAME_RE.match(name):
        return True
    if _DOTTED_VLAN_RE.match(name):
        return True
    return False


def vlan_id_for(
    name: str, vlans: list[CanonicalVlan]
) -> int | None:
    """Resolve the VLAN id for an interface name.

    Checks (in order):
      1. ``vlan<N>`` naming — id is the numeric suffix.
      2. ``<parent>.<N>`` dotted form — id is after the dot.
      3. Canonical VLAN list — returns the matching
         :class:`CanonicalVlan` id if any entry's ``name`` equals
         *name* (covers user-named VLANs via the canonical tree's
         VLAN records).

    Returns None when no signal is available — caller should warn
    or suppress the ``set vlanid`` line in rendered output.
    """
    m1 = _VLAN_NAME_RE.match(name)
    if m1:
        return int(m1.group(1))
    m2 = _DOTTED_VLAN_RE.match(name)
    if m2:
        return int(m2.group(2))
    for v in vlans:
        if v.name == name:
            return v.id
    return None


def parent_for_vlan_iface(
    name: str, all_interfaces: list[CanonicalInterface],
) -> str | None:
    """Find the parent physical interface for a VLAN sub-interface.

    Resolution order:
      1. Dotted form — parent is the substring before the dot.
        Only returned if the parent actually exists in
        *all_interfaces* (guards against malformed configs where
        the dotted-form parent was deleted).
      2. Fallback — the first non-VLAN interface in *all_interfaces*.
        Imperfect but better than omitting the ``set interface``
        line; operator can correct post-deploy.

    Returns None when no parent candidate exists (degenerate tree
    with only VLAN interfaces — unusual but possible during
    cross-vendor translation from an L3-only source).
    """
    if "." in name:
        parent = name.split(".", 1)[0]
        if any(i.name == parent for i in all_interfaces):
            return parent
    for i in all_interfaces:
        if not looks_like_vlan_iface(i.name):
            return i.name
    return None


def infer_iface_type(name: str) -> str:
    """Map a FortiOS interface name to an IANA ifType string.

    Used by the parse path when the config doesn't explicitly
    declare an interface type — FortiOS omits ``set type`` on
    physical ports, so we infer from the name shape.

    Returns:
      * ``ianaift:ethernetCsmacd`` — for port / ethernet /
        internal / wan / lan / dmz names (covers all factory-
        default physical-port names across the FortiGate range).
      * ``ianaift:ieee8023adLag`` — for ``agg*`` / ``trunk*``.
      * ``ianaift:softwareLoopback`` — for ``loopback*``.
      * ``ianaift:tunnel`` — for ``tunnel*``.
      * ``ianaift:ethernetCsmacd`` — fallback (conservative default
        — user-named interfaces with no recognisable prefix are
        assumed ethernet rather than something exotic).
    """
    lower = name.lower()
    if _ETHERNET_NAME_RE.match(lower):
        return "ianaift:ethernetCsmacd"
    if lower.startswith("agg") or lower.startswith("trunk"):
        return "ianaift:ieee8023adLag"
    if lower.startswith("loopback"):
        return "ianaift:softwareLoopback"
    if lower.startswith("tunnel"):
        return "ianaift:tunnel"
    return "ianaift:ethernetCsmacd"

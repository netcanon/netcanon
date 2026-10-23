"""
Cross-vendor port-name translation — orchestration layer.

The canonical intent stores interface names verbatim from the source
vendor (``GigabitEthernet1/0/24`` from Cisco, ``1/24`` from Aruba,
``ether1`` from MikroTik, ``igb0`` from OPNsense, ``port1`` from
FortiGate).  Cross-vendor translation can't just pass those through
— they're vendor-specific encodings of physical topology.

This module defines the **vendor-agnostic bridge**:

1. :class:`PortIdentity` — a logical classification of a port name
   (kind + structural coordinates) with no vendor knowledge.
2. :func:`translate_port_names` — iterates over a :class:`CanonicalIntent`
   and rewrites every port-name field from source convention to target
   convention, using ONLY each codec's own ``classify_port_name`` /
   ``format_port_identity`` methods.  Never conditionals vendor pair.
3. :func:`collect_port_names` — the port names a canonical tree
   holds, in the places the sweep rewrites.  And
   :func:`collect_hardware_port_names`, the subset that is evidence
   of a hardware port.  A new canonical field that holds a port
   name is added to the first and to the sweep in the same change;
   ``tests/unit/migration/test_port_name_universe.py`` looks for
   one that was not, by sending port names to one another on the
   committed captures and comparing the two outputs parsed again.
4. :func:`route_port_reference` — a route's next hop that is the
   name of an interface, which follows that interface.
5. :func:`rewrite_port_names` — the sweep itself: every place a port
   name is kept, written through a resolver.  Used by the translator
   and by a parser that finds one port under two names.
6. :func:`key_by_the_configs_spelling` — on a platform whose names
   have no letter case, a rename-map key in another case is the name
   the config uses.  The rule exists once: the translator applies it,
   and so does ``run_plan_with_models`` before it merges an
   operator's entries with a pairing's.  Beside it,
   :func:`single_spellings` - the names a config writes exactly
   one way, which are the only ones another spelling can mean.
7. :func:`split_unit`, :data:`UNIT_PARENT_KINDS` and
   :data:`UNIT_MAX_DIGITS` — what the name of a sub-interface is (a
   name, and the number after its last dot), which kinds of port
   carry one, and how long a unit can be and still be sent after
   its port onto another vendor.  The translator sends
   such a name after its port, and ``run_plan_with_models`` reads
   back which ones went.
8. :class:`LoopbackToPlace` — a loopback of the source config, as a
   target that names its loopbacks as a set is given it
   (``CodecBase.place_loopbacks``).  Junos has one loopback
   interface, ``lo0``, and places a unit of it in each routing
   instance, so its name for a loopback depends on the config's
   other loopbacks, which no name formatted one at a time can know.

What the sweep does NOT rewrite is a port's FACTORY name
(``interfaces[].default_name``, RouterOS).  That field is the port's
hardware identity, not a reference to it: an entry of the rename map
gives a port a name, and the renderer then writes "find the port
with this factory name and call it that".  Whether an entry instead
MOVES the config onto other hardware can only be told from a
declared target device, so it is decided where one is declared
(:func:`~netcanon.services.migration_pipeline.run_plan_with_models`).

**Two names the classifier is never asked about.**  Between two
configs of ONE codec a name nobody mapped keeps its name: it is valid
there by construction, and a classify / format round trip is not the
identity on several codecs' own names (Junos reads ``ge-0/0/1.54``
and ``fxp0`` and writes ``ge-0/0/1`` and ``em0``; AOS-S, IOS-XE CLI,
OS10, FortiOS and VyOS each have names that do not come back).  And
a sub-interface
(``<port>.<unit>``) goes where its port goes, with its unit: no
classifier keeps the unit -- :class:`PortIdentity` has no place for one
-- so left to them it lands ON its port (Junos, VyOS) or stays behind
under its source name (IOS, EOS, NX-OS, IOS-XR).  Onto a target
whose sub-interface is named by its tag (VyOS ``vif``) it goes with
its tag instead.  See :func:`translate_port_names`.

**Modular boundary:** each codec knows ONLY its own vendor's naming
convention.  Cisco's codec classifies ``Gi1/0/24`` → ``PortIdentity``
but has no idea how to turn that into Aruba's ``1/24`` — that's
Aruba's ``format_port_identity`` method's job.  The orchestrator
below sits in the middle and never hard-codes a vendor name.

**Mesh-ready:** works for every (source, target) pair, including
pairs that haven't shipped yet.  Adding a new codec requires
implementing the two methods; zero edits here.
"""

from __future__ import annotations

import logging
import unicodedata
from collections import Counter
from collections.abc import Callable, Collection, Iterable, Iterator
from typing import TYPE_CHECKING, Literal, NamedTuple, TypeVar

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from ..codecs.base import CodecBase
    from .intent import CanonicalIntent, CanonicalStaticRoute

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


PortKind = Literal[
    "physical",     # real ethernet port (1 logical = 1 physical)
    "breakout",     # one lane of a broken-out QSFP (parent = 1 physical,
                    # child = 1 of N logical; source vendor specifies via
                    # PortIdentity.breakout_lane + breakout_parent)
    "hw_aggregate", # N physical ports unified into 1 logical (FortiGate
                    # internal/hard-switch, some Aruba ArubaStack).  N of
                    # member names in PortIdentity.aggregate_members.
    "lag",          # LAG / port-channel / trunk / bond (explicit config)
    "svi",          # VLAN SVI (L3 interface bound to a VLAN)
    "loopback",     # virtual loopback
    "tunnel",       # VPN / GRE / WireGuard / IPsec tunnel
    "vtep",         # VXLAN tunnel endpoint (NX-OS nve1, etc.) — most
                    # codecs have no native equivalent and return None
                    # from format_port_identity (verbatim + warning)
    "mgmt",         # out-of-band management port
    "virtual",      # an interface only its own vendor has (IOS-XE
                    # VirtualPortGroup, a RouterOS bridge): the
                    # identity carries its vendor's mark in meta, and
                    # only that vendor's formatter gives it a name --
                    # no other vendor has a form for it
    "unknown",      # codec couldn't classify — leave verbatim
]


AggregateKind = Literal[
    "hardware-switch",  # L2 switched in silicon (FortiGate `internal`)
    "soft-switch",      # software aggregation
    "vsf-stack",        # Aruba VSF stack member grouping
    "",                 # not an aggregate
]


class PortIdentity(BaseModel):
    """Vendor-agnostic logical identity of a port name.

    Produced by ``CodecBase.classify_port_name(name)`` on the source
    side and consumed by ``CodecBase.format_port_identity(ident)`` on
    the target side.  Neither codec sees the other's name format —
    they both only know how to talk to this shape.

    Fields are deliberately permissive (all optional) because not
    every vendor encodes every concept.  Aruba's ``1/A24`` uses
    ``stack`` + ``subslot_letter`` + ``port`` but no ``module``.
    Cisco's ``Gi1/0/24`` uses ``stack`` + ``module`` + ``port`` but
    no ``subslot_letter``.  MikroTik's ``ether1`` uses just ``port``
    (no stack, no module).  OPNsense's ``igb0`` uses just ``port``
    too (the BSD unit number).  FortiGate's ``port1`` uses just
    ``port``.  When fields are irrelevant for a vendor, they stay
    ``None``/``""`` and the target's formatter ignores them.
    """

    #: Logical role of this port.  Drives the target formatter's
    #: top-level branching.
    kind: PortKind = "unknown"

    #: Stack member (1..N) for stacked switches.  ``None`` if the
    #: vendor doesn't encode stack membership in the port name
    #: (MikroTik, OPNsense, FortiGate) or the device is standalone.
    stack: int | None = None

    #: Slot / sub-module / line-card index.  Cisco uses this as the
    #: middle digit in ``<member>/<module>/<port>``.  Aruba uses the
    #: ``subslot_letter`` field instead.  MikroTik / OPNsense /
    #: FortiGate don't encode modules in names.
    module: int | None = None

    #: Terminal port number on the line card / stack member / device.
    port: int | None = None

    #: Aruba AOS-S uplink-module letter prefix (``A1``, ``B1``, ``C1``).
    #: Empty string when not applicable.
    subslot_letter: str = ""

    #: Bandwidth hint derived from the **port NAME** (Cisco
    #: ``GigabitEthernet`` prefix, MikroTik ``sfp-sfpplus`` vs ``ether``).
    #: This is the speed the NAMING convention implies, NOT the port's
    #: operational speed — a Cisco ``GigabitEthernet1/0/24`` mGig port
    #: can run at 2.5G/5G/10G despite the name, and the name stays
    #: ``GigabitEthernet`` regardless.  Kept for render-side prefix
    #: selection (so a ``10gig`` source maps to ``TenGigabitEthernet``
    #: on Cisco targets even when the same identity came from
    #: ``sfp-sfpplus1`` on MikroTik).  Empty when the source doesn't
    #: encode speed in the name.  Canonical values: ``"fast"``, ``"gig"``,
    #: ``"2.5gig"``, ``"5gig"``, ``"10gig"``, ``"25gig"``, ``"40gig"``,
    #: ``"100gig"``, ``"400gig"``.
    name_speed_hint: str = ""

    #: Actual operational / configured speed if the parser extracted
    #: it from explicit ``speed`` config lines.  Distinct from
    #: ``name_speed_hint`` because they can disagree (Cisco mGig).
    #: Empty in v1 — parsers don't populate yet; hook reserved for a
    #: future enrichment pass.  Target formatters MAY consult this in
    #: future to pick the right name prefix when the source name's
    #: implied speed doesn't match the actual speed.
    operational_speed: str = ""

    #: Integer index for ``kind`` in {``lag``, ``svi``, ``loopback``,
    #: ``tunnel``, ``virtual``}.  For LAGs this is the
    #: ``Port-channel<N>`` / ``Trk<N>`` / ``bond<N>`` number; for SVIs
    #: the VLAN id; for loopbacks the loopback number; for tunnels the
    #: tunnel id.  ``None`` otherwise.
    index: int | None = None

    # ---- Breakout (1 physical → N logical) ----

    #: For ``kind="breakout"`` child ports: which lane (1..N) of the
    #: QSFP breakout this interface represents.  Cisco 4-part notation
    #: ``TenGigabitEthernet1/1/1/1`` puts this in the 4th digit.
    breakout_lane: int | None = None

    #: For ``kind="breakout"`` child ports: the parent QSFP name
    #: (``FortyGigabitEthernet1/1/1``).  Used by target formatters that
    #: need to check "does my target also support breakout?" and
    #: fall back accordingly.
    breakout_parent: str = ""

    # ---- Aggregate (N physical → 1 logical) ----

    #: Distinguishes true L2/L3 aggregation (``kind="hw_aggregate"``)
    #: from a plain LAG (``kind="lag"``).  FortiGate's ``internal``
    #: interface is ``hardware-switch``; OPNsense/Aruba LAGs are
    #: ``""`` (not an aggregate — just a LAG).
    aggregate_kind: AggregateKind = ""

    #: For ``kind="hw_aggregate"`` / ``kind="lag"``: member physical
    #: interface names that make up this logical port.  Usually
    #: sparsely populated — the caller's rename pass works on the
    #: canonical tree's ``lags[].members`` list directly.  Kept here
    #: so future 1:N expansion passes (hardware-aware mode) have the
    #: membership info without re-parsing.
    aggregate_members: list[str] = Field(default_factory=list)

    #: Source-side advisory flag: this PHYSICAL port is a member of a
    #: hardware-switch L2 fabric on the source device.  FortiGate
    #: ``internalN`` / ``lanN`` on small appliances (40F/60F/80F) are
    #: switched ports of the ``internal`` / ``lan`` fabric, NOT
    #: standalone routed ports — the bare ``internal`` / ``lan`` form
    #: classifies as ``hw_aggregate`` (and warns), but the numbered
    #: member historically classified as plain ``physical`` and was
    #: remapped to a positional target name with no advisory at all.
    #: The cross-vendor name mapping is purely positional (name-shape)
    #: and cannot carry the L2-switch membership, so the orchestrator
    #: surfaces a soft "verify cabling / L2 role" advisory when source
    #: and target vendors differ.  ``kind`` STAYS ``physical`` (the
    #: port IS a real port) — this flag only drives the advisory, never
    #: the rename or drop.  Vendor-agnostic: any codec whose classifier
    #: can detect hw-switch membership may set it; today only FortiGate
    #: does.  Between two configs of one codec the name stands, so no
    #: advisory.
    hw_switch_member: bool = False

    #: Verbatim source name — used as fallback when the target codec
    #: can't format this identity (``format_port_identity`` returns
    #: ``None``).  Always populated by the source classifier.
    original: str = ""

    #: Free-form vendor-advisory hints.  Useful when a vendor has
    #: naming concepts that don't fit the structured fields — e.g.
    #: FortiGate's role-based names ``wan1`` / ``lan2`` stash
    #: ``{"role": "wan"}`` here.  Target codecs may consult this to
    #: pick better defaults but must not depend on it.
    meta: dict[str, str] = Field(default_factory=dict)


class LoopbackToPlace(NamedTuple):
    """A loopback of the source config, given to a target that places
    loopbacks as a set (``CodecBase.place_loopbacks``)."""

    #: The name the source config gives it.
    name: str
    #: Its number, as the source codec's classifier reads it
    #: (``Loopback7`` and a Junos ``lo0.7`` are 7), or ``None`` where
    #: its name has none.
    number: int | None
    #: The routing instance it is in; ``""`` for the global table.
    instance: str


class PortRenameResult(BaseModel):
    """Outcome of :func:`translate_port_names`.

    Returned so the UI / API can surface exactly what was rewritten
    and what was left verbatim (with a reason).
    """

    applied: dict[str, str] = Field(default_factory=dict)
    """Map of source_name → target_name for every rewrite that happened.
    Names that already match, or that fell through verbatim, are NOT in
    this map — it only captures actual changes.
    """

    warnings: list[str] = Field(default_factory=list)
    """Per-name advisories.  One line per affected port, describing
    why the name couldn't be auto-translated (unknown kind, no target
    equivalent, etc.).  Safe to concatenate into a UI panel.
    """

    dropped: list[str] = Field(default_factory=list)
    """Source names the operator explicitly marked "don't render".
    Entries in the :func:`translate_port_names` ``rename_map``
    parameter with ``None`` value signal a drop — the orchestrator
    removes every reference to that name from the canonical tree
    (interface stanzas, VLAN port lists, LAG members, static-route
    interface fields, DHCP pool interface).  The rendered output
    simply does not contain the dropped interface.  Used by the
    Tier 3 rename modal when the operator decides a source
    interface has no target representation and should be stripped
    rather than mapped (e.g. Cisco ``AppGigabitEthernet1/0/1``
    app-hosting bridge, loopbacks where the target has no loopback
    concept, unused physical ports)."""

    untranslated: list[str] = Field(default_factory=list)
    """Source names that are still in the tree under the name the
    source config has for them because the translator had no name to
    give them, in the order they were met.  Across vendors only: a
    name the source codec's classifier could not read as any kind of
    interface (the "could not classify ... left verbatim" warning),
    and -- with ``strip_unmappable=False`` -- a name the target has
    no form for, which is otherwise dropped and listed in
    :attr:`dropped`.

    Said as data because a warning line is not something a caller
    can act on: such a name is a source vendor's name written into
    another vendor's config, and nobody decided that.  So a name is
    never here by a decision or by a rule: not one an entry of the
    map names (to another name, to ITSELF -- which is how an operator
    says the name is right on the target -- or with ``None``), not a
    name between two configs of one codec (it stands there, valid by
    construction), and not a VLAN interface a target writes from its
    VLAN stanza.

    These are names the config CONFIGURES something under: an
    interface, a LAG, a member of a LAG, a port in a VLAN's lists.
    One it only refers to is in :attr:`untranslated_references`.

    Every such name is here, whether or not it happens to be a
    good name on the target as it stands: that is not the
    translator's to judge.  The entry that reads the finished run
    (:func:`~netcanon.services.migration_pipeline.run_plan_with_checked_names`)
    decides which of them hold a job."""

    untranslated_references: list[str] = Field(default_factory=list)
    """As :attr:`untranslated`, for a name the tree holds only where
    it REFERS to an interface: a static route's or a DHCP pool's
    interface, a VRRP track entry, a VXLAN source.  What those
    places hold is not always an interface -- a route to ``Null0``
    or to the keyword ``dhcp``, a pool keyed by a zone name, a track
    object number, a source ADDRESS -- and nothing says such a name
    is one: the classifier, which alone could, did not read it.
    Kept apart so that a caller can hold a job for a port left under
    another vendor's name without holding one for every route to
    ``Null0``."""


# ---------------------------------------------------------------------------
# Where port names live in a canonical tree
# ---------------------------------------------------------------------------

#: Canonical interface types that are not hardware ports.  An SVI, a
#: LAG, a loopback, a bridge or a tunnel is a real NAME in a config and
#: is rewritten like any other, but it is not a port a device model
#: lists.
NON_HARDWARE_INTERFACE_TYPES: frozenset[str] = frozenset({
    "ianaift:l3ipvlan",
    "ianaift:l2vlan",
    "ianaift:ieee8023adLag",
    "ianaift:softwareLoopback",
    "ianaift:bridge",
    "ianaift:tunnel",
})

#: Kinds a codec's classifier gives only to a name that is not a
#: hardware port.  ``unknown`` is deliberately absent: it is what a
#: classifier returns for a name it does not recognise, and on AOS-S
#: that includes a real uplink named ``A1``.
NON_HARDWARE_PORT_KINDS: frozenset[str] = frozenset({
    "lag", "svi", "loopback", "tunnel", "vtep", "virtual",
    "hw_aggregate",
})

#: Kinds a classifier gives to a name it recognises AS a hardware
#: port.  With :data:`NON_HARDWARE_PORT_KINDS` and ``unknown`` this
#: is every :data:`PortKind`.
HARDWARE_PORT_KINDS: frozenset[str] = frozenset({
    "physical", "breakout", "mgmt",
})


def _swept_names(intent: CanonicalIntent) -> Iterator[str]:
    """The port names in the places the rename sweep rewrites, in the
    order the sweep visits them, one per value it resolves."""
    for iface in intent.interfaces:
        yield iface.name
        if iface.lag_member_of:
            yield iface.lag_member_of
        if iface.vlan_parent:
            yield iface.vlan_parent
        # VRRP track-interface references are port names too.
        for grp in iface.vrrp_groups:
            yield from grp.track_interfaces
    for vlan in intent.vlans:
        yield from vlan.tagged_ports
        yield from vlan.untagged_ports
    for lag in intent.lags:
        yield lag.name
        yield from lag.members
    for route in intent.static_routes:
        if route.interface:
            yield route.interface
    for pool in intent.dhcp_servers:
        if pool.interface:
            yield pool.interface
    # A VXLAN VTEP source-interface is a port name (Loopback0 / lo0.0).
    for vx in intent.vxlan_vnis:
        if vx.source_interface:
            yield vx.source_interface


def _only_referred_to(intent: CanonicalIntent) -> set[str]:
    """The names *intent* holds only where it REFERS to an interface:
    a static route's or a DHCP pool's interface, a VRRP track entry,
    a VXLAN source, the parent a VLAN interface rides on -- and in no
    other place the sweep visits.

    Counted, not listed from the other side: a name is one of these
    when every place :func:`_swept_names` finds it is one of those
    named here.  So a field added to the sweep later counts as a
    place the config CONFIGURES a name, until this function is told
    otherwise -- the reading that reports more, not less."""
    referred: Counter[str] = Counter()
    for iface in intent.interfaces:
        for grp in iface.vrrp_groups:
            referred.update(grp.track_interfaces)
        if iface.vlan_parent:
            referred[iface.vlan_parent] += 1
    referred.update(r.interface for r in intent.static_routes if r.interface)
    referred.update(p.interface for p in intent.dhcp_servers if p.interface)
    referred.update(v.source_interface for v in intent.vxlan_vnis if v.source_interface)
    swept = Counter(_swept_names(intent))
    return {name for name, times in referred.items() if swept[name] == times}


def rewrite_port_names(
    intent: CanonicalIntent, resolve: Callable[[str], str], *, units: bool,
) -> None:
    """Give every port name *intent* holds the name *resolve* returns
    for it, in place.

    This is the sweep: the places :func:`_swept_names` yields, and a
    route's next hop where it names an interface
    (:func:`route_port_reference`).  It is the one list of those
    places that is written to, so that a caller that has to rename a
    port everywhere -- the translator, and a parser that finds one
    port written under two names -- cannot be a field short of the
    other.

    A port's factory name (``interfaces[].default_name``) is not
    touched: it says which hardware the port is, not what the config
    calls it.

    Args:
        intent: The tree, changed in place.
        resolve: Old name to new name.  Called once per reference;
            return the name itself to leave it.
        units: A next hop with a unit suffix (``et-0/0/24.0``) follows
            its interface too.  True only between two configs of one
            codec, where a unit means the same thing on both sides.
    """
    # Interface names as the config wrote them: a route's next hop can
    # name one (see route_port_reference).
    named_before = {iface.name for iface in intent.interfaces}
    for iface in intent.interfaces:
        iface.name = resolve(iface.name)
        if iface.lag_member_of:
            iface.lag_member_of = resolve(iface.lag_member_of)
        if iface.vlan_parent:
            iface.vlan_parent = resolve(iface.vlan_parent)
        # (#3) Rewrite each VRRP group's track-interface list so failover
        # tracking survives a rename (a stale name silently disables it).
        for grp in iface.vrrp_groups:
            grp.track_interfaces = [resolve(t) for t in grp.track_interfaces]
    for vlan in intent.vlans:
        vlan.tagged_ports = [resolve(p) for p in vlan.tagged_ports]
        vlan.untagged_ports = [resolve(p) for p in vlan.untagged_ports]
    for lag in intent.lags:
        lag.name = resolve(lag.name)
        lag.members = [resolve(m) for m in lag.members]
    for route in intent.static_routes:
        if route.interface:
            route.interface = resolve(route.interface)
        # A next hop that is an interface follows the interface.
        reference = route_port_reference(route, named_before, units=units)
        if reference is not None:
            route.gateway = resolve(reference[0]) + reference[1]
    for pool in intent.dhcp_servers:
        if pool.interface:
            pool.interface = resolve(pool.interface)
    # (#3) Rewrite the VXLAN VTEP source-interface so the binding stays valid
    # on the target (a stale source name breaks the whole VTEP).
    for vx in intent.vxlan_vnis:
        if vx.source_interface:
            vx.source_interface = resolve(vx.source_interface)


def collect_port_names(intent: CanonicalIntent) -> list[str]:
    """Every port name *intent* holds, in first-seen order: the
    names in the places :func:`translate_port_names` rewrites
    (:func:`_swept_names`).

    These are the names the CONFIG uses.  A port's factory name
    (``interfaces[].default_name``) is not one of them where an
    operator gave the port a name of their own: nothing in the config
    refers to the port by it, and an entry of a rename map keyed by
    it matches nothing.

    A route's ``gateway`` can hold an interface name too (RouterOS
    ``gateway=ether1``, Junos ``next-hop et-0/0/24.0``).  It adds no
    name to this list — it counts only when it is the name of an
    interface the tree already has — but the sweep rewrites it and a
    drop takes the route; see :func:`route_port_reference`.

    A new canonical field that holds a port name belongs here and in
    the sweep, in the same change.  Reading two functions side by
    side proves they agree with each other, not that they are
    complete: ``tests/unit/migration/test_port_name_universe.py``
    sends port names to one another through the translator on the
    committed captures and fails for a value of the re-parsed output
    that did not follow, where a capture fills the field.

    Returns:
        Names without duplicates.  Includes LAG, SVI and loopback
        names; see :func:`collect_hardware_port_names` for the subset
        a device model can account for.
    """
    seen: dict[str, None] = {}
    for name in _swept_names(intent):
        if name:
            seen.setdefault(name, None)
    return list(seen)


def route_port_reference(
    route: CanonicalStaticRoute,
    interface_names: Collection[str],
    units: bool = True,
) -> tuple[str, str] | None:
    """The interface a route's ``gateway`` names, when it names one.

    Some parsers keep a next hop that is an interface, not an
    address, in ``gateway``: RouterOS ``gateway=ether1``, Junos
    ``next-hop et-0/0/24.0``.  Such a route follows its interface
    when the interface is renamed and goes with it when it is
    dropped, exactly as a route bound through ``interface`` does.

    A gateway counts as an interface reference only when it is
    exactly the name of an interface of the tree, or (with *units*)
    such a name followed by a numeric unit — never by its shape, so
    an address is never taken for a port.

    Args:
        route: The route.
        interface_names: The names of the tree's interfaces.
        units: Also accept ``<name>.<unit>``.

    Returns:
        ``(interface name, unit suffix)`` — the suffix is ``".0"``
        style or ``""`` — or ``None``.
    """
    gateway = route.gateway
    if not gateway:
        return None
    if gateway in interface_names:
        return gateway, ""
    if units:
        port, dot, unit = gateway.rpartition(".")
        if dot and unit.isdigit() and port in interface_names:
            return port, dot + unit
    return None


def collect_hardware_port_names(
    intent: CanonicalIntent,
    classify: Callable[[str], PortIdentity] | None = None,
    always: Iterable[str] = (),
    fold: bool = True,
) -> list[str]:
    """The hardware ports *intent* references, in first-seen order.

    **Evidence and reference.**  A running-config names a port in an
    interface stanza only when the port carries non-default config; an
    unconfigured access port appears solely in a VLAN's membership
    list, and a LAG member solely under the LAG.  Each of those three
    is EVIDENCE that the device has a port of that name.

    A static route's or a DHCP pool's interface, a VRRP track entry and
    a VTEP source are REFERENCES.  The rename sweep rewrites them, so a
    real port named only there must be part of any mapping — but what
    those fields hold is not always an interface: a route to ``Null0``
    or to the keyword ``dhcp``, a pool keyed by a zone name, a track
    OBJECT number, a VTEP source address.  A reference therefore counts
    only when something says it is a port: the declared inventory lists
    it (*always*), or *classify* positively calls it a hardware kind.

    What is taken away from the evidence:

    * an interface whose canonical ``interface_type`` says SVI, LAG,
      loopback, bridge or tunnel;
    * a LAG's own name, and the name an interface gives as its
      ``lag_member_of``.  LAG names also arrive through VLAN
      membership, in either case (AOS-S prints both ``Trk1`` and
      ``trk1``), so they are subtracted after the union — compared
      as the platform compares names (*fold*): where an operator's
      names are kept apart by case, a port called ``BOND1`` is not
      the LAG ``bond1``;
    * when *classify* is given, a name it POSITIVELY calls one of
      :data:`NON_HARDWARE_PORT_KINDS`.  Several codecs never set
      ``interface_type`` (OPNsense, VyOS) or type everything that is
      not a LAG or a VLAN interface as Ethernet (FortiGate), and for
      those the classifier is the only thing that knows ``lo0`` or
      ``ssl.root`` is not a port.

    ``unknown`` is never grounds for leaving EVIDENCE out: on AOS-S the
    classifier returns it both for the synthesised SVI name ``Vlan2``
    and for a real uplink named ``A1``.  What a classifier does not
    recognise, and no type marks, is still returned — a sub-interface
    (``GigabitEthernet1/0/1.100``) and some firewall pseudo-interfaces
    are.  A classifier that raises on a name is treated as not
    recognising it: reading a config's port names must not be able to
    fail a job.

    **A port with two names.**  RouterOS keeps a port's factory name
    (``ether2``) beside the name an operator gave it (``core-a``).
    This function returns the name the CONFIG uses (``core-a``): it
    is the one every other line refers to, and the key an entry of a
    rename map has to carry.  A caller that pairs ports with a device
    model looks such a port up in the model by its factory name
    (``interfaces[].default_name``); see
    :func:`~netcanon.services.migration_pipeline.run_plan_with_models`.

    This is the set a positional mapping is made FOR.  It is not the
    set a finished run is checked over: the sweep rewrites every name
    in :func:`collect_port_names`, logical ones included, and the
    check for two names on one target has to look at all of them.

    Args:
        intent: The parsed source tree.
        classify: The SOURCE codec's ``classify_port_name``.
        always: Names that count whatever *classify* says — the ports
            of a declared source inventory.  A classifier that misread
            a real port must not be able to take it out of the set a
            mapping is made for.  (The type and LAG-name tests above
            still apply to it.)
        fold: Names of the source platform compare without regard to
            case (``not codec.port_names_case_sensitive``).
    """
    def key(name: str) -> str:
        return name.lower() if fold else name

    not_hardware: set[str] = {
        iface.name for iface in intent.interfaces
        if iface.interface_type in NON_HARDWARE_INTERFACE_TYPES
    }
    lag_names = {key(lag.name) for lag in intent.lags if lag.name}
    lag_names.update(
        key(iface.lag_member_of) for iface in intent.interfaces
        if iface.lag_member_of
    )
    evidenced: set[str] = {iface.name for iface in intent.interfaces if iface.name}
    for vlan in intent.vlans:
        evidenced.update(vlan.tagged_ports)
        evidenced.update(vlan.untagged_ports)
    for lag in intent.lags:
        evidenced.update(lag.members)
    keep = set(always)

    def kind_of(name: str) -> str:
        if classify is None:
            return "unknown"
        try:
            identity = classify(name)
        except Exception:
            # One of the per-vendor classifiers, on an arbitrary
            # string from a pasted config.  "Could not read it" is what
            # ``unknown`` already means.
            return "unknown"
        return identity.kind if identity is not None else "unknown"

    names: list[str] = []
    for name in collect_port_names(intent):
        if name in not_hardware or key(name) in lag_names:
            continue
        if name not in keep:
            kind = kind_of(name)
            if kind in NON_HARDWARE_PORT_KINDS:
                continue
            if name not in evidenced and kind not in HARDWARE_PORT_KINDS:
                continue
        names.append(name)
    return names


# ---------------------------------------------------------------------------
# Orchestrator — vendor-agnostic cross-vendor rewrite
# ---------------------------------------------------------------------------


#: Kinds of port that carry sub-interfaces: a physical port, one lane
#: of a breakout, an aggregate.  A unit of a loopback or of a
#: management port is not a sub-interface of anything another platform
#: has, and across vendors is left to the classifier.  The kind is the
#: port's own: what its parser read of it from context
#: (``CanonicalInterface.kind``) before what its name reads as.
UNIT_PARENT_KINDS: frozenset[str] = frozenset({"physical", "breakout", "lag"})


#: The most digits of a unit that is sent after its port ACROSS
#: VENDORS: as many as a 32-bit number has, and no grammar read here
#: numbers a sub-interface past that.  A name that ends in a longer
#: run of digits is no sub-interface another platform has, and is
#: left to the classifier.  The bound is what keeps such a name out
#: of another vendor's renderer: sent after its port it arrives as
#: ``<port>.<digits>``, which FortiOS and VyOS make a VLAN id of
#: where the tree holds no tag for it, and a pasted config can write
#: more digits than an integer is converted from.  Between two configs of one codec there is no
#: bound: the name is the same on both sides, and its own renderer
#: is handed nothing it was not handed already.
UNIT_MAX_DIGITS = 10


def split_unit(name: str) -> tuple[str, str] | None:
    """``("ge-0/0/1", "54")`` for ``ge-0/0/1.54``: a name and the
    numeric unit after its last dot.  ``None`` for any other name --
    ``ether1.backup`` is a name with a dot in it, not a unit of
    ``ether1``.  The unit is given as it is written: a caller that
    asks anything of it reads it as text."""
    port, dot, unit = name.rpartition(".")
    if dot and port and unit.isascii() and unit.isdigit():
        return port, unit
    return None


def stated_sub_interfaces(intent: CanonicalIntent) -> dict[str, tuple[str, int]]:
    """Sub-interfaces whose config states the port they ride on apart
    from their name: ``{name: (port, unit)}``.

    RouterOS ``/interface vlan add interface=ether3 name=gn-mgmt
    vlan-id=11`` is one: an operator's own name, which says nothing of
    a unit, on the port its line names.  A parser states a port so,
    with a tag, only for a VLAN interface whose parent is a port or a
    LAG; one on a bridge or a switch interface stays a VLAN interface,
    typed as one, and is not here.  The translator sends each after
    its port, named by a unit that is its tag (:func:`translate_port_names`),
    and the model path reads which went so from the same rule
    (``_units_that_followed``).  The unit of one that matches two tags
    is its INNER tag: its outer tag is the tag of the sub-interface it
    rides on (RouterOS ``add interface=<that one>``), named by that
    tag on the same port."""
    return {
        iface.name: (
            iface.vlan_parent,
            iface.dot1q_vlan if iface.dot1q_inner_vlan is None else iface.dot1q_inner_vlan,
        )
        for iface in intent.interfaces
        if iface.dot1q_vlan is not None and iface.vlan_parent
        and iface.vlan_parent != iface.name
        and iface.interface_type not in ("ianaift:l3ipvlan", "ianaift:l2vlan")
    }


def _is_drawn(char: str) -> bool:
    """*char* is neither white space nor a control or format
    character (Unicode ``Cc`` and ``Cf``: a NUL, a zero-width space,
    a byte-order mark, a word joiner)."""
    return not char.isspace() and unicodedata.category(char) not in ("Cc", "Cf")


def names_a_target(value: object) -> bool:
    """*value* is something an entry of a port map may say: a target
    name, or ``None`` for a port that is to go.  A blank string is
    neither -- and blank is a string that DRAWS nothing: an empty
    one, one of white space, and one made only of control or format
    characters.  ``"\\u200b"`` is not empty and not white space, and
    taken as a name it wrote an interface whose name nobody can see.
    A name has at least one character that is none of those
    (:func:`_is_drawn`).  The rule exists once, here: the
    translator sets such an entry aside, the request model refuses
    it, and a caller that asks whether an entry DECIDED a name asks
    this."""
    return value is None or (isinstance(value, str) and any(map(_is_drawn, value)))


def single_spellings(names: Iterable[str]) -> dict[str, str]:
    """Folded name -> its spelling, for each name written exactly one
    way among *names*.  A name written in two letter cases is left
    out: nothing can say which of the two a third spelling means."""
    spelt: dict[str, set[str]] = {}
    for name in names:
        spelt.setdefault(name.casefold(), set()).add(name)
    return {fold: next(iter(found)) for fold, found in spelt.items() if len(found) == 1}


def key_by_the_configs_spelling(entries: dict[str, _T], names: Iterable[str]) -> None:
    """Re-key, in place, an entry whose key is another letter case of
    a name the config uses.

    For a source platform whose port names have no letter case
    (``port_names_case_sensitive`` is false): an operator who writes
    ``Trk1`` means the port the config calls ``trk1``, and the entry
    goes to that name.  Only where it cannot be read two ways -- the
    config writes the name exactly one way, and that spelling has no
    entry of its own.  An entry is never guessed between two names,
    nor laid over one written exactly.  Of two keys that are spellings
    of one name the first is taken; the other stays as typed, and
    whoever applies the map reports it.

    The rule exists once, here.  The translator applies it to the map
    it is given.  ``run_plan_with_models`` applies it to the
    operator's entries BEFORE merging them with the pairing's own:
    merged first, the pairing's entry for a port is "an entry of its
    own", and the operator's is the one set aside.

    Args:
        entries: Keyed by port name; re-keyed in place.
        names: Every name the config uses.
    """
    one_way = single_spellings(names)
    for key in list(entries):
        name = one_way.get(key.casefold()) if isinstance(key, str) else None
        if name is not None and name not in entries:
            entries[name] = entries.pop(key)


def translate_port_names(  # noqa: C901
    intent: CanonicalIntent,
    source_codec: CodecBase,
    target_codec: CodecBase,
    rename_map: dict[str, str | None] | None = None,
    strip_unmappable: bool = True,
) -> PortRenameResult:
    """Rewrite every port-name reference in *intent* from source-vendor
    convention to target-vendor convention.

    A key of *rename_map* is the name the config uses for the port.
    Where the source platform's names have no letter case, a key in
    another letter case is taken for that name
    (:func:`key_by_the_configs_spelling`): only when the config writes
    the name one way and that spelling has no entry of its own.  A
    key that is a second spelling of a name with an entry is reported
    and ignored, unless the two entries say the same thing.  A value
    is a target name or ``None``: an entry whose target is blank is
    set aside with a warning (:func:`names_a_target`), and the name
    is treated as one with no entry.

    Priority for each name:
        1. If *rename_map* contains an entry for the source name with
           a ``None`` value: the entry is DROPPED from the canonical
           tree (no rename, no warning — the interface disappears
           from the rendered output entirely).  Used when an operator
           decides a source interface has no target representation
           and should be stripped rather than mapped.
        2. If *rename_map* contains an entry with a string value, use
           that as the target name verbatim.  (Tier 2 hybrid: user
           override wins over auto.)
        3. Else, a sub-interface goes where its port goes, with its
           unit: ``<port>.<unit>`` becomes ``<what the port became>.<unit>``,
           and is dropped (and listed in ``dropped``) where the port is
           dropped.  A name counts as a unit of ``<port>`` when the
           source classifier does not read the dotted name as a thing
           of its own -- it calls it ``unknown``, or gives it the kind
           it gives the port, which is the unit thrown away -- and

             * between two configs of one codec: the operator's map
               moved or dropped the port (otherwise rule 4 applies and
               the name stands);
             * across vendors: the name is an interface of the tree,
               one the source parser did not type as a VLAN interface
               (FortiOS names those freely), and the port is a physical
               port, a breakout lane or a LAG
               (:data:`UNIT_PARENT_KINDS`) -- by what the port IS:
               one its parser marked as the management port from
               context (the IOS-XE ``Mgmt-vrf`` port, whose name
               reads as any other port's) carries none.  A unit
               named only as a reference (Junos ``lo0.0``,
               ``ge-0/0/1.0``) is left to the classifier, which
               folds it onto its port -- right for a unit 0, which
               is the interface itself everywhere else.  So is an
               INTERFACE numbered 0 (``.0``, or ``.00``) that
               carries no tag: sent after its port it would be
               written as that port's own unit 0 on Junos, two
               interfaces in one.  An interface numbered 0 that
               carries a tag is no port's own -- a Junos unit 0
               with a ``vlan-id`` under ``vlan-tagging``, or a
               hand-written ``interface Gi0/0/1.0`` -- and goes
               after its port NAMED BY ITS TAG on every target:
               ``ge-0/0/1.0`` tagged 54 is ``Ethernet1.54``, as
               nowhere else is ``.0`` a sub-interface.

           Across vendors a unit is a number of at most ten
           digits (:data:`UNIT_MAX_DIGITS`).  A name that ends in a
           longer run of digits is left to the classifier like any
           name it does not know.  Between two configs of one codec
           it follows an entry for its port whatever its length:
           the name is the same on both sides.

           The port need have no line of its own.  An entry for a
           port the config names only through a unit of it (a pasted
           ``interface Gi0/0/1.54`` with no stanza for the port) moves
           or drops that unit, and is not reported as naming a port
           the config does not have.

           Where the source platform's names have no letter case, a
           unit spelt in another case than its port (``interface
           gigabitethernet0/0/1.54`` under ``interface
           GigabitEthernet0/0/1``) is a unit of that port: the part
           before the unit is read as the config spells that name
           -- or, for a port the config does not name, as a key of
           the map does -- where exactly one does.

           The rule is for one level, ``<port>.<unit>``.  A unit of
           a unit (``ge-0/0/1.54.2``, which no running-config
           prints) is read as a unit of the dotted name before its
           last dot, and nothing is promised about where it ends.

           The unit's 802.1Q tag is not in its name: it travels in
           the tree (``dot1q_vlan``).  Across vendors, a unit that
           went with its port and has no tag there is written
           without one, and a warning says so.  Onto a target
           whose sub-interface is NAMED by its tag
           (``CodecBase.units_are_named_by_their_tag``: VyOS, where
           ``eth1.200`` is ``vif 200`` and carries VLAN 200), a
           unit with a tag goes as ``<what the port became>.<tag>``:
           with its unit number it carried that number as its VLAN.
           Two units of one port with one tag are then one name,
           which is what the device allows, and the plan path
           reports them as two ports on one name.  The tree has none
           where the platform's parser reads none for a
           sub-interface (AOS-CX, OS10) and where the config states
           none.

           What the target makes of ``<its port>.<unit>`` is the
           target's renderer's business; where it has no tagged
           sub-interface its capability matrix says so and the job is
           ``partial``.
        4. Else, between two configs of ONE codec, the name stands.
           It is a valid name there by construction, and nothing but a
           declared device could justify another.
        5. Else run ``source_codec.classify_port_name(name)`` →
           ``target_codec.format_port_identity(ident)`` and use the
           target's native formatting.  A name the classifier does
           not know stays as it is, with a warning, and the result
           says so as data: ``untranslated`` where the config
           configures something under the name, and
           ``untranslated_references`` where it only refers to it.
        6. If the auto-path returns ``None`` (target has no equivalent
           for this kind — e.g. Aruba AOS-S can't express
           ``Loopback0``) the behaviour depends on *strip_unmappable*:

             * ``True`` (default) — the source name is AUTO-DROPPED
               from the canonical tree alongside the warning.  This
               produces clean target output (no garbage
               source-vendor names leaking into the render) and
               matches the operator's typical intent when cross-
               vendor translating.  Operators who want to keep the
               name verbatim anyway can add ``{name: name}`` to
               *rename_map* (a no-op rename beats the auto-drop) or
               use the Tier 3 UI's "keep verbatim" affordance.
             * ``False`` — name stays verbatim in the canonical
               tree, warning fires.  Used by tests or API callers
               that want to inspect what the auto-heuristic
               couldn't resolve without the rename sweep silently
               deleting data.

        SVI + target-absorbs-SVI is a special case that short-
        circuits before (6): no warning, no drop, name stays verbatim
        (target's VLAN-stanza render path handles the L3 data).

    Port-name references are rewritten uniformly across ALL places
    the canonical tree stores them:

        * ``intent.interfaces[].name``
        * ``intent.interfaces[].lag_member_of``
        * ``intent.interfaces[].vlan_parent``
        * ``intent.interfaces[].vrrp_groups[].track_interfaces[]``
        * ``intent.vlans[].tagged_ports[]``
        * ``intent.vlans[].untagged_ports[]``
        * ``intent.lags[].name``
        * ``intent.lags[].members[]``
        * ``intent.static_routes[].interface``
        * ``intent.dhcp_servers[].interface``
        * ``intent.vxlan_vnis[].source_interface``

    One more field follows a port without being resolved itself:
    ``intent.static_routes[].gateway``, when it is the name of an
    interface of the tree (:func:`route_port_reference`).

    One field is deliberately left alone:
    ``intent.interfaces[].default_name``, a port's factory name
    (RouterOS).  An entry of *rename_map* gives the port a NAME; the
    factory name is which hardware it is, and stays.  Rendered, that
    is ``set [ find default-name=ether1 ] name=WAN`` — what such an
    entry has always produced.  Rewriting the field with the name
    renders ``find default-name=WAN``, a lookup that matches no port,
    and nothing here can tell a name from a move: ``sfp1`` is a port
    of one RouterOS model and a short name for ``sfp-sfpplus1`` on
    another.  Moving a port onto other hardware is done where the
    target device is declared
    (:func:`~netcanon.services.migration_pipeline.run_plan_with_models`).

    Mutates *intent* in place.

    Returns a :class:`PortRenameResult` summarising what changed, what
    was dropped, and what was left as the source config has it.
    """
    # Non-CanonicalIntent trees have no port-name structure to
    # rewrite — the legacy mock adapter and any future back-compat
    # adapter that returns a plain dict fall through this path.
    # Returning an empty result is a correct no-op: nothing got
    # renamed, nothing got dropped, the pipeline continues and the
    # target's render pane sees the tree unchanged.  Without this
    # guard the iteration below crashes on ``intent.interfaces`` →
    # ``AttributeError: 'dict' object has no attribute 'interfaces'``
    # which surfaces in the UI as a spurious "status: failed" job.
    from .intent import CanonicalIntent

    # Entry log fires on EVERY call — including no-op paths — so
    # "did the orchestrator run at all?" is answerable from logs
    # even against a mock tree or when the operator's map is empty.
    # Outcome counts are summarised at the exit log below.
    logger.debug(
        "translate_port_names: entry %s → %s rename_map=%s "
        "source_ifaces=%d",
        source_codec.name, target_codec.name,
        "None" if rename_map is None
        else f"{len(rename_map)}-entry dict",
        len(getattr(intent, "interfaces", []) or []),
    )

    if not isinstance(intent, CanonicalIntent):
        return PortRenameResult(applied={}, warnings=[], dropped=[])

    user_map = dict(rename_map or {})
    applied: dict[str, str] = {}
    warnings: list[str] = []
    memo: dict[str, str] = {}

    # (#19) Reject empty / blank source keys BEFORE the drop/rename split.
    # ``interface`` defaults to '' on gateway-only static routes and unbound
    # DHCP pools, so an empty-string drop key (``{'': None}``) would match all
    # of them in _strip_dropped_ports and silently delete every such
    # route/pool.  Pydantic accepts the key (port_rename_map is
    # ``dict[str, str | None]``) and a UI row with a blank source + "drop"
    # produces exactly this.  Mirror local_user_names.py: warn + skip.
    for key in list(user_map):
        if not isinstance(key, str) or not key.strip():
            warnings.append(
                f"port_rename: source port {key!r} is empty or blank; "
                f"entry skipped"
            )
            del user_map[key]

    # A blank TARGET is no name, and neither is one that draws
    # nothing (a zero-width space).  Taken as one it was written into
    # the output -- ``interface `` with nothing after it -- and, being
    # an entry, counted as the operator's decision about the port.  A
    # value is a name or ``None``; the HTTP API refuses a blank one
    # outright (``MigrationPlanRequest``), and a caller that reaches
    # this function another way has the entry set aside and said.
    for key in [k for k, v in user_map.items() if not names_a_target(v)]:
        warnings.append(
            f"port_rename: the entry for {key!r} has no target name (it "
            f"is empty or blank); entry skipped — to drop the port, map "
            f"it to null"
        )
        del user_map[key]

    # A key in another letter case.  On a platform whose names have no
    # case, an operator who writes ``Trk1`` means the port the config
    # calls ``trk1`` (the device itself prints it both ways): the entry
    # goes to the name the config uses.  The flag is read, not
    # defaulted: there is no safe default for it.
    one_case = not source_codec.port_names_case_sensitive
    if one_case:
        key_by_the_configs_spelling(user_map, collect_port_names(intent))

    # Split user map into drops (value is None) and renames (value is str).
    # Drops never go through the target codec.
    #
    # (#6) User drops are keyed by SOURCE names and are stripped BEFORE the
    # rename sweep, not after: a rename can move a DIFFERENT interface ONTO a
    # dropped name (``{A: B, B: None}``), and a post-sweep strip keyed by ``B``
    # would then also delete the freshly-renamed survivor — silently losing a
    # configured interface while ``applied`` still claims the rename landed.
    # Stripping first (while names are still source-form) removes exactly the
    # operator's target and leaves the renamed survivor intact.
    user_dropped: set[str] = {
        name for name, tgt in user_map.items() if tgt is None
    }
    str_map: dict[str, str] = {
        name: tgt for name, tgt in user_map.items() if isinstance(tgt, str)
    }
    # Auto-drops accumulate in resolve() when ``strip_unmappable`` removes a
    # name the target codec can't format.  Every name is resolved in a pass of
    # its own before the sweep, and these are stripped then, while every name
    # is still in source form (see below).
    auto_dropped: set[str] = set()
    # Names left as they were for want of a name to give them, in the
    # order they were met.  ``memo`` keeps each to one mention.  Keys
    # of a dict and not a list: a unit asks whether its port is among
    # them, and a pasted config can hold as many of either as it likes.
    untranslated: dict[str, None] = {}

    # Per-interface kind overrides — populated by source codecs that
    # detect logical role (mgmt, etc.) from CONTEXT rather than from
    # the interface name.  Cisco IOS-XE CLI is the canonical example:
    # ``GigabitEthernet0/0`` with ``vrf forwarding Mgmt-vrf`` is
    # semantically the OOBM port but the name alone classifies as
    # kind="physical".  The parser sets ``CanonicalInterface.kind =
    # "mgmt"``; the override is applied AFTER classify_port_name so
    # the source codec doesn't have to thread context through its
    # pure name-based classifier.  The override cascades: every
    # target's kind=mgmt handling (Aruba ``oobm``, etc.) fires
    # automatically — no per-target codec changes required.
    kind_overrides: dict[str, str] = {
        iface.name: iface.kind
        for iface in intent.interfaces
        if getattr(iface, "kind", "")
    }

    same_codec = source_codec.name == target_codec.name
    # Ports a unit was sent after.  The config may name such a port
    # nowhere but in the unit (a pasted ``interface Gi0/0/1.54`` with
    # no stanza for its port), and an entry for it was still acted on.
    unit_parents: set[str] = set()
    # Interface names as the config wrote them, before anything is
    # stripped or rewritten.  Across vendors only a name that IS an
    # interface is taken for a sub-interface: a reference to a unit the
    # config gives no interface (Junos ``lo0.0``) is not one.
    records: frozenset[str] = frozenset(iface.name for iface in intent.interfaces)
    # Interfaces the source parser typed as a VLAN interface.  Where an
    # operator names those freely (FortiOS ``port1.55``) the dot is part
    # of a name, and the name is left to the classifier as before.
    vlan_interfaces: frozenset[str] = frozenset(
        iface.name for iface in intent.interfaces
        if iface.interface_type in ("ianaift:l3ipvlan", "ianaift:l2vlan")
    )
    # Interfaces the tree holds an 802.1Q tag for, and the tag.  The
    # tag of a sub-interface is not in its name, so one that is not
    # here is written without a tag wherever it goes -- and onto a
    # target that names a sub-interface by its tag, the tag is its
    # name.
    tags: dict[str, int] = {
        iface.name: iface.dot1q_vlan
        for iface in intent.interfaces if iface.dot1q_vlan is not None
    }
    named_by_tag = target_codec.units_are_named_by_their_tag
    # Sub-interfaces whose config states the port they ride on apart
    # from their name, and that port (:func:`stated_sub_interfaces`).
    stated = stated_sub_interfaces(intent)
    stated_ports: dict[str, str] = {name: port for name, (port, _unit) in stated.items()}

    def kind_of(name: str) -> str:
        try:
            ident = source_codec.classify_port_name(name)
        except Exception:
            # One of the per-vendor classifiers, on an arbitrary string
            # from a pasted config.  "Could not read it" is ``unknown``.
            return "unknown"
        return ident.kind if ident is not None else "unknown"

    def follows_its_port(name: str, port: str) -> bool:
        """*name* is ``<port>.<unit>`` and goes where *port* goes."""
        port_kind = kind_of(port)
        # RouterOS and OPNsense read ``ether1.55`` as a VLAN interface
        # that is NAMED after its parent: a thing of its own, with a
        # form of its own on every target.  So does the FortiOS parser,
        # by the interface's type.
        if name in vlan_interfaces or kind_of(name) not in ("unknown", port_kind):
            return False
        if same_codec:
            # The unit means the same thing on both sides.  It moves
            # only when its port was moved or dropped by an entry.
            return port in str_map or port in user_dropped
        unit = name.rpartition(".")[2]
        if not unit.strip("0") and name not in tags:
            # Unit 0 is the interface itself on every platform that
            # has one.  An interface NUMBERED 0 beside its port (a
            # hand-written ``Gi0/0/1.0``) sent after the port would
            # be written as the port's own unit 0 on Junos: two
            # interfaces in one.  Left to the classifier -- unless
            # it carries a tag, and is then named by it (below).
            # The unit is read as text -- 0 is what is left of ``0``
            # or ``00`` once its zeros are taken off -- and never
            # made a number: a pasted config can write more digits
            # after the dot than an integer is converted from, and
            # the conversion failed the whole job.
            return False
        if len(unit) > UNIT_MAX_DIGITS:
            # No sub-interface of any platform, and a name two of
            # the target renderers would make a number of.  Left to
            # the classifier, as it was.
            return False
        # What the port IS decides whether it carries sub-interfaces,
        # and a parser that read a port's role from context (the
        # IOS-XE ``Mgmt-vrf`` port) knows it better than the name.
        port_kind = kind_overrides.get(port) or port_kind
        return name in records and port_kind in UNIT_PARENT_KINDS

    def port_and_unit(name: str) -> tuple[str, str] | None:
        """*name* as a port and a unit of it, or ``None``.  On a
        platform whose names have no letter case the port is given
        as the config spells it when the unit spells it another
        way: ``interface gigabitethernet0/0/1.54`` is a unit of the
        port the config calls ``GigabitEthernet0/0/1``, and goes
        where that port goes.  A port the config does not name --
        it is there only through its unit -- is given as a key of
        the map spells it.  Each only where exactly one such
        spelling exists, and a spelling the config uses itself is
        never laid over by another."""
        split = split_unit(name)
        if split is None:
            return split
        port, unit = split
        # Both tables are empty where the platform's names have letter
        # case: another spelling is another name there.
        if port not in present_names:
            fold = port.casefold()
            port = one_way.get(fold) or mapped_one_way.get(fold) or port
        return port, unit

    def say_if_an_entry_moves_the_tag(name: str, out: str) -> None:
        """An entry decides the name, and on a target whose name is
        the tag that can be another VLAN than the source config
        tags.  Written as named, and said."""
        if not named_by_tag or name not in tags:
            return
        split = split_unit(out)
        if split is not None and split[1] == str(tags[name]):
            return
        warnings.append(
            f"port_rename: the entry for {name!r} names it {out!r}; on "
            f"{target_codec.name} the number after the dot is the VLAN "
            f"a sub-interface carries, and the source config tags it "
            f"{tags[name]} — name it '<port>.{tags[name]}' to keep its tag"
        )

    def after_its_stated_port(name: str, port: str) -> str:
        """*name* is a sub-interface of *port*, which its config
        states apart from its name.  Such a name is the operator's
        own (``gn-mgmt``, ``vlan0.10``) and says nothing another
        platform can read, so across vendors it goes where its port
        goes, named by its tag (``<port>.<tag>``; for two tags, its
        inner tag), as a unit is; its port is swept apart, as a
        reference.  Between two configs of
        one codec the name stands, as every name nobody mapped does.
        Its port dropped, it is dropped with it."""
        where = resolve(port)
        unit_parents.add(port)
        if port not in present_names:
            # The port is named nowhere but as the parent, so no
            # rename of it "happened".
            applied.pop(port, None)
        if port in user_dropped or port in auto_dropped:
            warnings.append(
                f"port_rename: {name!r} is a sub-interface of {port!r}, "
                f"which is not in the output; dropped with it"
            )
            auto_dropped.add(name)
            memo[name] = name
            return name
        out = name if same_codec else f"{where}.{stated[name][1]}"
        memo[name] = out
        if out != name:
            applied[name] = out
        if port in untranslated:
            # Its port was left as the source config has it, and the
            # sub-interface went where its port went: nowhere.
            untranslated[name] = None
        return out

    def resolve(name: str) -> str:
        # Idempotent + cached: resolving the same input twice returns
        # the same output without re-classifying.
        if name in memo:
            return memo[name]
        if name in user_dropped:
            # User drops are stripped from the tree BEFORE this sweep runs,
            # so resolve() normally never sees them; this guard is defensive
            # (any residual reference stays verbatim rather than being
            # classified/renamed).  Memoise to skip the classifier lookup.
            memo[name] = name
            return name
        if name in str_map:
            out = str_map[name]
            memo[name] = out
            if out != name:
                applied[name] = out
            say_if_an_entry_moves_the_tag(name, out)
            return out
        if name in stated_ports:
            return after_its_stated_port(name, stated_ports[name])
        # A sub-interface goes where its port goes.  No classifier
        # keeps a unit: asked, it either folds the name onto the port
        # itself (two interfaces on one name) or does not know it (the
        # sub-interface stays behind under its source name).
        split = port_and_unit(name)
        if split is not None and follows_its_port(name, split[0]):
            port, unit = split
            where = resolve(port)
            unit_parents.add(port)
            if port not in present_names:
                # The port itself is named nowhere in the config, so
                # no rename of it "happened".
                applied.pop(port, None)
            if port in user_dropped or port in auto_dropped:
                warnings.append(
                    f"port_rename: {name!r} is a unit of {port!r}, which "
                    f"is not in the output; dropped with it"
                )
                auto_dropped.add(name)
                memo[name] = name
                return name
            # The target's number after the dot may be the VLAN it
            # carries (VyOS ``vif``): sent with its unit number, a
            # Junos ``unit 100 vlan-id 200`` was ``vif 100``.  And a
            # unit 0 that is sent at all carries a tag (above), which
            # names it across vendors: ``.0`` is the port itself
            # everywhere but on Junos.
            by_tag = name in tags and (
                named_by_tag or (not same_codec and not unit.strip("0"))
            )
            out = f"{where}.{tags[name] if by_tag else unit}"
            memo[name] = out
            if out != name:
                applied[name] = out
            if port in untranslated:
                # Its port was left as the source config has it (only
                # with ``strip_unmappable=False``: otherwise such a
                # port is dropped, and the unit with it).  The unit
                # went where the port went, which is nowhere.
                untranslated[name] = None
            if not same_codec and name not in tags:
                # Its name says which port it is on; its tag is a
                # field, and there is none.  Not said between two
                # configs of one codec, where a unit is written as
                # the tree holds it and nothing was to be carried
                # across.  That is no promise about the tag: one
                # the parser does not read (AOS-CX, OS10) is lost on
                # every path, that one included -- the bare pipeline
                # loses it too -- and nothing reports it there.
                warnings.append(
                    f"port_rename: {name!r} went with its port to {out!r} "
                    f"with no 802.1Q tag: none was read for it from the "
                    f"source config, so the output carries no tag of the "
                    f"source config for it — look its VLAN id up in the "
                    f"source and set it on the target"
                )
            return out
        if same_codec:
            # One grammar on both sides: the name is already a name of
            # the target.  Asking the classifier and the formatter to
            # reproduce it is how ``fxp0`` became ``em0`` and
            # ``ge-0/0/1.54`` became ``ge-0/0/1``.
            memo[name] = name
            return name
        ident = source_codec.classify_port_name(name)
        if ident is None or ident.kind == "unknown":
            warnings.append(
                f"{source_codec.name}: could not classify port name "
                f"{name!r}; left verbatim"
            )
            untranslated[name] = None
            memo[name] = name
            return name
        # Apply CanonicalInterface.kind override — used when the source
        # vendor's interface-name alone undersells the role (Cisco
        # ``GigabitEthernet0/0`` with ``vrf forwarding Mgmt-vrf`` is
        # semantically mgmt but the name says physical).  The parser
        # set the override; we honour it before the target's formatter
        # sees the identity so kind=mgmt cascades through every
        # target's existing kind=mgmt handling automatically.
        if name in kind_overrides:
            ident = ident.model_copy(
                update={"kind": kind_overrides[name]},
            )
        out = target_codec.format_port_identity(ident)
        if out is None or out == "":
            # Target codecs that absorb SVI L3 state into the VLAN
            # stanza (Aruba AOS-S) have NO port-name for SVIs by
            # design — the rendered output still carries the IP
            # address via the VLAN stanza render path.  Suppress
            # the noise from the rename table so operators don't
            # see non-actionable "review" rows for something the
            # codec handles correctly elsewhere.
            if ident.kind == "svi" and getattr(
                target_codec, "absorbs_svi_into_vlan", False
            ):
                memo[name] = name
                return name
            # Surface specific advisory text for the complexity cases
            # the user most needs to review, not a generic "no native
            # representation" blurb.  The breakout / hw_aggregate cases
            # cannot be resolved without hardware-aware context; the
            # UI (Tier 3) turns these into an interactive punch list.
            if ident.kind == "breakout":
                warnings.append(
                    f"{target_codec.name}: {source_codec.name} port {name!r} "
                    f"is lane {ident.breakout_lane} of breakout parent "
                    f"{ident.breakout_parent!r} — target has no native "
                    f"breakout representation; review target port mapping."
                )
            elif ident.kind == "hw_aggregate":
                members = ", ".join(ident.aggregate_members) or "unknown"
                warnings.append(
                    f"{target_codec.name}: {source_codec.name} interface "
                    f"{name!r} is a {ident.aggregate_kind or 'hardware'} "
                    f"aggregate of [{members}]; target lacks this concept "
                    f"— enumerate member ports or LAG manually."
                )
            elif ident.kind == "loopback":
                warnings.append(
                    f"{target_codec.name}: {source_codec.name} loopback "
                    f"{name!r} has no native representation; drop or "
                    f"carry as raw_section."
                )
            elif ident.kind == "tunnel":
                warnings.append(
                    f"{target_codec.name}: {source_codec.name} tunnel "
                    f"{name!r} has no direct representation; tunnel "
                    f"configuration is inherently vendor-specific and "
                    f"needs manual porting."
                )
            elif ident.kind == "mgmt":
                warnings.append(
                    f"{target_codec.name}: {source_codec.name} mgmt "
                    f"interface {name!r} — target OOBM model differs; "
                    f"review target mgmt config."
                )
            else:
                warnings.append(
                    f"{target_codec.name}: no native representation for "
                    f"{ident.kind} {name!r} "
                    f"(source {source_codec.name}); left verbatim."
                )
            # Auto-drop: the target codec can't represent this name,
            # so leaving it verbatim in the canonical tree pollutes
            # the rendered output with invalid source-vendor syntax.
            # Default strip_unmappable=True removes the name from
            # downstream rendering; operators who explicitly want to
            # keep it can use a verbatim-override (``map[name] =
            # name``) or the Tier 3 UI's "keep verbatim" link.
            if strip_unmappable:
                auto_dropped.add(name)
            else:
                untranslated[name] = None
            memo[name] = name
            return name
        # A structurally-clean rename can STILL drop a source-side
        # semantic the target can't carry.  A hardware-switch member
        # (FortiGate ``internalN`` / ``lanN``) maps to a positional
        # target name by name-shape only — the L2-fabric membership is
        # lost even though the rename "succeeded".  This is the
        # success-branch analogue of the ``hw_aggregate`` warning above
        # (which fires for the bare ``internal`` / ``lan`` aggregate).
        # Between two configs of one codec the name stood before any
        # classifier was asked, so only a cross-vendor pair reaches
        # here; the condition says so where the advisory is made.  The
        # rename is still applied + recorded; the advisory rides
        # alongside it (the operator needs both).
        if ident.hw_switch_member and not same_codec:
            warnings.append(
                f"{target_codec.name}: {source_codec.name} port {name!r} is "
                f"a hardware-switch (L2 fabric) member; the mapping to {out!r} "
                f"is positional (name-shape only) and does NOT carry the "
                f"L2-switch membership — verify the target port's physical "
                f"cabling and L2 role."
            )
        memo[name] = out
        if out != name:
            applied[name] = out
        return out

    def place_the_loopbacks() -> None:
        """Ask the target once for every loopback no entry decides.

        Where a target's name for a loopback depends on the config's
        other loopbacks (Junos: one ``lo0``, a unit of it in each
        routing instance), one name at a time cannot place them --
        ``Loopback0`` and ``Loopback1`` came out as ``lo0`` and
        ``lo1``, an interface Junos does not have, in a job that said
        ``completed``.  What the target places is settled here; what
        it refuses is dropped and said, as a name it has no form for
        is (a name no entry decided, so the job is ``partial``); what
        it leaves out of both is formatted one at a time.  A loopback
        is an interface record the source classifier reads as one
        (with the parser's own word for its kind, as below), in the
        routing instance its record names.
        """
        loopbacks: dict[str, LoopbackToPlace] = {}
        for iface in intent.interfaces:
            name = iface.name
            if name in loopbacks or name in user_map:
                continue
            split = port_and_unit(name)
            if split is not None and follows_its_port(name, split[0]):
                continue
            ident = source_codec.classify_port_name(name)
            if ident is None or ident.kind == "unknown":
                continue
            if (kind_overrides.get(name) or ident.kind) != "loopback":
                continue
            loopbacks[name] = LoopbackToPlace(name, ident.index, iface.vrf or "")
        if not loopbacks:
            return
        placement = target_codec.place_loopbacks(
            list(loopbacks.values()), frozenset(str_map.values()),
        )
        if placement is None:
            return
        placed, refused = placement
        for name in loopbacks:
            if name in placed:
                out = placed[name]
                memo[name] = out
                if out != name:
                    applied[name] = out
            elif name in refused:
                warnings.append(
                    f"{target_codec.name}: {source_codec.name} loopback "
                    f"{name!r} {refused[name]}"
                )
                if strip_unmappable:
                    auto_dropped.add(name)
                else:
                    untranslated[name] = None
                memo[name] = name

    # (#49b) Snapshot every port name actually present in the tree BEFORE the
    # rewrite sweep mutates names in place — used to (a) warn on operator map
    # entries that named a port absent from the config, and (b) avoid
    # over-reporting those absent names as "dropped" (mirrors local_user /
    # snmpv3 honesty).
    present_names: set[str] = set(collect_port_names(intent))
    # Names the config only refers to (a route's interface, a pool's,
    # a track entry, a VXLAN source), read while every name is still
    # in source form.  One of these left as it was is reported apart.
    referred_only: set[str] = _only_referred_to(intent)
    # The names the config, and the map, each write exactly one way,
    # by their folded spelling: on a platform without letter case,
    # the only names another spelling can mean.
    one_way = single_spellings(present_names) if one_case else {}
    mapped_one_way = single_spellings(user_map) if one_case else {}

    # (#6) Strip operator-requested drops BEFORE the rename sweep so a rename
    # TARGET that reuses a dropped SOURCE name isn't itself deleted afterwards.
    if user_dropped:
        warnings.extend(_parents_gone(intent, user_dropped, stated_ports))
        _strip_dropped_ports(intent, user_dropped)

    # Resolve every name BEFORE anything is rewritten, in the order the
    # sweep visits them (so warnings come out in the order they always
    # did), and strip the names the target cannot express while every
    # name is still in source form.  Stripping them after the sweep, by
    # string, also deleted a DIFFERENT port that had just been renamed
    # ONTO that string — the failure (#6) describes for operator drops,
    # reachable without one once a device model renames every port.
    if not same_codec:
        place_the_loopbacks()
    for name in list(_swept_names(intent)):
        resolve(name)
    if auto_dropped:
        warnings.extend(_parents_gone(intent, auto_dropped, stated_ports))
        _strip_dropped_ports(intent, auto_dropped)

    # Rewrite everywhere a port name might be referenced.  Order doesn't
    # matter — memoisation keeps us idempotent.  ``default_name`` is not
    # touched: see the docstring.  A unit suffix on a next hop means the
    # same thing on both sides only between two configs of one codec.
    rewrite_port_names(intent, resolve, units=same_codec)

    # (#17) Detect rename TARGET collisions: two+ source ports resolving to the
    # same final interface/LAG name render duplicate stanzas (same-vendor) or
    # fuse into one interface on re-parse (cross-vendor) — previously silent
    # (warnings=[]).  The vlan / local-user / snmpv3 orchestrators surface
    # target collisions; the ports pane didn't.  Warn (naming the colliding
    # sources) so the operator can map each source to a distinct target.  We do
    # NOT drop/merge here: some targets already dedupe + annotate the collision
    # at render time (FortiGate emits ``# port collision``), and dropping at the
    # orchestrator would pre-empt that and silently discard a port's config.
    #: Final names a sweep below has ACTUALLY warned about.  The membership
    #: sweep further down must skip exactly these and nothing more.
    warned_finals: set[str] = set()

    def _warn_collisions(objs: list, kind: str) -> None:
        counts: dict[str, int] = {}
        for obj in objs:
            counts[obj.name] = counts.get(obj.name, 0) + 1
        ended_on: dict[str, list[str]] = {}
        for s, f in memo.items():
            if s not in auto_dropped:
                ended_on.setdefault(f, []).append(s)
        for final in sorted(n for n, c in counts.items() if c > 1):
            warned_finals.add(final)
            # A name the translator dropped reached no target, so it
            # shares none -- the same rule the membership sweep below
            # applies.  (An operator's drop is stripped before any name
            # is resolved, and is never among these.)
            sources = sorted(ended_on.get(final, ())) or [final]
            warnings.append(
                f"port_rename: multiple source ports map to {final!r} "
                f"(sources: {', '.join(sources)}); the target will render "
                f"duplicate/fused {kind} stanzas — map each source to a "
                f"distinct target"
            )

    _warn_collisions(intent.interfaces, "interface")
    _warn_collisions(intent.lags, "LAG")

    # (#482) The two sweeps above only see names that reached an
    # `interfaces` or `lags` RECORD.  A VLAN-centric source need not have
    # any: Aruba AOS-S captures routinely carry zero `interface` stanzas
    # and name every port only inside `vlans[].tagged_ports` /
    # `untagged_ports`.  On those configs both sweeps inspect empty lists
    # and the fusion below went out with `warnings == []`.
    #
    # `memo` holds every source -> final pair the sweep actually applied,
    # wherever the name lived, so it is the honest detection surface --
    # the same `present_names`-vs-`interfaces[].name` scoping mistake
    # that made the fusion invisible in the first place.
    #
    # Worked example: Aruba `1/A1` is an uplink-MODULE port and `1/1` is
    # an access port.  `classify_port_name` correctly distinguishes them
    # (`subslot_letter="A"`), but no target's `format_port_identity`
    # consumes that field, so both render to one name -- `ge-1/0/1` on
    # Junos, `Ethernet1/0/1` on NX-OS, `port1` on FortiGate, and so on
    # for 9 of the 11 public targets.  Two physically distinct ports
    # become one, and their VLAN memberships merge.
    #
    # We warn rather than invent: no target models a letter slot, and
    # synthesising an offset port number would fabricate topology the
    # operator never wrote.  An explicit `port_rename_map` entry still
    # overrides, which is the documented escape hatch.
    #
    # Two mistakes used to hide fusions here, both found 2026-10-07:
    #
    # 1. The skip-set was every final interface / LAG NAME, not the names
    #    the sweeps above had warned about.  One `interface 1/1` record
    #    (count 1, so no warning) was enough to suppress the report for a
    #    `1/A1` living only in a VLAN's port list -- both rendered as
    #    `ge-1/0/1` with `warnings == []`.  The regression test that
    #    existed used a capture with ZERO interface stanzas, the one shape
    #    this did not mask.
    # 2. Identity pairs were excluded, so a port that KEPT its name while
    #    another was renamed onto it counted as a single source.
    #
    # Whether two FINAL names are one place is the target's rule, as it
    # is two blocks below: on a target with no letter case ``Trk1`` and
    # ``trk1`` are one port, and a source port sent to either is on it.
    # Grouped by the exact string, ``{"5": "Trk1"}`` put port 5 on the
    # LAG an AOS-S config calls ``trk1`` -- and, from another vendor,
    # ``{"5": "trk1"}`` on the LAG the AOS-S formatter writes ``Trk1``
    # -- with nothing said.
    fold_final = not target_codec.port_names_case_sensitive
    fused: dict[str, set[str]] = {}
    written: dict[str, set[str]] = {}
    gone = user_dropped | auto_dropped
    for source, final in memo.items():
        # A dropped name reached no target, so it shares none.
        if final is not None and source not in gone:
            place = final.casefold() if fold_final else final
            fused.setdefault(place, set()).add(source)
            written.setdefault(place, set()).add(final)
    # Two spellings of one name are one source: on a platform whose
    # names have no letter case, ``A1`` and ``a1`` are one port, not two
    # ports sharing a target.  (An AOS-S LAG, which the device itself
    # writes ``trk1`` and ``Trk1``, no longer reaches here as two names:
    # its parser gives the LAG one.)
    for place in sorted(fused):
        distinct: dict[str, str] = {}
        for source in sorted(fused[place]):
            distinct.setdefault(source.casefold() if one_case else source, source)
        sources = sorted(distinct.values())
        # Said already, by the sweep of the records, only if EVERY
        # spelling written here was: a third source sent to ``trk1``
        # beside two sent to ``Trk1`` is named by no line of that sweep.
        if len(sources) < 2 or written[place] <= warned_finals:
            continue
        final, *others = sorted(written[place])
        also = (
            f" (also written {', '.join(repr(other) for other in others)}: "
            f"one port on {target_codec.name})"
        ) if others else ""
        warnings.append(
            f"port_rename: multiple source ports map to {final!r}{also} "
            f"(sources: {', '.join(sources)}); these are distinct ports "
            f"on the source device and their VLAN membership will be "
            f"merged — map each source to a distinct target"
        )

    # One name in two letter cases that this run sends APART.  The
    # rename map is keyed by the spelling, so an entry for ``A1`` leaves
    # ``a1`` where it was: one port's config on two targets, or half of
    # it dropped, in a job that would otherwise say nothing -- the
    # sweep above has just been told to count the two as one.  Whether
    # two final names are one place is the TARGET's rule: left as
    # ``A1`` and ``a1`` they are one port on a target with no case, and
    # two interfaces on one that has it.
    if one_case:
        spelt: dict[str, set[str]] = {}
        for name in present_names:
            spelt.setdefault(name.casefold(), set()).add(name)
        for key in sorted(spelt):
            names = sorted(spelt[key])
            if len(names) < 2:
                continue
            ends = {
                name: (None if name in gone else memo.get(name, name))
                for name in names
            }
            places = {
                end if end is None or target_codec.port_names_case_sensitive else end.casefold()
                for end in ends.values()
            }
            if len(places) > 1:
                said = ", ".join(
                    f"{name} -> {'dropped' if end is None else end}"
                    for name, end in ends.items()
                )
                warnings.append(
                    f"port_rename: {' and '.join(names)} are one name on "
                    f"{source_codec.name}, written in more than one letter "
                    f"case, and do not end together ({said}) — give every "
                    f"spelling the same entry"
                )

    # (#49b) Operator drop/rename keys that named a port absent from the tree
    # did nothing — warn instead of silently over-reporting them as dropped.
    # A key that is a second spelling of a name which has an entry is
    # not a port that "does not exist": say what it is, and say nothing
    # where the two entries agree.
    for key in user_map:
        if key in present_names or key in unit_parents:
            # Present, or named only through a unit that went where
            # the entry sent its port: either way it was not ignored.
            continue
        other = one_way.get(key.casefold())
        if other is not None and other in user_map:
            if user_map[key] != user_map[other]:
                warnings.append(
                    f"port_rename: source port {key!r} is another spelling "
                    f"of {other!r}, which has an entry of its own; entry "
                    f"ignored"
                )
            continue
        warnings.append(
            f"port_rename: source port {key!r} does not exist in the "
            f"parsed config; entry ignored"
        )
    # Report only drops that actually removed a present name (auto-dropped
    # unmappable names were resolved from real references, so they qualify).
    reported_dropped = sorted(
        d for d in (user_dropped | auto_dropped) if d in present_names
    )

    # (#4) A rename/drop invalidates any verbatim vendor-provenance group
    # bodies (Junos apply-groups): the target's render re-emits those bodies
    # UNCHANGED, resurrecting the PRE-rename interface names alongside the
    # renamed ones (the same IP ends up on two ports).  The flattened
    # canonical tree already carries the group semantics, so drop the
    # verbatim bodies + apply-group refs once names have moved — mirrors the
    # sanitizer's group_content strip.  Fail closed with a warning.
    if (applied or reported_dropped) and (
        intent.group_content or intent.apply_groups
    ):
        intent.group_content = {}
        intent.apply_groups = []
        warnings.append(
            "port_rename: cleared verbatim apply-group bodies because a "
            "rename/drop was applied — group content was flattened into the "
            "canonical tree to avoid resurrecting pre-rename names"
        )

    logger.debug(
        "translate_port_names: exit %s → %s applied=%d dropped=%d "
        "warnings=%d",
        source_codec.name, target_codec.name,
        len(applied),
        len(reported_dropped),
        len(warnings),
    )
    return PortRenameResult(
        applied=applied,
        warnings=warnings,
        dropped=reported_dropped,
        # As with the drops: only a name the config has.  A port named
        # nowhere but through a unit of it was resolved too.
        untranslated=[
            name for name in untranslated
            if name in present_names and name not in referred_only
        ],
        untranslated_references=[
            name for name in untranslated if name in referred_only
        ],
    )


def _parents_gone(
    intent: CanonicalIntent, dropped: set[str], sub_interfaces: dict[str, str],
) -> list[str]:
    """A warning for each VLAN interface that stays while the
    interface its config says it rides on (``vlan_parent``) is
    dropped.  :func:`_strip_dropped_ports` clears the reference, and a
    renderer that has to name a parent then chooses one itself: said
    here, so that the choice is not made in silence.  A sub-interface
    of a stated port (*sub_interfaces*) does not stay: it is dropped
    with its port, and said where that is decided."""
    return [
        f"port_rename: {iface.name!r} rides on {iface.vlan_parent!r}, which "
        f"is not in the output; the target codec chooses the interface it "
        f"rides on there -- check it"
        for iface in intent.interfaces
        if iface.vlan_parent in dropped and iface.name not in dropped
        and iface.name not in sub_interfaces
    ]


def _strip_dropped_ports(
    intent: CanonicalIntent, dropped: set[str]
) -> None:
    """Remove every reference to *dropped* port names from *intent*.

    Cascades through every canonical field that stores a port name:

        * ``intent.interfaces`` — interfaces whose name is dropped
          are deleted outright.  Surviving interfaces get their
          ``lag_member_of`` cleared if the referenced LAG is dropped,
          and their ``vlan_parent`` if the interface it names is.
        * ``intent.vlans[].tagged_ports`` / ``untagged_ports`` —
          dropped names filtered out.
        * ``intent.lags`` — LAGs whose name is dropped are deleted;
          surviving LAGs get their ``members`` list filtered.
        * ``intent.static_routes`` — routes whose ``interface`` is
          dropped are deleted (they no longer have a viable egress),
          and so are routes whose ``gateway`` names a dropped
          interface (:func:`route_port_reference`).
        * ``intent.dhcp_servers`` — pools whose ``interface`` is
          dropped are deleted (pool has no interface to serve).
        * ``intent.interfaces[].vrrp_groups[].track_interfaces`` — dropped
          names filtered out (a dangling track ref silently disables
          failover on the target).
        * ``intent.vxlan_vnis[].source_interface`` — cleared if dropped
          (a dangling VTEP source breaks the whole overlay binding).

    Mutates *intent* in place.  Idempotent: subsequent calls with the
    same *dropped* set are no-ops.
    """
    named = {iface.name for iface in intent.interfaces}
    intent.interfaces = [
        i for i in intent.interfaces if i.name not in dropped
    ]
    for iface in intent.interfaces:
        if iface.lag_member_of in dropped:
            iface.lag_member_of = None
        if iface.vlan_parent in dropped:
            iface.vlan_parent = None
        # (#3) Drop dangling VRRP track-interface references.
        for grp in iface.vrrp_groups:
            grp.track_interfaces = [
                t for t in grp.track_interfaces if t not in dropped
            ]
    for vlan in intent.vlans:
        vlan.tagged_ports = [
            p for p in vlan.tagged_ports if p not in dropped
        ]
        vlan.untagged_ports = [
            p for p in vlan.untagged_ports if p not in dropped
        ]
    intent.lags = [lag for lag in intent.lags if lag.name not in dropped]
    for lag in intent.lags:
        lag.members = [m for m in lag.members if m not in dropped]
    # (#19) Guard on a truthy interface: a gateway-only route / unbound pool
    # has ``interface == ''`` and must never be matched by a drop set (an
    # empty-string drop key would otherwise delete every one of them).
    def next_hop_dropped(route: CanonicalStaticRoute) -> bool:
        reference = route_port_reference(route, named)
        return reference is not None and reference[0] in dropped

    intent.static_routes = [
        r for r in intent.static_routes
        if not (r.interface and r.interface in dropped)
        and not next_hop_dropped(r)
    ]
    intent.dhcp_servers = [
        p for p in intent.dhcp_servers
        if not (p.interface and p.interface in dropped)
    ]
    # (#3) Clear dangling VXLAN VTEP source-interface references.
    for vx in intent.vxlan_vnis:
        if vx.source_interface in dropped:
            vx.source_interface = ""


def build_port_rename_transform(
    source_codec: CodecBase,
    target_codec: CodecBase,
    rename_map: dict[str, str | None] | None = None,
    strip_unmappable: bool = True,
) -> tuple[Callable[[CanonicalIntent], CanonicalIntent], PortRenameResult]:
    """Return a pipeline-compatible transform + a result accumulator
    for cross-vendor port-name rewriting.

    Tier-2 factory: callers build the transform with or without a
    user rename map and feed it into ``run_plan`` alongside any other
    transforms.  The pipeline stays oblivious — ``run_plan`` just
    sees another ``TransformCallable``.  Pattern is mirrored by the
    other four per-pane orchestrators
    (:func:`build_vlan_rename_transform`,
    :func:`build_local_user_rename_transform`,
    :func:`build_snmp_community_rename_transform`,
    :func:`build_snmpv3_user_rename_transform`).

    Args:
        source_codec: Adapter for the source vendor — supplies
            ``classify_port_name`` for the auto-heuristic path.
        target_codec: Adapter for the target vendor — supplies
            ``format_port_identity`` so the cross-vendor bridge can
            emit native target-vendor names.
        rename_map: Optional ``{source_name: target_name | None}``
            override map.  Sentinel semantics (per AGENTS.md +
            ``run_plan_with_overrides`` docstring):

              * ``None`` — pane not engaged (caller should not even
                wrap this transform; included for symmetry).
              * ``{}`` — engaged with auto-heuristic only; the
                cross-vendor classifier → formatter bridge runs but
                no explicit overrides are applied.
              * ``{src: tgt}`` — explicit rewrite; wins over the
                auto-heuristic.
              * ``{src: None}`` — explicit drop; the source name is
                stripped from every canonical-tree field that
                referenced it (interfaces, VLAN port lists, LAGs,
                static-route interfaces, DHCP pools).
        strip_unmappable: When the auto-heuristic finds no target
            equivalent for a source name, ``True`` (default) drops
            the name from the canonical tree alongside the warning;
            ``False`` leaves it verbatim.

    Returns:
        Tuple of ``(transform_fn, result)``.  ``transform_fn`` fits
        the existing ``run_plan(transforms=...)`` signature — it
        takes an intent, mutates it in-place via
        :func:`translate_port_names`, and returns the same intent.
        ``result`` is a :class:`PortRenameResult` that accumulates
        applied / warnings / dropped entries across any invocations
        of the transform (in practice, just one per pipeline run).
        The caller reads ``result`` after the pipeline finishes to
        surface the rewrite outcome on the :class:`MigrationJob`.
    """
    result = PortRenameResult()

    def transform(intent: CanonicalIntent) -> CanonicalIntent:
        outcome = translate_port_names(
            intent, source_codec, target_codec, rename_map,
            strip_unmappable=strip_unmappable,
        )
        # Merge into the shared result object so the caller sees the
        # aggregate even if the transform runs more than once.
        result.applied.update(outcome.applied)
        result.warnings.extend(outcome.warnings)
        # Union of drops (order-preserving dedup).
        seen = set(result.dropped)
        for name in outcome.dropped:
            if name not in seen:
                result.dropped.append(name)
                seen.add(name)
        for kept, more in (
            (result.untranslated, outcome.untranslated),
            (result.untranslated_references, outcome.untranslated_references),
        ):
            seen = set(kept)
            for name in more:
                if name not in seen:
                    kept.append(name)
                    seen.add(name)
        return intent

    return transform, result

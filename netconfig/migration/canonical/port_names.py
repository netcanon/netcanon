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

from typing import TYPE_CHECKING, Callable, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from ..codecs.base import CodecBase
    from .intent import CanonicalIntent


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
    "mgmt",         # out-of-band management port
    "virtual",      # vendor-specific virtual (VirtualPortGroup, etc.)
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


# ---------------------------------------------------------------------------
# Orchestrator — vendor-agnostic cross-vendor rewrite
# ---------------------------------------------------------------------------


def translate_port_names(
    intent: "CanonicalIntent",
    source_codec: "CodecBase",
    target_codec: "CodecBase",
    rename_map: "dict[str, str | None] | None" = None,
    strip_unmappable: bool = True,
) -> PortRenameResult:
    """Rewrite every port-name reference in *intent* from source-vendor
    convention to target-vendor convention.

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
        3. Else run ``source_codec.classify_port_name(name)`` →
           ``target_codec.format_port_identity(ident)`` and use the
           target's native formatting.
        4. If the auto-path returns ``None`` (target has no equivalent
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
        circuits before (4): no warning, no drop, name stays verbatim
        (target's VLAN-stanza render path handles the L3 data).

    Port-name references are rewritten uniformly across ALL places
    the canonical tree stores them:

        * ``intent.interfaces[].name``
        * ``intent.interfaces[].lag_member_of``
        * ``intent.vlans[].tagged_ports[]``
        * ``intent.vlans[].untagged_ports[]``
        * ``intent.lags[].name``
        * ``intent.lags[].members[]``
        * ``intent.static_routes[].interface``
        * ``intent.dhcp_servers[].interface``

    Mutates *intent* in place.

    Returns a :class:`PortRenameResult` summarising what changed.
    """
    user_map = dict(rename_map or {})
    # Split user map into drops (value is None) and renames (value is str).
    # Drops never go through the target codec — they're stripped from the
    # canonical tree after the rename pass completes.
    dropped_set: set[str] = {
        name for name, tgt in user_map.items() if tgt is None
    }
    str_map: dict[str, str] = {
        name: tgt for name, tgt in user_map.items() if isinstance(tgt, str)
    }
    applied: dict[str, str] = {}
    warnings: list[str] = []
    memo: dict[str, str] = {}

    def resolve(name: str) -> str:
        # Idempotent + cached: resolving the same input twice returns
        # the same output without re-classifying.
        if name in memo:
            return memo[name]
        if name in dropped_set:
            # Leave verbatim in the rename pass — the strip pass
            # below removes the name entirely.  Memoise to skip the
            # classifier lookup for subsequent references.
            memo[name] = name
            return name
        if name in str_map:
            out = str_map[name]
            memo[name] = out
            if out != name:
                applied[name] = out
            return out
        ident = source_codec.classify_port_name(name)
        if ident is None or ident.kind == "unknown":
            warnings.append(
                f"{source_codec.name}: could not classify port name "
                f"{name!r}; left verbatim"
            )
            memo[name] = name
            return name
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
                dropped_set.add(name)
            memo[name] = name
            return name
        memo[name] = out
        if out != name:
            applied[name] = out
        return out

    # Rewrite everywhere a port name might be referenced.  Order doesn't
    # matter — memoisation keeps us idempotent.
    for iface in intent.interfaces:
        iface.name = resolve(iface.name)
        if iface.lag_member_of:
            iface.lag_member_of = resolve(iface.lag_member_of)
    for vlan in intent.vlans:
        vlan.tagged_ports = [resolve(p) for p in vlan.tagged_ports]
        vlan.untagged_ports = [resolve(p) for p in vlan.untagged_ports]
    for lag in intent.lags:
        lag.name = resolve(lag.name)
        lag.members = [resolve(m) for m in lag.members]
    for route in intent.static_routes:
        if route.interface:
            route.interface = resolve(route.interface)
    for pool in intent.dhcp_servers:
        if pool.interface:
            pool.interface = resolve(pool.interface)

    # Strip pass: remove every reference to a dropped name from the
    # canonical tree.  Runs AFTER the rename sweep so dropped entries
    # don't interfere with other sources' resolution.
    if dropped_set:
        _strip_dropped_ports(intent, dropped_set)

    return PortRenameResult(
        applied=applied,
        warnings=warnings,
        dropped=sorted(dropped_set),
    )


def _strip_dropped_ports(
    intent: "CanonicalIntent", dropped: set[str]
) -> None:
    """Remove every reference to *dropped* port names from *intent*.

    Cascades through every canonical field that stores a port name:

        * ``intent.interfaces`` — interfaces whose name is dropped
          are deleted outright.  Surviving interfaces get their
          ``lag_member_of`` cleared if the referenced LAG is dropped.
        * ``intent.vlans[].tagged_ports`` / ``untagged_ports`` —
          dropped names filtered out.
        * ``intent.lags`` — LAGs whose name is dropped are deleted;
          surviving LAGs get their ``members`` list filtered.
        * ``intent.static_routes`` — routes whose ``interface`` is
          dropped are deleted (they no longer have a viable egress).
        * ``intent.dhcp_servers`` — pools whose ``interface`` is
          dropped are deleted (pool has no interface to serve).

    Mutates *intent* in place.  Idempotent: subsequent calls with the
    same *dropped* set are no-ops.
    """
    intent.interfaces = [
        i for i in intent.interfaces if i.name not in dropped
    ]
    for iface in intent.interfaces:
        if iface.lag_member_of in dropped:
            iface.lag_member_of = None
    for vlan in intent.vlans:
        vlan.tagged_ports = [
            p for p in vlan.tagged_ports if p not in dropped
        ]
        vlan.untagged_ports = [
            p for p in vlan.untagged_ports if p not in dropped
        ]
    intent.lags = [l for l in intent.lags if l.name not in dropped]
    for lag in intent.lags:
        lag.members = [m for m in lag.members if m not in dropped]
    intent.static_routes = [
        r for r in intent.static_routes if r.interface not in dropped
    ]
    intent.dhcp_servers = [
        p for p in intent.dhcp_servers if p.interface not in dropped
    ]


def build_port_rename_transform(
    source_codec: "CodecBase",
    target_codec: "CodecBase",
    rename_map: "dict[str, str | None] | None" = None,
    strip_unmappable: bool = True,
) -> tuple[Callable[["CanonicalIntent"], "CanonicalIntent"], PortRenameResult]:
    """Return a ``(transform, result)`` pair.

    *transform* fits the existing ``run_plan(transforms=...)`` signature
    — takes an intent, returns an intent.  *result* is a
    :class:`PortRenameResult` that accumulates across any invocations
    of the transform (in practice, just one per pipeline run).  The
    caller can read it after the pipeline finishes to surface warnings
    or the applied map in the UI.

    This is the Tier-2 factory: callers build the transform with or
    without a user rename map and feed it into ``run_plan`` alongside
    any other transforms.  The pipeline stays oblivious — ``run_plan``
    just sees another ``TransformCallable``.
    """
    result = PortRenameResult()

    def transform(intent: "CanonicalIntent") -> "CanonicalIntent":
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
        return intent

    return transform, result

"""
Positional port mapping — pair two inventories, produce a rename map.

Cross-vendor port translation by name shape cannot be right: the same
string means different ports on different models, and the same port has
different names in different deployment states.  This module does the
other thing.  Given the inventory of the source device and the
inventory of the target device (see
:mod:`netcanon.migration.device_models`), it pairs ports by POSITION —
the third access port of the second member with the third access port
of the second member — and returns the pairing as an ordinary
``port_rename_map``.  The existing translator already applies an
explicit rename entry ahead of its own guess, so nothing downstream
changes.

The pairing is a default, not a verdict.  It pre-fills the mapping an
operator can then edit; an operator's own entry always wins (the
caller merges it over :attr:`MappingPlan.rename_map`).

Two stages:

* :func:`plan_port_mapping` pairs the inventories.  Pure: it sees no
  config beyond the list of names the source uses.
* :func:`settle_plan` reconciles that plan with what a translation
  run then actually did — which ports the operator overrode, which
  were dropped, whether two names ended on one target — and rewrites
  the plan's flags and warnings to match.  ``pairings`` and
  ``rename_map`` stay the pairing as made; ``overridden`` says which
  of them the operator replaced.

What a drop took with it -- a route, a DHCP pool, a track entry, a
VTEP source, a LAG's members -- is said in one wording,
:func:`what_went_lines`: by the plan here, and where no devices are
declared by the job, from the translator's own record.

Policy, in order:

1. Members pair by rank — first with first, in the order each
   deployment lists them, whatever their member numbers are.  A
   source member beyond the target's member count is not folded onto
   another member, and a port one member has no place for is never
   put on another.
2. Within a member, ports pair role to role, in port-number order:
   access to access, uplink to uplink, management to management.
3. A source port with no position on the target is **unplaced**.  It
   is never spilled onto a spare port of another role.
4. The map is TOTAL over the data ports the source config uses.  A
   used port that pairs goes to its target; a used access or uplink
   port that is unplaced is DROPPED, explicitly (``None``).  "No
   entry" would hand the port to the name-shape translator, and for a
   same-vendor pair that translator is the identity: the port would
   keep its old name, which may be the name another port was just
   mapped to — two physical ports fused into one, in a job that
   reports success.
5. Some names get no entry, and are left to the name-shape
   translator: an unplaced MANAGEMENT port (the translator knows what
   each target does with out-of-band management — on AOS-S that is
   the ``oobm`` block, not an interface); a name the config uses that
   is not in the declared source inventory at all, which is
   **off-inventory** and is the tripwire for a source model that was
   declared wrongly; and every LOGICAL name — a LAG, an SVI, a
   loopback — which was never the mapper's to decide.  (Between two
   configs of one codec the translator leaves each of them as it is
   written.  A sub-interface is not among them: it goes where its
   port goes.)

   The hazard of policy 4 applies to every one of these exactly as it
   does to an unplaced data port: what the translator makes of a name
   may be a name the plan assigned to another port.  The mapper cannot
   know that in advance without re-deriving the translator, so the
   caller checks afterwards — over EVERY name the config references,
   not only the hardware ones (:func:`fused_targets`) — and drops any
   name nobody decided that clashes.  It is then **displaced**.  See
   :func:`~netcanon.services.migration_pipeline.run_plan_with_models`.
6. Only ports the source config uses are reported as problems.

Pure functions — no I/O, no global state.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence

from ..models.port_inventory import (
    Inventory,
    MappingPlan,
    PhysicalPort,
    PortPairing,
    UnplacedPort,
    weakest_grade,
)
from .device_models import SPEED_RANK

__all__ = [
    "MappingPlan",
    "PortPairing",
    "UnplacedPort",
    "describe_plan",
    "fused_targets",
    "name_key",
    "plan_port_mapping",
    "settle_plan",
]


def name_key(name: str, fold: bool = True) -> str:
    """The form in which two port names are compared.

    Surrounding space is never part of a port's identity.  Whether
    another letter case can be another interface is a fact about the
    platform.  On AOS-S or IOS ``1/a1`` is the port ``1/A1``, and a
    job that puts one source port on each has put two on one port.
    On FortiOS or RouterOS ``DMZ`` and ``dmz`` are two interfaces,
    and treating them as one would turn an operator's own name for a
    VLAN interface into the physical port beside it.

    Args:
        name: The name.
        fold: Compare without regard to case — ``not
            codec.port_names_case_sensitive`` for the platform the
            name belongs to.  Neither value is a safe guess: folding
            where case tells two interfaces apart counts them as one
            and says nothing, and not folding where it does not lets
            a misspelling pass beside the port.  A caller passes the
            platform's own rule.
    """
    text = name.strip()
    return text.casefold() if fold else text


def _is_downshift(source_speed: str, target_speed: str) -> bool:
    if source_speed not in SPEED_RANK or target_speed not in SPEED_RANK:
        return False
    return SPEED_RANK[target_speed] < SPEED_RANK[source_speed]


def _plain(name: str) -> str:
    # The migrate page reads single-quoted tokens out of job warnings
    # as extra rows of its rename table.  A name is free text on some
    # platforms (RouterOS, FortiGate) and may hold an apostrophe.
    return name.replace("'", "\N{RIGHT SINGLE QUOTATION MARK}")


def _summary(names: Iterable[str], limit: int = 8, sep: str = ", ") -> str:
    items = [_plain(name) for name in names]
    shown = sep.join(items[:limit])
    return shown if len(items) <= limit else f"{shown} and {len(items) - limit} more"


def _member_lines(plan: MappingPlan, decided: Iterable[str] = ()) -> list[str]:
    """The lines for members that were paired with a member of another
    NUMBER, if any.

    Members pair in the order they are declared (their rank), never by
    the vendor's member id.  Where the two ids differ every port of
    the member changes its name -- or loses its place -- for that
    reason alone, so the plan says which member went to which.  Two
    cases, each with a line of its own:

    * a RENUMBERING: neither number is declared on the other side (a
      fabric numbered 1 and 3 onto a stack numbered 1 and 2).  Nothing
      an operator could have meant is contradicted;
    * a CROSSING: one of the two numbers is declared on both sides,
      and the members of that number were not put together (2, 1
      onto 1, 2; and 2, 3 onto 1, 2, where member 2 lands beside its
      namesake).  That is what a list typed in another order looks
      like, so the line says how to keep them together: the same
      place in both lists.

    Said for a member the config uses -- a used port of it was paired,
    or has no place on the member it was paired with -- and whose
    ports the operator did not decide one by one (*decided*).  A
    device that stands alone has no member id and is not listed, and
    neither is either side of a flat profile: the number in its names
    is not known apart from them.  A member beyond the target's last
    has the ``no-member`` line instead.

    Neither line is a problem, and neither holds a job: the order of
    the two declarations is the operator's way to choose which member
    goes where.
    """
    if plan.source is None or plan.target is None:
        return []
    theirs = {member.rank: member.member_id for member in plan.target.members}
    on_target = {number for number in theirs.values() if number is not None}
    on_source = {
        member.member_id for member in plan.source.members if member.member_id is not None
    }
    seen = set(decided)
    used = {
        port.member_rank for port in (*plan.used_pairings, *plan.used_unplaced)
        if port.source not in seen
    }
    renumbered: list[str] = []
    crossed: list[str] = []
    for member in plan.source.members:
        there = theirs.get(member.rank)
        if member.rank not in used or member.member_id is None or there in (None, member.member_id):
            continue
        pair = f"source member {member.member_id} with target member {there}"
        both = member.member_id in on_target or there in on_source
        (crossed if both else renumbered).append(pair)
    lines: list[str] = []
    if renumbered:
        lines.append(
            f"port mapping: stack members pair in the order they are declared, "
            f"not by member number: {_summary(renumbered, limit=10, sep='; ')}"
        )
    if crossed:
        lines.append(
            f"port mapping: {len(crossed)} stack member(s) are paired with a "
            f"member of ANOTHER number while one of the two numbers is "
            f"declared on both sides "
            f"({_summary(crossed, limit=10, sep='; ')}); members pair in the "
            f"order the two declarations list them — to keep the members of "
            f"one number together, give them the same place in both lists"
        )
    return lines


def _by_position(
    ports: list[PhysicalPort],
) -> dict[tuple[int | None, str], list[PhysicalPort]]:
    """Ports grouped by ``(member_rank, role)``, each group in
    inventory order.  Position is computed here, when pairing, rather
    than read from a stored ordinal — two inventories need not number
    the same ports."""
    groups: dict[tuple[int | None, str], list[PhysicalPort]] = {}
    for port in ports:
        groups.setdefault((port.member_rank, port.role), []).append(port)
    return groups


def _repeated_names(inventory: Inventory) -> list[str]:
    counts = Counter(name_key(port.name) for port in inventory.ports)
    return sorted({
        port.name for port in inventory.ports if counts[name_key(port.name)] > 1
    })


def _not_applied(plan: MappingPlan, reason: str) -> MappingPlan:
    plan.applied = False
    plan.warnings = [
        f"port mapping: {reason}, so nothing was paired by position; "
        f"port names were translated by name shape instead"
    ]
    return plan


def plan_port_mapping(
    source: Inventory,
    target: Inventory,
    used_names: Iterable[str] | None = None,
    known_as: Mapping[str, str] | None = None,
    one_hardware: Iterable[str] = (),
) -> MappingPlan:
    """Pair *source* with *target* by position.

    Args:
        source: Inventory of the device the config came from.
        target: Inventory of the device the config is going to.
        used_names: Hardware port names the source config references.
            LAG, SVI, loopback and other non-port names must already
            be excluded — a name here that is not in *source* is
            reported as off-inventory.  ``None`` treats every source
            port as used, which is what a preview before any config
            is loaded wants.
        known_as: For a source port the config knows by a name of its
            own (RouterOS: ``ether2`` named ``core-a``), the
            inventory's name for the port to the config's.  The port
            is found in *source* by the first and appears in the plan
            — and is matched against *used_names* — by the second.
        one_hardware: Factory names the config looks MORE THAN ONE
            interface up by (a port that was renamed, beside a line
            that still uses its old name).  Which of them is the port
            cannot be told, so no pairing is made.

    Returns:
        The plan.  ``rename_map`` holds entries only for used source
        ports, so it can be handed to the translator without naming
        ports the config does not contain.  ``applied`` is ``False``,
        and the map empty, when no pairing can be made: one side lists
        no ports, or lists the same name twice (a position is then not
        a port), or the config gives one port the name another port of
        the source device has, so that a name no longer says which, or
        looks two interfaces up by one factory name.
    """
    plan = MappingPlan(
        source=source.summary(),
        target=target.summary(),
        evidence=weakest_grade([source.evidence, target.evidence]),
        caveats=list(dict.fromkeys([*source.caveats, *target.caveats])),
    )
    sides = (("source", source), ("target", target))
    empty = [side for side, inventory in sides if not inventory.ports]
    if empty:
        return _not_applied(
            plan, f"the {' and the '.join(empty)} device lists no ports",
        )
    for side, inventory in sides:
        repeated = _repeated_names(inventory)
        if repeated:
            return _not_applied(
                plan,
                f"the {side} device lists a port name more than once "
                f"({_summary(repeated)})",
            )

    twice = sorted(set(one_hardware))
    if twice:
        return _not_applied(
            plan,
            f"the config looks more than one interface up by one factory "
            f"name ({_summary(twice)}) — a renamed port beside a line that "
            f"still uses its old name, or two set lines for one port, which "
            f"are read as two interfaces — and which of them is the port "
            f"cannot be told",
        )
    shown = dict(known_as or {})

    def config_name(port: PhysicalPort) -> str:
        return shown.get(port.name, port.name)

    counts = Counter(config_name(port) for port in source.ports)
    ambiguous = sorted(name for name, count in counts.items() if count > 1)
    if ambiguous:
        return _not_applied(
            plan,
            f"the config gives a port the name another port of the source "
            f"device has ({_summary(ambiguous)}), so its ports cannot be "
            f"told apart by name",
        )

    used: set[str] | None = None if used_names is None else set(used_names)
    target_groups = _by_position(target.ports)
    target_members = {p.member_rank for p in target.ports}
    taken: set[str] = set()
    for (rank, role), ports in _by_position(source.ports).items():
        partners = target_groups.get((rank, role), [])
        for position, port in enumerate(ports):
            is_used = used is None or config_name(port) in used
            if position >= len(partners):
                plan.unplaced.append(UnplacedPort(
                    source=config_name(port),
                    role=port.role,
                    member_rank=rank,
                    position=position,
                    # A port of the whole deployment (no rank) has no
                    # member to be missing.
                    reason=(
                        "no-position" if rank is None or rank in target_members
                        else "no-member"
                    ),
                    used=is_used,
                    dropped=port.role != "mgmt",
                ))
                continue
            match = partners[position]
            taken.add(match.name)
            plan.pairings.append(PortPairing(
                source=config_name(port),
                target=match.name,
                role=port.role,
                member_rank=rank,
                position=position,
                used=is_used,
                source_speed=port.speed,
                target_speed=match.speed,
                slower=_is_downshift(port.speed, match.speed),
                poe_lost=port.poe and not match.poe,
                evidence=weakest_grade([port.evidence, match.evidence]),
            ))

    order = {config_name(port): at for at, port in enumerate(source.ports)}
    plan.labelled_ports = {
        config_name(port): port.name for port in source.ports
        if config_name(port) != port.name
    }
    plan.pairings.sort(key=lambda p: order[p.source])
    plan.unplaced.sort(key=lambda p: order[p.source])
    plan.off_inventory = sorted(used - set(order)) if used is not None else []
    plan.unused_target = [p.name for p in target.ports if p.name not in taken]
    plan.rename_map = {p.source: p.target for p in plan.pairings if p.used}
    plan.rename_map.update({p.source: None for p in plan.used_dropped})
    plan.unresolved_ports = plan.unresolved()
    plan.warnings = describe_plan(plan)
    return plan


def fused_targets(
    names: Iterable[str],
    port_renames: Mapping[str, str],
    port_drops: Iterable[str],
    involving: Iterable[str] | None = None,
    *,
    fold_source: bool = True,
    fold_target: bool = True,
) -> dict[str, list[str]]:
    """Target names that more than one source name ended on.

    Read from what a translation run reports, so it holds whatever
    decided each name: the pairing, an operator override, or the
    name-shape translator.

    Args:
        names: The source names to look at.  For the check to mean
            "no two ports share a name in the output" this has to be
            EVERY name the config references
            (:func:`~netcanon.migration.canonical.port_names.collect_port_names`),
            logical ones included: the translator rewrites them all,
            and an aggregate it calls a physical port lands on a
            physical port's name.
        port_renames: ``MigrationJob.port_renames`` — source name to
            the name it was given, for every name that changed.
        port_drops: ``MigrationJob.port_drops``.
        involving: When given, only a clash that includes one of these
            names is returned — the hardware ports the config uses.
            Two LAG names that clash with each other are the
            translator's own business and are reported by it.

        fold_source: Source names are compared without regard to
            case (the source platform's rule; see :func:`name_key`).
        fold_target: Target names are.

    Returns:
        Target name to its source names (two or more), in the order
        the sources were given.  Names are compared by
        :func:`name_key`: where the platform folds case, a target
        that differs from another only in case is the same target,
        and two spellings of ONE source name are one source.  Empty
        when every surviving source name has a target of its own.
    """
    dropped = set(port_drops)
    wanted = None if involving is None else {
        name_key(name, fold_source) for name in involving
    }
    spelling: dict[str, str] = {}
    groups: dict[str, dict[str, str]] = {}
    for name in names:
        if name in dropped:
            continue
        final = port_renames.get(name, name)
        key = name_key(final, fold_target)
        spelling.setdefault(key, final.strip())
        groups.setdefault(key, {}).setdefault(name_key(name, fold_source), name)
    return {
        spelling[key]: list(sources.values())
        for key, sources in groups.items()
        if len(sources) > 1 and (wanted is None or wanted.intersection(sources))
    }


def settle_plan(
    plan: MappingPlan,
    *,
    operator_map: Mapping[str, str | None],
    used_names: Iterable[str],
    every_name: Iterable[str],
    port_renames: Mapping[str, str],
    port_drops: Iterable[str],
    target_names: Iterable[str],
    displaced: Iterable[str] = (),
    sub_interfaces: Mapping[str, str | None] | None = None,
    untagged_units: Mapping[str, str] | None = None,
    ignored_overrides: Iterable[str] = (),
    emptied_lags: Iterable[str] = (),
    shrunk_lags: Iterable[str] = (),
    lost_routes: Iterable[str] = (),
    lost_dhcp_pools: Iterable[str] = (),
    lost_tracking: Iterable[str] = (),
    lost_vtep_sources: Iterable[str] = (),
    management_forms: Mapping[str, str] | None = None,
    fold_source: bool = True,
    fold_target: bool = True,
    target_hardware: Mapping[str, str] | None = None,
    landed_off_target: Mapping[str, str] | None = None,
    stale_next_hops: Iterable[str] = (),
    units: bool = False,
    unbound: Iterable[str] = (),
    by_factory_name: bool = False,
) -> None:
    """Reconcile *plan* with what the translation run actually did.

    :func:`plan_port_mapping` states an intention.  Several things can
    make the outcome differ, and what a client reads must describe the
    outcome:

    * the operator's own map replaced plan entries — an unplaced port
      they gave a target was kept, not dropped;
    * the name-shape translator, handed a name the plan left to it,
      dropped that name (a management port on a target that has no
      management interface) rather than renaming it;
    * a name nobody decided was found to clash with another name's
      target, or to land on a port of the target, and was dropped by
      the caller;
    * a sub-interface followed its parent port;
    * a dropped port took a route, a DHCP pool, a LAG member, a VRRP
      track entry or a VTEP source with it.

    Fills the outcome fields (``overridden``, ``sub_interfaces``,
    ``untagged_units``, ``unvouched_units``,
    ``displaced``, ``fused``, ``off_target``, ``target_hardware``,
    ``source_hardware``, ``unbound_ports``, ``landed_off_target``,
    ``stale_next_hops``, ``ignored_overrides``,
    ``emptied_lags``, ``shrunk_lags``, ``lost_routes``,
    ``lost_dhcp_pools``, ``lost_tracking``, ``lost_vtep_sources``,
    ``unused_target``, ``unresolved_ports``),
    sets every used unplaced port's ``dropped`` and ``landed`` to what
    happened to it, takes a followed sub-interface out of
    ``off_inventory``, and rebuilds ``warnings``.  ``pairings`` and
    ``rename_map`` are left as the pairing was made.

    Args:
        plan: The plan to settle, in place.
        operator_map: The operator's own ``port_rename_map``, as
            applied.  A key here is the operator deciding that port.
        used_names: The hardware names the plan was made for.
        every_name: Every name the config references — the universe
            the translator rewrites and the fusion check looks at.
        port_renames: ``MigrationJob.port_renames`` of the final run.
        port_drops: ``MigrationJob.port_drops`` of the final run.
        target_names: Every port name of the declared target.
        displaced: Names dropped because of a clash; see
            :attr:`MappingPlan.displaced`.
        sub_interfaces: Sub-interface names that followed their parent.
        untagged_units: Sub-interface names that went with their
            parent across vendors although the parsed source holds
            no 802.1Q tag for them, each with the name it has in the
            output; see :attr:`MappingPlan.untagged_units`.  They
            are not among *sub_interfaces* and stay off-inventory.
        ignored_overrides: Source names whose override was blank.
        emptied_lags: LAGs every member port of which was dropped.
        shrunk_lags: LAGs that lost some of their member ports.
        lost_routes: Destinations of routes removed with a port.
        lost_dhcp_pools: DHCP pools removed with a port.
        lost_tracking: Interfaces that lost a VRRP track entry.
        lost_vtep_sources: VTEP source interfaces that were dropped.
        management_forms: For each source management port the target
            model has no place for, the name the ordinary translation
            gives one on the target (``oobm`` on AOS-S).  An override
            that sends the port to that name is not off-target.
        fold_source: Source names compare without regard to case.
        fold_target: Target names do (see :func:`name_key`).
        target_hardware: Which hardware each source name's port is
            looked up by in the output — read from the tree that was
            rendered, on a target that keeps a factory name beside a
            port's own (RouterOS).  Entries equal to the name the
            port has there say nothing and are left out.  The rest
            decide :attr:`MappingPlan.fused` and ``unused_target``;
            those that are ports of the target are kept as
            :attr:`MappingPlan.target_hardware`, and an operator's
            entry for such a port NAMED it and is not off-target.
            For a placed port with no interface that the read-back
            reported, it carries the target port the port was PAIRED
            with, which no tree states.
        landed_off_target: See :attr:`MappingPlan.landed_off_target`.
        stale_next_hops: See :attr:`MappingPlan.stale_next_hops`.
        units: A unit of a target port (``ge-0/0/7.54``) is a name of
            the target — true between two configs of one codec.  On
            any pair it is one for an entry whose SOURCE name is a
            sub-interface: a unit of a port the target lists is
            where the translator itself puts a unit, and where the
            plan's own lines tell an operator to name one.
        unbound: Keys of *target_hardware* whose hardware no line of
            their own in the rendered output looks up; see
            :attr:`MappingPlan.unbound_ports`.  Such a port is on no
            hardware in the output, and counts for none.
        by_factory_name: The target finds a port by a factory name
            beside its own (``CodecBase.ports_keep_a_factory_name``),
            so an override target that is not a port is a NAME there
            and never another spelling of a port.
    """
    dropped = set(port_drops)
    decided = set(operator_map)
    used = list(used_names)
    every = list(every_name)
    targets = list(target_names)
    followed = dict(sub_interfaces or {})

    for port in plan.unplaced:
        if port.used:
            port.dropped = port.source in dropped
            port.landed = "" if port.dropped else port_renames.get(port.source, port.source)
    plan.overridden = sorted(k for k in operator_map if k in plan.rename_map)
    plan.sub_interfaces = followed
    plan.off_inventory = [n for n in plan.off_inventory if n not in followed]
    # A unit the operator has since named, or that went, is theirs or
    # gone: neither is a unit that moved and was left without a tag.
    stray = set(plan.off_inventory) - decided - dropped
    plan.untagged_units = {
        name: where for name, where in (untagged_units or {}).items()
        if name in stray
    }
    plan.unvouched_units = _moved_unvouched(
        plan, stray - set(plan.untagged_units), followed, port_renames,
        fold_source,
    )
    present = set(every)
    plan.displaced = sorted(displaced)
    # An entry for a name the config does not have decided nothing and
    # was ignored by the translator already; listing it here would say
    # a pairing "stands" for a port that is not there.
    plan.ignored_overrides = sorted(k for k in ignored_overrides if k in present)
    plan.emptied_lags = sorted(emptied_lags)
    plan.shrunk_lags = sorted(shrunk_lags)
    plan.lost_routes = list(lost_routes)
    plan.lost_dhcp_pools = list(lost_dhcp_pools)
    plan.lost_tracking = sorted(lost_tracking)
    plan.lost_vtep_sources = sorted(lost_vtep_sources)
    plan.stale_next_hops = list(stale_next_hops)
    # A name the operator has since decided, or that went, is no longer
    # a landing nobody looked at.
    plan.landed_off_target = {
        name: where for name, where in sorted((landed_off_target or {}).items())
        if name not in decided and name not in dropped
    }
    # A port the output does not look up by its hardware at all is
    # said as that, and is on no hardware below.
    nowhere = set(unbound)
    plan.unbound_ports = {
        name: where for name, where in sorted((target_hardware or {}).items())
        if name in nowhere and name not in dropped
    }
    # Which hardware a port is looked up by, where that is not simply
    # the name the port has in the output.
    hardware = {
        name: where for name, where in sorted((target_hardware or {}).items())
        if name not in dropped and name not in nowhere
        and where != port_renames.get(name, name)
    }
    on_target = {name_key(name, fold_target) for name in targets}
    # The field holds hardware the target HAS.  For a port the mapping
    # placed that is its place; for a port nobody placed it is a
    # coincidence of names -- the factory name it had happens to be a
    # port of the target too -- and not a place the mapping chose.
    # Hardware the target lacks is no place; it still counts for a
    # clash.
    plan.target_hardware = {
        name: where for name, where in hardware.items()
        if name_key(where, fold_target) in on_target
    }
    plan.source_hardware = {
        name: where for name, where in hardware.items()
        if name not in plan.target_hardware
    }
    if plan.applied:
        plan.fused = fused_targets(
            every, port_renames, dropped, involving=used,
            fold_source=fold_source, fold_target=fold_target,
        )
        if hardware:
            # Two ports on one piece of hardware under two names share
            # no NAME, and are fused all the same.
            by_hardware = fused_targets(
                every, {**port_renames, **hardware}, dropped, involving=used,
                fold_source=fold_source, fold_target=fold_target,
            )
            for where, sources in by_hardware.items():
                listed = plan.fused.setdefault(where, [])
                # Looked for in a set, kept in the list: a rename map
                # can send every name of a config to one port.
                have = set(listed)
                for name in sources:
                    if name not in have:
                        have.add(name)
                        listed.append(name)

        def listed_by_target(name: str, for_a_unit: bool = False) -> bool:
            if name_key(name, fold_target) in on_target:
                return True
            port, dot, unit = name.strip().rpartition(".")
            # A unit of a port the target lists.  Between two configs
            # of one codec that is a name of the target for any
            # source name.  Across vendors it is one for a source
            # name that is itself a sub-interface: it is where the
            # translator puts a unit, and the plan's line for a unit
            # it does not vouch for says to name the unit in the
            # port map.  Reported as off-target, the entry that did
            # so cleared one line and raised another.
            return bool(
                (units or for_a_unit) and dot and unit.isdigit()
                and name_key(port, fold_target) in on_target
            )

        # A management port the target model lists no place for has no
        # inventory name to go to.  The one name that is not a mistake
        # for it is the form the ordinary translation gives a
        # management port on this target (``oobm``); any other name the
        # device does not list is as off-target as it is for any port.
        forms = {
            source: name_key(form, fold_target)
            for source, form in (management_forms or {}).items() if form
        }
        # An entry whose target is not a port of the device is
        # off-target -- unless it only NAMED a port whose hardware has
        # a place (RouterOS), or a port no line of the output looks
        # up; each of those is said in a line of its own.
        plan.off_target = sorted({
            value for key, value in operator_map.items()
            if isinstance(value, str) and key in present
            and key not in plan.target_hardware
            and key not in plan.unbound_ports
            and not listed_by_target(value, _ends_in_a_unit(key))
            and forms.get(key) != name_key(value, fold_target)
        })
        # Every name that ended somewhere occupies that name -- a
        # logical interface an operator put on a port as much as a
        # hardware port the pairing put there.
        taken = {
            name_key(port_renames.get(name, name), fold_target)
            for name in every if name not in dropped
        }
        taken.update(name_key(where, fold_target) for where in hardware.values())
        plan.unused_target = [
            name for name in targets if name_key(name, fold_target) not in taken
        ]
    plan.unresolved_ports = plan.unresolved(decided)
    if plan.applied:
        plan.warnings = describe_plan(
            plan, decided=decided, dropped=dropped, by_factory_name=by_factory_name,
        )


def what_went_lines(
    prefix: str,
    *,
    emptied_lags: Sequence[str] = (),
    shrunk_lags: Sequence[str] = (),
    lost_routes: Sequence[str] = (),
    lost_dhcp_pools: Sequence[str] = (),
    lost_tracking: Sequence[str] = (),
    lost_vtep_sources: Sequence[str] = (),
    dropped: str = "port",
) -> list[str]:
    """A line for each kind of thing that went with a dropped name.

    One wording for the plan (``port mapping``, where what is dropped
    is a port of a declared device) and for a job with no devices
    (``port_rename``, from the translator's record,
    ``PortRenameResult.taken``, where it can be any interface).  The
    names in a line are not quoted: the migrate page reads a quoted
    name out of a warning as a row of its rename table.

    Args:
        prefix: What the line begins with, before ``": "``.
        emptied_lags: LAGs every member of which was dropped.
        shrunk_lags: LAGs that lost some members.
        lost_routes: The destinations of the static routes removed.
        lost_dhcp_pools: The DHCP pools removed.
        lost_tracking: Interfaces whose VRRP group lost a track entry.
        lost_vtep_sources: The VXLAN source interfaces dropped.
        dropped: What the dropped names are called in the lines.

    Returns:
        The lines, in that order; none for an empty list.
    """
    lines: list[str] = []
    if emptied_lags:
        lines.append(
            f"{prefix}: every member port of {len(emptied_lags)} "
            f"LAG(s) was dropped, so the LAG has no port on the target "
            f"({_summary(emptied_lags)}); review it and the VLANs "
            f"that reference it"
        )
    if shrunk_lags:
        lines.append(
            f"{prefix}: {len(shrunk_lags)} LAG(s) lost a member "
            f"port to a drop and have fewer members on the target: "
            f"{_summary(shrunk_lags)}"
        )
    if lost_routes:
        lines.append(
            f"{prefix}: {len(lost_routes)} static route(s) that "
            f"named a dropped {dropped} were removed with it: "
            f"{_summary(lost_routes)}"
        )
    if lost_dhcp_pools:
        lines.append(
            f"{prefix}: {len(lost_dhcp_pools)} DHCP pool(s) bound "
            f"to a dropped {dropped} were removed with it: "
            f"{_summary(lost_dhcp_pools)}"
        )
    if lost_tracking:
        lines.append(
            f"{prefix}: {len(lost_tracking)} interface(s) lost a "
            f"VRRP track entry with what it named (a dropped {dropped}, or a "
            f"track object number read as one), so failover no longer "
            f"follows it: {_summary(lost_tracking)}"
        )
    if lost_vtep_sources:
        lines.append(
            f"{prefix}: the VXLAN source interface was dropped "
            f"({_summary(lost_vtep_sources)}), so the VTEP is left "
            f"without the source it was bound to — give it one"
        )
    return lines


def _loss_lines(plan: MappingPlan) -> list[str]:
    """Lines for what went with a dropped port, and for a route
    left naming a port that moved."""
    lines = what_went_lines(
        "port mapping",
        emptied_lags=plan.emptied_lags,
        shrunk_lags=plan.shrunk_lags,
        lost_routes=plan.lost_routes,
        lost_dhcp_pools=plan.lost_dhcp_pools,
        lost_tracking=plan.lost_tracking,
        lost_vtep_sources=plan.lost_vtep_sources,
    )
    if plan.stale_next_hops:
        lines.append(
            f"port mapping: {len(plan.stale_next_hops)} static route(s) "
            f"still name, as next hop, an interface that has another name "
            f"in the output, or is not in it "
            f"({_summary(plan.stale_next_hops)}); the next hop was left as "
            f"written — correct the route by hand"
        )
    return lines


def _is_unit_of(name: str, ports: Iterable[str]) -> bool:
    """*name* is ``<port>.<unit>`` for one of *ports*.  A unit suffix
    is a number: ``ether1.backup`` is a name with a dot in it, not a
    sub-interface of ``ether1``."""
    parent, dot, unit = name.rpartition(".")
    return bool(dot and unit.isdigit() and parent in ports)


def _ends_in_a_unit(name: str) -> bool:
    """*name* is written ``<something>.<unit>``, whatever it is a
    unit of."""
    parent, dot, unit = name.rpartition(".")
    return bool(dot and parent and unit.isdigit())


def _moved_unvouched(
    plan: MappingPlan,
    names: Iterable[str],
    followed: Mapping[str, str | None],
    port_renames: Mapping[str, str],
    fold_source: bool,
) -> dict[str, str]:
    """The names among *names* that went where the name before their
    last dot went, although the plan did not take them for a unit of
    it; see :attr:`MappingPlan.unvouched_units`.

    Read from the run: a name is here only if it ended on exactly
    ``<where that name ended>.<unit>``.

    Args:
        plan: The plan; its pairings and unplaced ports are the
            ports of the declared source, as the config names them.
        names: The off-inventory names nobody decided, that were not
            dropped, and that are not units that went without a tag.
        followed: The units the plan does vouch for, each with the
            name it was given.  A unit of one of them is a unit of a
            unit.
        port_renames: ``MigrationJob.port_renames`` of the final run.
        fold_source: Source names compare without regard to case, so
            a unit spelt in another case than its port is that
            port's.

    Returns:
        Each such name with the name it has in the output.
    """
    spelt: dict[str, list[str]] = {}
    for port in [p.source for p in plan.pairings] + [p.source for p in plan.unplaced]:
        spelt.setdefault(name_key(port, fold_source), []).append(port)
    moved: dict[str, str] = {}
    for name in sorted(names):
        parent, dot, unit = name.rpartition(".")
        if not (dot and unit.isdigit()):
            continue
        if followed.get(parent):
            # A unit of a unit: the unit it is written under followed.
            ended = followed[parent]
        else:
            same = spelt.get(name_key(parent, fold_source), [])
            if len(same) != 1 or same[0] == parent:
                # No port, or two spellings of one, or the port spelt
                # as the config spells it -- and a unit written that
                # way which is still here did not go with its port.
                continue
            ended = port_renames.get(same[0], same[0])
        where = f"{ended}.{unit}"
        if port_renames.get(name, name) == where:
            moved[name] = where
    return moved


def _stray_lines(
    plan: MappingPlan, stray: list[str], ports: set[str], gone: set[str],
) -> list[str]:
    """Lines for the names the config uses that are no port of the
    declared source and that nobody decided (*stray*): a name the
    device does not have, a unit that went with its port and took
    no tag with it, a unit that went with its port and that the plan
    does not vouch for, and a unit that did not go with its port.

    Args:
        plan: The plan.
        stray: Those names.
        ports: The ports of the declared source, as the config
            names them.
        gone: The names the run dropped; empty before there has
            been one.
    """
    lines: list[str] = []
    untagged = [n for n in stray if n in plan.untagged_units]
    moved = [
        n for n in stray
        if n in plan.unvouched_units and n not in plan.untagged_units
    ]
    children = [
        n for n in stray
        if n not in plan.untagged_units and n not in plan.unvouched_units
        and _is_unit_of(n, ports)
    ]
    # Looked up in a set: a pasted config can name as many units as
    # it likes, and each is looked up once for every other.
    units = set(children) | set(untagged) | set(moved)
    others = [n for n in stray if n not in units]
    if others:
        lost = sum(1 for n in others if n in gone)
        outcome = "they were left to name-shape translation"
        if lost:
            outcome += f", which dropped {lost} of them"
        lines.append(
            f"port mapping: {len(others)} port name(s) in the config are "
            f"not ports of the declared source device "
            f"({_summary(others)}); {outcome} — check the source model"
        )
    if untagged:
        # These DID move with their port.  What they did not take is
        # a tag, because the parsed source has none for them, and a
        # sub-interface with no VLAN is not one an operator meant.
        shown = [f"{name} -> {plan.untagged_units[name]}" for name in untagged]
        lines.append(
            f"port mapping: {len(untagged)} sub-interface name(s) moved "
            f"with their port, but no 802.1Q tag was read for them from "
            f"the source config, so the output carries no tag of the "
            f"source config for them ({_summary(shown, limit=6, sep='; ')}) "
            f"— look the VLAN id of each up in the source and set it on "
            f"the target, then name the unit in the port map, or drop it"
        )
    if moved:
        # These moved with their port as well, tag and all.  Among
        # the names "left to name-shape translation — check the
        # source model" they would be told neither what happened to
        # them nor what is wrong with them.
        shown = [f"{name} -> {plan.unvouched_units[name]}" for name in moved]
        lines.append(
            f"port mapping: {len(moved)} sub-interface name(s) moved with "
            f"their port ({_summary(shown, limit=6, sep='; ')}), but the "
            f"plan does not vouch for where they went: it takes a name "
            f"for a unit of a port only where the name spells the port "
            f"as the config does, and these are spelt in another letter "
            f"case than their port, or are units of a unit — check each, "
            f"then name it in the port map, or drop it"
        )
    if children:
        # What is still here did not go with its port: across vendors
        # a unit of a port whose kind carries no sub-interface (a
        # management port, by its name or by what its parser read of
        # it), a unit of a port the source codec's classifier does
        # not know (a channelized Junos port), and an interface
        # numbered 0.  A unit that followed is in ``sub_interfaces``
        # and not listed; one that followed with no tag, or that the
        # plan does not vouch for, has a line above.
        lines.append(
            f"port mapping: {len(children)} sub-interface name(s) belong "
            f"to a port of the declared source device but are not ports "
            f"themselves ({_summary(children)}); they were left to "
            f"name-shape translation and did NOT move with their port"
        )
    return lines


def describe_plan(
    plan: MappingPlan,
    *,
    decided: Iterable[str] = (),
    dropped: Iterable[str] | None = None,
    by_factory_name: bool = False,
) -> list[str]:
    """Operator-readable lines for *plan*, one per kind of problem.

    Lines never contain a single quote: the migrate page reads
    single-quoted tokens out of job warnings as extra table rows, so
    an apostrophe inside a port name is written as a typographic one.

    Args:
        plan: The plan.
        decided: Source names the operator's own map names.  A port
            the operator has decided is not reported as a problem.
        dropped: What the run dropped, once there has been a run;
            ``None`` before one, when the lines can only say what is
            intended.
        by_factory_name: The target finds a port by a factory name
            beside its own.  An override target that is not a port is
            then a name, so the line about such targets does not warn
            of another spelling of a port, and a port nobody placed
            that was kept under a name is said in a line of its own.
    """
    seen = set(decided)
    ran = dropped is not None
    gone = set(dropped or ())
    displaced = set(plan.displaced)
    ports = {p.source for p in plan.pairings} | {p.source for p in plan.unplaced}
    lines: list[str] = []

    removed = [
        p for p in plan.used_unplaced
        if p.dropped and p.source not in seen and p.source not in displaced
    ]
    no_member = [p.source for p in removed if p.reason == "no-member"]
    if no_member:
        lines.append(
            f"port mapping: {len(no_member)} source port(s) belong to a "
            f"member with no target member in its position (the target "
            f"lists fewer members) and were DROPPED from the output: "
            f"{_summary(no_member)}"
        )
    for role in ("access", "uplink"):
        overflow = [
            p.source for p in removed
            if p.reason == "no-position" and p.role == role
        ]
        if overflow:
            lines.append(
                f"port mapping: {len(overflow)} source {role} port(s) have "
                f"no {role} port left on the target and were DROPPED from "
                f"the output: {_summary(overflow)}"
            )
    stripped = [
        p.source for p in removed
        if p.reason == "no-position" and p.role == "mgmt"
    ]
    if stripped:
        lines.append(
            f"port mapping: {len(stripped)} source management port(s) "
            f"have no management port in the target model, and the "
            f"target has no other form for one; they were DROPPED from "
            f"the output: {_summary(stripped)}"
        )
    kept = [p for p in plan.used_kept_management if p.source not in seen]
    if kept:
        where = [
            f"{p.source} -> {p.landed}" if p.landed and p.landed != p.source
            else p.source
            for p in kept
        ]
        outcome = (
            "were kept by name-shape translation" if ran
            else "are left to name-shape translation"
        )
        lines.append(
            f"port mapping: {len(kept)} source management port(s) have no "
            f"management port in the target model and {outcome} "
            f"({_summary(where)}); confirm the target has a management "
            f"interface, or drop them"
        )

    folded = sorted(name for name in displaced if _is_unit_of(name, ports))
    clashed = sorted(displaced - set(folded))
    if clashed:
        lines.append(
            f"port mapping: {len(clashed)} name(s) nobody decided would "
            f"have shared a name with another port, or taken a port of "
            f"the target, and were DROPPED from the output instead: "
            f"{_summary(clashed)}"
        )
    if folded:
        lines.append(
            f"port mapping: {len(folded)} sub-interface name(s) could not "
            f"be given a name of their own by name-shape translation and "
            f"were DROPPED from the output instead: {_summary(folded)}"
        )
    # A sub-interface that followed its port to a new name simply
    # moved, which is nothing to report; one that went with a dropped
    # port is.
    went = [name for name, target in plan.sub_interfaces.items() if not target]
    if went:
        lines.append(
            f"port mapping: {len(went)} sub-interface name(s) were DROPPED "
            f"with the port they belong to: {_summary(sorted(went))}"
        )

    stray = [
        n for n in plan.off_inventory if n not in seen and n not in displaced
    ]
    lines.extend(_stray_lines(plan, stray, ports, gone))
    if plan.fused:
        shown = [
            f"{target} <- {', '.join(sources)}"
            for target, sources in plan.fused.items()
        ]
        lines.append(
            f"port mapping: {len(shown)} target port(s) receive more than "
            f"one source port, so their config is merged: "
            f"{_summary(shown, limit=6, sep='; ')}"
        )
    if plan.off_target:
        # What is known is that the name is not one the device model
        # lists.  It may still be a port: an abbreviation the device
        # accepts (Gi1/0/1) is not recognised as the port it names.
        line = (
            f"port mapping: {len(plan.off_target)} override target(s) are "
            f"not names the declared target device lists for its ports: "
            f"{_summary(plan.off_target)}"
        )
        if not by_factory_name:
            # Where a port has one name, a target the model does not
            # list may still BE a port.  Where a port is found by its
            # factory name it cannot: it is a name, and nothing more.
            line += (
                "; if one is another spelling of a port (an abbreviation, "
                "say) it may share that port with the source port already "
                "paired to it — use the names the device model lists"
            )
        lines.append(line)
    # A port the pairing placed "is on" its hardware.  Any other -- one
    # with no place, or a name that is no port of the declared source
    # -- "stays on" hardware nobody chose for it.
    placed = {p.source for p in plan.used_pairings}
    named = [
        f"{name} is on {where}" if name in placed
        else f"{name} stays on {where}, which the mapping did not choose for it"
        for name, where in plan.target_hardware.items() if name in seen
    ]
    if named:
        # Not a problem: a decision the engine took for the operator,
        # between two readings of what they typed.  So it is said.
        lines.append(
            f"port mapping: {len(named)} override target(s) are not ports "
            f"of the declared target device and were taken as NAMES, which "
            f"does not move a port "
            f"({_summary(named, limit=6, sep='; ')}); if a port was meant, "
            f"use a name the device model lists"
        )
    loose = [
        f"{p.source} as {p.landed}" for p in plan.used_unplaced
        if by_factory_name and not p.dropped and p.landed in plan.off_target
        and p.source not in plan.source_hardware
        and p.source not in plan.unbound_ports
    ]
    if loose:
        lines.append(
            f"port mapping: {len(loose)} port(s) the mapping did not place "
            f"were kept under a name no port of the target has; the output "
            f"finds each by that name, or only refers to it "
            f"({_summary(loose, limit=6, sep='; ')}); give each a port of "
            f"the target, or drop it"
        )
    if plan.source_hardware:
        still = [f"{name} by {where}" for name, where in plan.source_hardware.items()]
        lines.append(
            f"port mapping: {len(still)} port(s) the mapping did not place "
            f"are still looked up by the factory name they had on the "
            f"SOURCE device, which the declared target does not have "
            f"({_summary(still, limit=6, sep='; ')}); give each a port of "
            f"the target, or drop it"
        )
    if plan.unbound_ports:
        lost = [f"{name} on {where}" for name, where in plan.unbound_ports.items()]
        lines.append(
            f"port mapping: {len(lost)} port(s) are not "
            f"looked up by their hardware anywhere in the output "
            f"({_summary(lost, limit=6, sep='; ')}) — the target writes no "
            f"line of its own for a port whose name reads as another kind "
            f"of interface (a VLAN, a bridge, a LAG, a loopback), or for a "
            f"port the config has no interface for, and of two ports given "
            f"one name it finds the first; name each with a port of the "
            f"target, or, where the config has an interface for it, with a "
            f"name of its own that does not read that way"
        )
    if plan.landed_off_target:
        shown = [
            f"{name} -> {where}"
            for name, where in plan.landed_off_target.items()
        ]
        lines.append(
            f"port mapping: {len(shown)} logical name(s) nobody decided "
            f"were given a port name the declared target device does not "
            f"list ({_summary(shown, limit=6, sep='; ')}), so their config "
            f"is on a port the device does not have — map or drop each one"
        )
    if plan.ignored_overrides:
        lines.append(
            f"port mapping: {len(plan.ignored_overrides)} override(s) had "
            f"no usable target and were ignored; what the mapping decided "
            f"stands for: {_summary(plan.ignored_overrides)}"
        )
    lines.extend(_loss_lines(plan))

    lines.extend(_member_lines(plan, seen))

    # A pairing the operator replaced is no longer the plan's: its
    # speed and PoE flags describe a target the port did not go to --
    # unless the operator only NAMED the port and its hardware went
    # where the pairing put it.
    paired = [
        p for p in plan.used_pairings
        if p.source not in seen or plan.target_hardware.get(p.source) == p.target
    ]
    slower = [p for p in paired if p.slower]
    if slower:
        lines.append(
            f"port mapping: {len(slower)} port(s) land on a slower target "
            f"port: {_summary([f'{p.source} -> {p.target}' for p in slower])}"
        )
    unpowered = [p for p in paired if p.poe_lost]
    if unpowered:
        lines.append(
            f"port mapping: {len(unpowered)} PoE port(s) land on a target "
            f"port without PoE: "
            f"{_summary([f'{p.source} -> {p.target}' for p in unpowered])}"
        )
    unvouched = [
        side for side, summary in (("source", plan.source), ("target", plan.target))
        if summary is not None and summary.origin == "legacy-profile"
    ]
    if unvouched:
        lines.append(
            f"port mapping: the {' and the '.join(unvouched)} port order "
            f"is the list order of a target profile, which has not been "
            f"checked against the faceplate; review the pairing"
        )
    return lines

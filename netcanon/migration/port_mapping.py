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
  were dropped, whether two source ports ended on one target name —
  and rewrites the plan's warnings to match.  A plan that has not
  been settled describes an intention.

Policy, in order:

1. Members pair by rank — first with first.  A source member beyond
   the target's member count is not folded onto another member.
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
5. Two kinds of name get no entry, and are left to the name-shape
   translator: an unplaced MANAGEMENT port (the translator knows what
   each target does with out-of-band management — on AOS-S that is
   the ``oobm`` block, not an interface), and a name the config uses
   that is not in the declared source inventory at all, which is
   **off-inventory** and is the tripwire for a source model that was
   declared wrongly.

   The hazard of policy 4 applies to these names exactly as it does to
   an unplaced data port: what the translator makes of one may be a
   name the plan assigned to another port.  The mapper cannot know
   that in advance without re-deriving the translator, so the caller
   checks afterwards (:func:`fused_targets`) and drops any such name —
   it is then **displaced**.  See
   :func:`~netcanon.services.migration_pipeline.run_plan_with_models`.
6. Only ports the source config uses are reported as problems.

Pure functions — no I/O, no global state.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping

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
    "plan_port_mapping",
    "settle_plan",
]


def _is_downshift(source_speed: str, target_speed: str) -> bool:
    if source_speed not in SPEED_RANK or target_speed not in SPEED_RANK:
        return False
    return SPEED_RANK[target_speed] < SPEED_RANK[source_speed]


def _summary(names: list[str], limit: int = 8) -> str:
    shown = ", ".join(names[:limit])
    return shown if len(names) <= limit else f"{shown} and {len(names) - limit} more"


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
    counts = Counter(port.name for port in inventory.ports)
    return sorted(name for name, seen in counts.items() if seen > 1)


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

    Returns:
        The plan.  ``rename_map`` holds entries only for used source
        ports, so it can be handed to the translator without naming
        ports the config does not contain.  ``applied`` is ``False``,
        and the map empty, when no pairing can be made: one side lists
        no ports, or lists the same name twice (a position is then not
        a port).
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

    used: set[str] | None = None if used_names is None else set(used_names)
    target_groups = _by_position(target.ports)
    target_members = {p.member_rank for p in target.ports}
    taken: set[str] = set()
    for (rank, role), ports in _by_position(source.ports).items():
        partners = target_groups.get((rank, role), [])
        for position, port in enumerate(ports):
            is_used = used is None or port.name in used
            if position >= len(partners):
                plan.unplaced.append(UnplacedPort(
                    source=port.name,
                    role=port.role,
                    member_rank=rank,
                    position=position,
                    reason="no-position" if rank in target_members else "no-member",
                    used=is_used,
                    dropped=port.role != "mgmt",
                ))
                continue
            match = partners[position]
            taken.add(match.name)
            plan.pairings.append(PortPairing(
                source=port.name,
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

    order = {port.name: at for at, port in enumerate(source.ports)}
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
    used_names: Iterable[str],
    port_renames: Mapping[str, str],
    port_drops: Iterable[str],
) -> dict[str, list[str]]:
    """Target names that more than one used source port ended on.

    Read from what a translation run reports, so it holds whatever
    decided each name: the pairing, an operator override, or the
    name-shape translator.

    Args:
        used_names: The hardware port names the source config uses.
        port_renames: ``MigrationJob.port_renames`` — source name to
            the name it was given, for every name that changed.
        port_drops: ``MigrationJob.port_drops``.

    Returns:
        Target name to its source names (two or more), in the order
        the sources were given.  Empty when every surviving source
        port has a target name of its own.
    """
    dropped = set(port_drops)
    groups: dict[str, list[str]] = {}
    for name in dict.fromkeys(used_names):
        if name in dropped:
            continue
        groups.setdefault(port_renames.get(name, name), []).append(name)
    return {target: names for target, names in groups.items() if len(names) > 1}


def settle_plan(
    plan: MappingPlan,
    *,
    operator_map: Mapping[str, str | None],
    used_names: Iterable[str],
    port_renames: Mapping[str, str],
    port_drops: Iterable[str],
    target_names: Iterable[str],
    displaced: Iterable[str] = (),
    emptied_lags: Iterable[str] = (),
) -> None:
    """Reconcile *plan* with what the translation run actually did.

    :func:`plan_port_mapping` states an intention.  Three things can
    make the outcome differ, and a plan a client reads must describe
    the outcome:

    * the operator's own map replaced plan entries — an unplaced port
      they gave a target was kept, not dropped;
    * the name-shape translator, handed a name the plan left to it,
      dropped that name (a management port on a target that has no
      management interface) rather than renaming it;
    * a name the plan left alone was found to collide with a target
      the plan assigned, and was dropped by the caller.

    Fills ``overridden``, ``displaced``, ``fused``, ``off_target``,
    ``emptied_lags`` and ``unresolved_ports``, sets every used unplaced
    port's ``dropped`` to what happened to it, and rebuilds
    ``warnings``.

    Args:
        plan: The plan to settle, in place.
        operator_map: The operator's own ``port_rename_map``.  A key
            here is the operator deciding that port.
        used_names: The names the plan was made for.
        port_renames: ``MigrationJob.port_renames`` of the final run.
        port_drops: ``MigrationJob.port_drops`` of the final run.
        target_names: Every port name of the declared target.
        displaced: Names dropped because the translator would have put
            them on a target port the plan or the operator assigned.
        emptied_lags: LAGs every member port of which was dropped.
    """
    dropped = set(port_drops)
    decided = set(operator_map)
    for port in plan.unplaced:
        if port.used:
            port.dropped = port.source in dropped
    plan.overridden = sorted(k for k in operator_map if k in plan.rename_map)
    plan.displaced = sorted(displaced)
    plan.fused = fused_targets(used_names, port_renames, dropped)
    if plan.applied:
        on_target = set(target_names)
        plan.off_target = sorted({
            value for value in operator_map.values()
            if isinstance(value, str) and value and value not in on_target
        })
    plan.emptied_lags = sorted(emptied_lags)
    plan.unresolved_ports = plan.unresolved(decided)
    if plan.applied:
        plan.warnings = describe_plan(plan, decided=decided, dropped=dropped)


def describe_plan(
    plan: MappingPlan,
    *,
    decided: Iterable[str] = (),
    dropped: Iterable[str] | None = None,
) -> list[str]:
    """Operator-readable lines for *plan*, one per kind of problem.

    Lines never put a port name in single quotes: the migrate page
    reads quoted names out of job warnings as extra table rows.

    Args:
        plan: The plan.
        decided: Source names the operator's own map names.  A port
            the operator has decided is not reported as a problem.
        dropped: What the run dropped, once there has been a run;
            ``None`` before one, when the lines can only say what is
            intended.
    """
    seen = set(decided)
    ran = dropped is not None
    gone = set(dropped or ())
    displaced = set(plan.displaced)
    lines: list[str] = []

    removed = [
        p for p in plan.used_unplaced
        if p.dropped and p.source not in seen and p.source not in displaced
    ]
    no_member = [p.source for p in removed if p.reason == "no-member"]
    if no_member:
        lines.append(
            f"port mapping: {len(no_member)} source port(s) belong to a "
            f"member the target does not have and were DROPPED from the "
            f"output: {_summary(no_member)}"
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
    management = [
        p.source for p in plan.used_unplaced
        if p.role == "mgmt" and not p.dropped and p.source not in seen
    ]
    if management:
        lines.append(
            f"port mapping: {len(management)} source management port(s) "
            f"have no management port in the target model and were "
            f"translated by name shape instead: {_summary(management)}"
        )
    if displaced:
        names = sorted(displaced)
        lines.append(
            f"port mapping: {len(names)} name(s) the pairing does not "
            f"decide would have landed on a target port that another "
            f"source port holds, and were DROPPED from the output "
            f"instead: {_summary(names)}"
        )

    ports = {p.source for p in plan.pairings} | {p.source for p in plan.unplaced}
    stray = [
        n for n in plan.off_inventory if n not in seen and n not in displaced
    ]
    children = [n for n in stray if "." in n and n.rsplit(".", 1)[0] in ports]
    others = [n for n in stray if n not in children]
    if others:
        lost = sum(1 for n in others if n in gone)
        outcome = "they were left to name-shape translation"
        if ran and lost:
            outcome += f", which dropped {lost} of them"
        lines.append(
            f"port mapping: {len(others)} port name(s) in the config are "
            f"not ports of the declared source device "
            f"({_summary(others)}); {outcome} — check the source model"
        )
    if children:
        lines.append(
            f"port mapping: {len(children)} sub-interface name(s) belong "
            f"to a port of the declared source device but are not ports "
            f"themselves ({_summary(children)}); they were left to "
            f"name-shape translation and did NOT move with their port"
        )
    if plan.fused:
        shown = [
            f"{target} <- {', '.join(sources)}"
            for target, sources in plan.fused.items()
        ]
        more = f" and {len(shown) - 6} more" if len(shown) > 6 else ""
        lines.append(
            f"port mapping: {len(shown)} target port(s) receive more than "
            f"one source port, so their config is merged: "
            f"{'; '.join(shown[:6])}{more}"
        )
    if plan.off_target:
        lines.append(
            f"port mapping: {len(plan.off_target)} override target(s) are "
            f"not ports of the declared target device: "
            f"{_summary(plan.off_target)}"
        )
    if plan.emptied_lags:
        lines.append(
            f"port mapping: every member port of {len(plan.emptied_lags)} "
            f"LAG(s) was dropped, so the LAG has no port on the target "
            f"({_summary(plan.emptied_lags)}); review it and the VLANs "
            f"that reference it"
        )

    # A pairing the operator replaced is no longer the plan's: its
    # speed and PoE flags describe a target the port did not go to.
    kept = [p for p in plan.used_pairings if p.source not in seen]
    slower = [p for p in kept if p.slower]
    if slower:
        lines.append(
            f"port mapping: {len(slower)} port(s) land on a slower target "
            f"port: {_summary([f'{p.source} -> {p.target}' for p in slower])}"
        )
    unpowered = [p for p in kept if p.poe_lost]
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

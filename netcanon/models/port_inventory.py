"""
Port inventories, deployments and mapping plans — the data shapes.

Pure Pydantic, no behaviour and no imports from the migration engine,
so both the engine (:mod:`netcanon.migration.device_models`,
:mod:`netcanon.migration.port_mapping`) and the API models
(:mod:`netcanon.models.migration`) can depend on it.

* What an operator declares: :class:`MemberSpec`, :class:`DeploymentSpec`
  (and :class:`Deployment`, the same with the vendor filled in).
* What a deployment compiles to: :class:`Inventory`, a list of
  :class:`PhysicalPort`, with :class:`InventoryMember` saying what each
  declared member resolved to.
* What pairing two inventories produces: :class:`MappingPlan`, made of
  :class:`PortPairing` and :class:`UnplacedPort`.

The behaviour lives beside the codecs; see those two modules.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints

#: How well a port name is established.  Strongest first:
#:
#: * ``capture`` — a committed real capture of that exact device, in
#:   that exact state, shows it; a test re-proves it on every run.
#: * ``vendor-doc`` — established from published sources: the vendor's
#:   own documentation and/or public real-device output that is not
#:   committed here.  Nothing re-checks it.
#: * ``inferred`` — derived by analogy, or doubtful.  Always carries a
#:   caveat saying what is unverified.
EvidenceGrade = Literal["capture", "vendor-doc", "inferred"]

PortRole = Literal[
    "access",  # a user-facing port on the fixed panel
    "uplink",  # a fabric / uplink port, fixed or on a module
    "mgmt",    # out-of-band management
]

#: Weakest first.  An ungraded part (``None``) is weaker than all.
_GRADE_ORDER: tuple[str, ...] = ("inferred", "vendor-doc", "capture")

#: Upper bound on the members of one deployment.  The largest real
#: stack is in the low tens.
MAX_DEPLOYMENT_MEMBERS = 64

#: Upper bound on the length of a model key, mode name, bay name or
#: module SKU in a declaration, and on the bays one member may state.
#: A declaration selects from loaded data; nothing real is this long.
MAX_DECLARED_NAME = 128
MAX_DECLARED_BAYS = 32

_DeclaredName = Annotated[str, StringConstraints(max_length=MAX_DECLARED_NAME)]


def weakest_grade(grades: list[EvidenceGrade | None]) -> EvidenceGrade | None:
    """The weakest of *grades*; ``None`` if any is ungraded or none given.

    Ungraded is not skipped: "not yet graded" is not a clean bill of
    health, so one ungraded part makes the whole ungraded.
    """
    if not grades or any(g is None for g in grades):
        return None
    return min(grades, key=_GRADE_ORDER.index)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Inventory — what a deployment compiles to
# ---------------------------------------------------------------------------


class PhysicalPort(BaseModel):
    """One port that exists on a deployed device, by its real name."""

    model_config = ConfigDict(frozen=True)

    name: str
    """The literal name the device uses in this deployment —
    ``49``, ``1/A1``.  Written verbatim into a generated config."""

    member_rank: int | None = 0
    """0-based position of the owning member within the deployment.
    Pairing uses this, never :attr:`member_id`: vendor member ids are
    sticky and sparse (a lone ex-member can be ``3/N``), so "the
    second member" is an ordinal, not an id.  ``None`` is reserved for
    a port that belongs to the deployment as a whole rather than to one
    member (a stack's single management interface)."""

    member_id: int | None = None
    """The vendor's member id that went into the name.  ``None`` when
    the mode names ports without one — and also for a port read from a
    legacy target profile, where the id is not known separately from
    the name."""

    role: PortRole
    """What the port is for.  Ports pair role to role."""

    ordinal: int
    """0-based position, in port-number order, within
    ``(member_rank, role)``: fixed-panel ports first, then each bay's
    ports in the order the model declares its bays.  Port-number
    order is not left-to-right on the panel.  A derived convenience — the facts are
    :attr:`slot` and :attr:`index`.  A mapper pairs on rank among the
    ports it considers eligible, computed when it pairs, and must not
    assume two inventories number the same ports."""

    slot: str = ""
    """Naming bank the port sits in: ``""`` for the main fixed panel,
    a fixed bank's name, or the bay name for a module port."""

    index: int = 0
    """0-based position within :attr:`slot`."""

    module: str = ""
    """SKU of the module that contributes the port; ``""`` for the
    chassis."""

    speed: str = ""
    """Maximum speed (``gig``, ``10gig``, ...).  A closed vocabulary
    for a family-compiled port, free text when read from a legacy
    profile.  Compare through
    :data:`netcanon.migration.device_models.SPEED_RANK` only."""

    cage: str = ""
    """Physical form (``rj45``, ``sfp+``, ``qsfp+``, ``combo`` ...).
    Empty when not stated — which is deliberate wherever the position
    of a cage type on the panel is not established."""

    poe: bool = False
    notes: str = ""

    evidence: EvidenceGrade | None = None
    """How well THIS port's name is established: the weakest of the
    facts that produced it, or ``capture`` when a capture claim covers
    it exactly.  ``None`` for a port read from an ungraded legacy
    profile."""


class InventoryMember(BaseModel):
    """What one declared member resolved to."""

    model_config = ConfigDict(frozen=True)

    rank: int
    member_id: int | None = None
    model: str
    """The registry key the member resolved to — never the SKU the
    caller typed."""

    display_name: str = ""
    modules: dict[str, str] = Field(default_factory=dict)
    """Bay name to fitted module SKU.  Empty bays are omitted."""

    unstated_bays: list[str] = Field(default_factory=list)
    """Bays the deployment did not mention.  They were compiled as
    empty; "not stated" is kept apart from "stated empty" because a
    source config often cannot say which module is fitted."""

    evidence: EvidenceGrade | None = None
    """Weakest grade among this member's ports."""


class InventorySummary(BaseModel):
    """An :class:`Inventory` without its port list.

    What a response echoes back so a client can show which model, mode
    and member ids were actually used — a deployment may leave the mode
    and the ids to defaults.
    """

    vendor: str
    origin: Literal["family", "legacy-profile"] = "family"
    """``family`` — compiled from a model family through a naming
    rule.  ``legacy-profile`` — read from a flat target profile: the
    names are that profile's literal list and the ORDER is its YAML
    list order, which nobody has checked against the hardware's own
    port numbering."""

    family: str = ""
    """Family key (``aruba_aoss/2930M``); ``""`` for a legacy profile."""

    mode: str = ""
    """The mode that was compiled — resolved, so a deployment that
    left it out can be told which one it got."""

    mode_label: str = ""
    mode_defaulted: bool = False
    """The deployment did not state a mode and the family's default
    was used.  The mode decides every name, so this is surfaced."""

    members: list[InventoryMember] = Field(default_factory=list)
    description: str = ""
    """One line an operator would recognise: model(s), fitted
    modules and the deployment mode."""

    port_count: int = 0

    evidence: EvidenceGrade | None = None
    """The weakest grade among the ports PRESENT.  ``None`` when any
    is ungraded, or when there are no ports at all.

    It grades the names that are listed, not the list.  A model
    compiled with a bay empty can be ``capture`` on the strength of
    a capture that had a module fitted there: every name present was
    seen.  It does not say the device has no other port."""

    evidence_refs: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


class Inventory(InventorySummary):
    """The ordered ports of one deployment, with how well they are known."""

    ports: list[PhysicalPort] = Field(default_factory=list)

    def names(
        self,
        role: PortRole | None = None,
        member_rank: int | None = None,
    ) -> list[str]:
        """Port names in inventory order, optionally filtered."""
        return [
            p.name for p in self.ports
            if (role is None or p.role == role)
            and (member_rank is None or p.member_rank == member_rank)
        ]

    def port(self, name: str) -> PhysicalPort | None:
        """The port called *name*, or ``None``."""
        for p in self.ports:
            if p.name == name:
                return p
        return None

    @property
    def member_count(self) -> int:
        return len(self.members)

    def summary(self) -> InventorySummary:
        """This inventory without its port list."""
        data = self.model_dump(exclude={"ports"})
        data["port_count"] = len(self.ports)
        return InventorySummary(**data)


# ---------------------------------------------------------------------------
# Deployment — what the operator declares
# ---------------------------------------------------------------------------


class MemberSpec(BaseModel):
    """One device in a deployment: a model and what is fitted to it."""

    model_config = ConfigDict(extra="forbid")

    model: _DeclaredName
    """Model key within the vendor (``2930M-48G-PoEP``).  A SKU the
    model lists (``JL322A``, any case) resolves too."""

    id: StrictInt | None = None
    """The vendor's member id.  ``None`` takes the lowest free id of
    the mode's range, so a deployment that lists three members with
    no ids gets 1, 2, 3.  Must be ``None`` in a mode whose names
    carry no member id.  An integer and nothing else: ``"2"``,
    ``2.0`` and ``true`` are refused rather than read as one."""

    modules: dict[_DeclaredName, _DeclaredName | None] = Field(
        default_factory=dict, max_length=MAX_DECLARED_BAYS,
    )
    """Bay name (any case) to fitted module SKU.  ``None`` or ``""``
    states the bay is EMPTY — a real and common configuration.  A bay
    that is not mentioned at all is compiled as empty too, but is
    reported back as *not stated*
    (:attr:`InventoryMember.unstated_bays`)."""


class DeploymentSpec(BaseModel):
    """A device, or a stack of them, in one stated deployment mode.

    The form a request carries: the vendor is not repeated, because it
    is the vendor of the codec the request already names.
    """

    model_config = ConfigDict(extra="forbid")

    mode: _DeclaredName | None = None
    """A mode the model's family defines (any case).  ``None`` or an
    empty string takes the family's default, and the response says
    which that was (:attr:`InventorySummary.mode_defaulted`)."""

    members: list[MemberSpec] = Field(
        min_length=1, max_length=MAX_DEPLOYMENT_MEMBERS,
    )
    """Ordered.  A member's rank is its position in this list."""


class Deployment(DeploymentSpec):
    """A :class:`DeploymentSpec` with its vendor."""

    vendor: str
    """Vendor id — the ``vendor_id`` of a codec's capability matrix,
    which is also ``TargetProfile.vendor``.  NOT a codec name: the two
    differ (``fortigate`` is the vendor of codec ``fortigate_cli``;
    ``cisco_iosxe`` is the vendor of two codecs)."""


# ---------------------------------------------------------------------------
# Mapping plan — what pairing two inventories produces
# ---------------------------------------------------------------------------

UnplacedReason = Literal[
    "no-member",    # the target has no member at this rank
    "no-position",  # the target member has fewer ports in this role
]


class PortPairing(BaseModel):
    """One source port paired with the target port in its position."""

    source: str
    target: str
    role: PortRole
    member_rank: int | None
    position: int
    """0-based position within ``(member_rank, role)`` at which the
    two were paired."""

    used: bool = True
    """The source config references this port."""

    source_speed: str = ""
    target_speed: str = ""

    slower: bool = False
    """The target port's maximum speed is below the source port's.
    Set only when both speeds are stated in the known vocabulary; an
    unstated speed is unknown, not equal."""

    poe_lost: bool = False
    """The source port supplies PoE and the target port does not."""

    evidence: EvidenceGrade | None = None
    """The weaker of the two port NAMES' grades.  It says how well
    each end's name is established.  It does not grade the pairing:
    that this port is an uplink, and so pairs with an uplink, is a
    fact about the panel that no capture proves, so a ``capture``
    here is not "this mapping was observed"."""


class UnplacedPort(BaseModel):
    """A source port that has no position on the target."""

    source: str
    role: PortRole
    member_rank: int | None
    position: int
    reason: UnplacedReason
    used: bool = True

    dropped: bool = True
    """The port is removed from the output.

    As planned, that is every unplaced port but a management port:
    the name-shape translator knows what each target does with
    out-of-band management (AOS-S has no management INTERFACE at all
    — it has an ``oobm`` block), so an unplaced management port is
    left to it rather than deleted.

    Once a translation has run, this is what HAPPENED to a used
    port (:func:`~netcanon.migration.port_mapping.settle_plan`):
    ``False`` for an unplaced port the operator gave a target, and
    ``True`` for a management port the translator could not express
    on the target and dropped, or that was displaced."""


class MappingPlan(BaseModel):
    """The outcome of pairing a source inventory with a target inventory."""

    applied: bool = True
    """``False`` when no positional mapping was made — one side has no
    ports to pair (a generic profile that lists none).  The rename map
    is then empty and everything is left to the name-shape translator;
    :attr:`warnings` says why."""

    source: InventorySummary | None = None
    """What the declared source resolved to."""

    target: InventorySummary | None = None
    """What the declared target resolved to."""

    pairings: list[PortPairing] = Field(default_factory=list)
    """Every source port that has a target position, in source order."""

    unplaced: list[UnplacedPort] = Field(default_factory=list)
    """Every source port that has none, in source order."""

    off_inventory: list[str] = Field(default_factory=list)
    """Names the source config uses that are not ports of the declared
    source inventory, sorted.  Left to the name-shape translator."""

    unused_target: list[str] = Field(default_factory=list)
    """Target ports nothing was paired onto, in target order."""

    rename_map: dict[str, str | None] = Field(default_factory=dict)
    """What to hand the translator, for every USED source port the plan
    decides: a paired port maps to its target name (including when the
    two names are equal — an explicit entry stops the name-shape
    translator re-deciding it); an unplaced port maps to ``None``, an
    explicit drop.  Off-inventory names are absent, and so is an
    unplaced management port (see :attr:`UnplacedPort.dropped`)."""

    overridden: list[str] = Field(default_factory=list)
    """Source ports whose plan entry an operator override replaced,
    sorted.  Filled in when the plan is settled against a run."""

    displaced: list[str] = Field(default_factory=list)
    """Names the plan left to the name-shape translator — an
    off-inventory name, an unplaced management port — that the
    translator would have put on a target port another source port
    holds.  They were dropped from the output instead, sorted.
    Filled in when the plan is settled against a run."""

    fused: dict[str, list[str]] = Field(default_factory=dict)
    """Target names that more than one used source port ended on,
    each with those source ports.  The pairing never produces one
    and a displaced name is dropped before it can, so what is left
    here is an operator override that points two ports at one name.
    The job is ``partial`` while this is not empty."""

    off_target: list[str] = Field(default_factory=list)
    """Operator override targets that are not ports of the declared
    target device, sorted.  Reported; an operator may mean it."""

    emptied_lags: list[str] = Field(default_factory=list)
    """LAGs of the source config every member port of which was
    dropped, sorted.  The LAG then has no port on the target."""

    unresolved_ports: list[str] = Field(default_factory=list)
    """Used source names that still need a decision, sorted: a port
    dropped because it had no place, an off-inventory name, a
    displaced name — minus those the operator's own map names.  The
    job is ``partial`` while this is not empty.  Stored, so a client
    does not have to re-derive the rule (see :meth:`unresolved`)."""

    evidence: EvidenceGrade | None = None
    """The weaker of the two inventories' grades; ``None`` when either
    is ungraded.  Like :attr:`PortPairing.evidence` it grades the
    port names at each end, not the pairing between them."""

    caveats: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    """Operator-readable lines, one per kind of problem found.  They
    never put a port name in single quotes: the migrate page reads
    quoted names out of job warnings as extra table rows."""

    @property
    def used_pairings(self) -> list[PortPairing]:
        return [p for p in self.pairings if p.used]

    @property
    def used_unplaced(self) -> list[UnplacedPort]:
        return [p for p in self.unplaced if p.used]

    @property
    def used_dropped(self) -> list[UnplacedPort]:
        """Used source ports the plan removes from the output."""
        return [p for p in self.unplaced if p.used and p.dropped]

    @property
    def is_clean(self) -> bool:
        """A mapping was made and nothing about it needs a decision:
        no used source port is dropped, off-inventory or displaced,
        and no target port received two source ports."""
        return (
            self.applied
            and not self.used_dropped
            and not self.off_inventory
            and not self.displaced
            and not self.fused
        )

    def unresolved(self, acknowledged: set[str] | None = None) -> list[str]:
        """Used source names the plan could not place or account for,
        minus those an operator has decided themselves.

        An unplaced port is dropped from the output; an off-inventory
        name was left to the name-shape translator.  Either is a loss
        or a doubt the operator has not yet looked at — unless their
        own override map names the port, which is them looking at it.
        A displaced name is always unresolved: it is displaced only
        because no map named it.

        The pipeline stores the result on :attr:`unresolved_ports`.
        """
        seen = acknowledged or set()
        names = {p.source for p in self.used_dropped} | set(self.off_inventory)
        return sorted({n for n in names if n not in seen} | set(self.displaced))

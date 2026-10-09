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
    """Bay name to fitted module SKU.  Empty bays are omitted.  A
    target profile has no bays, only a choice of module: read as an
    inventory it reports that choice under the key ``module``."""

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
    """Where each fact came from.  A capture is cited by its path in
    the netcanon source tree (``tests/fixtures/real/...``), which an
    installed wheel or image does not contain; a document by its
    title and number."""

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
    """Ordered.  A member's rank is its position in this list, and
    two stacks are paired member by member in that order: the first
    member listed for the source with the first listed for the target,
    whatever their member ids are.  List them in the order they are
    to be paired."""


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

    landed: str = ""
    """The name a used port that was NOT dropped ended under, once a
    translation has run: the operator's target, or what the
    name-shape translator made of a management port (``oobm`` on
    AOS-S).  ``""`` for a dropped port and before any run."""


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
    """Every source port that has a target position, in source order —
    the pairing AS MADE, before the operator's own map.  A port named
    in :attr:`overridden` went where the operator sent it, and its
    ``slower`` / ``poe_lost`` flags describe a target it did not go
    to.  ``MigrationJob.port_renames`` and ``port_drops`` say what
    every name ended as; on RouterOS, where a port can be on one
    piece of hardware under another name, :attr:`target_hardware`
    says where such a port's hardware is.  A source port is named
    here as the CONFIG names it (:attr:`labelled_ports`)."""

    unplaced: list[UnplacedPort] = Field(default_factory=list)
    """Every source port that has none, in source order."""

    off_inventory: list[str] = Field(default_factory=list)
    """Names the source config uses that are not ports of the declared
    source inventory, sorted.  Left to the name-shape translator."""

    labelled_ports: dict[str, str] = Field(default_factory=dict)
    """Source ports the config knows by a name of its own: the
    config's name to the port's name in the device model.  RouterOS
    keeps a port's factory name (``ether2``) beside the name an
    operator gave it (``core-a``), and every other line of the config
    uses the second.  Such a port is PAIRED by its factory name and
    appears under the config's name everywhere else: in
    :attr:`pairings`, in :attr:`rename_map`, in the job's lists, and
    as the key of an operator's ``port_rename_map`` entry."""

    unused_target: list[str] = Field(default_factory=list)
    """Target ports no used source port ended on, in target order.
    Before a run: the ports nothing was paired onto.  After one: the
    ports still free once the operator's map was applied — what a
    client may offer as a place for an unplaced port."""

    rename_map: dict[str, str | None] = Field(default_factory=dict)
    """What to hand the translator, for every USED source port the plan
    decides: a paired port maps to its target name (including when the
    two names are equal — an explicit entry stops the name-shape
    translator re-deciding it); an unplaced port maps to ``None``, an
    explicit drop.  Off-inventory names are absent, and so is an
    unplaced management port (see :attr:`UnplacedPort.dropped`).
    Like :attr:`pairings` this is the map as made, before the
    operator's own entries and before :attr:`sub_interfaces`."""

    overridden: list[str] = Field(default_factory=list)
    """Source ports whose plan entry an operator override replaced,
    sorted.  Filled in when the plan is settled against a run."""

    sub_interfaces: dict[str, str | None] = Field(default_factory=dict)
    """Sub-interface names (``ge-0/0/0.54``) that followed their
    parent port: source name to the name it was given, or ``None``
    when the parent was dropped and the sub-interface with it.  Made
    only between two configs of the SAME codec, where the unit
    suffix means the same thing on both sides; across codecs a
    sub-interface stays in :attr:`off_inventory`."""

    displaced: list[str] = Field(default_factory=list)
    """Names nobody decided — an off-inventory name, an unplaced
    management port, or a LOGICAL name such as an aggregate — that
    the name-shape translator would have put on a name another
    source name ends on, or on a port of the declared target.  They
    were dropped from the output instead, sorted.  Where every name
    in such a clash was undecided, one keeps the name — a port of the
    declared source if there is one, else a hardware port, else the
    first — and only the others are displaced.  Filled in when the
    plan is settled against a run."""

    fused: dict[str, list[str]] = Field(default_factory=dict)
    """Target names that more than one source name ended on, each
    with those names, where at least one of them is a hardware port
    the config uses.  Read from the finished run over every name
    the config references, compared as the two platforms compare
    names (without regard to case where another case cannot be
    another interface).
    The pairing never produces one and an undecided name is
    displaced before it can, so an entry here comes from an
    operator override that points two names at one.  A port is
    counted where its hardware is (:attr:`target_hardware`), so two
    ports on one piece of hardware under two names are here as
    well.  The converse
    does not hold for a target the device model does not list:
    see :attr:`off_target`.  The job is ``partial`` while this is
    not empty."""

    off_target: list[str] = Field(default_factory=list)
    """Names an operator override put a port on that the declared
    target device does not list for its ports, sorted.  Reported; an
    operator may mean it.  Names are compared by case and
    surrounding space only: an abbreviation the device would
    accept (``Gi1/0/1``) is not recognised as the port it names,
    is listed here, and can share that port with the source port
    paired to it without appearing in :attr:`fused`.  Between two
    configs of one codec a unit of a listed port
    (``ge-0/0/7.54``) is not off-target.  On a RouterOS target an
    entry whose target is not a port NAMES the port; while the
    port's hardware has a place (:attr:`target_hardware`) the name
    is not listed here, and the plan says in a line of its own that
    it was taken as a name."""

    target_hardware: dict[str, str] = Field(default_factory=dict)
    """Source names whose port is on a target port that is not the
    name they have in the output: source name to that target port.
    Only on a target that finds a port by a factory name beside its
    own (RouterOS).  A port an operator named in a RouterOS config
    keeps the name, and an operator's entry whose target is not a
    port of the declared target NAMES the port — from any source
    vendor; in both cases the hardware goes where the pairing put it
    (``set [ find default-name=sfp-sfpplus2 ] name=core-a``).
    ``MigrationJob.port_renames`` records names, so it has no entry
    for such a move; this field does.  :attr:`fused` and
    :attr:`unused_target` count a port where its hardware is.  A port
    nobody placed keeps the factory name it had: it is here if the
    target has a port of that name, and in :attr:`source_hardware` if
    it has not."""

    source_hardware: dict[str, str] = Field(default_factory=dict)
    """Source names whose port nobody placed and which the output
    still looks up by the factory name the port had on the SOURCE
    device, under another name: source name to that factory name.
    The declared target has no such port.  Two ways: an operator's
    entry NAMES a port the mapping could not place (it is also in
    :attr:`off_target`, by the name they typed), or the config names
    a port that is not a port of the declared source.  Between two
    configs of one codec only, on a target that finds a port by a
    factory name (RouterOS)."""

    unbound_ports: dict[str, str] = Field(default_factory=dict)
    """Source names of ports that no line of their own in the
    output looks up by their hardware: source name to that hardware.
    Read back from the rendered output with the target's own parser,
    on a target that finds a port by a factory name (RouterOS).  Two
    ways.  The port's name reads to the target as another kind of
    interface — the RouterOS renderer writes no Ethernet line for a
    name shaped like a VLAN, a bridge, a LAG or a loopback
    (``bond1``, ``bridge-uplink``, ``vlan-trunk``, ``uplink.10``,
    ``lo0``), whoever chose the name.  Or the config has no interface
    for the port — it names it only as a LAG member or in a route —
    and an entry gave it a name that is no port of the target, which
    the output then uses and nothing defines.  Such a port is in
    neither :attr:`target_hardware` nor :attr:`source_hardware`, nor
    is its name in :attr:`off_target`, and the job is ``partial``
    while this is not empty: name the port with a port of the target,
    or — where the config has an interface for it — with a name that
    does not read that way."""

    landed_off_target: dict[str, str] = Field(default_factory=dict)
    """Logical names nobody decided — a VLAN interface, say — that
    the name-shape translator gave a port-shaped name the declared
    target device does not list: source name to that name.  Its
    config is then on a port the device does not have.  Nothing
    shares the name, so it is not dropped; it needs a decision
    (:attr:`unresolved_ports`)."""

    stale_next_hops: list[str] = Field(default_factory=list)
    """Destinations of static routes whose next hop names an
    interface that has another name in the output, or is gone.  A
    next hop that is exactly an interface name follows that
    interface; a list of them (RouterOS ``gateway=ether1,ether2``), a
    routing-table suffix (``ether3@main``), and — across vendors — a
    unit of an interface (Junos ``next-hop et-0/0/24.0``) are left as
    written, and so is a next hop naming a port of the declared
    source that the config has no interface for.  A list whose
    members only changed places among themselves is not listed.  The
    job is ``partial`` while this is not empty.  No entry rewrites
    the route: correct it in the output, or keep the names it uses —
    an entry that gives each such port its old name leaves the route
    right where a name does not decide a port's hardware (RouterOS),
    and elsewhere leaves the port under a name the target does not
    list, which is reported."""

    ignored_overrides: list[str] = Field(default_factory=list)
    """Source names the config uses whose operator override had no
    usable target — blank, or not text.  Such an entry decides
    nothing (a blank would render a port with no name), so it was
    set aside and what the mapping decided stands."""

    emptied_lags: list[str] = Field(default_factory=list)
    """LAGs of the source config every member port of which was
    dropped, sorted.  The LAG then has no port on the target."""

    shrunk_lags: list[str] = Field(default_factory=list)
    """LAGs that lost some, not all, of their member ports to drops."""

    lost_routes: list[str] = Field(default_factory=list)
    """Destinations of static routes that named a dropped port — as
    their interface, or as a next hop that is an interface name.
    The translator removes such a route with the port — whole, even
    when it also has a next-hop address."""

    lost_dhcp_pools: list[str] = Field(default_factory=list)
    """DHCP pools (by network, else by interface) bound to a dropped
    port, and removed with it."""

    lost_tracking: list[str] = Field(default_factory=list)
    """Interfaces that survive but whose VRRP group tracked a dropped
    port, sorted.  The track entry was removed with the port, so
    failover on that interface no longer follows it."""

    lost_vtep_sources: list[str] = Field(default_factory=list)
    """VXLAN source interfaces that were dropped, sorted.  The
    VTEP's binding to that interface went with it; depending on the
    target the output then has no source for the VTEP, or names a
    default one that the output does not define."""

    unresolved_ports: list[str] = Field(default_factory=list)
    """Used source names that still need a decision, sorted: a port
    dropped because it had no place, a management port kept by the
    name-shape translator although the target lists none, an
    off-inventory name, a displaced name, a name in
    :attr:`landed_off_target` — minus those the operator's own map
    names.  The
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
    def used_kept_management(self) -> list[UnplacedPort]:
        """Used management ports with no management port on the
        target that were kept — handed to the name-shape translator.
        Whether the target has a management interface at all is not
        something the plan knows, so each needs the operator's eye."""
        return [
            p for p in self.unplaced
            if p.used and p.role == "mgmt" and not p.dropped
        ]

    @property
    def is_clean(self) -> bool:
        """A mapping was made and nothing about it needs a decision:
        :attr:`unresolved_ports` is empty, no target port received
        two source ports, no route still names a port that moved
        (:attr:`stale_next_hops`), and no port was found without a
        line of the output that looks it up by its hardware
        (:attr:`unbound_ports`).  This is the condition under which
        the port mapping leaves a job ``completed``."""
        return (
            self.applied and not self.unresolved_ports and not self.fused
            and not self.stale_next_hops and not self.unbound_ports
        )

    def unresolved(self, acknowledged: set[str] | None = None) -> list[str]:
        """Used source names the plan could not place or account for,
        minus those an operator has decided themselves.

        An unplaced data port is dropped from the output; an unplaced
        management port and an off-inventory name were left to the
        name-shape translator.  Each is a loss or a doubt the
        operator has not yet looked at — unless their own override
        map names the port, which is them looking at it.  A displaced
        name is always unresolved, and so is one in
        :attr:`landed_off_target`: each is there only because no map
        named it.

        The pipeline stores the result on :attr:`unresolved_ports`.
        """
        seen = acknowledged or set()
        names = {p.source for p in self.used_unplaced} | set(self.off_inventory)
        return sorted(
            {n for n in names if n not in seen}
            | set(self.displaced) | set(self.landed_off_target)
        )

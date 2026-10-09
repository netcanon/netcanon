"""
Device models — what ports a device actually has, by name.

A port's name is not a property of the port alone.  It depends on the
model, on which modules are fitted, and on how the device is deployed:
an Aruba 2930F port is ``24`` standalone and ``1/24`` as a VSF member;
a 2930M's first uplink is ``A1`` with stacking disabled and ``1/A1``
with it enabled, and does not exist at all when the bay is empty.  No
rule over the *shape* of a name can recover those facts, which is why
cross-vendor port translation by name shape alone cannot be correct
(see ``ARCHITECTURE.md``, "Device models and inventories").

This module holds the other approach: describe each end of a migration
as a **deployment**, compile it to an **inventory** — the ordered list
of physical ports that exist, each with its real name — and let a later
stage (:mod:`netcanon.migration.port_mapping`) pair two inventories by
position instead of guessing from names.

Vocabulary:

* **family** — one YAML file under
  ``definitions/library/model_families/``: models that share a naming
  rule, a set of deployment modes and a set of modules
  (:class:`FamilyDef`).
* **model** — one SKU's fixed front panel plus the module bays it has
  (:class:`ModelDef`).
* **mode** — a deployment state that changes how ports are named
  (:class:`ModeDef`): ``standalone`` versus ``vsf`` on a 2930F.
* **deployment** — a mode plus an ordered list of members, each a
  model with its fitted modules (:class:`Deployment`).
* **inventory** — what a deployment compiles to
  (:class:`Inventory`, a list of :class:`PhysicalPort`).
* **naming rule** — a small pure function, kept beside the vendor's
  codec, that renders one port's name from its coordinates
  (:class:`NamingRuleSpec`).  The model data says how many ports there
  are and in what order; the rule says what they are called.

Family YAML shape::

    schema: 1
    vendor: aruba_aoss
    family: 2930F
    display_name: "Aruba 2930F"
    naming: aoss
    default_mode: standalone
    modes:
      standalone:
        label: "standalone (VSF disabled)"
        naming: {grade: vendor-doc, ref: "..."}
      vsf:
        label: "VSF enabled"
        member_ids: [1, 8]          # names carry the member id
        naming: {grade: vendor-doc, ref: "..."}
    models:
      2930F-48G-4SFP:
        skus: [JL260A]
        display_name: "Aruba 2930F-48G-4SFP (JL260A)"
        panel: {grade: vendor-doc, ref: "..."}
        ports:                      # fixed front panel, PORT-NUMBER order
          - {role: access, count: 48, speed: gig, cage: rj45}
          - {role: uplink, count: 4,  speed: gig, cage: sfp}
    captures:
      - fixture: tests/fixtures/real/aruba_aoss/....cfg
        marker: "module 1 type jl260a"
        mode: standalone
        members: [{model: 2930F-48G-4SFP}]

A family with swappable modules adds ``modules:`` (keyed by SKU) and a
per-model ``bays:`` mapping; see :class:`ModuleDef` and
:class:`BayDef`.

Evidence.  How well a port's name is established is graded with the
vocabulary of :data:`~netcanon.migration.target_profiles.ProfileEvidence`,
but not per model: a name is the product of separately evidenced
facts, and each is graded where it is stated.

* a mode's ``naming`` — "in this state a fixed port is ``M/N``";
* a mode's ``bay_naming`` — the same for a port in a module bay, when
  that is established less well than the fixed panel;
* a model's ``panel`` — "this SKU has these ports, numbered in this
  order" (port-number order, which is not left-to-right on the
  panel: a 2930F's SFP cages are leftmost and numbered last);
* a module's ``inventory`` — "this module has four ports".

A port's grade is the weakest of the facts that produced it.  None of
those four may be ``capture``: a capture is a checked claim about ONE
deployment — this model, in this mode, as this member, with these
modules — so it is **granted**, by a :class:`CaptureClaim` that matches
exactly, and never inherited by a sibling model, another member id or a
module the capture does not show.  ``tests/unit/migration/
test_device_models_shipped.py`` re-proves every claim against its
fixture on every run — which is what the grade means, so only the
claims that test re-proves grant it (:data:`PROVEN_CAPTURE_CLAIMS`).
A claim in an operator's own family file is read and grants nothing.

This data describes the hardware and never the formatter — the rule in
``AGENTS.md`` on where a port id may come from applies here exactly as
it does to target profiles.

Nothing here touches the translation pipeline.  The module is pure: no
I/O beyond the YAML loader, no global state beyond the naming-rule
table.

See also :mod:`netcanon.migration.target_profiles` (the older, flat
per-SKU registry; :func:`inventory_from_profile` reads one into the
same :class:`Inventory` shape) and ``docs/adding-a-device-model.md``.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from itertools import product
from math import prod
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    ValidationError,
    field_validator,
    model_validator,
)

from ..models.port_inventory import (
    MAX_DEPLOYMENT_MEMBERS,
    Deployment,
    DeploymentSpec,
    Inventory,
    InventoryMember,
    InventorySummary,
    MemberSpec,
    PhysicalPort,
    PortRole,
    weakest_grade,
)
from .target_profiles import ProfileEvidence, TargetProfile

logger = logging.getLogger(__name__)

#: The data shapes live in :mod:`netcanon.models.port_inventory` so the
#: API models can use them without importing the engine; they are
#: re-exported here because this module is where they are produced.
__all__ = [
    "PROVEN_CAPTURE_CLAIMS",
    "SPEED_RANK",
    "BayDef",
    "CaptureClaim",
    "Deployment",
    "DeploymentError",
    "DeploymentSpec",
    "DeviceModelError",
    "DeviceModelLoadError",
    "DeviceModelRegistry",
    "FamilyDef",
    "Grade",
    "Inventory",
    "InventoryMember",
    "InventorySummary",
    "MemberSpec",
    "ModeDef",
    "ModelDef",
    "ModuleDef",
    "NamingRuleSpec",
    "PhysicalPort",
    "PortCage",
    "PortGroup",
    "PortNameRequest",
    "PortRole",
    "PortSpeed",
    "check_family",
    "compile_deployment",
    "inventory_from_profile",
    "load_family_file",
    "load_model_families",
    "load_model_families_dir",
    "weakest_grade",
]

#: Weakest first, for comparing two stated grades.
_GRADE_ORDER: tuple[str, ...] = ("inferred", "vendor-doc", "capture")


#: Maximum port speed.  ``""`` means "not stated" — never "slow".
PortSpeed = Literal[
    "", "fast", "gig", "2.5gig", "5gig", "10gig", "25gig", "40gig",
    "50gig", "100gig", "400gig",
]

#: Physical form of the port.  ``""`` means "not stated", which is the
#: right value wherever the position of a cage type on the panel is not
#: established for the model.
PortCage = Literal[
    "", "rj45", "sfp", "sfp+", "sfp28", "sfp56", "qsfp+", "qsfp28",
    "qsfp-dd", "osfp", "combo",
]

#: Ascending order of every stated :data:`PortSpeed`.  A speed absent
#: from this table (``""``, or free text read from a legacy profile) is
#: NOT comparable: callers must treat it as unknown, never as equal.
SPEED_RANK: dict[str, int] = {
    speed: rank for rank, speed in enumerate((
        "fast", "gig", "2.5gig", "5gig", "10gig", "25gig", "40gig",
        "50gig", "100gig", "400gig",
    ))
}

#: Upper bounds on what one family file can make the loader build.
#: A family file is operator-authored and trusted like a device
#: definition; these stop a typo, not an attacker.  One group's
#: ``count``, the groups of one panel or module, and the bay-and-
#: module combinations of one model that are compiled at load (see
#: :func:`check_family`).  No fixed-port device comes near any of
#: them; a modular chassis with many bays will need per-bay
#: checking before it can be described.
_MAX_GROUP_PORTS = 512
_MAX_PORT_GROUPS = 64
_MAX_BAY_COMBINATIONS = 4096

#: A family name, model key or module SKU: it is shown, logged and
#: joined into ``vendor/family`` keys, so it is a plain token.
_KEY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*")

#: ``(family key, fixture)`` of every capture claim that
#: ``tests/unit/migration/test_device_models_shipped.py`` re-proves
#: against its fixture.  ``capture`` means exactly that, so a claim
#: grants the grade only when it is listed here.  A claim in an
#: operator's own family file names a fixture nothing checks; it is
#: read, logged and grants nothing.  Kept in code rather than keyed
#: on which directory a file came from: a desktop install loads the
#: shipped families from a copy beside the executable.  The shipped
#: test asserts this set equals the claims the shipped files make.
PROVEN_CAPTURE_CLAIMS: frozenset[tuple[str, str]] = frozenset({
    ("aruba_aoss/2930F",
     "tests/fixtures/real/aruba_aoss/hpe_community_2930f_wc1607_intervlan.cfg"),
    ("aruba_aoss/2930F",
     "tests/fixtures/real/aruba_aoss/hpe_community_2930f_wc1610_dhcp_server.cfg"),
    ("aruba_aoss/2930M",
     "tests/fixtures/real/aruba_aoss/user_contrib_2930m_wc1611.cfg"),
})

#: The family-file schema this module reads.
SCHEMA_VERSION = 1


class DeviceModelError(Exception):
    """Base class for device-model errors."""


class DeviceModelLoadError(DeviceModelError):
    """A family YAML file could not be parsed or validated."""


class DeploymentError(DeviceModelError):
    """A deployment cannot be compiled.

    The message is written for the operator who declared the
    deployment: it names what was asked for and what is allowed.
    """


# ---------------------------------------------------------------------------
# Family registry schema
# ---------------------------------------------------------------------------


class Grade(BaseModel):
    """How well one fact is established."""

    model_config = ConfigDict(extra="forbid")

    grade: ProfileEvidence
    ref: str = ""
    """What backs it, written so that it can be found without this
    file: the document by its own name, number and page, or — for
    public device output — the thread title and post date.  It is
    served to API clients as it stands, so an abbreviation defined
    only in a YAML comment is of no use to the reader."""

    caveat: str = ""
    """What is unverified.  Required when the grade is ``inferred``."""

    @model_validator(mode="after")
    def _honest(self) -> Grade:
        if self.grade == "capture":
            raise ValueError(
                "a part cannot be graded `capture`: a capture proves one "
                "deployment, so it is declared under `captures:` and "
                "granted only where it matches exactly"
            )
        if self.grade == "inferred" and not self.caveat.strip():
            raise ValueError(
                "an `inferred` grade must say what is unverified in `caveat`"
            )
        return self


class PortGroup(BaseModel):
    """A run of like ports, in port-number order.

    Groups are listed in the order the device NUMBERS its ports,
    which is not left-to-right on the panel: on every pictured 2930F
    the SFP cages are leftmost and numbered last.
    """

    model_config = ConfigDict(extra="forbid")

    role: PortRole
    """Required.  A group that silently defaulted to ``access`` would
    turn a model's uplinks into access ports with every name intact."""

    count: StrictInt = Field(ge=1, le=_MAX_GROUP_PORTS)

    slot: str = ""
    """Naming bank on the FIXED panel.  Numbering is per slot: each
    slot counts from one, and a later group in the same slot carries
    on where the earlier one stopped, whatever lies between them.
    Almost always empty: an AOS-S 2930F numbers its uplinks ``49-52``
    straight after access ``1-48``.  Must be empty in a module's
    groups — a module's ports are named by the bay it is fitted in."""

    speed: PortSpeed = ""
    cage: PortCage = ""
    poe: bool = False
    notes: str = ""


class ModuleDef(BaseModel):
    """A swappable module that contributes ports when fitted."""

    model_config = ConfigDict(extra="forbid")

    sku: str = ""
    """Backfilled from the YAML key by the loader."""

    description: str = ""
    ports: list[PortGroup] = Field(min_length=1, max_length=_MAX_PORT_GROUPS)

    inventory: Grade
    """How well this module's port count and order are established."""

    caveat: str = ""
    """Operator-visible note carried into the inventory when the
    module is fitted (a breakout mode that is not modelled, say)."""

    @model_validator(mode="after")
    def _ports_named_by_the_bay(self) -> ModuleDef:
        for group in self.ports:
            if group.slot:
                raise ValueError(
                    f"module {self.sku or '?'}: a module port group "
                    f"cannot set `slot` ({group.slot!r}); its ports "
                    f"are named by the bay the module is fitted in"
                )
        return self


class BayDef(BaseModel):
    """A module bay on a model."""

    model_config = ConfigDict(extra="forbid")

    accepts: list[str] = Field(min_length=1)
    """Module SKUs the bay takes.  Empty is always allowed too."""

    label: str = ""


class ModeDef(BaseModel):
    """A deployment state that decides how ports are named."""

    model_config = ConfigDict(extra="forbid")

    label: str
    """Words an operator recognises: ``"standalone (VSF disabled)"``."""

    member_ids: tuple[int, int] | None = None
    """Inclusive range of member ids.  ``None`` means names carry no
    member id and the deployment is exactly one device."""

    naming: Grade
    """How well the NAME FORM of a fixed-panel port is established in
    this mode."""

    bay_naming: Grade | None = None
    """The same for a port in a module bay, where it is established
    differently; ``None`` uses :attr:`naming`."""

    caveat: str = ""
    """Operator-visible note that applies to every deployment in this
    mode, whatever its grade."""

    @model_validator(mode="after")
    def _coherent(self) -> ModeDef:
        if self.member_ids is None:
            return self
        low, high = self.member_ids
        if low < 0 or high < low:
            raise ValueError(
                f"mode {self.label!r}: member_ids {self.member_ids} "
                f"is not a valid inclusive range"
            )
        if high - low + 1 > MAX_DEPLOYMENT_MEMBERS:
            raise ValueError(
                f"mode {self.label!r}: member_ids spans "
                f"{high - low + 1} ids, more than the "
                f"{MAX_DEPLOYMENT_MEMBERS} cap"
            )
        return self

    @property
    def member_limit(self) -> int:
        if self.member_ids is None:
            return 1
        return self.member_ids[1] - self.member_ids[0] + 1


class ModelDef(BaseModel):
    """One model: its fixed front panel and its module bays."""

    model_config = ConfigDict(extra="forbid")

    model: str = ""
    """Backfilled from the YAML key by the loader."""

    skus: list[str] = Field(default_factory=list)
    """Part numbers that are this exact hardware: the J-number a
    config prints, and ordering aliases of it (``JL256ACM``).  A TAA
    variant is a different J-number and gets its own model entry, so
    that it cannot inherit a capture of its twin."""

    display_name: str = ""

    ports: list[PortGroup] = Field(min_length=1, max_length=_MAX_PORT_GROUPS)
    """The fixed panel, in port-number order (see :class:`PortGroup`)."""

    panel: Grade
    """How well this SKU's fixed port count and roles are
    established.  Stated on every model: a sibling's evidence is not
    this model's.  Where a port TYPE sits within the numbering — the
    ``speed``, ``cage`` and ``poe`` of each position — is not graded
    separately; say so in the grade's ``caveat`` where it is in doubt."""

    bays: dict[str, BayDef] = Field(default_factory=dict)
    """Bay name to what it accepts.  The bay name is the naming
    segment of the ports fitted there — ``A`` on an AOS-S 2930M, whose
    module ports are ``A1``..``A4``.  Declaration order is the order
    their ports are counted in when pairing by position."""

    modes: list[str] | None = None
    """Modes this model supports; ``None`` means every mode of the
    family."""

    caveat: str = ""

    def display(self) -> str:
        return self.display_name or self.model


class CaptureClaim(BaseModel):
    """A committed real capture, and the exact deployment it is of.

    The only source of a ``capture`` grade.  A port is graded
    ``capture`` when a claim has a member with the same model, in the
    same mode, with the same member id — and, for a port in a bay, the
    same module in that bay.  A sibling model, another member id or a
    module the capture does not show stays at the grade of its parts.

    The capture must name EVERY port of the deployment it is of: the
    shipped-data test requires the compiled inventory to equal what
    the fixture shows.  A capture that names only some ports cannot
    be claimed — it would grant the grade to ports it never shows.

    A claim grants the grade only when that test re-proves it
    (:data:`PROVEN_CAPTURE_CLAIMS`).
    """

    model_config = ConfigDict(extra="forbid")

    fixture: str
    """Repo-relative path under ``tests/fixtures/real/``."""

    marker: str
    """A line (lower-cased) that only a capture of THIS model
    contains.  Without it a model passes against any sibling whose
    port names happen to be a superset."""

    mode: str
    members: list[MemberSpec] = Field(min_length=1)
    """Exactly as captured: model, member id, modules.  In a mode
    whose names carry a member id, every member states its ``id`` —
    a default would grant the grade to an id the capture never shows."""


class FamilyDef(BaseModel):
    """One family file: models sharing a naming rule, modes and modules."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal[1] = Field(alias="schema")
    """Family-file schema.  Required, so a future change of shape can
    be told from a file written for this one."""

    vendor: str = Field(pattern=r"^[a-z0-9][a-z0-9_]*$")
    """Vendor id — the ``vendor_id`` of a codec's capability matrix.
    A family whose vendor no codec has can never be declared."""

    family: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
    display_name: str = ""
    naming: str
    """Key of the code-side naming rule; see :class:`NamingRuleSpec`."""

    default_mode: str
    modes: dict[str, ModeDef] = Field(min_length=1)
    modules: dict[str, ModuleDef] = Field(default_factory=dict)
    models: dict[str, ModelDef] = Field(min_length=1)
    captures: list[CaptureClaim] = Field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.vendor}/{self.family}"

    def display(self) -> str:
        return self.display_name or self.family

    @field_validator("schema_version", mode="before")
    @classmethod
    def _schema_is_the_integer(cls, value: object) -> object:
        # ``Literal[1]`` compares by equality, so ``true`` and ``1.0``
        # would both pass for the schema number.
        if type(value) is not int:
            raise ValueError("`schema` must be the integer 1")
        return value

    @model_validator(mode="after")
    def _cross_references_resolve(self) -> FamilyDef:
        rules = _naming_rules()
        if self.naming not in rules:
            raise ValueError(
                f"unknown naming rule {self.naming!r}; known: {sorted(rules)}"
            )
        rule = rules[self.naming]
        if self.default_mode not in self.modes:
            raise ValueError(
                f"default_mode {self.default_mode!r} is not one of "
                f"{sorted(self.modes)}"
            )

        def check_roles(owner: str, groups: list[PortGroup]) -> None:
            for group in groups:
                if group.role not in rule.roles:
                    raise ValueError(
                        f"{owner}: naming rule {self.naming!r} cannot name "
                        f"a {group.role!r} port ({rule.why_not}); it names "
                        f"{sorted(rule.roles)} only"
                    )

        for sku, module in self.modules.items():
            check_roles(f"module {sku!r}", module.ports)
        for key, model in self.models.items():
            check_roles(f"model {key!r}", model.ports)
            fixed = {g.slot for g in model.ports}
            folded: set[str] = set()
            for bay, bay_def in model.bays.items():
                if not bay:
                    raise ValueError(f"model {key!r}: empty bay name")
                if bay.lower() in folded:
                    raise ValueError(
                        f"model {key!r}: bay {bay!r} repeats another bay "
                        f"that differs only in case"
                    )
                folded.add(bay.lower())
                if bay in fixed:
                    raise ValueError(
                        f"model {key!r}: bay {bay!r} shares its name "
                        f"with a fixed-panel slot; their ports would collide"
                    )
                missing = [s for s in bay_def.accepts if s not in self.modules]
                if missing:
                    raise ValueError(
                        f"model {key!r} bay {bay!r} accepts {missing}, "
                        f"which this family does not define under `modules:`"
                    )
            for mode_name in model.modes or []:
                if mode_name not in self.modes:
                    raise ValueError(
                        f"model {key!r} lists mode {mode_name!r}, which "
                        f"this family does not define"
                    )
            if model.modes is not None and not model.modes:
                raise ValueError(f"model {key!r}: `modes` lists no mode")
        for claim in self.captures:
            if claim.mode not in self.modes:
                raise ValueError(
                    f"capture {claim.fixture!r} names mode {claim.mode!r}, "
                    f"which this family does not define"
                )
            carries_ids = self.modes[claim.mode].member_ids is not None
            if carries_ids and any(m.id is None for m in claim.members):
                raise ValueError(
                    f"capture {claim.fixture!r}: mode {claim.mode!r} "
                    f"puts the member id in every port name, so each "
                    f"member of the claim must state the `id` the "
                    f"capture shows"
                )
        return self

    def supports(self, model: ModelDef, mode_name: str) -> bool:
        return model.modes is None or mode_name in model.modes


class DeviceModelRegistry:
    """Every loaded family, indexed for lookup by model key or SKU."""

    def __init__(self, families: list[FamilyDef] | None = None) -> None:
        self.families: dict[str, FamilyDef] = {}
        self._models: dict[tuple[str, str], tuple[FamilyDef, ModelDef]] = {}
        self._skus: dict[tuple[str, str], str] = {}
        for family in families or []:
            self.add(family)

    def add(self, family: FamilyDef) -> None:
        """Index *family* after checking it compiles in every combination.

        Raises:
            DeviceModelLoadError: the family key, a model key or a SKU
                is already registered for the vendor; a model key
                equals another model's SKU; or some (model, mode,
                module) combination does not compile or one of its
                capture claims does not.  Nothing is added in any of
                those cases.
        """
        if family.key in self.families:
            raise DeviceModelLoadError(
                f"family {family.key} is already loaded and is not "
                f"replaced; the one loaded first stays in use"
            )
        claimed: dict[str, str] = {}
        for key, model in family.models.items():
            for label in (key, *model.skus):
                folded = label.lower()
                elsewhere = self._owner(family.vendor, folded)
                if elsewhere is not None:
                    raise DeviceModelLoadError(
                        f"{family.key}: {label!r} identifies both "
                        f"{elsewhere!r} (already loaded) and {key!r}"
                    )
                here = claimed.get(folded)
                if here is not None and here != key:
                    raise DeviceModelLoadError(
                        f"{family.key}: {label!r} identifies both "
                        f"{here!r} and {key!r}"
                    )
                claimed[folded] = key
        try:
            check_family(family)
        except DeviceModelError as exc:
            raise DeviceModelLoadError(f"{family.key}: {exc}") from exc
        self.families[family.key] = family
        for key, model in family.models.items():
            self._models[(family.vendor, key.lower())] = (family, model)
            for sku in model.skus:
                self._skus[(family.vendor, sku.lower())] = key

    def _owner(self, vendor: str, folded: str) -> str | None:
        hit = self._models.get((vendor, folded))
        if hit is not None:
            return hit[1].model
        return self._skus.get((vendor, folded))

    def resolve(self, vendor: str, model: str) -> tuple[FamilyDef, ModelDef] | None:
        """Find a model by its key or by one of its SKUs (any case)."""
        folded = model.strip().lower()
        hit = self._models.get((vendor, folded))
        if hit is not None:
            return hit
        key = self._skus.get((vendor, folded))
        if key is None:
            return None
        return self._models[(vendor, key.lower())]

    def model_keys(self, vendor: str) -> list[str]:
        """Model keys defined for *vendor*, in load order."""
        return [
            model.model for (v, _), (_, model) in self._models.items()
            if v == vendor
        ]

    def __len__(self) -> int:
        return len(self.families)


# ---------------------------------------------------------------------------
# Naming rules
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PortNameRequest:
    """Everything a naming rule may consult for one port.

    A request object rather than positional arguments so a later
    family that needs one more fact does not change every rule.
    """

    mode: str
    """The mode's name in the family file."""

    member_id: int | None
    """The vendor member id, or ``None`` when the mode names ports
    without one."""

    slot: str
    """``""`` on the main fixed panel; the group's ``slot`` for a
    banked fixed group; the bay name for a module port."""

    index0: int
    """0-based position within :attr:`slot`.  The rule applies the
    vendor's own index base."""

    group: PortGroup
    """The group the port belongs to (role, speed, cage)."""


@dataclass(frozen=True)
class NamingRuleSpec:
    """A naming grammar: how to render a name, and what it can name.

    Lives beside the vendor's codec.  One per naming grammar, not per
    product line — every AOS-S fixed-port switch is the single
    ``aoss`` rule.
    """

    render: Callable[[PortNameRequest], str]
    """Renders one port's name.  Raises ``ValueError`` for coordinates
    outside the grammar."""

    roles: frozenset[str]
    """The roles this grammar gives a port NAME to.  A group of any
    other role is refused at load: a counted group the rule cannot
    name would be handed the next free number and become a port the
    device does not have."""

    why_not: str = ""
    """One clause explaining the roles left out, for the load error."""


def _aoss_rule(request: PortNameRequest) -> str:
    from .codecs.aruba_aoss.port_names import physical_port_name

    return physical_port_name(
        member=request.member_id,
        slot=request.slot,
        port=request.index0 + 1,
    )


def _naming_rules() -> dict[str, NamingRuleSpec]:
    """The naming-rule table.

    Rule bodies import their codec module lazily so this module stays
    importable without the codec packages.
    """
    return {
        "aoss": NamingRuleSpec(
            render=_aoss_rule,
            roles=frozenset({"access", "uplink"}),
            why_not=(
                "AOS-S out-of-band management is the `oobm` context, "
                "not a numbered port"
            ),
        ),
    }


# ---------------------------------------------------------------------------
# Compile
# ---------------------------------------------------------------------------


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = item.strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _weaker_grade(a: Grade, b: Grade) -> Grade:
    return a if _GRADE_ORDER.index(a.grade) <= _GRADE_ORDER.index(b.grade) else b


def _assign_member_ids(
    members: list[MemberSpec], mode_name: str, mode: ModeDef,
) -> list[int | None]:
    if mode.member_ids is None:
        if len(members) != 1:
            raise DeploymentError(
                f"mode {mode_name!r} ({mode.label}) is a single device, "
                f"but {len(members)} members were declared"
            )
        if members[0].id is not None:
            raise DeploymentError(
                f"mode {mode_name!r} ({mode.label}) names ports without "
                f"a member id, but member id {members[0].id} was declared"
            )
        return [None]
    low, high = mode.member_ids
    if len(members) > mode.member_limit:
        raise DeploymentError(
            f"mode {mode_name!r} ({mode.label}) allows at most "
            f"{mode.member_limit} members; {len(members)} were declared"
        )
    taken: set[int] = set()
    for member in members:
        if member.id is None:
            continue
        if not low <= member.id <= high:
            raise DeploymentError(
                f"member id {member.id} is outside {low}-{high} for mode "
                f"{mode_name!r} ({mode.label})"
            )
        if member.id in taken:
            raise DeploymentError(f"member id {member.id} is declared twice")
        taken.add(member.id)
    ids: list[int | None] = []
    free = (n for n in range(low, high + 1) if n not in taken)
    for member in members:
        ids.append(member.id if member.id is not None else next(free))
    return ids


def _fitted_modules(
    family: FamilyDef, model: ModelDef, member: MemberSpec,
) -> tuple[dict[str, ModuleDef], list[str]]:
    """Bay name to fitted module (in the model's bay order), and the
    bays the member did not mention."""
    by_fold = {bay.lower(): bay for bay in model.bays}
    stated: dict[str, str | None] = {}
    for bay, sku in member.modules.items():
        real = by_fold.get(bay.strip().lower())
        if real is None:
            have = ", ".join(model.bays) or "none"
            raise DeploymentError(
                f"{model.display()} has no bay {bay!r} (bays: {have})"
            )
        if real in stated:
            raise DeploymentError(
                f"{model.display()}: bay {real} is stated twice"
            )
        stated[real] = sku
    fitted: dict[str, ModuleDef] = {}
    for bay, bay_def in model.bays.items():
        wanted = (stated.get(bay) or "").strip()
        if not wanted:
            continue
        match = next(
            (s for s in bay_def.accepts if s.lower() == wanted.lower()), None,
        )
        if match is None:
            raise DeploymentError(
                f"{model.display()} bay {bay} does not take {wanted!r} "
                f"(accepts: {', '.join(bay_def.accepts)})"
            )
        fitted[bay] = family.modules[match]
    return fitted, [bay for bay in model.bays if bay not in stated]


@dataclass(frozen=True)
class _ResolvedMember:
    member_id: int | None
    family: FamilyDef
    model: ModelDef
    fitted: dict[str, ModuleDef]
    unstated: list[str]


def _resolve(
    deployment: Deployment, registry: DeviceModelRegistry,
) -> tuple[FamilyDef, str, list[_ResolvedMember]]:
    hits: list[tuple[FamilyDef, ModelDef]] = []
    for member in deployment.members:
        hit = registry.resolve(deployment.vendor, member.model)
        if hit is None:
            raise DeploymentError(
                f"no device model {member.model!r} is defined for "
                f"{deployment.vendor}"
            )
        hits.append(hit)
    family = hits[0][0]
    for other, model in hits[1:]:
        if other.key != family.key:
            raise DeploymentError(
                f"{model.display()} ({other.display()}) cannot share a "
                f"deployment with {family.display()} models"
            )
    return (family, *_resolve_in_family(family, deployment.mode, deployment.members))


def _resolve_in_family(
    family: FamilyDef, mode: str | None, members: list[MemberSpec],
) -> tuple[str, list[_ResolvedMember]]:
    wanted = (mode or "").strip()
    modes_by_fold = {name.lower(): name for name in family.modes}
    mode_name = modes_by_fold.get(wanted.lower(), wanted) if wanted else (
        family.default_mode
    )
    mode_def = family.modes.get(mode_name)
    if mode_def is None:
        raise DeploymentError(
            f"{family.display()} has no mode {mode_name!r} "
            f"(modes: {', '.join(family.modes)})"
        )
    by_fold = {key.lower(): model for key, model in family.models.items()}
    for model in family.models.values():
        for sku in model.skus:
            by_fold.setdefault(sku.lower(), model)
    models: list[ModelDef] = []
    for member in members:
        model = by_fold.get(member.model.strip().lower())
        if model is None:
            raise DeploymentError(
                f"{family.display()} has no model {member.model!r}"
            )
        if not family.supports(model, mode_name):
            raise DeploymentError(
                f"{model.display()} does not support mode {mode_name!r} "
                f"({mode_def.label}); it supports: {', '.join(model.modes or [])}"
            )
        models.append(model)
    ids = _assign_member_ids(members, mode_name, mode_def)
    resolved = []
    for member, model, member_id in zip(members, models, ids, strict=True):
        fitted, unstated = _fitted_modules(family, model, member)
        resolved.append(_ResolvedMember(member_id, family, model, fitted, unstated))
    return mode_name, resolved


def _claimed(
    family: FamilyDef, mode_name: str,
) -> list[tuple[str, _ResolvedMember]]:
    """``(fixture, member)`` for every member a PROVEN capture claim
    of *family* shows in *mode_name*.  A claim the test suite does
    not re-prove grants nothing (:data:`PROVEN_CAPTURE_CLAIMS`)."""
    out: list[tuple[str, _ResolvedMember]] = []
    for claim in family.captures:
        if claim.mode != mode_name:
            continue
        if (family.key, claim.fixture) not in PROVEN_CAPTURE_CLAIMS:
            continue
        _, members = _resolve_in_family(family, claim.mode, claim.members)
        out.extend((claim.fixture, member) for member in members)
    return out


def _captured(
    member: _ResolvedMember, bay: str,
    claims: list[tuple[str, _ResolvedMember]],
) -> str | None:
    """The fixture of a claim that shows this model as this member —
    and, for a bay port, with this module in that bay."""
    for fixture, claim in claims:
        if claim.model.model != member.model.model:
            continue
        if claim.member_id != member.member_id:
            continue
        if not bay:
            return fixture
        ours, theirs = member.fitted.get(bay), claim.fitted.get(bay)
        if ours is not None and theirs is not None and ours.sku == theirs.sku:
            return fixture
    return None


def _member_ports(
    rule: NamingRuleSpec,
    mode_name: str,
    mode: ModeDef,
    rank: int,
    member: _ResolvedMember,
    claims: list[tuple[str, _ResolvedMember]],
) -> tuple[list[PhysicalPort], list[str], list[str]]:
    """One member's ports — the fixed panel, then each fitted bay —
    with the references and caveats of what established them.

    A port a capture claim covers is graded ``capture`` and cites the
    fixture; any other port takes the weaker of its naming grade and
    its panel-or-module grade, and both facts' references and caveats
    are kept.  A capture proves NAMES, so it retires the caveat of
    the naming fact and keeps the caveat of the panel or module
    fact: what a port is for is not something a config shows.
    Position within a slot runs on through every group of that slot;
    the per-role ordinal runs on through the whole member.
    """
    # (group, slot, module sku, the two facts that establish its names)
    groups: list[tuple[PortGroup, str, str, tuple[Grade, Grade]]] = [
        (group, group.slot, "", (mode.naming, member.model.panel))
        for group in member.model.ports
    ]
    for bay, module in member.fitted.items():
        naming = mode.bay_naming or mode.naming
        groups.extend(
            (group, bay, module.sku, (naming, module.inventory))
            for group in module.ports
        )
    ports: list[PhysicalPort] = []
    refs: list[str] = []
    caveats: list[str] = []
    next_index: dict[str, int] = {}
    next_ordinal: dict[str, int] = {}
    for group, slot, module_sku, facts in groups:
        fixture = _captured(member, slot if module_sku else "", claims)
        if fixture is not None:
            refs.append(fixture)
            caveats.append(facts[1].caveat)
            evidence: ProfileEvidence = "capture"
        else:
            refs.extend(fact.ref for fact in facts)
            caveats.extend(fact.caveat for fact in facts)
            evidence = _weaker_grade(*facts).grade
        for _ in range(group.count):
            index0 = next_index.get(slot, 0)
            next_index[slot] = index0 + 1
            ordinal = next_ordinal.get(group.role, 0)
            next_ordinal[group.role] = ordinal + 1
            try:
                name = rule.render(PortNameRequest(
                    mode=mode_name, member_id=member.member_id, slot=slot,
                    index0=index0, group=group,
                ))
            except ValueError as exc:
                raise DeploymentError(
                    f"{member.model.display()}: the naming rule cannot "
                    f"name port {index0 + 1} of slot {slot!r}: {exc}"
                ) from exc
            ports.append(PhysicalPort(
                name=name,
                member_rank=rank,
                member_id=member.member_id,
                role=group.role,
                ordinal=ordinal,
                slot=slot,
                index=index0,
                module=module_sku,
                speed=group.speed,
                cage=group.cage,
                poe=group.poe,
                notes=group.notes,
                evidence=evidence,
            ))
    return ports, refs, caveats


def compile_deployment(
    deployment: Deployment, registry: DeviceModelRegistry,
) -> Inventory:
    """Compile *deployment* to the ordered list of ports that exist.

    Args:
        deployment: The declared model(s), modules and mode.
        registry: The loaded families.

    Returns:
        The inventory: every port with its own grade, what each member
        resolved to, the resolved mode, and every applicable caveat.

    Raises:
        DeploymentError: the deployment names a model, mode, bay,
            module or member id the registry does not allow, or mixes
            families.  The message says what is allowed.
    """
    family, mode_name, members = _resolve(deployment, registry)
    return _compile(deployment.vendor, family, mode_name, members,
                    mode_defaulted=not (deployment.mode or "").strip())


def _compile(
    vendor: str,
    family: FamilyDef,
    mode_name: str,
    members: list[_ResolvedMember],
    *,
    mode_defaulted: bool,
) -> Inventory:
    mode = family.modes[mode_name]
    rule = _naming_rules()[family.naming]
    claims = _claimed(family, mode_name)

    ports: list[PhysicalPort] = []
    summaries: list[InventoryMember] = []
    refs: list[str] = []
    caveats: list[str] = [mode.caveat]
    parts: list[str] = []
    for rank, member in enumerate(members):
        member_ports, member_refs, member_caveats = _member_ports(
            rule, mode_name, mode, rank, member, claims,
        )
        ports.extend(member_ports)
        refs.extend(member_refs)
        caveats.extend(member_caveats)
        caveats.append(member.model.caveat)
        caveats.extend(module.caveat for module in member.fitted.values())
        for bay in member.unstated:
            caveats.append(
                f"{member.model.display()}: bay {bay} was not stated and "
                f"is assumed empty."
            )
        summaries.append(InventoryMember(
            rank=rank,
            member_id=member.member_id,
            model=member.model.model,
            display_name=member.model.display(),
            modules={bay: module.sku for bay, module in member.fitted.items()},
            unstated_bays=list(member.unstated),
            evidence=weakest_grade([p.evidence for p in member_ports]),
        ))
        part = member.model.display()
        if member.fitted:
            part += " + " + " + ".join(m.sku for m in member.fitted.values())
        if member.member_id is not None:
            part += f" as member {member.member_id}"
        parts.append(part)
    if mode_defaulted and len(family.modes) > 1:
        caveats.append(
            f"No deployment mode was stated; {family.display()} was "
            f"assumed to be in its default, {mode.label}. The mode "
            f"decides every port name."
        )

    repeated = sorted(
        name for name, seen in Counter(p.name for p in ports).items()
        if seen > 1
    )
    if repeated:
        raise DeploymentError(
            f"{family.key}: the model data names a port twice "
            f"({', '.join(repeated[:6])}) — this is a defect in the "
            f"family file, not in the deployment"
        )

    return Inventory(
        vendor=vendor,
        origin="family",
        family=family.key,
        mode=mode_name,
        mode_label=mode.label,
        mode_defaulted=mode_defaulted,
        members=summaries,
        description=f"{'; '.join(parts)} — {mode.label}",
        port_count=len(ports),
        ports=ports,
        evidence=weakest_grade([p.evidence for p in ports]),
        evidence_refs=_unique(refs),
        caveats=_unique(caveats),
    )


def check_family(family: FamilyDef) -> None:
    """Compile every combination a family allows.

    Every model, in every mode it supports, with each bay empty and
    with each module it accepts; then every capture claim.  A naming
    rule that refuses a bay name, a duplicate port name in an unusual
    combination, or a claim that names a model the family lacks is
    found here — at load — rather than when an operator first picks
    that combination.

    Raises:
        DeploymentError: some combination does not compile, or a
            model has more bay-and-module combinations than are
            compiled at load.
    """
    for model in family.models.values():
        bays = list(model.bays)
        choices = [[None, *model.bays[bay].accepts] for bay in bays]
        combinations = prod(len(choice) for choice in choices)
        if combinations > _MAX_BAY_COMBINATIONS:
            raise DeploymentError(
                f"{model.display()} has {combinations} bay-and-module "
                f"combinations; at most {_MAX_BAY_COMBINATIONS} are "
                f"compiled when a family loads"
            )
        for mode_name in family.modes:
            if not family.supports(model, mode_name):
                continue
            for choice in product(*choices):
                spec = MemberSpec(
                    model=model.model,
                    modules=dict(zip(bays, choice, strict=True)),
                )
                _, members = _resolve_in_family(family, mode_name, [spec])
                _compile(
                    family.vendor, family, mode_name, members,
                    mode_defaulted=False,
                )
    for claim in family.captures:
        _, members = _resolve_in_family(family, claim.mode, claim.members)
        _compile(family.vendor, family, claim.mode, members, mode_defaulted=False)


# ---------------------------------------------------------------------------
# Legacy compatibility — a flat TargetProfile as an inventory
# ---------------------------------------------------------------------------

#: ``TargetPort.kind`` to :data:`PortRole`.  A console port is never a
#: name in a running config, so it has no place in an inventory.
_ROLE_OF_KIND: dict[str, PortRole] = {
    "physical": "access",
    "uplink": "uplink",
    "mgmt": "mgmt",
}


def inventory_from_profile(
    profile: TargetProfile, module_sku: str | None = None,
) -> Inventory:
    """Read a flat :class:`TargetProfile` as a one-member inventory.

    A target profile already lists literal port names for one stated
    deployment state, so no naming rule is involved: names are taken
    verbatim, roles come from each port's ``kind`` and ordinals from
    list order (chassis ports, then the selected module's).

    What a profile does NOT state is not invented: the cage is left
    unstated (the profile's ``sfp`` flag means "a pluggable cage of
    some kind", from SFP to QSFP-DD), the member id is unknown, and
    the order is the YAML list order, which nobody has checked
    against the hardware's port numbering — the inventory's
    ``origin`` says so.

    Args:
        profile: The profile.
        module_sku: Module choice, with the semantics of
            :meth:`TargetProfile.effective_ports` — ``None`` selects
            the profile's default module when it declares any, and an
            unknown SKU (``""`` included) selects none.  This differs
            on purpose from :attr:`MemberSpec.modules`, where an
            unmentioned bay is empty.  A caller for whom the choice
            decides which ports exist must refuse an unknown SKU
            itself, as the API does.

    Returns:
        The inventory.  Its ``evidence`` is the profile's own, which
        is ``None`` for a profile nobody has graded.
    """
    chosen = module_sku if module_sku is not None else profile.default_module_sku()
    if chosen not in profile.modules:
        chosen = None
    groups = [("", list(profile.ports))]
    if chosen:
        groups.append((chosen, list(profile.modules[chosen].ports)))
    ports: list[PhysicalPort] = []
    next_ordinal: dict[str, int] = {}
    position = 0
    for module, group in groups:
        for port in group:
            index, position = position, position + 1
            role = _ROLE_OF_KIND.get(port.kind)
            if role is None:
                continue
            ordinal = next_ordinal.get(role, 0)
            next_ordinal[role] = ordinal + 1
            ports.append(PhysicalPort(
                name=port.id,
                member_rank=0,
                member_id=None,
                role=role,
                ordinal=ordinal,
                slot="",
                index=index,
                module=module,
                speed=port.speed,
                cage="",
                poe=port.poe,
                notes=port.notes,
                evidence=profile.evidence,
            ))
    description = profile.display()
    if chosen:
        description += f" + {chosen}"
    if profile.deployment_state:
        description += f" — {profile.deployment_state}"
    return Inventory(
        vendor=profile.vendor,
        origin="legacy-profile",
        mode_label=profile.deployment_state,
        members=[InventoryMember(
            rank=0,
            model=profile.model,
            display_name=profile.display(),
            modules={"module": chosen} if chosen else {},
            evidence=profile.evidence if ports else None,
        )],
        description=description,
        port_count=len(ports),
        ports=ports,
        evidence=profile.evidence if ports else None,
        evidence_refs=_unique([profile.evidence_ref]),
        caveats=_unique([profile.caveat]),
    )


# ---------------------------------------------------------------------------
# YAML loader
# ---------------------------------------------------------------------------


def _repeated_key(node: yaml.Node | None) -> tuple[str, int] | None:
    """The first mapping key that occurs twice under *node*, with its line.

    ``yaml.safe_load`` keeps the LAST of two equal keys, so a model
    block pasted twice (a merge artefact) silently replaces the first
    with whatever the second says.  This walks the composed node tree
    — which constructs no objects — so the data itself is still read
    with ``safe_load``.

    The tree is a tree: :func:`load_family_file` refuses a file that
    uses a YAML alias before this is called, so no node is reachable
    twice and the walk cannot recurse into itself.  Keys are compared
    as written; two spellings YAML resolves to one value (``1`` and
    ``01``) are caught later, when a non-string key is refused.
    """
    if isinstance(node, yaml.MappingNode):
        seen: set[str] = set()
        for key_node, value_node in node.value:
            if isinstance(key_node, yaml.ScalarNode):
                if key_node.value in seen:
                    return key_node.value, key_node.start_mark.line + 1
                seen.add(key_node.value)
            found = _repeated_key(value_node)
            if found is not None:
                return found
    elif isinstance(node, yaml.SequenceNode):
        for item in node.value:
            found = _repeated_key(item)
            if found is not None:
                return found
    return None


def load_family_file(path: Path) -> FamilyDef:
    """Load and validate one family YAML file.

    The YAML key of each model and each module is backfilled into its
    ``model`` / ``sku`` field.

    Raises:
        DeviceModelLoadError: the file cannot be read as UTF-8 text, is
            not valid YAML, uses a YAML alias, repeats a mapping key,
            is not a mapping, has a key that is not a plain name, or
            fails schema validation.  Unknown fields are rejected, so a
            misspelt field is an error rather than a silently ignored
            one.  Every way a file can be wrong surfaces as this one
            exception, so a caller that skips a bad file needs to catch
            nothing else.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise DeviceModelLoadError(
            f"{path}: cannot be read as UTF-8 text: {exc}"
        ) from exc
    try:
        # An alias makes one node reachable from two places.  No family
        # file needs one, and refusing them removes a self-referential
        # document (unbounded recursion), an alias bomb (exponential
        # work) and the merge key in a single rule.
        if any(
            isinstance(event, yaml.AliasEvent)
            for event in yaml.parse(raw, Loader=yaml.SafeLoader)
        ):
            raise DeviceModelLoadError(
                f"{path}: YAML aliases (`*name`) are not allowed in a "
                f"family file; write the value out"
            )
        repeated = _repeated_key(yaml.compose(raw, Loader=yaml.SafeLoader))
        data: Any = yaml.safe_load(raw)
    except (yaml.YAMLError, RecursionError) as exc:
        raise DeviceModelLoadError(f"{path}: YAML parse error: {exc}") from exc
    if repeated is not None:
        raise DeviceModelLoadError(
            f"{path}: duplicate key {repeated[0]!r} at line {repeated[1]} "
            f"— YAML would keep only the last one"
        )
    if not isinstance(data, dict):
        raise DeviceModelLoadError(f"{path}: expected a YAML mapping at top level")
    for section, field in (("models", "model"), ("modules", "sku")):
        entries = data.get(section)
        if entries is None:
            continue
        if not isinstance(entries, dict):
            raise DeviceModelLoadError(f"{path}: `{section}` must be a mapping")
        filled: dict[str, Any] = {}
        for key, entry_raw in entries.items():
            # YAML reads a bare ``yes`` as True, ``~`` as None and
            # ``0755`` as 493; ``str()`` of those is not what was typed.
            if not isinstance(key, str) or not _KEY_RE.fullmatch(key):
                raise DeviceModelLoadError(
                    f"{path}: {section} key {key!r} must be a plain name "
                    f"(letters, digits, `.`, `_`, `+`, `-`); quote it if "
                    f"YAML reads it as a number or a boolean"
                )
            if not isinstance(entry_raw, dict):
                raise DeviceModelLoadError(
                    f"{path}: {section} entry {key!r} must be a mapping"
                )
            entry = dict(entry_raw)
            entry.setdefault(field, key)
            filled[key] = entry
        data[section] = filled
    try:
        return FamilyDef.model_validate(data)
    except ValidationError as exc:
        raise DeviceModelLoadError(
            f"{path}: schema validation failed: {exc}"
        ) from exc


def load_model_families_dir(
    directory: Path, into: DeviceModelRegistry | None = None,
) -> DeviceModelRegistry:
    """Load every ``*.yaml`` family file in *directory*.

    A file that fails to load for any reason — unreadable, not UTF-8,
    not YAML, not the schema — that does not compile in some
    combination, or that repeats a family, model key or SKU already
    registered, is logged and skipped: one bad file must not stop the
    application starting.  The shipped files are loaded strictly by
    ``tests/unit/migration/test_device_models_shipped.py``, so a typo
    there fails the build instead of quietly removing a family.

    Args:
        directory: The directory to read.
        into: A registry to ADD to.  Used to lay an operator's own
            families over the shipped ones: a family, model key or SKU
            the registry already holds is refused (and logged), so an
            overlay can add new FAMILIES — each with its own models —
            and can never replace a shipped one, nor add a model to it.

    Returns:
        The registry — *into* when given, else a new one.  Unchanged
        or empty when *directory* does not exist: device models are an
        optional feature.
    """
    registry = into if into is not None else DeviceModelRegistry()
    before = len(registry)
    if not directory.exists():
        logger.info(
            "device_models: directory %s not found — no families loaded",
            directory,
        )
        return registry
    for path in sorted(directory.glob("*.yaml")):
        try:
            family = load_family_file(path)
            if registry.families.get(family.key) == family:
                # The same family, already loaded: a desktop install
                # keeps a copy of the shipped library beside the
                # executable.  Not a conflict, and not worth a warning
                # on every start.
                logger.debug(
                    "device_models: %s is already loaded; skipped", path.name,
                )
                continue
            registry.add(family)
        except DeviceModelLoadError as exc:
            logger.warning("device_models: skip %s: %s", path.name, exc)
            continue
        except Exception as exc:
            # The contract is "one bad file cannot stop the application";
            # it must hold for a failure nobody listed, too.
            logger.warning(
                "device_models: skip %s: %s: %s",
                path.name, type(exc).__name__, exc,
            )
            continue
        unproven = [
            claim.fixture for claim in family.captures
            if (family.key, claim.fixture) not in PROVEN_CAPTURE_CLAIMS
        ]
        if unproven:
            logger.warning(
                "device_models: %s: %d capture claim(s) are not re-proven "
                "by netcanon's tests and grant no `capture` grade: %s",
                path.name, len(unproven), ", ".join(unproven),
            )
    logger.info(
        "device_models: %d new family file(s) from %s",
        len(registry) - before, directory,
    )
    return registry


def load_model_families(definitions_dir: Path) -> DeviceModelRegistry:
    """The registry an application should use.

    The families shipped with netcanon are always loaded.  When
    *definitions_dir* is somewhere else — an operator who keeps their
    own device definitions — a ``model_families/`` directory there is
    laid over them.  An operator who has relocated their backup
    definitions therefore keeps model-to-model translation, where a
    plain "load from the definitions directory" would have dropped it
    with one log line.
    """
    from ..definitions import LIBRARY_DIR

    shipped = LIBRARY_DIR / "model_families"
    custom = definitions_dir / "model_families"
    if not shipped.is_dir():
        # Never expected: the families ship as package data.  Only the
        # operator's own directory is optional.
        logger.warning(
            "device_models: the model families shipped with netcanon were "
            "not found at %s; only families under %s will load",
            shipped, custom,
        )
    registry = load_model_families_dir(shipped)
    try:
        same = custom.resolve() == shipped.resolve()
    except OSError:
        same = False
    if not same:
        load_model_families_dir(custom, into=registry)
    return registry

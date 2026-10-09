"""
Source-device detection — propose a deployment from the config itself.

Positional port mapping needs to be told which device a config came
from (:mod:`netcanon.migration.device_models`).  Often the config
already says: a ``show running-config`` carries its chassis part
number, its fitted modules and whether it is stacked.  This module
turns those lines into a **proposal** an operator can confirm — the
same :class:`~netcanon.models.port_inventory.DeploymentSpec` a plan
request carries as ``source_deployment`` — instead of making them
type it.

Two halves, kept apart on purpose:

* a **detector** per vendor, beside that vendor's codec, reads the
  lines that state the hardware and returns them as printed
  (:class:`~netcanon.models.port_inventory.DetectedDeployment`).  It
  has no table of models;
* :func:`propose_deployment` resolves what was read against the model
  registry, compiles the result, and **checks it against the config**:
  every port name the config uses should be a port of the proposed
  device.  A name that is not is reported, because the commonest way
  for a detection to be wrong is a module the config does not state.

A proposal is never applied by itself.  What a config says is what the
device is PROVISIONED for, which is not always what is fitted, and
only some of a config may have been pasted.  The proposal carries the
lines it was read from so that whoever confirms it can see why.

Pure functions — no I/O, no global state beyond the detector table.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from ..models.port_inventory import (
    Deployment,
    DeploymentProposal,
    DeploymentSpec,
    DetectedDeployment,
    DetectedMember,
    MemberSpec,
)
from .device_models import (
    DeploymentError,
    DeviceModelRegistry,
    FamilyDef,
    compile_deployment,
)

if TYPE_CHECKING:
    from .codecs.base import CodecBase

__all__ = ["detection_vendors", "propose_deployment"]


def _aoss(raw_text: str) -> DetectedDeployment | None:
    from .codecs.aruba_aoss.deployment_detect import detect_deployment

    return detect_deployment(raw_text)


def _detectors() -> dict[str, Callable[[str], DetectedDeployment | None]]:
    """Vendor id to detector.

    Detector bodies import their codec module lazily so this module
    stays importable without the codec packages.  A detector reads
    what a config STATES; it must not infer a model from the shape or
    number of the port names — that is the guess this feature exists
    to replace.
    """
    return {"aruba_aoss": _aoss}


def detection_vendors() -> list[str]:
    """Vendor ids a detector exists for, sorted."""
    return sorted(_detectors())


def _mode_for(family: FamilyDef, fabric: str) -> tuple[str | None, str]:
    """The family mode a config in *fabric* is in, and a note if unsure.

    A config that is in a stacking mode names its ports with a member
    id, so its mode is the family's mode that carries member ids; one
    that is not is the mode that carries none.  Where a family has more
    than one mode of the kind wanted, the config's own word for the
    fabric decides if a mode is named after it, and otherwise no mode
    is proposed.
    """
    wanted = [
        name for name, mode in family.modes.items()
        if (mode.member_ids is not None) == bool(fabric)
    ]
    if len(wanted) == 1:
        return wanted[0], ""
    if fabric in wanted:
        return fabric, ""
    state = f"in `{fabric}` mode" if fabric else "not in a stacking mode"
    if not wanted:
        return None, (
            f"The config is {state}, and {family.display()} has no "
            f"deployment mode of that kind (modes: {', '.join(family.modes)})."
        )
    return None, (
        f"The config is {state}; {family.display()} has more than one such "
        f"mode ({', '.join(wanted)}) and the config does not say which."
    )


def propose_deployment(
    codec: CodecBase, raw_text: str, registry: DeviceModelRegistry,
) -> DeploymentProposal:
    """Propose the deployment *raw_text* came from.

    Args:
        codec: The source codec.  Its vendor selects the detector and
            the families a part number is looked up in.
        raw_text: The source configuration.
        registry: The loaded model families.

    Returns:
        A proposal.  ``deployment`` is set — and can be sent as a plan
        request's ``source_deployment`` — only when every member the
        config names is a model some family describes, they share one
        family, the mode is not in doubt and the result compiles.
        Otherwise it is ``None`` and ``notes`` says what stood in the
        way.  ``missing_ports`` lists port names the config uses that
        the proposed device does not have; ``consistent`` is ``True``
        when there are none, and ``None`` when nothing was proposed or
        the config could not be parsed to check.
    """
    vendor = codec.capabilities.vendor_id
    proposal = DeploymentProposal(vendor=vendor)
    detector = _detectors().get(vendor)
    if detector is None:
        proposal.notes.append(
            f"No detector reads the hardware lines of a {vendor} "
            f"configuration yet; declare the device yourself."
        )
        return proposal
    detected = detector(raw_text)
    if detected is None:
        proposal.notes.append(
            "The config does not say which device it came from; declare "
            "the device yourself."
        )
        return proposal

    proposal.fabric = detected.fabric
    proposal.evidence = list(detected.evidence)
    proposal.notes = list(detected.notes)
    proposal.stated = bool(detected.members)
    if not detected.members:
        return proposal

    families: dict[str, FamilyDef] = {}
    members: list[DetectedMember] = []
    for member in detected.members:
        hit = registry.resolve(vendor, member.part)
        if hit is None:
            proposal.unknown_parts.append(member.part)
            members.append(member)
            continue
        family, model = hit
        families[family.key] = family
        members.append(member.model_copy(update={"model": model.model}))
    proposal.members = members
    if proposal.unknown_parts:
        unknown = ", ".join(dict.fromkeys(proposal.unknown_parts))
        proposal.notes.append(
            f"No model family describes {unknown}, so no deployment can be "
            f"proposed.  A target profile for that device can be declared "
            f"instead, if one exists."
        )
        return proposal
    if len(families) > 1:
        proposal.notes.append(
            f"The members belong to different model families "
            f"({', '.join(families)}); no deployment can be proposed."
        )
        return proposal

    (family,) = families.values()
    proposal.family = family.key
    mode_name, doubt = _mode_for(family, detected.fabric)
    if mode_name is None:
        proposal.notes.append(doubt)
        return proposal
    carries_ids = family.modes[mode_name].member_ids is not None
    spec = DeploymentSpec(
        mode=mode_name,
        members=[
            MemberSpec(
                model=member.model,
                id=member.id if carries_ids else None,
                modules=dict(member.modules),
            )
            for member in members
        ],
    )
    try:
        inventory = compile_deployment(
            Deployment(vendor=vendor, **spec.model_dump()), registry,
        )
    except DeploymentError as exc:
        proposal.notes.append(
            f"What the config states does not compile as a "
            f"{family.display()} deployment: {exc}"
        )
        return proposal
    proposal.deployment = spec
    proposal.mode = mode_name
    proposal.inventory = inventory.summary()

    # The check that makes a proposal worth more than a regex: the
    # ports the config actually uses should all be ports of the device
    # the config says it is.
    from .canonical.intent import CanonicalIntent
    from .canonical.port_names import collect_hardware_port_names

    try:
        tree = codec.parse(raw_text)
    except Exception:
        tree = None
    if not isinstance(tree, CanonicalIntent):
        proposal.notes.append(
            "The config could not be parsed, so the proposal was not "
            "checked against the port names it uses."
        )
        return proposal
    names = set(inventory.names())
    used = collect_hardware_port_names(
        tree,
        classify=getattr(codec, "classify_port_name", None),
        always=names,
    )
    proposal.used_port_count = len(used)
    proposal.missing_ports = [name for name in used if name not in names]
    proposal.consistent = not proposal.missing_ports
    if proposal.missing_ports:
        shown = ", ".join(proposal.missing_ports[:8])
        if len(proposal.missing_ports) > 8:
            shown += f" and {len(proposal.missing_ports) - 8} more"
        proposal.notes.append(
            f"The config uses {len(proposal.missing_ports)} port name(s) the "
            f"proposed device does not have ({shown}).  A module may be "
            f"fitted that the config does not state, or the text may be "
            f"from more than one device; check before relying on this."
        )
    return proposal

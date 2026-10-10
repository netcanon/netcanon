"""
Source-device detection — propose a deployment from the config itself.

Positional port mapping needs to be told which device a config came
from (:mod:`netcanon.migration.device_models`).  Often the config
already says: a ``show running-config`` carries its chassis part
number, the modules it is provisioned for and whether it is stacked.
This module
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
  device.  A name that is not is reported, because the hardware
  lines cannot show everything: a module the config does not state,
  or text from more than one device.

What a proposal carries is bounded, whatever the text holds: a config
that states more devices than a declaration may list is answered with
a note, and the evidence and the list of missing ports are capped
(``MAX_EVIDENCE_LINES``, ``MAX_MISSING_PORTS``).

A proposal is never applied by itself.  What a config says is what the
device is PROVISIONED for, which is not always what is fitted, and
only some of a config may have been pasted.  The proposal carries the
lines it was read from so that whoever confirms it can see why.

Pure functions — no I/O, no global state beyond the detector table.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from pydantic import ValidationError

from ..models.port_inventory import (
    MAX_DEPLOYMENT_MEMBERS,
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

__all__ = [
    "MAX_EVIDENCE_LINES", "MAX_MISSING_PORTS", "detection_vendors", "propose_deployment",
]

#: The most evidence lines a proposal carries.  A stack of the largest
#: declarable size, with a module line per member and a banner, fits.
MAX_EVIDENCE_LINES = 2 * MAX_DEPLOYMENT_MEMBERS + 8

#: The most port names ``missing_ports`` carries.  A few short lines of
#: port ranges expand to hundreds of thousands of names;
#: ``missing_port_count`` has the whole number.
MAX_MISSING_PORTS = 256

logger = logging.getLogger(__name__)


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
    """The family mode a config in *fabric* is in, and a note.

    The note is the reason when no mode is returned; with a mode, it
    is empty, or says that the family's one stacking mode does not go
    by the stanza's word (in its name or its label).

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
        (only,) = wanted
        label = family.modes[only].label
        if fabric and fabric.casefold() not in f"{only} {label}".casefold():
            # The family's one such mode does not go by the stanza's
            # word, in its name or in its label: a `stacking` stanza
            # that names a switch whose mode is `vsf`.  No device
            # prints that; the mode is still the only one there is, so
            # it is proposed and the mismatch is said.
            return only, (
                f"The config has a `{fabric}` stanza, and "
                f"{family.display()}'s one mode with stack members is "
                f"`{only}` ({label}), which is not called that.  The "
                f"proposal is in that mode; check that the text is from "
                f"one device."
            )
        return only, ""
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
        Otherwise it is ``None`` and the FIRST of ``notes`` says what
        stood in the way; what the detector had to say about the lines
        it read comes after.  ``missing_ports`` lists port names the config uses that
        the proposed device does not have (capped;
        ``missing_port_count`` is the whole number); ``consistent`` is
        ``True`` when there are none, and ``None`` when there was
        nothing to check: nothing was proposed, the config could not
        be parsed, or it names no port.  Never raises on any text: a
        detector that does is answered with a note.
    """
    vendor = codec.capabilities.vendor_id
    proposal = DeploymentProposal(vendor=vendor)
    detector = _detectors().get(vendor)
    if detector is None:
        proposal.notes.append(
            f"No detector reads the hardware lines of {vendor} "
            f"configurations yet; declare the device yourself."
        )
        return proposal
    try:
        detected = detector(raw_text)
    except Exception as exc:
        # The text is whatever was pasted.  A detector that cannot read
        # it has read nothing; that is an answer, not a server error.
        # The type only: the message can quote the config.
        logger.warning("deployment detector for %s raised %s", vendor, type(exc).__name__)
        proposal.notes.append(
            "The lines that state the hardware could not be read; declare "
            "the device yourself."
        )
        return proposal
    if detected is None:
        proposal.notes.append(
            "The config does not say which device it came from; declare "
            "the device yourself."
        )
        return proposal

    proposal.fabric = detected.fabric
    proposal.evidence = list(dict.fromkeys(detected.evidence))[:MAX_EVIDENCE_LINES]
    proposal.notes = list(detected.notes)
    proposal.stated = bool(detected.members)
    if not detected.members:
        # The detector's first note is why: a stanza that names no
        # member, a stack banner with no stanza.
        return proposal
    if len(detected.members) > MAX_DEPLOYMENT_MEMBERS:
        # More devices than any declaration may list: not resolved one
        # by one, and not echoed back one by one.
        proposal.notes.insert(
            0,
            f"The config states {len(detected.members)} devices; a "
            f"deployment lists at most {MAX_DEPLOYMENT_MEMBERS}, so none can "
            f"be proposed.",
        )
        return proposal

    families: dict[str, FamilyDef] = {}
    members: list[DetectedMember] = []
    for member in detected.members:
        hit = registry.resolve(vendor, member.part)
        if hit is None:
            if member.part not in proposal.unknown_parts:
                proposal.unknown_parts.append(member.part)
            members.append(member)
            continue
        family, model = hit
        families[family.key] = family
        members.append(member.model_copy(update={"model": model.model}))
    proposal.members = members
    if proposal.unknown_parts:
        unknown = ", ".join(proposal.unknown_parts)
        proposal.notes.insert(
            0,
            f"No model family describes {unknown}, so no deployment can be "
            f"proposed.  A target profile for that device can be declared "
            f"instead, if one exists.",
        )
        return proposal
    if len(families) > 1:
        proposal.notes.insert(
            0,
            f"The members belong to different model families "
            f"({', '.join(families)}); no deployment can be proposed.",
        )
        return proposal

    (family,) = families.values()
    proposal.family = family.key
    mode_name, said = _mode_for(family, detected.fabric)
    if mode_name is None:
        proposal.notes.insert(0, said)
        return proposal
    if said:
        proposal.notes.append(said)
    proposal.mode = mode_name
    carries_ids = family.modes[mode_name].member_ids is not None
    try:
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
        inventory = compile_deployment(
            Deployment(vendor=vendor, **spec.model_dump()), registry,
        )
    except ValidationError as exc:
        # More members, or a longer name, than any declaration may
        # carry.  Said in our own words: pydantic's message quotes its
        # input.
        reasons = sorted({error["msg"] for error in exc.errors()})
        proposal.notes.insert(
            0,
            f"What the config states cannot be a deployment of "
            f"{family.display()}: {len(members)} member(s) stated; "
            f"{'; '.join(reasons)}.",
        )
        return proposal
    except DeploymentError as exc:
        proposal.notes.insert(
            0,
            f"What the config states does not compile as a deployment "
            f"of {family.display()}: {exc}",
        )
        return proposal
    proposal.deployment = spec
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
    # The same collection a translation makes, with the same folding.
    # It does NOT do what a translation does for a vendor whose ports
    # keep a factory name (`ports_keep_a_factory_name`): no such vendor
    # has a detector, and a test fails for the first that gets one
    # until this check is taught about them.
    used = collect_hardware_port_names(
        tree,
        classify=getattr(codec, "classify_port_name", None),
        always=names,
        fold=not getattr(codec, "port_names_case_sensitive", False),
    )
    proposal.used_port_count = len(used)
    missing = [name for name in used if name not in names]
    proposal.missing_port_count = len(missing)
    proposal.missing_ports = missing[:MAX_MISSING_PORTS]
    if not used:
        # Nothing to check against is not a check that passed.
        proposal.notes.append(
            "The config names no port, so the proposal could not be "
            "checked against the port names it uses."
        )
        return proposal
    proposal.consistent = not missing
    if missing:
        shown = ", ".join(missing[:8])
        if len(missing) > 8:
            shown += f" and {len(missing) - 8} more"
        proposal.notes.append(
            f"The config uses {len(missing)} port name(s) the "
            f"proposed device does not have ({shown}).  Possible causes: "
            f"a module is fitted that the config does not state; the text "
            f"is from more than one device; a name that is not a port of "
            f"the hardware.  Check before relying on this."
        )
    return proposal

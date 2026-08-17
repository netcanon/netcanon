"""
Capability-matrix-driven validation — translator pipeline stage 4.

Given a parsed tree and a target adapter, this service walks the
tree's xpaths, classifies each against the target's
:class:`CapabilityMatrix`, and returns a :class:`ValidationReport`
suitable for rendering the three-state banner (ok / warn / block) on
the migration UI.

Pure function — no I/O, no adapter instantiation, no configuration.
Same design as :mod:`netcanon.services.diff`.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..migration.codecs.base import CodecBase
from ..models.diff import CompatibilityReport
from ..models.migration import (
    CapabilityMatrix,
    DeviceClass,
    LossyPath,
    UnsupportedPath,
    ValidationReport,
)


def _enumerate_xpaths(
    tree: object, source: CodecBase | None = None
) -> Iterable[str]:
    """Yield xpaths for every leaf in *tree*.

    When a *source* adapter is supplied we delegate to its
    :meth:`CodecBase.iter_xpaths` override — the adapter is the only
    thing that knows how to walk its own tree shape.  Without *source*
    we fall back to the Phase 0 flat ``dict[str, str]`` walker so
    legacy callers (and the mock adapter in tests) keep working.
    """
    if source is not None:
        yield from source.iter_xpaths(tree)
        return
    if isinstance(tree, dict):
        for key in tree:
            if isinstance(key, str):
                yield key


def classify_tree(
    tree: object,
    caps: CapabilityMatrix,
    source: CodecBase | None = None,
) -> tuple[list[str], list[LossyPath], list[UnsupportedPath]]:
    """Classify every xpath in *tree* against *caps*.

    Helper split out from :func:`validate_against` so unit tests can
    exercise classification independently of severity aggregation.

    Args:
        tree: Adapter-internal tree representation.
        caps: Target adapter's capability matrix.
        source: Optional source adapter — supplies the xpath walker
            for non-dict tree shapes.  When ``None`` the flat
            ``dict[str, str]`` fallback is used.

    Returns:
        ``(supported_paths, lossy_paths, unsupported_paths)``.  Each
        list preserves discovery order; duplicate xpaths are preserved
        (one leaf per occurrence) so counts reflect impact.
    """
    supported: list[str] = []
    lossy: list[LossyPath] = []
    unsupported: list[UnsupportedPath] = []

    # Index lookups so we can return the declared LossyPath /
    # UnsupportedPath objects (carrying reason + severity), not just
    # path strings.
    lossy_by_path = {lp.path: lp for lp in caps.lossy}
    unsupp_by_path = {up.path: up for up in caps.unsupported}

    for xpath in _enumerate_xpaths(tree, source):
        kind = caps.classify(xpath)
        if kind == "supported":
            supported.append(xpath)
        elif kind == "lossy":
            lossy.append(lossy_by_path[xpath])
        else:  # "unsupported"
            unsupported.append(unsupp_by_path[xpath])
    return supported, lossy, unsupported


def validate_against(
    tree: object,
    target: CodecBase,
    source: CodecBase | None = None,
) -> ValidationReport:
    """Produce a :class:`ValidationReport` for *tree* against *target*.

    Severity rules:

    * Any ``unsupported`` path OR any ``lossy`` path with ``severity ==
      "error"`` → severity ``block`` (and ``compatible=False``).
    * Any remaining ``lossy`` path → severity ``warn``.
    * Otherwise → severity ``ok``.

    ``reasons`` is populated with one-liners the UI can show verbatim
    in the banner (same shape as ``CompatibilityReport.reasons`` in
    :mod:`netcanon.models.diff`).

    Args:
        tree: The parsed tree to validate.
        target: Adapter that will render *tree*; its capability
            matrix drives classification.
        source: Optional — adapter that produced *tree*.  Used to walk
            the tree when the source adapter uses a non-dict shape
            (e.g. :class:`CiscoIOSXECodec`'s nested dict).  Omitted
            for legacy callers that still pass flat ``dict[str, str]``.
    """
    supported, lossy, unsupported = classify_tree(
        tree, target.capabilities, source=source
    )
    reasons: list[str] = []

    # Promote any "error"-severity lossy path to a block condition —
    # treated identically to an unsupported path for severity purposes.
    hard_lossy = [lp for lp in lossy if lp.severity == "error"]

    if unsupported or hard_lossy:
        severity: str = "block"
        if unsupported:
            reasons.append(
                f"{len(unsupported)} unsupported path(s) the target "
                f"adapter cannot emit"
            )
        if hard_lossy:
            reasons.append(
                f"{len(hard_lossy)} lossy path(s) marked severity=error"
            )
    elif lossy:
        severity = "warn"
        reasons.append(
            f"{len(lossy)} lossy path(s) — migration will proceed with caveats"
        )
    else:
        severity = "ok"

    return ValidationReport(
        compatible=severity != "block",
        severity=severity,  # type: ignore[arg-type]
        supported_paths=supported,
        lossy_paths=lossy,
        unsupported_paths=unsupported,
        reasons=reasons,
    )


# ---------------------------------------------------------------------------
# Cross-device-class guardrail
# ---------------------------------------------------------------------------


def check_class_compat(
    source: CodecBase, target: CodecBase
) -> CompatibilityReport:
    """Is it sensible to translate *source* config into *target* config?

    Classes are the coarsest guardrail — e.g. translating a L2 switch
    config through a firewall adapter produces nonsense regardless of
    per-xpath support.  The rule is a non-empty intersection of the
    two adapters' ``device_classes`` declarations.

    Severity:
        * ``ok``   — at least one class in common.
        * ``warn`` — either adapter didn't declare any classes
          ("uncommitted" — common during adapter development).
        * ``block`` — both adapters declared classes AND the sets
          are disjoint.

    Shape matches :class:`CompatibilityReport` from
    :mod:`netcanon.models.diff` so the UI banner component stays the
    same regardless of which layer surfaced the mismatch.

    This function is a **gate**: its answer decides whether the job runs.
    Scope *notices* — which never refuse anything — live in
    :func:`check_scope_advisory`.  Keep the two separate; the reasoning is
    in the comment above this function's final ``return``.

    Args:
        source: Adapter that will parse the input.
        target: Adapter that will render the output.

    Returns:
        A :class:`CompatibilityReport` describing the outcome.
    """
    src = set(source.capabilities.device_classes)
    tgt = set(target.capabilities.device_classes)

    if not src and not tgt:
        return CompatibilityReport(
            compatible=True,
            severity="warn",
            reasons=[
                f"Neither adapter declares a device_class "
                f"({source.capabilities.adapter!r} or "
                f"{target.capabilities.adapter!r}) — proceed with caution.",
            ],
        )
    if not src:
        return CompatibilityReport(
            compatible=True,
            severity="warn",
            reasons=[
                f"Source adapter {source.capabilities.adapter!r} does not "
                f"declare a device_class; target declares "
                f"{sorted(c.value for c in tgt)}.",
            ],
        )
    if not tgt:
        return CompatibilityReport(
            compatible=True,
            severity="warn",
            reasons=[
                f"Target adapter {target.capabilities.adapter!r} does not "
                f"declare a device_class; source declares "
                f"{sorted(c.value for c in src)}.",
            ],
        )

    common = src & tgt
    if not common:
        return CompatibilityReport(
            compatible=False,
            severity="block",
            reasons=[
                f"Device-class mismatch: source adapter "
                f"{source.capabilities.adapter!r} declares "
                f"{sorted(c.value for c in src)} but target "
                f"{target.capabilities.adapter!r} declares "
                f"{sorted(c.value for c in tgt)}.",
                "Cross-class translation (e.g. switch -> firewall) "
                "almost always produces nonsense.",
            ],
        )

    # NOTE — do not add a firewall-target arm here, or anywhere above this
    # point.  Every codec declares ``router``, so a switch-only source and a
    # firewall-primary target still intersect and reach this line; but a
    # genuinely disjoint pair (a source declaring only ``switch`` against a
    # target declaring only ``firewall``) matches BOTH the block arm above and
    # any firewall-target predicate.  Hoisting one above the other makes this
    # guard's only refusal unreachable for every firewall target.  The scope
    # advisory is therefore a SEPARATE function — see
    # :func:`check_scope_advisory` — which also keeps this function's
    # gate semantics (block/allow) from being confused with a notice.
    return CompatibilityReport(
        compatible=True,
        severity="ok",
        reasons=[],
    )


# ---------------------------------------------------------------------------
# Scope advisory (notice, not a gate)
# ---------------------------------------------------------------------------

#: Per-target policy-binding grammar, named so the advisory never prints
#: FortiOS syntax on an OPNsense job.  Keyed by ``CapabilityMatrix.adapter``.
_POLICY_BINDING_PHRASE = {
    "fortigate_cli": "FortiOS policies bind to interface names (set srcintf / set dstintf)",
    "opnsense": "OPNsense rules bind to interface zone tags (<interface>lan</interface>)",
}
_POLICY_BINDING_FALLBACK = "Firewall policy binds to interface names"


def _primary_class(caps: CapabilityMatrix) -> DeviceClass | None:
    """First declared device class — the platform's scope declaration.

    See ``AGENTS.md`` § Hard Rules ("Never author or change a codec's
    ``device_classes[0]`` without applying the scope test").
    """
    classes = caps.device_classes
    return classes[0] if classes else None


def _is_firewall_primary(caps: CapabilityMatrix) -> bool:
    """``True`` iff this adapter's PRIMARY device class is ``firewall``.

    Keyed on position 0 deliberately, not on membership: ``mikrotik_routeros``,
    ``vyos`` and ``juniper_junos`` all declare ``firewall`` as a secondary
    class and are full-scope router/switch platforms.  A membership test
    misfires on all three.
    """
    return _primary_class(caps) is DeviceClass.firewall


def check_scope_advisory(
    source: CodecBase, target: CodecBase
) -> CompatibilityReport | None:
    """Notice for translations INTO a firewall-primary platform.

    This is deliberately **not** part of :func:`check_class_compat`.  That
    function is a gate whose contract is block-or-allow; this is a notice that
    never refuses anything.  Merging them would force the caller to demux on
    ``severity == "warn"``, which three of ``check_class_compat``'s own arms
    already return for an unrelated reason (an adapter that declares no
    classes at all) — and their text would then be rendered under this
    advisory's heading.

    Fires only when the target is firewall-primary and the source is not.
    A firewall-to-firewall pair is excluded on purpose: that direction is
    already loud, because the source codec's Tier-3 detector names the lost
    policy stanzas in ``dropped_tier3_sections``.  The silent direction — and
    the only one this covers — is switch/router into firewall.

    Args:
        source: Adapter that will parse the input.
        target: Adapter that will render the output.

    Returns:
        A ``warn``-severity, ``compatible=True`` report, or ``None`` when the
        pair does not warrant one.  ``None`` rather than an ``ok`` report so
        the caller needs no severity parsing to tell "no advisory" from
        "advisory that happens to be mild".
    """
    if not _is_firewall_primary(target.capabilities):
        return None
    if _is_firewall_primary(source.capabilities):
        return None

    adapter = target.capabilities.adapter
    binding = _POLICY_BINDING_PHRASE.get(adapter, _POLICY_BINDING_FALLBACK)
    return CompatibilityReport(
        compatible=True,
        severity="warn",
        reasons=[
            f"Target {adapter} is a firewall platform; Netcanon translates "
            f"its L2/L3 layer only.  It carries interface addressing, VLAN "
            f"interfaces and local users onto a firewall target - the policy "
            f"table, NAT, VPN and UTM are not emitted.  No banner reports the "
            f"target's missing policy plane: the Tier-3 banner reads your "
            f"source config, not the target.",
            f"{binding}, and the interface names in this output come from the "
            f"source config, rewritten by Netcanon's cross-vendor "
            f"interface-name translation - and by any target profile you "
            f"applied in the rename panel.  If you merge it into an appliance "
            f"that already carries policy, check every rule binding: a rule "
            f"can end up on a different interface than it was written for, or "
            f"on one this config does not define.",
        ],
    )

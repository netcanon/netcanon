"""
Capability-matrix-driven validation — translator pipeline stage 4.

Given a parsed tree and a target adapter, this service walks the
tree's xpaths, classifies each against the target's
:class:`CapabilityMatrix`, and returns a :class:`ValidationReport`
suitable for rendering the three-state banner (ok / warn / block) on
the migration UI.

Pure function — no I/O, no adapter instantiation, no configuration.
Same design as :mod:`netconfig.services.diff`.
"""

from __future__ import annotations

from typing import Iterable

from ..migration.adapters.base import AdapterBase
from ..models.diff import CompatibilityReport
from ..models.migration import (
    CapabilityMatrix,
    LossyPath,
    UnsupportedPath,
    ValidationReport,
)


def _enumerate_xpaths(
    tree: object, source: AdapterBase | None = None
) -> Iterable[str]:
    """Yield xpaths for every leaf in *tree*.

    When a *source* adapter is supplied we delegate to its
    :meth:`AdapterBase.iter_xpaths` override — the adapter is the only
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
    source: AdapterBase | None = None,
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
    target: AdapterBase,
    source: AdapterBase | None = None,
) -> ValidationReport:
    """Produce a :class:`ValidationReport` for *tree* against *target*.

    Severity rules:

    * Any ``unsupported`` path OR any ``lossy`` path with ``severity ==
      "error"`` → severity ``block`` (and ``compatible=False``).
    * Any remaining ``lossy`` path → severity ``warn``.
    * Otherwise → severity ``ok``.

    ``reasons`` is populated with one-liners the UI can show verbatim
    in the banner (same shape as ``CompatibilityReport.reasons`` in
    :mod:`netconfig.models.diff`).

    Args:
        tree: The parsed tree to validate.
        target: Adapter that will render *tree*; its capability
            matrix drives classification.
        source: Optional — adapter that produced *tree*.  Used to walk
            the tree when the source adapter uses a non-dict shape
            (e.g. :class:`CiscoIOSXEAdapter`'s nested dict).  Omitted
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
    source: AdapterBase, target: AdapterBase
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
    :mod:`netconfig.models.diff` so the UI banner component stays the
    same regardless of which layer surfaced the mismatch.

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

    return CompatibilityReport(
        compatible=True,
        severity="ok",
        reasons=[],
    )

"""
Pydantic models for the configuration diff feature.

Tier 1 (MVP): textual line diff between two stored configuration files.
Compatibility is anchored on the existing ``type_key`` (vendor/OS
classifier) and the file extension — matching both is "same-shape
configs", mismatching either is flagged as a hard-block unless the
caller explicitly sets ``force=true``.

Future tiers (tracked in ``translator-plans.txt``):
    * Tier 2 — per-vendor volatile-line filtering.
    * Tier 3 — semantic diff over the YANG canonical tree.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .backup import ConfigRecord


class DiffLine(BaseModel):
    """One line in the rendered diff.

    Attributes:
        kind: Render type — ``equal`` (present on both sides),
            ``add`` (right-only), ``remove`` (left-only), or
            ``context`` (shown around a change, equivalent to ``equal``
            but kept for future expansion to collapsed-context views).
        left_no: 1-based line number in the left file; ``None`` for
            ``add`` lines.
        right_no: 1-based line number in the right file; ``None`` for
            ``remove`` lines.
        text: The raw line text (trailing newline stripped).
    """

    kind: Literal["equal", "add", "remove", "context"]
    left_no: int | None
    right_no: int | None
    text: str


class CompatibilityReport(BaseModel):
    """Pre-flight check on whether two configs can be meaningfully diffed.

    Attributes:
        compatible: ``True`` when ``type_key`` and ``file_extension`` match
            on both records.
        severity:
            * ``ok``    — fully compatible; render the diff freely.
            * ``warn``  — match but one or more soft-mismatch signals
              (reserved for Phase B, e.g. differing OS version hints).
            * ``block`` — incompatible; API rejects with 422 unless the
              caller passes ``force=true``, in which case the diff is
              still rendered with a prominent red banner.
        reasons: Human-readable explanations appended to each signal.
    """

    compatible: bool
    severity: Literal["ok", "warn", "block"]
    reasons: list[str] = Field(default_factory=list)


class DiffRequest(BaseModel):
    """Request body for ``POST /api/v1/configs/diff``.

    Attributes:
        left: Filename of the left-hand (baseline) config.  Must match
            the output of ``GET /api/v1/configs/``.
        right: Filename of the right-hand (comparison) config.
        force: When ``True`` the compatibility check is advisory only —
            a ``block`` severity no longer produces a 422.  Exists to
            support deliberate cross-vendor comparisons; the rendered
            output carries a red warning banner.
    """

    left: str
    right: str
    force: bool = False


class DiffReport(BaseModel):
    """Result of a textual diff between two stored configurations.

    Attributes:
        left: Metadata record of the left-hand file.
        right: Metadata record of the right-hand file.
        compatibility: Pre-flight compatibility report.
        lines: Ordered sequence of ``DiffLine`` rows.
        stats: Count of each kind — ``added``, ``removed``, ``equal``.
            Computed once by the service layer so the UI doesn't have
            to re-scan ``lines``.
    """

    left: ConfigRecord
    right: ConfigRecord
    compatibility: CompatibilityReport
    lines: list[DiffLine]
    stats: dict[str, int]


class DiffGroup(BaseModel):
    """One rendered row in the folded (context-collapsed) diff view.

    The full-fidelity ``DiffReport.lines`` list can run to tens of
    thousands of entries for large configs (FortiGate, Junos).  The
    ``fold_context()`` service helper squashes long runs of equal lines
    that are far from any change into a single "collapsed" group so the
    rendered DOM stays manageable.

    Attributes:
        kind: ``equal`` / ``add`` / ``remove`` — a single visible line
            (``lines`` holds exactly one element).
            ``collapsed`` — a folded run of equal lines hidden until the
            user clicks to expand (``lines`` holds every hidden line in
            original order).
        lines: One-element list for a visible group; ``N``-element list
            for a ``collapsed`` group where ``N`` is the hidden count.
    """

    kind: Literal["equal", "add", "remove", "collapsed"]
    lines: list[DiffLine]

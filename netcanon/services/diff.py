"""
Stateless diff service — Tier 1 (textual line diff).

No I/O.  No dependencies on FastAPI or storage.  Callers are responsible
for loading the two configs, then handing the raw text strings (and the
``ConfigRecord`` metadata) to :func:`compute_diff`.

This design lets the service be:

* Unit-tested with synthetic inputs (no tmp dirs, no fixtures).
* Re-used verbatim by the API route and the HTML view.
* A clean extension point for Tier 2 (volatile filter) and Tier 3
  (semantic diff), which will add new functions alongside this one
  rather than thread kwargs through the existing signature.
"""

from __future__ import annotations

import difflib

from ..models.backup import ConfigRecord
from ..models.diff import (
    CompatibilityReport,
    DiffGroup,
    DiffLine,
    DiffReport,
)


def check_compatibility(
    left: ConfigRecord, right: ConfigRecord
) -> CompatibilityReport:
    """Classify a pair of ``ConfigRecord``s as diff-compatible or not.

    Two records are fully compatible when both ``device_type`` (the
    canonical ``type_key`` identifier) AND ``file_extension`` match.
    Mismatching either is a ``block`` — textual diffs across vendors or
    between ``.cfg`` and ``.xml`` are noise, not signal.

    Same record on both sides is allowed (and produces an empty diff);
    the caller may still want to compute it, e.g. to verify a file is
    unchanged.

    Args:
        left: Metadata of the left-hand config.
        right: Metadata of the right-hand config.

    Returns:
        A :class:`CompatibilityReport`.  ``severity`` is ``ok`` when
        both anchors match, ``block`` otherwise.  ``warn`` is reserved
        for future Phase B signals (e.g. differing OS version hints).
    """
    reasons: list[str] = []
    if left.device_type != right.device_type:
        reasons.append(
            f"type_key mismatch: {left.device_type!r} vs {right.device_type!r}"
        )
    if left.file_extension != right.file_extension:
        reasons.append(
            f"file_extension mismatch: {left.file_extension!r} vs "
            f"{right.file_extension!r}"
        )
    if not reasons:
        return CompatibilityReport(compatible=True, severity="ok", reasons=[])
    return CompatibilityReport(compatible=False, severity="block", reasons=reasons)


def compute_diff(
    left: ConfigRecord,
    left_text: str,
    right: ConfigRecord,
    right_text: str,
    *,
    force: bool = False,
) -> DiffReport:
    """Produce a textual line-level diff report for two configs.

    Uses :class:`difflib.SequenceMatcher` to identify add / remove /
    equal runs in a single pass, then expands each run into
    :class:`DiffLine` entries with 1-based line numbers preserved on
    whichever side the line exists.  Stats are accumulated inline so the
    UI doesn't need to re-scan the result.

    The compatibility report is produced unconditionally; the caller
    (route layer) decides whether to refuse a ``block`` severity.  When
    ``force=True`` is passed through to the caller, this function still
    produces a valid report — the UI uses the report to render a red
    banner above the diff itself.

    Args:
        left:       Metadata of the left-hand config.
        left_text:  Raw text of the left-hand config.
        right:      Metadata of the right-hand config.
        right_text: Raw text of the right-hand config.
        force:      Stored on the returned report's compatibility object
            so the template can surface whether the user overrode a
            block.  Does not change diff computation.

    Returns:
        A fully-populated :class:`DiffReport`.
    """
    compat = check_compatibility(left, right)
    # force=True doesn't change compatibility, but it's useful to remember
    # that the caller overrode the block so templates can show a banner.
    if force and not compat.compatible:
        compat = CompatibilityReport(
            compatible=False,
            severity="block",
            reasons=compat.reasons + ["force=true override applied by caller"],
        )

    left_lines = left_text.splitlines()
    right_lines = right_text.splitlines()

    lines: list[DiffLine] = []
    stats = {"added": 0, "removed": 0, "equal": 0}

    matcher = difflib.SequenceMatcher(
        a=left_lines, b=right_lines, autojunk=False
    )
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                lines.append(
                    DiffLine(
                        kind="equal",
                        left_no=i1 + offset + 1,
                        right_no=j1 + offset + 1,
                        text=left_lines[i1 + offset],
                    )
                )
                stats["equal"] += 1
        elif tag == "delete":
            for offset in range(i2 - i1):
                lines.append(
                    DiffLine(
                        kind="remove",
                        left_no=i1 + offset + 1,
                        right_no=None,
                        text=left_lines[i1 + offset],
                    )
                )
                stats["removed"] += 1
        elif tag == "insert":
            for offset in range(j2 - j1):
                lines.append(
                    DiffLine(
                        kind="add",
                        left_no=None,
                        right_no=j1 + offset + 1,
                        text=right_lines[j1 + offset],
                    )
                )
                stats["added"] += 1
        elif tag == "replace":
            # A replace is a deletion on the left + insertion on the
            # right.  SequenceMatcher already told us the exact ranges;
            # emit them in deletion-then-insertion order so reviewers
            # always see the outgoing line before its replacement.
            for offset in range(i2 - i1):
                lines.append(
                    DiffLine(
                        kind="remove",
                        left_no=i1 + offset + 1,
                        right_no=None,
                        text=left_lines[i1 + offset],
                    )
                )
                stats["removed"] += 1
            for offset in range(j2 - j1):
                lines.append(
                    DiffLine(
                        kind="add",
                        left_no=None,
                        right_no=j1 + offset + 1,
                        text=right_lines[j1 + offset],
                    )
                )
                stats["added"] += 1

    return DiffReport(
        left=left,
        right=right,
        compatibility=compat,
        lines=lines,
        stats=stats,
    )


def fold_context(
    lines: list[DiffLine], *, context: int = 3
) -> list[DiffGroup]:
    """Collapse long runs of equal lines that are far from any change.

    A line is "visible" if it is a change (``add`` / ``remove``) OR is
    within *context* lines of a change.  Every other equal line is
    "cold" and can safely be hidden from the initial render.

    The input is traversed once; cold runs are collected into a single
    ``DiffGroup(kind="collapsed", lines=[...])`` containing every hidden
    line in original order so the template can stash them in a
    ``<template>`` sibling for client-side expansion.

    For small diffs (e.g. same-file compare with no changes) every line
    is cold, so the entire diff collapses to a single group — the UI
    can then still render a useful summary.

    Args:
        lines: The full ``DiffReport.lines`` list.
        context: Number of equal lines to keep visible on either side of
            each change.  Default ``3`` matches the git / unified-diff
            convention.  Must be ``>= 0``.

    Returns:
        List of ``DiffGroup`` in render order.
    """
    if context < 0:
        raise ValueError(f"context must be >= 0, got {context!r}")
    n = len(lines)
    if n == 0:
        return []

    # Distance from each line to the nearest change (add/remove).  A
    # two-sweep Manhattan-style pass: seed change positions at 0, sweep
    # forward taking min(current, prev+1), then backward the same way.
    INF = n + 1
    dist = [0 if L.kind in ("add", "remove") else INF for L in lines]
    for i in range(1, n):
        if dist[i - 1] + 1 < dist[i]:
            dist[i] = dist[i - 1] + 1
    for i in range(n - 2, -1, -1):
        if dist[i + 1] + 1 < dist[i]:
            dist[i] = dist[i + 1] + 1

    def is_visible(i: int) -> bool:
        return dist[i] <= context

    groups: list[DiffGroup] = []
    i = 0
    while i < n:
        if is_visible(i):
            groups.append(DiffGroup(kind=lines[i].kind, lines=[lines[i]]))
            i += 1
        else:
            start = i
            while i < n and not is_visible(i):
                i += 1
            groups.append(
                DiffGroup(kind="collapsed", lines=lines[start:i])
            )
    return groups

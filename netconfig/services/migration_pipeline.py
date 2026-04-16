"""
Translator pipeline orchestrator — Phase 0 skeleton.

Phase 0 scope: ``run_plan`` — parse → (transforms) → validate → render.
No collect (caller supplies raw text), no diff, no deploy, no
snapshot.  Each later phase will layer stages on via additional public
functions; the existing ones should NEVER change shape to avoid
breaking API routes and tests.

Pure function — no I/O, no global state.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from ..migration.adapters.base import AdapterBase, ParseError, RenderError
from ..models.migration import (
    MigrationJob,
    MigrationJobStatus,
    TransformSpec,
)
from .migration_validate import check_class_compat, validate_against


#: A transform is any callable that accepts a tree and returns a new
#: tree.  Phase 0 does not resolve ``TransformSpec.name`` against a
#: registry — callers pass already-bound callables directly.  Phase 2
#: will add a resolver keyed on ``TransformSpec.name``.
TransformCallable = Callable[[Any], Any]


def run_plan(
    source: AdapterBase,
    target: AdapterBase,
    raw_text: str,
    transforms: list[TransformCallable] | None = None,
    transform_specs: list[TransformSpec] | None = None,
    force: bool = False,
) -> MigrationJob:
    """Execute parse → transform → validate → render against *raw_text*.

    Returns a fully-populated :class:`MigrationJob` regardless of
    outcome — successful runs reach ``completed``; any stage failure
    moves the job to ``failed`` with the error captured in ``.error``.

    Cross-device-class guard:
        Before parsing, :func:`check_class_compat` is called.  If the
        source and target adapters declare disjoint ``device_classes``
        (e.g. ``switch`` vs ``firewall``) the job immediately fails
        with ``error`` describing the mismatch.  Callers can pass
        ``force=True`` to skip the guard — deliberately cross-class
        experiments are legit, but the default refuses them because
        the resulting render is almost always nonsense.

    Args:
        source: Adapter used to parse the input.
        target: Adapter used to render the output.
        raw_text: Raw config text from *source*.  In Phase 1+ this
            slot is fed by the existing collectors layer, matching
            the backup engine's design.
        transforms: Ordered list of callables to apply between parse
            and validate.  Defaults to an empty list.
        transform_specs: Serialisable record of what was applied,
            stored on the ``MigrationJob``.  Expected to correspond
            1:1 with *transforms*; callers that care about
            reproducibility should pass both.
        force: Skip the cross-device-class guard.  Default ``False``.

    Returns:
        A :class:`MigrationJob` in a terminal state.
    """
    job = MigrationJob(
        source_adapter=source.name,
        target_adapter=target.name,
        transforms=transform_specs or [],
    )

    # Stage 0 — device-class compatibility guard.  Runs BEFORE parse
    # so a mismatched pair fails instantly without spending any
    # collector or parser time.
    class_compat = check_class_compat(source, target)
    if not class_compat.compatible and not force:
        job.status = MigrationJobStatus.failed
        job.error = (
            "Device-class guard refused migration: "
            + " ".join(class_compat.reasons)
            + " Pass force=True to override (NOT recommended)."
        )
        job.completed_at = datetime.now(timezone.utc)
        return job

    try:
        # Stage 2 — parse
        job.status = MigrationJobStatus.parsing
        tree = source.parse(raw_text)

        # Stage 3 — transforms
        job.status = MigrationJobStatus.transforming
        for fn in transforms or []:
            tree = fn(tree)

        # Stage 4 — validate
        job.status = MigrationJobStatus.validating
        # Pass the source adapter so the validator can walk adapter-
        # specific tree shapes via ``AdapterBase.iter_xpaths``.
        job.validation = validate_against(tree, target, source=source)

        # Stage 5 — render
        job.status = MigrationJobStatus.rendering
        job.rendered = target.render(tree)

    except ParseError as exc:
        job.status = MigrationJobStatus.failed
        job.error = f"parse failed: {exc}"
    except RenderError as exc:
        job.status = MigrationJobStatus.failed
        job.error = f"render failed: {exc}"
    except Exception as exc:  # noqa: BLE001 — honest catch-all
        job.status = MigrationJobStatus.failed
        job.error = f"unexpected error in stage {job.status.value}: {exc}"
    else:
        # Terminal success: mirror the BackupJob three-way convention.
        # Phase 0 has no partial condition — validate.severity == "block"
        # without force is treated by upstream callers (not the pipeline
        # itself) — so success means "all stages ran".
        if job.validation and job.validation.severity == "block":
            # Tree was rendered but the target can't faithfully consume
            # it.  Still a terminal state, but clearly flagged.
            job.status = MigrationJobStatus.partial
            job.error = (
                "Render completed but target adapter reported unsupported "
                "or error-level lossy paths — output may not be safe to "
                "deploy as-is."
            )
        else:
            job.status = MigrationJobStatus.completed

    job.completed_at = datetime.now(timezone.utc)
    return job

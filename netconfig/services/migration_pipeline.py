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

from ..migration.codecs.base import CodecBase, ParseError, RenderError
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
    source: CodecBase,
    target: CodecBase,
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
        source_codec=source.name,
        target_codec=target.name,
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
        # specific tree shapes via ``CodecBase.iter_xpaths``.
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


def run_plan_with_rename(
    source: CodecBase,
    target: CodecBase,
    raw_text: str,
    port_rename_map: dict[str, str | None] | None = None,
    transforms: list[TransformCallable] | None = None,
    transform_specs: list[TransformSpec] | None = None,
    force: bool = False,
) -> MigrationJob:
    """Extended pipeline: parse → port-name rewrite → transforms →
    validate → render.

    Wraps :func:`run_plan` with the cross-vendor port-name translator
    from :mod:`netconfig.migration.canonical.port_names` inserted as
    the FIRST transform in the chain.  The translator:

    * Rewrites every port-name field in the canonical tree
      (``interfaces[].name``, ``vlans[].tagged_ports``, etc.) from
      the source vendor's convention to the target vendor's, via
      each codec's own ``classify_port_name`` / ``format_port_identity``
      methods — strictly through the vendor-agnostic
      :class:`PortIdentity` bridge, never hard-coding any vendor
      pair.

    * Applies user-supplied *port_rename_map* entries FIRST (Tier 2
      override); falls back to auto-heuristic for any source name
      not in the map.

    * Populates :attr:`MigrationJob.port_renames` with the full
      applied source→target map and :attr:`MigrationJob.warnings`
      with per-name advisories for the complexity cases (breakout,
      hw-aggregate, unsupported kinds).

    Existing :func:`run_plan` remains unchanged — its signature is
    frozen per CLAUDE.md "never change signatures of pipeline-stage
    functions" rule.  Callers that want port-name normalisation
    explicitly choose this function; legacy callers of ``run_plan``
    get the historical behaviour (names pass through verbatim).

    Args:
        source: Source codec (classifies port names).
        target: Target codec (formats port names + renders output).
        raw_text: Source-vendor config text.
        port_rename_map: Optional user override map of
            source-name → target-name.  Entries win over the
            auto-heuristic.  Empty / None = fully auto.
        transforms: Additional transforms to apply AFTER the
            port-name rewrite.
        transform_specs: Serialisable transform record (mirrors
            *transforms* for job-reproducibility).
        force: Skip the cross-device-class guard.

    Returns:
        A :class:`MigrationJob` with ``rendered`` populated on
        success plus ``port_renames`` and ``warnings`` describing
        what the translator did.
    """
    # Lazy import to avoid circular dependency at module import time
    # (port_names imports CodecBase; this module imports CodecBase).
    from ..migration.canonical.port_names import build_port_rename_transform

    rename_transform, rename_result = build_port_rename_transform(
        source, target, rename_map=port_rename_map
    )

    combined_transforms = [rename_transform, *(transforms or [])]

    job = run_plan(
        source=source,
        target=target,
        raw_text=raw_text,
        transforms=combined_transforms,
        transform_specs=transform_specs,
        force=force,
    )

    # Attach the translator outcome AFTER run_plan so the job carries
    # what actually happened even when a later stage (validate/render)
    # failed — operators want to see the rename decisions that led up
    # to the failure.
    if rename_result.applied:
        job.port_renames = dict(rename_result.applied)
    if rename_result.warnings:
        # Extend rather than replace — run_plan itself doesn't populate
        # warnings today, but future pipeline stages might, and this
        # wrapper shouldn't eat them.
        job.warnings.extend(rename_result.warnings)
    if rename_result.dropped:
        job.port_drops = list(rename_result.dropped)

    return job

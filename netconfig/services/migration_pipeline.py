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


def run_plan_with_overrides(
    source: CodecBase,
    target: CodecBase,
    raw_text: str,
    port_rename_map: dict[str, str | None] | None = None,
    transforms: list[TransformCallable] | None = None,
    transform_specs: list[TransformSpec] | None = None,
    force: bool = False,
) -> MigrationJob:
    """Extended pipeline with user-override support for multiple
    canonical categories.

    Shared engine for every per-pane override surface (ports today;
    VLANs / local_users / SNMP / RADIUS in subsequent commits).  Each
    per-pane API endpoint in :mod:`netconfig.api.routes.migration`
    calls this function with only its category's override map
    populated; the other categories' params default to None (no-op).
    When multiple panes' overrides need to land together, the caller
    populates multiple maps in one call — future extension, not
    currently exercised by any shipped endpoint.

    Current category support:
      * ``port_rename_map`` — see
        :func:`netconfig.migration.canonical.port_names.build_port_rename_transform`.

    Planned future-commit categories:
      * ``vlan_rename_map`` — VLAN ID mapping (P2C2)
      * ``local_user_rename_map`` — username mapping (P2C5+)
      * ``snmp_override_map`` — community / trap-host mapping (P2C5+)

    Cross-device-class guard + validate stage are unchanged from
    :func:`run_plan`; this function composes the override transforms
    AHEAD of any caller-supplied transforms so overrides are the
    first thing that happens to the parsed tree.

    Frozen-signatures rule: NEW function (signature free to grow);
    :func:`run_plan` and :func:`run_plan_with_rename` remain
    unchanged.  Adding a new override category in a later commit is
    a same-function signature extension (optional param with default
    None) — backwards compatible.

    Args:
        source: Source codec.
        target: Target codec.
        raw_text: Source-vendor config text.
        port_rename_map: Optional source-name → target-name override
            map.  Entries win over the auto-heuristic.  Empty / None
            = fully auto.  Set to ``{}`` (rather than None) to opt
            into the rename-aware pipeline with no explicit overrides
            — this is what the UI sends when the operator has
            selected a target profile but not yet customised any row.
        transforms: Additional transforms applied AFTER all override
            transforms.
        transform_specs: Serialisable transform record.
        force: Skip the cross-device-class guard.

    Returns:
        :class:`MigrationJob` with ``rendered`` on success.  Per-
        category outcome fields are populated when their override
        was engaged:
          * ``port_renames`` / ``port_drops`` / ``warnings`` when
            ``port_rename_map is not None``.
    """
    # Lazy import to avoid circular dependency at module import time
    # (port_names imports CodecBase; this module imports CodecBase).
    from ..migration.canonical.port_names import build_port_rename_transform

    override_transforms: list[TransformCallable] = []
    rename_result = None

    # Port-rename category.  Engaged when the caller explicitly opts
    # in by passing a dict (even an empty one).  None means "don't
    # run the translator at all" — legacy run_plan behaviour.
    if port_rename_map is not None:
        rename_transform, rename_result = build_port_rename_transform(
            source, target, rename_map=port_rename_map
        )
        override_transforms.append(rename_transform)

    combined_transforms = override_transforms + list(transforms or [])

    job = run_plan(
        source=source,
        target=target,
        raw_text=raw_text,
        transforms=combined_transforms,
        transform_specs=transform_specs,
        force=force,
    )

    # Attach per-category outcomes AFTER run_plan so the job carries
    # what actually happened even when a later stage (validate/render)
    # failed — operators want to see the override decisions that led
    # up to the failure.
    if rename_result is not None:
        if rename_result.applied:
            job.port_renames = dict(rename_result.applied)
        if rename_result.warnings:
            # Extend rather than replace — future stages might push
            # warnings of their own.
            job.warnings.extend(rename_result.warnings)
        if rename_result.dropped:
            job.port_drops = list(rename_result.dropped)

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
    """Port-rename-specific pipeline entry (legacy signature).

    Thin compatibility wrapper around :func:`run_plan_with_overrides`
    preserved so existing callers (the UI's ``POST /api/v1/migration/plan``
    path, integration tests, e2e suite, sample code in this repo's
    README) keep working unchanged.  New code should prefer
    :func:`run_plan_with_overrides` directly.

    Signature-frozen per CLAUDE.md: dozens of tests and the main
    migration API route depend on the exact parameter shape.  Any
    parameter additions needed for multi-category overrides go on
    :func:`run_plan_with_overrides`, not here.

    See :func:`run_plan_with_overrides` for the canonical
    documentation of what port_rename_map does.

    Behaviour-preservation note: pre-P2C1 ``run_plan_with_rename``
    ALWAYS engaged the rename pipeline, regardless of whether the
    caller passed a rename map.  The new engine distinguishes
    ``None`` (don't engage) from ``{}`` (engage with no overrides);
    this wrapper normalises ``None`` → ``{}`` so existing callers
    (tests, the UI's ``POST /plan`` handler) keep getting the
    rename-aware behaviour they were written against.
    """
    return run_plan_with_overrides(
        source=source,
        target=target,
        raw_text=raw_text,
        port_rename_map=port_rename_map if port_rename_map is not None else {},
        transforms=transforms,
        transform_specs=transform_specs,
        force=force,
    )

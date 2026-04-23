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
    vlan_rename_map: dict[int, int | None] | None = None,
    local_user_rename_map: dict[str, str | None] | None = None,
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
      * ``vlan_rename_map`` — see
        :func:`netconfig.migration.canonical.vlan_names.build_vlan_rename_transform`.
      * ``local_user_rename_map`` — see
        :func:`netconfig.migration.canonical.local_user_names.build_local_user_rename_transform`.

    Planned future-commit categories:
      * ``snmp_override_map`` — community / trap-host mapping (P2C5+)
      * ``radius_override_map`` — host / key mapping (P2C5+)

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
        vlan_rename_map: Optional source_vlan_id → target_vlan_id
            override map.  Same None-vs-{} sentinel semantics as
            ``port_rename_map``.  Entries with ``None`` values drop
            the VLAN entirely + detach every referring interface.
            Collisions (two source IDs → same target ID) trigger
            merge-by-union of port memberships.
        local_user_rename_map: Optional source_name → target_name
            override map for :class:`CanonicalLocalUser.name`.
            Same None-vs-{} sentinel semantics.  ``None`` values
            drop the user entirely.  Collisions merge on highest
            privilege_level + first-wins role + first-wins hash.
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
          * ``vlan_renames`` / ``vlan_drops`` / ``warnings`` when
            ``vlan_rename_map is not None``.
          * ``local_user_renames`` / ``local_user_drops`` /
            ``warnings`` when ``local_user_rename_map is not None``.

        Capture-only fields always populate (all are needed by
        the Tier-3 rename modal even when no overrides engaged):
          * ``source_vlans`` — VLAN IDs as parsed from source
            config, before any rewrites.
          * ``source_local_users`` — local-user names as parsed
            from source config, before any rewrites.
          * ``source_hostname`` — canonical hostname, feeds the
            modal's localStorage ack key.
    """
    # Lazy imports to avoid circular dependency at module import time
    # (these modules import CodecBase; this module imports CodecBase).
    from ..migration.canonical.local_user_names import (
        build_local_user_rename_transform,
    )
    from ..migration.canonical.port_names import build_port_rename_transform
    from ..migration.canonical.vlan_names import build_vlan_rename_transform

    override_transforms: list[TransformCallable] = []
    rename_result = None
    vlan_result = None
    local_user_result = None

    # Capture-first transform — snapshots the post-parse canonical
    # tree's VLAN IDs + local-user names + hostname for the UI's
    # rename modal BEFORE any user overrides rewrite them.  The
    # result flows back onto the job via source_* fields so each
    # rename pane can enumerate every entity the operator could
    # rewrite/drop, and so localStorage persistence keys stay
    # stable across page reloads.
    captured: dict[str, Any] = {
        "vlan_ids": [],
        "local_user_names": [],
        "hostname": "",
    }

    def _capture_source_shape(tree: Any) -> Any:
        # Duck-typed access — mock adapters produce plain dicts that
        # don't have ``.vlans``; canonical trees do.  Either way we
        # fall through with empty defaults rather than crashing.
        vlans = getattr(tree, "vlans", None) or []
        captured["vlan_ids"] = [getattr(v, "id", None) for v in vlans]
        captured["vlan_ids"] = [i for i in captured["vlan_ids"] if i is not None]
        users = getattr(tree, "local_users", None) or []
        captured["local_user_names"] = [
            getattr(u, "name", "") for u in users
        ]
        captured["local_user_names"] = [
            n for n in captured["local_user_names"] if n
        ]
        captured["hostname"] = getattr(tree, "hostname", "") or ""
        return tree

    override_transforms.append(_capture_source_shape)

    # Port-rename category.  Engaged when the caller explicitly opts
    # in by passing a dict (even an empty one).  None means "don't
    # run the translator at all" — legacy run_plan behaviour.
    if port_rename_map is not None:
        rename_transform, rename_result = build_port_rename_transform(
            source, target, rename_map=port_rename_map
        )
        override_transforms.append(rename_transform)

    # VLAN-rename category.  Same None-vs-dict sentinel semantics.
    # Runs AFTER port rename so port-name rewrites don't have to
    # worry about VLAN-ID references still changing underneath them.
    if vlan_rename_map is not None:
        vlan_transform, vlan_result = build_vlan_rename_transform(
            rename_map=vlan_rename_map
        )
        override_transforms.append(vlan_transform)

    # Local-user-rename category.  Same None-vs-dict sentinel.
    # Ordering is independent of ports/VLANs — usernames don't
    # reference either — so this can run at any point.  Placing
    # it last in the override chain keeps the ordering invariant
    # documented in the docstring stable (ports → vlans → users).
    if local_user_rename_map is not None:
        local_user_transform, local_user_result = (
            build_local_user_rename_transform(
                rename_map=local_user_rename_map,
            )
        )
        override_transforms.append(local_user_transform)

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

    if vlan_result is not None:
        if vlan_result.applied:
            job.vlan_renames = dict(vlan_result.applied)
        if vlan_result.warnings:
            job.warnings.extend(vlan_result.warnings)
        if vlan_result.dropped:
            job.vlan_drops = list(vlan_result.dropped)

    if local_user_result is not None:
        if local_user_result.applied:
            job.local_user_renames = dict(local_user_result.applied)
        if local_user_result.warnings:
            job.warnings.extend(local_user_result.warnings)
        if local_user_result.dropped:
            job.local_user_drops = list(local_user_result.dropped)

    # Source-shape fields — ALWAYS populated when the capture ran
    # (which it did, unconditionally).  Empty lists are fine —
    # the UI handles that by showing each pane's empty state.
    job.source_vlans = list(captured.get("vlan_ids", []))
    job.source_local_users = list(captured.get("local_user_names", []))
    job.source_hostname = captured.get("hostname", "") or ""

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

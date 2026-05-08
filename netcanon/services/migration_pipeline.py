"""
Translator pipeline orchestrator — load-bearing migration engine.

This module is THE migration orchestrator: every code path that turns
a parsed source-vendor canonical tree into a rendered target-vendor
config funnels through one of the three public functions defined
here.  API routes (``netcanon.api.routes.migration``), the desktop
UI's preview/plan endpoints, integration tests, and dozens of unit
tests all bind directly to these signatures.

Public surface (frozen signatures — see Hard Rules below):

  * :func:`run_plan` — minimal pipeline: parse → caller-supplied
    transforms → validate → render.  No per-pane override knowledge;
    callers compose their own transform list.

  * :func:`run_plan_with_rename` — legacy wrapper that engages the
    port-name rename pipeline unconditionally.  Preserved as a thin
    forward to :func:`run_plan_with_overrides` so existing callers
    (the UI's ``POST /plan`` route, integration tests, e2e suite,
    sample code in this repo's README) keep working with their
    original parameter shape.  New code should target
    :func:`run_plan_with_overrides` directly.

  * :func:`run_plan_with_overrides` — the main entry for per-pane
    override flows.  Composes the five rename categories in a fixed
    order ahead of any caller-supplied transforms, threads results
    back onto the :class:`MigrationJob`, and snapshots source-side
    enumerations for the UI's rename modal via the capture-first
    transform (see below).

Per-pane override categories supported on :func:`run_plan_with_overrides`
(all SHIPPED):

  1. ``port_rename_map`` — physical / logical interface-name rewrites
     (Cisco ``Gi1/0/24`` → Aruba ``1/24``, etc.).
  2. ``vlan_rename_map`` — VLAN-ID rewrites + drops + collision merge.
  3. ``local_user_rename_map`` — local admin user-name rewrites + drops.
  4. ``snmp_community_rename_map`` — v1/v2c community string rewrite or
     clear (single-slot scalar; uses dict shape for API symmetry).
  5. ``snmpv3_user_rename_map`` — SNMPv3 USM securityName rewrites +
     drops.  Auth / priv keys + group + engine_id follow the renamed
     record; first-wins on collisions.

Sentinel semantics (uniform across all five categories):

  * ``rename_map is None`` — pane is NOT engaged; the corresponding
    canonical orchestrator never runs.  Result fields on the
    :class:`MigrationJob` stay at their defaults.
  * ``rename_map == {}`` — pane IS engaged with auto-heuristic only.
    The orchestrator runs, captures the source enumeration, and
    applies any built-in heuristics (e.g. port_names cross-vendor
    classifier → formatter bridge) but the operator has not pinned
    any explicit rewrite.  The UI sends ``{}`` when the operator
    has selected a target profile but not yet customised any row.
  * ``rename_map == {src: tgt}`` — explicit rewrite.  Operator
    overrides win over any heuristic.
  * ``rename_map == {src: None}`` — explicit drop.  Entry is removed
    from the canonical tree (with cascading reference cleanup as
    appropriate per category).

Capture-first transform (load-bearing for the rename modal):

The first transform inserted by :func:`run_plan_with_overrides`
unconditionally snapshots the post-parse canonical tree's
enumerations and stashes them onto the :class:`MigrationJob` as:

  * ``source_vlans`` — VLAN IDs as parsed.
  * ``source_local_users`` — local-user names as parsed.
  * ``source_snmp_community`` — SNMP community string (empty when
    the source had no SNMP block or no community).
  * ``source_snmpv3_users`` — SNMPv3 USM user names as parsed.
  * ``source_hostname`` — canonical hostname (drives the modal's
    localStorage ack key).

These fields are populated even when no overrides are engaged
because the Tier-3 rename modal needs to enumerate every entity the
operator could rewrite or drop, and localStorage persistence keys
must stay stable across page reloads.

Hard Rules (AGENTS.md, repeated here for proximity):

  * NEVER change the signatures of :func:`run_plan`,
    :func:`run_plan_with_rename`, or :func:`run_plan_with_overrides`.
    API routes and dozens of tests depend on the exact parameter
    shape.  New rename categories grow :func:`run_plan_with_overrides`
    as additional optional parameters defaulting to ``None`` — that
    is a backwards-compatible signature extension, not a change.
  * NEW pipeline behaviour goes on a NEW public function, not an
    existing one.

Pure function — no I/O, no global state.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable

from ..migration.codecs.base import CodecBase, ParseError, RenderError
from ..models.migration import (
    MigrationJob,
    MigrationJobStatus,
    TransformSpec,
)
from .migration_validate import check_class_compat, validate_against

logger = logging.getLogger(__name__)


#: A transform is any callable that accepts a tree and returns a new
#: tree.  Callers pass already-bound callables directly; ``TransformSpec``
#: records what was applied for round-trip / replay purposes but is not
#: resolved against a registry by this module — the API and UI layers
#: own their own transform-name resolution.
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

    logger.debug(
        "run_plan %s: entry %s → %s (raw=%d bytes, transforms=%d, force=%s)",
        job.id[:8],
        source.name,
        target.name,
        len(raw_text),
        len(transforms or []),
        force,
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
        # WARNING rather than ERROR — the guard working as designed
        # isn't a system fault; operator may have legitimately made
        # a picker mistake the UI surfaces back to them.  Logs give
        # ops a breadcrumb when customer tickets reference "my
        # translation refused" without detail.
        logger.warning(
            "run_plan %s: device-class guard refused %s → %s: %s",
            job.id[:8], source.name, target.name,
            " ".join(class_compat.reasons),
        )
        return job

    try:
        # Stage 2 — parse
        job.status = MigrationJobStatus.parsing
        logger.debug("run_plan %s: stage=parse", job.id[:8])
        tree = source.parse(raw_text)
        # Surface parser-detected Tier-3 stanza headers onto the job so
        # the migrate page's "Detected in source but not translated"
        # banner can render.  Notification-only — never read by render
        # or transforms (the field is a list[str] of human-readable
        # labels, not canonical config data).
        job.dropped_tier3_sections = list(
            getattr(tree, "dropped_tier3_sections", []) or []
        )

        # Stage 3 — transforms
        job.status = MigrationJobStatus.transforming
        logger.debug(
            "run_plan %s: stage=transform (%d transform(s))",
            job.id[:8], len(transforms or []),
        )
        for fn in transforms or []:
            tree = fn(tree)

        # Stage 4 — validate
        job.status = MigrationJobStatus.validating
        logger.debug("run_plan %s: stage=validate", job.id[:8])
        # Pass the source adapter so the validator can walk adapter-
        # specific tree shapes via ``CodecBase.iter_xpaths``.
        job.validation = validate_against(tree, target, source=source)

        # Stage 5 — render
        job.status = MigrationJobStatus.rendering
        logger.debug("run_plan %s: stage=render", job.id[:8])
        job.rendered = target.render(tree)

    except ParseError as exc:
        job.status = MigrationJobStatus.failed
        job.error = f"parse failed: {exc}"
        logger.exception(
            "run_plan %s: parse failed for %s → %s",
            job.id[:8], source.name, target.name,
        )
    except RenderError as exc:
        job.status = MigrationJobStatus.failed
        job.error = f"render failed: {exc}"
        logger.exception(
            "run_plan %s: render failed for %s → %s",
            job.id[:8], source.name, target.name,
        )
    except Exception as exc:  # noqa: BLE001 — honest catch-all
        # Preserve the stage the job was in at the moment of failure —
        # ``job.status`` holds the in-progress enum when the exception
        # fires, so capture it BEFORE reassigning to ``failed``.
        failing_stage = job.status.value
        job.status = MigrationJobStatus.failed
        job.error = f"unexpected error in stage {failing_stage}: {exc}"
        logger.exception(
            "run_plan %s: unexpected error in stage=%s for %s → %s",
            job.id[:8], failing_stage, source.name, target.name,
        )
    else:
        # Terminal success: three-way outcome — completed when the
        # render is safe to deploy, partial when the target adapter
        # reports a block-level lossy / unsupported path that survived
        # the run.
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
    logger.debug(
        "run_plan %s: terminal status=%s (rendered=%d bytes, "
        "validation=%s)",
        job.id[:8],
        job.status.value,
        len(job.rendered or ""),
        job.validation.severity if job.validation else "n/a",
    )
    return job


def run_plan_with_overrides(
    source: CodecBase,
    target: CodecBase,
    raw_text: str,
    port_rename_map: dict[str, str | None] | None = None,
    vlan_rename_map: dict[int, int | None] | None = None,
    local_user_rename_map: dict[str, str | None] | None = None,
    snmp_community_rename_map: dict[str, str | None] | None = None,
    snmpv3_user_rename_map: dict[str, str | None] | None = None,
    transforms: list[TransformCallable] | None = None,
    transform_specs: list[TransformSpec] | None = None,
    force: bool = False,
) -> MigrationJob:
    """Extended pipeline with user-override support for multiple
    canonical categories.

    Shared engine for every per-pane override surface (ports, VLANs,
    local_users, snmp_community, snmpv3_user — all shipped).  Each
    per-pane API endpoint in :mod:`netcanon.api.routes.migration`
    calls this function with only its category's override map
    populated; the other categories' params default to None (no-op).

    Current category support:
      * ``port_rename_map`` — see
        :func:`netcanon.migration.canonical.port_names.build_port_rename_transform`.
      * ``vlan_rename_map`` — see
        :func:`netcanon.migration.canonical.vlan_names.build_vlan_rename_transform`.
      * ``local_user_rename_map`` — see
        :func:`netcanon.migration.canonical.local_user_names.build_local_user_rename_transform`.
      * ``snmp_community_rename_map`` — see
        :func:`netcanon.migration.canonical.snmp_names.build_snmp_community_rename_transform`.
      * ``snmpv3_user_rename_map`` — see
        :func:`netcanon.migration.canonical.snmpv3_user_names.build_snmpv3_user_rename_transform`.

    Planned future-commit categories:
      * ``snmp_trap_host_rename_map`` — trap-host list rename
      * ``ntp_server_rename_map`` — NTP peer IP / hostname rewrites
      * ``dns_server_rename_map`` — DNS resolver IP rewrites
      * ``syslog_server_rename_map`` — syslog collector IP rewrites
      * ``radius_override_map`` — RADIUS host / key rewrites

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
        snmp_community_rename_map: Optional source_community →
            target_community override map for
            :class:`CanonicalSNMP.community`.  Effectively single-
            entry (the canonical tree holds one community string)
            but uses the dict shape for API symmetry with the other
            categories.  ``None`` value clears the community string
            (render paths then omit the SNMP block).
        snmpv3_user_rename_map: Optional source_name → target_name
            override map for :attr:`CanonicalSNMPv3User.name`
            (USM securityName).  Fifth per-pane category.  ``None``
            values drop the user entirely; collisions merge on
            first-wins.  Auth / priv keys + group + engine_id
            follow the renamed record; keys are never combined
            across users.
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
          * ``snmp_community_renames`` / ``snmp_community_drops`` /
            ``warnings`` when
            ``snmp_community_rename_map is not None``.
          * ``snmpv3_user_renames`` / ``snmpv3_user_drops`` /
            ``warnings`` when ``snmpv3_user_rename_map is not None``.

        Capture-only fields always populate (all are needed by
        the Tier-3 rename modal even when no overrides engaged):
          * ``source_vlans`` — VLAN IDs as parsed from source
            config, before any rewrites.
          * ``source_local_users`` — local-user names as parsed
            from source config, before any rewrites.
          * ``source_snmp_community`` — current community string
            from source config, before any rewrites.  Empty string
            when the source config has no SNMP block or a bare
            SNMP block without a community configured.
          * ``source_snmpv3_users`` — SNMPv3 USM user names as
            parsed from source config, before any rewrites.  Empty
            list when the source config had v1/v2c only.
          * ``source_hostname`` — canonical hostname, feeds the
            modal's localStorage ack key.
    """
    # Lazy imports to avoid circular dependency at module import time
    # (these modules import CodecBase; this module imports CodecBase).
    from ..migration.canonical.local_user_names import (
        build_local_user_rename_transform,
    )
    from ..migration.canonical.port_names import build_port_rename_transform
    from ..migration.canonical.snmp_names import (
        build_snmp_community_rename_transform,
    )
    from ..migration.canonical.snmpv3_user_names import (
        build_snmpv3_user_rename_transform,
    )
    from ..migration.canonical.vlan_names import build_vlan_rename_transform

    # Summarise which categories the caller opted into BEFORE any
    # transforms run so a subsequent failure has a breadcrumb for
    # "what was the operator actually trying to do?".  None = not
    # engaged; {} = engaged with auto-heuristic only; {k: v, ...} =
    # explicit overrides.
    engaged_categories: dict[str, int | str] = {}
    if port_rename_map is not None:
        engaged_categories["port"] = len(port_rename_map) or "auto"
    if vlan_rename_map is not None:
        engaged_categories["vlan"] = len(vlan_rename_map) or "auto"
    if local_user_rename_map is not None:
        engaged_categories["local_user"] = (
            len(local_user_rename_map) or "auto"
        )
    if snmp_community_rename_map is not None:
        engaged_categories["snmp_community"] = (
            len(snmp_community_rename_map) or "auto"
        )
    if snmpv3_user_rename_map is not None:
        engaged_categories["snmpv3_user"] = (
            len(snmpv3_user_rename_map) or "auto"
        )
    logger.debug(
        "run_plan_with_overrides: %s → %s engaged=%s",
        source.name, target.name,
        engaged_categories or "none (capture-only)",
    )

    override_transforms: list[TransformCallable] = []
    rename_result = None
    vlan_result = None
    local_user_result = None
    snmp_result = None
    snmpv3_user_result = None

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
        "snmp_community": "",
        "snmpv3_user_names": [],
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
        snmp = getattr(tree, "snmp", None)
        captured["snmp_community"] = (
            getattr(snmp, "community", "") or ""
        ) if snmp is not None else ""
        # SNMPv3 user names — drives the v3 rename pane's
        # enumeration.  Empty list when source had v1/v2c only
        # or no SNMP block at all.
        v3 = (
            getattr(snmp, "v3_users", []) or []
        ) if snmp is not None else []
        captured["snmpv3_user_names"] = [
            getattr(u, "name", "") for u in v3
        ]
        captured["snmpv3_user_names"] = [
            n for n in captured["snmpv3_user_names"] if n
        ]
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

    # SNMP-community rename category.  Same None-vs-dict sentinel.
    # Like local-users, independent of the other categories — SNMP
    # config doesn't reference ports or VLANs or users.  Ordering
    # invariant: ports → vlans → users → snmp_community → snmpv3_user.
    if snmp_community_rename_map is not None:
        snmp_transform, snmp_result = (
            build_snmp_community_rename_transform(
                rename_map=snmp_community_rename_map,
            )
        )
        override_transforms.append(snmp_transform)

    # SNMPv3 user-name rename category.  Independent of every other
    # category — v3 users don't reference ports / VLANs / local
    # users / community.  Placed last in the override chain
    # (consistent extension point — future ntp_server_rename_map
    # etc. append here).
    if snmpv3_user_rename_map is not None:
        snmpv3_user_transform, snmpv3_user_result = (
            build_snmpv3_user_rename_transform(
                rename_map=snmpv3_user_rename_map,
            )
        )
        override_transforms.append(snmpv3_user_transform)

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

    if snmp_result is not None:
        if snmp_result.applied:
            job.snmp_community_renames = dict(snmp_result.applied)
        if snmp_result.warnings:
            job.warnings.extend(snmp_result.warnings)
        if snmp_result.dropped:
            job.snmp_community_drops = list(snmp_result.dropped)

    if snmpv3_user_result is not None:
        if snmpv3_user_result.applied:
            job.snmpv3_user_renames = dict(snmpv3_user_result.applied)
        if snmpv3_user_result.warnings:
            job.warnings.extend(snmpv3_user_result.warnings)
        if snmpv3_user_result.dropped:
            job.snmpv3_user_drops = list(snmpv3_user_result.dropped)

    # Source-shape fields — ALWAYS populated when the capture ran
    # (which it did, unconditionally).  Empty lists are fine —
    # the UI handles that by showing each pane's empty state.
    job.source_vlans = list(captured.get("vlan_ids", []))
    job.source_local_users = list(captured.get("local_user_names", []))
    job.source_snmp_community = captured.get("snmp_community", "") or ""
    job.source_snmpv3_users = list(captured.get("snmpv3_user_names", []))
    job.source_hostname = captured.get("hostname", "") or ""

    # Post-run DEBUG summary — mirrors the per-category outcome
    # fields the UI will read.  Useful for post-hoc debugging when
    # a customer says "my rename didn't fire": the debug log shows
    # whether the override transform ran AND how many entries
    # actually applied.
    logger.debug(
        "run_plan_with_overrides %s: %s → %s captured "
        "vlans=%d users=%d snmp=%s v3_users=%d hostname=%r | applied "
        "ports=%d vlans=%d users=%d snmp=%d v3=%d | drops "
        "ports=%d vlans=%d users=%d snmp=%d v3=%d",
        job.id[:8],
        source.name, target.name,
        len(job.source_vlans),
        len(job.source_local_users),
        "yes" if job.source_snmp_community else "no",
        len(job.source_snmpv3_users),
        job.source_hostname,
        len(job.port_renames),
        len(job.vlan_renames),
        len(job.local_user_renames),
        len(job.snmp_community_renames),
        len(job.snmpv3_user_renames),
        len(job.port_drops),
        len(job.vlan_drops),
        len(job.local_user_drops),
        len(job.snmp_community_drops),
        len(job.snmpv3_user_drops),
    )
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

    Signature-frozen per AGENTS.md: dozens of tests and the main
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

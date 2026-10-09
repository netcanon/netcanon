"""
Translator pipeline orchestrator — load-bearing migration engine.

This module is THE migration orchestrator: every code path that turns
a parsed source-vendor canonical tree into a rendered target-vendor
config funnels through one of the public functions defined
here.  API routes (``netcanon.api.routes.migration``), the desktop
UI's preview/plan endpoints, integration tests, and dozens of unit
tests all bind directly to these signatures.

Public surface (the first three signatures are frozen — see Hard
Rules below).  Those three differ only in how much per-pane override
plumbing they pre-compose ahead of caller-supplied transforms;
the capture-first transform installed by
:func:`run_plan_with_overrides` (described further down) lets the
UI's rename modal pre-populate source-side enumerations even
before any rename engages.

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

  * :func:`run_plan_with_models` — the model-aware entry.  Takes the
    port inventory of the source device and of the target device,
    pairs the ports the config uses by POSITION, and forwards the
    resulting rename map (under any operator overrides) to
    :func:`run_plan_with_overrides`.  It then checks the finished
    run for two source ports on one target name, drops any name
    nobody decided that caused one, and records the outcome on
    ``MigrationJob.port_mapping_plan``.  For a target that finds a
    port by a factory name (RouterOS) it also sets that name on every
    port it can account for, and reads the output back for the line
    that uses it.  Its signature is not one of the three frozen ones.

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
  * ``source_ports`` — hardware port names as parsed, including
    ports no rename touches (``port_renames`` records only names
    that changed).

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
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from ..migration.codecs.base import CodecBase, ParseError, RenderError
from ..models.migration import (
    MigrationJob,
    MigrationJobStatus,
    TransformSpec,
)
from ..models.port_inventory import Inventory, MappingPlan
from .migration_validate import (
    check_class_compat,
    check_scope_advisory,
    validate_against,
)

logger = logging.getLogger(__name__)


#: A transform is any callable that accepts a tree and returns a new
#: tree.  Callers pass already-bound callables directly; ``TransformSpec``
#: records what was applied for round-trip / replay purposes but is not
#: resolved against a registry by this module — the API and UI layers
#: own their own transform-name resolution.
TransformCallable = Callable[[Any], Any]


def _input_not_recognized(raw_text: str, tree: Any, job: MigrationJob) -> bool:
    """True when *non-trivial* input parsed to an empty canonical tree.

    This is the **whole-input-rejection** silent-success surface (blind
    audit ``65f9c01`` T0-2, the output-side half of the silent-loss
    meta-finding): a permissive ``parse()`` returns an empty intent for
    input it doesn't understand (wrong source vendor, garbage, a config
    in a format this codec can't read), the validator then walks nothing,
    severity stays ``ok``, and the job would otherwise reach ``completed``
    with a banner-only render and zero warnings.  The web UI already flags
    this (``migrate.html`` ``isEmptyCompleted`` → parse-failure banner),
    but the backend ``MigrationJob.status`` — and therefore the HTTP /
    automation contract (``X-Netcanon-Job-Status``) — stayed ``completed``,
    so a CI gate that only checks status saw a green light for a translation
    that produced nothing.  This lifts the UI's signal to the pipeline.

    Gated tightly so a legitimate translation is never mislabelled:

      * the input must be **non-trivial** (non-whitespace) — an empty
        submission is vacuously empty, not a rejection (and most codecs
        raise ``ParseError`` on empty input anyway, never reaching here);
      * the validator must have recognized **zero** paths — any supported
        / lossy / unsupported path means the parse understood something,
        so a tiny-but-valid config (e.g. just ``hostname R1``) is safe;
      * **no Tier-3 sections were detected** — an all-Tier-3 config (e.g.
        a firewall-only ruleset) already carries its own honest "detected
        in source but not translated" signal via
        ``dropped_tier3_sections``, so it is a *recognized* (if
        untranslatable) input, not a rejection.

    Mirrors the UI's ``isEmptyCompleted`` zero-path test, plus the Tier-3
    exemption so the backend signal is at least as precise as the banner.

    Only applies to a real :class:`CanonicalIntent` tree: the internal
    ``mock`` reference codec and ad-hoc test stubs return a plain ``dict``
    by design (a deliberate no-op parse, not a parse that "recognized
    nothing"), so they are never flagged — same non-canonical guard the
    port-name orchestrator uses.
    """
    # Lazy import — mirrors translate_port_names' non-canonical guard and
    # avoids any import-time coupling from this codec-agnostic orchestrator.
    from ..migration.canonical.intent import CanonicalIntent

    if not isinstance(tree, CanonicalIntent):
        return False
    if not (raw_text or "").strip():
        return False
    if job.dropped_tier3_sections:
        return False
    report = job.validation
    if report is None:
        return False
    return not (
        report.supported_paths
        or report.lossy_paths
        or report.unsupported_paths
    )


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
        job.completed_at = datetime.now(UTC)
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

    # Stage 0b — scope advisory.  A NOTICE, not a gate: it never refuses and
    # never changes job.status.  Kept separate from the guard above because
    # that function's `warn` severity is already claimed by "an adapter
    # declared no device_classes", which is a different statement entirely.
    scope_advisory = check_scope_advisory(source, target)
    if scope_advisory is not None:
        job.scope_advisories.extend(scope_advisory.reasons)

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
    except Exception as exc:
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
        elif _input_not_recognized(raw_text, tree, job):
            # Whole-input rejection (audit 65f9c01 T0-2): non-trivial
            # input parsed to an empty tree — the source vendor almost
            # certainly doesn't match the input.  Surfacing this as
            # `partial` (not `completed`) makes the API / automation
            # contract honest, matching the UI's empty-result banner.
            job.status = MigrationJobStatus.partial
            job.error = (
                "No source constructs were recognized: the input is "
                "non-empty but parsed to an empty configuration (0 "
                "supported / lossy / unsupported paths) and rendered only "
                "a bare scaffold. The selected source vendor most likely "
                "does not match the input format — treat this as a failed "
                "translation, not a clean result."
            )
        else:
            job.status = MigrationJobStatus.completed

    job.completed_at = datetime.now(UTC)
    logger.debug(
        "run_plan %s: terminal status=%s (rendered=%d bytes, "
        "validation=%s)",
        job.id[:8],
        job.status.value,
        len(job.rendered or ""),
        job.validation.severity if job.validation else "n/a",
    )
    return job


def run_plan_with_overrides(  # noqa: C901
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

    Planned future-commit categories: see
    `docs/v0.2.0-planning/` for the active backlog of additional
    per-pane override surfaces (NTP / DNS / syslog / RADIUS / SNMP
    trap-host).  Listing inline here drifts every release; the
    planning folder is the canonical source.

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
            map.  Entries win over the auto-heuristic.  ``{}`` engages
            the auto-heuristic with no explicit overrides (what the UI
            sends when the operator opened a rename pane but customised
            nothing, and what ``POST /plan`` passes by default so a plain
            translation renders native target-vendor names).  ``None``
            does NOT run the port-name translator at all — verbatim
            source names, the legacy :func:`run_plan` behaviour (see the
            ``if port_rename_map is not None`` guard below).
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
          * ``source_ports`` — hardware port names the source config
            references, whether or not any rename touched them, as
            far as the source codec can tell a port from a logical
            interface (see ``collect_hardware_port_names``).
    """
    # Lazy imports to avoid circular dependency at module import time
    # (these modules import CodecBase; this module imports CodecBase).
    from ..migration.canonical.intent import CanonicalIntent
    from ..migration.canonical.local_user_names import (
        build_local_user_rename_transform,
    )
    from ..migration.canonical.port_names import (
        build_port_rename_transform,
        collect_hardware_port_names,
    )
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
        "ports": [],
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
        # Hardware port names -- every one, including a port that will
        # keep its name (which `port_renames` never records).  Only a
        # real canonical tree has the structure to enumerate.
        if isinstance(tree, CanonicalIntent):
            captured["ports"] = collect_hardware_port_names(
                tree, classify=getattr(source, "classify_port_name", None),
                fold=not getattr(source, "port_names_case_sensitive", False),
            )
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
    job.source_ports = list(captured.get("ports", []))

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


def _sub_interface_followers(
    plan: MappingPlan,
    operator_map: dict[str, str | None],
    names: dict[str, str | None],
) -> dict[str, str | None]:
    """Explicit entries that make a sub-interface follow its parent port.

    ``ge-0/0/0.54`` is not a port of any inventory; its parent is.
    Between two configs of the same codec the unit suffix means the
    same thing on both sides, so where the parent goes the
    sub-interface goes too — and where the parent is dropped, so is
    it.  Left to the name-shape translator instead, a classifier that
    folds a unit into its port (Junos) would send it onto the port
    itself, and one that does not recognise it (IOS-XE) would leave it
    behind under the old name.

    The parent's target is the operator's when they named the parent,
    else the name the pairing gives it on the target (*names*) —
    which for a port that keeps an operator's own name is that name,
    not the hardware it moved to.

    Args:
        plan: The pairing; its off-inventory names are the candidates.
        operator_map: The operator's own entries, as applied.
        names: Source port to the name it has on the target, as the
            pairing (and any pinned label) decided.

    Returns:
        A rename-map entry for each sub-interface that follows its
        parent: the parent's target with the unit, or ``None`` where
        the parent is dropped.
    """
    followers: dict[str, str | None] = {}
    for name in plan.off_inventory:
        parent, dot, unit = name.rpartition(".")
        # A unit suffix is a number.  A RouterOS port an operator named
        # ``ether1.backup`` is not a sub-interface of ``ether1``.
        if not (dot and unit.isdigit()):
            continue
        if parent in operator_map:
            target = operator_map[parent]
        elif parent in names:
            target = names[parent]
        else:
            continue
        followers[name] = f"{target}.{unit}" if target else None
    return followers


def _undecided_clashes(
    every: list[str],
    used: list[str],
    merged: dict[str, str | None],
    job: MigrationJob,
    target_names: list[str],
    source_names: list[str] | None = None,
    fold_source: bool = True,
    fold_target: bool = True,
    hardware: dict[str, str] | None = None,
) -> list[str]:
    """Names nobody decided that the finished run put somewhere they
    must not be.

    Two cases, both read from the run rather than predicted:

    * a name ended on a target that another name also ended on, and at
      least one of them is a hardware port the config uses.  Every
      member the pairing or the operator decided stays; the undecided
      ones lose.  Where NONE was decided, one keeps the name — a port
      of the declared source if there is one, else a hardware port,
      else the first — because the clash is among names the
      translator alone placed, and deleting all of them would lose a
      port whose place was good.
    * a LOGICAL name (an aggregate, say) ended on a port of the
      declared target.  Nothing may share that name with it yet, but a
      physical port of the target is not where an aggregate belongs.

    Args:
        every: Every name the config references.
        used: The hardware ports among them.
        merged: The map the run was given: a key is a decided name.
        job: The finished run.
        target_names: The ports of the declared target.
        source_names: The ports of the declared source, as the config
            names them.
        fold_source: Source names compare without regard to case.
        fold_target: Target names do.
        hardware: Which hardware each name's port is looked up by in
            the output, on a target that keeps a factory name beside a
            port's own (RouterOS).  Two names on one piece of
            hardware clash although they share no name.
    """
    from ..migration.port_mapping import fused_targets, name_key

    ports = set(used)
    own = set(source_names or ())
    losers: set[str] = set()
    clashes = list(fused_targets(
        every, job.port_renames, job.port_drops, involving=used,
        fold_source=fold_source, fold_target=fold_target,
    ).values())
    if hardware:
        clashes.extend(fused_targets(
            every, {**job.port_renames, **hardware}, job.port_drops,
            involving=used, fold_source=fold_source, fold_target=fold_target,
        ).values())
    for names in clashes:
        undecided = [name for name in names if name not in merged]
        if len(undecided) == len(names):
            # The declared device's own port before a name the device
            # does not list, whichever the config wrote first.
            keeper = next(
                (n for n in undecided if n in own),
                next((n for n in undecided if n in ports), undecided[0]),
            )
            undecided = [name for name in undecided if name != keeper]
        losers.update(undecided)
    gone = set(job.port_drops)
    on_target = {name_key(name, fold_target) for name in target_names}
    for name in every:
        if name in ports or name in merged or name in gone:
            continue
        if name_key(job.port_renames.get(name, name), fold_target) in on_target:
            losers.add(name)
    return sorted(losers)


def _unlisted_landings(
    every: list[str],
    used: list[str],
    merged: dict[str, str | None],
    job: MigrationJob,
    source: CodecBase,
    target: CodecBase,
    target_names: list[str],
    fold_target: bool,
) -> dict[str, str]:
    """Logical names nobody decided that the run put on a PORT the
    declared target does not list.

    The complement of the second case of :func:`_undecided_clashes`.
    A VLAN interface a source codec reads as a port (FortiGate ``DMZ``
    as a physical port, ``MGMT`` as the management port) is formatted
    as one for the target (``GigabitEthernet0/1``; ``em1``; the
    ``oobm`` block).  If the target device has that port the name is
    displaced; if it has not, nothing collides — and the interface's
    config is on a port the device does not have, in a job that
    reported success.  Not dropped (nothing shares the name); listed,
    and the job asks for a decision.

    A name counts when the result reads as a hardware port to the
    TARGET codec, or when the SOURCE codec read the name itself as
    one: a target's own form for a management port need not read back
    as anything (AOS-S ``oobm``).  A LAG, an SVI or a loopback that
    was given the target's own form for one is where it belongs.

    Args:
        every: Every name the config references.
        used: The hardware ports among them — not logical names, and
            reported as off-inventory when the model lacks them.
        merged: The map the run was given: a key is a decided name.
        job: The finished run.
        source: Source codec.
        target: Target codec.
        target_names: The ports of the declared target.
        fold_target: Target names compare without regard to case.
    """
    from ..migration.canonical.port_names import HARDWARE_PORT_KINDS
    from ..migration.port_mapping import name_key

    def reads_as_a_port(codec: CodecBase, name: str) -> bool:
        classify = getattr(codec, "classify_port_name", None)
        try:
            identity = classify(name) if classify is not None else None
        except Exception:
            # Naming a doubt is a courtesy to the report; it must not
            # be able to fail the job.
            return False
        return identity is not None and identity.kind in HARDWARE_PORT_KINDS

    ports = set(used)
    on_target = {name_key(name, fold_target) for name in target_names}
    found: dict[str, str] = {}
    for name in every:
        if name in ports or name in merged:
            continue
        # ``port_renames`` holds only names that changed, and none
        # that was dropped.
        final = job.port_renames.get(name)
        if not final or name_key(final, fold_target) in on_target:
            continue
        if reads_as_a_port(target, final) or reads_as_a_port(source, name):
            found[name] = final
    return found


def _stale_next_hops(
    tree: Any,
    job: MigrationJob,
    same_codec: bool,
    positions: dict[str, str | None],
) -> list[str]:
    """Destinations of static routes whose next hop still names a
    source port the run moved or dropped.

    The translator rewrites a ``gateway`` that is exactly the name of
    an interface of the tree (and, between two configs of one codec,
    such a name with a unit), and removes the route when that
    interface is dropped.  What it leaves as written: a LIST of
    gateways (RouterOS ``gateway=ether1,ether2``), a routing-table
    suffix (``ether3@main``), across vendors a unit of an interface
    (Junos ``next-hop et-0/0/24.0``) — and a next hop that names a
    port of the declared source the config gives no interface record,
    which the translator cannot know is a port.  Read here from the
    parsed source tree, the finished run and the pairing, so the plan
    can say it.

    A list that names the same ports after the run as before — its own
    two members exchanged — is still right, and is not listed.

    Args:
        tree: The parsed source tree.
        job: The finished run.
        same_codec: Source and target are one codec.
        positions: For every port of the declared source, by the name
            the config uses: the target port it is paired with, or
            ``None`` where it has no place.
    """
    from ..migration.canonical.port_names import route_port_reference

    named = {iface.name for iface in tree.interfaces}
    gone = set(job.port_drops)

    def now(name: str) -> str | None:
        """Where the port *name* is after the run; ``None`` if gone."""
        if name in named:
            return None if name in gone else job.port_renames.get(name, name)
        return positions.get(name, name)

    stale: list[str] = []
    for route in tree.static_routes:
        if not route.gateway or (route.interface and route.interface in gone):
            continue
        reference = route_port_reference(route, named)
        if reference is not None:
            port, unit = reference
            # Followed, or removed with its port -- except a unit hop
            # across vendors, which is rewritten only on a drop.
            if port in gone or same_codec or not unit:
                continue
            if now(port) != port:
                stale.append(route.destination)
            continue
        hops: list[str] = []
        for hop in route.gateway.split(","):
            hop = hop.partition("@")[0].strip()
            port, dot, unit = hop.rpartition(".")
            candidates = [hop, port] if dot and unit.isdigit() else [hop]
            hops.extend(
                name for name in candidates
                if name in named or name in positions
            )
        # A hop that went is ``None`` there, which no hop is: one
        # comparison covers "moved" and "gone".
        if hops and {now(name) for name in hops} != set(hops):
            stale.append(route.destination)
    return stale


def _management_form(source: CodecBase, target: CodecBase, name: str) -> str:
    """The name the ordinary translation gives a management port
    called *name* on the target (``oobm`` on AOS-S), or ``""`` when
    the target has no form for one or the name cannot be read."""
    try:
        identity = source.classify_port_name(name)
        if identity is None or identity.kind == "unknown":
            return ""
        identity = identity.model_copy(update={"kind": "mgmt"})
        return target.format_port_identity(identity) or ""
    except Exception:
        # Naming a form is a courtesy to the report; it must not be
        # able to fail the job.
        return ""


def _read_operator_map(
    port_rename_map: dict[str, str | None] | None,
    target_names: list[str],
    fold_target: bool,
) -> tuple[dict[str, str | None], list[str]]:
    """The operator's port map as it will be applied, and the keys of
    the entries that were set aside.

    A target is stripped, and -- where another letter case cannot be
    another interface on the target platform (it has no case, or it
    names every interface itself in lower case) -- re-spelt the way
    the declared target spells that port, so ``1/a1`` cannot be passed
    off as a second port beside ``1/A1``.  Where an operator chooses
    interface names as free text (FortiOS, RouterOS) a name is taken
    as typed: ``DMZ`` beside a port ``dmz`` is the operator's own
    interface, not a misspelling of the port.

    An entry whose target is blank, or is neither text nor ``None``,
    decides nothing and is set aside: passed on, a blank would render a
    port with no name and a non-text value would replace the pairing's
    entry with nothing.  (The API's model refuses the second; a direct
    caller can send it.)
    """
    from ..migration.port_mapping import name_key

    spelt: dict[str, list[str]] = {}
    if fold_target:
        for name in target_names:
            spelt.setdefault(name_key(name), []).append(name)
    operator_map: dict[str, str | None] = {}
    ignored: list[str] = []
    for key, value in (port_rename_map or {}).items():
        if value is None:
            operator_map[key] = None
            continue
        text = value.strip() if isinstance(value, str) else ""
        if not text:
            ignored.append(key)
            continue
        same = spelt.get(name_key(text), [])
        operator_map[key] = same[0] if len(same) == 1 else text
    return operator_map, ignored


def _taken_with_dropped_ports(
    tree: Any, port_drops: list[str],
) -> tuple[set[str], dict[str, list[str]]]:
    """What the ports a run dropped took with them.

    The translator removes a route or a DHCP pool that names a dropped
    port, a dropped member from its LAG, a VRRP track entry and a VTEP
    source; the job reports only the port.  Read here from the parsed
    SOURCE tree and the job's drop list, so the plan can say it.

    Returns:
        The dropped names, and the outcome lists keyed as
        :func:`settle_plan` takes them.
    """
    from ..migration.canonical.port_names import route_port_reference

    dropped = set(port_drops)
    named = {iface.name for iface in tree.interfaces}
    emptied_lags: list[str] = []
    shrunk_lags: list[str] = []
    for lag in tree.lags:
        members = {member for member in lag.members if member}
        members.update(
            iface.name for iface in tree.interfaces
            if lag.name and iface.lag_member_of == lag.name
        )
        lost = members & dropped
        if members and lost == members:
            emptied_lags.append(lag.name)
        elif lost:
            shrunk_lags.append(lag.name)

    def route_lost(route: Any) -> bool:
        if route.interface and route.interface in dropped:
            return True
        # A next hop that is an interface name, not an address.
        reference = route_port_reference(route, named)
        return reference is not None and reference[0] in dropped

    return dropped, {
        "emptied_lags": emptied_lags,
        "shrunk_lags": shrunk_lags,
        "lost_routes": [
            route.destination for route in tree.static_routes if route_lost(route)
        ],
        "lost_dhcp_pools": [
            pool.network or pool.interface for pool in tree.dhcp_servers
            if pool.interface and pool.interface in dropped
        ],
        "lost_tracking": sorted({
            iface.name for iface in tree.interfaces
            if iface.name not in dropped and any(
                tracked in dropped
                for group in iface.vrrp_groups
                for tracked in group.track_interfaces
            )
        }),
        "lost_vtep_sources": sorted({
            vx.source_interface for vx in tree.vxlan_vnis
            if vx.source_interface and vx.source_interface in dropped
        }),
    }


def _key_by_the_configs_name(
    operator_map: dict[str, str | None],
    plan: MappingPlan,
    every: list[str],
    ignored: list[str],
) -> None:
    """Re-key, in place, an operator's entry that names a port by its
    FACTORY name where the config has a name of its own for the port.

    The key of an entry is the name the config uses.  A RouterOS port
    the operator called ``core-a`` is ``core-a`` there — but the
    device model, which an operator may be reading, lists ``ether2``.
    With devices declared the plan knows which port that is
    (``labelled_ports``), so ``{"ether2": ...}`` is taken for
    ``core-a`` rather than ignored: ignored, a requested drop was not
    made and the job still reported success.

    Only where it cannot be read two ways: the key is not itself a
    name the config uses, and the port has no real entry under its
    own name.  Otherwise the entry is left as it is, and the
    translator says it matched nothing.  An entry that was set aside
    for a blank target is re-keyed the same way, so that it is still
    reported, once.  A blank entry beside a real one for the same
    port decided nothing and is nobody's: the real one stands, and
    nothing is said to have been ignored.

    Args:
        operator_map: The operator's entries, as applied; re-keyed in
            place.
        plan: The pairing, whose ``labelled_ports`` says which port a
            factory name is.
        every: Every name the config references.
        ignored: Keys of the entries that were set aside; re-keyed in
            place.
    """
    present = set(every)
    by_factory = {factory: name for name, factory in plan.labelled_ports.items()}
    for key in [key for key in operator_map if key not in present]:
        name = by_factory.get(key)
        if name is not None and name not in operator_map:
            operator_map[name] = operator_map.pop(key)
    for index, key in enumerate(ignored):
        name = by_factory.get(key)
        if key not in present and name is not None and name not in operator_map:
            ignored[index] = name
    ignored[:] = list(dict.fromkeys(key for key in ignored if key not in operator_map))


def _management_forms(
    plan: MappingPlan,
    source: CodecBase,
    target: CodecBase,
    operator_map: dict[str, str | None],
    fold_target: bool,
) -> dict[str, str]:
    """For each used management port the target model has no place
    for, the form the ordinary translation gives one on this target.

    An override that names that form in another spelling is re-spelt,
    in place, in *operator_map*: ``OOBM`` is ``oobm``, and a renderer
    matches the form exactly.

    Args:
        plan: The pairing; its unplaced management ports are read.
        source: Source codec.
        target: Target codec.
        operator_map: The operator's entries, as applied; re-spelt in
            place.
        fold_target: Target names compare without regard to case.

    Returns:
        Source management port to the form the target gives one
        (``""`` where it has none).
    """
    from ..migration.port_mapping import name_key

    forms = {
        port.source: _management_form(
            source, target, plan.labelled_ports.get(port.source, port.source),
        )
        for port in plan.unplaced if port.used and port.role == "mgmt"
    }
    for key, form in forms.items():
        value = operator_map.get(key)
        if (
            isinstance(value, str) and form
            and name_key(value, fold_target) == name_key(form, fold_target)
        ):
            operator_map[key] = form
    return forms


def _hardware_binder(
    plan: MappingPlan,
    factory_of: dict[str, str],
    own_names: list[str],
    sent: dict[str, str | None],
    target_names: list[str],
    fold_target: bool,
    same_codec: bool,
    hardware: dict[str, str],
) -> TransformCallable:
    """A transform that sets, on every port the mapping can account
    for, the factory name the target finds it by — and records it in
    *hardware*.

    For a target that looks a port up by a factory name beside the
    port's own (``CodecBase.ports_keep_a_factory_name``).  Runs after
    the port translator, which renames and never touches the field.

    Which port of the SOURCE an interface of the translated tree is:
    the one whose factory name it still carries, where the source
    config recorded one; else the port of the declared source whose
    name the map sent to this interface's name.  The second matters as
    much as the first — a RouterOS config states a factory name only
    on a port it has an ``/interface ethernet`` line for, and another
    vendor's config states none.

    Where that port then is: a port whose name in the output is a
    port of the declared target IS that port.  A port under any other
    name — one an operator gave it, in the source config or in their
    map — is on the hardware its pairing gave it.  A port nobody
    placed stays on the hardware it had, between two configs of one
    codec; from another vendor it had none this target knows.

    Args:
        plan: The pairing.
        factory_of: The name the source config uses for a port, to
            the port's factory name, where the config states one.
            Empty unless the source codec records factory names.
        own_names: The ports of the declared source, as the config
            names them.
        sent: The rename map of the run (source name to target name,
            ``None`` for a drop).
        target_names: The ports of the declared target.
        fold_target: Target names compare without regard to case.
        same_codec: Source and target are one codec.
        hardware: Filled on each run: the name the SOURCE config uses
            for a port, to the factory name the port ended with.
    """
    from ..migration.port_mapping import name_key

    pair_of = {pairing.source: pairing.target for pairing in plan.used_pairings}
    source_of = {factory: name for name, factory in factory_of.items()}
    spelt = {name_key(name, fold_target): name for name in target_names}
    own = set(own_names)

    def bind_hardware(moved: Any) -> Any:
        hardware.clear()
        # A port that carries no factory name is found by where the
        # map sent its name.
        arrived: dict[str, str] = {}
        for name, final in sent.items():
            if isinstance(final, str) and name in own and name not in factory_of:
                arrived.setdefault(final, name)
        for iface in getattr(moved, "interfaces", None) or []:
            factory = getattr(iface, "default_name", "")
            was = source_of.get(factory, "") if factory else arrived.get(iface.name, "")
            if not was:
                continue
            port = spelt.get(name_key(iface.name, fold_target))
            if port is None:
                port = pair_of.get(was)
            if port is None and not factory and same_codec:
                # Nobody placed it, and its own name is its factory
                # name: it stays on that hardware.
                port = was
            if port is not None:
                iface.default_name = port
            if iface.default_name:
                hardware[was] = iface.default_name
        return moved

    return bind_hardware


def _unbound_hardware(
    target: CodecBase,
    job: MigrationJob,
    hardware: dict[str, str],
    expected: dict[str, str],
    every: list[str],
) -> tuple[list[str], bool]:
    """Ports the output does not look up by the hardware the mapping
    put them on.

    *hardware* is what :func:`_hardware_binder` wrote on the tree.
    Whether the renderer then wrote a line that finds the port by it
    is the renderer's affair: the RouterOS one writes no Ethernet line
    for an interface whose name reads as a VLAN, a bridge, a LAG or a
    loopback, whatever factory name the interface carries.  So the
    output is read back with the target's own parser, and none of the
    renderer's rules is re-derived here.

    A port is confirmed by ITS OWN line: an interface of the output
    under the port's name that is looked up by the port's hardware.
    That another interface is looked up by the same hardware says
    nothing for this port.  Two allowances, both for what a parser
    cannot give back: where several names ended on one name the
    parser keeps one of their lines, so a line under that name that
    looks up the hardware of ONE of them counts for each; and where
    the parser reads a name back otherwise than it was written (a
    line break in it), a line looked up by the port's hardware under
    a name NO name of the job ended on counts.

    *expected* is the other half.  A port the config names only as a
    LAG member or in a route has no interface, so the binder had
    nothing to write a factory name on and the renderer no line to
    write.  Under the name of the target port it was paired with it
    needs none.  Under any other name it is looked up by nothing, and
    that matters where the output USES the name.  An allowance
    applies there too: a list is written unquoted (``slaves=``,
    ``gateway=``), so a name with white space, a comma, ``@`` or
    ``%`` in it is not given back whole, and is judged by the part of
    it before the first such character.  That is what a member list
    reads where the character is white space or a comma, and a next
    hop where it is any of the four; a name that begins with one of
    them, holds ``@`` or ``%`` ahead of the white space or comma as a
    LAG member, is wrapped in double quotes, or has a line break in
    it is NOT caught (its entry is then listed off-target only).
    Quoting the two lists in the renderer is what would retire the
    whole case.

    Args:
        target: The target codec.
        job: The finished run.
        hardware: The name the source config uses for a port, to the
            factory name the binder gave it.
        expected: Placed ports the binder recorded nothing for, whose
            name in the output is not a port of the target: source
            name to the target port each was paired with.
        every: Every name the config references.

    Returns:
        The keys of *hardware* that no line of their own looks up by
        that hardware, then the keys of *expected* whose name the
        output uses; and whether the output could be read back at all
        (``False``: every key of both is returned, confirmed by
        nothing).
    """
    if not hardware and not expected:
        return [], True
    from ..migration.canonical.port_names import collect_port_names

    renames = job.port_renames or {}
    gone = set(job.port_drops or ())

    def final(name: str) -> str:
        return renames.get(name, name)

    # The name an interface has in the output -> the factory names it
    # is looked up by; and every name the output refers to.
    looked_up: dict[str, set[str]] = {}
    try:
        read_back = target.parse(job.rendered or "")
        for iface in getattr(read_back, "interfaces", None) or []:
            if iface.default_name:
                looked_up.setdefault(iface.name, set()).add(iface.default_name)
        used = set(collect_port_names(read_back))
        # A next hop can name an interface too, and is not in that
        # list.  (After an address -- ``10.0.5.2%WAN`` -- the parser
        # gives the name as the route's interface, which is.)
        for route in getattr(read_back, "static_routes", None) or []:
            used.update(
                hop.partition("@")[0].strip() for hop in (route.gateway or "").split(",")
            )
    except Exception:
        return [*hardware, *expected], False

    ends = Counter(final(name) for name in {*every, *hardware} if name not in gone)
    # The hardware of every recorded port, by the name the port ended on.
    on: dict[str, set[str]] = {}
    for name, where in hardware.items():
        on.setdefault(final(name), set()).add(where)
    holders: dict[str, set[str]] = {}
    for shown, factories in looked_up.items():
        for factory in factories:
            holders.setdefault(factory, set()).add(shown)

    def bound(name: str, where: str) -> bool:
        mine = final(name)
        if where in looked_up.get(mine, ()):
            return True
        # The line under a shared name has to look one of the sharers
        # up.  A parser can report a factory name it never read (the
        # RouterOS one gives ``ether1.10`` itself as one), and that is
        # no line.
        if ends[mine] > 1 and looked_up.get(mine, set()) & on.get(mine, set()):
            return True
        return any(not ends[shown] for shown in holders.get(where, ()))

    def refers_to(name: str) -> bool:
        if name in used:
            return True
        # A list is written unquoted (``slaves=``, ``gateway=``), so the
        # parser gives a name back only up to its first white space or
        # comma -- or, in a next hop, ``@`` or ``%``.  A name that holds
        # one is judged by the part before the first of them (see the
        # docstring for what that does not catch).
        cut = next(
            (at for at, ch in enumerate(name) if ch.isspace() or ch in ",@%"), len(name),
        )
        return 0 < cut < len(name) and name[:cut] in used

    unbound = [name for name, where in hardware.items() if not bound(name, where)]
    unbound.extend(name for name in expected if refers_to(final(name)))
    return unbound, True


def _mapping_message(plan: MappingPlan, dropped: set[str]) -> str:
    """The sentence a job's ``error`` carries when the port mapping
    leaves something to decide, or ``""``."""
    if not plan.applied:
        reason = plan.warnings[0].removeprefix("port mapping: ") if plan.warnings else ""
        return f"Port mapping was not made: {reason}." if reason else (
            "Port mapping was not made."
        )
    sentences: list[str] = []
    if plan.unresolved_ports:
        sentence = (
            f"{len(plan.unresolved_ports)} name(s) in the source "
            f"config need a decision: a port with no place on the "
            f"target device, a management port the target model "
            f"lists no place for, a name that is not a port of the "
            f"declared source device, or a name that was displaced "
            f"or given a port the target does not list."
        )
        if dropped.intersection(plan.unresolved_ports):
            sentence += " Unplaced ports were dropped from the output."
        sentences.append(sentence)
    if plan.fused:
        sentences.append(
            f"{len(plan.fused)} target port(s) received more than "
            f"one source port."
        )
    if sentences:
        sentences.append("Review the port mapping and map or drop each one.")
    if plan.stale_next_hops:
        sentences.append(
            f"{len(plan.stale_next_hops)} static route(s) still name, "
            f"as next hop, an interface that has another name in the "
            f"output, or is not in it; correct them by hand."
        )
    if plan.unbound_ports:
        sentences.append(
            f"{len(plan.unbound_ports)} port(s) are not looked up by "
            f"their hardware in the output; give each a port of the "
            f"target, or - where the config has an interface for it - "
            f"another name."
        )
    return "Port mapping is incomplete: " + " ".join(sentences) if sentences else ""


def run_plan_with_models(
    source: CodecBase,
    target: CodecBase,
    raw_text: str,
    source_inventory: Inventory,
    target_inventory: Inventory,
    port_rename_map: dict[str, str | None] | None = None,
    vlan_rename_map: dict[int, int | None] | None = None,
    local_user_rename_map: dict[str, str | None] | None = None,
    snmp_community_rename_map: dict[str, str | None] | None = None,
    snmpv3_user_rename_map: dict[str, str | None] | None = None,
    transforms: list[TransformCallable] | None = None,
    transform_specs: list[TransformSpec] | None = None,
    force: bool = False,
) -> MigrationJob:
    """Model-aware pipeline entry: pair ports by position, then translate.

    The name-shape translator cannot know that the 49th port of one
    switch is the first uplink of another.  Given the inventory of
    each device (see :mod:`netcanon.migration.device_models`), this
    function pairs the ports the source config uses with the target's
    by position (:func:`~netcanon.migration.port_mapping.plan_port_mapping`),
    merges the operator's own overrides over that pairing, and runs
    :func:`run_plan_with_overrides` with the result.  The translator
    applies an explicit rename entry ahead of its own guess, so the
    pairing reaches the output as an ordinary rename map.

    What the pairing decides:

    * a used source port with a position on the target is renamed to
      the target port there;
    * a used access or uplink port with NO position on the target is
      dropped from the output and listed in ``job.port_drops`` — never
      left under its old name, which on a same-vendor pair could be
      the name another port was just mapped to;
    * between two configs of the same codec, a sub-interface
      (``ge-0/0/0.54``) follows its parent port.

    What it leaves to the name-shape translator, and then checks:

    * an unplaced management port, a name the config uses that is not
      a port of the declared source (off-inventory), and every logical
      name — a LAG, an SVI, a loopback.  What the translator makes of
      such a name can be a port the pairing gave to something else —
      the same fusion, by another door.  So the finished run is
      inspected, over EVERY name the config references and not only
      the hardware ones: where two names ended on one target, or a
      logical name ended on a port of the target, every name that
      neither the pairing nor the operator decided is dropped (it is
      **displaced**) and the translation is run once more.  Where no
      name in a clash was decided, one keeps the name.  A logical name
      that was given a port-shaped name the target does NOT list
      collides with nothing and is not dropped; it is listed
      (``landed_off_target``) and asks for a decision.  The translator
      is its own oracle here; none of its rules is re-derived.

    **A port with two names.**  RouterOS keeps a port's factory name
    (``ether2``) beside the name an operator gave it (``core-a``), and
    every other line of the config uses the second.  The factory name
    is the hardware and is what a device model lists; the translator,
    which is shared with every translation, never touches it.  It is
    handled here, where the target device is known:

    * the port is found in the source model by its factory name and
      is known everywhere else — in the plan, in the job's lists, as
      the key of an operator's entry — by the name the config uses
      (``port_mapping_plan.labelled_ports``);
    * onto another vendor, where a port has one name, that name
      becomes the port it was paired with;
    * between two RouterOS configs the port keeps the operator's
      name.

    **A target that finds a port by a factory name**
    (``CodecBase.ports_keep_a_factory_name``; RouterOS) is given one
    for every port the mapping placed that the config has an
    interface for, whatever vendor the config came from and whether
    or not the source config stated one (:func:`_hardware_binder`).
    A placed port with no interface -- a LAG member, a route's
    interface -- has no line to carry one; it needs none under the
    target port's name, and is reported if an entry names it
    (:func:`_unbound_hardware`).  An operator's entry whose target is
    a port of the declared target moves the port there; one whose
    target is not gives the port that NAME and changes nothing about
    its hardware.  Only a declared target can tell the two apart —
    ``sfp1`` is a port of one RouterOS model and a short name for
    ``sfp-sfpplus1`` on another — which is why a request that
    declares no devices never moves a factory name.  Where the
    hardware ended is read back from the tree that was rendered
    (``port_mapping_plan.target_hardware``), two ports on one piece
    of hardware are a clash although they share no name, and the
    rendered OUTPUT is read back for the line that looks each port up
    (:func:`_unbound_hardware`, ``port_mapping_plan.unbound_ports``).
    A config that looks two interfaces up by one factory name is not
    paired at all.

    An entry in *port_rename_map* replaces the plan's entry for that
    port, whatever the plan decided.  An entry keyed by the factory
    name of a port the config calls something else is taken for that
    port.  Where another letter case cannot be another interface on
    the target platform (``port_names_case_sensitive`` is false: it
    has no case, or it names every interface itself in lower case)
    the target is read as the declared target device spells it —
    ``1/a1`` and `` 1/A1`` are the port ``1/A1``; elsewhere it is
    stripped and taken as typed.  An entry with a blank target is set aside: it would
    render a port with no name, and decides nothing.  Where the
    operator's own entries point two ports at one target name, that is
    done as they asked and reported (``port_mapping_plan.fused``).

    Status.  A job that would have been ``completed`` is ``partial``,
    with ``job.error`` saying why, when

    * a used port was dropped, was off-inventory, was displaced, or is
      a management port kept although the target lists none, or a
      logical name landed on a port the target does not list — and
      the operator's map does not name it.  An entry for the port (a
      target, or an explicit ``None``) is them deciding it;
    * a target port received more than one source port, whoever
      decided it;
    * a static route still names, as next hop, an interface that
      has another name in the output, or is not in it
      (``stale_next_hops``);
    * a port is looked up by its hardware nowhere in the output
      (``unbound_ports``); or
    * no pairing could be made at all (one side lists no ports), so
      every name went by name shape although devices were declared.

    A job that is already ``partial`` for another reason keeps its
    status and has the same sentence appended to ``job.error``.  The
    detail is on the plan as fields — ``unresolved_ports``,
    ``displaced``, ``fused``, ``off_target``, ``landed_off_target``,
    ``stale_next_hops``, ``unbound_ports``, ``sub_interfaces``, and what a dropped port
    took with it (``emptied_lags``, ``shrunk_lags``, ``lost_routes``,
    ``lost_dhcp_pools``, ``lost_tracking``, ``lost_vtep_sources``) —
    so no client has to read it out of prose.

    The source is parsed here first, to learn which ports it uses, and
    again inside :func:`run_plan_with_overrides` — a third time when a
    name is displaced.  If that first parse fails, or yields something
    that is not a canonical tree, no pairing is attempted and the
    canonical failure is produced by the code that already produces
    it.  Reading the port names out of the tree cannot fail the job: a
    name a classifier cannot read is kept as it is.

    New function, per the frozen-signatures rule: the three older
    entries are unchanged.

    Args:
        source: Source codec.
        target: Target codec.
        raw_text: Source-vendor config text.
        source_inventory: The device the config came from.
        target_inventory: The device it is going to.
        port_rename_map: Operator overrides; they win over the pairing.
            Keyed by the name the CONFIG uses for a port.
        vlan_rename_map: As :func:`run_plan_with_overrides`.
        local_user_rename_map: As :func:`run_plan_with_overrides`.
        snmp_community_rename_map: As :func:`run_plan_with_overrides`.
        snmpv3_user_rename_map: As :func:`run_plan_with_overrides`.
        transforms: Applied after every override transform.
        transform_specs: Serialisable transform record.
        force: Skip the cross-device-class guard.

    Returns:
        The :class:`MigrationJob`, with ``port_mapping_plan`` set when
        a pairing was attempted and the output was rendered.  It is
        ``None`` when the source did not parse to a canonical tree or
        the job did not render (a parse failure, a refused device-class
        pair), whatever was declared.
    """
    from ..migration.canonical.intent import CanonicalIntent
    from ..migration.canonical.port_names import (
        collect_hardware_port_names,
        collect_port_names,
    )
    from ..migration.port_mapping import name_key, plan_port_mapping, settle_plan

    target_names = target_inventory.names()
    # Whether letter case is part of a name is a fact about each
    # platform, and each codec states it.
    fold_source = not getattr(source, "port_names_case_sensitive", False)
    fold_target = not getattr(target, "port_names_case_sensitive", False)
    # A factory name is one codec's own way of saying which hardware a
    # port is.  Only a target of the same codec can write "this
    # hardware, under that name"; on any other the name IS the port.
    same_codec = source.name == target.name

    operator_map, ignored = _read_operator_map(
        port_rename_map, target_names, fold_target,
    )

    plan = None
    used: list[str] = []
    every: list[str] = []
    followers: dict[str, str | None] = {}
    # The name the config uses for a port -> its factory name, for
    # every port that has one.
    factory_of: dict[str, str] = {}
    # The ports of the declared source, as the config names them.
    own_names: list[str] = source_inventory.names()
    try:
        tree = source.parse(raw_text)
    except Exception:
        # Not reported here: run_plan parses again below and turns the
        # same failure into the failed job it has always produced.
        tree = None
    if isinstance(tree, CanonicalIntent):
        every = collect_port_names(tree)
        factory_of = {
            iface.name: iface.default_name for iface in tree.interfaces
            if iface.name and iface.default_name
        }
        # A port the operator named is found in the model by its
        # factory name, and known everywhere else by theirs.
        known_as = {
            factory: name for name, factory in factory_of.items()
            if factory != name
        }
        own_names = [known_as.get(name, name) for name in own_names]
        # One factory name on two interfaces: a port that was renamed,
        # beside a line that still uses its old name.
        looked_up = Counter(factory_of.values())
        # A port of the declared source counts as used when the config
        # names it, whatever the codec's classifier makes of the name;
        # only a name OUTSIDE the inventory can be set aside as
        # "positively not hardware" (a loopback, a tunnel, an SVI).
        used = collect_hardware_port_names(
            tree,
            classify=getattr(source, "classify_port_name", None),
            always=own_names,
            fold=fold_source,
        )
        plan = plan_port_mapping(
            source_inventory, target_inventory, used, known_as=known_as,
            one_hardware=[name for name, count in looked_up.items() if count > 1],
        )
        # An operator may key an entry by the factory name of a port
        # the config calls something else.  The plan knows which port
        # that is; the entry is taken for it.
        _key_by_the_configs_name(operator_map, plan, every, ignored)

    paired = plan is not None and plan.applied
    keeps_names = paired and same_codec
    merged: dict[str, str | None] = dict(plan.rename_map) if plan else {}
    forms: dict[str, str] = {}
    if plan is not None and keeps_names:
        on_target = {name_key(name, fold_target) for name in target_names}
        for name in plan.labelled_ports:
            # Its hardware moves (see _hardware_binder).  The name the
            # rest of the config refers to it by stays, and is pinned
            # so that name shape cannot re-decide it -- unless that
            # name is itself a port of the target, where it could only
            # be THAT port: then the port takes its paired port's
            # name, like any other.
            if (
                isinstance(merged.get(name), str)
                and name_key(name, fold_target) not in on_target
            ):
                merged[name] = name
        followers = _sub_interface_followers(plan, operator_map, merged)
    if plan is not None and paired:
        forms = _management_forms(plan, source, target, operator_map, fold_target)
    merged.update(followers)
    merged.update(operator_map)

    # Where each port's hardware ended, by the name the source config
    # uses for the port.  Filled from the tree that is rendered, so it
    # is what happened and not what was intended.
    hardware: dict[str, str] = {}
    binders: list[TransformCallable] = []
    if plan is not None and paired and getattr(target, "ports_keep_a_factory_name", False):
        # Whatever vendor the config came from: the plan knows which
        # port of the target each paired port is on, and this target
        # finds a port by that and by nothing else.
        binders.append(_hardware_binder(
            plan, factory_of, own_names, merged,
            target_names, fold_target, same_codec, hardware,
        ))

    def translate(port_map: dict[str, str | None]) -> MigrationJob:
        return run_plan_with_overrides(
            source=source,
            target=target,
            raw_text=raw_text,
            port_rename_map=port_map,
            vlan_rename_map=vlan_rename_map,
            local_user_rename_map=local_user_rename_map,
            snmp_community_rename_map=snmp_community_rename_map,
            snmpv3_user_rename_map=snmpv3_user_rename_map,
            transforms=[*binders, *(transforms or [])] if binders else transforms,
            transform_specs=transform_specs,
            force=force,
        )

    job = translate(merged)
    if plan is None or job.rendered is None:
        return job

    # The plan decides paired and unplaced data ports.  Every other
    # name went to the name-shape translator, whose answer nobody has
    # checked against the targets the plan assigned.  Ask the run.
    displaced: list[str] = []
    landings: dict[str, str] = {}
    stale: list[str] = []
    if plan.applied:
        displaced = _undecided_clashes(
            every, used, merged, job, target_names,
            source_names=own_names,
            fold_source=fold_source, fold_target=fold_target,
            hardware=dict(hardware),
        )
        if displaced:
            merged.update(dict.fromkeys(displaced))
            job = translate(merged)
            if job.rendered is None:
                return job
        landings = _unlisted_landings(
            every, used, merged, job, source, target, target_names, fold_target,
        )
        positions: dict[str, str | None] = {p.source: p.target for p in plan.pairings}
        positions.update({p.source: None for p in plan.unplaced})
        stale = _stale_next_hops(tree, job, same_codec, positions)

    dropped, taken = _taken_with_dropped_ports(tree, job.port_drops)

    # Where the binder put a port is what the TREE says; whether a line
    # of the output finds the port there is asked of the output.  And
    # the binder walks interfaces, while the pairing is over every port
    # the config uses: a placed port with no interface (a LAG member, a
    # route's interface) under a name that is no port of the target is
    # handed over too.
    expected: dict[str, str] = {}
    if binders:
        listed = {name_key(name, fold_target) for name in target_names}
        gone = set(job.port_drops)
        for pairing in plan.used_pairings:
            landed = job.port_renames.get(pairing.source, pairing.source)
            if (
                pairing.source not in gone and pairing.source not in hardware
                and name_key(landed, fold_target) not in listed
            ):
                expected[pairing.source] = pairing.target
    unbound, read_back = _unbound_hardware(target, job, hardware, expected, every)

    settle_plan(
        plan,
        operator_map=operator_map,
        used_names=used,
        every_name=every,
        port_renames=job.port_renames,
        port_drops=job.port_drops,
        target_names=target_names,
        displaced=displaced,
        sub_interfaces={
            name: where for name, where in followers.items()
            if name not in operator_map
        },
        ignored_overrides=ignored,
        **taken,
        management_forms=forms,
        fold_source=fold_source,
        fold_target=fold_target,
        target_hardware={
            **{name: where for name, where in expected.items() if name in unbound},
            **hardware,
        },
        landed_off_target=landings,
        stale_next_hops=stale,
        units=same_codec,
        unbound=unbound,
        by_factory_name=bool(binders),
    )
    job.port_mapping_plan = plan
    if not read_back:
        # On the plan as well as on the job: a client that reads only
        # the plan must not take every port for one with a naming
        # problem.
        plan.warnings.append(
            "port mapping: the output could not be read back with the target "
            "codec, so no port could be confirmed as looked up by its hardware; "
            "every port is listed for that reason, whatever its name"
        )
    job.warnings.extend(plan.warnings)

    message = _mapping_message(plan, dropped)
    if message:
        if job.status == MigrationJobStatus.completed:
            job.status = MigrationJobStatus.partial
            job.error = message
        elif job.status == MigrationJobStatus.partial:
            # Already partial for another reason (validation, usually).
            # Say this as well rather than leave it to the warnings.
            job.error = f"{job.error} {message}" if job.error else message
    logger.debug(
        "run_plan_with_models %s: paired=%d unplaced=%d off_inventory=%d "
        "overridden=%d displaced=%d fused=%d unresolved=%d",
        job.id[:8],
        len(plan.used_pairings), len(plan.used_unplaced),
        len(plan.off_inventory), len(plan.overridden),
        len(plan.displaced), len(plan.fused), len(plan.unresolved_ports),
    )
    return job

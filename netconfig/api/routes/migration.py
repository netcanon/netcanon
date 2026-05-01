"""
``/api/v1/migration`` routes.

Read-only introspection:

    GET  /api/v1/migration/adapters
        → list of CodecInfo (one entry per registered adapter)

    GET  /api/v1/migration/adapters/{name}/capabilities
        → the full CapabilityMatrix

Translation pipeline entries:

    POST /api/v1/migration/plan
        → everything-at-once entry.  Accepts a MigrationPlanRequest
          with any combination of per-category override maps
          (``port_rename_map``, ``vlan_rename_map``,
          ``local_user_rename_map``, ``snmp_community_rename_map``);
          engages the rename-aware pipeline when any is present or
          when a target_profile is selected.

    POST /api/v1/migration/plan/ports
        → per-pane override endpoint for port-name rewrites
          (introduced P2C1).  Dispatches to run_plan_with_overrides
          with only port_rename_map engaged.

    POST /api/v1/migration/plan/vlans
        → per-pane override endpoint for VLAN-ID rewrites
          (introduced P2C2).  Dispatches to run_plan_with_overrides
          with only vlan_rename_map engaged.  Drop via None value +
          collision merge-by-union.  See the endpoint's own
          docstring for full semantics.

    POST /api/v1/migration/plan/local_users
        → per-pane override endpoint for local-user name rewrites
          (introduced P2C4).  Dispatches to run_plan_with_overrides
          with only local_user_rename_map engaged.  Drop via None
          value; collision merge keeps highest privilege_level +
          first-wins role + first-wins hashed_password.

    POST /api/v1/migration/plan/snmp
        → per-pane override endpoint for SNMP community-name
          rewrites (introduced P2C5).  Dispatches to
          run_plan_with_overrides with only snmp_community_rename_map
          engaged.  Effectively single-entry rename (CanonicalSNMP
          holds one community string); drop via None value clears
          the community and render paths omit the SNMP block.
          v1/v2c only — SNMPv3 users have their own endpoint.

    POST /api/v1/migration/plan/snmpv3
        → per-pane override endpoint for SNMPv3 USM user-name
          rewrites (introduced P2C6).  Dispatches to
          run_plan_with_overrides with only snmpv3_user_rename_map
          engaged.  Rename is identity-only: auth / priv keys +
          group + engine_id follow the renamed record.  Drop via
          None value removes the user entirely.  Collisions merge
          on first-wins.  Auth + priv passphrases are NEVER combined
          across users (different crypto keys per securityName is
          the whole point of USM).

    POST /api/v1/migration/render
        → current alias of /plan, retained for API symmetry and a
          future split (see TestRenderEndpoint lock-in tests).

Auto-detection:

    POST /api/v1/migration/detect
        → probe raw config prefix against every registered codec's
          ``probe()`` classifier; returns ranked DetectCandidates
          for UI suggestion.

Target profiles (for the Tier-3 rename modal's dropdown population):

    GET  /api/v1/migration/target-profiles
        → list all loaded profiles (vendor/model)
    GET  /api/v1/migration/target-profiles/{vendor}/{model}
        → one profile, including module-variants when declared

All POST endpoints accept the same :class:`MigrationPlanRequest`
body (input mode is raw_text XOR source_filename) and return a
:class:`MigrationJob`.  Future per-pane categories
(``radius``, ``snmp_trap_hosts``, ...) will extend the endpoint set
by adding siblings under ``/plan/<category>`` per the pattern
established by /plan/ports, /plan/vlans, /plan/local_users, and
/plan/snmp.

Deploy-time endpoints (``/deploy`` and associated MigrationJob
persistence analogous to ``FileJobStore``) are not yet shipped and
remain on the roadmap — see ``translator-plans.txt``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from pydantic import BaseModel, Field

from ...migration.codecs.registry import get_codec
from ...models.migration import (
    CodecInfo,
    CapabilityMatrix,
    MigrationJob,
    MigrationPlanRequest,
)
from ...migration.target_profiles import TargetProfile
from ...services.migration_detect import DetectCandidate, detect_codec
from ...services.migration_pipeline import (
    run_plan,
    run_plan_with_overrides,
    run_plan_with_rename,
)
from ...storage.base import BaseConfigStore
from ..deps import get_storage
from ._migration_helpers import (
    build_codec_info_list,
    get_target_profiles,
    request_has_overrides_or_profile,
    resolve_adapter_or_422,
    resolve_input_text,
)


class MigrationDetectRequest(BaseModel):
    """Body for ``POST /api/v1/migration/detect``.

    Exactly one of ``raw_text`` / ``source_filename`` is required,
    mirroring :class:`MigrationPlanRequest`.  Keeps the UI's two
    input modes (paste vs. stored-config) on a single endpoint.
    """

    raw_text: str | None = None
    source_filename: str | None = None
    min_confidence: int = Field(default=1, ge=0, le=100)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/migration", tags=["migration"])


@router.get(
    "/adapters",
    response_model=list[CodecInfo],
    summary="List registered migration codecs",
)
def list_migration_adapters(request: Request) -> list[CodecInfo]:
    """Return one ``CodecInfo`` per registered codec.

    Each entry includes the linked vendor's ``display_name`` (resolved
    from ``app.state.vendors``) so the UI can group codecs by vendor
    without a second round-trip.
    """
    vendors = getattr(request.app.state, "vendors", {})
    return build_codec_info_list(vendors)


@router.get(
    "/adapters/{name}/capabilities",
    response_model=CapabilityMatrix,
    summary="Get the capability matrix for a migration adapter",
    responses={404: {"description": "No adapter registered under that name"}},
)
def get_codec_capabilities(name: str) -> CapabilityMatrix:
    """Return the full :class:`CapabilityMatrix` for *name*.

    Raises:
        HTTPException 404: If no adapter is registered under *name*.
    """
    try:
        adapter = get_codec(name)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return adapter.capabilities


@router.post(
    "/plan",
    response_model=MigrationJob,
    summary="Parse + validate a config against a target adapter",
    responses={
        404: {"description": "source_filename does not exist"},
        422: {"description": "Invalid adapter name or input specification"},
    },
)
def plan_migration(
    body: MigrationPlanRequest,
    storage: BaseConfigStore = Depends(get_storage),
) -> MigrationJob:
    """Run the translator pipeline for *body* and return the job.

    Stages executed: class-guard → parse → (transforms) → validate →
    render.  Transforms are not yet configurable via this endpoint
    (Phase 2 will wire them in).

    The endpoint ALWAYS returns the ``MigrationJob`` — callers should
    inspect ``job.status``:

    * ``completed`` — every stage ran, validation severity is ``ok``
      or ``warn``, rendered output is in ``job.rendered``.
    * ``partial``  — rendered output exists but validation severity
      is ``block``; review before deploying.
    * ``failed``   — a stage raised; ``job.error`` has the summary.

    Use ``force=true`` in the request body to override the stage-0
    device-class guard for deliberate cross-class experiments.
    """
    source = resolve_adapter_or_422(body.source, side="source")
    target = resolve_adapter_or_422(body.target, side="target")
    raw_text = resolve_input_text(body, storage)
    # Route to the rename-aware pipeline when the caller supplied
    # ANY per-category override map OR a target profile selection
    # (target-profile alone means "run auto-heuristic + return
    # diagnostics the UI can render").  Legacy callers that supply
    # none of these get ``run_plan`` unchanged.
    if request_has_overrides_or_profile(body):
        # Dispatch directly to run_plan_with_overrides so EVERY
        # category map threads through — run_plan_with_rename is
        # signature-frozen and only accepts port_rename_map, so
        # calling it here would silently drop VLAN / local-user /
        # SNMP overrides posted in the same body.
        job = run_plan_with_overrides(
            source, target, raw_text,
            port_rename_map=(
                body.port_rename_map
                if body.port_rename_map is not None
                else ({} if body.target_profile is not None else None)
            ),
            vlan_rename_map=body.vlan_rename_map,
            local_user_rename_map=body.local_user_rename_map,
            snmp_community_rename_map=body.snmp_community_rename_map,
            snmpv3_user_rename_map=body.snmpv3_user_rename_map,
            force=body.force,
        )
    else:
        job = run_plan(source, target, raw_text, force=body.force)
    logger.info(
        "Migration plan %s: %s -> %s = %s",
        job.id[:8],
        body.source,
        body.target,
        job.status.value,
    )
    return job


@router.post(
    "/plan/ports",
    response_model=MigrationJob,
    summary="Per-pane override endpoint: port-name renames",
    responses={
        404: {"description": "source_filename does not exist"},
        422: {"description": "Invalid adapter name or input specification"},
    },
)
def plan_migration_ports(
    body: MigrationPlanRequest,
    storage: BaseConfigStore = Depends(get_storage),
) -> MigrationJob:
    """Port-rename-only entry into the migration pipeline.

    First concrete per-pane override endpoint.  Establishes the
    pattern that subsequent category endpoints (``/plan/vlans``,
    ``/plan/snmp``, ``/plan/local-users``) will follow: each accepts
    the same :class:`MigrationPlanRequest` body and dispatches to
    :func:`run_plan_with_overrides` with only its category's
    override map populated.

    Semantically equivalent to ``POST /plan`` when the request body
    carries a ``port_rename_map``.  The distinction is purely
    organisational — routing by URL rather than by body-field
    presence makes the UI's pane-switch behaviour explicit and lets
    operators observe which override category fired via server
    logs / network-tab inspection.  ``POST /plan`` stays as the
    "everything at once" entry; per-pane endpoints let the client
    post only the category that changed.

    Ignores other override maps if the body carries them — a
    hypothetical future client posting ``vlan_rename_map`` to
    ``/plan/ports`` would see the VLAN map silently dropped.
    Discipline of posting to the right URL is part of the contract.
    """
    source = resolve_adapter_or_422(body.source, side="source")
    target = resolve_adapter_or_422(body.target, side="target")
    raw_text = resolve_input_text(body, storage)
    # Always engage the rename-aware pipeline from this endpoint —
    # hitting /plan/ports signals clear intent even when the map is
    # empty ({} = "auto-heuristic only, please").
    job = run_plan_with_overrides(
        source, target, raw_text,
        port_rename_map=body.port_rename_map or {},
        force=body.force,
    )
    logger.info(
        "Migration plan/ports %s: %s -> %s = %s",
        job.id[:8],
        body.source,
        body.target,
        job.status.value,
    )
    return job


@router.post(
    "/plan/vlans",
    response_model=MigrationJob,
    summary="Per-pane override endpoint: VLAN ID renames",
    responses={
        404: {"description": "source_filename does not exist"},
        422: {"description": "Invalid adapter name or input specification"},
    },
)
def plan_migration_vlans(
    body: MigrationPlanRequest,
    storage: BaseConfigStore = Depends(get_storage),
) -> MigrationJob:
    """VLAN-rename-only entry into the migration pipeline.

    Second concrete per-pane override endpoint (ports was the first,
    see ``POST /plan/ports``).  Accepts the same
    :class:`MigrationPlanRequest` body and dispatches to
    :func:`run_plan_with_overrides` with only ``vlan_rename_map``
    populated.

    VLAN mapping is an integer → integer rewrite applied across the
    canonical tree (``CanonicalVlan.id``, ``access_vlan``,
    ``trunk_allowed_vlans``, ``trunk_native_vlan``, ``voice_vlan``).
    ``None`` as a map value drops the VLAN entirely and detaches any
    interface that was assigned to it — operator gets per-affected-
    interface warnings in :attr:`MigrationJob.warnings`.

    Collision semantics: when two source IDs map to the same target
    ID (or when an operator maps a VLAN to an ID that already exists
    in the tree), the canonical VLAN entries are merged by union
    (tagged/untagged port lists) and SVI-address concatenation.
    Merge events emit warnings so the operator notices.

    Ignores other override maps if the body carries them — hitting
    ``/plan/vlans`` applies the VLAN category only.  Use
    ``POST /plan`` for multi-category overrides in a single call.
    """
    source = resolve_adapter_or_422(body.source, side="source")
    target = resolve_adapter_or_422(body.target, side="target")
    raw_text = resolve_input_text(body, storage)
    job = run_plan_with_overrides(
        source, target, raw_text,
        vlan_rename_map=body.vlan_rename_map or {},
        force=body.force,
    )
    logger.info(
        "Migration plan/vlans %s: %s -> %s = %s",
        job.id[:8],
        body.source,
        body.target,
        job.status.value,
    )
    return job


@router.post(
    "/plan/local_users",
    response_model=MigrationJob,
    summary="Per-pane override endpoint: local-user renames",
    responses={
        404: {"description": "source_filename does not exist"},
        422: {"description": "Invalid adapter name or input specification"},
    },
)
def plan_migration_local_users(
    body: MigrationPlanRequest,
    storage: BaseConfigStore = Depends(get_storage),
) -> MigrationJob:
    """Local-user-rename-only entry into the migration pipeline.

    Third concrete per-pane override endpoint (ports + vlans came
    first, see ``POST /plan/ports`` and ``POST /plan/vlans``).
    Accepts the same :class:`MigrationPlanRequest` body and
    dispatches to :func:`run_plan_with_overrides` with only
    ``local_user_rename_map`` populated.

    Local-user rename is a string → string rewrite applied to
    :attr:`CanonicalLocalUser.name` across ``intent.local_users``.
    ``None`` as a map value drops the user entirely; the rest of
    the account (privilege level, role, hashed password) follows
    the user — or disappears with them.

    Collision semantics: when two source names map to the same
    target name (or when an operator maps a user to a name that
    already exists in the tree), the user entries are merged on a
    best-effort basis — highest privilege_level wins, first non-
    empty role wins, first hashed_password wins (hashes aren't
    composable).  Merge events emit warnings so the operator
    notices.

    Explicitly NOT in scope:
        * Rewriting usernames inside Tier-3 raw_sections (ACL
          text, AAA rules) — those pass through verbatim.
        * Changing privilege levels / roles — the rename map is
          strictly name-to-name.

    Ignores other override maps if the body carries them — hitting
    ``/plan/local_users`` applies the local-users category only.
    Use ``POST /plan`` for multi-category overrides in a single
    call.
    """
    source = resolve_adapter_or_422(body.source, side="source")
    target = resolve_adapter_or_422(body.target, side="target")
    raw_text = resolve_input_text(body, storage)
    job = run_plan_with_overrides(
        source, target, raw_text,
        local_user_rename_map=body.local_user_rename_map or {},
        force=body.force,
    )
    logger.info(
        "Migration plan/local_users %s: %s -> %s = %s",
        job.id[:8],
        body.source,
        body.target,
        job.status.value,
    )
    return job


@router.post(
    "/plan/snmp",
    response_model=MigrationJob,
    summary="Per-pane override endpoint: SNMP community rename",
    responses={
        404: {"description": "source_filename does not exist"},
        422: {"description": "Invalid adapter name or input specification"},
    },
)
def plan_migration_snmp(
    body: MigrationPlanRequest,
    storage: BaseConfigStore = Depends(get_storage),
) -> MigrationJob:
    """SNMP-community-rename-only entry into the migration pipeline.

    Fourth concrete per-pane override endpoint (ports + vlans +
    local_users came first).  Accepts the same
    :class:`MigrationPlanRequest` body and dispatches to
    :func:`run_plan_with_overrides` with only
    ``snmp_community_rename_map`` populated.

    SNMP-community rename is a string → string rewrite applied to
    :attr:`CanonicalSNMP.community` — a single-value scalar field.
    The rename map is effectively single-entry (at most one key
    can match the current community); using the dict shape keeps
    API symmetry with the other three per-pane endpoints.  ``None``
    as a map value clears the community string; render paths then
    omit the entire SNMP block on output.

    Explicitly NOT in scope:
        * SNMPv3 users.  :class:`CanonicalSNMP` models v1/v2c only
          (community, location, contact, trap_hosts).  Adding v3
          user-based security is a canonical-schema change — see
          ``docs/adding-a-canonical-field.md``.
        * Trap-host rename.  The ``trap_hosts`` list is a distinct
          rename surface planned as a follow-up commit
          (``snmp_trap_host_rename_map``); community-only was the
          proportionate first pass because community is the
          dominant migration use case.
        * Location / contact.  These are sysadmin metadata edited
          per-device in a CMDB, not identity fields — migrations
          carry them through unchanged by design.

    Ignores other override maps if the body carries them — hitting
    ``/plan/snmp`` applies the SNMP category only.  Use
    ``POST /plan`` for multi-category overrides in a single call.
    """
    source = resolve_adapter_or_422(body.source, side="source")
    target = resolve_adapter_or_422(body.target, side="target")
    raw_text = resolve_input_text(body, storage)
    job = run_plan_with_overrides(
        source, target, raw_text,
        snmp_community_rename_map=body.snmp_community_rename_map or {},
        force=body.force,
    )
    logger.info(
        "Migration plan/snmp %s: %s -> %s = %s",
        job.id[:8],
        body.source,
        body.target,
        job.status.value,
    )
    return job


@router.post(
    "/plan/snmpv3",
    response_model=MigrationJob,
    summary="Per-pane override endpoint: SNMPv3 USM user rename",
    responses={
        404: {"description": "source_filename does not exist"},
        422: {"description": "Invalid adapter name or input specification"},
    },
)
def plan_migration_snmpv3(
    body: MigrationPlanRequest,
    storage: BaseConfigStore = Depends(get_storage),
) -> MigrationJob:
    """SNMPv3-user-rename-only entry into the migration pipeline.

    Fifth concrete per-pane override endpoint after
    ``/plan/ports``, ``/plan/vlans``, ``/plan/local_users``, and
    ``/plan/snmp``.  Accepts the same :class:`MigrationPlanRequest`
    body and dispatches to :func:`run_plan_with_overrides` with
    only ``snmpv3_user_rename_map`` populated.

    SNMPv3 user rename is a string → string rewrite applied to
    :attr:`CanonicalSNMPv3User.name` (the USM securityName).  The
    user's auth protocol + passphrase + priv protocol + passphrase
    + group + engine_id stay with the renamed record — rename is
    an identity-only operation, not a re-key.

    Cross-vendor note: SNMPv3 auth / priv passphrases are salted
    with vendor-specific constants.  Same-vendor round-trip is
    lossless (the hash passes through verbatim); cross-vendor
    migration typically requires re-keying on the target device.
    The canonical tree carries the source's hash verbatim so the
    loss is visible to the operator.

    Explicitly NOT in scope:

        * SNMP v1/v2c community rename.  Use ``/plan/snmp`` for
          that — the two surfaces are orthogonal (v2c community
          is a shared-secret string, v3 user is an identity).
        * Trap-host / auth-key / priv-key rename.  Trap hosts are
          a list surface planned as a follow-up commit; auth /
          priv keys are not identity fields — rewriting them
          silently would break device-side crypto state.

    Ignores other override maps if the body carries them — hitting
    ``/plan/snmpv3`` applies the SNMPv3-user category only.
    """
    source = resolve_adapter_or_422(body.source, side="source")
    target = resolve_adapter_or_422(body.target, side="target")
    raw_text = resolve_input_text(body, storage)
    job = run_plan_with_overrides(
        source, target, raw_text,
        snmpv3_user_rename_map=body.snmpv3_user_rename_map or {},
        force=body.force,
    )
    logger.info(
        "Migration plan/snmpv3 %s: %s -> %s = %s",
        job.id[:8],
        body.source,
        body.target,
        job.status.value,
    )
    return job


@router.post(
    "/render",
    response_model=MigrationJob,
    summary="Alias of /plan — included for API symmetry and future split",
    responses={
        404: {"description": "source_filename does not exist"},
        422: {"description": "Invalid adapter name or input specification"},
    },
)
def render_migration(
    body: MigrationPlanRequest,
    storage: BaseConfigStore = Depends(get_storage),
) -> MigrationJob:
    """Currently an alias for :func:`plan_migration`.

    Kept as a separate route so Phase 2 can split plan (no render
    side-effects) from render (snapshots target pre-deploy, emits a
    diff URL) without another API rev.  For now both do the same
    thing — ``MigrationJob.rendered`` is populated in both cases
    because the pipeline runs all stages unless it fails.
    """
    return plan_migration(body, storage)


@router.post(
    "/detect",
    response_model=list[DetectCandidate],
    summary="Auto-detect compatible source codecs for a raw config",
    responses={
        404: {"description": "source_filename does not exist"},
        422: {"description": "Invalid input specification"},
    },
)
def detect_source_codec(
    body: MigrationDetectRequest,
    storage: BaseConfigStore = Depends(get_storage),
) -> list[DetectCandidate]:
    """Return a ranked list of codecs that can plausibly parse the input.

    Each candidate includes a confidence score (0-100) and a short
    reason.  The UI uses this to pre-select the source codec when
    the user pastes text or picks a stored config, eliminating the
    "which format is this?" step for known vendors.

    Exactly one of ``raw_text`` / ``source_filename`` must be set —
    same contract as ``/plan``.  Pass ``min_confidence`` to drop
    weak matches (default 1 keeps everything that scored).

    An empty list means no codec recognised the input.
    """
    has_text = body.raw_text is not None
    has_file = body.source_filename is not None
    if has_text == has_file:
        raise HTTPException(
            status_code=422,
            detail=(
                "Exactly one of `raw_text` or `source_filename` is required."
            ),
        )
    if has_text:
        raw = body.raw_text or ""
    else:
        try:
            raw = storage.get_content(body.source_filename or "")
        except FileNotFoundError:
            raise HTTPException(
                status_code=404,
                detail=f"source_filename not found: {body.source_filename!r}",
            )
    return detect_codec(raw, min_confidence=body.min_confidence)


# ---------------------------------------------------------------------------
# Target profiles (Tier 3 port-rename UI)
# ---------------------------------------------------------------------------


@router.get(
    "/target-profiles",
    response_model=list[TargetProfile],
    summary="List target-device profiles for the rename modal",
)
def list_target_profiles(
    request: Request,
) -> list[TargetProfile]:
    """Return every loaded target profile.

    Profiles drive the Tier 3 port-rename UI's dropdown options and
    collision-detection logic.  See
    :mod:`netconfig.migration.target_profiles` for the YAML schema
    and :file:`definitions/target_profiles/*.yaml` for examples.

    The list may be empty if no profiles are defined — the UI falls
    back to free-form target-name entry in that case.
    """
    profiles = get_target_profiles(request)
    return list(profiles.values())


@router.get(
    "/target-profiles/{vendor}/{model}",
    response_model=TargetProfile,
    summary="Fetch a single target profile by vendor/model key",
    responses={404: {"description": "profile not found"}},
)
def get_target_profile(
    vendor: str,
    model: str,
    request: Request,
) -> TargetProfile:
    """Return a single target profile by its ``vendor/model`` key."""
    profiles = get_target_profiles(request)
    key = f"{vendor}/{model}"
    if key not in profiles:
        raise HTTPException(
            status_code=404,
            detail=f"target profile not found: {key!r}",
        )
    return profiles[key]

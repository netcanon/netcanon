"""
``/api/v1/migration`` routes.

Phase 0 surfaces only read-only introspection:

    GET  /api/v1/migration/adapters
        → list of CodecInfo (one entry per registered adapter)

    GET  /api/v1/migration/adapters/{name}/capabilities
        → the full CapabilityMatrix

Phase 2 will add ``POST /plan``, ``/render``, ``/deploy`` and a
sibling ``MigrationJob`` persistence layer analogous to ``FileJobStore``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from pydantic import BaseModel, Field

from ...migration.codecs.registry import get_codec, list_codecs
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


def _resolve_adapter_or_422(name: str, side: str):
    """Return the named adapter or raise a 422 with a helpful message.

    Uses 422 not 404 because the adapter name is REQUEST-PAYLOAD data;
    callers should fix their body, not their URL.
    """
    try:
        return get_codec(name)
    except LookupError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"unknown {side} adapter: {exc}",
        )


def _resolve_input_text(
    body: MigrationPlanRequest, storage: BaseConfigStore
) -> str:
    """Return the raw config text referenced by *body*.

    Exactly one of ``raw_text`` / ``source_filename`` MUST be set.
    Raises:
        HTTPException 422: If both are set or neither is set.
        HTTPException 404: If ``source_filename`` refers to a file
            that doesn't exist.
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
        return body.raw_text or ""
    try:
        return storage.get_content(body.source_filename or "")
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"source_filename not found: {body.source_filename!r}",
        )


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
    result: list[CodecInfo] = []
    for name in list_codecs():
        codec = get_codec(name)
        caps = codec.capabilities
        vendor = vendors.get(caps.vendor_id)
        result.append(
            CodecInfo(
                name=caps.adapter,
                vendor_id=caps.vendor_id,
                vendor_display_name=vendor.display_name if vendor else "",
                version_range=caps.version_range,
                device_classes=list(caps.device_classes),
                input_format=getattr(codec, "input_format", "unknown"),
                direction=getattr(codec, "direction", "bidirectional"),
                certainty=getattr(codec, "certainty", "experimental"),
                canonical_model=getattr(codec, "canonical_model", "openconfig-lite"),
                supported_count=len(caps.supported),
                lossy_count=len(caps.lossy),
                unsupported_count=len(caps.unsupported),
                description=getattr(codec, "description", ""),
                sample_input=getattr(codec, "sample_input", ""),
                output_extension=getattr(codec, "output_extension", ""),
            )
        )
    return result


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
    source = _resolve_adapter_or_422(body.source, side="source")
    target = _resolve_adapter_or_422(body.target, side="target")
    raw_text = _resolve_input_text(body, storage)
    # Route to the rename-aware pipeline when the caller supplied
    # either an explicit rename map OR a target profile selection
    # (target-profile alone means "run auto-heuristic + return
    # diagnostics the UI can render").  Legacy callers that supply
    # neither get ``run_plan`` unchanged.
    if body.port_rename_map is not None or body.target_profile is not None:
        job = run_plan_with_rename(
            source, target, raw_text,
            port_rename_map=body.port_rename_map or {},
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
    source = _resolve_adapter_or_422(body.source, side="source")
    target = _resolve_adapter_or_422(body.target, side="target")
    raw_text = _resolve_input_text(body, storage)
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
    source = _resolve_adapter_or_422(body.source, side="source")
    target = _resolve_adapter_or_422(body.target, side="target")
    raw_text = _resolve_input_text(body, storage)
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


def _get_target_profiles(request: Request) -> dict[str, TargetProfile]:
    """Dependency: pull the app-state profiles dict loaded at startup."""
    return getattr(request.app.state, "target_profiles", {})


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
    profiles = _get_target_profiles(request)
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
    profiles = _get_target_profiles(request)
    key = f"{vendor}/{model}"
    if key not in profiles:
        raise HTTPException(
            status_code=404,
            detail=f"target profile not found: {key!r}",
        )
    return profiles[key]

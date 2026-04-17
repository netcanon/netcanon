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
from ...services.migration_detect import DetectCandidate, detect_codec
from ...services.migration_pipeline import run_plan
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

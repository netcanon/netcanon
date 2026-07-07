"""``/api/v1/sanitize`` — POST endpoint to redact PII from an uploaded config.

Same logic path as the CLI's ``netcanon sanitize`` (both call into
:func:`netcanon.tools.sanitize.sanitize_text`).  This endpoint is the
recommended invocation for Docker users — ``curl -F`` against the
running server avoids any ``docker exec`` gymnastics.

Endpoints:

    POST   /api/v1/sanitize
        → multipart form: source_vendor + config (file) + optional
          dry_run flag.  Returns text/plain sanitized config (default)
          or JSON with the substitution audit (dry_run=true).
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse

from ... import config as app_config
from ...migration.codecs.base import ParseError, RenderError
from ...migration.codecs.registry import list_public_codecs
from ...tools.sanitize import sanitize_text

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/sanitize",
    summary="Redact PII from an uploaded network config",
    description=(
        "Parses the uploaded config as `source_vendor`, applies "
        "field-typed PII redactions to the canonical model, then "
        "re-renders in the same vendor's format.  Returns the "
        "sanitized config as text/plain by default, or a JSON "
        "audit log when `dry_run=true`."
    ),
    # Default response is text/plain (the sanitized config); the dry_run
    # branch returns JSON explicitly.  Declaring the class + both content
    # types + the count header keeps the generated OpenAPI honest (#51).
    response_class=PlainTextResponse,
    responses={
        200: {
            "description": (
                "Sanitized config — `text/plain` by default, or a JSON "
                "substitution audit when `dry_run=true`."
            ),
            "content": {"text/plain": {}, "application/json": {}},
            "headers": {
                "X-Netcanon-Substitution-Count": {
                    "description": (
                        "Number of PII substitutions applied "
                        "(text/plain response only)."
                    ),
                    "schema": {"type": "integer"},
                },
            },
        },
        400: {"description": "Upload could not be parsed as `source_vendor`."},
        413: {"description": "Upload exceeds the configured size cap."},
        422: {
            "description": (
                "Unknown `source_vendor`, or the sanitized tree could not be "
                "re-rendered in that vendor's format."
            )
        },
    },
)
async def post_sanitize(
    source_vendor: str = Form(...),
    config: UploadFile = File(...),
    dry_run: bool = Form(False),
):
    available = list_public_codecs()
    if source_vendor not in available:
        # 422 (not 400) — unify with every migration endpoint's unknown-vendor
        # rejection so an unknown codec is one consistent status (#50).
        raise HTTPException(
            status_code=422,
            detail=f"Unknown source_vendor {source_vendor!r}; available: {available}",
        )

    # Bound the read: without a cap the whole body is pulled into memory and
    # fed to the synchronous parse→redact→render pipeline, so an oversized
    # upload is an availability footgun (blind-audit 276eaeb #19).  Read at
    # most cap+1 bytes — if we get more than the cap, the body is too large.
    # The cap is read at request time so it stays env-overridable + testable.
    cap = app_config.MAX_SANITIZE_UPLOAD_BYTES
    raw_bytes = await config.read(cap + 1)
    if len(raw_bytes) > cap:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Config upload exceeds the {cap} byte limit. Raise "
                "NETCANON_MAX_SANITIZE_UPLOAD_BYTES if you must sanitize a "
                "larger file, or run the CLI 'netcanon sanitize' locally."
            ),
        )
    raw = raw_bytes.decode("utf-8", errors="replace")

    try:
        # sanitize_text runs the full parse → redact → render pipeline,
        # which is synchronous + CPU-bound.  Offload it so it never blocks
        # the event loop (mirrors the scheduler's asyncio.to_thread dispatch
        # in routes/schedules.py).
        result = await asyncio.to_thread(
            sanitize_text, raw, source_vendor, dry_run=dry_run
        )
    except ParseError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to parse upload as {source_vendor!r}: {e}",
        ) from e
    except RenderError as e:
        # RenderError is a sibling of ParseError (not caught above); a render
        # failure on the sanitized tree must be a clean 4xx, not an uncaught
        # 500 (API-3).
        raise HTTPException(
            status_code=422,
            detail=f"Failed to render sanitized {source_vendor!r}: {e}",
        ) from e

    if dry_run:
        return JSONResponse({
            "substitutions": [
                {
                    "category": s.category,
                    "field": s.field,
                    "original": s.original,
                    "redacted": s.redacted,
                }
                for s in result.substitutions
            ],
            "total": len(result.substitutions),
        })

    return PlainTextResponse(
        result.sanitized_text,
        headers={
            "X-Netcanon-Substitution-Count": str(len(result.substitutions)),
        },
    )

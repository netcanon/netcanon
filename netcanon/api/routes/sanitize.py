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

import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse

from ...migration.codecs.base import ParseError
from ...migration.codecs.registry import list_codecs
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
)
async def post_sanitize(
    source_vendor: str = Form(...),
    config: UploadFile = File(...),
    dry_run: bool = Form(False),
):
    available = sorted(list_codecs())
    if source_vendor not in available:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown source_vendor {source_vendor!r}; available: {available}",
        )

    raw_bytes = await config.read()
    raw = raw_bytes.decode("utf-8", errors="replace")

    try:
        result = sanitize_text(raw, source_vendor, dry_run=dry_run)
    except ParseError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to parse upload as {source_vendor!r}: {e}",
        )

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

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
from typing import BinaryIO

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse

from ... import config as app_config
from ...migration.codecs.base import ParseError, RenderError
from ...migration.codecs.registry import list_public_codecs
from ...migration.limits import Answer, LimitExceeded, server_scope
from ...tools.sanitize import SanitizationResult, sanitize_text
from ._migration_helpers import refusal_as_http, request_answer, request_limits

router = APIRouter()
logger = logging.getLogger(__name__)


class _UploadTooLarge(Exception):
    """The upload is longer than the byte cap."""


def _sanitize_within(
    limits: str | None, answer: Answer | None, upload: BinaryIO, cap: int,
    vendor: str, dry_run: bool,
) -> SanitizationResult:
    """``sanitize_text`` of *upload* under this server's limits, with
    one deadline for its parse and its render.  The scope is opened
    here, on the worker thread that does the work -- and that waits
    for the request's turn, where the limits say how many work at
    once: the event loop is never the one waiting.  The turn is kept
    until the answer has gone out (*answer*).

    The upload is read HERE, with the turn, and not by the handler
    before it: a request that waits then holds its upload once, as
    the framework stored it, and not a second time as bytes and a
    third as text.

    Raises:
        LimitExceeded: The config is past a limit, the request ran
            out of time, or it did not get a turn.
        _UploadTooLarge: The upload is more than *cap* bytes.
    """
    with server_scope(limits, answer=answer):
        # At most cap+1 bytes: more than the cap is too large, and the
        # rest is never pulled into memory.
        raw_bytes = upload.read(cap + 1)
        if len(raw_bytes) > cap:
            raise _UploadTooLarge
        raw = raw_bytes.decode("utf-8", errors="replace")
        del raw_bytes
        return sanitize_text(raw, vendor, dry_run=dry_run)


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
        413: {
            "description": (
                "Upload exceeds the configured size cap, or the config asks "
                "for more than this server's limits allow "
                "(`NETCANON_CONFIG_LIMITS`): the detail names what was "
                "large, how large, and the limit."
            )
        },
        422: {
            "description": (
                "Unknown `source_vendor`, or the sanitized tree could not be "
                "re-rendered in that vendor's format."
            )
        },
        408: {
            "description": (
                "The upload had not arrived inside the time a request may "
                "take.  Only on a server whose limits say how many requests "
                "work at once."
            )
        },
        503: {
            "description": (
                "The server works on a set number of requests at once "
                "(under the `small` limits: one) and this one did not get "
                "a turn in the time it may take, or got it too late to "
                "finish, or as many were in flight already as may work and "
                "wait.  Send it again (`Retry-After`)."
            )
        },
    },
)
async def post_sanitize(
    request: Request,
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
    # upload is an availability footgun (blind-audit 276eaeb #19).  At most
    # cap+1 bytes are read — more than the cap is too large.  An upload
    # whose size is known is refused here, before any of it is read; the
    # read itself is in the worker (_sanitize_within), which checks again.
    # The cap is read at request time so it stays env-overridable + testable.
    cap = app_config.MAX_SANITIZE_UPLOAD_BYTES
    too_large = HTTPException(
        status_code=413,
        detail=(
            f"Config upload exceeds the {cap} byte limit. Raise "
            "NETCANON_MAX_SANITIZE_UPLOAD_BYTES if you must sanitize a "
            "larger file, or run the CLI 'netcanon sanitize' locally."
        ),
    )
    if config.size is not None and config.size > cap:
        raise too_large

    try:
        # sanitize_text runs the full parse → redact → render pipeline,
        # which is synchronous + CPU-bound.  Offload it so it never blocks
        # the event loop (mirrors the scheduler's asyncio.to_thread dispatch
        # in routes/schedules.py).
        result = await asyncio.to_thread(
            _sanitize_within, request_limits(request), request_answer(request),
            config.file, cap, source_vendor, dry_run,
        )
    except _UploadTooLarge:
        raise too_large from None
    except LimitExceeded as e:
        # 413, the status an upload over the byte cap gets, for the
        # same reason: more than this server is set to take.  503
        # for a request that did not get a turn, or got it too late
        # to finish.  Never the "failed unexpectedly, please report
        # this" net below.
        raise refusal_as_http(e) from e
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
    except Exception as e:  # un-hardened-sibling net (C1)
        # Any OTHER crash from the parse→redact→render pipeline (a raw
        # IndexError / AttributeError codec bug — the crash-on-input class this
        # project has repeatedly found) must be a clean 4xx, not an uncaught
        # 500.  This is the sibling of run_plan's broad-except
        # (services/migration_pipeline.py) and /detect's per-probe net — the
        # same untrusted config text reaches a codec here.  Keep the full
        # traceback server-side; hand the caller only the exception type.
        logger.exception(
            "sanitize pipeline crashed on %r input", source_vendor
        )
        raise HTTPException(
            status_code=422,
            detail=(
                f"Sanitize pipeline failed unexpectedly "
                f"({type(e).__name__}) on {source_vendor!r} input — please "
                "report this with the config snippet that triggered it."
            ),
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

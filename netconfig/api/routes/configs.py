"""
``/api/v1/configs`` routes.

Provides read, delete, and (when enabled) open-in-editor access to
configuration files stored by the backup engine.  Files are served as plain
text so clients can diff, display, or parse them without an extra encoding
step.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse

from ...models.backup import ConfigRecord
from ...models.diff import DiffReport, DiffRequest
from ...services.diff import compute_diff
from ...storage.base import BaseConfigStore
from ..deps import get_storage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/configs", tags=["configs"])

# Extensions permitted for the open-in-editor feature.
_OPEN_ALLOWED_EXTENSIONS = frozenset({".cfg", ".conf", ".txt", ".xml", ".log"})


@router.get(
    "/",
    response_model=list[ConfigRecord],
    summary="List stored configuration files",
)
def list_configs(
    storage: BaseConfigStore = Depends(get_storage),
) -> list[ConfigRecord]:
    """Return metadata for all stored configuration files, newest first."""
    configs = storage.list_configs()
    logger.debug("Listed %d stored config(s)", len(configs))
    return configs


@router.get(
    "/{filename}",
    response_class=PlainTextResponse,
    summary="Retrieve the text of a stored configuration",
)
def get_config(
    filename: str,
    storage: BaseConfigStore = Depends(get_storage),
) -> str:
    """Return the raw text content of the named config file.

    Args:
        filename: Bare filename as returned by the list endpoint
            (e.g. ``Cisco_192-168-1-1_20260414_120000.cfg``).

    Raises:
        HTTPException 404: If the file does not exist.
    """
    try:
        content = storage.get_content(filename)
        logger.debug("Served config %r (%d bytes)", filename, len(content))
        return content
    except FileNotFoundError:
        logger.warning("Config not found: %r", filename)
        raise HTTPException(status_code=404, detail=f"Config not found: {filename!r}")


@router.delete(
    "/{filename}",
    status_code=204,
    summary="Delete a stored configuration file",
)
def delete_config(
    filename: str,
    storage: BaseConfigStore = Depends(get_storage),
) -> None:
    """Permanently delete the named config file.

    Args:
        filename: Bare filename as returned by the list endpoint.

    Raises:
        HTTPException 404: If the file does not exist.
    """
    try:
        storage.delete(filename)
        logger.info("Deleted config %r", filename)
    except FileNotFoundError:
        logger.warning("Delete requested for missing config: %r", filename)
        raise HTTPException(status_code=404, detail=f"Config not found: {filename!r}")


@router.post(
    "/{filename}/open",
    status_code=204,
    summary="Open a stored configuration in the OS default text editor",
)
def open_config(
    filename: str,
    request: Request,
    storage: BaseConfigStore = Depends(get_storage),
) -> None:
    """Open the named config file in the OS default application.

    Uses ``os.startfile()`` (Windows) or ``xdg-open`` / ``open`` on Linux /
    macOS.  Only available when ``settings.open_in_editor`` is ``True``
    (enabled by the desktop application; disabled for remote web deployments).

    Args:
        filename: Bare filename as returned by the list endpoint.

    Raises:
        HTTPException 403: If ``open_in_editor`` is disabled in settings.
        HTTPException 404: If the file does not exist.
        HTTPException 501: If the platform does not support ``os.startfile``.
        HTTPException 500: If the OS refuses to open the file.
    """
    settings = request.app.state.settings
    if not settings.open_in_editor:
        raise HTTPException(
            status_code=403,
            detail="open_in_editor is disabled on this server.",
        )

    # Extension whitelist — only open known config file types.
    if Path(filename).suffix.lower() not in _OPEN_ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="File type not permitted for editor access.",
        )

    try:
        path = storage.resolve_path(filename)
    except FileNotFoundError:
        logger.warning("Open requested for missing config: %r", filename)
        raise HTTPException(status_code=404, detail=f"Config not found: {filename!r}")

    try:
        if sys.platform == "win32":
            import os
            os.startfile(str(path))  # noqa: S606
        elif sys.platform == "darwin":
            import subprocess
            subprocess.run(["open", str(path)], check=True)  # noqa: S603,S607
        else:
            import subprocess
            subprocess.run(["xdg-open", str(path)], check=True)  # noqa: S603,S607
        logger.info("Opened config %r in default editor", filename)
    except NotImplementedError:
        raise HTTPException(
            status_code=501,
            detail="os.startfile is not supported on this platform.",
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to open config %r: %s", filename, exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Could not open file: {exc}",
        )


# ---------------------------------------------------------------------------
# Diff endpoint (Tier 1 — textual line diff)
# ---------------------------------------------------------------------------


def _resolve_record(
    storage: BaseConfigStore, filename: str, side: str
) -> ConfigRecord:
    """Find the ``ConfigRecord`` for *filename* or raise a 404.

    The config list is authoritative — ``resolve_path`` only proves the
    bytes exist on disk, but the metadata (``device_type``,
    ``file_extension``) is what the compatibility check relies on.  A
    missing entry here means the filename was never produced by the
    backup engine, so a 404 is honest.

    Args:
        storage: Config storage backend whose ``list_configs()`` is
            treated as the authoritative inventory.
        filename: Bare filename as returned by the list endpoint.
        side: Either ``"left"`` or ``"right"``; surfaced verbatim in
            the 404 detail so the client can highlight the offending
            field in the diff form.

    Returns:
        The matching ``ConfigRecord`` from ``storage.list_configs()``.

    Raises:
        HTTPException 404: If no record's ``filename`` matches.
    """
    for record in storage.list_configs():
        if record.filename == filename:
            return record
    raise HTTPException(
        status_code=404,
        detail=f"{side.capitalize()} config not found: {filename!r}",
    )


@router.post(
    "/diff",
    response_model=DiffReport,
    summary="Diff two stored configuration files",
    responses={
        404: {"description": "Either referenced config file does not exist"},
        422: {
            "description": (
                "Configs are incompatible for textual diff "
                "(different device_type or file_extension). "
                "Pass ``force=true`` to override."
            )
        },
    },
)
def diff_configs(
    body: DiffRequest,
    storage: BaseConfigStore = Depends(get_storage),
) -> DiffReport:
    """Return a line-level textual diff between two stored configurations.

    Compatibility is checked first — two configs are only diffed freely
    when their ``type_key`` (``device_type``) and file extension match.
    Mismatches produce HTTP 422 unless the caller sets ``force=true`` in
    the request body, in which case the diff is still computed and the
    response's ``compatibility.severity`` is ``block`` so the UI can
    render a warning banner.

    Args:
        body: Request payload with ``left``, ``right``, and optional
            ``force`` flag.

    Raises:
        HTTPException 404: If either filename is not known to the store.
        HTTPException 422: If the two configs are incompatible and
            ``force`` is not set.
    """
    left_rec = _resolve_record(storage, body.left, side="left")
    right_rec = _resolve_record(storage, body.right, side="right")

    # Short-circuit the expensive read if we're going to reject anyway.
    from ...services.diff import check_compatibility

    compat = check_compatibility(left_rec, right_rec)
    if not compat.compatible and not body.force:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Configs are incompatible for textual diff.",
                "reasons": compat.reasons,
                "hint": "Pass force=true to override (cross-vendor diffs are noisy).",
            },
        )

    left_text = storage.get_content(body.left)
    right_text = storage.get_content(body.right)
    report = compute_diff(
        left_rec, left_text, right_rec, right_text, force=body.force
    )
    logger.info(
        "Diff %s vs %s: +%d / -%d (compat=%s, force=%s)",
        body.left,
        body.right,
        report.stats["added"],
        report.stats["removed"],
        report.compatibility.severity,
        body.force,
    )
    return report

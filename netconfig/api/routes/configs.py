"""
``/api/v1/configs`` routes.

Provides read and delete access to configuration files stored by the
backup engine.  Files are served as plain text so clients can diff,
display, or parse them without an extra encoding step.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from ...models.backup import ConfigRecord
from ...storage.base import BaseConfigStore
from ..deps import get_storage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/configs", tags=["configs"])


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

"""
``/api/v1/definitions`` routes.

Definitions are loaded from disk at startup.  Use ``POST /reload`` to
refresh the in-memory registry after editing YAML files without
restarting the server.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from ...definitions.loader import DefinitionLoader
from ...definitions.schema import DeviceDefinition
from ..deps import get_definitions

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/definitions", tags=["definitions"])


@router.get(
    "/",
    response_model=list[DeviceDefinition],
    summary="List all loaded device definitions",
)
def list_definitions(
    definitions: dict[str, DeviceDefinition] = Depends(get_definitions),
) -> list[DeviceDefinition]:
    """Return every device definition currently loaded from the definition tree.

    Definitions are sorted by ``type_key`` for stable ordering.
    """
    return sorted(definitions.values(), key=lambda d: d.type_key)


@router.get(
    "/{type_key}",
    response_model=DeviceDefinition,
    summary="Get a single device definition by type_key",
)
def get_definition(
    type_key: str,
    definitions: dict[str, DeviceDefinition] = Depends(get_definitions),
) -> DeviceDefinition:
    """Return the definition for *type_key*.

    Args:
        type_key: Case-sensitive definition key (e.g. ``Cisco``, ``Fortigate``).

    Raises:
        HTTPException 404: If *type_key* is not in the loaded registry.
    """
    if type_key not in definitions:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Definition {type_key!r} not found. "
                f"Available: {sorted(definitions.keys())}"
            ),
        )
    return definitions[type_key]


@router.post(
    "/reload",
    summary="Reload device definitions from disk",
)
def reload_definitions(request: Request) -> dict:
    """Reload all device definitions from the definitions directory.

    Re-reads every YAML file under the configured ``definitions_dir`` and
    replaces the in-memory registry.  Useful after adding or editing
    definition files without restarting the server.

    Returns:
        A mapping with ``loaded`` (int count) and ``type_keys`` (sorted list).
    """
    settings = request.app.state.settings
    request.app.state.definitions = DefinitionLoader(
        settings.definitions_dir
    ).load_all()
    count = len(request.app.state.definitions)
    logger.info(
        "Definitions reloaded from %s: %d definition(s)",
        settings.definitions_dir,
        count,
    )
    return {
        "loaded": count,
        "type_keys": sorted(request.app.state.definitions.keys()),
    }

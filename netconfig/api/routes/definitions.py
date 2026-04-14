"""
``/api/v1/definitions`` routes.

Definitions are read-only at runtime — they are loaded from disk at
startup and refreshed only by restarting the server.  These endpoints
expose the loaded registry for inspection by the UI and API clients.
"""

from fastapi import APIRouter, Depends, HTTPException

from ...definitions.schema import DeviceDefinition
from ..deps import get_definitions

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

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

    The reload refreshes BOTH:

    * ``state.definitions`` — the family-base map consumed by the
      backup flow and most read paths.
    * ``state.definition_loader`` — the loader instance whose
      ``_variants`` list backs the Definitions page's overlays
      section.  Pre-fix the reload route only updated the first one;
      operators who dropped a new overlay YAML and clicked "Reload
      from disk" silently kept seeing the old overlay set on the
      Definitions page until a process restart cleared it.

    Returns:
        A mapping with ``loaded`` (int count) and ``type_keys``
        (sorted list).
    """
    settings = request.app.state.settings
    new_loader = DefinitionLoader(settings.definitions_dir)
    request.app.state.definitions = new_loader.load_all()
    # Also rotate the loader reference — the /definitions page reads
    # overlays via ``state.definition_loader._variants``; without this
    # the overlays section stays stale until the next process restart.
    request.app.state.definition_loader = new_loader
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

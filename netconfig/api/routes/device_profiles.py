"""
``/api/v1/devices`` routes.

Device profiles store persistent connection details for network devices.
Profiles can be referenced by schedules and backup jobs so credentials
do not need to be re-entered for each operation.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from ...models.device_profile import DeviceProfile, DeviceProfileCreate, DeviceProfileUpdate
from ...storage.device_profile_store import FileDeviceProfileStore
from ..deps import get_device_profile_store, get_device_profiles

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/devices", tags=["device-profiles"])


@router.get(
    "/",
    response_model=list[DeviceProfile],
    summary="List all device profiles",
)
def list_device_profiles(
    device_profiles: dict[str, DeviceProfile] = Depends(get_device_profiles),
) -> list[DeviceProfile]:
    """Return all device profiles sorted newest-first."""
    return sorted(device_profiles.values(), key=lambda p: p.created_at, reverse=True)


@router.get(
    "/{profile_id}",
    response_model=DeviceProfile,
    summary="Get a device profile by ID",
)
def get_device_profile(
    profile_id: str,
    device_profiles: dict[str, DeviceProfile] = Depends(get_device_profiles),
) -> DeviceProfile:
    """Return a single device profile.

    Args:
        profile_id: UUID of the profile.

    Raises:
        HTTPException 404: If no profile with *profile_id* exists.
    """
    if profile_id not in device_profiles:
        raise HTTPException(
            status_code=404, detail=f"Device profile not found: {profile_id!r}"
        )
    return device_profiles[profile_id]


@router.post(
    "/",
    status_code=201,
    response_model=DeviceProfile,
    summary="Create a device profile",
)
def create_device_profile(
    body: DeviceProfileCreate,
    device_profiles: dict[str, DeviceProfile] = Depends(get_device_profiles),
    device_profile_store: FileDeviceProfileStore = Depends(get_device_profile_store),
) -> DeviceProfile:
    """Create a new device profile and persist it to disk.

    Args:
        body: Profile creation payload.

    Returns:
        The newly created ``DeviceProfile``.
    """
    if len(device_profiles) >= 1000:
        raise HTTPException(
            status_code=409,
            detail="Maximum device profile limit reached (1000). Delete unused profiles first.",
        )
    profile = DeviceProfile(**body.model_dump())
    device_profiles[profile.id] = profile
    device_profile_store.save(profile)
    logger.info(
        "Created device profile '%s' (id=%s)", profile.name, profile.id[:8]
    )
    return profile


@router.put(
    "/{profile_id}",
    response_model=DeviceProfile,
    summary="Update a device profile",
)
def update_device_profile(
    profile_id: str,
    body: DeviceProfileUpdate,
    device_profiles: dict[str, DeviceProfile] = Depends(get_device_profiles),
    device_profile_store: FileDeviceProfileStore = Depends(get_device_profile_store),
) -> DeviceProfile:
    """Partially update an existing device profile.

    Only fields that are explicitly supplied (non-``None``) in the request
    body are applied; omitted fields remain unchanged.

    Args:
        profile_id: UUID of the profile to update.
        body: Partial update payload.

    Returns:
        The updated ``DeviceProfile``.

    Raises:
        HTTPException 404: If no profile with *profile_id* exists.
    """
    if profile_id not in device_profiles:
        raise HTTPException(
            status_code=404, detail=f"Device profile not found: {profile_id!r}"
        )
    profile = device_profiles[profile_id]
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    updated_profile = profile.model_copy(update=updates)
    device_profiles[profile_id] = updated_profile
    device_profile_store.save(updated_profile)
    logger.info(
        "Updated device profile '%s' (id=%s)", updated_profile.name, profile_id[:8]
    )
    return updated_profile


@router.delete(
    "/{profile_id}",
    status_code=204,
    summary="Delete a device profile",
)
def delete_device_profile(
    profile_id: str,
    request: Request,
    device_profiles: dict[str, DeviceProfile] = Depends(get_device_profiles),
    device_profile_store: FileDeviceProfileStore = Depends(get_device_profile_store),
) -> None:
    """Delete a device profile.

    Logs a warning if any schedules reference the deleted profile.

    Args:
        profile_id: UUID of the profile to delete.

    Raises:
        HTTPException 404: If no profile with *profile_id* exists.
    """
    if profile_id not in device_profiles:
        raise HTTPException(
            status_code=404, detail=f"Device profile not found: {profile_id!r}"
        )
    # Warn if any schedules reference this profile.
    referencing = [
        s.name
        for s in request.app.state.schedules.values()
        if profile_id in s.target_device_ids
    ]
    if referencing:
        logger.warning(
            "Deleting profile %s which is referenced by schedules: %s",
            profile_id[:8],
            referencing,
        )
    del device_profiles[profile_id]
    device_profile_store.delete(profile_id)
    logger.info("Deleted device profile %s", profile_id[:8])

"""
``/api/v1/devices`` routes.

Device profiles store persistent connection details for network devices.
Profiles can be referenced by schedules and backup jobs so credentials
do not need to be re-entered for each operation.
"""

from __future__ import annotations

import logging
from typing import get_args

from fastapi import APIRouter, Depends, HTTPException, Request

from ...definitions.schema import DeviceDefinition
from ...models.device_profile import (
    DeviceProfile,
    DeviceProfileCreate,
    DeviceProfilePublic,
    DeviceProfileUpdate,
)
from ...storage.device_profile_store import (
    DEVICE_PROFILE_REGISTRY_LOCK,
    FileDeviceProfileStore,
)
from ...storage.schedule_store import SCHEDULE_REGISTRY_LOCK
from ..deps import (
    get_definitions,
    get_device_profile_store,
    get_device_profiles,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/devices", tags=["device-profiles"])

#: DeviceProfile fields whose annotation admits ``None`` — the only fields a
#: PUT may explicitly clear (``enable_password``, ``notes``, ``os_version``,
#: ``model``; plus the API-read-only ``detected_facts``).  Derived from the
#: model so a future nullable field is covered automatically.  An explicit
#: ``null`` for any OTHER (required) field is a 422, not a silent no-op (#12).
_NULLABLE_PROFILE_FIELDS = frozenset(
    name
    for name, field in DeviceProfile.model_fields.items()
    if type(None) in get_args(field.annotation)
)


def _require_known_type_key(
    type_key: str, definitions: dict[str, DeviceDefinition]
) -> None:
    """422 if *type_key* is not a loaded definition (review #53).

    The docs have always said ``type_key`` "must match a loaded definition",
    but the value was previously only checked at backup time — so a typo'd
    profile 201'd and failed days later.  Validate at create/update instead,
    mirroring the POST /backups check.
    """
    if type_key not in definitions:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unknown type_key {type_key!r}. "
                f"Loaded definitions: {sorted(definitions.keys())}"
            ),
        )


@router.get(
    "/",
    response_model=list[DeviceProfilePublic],
    summary="List all device profiles",
)
def list_device_profiles(
    device_profiles: dict[str, DeviceProfile] = Depends(get_device_profiles),
) -> list[DeviceProfile]:
    """Return all device profiles sorted newest-first.

    Credentials are stripped by the ``DeviceProfilePublic`` response model —
    they are never serialised over the API.
    """
    return sorted(device_profiles.values(), key=lambda p: p.created_at, reverse=True)


@router.get(
    "/{profile_id}",
    response_model=DeviceProfilePublic,
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
    response_model=DeviceProfilePublic,
    summary="Create a device profile",
)
def create_device_profile(
    body: DeviceProfileCreate,
    device_profiles: dict[str, DeviceProfile] = Depends(get_device_profiles),
    device_profile_store: FileDeviceProfileStore = Depends(get_device_profile_store),
    definitions: dict[str, DeviceDefinition] = Depends(get_definitions),
) -> DeviceProfile:
    """Create a new device profile and persist it to disk.

    Args:
        body: Profile creation payload.

    Returns:
        The newly created ``DeviceProfile``.

    Raises:
        HTTPException 422: If ``type_key`` is not a loaded definition.
    """
    _require_known_type_key(body.type_key, definitions)
    profile = DeviceProfile(**body.model_dump())
    # Serialise dict-mutate + persist against the backup worker thread and
    # the other route mutators (review finding #10).  The cap check runs
    # INSIDE the lock (review #44): checked outside, two concurrent creates
    # both passed at 999 and landed 1001 profiles.  create_schedule already
    # enforces its cap under the lock — this mirrors it.
    with DEVICE_PROFILE_REGISTRY_LOCK:
        if len(device_profiles) >= 1000:
            raise HTTPException(
                status_code=409,
                detail="Maximum device profile limit reached (1000). Delete unused profiles first.",
            )
        device_profiles[profile.id] = profile
        try:
            device_profile_store.save(profile)
        except OSError as exc:
            # This save is the SOLE persistence — a partial insert would leave
            # the registry ahead of disk (lost on restart).  Roll the in-memory
            # insert back and 500 rather than swallow (review #47b).
            del device_profiles[profile.id]
            logger.error("Failed to persist new device profile: %s", exc)
            raise HTTPException(
                status_code=500,
                detail="Failed to persist device profile to disk.",
            ) from exc
    logger.info(
        "Created device profile '%s' (id=%s)", profile.name, profile.id[:8]
    )
    return profile


@router.put(
    "/{profile_id}",
    response_model=DeviceProfilePublic,
    summary="Update a device profile",
)
def update_device_profile(
    profile_id: str,
    body: DeviceProfileUpdate,
    device_profiles: dict[str, DeviceProfile] = Depends(get_device_profiles),
    device_profile_store: FileDeviceProfileStore = Depends(get_device_profile_store),
    definitions: dict[str, DeviceDefinition] = Depends(get_definitions),
) -> DeviceProfile:
    """Partially update an existing device profile.

    Only fields the client actually SENT are applied; omitted fields remain
    unchanged.  An explicit ``null`` clears a nullable field
    (``enable_password`` / ``notes`` / ``os_version`` / ``model``); an
    explicit ``null`` for a required field (name, type_key, host, port,
    username, password) is rejected with 422 rather than being silently
    ignored (#12).

    Args:
        profile_id: UUID of the profile to update.
        body: Partial update payload.

    Returns:
        The updated ``DeviceProfile``.

    Raises:
        HTTPException 404: If no profile with *profile_id* exists.
        HTTPException 422: If a supplied ``type_key`` is not a loaded
            definition, or a required field was explicitly set to ``null``.
    """
    # (#12) exclude_unset distinguishes "field omitted" (leave unchanged)
    # from "field explicitly null" (clear it) — the previous ``v is not
    # None`` filter conflated the two, so a nullable field could never be
    # cleared via the API despite the docstring promising it.
    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        if value is None and field not in _NULLABLE_PROFILE_FIELDS:
            raise HTTPException(
                status_code=422,
                detail=f"Field {field!r} is required and cannot be cleared "
                f"(null).",
            )
    # Validate an explicitly-supplied type_key against loaded definitions
    # (review #53) before taking the lock — fail fast, not at backup time.
    if updates.get("type_key") is not None:
        _require_known_type_key(updates["type_key"], definitions)
    # Hold the lock across the existence check + mutate + persist so a
    # concurrent delete can't slip between them (review finding #10).
    with DEVICE_PROFILE_REGISTRY_LOCK:
        if profile_id not in device_profiles:
            raise HTTPException(
                status_code=404, detail=f"Device profile not found: {profile_id!r}"
            )
        profile = device_profiles[profile_id]
        updated_profile = profile.model_copy(update=updates)
        device_profiles[profile_id] = updated_profile
        try:
            device_profile_store.save(updated_profile)
        except OSError as exc:
            # Sole persistence — roll the registry back to the pre-update
            # profile so memory can't drift ahead of disk (review #47b).
            device_profiles[profile_id] = profile
            logger.error("Failed to persist updated device profile: %s", exc)
            raise HTTPException(
                status_code=500,
                detail="Failed to persist device profile to disk.",
            ) from exc
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
    # Snapshot the schedules under THEIR lock (review #43).  Iterating the
    # live dict here under the profile lock races a concurrent schedule
    # create/delete → "dictionary changed size during iteration".  Take a
    # copy under SCHEDULE_REGISTRY_LOCK first (released immediately), then
    # warn on the copy — the CONC-6 snapshot pattern.  The two registry
    # locks are never held nested.
    with SCHEDULE_REGISTRY_LOCK:
        schedules_snapshot = list(request.app.state.schedules.values())
    referencing = [
        s.name for s in schedules_snapshot if profile_id in s.target_device_ids
    ]
    # Hold the profile lock across the existence check + delete + file removal
    # so it can't interleave with the backup worker's detected_facts save and
    # resurrect the profile on disk (review finding #10).
    with DEVICE_PROFILE_REGISTRY_LOCK:
        if profile_id not in device_profiles:
            raise HTTPException(
                status_code=404, detail=f"Device profile not found: {profile_id!r}"
            )
        if referencing:
            logger.warning(
                "Deleting profile %s which is referenced by schedules: %s",
                profile_id[:8],
                referencing,
            )
        del device_profiles[profile_id]
        device_profile_store.delete(profile_id)
    logger.info("Deleted device profile %s", profile_id[:8])

"""
Device profile models.

A ``DeviceProfile`` is a persisted device configuration that stores
connection details and credentials for a network device.  Profiles can be
referenced by schedules and backup jobs so the same device does not need to
have its credentials re-entered each time.

Credentials are stored as plaintext strings in these model objects.
Encryption/decryption is handled by :class:`~netconfig.storage.device_profile_store.FileDeviceProfileStore`
so the in-memory representation is always ready to use.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator

from .validators import validate_host as _validate_host


class DeviceProfile(BaseModel):
    """A persisted device connection profile.

    Attributes:
        id: UUID4 string generated at creation.
        name: Human-readable label for the device (e.g. ``"Core Router"``).
        type_key: Must match the ``type_key`` of a loaded device definition.
        host: Hostname or IP address (IPv4, IPv6, or RFC-1123 hostname).
        port: SSH port number.  Defaults to 22.
        username: SSH login name.
        password: SSH login password (plaintext in memory; encrypted on disk).
        enable_password: Privileged-exec password; ``None`` if not required.
        notes: Optional free-text notes about the device.
        created_at: UTC time the profile was created.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    type_key: str
    host: str
    port: int = Field(default=22, ge=1, le=65535)
    username: str
    password: str
    enable_password: str | None = None
    notes: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        return _validate_host(v)


class DeviceProfileCreate(BaseModel):
    """Request body for ``POST /api/v1/devices/``.

    Attributes:
        name: Human-readable label.
        type_key: Must match a loaded definition ``type_key``.
        host: Hostname or IP address (IPv4, IPv6, or RFC-1123 hostname).
        port: SSH port number.  Defaults to 22.
        username: SSH login name.
        password: SSH login password.
        enable_password: Privileged-exec password; ``None`` if not required.
        notes: Optional free-text notes.
    """

    name: str
    type_key: str
    host: str
    port: int = Field(default=22, ge=1, le=65535)
    username: str
    password: str
    enable_password: str | None = None
    notes: str | None = None

    @field_validator("host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        return _validate_host(v)


class DeviceProfileUpdate(BaseModel):
    """Request body for ``PUT /api/v1/devices/{profile_id}``.

    All fields are optional — supply only the fields to change.

    Attributes:
        name: New human-readable label.
        type_key: New definition ``type_key``.
        host: New hostname or IP address (IPv4, IPv6, or RFC-1123 hostname).
        port: New SSH port number.
        username: New SSH login name.
        password: New SSH login password.
        enable_password: New privileged-exec password; pass ``None`` to clear.
        notes: New free-text notes; pass ``None`` to clear.
    """

    name: str | None = None
    type_key: str | None = None
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = None
    password: str | None = None
    enable_password: str | None = None
    notes: str | None = None

    @field_validator("host")
    @classmethod
    def validate_host(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _validate_host(v)

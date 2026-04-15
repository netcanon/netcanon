"""
Device connection models.

These models represent *what to connect to* and *how to authenticate*.
They are accepted as request bodies from API callers and the interactive
web form, never persisted to disk (credentials are in-memory only).
"""

import ipaddress
import re

from pydantic import BaseModel, Field, SecretStr, field_validator

# RFC-1123 hostname: labels of 1–63 alphanumeric/hyphen chars, not starting
# or ending with a hyphen, separated by dots.
_HOSTNAME_RE = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)*"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?$"
)


def _validate_host(v: str) -> str:
    """Accept a valid IPv4, IPv6, or RFC-1123 hostname; reject everything else."""
    v = v.strip()
    try:
        ipaddress.ip_address(v)
        return v
    except ValueError:
        pass
    if _HOSTNAME_RE.match(v):
        return v
    raise ValueError(f"Invalid hostname or IP address: {v!r}")


class DeviceCredentials(BaseModel):
    """SSH authentication credentials for a single device.

    Passwords are stored as ``SecretStr`` so they are never included in
    ``repr()`` output, log lines, or JSON serialisation by default.

    Attributes:
        username: SSH login name.
        password: SSH login password.
        enable_password: Privileged-exec (enable) password.  Required for
            Cisco devices in user-exec mode; ignored for all others.
    """

    username: str
    password: SecretStr
    enable_password: SecretStr | None = None


class DeviceTarget(BaseModel):
    """A device that should be backed up.

    Attributes:
        type_key: Must match the ``type_key`` field of a loaded device
            definition (e.g. ``"Cisco"``, ``"Fortigate"``).
        host: Hostname or IP address (IPv4, IPv6, or RFC-1123 hostname).
        port: SSH port number.  Defaults to 22.
        credentials: Login credentials.
        device_profile_id: UUID of the linked DeviceProfile, or None for
            ad-hoc backups.
    """

    type_key: str = Field(..., description="Must match a loaded definition type_key")
    host: str
    port: int = Field(22, ge=1, le=65535)
    credentials: DeviceCredentials
    device_profile_id: str | None = None

    @field_validator("host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        return _validate_host(v)


class BackupRequest(BaseModel):
    """Request body for ``POST /api/v1/backups``.

    Attributes:
        devices: One or more devices to back up in a single job.  All
            devices are processed; individual failures do not abort the job.
    """

    devices: list[DeviceTarget] = Field(..., min_length=1)

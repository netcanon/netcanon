"""Guard: ``DeviceProfilePublic`` is the read-side view of ``DeviceProfile``
with exactly the two credential fields removed.

The device-profile API serialises every response through
``DeviceProfilePublic`` so decrypted credentials never cross the API
boundary (2026-06 review finding #1).  Because ``DeviceProfilePublic`` lists
its fields explicitly (rather than deriving them), a field added to
``DeviceProfile`` later could silently fail to appear in the read API.  This
two-sided invariant catches that drift in both directions:

  * a new non-credential ``DeviceProfile`` field that wasn't mirrored, and
  * a credential field that leaked back into the public model.
"""

from __future__ import annotations

import pytest

from netcanon.models.device_profile import DeviceProfile, DeviceProfilePublic

pytestmark = pytest.mark.unit

# The two write-only credential fields that must never be serialised.
_CRED_FIELDS = {"password", "enable_password"}


def test_public_model_is_full_model_minus_credentials() -> None:
    full = set(DeviceProfile.model_fields)
    public = set(DeviceProfilePublic.model_fields)
    assert public == full - _CRED_FIELDS, (
        "DeviceProfilePublic field set drifted from DeviceProfile minus "
        f"credentials. Missing: {(full - _CRED_FIELDS) - public}; "
        f"unexpected: {public - (full - _CRED_FIELDS)}"
    )


def test_public_model_omits_both_credential_fields() -> None:
    assert _CRED_FIELDS.isdisjoint(DeviceProfilePublic.model_fields)


def test_public_model_dump_has_no_credentials() -> None:
    """Even constructed from a full profile, the serialised dict is clean."""
    profile = DeviceProfile(
        name="r1",
        type_key="Cisco",
        host="10.0.0.1",
        username="admin",
        password="hunter2",
        enable_password="enable-secret",
    )
    public = DeviceProfilePublic.model_validate(profile.model_dump())
    dumped = public.model_dump()
    assert "password" not in dumped
    assert "enable_password" not in dumped
    # Non-secret fields still round-trip.
    assert dumped["host"] == "10.0.0.1"
    assert dumped["username"] == "admin"

"""Guard: ``BackupSchedulePublic`` / ``ScheduleDevicePublic`` are the
read-side views that strip inline device credentials from schedule API
responses (2026-07-03 review finding SEC-1).

``GET /api/v1/schedules/`` (and create / toggle) previously serialised the
full ``BackupSchedule``, echoing the legacy inline ``devices[].password`` /
``enable_password`` in plaintext.  The routes now serialise through
``BackupSchedulePublic``, whose ``devices`` use ``ScheduleDevicePublic``.

Like the ``DeviceProfilePublic`` guard, these public models list their fields
explicitly, so this two-sided invariant catches drift in both directions:

  * a new ``ScheduleDevice`` / ``BackupSchedule`` field not mirrored, and
  * a credential field leaking back into a public model.
"""
from __future__ import annotations

import pytest

from netcanon.models.schedule import (
    BackupSchedule,
    BackupSchedulePublic,
    ScheduleDevice,
    ScheduleDevicePublic,
)

pytestmark = pytest.mark.unit

_CRED_FIELDS = {"password", "enable_password"}


def test_schedule_device_public_is_device_minus_credentials() -> None:
    full = set(ScheduleDevice.model_fields)
    public = set(ScheduleDevicePublic.model_fields)
    assert public == full - _CRED_FIELDS, (
        "ScheduleDevicePublic field set drifted from ScheduleDevice minus "
        f"credentials. Missing: {(full - _CRED_FIELDS) - public}; "
        f"unexpected: {public - (full - _CRED_FIELDS)}"
    )


def test_schedule_device_public_omits_both_credential_fields() -> None:
    assert _CRED_FIELDS.isdisjoint(ScheduleDevicePublic.model_fields)


def test_backup_schedule_public_has_same_field_names_as_full() -> None:
    """Only the inner ``devices`` type differs — the field NAME set must match
    so no schedule metadata silently disappears from the read API."""
    assert set(BackupSchedulePublic.model_fields) == set(
        BackupSchedule.model_fields
    )


def test_public_dump_from_schedule_with_inline_device_has_no_credentials() -> None:
    """Even constructed from a full schedule carrying an inline device with
    credentials, the serialised dict is clean."""
    schedule = BackupSchedule(
        name="legacy inline",
        interval_minutes=60,
        devices=[
            ScheduleDevice(
                type_key="Cisco",
                host="10.0.0.1",
                port=22,
                username="admin",
                password="hunter2",
                enable_password="enable-secret",
            )
        ],
    )
    public = BackupSchedulePublic.model_validate(schedule.model_dump())
    dumped = public.model_dump()
    assert "hunter2" not in str(dumped)
    assert "enable-secret" not in str(dumped)
    dev = dumped["devices"][0]
    assert "password" not in dev
    assert "enable_password" not in dev
    # Non-secret device fields still round-trip.
    assert dev["host"] == "10.0.0.1"
    assert dev["username"] == "admin"

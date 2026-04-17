"""
Unit tests for schedule-related models and the ``_format_interval`` helper.

Pure Pydantic model construction / validation — no I/O or network.
``_format_interval`` is imported inside each test body to avoid triggering the
module-level ``app = create_app()`` call at import time.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from netconfig.models.backup import BackupJob, JobStatus
from netconfig.models.schedule import BackupSchedule, ScheduleCreate, ScheduleDevice

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# ScheduleDevice
# ---------------------------------------------------------------------------


class TestScheduleDevice:
    def _make(self, **kwargs) -> ScheduleDevice:
        defaults = dict(
            type_key="Cisco",
            host="192.168.1.1",
            username="admin",
            password="secret",
        )
        defaults.update(kwargs)
        return ScheduleDevice(**defaults)

    def test_default_port_is_22(self):
        device = self._make()
        assert device.port == 22

    def test_custom_port_accepted(self):
        device = self._make(port=2222)
        assert device.port == 2222

    def test_enable_password_defaults_to_none(self):
        device = self._make()
        assert device.enable_password is None

    def test_enable_password_can_be_set(self):
        device = self._make(enable_password="enablepw")
        assert device.enable_password == "enablepw"

    def test_type_key_required(self):
        with pytest.raises(ValidationError):
            ScheduleDevice(
                host="192.168.1.1",
                username="admin",
                password="secret",
            )  # type: ignore[call-arg]

    def test_host_required(self):
        with pytest.raises(ValidationError):
            ScheduleDevice(
                type_key="Cisco",
                username="admin",
                password="secret",
            )  # type: ignore[call-arg]

    def test_username_required(self):
        with pytest.raises(ValidationError):
            ScheduleDevice(
                type_key="Cisco",
                host="192.168.1.1",
                password="secret",
            )  # type: ignore[call-arg]

    def test_password_required(self):
        with pytest.raises(ValidationError):
            ScheduleDevice(
                type_key="Cisco",
                host="192.168.1.1",
                username="admin",
            )  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# ScheduleCreate
# ---------------------------------------------------------------------------


class TestScheduleCreate:
    def test_valid_construction_with_type_keys(self):
        sc = ScheduleCreate(
            name="Nightly Backup",
            interval_minutes=60,
            target_type_keys=["Cisco"],
        )
        assert sc.name == "Nightly Backup"
        assert sc.interval_minutes == 60
        assert sc.target_type_keys == ["Cisco"]

    def test_valid_construction_with_device_ids(self):
        sc = ScheduleCreate(
            name="Specific Device Backup",
            interval_minutes=60,
            target_device_ids=["some-uuid-1234"],
        )
        assert sc.target_device_ids == ["some-uuid-1234"]

    def test_valid_construction_with_both_targets(self):
        sc = ScheduleCreate(
            name="Combined",
            interval_minutes=30,
            target_type_keys=["Cisco"],
            target_device_ids=["some-uuid-1234"],
        )
        assert sc.target_type_keys == ["Cisco"]
        assert sc.target_device_ids == ["some-uuid-1234"]

    def test_interval_minutes_zero_raises(self):
        with pytest.raises(ValidationError):
            ScheduleCreate(
                name="Bad Schedule",
                interval_minutes=0,
                target_type_keys=["Cisco"],
            )

    def test_interval_minutes_one_is_valid(self):
        sc = ScheduleCreate(
            name="Fast Schedule",
            interval_minutes=1,
            target_type_keys=["Cisco"],
        )
        assert sc.interval_minutes == 1

    def test_no_targets_raises(self):
        with pytest.raises(ValidationError):
            ScheduleCreate(
                name="No Targets",
                interval_minutes=30,
                target_type_keys=[],
                target_device_ids=[],
            )

    def test_no_targets_omitted_raises(self):
        with pytest.raises(ValidationError):
            ScheduleCreate(
                name="No Targets",
                interval_minutes=30,
            )


# ---------------------------------------------------------------------------
# BackupSchedule
# ---------------------------------------------------------------------------


class TestBackupSchedule:
    def _make_device(self) -> ScheduleDevice:
        return ScheduleDevice(
            type_key="Cisco",
            host="192.168.1.1",
            username="admin",
            password="secret",
        )

    def _make(self, **kwargs) -> BackupSchedule:
        defaults = dict(
            name="Weekly Backup",
            interval_minutes=10080,
            devices=[self._make_device()],
        )
        defaults.update(kwargs)
        return BackupSchedule(**defaults)

    def test_id_auto_generated(self):
        schedule = self._make()
        assert isinstance(schedule.id, str)
        assert len(schedule.id) > 0

    def test_two_schedules_have_different_ids(self):
        s1 = self._make()
        s2 = self._make()
        assert s1.id != s2.id

    def test_enabled_defaults_to_true(self):
        schedule = self._make()
        assert schedule.enabled is True

    def test_last_run_at_defaults_to_none(self):
        schedule = self._make()
        assert schedule.last_run_at is None

    def test_next_run_at_defaults_to_none(self):
        schedule = self._make()
        assert schedule.next_run_at is None

    def test_last_job_id_defaults_to_none(self):
        schedule = self._make()
        assert schedule.last_job_id is None

    def test_created_at_preserved(self):
        ts = datetime(2026, 4, 14, 9, 0, 0, tzinfo=timezone.utc)
        schedule = self._make(created_at=ts)
        assert schedule.created_at == ts

    def test_name_stored_correctly(self):
        schedule = self._make(name="My Schedule")
        assert schedule.name == "My Schedule"

    def test_interval_minutes_stored_correctly(self):
        schedule = self._make(interval_minutes=120)
        assert schedule.interval_minutes == 120


# ---------------------------------------------------------------------------
# BackupJob — schedule fields
# ---------------------------------------------------------------------------


class TestBackupJobScheduleFields:
    def _make_job(self, **kwargs) -> BackupJob:
        defaults = dict(
            id="test-uuid-abcd",
            status=JobStatus.pending,
            created_at=datetime(2026, 4, 14, 12, 0, 0, tzinfo=timezone.utc),
            total_devices=1,
        )
        defaults.update(kwargs)
        return BackupJob(**defaults)

    def test_schedule_id_defaults_to_none(self):
        job = self._make_job()
        assert job.schedule_id is None

    def test_schedule_name_defaults_to_none(self):
        job = self._make_job()
        assert job.schedule_name is None

    def test_schedule_id_can_be_set(self):
        job = self._make_job(schedule_id="sched-uuid-1234")
        assert job.schedule_id == "sched-uuid-1234"

    def test_schedule_name_can_be_set(self):
        job = self._make_job(schedule_name="Nightly Backup")
        assert job.schedule_name == "Nightly Backup"

    def test_both_fields_serialise_to_none_when_unset(self):
        job = self._make_job()
        data = job.model_dump()
        assert data["schedule_id"] is None
        assert data["schedule_name"] is None


# ---------------------------------------------------------------------------
# _format_interval
# ---------------------------------------------------------------------------


class TestFormatInterval:
    def test_1_minute(self):
        from netconfig.api.routes.ui import _format_interval
        assert _format_interval(1) == "Every 1 min"

    def test_30_minutes(self):
        from netconfig.api.routes.ui import _format_interval
        assert _format_interval(30) == "Every 30 min"

    def test_59_minutes(self):
        from netconfig.api.routes.ui import _format_interval
        assert _format_interval(59) == "Every 59 min"

    def test_60_minutes(self):
        from netconfig.api.routes.ui import _format_interval
        assert _format_interval(60) == "Every 1 hour"

    def test_120_minutes(self):
        from netconfig.api.routes.ui import _format_interval
        assert _format_interval(120) == "Every 2 hours"

    def test_90_minutes_integer_division(self):
        from netconfig.api.routes.ui import _format_interval
        assert _format_interval(90) == "Every 1 hour"

    def test_1439_minutes(self):
        from netconfig.api.routes.ui import _format_interval
        assert _format_interval(1439) == "Every 23 hours"

    def test_1440_minutes(self):
        from netconfig.api.routes.ui import _format_interval
        assert _format_interval(1440) == "Every 1 day"

    def test_2880_minutes(self):
        from netconfig.api.routes.ui import _format_interval
        assert _format_interval(2880) == "Every 2 days"

    def test_10079_minutes(self):
        from netconfig.api.routes.ui import _format_interval
        assert _format_interval(10079) == "Every 6 days"

    def test_10080_minutes(self):
        from netconfig.api.routes.ui import _format_interval
        assert _format_interval(10080) == "Every 1 week"

    def test_20160_minutes(self):
        from netconfig.api.routes.ui import _format_interval
        assert _format_interval(20160) == "Every 2 weeks"

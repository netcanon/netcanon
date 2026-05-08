"""
Unit tests for ``netcanon.models.device`` and ``netcanon.models.backup``.

Pure Pydantic model construction / validation — no I/O or network.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import SecretStr, ValidationError

from netcanon.models.backup import BackupJob, BackupResult, ConfigRecord, JobStatus
from netcanon.models.device import BackupRequest, DeviceCredentials, DeviceTarget

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# DeviceCredentials
# ---------------------------------------------------------------------------


class TestDeviceCredentials:
    def test_password_stored_as_secret_str(self):
        creds = DeviceCredentials(username="admin", password="s3cr3t")
        assert isinstance(creds.password, SecretStr)

    def test_password_not_in_repr(self):
        creds = DeviceCredentials(username="admin", password="s3cr3t")
        assert "s3cr3t" not in repr(creds)

    def test_password_not_in_str(self):
        creds = DeviceCredentials(username="admin", password="s3cr3t")
        assert "s3cr3t" not in str(creds)

    def test_password_accessible_via_get_secret_value(self):
        creds = DeviceCredentials(username="admin", password="s3cr3t")
        assert creds.password.get_secret_value() == "s3cr3t"

    def test_enable_password_optional(self):
        creds = DeviceCredentials(username="admin", password="pw")
        assert creds.enable_password is None

    def test_enable_password_stored_as_secret_str(self):
        creds = DeviceCredentials(
            username="admin", password="pw", enable_password="enable_pw"
        )
        assert isinstance(creds.enable_password, SecretStr)

    def test_enable_password_not_in_repr(self):
        creds = DeviceCredentials(
            username="admin", password="pw", enable_password="enable_pw"
        )
        assert "enable_pw" not in repr(creds)

    def test_username_required(self):
        with pytest.raises(ValidationError):
            DeviceCredentials(password="pw")  # type: ignore[call-arg]

    def test_password_required(self):
        with pytest.raises(ValidationError):
            DeviceCredentials(username="admin")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# DeviceTarget
# ---------------------------------------------------------------------------


class TestDeviceTarget:
    def _make(self, **kwargs) -> DeviceTarget:
        defaults = dict(
            type_key="Cisco",
            host="192.168.1.1",
            credentials=DeviceCredentials(username="admin", password="pw"),
        )
        defaults.update(kwargs)
        return DeviceTarget(**defaults)

    def test_default_port_is_22(self):
        target = self._make()
        assert target.port == 22

    def test_custom_port(self):
        target = self._make(port=2222)
        assert target.port == 2222

    def test_port_lower_bound(self):
        with pytest.raises(ValidationError):
            self._make(port=0)

    def test_port_upper_bound(self):
        with pytest.raises(ValidationError):
            self._make(port=65536)

    def test_type_key_required(self):
        with pytest.raises(ValidationError):
            DeviceTarget(
                host="192.168.1.1",
                credentials=DeviceCredentials(username="admin", password="pw"),
            )

    def test_host_required(self):
        with pytest.raises(ValidationError):
            DeviceTarget(
                type_key="Cisco",
                credentials=DeviceCredentials(username="admin", password="pw"),
            )

    # Host validation (security)
    def test_ipv4_accepted(self):
        t = self._make(host="10.0.0.1")
        assert t.host == "10.0.0.1"

    def test_ipv6_accepted(self):
        t = self._make(host="::1")
        assert t.host == "::1"

    def test_hostname_accepted(self):
        t = self._make(host="router.example.com")
        assert t.host == "router.example.com"

    def test_dotdot_host_rejected(self):
        with pytest.raises(ValidationError):
            self._make(host="../../etc/passwd")

    def test_slash_host_rejected(self):
        with pytest.raises(ValidationError):
            self._make(host="/etc/passwd")

    def test_space_in_host_rejected(self):
        with pytest.raises(ValidationError):
            self._make(host="host name")

    def test_semicolon_host_rejected(self):
        with pytest.raises(ValidationError):
            self._make(host="host;rm -rf /")


# ---------------------------------------------------------------------------
# BackupRequest
# ---------------------------------------------------------------------------


class TestBackupRequest:
    def _make_target(self, host: str = "192.168.1.1") -> DeviceTarget:
        return DeviceTarget(
            type_key="Cisco",
            host=host,
            credentials=DeviceCredentials(username="admin", password="pw"),
        )

    def test_single_device_valid(self):
        req = BackupRequest(devices=[self._make_target()])
        assert len(req.devices) == 1

    def test_multiple_devices_valid(self):
        req = BackupRequest(
            devices=[self._make_target("1.1.1.1"), self._make_target("2.2.2.2")]
        )
        assert len(req.devices) == 2

    def test_empty_device_list_raises(self):
        with pytest.raises(ValidationError):
            BackupRequest(devices=[])

    def test_devices_required(self):
        with pytest.raises(ValidationError):
            BackupRequest()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# JobStatus
# ---------------------------------------------------------------------------


class TestJobStatus:
    def test_all_statuses_are_str_subclass(self):
        for status in JobStatus:
            assert isinstance(status.value, str)

    def test_pending_value(self):
        assert JobStatus.pending == "pending"

    def test_running_value(self):
        assert JobStatus.running == "running"

    def test_completed_value(self):
        assert JobStatus.completed == "completed"

    def test_failed_value(self):
        assert JobStatus.failed == "failed"

    def test_partial_value(self):
        assert JobStatus.partial == "partial"


# ---------------------------------------------------------------------------
# ConfigRecord
# ---------------------------------------------------------------------------


class TestConfigRecord:
    def _make(self) -> ConfigRecord:
        return ConfigRecord(
            device_type="Cisco",
            host="192.168.1.1",
            timestamp=datetime(2026, 4, 14, 12, 0, 0, tzinfo=timezone.utc),
            filename="Cisco_192-168-1-1_20260414_120000.cfg",
            file_extension="cfg",
            size_bytes=1234,
        )

    def test_construction(self):
        r = self._make()
        assert r.device_type == "Cisco"
        assert r.size_bytes == 1234

    def test_serializes_to_dict(self):
        r = self._make()
        data = r.model_dump()
        assert data["device_type"] == "Cisco"
        assert data["filename"] == "Cisco_192-168-1-1_20260414_120000.cfg"


# ---------------------------------------------------------------------------
# BackupResult
# ---------------------------------------------------------------------------


class TestBackupResult:
    def _success_result(self) -> BackupResult:
        return BackupResult(
            device_type="Cisco",
            host="192.168.1.1",
            status="success",
            config_record=ConfigRecord(
                device_type="Cisco",
                host="192.168.1.1",
                timestamp=datetime(2026, 4, 14, 12, 0, 0, tzinfo=timezone.utc),
                filename="Cisco_192-168-1-1_20260414_120000.cfg",
                file_extension="cfg",
                size_bytes=100,
            ),
            duration_seconds=1.23,
        )

    def test_success_result(self):
        r = self._success_result()
        assert r.status == "success"
        assert r.error is None
        assert r.config_record is not None

    def test_failed_result(self):
        r = BackupResult(
            device_type="Cisco",
            host="192.168.1.1",
            status="failed",
            error="Connection refused",
            duration_seconds=0.5,
        )
        assert r.status == "failed"
        assert r.config_record is None
        assert r.error == "Connection refused"

    def test_invalid_status_raises(self):
        with pytest.raises(ValidationError):
            BackupResult(
                device_type="Cisco",
                host="192.168.1.1",
                status="unknown",  # type: ignore[arg-type]
                duration_seconds=0.1,
            )

    def test_queued_status_allowed(self):
        """Intermediate lifecycle state: device waiting for its turn."""
        r = BackupResult(
            device_type="Cisco",
            host="192.168.1.1",
            status="queued",
            duration_seconds=0.0,
        )
        assert r.status == "queued"
        assert r.config_record is None
        assert r.error is None

    def test_running_status_allowed(self):
        """Intermediate lifecycle state: collector actively working."""
        r = BackupResult(
            device_type="Cisco",
            host="192.168.1.1",
            status="running",
            duration_seconds=0.0,
        )
        assert r.status == "running"


# ---------------------------------------------------------------------------
# BackupJob
# ---------------------------------------------------------------------------


class TestBackupJob:
    def _make_job(self, **kwargs) -> BackupJob:
        defaults = dict(
            id="test-uuid-1234",
            status=JobStatus.pending,
            created_at=datetime(2026, 4, 14, 12, 0, 0, tzinfo=timezone.utc),
            total_devices=2,
        )
        defaults.update(kwargs)
        return BackupJob(**defaults)

    def test_default_results_empty(self):
        job = self._make_job()
        assert job.results == []

    def test_default_completed_at_none(self):
        job = self._make_job()
        assert job.completed_at is None

    def test_default_status_pending(self):
        job = self._make_job()
        assert job.status == JobStatus.pending

    def test_status_mutable(self):
        job = self._make_job()
        job.status = JobStatus.running
        assert job.status == JobStatus.running

    def test_serializes_status_as_string(self):
        job = self._make_job()
        data = job.model_dump()
        assert data["status"] == "pending"

    def test_id_preserved(self):
        job = self._make_job()
        assert job.id == "test-uuid-1234"

    def test_total_devices(self):
        job = self._make_job(total_devices=3)
        assert job.total_devices == 3

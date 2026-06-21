"""
Unit tests for the job-level ``Settings`` injection (run3
``settings-reinstantiated-per-call``).

Previously each collector ``collect`` / ``probe`` call constructed its own
``Settings()`` — re-reading env / .env on every SSH session (up to 2× per
device, ×N devices per job).  The backup runner now resolves ``Settings``
once per job and injects it onto each device's collectors via the
``BaseCollector.settings`` slot; collectors read it through
:meth:`BaseCollector._effective_settings`, falling back to a fresh resolve
when none was injected (standalone use / tests).

These tests cover the new contract directly so it can't silently regress:

1. :meth:`BaseCollector._effective_settings` returns the injected snapshot,
   or a fresh :class:`Settings` when absent.
2. :func:`run_backup_job` resolves exactly ONE snapshot and threads that same
   object to every device (mock :func:`_process_one_device` to observe the
   value without real SSH — per AGENTS.md the collection layer is mocked, not
   ``paramiko`` / ``ConnectHandler``).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from netcanon.collectors.base import BaseCollector
from netcanon.config import Settings
from netcanon.models.backup import BackupJob
from netcanon.models.device import BackupRequest, DeviceCredentials, DeviceTarget
from netcanon.services import backup_runner

pytestmark = pytest.mark.unit


class _StubCollector(BaseCollector):
    """Minimal concrete collector — never connects; only exercises the
    shared ``_effective_settings`` helper on the base class."""

    def collect(self, device, definition) -> str:  # pragma: no cover - unused
        return ""


class TestEffectiveSettings:
    def test_returns_injected_snapshot_when_set(self):
        """When the runner injects a snapshot, the collector uses that exact
        object rather than re-resolving."""
        injected = Settings()
        collector = _StubCollector()
        collector.settings = injected
        assert collector._effective_settings() is injected

    def test_resolves_fresh_when_absent(self):
        """A standalone collector (no injection) still resolves a usable
        :class:`Settings` on demand — back-compat for direct callers/tests."""
        collector = _StubCollector()
        assert collector.settings is None  # class default
        resolved = collector._effective_settings()
        assert isinstance(resolved, Settings)


def _one_device_request(host: str = "10.0.0.1") -> BackupRequest:
    return BackupRequest(
        devices=[
            DeviceTarget(
                type_key="X",
                host=host,
                credentials=DeviceCredentials(username="u", password="p"),
            )
        ]
    )


def _fresh_job() -> BackupJob:
    return BackupJob(id="test-job", created_at=datetime.now(UTC))


class TestRunBackupJobResolvesSettingsOnce:
    """``run_backup_job`` is the single seam that resolves Settings; it must
    thread one snapshot to every device.  We patch ``_process_one_device``
    (the real collection callee) to record the injected ``settings`` argument
    — its last positional arg — instead of attempting any SSH."""

    def _patch_recorder(self, monkeypatch) -> list:
        captured: list = []

        def _recorder(*args, **kwargs):
            # run_backup_job passes settings positionally as the final arg.
            captured.append(kwargs.get("settings", args[-1]))

        monkeypatch.setattr(backup_runner, "_process_one_device", _recorder)
        return captured

    def test_caller_supplied_settings_is_threaded_verbatim(self, monkeypatch):
        captured = self._patch_recorder(monkeypatch)
        sentinel = Settings()
        backup_runner.run_backup_job(
            _fresh_job(), _one_device_request(), {}, storage=None,
            settings=sentinel,
        )
        assert captured == [sentinel]
        assert captured[0] is sentinel

    def test_resolves_a_snapshot_when_caller_omits_settings(self, monkeypatch):
        captured = self._patch_recorder(monkeypatch)
        backup_runner.run_backup_job(
            _fresh_job(), _one_device_request(), {}, storage=None,
        )
        assert len(captured) == 1
        assert isinstance(captured[0], Settings)

    def test_same_snapshot_shared_across_all_devices(self, monkeypatch):
        """Resolved ONCE, not once-per-device: every device in a multi-device
        job receives the identical object."""
        captured = self._patch_recorder(monkeypatch)
        request = BackupRequest(
            devices=[
                DeviceTarget(
                    type_key="X", host=f"10.0.0.{i}",
                    credentials=DeviceCredentials(username="u", password="p"),
                )
                for i in range(1, 5)
            ]
        )
        backup_runner.run_backup_job(_fresh_job(), request, {}, storage=None)
        assert len(captured) == 4
        first = captured[0]
        assert all(s is first for s in captured), "settings re-resolved per device"

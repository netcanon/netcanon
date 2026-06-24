"""Unit tests for the host-key policy helpers (review finding #11).

The full paramiko TOFU behaviour is exercised against a real in-process SSH
server in ``tests/integration/test_ssh_hostkey.py``; here we pin the pure
bits: the Netmiko param mapping and the known_hosts path derivation.
"""

from __future__ import annotations

import pytest

from netcanon.collectors.hostkey import (
    host_key_warning_reason,
    known_hosts_path,
    netmiko_host_key_params,
)
from netcanon.config import Settings

pytestmark = pytest.mark.unit


def test_auto_add_adds_no_netmiko_params(tmp_path) -> None:
    s = Settings(ssh_host_key_checking="auto_add", data_dir=tmp_path)
    assert netmiko_host_key_params(s) == {}


@pytest.mark.parametrize("mode", ["tofu", "reject"])
def test_strict_modes_point_netmiko_at_netcanon_store(tmp_path, mode) -> None:
    """tofu/reject point Netmiko at the netcanon-managed known_hosts store
    (populated by the verify_host_key pre-flight), NOT the operator's OS
    ~/.ssh/known_hosts."""
    s = Settings(ssh_host_key_checking=mode, data_dir=tmp_path)
    params = netmiko_host_key_params(s)
    assert params == {
        "alt_host_keys": True,
        "alt_key_file": str(known_hosts_path(s)),
        "ssh_strict": True,
    }
    # The old OS-known_hosts mechanism must be gone.
    assert "system_host_keys" not in params


def test_known_hosts_path_under_data_dir(tmp_path) -> None:
    s = Settings(ssh_host_key_checking="tofu", data_dir=tmp_path)
    assert known_hosts_path(s) == tmp_path / "known_hosts"


def test_default_is_auto_add() -> None:
    # No env override → legacy behaviour, so existing deployments are unchanged.
    assert Settings().ssh_host_key_checking == "auto_add"


def test_warning_reason_fires_for_auto_add_default(tmp_path) -> None:
    """The insecure-default (auto_add) is surfaced once at startup — a
    server logs this so the posture is a conscious choice (audit T0-4)."""
    s = Settings(ssh_host_key_checking="auto_add", data_dir=tmp_path)
    reason = host_key_warning_reason(s)
    assert reason is not None
    assert "auto_add" in reason
    assert "NETCANON_SSH_HOST_KEY_CHECKING" in reason


@pytest.mark.parametrize("mode", ["tofu", "reject"])
def test_no_warning_reason_for_strict_modes(tmp_path, mode) -> None:
    s = Settings(ssh_host_key_checking=mode, data_dir=tmp_path)
    assert host_key_warning_reason(s) is None

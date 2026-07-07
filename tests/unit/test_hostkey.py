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
    persist_paramiko_host_keys,
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


def test_default_is_tofu() -> None:
    # v0.4.5 flipped the secure default: host-key verification is ON unless
    # explicitly disabled with auto_add.
    assert Settings().ssh_host_key_checking == "tofu"


def test_warning_reason_fires_when_auto_add_selected(tmp_path) -> None:
    """auto_add is now an explicit opt-OUT of host-key verification; a
    server surfaces that insecure choice once at startup (audit T0-4)."""
    s = Settings(ssh_host_key_checking="auto_add", data_dir=tmp_path)
    reason = host_key_warning_reason(s)
    assert reason is not None
    assert "auto_add" in reason
    assert "NETCANON_SSH_HOST_KEY_CHECKING" in reason


@pytest.mark.parametrize("mode", ["tofu", "reject"])
def test_no_warning_reason_for_strict_modes(tmp_path, mode) -> None:
    s = Settings(ssh_host_key_checking=mode, data_dir=tmp_path)
    assert host_key_warning_reason(s) is None


def test_persist_merges_concurrent_first_time_keys(tmp_path) -> None:
    """persist_paramiko_host_keys read-merge-writes the store (review #2).

    Two first-time TOFU backups that each learned a different device key must
    BOTH end up pinned.  ``client.save_host_keys`` (the pre-fix call) plain-
    overwrites with only the calling client's keys, so the second persist
    would drop the first device's pin — silently re-TOFU'ing it unverified.
    """
    import paramiko

    s = Settings(ssh_host_key_checking="tofu", data_dir=tmp_path)
    kh = known_hosts_path(s)

    def _client_with(hostname: str, key) -> paramiko.SSHClient:
        c = paramiko.SSHClient()
        c.get_host_keys().add(hostname, key.get_name(), key)
        return c

    key_a = paramiko.ECDSAKey.generate()
    key_b = paramiko.ECDSAKey.generate()
    # Each worker starts from an EMPTY in-memory store (the file did not exist
    # when its client applied the policy), then persists in sequence.
    persist_paramiko_host_keys(_client_with("10.0.0.1", key_a), s)
    persist_paramiko_host_keys(_client_with("10.0.0.2", key_b), s)

    saved = paramiko.HostKeys()
    saved.load(str(kh))
    assert saved.lookup("10.0.0.1") is not None, (
        "first device's pin was clobbered — persist overwrote instead of merging"
    )
    assert saved.lookup("10.0.0.2") is not None

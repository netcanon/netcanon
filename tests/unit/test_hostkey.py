"""Unit tests for the host-key policy helpers (review finding #11).

The full paramiko TOFU behaviour is exercised against a real in-process SSH
server in ``tests/integration/test_ssh_hostkey.py``; here we pin the pure
bits: the Netmiko param mapping and the known_hosts path derivation.
"""

from __future__ import annotations

import pytest

from netcanon.collectors.hostkey import known_hosts_path, netmiko_host_key_params
from netcanon.config import Settings

pytestmark = pytest.mark.unit


def test_auto_add_adds_no_netmiko_params(tmp_path) -> None:
    s = Settings(ssh_host_key_checking="auto_add", data_dir=tmp_path)
    assert netmiko_host_key_params(s) == {}


@pytest.mark.parametrize("mode", ["tofu", "reject"])
def test_strict_modes_enable_netmiko_host_key_checking(tmp_path, mode) -> None:
    s = Settings(ssh_host_key_checking=mode, data_dir=tmp_path)
    params = netmiko_host_key_params(s)
    assert params == {"system_host_keys": True, "ssh_strict": True}


def test_known_hosts_path_under_data_dir(tmp_path) -> None:
    s = Settings(ssh_host_key_checking="tofu", data_dir=tmp_path)
    assert known_hosts_path(s) == tmp_path / "known_hosts"


def test_default_is_auto_add() -> None:
    # No env override → legacy behaviour, so existing deployments are unchanged.
    assert Settings().ssh_host_key_checking == "auto_add"

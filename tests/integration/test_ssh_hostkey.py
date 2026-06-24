"""Real-SSH host-key policy tests (review finding #11).

The rest of the suite mocks ``get_collector``, so SSH never actually runs.
The host-key policy in :mod:`netcanon.collectors.hostkey` is the one place
where a unit-level mock would prove nothing — the behaviour lives in
paramiko's transport handshake.  These tests therefore stand up a real
in-process paramiko SSH **server** on a loopback socket and drive a real
``SSHClient`` against it (pure-Python, no Docker, no external host), so the
TOFU learn/persist, reconnect-stable, changed-key-rejected, and
reject-unknown paths are exercised end-to-end.
"""

from __future__ import annotations

import socket
import threading

import paramiko
import pytest

from netcanon.collectors.hostkey import (
    apply_paramiko_policy,
    known_hosts_path,
    persist_paramiko_host_keys,
    verify_host_key,
)
from netcanon.config import Settings

pytestmark = pytest.mark.integration


class _AcceptingServer(paramiko.ServerInterface):
    """Accepts any password; we only need the transport + auth to complete
    so the client performs host-key verification."""

    def check_auth_password(self, username, password):
        return paramiko.AUTH_SUCCESSFUL

    def get_allowed_auths(self, username):
        return "password"


class _SSHServerStub:
    """A loopback SSH server whose host key can be swapped between
    connections (to simulate a re-key / MITM on the same host:port)."""

    def __init__(self, host_key: paramiko.PKey) -> None:
        self.host_key = host_key
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(5)
        self.port = self._sock.getsockname()[1]
        self._running = True
        self._transports: list[paramiko.Transport] = []
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def set_host_key(self, host_key: paramiko.PKey) -> None:
        self.host_key = host_key

    def _serve(self) -> None:
        self._sock.settimeout(0.5)
        while self._running:
            try:
                conn, _ = self._sock.accept()
            except (TimeoutError, OSError):
                continue
            transport = paramiko.Transport(conn)
            transport.add_server_key(self.host_key)
            self._transports.append(transport)
            try:
                transport.start_server(server=_AcceptingServer())
            except Exception:
                pass

    def close(self) -> None:
        self._running = False
        for transport in self._transports:
            try:
                transport.close()
            except Exception:
                pass
        try:
            self._sock.close()
        except Exception:
            pass


def _settings(tmp_path, mode: str) -> Settings:
    return Settings(ssh_host_key_checking=mode, data_dir=tmp_path)


def _connect(host: str, port: int, settings: Settings) -> None:
    """Mirror the collector's connect path: apply policy, connect, persist."""
    client = paramiko.SSHClient()
    apply_paramiko_policy(client, settings)
    try:
        client.connect(
            hostname=host,
            port=port,
            username="netops",
            password="pw",
            timeout=5,
            banner_timeout=5,
            auth_timeout=5,
            look_for_keys=False,
            allow_agent=False,
        )
        persist_paramiko_host_keys(client, settings)
    finally:
        client.close()


@pytest.fixture()
def server():
    key_a = paramiko.RSAKey.generate(2048)
    stub = _SSHServerStub(key_a)
    try:
        yield stub
    finally:
        stub.close()


def test_auto_add_connects_without_a_store(tmp_path, server) -> None:
    settings = _settings(tmp_path, "auto_add")
    _connect("127.0.0.1", server.port, settings)
    # Legacy behaviour: no known_hosts file is created.
    assert not known_hosts_path(settings).exists()


def test_tofu_learns_and_persists(tmp_path, server) -> None:
    settings = _settings(tmp_path, "tofu")
    kh = known_hosts_path(settings)
    assert not kh.exists()
    _connect("127.0.0.1", server.port, settings)
    assert kh.exists()
    # The persisted store now knows this host:port.
    loaded = paramiko.HostKeys(str(kh))
    assert loaded.lookup(f"[127.0.0.1]:{server.port}") is not None


def test_tofu_same_key_reconnect_succeeds(tmp_path, server) -> None:
    settings = _settings(tmp_path, "tofu")
    _connect("127.0.0.1", server.port, settings)  # learn
    # Reconnect with the SAME server key — no exception.
    _connect("127.0.0.1", server.port, settings)


def test_tofu_changed_key_is_rejected(tmp_path, server) -> None:
    settings = _settings(tmp_path, "tofu")
    _connect("127.0.0.1", server.port, settings)  # learn key A + persist
    # The device "re-keys" (or a MITM swaps in) a different host key on the
    # same host:port.  TOFU must now refuse.
    server.set_host_key(paramiko.RSAKey.generate(2048))
    with pytest.raises(paramiko.BadHostKeyException):
        _connect("127.0.0.1", server.port, settings)


def test_reject_mode_refuses_unknown_host(tmp_path, server) -> None:
    settings = _settings(tmp_path, "reject")
    # No prior known_hosts entry → RejectPolicy refuses the connection.
    with pytest.raises(paramiko.SSHException):
        _connect("127.0.0.1", server.port, settings)


# ---------------------------------------------------------------------------
# Netmiko host-key pre-flight (``verify_host_key``).  Netmiko itself can't
# persist a learned key, so the collector runs this auth-less paramiko
# pre-flight first; it must show the same TOFU learn/persist, reconnect-
# stable, changed-key-rejected, and reject-unknown behaviour, and write a
# store the Paramiko collector can read (one pinned key per device, either
# collector).
# ---------------------------------------------------------------------------


def test_verify_auto_add_is_noop(tmp_path, server) -> None:
    settings = _settings(tmp_path, "auto_add")
    verify_host_key("127.0.0.1", server.port, settings)
    assert not known_hosts_path(settings).exists()


def test_verify_tofu_learns_and_persists(tmp_path, server) -> None:
    settings = _settings(tmp_path, "tofu")
    kh = known_hosts_path(settings)
    assert not kh.exists()
    verify_host_key("127.0.0.1", server.port, settings)
    assert kh.exists()
    loaded = paramiko.HostKeys(str(kh))
    assert loaded.lookup(f"[127.0.0.1]:{server.port}") is not None


def test_verify_tofu_same_key_reconnect_succeeds(tmp_path, server) -> None:
    settings = _settings(tmp_path, "tofu")
    verify_host_key("127.0.0.1", server.port, settings)  # learn
    verify_host_key("127.0.0.1", server.port, settings)  # same key — no raise


def test_verify_tofu_changed_key_is_rejected(tmp_path, server) -> None:
    settings = _settings(tmp_path, "tofu")
    verify_host_key("127.0.0.1", server.port, settings)  # learn key A
    server.set_host_key(paramiko.RSAKey.generate(2048))  # device re-keys / MITM
    with pytest.raises(paramiko.BadHostKeyException):
        verify_host_key("127.0.0.1", server.port, settings)


def test_verify_reject_refuses_unknown_host(tmp_path, server) -> None:
    settings = _settings(tmp_path, "reject")
    with pytest.raises(paramiko.SSHException):
        verify_host_key("127.0.0.1", server.port, settings)


def test_verify_store_is_interoperable_with_paramiko_collector(tmp_path, server) -> None:
    """A key pinned via the Netmiko pre-flight is trusted by the Paramiko
    collector against the SAME store — proving the file format interop that
    lets one device share a single pinned key across both collectors."""
    verify_host_key("127.0.0.1", server.port, _settings(tmp_path, "tofu"))  # learn
    # Paramiko collector in REJECT mode (same data_dir) now connects, because
    # the host is already known from the Netmiko-side pre-flight.
    _connect("127.0.0.1", server.port, _settings(tmp_path, "reject"))

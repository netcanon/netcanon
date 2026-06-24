"""SSH host-key verification policy for the backup collectors (review #11).

Historically both collectors used paramiko ``AutoAddPolicy`` with no
persistence — every host key was trusted unconditionally, so a man in the
middle on the management path could harvest the SSH password + Cisco enable
secret.  This module centralises an opt-in policy, selected by
``Settings.ssh_host_key_checking``:

* ``auto_add`` (default) — legacy behaviour, no persistence, no change.
* ``tofu`` — trust-on-first-use *with persistence* under
  ``{effective_data_dir}/known_hosts``; a later changed key is rejected.
* ``reject`` — only hosts already in the store may be connected to.

Both collectors share the persisted ``{effective_data_dir}/known_hosts``
store.  The Paramiko shell collector applies the policy inline
(:func:`apply_paramiko_policy` + :func:`persist_paramiko_host_keys`).
Netmiko exposes no TOFU-*persistence* hook, so the Netmiko collector runs
an auth-less paramiko *pre-flight* (:func:`verify_host_key`) that reads the
remote host key, applies the same TOFU / reject policy against the store,
and then lets Netmiko connect ``ssh_strict`` against the now-populated
store (:func:`netmiko_host_key_params`) — NOT the operator's OS
``~/.ssh/known_hosts``.  See SECURITY.md.

Default-off (``auto_add``) means existing deployments see no behaviour
change; the helpers below early-return for that mode.
"""

from __future__ import annotations

import logging
import socket
import threading
from pathlib import Path

import paramiko

from ..config import Settings

logger = logging.getLogger(__name__)

#: Serialises read + write of the shared ``known_hosts`` store.  Backups run
#: in a ThreadPoolExecutor (up to 10 workers), so two concurrent TOFU
#: ``save_host_keys`` calls could otherwise interleave and corrupt the file.
_KNOWN_HOSTS_LOCK = threading.Lock()

#: Socket + key-exchange timeout (seconds) for the Netmiko host-key
#: pre-flight (:func:`verify_host_key`).  Short — it does a single KEX and
#: closes; the real Netmiko connect that follows carries the full timeout.
_PREFLIGHT_TIMEOUT = 30


def known_hosts_path(settings: Settings) -> Path:
    """Location of the persisted known-hosts store (Paramiko collector)."""
    return settings.effective_data_dir / "known_hosts"


def apply_paramiko_policy(client: paramiko.SSHClient, settings: Settings) -> None:
    """Configure *client*'s host-key loading + missing-key policy.

    For ``tofu`` / ``reject`` the persisted store is loaded first (so a
    changed key trips paramiko's native ``BadHostKeyException`` regardless of
    the missing-key policy).  ``tofu`` then auto-adds unknown hosts;
    ``reject`` refuses them.  ``auto_add`` keeps the legacy trust-anything
    behaviour with no store.
    """
    mode = settings.ssh_host_key_checking
    if mode == "auto_add":
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        return

    kh = known_hosts_path(settings)
    with _KNOWN_HOSTS_LOCK:
        if kh.exists():
            try:
                # load_host_keys also marks this file as the save target.
                client.load_host_keys(str(kh))
            except OSError as exc:  # race: file vanished/locked since exists()
                logger.warning("Could not read known_hosts at %s: %s", kh, exc)

    client.set_missing_host_key_policy(
        paramiko.AutoAddPolicy() if mode == "tofu" else paramiko.RejectPolicy()
    )


def persist_paramiko_host_keys(
    client: paramiko.SSHClient, settings: Settings
) -> None:
    """Persist newly-learned host keys after a successful ``tofu`` connect.

    No-op for ``auto_add`` (no store) and ``reject`` (the store is operator-
    curated; we never extend it implicitly).
    """
    if settings.ssh_host_key_checking != "tofu":
        return
    kh = known_hosts_path(settings)
    try:
        with _KNOWN_HOSTS_LOCK:
            kh.parent.mkdir(parents=True, exist_ok=True)
            client.save_host_keys(str(kh))
    except OSError as exc:  # pragma: no cover - disk/permission edge
        logger.warning("Could not persist known_hosts at %s: %s", kh, exc)


def netmiko_host_key_params(settings: Settings) -> dict:
    """Return the Netmiko ConnectHandler kwargs for the host-key policy.

    ``auto_add`` → ``{}`` (Netmiko's default auto-add).  ``tofu`` /
    ``reject`` → strict checking against the netcanon-managed
    ``{effective_data_dir}/known_hosts`` store (NOT the operator's OS
    ``~/.ssh/known_hosts``).  The :func:`verify_host_key` pre-flight runs
    first and populates that store with the trust-on-first-use decision, so
    by the time Netmiko loads it ``ssh_strict`` the verified key is present;
    a changed key was already rejected by the pre-flight.
    """
    if settings.ssh_host_key_checking == "auto_add":
        return {}
    return {
        "alt_host_keys": True,
        "alt_key_file": str(known_hosts_path(settings)),
        "ssh_strict": True,
    }


def verify_host_key(host: str, port: int, settings: Settings) -> None:
    """Trust-on-first-use host-key pre-flight for the Netmiko collector.

    Netmiko exposes no TOFU-*persistence* hook (``ssh_strict`` only checks
    against an already-populated store and never saves a newly-learned
    key), so this opens a short, **auth-less** paramiko transport to
    ``host:port`` purely to read the remote host key — no credentials are
    sent — applies the same policy + persisted
    ``{effective_data_dir}/known_hosts`` store the Paramiko collector uses,
    and returns so Netmiko can connect ``ssh_strict`` against that store
    (see :func:`netmiko_host_key_params`).

    * ``auto_add`` — no-op (legacy trust-anything; nothing to verify).
    * ``tofu``     — unknown host: learn + persist the key; known host:
                     return iff the key is unchanged, else raise.
    * ``reject``   — known + unchanged only; unknown or changed → raise.

    The store is paramiko ``HostKeys`` format, identical to what the
    Paramiko collector's ``save_host_keys`` writes, so a device backed up
    over either collector shares one pinned key.

    Raises:
        paramiko.BadHostKeyException: the host is pinned to a different key
            (changed key / possible MITM).
        paramiko.SSHException: ``reject`` mode and the host is unknown, or
            the transport could not complete key exchange.
    """
    mode = settings.ssh_host_key_checking
    if mode == "auto_add":
        return

    # paramiko (and OpenSSH) key non-standard ports as ``[host]:port``.
    name = host if port == 22 else f"[{host}]:{port}"
    kh = known_hosts_path(settings)

    # Read the remote host key over an auth-less transport: ``start_client``
    # completes the key exchange (which yields the server's host key) before
    # any authentication, so the pre-flight never transmits credentials.
    sock = socket.create_connection((host, port), timeout=_PREFLIGHT_TIMEOUT)
    transport = paramiko.Transport(sock)
    try:
        transport.start_client(timeout=_PREFLIGHT_TIMEOUT)
        remote_key = transport.get_remote_server_key()
    finally:
        transport.close()
        try:
            sock.close()
        except OSError:
            pass

    with _KNOWN_HOSTS_LOCK:
        known = paramiko.HostKeys()
        if kh.exists():
            try:
                known.load(str(kh))
            except OSError as exc:  # race: file vanished/locked since exists()
                logger.warning("Could not read known_hosts at %s: %s", kh, exc)

        if known.check(name, remote_key):
            return  # known host, key unchanged

        entry = known.lookup(name)
        if entry is not None:
            # Host is pinned to a DIFFERENT key — changed key / MITM.
            expected = next(iter(entry.values()))
            raise paramiko.BadHostKeyException(name, remote_key, expected)

        # Unknown host.
        if mode == "reject":
            raise paramiko.SSHException(
                f"reject: host {name} is not in {kh} and "
                f"ssh_host_key_checking='reject' forbids learning it."
            )

        # tofu — learn + persist for next time.
        known.add(name, remote_key.get_name(), remote_key)
        try:
            kh.parent.mkdir(parents=True, exist_ok=True)
            known.save(str(kh))
        except OSError as exc:  # pragma: no cover - disk/permission edge
            logger.warning("Could not persist known_hosts at %s: %s", kh, exc)


def host_key_warning_reason(settings: Settings) -> str | None:
    """Return a startup-warning message when the host-key policy is the
    insecure ``auto_add`` default, else ``None``.

    ``auto_add`` trusts any SSH host key on every connect with no
    persistence, so a man-in-the-middle on the management path could
    harvest the SSH password + enable secret.  The default stays
    ``auto_add`` for backward-compatibility (flipping it is a deliberate,
    separately-gated change); ``tofu`` now does real trust-on-first-use
    persistence on BOTH collectors — the Paramiko collector inline and the
    Netmiko collector via the :func:`verify_host_key` pre-flight — so the
    historical "Netmiko can't persist" blocker is gone.  A running server
    should surface the insecure default once at startup so it is a
    conscious choice (mirrors :func:`bind_refusal_reason`).  See SECURITY.md.
    """
    if settings.ssh_host_key_checking != "auto_add":
        return None
    return (
        "SSH host-key checking is 'auto_add' (the default): the backup "
        "collectors trust any device host key on first connect with no "
        "persistence, so a man-in-the-middle on the management path could "
        "capture SSH/enable credentials. Set NETCANON_SSH_HOST_KEY_CHECKING="
        "'tofu' to pin each device's key on first use — both the Paramiko "
        "and Netmiko collectors persist learned keys to the netcanon "
        "known_hosts store and reject a later changed key. See SECURITY.md."
    )

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

The Paramiko shell collector gets the full TOFU store; Netmiko has no
custom-known-hosts / persist API, so for ``tofu`` / ``reject`` it is mapped
to strict checking against the operator's OS ``~/.ssh/known_hosts``
(``system_host_keys=True`` + ``ssh_strict=True``).  See SECURITY.md.

Default-off (``auto_add``) means existing deployments see no behaviour
change; the helpers below early-return for that mode.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import paramiko

from ..config import Settings

logger = logging.getLogger(__name__)

#: Serialises read + write of the shared ``known_hosts`` store.  Backups run
#: in a ThreadPoolExecutor (up to 10 workers), so two concurrent TOFU
#: ``save_host_keys`` calls could otherwise interleave and corrupt the file.
_KNOWN_HOSTS_LOCK = threading.Lock()


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
    ``reject`` → strict checking against the OS ``~/.ssh/known_hosts``
    (Netmiko exposes no custom-store / TOFU-persist API, so both strict
    modes collapse to the same OS-known_hosts enforcement).
    """
    if settings.ssh_host_key_checking == "auto_add":
        return {}
    return {"system_host_keys": True, "ssh_strict": True}


def host_key_warning_reason(settings: Settings) -> str | None:
    """Return a startup-warning message when the host-key policy is the
    insecure ``auto_add`` default, else ``None``.

    ``auto_add`` trusts any SSH host key on every connect with no
    persistence, so a man-in-the-middle on the management path could
    harvest the SSH password + enable secret.  The default stays
    ``auto_add`` for backward-compatibility — and because the strict
    ``tofu`` / ``reject`` modes require the *Netmiko* collector's targets
    to be pre-seeded in the operator's OS ``~/.ssh/known_hosts`` (Netmiko
    exposes no TOFU-persist API), so flipping the default would break
    first-run backups of unknown devices.  But a running server should at
    least surface the posture once at startup, so it is a conscious choice
    rather than a silent default (mirrors :func:`bind_refusal_reason`).
    See SECURITY.md.
    """
    if settings.ssh_host_key_checking != "auto_add":
        return None
    return (
        "SSH host-key checking is 'auto_add' (the default): the backup "
        "collectors trust any device host key on first connect with no "
        "persistence, so a man-in-the-middle on the management path could "
        "capture SSH/enable credentials. Set NETCANON_SSH_HOST_KEY_CHECKING="
        "'tofu' to pin keys on first use (the Paramiko shell collector "
        "persists them; the Netmiko collector then requires targets to "
        "already be in the operator's ~/.ssh/known_hosts). See SECURITY.md."
    )

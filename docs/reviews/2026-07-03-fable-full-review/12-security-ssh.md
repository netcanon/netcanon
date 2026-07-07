# 12 — Security: SSH backup & network egress

Lens: `netcanon/collectors/` (paramiko / netmiko), TOFU host-key handling,
the opt-in egress allow-list (`netcanon/services/egress.py`), and the device
definitions (command sequences sent to devices, incl. the provisional
nxos/iosxr/aoscx/vyos defs).

**Verdict: GO-WITH-FIXES.** The core posture is sound and matches what prior
passes established as known-good (TOFU default, RejectPolicy for `reject`,
paramiko native `BadHostKeyException` for changed keys, egress guard at the
entry points, no credential logging, static command sequences, fail-closed
absolute read cap on the main collect). No command injection, no credential
leak, no host-key-verification bypass in the normal path. But three concrete
implementation gaps that prior passes did not surface:

- **MAJOR** — `ParamikoShellCollector._drain` has **no absolute time / size cap**
  (unbounded read + unbounded memory from a hostile/slow device).
- **MINOR** — egress allow-list lets the unspecified address `0.0.0.0` / `::`
  through, which reaches loopback on connect (Linux/Windows) — a loopback-block
  bypass.
- **MINOR** — the `known_hosts` write race the `_KNOWN_HOSTS_LOCK` is documented
  to prevent is still reachable: paramiko's `AutoAddPolicy` saves the store
  *inside* `client.connect()`, which runs **outside** the lock.

No new findings against the provisional device defs — their command sequences
are safe.

---

## MAJOR-1 — `_drain` is an unbounded read loop (DoS: hung worker + unbounded memory)

`netcanon/collectors/paramiko_collector.py:342-361`

```python
def _drain(self, shell, timeout: float = 0.5) -> str:
    buf = ""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if shell.recv_ready():
            chunk = shell.recv(65536).decode("utf-8", errors="replace")
            buf += chunk
            deadline = time.monotonic() + timeout  # reset on new data  <-- resets forever
        else:
            time.sleep(0.05)
    return buf
```

The deadline is **reset on every chunk** and there is **no absolute cap**. A
device that emits at least one byte every < 0.5 s (an infinite login banner,
`yes`-style flood, or an MITM injecting a stream) makes `_drain` loop forever
while `buf += chunk` grows without bound → the backup worker thread hangs
permanently and consumes unbounded memory.

`_drain` runs **before any config command is sent** and on several other legs:
`initial = self._drain(shell)` right after connect (collect line 196; probe line
299), after the OPNsense menu (207/311), after every pre-command (213), the
final pre-collect drain (217), and after every post-command (230). So the hang
is reachable on the very first drain, before the collector has even decided what
to run.

This is asymmetric with the sibling `_collect_output` /
`_collect_probe_output`, which were **explicitly hardened to fail closed**
against exactly this (audit 276eaeb T0-3): they set `deadline =
time.monotonic() + _MAX_SECONDS` **once** (not reset on data) and raise
`TimeoutError` if the stream never settles (lines 418, 448-459, 481). `_drain`
never got that treatment.

Impact: backups run in a bounded pool (`MAX_BACKUP_CONCURRENCY=10`) further
capped by the process-wide `_GLOBAL_LIMITER`. A handful of malicious/broken
OPNsense-strategy targets (or one target reached N times via schedules) can
permanently pin every worker permit → all backups stall (availability), plus
OOM from the growing `buf`. The `paramiko_shell` strategy is the only affected
collector; the netmiko path is bounded by netmiko's own `read_timeout`.

Mitigating context: netcanon is operator-trust-anchor (operators point it at
devices they trust), and TOFU pins the host key, so an MITM-injected flood only
works on first-connect or an already-compromised device. Still a real
unbounded-resource bug and a regression of the stated fail-closed intent.

Fix: give `_drain` an absolute wall-clock ceiling and/or a `buf` size cap
independent of the idle-reset (mirror `_MAX_SECONDS`), and stop resetting the
outer deadline — reset only an *idle* timer, not the absolute one.

---

## MINOR-1 — Egress allow-list lets `0.0.0.0` / `::` through → loopback bypass

`netcanon/services/egress.py:38-51` (`_is_blocked_ip`)

The guard blocks only `is_loopback` or `is_link_local` (plus IPv4-mapped IPv6).
The **unspecified** address is neither, so it passes:

Probe (verified locally):
```
'0.0.0.0'          parsed 0.0.0.0  blocked=False  loopback=False linklocal=False unspec=True
'::'               parsed ::       blocked=False  loopback=False linklocal=False unspec=True
'127.0.0.1'        blocked=True
'169.254.169.254'  blocked=True
'::ffff:127.0.0.1' blocked=True
```

`models/validators.py:validate_host` accepts `0.0.0.0` and `::` (valid IPs), so
they flow straight through `assert_egress_allowed` unblocked. On Linux (and
Windows) a TCP `connect()` to `0.0.0.0` is serviced by the kernel as
`127.0.0.1`, so an operator/caller can reach a loopback SSH service on the
backup host even though the guard's documented purpose (module docstring lines
1-23, and `config.py:178-187`) is to block loopback. The high-value metadata
endpoint `169.254.169.254` stays blocked (it is link-local), so this is not a
metadata-SSRF hole — the residual reach is loopback-only, hence minor. It is
still an undocumented gap in a guard framed as "loopback + link-local blocked."

Note: `ipaddress.ip_address` rejects the ambiguous decimal/octal integer forms
(`2130706433`, `017700000001`) so those classic SSRF encodings are **not** a
bypass here — good.

Fix: also reject `ip.is_unspecified` (and arguably `is_multicast` /
`is_reserved`, which are never valid SSH targets) in `_is_blocked_ip`.

Secondary (already acknowledged in-code, not a separate finding): the hostname
branch uses `socket.getaddrinfo(host, None)` with **no timeout**
(`egress.py:85`); a slow DNS answer occupies the calling thread. The schedule
path offloads this to a worker thread (`schedules.py:212-215`) and the docstring
calls it out, so it is bounded-ish. Consider a resolver timeout if hardening.

---

## MINOR-2 — `known_hosts` corruption race: `AutoAddPolicy` saves outside `_KNOWN_HOSTS_LOCK`

`netcanon/collectors/hostkey.py:43-46, 59-84` + `paramiko_collector.py:166-191, 264-286`

`_KNOWN_HOSTS_LOCK` is documented (hostkey.py:43-46) to exist specifically so
that "two concurrent TOFU `save_host_keys` calls could otherwise interleave and
corrupt the file." But in the Paramiko shell collector the lock only wraps
`apply_paramiko_policy`'s `load_host_keys` and the explicit
`persist_paramiko_host_keys` save. It does **not** wrap the *other* writer:

In `tofu` mode `apply_paramiko_policy` calls `client.load_host_keys(kh)`, which
sets `_host_keys_filename`. On a first connect to an unknown host, paramiko's
`AutoAddPolicy.missing_host_key` then calls
`client.save_host_keys(client._host_keys_filename)` — verified in paramiko 4.0.0:

```
AutoAddPolicy.missing_host_key: ... if client._host_keys_filename is not None:
                                         client.save_host_keys(client._host_keys_filename)
SSHClient.save_host_keys:  ... with open(filename, "w") as f:  # truncate, non-atomic, line-by-line
```

That save fires **inside `client.connect(...)`** (paramiko_collector.py:181 and
:277), which is called **outside** `_KNOWN_HOSTS_LOCK`. `save_host_keys` opens
with `"w"` (truncate) and writes line-by-line — not atomic (no temp+rename).
So two workers doing first-time TOFU connects concurrently via the
`paramiko_shell` strategy (e.g. several OPNsense devices in one job) can
interleave truncate+write and corrupt/short-write the shared store. The
subsequent locked `persist_paramiko_host_keys` save (line 191/286) can also race
the unlocked AutoAddPolicy save of another worker — the lock only helps if
*both* writers take it, and the AutoAddPolicy writer never does.

Security tail: a corrupted store that drops a host's pinned line causes the next
connect to re-learn (re-TOFU) whatever key is presented — reopening the
first-use trust window that TOFU is meant to close after connect #1. Also
produces spurious `BadHostKeyException` false-positives (failing good backups).
Narrow trigger (concurrent first-time TOFU via `paramiko_shell` only; the
netmiko path uses `verify_host_key` whose `HostKeys.save` *is* under the lock
and connects `ssh_strict` with no auto-save), hence minor.

Fix options: set the missing-key policy to `RejectPolicy` for `tofu` and rely
solely on the explicit locked `persist_paramiko_host_keys` (so paramiko never
auto-saves), or perform the whole `connect()` under `_KNOWN_HOSTS_LOCK` for the
first-connect case, or write via an atomic temp+rename helper under the lock.

---

## Areas checked — clean (no findings)

- **Command injection into device CLI.** All commands sent to devices come from
  static definition YAML (`commands.pre/config/post`), never from
  user/request-controlled data. The only dynamic shell writes are
  `shell.send(f"{cmd}\n")` over those static strings and the fixed `"8\n"`
  menu-dismiss (paramiko_collector.py:205/220/226/309/316). Username/password
  are passed to `client.connect(...)` / `ConnectHandler(**params)` as auth
  parameters — never interpolated into a command line. `host` is validated by
  `validate_host` (IP or RFC-1123 hostname) before use.
- **Host-key verification.** TOFU default (`config.py:224`). `apply_paramiko_policy`
  loads the store first so paramiko's native `BadHostKeyException` fires on a
  changed key regardless of the missing-key policy; `reject` uses `RejectPolicy`.
  `verify_host_key` (netmiko pre-flight) reads the server key over an
  **auth-less** transport (`start_client` completes KEX before auth, so no
  credentials are sent — hostkey.py:161-174), applies TOFU/reject against the
  netcanon-managed store, then netmiko connects `ssh_strict`. First-use trust is
  inherent to TOFU and documented — not a bug.
- **AutoAddPolicy misuse.** `AutoAddPolicy` is used *only* for the explicit
  `auto_add` opt-out (documented, startup warning via `host_key_warning_reason`)
  and as the missing-key handler under `tofu` *after* the store is loaded (so
  changed keys still reject). No unconditional trust-anything in the default
  posture. (The `tofu` AutoAddPolicy path is the source of MINOR-2's save race,
  not a verification bypass.)
- **Allow-list bypass via IP encodings.** IPv4-mapped IPv6 (`::ffff:127.0.0.1`,
  `::ffff:169.254.169.254`) are unwrapped and blocked (egress.py:50-51);
  decimal/octal integer forms are rejected by `ipaddress`. The only encoding gap
  is the unspecified address (MINOR-1). DNS-rebinding at connect time is a
  pre-existing documented limitation (egress.py:11-17) — not re-litigated.
- **Credential exposure during connection setup.** Passwords are `SecretStr`;
  only `device.credentials.username` is logged, at DEBUG
  (netmiko_collector.py:104-109; paramiko_collector.py:175-180). No password /
  enable-secret in any log line. `netcanon/api/_errors.py` deliberately
  suppresses filesystem paths and multi-line auth troubleshooting blocks, and
  only echoes `str(exc)` for paramiko `SSHException` / in-house `ValueError`
  (device-banner text at worst — no credentials). No session_log enabled.
- **Read/timeout DoS on the netmiko path.** Bounded by netmiko `conn_timeout=30`
  and `read_timeout=120`/`30` (netmiko_collector.py:88,127,203); the pre-flight
  uses `_PREFLIGHT_TIMEOUT=30` (hostkey.py:164-167). The main paramiko collect
  fails closed at `_MAX_SECONDS=120` (paramiko_collector.py:418,448-459). Only
  `_drain` is unbounded (MAJOR-1).
- **Concurrency ceilings.** Per-job pool ≤ `MAX_BACKUP_CONCURRENCY` and the
  process-wide `_GLOBAL_LIMITER` cap the SUM of in-flight collections; a worker
  without a permit stays `queued` (back-pressure), never a failure.
- **Provisional device defs (nxos / iosxr / aoscx / vyos).** All run a
  read-only capture (`show running-config`, or vyos `show configuration
  commands`) with **empty** `pre`/`post`, `needs_enable: false`, and
  `cisco_more_paging: false`. No config-mutating or state-changing commands. The
  Fortigate def *does* change device state in `pre` (`config system console` /
  `set output standard`) but restores it in `post` (`set output more`) — a
  legitimate, low-risk pager toggle, and static. No unsafe sequences.

## Observation (out-of-lens, functional — flagged for the codec/UX lenses)

`connection.cisco_more_paging` is declared in every YAML and in `schema.py` but
is **never read by any collector** (`grep` shows only YAML/docs/schema hits — no
Python consumer in `netcanon/collectors/`). The netmiko collector relies on
netmiko's per-driver paging handling; the flag is effectively inert config.
This is not a security issue (an undismissed `--More--` would just time out and
fail closed), but the memory note "keep `--More--` space injection" assumes this
flag drives behaviour, and it does not. Worth a functional-lens check that the
Cisco/Arista/AOS-S paging is actually handled by the driver as intended.

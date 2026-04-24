# Collectors

Collectors are responsible for opening an SSH session, running the config
command sequence from a device definition, and returning the raw output as a
string.

## Architecture

```
netconfig/collectors/
├── base.py               BaseCollector ABC + get_collector() factory
├── netmiko_collector.py  Netmiko-based collector (most vendors)
├── paramiko_collector.py Raw Paramiko shell collector (OPNsense, etc.)
└── probe.py              Pure-function probe-output parser (parse_probe_output)
```

## The Factory

`get_collector(definition)` in `base.py` is the **single entry point** for
collector instantiation.  The backup route calls this function — it never
imports concrete collector classes directly.  This design means tests only
need to patch one symbol:

```python
# In tests:
monkeypatch.setattr(
    "netconfig.api.routes.backups.get_collector",
    lambda _: FakeCollector(),
)
```

## Strategies

### `netmiko` — `NetmikoCollector`

Uses Netmiko's `ConnectHandler` context manager.  Handles:

- Enable mode (`needs_enable: true`): detects `>` prompt and issues `enable`.
- Pre/post commands from `commands.pre` / `commands.post`.
- Main config command via `send_command(..., read_timeout=120)`.
- `--More--` paging via `cisco_more_paging: true` (space-injection, not
  `terminal length 0` — see note below).

Supported `netmiko_device_type` values (non-exhaustive):

| Vendor      | `netmiko_device_type` |
|-------------|----------------------|
| Cisco IOS-XE | `cisco_xe` |
| Fortigate FortiOS | `fortinet` |
| MikroTik RouterOS | `mikrotik_routeros` |

> **Why no `terminal length 0`?**  This command is unreliable on some IOS-XE
> versions and was deliberately removed.  The space-injection approach
> (`cisco_more_paging: true`) is used instead.

### `paramiko_shell` — `ParamikoShellCollector`

Opens a raw interactive PTY shell via `paramiko.SSHClient`.  Replicates the
PowerShell idle-detection heuristic from the original script:

- Poll for output every 200 ms.
- After 15 consecutive idle polls (~3 s of silence) the command is considered
  complete.
- Handles OPNsense console menu automatically when
  `connection.opnsense_shell_menu: true`.
- Strips the echoed command from the head of the collected buffer
  (via `_strip_command_echo`).  PTY shells echo the bytes the caller
  sent — without this strip every paramiko-shell backup would land
  on disk with a literal command-line preamble (e.g.
  `cat /conf/config.xml\r\r\n`) before the actual output.  Netmiko
  handles the same issue via `strip_command=True`; the raw paramiko
  path has to do it explicitly.

Use this strategy for devices that need custom session orchestration that
Netmiko cannot express (numbered menus, non-standard prompts, etc.).

## Adding a New Strategy

1. Create `netconfig/collectors/<name>_collector.py`.
2. Subclass `BaseCollector` and implement `collect(device, definition) -> str`.
3. Add a branch to `get_collector()` in `base.py`:

   ```python
   if strategy == "my_strategy":
       from .my_collector import MyCollector
       return MyCollector()
   ```

4. Add `"my_strategy"` to the `Literal` type in `CollectorConfig.strategy`
   (`netconfig/definitions/schema.py`).
5. Write a YAML definition with `collector.strategy: my_strategy` and add
   tests under `tests/unit/` and `tests/integration/`.

## Probe phase

Collectors expose an optional `probe(device, definition) -> dict[str, str]`
method for pre-backup fact extraction.  When the definition declares
`probe.command` (a "show version" style lookup) plus a `probe.patterns`
regex map, the backup route runs the probe BEFORE the main collect and
uses the result for two purposes:

1. Populates `DeviceProfile.detected_facts` — visible in the device-edit
   form's read-only panel so operators can see what the device actually
   reports (OS version, model, firmware build).
2. Feeds `DefinitionLoader.resolve(type_key, os_version, model)` so
   version/model overlays get picked automatically when operator pins
   are absent.

**Default behaviour is no-op:** `BaseCollector.probe` returns `{}` so
collectors that haven't wired probing support keep working unchanged.
Both `NetmikoCollector` and `ParamikoShellCollector` ship concrete
overrides — the Paramiko variant handles the OPNsense console menu
opt-in and uses tighter idle + timeout bounds suitable for small
"show version" style output.

Probe failure is NEVER fatal:

- Connection error → log WARNING, return `{}`, continue with the
  family-base definition.
- `probe.command` empty → return `{}`.
- Pattern doesn't match → key is absent in the result dict.
- Malformed regex → individual pattern is skipped; others still work.

Output parsing lives in `probe.py` (pure function) — unit-testable
without any session mocking; see `tests/unit/test_probe_parser.py`.

## Testing

Integration tests mock `get_collector` via `unittest.mock.patch` so no real
SSH connections occur.  **Do not patch `ConnectHandler` or
`paramiko.SSHClient` directly** (per CLAUDE.md hard rule); patch
`netconfig.api.routes.backups.get_collector` and inject a `FakeCollector`
that returns canned output.  The probe-parser lives in its own module and
IS unit-testable in isolation (`tests/unit/test_probe_parser.py`) without
touching any transport layer.

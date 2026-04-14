# Collectors

Collectors are responsible for opening an SSH session, running the config
command sequence from a device definition, and returning the raw output as a
string.

## Architecture

```
netconfig/collectors/
├── base.py               BaseCollector ABC + get_collector() factory
├── netmiko_collector.py  Netmiko-based collector (most vendors)
└── paramiko_collector.py Raw Paramiko shell collector (OPNsense, etc.)
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

## Testing

Integration tests mock `get_collector` via `unittest.mock.patch` so no real
SSH connections occur.  Unit tests for individual collector classes should use
`unittest.mock.patch` on the underlying library (`ConnectHandler` for Netmiko,
`paramiko.SSHClient` for Paramiko) and test the sequence of calls made.

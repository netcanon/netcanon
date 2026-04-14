# Device Definition Files

YAML files under this directory describe one device family each.  The Python
loader validates every file against a Pydantic schema at startup; malformed or
incomplete files emit a warning and are silently skipped.

## Directory Layout

```
definitions/
  <vendor>/
    <os>/
      <version>.yaml      (e.g. 17.x.yaml)
      models/
        <model>.yaml      (optional high-priority model-specific overrides)
```

The path is purely cosmetic — the loader uses recursive glob (`*.yaml`) and
ignores directory names.  Use the tree to keep things organised.

## Full Schema Reference

```yaml
# ── Identity ────────────────────────────────────────────────────────────────
vendor: Cisco                      # Human-readable vendor name (shown in UI)
os: IOS-XE                         # OS or firmware name
version_match: "^17\\."            # Regex matched against detected version (future)
type_key: Cisco                    # Lookup key; must be unique (priority wins on collision)
priority: 10                       # Higher values override lower on type_key collision

# ── Output file ─────────────────────────────────────────────────────────────
file_extension: cfg                # Extension without leading dot (cfg / xml / rsc / …)

# ── SSH session behaviour ────────────────────────────────────────────────────
connection:
  needs_enable: false              # Send 'enable' if banner shows '>' prompt
  handle_paging: false             # Inject SPACE to dismiss --More-- mid-stream
  needs_shell_menu: false          # Detect + dismiss a numbered console menu (OPNsense)

# ── Command sequence ─────────────────────────────────────────────────────────
commands:
  pre:                             # Commands drained before the config command
    - "config system console"
    - "set output standard"
    - "end"
  config: "show running-config"   # The command whose output IS the config
  post:                            # Commands run after collection (restore state)
    - "config system console"
    - "set output more"
    - "end"

# ── Prompt patterns ──────────────────────────────────────────────────────────
prompts:
  trailing:                        # Regex list; trailing lines matching any are stripped
    - '^\S+[#>]\s*$'               # Router# or Router>
    - '^\S+\s+[#]\s*$'            # FortiGate # (space before #)

# ── Collector strategy ───────────────────────────────────────────────────────
collector:
  strategy: netmiko                # "netmiko" | "paramiko_shell"
  netmiko_device_type: cisco_xe   # Required when strategy=netmiko

# ── Notes (shown in UI, document quirks here) ────────────────────────────────
notes: >
  Free-text.  Document any known device quirks, version gotchas, or
  reasons for non-default settings.
```

## Collector Strategies

| Strategy         | When to use |
|------------------|-------------|
| `netmiko`        | Any device Netmiko supports natively.  Set `netmiko_device_type` to the Netmiko device-type string. |
| `paramiko_shell` | Devices that need raw interactive-shell orchestration (e.g. OPNsense, which presents a numbered console menu before a shell prompt). |

## Priority and Override Resolution

The loader uses a two-pass algorithm:

1. **Parse all files** — validate each `*.yaml` against the schema; skip failures.
2. **Sort by priority ascending** — apply definitions in order; higher-priority
   definitions are applied last and therefore win on `type_key` collision.

This allows a base definition at `priority: 0` to serve as a sensible default
while a model-specific file at `priority: 20` can override individual fields
without duplicating the entire definition.

```
cisco/ios-xe/base.yaml        priority: 0   ← loaded first, forms the baseline
cisco/ios-xe/17.x.yaml        priority: 10  ← overrides base for IOS-XE 17
cisco/ios-xe/models/ASR1K.yaml priority: 20 ← overrides both for ASR1000 series
```

## Vendor-Specific Notes

### Cisco IOS-XE
- `connection.needs_enable: true` — SSH often lands in user-exec mode.
- `connection.handle_paging: true` — **`terminal length 0` is deliberately
  avoided**; instead, the collector injects a SPACE character to dismiss each
  `--More--` prompt mid-stream.  This is more reliable across IOS versions.

### Fortigate FortiOS
- Paging is suppressed with `config system console / set output standard`
  and restored with `set output more` in `commands.post`.
- Prompt has a space before `#`: `hostname # ` — pattern must account for it.

### OPNsense
- `connection.needs_shell_menu: true` — SSH lands at a numbered menu;
  the paramiko_shell collector detects `"Enter an option:"` and sends `"8"`.
- `collector.strategy: paramiko_shell` — Netmiko does not support OPNsense.

### MikroTik RouterOS
- `/export verbose` includes all defaults, which is preferable for a full
  backup and future diff/translation work.

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
priority: 10                       # Higher values override lower within the family-base set

# ── Overlay qualifiers (layered definitions) ────────────────────────────────
# Leave both unset (None) for a family-base entry.  Setting either makes
# this file an "overlay" — it is not visible in the legacy family-base
# lookup map and is reachable only via DefinitionLoader.resolve().
os_version:                        # Pin to a specific OS version (e.g. "17.12")
model:                             # Pin to a specific hardware model (e.g. "C9300-48P")

# ── Output file ─────────────────────────────────────────────────────────────
file_extension: cfg                # Extension without leading dot (cfg / xml / rsc / …)

# ── SSH session behaviour ────────────────────────────────────────────────────
connection:
  needs_enable: false              # Send 'enable' if banner shows '>' prompt
  cisco_more_paging: false         # Cisco only: inject SPACE to dismiss --More-- mid-stream
  opnsense_shell_menu: false       # OPNsense only: detect + dismiss the numbered console menu

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

Two lookup surfaces exist, both served by the same definition tree:

### Family-base map (legacy surface — `loader.load_all()`)

Returns `dict[type_key, DeviceDefinition]` with exactly one entry per
`type_key`.  Entries with `os_version` or `model` set are **excluded**
from this map; they live in the parallel variant registry instead.

Within the family-base set the loader uses a two-pass algorithm:

1. **Parse all files** — validate each `*.yaml` against the schema; skip failures.
2. **Sort by priority ascending** — apply definitions in order; higher-priority
   definitions are applied last and therefore win on `type_key` collision.

```
cisco/ios-xe/base.yaml        priority: 0   ← family-base baseline
cisco/ios-xe/17.x.yaml        priority: 10  ← higher priority wins among bases
```

### Longest-match resolver — `loader.resolve(type_key, os_version=None, model=None)`

For callers aware of the `(type_key, os_version, model)` triple (the
backup pipeline, the device form with operator-pinned variants,
future probe-driven refinement).  Returns the most-specific
overlay that matches, falling through to the family base:

| Tier | Match | Example |
|---|---|---|
| 1 | Exact triple | `resolve("Cisco", "17.12", "C9300-48P")` → triple-overlay if one exists |
| 2 | Version pin, model wildcard | `resolve("Cisco", "17.12")` → `os_version=17.12` overlay |
| 3 | Model pin, version wildcard | `resolve("Cisco", None, "C9300-48P")` → `model=...` overlay |
| 4 | Family base | `resolve("Cisco")` → plain family base |

Within a tier, the highest-priority matching file wins.

```
cisco/ios-xe/17.x.yaml            family base  (os_version=None, model=None)
cisco/ios-xe/17.12.yaml           overlay      (os_version="17.12")
cisco/ios-xe/models/C9300-48P.yaml overlay     (model="C9300-48P")
```

The two surfaces never contradict each other: family-base entries are
both in `load_all()` AND resolvable at tier 4; overlays are visible
only via `resolve()`.

## Vendor-Specific Notes

### Cisco IOS-XE
- `connection.needs_enable: true` — SSH often lands in user-exec mode.
- `connection.cisco_more_paging: true` — **`terminal length 0` is deliberately
  avoided**; instead, the collector injects a SPACE character to dismiss each
  `--More--` prompt mid-stream.  This is more reliable across IOS versions.

### Fortigate FortiOS
- Paging is suppressed with `config system console / set output standard`
  and restored with `set output more` in `commands.post`.
- Prompt has a space before `#`: `hostname # ` — pattern must account for it.

### OPNsense
- `connection.opnsense_shell_menu: true` — SSH lands at a numbered menu;
  the paramiko_shell collector detects `"Enter an option:"` and sends `"8"`.
- `collector.strategy: paramiko_shell` — Netmiko does not support OPNsense.

### MikroTik RouterOS
- `/export verbose` includes all defaults, which is preferable for a full
  backup and future diff/translation work.

### Aruba AOS-S 16.x (formerly HP ProCurve)
- `collector.netmiko_device_type: aruba_osswitch` — modern AOS-S 16.x driver;
  switch to `hp_procurve` for legacy 15.x firmware.
- `connection.cisco_more_paging: true` — Aruba's `-- MORE --` pager responds
  to space-injection (the same mechanism Cisco uses); netmiko handles it
  internally for the `aruba_osswitch` driver.  CLAUDE.md hard rule: never
  `terminal length 0`.
- Manager-mode escalation handled by netmiko via the `secret` credential —
  the definition does NOT need `needs_enable: true`.
- `probe.command: show system` — colon-aligned key/value rows expose
  Software revision (e.g. `WC.16.10.0023`), Hardware (chassis SKU + name)
  and Serial Number; patterns anchor per-line via re.MULTILINE.

---

## See also

- [`../ARCHITECTURE.md`](../ARCHITECTURE.md) — four-layer design (definitions feed both the backup collectors and the migration target-profile picker)
- [`../netconfig/migration/codecs/README.md`](../netconfig/migration/codecs/README.md) — codec authorship guide (each codec consumes target-profile shape)
- [`../netconfig/collectors/README.md`](../netconfig/collectors/README.md) — collector strategies a definition's `connection` block selects from

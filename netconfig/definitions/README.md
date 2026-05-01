# Definition Loader

The loader scans a directory tree for `*.yaml` files, validates each against
the `DeviceDefinition` Pydantic schema, and returns a
`dict[str, DeviceDefinition]` keyed by `type_key`.

## Usage

```python
from pathlib import Path
from netconfig.definitions.loader import DefinitionLoader

loader = DefinitionLoader(Path("definitions"))
profiles = loader.load_all()   # dict[str, DeviceDefinition]

# Look up a family-base definition by type_key
cisco = profiles["Cisco"]
print(cisco.collector.strategy)          # "netmiko"
print(cisco.collector.netmiko_device_type)  # "cisco_xe"

# Layered lookup — returns the most-specific overlay matching
# (type_key, os_version, model) with longest-match semantics.
# Falls through to the family base when no overlay matches.
overlay = loader.resolve("Cisco", os_version="17.12", model="C9300-48P")
```

The production app calls `DefinitionLoader` once during the FastAPI lifespan
and stores the result in `app.state.definitions` (the family-base dict
for type_key iteration) plus the loader itself in
`app.state.definition_loader` (for `.resolve(...)` calls from the backup
route).  Definitions are read-only at runtime; restart the server to
pick up changes.

## Two-Pass Loading Algorithm

```
Pass 1: rglob("*.yaml")
        for each file:
            parse YAML → validate against DeviceDefinition
            on error: log WARNING, skip file
            on success: collect (priority, definition) pair

Pass 2: sort candidates by priority ascending
        for each (priority, definition):
            profiles[definition.type_key] = definition
            # higher priority → loaded later → wins on collision
```

Higher `priority` values win when multiple files share the same `type_key`.
Equal-priority files are resolved by lexicographic file path order (later path
wins) — but explicitly setting `priority` is more reliable.

## Schema

See `netconfig/definitions/schema.py` for the authoritative Pydantic models:

| Class | Fields |
|-------|--------|
| `DeviceDefinition` | `vendor`, `os`, `version_match`, `type_key`, `priority`, `os_version`, `model`, `file_extension`, `connection`, `commands`, `prompts`, `collector`, `probe`, `notes` |
| `ConnectionConfig` | `needs_enable`, `cisco_more_paging`, `opnsense_shell_menu` |
| `CommandConfig` | `pre`, `config`, `post` |
| `PromptConfig` | `trailing` |
| `CollectorConfig` | `strategy`, `netmiko_device_type` |
| `ProbeConfig` | `command`, `patterns` |

`source_file` is set by the loader after validation and is excluded from
JSON serialisation (`Field(..., exclude=True)`).

### Layered definitions (`os_version` / `model`)

`os_version` and `model` pin a YAML file to a specific OS version or
hardware model.  Both default to `None` — a "family-base" definition
that applies to any version/model with the matching `type_key`.  Files
that DO declare them become overlays resolved via
`DefinitionLoader.resolve(type_key, os_version=..., model=...)`.  The
resolver picks the most-specific match in priority order (exact triple
→ version-pin → model-pin → family base).

This is the backup-layer counterpart to the migration layer's target
profiles — both subsystems share the vendor slug but have distinct
schemas.

### Probe config (`probe`)

A `probe` block on a definition configures a pre-backup "show version"
style command + regex extractors that populate
`DeviceProfile.detected_facts`.  Used by the backup route to:

1. Show the device's actual OS version and model in the UI.
2. Drive `DefinitionLoader.resolve` when the operator hasn't pinned
   `os_version` / `model` on the profile.

Example (Cisco IOS-XE):

```yaml
probe:
  command: show version
  patterns:
    detected_os_version: "Version\\s+([\\d.]+(?:\\(\\w+\\))?)"
    detected_model: "Model Number\\s+:\\s+(\\S+)"
```

Probe is **optional** — definitions without a `probe` block continue
to work unchanged, and backup failures in the probe phase are
non-fatal (log WARNING, fall back to family-base).  The pure-function
parser lives at `netconfig/collectors/probe.py` for unit-testable
regex logic without any session dependency.

## Error Handling

| Condition | Behaviour |
|-----------|-----------|
| Directory missing | `FileNotFoundError` |
| No `*.yaml` files found | `RuntimeError` |
| YAML parse error | `WARNING` log, file skipped |
| Non-dict top-level YAML | `WARNING` log, file skipped |
| Pydantic `ValidationError` | `WARNING` log, file skipped |
| All files invalid | `RuntimeError` |

A single bad file never prevents other files from loading.

## Extending

To add a new device:

1. Create a YAML file under `definitions/<vendor>/<os>/<version>.yaml`.
2. The server picks it up on the next restart.
3. Add a test definition in `tests/unit/test_loader.py` to cover any new
   schema fields.

See `definitions/README.md` for the full YAML schema reference.

---

## See also

- [`../../definitions/README.md`](../../definitions/README.md) — YAML-author-facing schema reference (this directory is the loader / Pydantic model side)
- [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md) — four-layer design and where definitions feed into the backup + migration concerns

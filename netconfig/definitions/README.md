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

# Look up a definition by type_key
cisco = profiles["Cisco"]
print(cisco.collector.strategy)          # "netmiko"
print(cisco.collector.netmiko_device_type)  # "cisco_xe"
```

The production app calls `DefinitionLoader` once during the FastAPI lifespan
and stores the result in `app.state.definitions`.  Definitions are read-only
at runtime; restart the server to pick up changes.

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
| `DeviceDefinition` | `vendor`, `os`, `version_match`, `type_key`, `priority`, `file_extension`, `connection`, `commands`, `prompts`, `collector`, `notes` |
| `ConnectionConfig` | `needs_enable`, `handle_paging`, `needs_shell_menu` |
| `CommandConfig` | `pre`, `config`, `post` |
| `PromptConfig` | `trailing` |
| `CollectorConfig` | `strategy`, `netmiko_device_type` |

`source_file` is set by the loader after validation and is excluded from
JSON serialisation (`Field(..., exclude=True)`).

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

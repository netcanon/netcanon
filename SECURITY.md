# NetConfig — Security Architecture

This document describes the security model, threat assumptions, implemented
controls, and known limitations of NetConfig.  It must be updated whenever
a security-relevant change is made to the codebase.

---

## Threat Model

NetConfig is designed as a **local desktop application**.  The server
component (`netconfig/`) binds exclusively to `127.0.0.1` and is not
intended to be exposed to a network.  All security controls are designed
with this assumption.

| Actor | Trust level |
|-------|-------------|
| Local user running the desktop app | Fully trusted |
| Other processes on the same machine | Untrusted |
| Network peers | Out of scope — server must not be exposed |

---

## Credential Storage (Encryption at Rest)

**Module:** `netconfig/security/credentials.py`  
**Stores:** `netconfig/storage/device_profile_store.py`, `netconfig/storage/schedule_store.py`

Device passwords and enable passwords are **never written to disk in
plaintext**.  The storage layer encrypts all credential fields with
[Fernet symmetric encryption](https://cryptography.io/en/latest/fernet/)
before writing JSON files, and decrypts them immediately after reading.

### Key management

A random 256-bit Fernet key is generated on first use and stored in the
**OS secure credential store**:

| Platform | Backend |
|----------|---------|
| Windows  | Windows Credential Manager (DPAPI) |
| macOS    | Keychain |
| Linux    | SecretService / libsecret |

The key is retrieved from the OS store on every startup via the
[`keyring`](https://pypi.org/project/keyring/) library.  The application
never writes the key to disk itself.

### Migration

On first startup after upgrading from a pre-encryption version, any
credential field that fails Fernet decryption is assumed to be a legacy
plaintext value.  `decrypt_field()` returns the plaintext and signals the
caller to re-save the file with encryption applied.  Migration is
transparent and logged at `INFO`.

### In-memory model

`DeviceProfile`, `ScheduleDevice`, and all other model objects always hold
**plaintext** credential strings in memory.  Encryption is a storage-layer
concern only.  Credential fields are **never logged** (verified by
`tests/unit/test_logging_config.py`).

---

## Credential Exposure in the Browser

Credentials are **not embedded in HTML**.

- **Dashboard (`index.html`)** — the Saved Device `<select>` options include
  only non-sensitive fields (`type_key`, `host`, `port`, `username`).
  Passwords are fetched via `GET /api/v1/devices/{id}` when a profile is
  selected; the API call is over localhost HTTP.

- **Devices page (`devices.html`)** — the `data-profile` DOM attribute
  contains only non-sensitive fields (id, name, type_key, host, port,
  notes, created_at).  `runDeviceBackup()` fetches the full profile from
  the API before submitting a backup job.

---

## Path Traversal Protection

**File:** `netconfig/storage/file_store.py` → `FileConfigStore.resolve_path()`

All config file access is gated through `resolve_path()`, which:

1. Requires the filename to match `_FILENAME_RE` — a strict regex that only
   accepts the `{DeviceType}_{safe_host}_{YYYYMMDD_HHmmss}[_N].{ext}` naming
   convention.  Any filename containing `..`, `/`, path separators, or
   characters outside that pattern is immediately rejected with
   `FileNotFoundError`.

2. Resolves symlinks (`Path.resolve()`) and asserts the result lies inside
   `storage_dir` before returning the path.  This is defence-in-depth
   against symlink attacks.

Covered by `tests/unit/test_storage.py` → `TestResolvePathSecurity` and
`tests/integration/test_configs_api.py` → `TestPathTraversal`.

---

## Open-in-Editor Endpoint

**File:** `netconfig/api/routes/configs.py` → `open_config()`

`POST /api/v1/configs/{filename}/open` is **only enabled on the desktop
build** (`Settings.open_in_editor = True`).  It is disabled (403) on all
web deployments.

Two additional guards beyond the path traversal fix:

1. **Extension whitelist** — only `.cfg`, `.conf`, `.txt`, `.xml`, `.log`
   may be opened.  Any other suffix returns 400 before filesystem access.

2. **`resolve_path()` guard** — the filename must pass the regex check;
   traversal attempts are rejected with 404.

Covered by `tests/integration/test_configs_api.py` → `TestOpenConfig`.

---

## Input Validation — Host Field

**Files:** `netconfig/models/device.py`, `netconfig/models/device_profile.py`

`DeviceTarget.host`, `DeviceProfileCreate.host`, and `DeviceProfileUpdate.host`
all run through `_validate_host()`, which accepts only:

- Valid IPv4 addresses (`ipaddress.ip_address()`)
- Valid IPv6 addresses
- RFC-1123 hostnames (alphanumeric labels, hyphens, dots)

Any other value (path separators, semicolons, spaces, shell metacharacters)
is rejected with a Pydantic `ValidationError` → HTTP 422.

Covered by `tests/unit/test_models.py` → `TestDeviceTarget` host validation cases.

---

## Data Directory Isolation

Runtime data directories (`devices/`, `schedules/`, `jobs/`, `configs/`)
are listed in `.gitignore` and must not be committed to version control.
These directories are created automatically at runtime.

---

## Localhost-Only Binding

**File:** `netconfig_desktop/settings.py`

The desktop app binds the embedded Uvicorn server to `127.0.0.1` only.
`--host` / `--port` flags for public binding are a web-deployment-only
concern and are never exposed in the desktop shell.

---

## Template Security

All Jinja2 templates use **automatic HTML escaping** (the default for HTML
templates).  No `| safe` filter is applied to any user-controlled value.
XSS via template injection is not possible under the current design.

---

## Dependency Supply Chain

Key dependencies and their security relevance:

| Package | Role | Notes |
|---------|------|-------|
| `cryptography` | Fernet encryption | Well-maintained; used by Paramiko |
| `keyring` | OS credential store access | Thin wrapper; minimal attack surface |
| `paramiko` | SSH transport | Keep updated; historical key-handling CVEs |
| `netmiko` | SSH device abstraction | Wraps Paramiko |
| `pyyaml` | Definition file parsing | Uses `safe_load()` exclusively |
| `fastapi` | Web framework | Actively maintained |
| `pydantic` | Input validation | v2; strict validation model |

Run `pip-audit` or `safety check` regularly to detect known CVEs.

---

## Known Limitations / Accepted Risks

| Item | Risk | Accepted? | Rationale |
|------|------|-----------|-----------|
| No API authentication | Any local process can call the API | Yes | Local app; single-user machine assumed |
| Credentials over localhost HTTP | Plaintext in transit on loopback | Yes | Loopback is not a network interface; TLS on localhost adds no practical security |
| OS keyring unavailable (some Linux headless) | Key falls back to generation with no secure storage | Partial | Desktop app; headless Linux is not a supported target |
| Key loss (keyring entry deleted) | Encrypted profiles become unreadable | Accepted | User must re-enter credentials; profiles are low-volume |

---

## Updating This Document

This file must be updated when any of the following change:

- A new credential field is added to any persisted model
- A new file-access endpoint is added
- A new input field is accepted from untrusted sources
- A dependency with security relevance is added or removed
- The threat model assumption (localhost-only) changes

---

## See also

- [`README.md`](README.md) — project orientation and quickstart
- [`CLAUDE.md`](CLAUDE.md) — contributor directives, including the "never commit real credentials" hard rule

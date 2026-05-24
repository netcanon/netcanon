# Netcanon — Security Architecture

This document describes the security model, threat assumptions, implemented
controls, and known limitations of Netcanon.  It must be updated whenever
a security-relevant change is made to the codebase.

---

## Reporting a Vulnerability

**Do not open public GitHub issues for security vulnerabilities.**

Use GitHub's private vulnerability reporting flow:
**https://github.com/netcanon/netcanon/security/advisories/new**

What to include:

- Affected component (codec, pipeline stage, API endpoint, desktop shell)
- Affected versions (commit SHA or release tag)
- Steps to reproduce — sanitized; never include real credentials, IPs,
  or hostnames in the report
- Impact assessment as you see it
- Suggested fix if you have one

What to expect:

- Acknowledgment within 7 days
- Triage outcome within 14 days
- Coordinated disclosure if a fix is needed
- Credit in the advisory unless you prefer otherwise

We treat any cross-trust-boundary vulnerability — auth bypass, credential
exposure, arbitrary file write outside the configured directory, code
execution via crafted device output — as critical.  Issues entirely within
the local-trust boundary (a malicious local user) are accepted risks per
the threat model below.

---

## Threat Model

Netcanon ships in two deployment shapes:

1. **Desktop application (primary).**  The Windows MSI / `python -m
   netcanon_desktop` shell binds the embedded server exclusively to
   `127.0.0.1`.  Security controls assume a single-user local
   machine.
2. **Web / Docker deployment.**  Operators who pass `--host 0.0.0.0`
   (or run the published GHCR image) are deploying outside the
   single-user-local-machine threat model.  Netcanon does NOT ship
   API authentication, TLS, or rate-limiting — operators in this
   shape must front the app with a reverse proxy that provides those
   controls (nginx + auth_request, Caddy + basic-auth, Cloudflare
   Access, etc.) and restrict ingress at the network layer.

| Actor | Trust level |
|-------|-------------|
| Local user running the desktop app | Fully trusted |
| Other processes on the same machine | Untrusted |
| Network peers (desktop deployment) | Out of scope — server bound to loopback only |
| Network peers (web deployment without reverse proxy) | Out of scope — operator responsibility to add auth + TLS |

---

## Credential Storage (Encryption at Rest)

**Module:** `netcanon/security/credentials.py`  
**Stores:** `netcanon/storage/device_profile_store.py`, `netcanon/storage/schedule_store.py`

Device passwords and enable passwords are **never written to disk in
plaintext**.  The storage layer encrypts all credential fields with
[Fernet symmetric encryption](https://cryptography.io/en/latest/fernet/)
before writing JSON files, and decrypts them immediately after reading.

### Key management — three-tier resolution

The Fernet key is resolved in this order, first hit wins:

| Tier | Source | Best fit | Key on disk? |
|------|--------|----------|--------------|
| **1** | `NETCANON_FERNET_KEY` env var | Container / headless / production | No |
| **2** | OS keyring (Windows Cred Manager / macOS Keychain / Linux SecretService) | Desktop install | No |
| **3** | File at `$NETCANON_DATA_DIR/.fernet_key` (auto-generated) | Zero-config container | Yes, in the operator's bind-mounted data volume |

The key never moves between tiers — once a key exists at any tier, that
key is used.  Tier promotion (e.g. moving from file fallback to env var)
is an operator-driven re-keying operation: read the key from the lower
tier, set it as the higher-tier value, then optionally remove the lower
tier (e.g. `rm $NETCANON_DATA_DIR/.fernet_key` after copying the value
into `NETCANON_FERNET_KEY`).

**Tier 1 — Environment variable (recommended for production):**
Generate once with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Inject via your orchestrator's secret-injection mechanism:

```bash
docker run -e NETCANON_FERNET_KEY=<key> ghcr.io/netcanon/netcanon:latest
```

The key never touches the application's data directory.  This is the
recommended deployment pattern for any environment where the bind-
mounted volume's filesystem permissions aren't sufficient credential
protection (multi-tenant hosts, shared CI environments, regulated
infrastructure).

**Tier 2 — OS keyring (default for desktop installs):**

| Platform | Backend |
|----------|---------|
| Windows  | Windows Credential Manager (DPAPI) |
| macOS    | Keychain |
| Linux    | SecretService / libsecret (via dbus) |

A random 256-bit Fernet key is generated on first use and stored via
the [`keyring`](https://pypi.org/project/keyring/) library.  The
application never writes the key to disk itself.  This is the default
for `pip install netcanon` and MSI / desktop-app deployments.

**Tier 3 — File fallback (zero-config bootstrap):**
When neither the env var nor a working keyring backend is available
(typical container deployments without an injected env var), a new
Fernet key is auto-generated and written to
`$NETCANON_DATA_DIR/.fernet_key` with restrictive permissions (0o600
on POSIX; Windows relies on operator-managed directory perms).  The
file persists in the operator's bind-mounted data volume, so
subsequent container restarts decrypt existing profiles.

The key is plaintext on disk, but the disk in question is
`NETCANON_DATA_DIR` — the same volume the operator already chose to
trust for jobs / schedules / device profile JSON.  This is the weakest
tier; production deployments should prefer tier 1 so the key is
auditable through the orchestrator's secret-management surface rather
than living in the data volume.

A `WARNING`-level log line announces the auto-generation event so the
operator can choose to upgrade to tier 1 by reading the file contents,
setting them as `NETCANON_FERNET_KEY`, and deleting the file.

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

**File:** `netcanon/storage/file_store.py` → `FileConfigStore.resolve_path()`

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

**File:** `netcanon/api/routes/configs.py` → `open_config()`

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

## Input Validation — Operator-Uploaded XML

**Files:** `netcanon/migration/codecs/opnsense/parse.py` (line 169) +
`netcanon/migration/codecs/cisco_iosxe/codec.py` (line 543)

Both codecs parse operator-uploaded XML — OPNsense `config.xml` files
and Cisco IOS-XE NETCONF outputs.  Until v0.1.2, both used Python's
stdlib `xml.etree.ElementTree.fromstring`, which expands internal
entities by default — verified empirically on Python 3.14.4.  A
five-line billion-laughs payload (`<!ENTITY lol "lol">` + `<!ENTITY
lol1 "&lol;&lol;&lol;">` + `&lol1;`) would return the expanded text
rather than raising, hanging the FastAPI worker on memory exhaustion.
External entities (XXE `SYSTEM "file:///etc/passwd"`) are already
blocked since Python 3.7.1, but the entity-bomb / quadratic-blowup
DoS class was live.

v0.1.2 swapped both parse sites to `defusedxml.ElementTree.fromstring`,
which is an exact API drop-in that rejects entity-bomb / external-
entity payloads while preserving full compatibility with normal
config XML.  Generation-side ET use (`ET.Element`, `ET.SubElement`,
`tostring`, `register_namespace`) stays on stdlib — those don't
consume untrusted input.

Each call site wraps the rejection in an explicit `DefusedXmlException`
clause so malicious-payload rejection produces a clean operator-facing
`ParseError` (`opnsense: refusing potentially-malicious XML
(entity-bomb / XXE attempt)`) rather than a 500 stack trace.

Triage detail: [`docs/security-triage/2026-05-21/`](docs/security-triage/2026-05-21/)
investigations A § alerts #14/#15.

Covered by the normal codec round-trip test suites; a bomb-payload
unit test is on the v0.1.x follow-up backlog.

---

## Input Validation — Host Field

**Files:** `netcanon/models/device.py`, `netcanon/models/device_profile.py`

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

## Localhost-Only Binding (Desktop)

**File:** `netcanon_desktop/settings.py`

The desktop app binds the embedded Uvicorn server to `127.0.0.1` only.
`--host` / `--port` flags for public binding are a web-deployment-only
concern and are never exposed in the desktop shell.

For the web/Docker deployment shape, operators who choose to bind on
a non-loopback address are responsible for fronting the app with a
reverse proxy that adds authentication and TLS — see "Threat Model"
above.

---

## Sanitiser (Bug-Reporting Workflow)

**Module:** `netcanon/tools/sanitize.py`
**CLI:** `netcanon sanitize`
**HTTP:** `POST /api/v1/sanitize`

When operators submit configs for bug reports / fixture submissions,
the sanitiser strips identity-bearing data via field-typed redactions
on the canonical model:

| Category | Replacement |
|---|---|
| Hostname | `device-N` |
| Domain | `example-N.test` |
| Public IPv4 | RFC 5737 docs ranges |
| Hashed passwords | Format-preserving fakes (Junos `$9$`, FortiGate `ENC`, crypt `$5$`/`$6$`, bcrypt `$2y$`, Cisco type-7 hex, Aruba SHA-1) |
| SNMP communities | `public_redacted_N` |
| SNMPv3 auth/priv passphrases | `REDACTED-AUTH-N` / `REDACTED-PRIV-N` |
| RADIUS shared secrets | `REDACTED-RADIUS-N` |
| Interface descriptions | `description redacted` |
| Tier-3 sections (firewall / NAT / VPN) | Stripped entirely |

Counter-per-session stable: same input value always maps to the same
redaction (so cross-references survive — a hostname referenced 5 times
gets the same redacted value all 5 times).  `--dry-run` prints the
substitution table for operator review before writing output.

Known limitations are listed in
[`BUG_REPORTING.md`](BUG_REPORTING.md) — notably IPv6-public redaction
is IPv4-only at v0.1.0; banner / comment text is parse-and-ignored
rather than redacted.

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
| `defusedxml` | Safe XML parsing for operator-uploaded input | Added v0.1.2. Drop-in replacement for `xml.etree.ElementTree.fromstring` at the OPNsense + Cisco IOS-XE NETCONF parse sites; rejects entity-bomb / billion-laughs / quadratic-blowup payloads.  Stdlib ET expands internal entities by default on Python 3.x (verified empirically on 3.14.4) — `defusedxml` closes that DoS class without altering legitimate-config behaviour |

Run `pip-audit` or `safety check` regularly to detect known CVEs.
Dependabot is also configured (`.github/dependabot.yml`) with a 7-day
cooldown across all 3 ecosystems (pip / github-actions / docker) to
let upstream yank windows close before bumps land automatically.

---

## Supply-Chain Integrity

Phase 6 of the public release plan shipped the following supply-chain
integrity controls.  Operators in environments that require attested
provenance can verify each:

- **Multi-stage Docker builds.**  `Dockerfile` separates a `builder`
  stage (compiles wheels with `build-essential`) from a `runtime`
  stage that installs prebuilt wheels with `pip install --no-index`.
  No compilers in the runtime layer; no network during the runtime
  install.
- **Cosign signatures via Sigstore (GHCR only).**  Published GHCR
  images (`ghcr.io/netcanon/netcanon`) are signed with keyless cosign
  through GitHub Actions OIDC.  Verifiable with:
  ```
  cosign verify ghcr.io/netcanon/netcanon:<tag> \
      --certificate-identity-regexp 'github.com/netcanon/netcanon' \
      --certificate-oidc-issuer https://token.actions.githubusercontent.com
  ```
- **SBOM via syft + cosign attestation (GHCR only).**  An SPDX-format
  SBOM is generated by syft and attached to the image as a cosign
  attestation.  Verifiable with `cosign verify-attestation`.
- **Trusted Publishing for PyPI.**  The PyPI workflow uses
  `pypa/gh-action-pypi-publish@release/v1` with the `pypi`
  environment.  No long-lived API tokens; OIDC-based publish.
- **Non-root container runtime.**  The image runs as `app` (uid=1000);
  bind-mounted volumes are the only writable surface.

### v0.1.2 supply-chain hardening

The v0.1.2 release added a second layer of supply-chain integrity
controls focused on the CI/workflow surface and the artifact-scan
surface.  Triage scaffolding for handling alerts these controls
surface lives at [`docs/security-triage/`](docs/security-triage/);
the worked example is the 2026-05-21 cycle that produced this
hardening.

- **GitHub Code Scanning enabled.**  CodeQL default setup covers
  Python + JavaScript/TypeScript + GitHub Actions surfaces.  Findings
  surface in the repo's Security → Code scanning view with
  Copilot Autofix suggestions.
- **`zizmor` workflow security scanning.**
  `.github/workflows/zizmor.yml` runs on every workflow-file or
  Dependabot-config change + a weekly cron.  SARIF results upload to
  Code scanning under the `zizmor` category.  Site config at
  `.github/zizmor.yml` implements the hybrid action-pinning policy
  (tag-pin allowed for `actions/*` + `github/*` first-party
  publishers; SHA-pin required for third-party publishers).
- **Trivy Docker image scanning.**  Runs after `Build and push` in
  `.github/workflows/docker-publish.yml`; scans the just-built image
  for OS-package + Python-package CVEs at HIGH+CRITICAL severity
  (`ignore-unfixed: true` filters noise).  Results upload to Code
  scanning under the `trivy-image` category.  Fires on every release
  tag push (`v*.*.*`).
- **SHA-pinned third-party actions.**  All 11 third-party action
  references in the workflow corpus
  (`softprops/action-gh-release`, `docker/setup-buildx-action`,
  `docker/login-action`, `docker/metadata-action`,
  `docker/build-push-action`, `aquasecurity/trivy-action`,
  `sigstore/cosign-installer`, `anchore/sbom-action`,
  `pypa/gh-action-pypi-publish`, `zizmorcore/zizmor-action`) are
  pinned to full commit SHAs with trailing tag comments
  (`@<sha>  # <tag>`) so Dependabot can still propose bumps.  GitHub
  first-party actions (`actions/*`, `github/*`) retain tag-pins per
  the hybrid policy — GitHub controls those repos with force-push
  protection.
- **Workflow-level `permissions: contents: read` on `ci.yml`.**
  Default-deny `GITHUB_TOKEN` scope at workflow level; all three
  ci.yml jobs are read-only.  Other workflow files (`docker-publish`,
  `pypi-publish`, `desktop-msi-publish`, `zizmor`) declare narrower
  per-job scopes where write access is required (`packages: write` /
  `id-token: write` for publish jobs; `security-events: write` for
  SARIF upload).
- **`persist-credentials: false` on all `actions/checkout` calls.**
  Closes the default behaviour of `actions/checkout@v6` writing
  `GITHUB_TOKEN` into `.git/config` for later steps.  No netcanon
  workflow performs a git push / fetch / tag / config write that
  needs the persisted credential helper; registry logins use
  explicit secrets, OIDC, or action-internal auth.
- **Template-injection hardening on `desktop-msi-publish.yml`.**
  Replaced inline `${{ inputs.tag || github.ref_name }}` shell
  interpolation with `env:`-mediated indirection so a tag name with
  shell metacharacters can't execute arbitrary code with access to
  `DOCKERHUB_TOKEN` / signing keys.
- **Dependabot cooldown blocks.**  All 3 ecosystems (pip /
  github-actions / docker) wait 7 days after upstream release before
  opening a bump PR.  Closes the rare-but-real window where a
  briefly-hijacked release tag gets picked up automatically before
  the upstream maintainer notices.
- **Private vulnerability reporting + secret scanning + push
  protection + Dependabot malware alerts.**  All enabled at the repo
  level via GitHub's Advanced Security settings.  Researchers can
  privately disclose at
  `https://github.com/netcanon/netcanon/security/advisories/new`;
  secret scanning runs on history + blocks credential pushes at
  commit time.

### Distribution channels and what each provides

| Channel | Image bytes | Cosign signature | SBOM attestation |
|---|---|---|---|
| GHCR — `ghcr.io/netcanon/netcanon` | ✅ canonical | ✅ keyless via Sigstore + GitHub OIDC | ✅ SPDX JSON via syft |
| Docker Hub — `docker.io/netcanon/netcanon` | ✅ same bytes (mirror) | ❌ unsigned | ❌ no attestation |
| PyPI — `pip install netcanon` | n/a | ✅ Trusted Publishing (OIDC) | n/a |

Same image manifest is pushed to both registries from the same
`docker/build-push-action` step; the bytes are byte-identical with
the same digest.  Cosign signing only attaches signatures to the GHCR
copy because Docker Hub is treated as a convenience mirror — operators
in regulated environments should pull from GHCR to get the attested
provenance chain.  Operators in casual environments who just want
the image working can use either.

**Pending:** a pinned dependency manifest (`requirements.lock` /
`uv.lock`).  Production builds currently resolve from `pyproject.toml`
ranges; lock-file resolution is a follow-up wave for operators in
regulated environments.

---

## Known Limitations / Accepted Risks

| Item | Risk | Accepted? | Rationale |
|------|------|-----------|-----------|
| No API authentication | Any local process can call the API | Yes (desktop) / Operator responsibility (web/Docker) | Desktop assumes single-user local machine; web operators must add auth via reverse proxy |
| Credentials over localhost HTTP | Plaintext in transit on loopback | Yes | Loopback is not a network interface; TLS on localhost adds no practical security |
| OS keyring unavailable (container / headless Linux) | Resolved via env-var tier (recommended) or file-fallback tier (auto-bootstrap) | No (resolved) | Three-tier key resolution — `NETCANON_FERNET_KEY` for production; `$NETCANON_DATA_DIR/.fernet_key` auto-bootstrap for zero-config containers.  See "Credential Storage" above |
| Key loss (keyring entry deleted / env var unset on restart / `.fernet_key` deleted) | Encrypted profiles become unreadable | Accepted | User must re-enter credentials; profiles are low-volume.  Operators using tier 1 / tier 3 should back the key up alongside their other infrastructure secrets |
| Banner / comment text not sanitised | Operator-submitted bug reports may leak banner content | Documented | Sanitiser is canonical-model-driven; banner text is parse-and-ignored.  See `BUG_REPORTING.md`; hand-redact banners before submission. |
| IPv6-public redaction not implemented | Operator-submitted public IPv6 addresses pass through verbatim | Documented | v0.1.0 limitation; sanitiser is IPv4-only.  Hand-redact public IPv6 before submission. |

---

## Updating This Document

This file must be updated when any of the following change:

- A new credential field is added to any persisted model
- A new file-access endpoint is added
- A new input field is accepted from untrusted sources
- A dependency with security relevance is added or removed
- The threat model assumption (localhost-only desktop / operator-
  responsibility web) changes
- A new redaction category lands in `netcanon/tools/sanitize.py`
- A new supply-chain integrity control ships (signature, attestation,
  lock manifest, etc.)

---

## See also

- [`README.md`](README.md) — project orientation and quickstart
- [`BUG_REPORTING.md`](BUG_REPORTING.md) — sanitiser workflow for
  submitting configs in public issues
- [`docs/CAPABILITIES.md`](docs/CAPABILITIES.md) — per-codec capability
  matrix and Tier-3 boundary
- [`AGENTS.md`](AGENTS.md) — contributor directives, including the
  "never commit real credentials" hard rule and the
  "PII review before any push to an online repo" hard rule
- [`docs/security-triage/`](docs/security-triage/) — process + per-run
  evidence trail for triaging Code Scanning / Dependabot / secret-
  scanning alert waves; the operational complement to the controls
  documented above
- [`docs/docs-audit/`](docs/docs-audit/) — sister process applying the
  same cluster-scaffolded read-only-agents-then-orchestrator-fixes
  pattern to documentation hygiene; recurring cycle that catches
  drift between docs and code (the v0.1.2 SECURITY.md update wave
  documented above was produced by the 2026-05-21 audit cycle)

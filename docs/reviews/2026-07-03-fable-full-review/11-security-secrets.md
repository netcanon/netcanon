# 11 — Secrets & credential handling (Fable fresh-eyes pass)

**Reviewer lens:** Fernet crypto, credential storage/resolution, DeviceProfilePublic
write-only paradigm, sanitizer/redaction, logging_config, clear-text-logging class.

**Verdict: GO-WITH-FIXES.** The core paradigms (Fernet 3-tier, SecretStr in transit,
DeviceProfilePublic write-only, constant-time API-key compare, sanitizer field-typed
redaction) are intact and carefully built. But the write-only paradigm has **one
unclosed sibling surface** (legacy schedule inline credentials echoed in plaintext over
the read API) and **one clear-text-logging path** (decrypted credentials embedded in
pydantic `ValidationError` text at ERROR level), both verified by live probe. Two minor
findings round it out. No sanitizer coverage gaps found; no ReDoS in redaction regexes.

---

## Finding 1 — MAJOR: `GET /api/v1/schedules/` echoes legacy inline device credentials in plaintext

**Cites:**
- `netcanon/models/schedule.py:38-39` — `ScheduleDevice.password: str`,
  `enable_password: str | None` — plain `str`, **not** `SecretStr`, no serializer scrub.
- `netcanon/api/routes/schedules.py:279` — `GET /` `response_model=list[BackupSchedule]`;
  also `:292` (`POST /` echo) and `:354` (`POST /{id}/toggle` echo). Router prefix
  `/schedules` under `/api/v1` (`schedules.py:28`, `main.py:314`).
- `netcanon/storage/schedule_store.py:90-95` — `load_all()` decrypts the legacy inline
  `devices[].password` / `enable_password` **in place** on startup, so the in-memory
  registry these routes serialise holds plaintext.

**Probe (verified):**
```
BackupSchedule(name='legacy', interval_minutes=60,
    devices=[ScheduleDevice(..., password='PlainTextPw!', enable_password='EnPw!')]
).model_dump_json()
→ 'PlainTextPw!' in output: True ; 'EnPw!' in output: True
```

**Failure scenario:** an operator who upgraded from a pre-profile version has an
old-style schedule file on disk (exactly the population `schedule_store`'s decrypt-and-
migrate path exists to serve). Every `GET /api/v1/schedules/` response — readable by any
local process on the default unauthenticated loopback bind, by same-origin browser JS,
or by any bearer-token holder on an exposed deployment — contains the device SSH
password and enable password in clear JSON. `ScheduleCreate` (`models/schedule.py:78-95`)
can no longer create inline devices, so this is a legacy-only surface, but the files
are load-supported indefinitely and the leak repeats on every list/toggle call.

**Why this is a paradigm break, not a re-litigation:** the 2026-06 cred-scrub gave
`DeviceProfile` a `DeviceProfilePublic` read model + guard test precisely so decrypted
in-memory credentials "are never serialised back to a client"
(`models/device_profile.py:73-92`); `BackupSchedule` is the sibling read surface and was
skipped. The `ScheduleDevice` docstring's claim "The data lives only on the local
filesystem" (`models/schedule.py:20-22`) is false at the API layer. The 2026-06-17 SOPS
secret census (`docs/reviews/2026-06-17-sops-evaluation/10-research-secret-census.md:198`)
covered only the at-rest side (Fernet ciphertext — correct); no prior pass adjudicated
the API echo.

**Suggested fix:** a `BackupSchedulePublic` response model that drops (or blanks
credentials inside) `devices`, used on all three `response_model=` sites, plus a guard
test mirroring `tests/unit/test_device_profile_public.py`.

---

## Finding 2 — MAJOR: decrypted plaintext credentials reach ERROR-level logs via pydantic `ValidationError` `input_value`

**Cites:**
- `netcanon/storage/device_profile_store.py:105-109` — `migrate_credential_fields(data,
  ["password", "enable_password"])` decrypts **in place**, *then*
  `DeviceProfile.model_validate(data)` at `:109`.
- `netcanon/storage/device_profile_store.py:120-123` — broad
  `except Exception as exc: logger.error("CORRUPT FILE SKIPPED: %s — %s", path.name, exc)`.
- Same pattern: `netcanon/storage/schedule_store.py:110-113` (legacy inline device creds
  decrypted at `:91-93` before `BackupSchedule.model_validate` at `:95`).

**Probe (verified, local `DeviceProfile` model):** a profile dict missing `type_key`
(post-decryption) raises `ValidationError` whose `str()` embeds
`input_value={'id': 'abc-123', 'name':...word': 'EnableSecret99'}, input_type=dict` —
the **decrypted enable password appeared verbatim** in the formatted log line. Pydantic
truncates the *middle* of `input_value`, so which credential survives depends on dict
size, but head/tail always survive and `password`/`enable_password` sit late in the
field order.

**Failure scenario:** a profile/schedule JSON that decrypts fine but fails model
validation — hand-edited file, schema drift across an upgrade (a future required field
makes *every* existing profile hit this at startup), or partial corruption that spares
the credential fields. The plaintext credential then lands at ERROR level on stderr
**and in the rotating log file** (`logging_config.py:156-161`), defeating
encryption-at-rest in exactly the recovery path the migration helper was built to
protect. This is the CodeQL clear-text-logging HIGH class, one layer up from codec
parse.

**Contrast showing the codebase already knows this trap:**
`netcanon/migration/codecs/base.py:105-112` (`_validation_error_as_parse_error`)
deliberately formats only `loc` + `msg` and never the input value. The stores predate
that care.

**Suggested fix:** in both `load_all()` `except` blocks, special-case
`pydantic.ValidationError` and log `exc.errors(include_input=False, include_url=False)`
(or just loc+msg per error); alternatively scrub the credential keys from `data` before
any formatting, or validate the raw (still-encrypted) dict first and decrypt on the
model object.

---

## Finding 3 — MINOR: SNMP community string logged at DEBUG; sibling orchestrators log counts only

**Cites:** `netcanon/migration/canonical/snmp_names.py:149-154` — entry log
`"translate_snmp_community: entry rename_map=%s current=%r"` passes
`current_community` (the **parsed community string**, a credential the sanitizer itself
classifies as `snmp-community`) verbatim. Every sibling orchestrator's entry log is
counts-only by design: `port_names.py:321-328`, `vlan_names.py:138-144`,
`local_user_names.py:121-127`, `snmpv3_user_names.py:134-139` — even the *rename_map*
in this same call is summarised as `"N-entry dict"`, making the `current=%r` the lone
deviation from the uniform pattern.

**Failure scenario:** an operator running `NETCANON_LOG_LEVEL=debug` (a documented
Settings value, `config.py:216-218`) gets the SNMP community of every migrated config
written to stderr/log file. DEBUG-only and same-box, hence minor — but it is the exact
"parsed config values logged" class the CI CodeQL gate exists for, and trivially fixed
by logging presence/length instead of the value.

**Related (accepted, no action needed):** the advisory warnings at
`snmp_names.py:207-217` embed `{current!r}` and flow into `job.warnings` →
migration API response (`services/migration_pipeline.py:692-693`). That returns the
community only to the principal who uploaded the config — same-principal echo, fine.

---

## Finding 4 — MINOR: SECURITY.md's "credentials never logged" claim cites a test that doesn't verify it

**Cites:** `SECURITY.md:190-193` — "Credential fields are **never logged** (verified by
`tests/unit/test_logging_config.py`)". That file tests handler/level/rotation/request-id
wiring only; it contains no credential assertion (grep for
`password|credential|secret` = zero hits). The only credential-log test in the tree is
`tests/unit/test_credentials.py:251-269`, which asserts a decrypt-failure *warning
fires* — not that secrets are absent from log output. So the claim is unverified — and,
per Finding 2, currently false in the corrupt-file path. Fix alongside Finding 2:
correct the citation and/or add a real caplog-based "plaintext never in records" guard.

---

## Verified clean (negative results — checked, no findings)

- **Fernet 3-tier** (`security/credentials.py`): fail-closed `decrypt_field` with
  positive token-shape detection (`:277-289`, 0x80 marker + 57-byte floor) — no
  fail-open regression; no key material ever logged (only key *location*); no hardcoded
  keys/salts; `migration.py:55-57` correctly suppresses re-save on partial decrypt
  (no double-encryption).
- **API auth** (`api/auth.py:54-56`): `hmac.compare_digest` — constant-time; no api_key
  value in any log or error message; `Settings` never dumped wholesale.
- **Collectors** (`netmiko_collector.py:82-108`, `paramiko_collector.py:174-191`):
  `SecretStr.get_secret_value()` used only as connect kwargs; DEBUG logs username only
  (deliberate); probe/collect exception logs pass through library messages that don't
  carry credentials; hostkey.py logs paths only. (Note for lens 21: `hostkey.py:9` says
  "auto_add (default)" while the default is `tofu` since v0.4.5 — doc drift within the
  same docstring, `:24-25`.)
- **Error surfaces**: `api/_errors.py` deliberately suppresses paths/tracebacks
  (auth-failure formatter echoes nothing from the exception); the global 500 handler
  (`api/routes/ui.py:155-167`) never echoes tracebacks to the client;
  `_validation_error_as_parse_error` (`codecs/base.py:105-112`) excludes input values.
- **Sanitizer coverage** (`tools/sanitize.py`): walked every `CanonicalIntent` field and
  every sub-model (`CanonicalLAG/Interface/Vxlan/RoutingInstance/DHCPPool/StaticRoute/
  VRRPGroup/SNMP` field lists probed live) — no secret-bearing or network-identifying
  field escapes the walk; `CanonicalVlan` has no `ipv6_addresses` field, so the missing
  v6 branch in the VLAN loop is not a gap; `raw_sections`/`group_content`/`apply_groups`
  strip fail-closed; type-7 (reversible) hashes are redacted by `redact_hash:1433`.
- **ReDoS**: `_HOSTNAME_RE` (`tools/sanitize.py:149-152`) — bounded `{0,61}` quantifiers,
  each repetition anchored by a literal `.`, 254-char lookahead cap → linear; `_MAC_RE`
  and the hash-shape regexes are trivially bounded. Not ReDoS-prone.
- **Persistence**: `BackupJob`/`BackupResult`/`ConfigRecord` (`models/backup.py`) carry
  no credentials, so job JSON persistence is clean; profile/schedule `save()` encrypts
  before write; templates never prefill password inputs (`devices.html:56,196` use
  `type="password"` with blank-to-keep semantics); FastAPI 422 echo of request bodies is
  same-principal only (no custom handler logs it).
- **Sanitize API dry-run** returning `original` values (`api/routes/sanitize.py:88-100`)
  is the documented operator-preview contract — same principal, by design.

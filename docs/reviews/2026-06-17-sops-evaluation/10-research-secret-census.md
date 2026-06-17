# 10 — Secret / Credential Census (netcanon AS-IS, at rest)

**Author:** R1 (research) · **Run:** 2026-06-17 SOPS evaluation · **Status:** read-only census, every claim cited to `file:line`.

This is the factual spine for the design + review phases. The single load-bearing
finding for the SOPS verdict is at the bottom (§7): in **every zero-config run mode the
Fernet key co-locates with the ciphertext it protects**, and in the OS-keyring mode it is
out-of-band. There is no run mode where SOPS would add a key-separation property that
netcanon's existing 3-tier scheme doesn't already offer (env var) or can't (file fallback).

---

## 1. What secrets netcanon actually handles

netcanon handles exactly **two classes** of secret material, plus one supporting key:

1. **Device login credentials it is given** — SSH `username`/`password` + Cisco `enable`
   secret, supplied by the operator to back up a device. netcanon *owns* these and is
   responsible for storing them. (`netcanon/models/device.py:29-31`,
   `netcanon/models/device_profile.py:53-65`)
2. **Device-side secrets inside the fetched configs** — the backup artifacts contain the
   target device's own hashed/encrypted passwords (`$9$…`, type-7, `$6$…`), SNMP community
   strings, RADIUS/TACACS keys, IKE/IPsec pre-shared keys, etc. netcanon does **not** own
   these — it transcribes whatever the device emits. (See §5.)
3. **The Fernet symmetric key** that encrypts class (1) at rest — a derived/supporting
   secret, not operator-facing. (`netcanon/security/credentials.py`)

There are **no** API tokens, cloud credentials, signing keys, or service-account secrets in
netcanon's own product surface (the PVE/scratch-VM token discussed in the seed is dogfood-lab
infrastructure, gitignored under `local/`, explicitly out of scope per `00-blackboard.md:57-58`).

---

## 2. Device credentials — the only secret netcanon encrypts at rest

### 2.1 In-memory model: `SecretStr` masking only, NOT encryption

- The **request/transport** model `DeviceCredentials` types `password` / `enable_password`
  as pydantic `SecretStr` (`netcanon/models/device.py:11,30-31`). This masks `repr()`/log/JSON
  output **in memory only** — it is not encryption and never reaches disk in this form.
- The **persisted** model `DeviceProfile` stores credentials as **plain `str`**
  (`netcanon/models/device_profile.py:59-60`), with the docstring explicitly stating
  "plaintext in memory; encrypted on disk" (`device_profile.py:9-12,34`). So the in-memory
  representation of a *persisted* profile is plaintext `str`, NOT `SecretStr`. The `SecretStr`
  only exists on the transport path (`DeviceCredentials`), and the backup route re-wraps the
  plaintext profile password back into `SecretStr` when resolving credentials
  (`netcanon/api/routes/backups.py:128-136`).

**Conclusion:** `SecretStr` contributes nothing to at-rest protection here; it is a
log/repr hygiene measure only. The at-rest protection is Fernet (next).

### 2.2 On-disk format: Fernet-encrypted inside otherwise-plaintext JSON — CONFIRMED

`FileDeviceProfileStore.save()` writes one JSON file per profile to `{data_dir}/devices/{id}.json`:

- It dumps the full model to JSON, then **overwrites** the `password` field (and
  `enable_password` if present) with `encrypt(...)` before writing
  (`netcanon/storage/device_profile_store.py:64-67`).
- `encrypt()` returns a Fernet token: `_get_fernet().encrypt(plaintext.encode()).decode()`
  — a base64url string of the form `gAAAAA…` (`netcanon/security/credentials.py:227-233`).
- Everything **else** in the file (id, name, type_key, **host**, port, **username**, notes,
  os_version, model, detected_facts, created_at) is **plaintext JSON**. Only the two password
  fields are ciphertext.
- Write is atomic temp-then-rename (`device_profile_store.py:69-73`).

`load_all()` reads the JSON back, decrypts the two credential fields via
`migrate_credential_fields(...)` → `decrypt_field(...)`, and re-hydrates a `DeviceProfile`
with plaintext credentials (`device_profile_store.py:99-125`,
`netcanon/security/migration.py:18-35`, `credentials.py:246-263`).

**Test-verified, not aspirational:** `tests/unit/test_device_profile_store.py:124-133`
(`test_password_is_encrypted_on_disk`) saves a profile then asserts the plaintext password
string does **not** appear in the on-disk JSON bytes. The encrypt/decrypt round-trip and the
random-IV property are also tested in `tests/unit/test_credentials.py:107-149`.

### 2.3 Legacy plaintext migration (one-shot, transparent)

On load, any credential field that fails Fernet decryption (`InvalidToken`) is assumed to be
a legacy pre-encryption plaintext value, returned as-is, and the file is immediately re-saved
encrypted (`device_profile_store.py:104-118`, `credentials.py:246-263`,
`migration.py:27-35`). Documented in the module docstring (`device_profile_store.py:11-15`)
and `SECURITY.md:155-161`.

---

## 3. The Fernet key — where it lives per resolution tier (THE load-bearing fact)

The key is resolved lazily, first-hit-wins, by `_resolve_key()`
(`netcanon/security/credentials.py:156-211`):

| Tier | Source | Resolved by | Key on disk in data-dir? | Key co-located with ciphertext? |
|---|---|---|---|---|
| **1** | `NETCANON_FERNET_KEY` env var | `credentials.py:163-167` | **No** | **No** — out-of-band (orchestrator/env) |
| **2** | OS keyring (Win DPAPI / macOS Keychain / Linux SecretService) | `credentials.py:169-190` (`_read_keyring`/`_write_keyring` 82-114) | **No** | **No** — out-of-band (OS secret store) |
| **3** | File fallback `$NETCANON_DATA_DIR/.fernet_key` | `credentials.py:192-211` (`_read_key_file`/`_write_key_file` 117-153) | **Yes**, plaintext 44-char base64 | **YES** — same volume as `devices/*.json` |

Key facts to carry forward:

- **Tier 3 is the zero-config bootstrap.** If neither the env var nor a usable keyring backend
  exists, a fresh key is generated and written **plaintext** to `$NETCANON_DATA_DIR/.fernet_key`
  with best-effort `chmod 0o600` (a **no-op on Windows** — `credentials.py:125-153`). A
  `WARNING` log fires (`credentials.py:204-210`). This is the **typical Docker / headless**
  path when the operator doesn't inject the env var.
- The key-file directory is `Path(os.environ.get("NETCANON_DATA_DIR", "data"))`
  (`credentials.py:70-79`) — i.e. the **same data root** that holds `devices/`, `schedules/`,
  `jobs/`, and (by default) `configs/`. So in Tier 3 the decryption key sits **right next to**
  the ciphertext it decrypts.
- `.fernet_key` is gitignored (`.gitignore:23-28`, both `.fernet_key` and `**/.fernet_key`),
  so it won't be committed, but it is present in any data-dir read / disk image / volume snapshot.
- Key-loss == credential-loss is an accepted risk (`SECURITY.md:502`); profiles are
  re-enterable.

This 3-tier scheme is the existing answer to "where does the key live per run mode" — and it
**already** offers the env-var separation that SOPS-with-an-external-key-backend would offer
(Tier 1), and the OS-keyring separation desktop already uses (Tier 2). The design/review
phases should weigh SOPS against *this*, not against a strawman plaintext store.

---

## 4. Schedule store — same credential treatment (legacy inline lists only)

`FileScheduleStore` writes `{data_dir}/schedules/{id}.json`. Legacy inline `devices[]`
entries carry `password`/`enable_password`; these are **Fernet-encrypted** with the same
`encrypt()` on save and decrypted/legacy-migrated on load
(`netcanon/storage/schedule_store.py:43-64,73-104`). New-style schedules reference
`device_profile_id`s and **carry no credentials of their own** (`schedule_store.py:9-13`).
Same at-rest format and key as §2/§3.

---

## 5. Backup artifacts — RAW device configs, NO at-rest sanitization (the bigger exposure)

This is the larger, *unencrypted* secret surface and the place where netcanon's own
credential encryption does **not** help.

- **What is written:** `_process_one_device` calls `raw_output = collector.collect(...)` then
  `storage.save(content=raw_output, ...)` — the device's `running-config` (or vendor
  equivalent) is written to disk **verbatim** (`netcanon/services/backup_runner.py:233-241`).
- **Where:** `{configs_dir}/{DeviceType}/{safe_host}/{DeviceType}_{host}_{ts}.{ext}` as
  **plain text**, UTF-8, atomic temp-rename (`netcanon/storage/file_store.py:1-19,162-186`).
  The module docstring's own first sentence: "Configurations are saved as **plain text
  files**" (`file_store.py:1-3`).
- **What's in them:** these configs routinely contain the *device's own* secrets —
  hashed/reversible local passwords (`$9$…`, Cisco type-7, `$1$/$5$/$6$`), SNMP community
  strings, RADIUS/TACACS shared keys, IKE/IPsec PSKs, certificate material. **None of this is
  encrypted, hashed, or redacted at rest.** It is stored exactly as the device emitted it.
- **Sidecar:** an optional `{filename}.meta.json` records `{"device_profile_id": "..."}` only
  — a UUID, **no secrets** (`file_store.py:188-196`).
- **No size/secret scrubbing on the write path** beyond a 50 MB size ceiling
  (`file_store.py:100,157-161`).

### 5.1 The sanitizer is ON-DEMAND only — it does NOT touch stored backups

There is a sanitizer (`netcanon/tools/sanitize.py`, exposed at `POST /api/v1/sanitize` and the
`netcanon sanitize` CLI), but it operates on an **uploaded** config the operator hands it for
bug-reporting, running parse→redact→render and returning the sanitized text in the HTTP
response (`netcanon/api/routes/sanitize.py:1-14,43-91`). It is **never** invoked on the
backup write path (`backup_runner.py` does not import or call it). Therefore:

> **The most voluminous secret material netcanon stores — the fetched device configs — is at
> rest in cleartext, and nothing in the product encrypts or redacts it at rest.**

This matters for the SOPS verdict: device-credential *encryption* is already solved; the
realistically larger "secrets on disk" exposure is the `configs/` tree, which is plaintext.
Any "should we encrypt secrets at rest" conversation that only looks at `devices/*.json` is
looking at the smaller half.

---

## 6. Non-secret state and supporting stores (for completeness)

| Store / file | Path | Contents | Secret? |
|---|---|---|---|
| Job history | `{data_dir}/jobs/{id}.json` | `BackupJob`: id, status, per-device host/status/error/duration, `ConfigRecord` metadata | **No credentials.** `BackupResult`/`BackupJob` carry no password fields (`netcanon/models/backup.py:61-117`); `FileJobStore.save` dumps the model verbatim (`netcanon/storage/job_store.py:37-48`). Host/IP + error strings are network-identifying but not secret. |
| SSH host-key TOFU store | `{effective_data_dir}/known_hosts` | Device SSH **public** host keys learned on first connect | **Not secret** — public keys, OpenSSH `known_hosts` format. It is *security-relevant* (tamper would weaken MITM detection) but contains no confidential material. Written only in `tofu` mode (`netcanon/collectors/hostkey.py:41-90`), default `auto_add` writes nothing (`config.py:108`). |
| Egress allow-list | n/a (code-only) | Loopback/link-local block policy | **Config, not secret.** A boolean `block_private_egress` toggle + pure-function IP checks (`netcanon/services/egress.py`, `config.py:107`). No stored state. |
| Definitions | `{definitions_dir}/**/*.yaml` | Vendor probe/command templates | Not secret (shipped library). |
| `.env` | repo root | `NETCANON_*` settings incl. optionally `NETCANON_FERNET_KEY` | Potentially key-bearing; gitignored (`.gitignore:69-73`). The Fernet key is the only secret that can appear here. |
| Desktop prefs | `%APPDATA%\Netcanon\preferences.json` | paths, port, toggles | Not secret (`netcanon_desktop/preferences.py:3,69`). |

**Data-dir layout** (`config.py:33-37,116-128`): `effective_data_dir` = explicit `data_dir`
if set (desktop prefs / `NETCANON_DATA_DIR`), else `configs_dir.parent`. Under it:
`devices/` (encrypted creds), `schedules/` (encrypted creds), `jobs/` (no creds),
`known_hosts` (public keys), `.fernet_key` (Tier-3 key, plaintext), and typically `configs/`
(plaintext device configs). On the **desktop** the root is `%APPDATA%\Netcanon\`
(`netcanon_desktop/settings.py:40-52,83-85`; README table `netcanon_desktop/README.md:120`),
where Tier 2 (DPAPI keyring) is the default key tier and `.fernet_key` normally does **not**
exist.

---

## 7. The master table: every secret, where, format, who reads it, exposure if data-dir is read

| Secret type | Where stored (path) | At-rest format | Who decrypts/reads it at runtime | Exposed if data-dir is read? |
|---|---|---|---|---|
| Device SSH `password` | `{data_dir}/devices/{id}.json` (field `password`) | **Fernet ciphertext** (`gAAAAA…` base64url) inside plaintext JSON | `FileDeviceProfileStore.load_all` → `decrypt` → `DeviceProfile.password` (plaintext str in memory); reused by `backups._resolve_credentials` → `netmiko/paramiko` (`backups.py:128-136`, `netmiko_collector.py:88`, `paramiko_collector.py:184`) | **Only if the Fernet key is also obtained.** Tier 3: **yes** — key is `.fernet_key` in the same dir. Tier 1/2: **no** — key is out-of-band (env/OS keyring). |
| Device `enable_password` | `{data_dir}/devices/{id}.json` (field `enable_password`) | **Fernet ciphertext** | Same as above; passed as netmiko `secret` (`netmiko_collector.py:91-94`) | Same as above. |
| Legacy schedule inline creds | `{data_dir}/schedules/{id}.json` (`devices[].password`/`enable_password`) | **Fernet ciphertext** | `FileScheduleStore.load_all` → `decrypt` (`schedule_store.py:88-104`) | Same as above (same key). New-style schedules store none. |
| **Fernet master key** | `$NETCANON_DATA_DIR/.fernet_key` (**Tier 3 only**) | **Plaintext** 44-char base64 (chmod 0o600 POSIX; no-op Windows) | `_resolve_key`/`_get_fernet` (`credentials.py:192-224`) — caches a process-global Fernet | **YES, fully** — and it decrypts every credential above. Tier 1 (env) / Tier 2 (keyring): key not in data-dir. |
| **Device-side config secrets** (`$9$`, type-7, SNMP/RADIUS/IKE keys) | `{configs_dir}/{Type}/{host}/*.{ext}` | **Plaintext** (raw device output, verbatim) | Read on demand by config view/migrate/sanitize routes; never decrypted (never encrypted) | **YES, fully.** No at-rest encryption or redaction; sanitizer is on-demand-only (`sanitize.py`), not on the write path (`backup_runner.py:233-241`). |
| SSH host **public** keys (TOFU) | `{effective_data_dir}/known_hosts` (tofu mode) | Plaintext OpenSSH `known_hosts` | `apply_paramiko_policy` / `save_host_keys` (`hostkey.py:46-90`) | **Yes, but not secret** — public keys. Read-exposure is benign; tamper-exposure weakens MITM detection. |
| Job history | `{data_dir}/jobs/{id}.json` | Plaintext JSON | `FileJobStore` (`job_store.py`) | Host/IP + error strings exposed; **no credentials** (`models/backup.py:61-117`). |
| Sidecar metadata | `{configs_dir}/.../{file}.meta.json` | Plaintext JSON | `FileConfigStore.list_configs` (`file_store.py:222-233`) | Profile UUID only — not secret. |

---

## 8. Prose: what is genuinely sensitive-at-rest (candidate SOPS targets) vs not

**Genuinely sensitive at rest (the candidate "encrypt this" set):**

1. **Device login credentials** (`devices/*.json`, legacy `schedules/*.json`). These ARE
   already Fernet-encrypted at rest (test-guarded). The only at-rest weakness is **Tier 3**,
   where the decrypting key (`.fernet_key`) sits in the same data-dir as the ciphertext — so
   a data-dir read defeats the encryption. Tier 1 (env) and Tier 2 (OS keyring) have **no**
   such co-location.
2. **The fetched device configs** (`configs/**`). These are **plaintext** and contain real
   device secrets (hashed/reversible passwords, SNMP/RADIUS/IKE keys). This is the **largest
   cleartext secret surface in the product** and is the one place the existing credential
   encryption doesn't reach. If "secrets on disk" is the threat, this is the target that most
   matters — and notably it is bulk, high-volume, frequently-written content that an
   encrypt-at-rest scheme would have to wrap on every backup.

**Not meaningfully sensitive at rest (do NOT spend SOPS on these):**

- The **Fernet key under Tier 1/2** — it's already off the data volume; nothing to add.
- **`known_hosts`** — public keys; the property that matters is integrity, not confidentiality.
- **`jobs/`**, sidecars, prefs, definitions, egress config — no confidential payload.

**Implication for the SOPS verdict (handed to D1/D2/V1, not decided here):** netcanon's secret
problem decomposes into (a) a *small, already-encrypted* credential set whose only gap is
key-co-location in the zero-config Tier-3 mode, and (b) a *large, fully-plaintext* config-artifact
set the product deliberately stores raw. SOPS is a **file-level encrypt-at-rest-in-a-repo** tool;
its natural fit is small declarative secret files that live in version control, decrypted at
render/deploy time by an out-of-band key (the Kontroll model). Neither netcanon secret class
is that shape: credentials are runtime-mutable per-profile JSON the operator never commits
(already covered by Fernet + the env-var tier for key separation), and the config artifacts are
bulk runtime output. The recurring question the design phase must answer honestly is **"where
does the SOPS key live in each run mode, and does it co-locate with the ciphertext?"** — because
in the Tier-3/Docker zero-config case it would face the *exact same* co-location problem
`.fernet_key` already has, and in the desktop case the OS keyring (DPAPI) already provides the
out-of-band key SOPS would otherwise need an age/gpg key to replicate.

---

## 9. Pointers for peer reports

- **R2 (Kontroll SOPS)**: contrast Kontroll's *committed* `*.sops.yml` + out-of-band age key
  (control-VM) against netcanon's *gitignored, runtime-mutable* `devices/*.json` + 3-tier
  key. The "secret file is in git" precondition that makes SOPS valuable in Kontroll does not
  hold for any netcanon secret.
- **R3 (runtime/deploy)**: the key-location matrix in §3 is the per-run-mode key story already
  — Tier 1 env (Docker/server), Tier 2 keyring (desktop/MSI), Tier 3 file (zero-config Docker).
  Map any SOPS key backend onto these same four modes and check for co-location.
- **V1 (review)**: fact-check the "Tier-3 key co-locates with ciphertext" claim against
  `credentials.py:70-79,192-211` + `.gitignore:23-28`, and the "configs stored raw, sanitizer
  is on-demand-only" claim against `backup_runner.py:233-241` + `sanitize.py`. Both are the
  spine of any NO-GO / GO-WITH-NARROW-SCOPE argument.

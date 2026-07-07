# 40 — Adversarial verification: security lens (reports 10 / 11 / 12)

Verifier: Fable adversarial pass. Method: opened every cited `file:line`, tried to
**refute** each claim against the known-good posture (127.0.0.1 default bind, fail-closed
`netcanon serve`, opt-in egress allow-list, TOFU host-key default). Re-ran or wrote my own
read-only `py` probes for the reproducible claims. Default verdict = REFUTED unless I could
independently confirm reachability.

**Posture verdict: GO-WITH-FIXES.** No blocker. The known-good posture holds — I found no
unauthenticated-remote exploit on any default or *recommended* deployment. Two genuine
credential-hygiene MAJORs survive (both bounded / same-box), the rest downgrade to minor or
were overstated on a stale premise.

---

## Report 10 — Web/API

### MAJOR-1 — Path traversal via `job_id` — **CONFIRMED (defect) / DOWNGRADED to MINOR**

- **Defect is real.** Reproduced on Windows: `Path(jobs_dir) / "..\\..\\secret.json"` and
  `"../../secret.json"` both resolve **outside** the jobs dir (`is_relative_to` = False),
  while a bare UUID stays inside. `job_store.py` (`load_one:93`, `save:43`, `list_job_ids:120`)
  and `job_registry.py:188` (`__contains__`) take the raw `job_id` with **no** validation —
  a genuine asymmetry vs `FileConfigStore.resolve_path` (`file_store.py:282-299`), which has
  the `_FILENAME_RE` + `is_relative_to` double guard. `get_job` (`backups.py:261-275`) passes
  the raw path param straight through. The existence-oracle (404 vs 500) and bounded
  `BackupJob`-shaped disclosure are as described.
- **Severity basis is FALSE.** The report rates it MAJOR because "the published Docker image
  sets `NETCANON_HOST=0.0.0.0` and runs `uvicorn netcanon.main:app` directly, which never
  invokes `bind_refusal_reason`." The **current** `Dockerfile:118` ENTRYPOINT is
  `["netcanon", "serve"]`, and `cli.py:_cmd_serve` (190-217) calls `bind_refusal_reason`
  **before** `uvicorn.run` and exits 2 on refusal. So a keyless `0.0.0.0` container **refuses
  to start**. The stale `uvicorn`-entrypoint claim survives only in a 2026-06 SOPS-eval doc.
- **Actual reachability:** exposed posture requires either `NETCANON_API_KEY` (→ the
  `/api/v1/backups/{job_id}` route is bearer-gated, `main.py:313` — post-auth by a token
  holder) or an explicit `NETCANON_ALLOW_INSECURE_BIND=1` (a conscious, documented insecure
  opt-out where *all* data is already exposed). On the default loopback bind it is a
  **local-only** existence oracle / bounded disclosure.
- **Verdict:** DOWNGRADED to MINOR. Real code defect, cheap fix (mirror the config-store guard
  or `pattern=UUID` on the path param), worth doing — but not pre-auth on any default or
  recommended posture. Evidence killing the MAJOR: `Dockerfile:118` + `cli.py:201-206`.

### MAJOR-2 — API key gates `/api/v1` but not UI — **CONFIRMED (asymmetry) / DOWNGRADED to MINOR**

- **Factually true:** `main.py:319` mounts `ui_router` with no auth dep; `ui.py` `/jobs`
  (202), `/devices` (363), `/configs` render device host/username/notes + job/config
  inventory unauthenticated.
- **But it's documented, intended behavior.** `auth.py:16-21` states the key is "an orthogonal
  front door, not a replacement for the reverse proxy" and "`/health` and the UI routes are not
  bearer-gated." On the recommended posture (reverse proxy terminates auth for the whole app)
  there is no gap. The residual risk is a *misconfiguration* — operator sets a key, exposes the
  UI directly with no proxy, and believes the key protects the browser pages.
- **Verdict:** DOWNGRADED to MINOR. Real false-sense-of-security / data-exposure asymmetry, but
  it does not defeat the known-good posture; fix is a loud doc note or extending the optional
  gate to the UI routes. The report author explicitly invited this downgrade.

### MINOR-3 — CSRF on no-body POSTs (`/open`) — **CONFIRMED / MINOR**
`configs.py:126 open_config` takes only path params (no body → "simple request", no preflight);
tree-wide grep confirms **no** `CORSMiddleware`/`add_middleware` in `netcanon/` (all hits are
docs). Real cross-site side-effect, but gated on `open_in_editor` (off by default, desktop-only
+ loopback) and only opens a file (no exfil). MINOR.

### MINOR-4 — No Content-Security-Policy — **CONFIRMED / MINOR**
`main.py:297-302 add_security_headers` sets only `X-Content-Type-Options` + `X-Frame-Options`.
Defense-in-depth only (autoescape + client-side escaping already mitigate XSS). MINOR.

### MINOR-5 — `/migration/detect` `raw_text` uncapped — **CONFIRMED / MINOR**
`migration.py:131 MigrationDetectRequest.raw_text: str | None = None` (no cap) vs
`models/migration.py:663 MigrationPlanRequest.raw_text = Field(..., max_length=10_000_000)`.
Genuine parity gap (pydantic buffers the full body before the processing-side truncation).
Same-box on default bind / token-holder on exposed. MINOR.

---

## Report 11 — Secrets & credentials

### Finding 1 — Schedules echo legacy inline creds in plaintext — **CONFIRMED / MAJOR**
Probe: `BackupSchedule(... devices=[ScheduleDevice(password='PlainTextPw!',
enable_password='EnPw!')]).model_dump_json()` → both plaintext values present. `schedules.py:279`
serves `response_model=list[BackupSchedule]`; `schedule_store.py:91-95` decrypts inline creds
in place at load. `ScheduleDevice.password/enable_password` are plain `str` (not `SecretStr`),
no serializer scrub — a genuine break of the `DeviceProfilePublic` write-only paradigm on its
sibling read surface. **Bounded:** legacy-only (`ScheduleCreate` can no longer create inline
devices), so it needs a pre-profile schedule file on disk. High-sensitivity data (SSH + enable
passwords over an API) → keep MAJOR; fix is a `BackupSchedulePublic` response model + guard test.

### Finding 2 — Decrypted creds reach ERROR logs via pydantic `ValidationError` — **CONFIRMED / MAJOR**
Probe: a post-decryption profile dict missing required `type_key` → `str(ValidationError)` embeds
`input_value={...'enable_password': 'EnableSecret99'}` — the tail credential survived pydantic's
**middle**-truncation verbatim (the earlier `password` was truncated away, but field order puts
`enable_password` last). `device_profile_store.py:120-123` and `schedule_store.py:110-113` log
`"CORRUPT FILE SKIPPED: %s — %s", path.name, exc` at ERROR → stderr + rotating file. This is the
CodeQL clear-text-logging HIGH class the project's own CI gates against; the codec layer already
avoids it (`codecs/base.py:105-112` formats loc+msg only). Trigger is narrow (decryptable-but-
invalid file), but a future required field added across an upgrade would dump **every** profile's
credential at startup. Same-box exposure (logs), but logs get shared in bug reports → defeats
encryption-at-rest in the recovery path. Keep MAJOR.

### Finding 3 — SNMP community logged at DEBUG — **CONFIRMED / MINOR**
`snmp_names.py:149-154` logs `current=%r` with the parsed community string verbatim; all four
sibling orchestrators log counts only (even the rename_map here is summarised as `N-entry dict`).
DEBUG-only + same-box. MINOR.

### Finding 4 — SECURITY.md cites a test that doesn't verify the claim — **CONFIRMED / MINOR**
`SECURITY.md:192-193` "Credential fields are **never logged** (verified by
`tests/unit/test_logging_config.py`)" — grep of that file for `password|credential|secret`
(case-insensitive) = **0 matches**. Citation is false, and per Finding 2 the claim itself is
currently false in the corrupt-file path. Doc-honesty MINOR; fix alongside Finding 2.

---

## Report 12 — SSH backup & egress

### MAJOR-1 — `_drain` unbounded read loop — **CONFIRMED (defect) / DOWNGRADED to MINOR**
`paramiko_collector.py:342-361`: `deadline = time.monotonic() + timeout` is reset **inside** the
`recv_ready()` branch on every chunk, with no absolute wall-clock ceiling and no `buf` size cap —
a device emitting ≥1 byte per <0.5 s loops forever with unbounded memory. Genuinely asymmetric
with the hardened sibling `_collect_output:418` (sets the deadline **once**, fails closed at
`_MAX_SECONDS`). The defect and the OOM/hung-worker impact are real. **But** exploitation requires
the operator to point netcanon at a hostile/broken device (trust-anchor model) or an MITM on the
first TOFU connect — not remotely triggerable by an unauthenticated attacker, availability-only.
DOWNGRADED to MINOR; fix is cheap and recommended (give `_drain` an absolute cap + idle-only reset,
mirroring `_MAX_SECONDS`).

### MINOR-1 — Egress allow-list lets `0.0.0.0` / `::` through — **CONFIRMED / MINOR**
Reproduced: `_is_blocked_ip(0.0.0.0)`/`(::)` = False (unspecified, not loopback/link-local);
`validate_host` accepts both. `127.0.0.1`, `169.254.169.254`, `::ffff:127.0.0.1` all stay blocked.
Only active when `block_private_egress` is opt-in enabled; residual reach is loopback-only (the
metadata endpoint stays blocked), so not a metadata-SSRF hole. MINOR; fix = also reject
`is_unspecified`.

### MINOR-2 — `known_hosts` write race (AutoAddPolicy saves outside the lock) — **CONFIRMED / MINOR**
Verified against installed **paramiko 4.0.0**: `SSHClient.load_host_keys` sets
`self._host_keys_filename`, and `AutoAddPolicy.missing_host_key` then calls
`client.save_host_keys(client._host_keys_filename)` — that write fires inside `client.connect()`
(`paramiko_collector.py:181/277`), which runs **outside** `_KNOWN_HOSTS_LOCK` (hostkey.py:74/99
only wrap load + the explicit `persist_paramiko_host_keys`). `save_host_keys` opens `"w"`
(truncate, non-atomic). Real corruption/re-TOFU race, but narrow: concurrent **first-time** TOFU
connects via the `paramiko_shell` strategy only (netmiko path saves under the lock). MINOR.

### Out-of-lens observation (not a security finding)
`cisco_more_paging` declared in YAML/schema but never read by any collector — flagged by report 12
for the functional/UX lens; no security impact (undismissed `--More--` fails closed via timeout).
Out of scope for this verdict.

---

## Confirmed clean (spot-checked the reviewers' negative claims — no dispute)
- `bind_refusal_reason` genuinely enforced in `cli.py:201-206` before `uvicorn.run`; Docker
  ENTRYPOINT is `netcanon serve` (`Dockerfile:118`).
- `require_api_key` (`auth.py:39-61`): fail-closed only when a key is set, `hmac.compare_digest`,
  no key value logged.
- YAML `safe_load` everywhere; no `pickle`/`eval`/`exec`/`shell=True`; config-store traversal
  guard solid.
- Fernet 3-tier fail-closed; `SecretStr` in transit; collectors log username-only at DEBUG.
- IPv4-mapped-IPv6 unwrap blocks `::ffff:169.254.169.254`; decimal/octal integer IP forms
  rejected by `ipaddress`.

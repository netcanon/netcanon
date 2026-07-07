# 01 — Security & trust boundaries (Fable full-review, v0.5.3 @ 8598d74)

**Reviewer lens:** SSH backup runner + egress allow-list + host-key handling;
Fernet credential encryption + write-only public models; sanitizer/redaction;
FastAPI auth + per-route authz; serve bind / fail-closed; CSP/headers; any path
a parsed-config value or secret could reach logs/errors/responses.

**Method:** full read of `api/` (routes/auth/deps/_errors), `main.py`,
`config.py`, `cli.py`, `logging_config.py`, `services/{backup_runner,egress}`,
`security/{credentials,migration}`, `collectors/*`, `storage/*`,
`models/{backup,device,device_profile,schedule,validators}`, `tools/sanitize.py`,
`Dockerfile`, plus the three prior 2026-07-03 security lens reports
(10-web / 11-secrets / 12-ssh) to avoid re-reporting. Findings reproduced with
read-only `py -c` probes of the local package (no server, no mesh).

## Verdict

**The API + trust boundaries are very well hardened, and every MAJOR/MINOR from
the 2026-07-03 pass has been remediated in v0.5.x** (verified in-tree):

- Job-store path traversal (prior 10-web MAJOR-1) → `GET /api/v1/backups/{job_id}`
  now pins `job_id` to a strict UUID regex (`backups.py:284-295`); profile/schedule
  delete/update check in-memory dict membership before touching the store.
- Docker unauth exposure premise (prior 10-web MAJOR-1/2) → the image `ENTRYPOINT`
  is `["netcanon","serve"]` (`Dockerfile:118`), NOT bare uvicorn, so a keyless
  `0.0.0.0` container **fails closed** via `bind_refusal_reason`. UI-open-when-key-set
  is now explicitly documented in `SECURITY.md:632`.
- Schedule inline-cred echo (prior 11-secrets MAJOR-1) → `BackupSchedulePublic` +
  `ScheduleDevicePublic` now response-model every schedule route.
- Plaintext creds in ValidationError logs (prior 11-secrets MAJOR-2) →
  `scrub_exc_for_log` used in both `device_profile_store.py:126` and
  `schedule_store.py:132`.
- SNMP community DEBUG log (prior 11-secrets MINOR-3) → now logs `has_community=%s`
  bool, not the value (`snmp_names.py:152`).
- `_drain` unbounded read (prior 12-ssh MAJOR-1) → `_DRAIN_MAX_SECONDS` /
  `_DRAIN_MAX_BYTES` caps added (`paramiko_collector.py:70-71,383-403`).
- Egress unspecified-address bypass (prior 12-ssh MINOR-1) → `_is_blocked_ip` now
  checks `is_unspecified` (`egress.py:52`).

**One new finding survives**, in the exact same class the maintainers already
chose to fix once (the unspecified-address egress gap): the egress allow-list
does not unwrap IPv6 *transition* formats, so a NAT64/6to4/IPv4-compatible
literal embedding the cloud-metadata endpoint or loopback slips through — even
though the sanitizer in the same repo unwraps precisely these formats for the
identical "embedded routable IP" reason. Low severity (opt-in guard + unusual
host routing needed for full metadata reach), but a real, reproduced gap in a
documented-purpose control.

Two prior-review MINORs remain open by design-choice and are noted (not
re-raised as fresh) at the end.

---

## MINOR-1 — Egress allow-list does not unwrap IPv6 transition formats (NAT64 / 6to4 / IPv4-compatible) → loopback / metadata reach

**Severity:** MINOR (LOW). **Confidence:** confirmed (reproduced).

**Where:** `netcanon/services/egress.py:38-58` (`_is_blocked_ip`), reached from
`assert_egress_allowed` (`egress.py:61-113`) via `create_backup`
(`api/routes/backups.py:208-218`) and the schedule trigger
(`api/routes/schedules.py:227-230`), gated on `Settings.block_private_egress`.

**The defect:** `_is_blocked_ip` blocks `is_loopback` / `is_link_local` /
`is_unspecified` and unwraps **only** `ipv4_mapped` (`::ffff:a.b.c.d`). It does
NOT unwrap the other IPv6 transition formats — NAT64 (`64:ff9b::/96` and the
RFC 8215 `64:ff9b:1::/48`), 6to4 (`2002::/16`), Teredo, or IPv4-compatible
(`::a.b.c.d`) — which also carry a routable IPv4 in their low bits but classify
as none of loopback/link-local/unspecified at the v6 layer.

**Reproduced** (read-only probe of the local package):
```
169.254.169.254        _is_blocked_ip=True   assert_egress=BLOCKED   (direct link-local)
::ffff:169.254.169.254 _is_blocked_ip=True   assert_egress=BLOCKED   (ipv4_mapped — handled)
64:ff9b::a9fe:a9fe     _is_blocked_ip=False  assert_egress=ALLOWED   (NAT64 → 169.254.169.254)
64:ff9b:1::a9fe:a9fe   _is_blocked_ip=False  assert_egress=ALLOWED   (NAT64 RFC8215 → metadata)
2002:a9fe:a9fe::       _is_blocked_ip=False  assert_egress=ALLOWED   (6to4 → 169.254.169.254)
::7f00:1               _is_blocked_ip=False  assert_egress=ALLOWED   (IPv4-compat → 127.0.0.1)
2002:7f00:0001::       _is_blocked_ip=False  assert_egress=ALLOWED   (6to4 → 127.0.0.1)
```
All three literals are also accepted by `models/validators.py:validate_host`, so
they are reachable as a `DeviceTarget.host` / `DeviceProfile.host`
(verified: `validate_host("64:ff9b::a9fe:a9fe")` returns the value unchanged).

**Failure scenario:** operator enables `NETCANON_BLOCK_PRIVATE_EGRESS=true`
(the network-exposed web posture the guard exists for) believing loopback +
link-local (incl. `169.254.169.254`) are blocked. A caller submits a backup
target `64:ff9b::a9fe:a9fe` (or a hostname resolving to it). `assert_egress_allowed`
passes it. On a backup host that has NAT64 configured (CLAT / a NAT64 gateway on
the management path), the SSH connect is translated to `169.254.169.254` and the
guard's headline purpose — blocking the metadata endpoint — is defeated. The
loopback variants (`::7f00:1` / 6to4-wrapped `127.0.0.1`) are lower-value
(loopback-only, and IPv4-compatible is deprecated on modern stacks).

**Honest reachability caveat:** reaching the metadata endpoint this way needs the
*host* to actually route the transition prefix (NAT64/6to4 relay), which is
uncommon on a default cloud VM — hence MINOR, not MAJOR. But it is a genuine gap
in a documented control, in the same class the maintainers already fixed for the
unspecified address (prior 12-ssh MINOR-1), and the codebase demonstrably knows
this class: `tools/sanitize.py:_embedded_public_ipv4` (lines ~1019-1053) unwraps
6to4 / ipv4_mapped / IPv4-compatible / NAT64 / Teredo for redaction for exactly
the "embeds a routable IPv4 yet classifies as private/reserved at the v6 layer"
reason. The egress guard just never got the same treatment.

**Fix:** in `_is_blocked_ip`, after the current checks, also test the embedded
IPv4 of transition formats and block when that IPv4 is loopback/link-local/
unspecified. The sanitizer's `_embedded_public_ipv4` is the ready-made shape —
extract a shared `_embedded_ipv4(addr) -> IPv4Address | None` helper (6to4 via
`addr.sixtofour`, `addr.ipv4_mapped`, `addr.teredo`, the two NAT64 nets, and the
`::a.b.c.d` low-word case) and reuse it in both modules. Minimal version:
```python
def _is_blocked_ip(ip):
    if ip.is_loopback or ip.is_link_local or ip.is_unspecified:
        return True
    for cand in _embedded_ipv4s(ip):          # ipv4_mapped, sixtofour, teredo, NAT64, ::a.b.c.d
        if cand.is_loopback or cand.is_link_local or cand.is_unspecified:
            return True
    return False
```

---

## Still-open from the 2026-07-03 pass (noted, not re-raised as fresh)

These were reported previously and remain open by an apparent design choice; I
verified they are unchanged at 8598d74. Listing for completeness, not as new work.

- **CSRF on no-body "simple request" POSTs** (prior 10-web MINOR-3): no CSRF
  token / custom-header / `Sec-Fetch-Site` check, no CORS middleware. On the
  desktop build (`open_in_editor=True`, loopback, keyless) a visited malicious
  page can `fetch('http://127.0.0.1:8000/api/v1/configs/<guessable>/open',
  {method:'POST',mode:'no-cors'})` and pop a local file in the OS editor
  (`configs.py:126`). `/definitions/reload` + `/schedules/{uuid}/toggle` are the
  other no-body POSTs (low impact: harmless / need a UUID). JSON-body POSTs are
  preflight-protected.

- **`known_hosts` AutoAddPolicy save race** (prior 12-ssh MINOR-2): `tofu` mode
  still installs `paramiko.AutoAddPolicy()` (`hostkey.py:82-84`), whose
  `missing_host_key` calls `save_host_keys` (truncate + line-by-line, non-atomic)
  *inside* `client.connect()` (`paramiko_collector.py:197`), which runs OUTSIDE
  `_KNOWN_HOSTS_LOCK`. Two concurrent first-time TOFU connects via the
  `paramiko_shell` strategy can interleave and corrupt the shared store,
  re-opening the first-use trust window. Narrow trigger; netmiko path is unaffected
  (its preflight `HostKeys.save` is under the lock).

---

## Checked and clean (no finding)

- **Path traversal:** `job_id` UUID-pinned at route (`backups.py:284-295`);
  `FileConfigStore.resolve_path` regex + double `is_relative_to` guard
  (`file_store.py:300-317`) — verified a regex-matching backslash-traversal
  filename still fails the containment check on Windows; profile/schedule
  delete/update gate on in-memory dict membership (server-uuid keys) before the
  store, so attacker strings 404 first.
- **Auth:** `require_api_key` constant-time `hmac.compare_digest`, opt-in,
  fail-closed only when a key is set; `bind_refusal_reason` gates non-loopback
  binds; Docker entrypoint is `netcanon serve` so keyless `0.0.0.0` fails closed.
- **Secrets:** Fernet `decrypt_field` fail-closed with positive 0x80/57-byte
  token detection; `_fernet_lock` double-checked init (CONC-7); `scrub_exc_for_log`
  on both store load paths; `DeviceProfilePublic` / `BackupSchedulePublic`
  write-only creds; `SecretStr` in transit; only `username` logged (DEBUG).
- **SSH:** TOFU default, auth-less host-key preflight (KEX-before-auth, no creds
  sent), `_drain` now time+byte capped, static definition command sequences only
  (no request-controlled data into `shell.send`), fail-closed `_collect_output`.
- **Sanitizer:** field-typed redaction across every `CanonicalIntent` surface;
  `dropped_tier3_sections` / `raw_sections` / `group_content` / `apply_groups`
  stripped fail-closed; transition-IPv6 unwrap present for redaction; dry-run
  returns originals only to the uploader (same principal).
- **Logging/errors:** `X-Request-ID` echo length+charset-validated (no CRLF/log
  injection); `_errors.py` suppresses paths + multi-line auth blocks; global 500
  handler never echoes tracebacks; no parsed-secret logging at INFO+.
- **CSP/headers:** `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  CSP default-src 'self' (docs variant scoped to jsdelivr); `unsafe-inline`
  tradeoff documented.
- **DoS caps:** `/sanitize` upload cap + `to_thread` offload; `MigrationPlanRequest`
  / `MigrationDetectRequest` `raw_text` both capped at 10 MB; `BackupRequest`
  `max_length=500`; per-job + process-wide backup concurrency ceilings.
- **YAML/exec:** (per prior pass, spot-rechecked) `safe_load` only, no
  pickle/eval/exec/shell=True; `open_config` uses argv (no shell) on the guarded
  resolve_path with an extension allowlist.

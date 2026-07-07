# 10 — Web/API security lens

Reviewer: Fable fresh-eyes pass (web/API security)
Scope: `netcanon/api/` (routes, auth, deps, errors), `netcanon/main.py`,
`netcanon/templates/`, `netcanon/services/`, `netcanon/storage/`.
Method: full read of every route + storage class + the request models they
bind, plus grep sweeps for `eval/exec/os.system/subprocess/yaml.load/pickle/
Template(/|safe/autoescape`, and read-only `py -c` probes of the local
package (no server, no pytest).

## Verdict

The API surface is genuinely hardened — prior passes did real work. YAML is
`safe_load` everywhere, no `pickle`/`eval`/`exec`/`shell=True`, the one
`subprocess` call uses argv (no shell) on a regex-guarded path, Jinja
autoescape is on with zero `|safe` on user data, the config-viewer JS escapes
before every `innerHTML`, `FileConfigStore.resolve_path` has a proper
regex + `is_relative_to` traversal guard, credentials are write-only over the
API and Fernet-at-rest, request bodies are size/length-capped (`BackupRequest`
`max_length=500`, `raw_text` `max_length=10_000_000`, `/sanitize` upload cap),
and `require_api_key` uses `hmac.compare_digest`.

**But two real findings survive**, both authz/path-handling gaps that the
sibling code already knows how to defend and simply didn't apply here:

- **MAJOR** — path traversal via `job_id` in the job store (the one storage
  class with NO traversal guard, unlike `FileConfigStore`).
- **MAJOR** — `NETCANON_API_KEY` gates `/api/v1` but leaves the server-rendered
  UI pages (which render the same device/job/config data) fully open.

Plus three minor items. None re-litigate the adjudicated
bind-127.0.0.1 / SSRF-egress / SEC-01 decisions.

---

## MAJOR-1 — Path traversal in the backup-job store (`job_id` is unguarded)

**Where:**
- `netcanon/storage/job_registry.py:188` — `BackupJobRegistry.__contains__`:
  `return (self._store._dir / f"{job_id}.json").exists()`
- `netcanon/storage/job_store.py:93` — `FileJobStore.load_one`:
  `path = self._dir / f"{job_id}.json"` (also `save` line 43, `list_job_ids` 120)
- Reached from `netcanon/api/routes/backups.py:261` — `GET /api/v1/backups/{job_id}`:
  `if job_id not in jobs: raise 404 … return jobs[job_id]` (calls
  `__contains__` then `__getitem__` → `load_one`), both with the raw path param.

**The defect:** `job_id` flows from the URL straight into a filesystem path
with **no validation and no `is_relative_to` containment check**. Compare
`FileConfigStore.resolve_path` (`file_store.py:265-299`), which deliberately
rejects anything not matching `_FILENAME_RE` *and* re-verifies
`candidate.resolve().is_relative_to(storage_root)`. The job store got neither
guard — the hardening applied to configs was never mirrored here.

**Reachability / exploit (Windows — the primary distribution platform, ships an
MSI):** FastAPI's `str` path convertor matches `[^/]+`, so a percent-encoded
backslash survives routing. `GET /api/v1/backups/..%5C..%5Csecret` decodes
(uvicorn) to `job_id = "..\..\secret"`, which contains no forward slash so it
matches as a single segment; Python `pathlib` on Windows treats `\` as a
separator, so `jobs_dir / "..\..\secret.json"` escapes the data dir.

Confirmed with a read-only probe of the local package:
```
'..\\..\\secret' -> C:\...\tmp\secret.json      | inside jobs dir: False
'../../secret'   -> C:\...\tmp\secret.json      | inside jobs dir: False   (Windows also splits '/')
```
(Forward-slash payloads are blocked at the routing layer because uvicorn
decodes `%2F`→`/` and `[^/]+` won't match across it — the working vector is the
backslash. POSIX is NOT affected: there `\` is an ordinary filename char, so no
traversal occurs.)

**Impact:**
1. Reliable filesystem **existence oracle** for any `*.json` path: a traversed
   path that exists but doesn't parse as a `BackupJob` makes `__contains__`
   return `True`, then `__getitem__` raises `KeyError` → unhandled 500; a
   non-existent path → clean 404. 200 vs 500 vs 404 distinguishes existence.
2. **Disclosure** of any `*.json` on the host that validates as `BackupJob`
   (`models/backup.py:109` requires only `id` + `created_at`, rest defaulted) —
   e.g. another netcanon data dir's job files, sibling backups, etc. Content is
   coerced to the `BackupJob` shape, so it's bounded but real.

**Severity: MAJOR.** It's pre-auth on the documented network-exposed posture:
`netcanon serve` refuses an insecure bind, but the published Docker image sets
`NETCANON_HOST=0.0.0.0` and runs `uvicorn netcanon.main:app` directly, which
never invokes `bind_refusal_reason` — so a keyless 0.0.0.0 Docker deployment
exposes this unauthenticated. Windows-scoped and bounded disclosure keep it out
of blocker territory.

**Fix:** give the job store the same guard as the config store — validate
`job_id` is a bare UUID (or at minimum reject any value where
`(dir / f"{job_id}.json").resolve().is_relative_to(dir.resolve())` is false)
in `FileJobStore.load_one` / `save` / `list_job_ids` and
`BackupJobRegistry.__contains__`. A `job_id: str = Path(..., pattern=UUID_RE)`
on the route would also close it.

---

## MAJOR-2 — `NETCANON_API_KEY` gates `/api/v1` but not the UI that renders the same data

**Where:** `netcanon/main.py:307` (`health_router`, no auth dep) and
`main.py:319` (`ui_router`, no auth dep) — only the `/api/v1` routers get
`dependencies=[Depends(require_api_key)]` (`main.py:311-317`). The UI handlers
in `api/routes/ui.py` read and render the same underlying state:
- `/jobs` (`ui.py:202`) → full job history incl. per-device hosts.
- `/configs` (`ui.py:253`) → every stored config filename (filenames encode
  `DeviceType_host_timestamp`).
- `/devices` (`ui.py:363`) → device-profile inventory: name, **host, username,
  notes** (creds are stripped, but host/username/notes are rendered).
- `/schedules`, `/` → schedule + recent-job metadata.

**The problem:** setting `NETCANON_API_KEY` is the action an operator takes to
"require auth." It gates the JSON API (`GET /api/v1/devices/` etc.) but leaves
the browser pages that display the *same* device inventory, job history, and
config filenames completely open. On a network-exposed deployment where the
operator set a key but the fronting proxy doesn't itself require auth, an
unauthenticated attacker still enumerates the device fleet (hostnames +
usernames) and config inventory via `/devices`, `/jobs`, `/configs`.

**Severity: MAJOR, with an honest caveat.** `auth.py`'s docstring says
"`/health` and the UI routes are not bearer-gated" and frames SEC-01 as "an
orthogonal front door, not a replacement for the reverse proxy," so this is
arguably intended (rely on the proxy for real auth). But it is a genuine
false-sense-of-security trap and a data-exposure asymmetry not covered by the
adjudicated bind/SSRF/SEC-01 list. Verifier may downgrade to minor if the
"proxy terminates all auth" contract is considered sufficient — but at minimum
the key-set-but-UI-open behavior should be documented loudly, or the UI routes
should share the same optional gate (redirecting browsers to a login rather
than 401 if UX is the concern).

---

## MINOR-3 — CSRF on the no-body "simple request" POST endpoints (notably `/open` on desktop)

**Where:** no CSRF token anywhere, and no `CORSMiddleware` is installed
(confirmed — `main.py` has none), so JSON-body endpoints are protected by the
CORS preflight (a cross-site page can't send `application/json` without a
preflight that the server never answers). But three state-changing POSTs take
**no body** and so are "simple requests" a cross-origin page can fire blind:
- `POST /api/v1/configs/{filename}/open` (`configs.py:126`) — opens a stored
  config in the OS editor.
- `POST /api/v1/definitions/reload` (`definitions.py:70`).
- `POST /api/v1/schedules/{schedule_id}/toggle` (`schedules.py:357`).

**Impact:** on the desktop build (`open_in_editor=True`, loopback, no key), a
malicious page the user visits can `fetch('http://127.0.0.1:8000/api/v1/
configs/<guessable-filename>/open', {method:'POST', mode:'no-cors'})` and pop a
local file in the editor (filenames follow the predictable
`DeviceType_host_ts.ext` grammar). `reload` is near-harmless; `toggle` needs a
UUID. DELETE/PUT and all JSON POSTs are safe (non-simple → preflighted).
Low impact, but it's a real cross-site side-effect on a local service.

**Fix:** require a custom header (e.g. `X-Requested-With`) on state-changing
routes, or a same-origin/`Sec-Fetch-Site` check, or a CSRF token on the forms.

## MINOR-4 — No Content-Security-Policy header

**Where:** `main.py:297-302` `add_security_headers` sets only
`X-Content-Type-Options: nosniff` and `X-Frame-Options: DENY`. There is no
`Content-Security-Policy`. XSS is otherwise well-mitigated (Jinja autoescape,
client-side `_cvEscape` before every `innerHTML`, config bytes served as
`text/plain` + nosniff), so this is defense-in-depth only — but a CSP
(`default-src 'self'`) would harden the config-viewer / migrate innerHTML paths
against any future escaping regression. Note the `/docs` page loads Swagger UI
from a CDN, so a CSP would need a `/docs`-specific relaxation.

## MINOR-5 — `/migration/detect` `raw_text` is uncapped (inconsistent with `/plan`)

**Where:** `migration.py:131` — `MigrationDetectRequest.raw_text: str | None =
None` has no `max_length`, whereas `MigrationPlanRequest.raw_text`
(`models/migration.py:663`) caps at `10_000_000`. `detect_codec`
(`services/migration_detect.py:74`) truncates to a probe prefix for
*processing*, so CPU is bounded — but the full body is still buffered into
memory by pydantic before truncation, so a multi-hundred-MB `raw_text` is a
memory-DoS the sibling endpoint already rejects. Add the same `max_length` to
`MigrationDetectRequest.raw_text` for parity.

---

## Checked and clean (no finding)

- **YAML**: `loader.py:283`, `target_profiles.py:471`, `vendors/__init__.py:60`
  all use `yaml.safe_load`. No `pickle`, `eval`, `exec`, `os.system`,
  `shell=True`, `Template(`.
- **`open_config` subprocess** (`configs.py:180-189`): argv form (no shell),
  path via the guarded `resolve_path`, extension allowlist, `open_in_editor`
  off by default, OS errors not echoed to client. Fine.
- **Config path traversal** (`file_store.py:265`): regex + `is_relative_to`
  double guard. Solid — this is the pattern MAJOR-1 is missing.
- **Store IDs**: `ScheduleCreate` / `DeviceProfileCreate` don't declare `id`,
  and pydantic ignores extras, so `id` is always a server uuid4 — no
  client-controlled write path in `save`. DELETE/PUT check in-memory dict
  membership (uuid keys) before hitting the store, so those store paths aren't
  reachable with attacker strings.
- **Templates**: autoescape on, zero `|safe` on user data; user-controlled
  `left/right` filenames in `diff.html` are autoescaped. `job.rendered` reaches
  the DOM only via `_cvRenderHighlighted` (escapes) or `textContent` (safe).
- **Reflected error content**: 404/500 details are JSON for the API surface;
  the themed HTML error page uses only server-side constants.
- **Secrets in responses**: `DeviceProfilePublic` strips creds (guard-tested);
  `SecretStr` on `DeviceCredentials`; `devices_page` additionally builds a
  cred-stripped `profiles_safe` for its JS. `/sanitize?dry_run` returns
  originals only to the uploader (their own input).
- **Auth**: `require_api_key` fails closed only when a key is set, constant-time
  compare, honours empty-key zero-config. `X-Request-ID` echo is length- and
  charset-validated (no log/header injection).
- **SSRF**: backup targets SSH-connect to arbitrary hosts by design; the
  opt-in `block_private_egress` allow-list (`services/egress.py`, incl.
  IPv4-mapped-IPv6 unwrap for `::ffff:169.254.169.254`) is the adjudicated
  mitigation. Not re-litigated.

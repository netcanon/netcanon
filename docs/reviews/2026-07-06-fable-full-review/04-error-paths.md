# Lens 04 — Error paths & failure modes

**Verdict: the error-path surface is unusually well-hardened.** Parse and render
degrade cleanly across the board; the migration pipeline funnels every stage
failure into `MigrationJob.failed`; the SSH runner fails *closed* on truncated
captures; the XML codecs defend against entity bombs; the credential layer fails
closed on undecryptable tokens; concurrency and TOCTOU edges are all fixed
(CONC-3..9). Extensive fuzzing found **zero** parse crashes and **zero**
non-`RenderError` render crashes.

What survived scrutiny is a small tail of *degraded-but-not-crashing* paths:
one opaque 500-family class (non-UTF-8 stored config) that spans many endpoints,
and two minor uncaught-write / wrong-status nits.

## Methodology (what I actually ran)

- **Parse crash fuzz** — `scratchpad/fuzz_parse.py`: 18,252 parses across all 12
  public codecs (sample_input + up to 2 real fixtures each, token-truncated and
  value-mutated per line, plus 12 junk inputs). **0 non-`ParseError` crashes.**
- **Adversarial XML** — truncated / mismatched / deeply-nested / billion-laughs
  against `cisco_iosxe` + `opnsense`. All raise `ParseError`; both reject
  entity bombs in <3 ms.
- **VyOS brace pathology** — 4000-deep open braces, unbalanced, only-braces,
  50k flat lines. Iterative parser, no `RecursionError`, all handled.
- **Render/sanitize crash hunt** — `scratchpad/render_hunt.py`: 90 same-vendor
  sanitize round-trips (the exact `/sanitize` + CLI path) + 242 cross-vendor
  renders. **0 non-`RenderError`/`ParseError` crashes.**
- Read every `except Exception` site, both collectors, all stores, the pipeline,
  and every API route's catch clauses.

---

### Finding 1 — Non-UTF-8 stored config yields an opaque 500 on read / diff / migrate / detect (7+ endpoints)

- **Severity:** MEDIUM
- **Confidence:** confirmed (reproduced `get_content` behavior; all four route catch-clauses read directly)
- **File:** `netcanon/storage/file_store.py:263` (`get_content`) — consumed unguarded by `netcanon/api/routes/configs.py:87`, `netcanon/api/routes/_migration_helpers.py:89`, `netcanon/api/routes/configs.py:326`, `netcanon/api/routes/migration.py:681`

**Failure scenario:**
`FileConfigStore.get_content` does `resolve_path(filename).read_text(encoding="utf-8")`
with **no `errors=` argument**. A stored config whose bytes are not valid UTF-8
(e.g. a CP1252 / latin-1 capture with a non-ASCII banner or interface
description, a manually-restored backup, or a legacy capture from before the
collectors decoded with `errors="replace"`) raises `UnicodeDecodeError`.

Reproduced:
```
get_content *** UNCAUGHT-BY-ROUTES UnicodeDecodeError
  'utf-8' codec can't decode byte 0xff in position 14: invalid start byte
```

`list_configs()` reads only the filename + `stat` (never the content), so the
bad file **is listed and selectable in the UI**. But every consumer of
`get_content` catches **only `FileNotFoundError`**:

- `GET /api/v1/configs/{filename}` — `configs.py:87` (`except FileNotFoundError`)
- `POST /api/v1/configs/diff` — `configs.py:326` (`except FileNotFoundError`)
- `POST /api/v1/migration/detect` — `migration.py:681` (`except FileNotFoundError`)
- `resolve_input_text` → all 7 `/migration/plan*` + `/render` endpoints — `_migration_helpers.py:89` (`except FileNotFoundError`)

So the `UnicodeDecodeError` propagates to the global handler and returns a bare
`500 {"detail":"Internal Server Error"}`. Net UX: a file the operator can see in
the config list 500s on *every* action (open, diff, translate) with no
actionable message — indistinguishable from a server bug. (The server itself
does not crash and no stack reaches the client; the stack is logged.)

**Fix:** decode the same way the rest of the stack already does. The collectors
(`netmiko`/`paramiko`) and the `/sanitize` endpoint all decode with
`errors="replace"`; match them at the single choke point:
```python
# file_store.py get_content
return self.resolve_path(filename).read_text(encoding="utf-8", errors="replace")
```
That makes reads lossy-but-successful (a `�` in a banner never blocks a
translation). If a byte-exact contract is preferred instead, catch
`UnicodeDecodeError` alongside `FileNotFoundError` in the four route sites and
return `422`/`400` ("stored config is not valid UTF-8"). The one-line store fix
is preferable — it fixes all seven endpoints at once and needs no per-route
change.

---

### Finding 2 — CLI `sanitize` output write is unguarded; an unwritable `-o` path dumps a raw traceback (asymmetric with the guarded input read)

- **Severity:** MINOR
- **Confidence:** confirmed (read; line is outside any try/except)
- **File:** `netcanon/cli.py:183`

**Failure scenario:**
`_cmd_sanitize` wraps the **input** read in `try/except OSError` → clean
`error: cannot read ...` + exit 2 (`cli.py:137-140`). The **output** write is
not:
```python
if args.output:
    Path(args.output).write_text(result.sanitized_text, encoding="utf-8")
```
`netcanon sanitize -i cfg.txt -o /nonexistent/dir/out.txt` (missing parent dir,
read-only target, or a path that is a directory) raises `OSError` →
uncaught → Python prints a full traceback and exits 1. Same asymmetry for the
`--dry-run=false` no-output-arg path is fine (stdout), but the explicit-output
path is the common one for a redaction workflow, and a redaction tool throwing a
traceback right after doing the redaction work is a poor failure mode.

**Fix:** wrap the write to mirror the input-read handler:
```python
if args.output:
    try:
        Path(args.output).write_text(result.sanitized_text, encoding="utf-8")
    except OSError as e:
        print(f"error: cannot write {args.output!r}: {e}", file=sys.stderr)
        return 2
```

---

### Finding 3 — `open_config` returns 500 (not the intended 501) when the OS helper binary is missing; create/update profile 500s on disk-write failure

- **Severity:** MINOR
- **Confidence:** confirmed (read)
- **File:** `netcanon/api/routes/configs.py:188-213`, `netcanon/api/routes/device_profiles.py:100` / `:144`

**Failure scenario (a) — open-in-editor status mislabel:**
On Linux/macOS `open_config` runs `subprocess.run(["xdg-open", path], check=True)`.
If `xdg-open` is not installed (headless Linux running in desktop mode) the call
raises `FileNotFoundError` (missing executable) → caught by the broad
`except Exception` at `configs.py:202` → `500` "The OS refused to open…". The
dedicated `except NotImplementedError → 501` branch (meant for "this platform
can't open files") never fires for the missing-binary case, so a genuinely
platform-can't-do-this condition is reported as a server error rather than the
intended, more honest 501. Impact is small: the endpoint is desktop-only and
gated behind `settings.open_in_editor` (off for web deployments), and no
internals leak.

**Failure scenario (b) — profile save inconsistency:**
`create_device_profile` / `update_device_profile` mutate the in-memory registry
(`device_profiles[id] = profile`, `device_profiles.py:99`/`:143`) **before**
`device_profile_store.save(...)`, and the save is not wrapped. On a disk-write
failure (disk full, permission) the save raises `OSError` → 500, but the profile
is already live in memory for the rest of the process lifetime and then
disappears on restart. Note the sibling `backups.create_backup` deliberately
made its pending-job save non-fatal (`except OSError` → warning, `backups.py:235`),
so this is an inconsistency with the team's own established pattern.

**Fix:**
(a) In `open_config`, treat `FileNotFoundError` from `subprocess.run` (the
xdg-open/open binary being absent) as a 501 like the `NotImplementedError`
branch. (b) Optionally wrap the profile `save()` in `except OSError` and either
roll back the in-memory insert or return a 503 that matches the create/update
being non-durable — at minimum log it so the memory/disk drift is visible.

---

## Explicitly checked and found solid (do not re-hunt)

- **Migration pipeline** (`run_plan`, `services/migration_pipeline.py:301-325`):
  `ParseError` / `RenderError` / generic `Exception` all captured into
  `MigrationJob.failed` with the failing stage preserved. `run_plan_with_overrides`
  builds transforms *before* the try but the builders only construct a result
  object + closure (no raising on adversarial maps); the real work runs inside
  `run_plan`'s try.
- **`CodecBase.__init_subclass__`** wraps every codec's `parse` so a pydantic
  `ValidationError` (out-of-range VLAN id, HSRP group id, prefix length) surfaces
  as `ParseError` uniformly — verified live: XML entity bombs, deep nesting,
  truncated stanzas all become `ParseError`.
- **SSH runner** (`paramiko_collector.py`): `_collect_output` fails **closed** on
  truncated/never-settled captures (`TimeoutError`, `:497`); `_drain` has hard
  wall-clock + byte caps (SEC-5); connect/auth failures close the client in
  `finally`/explicit `close()` (CONC-8). `translate_backup_error`
  (`api/_errors.py`) collapses raw SSH exceptions to host-prefixed operator lines
  and never echoes filesystem paths or multi-line netmiko blocks.
- **`run_backup_job`**: per-device failures are isolated; the terminal safety-net
  (`backup_runner.py:527-534`) forces any still-non-terminal result to `failed`
  so a never-ran device can never read as `completed` (81d9740 T0-2).
  `BackupRequest.devices` is `min_length=1`, so no zero-device "completed" job.
- **Credentials** (`security/credentials.py`): token-shaped-but-undecryptable
  fails closed (`CredentialDecryptError`); keyring/file write failures fall
  through tiers without raising; double-checked lock on first-key generation
  (CONC-7).
- **Stores**: `FileJobStore` / `FileScheduleStore` / `FileDeviceProfileStore`
  `load_all` skip corrupt files with a scrubbed log line (device-profile load
  scrubs decrypted plaintext out of the error). `FileConfigStore.save` enforces
  a 50 MB cap and writes atomically under a lock; `list_configs` skips `.tmp`
  and `.meta.json`.
- **XML DoS**: both XML codecs reject entity-bomb / XXE in milliseconds.
- **`detect_codec`** swallows per-codec probe exceptions so one malformed codec
  can't take down detection.

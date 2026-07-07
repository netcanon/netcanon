# 21 — CLI / API contract lens

Reviewer: Fable fresh-eyes pass, 2026-07-03. Scope: `netcanon/cli.py`, `netcanon/tools/demo.py`,
`netcanon/tools/sanitize.py` (CLI-facing entry), `netcanon/api/routes/` (migration + sanitize focus),
`netcanon/services/migration_pipeline.py` public trio (`run_plan` / `run_plan_with_rename` /
`run_plan_with_overrides`), `netcanon/api/auth.py`, `netcanon/models/migration.py`.
All behavioural claims below were confirmed with read-only `py -c` probes against the local package
(probe transcripts inline).

Verdict: **one major API-contract footgun (reproduced), rest minor.** The CLI's exit-code discipline
is largely sound (probed: unknown vendor → 2, unreadable input → 2, parse failure → 2, `--help` → 0,
missing subcommand → 2, bad `--pair` → 2), the `X-Netcanon-Job-Status` automation header is set and
OpenAPI-declared on all seven job-running POST handlers, `serve` fail-closes with exit 2 and a clear
message, `source_filename` resolution is traversal-guarded (`file_store.resolve_path`), and the
sanitize upload cap returns a clean 413. The findings below are the residue.

---

## F-1 (MAJOR) — `POST /plan` silently disables port-name translation when the body carries a non-port override map

**Where:** `netcanon/api/routes/migration.py:254-283` — specifically the conditional default at
`migration.py:262-266`:

```python
port_rename_map=(
    body.port_rename_map
    if body.port_rename_map is not None
    else ({} if body.target_profile is not None else None)
),
```

**Mis-contract:** the endpoint's three dispatch shapes are inconsistent:

| Request body | port pane | rendered interface names |
|---|---|---|
| no override maps, no profile | engaged (`{}`, else-branch :281-283) | translated (`ge-1/0/1`) |
| `port_rename_map` and/or `target_profile` | engaged | translated |
| **only** `vlan_rename_map` / `local_user_rename_map` / `snmp_community_rename_map` / `snmpv3_user_rename_map` | **`None` — disengaged** | **source-vendor names verbatim** |

So adding an *unrelated* override category to a previously-working request silently regresses the
output from valid target syntax to invalid source-vendor interface names — with `status=completed`,
`X-Netcanon-Job-Status: completed`, and zero warnings. Probe (cisco_iosxe_cli → juniper_junos,
demo config):

```
A (port_rename_map={}):            status completed | port_renames: 3 | rendered has GigabitEthernet: False
B (vlan_rename_map={10:110} only): status completed | port_renames: 0 | rendered has GigabitEthernet: True
B> set interfaces GigabitEthernet1/0/1 description "Server-A"
```

`set interfaces GigabitEthernet1/0/1 …` is not valid Junos; the fidelity/honesty machinery does not
flag it (round-trip preservation ≠ target-syntax validity — the known blind spot from the 2026-06-17
demo incident, now reachable through the primary HTTP endpoint). The endpoint docstring
(`migration.py:219-227`) documents only the two outer rows of the table ("when the body carries any
override map … every supplied category is threaded; when it carries none the endpoint STILL engages
the auto port-name heuristic") — it never states that supplying a *non-port* map turns the heuristic
OFF, and there is no plausible reason an operator renaming a VLAN wants their interface names to stop
translating.

**Why the earlier passes missed it:** the web UI is immune by accident — `templates/_partials/
rename-apply.js:31` unconditionally sets `body.port_rename_map` before every re-post, so only
programmatic API callers (curl / CI automation, the audience the `X-Netcanon-Job-Status` header was
built for) hit the gap.

**Suggested fix:** make the fallback unconditional — `else {}` instead of
`else ({} if body.target_profile is not None else None)` — so the auto heuristic is the invariant
default on `/plan`, matching the else-branch and the documented v0.3.2 "default `/plan` flow now
auto-translates" decision. (A caller who genuinely wants verbatim names has `run_plan` — that escape
hatch is the library layer, not this endpoint.)

## F-2 (minor) — per-pane endpoints: same untranslated-names behaviour + docstrings claim UI usage that doesn't exist

`POST /plan/vlans|local_users|snmp|snmpv3` (`migration.py:358-601`) pass only their own category, so
every response's `rendered` carries verbatim source interface names (same probe shape as F-1 row 3).
For these routes it is at least *stated* ("applies the VLAN category only" — `migration.py:390-392`),
but "category-only" is a strange contract for `rendered` output the response prominently carries.
Compounding: the docstrings sell these as the UI's pane-switch mechanism ("lets operators observe
which override category fired via server logs / network-tab inspection", `migration.py:322-326`;
"The UI sends `{}` when…", `migration_pipeline.py:60-62`) — but **no template or JS calls them**:
grep for `plan/(vlans|ports|local_users|snmp|snmpv3)` across the repo hits only
`tests/integration/test_migration_api.py`, docs, and the route file itself. `rename-apply.js` posts
everything to `/plan`. They are tested-but-unused public surface whose documented rationale is
fictional. Also trivial: `migration.py:315` names the future route `/plan/snmpv3_users`; the shipped
route is `/plan/snmpv3`.

## F-3 (minor) — `netcanon sanitize -o` dies with a raw traceback on an unwritable output path; `RenderError` also uncaught

`cli.py:173-174` writes the output with no `OSError` guard, and the `try` at `cli.py:142-158`
catches only `ValueError` + `ParseError`. Probe:

```
sanitize -i <ok> -s cisco_iosxe_cli -o C:\...\no_such_dir_xyz\out.txt
  -> UNHANDLED FileNotFoundError [Errno 2] ... (raw traceback, interpreter exit 1)
```

Contrast the input side, which is handled cleanly (`cli.py:137-139`, `error: cannot read … → exit 2`).
Asymmetric contract: read errors are operator-friendly exit 2, write errors are a stack trace. A
`RenderError` escaping `sanitize_text` (documented raise surface of `codec.render`,
`tools/sanitize.py:241`) would likewise traceback out of both the CLI and — as a 500 — the
`/api/v1/sanitize` route (`routes/sanitize.py:74-86` catches `ParseError` only). Wrap the write in
`except OSError → exit 2` and add `RenderError` to both catch lists.

## F-4 (minor) — sanitize path lacks the whole-input-rejection guard the migration pipeline gained (audit T0-2)

`run_plan` flags "non-trivial input parsed to an empty tree" as `partial`
(`migration_pipeline.py:127-183`, wired at `:340-354`). The sibling entry `sanitize_text`
(`tools/sanitize.py:184-245`) has no such guard. Probe — a Junos config sanitized as
`cisco_iosxe_cli` (permissive parser, no ParseError):

```
substitutions: 0
output head: 'Building configuration...\n\n! Generated by netcanon translator (cisco_iosxe_cli)\n...'
```

CLI exits **0** ("0 substitutions applied."), HTTP returns **200** with
`X-Netcanon-Substitution-Count: 0`. The operator's real config is silently replaced by an empty
scaffold — not a PII leak (nothing of the input survives), but a silent-success on unrecognized
input, the exact class the pipeline guard was built to close. A zero-recognized-paths check (or even
`substitutions == 0 and input non-trivial` → warning + non-zero exit / 4xx-adjacent signal) would
restore parity.

## F-5 (minor) — `netcanon demo` exits 0 on `partial` jobs; brittle status test

`tools/demo.py:274`: `if str(job.status).endswith("failed")`. Probed: `str(MigrationJobStatus.failed)`
is `'MigrationJobStatus.failed'` so the check works today, and `partial` does not match — meaning a
demo scenario degraded to `partial` (e.g. a codec regression tripping the empty-parse guard or a
block-severity validation) prints "Done … Translated …" and **exits 0**. README markets `netcanon
demo` as the zero-setup smoke test; its exit code should honour the same three-way disposition the
API header does (`partial` → non-zero, or at least a loud banner). Also prefer
`job.status is MigrationJobStatus.failed` over string suffix matching — `str()` of a str-mixin enum
changed semantics once already in CPython 3.11 and this is exactly the pattern that breaks.

## F-6 (minor) — doc drift around the `/plan` else-branch and README sample code

- `netcanon/api/routes/_migration_helpers.py:173-174` (`request_has_overrides_or_profile`): "Legacy
  callers that supply none of these get the plain `run_plan` path unchanged." False since the
  auto-translate change — the else-branch calls `run_plan_with_overrides(..., port_rename_map={})`
  (`migration.py:281-283`). Anyone extending the predicate from its docstring will mis-model the
  routing.
- `migration_pipeline.py:27-28` and `:758-760` claim `run_plan_with_rename` is kept for "sample code
  in this repo's README" — README contains no programmatic sample (`grep 'run_plan|from netcanon'
  README.md` → no matches). Harmless, but it misstates the compatibility constituency of a
  signature-frozen function.

## F-7 (minor) — `force=True` semantics: model docstrings promise block-override behaviour the pipeline doesn't have

`models/migration.py:128-130` (`LossyPath`): "``error`` escalates to a block unless ``force=True``";
`models/migration.py:141-143` (`UnsupportedPath`): "The caller may still override with
``force=True``…". In the actual pipeline, `force` **only** skips the stage-0 device-class guard
(`migration_pipeline.py:245-264`); validation severity `block` is unaffected by `force` and yields
`partial` after an unconditional render (`:331-339`). `MigrationPlanRequest.force`'s own docstring
(`models/migration.py:653`) is correct ("Skip the device-class guard"). A programmatic caller reading
the LossyPath/UnsupportedPath docs will pass `force=True` expecting to clear a block and observe a
no-op flag — the classic "flag that silently no-ops" in documented-contract form. Fix the two model
docstrings (or make `force` actually mean something at validate-time, but that's a design decision).

## F-8 (minor) — `/detect` request body lacks the 10 M-char cap `/plan` has

`MigrationPlanRequest.raw_text` is bounded (`models/migration.py:663`,
`max_length=10_000_000`, explicitly labelled an abuse guard); the sibling
`MigrationDetectRequest.raw_text` (`routes/migration.py:131`) has no `max_length`. `detect_codec`
only probes a 500-byte prefix (`services/migration_detect.py:74`), so CPU is bounded, but the full
body still deserialises into memory first. Inconsistent defence-in-depth on two endpoints that the
docstring says share "the same contract as `/plan`". One-line fix.

---

## Checked, no finding

- **Exit codes** (probed): unknown vendor 2, unreadable input 2, wrong-vendor ParseError 2, `--help`
  0, no subcommand 2, `demo --pair bogus` 2 (argparse, with correct `netcanon demo` usage text since
  validation is delegated to the demo's own parser), dry-run 0, success 0 with sanitized text on
  stdout and the status line on stderr (pipe-friendly — correct stream separation).
- `netcanon serve` fail-closed bind guard: refusal → exit 2 with actionable message
  (`cli.py:200-206`, `api/auth.py:81-101`); `Settings` attribute names all match `_cmd_serve` usage;
  `log_level` is pre-normalised to lowercase so `uvicorn.run` can't KeyError on case
  (`config.py:241-263`).
- `X-Netcanon-Job-Status` automation header: set on all 7 job-running handlers and declared in the
  shared OpenAPI `responses` map (`migration.py:147-165`) — the always-200 + header contract is
  consistent and documented.
- `resolve_input_text` XOR validation (422 both/neither, 404 missing file) and storage path-traversal
  guard (`storage/file_store.py:265-296`) — sound.
- `/api/v1/sanitize`: vendor allow-list 400, capped read + 413, CPU work off-loaded via
  `asyncio.to_thread` — good contract (modulo F-3's uncaught `RenderError` and F-4).
- `require_api_key`: constant-time compare, opt-in, correctly attached to every `/api/v1` router in
  `main.py:311-317`.
- `run_plan_with_rename` None→`{}` normalisation preserves its pre-P2C1 always-rename behaviour as
  documented (`migration_pipeline.py:770-786`) — the demo's `port_rename_map={}` call is redundant
  but harmless.

# 01 — Investigation CF: Cross-Cutting (Error-Handling, Security Posture, Performance, Dependencies)

**Reviewer:** CF — Cross-Cutting lens, whole tree
**Commit:** `b08040c` (v0.1.2)
**Mode:** READ-ONLY, review-grade
**Date:** 2026-06-06

---

## 1. Scope & method

CF owns four cross-cutting sub-lenses over the entire `netcanon/` tree
plus the top-level `tools/`, `pyproject.toml`, `Dockerfile`, and
`.dockerignore`:

1. **Error-handling discipline** — the exception taxonomy
   (`CodecError`/`ParseError`/`RenderError` in `codecs/base.py`;
   `_errors.py` backup-translation layer), whether errors are caught
   at the right layer, silent-drop vs surfaced, and the specific
   candidate Junos `TypeError` outlier Fleet D surfaced.
2. **Security posture** — confirming the 2026-05-21 security-triage
   landed and stuck (defusedxml swaps, SHA-pinning, AutoAddPolicy
   dismissal, `file_store` size guard) and finding what it did *not*
   cover. Specifically: every XML parse site, the paramiko trust
   model, `file_store` path/size guards, the
   `eval`/`exec`/`subprocess`/`pickle`/`yaml.load`/SSRF surface, and
   the sanitiser's redaction coverage cross-checked against the live
   canonical model.
3. **Performance footguns** — unbounded loops, O(n²) over config size,
   ReDoS / catastrophic-backtracking risk in the large parsers,
   job-registry LRU correctness, full-file reads without the size
   guard.
4. **Dependency hygiene + packaging** — `pyproject.toml` pins,
   `defusedxml` presence, `yaml.safe_load` discipline, over-broad /
   unused deps, and whether the published wheel / image actually ships
   `tools/` (referenced by the README demo).

**Method.** Read the two snapshot docs, `METHODOLOGY.md`, `AGENTS.md`
§ Hard Rules, `SECURITY.md`, and the full 2026-05-21 security-triage
synthesis (`docs/security-triage/2026-05-21/99-synthesis.md`) first so
that accepted/dismissed risks are not re-litigated. Then traced the
candidate Junos `TypeError` through every render call site; inventoried
all XML parse sites via Grep; cross-checked `tools/sanitize.py`
field-by-field against `migration/canonical/intent.py`; scanned the
five largest parsers for nested-quantifier regex shapes; read
`storage/job_registry.py`, `storage/file_store.py`,
`collectors/paramiko_collector.py`, `security/credentials.py`,
`security/migration.py`, `migration/_user_secrets.py`,
`pyproject.toml`, `Dockerfile`, `.dockerignore`, and `tools/demo.py`.
All findings carry `file:line` citations. Unverified claims are marked
`UNVERIFIED`.

**Confidence framing.** This is a mature, deliberately-disciplined
codebase. Two prior review cycles (security-triage + docs-audit, both
2026-05-21) already closed 79 + 128 findings. The bar for a P-level
defect here is high; load-bearing-by-design choices are recorded as
OBSERVATIONS with rationale, not bugs.

---

## 2. Executive summary

The 2026-05-21 security hardening **stuck cleanly**. Both XML parse
sites are on `defusedxml`; the `paramiko` AutoAddPolicy is documented +
dismissed-by-design; the `file_store` 50 MB guard and the strict
filename regex are intact; SHA-pinning and workflow-permission changes
are reflected in `SECURITY.md`. No `eval`, `exec`, `os.system`,
`pickle`, `marshal`, or `yaml.load` (unsafe) anywhere in the tree. The
single `subprocess` site (`configs.py` open-in-editor) is list-form,
desktop-gated, extension-whitelisted, and `resolve_path()`-guarded.

Three findings are worth attention, none of them a remote-exploit P0
under the documented threat model:

* **CF-01 (P2) — sanitiser leaks VRRP/CARP authentication secrets.**
  `tools/sanitize.py::sanitize_intent` walks 11 canonical surfaces but
  **never touches `CanonicalInterface.vrrp_groups[].authentication`** —
  a field that six codecs populate with *cleartext* auth material
  (Arista/Aruba/FortiGate `plain:<secret>`, OPNsense `carp-key:<pw>`,
  MikroTik/Junos pass-through). The Aruba renderer emits it back as
  `authentication mode plaintext-password "<secret>"`. An operator who
  sanitises a config with VRRP/CARP auth for a public bug report leaks
  the plaintext secret. This is **not** in `SECURITY.md`'s documented
  limitations and is a genuine matrix-honesty gap (the sanitiser claims
  AST-level redaction of secret-bearing fields; this secret-bearing
  field is uncovered).

* **CF-02 (P2) — README's headline demo command is broken in every
  distributed artifact.** `pyproject.toml`
  `[tool.setuptools.packages.find]` includes only `netcanon*` and
  `netcanon_desktop*` (not `tools*`), and the `Dockerfile` copies only
  `netcanon/` + `definitions/`. Top-level `tools/demo.py` is therefore
  **absent from both the wheel and the Docker image**, yet `README.md`
  line 24 instructs `docker run --rm ghcr.io/netcanon/netcanon:latest
  python tools/demo.py …` and `tools/demo.py`'s own docstring says
  "`pip install netcanon` and run". This confirms Fleet D's packaging
  finding. The code *would* run if shipped (it imports only from the
  installed `netcanon` package), so the fix is a packaging decision,
  not a code change.

* **CF-03 (P3) — Junos render raises bare `TypeError`; the other seven
  codecs raise `RenderError`.** Through the *pipeline* this is fully
  contained (the broad `except Exception` catch-all turns it into a
  clean `failed` job — see § 3), so the blast radius is **small**. But
  the second render call site, `tools/sanitize.py:159`, has **no
  try/except**, so a non-`CanonicalIntent` reaching Junos render there
  surfaces as an unhandled `TypeError`. The inconsistency is a latent
  trap, not a live remote bug.

The remaining surface is healthy: job-registry LRU eviction is correct,
the regex corpus has no nested-quantifier (catastrophic-backtracking)
shapes, credential encryption is sound, and dependency pins are
reasonable. A handful of OBSERVATIONS (size-guard asymmetry on the
paste path, no upload cap on `/sanitize`, broad-except idioms) round out
the report.

---

## 3. Error-handling assessment

### 3.1 The taxonomy is clean and correctly layered

`codecs/base.py:37-81` defines a tight three-level hierarchy:

* `CodecError(Exception)` — base for all adapter-layer faults.
* `ParseError(CodecError)` — malformed input; carries optional
  `path` + `snippet` (≤120 chars) for UI display.
* `RenderError(CodecError)` — tree the adapter cannot emit; carries
  optional `yang_path`.

The pipeline (`services/migration_pipeline.py:241-265`) catches these
in the right order and at the right layer:

```python
except ParseError as exc:
    job.status = MigrationJobStatus.failed
    job.error = f"parse failed: {exc}"
    logger.exception(...)
except RenderError as exc:
    job.status = MigrationJobStatus.failed
    job.error = f"render failed: {exc}"
    logger.exception(...)
except Exception as exc:  # noqa: BLE001 — honest catch-all
    failing_stage = job.status.value
    job.status = MigrationJobStatus.failed
    job.error = f"unexpected error in stage {failing_stage}: {exc}"
    logger.exception(...)
```

This is exemplary: typed errors get clean operator-facing prefixes; the
broad catch-all preserves the in-progress stage before reassigning
status, logs the full traceback server-side (`logger.exception`), and
never lets a stage exception escape the pipeline. The route layer
(`api/routes/migration.py`) **always returns the `MigrationJob`**
regardless of status — `plan_migration` has no try/except because it
doesn't need one; the pipeline guarantees a terminal-state job. The
caller inspects `job.status` (`completed` / `partial` / `failed`).

The backup-side error translator (`api/_errors.py`) is a separate, very
thoughtful layer: it maps `paramiko` / `netmiko` / socket exceptions to
single-line, host-prefixed, operator-readable strings, deliberately
suppressing internal filesystem paths (`_humanize_storage_error`,
line 222) and multi-line "see also" blocks (`_first_line`, line 85).
The module docstring explicitly explains *why* it's a function and not
a FastAPI exception handler (it runs inside a `BackgroundTasks` worker
thread, off the request stack — lines 44-51). This is mature
error-handling design.

### 3.2 The Junos `TypeError` outlier — trace + verdict

**Claim (from Fleet D):** `juniper_junos/render.py::render_intent`
raises `TypeError` on its wrong-type guard while the pipeline only
catches `RenderError`; a non-`CanonicalIntent` input to Junos render
could escape as a 500 / "unexpected error".

**What the code actually does** (`juniper_junos/render.py:104-108`):

```python
if not isinstance(tree, CanonicalIntent):
    raise TypeError(
        "juniper_junos.render: expected CanonicalIntent, got "
        f"{type(tree).__name__}"
    )
```

This is the **only** codec render path that raises `TypeError`. The
other seven all raise `RenderError`:

| Codec | render guard | line | exception |
|---|---|---|---|
| arista_eos | `if not isinstance(tree, CanonicalIntent)` | render.py:154-157 | `RenderError` |
| aruba_aoss | same | render.py:372-375 | `RenderError` |
| cisco_iosxe_cli | same | render.py:69-72 | `RenderError` |
| cisco_iosxe (NETCONF) | dict-or-canonical dispatch | codec.py:646-649 | `RenderError` |
| fortigate_cli | same | render.py:420-423 | `RenderError` |
| mikrotik_routeros | same | render.py:106-109 | `RenderError` |
| opnsense | canonical-or-dict, else | render.py:70-76 | `RenderError` |
| **juniper_junos** | `if not isinstance(tree, CanonicalIntent)` | **render.py:104-108** | **`TypeError`** |

**Blast-radius trace.** There are exactly **two** call sites that invoke
a codec's `render()`:

1. **`services/migration_pipeline.py:239`** — `job.rendered =
   target.render(tree)`. This sits inside the `try` block whose final
   `except Exception` catch-all (line 255) catches `TypeError` along
   with everything else. **Verdict for path 1: fully contained.** A
   non-`CanonicalIntent` reaching Junos render here produces a clean
   `job.status = failed`, `job.error = "unexpected error in stage
   rendering: juniper_junos.render: expected CanonicalIntent, got
   <X>"`, the traceback goes to the server log, and the HTTP layer
   returns a normal 200 with a `failed` `MigrationJob`. **No 500.** The
   *only* observable difference vs the other seven codecs is the
   `job.error` prefix: `"unexpected error in stage rendering: …"`
   instead of `"render failed: …"`. That's a cosmetic / diagnostic
   inconsistency, not a fault.

2. **`tools/sanitize.py:159`** — `sanitized_text =
   codec.render(sanitized_intent)`. This call has **no surrounding
   try/except** inside `sanitize_text`. It is reached by both the CLI
   (`netcanon sanitize`) and the HTTP endpoint (`POST /api/v1/sanitize`
   → `api/routes/sanitize.py:58`). **Verdict for path 2: the HTTP
   endpoint only catches `ParseError`** (`sanitize.py:59`), so a
   `RenderError` *or* a `TypeError` from render would propagate up as an
   unhandled exception → FastAPI 500. *However*, in practice
   `sanitized_intent` here is always a `CanonicalIntent` (it's a
   `model_copy(deep=True)` of the parsed intent — `sanitize.py:182`),
   so the guard is structurally unreachable on the sanitise path *as
   currently wired*. The `TypeError` vs `RenderError` divergence is
   therefore a **latent** inconsistency: it does not change behaviour
   today, but it means the Junos codec violates the implicit contract
   that "wrong-type tree → `RenderError`" that every other codec
   honours and that `codecs/base.py:228-240`'s `render()` docstring
   documents (`Raises: RenderError`).

**Overall verdict on the Junos `TypeError`:** **Real but low-severity
(P3).** It does *not* escape as a 500 through the migration pipeline
(the dominant path) because the broad catch-all contains it. The risk
is (a) a cosmetically wrong `job.error` prefix on the pipeline path and
(b) a contract violation that *would* bypass `RenderError`-specific
handling if any future caller wraps render in `except RenderError`
only — exactly what the sanitise HTTP endpoint does for `ParseError`.
The fix is one line (raise `RenderError` with `yang_path="/"` to match
the other seven). I did **not** find a path where it produces a live
500 today, so I am not rating it higher. See CF-03.

### 3.3 Silent-drop vs surfaced — spot checks

* **Tier-3 content** is surfaced, not silently dropped:
  `migration_pipeline.py:216-218` copies
  `tree.dropped_tier3_sections` onto the job for the UI banner. This is
  the Wave 11 anti-silent-drop discipline (METHODOLOGY.md § anti-
  patterns) working as designed.
* **`file_store.list_configs`** swallows sidecar-metadata read failures
  with a logged warning (`file_store.py:224-228`) and falls back to
  filename-derived fields — correct (a corrupt sidecar shouldn't hide a
  real config).
* **`_migrate_flat_files`** (`file_store.py:321-324`) logs-and-skips
  per-file migration errors so one bad file can't block startup —
  correct.
* **`credentials._write_keyring`** (`credentials.py:109-114`) returns
  `False` on any backend failure to fall through to the file tier —
  correct, and documented.

No problematic silent-drop sites found.

---

## 4. Security-posture sweep

### 4.1 XML-parse-site inventory

The 2026-05-21 triage swapped the two operator-input XML parse sites to
`defusedxml`. **Confirmed stuck.** Full inventory of every ET / XML
reference in `netcanon/`:

| File:line | Construct | Consumes untrusted input? | On defusedxml? | Verdict |
|---|---|---|---|---|
| `opnsense/parse.py:79-80` | `from defusedxml.ElementTree import fromstring as _safe_fromstring` + `DefusedXmlException` | **Yes** (operator `config.xml`) | **Yes** | SAFE |
| `opnsense/parse.py:180` | `root = _safe_fromstring(raw)` | Yes | Yes | SAFE — wrapped: `DefusedXmlException`→`ParseError` (182-186), `ET.ParseError`→`ParseError` (187-191) |
| `opnsense/parse.py:69` | `from xml.etree import ElementTree as ET` | No (only `ET.ParseError` type ref) | n/a | SAFE — stdlib import is used only for the exception type, not for parsing |
| `cisco_iosxe/codec.py:100-101` | `from defusedxml.ElementTree import fromstring as _safe_fromstring` + `DefusedXmlException` | **Yes** (NETCONF payload) | **Yes** | SAFE |
| `cisco_iosxe/codec.py:556` | `root = _safe_fromstring(raw)` | Yes | Yes | SAFE — wrapped: `DefusedXmlException`→`ParseError` (557-562), `ET.ParseError`→`ParseError` (563-567) |
| `cisco_iosxe/codec.py:88` | `from xml.etree import ElementTree as ET` | No (generation + `ET.ParseError` ref) | n/a | SAFE — used for `ET.Element`/`SubElement`/`tostring` on the render side, which emit XML and never parse untrusted bytes |
| `opnsense/render.py:39` | `from xml.etree import ElementTree as ET` | **No** (render only — emits XML) | n/a | SAFE — generation-side; out of scope by definition |

**Verdict (b): Are ALL XML parse sites on defusedxml? YES.** Both input
parse sites (`opnsense/parse.py:180`, `cisco_iosxe/codec.py:556`) use
`defusedxml.ElementTree.fromstring` and wrap rejection in an explicit
`DefusedXmlException`→`ParseError` clause that produces a clean
operator-facing message. The three remaining stdlib `xml.etree`
references are either generation-side (render emits XML) or used only
for the `ET.ParseError` exception type — none parse untrusted input.
This matches the triage's claim of "only 3 stdlib-ET import sites,
3rd is render-only". No new XML entry points were introduced since.

### 4.2 Secret-redaction coverage table (sanitiser vs canonical model)

This is the highest-value part of the sweep. The sanitiser
(`tools/sanitize.py::sanitize_intent`) claims AST-level redaction of
identity- and secret-bearing fields. I cross-checked **every** field on
the canonical model (`migration/canonical/intent.py`) against the
sanitiser walk.

| Canonical field | Bears secret/PII? | Sanitised? | Where / gap |
|---|---|---|---|
| `CanonicalIntent.hostname` | PII | **Yes** | sanitize.py:187-195 → `device-N` |
| `CanonicalIntent.domain` | PII | **Yes** | :197-205 → `example-N.test` |
| `CanonicalIntent.dns_servers` | net | **Yes (IPv4 only)** | :208-209 |
| `CanonicalIntent.ntp_servers` | net | **Yes (IPv4 only)** | :210-211 |
| `CanonicalIntent.syslog_servers` | net | **Yes (IPv4 only)** | :212-213 |
| `CanonicalInterface.description` | PII | **Yes** | :217-225 → "description redacted" |
| `CanonicalInterface.ipv4_addresses[].ip` | net | **Yes** | :227-236 |
| `CanonicalInterface.ipv6_addresses[].ip` | net | **No** | **GAP** — documented IPv4-only limitation (SECURITY.md known-limitation row); v0.1.0 carry-in |
| **`CanonicalInterface.vrrp_groups[].authentication`** | **secret (often cleartext)** | **No** | **GAP — CF-01.** Not walked at all. See § 4.2.1 |
| `CanonicalLocalUser.name` | PII | **Yes** | :247-256 → `localuserN` |
| `CanonicalLocalUser.hashed_password` | secret | **Yes** | :257-265 → format-preserving fake |
| `CanonicalSNMP.community` | secret | **Yes** | :269-277 → `public_redacted_N` |
| `CanonicalSNMP.location` | PII (site/address) | **No** | GAP (minor) — operator site string passes through |
| `CanonicalSNMP.contact` | **PII (often email/name)** | **No** | **GAP** — e.g. `admin@corp.example` passes through verbatim |
| `CanonicalSNMP.trap_hosts[]` | net | **No** | GAP — trap-target IPs pass through |
| `CanonicalSNMPv3User.name` | PII | **Yes** | :283-291 → `snmpv3userN` |
| `CanonicalSNMPv3User.auth_passphrase` | secret | **Yes** | :292-300 → `REDACTED-AUTH-N` |
| `CanonicalSNMPv3User.priv_passphrase` | secret | **Yes** | :301-309 → `REDACTED-PRIV-N` |
| `CanonicalSNMPv3User.engine_id` | low | **No** | acceptable (device-derived hex) |
| `CanonicalRADIUSServer.key` | secret | **Yes** | :312-321 → `REDACTED-RADIUS-N` |
| `CanonicalRADIUSServer.host` | net | **No** | GAP — RADIUS server IP/hostname passes through |
| `CanonicalDHCPPool.dns_servers[]` | net | **Yes** | :324-336 |
| `CanonicalDHCPPool.gateway` | net | **No** | GAP — pool gateway IP passes through |
| `CanonicalDHCPPool.network`/`start_ip`/`end_ip` | net | **No** | GAP — pool addressing passes through (usually private, lower risk) |
| `CanonicalDHCPPool.domain_name` | PII | **No** | GAP — search domain passes through |
| `CanonicalStaticRoute.gateway` | net | **Yes** | :339-349 |
| `CanonicalStaticRoute.destination` | net | **No** | GAP — destination prefix passes through (lower risk) |
| `CanonicalVlan.ipv4_addresses[].ip` (SVI) | net | **No** | **GAP** — SVI L3 addresses on VLAN records are not walked; only `interface.ipv4_addresses` is |
| `CanonicalVxlan.*` (mcast_group, flood_list) | net | **No** | GAP (minor) — overlay IPs pass through |
| `CanonicalIntent.dropped_tier3_sections` | anything | **Yes (stripped)** | :352-360 |
| `CanonicalIntent.raw_sections` | anything | **No** | OBSERVATION — Tier-3 raw text not stripped; but no codec populates it on parse (it's a carry-through dict), so latent. See § 4.2.2 |

**Verdict (c): Does the sanitiser redact ALL secrets? NO.** It covers
the high-frequency secret fields well (local-user hashes, SNMP
community, SNMPv3 auth/priv passphrases, RADIUS keys), but it **misses
`CanonicalVRRPGroup.authentication`** — a field that carries *cleartext*
secrets in six codecs (CF-01, the material gap) — and it also leaks
several PII/network surfaces (`snmp.contact`, IPv6 addresses, VLAN-SVI
IPv4, RADIUS/trap/DHCP hosts). The IPv6 gap is already documented in
`SECURITY.md`; the VRRP-auth and `snmp.contact` gaps are **not**.

#### 4.2.1 CF-01 detail — VRRP/CARP auth secret leak (P2)

`CanonicalVRRPGroup.authentication` is documented in
`intent.py:563-569` as an opaque token in `<scheme>:<value>` form, with
explicit examples `"plain:secret123"`, `"md5:hash"`,
`"carp-key:bytes"`. It is populated by **six codecs**, several with
genuinely cleartext material:

* `arista_eos/parse.py:1248` — `g.authentication = f"plain:{m.group(2)}"`
  (cleartext VRRP auth string)
* `aruba_aoss/parse.py:657` — `group.authentication = f"plain:{auth.group(1)}"`
  (cleartext)
* `fortigate_cli/parse.py:507` — `group.authentication = f"plain:{auth_tokens[0]}"`
  (cleartext)
* `opnsense/parse.py:818` — `authentication = f"carp-key:{password}"`
  (the raw CARP `<password>` element — cleartext)
* `mikrotik_routeros/parse.py:779` — `authentication=scratch["authentication"]`
  (combines `password=X` from `/interface vrrp`)
* `juniper_junos/parse.py:2409` — `authentication=scratch.get("authentication", "")`
  (pass-through)

And it **round-trips back into rendered output**. Confirmed in the
Aruba renderer (`aruba_aoss/render.py:673-677`):

```python
if group.authentication.startswith("plain:"):
    lines.append(
        f'      authentication mode plaintext-password '
        f'"{group.authentication[6:]}"'
    )
```

So the full chain `parse → sanitize_intent → render` preserves the
original plaintext VRRP/CARP secret verbatim. An operator using
`netcanon sanitize` (or `POST /api/v1/sanitize`) on a config that
contains VRRP/CARP authentication — precisely the bug-report workflow
the sanitiser exists to make safe — will publish that secret.

This is a matrix-honesty violation: `SECURITY.md` § Sanitiser lists
"SNMPv3 auth/priv passphrases", "RADIUS shared secrets", and "Hashed
passwords" as redacted categories and frames the sanitiser as
canonical-model-driven, but a canonical secret-bearing field is
uncovered. It is not in the Known-Limitations table either (unlike the
IPv6 and banner-text gaps, which *are* honestly documented).

**Severity P2** (not P1): exploitation requires the operator to (a) have
VRRP/CARP auth configured, (b) run the sanitiser, and (c) publish the
output — and the threat is *disclosure of a device-side L3-redundancy
auth string*, not credential-store compromise or RCE. But it is a real
secret leak in a security-critical workflow, and it is silent (no
`Substitution` entry warns the operator the field went through
unredacted).

**Suggested direction:** add a `redact_secret("VRRP")` walk over
`iface.vrrp_groups[].authentication` (and, for completeness, surface a
`Substitution` so `--dry-run` shows it), preserving the `<scheme>:`
prefix so the format-preserving render still emits valid syntax. Update
`SECURITY.md` § Sanitiser + `BUG_REPORTING.md` in the same commit
(AGENTS.md doc-sync "new redaction category" row).

#### 4.2.2 `raw_sections` (OBSERVATION)

`CanonicalIntent.raw_sections` is a Tier-3 carry-through dict that the
sanitiser does not strip (it only strips `dropped_tier3_sections`,
which is the *header-label* notification list). Today no codec parse
path populates `raw_sections` (it's reserved carry-through — verified by
the absence of `.raw_sections[` writes in any `parse.py`), so this is
latent, not live. Worth a one-line strip for defence-in-depth alongside
the CF-01 fix, since Tier-3 raw text "may contain anything" by the
sanitiser's own docstring (sanitize.py:39-40).

### 4.3 Injection / SSRF / deserialization scan

| Class | Result |
|---|---|
| `eval` / `exec` | **None** in source (only the substring `user-exec` / `exec()` JS-regex `re.exec` in a template, and `enable_password` docstrings). Confirmed via Grep across `netcanon/`. |
| `os.system` / `popen` | **None** |
| `subprocess` | **One site:** `api/routes/configs.py:179-183` — `subprocess.run(["open", path])` / `["xdg-open", path]`. **List-form (no `shell=True`), `check=True`.** Gated by `settings.open_in_editor` (desktop-only, 403 on web — line 143), extension whitelist (`_OPEN_ALLOWED_EXTENSIONS`, line 157), and `storage.resolve_path()` (line 169). The `path` is the resolved Path of a regex-validated filename inside `storage_dir`. **No injection surface.** |
| `os.startfile` | Same endpoint, Windows branch (`configs.py:177`); same guards. Safe. |
| `pickle` / `marshal` / `__import__` | **None** |
| `yaml.load` (unsafe) | **None** — `SECURITY.md` claims `safe_load` exclusively; consistent with no `yaml.load(` hits. (Definition loading is CB's deep-dive; CF confirms no unsafe-load grep hit.) |
| SSRF (collectors → user host) | The `paramiko`/`netmiko` collectors connect to `DeviceTarget.host`, which is operator-supplied. This is **operator-as-trust-anchor by design** (paramiko_collector.py:18-30; triage Class 5 dismissal). `host` is validated by `_validate_host()` (`models/device.py`, per SECURITY.md § Input Validation — Host Field) to IPv4/IPv6/RFC-1123 only, blocking shell-metacharacter / path injection. **No new SSRF beyond the accepted operator-driven backup model.** |
| Path traversal | `file_store.resolve_path` (file_store.py:260-294): strict `_FILENAME_RE` (rejects `..`, `/`, separators) + `Path.resolve().is_relative_to(storage_root)` defence-in-depth on BOTH the canonical and flat-fallback candidates. The save-path filename is built from `device_type` (validated `type_key_filename_safe`) + `host.replace(":","--").replace(".","-")` (file_store.py:157). **No traversal surface; no injection via host/device_type.** |

**Verdict:** no new injection / SSRF / deserialization surface beyond
the accepted operator-trust model. The 2026-05-21 dismissals
(AutoAddPolicy, path-traversal-already-guarded) hold.

### 4.4 Credential handling

`security/credentials.py` is sound: Fernet symmetric encryption with a
3-tier key resolution (env → keyring → file fallback), lazy `_get_fernet`
init, `decrypt_field` legacy-plaintext migration, file-tier `chmod
0o600` (best-effort, non-fatal on Windows — line 137-141). The
`WARNING`-level auto-generation log (line 193-199) nudges operators
toward tier 1. `security/migration.py` centralises the
plaintext→encrypted re-save logic for both stores. No credential value
reaches a logger anywhere I traced (the closing-summary `logger.debug`
statements in codecs consume only `.hostname` + `len()` counts — exactly
the triage Class-1 dismissal rationale). **No findings.**

---

## 5. Performance footguns

### 5.1 Regex catastrophic-backtracking (ReDoS)

I scanned the five largest parsers (junos 2455, iosxe_cli 1672, arista
1387, mikrotik 1291, aruba 1215 LOC) plus the others for
nested-quantifier shapes — `(\S+)+`, `(.*)*`, `(\w+\s*)+`, `)+`/`)*`
followed by another quantifier, and bounded-repeat-on-group `){n}`. The
targeted scan (`[+*]\)[+*]`, `(?:...[+*])[+*]`, `)\{[0-9]`) across all
`parse.py` files returned **zero matches**. A spot search of the Junos
parser's regexes surfaced only linear, anchored shapes such as
`^(.+)\.(\d+)$` (parse.py:1289) — a greedy `.+` followed by `\.\d+$`
with no nested quantifier, which backtracks at most linearly.

This corroborates the 2026-05-21 triage Class-4 dismissal
(19 alerts): "polynomial-not-exponential pattern shape (no nested
quantifiers compounding) applied per-line via `splitlines()`". **No
catastrophic-backtracking risk found.** Codec parsing is line-oriented;
each regex sees one bounded line.

### 5.2 The size-guard asymmetry (OBSERVATION, perf nuance)

The triage's ReDoS dismissal rests on two compensating controls:
per-line `splitlines()` *and* "File-upload path bounded at 50 MB by
`MAX_CONFIG_SIZE`". The 50 MB cap (`file_store.py:95,152-156`) fires on
the **backup save** path. But the **migration / sanitise paste path**
does NOT pass through it:

* `api/routes/_migration_helpers.py:resolve_input_text` returns
  `body.raw_text` directly (line 86) with no size check.
* `api/routes/sanitize.py:54-55` reads the entire upload
  (`await config.read()`) into memory with no `MAX_CONFIG_SIZE` check.

So a pasted / uploaded multi-hundred-MB config to `/migration/plan` or
`/sanitize` is bounded only by uvicorn/FastAPI request limits, not by
the documented `MAX_CONFIG_SIZE`. Because the regexes are polynomial and
the input is line-bounded, this is **not** a ReDoS vector — but it does
mean the triage's stated compensating control ("50 MB cap") is
*incompletely true*: it covers the collector-save path, not the
operator-paste path. Memory pressure from a giant paste is the realistic
worst case, and the threat model (loopback / operator-proxied) makes it
low-severity. Worth a note so a future reader doesn't over-trust the
"50 MB cap protects all parse paths" framing. See CF-05.

### 5.3 Job-registry LRU (correct)

`storage/job_registry.py` is a clean LRU over `OrderedDict`:

* `__setitem__` (line 129-155): existing key → `move_to_end` (MRU);
  new key over cap → `popitem(last=False)` (evict LRU). Correct.
* `__getitem__` (line 157-175): memory hit → `move_to_end` + return;
  miss → disk `load_one`, promote (may evict). Correct lazy-load.
* `max_memory_jobs == 0` disables caching (drop-on-floor, disk is
  source of truth) — line 138-141. Correct.
* `__contains__` uses a cheap `path.exists()` for the disk check (no
  JSON parse) — line 188. Good.
* Negative cap rejected in constructor (line 88-91).

**No eviction bug.** The one perf caveat is `_warm_from_disk` (line
98-125): it calls `load_all()` (one JSON parse per job) then trims to N
— O(total-disk-jobs) at startup, which the docstring honestly flags as
a v0.2.0 optimisation target for 100k+-job installs. Documented, not a
defect.

### 5.4 Unbounded loops / O(n²)

No O(n²)-over-config-size hot loop found in the platform layer. The
pipeline applies transforms in a single pass (`migration_pipeline.py:226`).
Codec-internal complexity (e.g. interface-range collapse) is CC's
deep-dive; from the cross-cutting lens the parsers are line-oriented
single-pass. `file_store.list_configs` does a full `rglob("*")` walk per
call (line 215) — O(files), unavoidable for a filename-as-database
design, and the result is sorted once.

---

## 6. Dependency hygiene + packaging check

### 6.1 Dependency pins (`pyproject.toml:51-72`)

| Package | Pin | Assessment |
|---|---|---|
| fastapi | `>=0.115.0` | floor-only; reasonable for a lib |
| uvicorn[standard] | `>=0.30.0` | ok |
| pydantic | `>=2.0.0` | v2; ok |
| pydantic-settings | `>=2.0.0` | ok |
| pyyaml | `>=6.0` | `safe_load` discipline confirmed |
| netmiko | `>=4.4.0` | ok |
| paramiko | `>=3.4.0` | floor avoids historical key CVEs; SECURITY.md flags "keep updated" |
| jinja2 | `>=3.1.0` | autoescape default; SECURITY.md confirms no `|safe` on user data |
| python-multipart | `>=0.0.9` | floor above the CVE-2024-24762 fix line — good |
| aiofiles, apscheduler | floors | ok |
| cryptography | `>=41.0.0` | Fernet; ok |
| keyring | `>=24.0.0` | ok |
| **defusedxml** | **`>=0.7.1`** | **present** — confirms triage Group I landed; comment cites the triage doc |

All pins are floor-only (`>=`), which `SECURITY.md` § Supply-Chain
acknowledges as "Pending: a pinned dependency manifest
(`requirements.lock` / `uv.lock`)" — an honestly-documented follow-up,
not a finding. No over-broad or obviously-unused runtime dep (the heavy
desktop deps PySide6/pystray/Pillow are correctly isolated under the
`desktop` optional extra). `defusedxml` is present and version-floored
at the entity-bomb-fix line. **No dependency findings.**

### 6.2 Packaging — does the wheel/image ship `tools/`? (CF-02, confirms Fleet D)

**No.** Two independent exclusions:

1. **Wheel.** `pyproject.toml:122-124`:
   ```toml
   [tool.setuptools.packages.find]
   where = ["."]
   include = ["netcanon*", "netcanon_desktop*"]
   ```
   Top-level `tools/` is **not** in `include`, and it has no
   `__init__.py` to be auto-discovered as a package anyway. So
   `pip install netcanon` does **not** ship `tools/demo.py`,
   `tools/run_full_mesh.py`, etc. (Note: `netcanon/tools/sanitize.py`
   *is* shipped — it's inside the `netcanon` package — so the sanitise
   feature itself is fine. The gap is the *top-level* `tools/`
   directory.)

2. **Docker image.** `Dockerfile:35-36` copies only `pyproject.toml`,
   `README.md`, `LICENSE`, and `netcanon/`; `Dockerfile:69` copies
   `definitions/`. Top-level `tools/` is never `COPY`'d, so it is
   absent from the image regardless of `.dockerignore` (only
   explicitly-copied paths land in a multi-stage runtime image). The
   builder stage also only `pip wheel`s `netcanon`, which by (1)
   excludes `tools/`.

**Why this matters — broken operator-facing instructions
(matrix-honesty):**

* `README.md:24` — `docker run --rm ghcr.io/netcanon/netcanon:latest
  python tools/demo.py --pair cisco__junos`. The image has no
  `tools/demo.py` → `python: can't open file '/app/tools/demo.py'`.
* `README.md:52, 163` — `python tools/demo.py --list` / `--pair <key>`,
  presented in a `pip install`-oriented quickstart.
* `tools/demo.py:14-15` docstring — "Drop into a Python 3.11+ env with
  `pip install netcanon` and run." But `pip install netcanon` does not
  install `tools/demo.py`.

The code itself is correct — `tools/demo.py:28-29` imports only from the
installed `netcanon` package (`registry`, `migration_pipeline`), so it
*would* run if shipped. This is purely a packaging/doc-sync gap: either
(a) move `demo.py` into the `netcanon` package and expose it as a
console script (e.g. `netcanon demo`), or (b) ship top-level `tools/`
into the wheel + image, or (c) correct the README to describe a
source-checkout-only invocation. **Severity P2** — the headline
"30-second show-me-what-this-does" path advertised in the README is
broken for the two primary distribution channels (Docker + pip), which
is exactly the kind of operator-trust erosion the project's
matrix-honesty discipline exists to prevent.

`UNVERIFIED`: I did not build the wheel or pull the image to observe the
failure at runtime (READ-ONLY; no network). The conclusion is from
static inspection of `pyproject.toml` + `Dockerfile` + `demo.py`
imports + README text, which is conclusive on file inclusion. A
confirming repro would be `pip install .` into a clean venv then
`python -c "import tools.demo"` (expect ModuleNotFoundError) — left to
the adversarial pass.

### 6.3 `.dockerignore` sanity

`.dockerignore` correctly excludes operator-state dirs (`configs/`,
`devices/`, `schedules/`, `jobs/`, `data/`), `tests/`, `docs/`, `.git/`,
`.env*`, and `netcanon_desktop/` from the build context. `*.md` is
excluded except `README.md` (line 29-30) — consistent with the
Dockerfile's explicit README copy. No secret-bearing path is at risk of
being baked into the image. Good.

---

## 7. Findings (severity-ordered)

> Severity scale per the review README (P0 critical … P3 minor /
> OBSERVATION). This is a hardened codebase; nothing here is a remote
> P0/P1 under the documented threat model.

### CF-01 — Sanitiser leaks VRRP/CARP authentication secrets — **P2**

* **File:line:** `netcanon/tools/sanitize.py:166-362`
  (`sanitize_intent` omits `vrrp_groups`); secret populated at
  `arista_eos/parse.py:1248`, `aruba_aoss/parse.py:657`,
  `fortigate_cli/parse.py:507`, `opnsense/parse.py:818`,
  `mikrotik_routeros/parse.py:779`, `juniper_junos/parse.py:2409`;
  rendered back at e.g. `aruba_aoss/render.py:673-677`.
* **Claim:** `CanonicalInterface.vrrp_groups[].authentication` is a
  secret-bearing canonical field (often *cleartext* — `plain:<secret>`,
  `carp-key:<pw>`) that the sanitiser never walks, so it survives the
  parse→sanitise→render round-trip and is published in "sanitised" bug
  reports.
* **Evidence:** `intent.py:563-569` documents the field as an opaque
  `<scheme>:<value>` auth token incl. `"plain:secret123"`; six parsers
  populate it; Aruba render emits `authentication mode
  plaintext-password "<value-after-plain:>"`. The sanitiser's field
  walk (sanitize.py:186-360) covers hostname/domain/IPs/descriptions/
  local-users/SNMP/RADIUS/DHCP-DNS/static-gw/Tier-3 but has **no**
  `vrrp_groups` branch. No `Substitution` warns the operator.
* **Not previously known:** absent from `SECURITY.md` § Sanitiser table
  and from its Known-Limitations table (unlike IPv6/banner gaps, which
  are documented).
* **Suggested direction:** add a `vrrp_groups[].authentication` redaction
  (preserve the `<scheme>:` prefix, replace the value via
  `redact_secret("VRRP")`, emit a `Substitution`); strip
  `raw_sections` for defence-in-depth; update `SECURITY.md` +
  `BUG_REPORTING.md` in the same commit per the AGENTS.md "new
  redaction category" doc-sync row.

### CF-02 — README demo command broken in wheel + Docker image (no top-level `tools/`) — **P2**

* **File:line:** `pyproject.toml:122-124` (packages.find excludes
  `tools*`); `Dockerfile:35-36,69` (no `tools/` COPY); `README.md:24,52,163`
  and `tools/demo.py:14-15` (instructions that assume `tools/demo.py`
  is present).
* **Claim:** `tools/demo.py` ships in neither the PyPI wheel nor the
  GHCR/Docker Hub image, but the README's headline demo
  (`docker run … python tools/demo.py`) and the `pip install`-oriented
  quickstart both invoke it → file-not-found for operators following the
  docs.
* **Evidence:** see § 6.2. `demo.py` imports only from the installed
  `netcanon` package, so the code is correct — this is a
  packaging/doc-sync gap, not a code bug. Confirms Fleet D's finding.
* **Suggested direction:** promote `demo.py` to a `netcanon` console
  script (`netcanon demo`) so it ships with the package, OR add
  `tools/` to the wheel + a Docker `COPY tools/ /app/tools/`, OR correct
  the README to a source-checkout-only framing. Update README + the
  AGENTS.md "packaging / distribution workflow changes" doc-sync targets
  together.
* `UNVERIFIED` (runtime repro not run — static inclusion analysis is
  conclusive).

### CF-03 — Junos render raises bare `TypeError`; seven peers raise `RenderError` — **P3**

* **File:line:** `netcanon/migration/codecs/juniper_junos/render.py:104-108`.
* **Claim:** Junos render's wrong-type guard raises `TypeError`, diverging
  from the `RenderError` contract every other codec honours
  (`codecs/base.py:228-240` documents `Raises: RenderError`).
* **Blast radius:** **Contained on the pipeline path** — the broad
  `except Exception` at `migration_pipeline.py:255` catches it and
  produces a clean `failed` job (no 500); the only visible difference is
  the `job.error` prefix ("unexpected error in stage rendering" vs
  "render failed"). The **second** render call site,
  `tools/sanitize.py:159`, has no try/except and is reached by the HTTP
  endpoint that catches only `ParseError` (`api/routes/sanitize.py:59`),
  so a `TypeError`/`RenderError` there would be an unhandled 500 — but
  `sanitized_intent` is always a `CanonicalIntent` (model_copy), so the
  guard is structurally unreachable on that path *today*. Net: latent
  contract inconsistency, no live 500.
* **Evidence:** § 3.2 table (8 codecs, 7×`RenderError` vs 1×`TypeError`).
* **Suggested direction:** change the Junos guard to
  `raise RenderError("juniper_junos: tree must be a CanonicalIntent.",
  yang_path="/")` to match the other seven; one-line fix, removes the
  contract divergence and normalises the `job.error` prefix.

### CF-04 — `snmp.contact` (and other PII/network fields) not redacted by sanitiser — **P3**

* **File:line:** `netcanon/tools/sanitize.py:267-309` (SNMP block walks
  community + v3 users only, not `location`/`contact`/`trap_hosts`).
* **Claim:** `CanonicalSNMP.contact` commonly holds an operator email /
  name (`admin@corp.example`, "Jane Doe x4012"); it passes through
  sanitisation verbatim. Same for `snmp.location`, `snmp.trap_hosts`,
  `radius_servers[].host`, `dhcp_servers[].gateway`/`domain_name`,
  `static_routes[].destination`, and `vlan.ipv4_addresses` (SVI L3).
* **Evidence:** § 4.2 coverage table.
* **Suggested direction:** at minimum redact `snmp.contact` (PII) and
  VLAN-SVI IPv4 (same class as interface IPv4 which *is* redacted).
  Document the residual network-field passthrough in
  `BUG_REPORTING.md` if a decision is made to leave it (consistency with
  the honestly-documented IPv6 limitation).

### CF-05 — `MAX_CONFIG_SIZE` does not guard the migration/sanitise paste path — **OBSERVATION**

* **File:line:** `api/routes/_migration_helpers.py:86`
  (`return body.raw_text`); `api/routes/sanitize.py:54-55`
  (`await config.read()`), vs the 50 MB cap at `file_store.py:152-156`.
* **Claim:** the documented 50 MB cap fires only on the backup-save
  path; pasted `raw_text` to `/migration/plan` and uploads to
  `/sanitize` are unbounded by it. The 2026-05-21 ReDoS dismissal cited
  the 50 MB cap as a compensating control "no unbounded input path
  reaches this regex" — that's true for the *collector* path but not the
  *paste* path.
* **Why only OBSERVATION:** regexes are polynomial + line-bounded, so
  this is not a ReDoS vector; the realistic worst case is transient
  memory pressure from a huge paste, and the threat model is
  loopback / operator-proxied. Still worth a note so the "50 MB cap
  protects all parse paths" framing isn't over-trusted.
* **Suggested direction:** apply a `len(raw)`/`Content-Length` check in
  `resolve_input_text` + `post_sanitize` reusing `MAX_CONFIG_SIZE`, OR
  amend the triage note to scope the compensating control to the
  collector path.

### CF-06 — Diagnostic `job.error` prefix inconsistency (subsumed by CF-03) — **OBSERVATION**

Captured under CF-03; recording separately for the findings register:
a Junos render type-mismatch yields `job.error = "unexpected error in
stage rendering: …"` while all other codecs yield `"render failed:
…"`. Cosmetic; fixed for free by the CF-03 one-liner.

---

## 8. What's GOOD

The cross-cutting posture is, on the whole, strong and the prior
hardening clearly held:

* **Exception taxonomy + pipeline containment are textbook.** Typed
  `ParseError`/`RenderError` with structured attributes; an honest broad
  catch-all that preserves the failing stage and logs the traceback; the
  route layer always returns a terminal-state job. The backup-side
  `_errors.py` translator (suppressing internal paths + multi-line
  upstream noise, host-prefixing, dispatch-by-`isinstance` with
  subclass-ordering documented) is a model of operator-facing error
  hygiene.
* **All XML input parsing is on `defusedxml`** with explicit
  `DefusedXmlException`→`ParseError` wrapping at both sites; render-side
  ET use is correctly left on stdlib. The triage swap stuck.
* **No dangerous primitives anywhere** — zero `eval`/`exec`/`os.system`/
  `pickle`/`marshal`/unsafe-`yaml.load`. The single `subprocess` site is
  list-form, desktop-gated, extension-whitelisted, and
  `resolve_path()`-guarded.
* **`file_store` path-traversal + size guards are intact** — strict
  filename regex + `is_relative_to(storage_root)` on both candidates +
  50 MB save cap; filename built from validated `type_key` + sanitised
  host.
* **Credential encryption is sound** — 3-tier Fernet resolution, lazy
  init, legacy-plaintext migration, best-effort `chmod 0o600`, no
  credential value reaching any logger.
* **Job-registry LRU is correct** — `OrderedDict` + `move_to_end` +
  `popitem(last=False)`, disk-backed lazy-load, cap-0 disable, negative
  guard.
* **No ReDoS** — the parser regex corpus has no nested-quantifier
  shapes; line-oriented parsing bounds every match.
* **Dependency pins are reasonable** and `defusedxml` is floored at the
  fix line; the lock-file gap is honestly documented as pending.
* **The sanitiser does the hard 80% right** — local-user hashes (format-
  preserving), SNMP community, SNMPv3 auth/priv, RADIUS keys, hostname/
  domain/description/IPv4 are all redacted with cross-reference-stable
  counters and a `--dry-run` audit log. CF-01/CF-04 are the missing
  20%, not a broken design.

---

## 9. Coverage table

| Sub-lens | Surface | Coverage | Verdict |
|---|---|---|---|
| Error-handling | `codecs/base.py` taxonomy | full read | clean |
| Error-handling | `migration_pipeline.py` try/except | full read | exemplary |
| Error-handling | `api/_errors.py` backup translator | full read | exemplary |
| Error-handling | Junos `TypeError` trace (both render call sites) | full trace | CF-03 (P3), contained |
| Error-handling | route-layer status handling (`migration.py`, `sanitize.py`, `configs.py`) | full read | clean |
| Security | XML parse-site inventory (7 refs) | full grep + read | all-on-defusedxml = YES |
| Security | sanitiser vs canonical model (every field) | full cross-check | CF-01 (P2) + CF-04 (P3) |
| Security | injection/SSRF/deserialization grep | full tree | clean (1 safe subprocess) |
| Security | `file_store` path/size guard | full read | clean |
| Security | `paramiko` AutoAddPolicy trust model | full read | documented/dismissed |
| Security | `credentials.py` + `security/migration.py` | full read | clean |
| Performance | ReDoS scan (5 largest parsers + all parse.py) | targeted grep + spot read | no nested quantifiers |
| Performance | `job_registry.py` LRU | full read | correct |
| Performance | size-guard / paste path | traced | CF-05 (OBSERVATION) |
| Dependencies | `pyproject.toml` pins + `defusedxml` | full read | clean (lock pending, documented) |
| Packaging | wheel + image ship `tools/`? | `pyproject` + `Dockerfile` + `.dockerignore` + `demo.py` imports | CF-02 (P2), confirms Fleet D |

Files read in full or substantial part: `codecs/base.py`,
`services/migration_pipeline.py`, `api/_errors.py`,
`api/routes/migration.py`, `api/routes/_migration_helpers.py`,
`api/routes/sanitize.py`, `api/routes/configs.py` (open endpoint),
`tools/sanitize.py`, `migration/canonical/intent.py`,
`storage/file_store.py`, `storage/job_registry.py`,
`collectors/paramiko_collector.py` (head), `security/credentials.py`,
`security/migration.py`, `migration/_user_secrets.py` (head),
`juniper_junos/render.py` (head), `pyproject.toml`, `Dockerfile`,
`.dockerignore`, `tools/demo.py` (head), plus the 2026-05-21 triage
synthesis and `SECURITY.md` / `AGENTS.md` / `METHODOLOGY.md`.

---

## 10. Open questions

1. **CF-02 runtime repro.** `UNVERIFIED` by static analysis only
   (READ-ONLY, no network/build). A clean-venv `pip install .` + `python
   tools/demo.py` (expect file-not-found) and a `docker run … python
   tools/demo.py` would confirm. Recommend the adversarial pass execute
   this — it's the single highest-confidence, easiest-to-verify finding.
2. **Is there a render call site I missed?** I found exactly two
   (`migration_pipeline.py:239`, `sanitize.py:159`) via Grep on
   `\.render(` / `render_intent`. If the desktop shell
   (`netcanon_desktop/`, CB's scope) calls a codec `render()` outside a
   try/except, the CF-03 blast radius would widen. CB should confirm no
   desktop-side direct render call. `UNVERIFIED` for the desktop package.
3. **Does any codec populate `CanonicalIntent.raw_sections` on a path I
   didn't see?** I found no `.raw_sections[` write in any `parse.py`,
   making the § 4.2.2 strip latent. CC (codec deep-dive) is better
   placed to confirm exhaustively across all parse helpers.
4. **`snmp.contact` real-world prevalence.** CF-04 severity assumes
   `contact` frequently carries email/name PII; if the shipped
   capability matrices mark `/snmp/contact` unsupported on most codecs
   (so it's rarely parsed), the practical exposure shrinks. Cross-check
   with CC's capability-matrix audit.
5. **`/sanitize` upload cap (CF-05).** Confirm whether uvicorn's default
   request-body limit (if any is configured in `main.py`) already bounds
   the paste path; CB owns `main.py`. If a global limit exists, CF-05
   downgrades further.

---

*End of CF chapter.*

# Cluster A — real attack-surface investigation

## Summary

Of the 13 alerts, **2 are REAL** (the two `py/xml-bomb` findings on the
operator-uploaded XML codecs at `opnsense/parse.py:169` and
`cisco_iosxe/codec.py:543` — Python stdlib `xml.etree.ElementTree`
expands internal entities by default and so is vulnerable to the
billion-laughs class of XML bombs on any operator-supplied input).
**2 are REAL but LOW-priority** (the two `zizmor/cache-poisoning`
findings on `pypi-publish.yml` and `desktop-msi-publish.yml` — pip
cache enabled on the build job whose artefact is later published).
**9 are DISMISS** — 7 false-positive `clear-text-logging` findings
(all are the same parse-end summary that logs only `hostname` +
`len(...)` counts; CodeQL flags the call because the `intent`
object also *contains* password fields elsewhere), 1 false-positive
URL-substring check (a `pytest` assertion not a security gate), and
1 false-positive `xss-through-dom` (every interpolation in the
flagged code path goes through a local `escapeHtml()` helper and the
data source is hardcoded server-side capability matrix, not
operator input).

## Per-alert verdicts

| Alert # | Rule | Path:Line | Verdict | Severity | Fix shape (if REAL) | Dismissal reason (if DISMISS) |
|---|---|---|---|---|---|---|
| 77 | zizmor/cache-poisoning | .github/workflows/pypi-publish.yml:35 | REAL | low | Remove `cache: "pip"` on the build job — single-shot publish, no cache benefit. (Or: leave + dismiss "won't fix" with OIDC Trusted Publishing as compensating control.) | |
| 58 | zizmor/cache-poisoning | .github/workflows/desktop-msi-publish.yml:74 | REAL | low | Remove `cache: "pip"` on the build-msi job — single-shot publish, no cache benefit. | |
| 16 | py/incomplete-url-substring-sanitization | tests/unit/migration/test_synthetic_mikrotik_routeros_kitchen_sink.py:86 | DISMISS | n/a | | `used in tests`: line is `assert "pool.ntp.org" in intent.ntp_servers` — a pytest assertion that the canonical NTP-server list contains the expected pool host. Not URL routing, no security boundary. |
| 15 | py/xml-bomb | netcanon/migration/codecs/opnsense/parse.py:169 | REAL | high | Switch `xml.etree.ElementTree.fromstring` to `defusedxml.ElementTree.fromstring` (or pass an `XMLParser` with `forbid_dtd=True`). Add `defusedxml>=0.7.1` to project dependencies. | |
| 14 | py/xml-bomb | netcanon/migration/codecs/cisco_iosxe/codec.py:543 | REAL | high | Same fix as alert #15 — switch this codec's `ET.fromstring` to `defusedxml.ElementTree.fromstring`. | |
| 11 | py/clear-text-logging-sensitive-data | netcanon/migration/codecs/juniper_junos/render.py:1195 | DISMISS | n/a | | `false positive`: the flagged `logger.debug` only consumes `tree.hostname`, `len(tree.<list>)` counts, and `len(result)`. No password / credential field is passed. CodeQL flags it because the `tree` object also contains credential-bearing sub-fields. |
| 10 | py/clear-text-logging-sensitive-data | netcanon/migration/codecs/aruba_aoss/parse.py:1201 | DISMISS | n/a | | `false positive`: same parse-end summary shape — logs only `intent.hostname` + `len(intent.<list>)` counts + `len(raw)`. No credential value reaches the logger. |
| 9 | py/clear-text-logging-sensitive-data | netcanon/migration/codecs/cisco_iosxe_cli/parse.py:574 | DISMISS | n/a | | `false positive`: identical parse-end summary shape. Only `hostname` + counts are logged. |
| 8 | py/clear-text-logging-sensitive-data | netcanon/migration/codecs/juniper_junos/parse.py:793 | DISMISS | n/a | | `false positive`: identical parse-end summary shape. Only `hostname` + counts (including `len(group_lines)` and `len(applied_groups)`) are logged. |
| 7 | py/clear-text-logging-sensitive-data | netcanon/migration/codecs/fortigate_cli/parse.py:945 | DISMISS | n/a | | `false positive`: identical parse-end summary shape, plus a secondary `logger.debug` at line 942 that logs `len(ignored_paths)` and the first 15 sorted *config-path* strings (e.g. `system.global`) — these are CLI section names, not credential values. |
| 6 | py/clear-text-logging-sensitive-data | netcanon/migration/codecs/arista_eos/parse.py:582 | DISMISS | n/a | | `false positive`: identical parse-end summary shape. The "secret" entries in the message string are CodeQL flow-tracking through the `intent.snmp` ternary (`"yes" if intent.snmp else "no"`) — the literal string `"yes"`/`"no"` is what reaches the formatter, not any community/secret value. |
| 5 | py/clear-text-logging-sensitive-data | tools/demo.py:227 | DISMISS | n/a | | `false positive`: line 227 is `print(body)` inside `_print_section(title, body)`. `body` comes from hardcoded synthetic fixtures (the `_CISCO_IOSXE` / `_FORTIGATE` / `_ARUBA_AOSS` / `_OPNSENSE` string constants at the top of the file — verified, no `password`/`secret` literals) and from `job.rendered`. The script is an operator-local demo printing to stdout, not a server-side logger; no credential exfiltration path exists. |
| 4 | js/xss-through-dom | netcanon/templates/definitions.html:877 | DISMISS | n/a | | `false positive`: the `innerHTML` sink at line 877 receives `renderBucket(caps, bucket)` output; every interpolation in `renderBucket` (lines 815, 824, 832, 834-836) goes through the local `escapeHtml()` helper (lines 843-848) which HTML-encodes `&<>"'`. The `caps` data source is the hardcoded server-side `CapabilityMatrix` from `/api/v1/migration/adapters/{name}/capabilities` (`netcanon/api/routes/migration.py:163`), not operator input. |

## REAL findings — deeper notes

### Alerts #14 + #15 — `py/xml-bomb` on operator-uploaded XML codecs (HIGH)

Both alerts share the same root cause: the OPNsense and Cisco IOS-XE
(NETCONF) codecs parse operator-supplied XML via `xml.etree.ElementTree.fromstring`.
Verified locally on Python 3.14.4 that stock ET expands internal
entities by default — a 5-line billion-laughs payload (`<!ENTITY lol "lol">`
+ `<!ENTITY lol1 "&lol;&lol;&lol;">` + `&lol1;`) returns
`'lollollol'` instead of raising. External entities (XXE
`SYSTEM "file:///etc/passwd"`) are blocked since Python 3.7.1, but
the billion-laughs / quadratic-blowup class is not.

Attacker model: an operator uploads a config they've been emailed
by a third party (or that's been tampered with in transit), the
codec parses it via the migration API at `/api/v1/migration/plan`
(routed through `run_plan` in `netcanon/api/routes/migration.py`),
and a memory-exhaustion DoS hangs the FastAPI worker. Real even
for a benign-operator threat model because uploaded configs are
not guaranteed to be from a trusted source — the entire point of
the codec is to accept "the config someone sent me" as input.

Fix shape: switch both `ET.fromstring(raw)` calls
(`opnsense/parse.py:169`, `cisco_iosxe/codec.py:543`) to
`defusedxml.ElementTree.fromstring`. Add `defusedxml>=0.7.1` to
`pyproject.toml` dependencies. The defusedxml drop-in raises
`EntitiesForbidden` on bomb payloads while preserving full
compatibility with normal config XML. Sweep for any other
`ET.fromstring` / `ET.parse` / `ET.XMLParser` sites — Grep
across `netcanon/` shows exactly the two flagged sites plus the
opnsense `render.py` import (which is only used for *generating*
XML, not parsing input — render is safe).

Doc-sync row that applies: `SECURITY.md` references the codec
parsing surface in its "supply-chain integrity" section; the fix
PR should update the SECURITY.md threat-model note for
operator-uploaded XML.

### Alerts #58 + #77 — `zizmor/cache-poisoning` on publish workflows (LOW)

Both alerts flag the same pattern: `actions/setup-python@v6` with
`cache: "pip"` on a job whose later steps produce the published
artefact (wheel/sdist for PyPI, MSI for the GitHub Release). The
hypothetical attack: a cache-key collision or compromise injects a
tampered transitive dependency into the build environment, which
gets baked into the published artefact and signed off by OIDC.

Reality check: GitHub's pip-cache scope is per-repo + per-cache-key,
so cross-repo poisoning isn't a vector. The PyPI publish step uses
OIDC Trusted Publishing (no API token), and the MSI publish is
GitHub-internal. For a single-maintainer repo with no PR-cache
sharing, the residual risk is low.

Fix shape: drop `cache: "pip"` from both publish workflows.
Single-tag publish jobs run once per release and don't benefit from
the cache (no warm dep tree to reuse — first install is also the
last install for that workflow run). This is the smallest possible
patch: delete one YAML line per workflow. User policy ("fix HIGH +
MEDIUM") technically lets these dismiss as low-band, but the patch
is so small that fixing is cheaper than writing the dismissal
reason.

If preferred, alternative dismissal is `won't fix` with the
comment "OIDC Trusted Publishing + Trivy supply-chain scan are
compensating controls; pip cache scoped per-repo with no PR-cache
sharing."

## DISMISS findings — deeper notes

### Alerts #6, #7, #8, #9, #10, #11 — `clear-text-logging-sensitive-data` on codec parse/render summaries

All six alerts target the same idiom — a `logger.debug(...)` at the
tail of each codec's `parse()` or `render()` function emitting a
one-line "parsed/rendered: hostname=%r ifaces=%d ... (input=%d chars)"
summary. Inspecting each flagged line individually:

* `juniper_junos/render.py:1195` → arg is `tree.hostname` (one string).
  Remaining args are `len(tree.interfaces)`, `len(tree.vlans)`,
  `len(tree.static_routes)`, `len(tree.local_users)`, the literal
  `"yes"` or `"no"`, and `len(result)`. Zero credential values.

* `aruba_aoss/parse.py:1201` → same pattern, `intent.hostname` + counts.

* `cisco_iosxe_cli/parse.py:574` → same pattern, `intent.hostname` + counts.

* `juniper_junos/parse.py:793` → same pattern plus `len(group_lines)`
  and `len(applied_groups)` (both counts of `apply-groups` directive
  names — not credentials).

* `fortigate_cli/parse.py:945` → same pattern; line 945 is `len(intent.local_users)`.
  CodeQL is tracking taint through the *count* of local users, not
  the user records themselves.

* `arista_eos/parse.py:582` → same pattern; line 582 is `intent.hostname`.

CodeQL flags these because the `intent` / `tree` argument *contains*
password-bearing sub-fields (e.g. `intent.local_users[i].password_hash`),
and the dataflow analyser sees the object flowing into a `logger.*`
call. The actual log-emission path doesn't read any of those
sub-fields — only `.hostname` and `len(...)`. The wholesale-class
dismissal reason is "false positive on flow-tracking through
container objects; only scalar counts and the hostname literal are
formatted into the log line".

Note also that AGENTS.md and BUG_REPORTING.md collectively impose a
project-wide rule that no real password hashes ever appear in test
fixtures or logs — these debug logs are at `DEBUG` level (silent at
default `INFO`) and emit no credential values. Compliant by design.

### Alert #5 — `clear-text-logging-sensitive-data` on `tools/demo.py`

Line 227 is `print(body)` inside the `_print_section(title, body)`
helper. The `body` parameter has two upstream sources: hardcoded
fixture strings at the top of `demo.py` (`_CISCO_IOSXE`,
`_FORTIGATE`, `_ARUBA_AOSS`, `_OPNSENSE` — verified, none contain
`password` / `secret` / `community` literals; they're VLAN, DNS,
DHCP, interface configs only), and `job.rendered` from
`run_plan(...)` (rendered translation output, never an unredacted
credential dump). The script is a CLI demo printing to local stdout;
even if a future fixture grew credential fields, this is operator-
local output, not a server-side log destination. Dismissal:
`used in tests` with the comment "operator-local demo CLI; sources
are hardcoded synthetic fixtures + own-process translation output;
no remote logging or credential extraction path".

### Alert #16 — `py/incomplete-url-substring-sanitization` on a pytest assertion

Line 86 is `assert "pool.ntp.org" in intent.ntp_servers`. This is a
pytest unit test verifying that the parsed NTP-server list from a
synthetic MikroTik fixture contains the expected pool host. There's
no URL handling, no allowlist check, no security boundary — the `in`
operator is set/list membership, not URL substring sanitisation.
Dismissal: `used in tests` with the comment "pytest assertion on
parsed canonical NTP-server list membership; not a URL trust check".

### Alert #4 — `js/xss-through-dom` on the Definitions page capability detail row

Line 877 is `td.innerHTML = renderBucket(caps, bucket);` inside the
Vendors+codecs capability-detail expansion handler. Tracing the data
flow:

1. `caps` comes from `fetchCaps(codecName)` (line 779-800), which
   GETs `/api/v1/migration/adapters/{name}/capabilities`.
2. Server side, that endpoint (`netcanon/api/routes/migration.py:163,
   `get_codec_capabilities`) returns the codec's hardcoded
   `CapabilityMatrix` declaration (compiled-in per-codec config, not
   operator input).
3. Inside `renderBucket()` (lines 802-841), every interpolation
   reaches `innerHTML` via the local `escapeHtml()` helper
   (lines 843-848): `escapeHtml(p)` for supported paths,
   `escapeHtml(e.path || '')` for path entries,
   `escapeHtml(sev)` for severity tags, `escapeHtml(e.reason || ...)`
   for reasons.

The data source is server-controlled (compiled), and the sink is
escape-encoded. CodeQL flags it because `innerHTML` is a known XSS
sink — the flow analyser doesn't model the inner `escapeHtml()`
encode-then-concatenate pattern as safe. Dismissal: `false positive`
with the comment "every interpolation in renderBucket() goes through
the inline escapeHtml() helper; the data source (CapabilityMatrix)
is compiled-in server-side, not operator-supplied".

## Cross-cutting observations

* **The 7 `clear-text-logging` findings are all the same parse/render
  closing-summary idiom.** They should bulk-dismiss as one class with
  a shared comment. Worth filing a CodeQL suppression comment on each
  line so future scans don't re-flag.

* **Only stdlib `xml.etree.ElementTree` is in use** — no `lxml` and
  no existing `defusedxml`. Verified via `Grep` across `netcanon/`:
  exactly three import sites (`opnsense/parse.py`, `opnsense/render.py`,
  `cisco_iosxe/codec.py`), of which only the two `parse.py-side`
  uses consume external input. `render.py` only *generates* XML and
  is unaffected by the bomb class. Single dependency add + 2 import
  swaps = full fix.

* **`defusedxml` is the canonical fix** because the codebase requires
  Python 3.11+ — `defusedxml.ElementTree` has a drop-in `fromstring`
  with identical signature, no API-shape change needed at call sites.
  Confirmed stdlib behaviour empirically: billion-laughs returns
  expanded text on Python 3.14, while XXE-via-SYSTEM raises a
  ParseError (the 3.7.1+ improvement). So XXE is already mitigated
  for these codecs — only the entity-bomb class needs the fix.

* **The publish-workflow cache-poisoning findings are
  one-line YAML deletes.** The smaller patch (drop `cache: "pip"`)
  is strictly cheaper than the dismissal-and-justify path, and
  removes a real attack surface independent of severity grading.
  Recommended: fix not dismiss.

* **No template-injection findings reached this cluster** — cluster D
  already-identified contains 2 zizmor/template-injection alerts;
  cluster A is unaffected.

# 19 — Docs-honesty + Web UI/UX (merged lens)

Reviewer: Fable fresh-eyes pass, 2026-07-03, repo @ `v0.4.15` (`79c29a0`).
Scope A: README / ARCHITECTURE / CHANGELOG / SECURITY / CONTRIBUTING /
BUG_REPORTING / AGENTS / THIRD-PARTY-NOTICES / TRADEMARKS / docs/ (excl.
forbidden dirs).  Scope B: `netcanon/templates/` + partials, migrate /
sanitize / backup flows.  Method: every doc claim checked against code or a
read-only `py` probe; no state-changing commands run.

**Verdict: GO-WITH-FIXES.**  The doc corpus is unusually honest and almost
everything spot-checked verified clean (see "Verified-true claims" at the
bottom).  The real findings cluster in one place: **the 0.4.13–0.4.14 codec
arc (dot1q_vlan, FHRP owner/255) shipped without its doc-sync**, plus one
genuine UI bug in the migrate page's parse-failure recovery banner and an
attribution gap in THIRD-PARTY-NOTICES.

Note on process: one broad grep I ran matched lines inside
`docs/codebase-review/` (forbidden dir).  I did not open any file there and
nothing below derives from it.

---

## MAJOR findings

### M-1 (UI bug) — Parse-failure "Did you mean" banner renders the literal string `undefined`

`netcanon/templates/migrate.html:1372-1375`:

```js
var suggestedAdapter = adapterEntry(top.codec);
var suggestedLabel = suggestedAdapter
  ? (suggestedAdapter.vendor_display_name || suggestedAdapter.name)
  : top.codec;
```

`adapterEntry()` (migrate.html:860-875) returns `{codec, label, desc,
sample, ext, inputFormat}` — it has **no** `vendor_display_name` and no
`name` key.  So whenever the adapter IS found (the normal case, since the
`adapters` cache is loaded at page load), `suggestedLabel` is `undefined`,
and `escapeHtml(undefined)` → the string `"undefined"` (migrate.html:1628
does `String(s)`).  Operator-visible result on every parse failure /
empty-completed enrichment (migrate.html:1301-1311 triggers):

- banner text: **"Did you mean: undefined  \<NN% confidence\>"**
  (migrate.html:1384-1390)
- button label: **"Switch source to undefined and retry"**
  (migrate.html:1398-1399)

The button still *works* (it applies `top.codec`, migrate.html:1405), but
this is corrupted copy on the app's flagship error-recovery flow (the
Round-4 one-click recovery).  Contrast the *proactive* detect banner, which
does it correctly via the raw adapter record
(`adapters.find(...)` → `a.vendor_display_name || a.name`,
migrate.html:1146-1147).  No e2e test asserts the visible label — only the
testid is documented (`tests/testid_reference.md:513`) — which is why it
survived.  Fix: use `adapters.find(...)` like line 1147, or return
`vendor_display_name` from `adapterEntry`.

### M-2 (docs-honesty + operator-facing UI text) — Junos `unit N vlan-id` still declared "parses-and-ignores"; contradicts the shipped 0.4.13 dot1q_vlan surface

Shipped reality (0.4.13, PRs #239–#243): `unit N vlan-id` parses onto the
dedicated `CanonicalInterface.dot1q_vlan` surface
(`netcanon/migration/codecs/juniper_junos/parse.py:1516-1526`) and
`/interfaces/interface/dot1q-vlan` sits in the junos **supported** list
(`netcanon/migration/codecs/juniper_junos/codec.py:135-139`).

Contradicting text, in priority order:

1. `netcanon/migration/codecs/juniper_junos/codec.py:264-277` — the
   `/interfaces/interface/subinterfaces/subinterface` `LossyPath.reason`
   still says *"per-unit VLAN tagging (`unit N vlan-id 100`) still
   parses-and-ignores pending a canonical tagged-subinterface model."*
   This reason string is **rendered to operators** in the migrate page's
   Validation details → Lossy panel, so the UI itself now asserts the
   opposite of what the same codec's supported list declares.  A
   matrix-honesty text drift inside the matrix itself.
2. `docs/CAPABILITIES.md:278` — repeats the same stale sentence in the
   juniper_junos per-codec table (the doc that calls itself "the
   operator-facing source of truth").
3. `docs/CAPABILITIES.md` contains **no mention of `dot1q_vlan` at all**
   (grep: only the unrelated IOS-XR "dot1q→VLAN" phrasing at :31/:366) —
   the new Tier-1/Tier-2 surface wired across junos / iosxe_cli / nxos /
   arista / iosxr (plus the #244 aoscx architecturally-unsupported
   adjudication) is invisible to the capability doc.

### M-3 (attribution gap) — THIRD-PARTY-NOTICES.txt omits four direct runtime deps that the MSI redistributes

`THIRD-PARTY-NOTICES.txt` frames itself as the attribution record for
everything the MSI bundles (lines 4-14) and even lists deep transitive deps
(cffi, pycparser, six, h11 — lines 69-87).  Missing entirely, though all
four are **direct runtime dependencies** (`pyproject.toml:55-93`) and
appear in the dependency closure (`requirements.lock`):

- `pydantic-settings` (MIT) — requirements.lock:588
- `aiofiles` (Apache-2.0) — requirements.lock:7
- `apscheduler` (MIT) — requirements.lock:25
- `tzlocal` (MIT) — requirements.lock:756

Also absent: `rich` / `pygments` / `ruamel-yaml` (netmiko's transitive
chain, requirements.lock:715/592/719), which land in the MSI freeze too.
MIT/Apache attribution obligations technically attach to the MSI
redistribution, so the "Additional permissive components (direct +
transitive deps redistributed in the MSI)" section is incomplete on its
own terms.  Low legal risk (all permissive), but this file's whole purpose
is completeness.

---

## MINOR findings

### m-1 — SECURITY.md § "Credential Exposure in the Browser" describes flows that were removed by the cred-scrub remediation

`SECURITY.md:229-241` claims:

- *"Passwords are fetched via `GET /api/v1/devices/{id}` when a profile is
  selected"* (dashboard bullet) — false since the #53–#65 cred-scrub.
  `netcanon/templates/index.html:189-193` explicitly documents the current
  behaviour: *"Credentials are NOT fetched — the backup endpoint resolves
  them server-side, so the plaintext password never reaches the browser."*
  And the API cannot return them anyway: every devices route responds with
  `DeviceProfilePublic`, which strips credentials
  (`netcanon/api/routes/device_profiles.py:33-49`).
- *"`runDeviceBackup()` fetches the full profile from the API before
  submitting a backup job"* (devices bullet) — false;
  `netcanon/templates/devices.html:412-433` sends only profile id +
  non-secret fields.

The error direction is "understates security" (actual behaviour is
stronger), but SECURITY.md:635-647 mandates that this doc track
security-relevant changes, and the same file's own Migration section
(:184) already describes the stripped `DeviceProfilePublic` — the doc is
internally inconsistent.

### m-2 — CAPABILITIES.md still says AOS-S `owner` → priority 254 "(255 unrepresentable)"

`docs/CAPABILITIES.md:257`.  As of 0.4.14 (#247), `owner` maps to 255 and
round-trips symmetrically: `netcanon/migration/codecs/aruba_aoss/parse.py:604-659`
("now representable"), `render.py:675-678` (255 → `owner`).  The FHRP
widening (priority 0-255, group_id 0-4095, FortiGate priority-255
preserved) has no reflection anywhere in CAPABILITIES.md.

### m-3 — CONTRIBUTING.md fixture-path step names the wrong regen tool/output pairing

`CONTRIBUTING.md:50-52`: "Run the cross-mesh audit
(`python tools/run_full_mesh.py --matrix`) and commit the regenerated
`tests/fixtures/real/PHASE4_RECONCILIATION.md`."  `--matrix` regenerates
`CROSS_MESH_RESULTS.md` (`tools/run_full_mesh.py:24-28,69`);
`PHASE4_RECONCILIATION.md` is produced by
`tools/run_phase4_reconciliation.py` (its own header, line 3).  A
contributor following the steps literally will never regenerate the file
they're told to commit.

### m-4 — CAPABILITIES.md § E rename-category claim out of date

`docs/CAPABILITIES.md:549-554`: "Today only the `cisco_iosxe` (NETCONF)
and `opnsense` codecs declare anything — both list `"snmpv3"`."  The
NETCONF codec declares `{"snmpv3", "ports"}`
(`netcanon/migration/codecs/cisco_iosxe/codec.py:220-223`), and the
"ports" entry has its own operator-visible banner behaviour the doc never
mentions.

### m-5 — CAPABILITIES.md:95 hard-codes "all seven bidirectional codecs" for VRRP

Stale count in a 12-codec registry (nxos renders FHRP as HSRP-lossy
:348, aoscx declares VRRP unsupported :403, vyos/iosxr have no FHRP
rows).  Violates the repo's own "never hard-code counts in prose docs"
rule (`CONTRIBUTING.md:99`).

### m-6 — Sanitize page category labels cover 12 of ~29 emitted categories

`netcanon/templates/sanitize.html:196-209` maps 12 categories; the library
emits ≥29 distinct ones (`netcanon/tools/sanitize.py` — e.g. `mac`,
`ipv6-public`, `vrf-name`, `vlan-name`, `vrrp-authentication`,
`snmp-contact`, `snmp-location`, `snmpv3-engine-id`, `route-distinguisher`,
`evpn-type5-prefix`, `apply-groups-stripped`, `route-target`,
`static-route-description`, `mcast-group`).  The fallback renders the raw
key (sanitize.html:210) so nothing breaks — but roughly half of a typical
audit table shows machine-style keys where the page promises "human prose".
Cosmetic; the falls-through-safely design was deliberate.

### m-7 — SECURITY.md stale line-number citations

`SECURITY.md:287-288`: "opnsense/parse.py (line 169)" — actual defused
parse call is at `netcanon/migration/codecs/opnsense/parse.py:181`;
"cisco_iosxe/codec.py (line 543)" — actual at
`netcanon/migration/codecs/cisco_iosxe/codec.py:799`.  The *claims*
themselves verified true (defusedxml at both sites, DefusedXmlException
handled); only the line anchors rotted.  Suggest dropping line numbers.

### m-8 (nit) — CONTRIBUTING.md:115-116 "Local pre-commit hooks should catch most issues before push"

The repo ships only a **pre-push** hook (`scripts/git-hooks/pre-push`);
there is no `.pre-commit-config.yaml` and no pre-commit hook.  Wording
implies tooling that doesn't exist.

---

## Verified-true claims (checked, no finding — do not re-hunt)

- **CHANGELOG integrity**: every stable tag `v0.1.1..v0.4.15` has a dated
  `## [X.Y.Z]` header; `v0.4.3`/`v0.4.4` were never tagged (tag list
  confirms), so the 0.4.5→0.4.2 header jump is correct, and the guard
  (`tests/unit/test_changelog.py`) covers exactly this.  `[0.4.15]` dated
  2026-07-03 sits at HEAD tag `79c29a0`.  All 0.4.13–0.4.15 PR refs
  (#237–#264) match `git log` one-for-one, including the per-codec IPv6
  static-route attributions (#251–#260) and mikrotik #261/#262, iosxr #263.
- **README demo honesty**: ran `py -c` probe of
  `netcanon.tools.demo main(['--pair','cisco__junos'])` — output shows
  `GigabitEthernet1/0/1 → ge-1/0/1` and ethernet-switching membership
  exactly as README claims; demo uses `run_plan_with_rename`
  (`netcanon/tools/demo.py:272`), so the old bare-`run_plan` dishonesty is
  gone.  All four advertised scenarios exist (demo.py:178-213).
- **README trust-signal numbers**: "8 of the 12 codecs" expectation
  coverage and "5 residual high-severity cells (4 real + 1 synthetic)"
  match `tests/fixtures/real/PHASE4_RECONCILIATION.md:9,16` and the
  per-cell matrix.
- **README CI claims**: unit+integration on 3.11/3.12/3.13/3.14
  (`.github/workflows/ci.yml:69,95-98`); e2e/desktop as separate jobs;
  `-x` comes from pyproject addopts (`pyproject.toml:190`).
- **Install docs vs Dockerfile**: `ENTRYPOINT ["netcanon","serve"]`,
  `NETCANON_HOST=0.0.0.0`, EXPOSE 8000, `/health` healthcheck
  (`Dockerfile:100-118`) all match README/SECURITY fail-closed narrative;
  `block_private_egress` default False and `ssh_host_key_checking`
  default `"tofu"` confirmed (`netcanon/config.py:223-224`).
- **Template security claim**: zero `| safe` filters anywhere under
  `netcanon/templates/` (SECURITY.md:408-411 verified).
- **BUG_REPORTING.md**: CLI flags `-i/-o/--source-vendor/--dry-run` match
  `netcanon/cli.py:49-71`; both issue templates + `WANTED.md` exist.
- **pyproject extras** (`dev`, `desktop`, `desktop-build`) match README
  install instructions; `docs/assets/migrate.png` exists.
- **UI a11y bar held** on the pages re-audited (base.html skip-link, focus
  ring token, aria-live toasts with error escalation, dialog
  focus-return in the rename modal, `scope="col"` table headers,
  aria-labels on icon buttons in configs/jobs/index/devices, WCAG-noted
  contrast tokens).  The 20-must-fix UX pass has not visibly regressed
  outside M-1.
- Sanitize page's dual-POST (audit + output in parallel,
  sanitize.html:347-408) is deterministic per-run (counter-per-session
  stable), so the audit table matches the rendered output; error paths all
  route through `formatApiError` — no dead-ends found in the forms audited.

## Suggested fix order

1. M-1 — one-line JS fix + an e2e assertion on the button's visible text.
2. M-2 — rewrite the junos subinterface `LossyPath.reason` (codec.py:264)
   and sync CAPABILITIES.md (junos row + a dot1q_vlan mention in Tier 1/2 +
   the #244 aoscx adjudication); fold m-2/m-4/m-5 into the same doc PR.
3. M-3 — add the four missing entries (+ rich/pygments/ruamel-yaml) to
   THIRD-PARTY-NOTICES.txt.
4. m-1 — rewrite SECURITY.md § Credential Exposure to the server-side
   resolution model; m-3/m-7/m-8 one-liners in the same pass.

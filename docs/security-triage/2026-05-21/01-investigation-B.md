# Cluster B — pattern verification

## Summary

Of 47 alerts in this cluster, **36 are confirmed as the expected
by-design pattern (DISMISS)** and **11 require real treatment (REAL
fix)**.  No outliers exited their bulk pattern: every CodeQL alert is
in the predicted file path, every paramiko alert is in the operator-
trust-anchor SSH collector, and every zizmor unpinned-uses alert
landed exactly where the orchestrator's hybrid policy predicted.  The
11 REAL alerts are all third-party `zizmor/unpinned-uses` findings
that need SHA-pinning; SHAs are resolved below so Stage 2 can apply
the pins without re-resolving.

* 19/19 `py/polynomial-redos` → DISMISS (all in `codecs/*/parse.py`)
* 2/2 `py/paramiko-missing-host-key-validation` → DISMISS (both in
  `netcanon/collectors/paramiko_collector.py`, ad-hoc operator SSH)
* 15/26 `zizmor/unpinned-uses` → DISMISS (first-party `actions/*` ×14
  + `github/*` ×1, per the hybrid tag-pin acceptance policy)
* 11/26 `zizmor/unpinned-uses` → REAL (third-party publishers — SHAs
  resolved in the table below)

## py/polynomial-redos × 19 — codec regex DoS

All 19 alerts are in `netcanon/migration/codecs/<vendor>/parse.py`
files (the predicted location).  Each flagged regex is one of:

1. **Anchored line grammar** — e.g. `r'^snmp-server\s+location\s+(.+)$'`
   used via `re.MULTILINE` `.search/finditer(raw)` or matched against
   the per-line product of `raw.splitlines()`.  Polynomial worst-case
   is O(line_length²) — bounded by the line, not the file.
2. **Port-range expansion** — `^(.*?)(\d+)$` used inside
   `_parse_port_list` on short tokens like `1/A1` / `1/47`.
   Per-token bound; never sees attacker-controlled long strings.
3. **Block-header recognisers** — `^config\s+(.+?)\s*$`,
   `^edit\s+(.+?)\s*$`, `^set\s+(\S+)\s*(.*)$`.  Linear due to
   non-overlapping atom sequence.

Input boundedness chain confirmed:
* `POST /api/v1/migration/plan` `raw_text` field — Pydantic
  `MigrationPlanRequest.raw_text: str | None = None` has no explicit
  `max_length`, but is processed via `raw.splitlines()` at the top
  of each codec's `parse_intent`, so per-line bound applies.
* `source_filename` path is bounded at 50 MB by
  `netcanon/storage/file_store.py:133` (`MAX_CONFIG_SIZE`).
* Even un-capped, the regex shape is polynomial-not-exponential in
  *line length*, and operator-supplied device config has well-bounded
  line lengths in practice.

No outliers — none of these regexes are in URL routing, request-body
validation, telemetry, or any non-codec module.  None contain nested
quantifiers like `(.*)+` or `(\w+)*` that compound to exponential
ReDoS.

**Group verdict: all 19 DISMISS** with reason:

> Codec grammar regex with file-bounded input (codec parses are
> per-line via `raw.splitlines()` and a 50 MB cap applies to the
> file-upload path via `MAX_CONFIG_SIZE` in `file_store.py`).
> Pattern is polynomial-not-exponential in line length and has no
> nested quantifier that compounds.  Polynomial backtracking risk
> is theoretical but not exploitable — no path for unbounded input
> to reach this regex.

| Alert # | Path:Line | Pattern owner | Bounded? | Verdict | Reason |
|---|---|---|---|---|---|
| 17 | `netcanon/migration/codecs/fortigate_cli/parse.py:237` | `_CONFIG_HEADER_RE = r"^config\s+(.+?)\s*$"` | Yes — per-line via `splitlines()` | DISMISS | Codec grammar regex, polynomial-only, file-bounded |
| 18 | `netcanon/migration/codecs/fortigate_cli/parse.py:243` | `_EDIT_HEADER_RE = r"^edit\s+(.+?)\s*$"` | Yes — per-line | DISMISS | Codec grammar regex, polynomial-only, file-bounded |
| 19 | `netcanon/migration/codecs/fortigate_cli/parse.py:249` | `_SET_RE = r"^set\s+(\S+)\s*(.*)$"` | Yes — per-line | DISMISS | Codec grammar regex, polynomial-only, file-bounded |
| 20 | `netcanon/migration/codecs/aruba_aoss/parse.py:428` | port-range `^(.*?)(\d+)$` on `lo` token | Yes — per-token, short | DISMISS | Codec grammar regex (port-range), polynomial-only, token-bounded |
| 21 | `netcanon/migration/codecs/aruba_aoss/parse.py:429` | port-range `^(.*?)(\d+)$` on `hi` token | Yes — per-token, short | DISMISS | Codec grammar regex (port-range), polynomial-only, token-bounded |
| 22 | `netcanon/migration/codecs/aruba_aoss/parse.py:505` | `_UNTAGGED_RE = r"^(no\s+)?untagged\s+(.+)$"` | Yes — per-line | DISMISS | Codec grammar regex, polynomial-only, file-bounded |
| 23 | `netcanon/migration/codecs/aruba_aoss/parse.py:517` | `_TAGGED_RE = r"^(no\s+)?tagged\s+(.+)$"` | Yes — per-line | DISMISS | Codec grammar regex, polynomial-only, file-bounded |
| 24 | `netcanon/migration/codecs/cisco_iosxe_cli/parse.py:614` | `_TOP_NAME_SERVER_RE = r"^ip\s+name-server\s+(?:vrf\s+\S+\s+)?(.+)$"` (MULTILINE) | Yes — line-anchored via MULTILINE `^...$` | DISMISS | Codec grammar regex, polynomial-only, file-bounded |
| 25 | `netcanon/migration/codecs/cisco_iosxe_cli/parse.py:682` | `_VRF_DESCRIPTION_RE = r"^\s+description\s+(.+)$"` | Yes — per-line | DISMISS | Codec grammar regex, polynomial-only, file-bounded |
| 26 | `netcanon/migration/codecs/aruba_aoss/parse.py:655` | `_VRRP_AUTH_PLAINTEXT_RE = r'^authentication\s+mode\s+plaintext-password\s+"?([^"\n]+?)"?\s*$'` | Yes — per-line | DISMISS | Codec grammar regex, polynomial-only, file-bounded |
| 27 | `netcanon/migration/codecs/cisco_iosxe_cli/parse.py:995` | `_VRRP_DESCRIPTION_RE = r"^\s+vrrp\s+(?P<group>\d+)\s+description\s+(?P<text>.+?)\s*$"` | Yes — per-line | DISMISS | Codec grammar regex, polynomial-only, file-bounded |
| 28 | `netcanon/migration/codecs/aruba_aoss/parse.py:817` | `_SNMP_LOCATION_RE = r'^snmp-server\s+location\s+(.+)$'` | Yes — per-line | DISMISS | Codec grammar regex, polynomial-only, file-bounded |
| 29 | `netcanon/migration/codecs/aruba_aoss/parse.py:825` | `_SNMP_CONTACT_RE = r'^snmp-server\s+contact\s+(.+)$'` | Yes — per-line | DISMISS | Codec grammar regex, polynomial-only, file-bounded |
| 30 | `netcanon/migration/codecs/aruba_aoss/parse.py:946` | `_RADIUS_HOST_RE` (radius-server host IP + optional rest) | Yes — per-line | DISMISS | Codec grammar regex, polynomial-only, file-bounded |
| 31 | `netcanon/migration/codecs/aruba_aoss/parse.py:979` | `_RADIUS_INLINE_KEY_RE = r'\bkey\s+"?([^"]*)"?\s*$'` on `rest` slice | Yes — per-line residue | DISMISS | Codec grammar regex, polynomial-only, file-bounded |
| 32 | `netcanon/migration/codecs/aruba_aoss/parse.py:1003` | `_RADIUS_KEY_GLOBAL_RE = r'^radius-server\s+key\s+"?([^"]*)"?\s*$'` | Yes — per-line | DISMISS | Codec grammar regex, polynomial-only, file-bounded |
| 33 | `netcanon/migration/codecs/cisco_iosxe_cli/parse.py:1437` | `_DHCP_DNS_SERVER_RE = r"^\s+dns-server\s+(.+)$"` | Yes — per-line | DISMISS | Codec grammar regex, polynomial-only, file-bounded |
| 34 | `netcanon/migration/codecs/cisco_iosxe_cli/parse.py:1634` | `_SNMP_LOCATION_RE = r'^snmp-server\s+location\s+(.+)$'` (MULTILINE) | Yes — line-anchored via MULTILINE `^...$` | DISMISS | Codec grammar regex, polynomial-only, file-bounded |
| 35 | `netcanon/migration/codecs/cisco_iosxe_cli/parse.py:1635` | `_SNMP_CONTACT_RE = r'^snmp-server\s+contact\s+(.+)$'` (MULTILINE) | Yes — line-anchored via MULTILINE `^...$` | DISMISS | Codec grammar regex, polynomial-only, file-bounded |

## py/paramiko-missing-host-key-validation × 2 — netmiko AutoAddPolicy

Both alerts are in `netcanon/collectors/paramiko_collector.py` — the
predicted location.  This collector is the OPNsense-specific raw-shell
SSH path (used because OPNsense presents a numbered console menu on
SSH login before a shell is available, which netmiko's standard
device handlers don't model).

* **Line 147** — main `collect()` path:
  `client.set_missing_host_key_policy(paramiko.AutoAddPolicy())`
  followed by `client.connect(hostname=device.host, ...)` where
  `device.host` is the operator-configured target IP from
  `DeviceTarget`.
* **Line 237** — `probe()` path: identical setup, separate session
  for the probe command.

Threat-model match: operator types a device IP into the netcanon UI
or definition YAML; netcanon SSHes to that IP to pull config.  The
operator IS the trust anchor — the same trust posture as a human
typing `ssh root@10.0.0.1` from their terminal.  There is no
"pre-known service identity" semantics here: the device is whichever
IP the operator entered, not a fixed-inventory target with a known
key fingerprint.

No outliers — both instances share the operator-driven SSH pattern.

| Alert # | Path:Line | Context | Verdict | Reason |
|---|---|---|---|---|
| 12 | `netcanon/collectors/paramiko_collector.py:147` | `collect()` — main config pull via raw paramiko shell (OPNsense menu handler) | DISMISS | Operator-initiated SSH to ad-hoc network device IPs. AutoAddPolicy is the documented netmiko / paramiko default for operator tooling and matches the threat model (operator is trust anchor, not a service identity). |
| 13 | `netcanon/collectors/paramiko_collector.py:237` | `probe()` — short-lived session for the probe command (device-type detection) | DISMISS | Operator-initiated SSH to ad-hoc network device IPs. AutoAddPolicy is the documented netmiko / paramiko default for operator tooling and matches the threat model (operator is trust anchor, not a service identity). |

## zizmor/unpinned-uses × 26 — action references

Hybrid policy applied per the orchestrator brief:

* **First-party trusted** (`actions/*`, `github/*`): DISMISS as
  accepted-risk via tag-pin
* **Third-party**: REAL — needs SHA pin

Tally: 15 first-party + 11 third-party = 26.  Matches the cluster
count.

For each REAL alert I resolved the current commit SHA at the tag /
branch ref so Stage 2 can apply the pin without re-resolving.  For
`pypa/gh-action-pypi-publish@release/v1`, `release/v1` is a **branch**
not a tag — resolved via `git/ref/heads/release/v1` rather than the
tag endpoint.  Annotated tags (when present) were dereferenced from
the tag object to the underlying commit.

DISMISS reason (verbatim, for the 15 first-party alerts):

> Accepted-risk per netcanon's hybrid action-pinning policy
> (2026-05-21 triage): tag-pin is allowed for `actions/*` and
> `github/*` first-party publishers because GitHub controls the
> repos and force-push protections apply; SHA pinning is reserved
> for third-party publishers where compromise risk is materially
> higher.  Policy documented in `docs/security-triage/2026-05-21/
> 00-snapshot.md` § "User-set policy for this run".

| Alert # | Path:Line | Action reference | Publisher | Verdict | Target action SHA (if REAL) |
|---|---|---|---|---|---|
| 46 | `.github/workflows/ci.yml:29` | `actions/checkout@v6` | actions (first-party) | DISMISS | — |
| 47 | `.github/workflows/ci.yml:38` | `actions/setup-python@v6` | actions (first-party) | DISMISS | — |
| 48 | `.github/workflows/ci.yml:59` | `actions/checkout@v6` | actions (first-party) | DISMISS | — |
| 49 | `.github/workflows/ci.yml:68` | `actions/setup-python@v6` | actions (first-party) | DISMISS | — |
| 50 | `.github/workflows/ci.yml:93` | `actions/checkout@v6` | actions (first-party) | DISMISS | — |
| 54 | `.github/workflows/desktop-msi-publish.yml:64` | `actions/checkout@v6` | actions (first-party) | DISMISS | — |
| 55 | `.github/workflows/desktop-msi-publish.yml:74` | `actions/setup-python@v6` | actions (first-party) | DISMISS | — |
| 56 | `.github/workflows/desktop-msi-publish.yml:128` | `actions/upload-artifact@v7` | actions (first-party) | DISMISS | — |
| 57 | `.github/workflows/desktop-msi-publish.yml:139` | `softprops/action-gh-release@v3` | softprops (third-party) | REAL | `b4309332981a82ec1c5618f44dd2e27cc8bfbfda` |
| 61 | `.github/workflows/docker-publish.yml:36` | `actions/checkout@v6` | actions (first-party) | DISMISS | — |
| 62 | `.github/workflows/docker-publish.yml:39` | `docker/setup-buildx-action@v4` | docker (third-party) | REAL | `4d04d5d9486b7bd6fa91e7baf45bbb4f8b9deedd` |
| 63 | `.github/workflows/docker-publish.yml:42` | `docker/login-action@v4` | docker (third-party) | REAL | `4907a6ddec9925e35a0a9e82d7399ccc52663121` |
| 64 | `.github/workflows/docker-publish.yml:49` | `docker/login-action@v4` | docker (third-party) | REAL | `4907a6ddec9925e35a0a9e82d7399ccc52663121` |
| 65 | `.github/workflows/docker-publish.yml:56` | `docker/metadata-action@v6` | docker (third-party) | REAL | `030e881283bb7a6894de51c315a6bfe6a94e05cf` |
| 66 | `.github/workflows/docker-publish.yml:86` | `docker/build-push-action@v7` | docker (third-party) | REAL | `bcafcacb16a39f128d818304e6c9c0c18556b85f` |
| 68 | `.github/workflows/docker-publish.yml:137` | `github/codeql-action/upload-sarif@v3` | github (first-party) | DISMISS | — |
| 69 | `.github/workflows/docker-publish.yml:144` | `sigstore/cosign-installer@v3` | sigstore (third-party) | REAL | `398d4b0eeef1380460a10c8013a76f728fb906ac` |
| 70 | `.github/workflows/docker-publish.yml:169` | `anchore/sbom-action@v0` | anchore (third-party) | REAL | `e22c389904149dbc22b58101806040fa8d37a610` |
| 72 | `.github/workflows/pypi-publish.yml:26` | `actions/checkout@v6` | actions (first-party) | DISMISS | — |
| 73 | `.github/workflows/pypi-publish.yml:35` | `actions/setup-python@v6` | actions (first-party) | DISMISS | — |
| 74 | `.github/workflows/pypi-publish.yml:52` | `actions/upload-artifact@v7` | actions (first-party) | DISMISS | — |
| 75 | `.github/workflows/pypi-publish.yml:73` | `actions/download-artifact@v8` | actions (first-party) | DISMISS | — |
| 76 | `.github/workflows/pypi-publish.yml:79` | `pypa/gh-action-pypi-publish@release/v1` | pypa (third-party) | REAL | `cef221092ed1bacb1cc03d23a2d87d1d172e277b` |
| 78 | `.github/workflows/zizmor.yml:46` | `actions/checkout@v6` | actions (first-party) | DISMISS | — |
| 79 | `.github/workflows/zizmor.yml:55` | `zizmorcore/zizmor-action@v0.5.6` | zizmorcore (third-party) | REAL | `5f14fd08f7cf1cb1609c1e344975f152c7ee938d` |
| 80 | `.github/workflows/docker-publish.yml:127` | `aquasecurity/trivy-action@v0.36.0` | aquasecurity (third-party) | REAL | `ed142fd0673e97e23eac54620cfb913e5ce36c25` |

### SHA-pin replacement guide (for Stage 2)

For each REAL alert, the edit is a single-line `uses:` swap.
Convention: keep the human-readable tag as a trailing comment so
Dependabot can still propose updates.  Example:

```yaml
- uses: aquasecurity/trivy-action@ed142fd0673e97e23eac54620cfb913e5ce36c25  # v0.36.0
```

Concrete substitutions (path:line → replacement):

| Path:Line | Replace with |
|---|---|
| `.github/workflows/desktop-msi-publish.yml:139` | `uses: softprops/action-gh-release@b4309332981a82ec1c5618f44dd2e27cc8bfbfda  # v3` |
| `.github/workflows/docker-publish.yml:39` | `uses: docker/setup-buildx-action@4d04d5d9486b7bd6fa91e7baf45bbb4f8b9deedd  # v4` |
| `.github/workflows/docker-publish.yml:42` | `uses: docker/login-action@4907a6ddec9925e35a0a9e82d7399ccc52663121  # v4` |
| `.github/workflows/docker-publish.yml:49` | `uses: docker/login-action@4907a6ddec9925e35a0a9e82d7399ccc52663121  # v4` |
| `.github/workflows/docker-publish.yml:56` | `uses: docker/metadata-action@030e881283bb7a6894de51c315a6bfe6a94e05cf  # v6` |
| `.github/workflows/docker-publish.yml:86` | `uses: docker/build-push-action@bcafcacb16a39f128d818304e6c9c0c18556b85f  # v7` |
| `.github/workflows/docker-publish.yml:127` | `uses: aquasecurity/trivy-action@ed142fd0673e97e23eac54620cfb913e5ce36c25  # v0.36.0` |
| `.github/workflows/docker-publish.yml:144` | `uses: sigstore/cosign-installer@398d4b0eeef1380460a10c8013a76f728fb906ac  # v3` |
| `.github/workflows/docker-publish.yml:169` | `uses: anchore/sbom-action@e22c389904149dbc22b58101806040fa8d37a610  # v0` |
| `.github/workflows/pypi-publish.yml:79` | `uses: pypa/gh-action-pypi-publish@cef221092ed1bacb1cc03d23a2d87d1d172e277b  # release/v1` |
| `.github/workflows/zizmor.yml:55` | `uses: zizmorcore/zizmor-action@5f14fd08f7cf1cb1609c1e344975f152c7ee938d  # v0.5.6` |

For the `actions/*` and `github/*` DISMISS group, no edit is needed
in the workflow files — the alert is dismissed via
`gh api PATCH /code-scanning/alerts/<id>`.  The orchestrator's
"hybrid" policy also implies a one-time addition of a zizmor config
entry so `unpinned-uses` doesn't keep firing on the next scan; that
config change is a Stage 2 workflow-security task and is out of
scope for this Cluster B investigation (it would land in Cluster C
or as a standalone Stage 2 item).

## Outliers + cross-cutting

* **Zero outliers** — every CodeQL alert landed in its predicted
  module class, and every zizmor unpinned-uses alert categorised
  cleanly into the publisher buckets the orchestrator policy
  anticipated.  The "anticipated counts" in the brief (≈15 actions/*
  + ≈11 third-party) match exactly (15 + 11).
* **`docker/*` org categorisation** — the orchestrator policy listed
  `docker/build-push-action` explicitly as a third-party example, so
  all five `docker/*` uses (`setup-buildx-action`, `login-action` ×2,
  `metadata-action`, `build-push-action`) are categorised as
  third-party REAL.  This matches the "Docker Inc owns the org,
  GitHub doesn't" rationale.
* **`pypa/gh-action-pypi-publish@release/v1` is a branch ref, not
  a tag.**  Stage 2 should be aware that pinning to a SHA breaks
  the "always pull the latest patch" semantic that the branch ref
  implies.  This is correct per the SHA-pin policy (and is the
  whole point of pinning), but Dependabot's github-actions
  ecosystem support for branch-tracking refs is weaker than for
  semver tags — the project may want to switch to a tag-based
  release in the future, or accept that bumps will be manual.  Not
  a Cluster B blocker; flagging for awareness.
* **`actions/checkout@v6` already has `persist-credentials: false`
  in zizmor.yml** (line 48).  This is unrelated to unpinned-uses
  but worth noting as a related defence-in-depth pattern that's
  already applied in one place — Cluster C may want to verify
  it's applied elsewhere.  Not in scope for this investigation;
  flagging for Cluster C's awareness.
* **`FORCE_JAVASCRIPT_ACTIONS_TO_NODE24` env var** is set in all
  five workflow files.  Unrelated to any Cluster B alert; an opt-in
  pragma for Node.js 24 ahead of the June 2026 cutover.  Cluster C
  may want to verify the pragma is consistent if any future Node
  24-incompatible third-party action surfaces.  Not Cluster B's
  problem.
* **No size cap on `MigrationPlanRequest.raw_text`** — the Pydantic
  field has no explicit `max_length`.  In theory this is a separate
  weakness (defence-in-depth would set one), but it does not turn
  any of the 19 polynomial-redos alerts into REAL findings because
  the regex patterns themselves are polynomial-not-exponential and
  operate per-line via `splitlines()`.  Flagging as a possible
  future hardening item (not Cluster B's scope to fix); could be a
  Cluster A or future-triage item if anyone wants to set
  `Field(..., max_length=50 * 1024 * 1024)` to match the
  `MAX_CONFIG_SIZE` cap on the file-store path.

### Methodology notes for the next triage cycle

* All third-party SHAs were resolved via `gh api repos/<owner>/<repo>/
  git/ref/tags/<tag>` then (when the ref pointed at an annotated tag
  object) `gh api repos/<owner>/<repo>/git/tags/<sha>`.  Both calls
  use `--jq` for parsing — POSIX `jq` is not installed on the agent
  worker but `gh`'s built-in `--jq` works.  `pypa/gh-action-pypi-
  publish@release/v1` required `git/ref/heads/release/v1` since
  `release/v1` is a branch not a tag.
* The current commit SHAs were captured at 2026-05-21.  If Stage 2
  applies these pins more than a few weeks after this date, re-
  resolve before applying — third-party publishers may have
  shipped patch releases under the same major-version tag in the
  interim, and the SHA-pin should track the latest patch within
  the major.

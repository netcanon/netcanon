# Bug Reporting + Fixture Submission

The single highest-impact contribution to Netcanon is a **real-world
config that exercises a translation we don't currently test.**
This page walks the workflow.

There are two related-but-distinct submission types:

1. **Bug report** — "I translated my config and got the wrong
   output."  Use the `bug_report.yml` issue template.
2. **Fixture submission** — "I have a real-world config that surfaces
   coverage we don't have.  Please add it to the test matrix."  Use
   the `fixture_submission.yml` issue template.

Both share the same sanitization step.  Both are deeply welcome.

---

## Sanitize first, always

Network configs contain credentials, encryption keys, real WAN IPs,
real internal hostnames, and personally-identifying information.
**Never paste raw configs into a public issue.**  Netcanon ships a
sanitiser specifically for this workflow.

### Option A: CLI (no server required)

```bash
pip install netcanon
netcanon sanitize -i my-config.txt -o sanitised.txt \
    --source-vendor cisco_iosxe_cli --dry-run
```

The `--dry-run` flag prints the substitution table without writing
output — review every replacement before committing:

```
=== Substitution audit (47 entries) ===
  [hostname] hostname
    'production-edge-01'
    -> 'device-1'
  [interface-description] interfaces[0].description
    'Uplink to ISP-PRD'
    -> 'description redacted'
  [snmp-community] snmp.community
    'SuperSecret'
    -> 'public_redacted_1'
  [ipv4-public] interfaces[2].ipv4_addresses[0].ip
    '198.51.100.42'
    -> '192.0.2.1'
  ... (full table) ...

47 substitutions identified.
Run again without --dry-run to write the sanitized output.
```

When you're satisfied:

```bash
netcanon sanitize -i my-config.txt -o sanitised.txt \
    --source-vendor cisco_iosxe_cli
```

The output is in the same vendor's format as the input — operators
who understand the source format can read the sanitised output.

### Option B: HTTP API (Docker / running-server users)

If you're running Netcanon as a server (Docker, embedded desktop,
deployed instance), `curl` against the API:

```bash
# Dry-run to preview redactions:
curl -X POST http://localhost:8000/api/v1/sanitize \
    -F "source_vendor=cisco_iosxe_cli" \
    -F "config=@my-config.txt" \
    -F "dry_run=true" | jq .

# Apply for real:
curl -X POST http://localhost:8000/api/v1/sanitize \
    -F "source_vendor=cisco_iosxe_cli" \
    -F "config=@my-config.txt" \
    -o sanitised.txt
```

Both paths call the same shared library
([`netcanon.tools.sanitize`](../netcanon/tools/sanitize.py)) — output
is identical between CLI and HTTP invocation.

### What gets sanitised

The sanitiser walks the canonical-intermediate model and applies
field-typed redactions.  Counter-per-session stable: same input
value always maps to the same redaction across the whole config
(so cross-references survive — a hostname referenced 5 times gets
the same redacted value all 5 times).

| Field | Replacement |
|---|---|
| Hostname | `device-N` |
| Domain | `example-N.test` |
| Public IPv4 | RFC 5737 docs ranges (`192.0.2.x` / `198.51.100.x` / `203.0.113.x`) |
| Private IPs (RFC 1918, ULA, link-local, loopback, multicast, CGNAT) | Preserved |
| Hashed passwords | Format-preserving fakes (Junos `$9$`, FortiGate `ENC`, crypt `$5$`/`$6$`, bcrypt `$2y$`, Cisco type-7 hex, Aruba SHA-1) |
| SNMP communities | `public_redacted_N` |
| SNMPv3 auth/priv passphrases | `REDACTED-AUTH-N` / `REDACTED-PRIV-N` |
| RADIUS shared secrets | `REDACTED-RADIUS-N` |
| Interface descriptions | `description redacted` |
| Tier-3 sections (firewall, NAT, VPN) | Stripped entirely |

Full rules and limitations in the sanitiser's module docstring at
[`netcanon/tools/sanitize.py`](../netcanon/tools/sanitize.py).

### Limitations of the sanitiser

- **Round-trip is sub-lossless.**  Parse drops Tier-3 content, render
  emits only what the codec models.  Sanitised output is the
  supported-subset reshape, not byte-identical with the original.
  This is acceptable for bug reports — operators usually don't want
  to share Tier-3 content (firewall, NAT, VPN) anyway.
- **Banner / comment text not redacted.**  These aren't in the
  canonical model.  Most are parse-and-ignored.  If your config has
  sensitive banner text, hand-edit it after sanitising.
- **IPv6-public redaction is IPv4-only at v0.1.0.**  IPv6 addresses
  pass through verbatim.  If your config has public IPv6 addresses,
  hand-redact those before submitting.

---

## Filing a bug report

Use the `bug_report.yml` issue template (GitHub auto-loads it).
Required fields:

| Field | Example |
|---|---|
| Source vendor + OS version | `Cisco IOS-XE 17.6.4` |
| Target vendor + OS version | `Aruba AOS-CX 10.13` |
| Sanitised input snippet | The smallest reproducer (post-sanitiser) |
| Expected output | What you expected the translation to produce |
| Actual output | What Netcanon produced (sanitised) |
| Netcanon version / commit SHA | `v0.1.0` or `abc123` |

Plus the confirmation checkboxes:
- [ ] I have replaced all real credentials, IPs, and hostnames in
      the snippets above with synthetic equivalents.
- [ ] I have searched existing issues for this bug.

The issue template enforces sanitisation by including the checkbox
as required.  If you didn't sanitise, please **don't submit yet** —
sanitise first.

---

## Filing a fixture submission

Use the `fixture_submission.yml` issue template.  This is for "here's
a real-world config that exercises grammar / a vendor-pair we don't
yet test."  These are the highest-impact contributions to the
project.

| Field | What to provide |
|---|---|
| Vendor + OS version | `Cisco IOS-XE 17.6.4` |
| Sanitised capture | Paste inline if < 1000 lines, else gist + link |
| What does this fixture cover? | "VRF on FortiGate", "EVPN type-5 on Arista with route-target manual mode", etc. |
| Translation expectation (optional) | If you have an expected target-vendor output |
| Provenance | Where did this capture come from?  E.g. "production switch in my own network, sanitised", "public-research repo X under MIT license", "vendor doc example" |

Plus confirmation:
- [ ] All real credentials, IPs, hostnames, and identifying
      information have been replaced with synthetic equivalents.
- [ ] I have the right to share this capture under the project's
      license.

---

## What we'll do with your submission

### For bug reports

1. **Triage within 48 hours.**  Maintainer reads the report,
   classifies it (CODEC_BUG vs expected-Tier-3 vs lossy-within-
   bounds vs methodology-issue).
2. **Reproduction within 7 days.**  We add a unit test that
   captures the bug shape against your sanitised snippet.
3. **Fix wave.**  Codec change + matrix regen + fixture import +
   regression-guard test.
4. **Disclosure.**  Issue closes with a CHANGELOG entry crediting
   the report.

If we conclude it's expected behaviour (Tier-3 / lossy / by-design),
we'll explain why and link the relevant capability matrix
declaration.  An honest "this is by design and here's the cited
reason" is the right outcome — not every issue is a bug.

### For fixture submissions

1. **Review provenance.**  We confirm the capture is shareable
   under a permissive licence.
2. **Drop into `tests/fixtures/real/<vendor>/`.**  Add to
   `NOTICE.md` with provenance; add to `RESULTS.md` with what
   it covers.
3. **Run the matrix.**  Surface any new variance cells.  If
   anything classifies as `CODEC_BUG`, that's the highest-value
   outcome — it found something the synthetic suite missed.
4. **Wire into the per-vendor unit test.**  Pinned regression
   guard so future codec changes don't drift.
5. **Disclosure.**  CHANGELOG entry crediting the contribution.

---

## What we WON'T accept

- **Configs with real credentials / IPs / hostnames.**  Sanitise
  first.  We can't accept binary device-config submissions in
  public issues.
- **Closed-source vendor configs you don't have rights to share.**
  Provenance must be permissive (operator's own network with
  appropriate authorisation; public-research repos under MIT /
  Apache / BSD; vendor docs).
- **Feature requests for Tier-3 surfaces** (firewall translation,
  NAT translation, VPN translation, QoS).  These are deliberate
  deferrals; see [`docs/CAPABILITIES.md`](docs/CAPABILITIES.md).
  We may build a sister product for these surfaces; we won't add
  them to this one.

---

## Security vulnerabilities

**Don't open public issues for security vulnerabilities.**  Use
GitHub's private vulnerability reporting flow:
[https://github.com/netcanon/netcanon/security/advisories/new](https://github.com/netcanon/netcanon/security/advisories/new).

See [`SECURITY.md`](SECURITY.md) for the full policy.

---

## See also

- [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) — diagnostic
  flowchart before filing
- [`docs/HOW_WE_TEST.md`](docs/HOW_WE_TEST.md) — what the audit
  matrix means
- [`docs/CAPABILITIES.md`](docs/CAPABILITIES.md) — what's
  supported / lossy / out of scope
- [`docs/vendors/`](docs/vendors/) — per-vendor pages with what
  works for your vendor
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — broader contribution
  guide (codec authors, canonical-field additions)
- [`SECURITY.md`](SECURITY.md) — security disclosure flow

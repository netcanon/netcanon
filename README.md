# Netcanon

**Multi-vendor network config translator with a verifiable cross-vendor audit.**

Translates running-config between Cisco IOS-XE, Juniper Junos, Aruba
AOS-S, Arista EOS, Fortinet FortiGate, MikroTik RouterOS, and OPNsense.
You point Netcanon at a config from one vendor and it renders the
equivalent config for another — through a shared canonical model, with
every translatable field declared as supported, lossy, or unsupported.

What sets it apart is the audit underneath.  Every supported vendor
pair × every field gets classified into one of eight variance classes
(`ALIGNED` / `CODEC_BUG` / `EXPECTED_LOSSY` / `EXPECTED_UNSUPPORTED` /
`METHODOLOGY_ISSUE_under` / `METHODOLOGY_ISSUE_over` / `STRUCTURAL_ONLY`
/ `TRIVIAL_EMPTY`).  The cross-mesh audit catches silent translation
errors — the kind that produce output that *looks* valid but quietly
drops or transforms a field — before they ship.

---

## See it in 10 seconds

```bash
docker run --rm ghcr.io/netcanon/netcanon:latest python tools/demo.py --pair cisco__junos
```

Paste this:

```
hostname leaf-01
!
vlan 10
 name DATA
!
interface GigabitEthernet0/0/0
 description Uplink to spine
 switchport access vlan 10
!
ip route 0.0.0.0 0.0.0.0 192.168.1.1
```

Get this:

```
set system host-name leaf-01
set interfaces GigabitEthernet0/0/0 description "Uplink to spine"
set vlans DATA vlan-id 10
set routing-options static route 0.0.0.0/0 next-hop 192.168.1.1
```

Same canonical pipeline drives the HTTP API and the browser UI.  Run
`python tools/demo.py --list` to see all four embedded scenarios
(Cisco→Junos, FortiGate→MikroTik, Aruba→Arista, OPNsense→Junos).

---

## The trust signal — and the invitation

Across every supported vendor pair × every field declared as
`supported`, the cross-mesh audit holds **zero `CODEC_BUG` cells**.
That's not "we think it works"; that's every cell that should
translate, does, by automated test against vendor-doc-grounded
expectations.

The honest follow-up: **the audit only covers cells we have fixtures
for.**  Real-world configs exercise paths the synthetic fixtures
haven't reached — and that's where you come in.  If you have a
running-config that translates wrong (or doesn't translate at all),
that's the highest-impact bug report this project can receive.  See
[`BUG_REPORTING.md`](BUG_REPORTING.md) for the workflow — Netcanon
ships its own sanitiser (the `/sanitize` browser page, the
`netcanon sanitize` CLI, and the `POST /api/v1/sanitize` HTTP
endpoint all share one library) so you never paste real WAN IPs,
hashes, hostnames, or usernames into a public issue.

For the full audit narrative + the variance-class taxonomy, see
[`docs/HOW_WE_TEST.md`](docs/HOW_WE_TEST.md).

---

## Install

### Docker (recommended)

```bash
# Generate a Fernet key once and keep it somewhere safe — this is the
# encryption key for device credentials at rest.  Loss = re-entering
# every saved device password; leak = decryptable backup state.
NETCANON_FERNET_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

docker run --rm -p 8000:8000 \
    -v $(pwd)/configs:/app/configs \
    -v $(pwd)/data:/app/data \
    -e NETCANON_FERNET_KEY="$NETCANON_FERNET_KEY" \
    ghcr.io/netcanon/netcanon:latest
# -> http://127.0.0.1:8000        (UI)
# -> http://127.0.0.1:8000/docs   (Swagger)
# -> http://127.0.0.1:8000/health (health probe)
```

`configs/` is where backed-up running-configs land; `data/` holds
device profiles, schedules, and job state.  Don't bind-mount
`definitions/` — those YAMLs are baked into the image as tracked
content; mounting an empty host directory over them will crash
startup.

`NETCANON_FERNET_KEY` injects the credential-encryption key directly
(recommended for production / orchestrated deployments — the key
never touches disk).  If you skip the `-e` flag, Netcanon auto-
generates a key on first run inside `data/.fernet_key` so the
container works zero-config; for the production deployment path see
[`SECURITY.md`](SECURITY.md) "Credential Storage".

The published image is signed via Sigstore (`cosign verify
ghcr.io/netcanon/netcanon ...`) with an SBOM attestation.

**Docker Hub mirror** — same image, convenience-mirrored to Docker
Hub if your tooling defaults to `docker.io`:

```bash
docker run --rm -p 8000:8000 netcanon/netcanon:latest
```

The Docker Hub mirror has the same image bytes but no cosign
signature or SBOM attestation — operators in regulated environments
should pull from GHCR for the attested provenance chain.  See
[`SECURITY.md`](SECURITY.md) for the supply-chain story.

### Pip

```bash
pip install netcanon
uvicorn netcanon.main:app --host 127.0.0.1 --port 8000
```

`netcanon` also installs the `netcanon` CLI — `netcanon sanitize -i
my-config.txt --source-vendor cisco_iosxe_cli --dry-run` is the
typical CLI entrypoint for the bug-reporting workflow.  If the
server's running, the **`/sanitize` browser page** is the easier
path (paste or pick a stored config, click Sanitize, copy the
output — see [`BUG_REPORTING.md`](BUG_REPORTING.md) for the full
workflow including what gets redacted).

### Desktop (Windows)

Download the MSI from
[Releases](https://github.com/netcanon/netcanon/releases), or from
source:

```bash
pip install -e ".[desktop]"
python -m netcanon_desktop
```

The desktop shell runs the same FastAPI app inside a PySide6 webview
with a tray icon — same UI, no command-line.

---

## Walkthroughs — "is this the right tool for my migration?"

Each walkthrough is paired 1:1 with a runnable demo scenario.  Read
the narrative first, run `python tools/demo.py --pair <key>` to see
the actual translation.

| Walkthrough | Demo scenario | Frame |
|---|---|---|
| [Cisco IOS-XE → Juniper Junos](docs/walkthroughs/cisco_iosxe_to_junos.md) | `cisco__junos` | DC leaf migration: VLANs + interfaces + routes |
| [FortiGate → MikroTik RouterOS](docs/walkthroughs/fortigate_to_mikrotik.md) | `fortigate__mikrotik` | Branch-firewall consolidation: DNS + interfaces + DHCP pools |
| [Aruba AOS-S → Arista EOS](docs/walkthroughs/aruba_to_arista.md) | `aruba__arista` | Switch refresh: VLAN-centric → port-centric grammar |
| [OPNsense → Juniper Junos](docs/walkthroughs/opnsense_to_junos.md) | `opnsense__junos` | Edge-firewall migration with explicit Tier-3 boundary |

Each walkthrough ends in a manual-review checklist — what to verify
on the device after the rendered config lands, before you apply it.

---

## What translates, and what doesn't

The canonical model classifies every field by semantic stability
across vendors.  Full per-codec matrix is in
[`docs/CAPABILITIES.md`](docs/CAPABILITIES.md); the short version:

* **Tier 1 — auto-translatable.**  hostname, interfaces (name /
  description / enabled state / IPv4 + IPv6 addresses / per-interface
  VRF binding), VLANs, static routes, DNS / NTP / syslog servers,
  timezone.  Every shipped codec parses + renders these fully.
* **Tier 2 — translatable with caveats.**  SNMP (incl. SNMPv3 USM),
  LAGs, local users, RADIUS, DHCP server pools, VXLAN VNIs, EVPN
  type-5 routes, routing instances / VRFs, Junos `apply-groups`.
  Hashes that the target's CLI cannot consume surface as commented
  review lines, never as plaintext fallback.
* **Tier 3 — opaque carry / never auto-rendered.**  Firewall rules,
  NAT, IPsec / OpenVPN / WireGuard, QoS, route-maps, dynamic routing
  protocol stanzas, PKI.  These are vendor-specific stateful policy
  that doesn't translate cross-vendor cleanly — Netcanon **detects**
  them, surfaces them via the migrate-page banner with a count and
  section names, and deliberately doesn't auto-render.  Hand-build
  them natively on the target.

If your migration's primary need is firewall translation,
[`docs/COMPARISON.md`](docs/COMPARISON.md) names adjacent tools
(Capirca / Aerleon) that handle that scope.  Netcanon is the right
tool for the *router* portion of a migration — and explicitly the
wrong tool to claim it does the firewall portion.

---

## Two concerns, one app

Netcanon co-hosts:

1. **Backup** — pulls `running-config` (or vendor equivalent) from
   network devices over SSH / NETCONF / REST and stores it verbatim
   in `configs/<hostname>.<ext>`.  Runs on a schedule or on demand.
2. **Migration** — translates a stored backup from one vendor's
   config grammar to another through the canonical intent tree.

Same FastAPI process; same UI; same Docker image.  Use whichever
half (or both).  See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the
four-layer design.

---

## Found a bug?  Got a config that breaks it?

That's the contribution this project values most.  Workflow:

1. Sanitise your config — open the `/sanitize` browser page (easiest
   if the server's running), or run the `netcanon sanitize` CLI
   (no server required).  Both strip hostnames, usernames, IPs,
   hashes, certs, SNMP communities, etc., with a counter-per-session
   stable substitution table you can audit before submission.
2. Open a [bug report](https://github.com/netcanon/netcanon/issues/new?template=bug_report.yml)
   or [fixture submission](https://github.com/netcanon/netcanon/issues/new?template=fixture_submission.yml).
3. The fixture lands in `tests/fixtures/real/<vendor>/`, the
   cross-mesh audit re-runs, and the variance class your fixture
   surfaces gets a row in `tests/fixtures/real/PHASE4_RECONCILIATION.md`.

Full workflow is in [`BUG_REPORTING.md`](BUG_REPORTING.md).

---

## For contributors

| You want to… | Start here |
|---|---|
| Understand the architecture | [`ARCHITECTURE.md`](ARCHITECTURE.md) — four-layer model, canonical bridge, codec types |
| Follow the contributor rules | [`AGENTS.md`](AGENTS.md) — hard rules, parity checklist, gotchas |
| Read the slower-changing methodology | [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) — matrix-honesty discipline distilled, portable to other projects |
| Look up project jargon | [`docs/glossary.md`](docs/glossary.md) — canonical, codec, mesh, ship-before-wire, target profile |
| Read the canonical model overview | [`netcanon/migration/canonical/README.md`](netcanon/migration/canonical/README.md) |
| Add or change an HTTP route | [`netcanon/api/routes/README.md`](netcanon/api/routes/README.md) — frozen pipeline-stage signatures, endpoint inventory |
| Add a new codec | [`netcanon/migration/codecs/README.md`](netcanon/migration/codecs/README.md) |
| Add a new device definition / target profile | [`definitions/README.md`](definitions/README.md) |
| Add a new canonical field | [`docs/adding-a-canonical-field.md`](docs/adding-a-canonical-field.md) |
| Ship a feature across web + desktop | [`docs/feature-parity-walkthrough.md`](docs/feature-parity-walkthrough.md) |
| See what's shipped recently | [`CHANGELOG.md`](CHANGELOG.md) |
| Check codec certification tiers | [`tests/fixtures/real/RESULTS.md`](tests/fixtures/real/RESULTS.md) |
| Write tests | [`tests/README.md`](tests/README.md) |
| Review the security model | [`SECURITY.md`](SECURITY.md) |

### Run the test suite

```bash
pip install -e ".[dev]"
pytest                       # unit + integration + desktop (fast)
pytest -m e2e                # Playwright browser tests (slower)
```

Tests run across four layers: unit (pure functions, no I/O — the
real-capture validation harness lives here as a unit subset),
integration (TestClient + mocked SSH at the `get_collector`
factory), e2e (Playwright against a live Uvicorn), and desktop
(PySide6 + pystray mocked).  CI runs the full matrix on Python
3.11 / 3.12 / 3.13 / 3.14 against Ubuntu.  CI output is the source of
truth for pass counts.

### Layout

```
netcanon/              FastAPI application (shared by both platforms)
 ├── api/routes/          HTTP endpoints
 ├── collectors/          SSH/NETCONF/REST fetchers — one factory,
 │                        one mock-point (`get_collector`)
 ├── migration/           Cross-vendor translation pipeline
 │   ├── canonical/         CanonicalIntent model + shared transforms
 │   └── codecs/            Per-vendor parse/render implementations
 ├── services/            Plain-function orchestrators (pipeline, detect, …)
 ├── storage/             FileConfigStore
 ├── tools/               sanitize, etc.
 └── templates/           Jinja2 templates (every interactive element
                          carries a data-testid — see AGENTS.md)

netcanon_desktop/      Windows tray/webview shell around the same server
definitions/            Device definition YAMLs
tools/demo.py           One-command cross-vendor translation demo
docs/walkthroughs/      Narrative migration walkthroughs (paired with demo)
docs/vendors/           Per-vendor "what works for me?" pages
tests/unit/             Pure-function tests, no I/O
tests/integration/      FastAPI TestClient tests, SSH mocked
tests/e2e/              Playwright browser tests
tests/desktop/          PySide6/pystray-mocked desktop shell tests
tests/fixtures/real/    Real-capture validation corpus (see RESULTS.md)
```

---

## License

MIT.  See [`LICENSE`](LICENSE).  Third-party fixtures keep their
upstream licences — see [`tests/fixtures/real/NOTICE.md`](tests/fixtures/real/NOTICE.md)
for provenance.

For responsible disclosure of security issues, see
[`SECURITY.md`](SECURITY.md).

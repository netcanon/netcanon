# Netcanon

[![CI](https://github.com/netcanon/netcanon/actions/workflows/ci.yml/badge.svg)](https://github.com/netcanon/netcanon/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/netcanon)](https://pypi.org/project/netcanon/)
[![Python versions](https://img.shields.io/pypi/pyversions/netcanon)](https://pypi.org/project/netcanon/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Container: GHCR](https://img.shields.io/badge/ghcr.io-netcanon%2Fnetcanon-2496ED?logo=docker&logoColor=white)](https://github.com/netcanon/netcanon/pkgs/container/netcanon)
[![Live demo](https://img.shields.io/badge/live_demo-demo.netcanon.net-2ea44f)](https://demo.netcanon.net)

**Multi-vendor network config translator with a verifiable cross-vendor audit.**

Translates running-config across twelve codecs spanning Cisco (IOS-XE,
NX-OS, IOS-XR), Juniper Junos, Arista EOS, Aruba (AOS-S, AOS-CX),
Fortinet FortiGate, MikroTik RouterOS, OPNsense, and VyOS — see
[`docs/CAPABILITIES.md`](docs/CAPABILITIES.md) for the full per-codec list.
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

<p align="center">
  <img src="docs/assets/migrate.png" width="860" alt="Netcanon migrate page: a Cisco IOS-XE config translated to Junos, showing auto-detection, a green “Validation OK” banner, an amber “Tier-3 sections detected” banner listing the ACL and NAT lines that don’t translate, and the rendered Junos `set` output.">
</p>

<p align="center"><sub>The browser UI translating Cisco IOS-XE → Junos — interface names and L2 membership mapped across vendors, every field declared supported/lossy/unsupported, and Tier-3 sections (ACLs, NAT, …) surfaced rather than silently dropped.</sub></p>

---

## Try it in your browser — nothing to install

### **[demo.netcanon.net](https://demo.netcanon.net)**

Paste a config, pick a target vendor, read the translation. It is the real
application, not a video or a sandbox with the interesting parts removed.

Because you are being asked to paste a network config into someone else's
website, here is exactly what happens to it:

- Every visitor gets their **own throwaway container**, destroyed when you close
  the tab or after 15 minutes, whichever comes first.
- Instances run with a **read-only root filesystem, tmpfs-only writes, and no
  network egress at all** — the container that holds your config cannot reach
  the internet.
- **No access log, no analytics, no tracking cookies** (one session-routing
  cookie, nothing else). The host has swap disabled and discards core dumps, so
  your config cannot reach disk even indirectly.

None of that is a promise you have to take on trust. The
[demo whitepaper](docs/DEMO_WHITEPAPER.md) states each claim, and
[`deploy/VERIFY.md`](deploy/VERIFY.md) gives you the commands to check them
yourself — including a canary sweep of the entire host filesystem. The stack is
built from this repo, pinned by digest, and cosign-signed, so you can rebuild
the identical thing locally and audit it.

> **Handling something sensitive?** Don't paste it. Run the container yourself —
> it is one command, below, and it is the same image the demo runs.

## See it in 10 seconds — locally

```bash
docker run --rm --entrypoint netcanon ghcr.io/netcanon/netcanon:latest demo --pair cisco__junos
```

(Installed via pip instead? Just `netcanon demo --pair cisco__junos`.
The published image is amd64/x86-64 only today.)

The `demo` command above translates a built-in sample. To translate your
own, start the server (see [Install](#install)) and paste a config like
this into the browser migrate page:

```
hostname access-sw-01
!
vlan 10
 name DATA
!
interface GigabitEthernet1/0/1
 description Server-A
 switchport mode access
 switchport access vlan 10
!
snmp-server community public RO
!
ip route 0.0.0.0 0.0.0.0 192.168.1.1
```

Get this:

```
set system host-name access-sw-01
set interfaces ge-1/0/1 description "Server-A"
set interfaces ge-1/0/1 unit 0 family ethernet-switching interface-mode access
set interfaces ge-1/0/1 unit 0 family ethernet-switching vlan members DATA
set vlans DATA vlan-id 10
set routing-options static route 0.0.0.0/0 next-hop 192.168.1.1
set snmp community public authorization read-only
```

Notice ``GigabitEthernet1/0/1`` became ``ge-1/0/1`` and the access-VLAN
membership rendered into Junos `ethernet-switching` form — Netcanon
translates interface names and L2 membership across vendor conventions,
not just the surrounding scalar config.

Same canonical pipeline drives the HTTP API and the browser UI.  Run
`netcanon demo --list` (or `python tools/demo.py --list` from a source
checkout) to see all four embedded scenarios (Cisco→Junos,
FortiGate→MikroTik, Aruba→Arista, OPNsense→Junos).

---

## The trust signal — and the invitation

Across every vendor pair we ship a fixture **and** a cross-vendor
expectation for — 8 of the 12 codecs today; `aruba_aoscx`, `cisco_iosxr`,
`cisco_nxos`, and `vyos` have fixtures but not yet cross-vendor
expectations — the cross-mesh audit tracks `CODEC_BUG` drift cell by
cell.  The live reconciliation (`tests/fixtures/real/PHASE4_RECONCILIATION.md`
for the roll-up, `tests/fixtures/real/phase4_findings_residuals.md` for
the per-cell triage) currently reports a small number of residual
high-severity cells (5 at last run) — each triaged as a benign
modelling/structural artifact (4 on real fixtures, 1 synthetic) rather
than a translation error, and every one is enumerated.  That's not "we
think it works"; that's every covered cell, checked by automated test
against vendor-doc-grounded expectations, with nothing swept under the rug.

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

## How it compares

Arriving from "I need a Batfish / NAPALM / Capirca alternative"?  Most
adjacent tools occupy a different slot — Netcanon's niche is
**bidirectional translation between vendors' native running-config
formats**, with a per-field capability matrix and a cross-mesh audit.

| Tool | What it does | Translates native config? |
|---|---|---|
| **Netcanon** | Multi-vendor config translation (parse + render) | ✅ bidirectional, 12 codecs |
| [Batfish](https://github.com/batfish/batfish) | Config analysis + routing simulation | ❌ parse-only — *complements* Netcanon |
| [Capirca](https://github.com/google/capirca) / [Aerleon](https://github.com/aerleon/aerleon) | Firewall ACL DSL → vendor syntax | ❌ render-only from a DSL — *competes* (firewall scope) |
| [NAPALM](https://github.com/napalm-automation/napalm) / [Netmiko](https://github.com/ktbyers/netmiko) | Device get/set + SSH transport | ❌ no translation — *complements* (deploy side) |
| [Oxidized](https://github.com/ytti/oxidized) / [RANCID](https://shrubbery.net/rancid/) | Multi-vendor config **backup** + diff | ❌ backup-only — overlaps Netcanon's backup half |

Netcanon **competes** with Capirca / Aerleon (but defers firewall / NAT
/ VPN / QoS to Tier-3) and **complements** Batfish (analyse what you
translated), NAPALM / Netmiko (deploy it), and NetBox / Nautobot
(desired-state vs existing-state).  Full breakdown — including the
backup + sanitiser landscape — in
[`docs/COMPARISON.md`](docs/COMPARISON.md).

---

## Install

### Docker (recommended)

> [!IMPORTANT]
> **As of 0.4.0 the container fails closed on a public bind.** The
> default entrypoint (`netcanon serve`) binds `0.0.0.0`, so it now
> **refuses to start** unless you either set an API key
> (`-e NETCANON_API_KEY=...`, which gates `/api/v1`) **or** explicitly
> opt out with `-e NETCANON_ALLOW_INSECURE_BIND=1`. This is deliberate
> — it stops an accidental `docker run -p` from exposing an
> unauthenticated API to your network. Just kicking the tyres? Add
> `-e NETCANON_ALLOW_INSECURE_BIND=1`; for anything reachable by other
> hosts, set `NETCANON_API_KEY` (the full command below does). A pure
> loopback bind (`-e NETCANON_HOST=127.0.0.1`) needs neither.

The published image is **amd64/x86-64 only** today — there is no arm64
build yet, on GHCR or the Docker Hub mirror.

```bash
# Optional but recommended for production: setting the key explicitly keeps
# it in your secret store, separate from the data volume.  Skip this line
# AND the `-e` flag below and Netcanon auto-generates + persists a key in
# data/.fernet_key on first run (zero-config).  This key encrypts device
# credentials at rest: loss = re-entering every saved device password;
# leak = decryptable stored credentials.
NETCANON_FERNET_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

# Required for a network-exposed (0.0.0.0) deployment: an API key gates
# /api/v1.  Without it (or NETCANON_ALLOW_INSECURE_BIND=1) the container
# refuses to start on a non-loopback bind (SEC-01 fail-closed).
NETCANON_API_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")

docker run --rm -p 8000:8000 \
    -v $(pwd)/configs:/app/configs \
    -v $(pwd)/data:/app/data \
    -e NETCANON_FERNET_KEY="$NETCANON_FERNET_KEY" \
    -e NETCANON_API_KEY="$NETCANON_API_KEY" \
    ghcr.io/netcanon/netcanon:latest
# -> http://127.0.0.1:8000        (UI)
# -> http://127.0.0.1:8000/docs   (Swagger)
# -> http://127.0.0.1:8000/health (health probe)
```

`configs/` is where backed-up running-configs land; `data/` holds
device profiles, schedules, and job state.  The device-definition
library ships *inside the package* (there is no `definitions/` mount
target) — set `NETCANON_DEFINITIONS_DIR` to a bind-mounted directory
only if you maintain a custom definition set.

`NETCANON_FERNET_KEY` injects the credential-encryption key directly
(recommended for production / orchestrated deployments — the key
never touches disk).  If you skip the `-e` flag, Netcanon auto-
generates a key on first run inside `data/.fernet_key` so the
container works zero-config; for the production deployment path see
[`SECURITY.md`](SECURITY.md) "Credential Storage".

`NETCANON_API_KEY` turns on a built-in bearer-token gate: when set,
every `/api/v1` request must carry `Authorization: Bearer
$NETCANON_API_KEY`.  **The key gates the `/api/v1` surface only — it does
NOT cover the HTML UI.**  Several UI pages are server-rendered and read
data server-side, *not* through `/api/v1`: the diff view
(`/configs/{a}/vs/{b}`) emits full config text (secrets included), and
`/configs` / `/devices` list the config + device inventory.  The API key
does **not** protect those pages, so for any non-loopback exposure you
**must** front the app with a reverse proxy that authenticates the whole
surface — do not rely on the key alone to secure the UI.  Because the
image binds `0.0.0.0`, `netcanon serve` refuses to start without a key
(or `NETCANON_ALLOW_INSECURE_BIND=1`), so an unauthenticated public bind
is a deliberate choice — see [`SECURITY.md`](SECURITY.md) "Threat Model".

The published image is signed via Sigstore with an SBOM attestation.
Verify against the immutable digest (`ghcr.io/netcanon/netcanon@sha256:<digest>`),
not a mutable tag — see [`SECURITY.md`](SECURITY.md) "Supply-Chain
Integrity" for the exact `cosign verify` invocation.

**Docker Hub mirror** — same image, convenience-mirrored to Docker
Hub if your tooling defaults to `docker.io`:

```bash
docker run --rm -p 8000:8000 -e NETCANON_ALLOW_INSECURE_BIND=1 netcanon/netcanon:latest
```

The Docker Hub mirror has the same image bytes but no cosign
signature or SBOM attestation — operators in regulated environments
should pull from GHCR for the attested provenance chain.  See
[`SECURITY.md`](SECURITY.md) for the supply-chain story.

### API stability (v0.x)

The `/api/v1` surface carries a stability promise: request/response
shapes don't break within v0.x; changed behaviour ships as new
endpoints alongside the old ones, and the
[CHANGELOG](CHANGELOG.md) names every break.  (Internal frozen
surfaces are documented in
[`netcanon/api/routes/README.md`](netcanon/api/routes/README.md).)

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
with a tray icon — same UI, no command-line.  See
[`netcanon_desktop/README.md`](netcanon_desktop/README.md) for the
threading model, settings, and MSI build instructions.

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
  VRF binding), VLANs, static routes.  Nearly every shipped codec
  parses + renders these — the per-codec §A tables in
  [`docs/CAPABILITIES.md`](docs/CAPABILITIES.md) are authoritative for
  the exceptions (OPNsense renders no static routes, VyOS has no
  top-level VLAN database, per-interface VRF binding is wired on 6 of
  the 12 codecs, and the experimental `cisco_iosxe` NETCONF stub
  renders interfaces only).  DNS / NTP servers translate
  on most codecs; `syslog` servers translate on `juniper_junos`,
  `cisco_iosxe_cli`, `arista_eos` (`logging host <ip>` /
  `set system syslog host <ip>`), `cisco_nxos` (`logging server <ip>`)
  and `cisco_iosxr` (bare `logging <ip>`), while `timezone` is wired on
  no codec — check the per-codec matrices in
  [`docs/CAPABILITIES.md`](docs/CAPABILITIES.md), and note that where a
  codec doesn't wire a field the source-side value is currently dropped
  without a banner.
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
   network devices over SSH (Netmiko or Paramiko) and stores it verbatim
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
   hashes, SNMP communities, etc., with a counter-per-session
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
| Add a new device definition / target profile | [`netcanon/definitions/library/README.md`](netcanon/definitions/library/README.md) |
| Add a new canonical field | [`docs/adding-a-canonical-field.md`](docs/adding-a-canonical-field.md) |
| Ship a feature across web + desktop | [`docs/feature-parity-walkthrough.md`](docs/feature-parity-walkthrough.md) |
| See what's shipped recently | [`CHANGELOG.md`](CHANGELOG.md) |
| Check codec certification tiers | [`tests/fixtures/real/RESULTS.md`](tests/fixtures/real/RESULTS.md) |
| Write tests | [`tests/README.md`](tests/README.md) |
| Review the security model | [`SECURITY.md`](SECURITY.md) |
| Community / participation norms | [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) — Contributor Covenant + enforcement contact |

### Run the test suite

```bash
pip install -e ".[dev]"
pytest                       # all tiers; desktop tier needs the [desktop] extra
pytest -m e2e                # Playwright browser tests (slower)
```

Tests run across four layers: unit (pure functions, no I/O — the
real-capture validation harness lives here as a unit subset),
integration (TestClient + mocked SSH at the `get_collector`
factory), e2e (Playwright against a live Uvicorn), and desktop
(PySide6 + pystray mocked).  CI runs **all four tiers on every PR** —
unit + integration on Python 3.11 / 3.12 / 3.13 / 3.14 against Ubuntu,
plus e2e (Playwright) and desktop (PySide6) on Python 3.13.  No pytest
invocation uses `-x`, so each tier reports its full pass/fail count
(see `SECURITY.md` for the authoritative required merge checks).

### Layout

```
netcanon/              FastAPI application (shared by both platforms)
 ├── api/routes/          HTTP endpoints
 ├── collectors/          SSH fetchers (Netmiko / Paramiko) — one factory,
 │                        one mock-point (`get_collector`)
 ├── definitions/         Device-definition loader + shipped YAML
 │                        library (`library/`, baked into the wheel)
 ├── migration/           Cross-vendor translation pipeline
 │   ├── canonical/         CanonicalIntent model + shared transforms
 │   └── codecs/            Per-vendor parse/render implementations
 ├── services/            Plain-function orchestrators (pipeline, detect, …)
 ├── storage/             FileConfigStore
 ├── tools/               sanitize, etc.
 └── templates/           Jinja2 templates (most interactive elements
                          carry a data-testid — see AGENTS.md)

netcanon_desktop/      Windows tray/webview shell around the same server
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

## See also

* **[demo.netcanon.net](https://demo.netcanon.net)** — the live hosted demo;
  no install, private throwaway instance per visitor
* [`docs/DEMO_WHITEPAPER.md`](docs/DEMO_WHITEPAPER.md) — what the demo does with
  your config, claim by claim
* [`deploy/VERIFY.md`](deploy/VERIFY.md) — the commands to verify those claims
  yourself
* [`ARCHITECTURE.md`](ARCHITECTURE.md) — the four-layer model + canonical
  bridge + codec types
* [`AGENTS.md`](AGENTS.md) — contributor directives, hard rules, doc-sync
  checklist
* [`tests/README.md`](tests/README.md) — test-tier layout + how to run
* [`docs/CAPABILITIES.md`](docs/CAPABILITIES.md) — per-codec capability matrix
* [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) — operator-facing
  diagnostic flowchart
* [`SECURITY.md`](SECURITY.md) — security model, sanitiser, supply-chain
  integrity controls
* [`CHANGELOG.md`](CHANGELOG.md) — release log
* [`TRADEMARKS.md`](TRADEMARKS.md) — third-party trademark / nominative-use notice

---

## License

MIT.  See [`LICENSE`](LICENSE).  Third-party fixtures keep their
upstream licences — see [`tests/fixtures/real/NOTICE.md`](tests/fixtures/real/NOTICE.md)
for provenance.

For responsible disclosure of security issues, see
[`SECURITY.md`](SECURITY.md).

# Netcanon

Multi-vendor network configuration backup and translation engine.

Two concerns, one FastAPI application:

1. **Backup** — pull `running-config` (or vendor equivalent) from network
   devices over SSH / NETCONF / REST, store verbatim in
   `configs/<hostname>.<ext>`.  Runs on a schedule or on demand.
2. **Migration** — translate a stored backup from one vendor's config
   grammar to another through a shared canonical intent tree.  Cisco
   IOS-XE → Aruba AOS-S, FortiGate → OPNsense, etc.

Ships on two platforms kept at strict feature parity:

| Platform | Package | Entry point |
|---|---|---|
| Web (browser) | `netconfig/` | `uvicorn netconfig.main:app` |
| Desktop (Windows) | `netconfig_desktop/` | `python -m netconfig_desktop` |

---

## Quickstart

```bash
pip install -e ".[dev]"
uvicorn netconfig.main:app --host 127.0.0.1 --port 8000
# -> http://127.0.0.1:8000        (UI)
# -> http://127.0.0.1:8000/docs   (Swagger)
```

Desktop shell:

```bash
pip install -e ".[desktop]"
python -m netconfig_desktop
```

Run the test suite:

```bash
pytest                       # unit + integration + desktop (fast)
pytest -m e2e                # Playwright browser tests (slower)
```

Tests run across four layers: unit (pure functions, no I/O — the
real-capture validation harness lives here as a unit subset),
integration (TestClient + mocked SSH), e2e (Playwright against a
live Uvicorn), and desktop (PySide6 + pystray mocked).  CI output
is the source of truth for pass counts.

---

## Where to go next

| You want to… | Start here |
|---|---|
| Understand the architecture | [`ARCHITECTURE.md`](ARCHITECTURE.md) — four-layer model, canonical bridge, codec types |
| Follow the contributor rules | [`CLAUDE.md`](CLAUDE.md) — hard rules, parity checklist, gotchas |
| Look up project jargon | [`docs/glossary.md`](docs/glossary.md) — canonical, codec, mesh, ship-before-wire, target profile, etc. |
| Read the canonical model overview | [`netconfig/migration/canonical/README.md`](netconfig/migration/canonical/README.md) — Tier 1 / 2 / 3 fields and promotion rules |
| Add or change an HTTP route | [`netconfig/api/routes/README.md`](netconfig/api/routes/README.md) — frozen pipeline-stage signatures, endpoint inventory |
| Add a new codec (vendor parser/renderer) | [`netconfig/migration/codecs/README.md`](netconfig/migration/codecs/README.md) |
| Add a new device definition / target profile | [`definitions/README.md`](definitions/README.md) — layered definitions (family base + os_version / model overlays), target-profile module-variant schema |
| Add a new canonical field | [`docs/adding-a-canonical-field.md`](docs/adding-a-canonical-field.md) — MTU as a worked example |
| Add a new target-profile YAML | [`docs/adding-a-target-profile.md`](docs/adding-a-target-profile.md) — flat-port + module-variant shapes, fit-check propagation |
| Ship a feature across web + desktop | [`docs/feature-parity-walkthrough.md`](docs/feature-parity-walkthrough.md) — SNMPv3 USM rename as a worked example |
| See what's shipped recently / current state | [`CHANGELOG.md`](CHANGELOG.md) — authoritative per-wave shipping log |
| Read the slower-changing architectural sketch | [`translator-plans.txt`](translator-plans.txt) — dense, grep-friendly long-term roadmap; most R / GAP / Phase items now `[SHIPPED]` |
| Check codec certification tiers | [`tests/fixtures/real/RESULTS.md`](tests/fixtures/real/RESULTS.md) |
| Manually exercise recent changes | [`HUMAN_TESTING.md`](HUMAN_TESTING.md) |
| Write tests | [`tests/README.md`](tests/README.md) |
| Review the security model | [`SECURITY.md`](SECURITY.md) — threat model, controls, known limitations |
| Look up what Netcanon translates and what it doesn't | [`docs/CAPABILITIES.md`](docs/CAPABILITIES.md) — operator-facing capabilities, per-codec unsupported/lossy paths, Tier-3 boundary, notification surfaces |

---

## Layout

```
netconfig/              FastAPI application (shared by both platforms)
 ├── api/routes/          HTTP endpoints (backups, migration, configs, …)
 ├── collectors/          SSH/NETCONF/REST fetchers — one factory,
 │                        one mock-point (`get_collector`)
 ├── migration/           Cross-vendor translation pipeline
 │   ├── canonical/         CanonicalIntent model + shared transforms
 │   ├── codecs/            Per-vendor parse/render implementations
 │   └── ...
 ├── services/            Plain-function orchestrators (pipeline, detect, …)
 ├── storage/             FileConfigStore
 └── templates/           Jinja2 templates (every interactive element
                          must carry a data-testid — see CLAUDE.md)

netconfig_desktop/      Windows tray/webview shell around the same server
definitions/            Device definition YAMLs (shared with backup layer)
tests/unit/             Pure-function tests, no I/O
tests/integration/      FastAPI TestClient tests, SSH mocked at get_collector
tests/e2e/              Playwright browser tests against a live Uvicorn
tests/desktop/          PySide6/pystray-mocked desktop shell tests
tests/fixtures/real/    Real-capture validation corpus (see RESULTS.md)
scripts/                One-off utilities (Aruba template renderer, …)
```

---

## Certification status

Per-codec certainty (read from `CanonicalCodec.certainty` at module load,
surfaced via `GET /api/v1/migration/adapters`).  See
[`tests/fixtures/real/RESULTS.md`](tests/fixtures/real/RESULTS.md) for
the live per-codec status — RESULTS.md is the source of truth and this
README intentionally omits per-codec counts to avoid drift.

---

## License

See [`SECURITY.md`](SECURITY.md) for responsible-disclosure policy.
Project licence is per-file (most files are MIT; third-party fixtures
keep their upstream licences — see
[`tests/fixtures/real/NOTICE.md`](tests/fixtures/real/NOTICE.md)).

# NetConfig

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

Current test state: **1,130 passing, 55 skipped** across unit /
integration / e2e / desktop / real-capture-validation layers.

---

## Where to go next

| You want to… | Start here |
|---|---|
| Understand the architecture | [`ARCHITECTURE.md`](ARCHITECTURE.md) — four-layer model, canonical bridge, codec types |
| Follow the contributor rules | [`CLAUDE.md`](CLAUDE.md) — hard rules, parity checklist, gotchas |
| Add a new codec (vendor parser/renderer) | [`netconfig/migration/codecs/README.md`](netconfig/migration/codecs/README.md) |
| Add a new canonical field | [`docs/adding-a-canonical-field.md`](docs/adding-a-canonical-field.md) — MTU as a worked example |
| Read the roadmap / current blockers | [`translator-plans.txt`](translator-plans.txt) — dense, grep-friendly, opens with a TL;DR |
| See what's shipped recently | [`CHANGELOG.md`](CHANGELOG.md) |
| Check codec certification tiers | [`tests/fixtures/real/RESULTS.md`](tests/fixtures/real/RESULTS.md) |
| Manually exercise recent changes | [`HUMAN_TESTING.md`](HUMAN_TESTING.md) |
| Write tests | [`tests/README.md`](tests/README.md) |

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

Per-codec certainty (read from `CanonicalCodec.certainty` at module
load, surfaced via `GET /api/v1/migration/adapters`):

| Codec | Certainty | Real fixtures |
|---|---|---:|
| mikrotik_routeros | **certified** ✅ | 4 across 3 OS versions |
| cisco_iosxe_cli | best_effort | 6 (grammar-test sources) |
| opnsense | best_effort | 3 (opnsense/core repo) |
| fortigate_cli | best_effort | 2 (same OS version) |
| aruba_aoss | best_effort | 1 (rendered from template) |
| cisco_iosxe (NETCONF) | best_effort | — |

See `tests/fixtures/real/RESULTS.md` for the full matrix, per-fixture
coverage, and per-codec "what blocks promotion to certified" notes.

---

## License

See [`SECURITY.md`](SECURITY.md) for responsible-disclosure policy.
Project licence is per-file (most files are MIT; third-party fixtures
keep their upstream licences — see
[`tests/fixtures/real/NOTICE.md`](tests/fixtures/real/NOTICE.md)).

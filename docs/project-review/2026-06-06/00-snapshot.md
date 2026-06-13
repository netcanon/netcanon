# 00 — Repository snapshot (2026-06-06)

State the review was taken against.  All metrics from
`git ls-files` + `wc -l` at the commit below; no working-tree
changes present (clean tree, level with `origin/main`).

## Commit / release

* **HEAD:** `b08040c` — *docs(audit): 2026-05-21 evidence trail + snapshot correction (Commit 17)*
* **Latest tag:** `v0.1.2` (security-hardening release, 2026-05-21)
* **Tag history:** `v0.1.0-rc7` → `rc8` → `rc9` → `v0.1.1` → `v0.1.2`
* Prior two review cycles already landed: security-triage (2026-05-21,
  79 alerts closed) and docs-audit (2026-05-21, 128 findings, 17
  commits).

## File inventory

| Class | Count | Notes |
|-------|------:|-------|
| `netcanon/` Python | 112 | platform + canonical + 8 codecs |
| `netcanon_desktop/` Python | 11 | PySide6 tray/embedded-server shell |
| `tests/` Python | 212 | unit / integration / e2e / desktop tiers |
| `tools/` Python | 4 | demo, full-mesh, phase4 reconciler, loader |
| `*.md` (all) | 792 | **~680 are `docs/vendor-references/` per-pair citation cache** |
| `netcanon/templates/` | 23 | Jinja HTML + `_partials/*.js` |
| `definitions/` YAML | 62 | device-class + target-profile defs |

> **The 792 .md figure is dominated by the generated per-pair,
> per-field vendor-reference cache** (`docs/vendor-references/<pair>/<field>.md`).
> The hand-authored doc surface is ~40 top-level + `docs/*.md` files
> plus per-vendor pages.  Fleet D treats the vendor-reference cache as
> a *structured artifact* (spot-check schema + a few cells), not an
> exhaustive per-file read.

## Source layout (`netcanon/`)

```
netcanon/
  main.py  cli.py  config.py  logging_config.py
  api/
    deps.py  _errors.py
    routes/  (ui.py 894, migration.py 678, backups.py 520, configs,
              definitions, schedules, sanitize, health, device_profiles,
              _migration_helpers, __init__)
  services/        (migration_pipeline.py 711, diff, migration_detect,
                    migration_validate)
  storage/         (file_store, device_profile_store, schedule_store,
                    job_store, job_registry, base)
  collectors/      (paramiko_collector 459, netmiko_collector, base, probe)
  models/          (migration.py 842, device, diff, schedule,
                    device_profile, backup, validators)
  security/        (credentials.py, migration.py)
  definitions/     (loader.py, schema.py)
  tools/           (sanitize.py 565, demo, load_cross_vendor_expectations)
  migration/
    _naming.py  _tier3_detection.py  _user_secrets.py  target_profiles.py 544
    canonical/   (intent.py 926, transforms.py 373, port_names.py 614,
                  loader, vlan_names, local_user_names, snmp_names,
                  snmpv3_user_names)
    codecs/      (base.py, registry.py, _input_shape.py, _mock/, + 8 codecs)
```

## Codec inventory (8 real + 1 mock)

`arista_eos`, `aruba_aoss`, `cisco_iosxe` (NETCONF), `cisco_iosxe_cli`,
`fortigate_cli`, `juniper_junos`, `mikrotik_routeros`, `opnsense`,
plus `_mock` (test scaffold).  Note `cisco_iosxe` (NETCONF, single-file
`codec.py`) and `cisco_iosxe_cli` (split parse/render) share
`vendor_id=cisco_iosxe` but are distinct adapters.

## God-file candidates — top source files by LOC

| LOC | File | Shape |
|----:|------|-------|
| 2455 | `migration/codecs/juniper_junos/parse.py` | split-codec parse (set + block form) |
| 1672 | `migration/codecs/cisco_iosxe_cli/parse.py` | split-codec parse |
| 1503 | `migration/codecs/juniper_junos/render.py` | split-codec render |
| 1387 | `migration/codecs/arista_eos/parse.py` | split-codec parse |
| 1291 | `migration/codecs/mikrotik_routeros/parse.py` | split-codec parse |
| 1254 | `migration/codecs/cisco_iosxe/codec.py` | **single-file** NETCONF codec |
| 1215 | `migration/codecs/aruba_aoss/parse.py` | split-codec parse |
| 1025 | `migration/codecs/mikrotik_routeros/render.py` | split-codec render |
|  958 | `migration/codecs/fortigate_cli/render.py` | |
|  950 | `migration/codecs/fortigate_cli/parse.py` | |
|  926 | `migration/canonical/intent.py` | **canonical model — cross-cutting** |
|  916 | `migration/codecs/arista_eos/render.py` | |
|  894 | `api/routes/ui.py` | **all HTML GET routes** |
|  858 | `migration/codecs/opnsense/parse.py` | |
|  845 | `migration/codecs/aruba_aoss/render.py` | |
|  842 | `models/migration.py` | **MigrationJob + request/response + matrix** |
|  817 | `migration/codecs/cisco_iosxe_cli/render.py` | |
|  711 | `services/migration_pipeline.py` | **frozen-signature orchestrator** |
|  678 | `api/routes/migration.py` | per-pane override endpoints |
|  614 | `migration/canonical/port_names.py` | cross-vendor port identity IR |
|  565 | `tools/sanitize.py` | bug-report redactor |
|  544 | `migration/target_profiles.py` | hardware-shape model |

Total `netcanon/` Python ≈ **38,914 LOC**.

## Template god-file candidates

| LOC | File |
|----:|------|
| 2477 | `templates/migrate.html` |
|  926 | `templates/definitions.html` |
|  650 | `templates/base.html` |
|  518 | `templates/devices.html` |
|  468 | `templates/sanitize.html` |

## Test corpus — largest files

| LOC | File |
|----:|------|
| 2063 | `tests/unit/migration/test_juniper_junos.py` |
| 1915 | `tests/unit/migration/test_arista_eos.py` |
| 1753 | `tests/integration/test_migration_api.py` |
| 1392 | `tests/unit/migration/test_cisco_iosxe_cli.py` |
| 1145 | `tests/unit/migration/test_mikrotik_routeros.py` |
| 1097 | `tests/e2e/test_migrate_rename_modal.py` |

Total `tests/` Python ≈ **61,166 LOC** — i.e. the test corpus is
~1.57× the size of the implementation.  Last known green run:
**3347 passed, 56 skipped** (`tests/unit`, 2026-06-06).

## Known-honest gaps carried in (from v0.1.2 CHANGELOG)

UI verification still open · cross-vendor VRRP integration test open ·
IPv6 anycast on IOS-XE SD-Access unsupported · NETCONF stub anycast
unsupported · Junos per-VRF static routes lossy · modern multi-line
VRRP AF form lossy.  Reviewers should treat these as *documented*
(not new findings) but may comment on how they're surfaced.

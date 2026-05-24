# Cluster E — Platform code docstrings

Stage 1 audit (read-only) of every `netcanon/*.py` outside `migration/codecs/`. Coverage
spans `canonical/`, `services/`, `api/`, `collectors/`, `storage/`, `models/`,
`migration/` root, plus top-level (`cli.py`, `main.py`, `config.py`, `logging_config.py`,
`__init__.py`), `definitions/`, `security/`, `tools/`.

## Summary

Platform docstring quality is **substantially better than expected for a project this
size** — the majority of modules carry purpose-rich top-of-file blocks, Pydantic models
have role docstrings, FastAPI endpoints document their contracts, and the FROZEN
`migration_pipeline.py` carries the AGENTS.md freeze rule inline.

The findings below cluster in three buckets:

1. **WRONG** — concrete contradictions between docstring and code. Six findings,
   each with a clear narrow fix.
2. **MISSING** — surfaces with no docstring or partial coverage. Twelve findings,
   mostly Pydantic models in `models/migration.py` whose field-level docstrings
   stop short of the v0.1.x additions.
3. **INCOMPLETE** — docstring exists but doesn't match the structural-load-bearing
   "enumerates contents" promise (AGENTS.md row). Five findings, all on
   `api/routes/migration.py` + `services/migration_pipeline.py` where the contents
   block enumerates per-pane override categories.

There is **one FROZEN-surface finding** (`migration_pipeline.py`) flagged for Stage 2
to touch the docstring ONLY, never the signature.

Cross-cutting observations at the end identify two pattern-level inconsistencies worth
addressing systematically (Tier annotations on canonical models; v0.2.0 Wave A schema
mentions on `CanonicalIntent`).

---

## Per-area audit

### canonical/ (CanonicalIntent + related models)

**Module-level docstrings — verified strong.** `migration/canonical/intent.py`
opens with a deep design-principles section (4 principles + Tier 1/2/3 scope + the
ship-before-wire and SNMPv3 schema-extension sections). Three subordinate modules
(`local_user_names.py`, `vlan_names.py`, `snmp_names.py`, `snmpv3_user_names.py`,
`port_names.py`) all carry purpose + collision semantics + intentionally-not-in-scope
sections.

**Class-level audit per canonical type:**

| Class | Tier annotation | Field enumeration | v0.2.0 Wave A mentions |
|---|---|---|---|
| `CanonicalIPv4Address` | Implicit (Tier 1) | Full Attributes block | `is_secondary`, `virtual_gateway_address`, `virtual_gateway_mac` documented |
| `CanonicalIPv6Address` | Implicit (Tier 1) | Full Attributes block | All Wave-A fields documented |
| `CanonicalInterface` | Implicit (Tier 1) | MIXED — inline comments on every field, but no "Attributes:" Google-style block | `vrrp_groups` documented inline |
| `CanonicalVlan` | Implicit (Tier 1) | Inline comments | n/a |
| `CanonicalStaticRoute` | Implicit (Tier 1) | Full Attributes block | `vrf` documented |
| `CanonicalDHCPPool` | Tier 2 implicit | Inline comments only — no docstring beyond one-liner | n/a |
| `CanonicalSNMP` | Tier 2 implicit | One-line role docstring + per-field `#:` markers on `v3_users` only | n/a |
| `CanonicalSNMPv3User` | Tier 2 implicit | Full Attributes block (excellent) | n/a |
| `CanonicalLAG` | Tier 2 implicit | One-liner; inline comments on fields | n/a |
| `CanonicalLocalUser` | Tier 2 implicit | One-liner; inline comments on fields | n/a |
| `CanonicalRADIUSServer` | Tier 2 implicit | One-liner; inline comments on fields | n/a |
| `CanonicalVRRPGroup` | Implicit (Wave A) | Full Attributes block (excellent) + ship-before-wire note | n/a (is itself the Wave A surface) |
| `CanonicalVxlan` | Tier 2 implicit | Full Attributes block | n/a |
| `CanonicalRoutingInstance` | Tier 2 implicit | Full Attributes block + `l3_vni` inline comment block | n/a |
| `CanonicalEvpnType5Route` | Tier 2 implicit | Full Attributes block | n/a |
| `CanonicalIntent` | Mentioned via section comments | Inline comments only — does NOT enumerate fields in Attributes block | `vrrp_groups`, `virtual_gateway_address`, `is_secondary`, `vrf`, `anycast_gateway_mac` all present as inline comments but NOT in a class docstring "Attributes" section |

**Tier annotation pattern:** The module docstring divides canonical types into Tier 1
/ 2 / 3 (lines 31-49), but the per-class docstrings rely on section comments in
intent.py (`# Tier 1 — auto-translatable`) rather than declaring "Tier N" inside each
class docstring. This is consistent within the file but a contributor reading just one
class via `help()` or an IDE tooltip wouldn't see the tier without scrolling.

**Findings:**

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| E-canon-1 | `netcanon/migration/canonical/intent.py:171-172` | INCOMPLETE | `CanonicalInterface` docstring is a one-line role description; doesn't enumerate any of the ~25 fields. Every field has an inline comment, but no Google-style "Attributes:" block. v0.2.0 Wave A field `vrrp_groups` appears as inline comment block (lines 294-303) but isn't in the class docstring. | Convert inline comments into an "Attributes:" Google-style block; or at minimum add an "Attributes" pointer line saying "see field-level inline comments" + explicit mention of v0.2.0 additions. |
| E-canon-2 | `netcanon/migration/canonical/intent.py:764-774` | INCOMPLETE | `CanonicalIntent` docstring describes the top-level role but doesn't enumerate fields. Six v0.2.0 Wave A additions (`vrrp_groups` on each Interface, `virtual_gateway_address`, `is_secondary`, `anycast_gateway_mac`, `routing_instances`, `vxlan_vnis`, `evpn_type5_routes`, plus `dropped_tier3_sections` and `apply_groups`/`group_content` Junos provenance) are documented as inline `# ── ── ──` comments. AGENTS.md "module docstring enumerates contents" rule applies here. | Add an "Attributes:" or "Top-level fields" enumeration section to the class docstring (or convert to "see field comments + module docstring scope sections"). Explicitly mention `anycast_gateway_mac` since v0.2.0 Wave A ship-before-wire — currently only visible via long inline comment at 804-825. |
| E-canon-3 | `netcanon/migration/canonical/intent.py:362-363` | INCOMPLETE | `CanonicalDHCPPool` docstring is `"""A DHCP server pool."""` — every field uses inline `#` comments, but no Attributes block. Tier 2 status not stated. | Expand to Attributes block or add tier annotation. |
| E-canon-4 | `netcanon/migration/canonical/intent.py:482-483` | INCOMPLETE | `CanonicalLAG` docstring is one-liner. Wave-A-adjacent: `mode` accepts `"active"`/`"passive"`/`"static"` (inline comment); a Google-style Attributes block would surface the enum-of-strings cleanly. | Expand to Attributes block. |
| E-canon-5 | `netcanon/migration/canonical/intent.py:597-598` | INCOMPLETE | `CanonicalLocalUser` docstring is one-liner. Inline comments cover fields but no Tier 2 annotation. | Expand or add tier annotation. |
| E-canon-6 | `netcanon/migration/canonical/intent.py:606-607` | INCOMPLETE | `CanonicalRADIUSServer` docstring is one-liner. Field `key` carries inline comment "shared secret (opaque)" but the class docstring doesn't enumerate it. | Expand to Attributes block; clarify `key` is a shared-secret field. Related to finding E-tools-1 below (sanitize.py docstring claims field is named `shared_secret`). |
| E-canon-7 | `netcanon/migration/canonical/loader.py:1-12` | EXPECTED-STALE | Module is a stub that says "Phase 0 ships only this stub" and raises NotImplementedError on every call. Per the broader audit charter this is documented "phased deliverable" not drift. Leave. | None — document in synthesis as expected per Phase 0.5 plan. |

### api/ (FastAPI routes + dependencies)

**Module docstring enumeration verified against actual routes:**

- `migration.py`: docstring lists every endpoint (`/adapters`, `/adapters/{name}/capabilities`,
  `/plan`, `/plan/ports`, `/plan/vlans`, `/plan/local_users`, `/plan/snmp`,
  `/plan/snmpv3`, `/render`, `/detect`, `/target-profiles`,
  `/target-profiles/{vendor}/{model}`) — every route in the file is enumerated.
  **MATCHES.**
- `backups.py`: docstring lists POST/GET/GET — all three present. **MATCHES.**
- `configs.py`: docstring lists GET/GET/DELETE/POST/POST — all five present. **MATCHES.**
- `schedules.py`: NO enumeration in module docstring (describes purpose only) but the
  routes are GET/POST/DELETE/POST. The "no enumeration" form is the safer pattern
  per AGENTS.md (describe intent vs. inventory). No drift.
- `device_profiles.py`: NO enumeration in module docstring. Routes are GET/GET/POST/PUT/DELETE.
  No drift.
- `definitions.py`: NO enumeration in module docstring. Routes are GET/GET/POST. No drift.
- `health.py`: enumerates one route. **MATCHES.**
- `sanitize.py`: enumerates POST. **MATCHES.**
- `ui.py`: NO enumeration — describes intent. Routes are GET on `/`, `/jobs`,
  `/schedules`, `/configs`, `/configs/{left}/vs/{right}`, `/devices`, `/definitions`,
  `/migrate`, `/sanitize`, `/docs`. No drift.

**Per-endpoint docstring presence:** Every route function I read carries a docstring.
The Google-style Args/Raises sections vary: routes that take path params or return
non-trivial shapes have full Args+Raises (backups.py, configs.py, device_profiles.py
all good); single-shot routes have one-liners (acceptable for trivial returns).

**Findings:**

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| E-api-1 | `netcanon/api/routes/migration.py:269` | WRONG | Inside `plan_migration_ports` docstring: "subsequent category endpoints (``/plan/vlans``, ``/plan/snmp``, ``/plan/local-users``) will follow". Hyphenated `local-users` is wrong — every other reference (module docstring line 34, function decorator at 366, internal cross-refs at 84, 407, 510) uses `local_users` with underscore, and the actual route is `/plan/local_users`. | Edit single token: `/plan/local-users` → `/plan/local_users`. |
| E-api-2 | `netcanon/api/routes/migration.py:12-22` | INCOMPLETE | Module docstring's "Translation pipeline entries" block enumerates `/plan` and `/plan/ports`, `/plan/vlans`, `/plan/local_users`, `/plan/snmp`, `/plan/snmpv3` — but the per-category bullet under `/plan` only mentions `port_rename_map`, `vlan_rename_map`, `local_user_rename_map`, `snmp_community_rename_map`. Missing `snmpv3_user_rename_map` from the dispatch-condition list at line 18. | Extend the list at line 18-19 to include `snmpv3_user_rename_map`. |
| E-api-3 | `netcanon/api/routes/migration.py:82-86` | STYLE | The "Future per-pane categories" sentence cites `radius`, `snmp_trap_hosts` as future plans. No drift today, but it's worth verifying this list against `docs/v0.2.0-planning/` so doc cross-refs hold. | Cross-reference verification in Stage 2 (orchestrator-direct). |
| E-api-4 | `netcanon/api/__init__.py:1` | STYLE | One-line module docstring `"""FastAPI router modules for the Netcanon REST API."""` is fine for an `__init__.py`. No drift. | None. |

### services/ (migration_pipeline + sanitiser + others)

**FROZEN-surface verification:**

`netcanon/services/migration_pipeline.py` module docstring (lines 1-93) explicitly
states the freeze:

> Public surface (frozen signatures — see Hard Rules below):
>   * `run_plan`
>   * `run_plan_with_rename`
>   * `run_plan_with_overrides`

And again at lines 82-90 ("Hard Rules"):

> NEVER change the signatures of `run_plan`, `run_plan_with_rename`, or
> `run_plan_with_overrides`. … NEW pipeline behaviour goes on a NEW public function,
> not an existing one.

This matches AGENTS.md hard rule line 281-284. **Verified — the freeze is documented
in the module docstring as required.**

**Per-function docstrings:**

- `run_plan`: full docstring with stages explained, cross-device-class guard
  documented, Args/Returns. Good.
- `run_plan_with_overrides`: extensive docstring covering the five categories +
  capture-only fields. Good. Notes the "Frozen-signatures rule: NEW function (signature
  free to grow)" — consistent with AGENTS.md.
- `run_plan_with_rename`: documented as legacy wrapper around
  `run_plan_with_overrides`. Notes the `None → {}` normalisation for behaviour
  preservation. Good.

**Other services:**

- `services/__init__.py`: One-liner. Fine.
- `services/diff.py`: Full module docstring + every function has Args/Returns/Raises.
- `services/migration_detect.py`: Full module docstring + class & function docstrings.
- `services/migration_validate.py`: Full module docstring + class & function docstrings.

**Findings:**

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| E-svc-1 | `netcanon/services/migration_pipeline.py:323-328` | INCOMPLETE | The "Planned future-commit categories" list (snmp_trap_host, ntp_server, dns_server, syslog_server, radius_override) is forward-looking. Since the file is FROZEN, this list will drift as categories ship. Recommend converting to "see `docs/v0.2.0-planning/` for the planned extension surface" pointer rather than maintaining an inline inventory. **FROZEN: Stage 2 touches the docstring only, never the signature.** | Replace the inline list with a pointer to `docs/v0.2.0-planning/`. FROZEN docstring-only edit. |
| E-svc-2 | `netcanon/services/migration_pipeline.py:11-12` | INCOMPLETE | The "Public surface" enumeration lists three functions but doesn't mention that `_capture_source_shape` (the capture-first transform) is also an implicitly-public behaviour — it populates `source_*` fields on every job. The capture-transform's invariants are documented further down (lines 62-79) but a quick `help()`-style reader of the public-surface block might miss it. **FROZEN: docstring only.** | Add a one-line cross-reference from the "Public surface" section pointing to the "Capture-first transform" section further down. FROZEN. |

### collectors/ (netmiko + paramiko)

**Module docstrings:**

- `__init__.py`: orientation + "Adding a new strategy" recipe. Good.
- `base.py`: brief module docstring + comprehensive class docstring for `BaseCollector`
  including the probe-vs-collect abstraction.
- `paramiko_collector.py`: lists what's customised + cites OPNsense console-menu special
  case. Good purpose framing.
- `netmiko_collector.py`: lists supported `netmiko_device_type` values (Cisco IOS-XE,
  FortiOS, MikroTik RouterOS). **Verify against current adapters.**
- `probe.py`: full module docstring + parse_probe_output has Args/Returns.

**Security framing (AutoAddPolicy threat model):**

The scope file calls out `paramiko_collector.py` as the AutoAddPolicy path requiring
the "operator-as-trust-anchor" threat-model documentation. The file currently does
NOT mention AutoAddPolicy or host-key trust anywhere in module / class / method
docstrings. Line 147 in `collect()`:
```python
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
```
…has no docstring or comment justifying the choice. Same on line 237 in `probe()`.

This appeared in the security-triage cycle and was accepted; per the audit charter the
docstring should reflect the threat model so anyone reading the file cold sees the
trust assumption.

**Findings:**

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| E-col-1 | `netcanon/collectors/paramiko_collector.py:1-16, 118-127, 147, 237` | MISSING | No mention of `AutoAddPolicy` / operator-as-trust-anchor threat model in module docstring, `ParamikoShellCollector` class docstring, or near the two `set_missing_host_key_policy(paramiko.AutoAddPolicy())` call sites. Security-triage accepted this as operator-trust-anchored per `docs/security-triage/2026-05-21/`; the file should carry that rationale inline. | Add a "Security model" section to the module docstring naming AutoAddPolicy + linking to the security-triage decision. Add an explanatory comment above each `set_missing_host_key_policy()` call. |
| E-col-2 | `netcanon/collectors/netmiko_collector.py:11-15` | INCOMPLETE | "Supported netmiko_device_type values" lists `cisco_xe`, `fortinet`, `mikrotik_routeros`. This is a hard-coded inventory — the actual list depends on which device definitions declare `collector.strategy: netmiko`. Per AGENTS.md "Never hard-code a count" cousin rule, an enumeration that drifts silently. | Convert to "see `definitions/*/collector.yaml` files declaring `strategy: netmiko` for the current set" pointer. |
| E-col-3 | `netcanon/collectors/__init__.py:1-14` | STYLE | The "Adding a new strategy" recipe is good. Step 2 says "Register it in `get_collector` (`base.py`)" — verified correct. Step 4 says "Document the strategy in `collectors/README.md`" — `collectors/README.md` was not in scope for this audit (sub-READMEs are Cluster C). Worth verifying that file exists. | Cluster C cross-check (separate cluster). |
| E-col-4 | `netcanon/collectors/probe.py` | (none) | Full module docstring + function Args/Returns. **VERIFIED.** | None. |

### storage/

**Module docstrings + class docstrings — all five files audited.**

- `__init__.py`: Good purpose framing.
- `base.py`: `BaseConfigStore` ABC + every abstract method has Args/Returns/Raises. Good.
- `file_store.py`: Comprehensive module docstring covering directory layout, filename
  grammar, type_key invariants, startup migration, collision safety, sidecar metadata.
- `job_registry.py`: Excellent module + class docstring with semantic notes (`__len__`,
  `values()`, `__getitem__` lazy-load).
- `job_store.py`: Module docstring + class + method docstrings.
- `schedule_store.py`: Module docstring + class + method docstrings.
- `device_profile_store.py`: Module docstring (covers credential encryption + legacy
  plaintext migration) + class + method docstrings.

**MAX_CONFIG_SIZE rationale verification:**

The scope file requires `MAX_CONFIG_SIZE` documentation + rationale. The constant
lives at `netcanon/storage/file_store.py:133` — **inside the `save()` method body**,
not at module level. Inline comment is just `# 50 MB`. The `save()` method docstring
(lines 119-130) does not mention the size cap.

This is a structural problem: the cap is a load-bearing operator-visible limit (the
error path is plumbed all the way through `api/_errors.py` to the operator UI). It
should be a module-level constant with rationale (similar to
`config.py:MAX_BACKUP_CONCURRENCY` which IS module-level + documented).

**Findings:**

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| E-store-1 | `netcanon/storage/file_store.py:133-138` | INCOMPLETE | `MAX_CONFIG_SIZE` is defined inside the `save()` method body with only `# 50 MB` as comment. No rationale (why 50MB? observed largest config? memory-safety choice?). Not surfaced in module docstring or `save()` docstring. The cap is operator-visible via `api/_errors.py:243-247` which calls these "in-house ValueErrors (file_store 50MB cap, ...)". | Hoist to module-level constant with a comment block explaining the choice. Add a "Raises: ValueError" entry to `save()` docstring with the cap reasoning. Reference `config.py:MAX_BACKUP_CONCURRENCY:17-20` for the pattern. |
| E-store-2 | `netcanon/storage/file_store.py:104` | INCOMPLETE | `_migrate_flat_files()` is called from `__init__` but `FileConfigStore.__init__` docstring (lines 91-99) doesn't mention that one-time legacy-flat-file migration happens on construction. The module docstring DOES (lines 32-34) — but `__init__` is the surface contributors see when grepping for class init behaviour. | Add one sentence to `__init__` docstring or class docstring linking to the module's "Startup migration" section. |

### models/

**Pydantic model docstrings — coverage verified for all 8 files.**

- `__init__.py`: One-liner + `__all__`. Good for a re-export module.
- `backup.py`: All four classes (`JobStatus`, `ConfigRecord`, `BackupResult`, `BackupJob`)
  have full Attributes blocks. Note: docstring on `BackupJob` doesn't mention the
  v0.1.x added fields `schedule_id`, `schedule_name` — they exist on the model (lines
  108-109) but aren't in the Attributes list (lines 92-100).
- `device.py`: All three classes have full Attributes blocks including v0.1.x
  additions (`os_version`, `model`, `device_profile_id`).
- `device_profile.py`: All three classes have full Attributes blocks. `detected_facts`
  documented.
- `diff.py`: All five classes have full Attributes blocks. Good.
- `schedule.py`: All three classes have full Attributes blocks.
- `validators.py`: One-liner module docstring + `validate_host` has docstring. Good.
- `migration.py`: MIXED — see findings below; the v0.2.0 / v0.1.x additions to
  `MigrationJob` are documented via `#:` markers but the `Attributes:` block in the
  class docstring (lines 318-330) lists only 10 of the actual ~25 fields.

**Findings:**

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| E-mod-1 | `netcanon/models/migration.py:310-343` | INCOMPLETE | `MigrationJob` class docstring's `Attributes:` block (lines 318-330) lists 10 fields. The class actually has 23 fields (counting). Fields after `error` (`warnings`, `port_renames`, `port_drops`, `vlan_renames`, `vlan_drops`, `source_vlans`, `source_hostname`, `local_user_renames`, `local_user_drops`, `source_local_users`, `snmp_community_renames`, `snmp_community_drops`, `source_snmp_community`, `snmpv3_user_renames`, `snmpv3_user_drops`, `source_snmpv3_users`, `dropped_tier3_sections`) are documented via `#:` Sphinx markers on each individual field — Sphinx-correct, but a reader of just the class docstring sees only the original 10. AGENTS.md "doc-sync" row about "function gains a new parameter" applies to attribute additions on shared Pydantic models. | Either (a) extend the `Attributes:` block to list all fields with cross-pointers; or (b) shorten the Attributes block to "Initial Phase-0 attributes are described below; per-category override outcome fields (port_renames, vlan_renames, ...) are documented inline via per-field markers." |
| E-mod-2 | `netcanon/models/backup.py:87-100` | INCOMPLETE | `BackupJob.Attributes` (lines 92-100) lists 7 attributes; class actually has 9 (`schedule_id`, `schedule_name` added later). Inline `# None for manually triggered jobs` on lines 108-109 documents them but they're not in the Attributes block. | Extend Attributes to include both new fields. |
| E-mod-3 | `netcanon/models/migration.py:154-172` | INCOMPLETE | `CapabilityMatrix.Attributes` (lines 161-167) lists 5 fields. Actual model has 7 (`vendor_id`, `device_classes` added later — both documented inline via `#:` comments but missing from the Attributes block). | Extend Attributes to include `vendor_id` and `device_classes`. |
| E-mod-4 | `netcanon/models/migration.py:31-50` | (none) | `DeviceClass` enum docstring is excellent — covers taxonomy rationale, sparsely-add discipline, primary-feature-surface filter. **VERIFIED.** | None. |

### Top-level (cli.py, main.py, config.py, logging_config.py, __init__.py)

**`netcanon/__init__.py`:**

- Module docstring lists `package layout` (config / models / definitions / storage /
  collectors / api / main). Notable: the `migration` package is NOT in this layout
  enumeration — it's a substantial subpackage that has shipped since this docstring
  was written. Per AGENTS.md doc-sync row about "module docstring enumerates
  contents", this needs updating.

**`netcanon/cli.py`:**

- Module docstring covers the `netcanon sanitize` subcommand + entry-point invocation
  forms. **VERIFIED `main()` has usable `--help` text via `description=` + per-arg
  help.**

**`netcanon/main.py`:**

- Module docstring covers `create_app` + UI route delegation. Good.
- `create_app` has full docstring with Args/Returns.
- **FastAPI app version is hard-coded to `"0.1.0"` at line 218** — current release
  is v0.1.2 per the snapshot. This is exposed via `/api/v1/openapi.json` and
  consumed by `/docs` Swagger UI. The `/health` endpoint at `netcanon/api/routes/health.py:32`
  correctly uses `importlib.metadata.version("netcanon")`; main.py doesn't.

**`netcanon/config.py`:**

- Module docstring covers env-var prefix + `.env` discovery.
- `Settings` class has Attributes block listing every settings field. Recent additions
  (`data_dir`, `effective_data_dir`, `backup_concurrency`, `max_memory_jobs`,
  `open_in_editor`) all documented. **VERIFIED.**
- `MAX_BACKUP_CONCURRENCY` module-level constant has rationale comment (good pattern;
  contrast with `MAX_CONFIG_SIZE` in finding E-store-1).

**`netcanon/logging_config.py`:**

- Module docstring covers idempotence + uvicorn interaction + the request-id format
  + the contextvar mechanism. **VERIFIED.**
- `configure_logging` + `RequestIdFilter` + `REQUEST_ID_CTX` all documented.

**Findings:**

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| E-top-1 | `netcanon/main.py:218` | WRONG | `version="0.1.0"` in FastAPI app definition. Current release is v0.1.2 per `docs/docs-audit/2026-05-21/00-snapshot.md`. This is operator-visible via `/api/v1/openapi.json` and `/docs`. The pattern at `api/routes/health.py:25` (`version("netcanon")`) should be reused here. | Replace literal `"0.1.0"` with `importlib.metadata.version("netcanon")` (with `PackageNotFoundError` fallback like health.py uses), OR with a runtime-resolved `_VERSION` constant defined at module load. |
| E-top-2 | `netcanon/__init__.py:5-12` | INCOMPLETE | Package-layout list omits `netcanon.migration` (the migration engine subpackage). The package layout has grown substantially since this docstring. AGENTS.md "module docstring enumerates contents" rule applies. | Add `netcanon.migration` row (with a brief "Multi-vendor config translation through CanonicalIntent" tag). Optionally add `netcanon.services`, `netcanon.security`, `netcanon.tools` for completeness. |
| E-top-3 | `netcanon/cli.py:1-22` | (none) | `--help` text is rendered from argparse's `description` (line 35) + per-arg `help` strings. Adequate. | None. |
| E-top-4 | `netcanon/main.py:212-223` | STYLE | FastAPI `description` says "See /docs for the interactive API reference" — accurate, with `/docs` served via `ui.py:831`. | None. |
| E-top-5 | `netcanon/main.py:295-302` | STYLE | The fallback try/except around `create_app()` for production-instance startup is good defensive coding but isn't mentioned in the module docstring. Low priority. | None or one-line module-docstring mention. |

### migration/ root (non-codec)

**Files in scope:** `__init__.py`, `_naming.py`, `_tier3_detection.py`,
`_user_secrets.py`, `target_profiles.py`, `vendors/__init__.py`.

- `__init__.py`: Module docstring covers Phase 0 scope + auto-discovery mechanism +
  "leading underscore = internal" convention. **VERIFIED.**
- `_naming.py`: Full module docstring covering the hostname-with-whitespace bug +
  "See also" cross-references. Each function has Args/Returns.
- `_tier3_detection.py`: Comprehensive module docstring + per-vendor function
  enumeration + per-pattern-set rationale. Good.
- `_user_secrets.py`: Excellent module docstring covering the algorithm vocabulary,
  per-target accept lists, and rationale comments on each entry in `_TARGET_ACCEPTS`.
- `target_profiles.py`: Excellent module docstring covering use cases, YAML shape,
  module variants, per-vendor capacity limits + `max_vlans_source` provenance pattern.
- `vendors/__init__.py`: Module docstring + `load_vendors` docstring. Good.

**Findings:** None.

### definitions/, security/, tools/ (light audit)

These weren't in the scope file's primary list but I verified all carry purpose-rich
docstrings on read.

- `definitions/__init__.py`: orientation. Good.
- `definitions/loader.py`: comprehensive module docstring covering load_all vs.
  resolve, override resolution, longest-match resolution examples.
- `definitions/schema.py`: module docstring + per-class Attributes blocks + field-level
  inline comments. Type-key invariant documented.
- `security/__init__.py`: one-liner.
- `security/credentials.py`: extensive module docstring covering the 3-tier Fernet
  key resolution + migration policy.
- `security/migration.py`: brief module docstring + function docstring. Good.
- `tools/__init__.py`: orientation.
- `tools/sanitize.py`: extensive module docstring covering field-typed rules. **One
  WRONG finding below.**

**Findings:**

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| E-tools-1 | `netcanon/tools/sanitize.py:35` | WRONG | Docstring claims `CanonicalRADIUSServer.shared_secret` is sanitised to `"REDACTED-RADIUS-N"`. Actual field name on `CanonicalRADIUSServer` is `key` (`netcanon/migration/canonical/intent.py:610`). Grep confirms `shared_secret` appears nowhere in the canonical model. | Edit single token: `CanonicalRADIUSServer.shared_secret` → `CanonicalRADIUSServer.key`. Verify the actual sanitization rule by reading the code path (which I didn't fully trace — Stage 2 should confirm field name matches what sanitizer mutates). |

---

## Cross-cutting observations

### CC-1 — Tier annotations on canonical Pydantic classes (PATTERN)

The `intent.py` module docstring divides canonical types into Tier 1 / 2 / 3 (lines
31-49). The classes themselves use section comments (`# Tier 1 — auto-translatable`,
`# Tier 2 — auto-translate with review banner`) to mark boundaries. But individual
class docstrings don't carry their tier annotation.

A contributor reading `CanonicalDHCPPool.__doc__` via `help()` or IDE tooltip sees
`"A DHCP server pool."` with no tier context. The tier is load-bearing for the
pipeline (validation banner severity, migrate page UX), so it deserves a per-class
tag.

**Recommendation:** Add a one-line "Tier N (rationale)" header to every canonical
class docstring. Example:
```
class CanonicalDHCPPool(BaseModel):
    """A DHCP server pool (Tier 2 — auto-translate with review banner)."""
```
Or use a Sphinx role: `:tier: 2`. This is a 16-line edit across `intent.py` (one per
class), all small, all consistent.

### CC-2 — v0.2.0 Wave A schema-extension visibility (PATTERN)

v0.2.0 Wave A added `vrrp_groups`, `virtual_gateway_address`, `virtual_gateway_mac`,
`is_secondary`, `vrf` on static-route, `anycast_gateway_mac` on intent, plus
`vxlan_vnis`, `evpn_type5_routes`, `routing_instances`. The intent.py module
docstring's "Schema extensions" sub-sections cover most of these; per-field inline
comments document each. But:

- `CanonicalIntent` class docstring (lines 764-774) does NOT enumerate ANY of these
  ship-before-wire fields. Reader of just the class docstring sees a generic
  description.
- `CanonicalInterface` class docstring (line 172) is a one-liner; `vrrp_groups` is
  added via inline section comment but absent from class docstring.

**Recommendation:** When extending `CanonicalIntent` or `CanonicalInterface` (the
load-bearing classes), also extend the class docstring's enumeration in the SAME
commit per AGENTS.md doc-sync. The current code-change-without-docstring-update
pattern explains the drift.

### CC-3 — `MAX_CONFIG_SIZE` vs `MAX_BACKUP_CONCURRENCY` pattern inconsistency

`config.py:17-20` defines `MAX_BACKUP_CONCURRENCY` as a documented module-level
constant with rationale. `storage/file_store.py:133` defines `MAX_CONFIG_SIZE`
inside a method body with a `# 50 MB` comment. Both are operator-visible caps that
surface as `ValueError` to the UI. They should follow the same pattern.

**Recommendation:** Hoist `MAX_CONFIG_SIZE` to module level in `file_store.py` with
the same rationale-comment shape. Same fix as finding E-store-1.

### CC-4 — Forward-looking inventories in FROZEN file (RISK)

`migration_pipeline.py` is FROZEN per AGENTS.md hard rule. Its docstring contains
several inline enumerations of "Planned future-commit categories" (line 323-328)
and "Current category support" (line 311-321) that will drift as the codebase
grows. Per the FROZEN constraint, Stage 2 CAN touch the docstring to fix drift,
but the docstring shape that drifts least is "see `docs/v0.2.0-planning/` for the
extension surface" pointers, not maintained inventories.

**Recommendation:** Replace inline future-category inventories with cross-pointers.
This is finding E-svc-1.

### CC-5 — Auto-detection module list in `netcanon/__init__.py` is outdated (RISK)

`netcanon/__init__.py:5-12` enumerates the package layout but omits `netcanon.migration`
(a substantial subpackage). Same drift class as CC-4 — inline inventory of fast-moving
content. Per AGENTS.md, either keep current OR convert to pointer.

**Recommendation:** Extend the enumeration. This is finding E-top-2.

### CC-6 — Collector AutoAddPolicy threat model invisibility (SECURITY-ADJACENT)

The paramiko_collector.py file uses `AutoAddPolicy` without any docstring
documentation. The security-triage cycle accepted this as operator-trust-anchored
but the rationale lives in `docs/security-triage/2026-05-21/` — anyone reading the
file in isolation can't tell whether this is a known accepted decision or a bug.

**Recommendation:** Surface the security-model decision into the file's docstring +
near each call site. Finding E-col-1.

### CC-7 — Per-pane override category symmetry across multiple files (PATTERN)

The five per-pane categories (port, vlan, local_user, snmp_community, snmpv3_user)
are documented consistently across `migration_pipeline.py`, `api/routes/migration.py`,
`models/migration.py`, and the per-category orchestrators under
`migration/canonical/`. This is a quality high-water mark — when the sixth category
ships, the docstring template is well-established. No action needed; capturing as
positive observation.

### CC-8 — Pydantic `Attributes:` block drift (PATTERN)

`MigrationJob` (15 fields not in Attributes), `BackupJob` (2 missing), `CapabilityMatrix`
(2 missing) all show the same drift class: the original `Attributes:` block was
written with the original fields, and subsequent additions used Sphinx `#:` markers
on individual fields. Sphinx renders them correctly, but the `help()` / class-docstring
surface is incomplete.

**Recommendation:** Either commit to the `#:` per-field pattern and shorten the
`Attributes:` block to a "see field-level docs" pointer; or commit to the
`Attributes:` block and update it on every new-field add (AGENTS.md doc-sync row
exists for this). Either decision is fine; the inconsistency is the actual drift.

---

## Summary table — all findings by severity

| Severity | Count | Findings |
|---|---|---|
| WRONG | 3 | E-api-1 (URL hyphen), E-top-1 (hard-coded 0.1.0), E-tools-1 (shared_secret) |
| MISSING | 1 | E-col-1 (AutoAddPolicy threat model) |
| INCOMPLETE | 13 | E-canon-1, E-canon-2, E-canon-3, E-canon-4, E-canon-5, E-canon-6, E-api-2, E-svc-1 (FROZEN), E-svc-2 (FROZEN), E-store-1, E-store-2, E-col-2, E-top-2, E-mod-1, E-mod-2, E-mod-3 |
| STYLE | 4 | E-api-3, E-api-4, E-col-3, E-top-4, E-top-5 |
| EXPECTED-STALE | 1 | E-canon-7 (Phase-0 stub by design) |

**FROZEN-surface flags (Stage 2 must touch DOCSTRING ONLY, never signature):**
E-svc-1, E-svc-2 — both in `netcanon/services/migration_pipeline.py`.

---

## Recommendations for Stage 2 dispatch

* **Quick orchestrator-direct fixes (single-token edits):** E-api-1, E-top-1,
  E-tools-1. Three edits, each one-line.
* **Pattern-fix opportunities (one batch each):**
  * Canonical-class Tier-N annotations (CC-1) — 16-line consistent edit across
    `intent.py`.
  * Pydantic `Attributes:` block consistency (CC-8) — decide pattern, then apply to
    `MigrationJob`, `BackupJob`, `CapabilityMatrix`.
* **Single-file rewrites:**
  * `paramiko_collector.py` security model (E-col-1) — module docstring + 2 inline
    comments.
  * `file_store.py` MAX_CONFIG_SIZE hoist (E-store-1, CC-3) — small structural
    refactor + docstring.
* **FROZEN docstring-only edits:** E-svc-1, E-svc-2 — `migration_pipeline.py`
  docstring ONLY; signature stays.
* **Light review:** E-api-3 (forward-looking category list cross-ref to
  `docs/v0.2.0-planning/`).

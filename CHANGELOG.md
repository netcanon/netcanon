# Changelog

All notable changes to NetConfig are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Added (ship `probe:` block for Cisco IOS-XE family-base + overlay inheritance note)

- `definitions/cisco/ios-xe/17.x.yaml` now declares a `probe:` block
  — the first shipped definition to opt into the P1C3 probe-phase
  machinery.  Command is `show version`; two regex patterns feed
  `DefinitionLoader.resolve()` and `DeviceProfile.detected_facts`:
    - `detected_os_version: "Version\\s+(\\d+\\.\\d+)"` — captures
      major.minor (e.g. `17.12`) from `Version 17.12.03, RELEASE …`.
      Major.minor is deliberate: the 17.12 overlay pins
      `os_version: "17.12"` and the resolver's match is exact-string,
      so capturing the full patch level (`17.12.03`) would MISS
      the overlay.
    - `detected_model: "Model Number\\s+:\\s+(\\S+)"` — captures
      hardware model (e.g. `C9300-48P`) from the `Model Number` line
      of Catalyst 9000 `show version` output.
- `definitions/cisco/ios-xe/17.12.yaml` intentionally does NOT
  declare its own `probe:` block.  The backup pipeline runs probe()
  on the family-base collector BEFORE resolving overlays, so the
  overlay inherits the family-base probe behaviour without
  duplication.  Inline comment in the overlay YAML documents this
  so a future contributor doesn't "helpfully" copy the block down.
- New integration tests in `tests/integration/test_backup_probe_wiring.py`
  (`TestShippedCiscoIOSXEProbeBlock`) lock in that the shipped
  family-base carries a non-empty `probe.command` with both
  `detected_os_version` + `detected_model` patterns, and that the
  17.12 overlay ships with NO probe block of its own.

### Changed (data enrichment — soft-limit `max_vlans` populated across MikroTik / OPNsense / FortiGate)

- Every shipped target profile now declares `max_vlans` so the
  VLAN-pane fit-check banner renders something for every
  selectable target.  New per-vendor distribution:
    - MikroTik RouterOS (2 profiles): 4094 — 802.1Q protocol
      ceiling supported universally on modern RouterOS.
    - OPNsense (24 profiles): 4094 — FreeBSD netgraph VLANs,
      protocol ceiling is the only hard limit.
    - FortiGate: 40F = 512, 60F = 512, 100E = 1024 (from
      Fortinet's FortiOS 7.x "Maximum Values Table").
  Aruba + Cisco values from prior commit unchanged.
- `max_local_users` intentionally STAYS unset on MikroTik /
  OPNsense / FortiGate profiles:
    - MikroTik: software-unbounded, no meaningful fit-check.
    - OPNsense / FortiGate: codecs don't yet round-trip
      CanonicalLocalUser, so the local-users pane surfaces a
      compat banner (see Item 1B) instead — setting the fit-check
      limit would visually overlap with that banner and confuse
      operators.
- New shipped-profile lock-in tests (3 cases) guard against
  silent drift: every profile declares `max_vlans`, distinct
  values match the documented per-vendor rationale, and
  `max_local_users` stays unset on the three soft-limit vendor
  families.

### Added (per-pane capacity fit-check banners — `TargetProfile.max_vlans` + `max_local_users`)

- Two new optional fields on `TargetProfile`:
    - `max_vlans: int | None` — active-VLAN limit for the device.
    - `max_local_users: int | None` — local-account limit.
- Each rename-modal pane (VLANs, local_users) renders its own
  fit-check banner sourced from these fields.  Three states:
  hidden (no profile picked OR limit undeclared) / green OK
  ("VLAN fit: N / limit") / red block ("VLAN OVER capacity — K
  over, pick a larger model").
- Pane-scoped: the ports fit-check banner (driven by per-kind
  capacity counts) stays in its own element; each new category's
  banner is a sibling, not an overload.  Adding a future SNMP /
  RADIUS fit-check banner follows the same pattern.
- Shipped profiles populated where datasheet numbers are
  reliable:
    - Aruba 2930F family (4 profiles): max_vlans=2048, max_local_users=16
    - Aruba 3810M (2): max_vlans=4094, max_local_users=16
    - Aruba 6300M (1): max_vlans=4094, max_local_users=64
    - Cisco C9300 family (6) + C9500 (2): max_vlans=4094
  Softer-limit vendors (MikroTik / OPNsense / FortiGate) left
  unset — populating them with best-guess values would mislead
  operators more than helping.
- 5 new unit tests (TargetProfile schema) + 3 new e2e tests
  (TestRenameModalPerPaneFitCheck).

### Added (Item 1 Option B — target-codec compatibility banners on rename panes)

- `CodecBase.unsupported_rename_categories: frozenset[str]`
  declares per-pane categories the codec doesn't round-trip.
  OPNsense + FortiGate both declare `{"local_users"}` because
  their parse+render path currently leaves user blocks in
  `raw_sections` as Tier-3 passthrough.
- `CodecInfo.unsupported_rename_categories` exposes the list via
  `GET /api/v1/migration/adapters`; UI caches it alongside the
  existing adapter metadata.
- Rename modal's local-users pane now shows an amber banner
  up-front when the active target is in the declaring set.
  Warns operators that rename overrides apply to the canonical
  tree but won't reach rendered output.  Kills the
  ghost-success bug where `job.local_user_renames` populates but
  the rendered config has no user stanzas.
- Rename-open button gate broadened (was ports-only): now shows
  when ANY pane has content (port renames/warnings, source_vlans,
  source_local_users).  Pre-P2C4 gap — becomes visible once the
  VLAN/users panes started carrying non-port-dependent content.
- Deferred: **Option A** — full parser+render wiring for
  local_users on OPNsense + FortiGate.  Tracked for the
  "certified-tier Tier-2 parity" sweep; remove the codec
  declarations when it ships.
- 2 new integration tests + 2 new e2e tests.

### Fixed (post-P2C4 rename-modal UX polish + OPNsense probe support)

- **Target-profile dropdowns scoped to ports pane.**  The vendor /
  model / module selects in the modal toolbar + the fit-check
  banner drive ports-pane-specific behaviour only.  Previously
  visible on all panes, misleading operators into thinking they
  needed to pick a profile before renaming VLANs or users.  Now
  hidden when the active rail category isn't `ports`.  New
  testid: `migrate-rename-target-profile-group`.
- **Collision blocks Apply across all panes.**  Pre-fix, ports-
  pane collisions disabled Apply but VLAN + local-user collisions
  only showed the ⛔ icon while letting Apply proceed (server
  would auto-merge).  Fixed for feature parity — any-pane
  collision now disables Apply so operators must explicitly
  resolve rather than silently ship a merged output.
- **Preview pane extended to VLAN + user renames.**  The client-
  side approximation (whole-word substitution) now covers all
  three categories' rename operations.  Drops still rely on the
  server-side re-render (Apply) since multi-line stanza removal
  isn't safe client-side.
- **ParamikoShellCollector.probe() implementation.**  OPNsense
  backups can now populate `detected_facts` — the paramiko_shell
  strategy finally has a probe override.  Handles the console
  menu opt-in; short-lived separate session with tighter idle +
  timeout bounds (~1.6s idle, 30s absolute).  Failure modes still
  never-fatal; family-base fallback unchanged.

### Added (P2C4 — local-users rename pane + three-category composition fix)

- Third per-pane override category after ports + VLANs.  New
  orchestrator `netconfig/migration/canonical/local_user_names.py`
  walks `CanonicalIntent.local_users` and applies a string → string
  (or string → None for drop) rewrite map.  Collision merge:
  highest `privilege_level` wins, first non-empty `role` wins,
  first `hashed_password` wins (hashes aren't composable).
- `run_plan_with_overrides` gains `local_user_rename_map`
  parameter.  `MigrationJob` gains `local_user_renames` +
  `local_user_drops` + `source_local_users` fields.  Capture
  transform now snapshots user names alongside VLAN IDs + hostname.
- New endpoint `POST /api/v1/migration/plan/local_users` follows
  the per-pane pattern — delegates to `run_plan_with_overrides`
  with only its category's map populated.
- **Latent /plan routing fix:** `/plan` previously only engaged
  the rename-aware pipeline when `port_rename_map` or
  `target_profile` was set.  A client posting `vlan_rename_map`
  (shipped P2C2) or `local_user_rename_map` WITHOUT also setting
  `port_rename_map` silently dropped the override.  Fixed:
  `/plan` now dispatches directly to `run_plan_with_overrides`
  whenever ANY override map is present and threads every category
  through.
- UI: left rail gains a "Local users" button + category pane
  rendered by new `_partials/local-user-rename-table.js`
  (structural copy of vlan-rename-table.js, string keys, free-text
  rewrite).  Every operator override is persisted to localStorage
  under the same `netconfig.rename-ack.v1:…` key as the other
  categories — additive schema, old payloads load unchanged.
- Apply flow: `local_user_rename_map` included in the POST body
  only when the operator actually touched a user row (gate-on-
  non-empty — same pattern as VLANs).
- 10 new testids under
  `tests/testid_reference.md` → "Left-rail category nav + VLAN pane"
  section now also covers local-users rows, override inputs, drop
  links, and the summary chip.
- 16 new unit tests (`tests/unit/migration/test_local_user_names.py`)
  + 16 new integration tests (`TestPlanLocalUsersEndpoint`,
  `TestPlanMultiCategoryRouting`, source-shape capture) + 9 new
  cross-mesh smoke cases + 6 new e2e tests
  (`TestRenameModalLocalUsersPane`).

### Added (P1C3 — pre-backup probe phase + layered-definition resolver wiring)

- New `ProbeConfig` block on `DeviceDefinition` (optional `command:` +
  `patterns:` regex map).  Empty defaults keep existing definitions
  working unchanged; only definitions that opt in by declaring a
  probe command participate.
- New pure-function parser at `netconfig/collectors/probe.py` with
  11 unit tests (`tests/unit/test_probe_parser.py`).  Handles
  multi-line output, missing captures, malformed regexes, auto-
  timestamps successful results.
- New `probe()` method on `BaseCollector` (no-op default) + concrete
  Netmiko implementation.  Short-lived separate session (30s probe
  timeout, 4x tighter than the main 120s config timeout).  Failures
  are non-fatal — log WARNING, return `{}`, proceed with family-base.
- Backup pipeline (`_process_one_device`) now threads a
  `DefinitionLoader` + device-profile store through the execution
  path: probe → resolve overlay (operator pins win over detected
  facts) → persist `detected_facts` on the linked profile → collect
  against the resolved definition.  Both interactive and scheduled
  backups get the same treatment.
- `app.state.definition_loader` exposed on the FastAPI app alongside
  the existing `app.state.definitions` dict (kept for endpoints that
  iterate type_keys).  New `get_definition_loader` dependency.

### Added (P2C3 — rename-modal left-rail category nav + VLAN pane + localStorage persistence)

- Rename modal body refactored from `table | preview` into
  `rail | table | preview`.  Left rail is a vertical category
  navigation with Ports and VLANs today; the rail is the extension
  point for future categories (local_users / SNMP / RADIUS under
  P2C4+).  Counts + badges on rail buttons show per-category row
  totals at a glance.
- New `_partials/vlan-rename-table.js` renders the VLAN pane —
  structural parallel to the existing ports table but simpler
  (integer IDs, no per-kind sections, no target-profile dropdown).
  Rows enumerate every VLAN declared in the source config; each row
  has an integer override input + drop/un-drop link.
- `MigrationJob` exposes `source_vlans: list[int]` and
  `source_hostname: str` populated by a capture transform that
  runs ahead of every user-override transform in
  `run_plan_with_overrides`.  The UI needs both — source_vlans
  drives the VLAN pane's row enumeration, source_hostname keys
  the localStorage persistence entry.
- localStorage ack persistence: overrides survive page reloads
  keyed on `(source_codec, target_codec, hostname)` under
  `netconfig.rename-ack.v1:…`.  Load on modal-open, save on every
  render-summary (universal choke point), clear on Reset-all.
  Surfaces an age hint on restore ("Restored prior overrides
  (N port, M VLAN) from 3m ago").
- ARCHITECTURE.md gains a "Per-pane overrides (Tier-3 rename
  modal)" section documenting the three-step recipe for adding a
  new category (orchestrator → pipeline wiring → UI rail + pane),
  the sentinel semantics, and the localStorage schema.
- 14 new testids documented in `tests/testid_reference.md` under
  a new "Left-rail category nav + VLAN pane" subsection.
- 7 new e2e tests (`TestRenameModalLeftRail`,
  `TestRenameModalLocalStoragePersistence`) + 5 new integration
  tests (`TestSourceShapeCapture`).

### Added (P2C2 — canonical VLAN-rename orchestrator + /plan/vlans endpoint)

- Cross-vendor VLAN-ID rewrite transform
  (`netconfig/migration/canonical/vlan_names.py`) — walks the
  canonical tree and rewrites every VLAN-referring field
  (`CanonicalVlan.id`, `access_vlan`, `trunk_allowed_vlans`,
  `trunk_native_vlan`, `voice_vlan`).  Drop semantics via `None`
  values; collision merge (union of port lists, concat of SVI
  addresses) when multiple source IDs map to the same target.
- `POST /api/v1/migration/plan/vlans` per-pane endpoint accepts
  only the VLAN override map; delegates to `run_plan_with_overrides`
  with `port_rename_map=None`.
- `run_plan_with_overrides` extended with `vlan_rename_map`
  parameter.  VLAN transform runs AFTER port rename so port-name
  rewrites don't race with VLAN-ID changes.
- Cross-mesh smoke tests
  (`tests/unit/migration/test_cross_mesh_overrides.py`) parametrised
  over every `(source, target)` capable pair; new `cross_mesh`
  pytest marker with documented 30s aggregate-runtime budget.

### Added (P2C1 — run_plan_with_overrides engine + /plan/ports per-pane endpoint)

- New `run_plan_with_overrides` in `migration_pipeline.py` — the
  shared engine for every per-pane override surface.  Grows via
  optional category-map parameters; existing `run_plan` +
  `run_plan_with_rename` signatures stay frozen per CLAUDE.md's
  pipeline-signatures invariant.
- Sentinel semantics standardised across categories:
  `None` → don't engage, `{}` → engage with auto-heuristic only,
  `{src: tgt}` → engage with explicit overrides.
- `POST /api/v1/migration/plan/ports` per-pane endpoint — first
  instance of the per-pane pattern; dispatches to
  `run_plan_with_overrides` with only `port_rename_map`
  populated.

### Added (Tier 3 port-rename modal — interactive cross-vendor interface-name mapping in the /migrate UI)

- Draggable, non-blocking modal on the Migrate results view that
  exposes the Tiers 1+2 port-name translator to the operator.  The
  cross-vendor rename that used to happen silently (or fail to
  happen at all — the original complaint was Cisco ``GigabitEthernet1/0/24``
  leaking into Aruba output) is now:
    * **Auditable** — a mapping table shows every source name, the
      codec's auto-computed target, and warnings for untranslatable
      cases (breakout ports, loopbacks without target equivalents,
      uplink modules without operator input, etc.)
    * **Editable** — per-row override dropdown (profile-driven when
      a target profile is selected) or free-form input; user's
      choice wins over the auto-heuristic.
    * **Validated** — collision detection disables the Apply button
      when two sources map to the same target; warnings count shown
      in the header badge.

- Modal features:
    * Draggable (grab the ⋮⋮ grip header); non-blocking — user
      can drag aside to consult the rendered output behind it.
    * 2-pane layout: mapping table on the left (grouped by kind —
      physical / lag / svi / loopback / tunnel / breakout /
      hw_aggregate / virtual / unknown), client-side live preview
      on the right.
    * Sections collapsible; first-non-empty + any section with
      warnings/collisions auto-opens.
    * Target-profile selector in the toolbar: picking a profile
      swaps free-form inputs for dropdowns listing only ports the
      target hardware actually has; falls back to free-form when
      none selected.
    * Collision icons (⛔) with tooltips naming the colliding
      sources; warning icons (⚠) with the orchestrator's advisory
      text as tooltips.
    * "Reset all" clears user overrides; Apply POSTs to ``/plan``
      with the updated rename_map and refreshes the main output
      pane.

- The ``/migrate`` form now always sends ``port_rename_map: {}`` to
  opt into the rename-aware pipeline.  This means cross-vendor
  translations no longer leak source-vendor port names into the
  target output by default — the original Tier 3 complaint is fixed
  end-to-end.

- New e2e tests (7):
  ``tests/e2e/test_migrate_rename_modal.py`` — visibility gating,
  modal open/close, section rendering, override apply end-to-end,
  collision detection disables Apply, loopback warning row styling.

- Docs: ``translator-plans.txt`` gains a "PORT-NAME TRANSLATION
  (Tiers 1+2+3) — SHIPPED + DEFERRED WORK" section tracking the
  deferred save-as-profile, 3-pane layout, hardware fit-check,
  rename-operation diff, and target-profile expansion.
  ``HUMAN_TESTING.md`` gains a per-feature manual-verification
  checklist for the modal.

### Added (Tier 3 port-rename backend: target profiles + rename-aware /plan)

See commit ``b5cb5ca`` for the backend foundation that the frontend
consumes.

### Added (FortiGate CLI promoted to `certified` — 5th codec to reach the bar + real RADIUS round-trip bug fixed)

- User-contributed real ``show full-configuration`` from a physical
  **FortiGate 100E** running **FortiOS 7.2.13** (build 1762),
  captured via NetConfig's backup layer and sanitised per CLAUDE.md
  hard rule.  ~35K lines — 34 interfaces, 5 VLANs, 2 LAGs, 6 DHCP
  servers, 3 admins, 1 RADIUS server, 1 SNMP community, full
  firewall policy table + VIPs + SDWAN + SSL-VPN.  First physical-
  appliance FortiGate capture in the corpus (existing 2 from
  KevinGuenay were a VM hub + 70G branch, both on 7.6.6); first
  FortiOS 7.2.x capture.
- ``user_contrib_fg100e_fos7213.conf`` — sanitisation inventory
  (per CLAUDE.md "never commit real credential hashes" rule):
  - 48 ``ENC <base64>`` encrypted FortiGate secrets (admin
    passwords, RADIUS secret, FortiGuard proxy password, NTP
    key, DHCP option passwords, TACACS passwd1/2/3, etc.)
    replaced with ``ENC fakeEncodedSecret...`` markers
  - 14 ``-----BEGIN (ENCRYPTED) PRIVATE KEY-----`` /
    ``-----END`` blocks stripped with ``REMOVED_FIXTURE_SANITISATION``
    placeholder (public certificate chains retained for grammar)
  - 5 SSH public keys (``ssh-rsa AAAA...``) replaced with
    ``AAAAfakeSSHPublicKey...`` markers
  - 1 Firebase/APNs registration ID (``set reg-id "dxurAYJ..."``)
    sanitised
  - Real WAN IP ``[redacted-WAN-IP]`` (6 occurrences in address
    objects + VIP ``set extip`` entries) replaced with RFC 5737
    TEST-NET-3 ``203.0.113.217``
  - Real email ``[redacted-email]`` (2 occurrences in admin
    contact fields) replaced with ``netadmin@example.test``
  - All other real data retained — RFC1918 addressing, hostname
    ``fortihome``, alias ``FortiGate-100E``, interface descriptions,
    firewall policies with internal IPs, DHCP reservations,
    SD-WAN SLAs, SSL-VPN portal config.
- **Real codec bug surfaced + fixed in the same commit:** FortiOS
  uses ``set radius-port 0`` as the idiom for "use the default port
  1812" — real FortiOS exports (including the FG100E capture)
  emit this literally.  Our parser stored the 0 faithfully in
  ``CanonicalRADIUSServer.auth_port``, but the renderer had an
  early-out that omitted ``radius-port`` when ``auth_port == 1812``
  (mirroring FortiOS's own default-omission pattern).  Round-trip
  drift: first parse gave auth_port=0, render emitted nothing,
  re-parse defaulted to 1812.  Fix canonicalises ``radius-port 0``
  to 1812 at parse time in ``_apply_user_radius`` — canonical
  stores the *effective* value, not the literal 0.  Regression
  test
  ``TestRoundTrip::test_radius_port_zero_canonicalised_to_default``
  in ``tests/unit/migration/test_fortigate_cli.py`` pins the fix.
- ``certainty`` ClassVar bumped from ``best_effort`` to
  ``certified`` in
  ``netconfig/migration/codecs/fortigate_cli/codec.py``; matching
  test updated in
  ``tests/unit/migration/test_fortigate_cli.py::TestR3Fields::test_certainty``
  with comment citing the promotion evidence.
- ``fortigate_cli`` is the **5th codec to reach ``certified``**
  (after ``mikrotik_routeros``, ``aruba_aoss``,
  ``cisco_iosxe_cli``, ``opnsense``).  Only ``cisco_iosxe``
  (NETCONF OpenConfig) remains at ``best_effort``.
- Docs: ``tests/fixtures/real/NOTICE.md`` (provenance +
  sanitisation inventory), ``tests/fixtures/real/RESULTS.md``
  (per-codec section + summary total from 25 → 26 fixtures),
  ``README.md`` cert table.
- **677 migration tests passing** (+4 from the OPNsense commit),
  zero regressions.

### Added (OPNsense promoted to `certified` — 4th codec to reach the bar + real render bug fixed)

- User-contributed real ``config.xml`` from a deployed OPNsense
  instance ("supergate"), captured via NetConfig's own backup layer
  (SSH + ``cat /conf/config.xml``).  Sanitised per CLAUDE.md hard
  rule — 2 bcrypt ``<password>`` hashes replaced with
  ``$2y$11$fakeBcrypt...`` markers; API keys and the QFeeds
  ``tip_...`` token replaced with synthetic placeholders; 2
  self-signed-cert private-key ``<prv>`` blobs stripped (public
  ``<crt>`` retained for grammar coverage); the real domain
  (``[redacted-domain]``) replaced with ``example.test`` across 22
  occurrences; 13 real MAC addresses sanitised with OUI-preserving
  last-3-octet anonymisation; SSH-capture artifacts (``cat
  /conf/config.xml`` prefix and trailing shell prompt) stripped.
- ``user_contrib_supergate_opn25.xml`` — 2,302 lines, 8 interfaces
  (wan/lan/opt1-5/loopback with USERVLAN/MGMTVLAN/SERVERVLAN/
  CLUSTERVLAN/IOTVLAN descriptions), 5 VLANs with ``<tag>`` +
  ``<descr>``, 2 local users w/ bcrypt hashes, extensive per-zone
  DHCP static MAC reservations (~20/zone with operational
  commentary), Unbound DNS with local overrides, IPsec, WireGuard,
  SNMP, NTP.  The first genuinely-real-deployment OPNsense fixture
  (previous 3 were all from ``opnsense/core`` upstream).
- **Real codec bug surfaced + fixed in the same commit:** the
  render path silently dropped every ``CanonicalVlan`` entry.  The
  parser correctly read ``<vlans><vlan><tag/>`` + ``<descr/>`` into
  ``intent.vlans``, but ``_render_canonical`` had no inverse block
  — so a ``parse → render → parse`` cycle on the supergate capture
  collapsed 5 VLANs down to 0.  The three upstream
  ``opnsense/core`` fixtures didn't exercise the ``<vlans>`` block
  at all, so this bug slept until real-deployment contact.  Fix:
  added a ``<vlans>`` render block in
  ``netconfig/migration/codecs/opnsense/codec.py`` that emits
  ``<tag>`` + ``<descr>`` per VLAN (round-trip-symmetric with what
  the parser reads).  Regression test
  ``TestRoundTrip::test_roundtrip_preserves_vlans`` in
  ``tests/unit/migration/test_opnsense.py`` pins the fix — the
  test constructs a 3-VLAN input, parses/renders/re-parses, and
  asserts the VLAN ids and names survive.
- ``certainty`` ClassVar bumped from ``best_effort`` to
  ``certified`` in
  ``netconfig/migration/codecs/opnsense/codec.py``; matching
  ``test_certainty_is_certified`` added in
  ``tests/unit/migration/test_opnsense.py`` with comment citing the
  promotion evidence.
- ``opnsense`` is the **4th codec to reach ``certified``** (after
  ``mikrotik_routeros``, ``aruba_aoss``, ``cisco_iosxe_cli``).
- Docs: ``tests/fixtures/real/NOTICE.md`` (provenance for the new
  file + sanitisation inventory), ``tests/fixtures/real/RESULTS.md``
  (per-codec table + summary total from 24 → 25 fixtures),
  ``README.md`` cert table.
- **673 migration tests passing** (+7 from the last cert commit),
  zero regressions.

### Added (Cisco IOS-XE CLI cert strengthened with physical Cat 9300-24UX real capture)

- User-contributed real ``show running-config`` from a physical
  **Cisco Catalyst 9300-24UX** running **IOS-XE 17.12**, captured via
  NetConfig's own backup layer against the contributor's live home-
  lab switch and sanitised per CLAUDE.md hard rules.  Fills the
  physical-switch coverage gap that the earlier 3 BSD-3 racc
  captures didn't address — they were all **virtual routers**
  (CSR1000v / Cat8000V) and validated IOS-XE routing grammar but not
  physical-switch switching grammar.
- ``user_contrib_cat9300_iosxe1712.txt`` — 491 lines, 47 interfaces,
  6 VLANs, 3 LACP EtherChannels (the Fortigate uplink, NAS LAG, and
  Proxmox-blade LAG), 2 local users, 1 default-gateway static route.
  Exercises the whole physical-switch grammar surface: ``switch 1
  provision c9300-24ux``, ``TenGigabitEthernet1/0/N`` /
  ``FortyGigabitEthernet1/1/N`` / ``TwentyFiveGigE1/1/N`` /
  ``AppGigabitEthernet1/0/1`` port families, ``switchport mode
  trunk/access`` + ``switchport trunk allowed vlan <list>`` +
  ``switchport trunk native vlan``, ``channel-group N mode active``
  binding into ``interface Port-channel N``, ``interface Vlan N``
  SVIs, ``vrf forwarding Mgmt-vrf`` on the management port, the
  full Cat9k ``class-map system-cpp-police-*`` + ``policy-map
  system-cpp-policy`` CPP (control-plane policer) grammar,
  ``spanning-tree mode rapid-pvst``, 28 × ``privilege exec level 5
  show X`` delegation entries, multiple ``line vty`` ranges
  (``0 4`` / ``5 29`` / ``30 31``).
- Sanitisation: the two ``username X secret 9 $9$...`` hashes were
  replaced with synthetic-marked ``$9$fakeSalt...$fakeHash...`` per
  CLAUDE.md "never commit real hashes from non-public devices" rule;
  the ``by <windows-username>`` annotation in the
  ``Last configuration change`` timestamp was updated to
  ``by netadmin``.  All other real data retained — RFC1918
  addressing, VLAN IDs, infrastructure-describing interface
  descriptions (``TRUNK - FORTIGATE`` / ``pvenas 2x 10gbe trunk`` /
  ``pveblade lacp``), and the self-signed device certificate chain.
  Same convention as the MikroTik ``user_contrib_crs310_ros7.rsc``
  precedent.
- Secondary fixture added: ``cml_saumur_iosxe1712_pvrstp.txt`` —
  BSD-3-Clause capture extracted from
  [CiscoDevNet/cml-community](https://github.com/CiscoDevNet/cml-community)
  `lab-topologies/ccna/Domain_2/2.5-interpret_stp/saumur_PVRSTP_solution.yaml`
  (the ``saumur`` node's ``configuration:`` block).  147 lines, IOS-
  XE 17.12 on a virtual ``ioll2-xe`` image (IOU port notation
  ``Ethernet0/N`` rather than physical ``Gi1/0/N``).  Complements
  the Cat 9300 capture with PVRST+ cost-tuning grammar the Cat 9300
  doesn't exercise: ``spanning-tree pathcost method long``,
  ``spanning-tree vlan 1-4094 priority 4096``, ``spanning-tree
  link-type point-to-point``, ``spanning-tree cost 2000000``,
  ``vtp version 1``, ``vlan internal allocation policy ascending``.
- **Zero codec bugs surfaced.**  Both fixtures parse cleanly on
  first contact and produce populated canonical trees.
- The cert promotion from the previous commit is now justified on
  **both** router grammar (racc corpus) and physical-switch grammar
  (Cat 9300 capture) rather than router grammar alone.  Test
  assertion comment updated in
  ``tests/unit/migration/test_cisco_iosxe_cli.py`` to reflect
  strengthened coverage.
- Docs: ``tests/fixtures/real/NOTICE.md`` (provenance for both new
  files), ``tests/fixtures/real/RESULTS.md`` (per-codec table +
  summary total from 22 → 24 fixtures; cisco_iosxe_cli row now
  shows 4 LTS OS versions and 11 fixtures), ``README.md`` cert
  table.
- **666 migration tests passing**, zero regressions.

### Added (Cisco IOS-XE CLI promoted to `certified` — 3rd codec to reach the bar)

- Three BSD-3-Clause real captures ingested from
  [nickrusso42518/racc](https://github.com/nickrusso42518/racc) —
  authored by a Cisco DevNet trainer, checked in as the playbook's
  own sample output directory, so provenance is unambiguous:
  - ``racc_csr1000v_iosxe169_bgp_ospf.txt`` — CSR1000v on
    **IOS-XE 16.9 LTS**, 280 lines.  BGP AS 65001 with ``vpnv4`` +
    ``rtfilter`` address-families, OSPF, QoS ``class-map`` +
    ``policy-map``, ``logging host``, RESTCONF + NETCONF-YANG.
  - ``racc_csr1_iosxe173_umbrella_sig.txt`` — CSR1000v on
    **IOS-XE 17.3 LTS**, 398 lines.  Cisco Umbrella SIG tunnel
    deployment: IKEv2 proposal/policy/profile + IPsec profile +
    ``tunnel protection ipsec profile`` on Tunnel100, 22 static
    routes (anycast SIG targets), EIGRP CITYNET, OSPF, SSH
    ``pubkey-chain``, guestshell app-hosting, NETCONF-YANG
    ``candidate-datastore``.
  - ``racc_cat8000v_iosxe179_netconf.txt`` — Cat8000V on
    **IOS-XE 17.9 LTS**, 343 lines.  ``ip nat inside source list
    ... overload`` (PAT), ``telemetry ietf subscription`` (YANG-
    push periodic update-policy over grpc-tcp), type-9 ``$9$...``
    hash, RESTCONF + NETCONF-YANG, app-hosting guestshell.
- **Zero codec bugs surfaced.**  All three fixtures parse cleanly
  on first contact and produce populated canonical trees —
  evidence the grammar coverage from the Batfish / NTC corpus
  already generalised to real deployed CSR1000v / Cat8000V
  configs.  Large cert chains, IKEv2 profiles, guestshell stanzas,
  telemetry subscriptions, PKI trustpoints all fell through to
  "parse-and-ignore" without tripping the parser — exactly as
  designed.
- Cert-bar for ``parse_only`` codecs: ≥3 real captures from ≥2 OS
  versions that parse cleanly and produce populated canonical
  trees (round-trip is N/A for parse-only).  The three racc
  fixtures give us 3 distinct LTS OS versions — meets the bar
  decisively.
- ``certainty`` ClassVar bumped from ``best_effort`` to
  ``certified`` in
  ``netconfig/migration/codecs/cisco_iosxe_cli/codec.py``;
  matching test renamed/updated in
  ``tests/unit/migration/test_cisco_iosxe_cli.py``
  (``test_certainty_is_certified``).
- ``cisco_iosxe_cli`` is the **3rd codec to reach ``certified``**
  (after ``mikrotik_routeros`` and ``aruba_aoss``).
- Docs: ``tests/fixtures/real/NOTICE.md`` (provenance for 3 new
  files), ``tests/fixtures/real/RESULTS.md`` (per-codec table +
  summary total from 19 → 22 fixtures), ``README.md`` cert table.
- **664 migration tests passing**, zero regressions.

### Added (Aruba AOS-S promoted to `certified` — 2nd codec to reach the bar)

- Three sanitised real captures ingested from HPE Community forum
  threads, collectively spanning **3 distinct OS versions** and
  **2 switch families**:
  - ``hpe_community_2930f_wc1607_intervlan.cfg`` — 2930F JL260A on
    **WC.16.07.0002**.  12 VLANs with per-VLAN SVIs, ``ip
    helper-address`` (DHCP relay) at scale, ``ip forward-protocol udp``
    for DNS/NTP helper forwarding, ``primary-vlan``, 4 static routes
    including ``ip default-gateway``.
  - ``hpe_community_2920_wb1608_dhcp_snooping.cfg`` — 2920 J9729A on
    **WB.16.08.0001** (different WB branch + different switch family
    to the other two).  Exercises ``dhcp-snooping`` with 13
    authorized-servers + VLAN scope + trust ports, ``ntp unicast``
    with ``iburst``, ``web-management ssl``, ``ip authorized-managers``,
    ``snmp-server host ... trap-level critical``.
  - ``hpe_community_2930f_wc1610_dhcp_server.cfg`` — 2930F JL258A on
    **WC.16.10.0005**.  Real AOS-S built-in ``dhcp-server pool``
    grammar (3 pools × ``default-router``/``dns-server``/``network``/
    ``range``), per-VLAN ``dhcp-server`` enable flag,
    ``allow-unsupported-transceiver``.
- **Zero codec bugs surfaced.**  All four fixtures (3 new + 1
  pre-existing rendered template) round-trip clean on first pass,
  parse deterministically, produce matching canonical trees — the
  harness invariants held without a single fix.
- ``certainty`` ClassVar bumped from ``best_effort`` to ``certified``
  in ``netconfig/migration/codecs/aruba_aoss/codec.py``; matching
  test updated in ``tests/unit/migration/test_aruba_aoss.py`` with
  a comment citing the promotion evidence (pattern mirrors the
  MikroTik certification commit).
- ``aruba_aoss`` is the **2nd codec to reach ``certified``** (after
  ``mikrotik_routeros``).  Cert bar: ≥3 real captures from ≥2 OS
  versions, all round-tripping clean.
- Docs: ``tests/fixtures/real/NOTICE.md`` (provenance for all 3 new
  files), ``tests/fixtures/real/RESULTS.md`` (per-codec table + summary
  total from 16 → 19 fixtures), ``README.md`` cert table.
- **658 migration tests passing**, zero regressions.

### Fixed (Bug 1: Cisco IOS-XE SVI dropped silently into Aruba render)

- **Symptom** (found via real-config dogfooding): feeding a Cisco
  9300 config containing ``interface Vlan11 / ip address
  192.168.11.252 255.255.255.0`` through the
  ``cisco_iosxe_cli -> aruba_aoss`` pipeline produced an Aruba render
  with **no ``vlan 11`` stanza at all** — the SVI's IP address
  silently vanished.
- **Root cause**: the IOS-XE CLI parser only created ``CanonicalVlan``
  records from explicit top-level ``vlan N / name X`` stanzas, not
  from ``interface Vlan<N>`` SVIs.  Aruba's renderer unconditionally
  skips interfaces named ``Vlan*`` (expecting the VLAN stanza to
  absorb the SVI's IP), so with no VLAN record the SVI + its L3
  data fell through the gap.
- **Fix**: new ``_synthesize_vlans_from_svis()`` post-pass in the
  Cisco IOS-XE CLI parser derives a ``CanonicalVlan(id=N)`` from
  each ``interface Vlan<N>`` stanza, attaches the SVI's IPv4
  addresses, and merges with any existing top-level ``vlan N``
  record (explicit ``name`` stays authoritative; SVI description
  falls back as the name when no stanza is present).
- **New cross-codec invariant** in the full-mesh matrix:
  ``test_every_source_ip_appears_in_rendered_output`` — every IP
  in the parsed-source tree MUST appear as a literal substring in
  the target codec's rendered output.  Substring-based so it
  doesn't depend on target parsers accepting foreign interface
  names (AOS-S can't re-parse ``GigabitEthernet0/0/0`` but the IP
  still reaches the rendered text, which is what matters for
  silent-drop detection).  This guard would have caught Bug 1 on
  day one.
- **8 new unit tests** (``TestSVIVlanSynthesis``) + 25 parametrized
  invariant runs.  **885 passing**, zero regressions.

### Added (Tier 2 — SNMP parse/render across all 5 real codecs)

- First Tier 2 feature wired end-to-end through every real codec:
  **SNMP** (community, location, contact, trap_hosts).  Previously
  the ``CanonicalSNMP`` model existed but no codec consumed or
  produced it.
- **Per-codec grammar coverage:**
  - ``cisco_iosxe_cli``: ``snmp-server community/location/contact/host``
  - ``opnsense``: ``<snmpd>`` plugin element (``<rocommunity>``,
    ``<syslocation>``, ``<syscontact>``, ``<traphost>``)
  - ``mikrotik_routeros``: ``/snmp set`` (sysinfo) + ``/snmp community
    set`` (community strings)
  - ``aruba_aoss``: ``snmp-server community/location/contact/host``
  - ``fortigate_cli``: ``config system snmp sysinfo`` + ``config
    system snmp community`` with nested ``config hosts`` sub-table
- Each codec's capability matrix now declares ``/snmp/community``,
  ``/snmp/location``, ``/snmp/contact``, ``/snmp/trap-host``.
- ``_walk_canonical`` emits SNMP xpaths only when populated, so
  codecs that don't carry SNMP produce no false xpath occurrences.
- 24 new unit tests in ``tests/unit/migration/test_tier2_snmp.py``:
  per-codec parse/render/round-trip + parametrized universal-render
  + universal-roundtrip across every real codec.  **852 passing.**
- Paves the way for the remaining Tier 2 features (local_users,
  LAGs, RADIUS servers, DHCP server pools) — identical shape of
  work, just different grammars.

### Added (FortiGate CLI codec — 5th real vendor, recursive grammar)

- **``FortiGateCLICodec``** in
  ``netconfig/migration/codecs/fortigate_cli/`` — parses and renders
  FortiOS 7.x CLI (``config/edit/set/next/end`` 5-keyword grammar).
  Recursive block model handles arbitrary nesting including nested
  ``config`` inside ``config`` (NTP ntpserver sub-table).
- **Parser scope:** ``system global`` (hostname), ``system dns``
  (primary/secondary), ``system ntp`` (ntpserver sub-table),
  ``system interface`` (physical + VLAN sub-interfaces via ``set
  type vlan`` + ``set vlanid`` + parent ``set interface``),
  ``router static`` (dst + gateway + device).
- **Structural handling:** quoted values with spaces, multi-token
  set values (``set allowaccess ping https ssh``), integer ``edit``
  IDs for routes + quoted ``edit`` IDs for interfaces, dotted-
  decimal mask form for IPs.
- **Capability matrix:** firewall policies + NAT rules marked
  unsupported (Tier 3); alias 25-char truncation marked lossy.
- **Auto-detection probe:** ``#config-version=`` banner (98%),
  5-keyword grammar markers (75-92%).
- **Vendor YAML** at ``netconfig/migration/vendors/fortigate.yaml``
  declaring ``[firewall, router]``.

### Added (full-mesh cross-codec matrix test)

- **``tests/unit/migration/test_cross_codec_matrix.py``** — parametrized
  pytest that auto-enumerates every ``(source, target)`` codec pair,
  filters to those sharing a ``DeviceClass``, runs each source's
  ``sample_input`` through ``run_plan``, and asserts the job
  completes.  Answers the user's question: yes, we now have
  full-mesh cross-vendor testing built into every codec addition.
  26 real pairs covered today; grows automatically with each new
  codec.
- **Latent bugs exposed + fixed on first matrix run:**
  - ``MockCodec.render()`` couldn't JSON-serialise ``CanonicalIntent``
    — now detects the type and uses pydantic's ``model_dump()``.
  - ``CiscoIOSXECodec.parse()`` still returned the legacy nested
    dict shape (never migrated during the canonical bridge work).
    Now returns ``CanonicalIntent`` like every other codec; 8 test
    assertions updated to use the canonical attribute access.
    Capability matrix updated to declare canonical xpaths.

### Added (Aruba AOS-S codec — 4th real vendor, VLAN-centric)

- **``ArubaAOSSCodec``** in ``netconfig/migration/codecs/aruba_aoss/``
  — parses and renders Aruba AOS-S (ProCurve / ArubaOS-Switch 16.x)
  ``show running-config`` text.  Architecturally the first codec
  where VLAN port membership lives naturally on the VLAN object
  (``vlan 10`` → ``untagged 1-24`` / ``tagged 25-26``), validating
  the canonical VLAN-centric design decision.
- **Parser scope (Tier 1):** hostname, VLANs (id, name, untagged/
  tagged port lists, SVI IPs), interfaces (name, enable/disable,
  routing keyword, per-port IP), static routes (``ip route`` +
  ``ip default-gateway``), SNMP community, DNS / NTP servers.
- **Structural quirks handled:**
  - ``;`` as comment character (not ``!``)
  - Stanza delimiter is ``exit`` or an un-indented line
  - Port names: bare numerics + alpha-numeric (``1``, ``A1``, ``Trk1``)
  - Port-range expansion (``1-24``) + compression on render
  - IP accepts both ``A.B.C.D/N`` and ``A.B.C.D M.M.M.M``
  - Default gateway ↔ ``0.0.0.0/0`` static route round-trip
  - ``no untagged 1-24`` port-list subtraction
- **Vendor YAML** at ``netconfig/migration/vendors/aruba_aoss.yaml``
  declaring ``[switch, router]``.
- **OPNsense renderer hardened**: bare-numeric interface names
  (legal on Aruba, invalid as XML element tags) now sanitise via
  ``_zone_tag_for()`` — ``1`` becomes ``if_1``, etc.  Closes a
  cross-vendor regression exposed by the Aruba→OPNsense pipeline.
- **Auto-detection probe** with three confidence tiers: ProCurve
  banner (98%), combined structural markers + ``;`` comment (95%),
  individual structural hits (70-88%).
- 49 new unit tests.  **760 passing, zero regressions.**

### Changed (auto-discover codec packages — zero-bookkeeping vendor add)

- **``netconfig/migration/__init__.py``** now auto-discovers every
  codec sub-package under ``netconfig/migration/codecs/`` using
  ``pkgutil.iter_modules``.  Each package's module-level
  ``@register`` decorator fires on import, populating the registry.
- Adding a new vendor is now a true drop-in: create the codec
  package directory + drop a vendor YAML — the translator picks
  both up at next import with **zero edits to any shared file**.
  (The ``INPUT_FORMATS`` frozenset and per-codec probe signatures
  remain in the codec's own module, so they're also vendor-local.)
- Broken codec packages log the failure and are skipped —
  robustness test pins that behaviour.
- 2 new unit tests: auto-discovery finds every expected codec;
  importing the package is idempotent across reloads.  **710 passing.**

### Changed (UI metadata migration — close the R5 client-side leak)

- **CodecBase gains three UI-metadata ClassVars**: ``description``,
  ``sample_input``, ``output_extension``.  Each codec class is now
  the single source of truth for its own presentation strings.
- **``CodecInfo`` pydantic model grew three fields** (same names)
  and ``GET /api/v1/migration/adapters`` surfaces them so the client
  can render format hints / load samples / pick download extensions
  without any vendor-specific JS.
- **`migrate.html` lost its 130-line ``FORMAT_CATALOGUE`` dict** and
  all six call sites that read from it.  New ``adapterEntry()`` and
  ``compatibleExtensions()`` helpers read server-provided metadata
  off the ``adapters`` array.  ``guessExtension`` and
  ``downloadMigrateOutput`` likewise delegate to
  ``target.output_extension``.
- **Adding a new codec no longer requires editing the template** —
  the codec class ships its own description + sample + download
  extension, which the UI picks up automatically.
- Every real codec (cisco_iosxe, cisco_iosxe_cli, opnsense,
  mikrotik_routeros, mock) now declares all three metadata fields.
- 3 new integration-test assertions confirm the surface
  (``test_ui_metadata_fields_surface``,
  ``test_real_codecs_have_sample_input``,
  ``test_real_codecs_have_output_extension``).  **708 passing.**

### Added (R5 — auto-detection of source codec from raw bytes)

- **`CodecBase.probe(raw_prefix)`** classmethod — new auto-detection
  hook.  Each codec overrides it to return a ``(confidence, reason)``
  tuple if the first ~500 bytes match its format, or ``None`` if it
  has no opinion.  Default base implementation returns ``None`` so
  codecs without a probe still load cleanly.
- **Per-codec probe signatures** on all four real codecs:
  - ``opnsense`` — matches ``<opnsense>`` root (98% confidence)
  - ``cisco_iosxe`` — matches OpenConfig YANG namespace (95%),
    ``<rpc-reply>`` envelope (70%), OpenConfig-shaped XML (75%)
  - ``cisco_iosxe_cli`` — matches ``Building configuration…`` banner
    (98%), strong CLI markers like ``interface Giga`` + ``ip address
    X.X.X.X Y.Y.Y.Y`` + ``no shutdown`` (90% for ≥2 hits), weaker
    fallbacks
  - ``mikrotik_routeros`` — matches ``# ... by RouterOS`` banner
    (98%), multiple ``/section`` headers + find-default-name idiom
    (97%), individual sections / idioms (80-95%)
  - ``mock`` — weak JSON-shape detection (40-55%)
- **`netconfig/services/migration_detect.py`** — pure-function
  detection service.  ``detect_codec(raw)`` walks every registered
  codec's ``.probe()``, filters by ``min_confidence``, and returns a
  ranked list.  ``best_codec(raw)`` is a convenience wrapper that
  returns only the top candidate (default strict threshold 50).
- **`POST /api/v1/migration/detect`** — new API endpoint.  Body
  accepts ``raw_text`` OR ``source_filename`` (same contract as
  ``/plan``) plus optional ``min_confidence``.  Returns
  ``list[DetectCandidate]`` sorted by descending confidence.
- **/migrate UI auto-detection** — debounced 350ms on textarea
  input, fires on stored-config selection, and on source-codec
  change.  Banner shows "Detected: \<vendor\> (\<confidence\>%)"
  with a "Use this source" button.  When the user has already
  picked the detected codec the banner goes green (confirmation).
- **MikroTik sample + format hint** — client-side
  ``FORMAT_CATALOGUE`` now has a ``cli-mikrotik`` entry (label,
  desc, sample, ``exts=['rsc']``) so the "Load sample" button and
  stored-config compatibility warning work for MikroTik too.  The
  ``guessExtension`` function was refactored to read
  ``adapter.input_format`` from the /adapters response instead of
  hard-coding vendor names — partial closure of a known client-side
  vendor-metadata leak.  Full structural fix (moving all codec
  metadata out of JS and onto the codec class) is queued as a
  standalone UI-metadata-migration session.
- **46 new tests**: 37 unit tests (per-codec probe signatures +
  detection service + robustness) + 9 integration tests (endpoint
  contract, sorting, min-confidence filtering, both-fields 422,
  missing-file 404).  Total suite: 705 passing.
- **Testid additions**: ``migrate-detect-banner`` (with
  ``data-detected-codec`` and ``data-detected-confidence`` attrs),
  ``migrate-detect-use-btn``.

### Added (MikroTik RouterOS codec — third canonical-bridged vendor)

- **``MikroTikRouterOSCodec``** in
  ``netconfig/migration/codecs/mikrotik_routeros/`` — parses and renders
  RouterOS ``/export verbose`` text through ``CanonicalIntent``.  First
  third-party validation that the canonical dict is portable across
  structurally different formats (XML / indented IOS CLI / section-
  oriented RouterOS script).
- **Parser scope (Tier 1):** system identity (hostname), DNS + NTP
  servers, ethernet-port tweaks (``set [ find default-name=ether1 ]``),
  VLAN interfaces (``add name=vlanN vlan-id=N``), bridge interfaces,
  IPv4 addresses bound to interfaces (``/ip address add``), and static
  routes (``/ip route add``).  Handles RouterOS quirks: quoted
  values with spaces, ``\`` line continuation, ``#`` banner comments.
- **Renderer scope:** emits deterministic, section-ordered output.
  Ethernet ports render as default-name tweaks; VLANs, bridges, and
  other interfaces render as `add` lines.  Round-trip invariant holds
  for the canonical subset.
- **Vendor YAML** added at
  ``netconfig/migration/vendors/mikrotik_routeros.yaml`` declaring
  device classes ``[router, firewall]``.
- **Capability matrix** marks firewall/filter rules and NAT as
  unsupported (Tier 3 — informational only), interface type as lossy
  (inferred from name prefix).
- **Cross-vendor translation proven for 3 new pairs:** Cisco IOS-XE
  CLI → MikroTik; MikroTik → OpenConfig NETCONF XML; MikroTik →
  OPNsense config.xml.  Ecosystem now supports 4! = 24 vendor-pair
  combinations (up from 6 before this codec).
- **38 new unit tests** covering R3 fields, parse, parse-errors,
  render, round-trip, iter_xpaths, capabilities, cross-adapter
  pipeline integration, and registry.  Total suite: 659 tests passing.

### Added (canonical intent dict — cross-vendor translation bridge)

- **``CanonicalIntent``** pydantic model in
  ``netconfig/migration/canonical/intent.py`` — the shared tree shape
  every codec's ``parse()`` emits and ``render()`` consumes.  Defines
  Tier 1 (auto-translatable: hostname, interfaces, VLANs, static
  routes), Tier 2 (review-required: DHCP, SNMP, LAGs, users, RADIUS),
  and Tier 3 (informational-only: firewall, NAT, VPN stored as
  raw_sections for display, never auto-rendered).
- **VLAN-centric membership model**: VLANs carry their port lists
  (tagged/untagged), not the reverse — Aruba AOS-S and OPNsense work
  this way natively; Cisco's per-interface switchport is transposed
  on parse.
- **Cisco IOS-XE CLI codec refactored** to emit ``CanonicalIntent``:
  now parses hostname, VLANs (``vlan <id>`` / ``name`` stanzas),
  static routes (``ip route``), and switchport config
  (``switchport mode``, ``access vlan``, ``trunk allowed vlan``,
  ``trunk native vlan``) in addition to interfaces.
- **OPNsense codec refactored** to emit/consume ``CanonicalIntent``:
  new ``_render_canonical()`` method renders OPNsense config.xml from
  any canonical intent (including those parsed from Cisco CLI).
- **Cisco IOS-XE NETCONF codec** gains ``_render_canonical()`` to
  produce OpenConfig XML from any ``CanonicalIntent``.
- **Cross-vendor translation proven**: ``cisco_iosxe_cli`` (source) →
  ``opnsense`` (target) completes successfully through the pipeline.
  First time in the project's history that a stored backup config
  from one vendor renders as another vendor's config format.
- **740 tests pass** — zero regressions.  All existing tests updated
  to assert against canonical model attributes instead of raw dicts.

### Added (R3+R4: codec direction/certainty fields + first CLI codec)

- **R3: three new fields on ``CodecBase``:**
  - ``direction`` — ``"bidirectional"`` (default), ``"parse_only"``, or
    ``"render_only"``.  Parse-only codecs can only be SOURCE; the
    ``/migrate`` UI now filters them out of the target dropdown.
  - ``certainty`` — ``"certified"`` / ``"best_effort"`` /
    ``"experimental"``.  Surfaced on the API and in the source
    dropdown label so users know the trust level.
  - ``canonical_model`` — which CIM the tree targets (default
    ``"openconfig-lite"``).  Informational for now; becomes load-
    bearing when cross-CIM translation lands.
  All three fields exposed on ``CodecInfo`` via
  ``GET /api/v1/migration/adapters``.

- **R4: ``CiscoIOSXECLICodec``** — first ``parse_only`` codec, first
  multi-codec-per-vendor instance.  Parses ``show running-config``
  text — the format NetConfig's existing Netmiko backup collectors
  already capture.  Shares ``vendor_id=cisco_iosxe`` with the
  NETCONF codec; both produce the same tree shape so they're
  interchangeable as pipeline SOURCEs.
  - Direction: ``parse_only`` (render raises ``RenderError``).
  - Certainty: ``experimental`` (synthetic samples only).
  - Scope: interface stanzas — name, description, ``shutdown`` /
    ``no shutdown``, ``ip address <ip> <mask>`` with mask→prefix-
    length conversion.  Infers IANA ifType from the interface name
    prefix (``GigabitEthernet`` → ``ethernetCsmacd``, ``Loopback`` →
    ``softwareLoopback``, etc.).
  - Rejects XML/JSON input with a clear error pointing at the
    NETCONF codec.  Rejects non-contiguous subnet masks.
  - ``/migrate`` page: CLI codec appears in the SOURCE dropdown
    (with ``[experimental]`` badge) but NOT in the TARGET dropdown.
    Format hint says "Paste the output of show running-config."
    The "Load sample" button provides a working IOS CLI snippet.

- **Pipeline proof:** ``cisco_iosxe_cli`` (source) → ``cisco_iosxe``
  (target) completes successfully — the first time a stored backup
  config can be translated to OpenConfig XML through the UI.

- **Tests (+23):** ``tests/unit/migration/test_cisco_iosxe_cli.py``
  covers R3 field declarations, parse (minimal, fixture, shutdown,
  loopback /32, type inference), parse errors (empty, XML, JSON,
  non-contiguous mask), render-raises, tree-shape compatibility with
  the NETCONF codec's capability matrix, pipeline integration
  (CLI→NETCONF succeeds, CLI-as-target fails with parse-only error),
  and registry (two codecs for one vendor).

- Full suite: **740 passing** (was 717).

### Added (R2: declarative vendor YAML)

- **Vendor declarations** extracted to YAML files under
  ``netconfig/migration/vendors/``.  Three shipped: ``mock.yaml``,
  ``cisco_iosxe.yaml``, ``opnsense.yaml``.  Each declares ``id``,
  ``display_name``, ``device_classes``, ``default_timeout``, ``notes``.
  No Python code — adding a new vendor is a 30-second YAML-copy
  operation.
- **``VendorInfo``** pydantic model in ``netconfig.models.migration``.
- **``load_vendors()``** function in ``netconfig.migration.vendors``
  scans the directory at startup, validates against the model, skips
  corrupt files with a log.  Loaded into ``app.state.vendors``.
- **``CodecInfo``** now carries ``vendor_id`` and
  ``vendor_display_name`` so the UI can group codecs by vendor without
  a second request.  ``vendor_display_name`` is resolved from the
  loaded YAML at response time.
- **Codec ↔ vendor linkage test:** a dedicated unit test asserts that
  every shipped codec's ``vendor_id`` resolves to a loaded vendor — a
  build-time guard against orphaned references.
- **Tests (+17):** ``test_vendors.py`` (14 unit — built-in loading,
  model shape, error resilience, corrupt/missing/duplicate YAML,
  codec linkage guard) + 3 integration (API surfaces ``vendor_id``
  and ``vendor_display_name`` for each codec).
- Full suite: **717 passing** (was 700).

### Refactored (R1: rename adapter → codec + add vendor_id)

- **`AdapterBase` → `CodecBase`** — "codec" accurately describes the
  class's job: translate between a wire format and the canonical tree.
  All related types renamed: `AdapterInfo` → `CodecInfo`,
  `AdapterError` → `CodecError`, `MockAdapter` → `MockCodec`,
  `CiscoIOSXEAdapter` → `CiscoIOSXECodec`, `OPNsenseAdapter` →
  `OPNsenseCodec`, `get_adapter` → `get_codec`, `list_adapters` →
  `list_codecs`.
- **Directory:** `netconfig/migration/adapters/` →
  `netconfig/migration/codecs/`.  `adapter.py` → `codec.py`.
- **Test files:** `test_mock_adapter.py` → `test_mock_codec.py`,
  `test_cross_adapter_pipeline.py` → `test_cross_codec_pipeline.py`.
- **`CapabilityMatrix.vendor_id: str`** — new field, links the codec
  to a vendor YAML (R2).  Set on all 3 codecs.
- **JSON back-compat:** `CapabilityMatrix.adapter` stays as the JSON
  field name so API consumers don't break.
- 700 tests pass — zero regressions.

### Refactored (god-file cleanup — zero behaviour change)

Three files identified as god-files during a structural audit;
all three refactored with zero behaviour change (674 tests pass
before and after, same count).

- **`netconfig/main.py` (539 → 208 lines).**  All 12 UI route
  handlers (``/``, ``/jobs``, ``/schedules``, ``/configs``,
  ``/configs/{L}/vs/{R}``, ``/devices``, ``/definitions``,
  ``/migrate``, ``/docs``, ``/health``) extracted to a new
  ``netconfig/api/routes/ui.py`` (406 lines).  ``_format_interval``
  and the Jinja2 ``templates`` instance moved with them.
  ``create_app`` now only wires routers and configures the lifespan.

- **`netconfig/templates/base.html` (834 → 262 lines).**  Two
  self-contained JS widgets extracted to Jinja ``{% include %}``
  partials (no ``StaticFiles`` mount needed):
  - ``_partials/config-viewer.js`` (346 lines) — syntax highlighter,
    tokenizer, cross-span search.
  - ``_partials/job-progress.js`` (231 lines) — floating progress
    panel, localStorage persistence, CustomEvent dispatch.
  Toast + timestamp localiser + config downloader remain inline
  (~80 lines; not worth a separate file at that size).

- **``tests/e2e/test_backup_flow.py`` (805 lines, 13 classes)
  split into 6 focused files:**
  - ``test_navigation.py`` (60 lines) — nav smoke tests.
  - ``test_backup_form.py`` (129 lines) — dashboard structure +
    multi-device form + backup submission.
  - ``test_pages.py`` (72 lines) — definitions + configs pages.
  - ``test_config_viewer.py`` (178 lines) — syntax highlighting +
    cross-span search.
  - ``test_progress_panel.py`` (153 lines) — floating panel
    visibility, persistence, dismiss.
  - ``test_diff.py`` (226 lines) — diff API, UI, content, context
    folding.
  Shared helpers ``ensure_cisco_config`` and
  ``ensure_n_configs_of_type`` promoted from private functions in
  the old monolith to public utilities in ``tests/e2e/helpers.py``.
  Old ``test_backup_flow.py`` deleted.

- **Import fix:** ``tests/unit/test_schedule_models.py`` updated to
  import ``_format_interval`` from its new home in
  ``netconfig.api.routes.ui`` instead of ``netconfig.main``.

### Fixed + Added (translator `/migrate` UX after manual QA pass)

Five findings from a hands-on walk-through of the page — one real UX
bug, three workflow gaps, one display issue.

- **Fixed: banner severity out-of-sync with job outcome** (manual
  QA #10b).  Previously a parse-OK / render-failed job rendered the
  GREEN "validation OK" banner because validation ran fine before
  render blew up.  Now the banner's severity follows a strict
  priority: `job.error` present → block, `failed`/`partial` status →
  block, else `validation.severity`, else `info`.  Colour can no
  longer contradict the message.  Banner also carries a
  `data-severity` attribute now so tests can assert on it
  unambiguously.
- **Added: `AdapterBase.input_format`** (str, defaults to
  `"unknown"`).  Each adapter declares what its `parse()` accepts:
  - `cisco_iosxe` → `xml-netconf` (OpenConfig NETCONF payload)
  - `opnsense` → `xml-opnsense` (`config.xml`)
  - `mock` → `json-flat`
  - reserved: `xml-panos`, `cli-ios`, `cli-fortigate`, `cli-mikrotik`
  Catalogued in `netconfig.migration.adapters.base.INPUT_FORMATS`
  (frozenset).  `AdapterInfo` now exposes the field so the UI can
  read it from `GET /api/v1/migration/adapters`.
- **Added: format-hint banner on `/migrate`** — explains in-line
  what the source adapter expects (e.g. "OpenConfig NETCONF —
  machine-readable payload from `netconf get-config`, NOT `show
  running-config`").  Addresses manual QA #4 (user confusion about
  paste-box contents).
- **Added: "Load sample for source adapter" button** with a
  working minimal payload per format.  The iosxe sample round-trips
  cleanly; the opnsense sample is a minimal `<opnsense>` tree.
- **Added: stored-config compatibility warning** — when the picked
  stored config's extension doesn't match the source adapter's
  declared `input_format`, a red in-place warn appears BEFORE submit
  ("`Fortigate_*.cfg` has extension `.cfg` but `cisco_iosxe`
  expects OpenConfig NETCONF XML — translate will almost certainly
  fail").  Addresses manual QA #12, #13.
- **Fixed: path-list de-duplication** (manual QA #11).  Three
  interfaces each with a description used to produce three visually-
  identical rows in the Supported list.  Now collapses to one row
  with an `×3` count badge.  Top stats count still reflects per-leaf
  impact (unchanged).

**Tests (+23):**

- `tests/unit/migration/test_input_format.py` (13) — catalogue
  immutability, base-class default, concrete adapter declarations,
  "every registered adapter declares a KNOWN format" guard.
- `tests/integration/test_migration_api.py` (+3) — `input_format`
  surfaces on the list endpoint for every adapter.
- `tests/e2e/test_migrate_page.py` (+10) — banner severity
  regression for failed/partial/ok jobs, format-hint visibility +
  auto-update, Load-sample button, stored-config compat warn,
  path-list coalescing.

Full project suite: **674 passing** (was 651).  Pre-existing
unrelated failure in `test_jobs_schedules.py` schedule form — same
drift flagged in earlier sessions, untouched here.

### Added (translator Phase 2, part 1 — `/migrate` workbench UI)

- **New HTML page at `/migrate`** — translator workbench.  Pick source
  + target adapter, paste raw text OR pick a stored config, optionally
  tick "Force cross-class", hit Translate.  Backed entirely by the
  already-shipped `POST /api/v1/migration/plan` endpoint.
- **Nav link:** "Migrate" after "Definitions".  Active highlighting
  via the same `active_page` convention as every other page.
- **Client-side adapter hydration**: the two dropdowns fetch
  `GET /api/v1/migration/adapters` on page load, so newly-registered
  adapters appear without a template redeploy.  Each option carries
  the adapter's device classes; the info strip below shows chip
  badges (colour-coded per class) plus supported/lossy/unsupported
  counts.  A class-guard hint renders in red BEFORE submit when the
  picked pair has no common class — user knows it'll be blocked.
- **Result surface** reuses existing components so visual language
  stays consistent across the app:
  - Banner palette mirrors the diff page (`mig-banner-ok` / `warn`
    / `block` / `info`) — user's eye already knows what those mean.
  - Rendered-output pane uses the config viewer's
    `_cvRenderHighlighted(text, ext)` helper for syntax highlighting
    — same `.tok-*` colours as every other code surface.
  - Toast notifications via `window.showToast`.
- **Paths drill-down** (collapsed by default): three buckets
  (supported / lossy / unsupported) with counts, full xpath lists,
  adapter-provided reasons, and severity chips.  Users can see every
  finding the ValidationReport carries without another request.
- **Copy button** for the rendered output — one-click clipboard
  without leaving the page.
- **Parse failures are surfaced as results, not errors.** The
  pipeline returns HTTP 200 with a `failed` job on adapter errors;
  the page renders the failure banner + status summary instead of a
  toast.  Genuine 4xx responses (unknown adapter, missing filename)
  DO toast.

- **Testids:** 29 new `migrate-*` testids promoted from reserved
  status in `tests/testid_reference.md` (nav, form, dropdowns, input
  mode toggle, result region, banner, stats, output, paths buckets).
  The reserved list for Phase 2 "transforms + deploy" remains
  (`migrate-transforms-list`, `migrate-deploy-btn`, etc.).

- **E2E tests (+13):** `tests/e2e/test_migrate_page.py` covers nav
  link, page structure, result-region hidden-on-load, adapter
  dropdown hydration, adapter-info update on change, input-mode
  toggle, iosxe round-trip happy path (ok banner), rendered-output
  panel appearance, parse-failure rendering, validation-block
  rendering (partial status).  `MigratePage` helper added to
  `tests/e2e/helpers.py` following the existing page-object pattern.

- **Total suite: 651 passing** (was 567 immediately after Phase 1
  backend).  Zero regressions; no new runtime dependencies.

### Added (translator Phase 1 — OPNsense adapter + write endpoints)

- **Second real adapter: `OPNsenseAdapter`** under
  `netconfig/migration/adapters/opnsense/`.  Parses/renders OPNsense
  `config.xml`.  Scope: system hostname/domain and interfaces
  (zone, `if`, descr, enable-flag, ipaddr, subnet).  Declares
  `device_classes=[firewall, router]`.
- **OPNsense zone-keyed interface idiom flattened** at parse time:
  native `<wan>…</wan><lan>…</lan>` children become a list of dicts
  with a synthetic `zone` key, so `iter_xpaths` can emit OpenConfig-
  style schema paths (no list keys).  The render step reverses the
  transformation.  Round-trip invariant `parse(render(tree)) == tree`
  is tested with sanitised 3-interface fixture.
- **Cross-vendor guardrail shown working:** OPNsense ∩ IOS-XE =
  `{router}`, so the class guard permits the migration; the per-
  xpath capability matrices then honestly flag firewall rules
  (`/filter/rule`, `/nat/outbound`) as unsupported by IOS-XE.
  The intended layering — class guard for coarse "is this meaningful
  at all?", capability matrix for fine "which features translate?".

- **New write endpoints:**
  - `POST /api/v1/migration/plan` — runs the full pipeline
    (class-guard → parse → transforms → validate → render) on a
    raw config payload.  Returns the `MigrationJob` as JSON, even
    on parse failure (the error is in `job.error`, not an HTTP
    status).  Callers inspect `job.status` for the outcome.
  - `POST /api/v1/migration/render` — currently an alias for
    `/plan`; kept as a separate route so Phase 2 can split plan
    (no side effects) from render (pre-deploy snapshot + diff URL)
    without another API rev.
  - Input mode toggle: request body supplies EITHER `raw_text` OR
    `source_filename` (which loads from the existing backup store).
    Exactly one MUST be set — otherwise 422.  Source-filename
    shorthand means you can migrate any stored config without
    shipping the bytes through HTTP.
  - `force=true` in the body skips the device-class guard.
- **New model:** `MigrationPlanRequest` in
  `netconfig.models.migration` — documented, tested, ready for a
  Phase 2 UI to reuse.

- **Manual testing now possible** end-to-end via curl:

      curl -X POST http://127.0.0.1:8000/api/v1/migration/plan \
           -H 'Content-Type: application/json' \
           -d '{"source":"cisco_iosxe","target":"cisco_iosxe",
                "raw_text":"<interfaces xmlns=\"http://openconfig.net/yang/interfaces\">…"}'

- **Tests (+32):**
  - `tests/unit/migration/test_opnsense.py` (21): parse, errors,
    render determinism, round-trip invariant (inline + fixture),
    iter_xpaths coverage, capability declarations, cross-adapter
    class-intersection, registry.
  - `tests/integration/test_migration_api.py` (+11): plan endpoint
    happy path, 422 variants (unknown source, unknown target,
    neither/both input modes), 404 for missing filename, parse
    failure returns 200 with failed job, force flag round-trip,
    render is alias, end-to-end integration with backup store.
  - `tests/fixtures/opnsense/config_simple.xml` — sanitised sample.

- **Total suite:** 567 passing (was 535, +32).  Migration suite
  alone: 184 tests (was 140, +44 across OPNsense + API integration).

### Added (translator: adversarial-input hardening + cross-adapter tests)

- **Strict YANG boolean parsing.** `CiscoIOSXEAdapter` used to silently
  coerce any `<enabled>` text other than literal `true` to `False` —
  meaning `<enabled>yes</enabled>` would ship a DISABLED interface.
  The parser now rejects every non-RFC-7950 spelling (`yes`, `no`,
  `1`, `0`, `on`, `off`, empty string, …) with a `ParseError` that
  names the exact xpath.
- **IPv4 prefix-length range check.** Previously values like `99`
  or `-1` were accepted silently and round-tripped into the rendered
  NETCONF payload, where the device would reject the edit at deploy
  time.  The parser now enforces the YANG `inet:ipv4-prefix` range
  (`0..32`).
- **Interface-index error paths.** Empty or missing `<name>` elements
  now raise a `ParseError` whose `path` includes the zero-based
  `interface[N]` index and whose `snippet` contains the offending
  element serialised to XML (capped at 200 chars).  A device
  returning ten interfaces with one malformed entry is now locatable
  in ~5 seconds instead of "open the XML and scroll".
- **UTF-8 BOM tolerance.** Some devices (and some editors) prepend a
  BOM to their XML declaration.  Test lock-in so this stays working.
- **Cross-adapter pipeline tests** (`tests/unit/migration/
  test_cross_adapter_pipeline.py`): prove stage transitions, error
  routing, and type boundaries that no single-adapter test touches:
  - IOS-XE → mock: class guard permits, nested walker reaches leaves,
    render produces JSON despite type-shape mismatch.
  - Mock → IOS-XE: render mismatch caught as `failed` with useful
    error; validation still ran first; `completed_at` is always set.
  - Partial-status routing: a validation `block` with a successful
    render correctly lands in `partial`, not `completed` or `failed`.
  - Stage ordering: class guard runs at stage 0, before parse — a
    disjoint-class pair with broken XML fails with the class-guard
    error, not a parser error.
- **Tests (+22)**:
  - `test_cisco_iosxe.py`: 10 new adversarial-input tests covering
    the four hardening items above.
  - `test_cross_adapter_pipeline.py`: 11 new pipeline scenarios.
  - Full migration suite now 140 tests (was 97 before this hardening
    pass, 77 before Phase 0.5's round-trip work, 30 at end of Phase 0).
- Full project suite: **535 passing** (was 513).  Zero regressions.

### Added (translator Phase 0.5 — Cisco IOS-XE adapter)

- **First real adapter: `CiscoIOSXEAdapter`** under
  `netconfig/migration/adapters/cisco_iosxe/`.  Scope:
  `openconfig-interfaces` + `openconfig-if-ip` subset (name,
  description, enabled, type, IPv4 address + prefix-length on
  subinterfaces).  Enough to prove the adapter contract against
  real OpenConfig NETCONF payloads.
- **Internal tree shape:** nested dict mirroring the OpenConfig XML
  structure, namespace-stripped for readability.  Canonical namespaces
  are re-attached on render.  Operates against captured NETCONF
  `<get-config>` responses today; live `ncclient` transport is
  Phase 1's responsibility (same split as the existing
  collectors-vs-collector-consumers layout).
- **Stdlib only** — `xml.etree.ElementTree` for parse/render.  No new
  runtime dependencies; libyang canonical validation is deferred to
  Phase 0.7 behind a "validates if installed" seam.
- **Round-trip invariant enforced:** `parse(render(tree)) == tree`
  for every supported tree.  Tested over inline samples and a real
  sanitised 3-interface fixture under `tests/fixtures/iosxe/`.
- **Capability matrix declares:**
  - 9 supported paths (name, config.name, config.description,
    config.enabled, config.type, subinterface.index, address.ip,
    address.config.ip, address.config.prefix-length).
  - Lossy: `/interfaces/interface/config/mtu` — YANG model doesn't
    round-trip every platform-specific MTU tweak.
  - Unsupported: IPv6 subtree (Phase 1 work).
  - `device_classes=[router, switch]` — IOS-XE platforms routinely
    fulfil both roles.

### Changed (translator: adapter-driven tree walker)

- **`AdapterBase` gets `iter_xpaths(tree)`** — non-abstract, defaults
  to the flat `dict[str, str]` walker so the mock adapter and any
  existing callers keep working.  Adapters with nested tree shapes
  (the new `CiscoIOSXEAdapter`) override to yield schema xpaths
  (no list-key predicates) that match their declared capability
  matrix.
- **`validate_against(tree, target)` gains an optional
  `source` adapter parameter.**  When supplied, the validator uses
  `source.iter_xpaths` to walk the tree — required for adapters
  whose internal tree shape isn't a flat dict.  Backward-compatible:
  omitting `source` keeps the Phase 0 behaviour.
- **`run_plan` threads `source` through to `validate_against`**
  automatically, so all pipeline callers get adapter-aware walking
  for free.

### Tests (+41 over Phase 0 baseline)

- `tests/unit/migration/test_cisco_iosxe.py` (30): parse (bare +
  envelope), parse errors (malformed XML, missing interfaces,
  non-integer prefix-length, interface without name), render
  determinism, round-trip invariant (inline + fixture), iter_xpaths
  predicate-freedom + matrix alignment, capability declarations,
  pipeline integration, registry.
- `tests/integration/test_migration_api.py`: new assertions that
  `cisco_iosxe` appears in the list endpoint, declares the expected
  device_classes, and exposes its full capability matrix (lossy
  MTU + unsupported IPv6) via the detail endpoint.
- `tests/fixtures/iosxe/get_config_simple.xml` — sanitised 3-interface
  NETCONF `<get-config>` response (RFC 5737 documentation IPs).

### Added (translator: cross-device-class guardrail)

- **Coarse-grained device-class compatibility check** prevents
  nonsensical migrations (e.g. trying to render a Layer-2 switch
  config through a firewall adapter).  Adapters declare one or more
  ``DeviceClass`` values on their ``CapabilityMatrix``; the pipeline
  refuses a pair with no class in common unless ``force=True``.
- **New `DeviceClass` enum** in `netconfig.models.migration`:
  ``switch``, ``router``, ``firewall``, ``load_balancer``,
  ``wireless_controller``, ``access_point``, ``waf``.  Taxonomy is
  flat and additive; multi-class devices (L3 switches, UTM
  appliances) declare multiple values.
- **`CapabilityMatrix.device_classes: list[DeviceClass]`** — empty
  default is "uncommitted" and produces a ``warn`` (not block) so
  adapters can be developed before their class declarations are
  finalised.
- **`check_class_compat(source, target) -> CompatibilityReport`** in
  `netconfig.services.migration_validate`.  Reuses the
  `CompatibilityReport` shape from the diff models so UIs can render
  both class-mismatch and xpath-mismatch banners with the same
  component.  Severity branches: same/overlapping class → `ok`;
  either side undeclared → `warn`; both declared but disjoint → `block`.
- **`run_plan` stage-0 guard**: the class check runs BEFORE parse,
  so mismatched adapters fail instantly with a clear
  ``"Device-class guard refused migration: …"`` error.  A new
  ``force: bool = False`` parameter on `run_plan` skips the guard
  for deliberate cross-class experiments (same idiom as the diff
  page's `?force=true` override).
- **API surface**: `AdapterInfo.device_classes` is now returned on
  ``GET /api/v1/migration/adapters`` so UIs can filter the target
  picker to compatible adapters before the user commits.  The
  detailed ``CapabilityMatrix`` response also surfaces the field.
- **Tests (+20)**: `tests/unit/migration/test_device_class.py`
  covers the enum shape, pydantic coercion of string values (for
  capabilities.yaml loading in Phase 1), every `check_class_compat`
  severity branch, and the `run_plan` stage-0 guard (default
  behaviour + `force=True` override + no-op when already
  compatible).  Integration test added for the new
  `device_classes` field on the list endpoint.

### Added (translator Phase 0 — adapter contract + pipeline skeleton)

- **Phase 0 of the translator / migration engine landed.**  Scope per
  `translator-plans.txt` §12: prove the shape end-to-end with a
  reference adapter, no real YANG tooling required yet.
- **New pydantic models** in `netconfig.models.migration`:
  `CapabilityMatrix` (with a `classify()` resolver using
  "strictest-wins" semantics — unsupported > lossy > supported),
  `LossyPath`, `UnsupportedPath`, `ValidationReport`, `XPathDelta`,
  `TransformSpec`, `MigrationJob`, `MigrationJobStatus`, `AdapterInfo`.
  Shape deliberately mirrors `CompatibilityReport` + `BackupJob` so UI
  banners and lifecycle conventions stay consistent.
- **`netconfig.migration` package**:
  - `adapters/base.py` — `AdapterBase` ABC + `ParseError` / `RenderError`.
  - `adapters/registry.py` — in-memory `register` / `get_adapter` /
    `list_adapters` with name-collision and missing-name guards.
  - `adapters/_mock/` — reference adapter that round-trips a flat
    `dict[str, str]` via JSON; exercises every `classify()` branch
    (supported, lossy, unsupported).
  - `canonical/loader.py` — Phase 0.5 stub; `NotImplementedError`
    with clear roadmap pointer.  `PLANNED_MODULES` tuple documents
    the OpenConfig + `netconfig-ext` modules that will be pinned
    once libyang lands.
- **New services**:
  - `services/migration_validate.py` — walks a tree's xpaths,
    classifies each against the target's `CapabilityMatrix`, returns
    a `ValidationReport` with `ok` / `warn` / `block` severity.
  - `services/migration_pipeline.py` — `run_plan(source, target,
    raw_text, transforms)` orchestrator covering stages
    parse → transform → validate → render.  Each failure class
    (`ParseError`, `RenderError`, generic `Exception`) yields a
    terminal `failed` job with a `.error` summary.  A successful
    render against a `block`-severity validation yields `partial`
    (output available for review, not safe to auto-deploy).
- **New API endpoints** (read-only Phase 0):
  - `GET /api/v1/migration/adapters` — list registered adapters
    with summary counts.
  - `GET /api/v1/migration/adapters/{name}/capabilities` — full
    `CapabilityMatrix`; 404 for unknown adapters.
- **Tests (+77)**:
  - `tests/unit/migration/test_models.py` (20) — every pydantic
    type + `classify` resolution rules.
  - `tests/unit/migration/test_registry.py` (10) — decorator
    contract, collision detection, idempotent re-registration,
    LookupError on unknown names, mock always registered.
  - `tests/unit/migration/test_mock_adapter.py` (14) — round-trip
    invariant over 5 sample trees, deterministic output, parse
    error paths, capability-matrix shape.
  - `tests/unit/migration/test_validate.py` (11) — every severity
    branch including `error`-level lossy escalation, mixed
    unsupported+lossy, empty tree, non-dict tree.
  - `tests/unit/migration/test_pipeline.py` (9) — happy path,
    transform ordering + failure, parse failure, validation
    block → partial status, failed-job timing.
  - `tests/unit/migration/test_canonical_loader.py` (4) — stubs
    raise `NotImplementedError` with roadmap pointer.
  - `tests/integration/test_migration_api.py` (9) — list + detail
    endpoints, 404 for unknown adapter, summary/detail consistency.
- **No UI in this phase.**  testids for the migration UI are
  queued for Phase 2 (`migrate-source-select`, etc. — see
  `translator-plans.txt` §11); the config diff page already
  handles rendered-output review so no second viewer is needed.

### Changed (diff page: directional paradigm — `FROM → TO`)

- **"Sides" paradigm replaced with a temporally-neutral direction.**
  The unified diff layout has directionality (`+N` added / `-M`
  removed going from one file to another), not sides.  The UI now
  surfaces that explicitly with `FROM` and `TO` role labels:
  - Each filename chip is preceded by a role badge: `FROM` (dark)
    next to the left chip, `TO` (green) next to the right chip.
  - A directional arrow (`→`) replaces the neutral "vs".
  - The stats strip is prefixed `from → to:` so `+12 / −3` reads
    naturally ("12 added, 3 removed going from the left file to the
    right file").
  - The `⇄ Swap sides` button becomes `⇋ Reverse direction`; its
    tooltip explains that the click swaps FROM/TO.
- **Why `from`/`to` instead of `baseline`/`current`?**  `current`
  implied one of the configs was from "now", which is wrong when you
  diff two old configs against each other.  `from`/`to` encodes only
  direction, not time — perfect for any pairwise comparison whether
  both configs are historical, both are fresh, or mixed.
- **Testid renames:**
  - `diff-swap-sides-btn` → `diff-reverse-btn`
  - New testids: `diff-from-label`, `diff-to-label`
- **Helper / test updates:** `DiffPage.swap_sides_btn` →
  `DiffPage.reverse_btn`; `test_swap_sides_link_reverses_url` →
  `test_reverse_direction_link_reverses_url`; new assertion
  `test_from_and_to_role_labels_visible`.

### Added (diff: collapsed-context folding for large configs)

- **Context folding** on `/configs/{left}/vs/{right}`.  Long runs of
  equal lines far from any change are squashed into a single expandable
  "… N unchanged lines …" marker, matching the convention used by git,
  GitHub, GitLab and VS Code.  Drops a real-world FortiGate vs
  FortiGate comparison from **35,422 rendered `<div>`s** to **~900** —
  a ~32× reduction in browser layout cost.
- **Zero-round-trip expansion.**  Every collapsed marker ships a
  sibling `<template>` element carrying the hidden lines as
  pre-rendered markup.  Clicking the marker clones the fragment into
  the DOM in place of the marker, applies syntax highlighting to the
  new lines, and removes the marker + template.  No network call, no
  flash of unstyled content.
- Keyboard-accessible: markers are `<button>`s so Tab / Enter / Space
  all work.
- **New model:** `netconfig.models.diff.DiffGroup` — `{kind, lines}`
  where ``kind`` is the per-line classification or the new
  ``"collapsed"`` group.
- **New service:** `netconfig.services.diff.fold_context(lines,
  context=3)` — pure, two-sweep Manhattan-style distance-to-change
  computation.  Default context (`3` lines) matches unified-diff
  convention.
- **New testids:** `diff-line-collapsed`, `diff-collapsed-template`.
- **Tests:** 9 new unit tests in `tests/unit/test_diff_service.py`
  exercising the folding algorithm (boundaries, adjacent changes,
  context=0, default=3, negative rejected, order preservation).
  3 new E2E tests in `TestDiffContextFolding` covering marker
  visibility, count attribute, and click-to-expand behaviour.

### Added (config diff — Tier 1 textual line diff with compatibility guardrails)

- **`POST /api/v1/configs/diff`** — line-level unified diff between two
  stored configurations.  Body: `{left, right, force?}`.  Returns a
  `DiffReport` containing the per-line breakdown, aggregate stats
  (`{added, removed, equal}`), and a compatibility report.  Uses
  stdlib `difflib.SequenceMatcher`; no new runtime dependencies.
- **Compatibility guardrails (defence in depth).**  Two configs are
  considered diff-compatible when `type_key` (`device_type`) AND
  `file_extension` match on both records.  Mismatches:
  - API refuses with **HTTP 422** unless the caller explicitly passes
    `force=true` in the body.
  - UI: the "Compare" button on `/configs` opens a target picker that
    lists only matching configs by default; cross-vendor options are
    hidden behind a "Show cross-vendor" toggle and dimmed.
  - `/configs/{left}/vs/{right}` page always renders, but an
    incompatible pair without `?force=true` gets a red block banner
    and a "Compare anyway" override button in place of the diff body.
  - With `force=true` the diff is computed anyway; a red banner warns
    semantic equivalence is not guaranteed.
- **Deep-linkable diff URL** at `/configs/{left}/vs/{right}` (with
  optional `?force=true`).  Reuses the config viewer's syntax
  highlighter client-side — each diff line's `<span>` goes through
  `_cvRenderHighlighted(text, ext)` post-render so cfg/xml colouring
  stays consistent between the viewer and the diff view.
- **Compare button** on every row of `/configs`; lightweight modal
  picker keyed on `type_key` + `file_extension`.
- **New models:** `netconfig.models.diff.{DiffLine, CompatibilityReport,
  DiffRequest, DiffReport}`.  **New service:**
  `netconfig.services.diff.{check_compatibility, compute_diff}` — pure,
  no I/O, easily testable.
- **New tests:**
  - `tests/unit/test_diff_service.py` (12 tests): pure-function tests
    for compat logic, add/remove/replace, force annotation, empty input,
    trailing-newline handling.
  - `tests/integration/test_configs_api.py::TestDiffCompatibility` +
    `::TestDiffOutput` (8 tests): same-type OK, cross-vendor 422,
    force override, 404 on missing filename, line-number monotonicity.
  - `tests/e2e/test_backup_flow.py::TestDiffApi` +
    `::TestDiffPageUI` + `::TestDiffPageContent` (13 tests): live-API
    wiring, Compare button and picker, cross-vendor hide/show, banner
    severity, force override, swap-sides link.
- **New testids** for Compare picker and the diff page; see
  `tests/testid_reference.md`.

### Fixed (config viewer search misses queries that cross syntax-highlight spans)

- **Cross-span search now works.** The syntax highlighter splits the
  config text into many text nodes interleaved with ``<span class="tok-*">``
  elements.  The previous per-text-node ``indexOf`` loop couldn't see a
  match that straddled a span boundary, so queries like ``64:ff9b``
  (FortiGate IPv6 NAT prefix — ``64`` is a ``tok-number`` span, ``:ff9b``
  is plain text in the next node) or ``hostname Router`` (keyword span
  followed by plain text) silently returned zero matches even when the
  substring was clearly present.
- **Fix:** ``_cvSearch`` in ``base.html`` now flattens the ``<pre>`` into
  a single string while building a ``(node, absolute_offset)`` segment
  map, finds matches in the flat text, and wraps each match across
  whatever boundaries it crosses.  Matches are processed in reverse
  document order so earlier offsets stay valid as later ones mutate
  the DOM.  A single logical match becomes a *group* of ``<mark>``
  elements; ``configViewerNav`` toggles the ``.current`` class on every
  element in the group and scrolls to the first.
- **New E2E tests** in ``tests/e2e/test_backup_flow.py``:
  - ``test_cross_span_query_finds_match`` — asserts ``"hostname Router"``
    (straddles the ``tok-keyword`` span) now matches.
  - ``test_cross_span_match_current_class_applied_to_all_pieces`` —
    asserts every ``<mark>`` in the group gets ``.current``.

### Added (parallel backup execution within a job)

- **Per-job parallelism** — `_run_backup_job` now dispatches device work
  to a bounded `ThreadPoolExecutor`.  Up to `backup_concurrency` devices
  run simultaneously; additional devices wait in the executor's FIFO
  queue and start as slots free up.  A 30-device job with 30 s per
  device now completes in ~3 × the per-device latency instead of 30 ×.
- **`Settings.backup_concurrency`** — new configurable, range `[1, 10]`,
  default `10`.  Hard-capped at `MAX_BACKUP_CONCURRENCY = 10` in
  `netconfig/config.py` to protect target SSH servers (most vendor caps
  are 5–16) and bound server thread count.  Override via
  `NETCONFIG_BACKUP_CONCURRENCY`; see `.env.example`.
- **Serial fast-path** — jobs with a single device (or deployments
  pinned to `backup_concurrency=1`) skip the thread pool entirely;
  traces and error paths stay unchanged for those callers.
- **Thread-safety contract** documented in the `_run_backup_job`
  docstring: results list is pre-populated and never resized, each
  worker mutates exactly one index, and `FileConfigStore` atomic writes
  handle storage concurrency.
- Tests default to serial execution (`test_settings` sets
  `backup_concurrency=1`) so the existing observation test and all
  ordering-sensitive assertions remain deterministic.  Explicit parallel
  tests in `TestBackupConcurrency` exercise the pool via `Barrier(n)`.

### Added (persistent backup-progress panel + per-device lifecycle states)

- **`BackupResult.status` lifecycle** — new intermediate values `queued`
  and `running` alongside the existing terminal `success` / `failed`.
  `_run_backup_job` now pre-populates one `BackupResult` per device in
  `queued` state, flips each to `running` when its collector is invoked,
  and sets the terminal state on completion.  Polling clients can snapshot
  the results list at any point and see exactly which device the engine is
  working on.
- **Floating job-progress panel** (`base.html` — global):
  - Bottom-right floating widget, present on every page.
  - Collapsible header showing aggregated job status + live summary
    (`2/5 complete — running: 1 — queued: 2` or `5/5 succeeded`).
  - One row per device with status icon (`○` queued, `⟳` running, `✓`
    success, `✗` failed), host label, per-device duration, and truncated
    error on failure.
  - **Persists across full page reloads** — the active job ID is stored
    in `localStorage["netconfig.activeJob"]`; on `DOMContentLoaded` the
    panel resumes polling if the stored job is still non-terminal, and
    renders the final state otherwise.
  - Explicit `Dismiss` button (no auto-dismiss) clears the panel AND the
    localStorage key.  A "View full job details" deep link jumps to the
    corresponding card on `/jobs`.
  - Dispatches `netconfig:job-started`, `netconfig:job-progress`,
    `netconfig:job-complete`, and `netconfig:job-dismissed` `CustomEvent`s
    on `document` so page-level code (e.g. the dashboard row injector)
    can react without re-polling.
- **New `data-testid`s:** `job-progress-panel`, `job-progress-header`,
  `job-progress-summary`, `job-progress-toggle`, `job-progress-body`,
  `job-progress-device-row`, `job-progress-device-status`,
  `job-progress-device-host`, `job-progress-device-duration`,
  `job-progress-device-error`, `job-progress-footer`,
  `job-progress-view-link`, `job-progress-dismiss`.  The legacy
  `job-status-banner`, `job-id-display`, and `job-status-display` testids
  are aliased onto the new panel for backward compatibility.

### Removed

- **Inline job status banner** on `index.html` — replaced by the global
  floating progress panel (above).  The dashboard's submit handler now
  delegates to `startJobProgress(jobId)` and listens for the
  `netconfig:job-complete` event for the "inject a row into the recent
  jobs table" step.

### Added (config viewer: syntax highlighting + in-modal search)

- **Syntax highlighting** in the shared config viewer modal (`viewConfig()`):
  comments, keywords, strings, IP addresses, and numbers for Cisco / Fortigate /
  Mikrotik `.cfg` output, plus tags and attributes for OPNsense XML.  Unknown
  extensions fall back to escaped plain text.  Palette is VS Code "Dark+"
  inspired; all tokens are rendered as `<span class="tok-*">` so E2E tests and
  custom themes can target them.
- **In-modal search** with live match counter, previous / next navigation
  (▲ / ▼ buttons), keyboard shortcuts (Enter = next, Shift+Enter = previous,
  Escape = clear or close), and wrap-around.  Matches are wrapped in `<mark>`
  elements; the currently-selected match gets `mark.current` for a distinct
  highlight colour and is auto-scrolled into view.
- **New `data-testid`s** for the viewer: `config-viewer`, `config-viewer-title`,
  `config-viewer-content`, `config-viewer-search`, `config-viewer-search-count`,
  `config-viewer-search-prev`, `config-viewer-search-next`, `config-viewer-close`.
  Full reference in `tests/testid_reference.md`.

### Changed (job status reflects per-device outcomes)

- **`JobStatus.partial`** — new terminal state for backup jobs where at least
  one device succeeded AND at least one failed.  Terminal-state semantics are
  now:
  - `completed` — every device succeeded.
  - `partial`   — mixed result (≥1 success, ≥1 failure).
  - `failed`    — zero successes (every device failed).

  Previously a job was marked `completed` regardless of per-device outcomes;
  users had to look at the success/total column to notice failures.  The UI
  now shows an amber `badge-partial` and a ⚠ indicator for mixed runs.

### Added (backup jobs page + recurring schedules)

- **Job persistence** — `FileJobStore` writes one JSON file per completed backup
  job to `{data_root}/jobs/`.  All jobs are reloaded into `app.state.jobs` at
  startup, so job history survives server restarts.
- **`BackupJob.schedule_id` / `schedule_name`** — new optional fields track
  which schedule triggered a job (snapshot of name at run time).  `None` for
  manually triggered runs.
- **`GET /jobs`** — dedicated Jobs page listing all backup jobs newest-first.
  Each job is a collapsible card showing: short ID, status badge, success/total
  count, timestamp, duration, and trigger (schedule name or "Manual").  Expanded
  body shows a per-device results table with View / Download / (Open) links and
  the config filename.  URL hash navigation: `/jobs#a1b2c3d4` auto-expands and
  scrolls to the matching job card.
- **`/schedules`** — Schedule management page and backing API:
  - **`GET /api/v1/schedules/`** — list all schedules
  - **`POST /api/v1/schedules/`** — create a recurring backup schedule
    (name, interval\_minutes, devices list)
  - **`DELETE /api/v1/schedules/{id}`** — delete a schedule
  - **`POST /api/v1/schedules/{id}/toggle`** — enable / disable a schedule
- **`BackupSchedule` model** (`netconfig/models/schedule.py`) — stores schedule
  metadata: id, name, enabled, interval\_minutes, devices, created\_at,
  last\_run\_at, next\_run\_at, last\_job\_id.
- **`FileScheduleStore`** (`netconfig/storage/schedule_store.py`) — persists
  schedule definitions as JSON under `{data_root}/schedules/`.
- **APScheduler integration** — `AsyncIOScheduler` (timezone=UTC) is started in
  the app lifespan.  Each enabled schedule registers an `IntervalTrigger` job.
  Blocking SSH runs via `asyncio.to_thread` so it never blocks the event loop.
  Scheduler state is purely in-memory; schedule definitions are re-loaded from
  disk and re-registered on every startup.
- **`next_run_at` tracking** — captured from APScheduler after registration and
  after each run; persisted to disk so the Schedules page always shows an
  accurate value even before the first tick.
- **Nav updated** — "Jobs" and "Schedules" links added between Dashboard and
  Configs in the nav bar (order: Dashboard | Jobs | Schedules | Configs |
  Definitions | API Docs).  Swagger nav updated to match.
- **`apscheduler>=3.10.4`** added to `requirements.txt` and `pyproject.toml`.

### Added (nav bar on API Docs page)

- **`GET /docs`** — FastAPI's built-in Swagger UI is now replaced by a
  custom route that injects the NetConfig nav bar (sticky, same style as
  all other pages) so users can always navigate back from the API explorer.
  The raw `/openapi.json` schema endpoint is unchanged.  `/redoc` is
  disabled (it was unreachable from the UI anyway).

### Changed (vendor-specific field naming)

- **`ConnectionConfig.handle_paging` → `cisco_more_paging`** — renamed to make
  clear this flag controls Cisco `--More--` space-injection specifically.
  `terminal length 0` remains deliberately avoided on all Cisco definitions.
- **`ConnectionConfig.needs_shell_menu` → `opnsense_shell_menu`** — renamed to
  make clear this flag detects and dismisses the OPNsense numbered console menu
  (sends `"8"` to enter the shell).  Not applicable to any other current vendor.
- **`ConnectionConfig.needs_enable`** — unchanged.  Enable/privileged-mode
  escalation is a cross-vendor concept in Netmiko (Cisco IOS, HP ProCurve,
  Aruba OS-CX, and others).
- Updated all four YAML definition files, both collectors, all test YAML strings,
  `tests/fixtures/definitions.py`, `Get-NetworkConfigs.ps1`,
  `Test-NetworkConfigs.ps1`, and all README/doc files to match.

### Added (config storage & open-in-editor)

- **Subdirectory storage layout** — config files are now saved under
  `{device_type}/{safe_host}/` inside `configs_dir` instead of a flat root.
  Example: `configs/Cisco/192-168-1-1/Cisco_192-168-1-1_20260414_120000.cfg`.
  The self-describing filename format is unchanged.
- **Startup migration** — `FileConfigStore.__init__` automatically moves any
  flat files left by older versions into the correct subdirectory.  Non-config
  files (log files, README) are left untouched.
- **Collision safety** — if two backups of the same device complete within the
  same second, a numeric suffix is appended (`…_1.cfg`, `…_2.cfg`, …) so no
  file is ever silently overwritten.
- **`resolve_path(filename)`** — new public method on `BaseConfigStore` and
  `FileConfigStore`.  Returns the absolute filesystem path for a given filename,
  checking the subdirectory location first then falling back to the root for
  files that pre-date migration.
- **`Settings.open_in_editor: bool = False`** — new flag.  When `True`, enables
  the `POST /api/v1/configs/{filename}/open` endpoint.  Set to `True` in
  `netconfig_desktop/settings.py`.  Can also be enabled for local web
  deployments via `NETCONFIG_OPEN_IN_EDITOR=true`.
- **`POST /api/v1/configs/{filename}/open`** — opens the named config file in
  the OS default text editor (`os.startfile` on Windows, `open` on macOS,
  `xdg-open` on Linux).  Returns 204 on success; 403 if disabled; 404 if not
  found; 500 if the OS refuses to open the file.  Documented as desktop-only
  in `CLAUDE.md`; the web equivalent is the existing View button.
- **"Open" button** (`data-testid="config-open-btn"`) — appears in the Actions
  column of the Configs page only when `open_in_editor=True`.  Calls the open
  endpoint; shows a success or error toast via `showToast()`.

### Tests (config storage & open-in-editor)

- `tests/unit/test_storage.py` — 19 new/updated tests: subdirectory save,
  collision safety (triple-collision), `resolve_path` (subdir + flat fallback +
  missing), startup migration (multiple files, non-config left in place,
  idempotent), and `rglob`-based listing.  Existing tests updated to use
  `store.resolve_path()` instead of manually constructing paths.
- `tests/integration/test_configs_api.py` — `TestOpenConfig` (5 tests): 403
  when disabled, 404 for missing file, 204 on success, correct path passed to
  `os.startfile`, 500 when OS refuses.
- `tests/testid_reference.md` — `config-open-btn` added with conditional
  visibility note.

---

### Added (logging)

- **`netconfig/logging_config.py`** — New `configure_logging(level, log_file)` function.
  Sets up a `StreamHandler` (stderr) plus an optional `RotatingFileHandler` (5 MB, 3
  backups) on the root logger.  Idempotent: skips when real (non-pytest) handlers are
  already present.  Suppresses `paramiko`, `uvicorn.access`, `multipart`, and `asyncio`
  to `WARNING` regardless of root level to reduce noise in INFO/DEBUG runs.
- **`netconfig_desktop/__main__.py`** — `_configure_logging()` called before
  `DesktopApp()`.  In frozen (installed) mode writes to
  `%APPDATA%\NetConfig\netconfig.log`; in dev mode uses console only.  Fatal startup
  exceptions now go through `logger.critical(..., exc_info=True)` before the message
  box so the stack trace is captured in the log file.
- **`netconfig_desktop/server.py`** — `log_config=None` added to `uvicorn.Config` so
  uvicorn's startup does not call `logging.config.dictConfig()` and overwrite the root
  logger configuration set by `configure_logging()`.
- **`netconfig_desktop/settings.py`** — `log_level` default raised from `"warning"` to
  `"info"` so desktop INFO logs reach the file handler.

### Changed (logging)

- **`netconfig/api/routes/backups.py`** — Device backup failures upgraded from
  `WARNING` to `ERROR` and now include `exc_info=True` for full traceback capture.
- **`netconfig/api/routes/configs.py`** — Added module logger; all three endpoints now
  emit structured log records (`DEBUG` for list/get, `INFO` for delete success,
  `WARNING` for 404 paths).
- **`netconfig/api/routes/definitions.py`** — Added module logger; reload endpoint
  logs loaded count and source directory at `INFO`.
- **`netconfig/storage/file_store.py`** — Added module logger; `save()` logs filename
  and byte count at `INFO`, `list_configs()` at `DEBUG`, `delete()` at `INFO`.
- **`netconfig_desktop/app.py`** — Lifecycle events (start, server ready, quit, window
  closed) logged at `INFO`.
- **`netconfig_desktop/tray.py`** — Added module logger; `run_detached()` at `DEBUG`,
  Show/Quit callbacks at `DEBUG`/`INFO`, `stop()` exception swallowed at `DEBUG`
  (was silent).
- **`netconfig_desktop/window.py`** — Added module logger; `create()` and `start()` at
  `INFO`, show/hide/destroy at `DEBUG`, `on_closed` callback exception at `DEBUG`
  (was silent).

### Tests (logging)

- `tests/unit/test_logging_config.py` — 17 new unit tests across three classes:
  `TestConfigureLoggingBasic` (handler type, levels, idempotency),
  `TestFileHandler` (rotating handler, directory creation, write-through),
  `TestNoisyLoggerSuppression` (third-party loggers capped at WARNING, netconfig.*
  left at NOTSET).  `reset_root_logger` autouse fixture restores root logger state
  after each test.

---

### Security

- **Credential encryption at rest** (`netconfig/security/credentials.py`) —
  Device passwords and enable passwords are now encrypted with Fernet
  symmetric encryption before being written to disk.  The key is stored in
  the OS secure credential store (Windows Credential Manager / macOS Keychain
  / Linux SecretService) via the `keyring` library.  Existing plaintext
  profiles and schedule device lists are automatically migrated to encrypted
  storage on first load.  In-memory model objects always hold plaintext;
  encryption is a storage-layer concern only.
- **Path traversal protection** (`netconfig/storage/file_store.py`) —
  `resolve_path()` now rejects any filename that does not match the expected
  naming convention regex before touching the filesystem.  Both the
  subdirectory and flat-fallback paths are verified to lie inside the storage
  root via `Path.resolve().is_relative_to()`.
- **Open-in-editor extension whitelist** (`netconfig/api/routes/configs.py`) —
  `POST /api/v1/configs/{filename}/open` now checks the file extension against
  an explicit allowlist (`{.cfg, .conf, .txt, .xml, .log}`) and returns 400
  for any other type, preventing the OS handler from being invoked on
  executables or other unintended file types.
- **Host field validation** (`netconfig/models/device.py`,
  `netconfig/models/device_profile.py`) — `DeviceTarget.host`,
  `DeviceProfileCreate.host`, and `DeviceProfileUpdate.host` now validate
  against `ipaddress.ip_address()` or an RFC-1123 hostname regex.  Shell
  metacharacters, path separators, and other invalid values are rejected
  with HTTP 422.
- **Passwords removed from HTML DOM** — `data-password` /
  `data-enable-password` attributes removed from the Dashboard
  `<option>` elements (`index.html`).  Credentials are fetched via
  `GET /api/v1/devices/{id}` when a saved device is selected.  The
  `data-profile` attribute on Devices page cards (`devices.html`) no
  longer includes credential fields; `runDeviceBackup()` fetches the full
  profile from the API on demand.
- **Data directories added to `.gitignore`** — `devices/`, `schedules/`,
  `jobs/`, and `configs/` are now excluded from version control to prevent
  credential-bearing files from being committed.
- **`cryptography>=41.0.0` and `keyring>=24.0.0`** added to
  `requirements.txt` and `pyproject.toml` dependencies.
- **`SECURITY.md`** — new document describing the security architecture,
  threat model, implemented controls, and known limitations.  Must be kept
  up-to-date with any security-relevant change.

### Tests (security)

- `tests/unit/test_credentials.py` — 18 tests covering key initialisation
  (first run, cached reload, idempotent), `encrypt`/`decrypt` round-trip
  (empty string, unicode, uniqueness per call), `InvalidToken` on garbage
  input, and `decrypt_field()` migration helper (encrypted→True,
  plaintext→False, empty→False).
- `tests/unit/test_storage.py` → `TestResolvePathSecurity` — 7 tests
  covering `../` traversal, `.cfg`-suffixed traversal, absolute paths,
  subdir-relative paths, empty string, and a positive case asserting the
  resolved path stays inside the storage root.
- `tests/unit/test_models.py` → `TestDeviceTarget` — 7 host validation tests:
  IPv4, IPv6, hostname accepted; `../`, `/`, space, semicolon rejected.
- `tests/integration/test_configs_api.py` → `TestOpenConfig` — 2 new tests
  for extension whitelist (`.exe`, `.zip` → 400).
- `tests/integration/test_configs_api.py` → `TestPathTraversal` — 4 new
  tests: `../../etc/passwd` GET/DELETE → 404, `.cfg`-suffixed traversal →
  404, absolute path → 404.

### Added (device profiles)

- **`DeviceProfile` model** (`netconfig/models/device_profile.py`) — stores
  profile metadata: `id` (UUID), `name`, `type_key`, `host`, `port`, `username`,
  `password`, `enable_password` (optional), `notes` (optional), `created_at`.
  `DeviceProfileCreate` and `DeviceProfileUpdate` companion models.
- **`FileDeviceProfileStore`** (`netconfig/storage/device_profile_store.py`) —
  persists profiles as JSON under `{data_root}/devices/{id}.json`.
- **`GET/POST /api/v1/devices/`** and **`GET/PUT/DELETE /api/v1/devices/{id}`** —
  full CRUD for device profiles.
- **`GET /devices`** — Devices page listing all profiles as collapsible cards.
  Each card shows name, type badge, host, backup count, and actions (▶ Backup /
  Edit / Delete).  Expanding the card reveals a per-config history table.
  Inline edit panel (`device-edit-panel`) allows credential updates without
  leaving the page.
- **Dashboard — saved device select** (`data-testid="device-profile-select"`) —
  selecting a saved profile pre-fills all form fields.  Optional "Save as Profile"
  name input (`data-testid="device-profile-name-input"`) creates or links a profile
  when the backup form is submitted.
- **`ConfigRecord.device_profile_id`** — new optional field linking a stored
  config to the device profile that produced it.  Persisted as a sidecar
  `{filename}.meta.json` alongside each config file; sidecar is cleaned up on
  delete.  `list_configs()` reads sidecars to populate the field.
- **`BackupSchedule` — two-pronged targeting** — `target_type_keys: list[str]`
  (back up all profiles of matching types) and `target_device_ids: list[str]`
  (back up specific profile UUIDs); mix is permitted.  Inline `devices` list
  retained for backward compatibility.  `ScheduleCreate` validates that at least
  one target field is non-empty.
- **`GET /devices` nav link** added between Dashboard and Jobs.
  Order: Dashboard | Devices | Jobs | Schedules | Configs | Definitions | API Docs.

### Fixed (View / Download buttons — WebView compatibility)

- **`base.html`** — Added shared `viewConfig(filename)` function (fetches config
  and displays it in a new inline modal), `downloadConfig(filename)` function
  (blob-based download, works in Qt WebEngine where `<a download>` is unreliable),
  and `closeConfigViewer()`.  New config viewer modal (`#_config-viewer`) added to
  the base layout; closes on backdrop click or Escape key.
- **`configs.html`** — View (`config-view-link`) and Download (`config-download-btn`)
  changed from `<a target="_blank">` / `<a download>` to `<button>` elements
  calling `viewConfig()` / `downloadConfig()`.  Added `DOMContentLoaded` hash
  handler: navigating to `/configs#{filename}` scrolls to the matching row,
  briefly highlights it, and auto-opens the viewer modal.
- **`jobs.html`** — View (`job-config-view-link`) changed from
  `<a href="/api/v1/configs/…" target="_blank">` to `<a href="/configs#{filename}">`
  so clicking View on a job result navigates to the Configs tab with the file
  pre-selected.  Download (`job-config-download-btn`) changed from `<a download>`
  to `<button onclick="downloadConfig(…)">`.
- **`devices.html`** — Same View / Download fix as `configs.html` applied to the
  per-device config history table.

### Fixed

- **`configs.html`** — Post-delete empty-check used CSS selector `.config-row`
  (no such class) instead of `[data-testid="config-row"]`, causing the page to
  reload after *every* deletion rather than only when the last config was removed.
- **`base.html`** — Removed orphaned `.badge-success` CSS rule that duplicated
  `.badge-completed` and leaked device-result vocabulary into the job-level badge
  namespace.

### Added

- **`POST /api/v1/definitions/reload`** — New API endpoint that re-reads all YAML
  files from `definitions_dir` and replaces the in-memory registry without a server
  restart.  Returns `{ "loaded": N, "type_keys": [...] }`.
- **Definitions page** — "↻ Reload" button (`data-testid="def-reload-btn"`) that
  calls the new reload endpoint and refreshes the page on success.
- **Configs page** — "View" link (`data-testid="config-view-link"`) and download
  button (`data-testid="config-download-btn"`) are now separate explicit actions in
  the Actions column.  The filename cell is now plain text.
- **Toast notifications** (`data-testid="toast"`) — Global `showToast(msg, type)`
  function in `base.html` replaces all `alert()` calls with a non-blocking,
  auto-dismissing notification (4 s timeout).  Types: `info`, `success`, `error`.
- **Inline job results** — After a backup job completes, per-device results
  (host, type, success/failure, error message) are rendered directly in the status
  banner.  The recent-jobs table row is injected by JS; no full-page reload occurs.
- **Active nav state** — Current page is highlighted in the navbar
  (`class="active"`, `aria-current="page"`).  `active_page` context variable added
  to all three UI route responses in `main.py`.
- **UTC timestamp localisation** — All `[data-utc]` elements are converted to
  browser-local time on `DOMContentLoaded` via a global script in `base.html`.
  Server-rendered fallback (UTC string) is preserved for non-JS contexts.
- **Enable Password conditional visibility** — The Enable Password field is shown
  only for device types where `connection.needs_enable` is `true`.  Driven by
  `data-needs-enable` attributes on `<option>` elements; toggled on type change.
- **Port collapsed to Advanced** — The SSH port field (default 22, rarely changed)
  is now inside a `<details>` summary labelled "⚙ Port", reducing visual noise in
  the backup form.
- **Inline delete confirmation** — The Delete button on the Configs page now shows
  an in-row "Delete? Yes / No" prompt instead of the browser's native `confirm()`
  dialog (which can be suppressed in embedded WebView contexts).
- **Empty-state guidance** — All three pages now include actionable text in their
  empty states rather than bare declarative messages.

### Changed

- **Nav brand** (`data-testid="nav-brand"`) changed from `<span>` to `<a href="/">`
  so clicking the product name navigates home, per standard convention.
- **Submit button** (`data-testid="submit-backup-btn"`) is now disabled and labelled
  "Running…" while a backup job is in flight, preventing double-submission.
- **Polling error handling** — The job-status polling `setInterval` now counts
  consecutive fetch failures and stops after 3, showing a toast instead of silently
  looping forever.
- **Jobs table** — "Devices" column removed (redundant with "Success / Total"
  denominator).  "Job ID" column is now plain text (`data-testid="job-id-text"`)
  rather than a link to the raw JSON API response.  "Created (UTC)" header
  simplified to "Created" (timestamps are localised by JS).
- **Configs table** — "Captured (UTC)" column header simplified to "Captured".
  Filename column is now plain text; view/download actions moved to the Actions
  column.
- **Definitions table** — "Strategy" column renamed to "Collection"; strategy
  values are now human-readable ("SSH (Netmiko)", "SSH (Shell)") rather than
  internal Python identifiers.  "Ext" column header renamed to "File Ext".
  Notes cell gains a `title` tooltip showing the full (untruncated) text.
- **`button:disabled`** CSS rule added to `base.html` — disabled buttons now show
  `opacity: 0.6` and `cursor: not-allowed` globally.
- **E2E test** `test_submit_completes_and_page_reloads` renamed to
  `test_submit_completes_and_shows_job_in_table` and updated to assert that the
  jobs table becomes visible via JS injection (no `wait_for_load_state` needed).
- **Remove device button** gains `aria-label="Remove this device"` for
  accessibility.

### Tests

- `tests/integration/test_definitions_api.py` — Added `TestReloadDefinitions`
  (5 tests): 200 response, loaded count, type_keys list, post-reload registry
  accessibility, idempotency.
- `tests/testid_reference.md` — Updated for all new/changed testids: `toast`,
  `job-id-text` (replaces `job-link`), `config-view-link` (moved to Actions),
  `config-download-btn`, `config-delete-confirm-btn`, `config-delete-cancel-btn`,
  `def-reload-btn`.  Notes added for conditional visibility and `data-utc`.

---

## [0.1.0] — initial release

- Multi-vendor SSH configuration backup via Netmiko and Paramiko Shell strategies
- FastAPI + Jinja2 web UI: Dashboard, Configs browser, Definitions viewer
- Windows desktop shell: PySide6/QtWebEngine window, pystray system-tray icon,
  embedded Uvicorn server (`netconfig_desktop`)
- cx_Freeze MSI installer (`setup_desktop.py`)
- Four-layer test suite: unit, integration, E2E (Playwright), desktop

# Netcanon v0.5.3 — Fable Full Review: Synthesis (2026-07-06)

Target: git main @ `8598d74` (tag `v0.5.3`). Twelve read-only review lenses + two promotion scouts,
every finding adversarially re-verified by an independent verifier agent before inclusion here.

Raw intake: 69 findings + 20 promotion candidates. Reconciliation: **1 finding REFUTED and dropped**
(MSI rc/final ProductVersion collision — cx_Freeze authors an inclusive-VersionMax Upgrade row, so
rc→final major-upgrades cleanly; the WiX default the finder assumed does not apply), **2 cross-lens
duplicates merged** (CLI sanitize `-o` raised by 04+06; port-rename target collision raised by 03+12),
**1 finding severity adjusted** (junos irb-fold MINOR→MEDIUM after live repro). Net: **66 findings —
1 HIGH, 14 MAJOR, 26 MEDIUM, 25 MINOR — all verifier-CONFIRMED** (finder precision 68/69). All 20
promotion candidates survived verification, **4 with material adjustments** (metric-sweep junos/aoss
wiring redesign, NVE parse-only option ruled unsound, ntp/dns YAML flip subset corrected, snmp
sub-key split demoted to documentation-only); see `98-promotion-candidates.md`.

## VERDICT: SHIP-WITH-FIXES

v0.5.3 stays shipped: fuzzing found zero parse crashes across all 12 codecs (18,252 mutated parses),
every remediation from the 2026-07-03 review is verified present in-tree, the API/trust boundaries are
well hardened, and the release pipeline fundamentals are sound. Nothing here is a
pull-the-release defect. But the next release wave should bundle three clusters that produce **silent
wrong output on default, documented flows**: (1) the rename-transform seam walks an incomplete set of
canonical cross-references, so the default `/plan` flow can render internally inconsistent or
duplicate-IP configs with `warnings=[]` (DATA-1/2, 03-F1/F2/F6); (2) junos block-form and MikroTik
`%`-gateway inputs — both documented supported shapes — silently corrupt VLAN membership, DNS, and
next-hops (11-F1/F2/F3); (3) the front-page Tier-1 promise claims timezone (0/12 codecs) and syslog
(1/12) round-trip everywhere, and the drop is silent (DOC-1, the sole HIGH). Two items deserve
immediate attention independent of the wave: gate Docker `:latest` off prerelease tags **before the
next rc tag is pushed** (07-F1, certain to fire), and make the TOFU paramiko host-key persist a
read-merge-write (CONC-10, silently re-opens the MITM window the v0.4.5 default closed).

---

## HIGH

### 1. [HIGH] Tier-1 promise includes timezone + syslog_servers that (almost) no codec wires; source-side drop is silent
**Where:** `README.md:283` (also `docs/CAPABILITIES.md:92`, `netcanon/migration/canonical/README.md:189-193`, 4 vendor pages, `docs/glossary.md:39`) · **Lens:** 09-docs-truth · **Confidence:** confirmed (verifier: CONFIRMED, reproduced)
**Failure:** Docs promise "Tier 1 … DNS / NTP / syslog servers, timezone. Every shipped codec parses + renders these fully." Reality: timezone is wired on **0/12** codecs (every matrix declares `/system/timezone` unsupported; zero parse.py references), syslog on **1/12** (junos). Reproduced: cisco source with `clock timezone PST -8 0` + `logging host 10.1.1.9` → both parse to empty, `dropped_tier3_sections=[]` (no banner), junos output contains neither — device ships with no audit logging and wrong clock, silently. DNS/NTP half is also false for nxos/iosxr. Bonus contradiction: cisco_iosxe_cli render.py:188 already emits `logging host` while its own matrix reason claims it doesn't (see promotion #1).
**Fix:** Remove timezone + syslog from every Tier-1 claim list; scope DNS/NTP as "most codecs — see per-codec tables"; demote the two fields' Tier-1 labels in `intent.py:831-834` or wire them; optionally add `logging`/`clock timezone` to IOS-style Tier-3 detection so the source-side drop banners.

---

## MAJOR

### 2. [MAJOR] TOFU known_hosts: concurrent paramiko saves are last-writer-wins, silently dropping freshly pinned host keys
**Where:** `netcanon/collectors/hostkey.py:101` · **Lens:** 02-concurrency · **Confidence:** confirmed (reproduced with real paramiko clients)
**Failure:** First fleet backup with ≥2 unpinned paramiko-shell (OPNsense) devices, workers>1, default tofu: `apply_paramiko_policy` loads and `persist_paramiko_host_keys` saves under **separate** lock holds with the whole SSH connect between; when the store file didn't exist at policy-apply time, paramiko's `save_host_keys` plain-overwrites (no merge). Worker A pins devA → worker B saves {devB} → devA's pin silently deleted; also clobbers keys a concurrent Netmiko `verify_host_key` just persisted. Device is re-TOFU'd unverified next run — the exact MITM window the v0.4.5 default closed — with no error.
**Fix:** Make `persist_paramiko_host_keys` read-merge-write under one `_KNOWN_HOSTS_LOCK` hold: load the current file into a fresh `paramiko.HostKeys`, union in `client.get_host_keys()`, save the merged set; never call `client.save_host_keys()`. Mirrors the already-atomic `verify_host_key`.

### 3. [MAJOR] Port-rename transform leaves `vxlan_vnis[].source_interface` and `vrrp_groups[].track_interfaces` stale → dangling references on the DEFAULT cross-vendor flow
**Where:** `netcanon/migration/canonical/port_names.py:496` (strip twin at :534) · **Lens:** 12-data-integrity · **Confidence:** confirmed (reproduced end-to-end)
**Failure:** Junos EVPN source (lo0.0 VTEP, VRRP tracking ge-0/0/1) → arista via the default `/plan` auto-translate: interfaces rename to Loopback0/Ethernet1/Vlan10 but render emits `vxlan source-interface lo0.0` (invalid EOS name, VTEP binding broken) and `vrrp 10 track ge-0/0/1` (nonexistent port — failover silently disabled). Even an explicit map entry doesn't reach these fields; `intent.py:695-699`'s docstring claiming coverage is false. Invisible to the cross-mesh (bare render) and to live validation (path classifies supported).
**Fix:** In the rewrite sweep (lines 494-511) resolve `vx.source_interface` and each VRRP group's `track_interfaces`; in `_strip_dropped_ports` filter `track_interfaces` and clear `source_interface`. Fix the mount-list docstring.

### 4. [MAJOR] Junos `group_content` verbatim re-emission resurrects pre-rename interfaces: same IP emitted for BOTH old and new names
**Where:** `netcanon/migration/codecs/juniper_junos/render.py:1190` · **Lens:** 12-data-integrity · **Confidence:** confirmed (reproduced)
**Failure:** junos→junos rename {ge-0/0/1: xe-0/0/5} on a config where the interface lives in an apply-group: render emits the renamed config top-level under xe-0/0/5 AND the verbatim group body under ge-0/0/1; re-parse yields both interfaces each carrying 10.9.9.1/30 — the same /30 on two ports, `warnings=[]`. Same hole defeats drops and the VLAN/user/SNMP panes for group-resident objects. `tools/sanitize.py:956` already strips group_content for exactly this reason; the rename pipeline never got the guard.
**Fix:** Fail closed: when any rename/drop was applied and `tree.group_content` is non-empty, clear group_content + apply_groups (the flattened canonical data already carries semantics) and append a warning that group bodies were flattened.

### 5. [MAJOR] `translate_vlan_ids` misses `dot1q_vlan` and `vxlan_vnis[].vlan_id` — rename/drop renders broken configs
**Where:** `netcanon/migration/canonical/vlan_names.py:249` · **Lens:** 03-correctness · **Confidence:** confirmed (reproduced unit + E2E)
**Failure:** `vlan_rename_map={10:20}` renders `vlan 20` + `access vlan 20` but the routed sub-interface still emits `encapsulation dot1Q 10` (job completed, zero warnings) — L3 on the renumbered VLAN dead on deploy. `CanonicalVxlan.vlan_id` also stays 10 despite intent.py's documented keep-in-sync invariant; cisco_nxos render unions vni vlan_ids into the emitted VLAN list, so a rename/drop resurrects `vlan 10` with the vn-segment bound to the old VLAN.
**Fix:** Pass 2: rewrite `iface.dot1q_vlan` like `access_vlan` (rename→renumber, drop→warn). Add Pass 3 over `intent.vxlan_vnis`: rename `vlan_id`; on drop, remove the VNI record with a warning.

### 6. [MAJOR] Port rename map `{A:'B', B:None}` deletes BOTH interfaces; `applied` claims the rename landed
**Where:** `netcanon/migration/canonical/port_names.py:556` · **Lens:** 03-correctness · **Confidence:** confirmed (reproduced)
**Failure:** Operator retires B and renames A onto its name: the strip pass filters the POST-rename tree against SOURCE-name drops, so renamed-A matches and is deleted too. Repro: `applied={A:B}`, `dropped=[B]`, zero surviving interfaces, no warning — silent loss of a configured interface with a contradictory job report.
**Fix:** Strip user-supplied drops BEFORE the rename sweep (they're keyed by source names), keeping the post-sweep strip only for the `strip_unmappable` auto-drop set; or track dropped objects instead of names.

### 7. [MAJOR] Junos block-form bracket value lists never expanded: silent loss + literal `[` ingested as data
**Where:** `netcanon/migration/codecs/juniper_junos/parse.py:986` · **Lens:** 11-codec-deepdive · **Confidence:** confirmed (reproduced)
**Failure:** Block-form (`show configuration`) is one of the two supported junos input shapes; it writes multi-value leaves as bracket lists. `name-server [ 8.8.8.8 1.1.1.1 ];` → `dns_servers==['[']` (both servers lost; cross-vendor renders `ip name-server [`); `vlan { members [ v10 v20 ]; }` on a trunk → `trunk_allowed_vlans==[]` → IOS targets render bare `switchport mode trunk` = ALL VLANs allowed. All committed junos fixtures are .set files, so the mesh is blind to it.
**Fix:** In `_blockform_to_setform`'s statement reader, expand a trailing `[ v1 v2 … ]` group into one set-line per value; add a block-form fixture with bracket lists.

### 8. [MAJOR] Junos `vlan members <vid>`/`<vid-range>` silently dropped (numeric tokens never resolve)
**Where:** `netcanon/migration/codecs/juniper_junos/parse.py:543` · **Lens:** 11-codec-deepdive · **Confidence:** confirmed (reproduced end-to-end)
**Failure:** The resolve post-pass consults only the name→id map, so `set vlans v100 vlan-id 100` + `vlan members 100` → `access_vlan=None` (port lands in VLAN 1 on cisco targets); trunk + `members 100-110` → bare trunk = 4094 VLANs instead of 11. Bites hardest on the new pre-ELS path (#294) where numeric members are common.
**Fix:** In the resolve pass: if `vname.isdigit()` and 1≤int≤4094 use it as the VID; expand `^(\d+)-(\d+)$` ranges for trunks; optionally materialise a CanonicalVlan for unmatched numerics.

### 9. [MAJOR] MikroTik `gateway=<ip>%<iface>` combined form not split on parse → invalid next-hop tokens on every target
**Where:** `netcanon/migration/codecs/mikrotik_routeros/parse.py:1282` · **Lens:** 11-codec-deepdive · **Confidence:** confirmed (reproduced)
**Failure:** RouterOS documents `gateway=192.168.88.1%ether1` and netcanon's own renderer emits it (render.py:609-612), but `_parse_ip_route` stores the whole token as `route.gateway`: cisco gets `ip route 0.0.0.0 0.0.0.0 192.168.88.1%ether1` (invalid), junos `next-hop 192.168.88.1%ether1` (commit-rejected); the codec's own emission reparses asymmetrically. No committed fixtures carry `%` gateways, so the mesh never sees it.
**Fix:** `gw, sep, egress = gateway.partition('%')`; when `sep`, set `route.gateway=gw`, `route.interface=egress`.

### 10. [MAJOR] SVI-mounted IPv6 has no home in the VLAN-centric model → silent UNDECLARED drop into aruba_aoss
**Where:** `netcanon/migration/codecs/aruba_aoss/parse.py:632` (model root: `intent.py:313`, `transforms.py:308/390`, `xpath_walker.py:215-238`) · **Lens:** 10-architecture · **Confidence:** confirmed (reproduced both ways)
**Failure:** cisco `interface Vlan10 / ipv6 address 2001:DB8:10::1/64` → aoss: the SVI is absorbed into the vlan stanza and the v6 address vanishes while `validate_against` reports zero ipv6 findings (path declared supported; exact-match xpaths can't condition on interface kind). Native aoss→aoss sanitize loses it too (parse skips `ipv6 address` inside `vlan N`). `CanonicalVlan`, both SVI projection transforms, and the walker's VLAN mount are all IPv4-only — the honesty machinery is structurally blind to the loss (the exact class the blind audits closed for IPv4).
**Fix:** Near-term: parse vlan-context ipv6 onto the synthesized `Vlan<N>` CanonicalInterface (VRRP already attaches there) + emit it in the absorption render; until then declare the aoss path LOSSY. Long-term: `CanonicalVlan.ipv6_addresses`, extend both projections, add `/vlans/vlan/ipv6/...` walker mounts.

### 11. [MAJOR] `merge_trunk_allowed` 'add' branch is O(|ids|·|base|) list-membership; 8.6 KB config → ~7 s parse across 3 codecs
**Where:** `netcanon/migration/codecs/_helpers.py:199` · **Lens:** 05-performance · **Confidence:** confirmed (reproduced at scale)
**Failure:** POST `/plan` (arista_eos / cisco_nxos / cisco_iosxe_cli) with one interface + K× `switchport trunk allowed vlan add 1-4094`: each line costs ~8.4M comparisons against the accumulating 4094-element list. K=200 → 8.6 KB → ~7 s (repro); ~250 KB (well under the 10 MB cap) pins a threadpool worker ~3 min; near-cap bodies → hours. Unauthenticated on the default local bind.
**Fix:** `seen = set(base); return base + [vid for vid in ids if vid not in seen]` — behavior-identical, order preserved (remove/except already use sets).

### 12. [MAJOR] PUT /api/v1/devices/{id}: documented "pass None to clear" is a silent no-op — pinned fields can never be cleared
**Where:** `netcanon/api/routes/device_profiles.py:141` · **Lens:** 06-api-contract · **Confidence:** confirmed (reproduced over HTTP)
**Failure:** `DeviceProfileUpdate` promises "pass None to clear" for enable_password/notes/os_version/model, but the handler filters `is not None` over `model_dump()` (no `exclude_unset`), so explicit nulls == omitted. The UI (devices.html:460) defers operators to exactly this broken path. Only workaround is delete+recreate, which mints a new UUID and orphans schedule `target_device_ids`. A stale os_version pin keeps resolving the wrong definition overlay every backup.
**Fix:** `updates = body.model_dump(exclude_unset=True)`; apply None as a genuine clear for the four nullable fields; 422 on explicit None for non-nullables. Add an explicit-null integration test; fix the devices.html affordance.

### 13. [MAJOR] Docker `:latest` moves onto pre-release tags on GHCR and Docker Hub
**Where:** `.github/workflows/docker-publish.yml:224` · **Lens:** 07-build-release-ci · **Confidence:** confirmed (history-proven)
**Failure:** Trigger includes `v*.*.*-*` and `type=raw,value=latest` is unconditional (raw entries have no prerelease awareness). Pushing e.g. `v0.6.0-rc1` publishes the rc AND repoints `:latest` — the README/SECURITY quickstart pull — on both registries, cosign-signed. Git history proves it: commit `e809839` removed the old `enable={{is_default_branch}}` gate and rc5–rc9 were tagged after it. Certain to fire on the next rc.
**Fix:** `type=raw,value=latest,enable=${{ !contains(github.ref_name, '-') }}` (or drop the raw line for `flavor: latest=auto`, which is prerelease-aware).

### 14. [MAJOR] Cross-mesh fidelity ratchet covers only 41% of the mesh: all 76 pairs involving the 4 newest codecs can never produce CODEC_BUG
**Where:** `tests/integration/test_cross_mesh_ci_guard.py:129` (root: `tools/run_phase4_reconciliation.py:797`) · **Lens:** 08-test-quality · **Confidence:** confirmed
**Failure:** The 56 expectation YAMLs are exactly the 8×7 mesh of the original 8 codecs; 723/1224 cells have no YAML → `field_variances={}` → drift on any pair involving cisco_nxos/cisco_iosxr/aruba_aoscx/vyos structurally cannot classify as CODEC_BUG. A regression dropping every static route on arista→nxos keeps all six guard tests green. Same-vendor cells are likewise excluded — the exact surface v0.5.3/#297 changed.
**Fix:** Short term: pin `sum(summary.fields_drifted)` per YAML-less pair against a committed baseline (cells already carry this). Long term: author YAMLs for the 76 uncovered pairs, starting with the new codecs' highest-traffic partners.

### 15. [MAJOR] CAPABILITIES.md §A claims complete enumeration of lossy/unsupported paths; tables badly stale vs live matrices
**Where:** `docs/CAPABILITIES.md:181` · **Lens:** 09-docs-truth · **Confidence:** confirmed (verified against live registry)
**Failure:** Doc says the tables "enumerate every UnsupportedPath and LossyPath declared today", but cisco_iosxe_cli shows 4 lossy/10 unsup vs live 12/12 — including one row marked "Supported (Wave C)" for a path the live matrix declares **Lossy** (anycast virtual-gateway-address; wrong-direction error, planning-relevant). 3 of 4 hard-coded counts wrong (nxos 46→44, aoscx 36→34, vyos 30→29); line 30's nxos summary false (20 unsupported paths, not "only IPv6 anycast + Tier-3"); line 731 even claims the doc omits hard-coded counts.
**Fix:** Regenerate §A from the live registry (same source as the /definitions page and the capabilities API), or replace per-path tables with pointers to those live surfaces; delete or auto-derive the counts.

---

## MEDIUM

### 16. [MEDIUM] Four per-pane endpoints still carry the API-1 verbatim-names trap fixed on /plan
**Where:** `netcanon/api/routes/migration.py:412` (also 475, 539, 603) · **Lens:** 03-correctness · **Confidence:** confirmed (reproduced)
**Failure:** `/plan/vlans`, `/plan/local_users`, `/plan/snmp`, `/plan/snmpv3` leave `port_rename_map=None`, disengaging the port-name translator: same body renders `ge-1/0/2` on /plan but invalid `GigabitEthernet1/0/2` on /plan/vlans — contradicting /plan's own post-v0.5.0 contract comment. (Shipped UI posts only to /plan, so exposure = direct API consumers.)
**Fix:** Pass `port_rename_map=(body.port_rename_map if body.port_rename_map is not None else {})` in the four handlers; add a per-pane parity test asserting no source-vendor names in the render.

### 17. [MEDIUM] Port-rename target collisions: no detection, no warning — duplicate stanzas or silently merged interfaces
**Where:** `netcanon/migration/canonical/port_names.py:375` · **Lenses:** 03-correctness (F6) + 12-data-integrity (DATA-3), deduped · **Confidence:** confirmed (both repros)
**Failure:** Rename onto an existing name (same-vendor) renders TWO `interface GigabitEthernet1/0/2` stanzas with conflicting config — on-device the second silently overwrites the first. Cross-vendor, a one-character typo mapping two sources to `ge-0/0/9` interleaves both configs; re-parse fuses them into ONE interface (desc clobbered, both /30s on unit 0) — two physical links fused, `warnings=[]`. The vlan/local-user/snmpv3 orchestrators all detect target collisions and merge+warn; the ports pane is the odd one out.
**Fix:** After the rename sweep, detect duplicate resolved interface/LAG names; append a "rename collision: N sources map to <name>" warning naming the sources and refuse or deterministically merge; optionally 400 explicit maps with duplicate values at the API boundary.

### 18. [MEDIUM] VLAN rename with an existing SVI renders two SVIs with the same IP
**Where:** `netcanon/migration/canonical/vlan_names.py:217` · **Lens:** 03-correctness · **Confidence:** confirmed (reproduced E2E)
**Failure:** `vlan 10` + `interface Vlan10 / ip 10.1.1.1/24`, rename {10:20}: parse-side SVI folding carries the L3 to id 20, render-side synthesis emits a new `interface Vlan20` while the un-renamed `Vlan10` also renders — duplicate overlapping-subnet SVIs IOS rejects, zero warnings. The claimed mitigation ("UI composes the two maps") is NOT implemented — verified the UI never composes SVI entries into the port map.
**Fix:** When renaming/dropping id N, detect an interface matching the canonical `Vlan<N>` spelling and warn to compose the port map — or rename the canonical-named SVI alongside the VLAN record.

### 19. [MEDIUM] Empty-string key `{'': None}` in port_rename_map silently deletes every gateway-only static route and unbound DHCP pool
**Where:** `netcanon/migration/canonical/port_names.py:337` (filters at :572-577) · **Lens:** 03-correctness · **Confidence:** confirmed (reproduced)
**Failure:** `interface` defaults to `''` on routes/pools; `dropped_set={''}` matches all of them — default route deleted, job completed, `warnings=[]`, `port_drops=['']`. Pydantic accepts the key; sibling orchestrators (local_user_names.py:144-149) warn+skip exactly this input class.
**Fix:** Skip+warn empty/blank source keys in `translate_port_names`; guard strip filters with `r.interface and r.interface in dropped`.

### 20. [MEDIUM] `project_switchport_to_vlan` trunk-all stamp is interface-order-dependent and non-idempotent
**Where:** `netcanon/migration/canonical/transforms.py:159` · **Lens:** 03-correctness · **Confidence:** confirmed (reproduced both halves)
**Failure:** Trunk-all port declared before an access port whose VLAN has no top-level stanza: the VLAN is synthesized after the stamp, so its `tagged_ports` misses the trunk — VLAN-centric targets lose the uplink membership (blackhole). Realistic: stacked switches with the uplink on member 1. Second call adds the entry, violating the module's "idempotent — safe to call twice" contract.
**Fix:** Two-pass: materialize all `_vlan()` records first, then run membership stamping so trunk-all stamps the final VLAN set.

### 21. [MEDIUM] Arista legacy `vrf definition` harvest (#295) reads only the header; inline rd/description silently dropped
**Where:** `netcanon/migration/codecs/arista_eos/parse.py:574` · **Lens:** 11-codec-deepdive · **Confidence:** confirmed (reproduced)
**Failure:** Pre-4.23 EOS (the dialect #295 targets) carries the RD inside the stanza IOS-style; harvest creates the instance with `route_distinguisher=''`/`description=''`. EOS→EOS re-render emits `vrf instance RED` with no rd (silent same-vendor loss); L3VPN targets lose the RD. Mesh-invisible (committed 4.21/4.22 fixtures carry no VRFs).
**Fix:** Harvest the stanza body like cisco_iosxe_cli does (scan_stanzas with rd/description/route-target handlers); let the existing router-bgp pass merge by name on top.

### 22. [MEDIUM] MikroTik VRRP VIP prefix rewritten to the parent interface's prefix on same-vendor round-trip
**Where:** `netcanon/migration/codecs/mikrotik_routeros/parse.py:877` (render fallback :1048-1055) · **Lens:** 11-codec-deepdive · **Confidence:** confirmed (reproduced)
**Failure:** VIP `10.0.0.100/28` on vrrp10 with parent at /24: parse stashes `virtual_ip_prefix=28` in scratch but `_materialise_vrrp_groups` drops it (grep: written, never read — render.py:998's docstring claiming it's mirrored is false); render falls back to the parent prefix → emits `/24`. Same-vendor sanitize silently changes the on-wire netmask (alters the connected route); comparator-invisible; matrix declares the surface supported so no banner.
**Fix:** Carry the stashed prefix onto the group (optional `virtual_ip_prefix`/`virtual_ip6_prefix` ints on CanonicalVRRPGroup, ship-before-wire) and prefer it over the parent-prefix fallback; or minimally declare the loss as a LossyPath.

### 23. [MEDIUM] MikroTik silently substitutes SNMPv3 auth/priv algorithms with no lossy declaration — validation reports ok during a crypto change
**Where:** `netcanon/migration/codecs/mikrotik_routeros/render.py:651` (matrix: codec.py:151) · **Lens:** 12-data-integrity · **Confidence:** confirmed (reproduced; scenario detail corrected — 3des sources are cisco/junos/arista/nxos, not fortigate)
**Failure:** sha224→SHA256, sha384→SHA512, 3des→DES (strength downgrade), unknown→SHA1/AES fallback via `_CAN_TO_MT_AUTH/_PRIV`; the walker yields `/snmp/v3-user/auth-protocol` + `priv-protocol` precisely so downgrading codecs declare them — six codecs do, MikroTik doesn't, so classify() fail-opens to supported and existing SNMP managers keyed for sha224/3DES stop authenticating with no banner anywhere. Sibling: aruba_aoss emits `auth_protocol` verbatim, so sha256 renders invalid AOS-S syntax.
**Fix:** Add the two LossyPath declarations to the MikroTik matrix (reasons naming the substitutions); add an aoss lossy declaration for the verbatim-emit.

### 24. [MEDIUM] DHCP pool is the one Tier-2 surface with zero sub-field walker vocabulary; MikroTik silently resets lease_time
**Where:** `netcanon/migration/canonical/xpath_walker.py:295` · **Lens:** 10-architecture · **Confidence:** confirmed (reproduced end-to-end)
**Failure:** `lease 0 2 0` (7200 s) → mikrotik render emits no `lease-time=` → re-parse 86400: a 2h lease policy silently becomes 1 day while validation reports ok (mikrotik declares no dhcp path at all → fail-open). Worse, the codec author CANNOT declare it honestly: the walker yields only opaque `/dhcp-servers/pool`, so a `/lease-time` declaration is flagged as a suspicious dead path by the honesty guard. Static routes/SNMPv3/VRRP/VXLAN all got sub-field walks; DHCP was left out — "declare what you drop" is structurally unsatisfiable there.
**Fix:** Extend `_walk_canonical` with conditional DHCP sub-field yields (gateway/dns-servers/domain-name when populated; lease-time when ≠86400), then have mikrotik declare `/dhcp-servers/pool/lease-time` lossy or wire `lease-time=` into its render. Registry-wide guards then police the fleet automatically.

### 25. [MEDIUM] BackupJobRegistry can evict a running job; a poll promotes the stale disk snapshot which masks the live job forever
**Where:** `netcanon/storage/job_registry.py:162` · **Lens:** 02-concurrency · **Confidence:** confirmed (reproduced)
**Failure:** `__setitem__` evicts LRU regardless of status; a poll then promotes the stale PENDING disk snapshot into the cache; the worker's terminal save goes to disk only (never re-inserted) — registry answers "pending" forever while disk says "completed", and every poll pins the lie to MRU. (Ironic: the CONC-5 pending-snapshot fix converted a transient self-healing 404 into a permanent wrong status.) Realistic with the documented NETCANON_MAX_MEMORY_JOBS knob tuned low.
**Fix:** Never evict non-terminal jobs in `__setitem__` (scan from LRU end for the first terminal job; allow temporary cap overshoot); optionally re-insert into the registry after the terminal save in `run_backup_job`.

### 26. [MEDIUM] Scheduled jobs never persisted at creation — the CONC-5 fix landed on the manual path only
**Where:** `netcanon/api/routes/schedules.py:249` · **Lens:** 02-concurrency · **Confidence:** confirmed (exact-code asymmetry)
**Failure:** `_run_scheduled_backup_inner` inserts into `app.state.jobs` and dispatches with no `job_store.save(job)`. (a) Evicted mid-run scheduled job → GET 404 while genuinely running, absent from the list; (b) documented `max_memory_jobs=0` makes EVERY scheduled run invisible for its whole duration; (c) a crash mid-run leaves no trace the run started — for the tool's primary unattended mode.
**Fix:** Mirror backups.py: `app.state.job_store.save(job)` in try/except OSError (log, non-fatal) before dispatch.

### 27. [MEDIUM] Minutes-long backup jobs run on shared default thread pools: pile-ups starve every sync route (manual) or /sanitize + egress filter (scheduled)
**Where:** `netcanon/api/routes/backups.py:245` (scheduled: `schedules.py:260`) · **Lens:** 02-concurrency · **Confidence:** confirmed (mechanics lib-source-verified; end-to-end derived, not load-tested)
**Failure:** Manual path holds one of anyio's 40 default tokens per in-flight job for minutes (excess jobs also block on the r7 global SSH semaphore while holding tokens); ~40 concurrent jobs freeze all sync routes while async /health stays green. Scheduled path shares the 8-thread default executor with /sanitize and the egress filter; startup re-registration anchors same-interval schedules together so they burst after restarts. There is no ceiling on concurrent jobs today, only devices.
**Fix:** Dedicated module-level ThreadPoolExecutor in backup_runner.py sized to an explicit max-concurrent-jobs cap (8-16), used by both entry points (route submits to it; scheduler `run_in_executor`s it).

### 28. [MEDIUM] Non-UTF-8 stored config yields an opaque 500 on read/diff/migrate/detect (9 endpoints)
**Where:** `netcanon/storage/file_store.py:263` · **Lenses:** 04-error-paths · **Confidence:** confirmed (reproduced over HTTP)
**Failure:** `get_content` is the lone strict decoder in the stack (collectors/CLI/sanitize all use errors='replace'); the file IS listed/selectable (list reads only stat), but GET /configs/{f}, /configs/diff, /migration/detect, and `resolve_input_text` (feeding 6 plan/render endpoints) catch only FileNotFoundError → UnicodeDecodeError escapes to a bare 500 on every action.
**Fix:** `read_text(encoding="utf-8", errors="replace")` at the choke point (matches the stack convention); or catch UnicodeDecodeError at the four route sites → 422.

### 29. [MEDIUM] GET /api/v1/backups/ says "all backup jobs" but lists only the memory-resident LRU; documented `NETCANON_MAX_MEMORY_JOBS=0` empties it permanently
**Where:** `netcanon/api/routes/backups.py:274` · **Lens:** 06-api-contract · **Confidence:** confirmed (reproduced)
**Failure:** Silent truncation past the cap with no pagination/total (default 1000 is exceeded in ~5 weeks at the project's own sizing); with the documented 0 setting — whose config.py docstring claims "every read hits disk" — the list endpoint and Jobs page go permanently blank while POSTs 202 and get-by-id works. Registry semantics are intentional; the route-level "all" promise and the config docstring are stale.
**Fix:** Minimum: reword route summary + config docstring. Better: merge/fall back to job_store when cache < disk count, or add paging; or forbid 0 (ge=1).

### 30. [MEDIUM] Fortigate LAG first-pass reverse-link is a redundant O(M·I) scan
**Where:** `netcanon/migration/codecs/fortigate_cli/parse.py:428` · **Lens:** 05-performance · **Confidence:** confirmed (reproduced quadratic)
**Failure:** Per-aggregate full scan of the growing interfaces list; the dict-based second pass (:524-532) already reverse-links everything in O(I). n=4000 → 536 KB → quadratic growth; ~minutes near the 10 MB cap, pinning a worker.
**Fix:** Prefer an O(1) name-dict lookup in the first pass (verifier caveat: outright deletion changes behavior in the degenerate duplicate-member case; the dict variant is byte-exact).

### 31. [MEDIUM] Arista channel-group reverse-link is O(D²) via `next()` scan over intent.lags
**Where:** `netcanon/migration/codecs/arista_eos/parse.py:804` · **Lens:** 05-performance · **Confidence:** confirmed (reproduced)
**Failure:** D distinct channel-groups → list grows to D, each iteration rescans → ~4× per size doubling (D=4000 → 226 KB → 0.27 s; ~9 min at the cap).
**Fix:** Build `lags_by_name` dict once (or maintain as created); O(1) lookup.

### 32. [MEDIUM] Junos irb-fold (and two sibling handlers) scan intent.vlans per entry → O(n²)
**Where:** `netcanon/migration/codecs/juniper_junos/parse.py:616` (siblings :1756, :1790-1792) · **Lens:** 05-performance · **Confidence:** confirmed (verifier ADJUSTED MINOR→MEDIUM after live repro)
**Failure:** Per-irb `next((v for v in intent.vlans ...))` with a stub append growing the list; V=4000 → 146 KB → 0.275 s, ~3.2× per doubling (worse per-byte than #31). Verifier found the same anti-pattern fires on EVERY `set vlans <name> vlan-id <N>` line (:1756), i.e. ordinary vlan-heavy configs, plus the vxlan-vni name scan.
**Fix:** One `vlan_by_id`/`vlan_by_name` dict shared across all three sites, updated on stub append.

### 33. [MEDIUM] compute_diff uses `SequenceMatcher(autojunk=False)` → O(n²) on configs with many repeated lines
**Where:** `netcanon/services/diff.py:119` · **Lens:** 05-performance · **Confidence:** confirmed (reproduced; fix-safety stress-tested)
**Failure:** Configs are dense with repeated `!`/`exit` lines; n=16000 → 25 s, n=50000 → ~4 min via POST /configs/diff and the UI diff page. Stored configs may be 50 MB (> the migration cap); the context fold runs after the quadratic compute. No comment justifies disabling autojunk.
**Fix:** Drop `autojunk=False` (verifier probe: identical popular-line files still diff as equal; 1-line-change churn identical either way), or add a line-count guard/fallback.

### 34. [MEDIUM] PII guard grep misses forward-slash, doubled-backslash (JSON/repr), MSYS, and case variants of the operator-path leak
**Where:** `.github/workflows/pii-guard.yml:52` · **Lens:** 07-build-release-ci · **Confidence:** confirmed (byte-exact repro)
**Failure:** The recurrence guard matches only the exact-case single-backslash Windows profile-path form. Verified: the forward-slash form, the doubled-backslash form (exactly how this repo's job-record JSONs serialize paths), the Git-Bash `/c/…` form, and case variants (path and email) all pass. A committed traceback/JSON paste re-leaks the operator username publicly with CI green — the incident class that forced the 2026-06 history rewrite. Tracked tree currently has zero occurrences of any variant, so hardening cannot break the build.
**Fix:** Case-insensitive grep with a widened path branch covering both slash directions and the doubled-backslash encoding, keeping the self-masking char-class trick (the finder's report has the exact pattern, kept out of this file deliberately).

### 35. [MEDIUM] Guard never pins expectation-YAML coverage: deleting one YAML removes 2 of 5 baseline CODEC_BUGs, all guards green
**Where:** `tests/integration/test_cross_mesh_ci_guard.py:195` · **Lens:** 08-test-quality · **Confidence:** confirmed
**Failure:** `arista_eos__cisco_iosxe_cli.yaml` holds 2 of the 5 baseline bugs; delete/orphan it (codec renames orphan YAMLs silently — loader keys by filename stem) and live=3≤5 passes, vanished-pair checks pass, `cells_total` unchanged. `expectation_yamls_loaded` and `fields_total` exist in both result and baseline but are asserted nowhere.
**Fix:** Assert `expectation_yamls_loaded >= baseline` and `len(cells_without_expectation_yaml) <= baseline`; optionally `fields_total >= baseline` to catch per-key shrinkage.

### 36. [MEDIUM] Render-failure allowlist is pair-scoped, so ~24 committed real-vyos cells can go render-dead invisibly
**Where:** `tests/integration/test_cross_mesh_ci_guard.py:49` · **Lens:** 08-test-quality · **Confidence:** confirmed
**Failure:** Documented intent covers only vyos `kitchen_sink.conf` on 2 targets, but the test reduces failures to (source,target); a regression crashing on the 12 committed REAL vyos captures lands inside the allowlisted pairs, and render-error cells also exit CODEC_BUG counting entirely.
**Fix:** Key `_ALLOWED_RENDER_FAILURES` by (source, target, fixture basename) — cells already carry `fixture` — or pin failing-cell count per pair.

### 37. [MEDIUM] MikroTik kitchen-sink round-trip skipped fixture-wide for one bond-description gap, masking all other regressions on the codec
**Where:** `tests/unit/migration/test_synthetic_kitchen_sink_round_trips.py:103` (skip at :247-249) · **Lens:** 08-test-quality · **Confidence:** confirmed (gap re-verified current)
**Failure:** The only real drift is bond1/bond2 description loss, but the pytest.skip fires before parse/render/compare, so the round-trip asserts nothing — a regression on VLANs/VRRP/routes/the v0.5.3-changed NTP block stays green (same-vendor cells are also outside Phase-4). Being a skip (not strict-xfail), the entry rots silently once fixed.
**Fix:** Field-targeted exemption: run the comparison and blank only the documented field before asserting, or assert the diff set equals exactly the documented gap.

### 38. [MEDIUM] Round-trip semantic-compare normalizer exists in three hand-synced copies that have already drifted
**Where:** `tests/unit/migration/test_synthetic_kitchen_sink_round_trips.py:280` (twins: `test_real_captures.py:347-367`, `tools/run_full_mesh.py:200-259`) · **Lens:** 10-architecture · **Confidence:** confirmed (landmine reproduced in-memory)
**Failure:** The synthetic copy claims to mirror the real-captures twin but lacks the `dropped_tier3_sections` pop and `routing_instances` sort: adding a second Tier-3 stanza to the iosxr kitchen sink makes the synthetic harness fail on correct-by-design behavior while identical content passes the real harness. Green today only by coincidence (iosxr render re-trips the tier3 detector identically). The mesh copy has its own extras.
**Fix:** Extract one `canonical_compare_dump(intent, *, cross_vendor=False)` helper encoding the union of invariants; import from all three sites (the DIR_TO_CODEC_NAME consolidation is the precedent).

### 39. [MEDIUM] README + HOW_WE_TEST claim e2e/desktop tiers "run locally, not in CI" and CI pytest uses -x; both false
**Where:** `README.md:380` (also `docs/HOW_WE_TEST.md:16-18/42-44/141-142`) · **Lens:** 09-docs-truth · **Confidence:** confirmed
**Failure:** ci.yml runs unconditional E2E (Playwright) and Desktop (PySide6) jobs on every PR — in-file comments even note the old local-only policy — and no pytest invocation uses -x (fail-fast:false). SECURITY.md lists both jobs as REQUIRED merge checks, so the project's docs contradict each other about the release gate. Safe direction (CI stronger than documented) but misleads auditors.
**Fix:** Rewrite the three doc sites to name the actual five-job gate; drop the -x sentence.

### 40. [MEDIUM] VyOS backup definition still documented provisional despite the #113 live-validation graduation
**Where:** `netcanon/definitions/library/README.md:255` (also `ARCHITECTURE.md:45-46`) · **Lens:** 09-docs-truth · **Confidence:** confirmed
**Failure:** Library README says "Not yet validated on live hardware … Confirm on a real router" and "(Notes column flags it)" — the YAML says LIVE-VALIDATED 2026-06-17, a unit test asserts it, CAPABILITIES.md already lists only the other three as provisional, and the Notes column now shows the opposite. Operators re-validate or distrust a graduated def.
**Fix:** Replace the warning bullet with the LIVE-VALIDATED note; drop VyOS from ARCHITECTURE.md's provisional list.

### 41. [MEDIUM] migrate.html "Validation OK" banner cites SNMPv3 algorithms and VRRP priority/preempt as "not yet checked" — exactly what #205/#206 wired
**Where:** `netcanon/templates/migrate.html:1530` · **Lens:** 09-docs-truth · **Confidence:** confirmed
**Failure:** The walker yields `/snmp/v3-user/auth-protocol`+`priv-protocol` and VRRP `priority`/`preempt`, all classified by validation; the banner un-advertises the shipped hardening, pushing operators into unnecessary manual crypto audits.
**Fix:** Update the banner string to drop the parenthetical or cite genuinely-unwalked examples (e.g. VRRP sub-second timers), keeping the "review the output" tail.

---

## MINOR

### 42. [MINOR] Egress allow-list does not unwrap IPv6 transition formats (NAT64/6to4/IPv4-compatible)
**Where:** `netcanon/services/egress.py:52` · **Lens:** 01-security · **Confidence:** confirmed (reproduced)
**Failure:** With NETCANON_BLOCK_PRIVATE_EGRESS=true, `64:ff9b::a9fe:a9fe` (NAT64-wrapped 169.254.169.254), 6to4, and IPv4-compatible literals pass `assert_egress_allowed` (only ipv4_mapped is unwrapped) — while `tools/sanitize.py:_embedded_public_ipv4` in the same repo handles all of them. Reach requires the deploying network to route the transition prefix; opt-in guard.
**Fix:** Factor a shared `_embedded_ipv4s(addr)` helper from the sanitizer's logic; block when the embedded IPv4 is loopback/link-local/unspecified.

### 43. [MINOR] delete_device_profile iterates the live schedules dict under the WRONG lock → RuntimeError 500, profile not deleted
**Where:** `netcanon/api/routes/device_profiles.py:183` · **Lens:** 02-concurrency · **Confidence:** confirmed (pattern reproduced, 0.03 s under contention)
**Fix:** Snapshot `list(schedules.values())` under SCHEDULE_REGISTRY_LOCK before taking the profile lock (CONC-6 pattern).

### 44. [MINOR] Device-profile 1000-cap check outside the registry lock (schedules route fixed exactly this race)
**Where:** `netcanon/api/routes/device_profiles.py:90` · **Lens:** 02-concurrency · **Confidence:** confirmed
**Fix:** Move the cap check inside the `with DEVICE_PROFILE_REGISTRY_LOCK:` block, mirroring `create_schedule`.

### 45. [MINOR] No startup reconciliation of non-terminal persisted jobs: crash → forever-"pending" ghosts
**Where:** `netcanon/main.py:199` · **Lens:** 02-concurrency · **Confidence:** confirmed
**Fix:** At lifespan startup (or in `_warm_from_disk` + a `load_one` guard), flip loaded pending/running jobs to failed("interrupted by server restart") and re-persist.

### 46. [MINOR] CLI `sanitize -o <unwritable>` dies with a raw traceback, exit 1 — unfixed write half of prior API-3
**Where:** `netcanon/cli.py:183` · **Lenses:** 04-error-paths + 06-api-contract (deduped) · **Confidence:** confirmed (reproduced)
**Failure:** Input read is guarded (clean error, exit 2); the output write is not — missing parent dir/read-only target dumps a traceback and the sanitized output is lost. Commit `059883f` (#285) fixed only the RenderError half.
**Fix:** Wrap the write in try/except OSError → `error: cannot write {path!r}: {e}` to stderr, return 2, mirroring cli.py:137-139.

### 47. [MINOR] open_config 500s (not 501) on missing OS helper; profile create/update mutates memory before an unguarded save → 500 + memory/disk drift
**Where:** `netcanon/api/routes/configs.py:202`; `device_profiles.py:99/143` · **Lens:** 04-error-paths · **Confidence:** confirmed (b reproduced)
**Fix:** (a) Treat FileNotFoundError from subprocess.run as 501 like the NotImplementedError branch. (b) Wrap the profile save in except OSError and roll back the in-memory insert (note: unlike the backups pending-save, this save is the SOLE persistence — rollback-and-error, don't swallow).

### 48. [MINOR] snmpv3 rename collision: dropped record still reported in `applied`, missing from `dropped`
**Where:** `netcanon/migration/canonical/snmpv3_user_names.py:212` · **Lens:** 03-correctness · **Confidence:** confirmed (reproduced)
**Fix:** Record `result.applied` only after the collision check passes; append collision-dropped names to `result.dropped`.

### 49. [MINOR] Not-found rename-map entries: vlan docstring promises a warning that never fires; port `dropped` over-reports never-present names
**Where:** `netcanon/migration/canonical/vlan_names.py:117`; `port_names.py:530` · **Lens:** 03-correctness · **Confidence:** confirmed (reproduced)
**Fix:** Add the existence check + warning in `translate_vlan_ids`; in `translate_port_names` warn on keys that matched nothing and report only drops that removed something (local_user/snmpv3 already do).

### 50. [MINOR] Unknown codec name: 400 on /sanitize, 422 on all migration endpoints
**Where:** `netcanon/api/routes/sanitize.py:51` · **Lens:** 06-api-contract · **Confidence:** confirmed (reproduced)
**Fix:** Route /sanitize's unknown-vendor rejection through the 422 convention (update the sanitize integration assertions in the same commit), or declare the 400 deliberately in `responses=`.

### 51. [MINOR] OpenAPI declaration gaps: /sanitize 200 wrong content-type + undeclared header; 404/400/403/413/409/501 undeclared across CRUD routes
**Where:** `netcanon/api/routes/sanitize.py:33` (+ backups/devices/schedules/definitions/configs routes) · **Lens:** 06-api-contract · **Confidence:** confirmed (verified in generated schema)
**Fix:** Add `responses={}` maps mirroring the migration-route pattern (which declares X-Netcanon-Job-Status); give /sanitize `response_class=PlainTextResponse` + explicit 200 content documenting both modes and the substitution-count header.

### 52. [MINOR] `request_has_overrides_or_profile` docstring still claims bare requests get "plain run_plan … unchanged" — missed API-6 site
**Where:** `netcanon/api/routes/_migration_helpers.py:173` · **Lens:** 06-api-contract · **Confidence:** confirmed
**Fix:** One-line correction: bare requests get auto port-name translation via `run_plan_with_overrides(port_rename_map={})` (migration.py doesn't even import bare run_plan).

### 53. [MINOR] Device-profile docs say type_key "must match a loaded definition" but create/update never validate — typo'd profile 201s, fails days later at backup time
**Where:** `netcanon/api/routes/device_profiles.py:77` (docs: `models/device_profile.py:33/113`) · **Lens:** 06-api-contract · **Confidence:** confirmed (reproduced)
**Fix:** Validate against `get_definitions` with a 422 + loaded-keys list (matching POST /backups), or soften the two docstrings to "validated when a backup runs".

### 54. [MINOR] Publish-time gates re-verify ci.yml only — pii-guard.yml has no publish-time backstop
**Where:** `.github/workflows/pypi-publish.yml:136` (also docker :138, msi :149) · **Lens:** 07-build-release-ci · **Confidence:** confirmed
**Failure:** The T0-4 "holds even if the merge gate was bypassed" property is false for the one check whose failure already cost a history rewrite; ci.yml contains no PII scan and no test replicates it.
**Fix:** Add a second gh-api query asserting the latest pii-guard run for `$head_sha` succeeded (same poll/fail-closed shape) in all three publish workflows — or move the greps into ci.yml as a job.

### 55. [MINOR] MSI workflow_dispatch lacks the PKG-5 refuse-non-tag guard its siblings gained in #288
**Where:** `.github/workflows/desktop-msi-publish.yml:114` · **Lens:** 07-build-release-ci · **Confidence:** confirmed
**Failure:** `inputs.tag` is checked out and released without verifying it names a tag; a version-ish branch input ships an MSI from a mutable tip AND action-gh-release creates the tag at default-branch HEAD — artifact and tag pointing at different commits.
**Fix:** After checkout: `git show-ref --verify --quiet "refs/tags/${TAG_RAW}"` (env-passed), fail with ::error:: otherwise.

### 56. [MINOR] MSI dependency closure unpinned — the audit hash-lock covers the Docker image only
**Where:** `.github/workflows/desktop-msi-publish.yml:205` · **Lens:** 07-build-release-ci · **Confidence:** confirmed (one detail corrected: no WiX auto-download; instead python-msilib/lief resolve live and WRITE the MSI database)
**Fix:** Maintain a Windows/CPython-3.13-resolved constraints file for the desktop-build extra and install with `-c`; delete the stale WiX comment.

### 57. [MINOR] Complexity-ratchet marker is dodgeable: three ruff-legal noqa spellings suppress C901 without matching the counted literal
**Where:** `tests/unit/test_complexity_ratchet.py:36` · **Lens:** 08-test-quality · **Confidence:** confirmed (empirically, repo's ruff)
**Fix:** Count via regex `#\s*noqa:?[^\n]*\bC901\b`; also assert no file-level `# ruff: noqa` names C901/is bare and per-file-ignores has no C90 entry.

### 58. [MINOR] Three junos real-fixture tests (incl. the #294 EX4550 guard) read fixtures via CWD-relative paths
**Where:** `tests/unit/migration/test_juniper_junos.py:1230` (also 975, 986) · **Lens:** 08-test-quality · **Confidence:** confirmed (reproduced from tests/)
**Fix:** Switch to the `Path(__file__).resolve().parents[2]` anchor every sibling uses.

### 59. [MINOR] E2E stored-config compat-warning test self-skips unless test_backup_form.py ran first — order-dependent coverage, no vacuous-skip guard
**Where:** `tests/e2e/test_migrate_page.py:476` · **Lens:** 08-test-quality · **Confidence:** confirmed (airtight source chain)
**Fix:** Seed a .cfg deterministically in the test via the backups API/FakeCollector and delete the skip; or env-gate the skip into a hard failure under CI (existing vacuous-skip-guard pattern).

### 60. [MINOR] Junos render byte-order not a fixpoint: double-pass output drift (settles on pass 2)
**Where:** `netcanon/migration/codecs/juniper_junos/parse.py:497` · **Lens:** 11-codec-deepdive · **Confidence:** confirmed (reproduced on 2 committed fixtures)
**Failure:** Late-materialised VRF-loopback stubs sort into place only on re-parse; lags order follows member-port alphabetical order → render(parse(render(parse(x)))) ≠ render(parse(x)). Semantics identical; diff noise for re-sanitize/version-controlled output; violates the render-preserves-tree-order doctrine.
**Fix:** Normalise at parse end: sort `intent.lags` by name; route late stubs through the same deterministic ordering (mikrotik `_sort_interfaces` pattern).

### 61. [MINOR] MikroTik v6 NTP dialect gate self-destructs on second sanitize (documented in-code; cheap #297-style fix)
**Where:** `netcanon/migration/codecs/mikrotik_routeros/render.py:150` · **Lens:** 11-codec-deepdive · **Confidence:** confirmed (reproduced on committed fixture; borderline intentional — single-pass correctness is documented)
**Failure:** Render writes no RouterOS version header, so pass 2 sees `source_version==''` and emits the v7 `servers=` form — the exact output #299 avoids on a 6.x device. MikroTik is now the only codec whose render CONSUMES source_version while being the one left out of #297's echo.
**Fix:** Emit a `# … by RouterOS {source_version}` header on same-vendor render when set (parse already reads it) — makes the gate idempotent.

### 62. [MINOR] Five stale `_extract_version` parse docstrings contradict #297/#299 behaviour
**Where:** `netcanon/migration/codecs/cisco_nxos/parse.py:484` (+ iosxr :313, aoscx :418, vyos :145, mikrotik :238) · **Lens:** 11-codec-deepdive · **Confidence:** confirmed
**Failure:** All five claim render "does not echo / synthesises fresh" — false since #297; mikrotik's "informational only" is false since #299 (it gates the NTP dialect). A maintainer trusting these could remove extraction and silently break both.
**Fix:** Update the five docstrings ("echoed on same-vendor render (#297)" / "gates the v6 NTP render dialect (#299)"). Same truth-maintenance class as #300.

### 63. [MINOR] Same-vendor version-echo gate copy-pasted 5× with hardcoded vendor literals; the source_vendor==vendor_id pairing is unenforced
**Where:** `netcanon/migration/codecs/cisco_nxos/render.py:50` (+ iosxr, aoscx, vyos, mikrotik) · **Lens:** 10-architecture · **Confidence:** confirmed
**Failure:** Each copy must compare against `capabilities.vendor_id`, NOT the registry name (cisco_iosxe_cli stamps `cisco_iosxe`, fortigate_cli stamps `fortigate`); the next copy that uses the registry name never fires, and no round-trip test can catch it (source_version is comparator-excluded).
**Fix:** One shared `same_vendor_version(tree, *, vendor_id, default)` helper in `_helpers.py`; add a registry-wide test pinning `parse(sample).source_vendor == capabilities.vendor_id`.

### 64. [MINOR] 11 identical iter_xpaths overrides import the shared walker through a sibling vendor codec; README teaches the legacy path
**Where:** `netcanon/migration/codecs/README.md:405` (11 codec.py files) · **Lens:** 10-architecture · **Confidence:** confirmed
**Failure:** The walker was relocated to `canonical/xpath_walker.py` explicitly to escape the vendor package, yet every codec's capability classification still imports through the full cisco_iosxe_cli package, and the README instructs codec #13 to copy the deprecated edge.
**Fix:** Add the canonical branch to `CodecBase.iter_xpaths` (runtime import from `...canonical.xpath_walker`; keep the flat-dict fallback), delete the 11 overrides, keep the re-export for compat, fix the README.

### 65. [MINOR] SECURITY.md omits the v0.5.1 security controls (SEC-9 CSP, SEC-5 _drain caps) despite its own update contract
**Where:** `SECURITY.md:4` · **Lens:** 09-docs-truth · **Confidence:** confirmed (grep-proven)
**Fix:** Add a CSP subsection (default policy, /docs-scoped CDN variant, 'unsafe-inline' rationale — currently only in a main.py comment) and a sentence on the _drain caps in the SSH hardening rows.

### 66. [MINOR] CHANGELOG v0.5.1 entry asserts the `strip_unsupported` mechanism that v0.5.2/#292 established never existed
**Where:** `CHANGELOG.md:150` · **Lens:** 09-docs-truth · **Confidence:** confirmed
**Fix:** Append a bracketed erratum to the 0.5.1 API-7 bullet pointing at the 0.5.2/#292 correction (Keep-a-Changelog entries stay historical; inline erratum is the standard remedy).

---

## Refuted (dropped)

- **MSI ProductVersion collision (07-F5):** premise facts real (`${tag%%-*}` collapses rc/final; constant UpgradeCode) but the failure doesn't occur — cx_Freeze writes an **inclusive**-VersionMax Upgrade row (attributes 513) with REMOVEOLDVERSION + resequenced RemoveExistingProducts, so an equal-version rc is cleanly removed by the final's install. The "FindRelatedProducts excludes equal versions" default the finder cited is WiX authoring behavior, not applicable here. Residual is cosmetic (ARP shows final-style version while the rc is installed).

## Themes

1. **Hardened-path / un-hardened-sibling (the dominant recurrence, again).** The same fix keeps landing on one path while its twin stays exposed: CONC-5 pending-save on manual but not scheduled jobs (#26); cap-in-lock on schedules but not device profiles (#44); snapshot-under-lock in the scheduler but not delete_device_profile (#43); /plan auto-translate fixed but not the four per-pane endpoints (#16); CLI read guarded, write not (#46); API-3/API-6 half-fixed (#46, #52); PKG-5 non-tag guard on 2 of 3 publish workflows (#55); #297 version echo on 4 of 5 version-aware codecs (#61); verify_host_key atomic but the paramiko persist not (#2); egress unwraps ipv4_mapped but not the transition formats the sanitizer already handles (#42). Recommendation: when fixing a race/contract bug, grep for the sibling shape before closing the PR — this review's biggest single yield.
2. **Rename/transform orchestrators walk an incomplete canonical-reference set and misreport.** The canonical tree has cross-references (vxlan source_interface/vlan_id, vrrp track_interfaces, dot1q_vlan, canonical-named SVIs, junos group_content) that the rename sweeps miss (#3, #4, #5, #18), plus bookkeeping that diverges from the tree (`applied` claims renames that didn't survive, `dropped` over/under-reports — #6, #17, #19, #48, #49). The cross-mesh can't see any of it because it runs bare parse→render with no translation. A "rename-sweep completeness" test enumerating every interface-name-typed and vlan-id-typed field in intent.py would close the class.
3. **Honesty-machinery blind spots at the seams.** Declared-supported-but-dropped or comparator-invisible surfaces: SVI IPv6 (#10), MikroTik SNMPv3 algorithm substitution (#23), DHCP lease-time undeclarable for lack of walker vocabulary (#24), VRRP VIP prefix (#22), fortigate nested config-ipv6 (promotion #2). Meanwhile the fidelity ratchet itself covers 41% of pairs (#14), excludes same-vendor and render-failed cells (#36, #37), and doesn't pin its own denominator (#35). The walker/matrix design is sound; its VOCABULARY and the mesh's COVERAGE are what lag.
4. **Docs and declarations trail shipped behavior — in both directions.** Over-promise (unsafe direction): Tier-1 (#1), CAPABILITIES tables (#15), "pass None to clear" (#12), type_key "must match" (#53). Under-promise (wasteful direction): CI policy docs (#39), VyOS provisional (#40), validation banner (#41), stale version/echo docstrings (#62, #52), the iosxe_cli syslog matrix reason that's false about its own render (promotion #1). SECURITY.md and CHANGELOG have inventory gaps (#65, #66). Truth-maintenance passes like #300 work — they just need to run wider.
5. **Quadratic scans on growing lists in parse hot paths.** One shape, five sites: list-membership or `next()` scans against a list that grows per iteration (#11, #30, #31, #32, #33). All reachable via POST /plan (or /configs/diff) with small crafted bodies under the size caps; all one-line set/dict fixes. Worth a lint-ish sweep for `next((x for x in intent.<list>` inside loops.
6. **Junos depth on non-.set inputs; MikroTik combined-token forms.** The corpus being all .set files leaves block-form structurally untested (#7, and #8's numeric members are common in exactly the pre-ELS configs #294 targets); MikroTik's own renderer emits forms its parser can't read back (#9, #61). Both codecs deserve a fixture-shape audit: one committed block-form junos fixture with brackets + numeric members, one mikrotik fixture with `%`-gateways.

## What's healthy

- **Error paths:** 18,252 mutated parses across all 12 codecs → zero crashes; 332 render probes → zero non-RenderError failures; XML codecs reject entity bombs; pipeline funnels every stage failure into `MigrationJob.failed`; SSH runner and credentials fail closed.
- **Prior remediation integrity:** every 2026-07-03 MAJOR/MINOR verified fixed in-tree (job_id pinning, fail-closed Docker entrypoint, write-only schedule creds, _drain caps, egress unspecified-address, CONC-3/5/6/7, CSP); v0.5.2/v0.5.3 codec fixes (#294–#299) all verified sound with direct tests — the defects found are in their *surroundings*, not the fixes.
- **Guard architecture:** walker-completeness, sanitizer partition, ship-before-wire two-sided invariants, vacuous-skip guards, CHANGELOG/lock drift guards all intact; the release pipeline has no untrusted-event publishes, no template injection, SHA-pinned actions, fail-closed ancestry/CI gates.
- **Finder precision:** 68/69 findings survived independent adversarial verification (1 refuted), and 30+ were confirmed by live reproduction — the verify-first culture is working.
- **The one HIGH is a documentation defect,** not a runtime one, and the worst runtime findings all have small, local, well-understood fixes.

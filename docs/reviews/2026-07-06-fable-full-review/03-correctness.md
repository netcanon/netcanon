# Lens 03 — Correctness & edge-cases (non-codec core)

Target: main @ 8598d74 (v0.5.3). Scope: `canonical/{transforms,port_names,vlan_names,local_user_names,snmp_names,snmpv3_user_names,xpath_walker}.py`, `services/migration_pipeline.py`, `services/migration_validate.py`, `api/routes/{migration,_migration_helpers}.py`.

**Summary:** 9 findings, all reproduced live (`py -c` / small scripts, no pytest, no mesh). Dominant theme: the rename orchestrators walk an *incomplete* set of canonical-tree references and report outcomes that diverge from what actually happened to the tree. Two MAJOR (vlan rename misses `dot1q_vlan` + `vxlan_vnis[].vlan_id`; port rename-into-dropped-name silently deletes the renamed interface), five MEDIUM, two MINOR. Notably, four of the five per-pane API endpoints still carry the exact API-1 trap the 2026-07-03 review fixed on `/plan` — a fresh instance of that review's "hardened-path / un-hardened-sibling" theme. Non-findings verified along the way: out-of-range VLAN ids are already wrapped into clean `ParseError`s by all probed codecs; walker granularity gaps (DHCP-pool/EVPN sub-fields) are consciously exempted in `test_walker_completeness.py`; render-side `project_vlan_to_switchport` mutation cannot leak (every production path parses fresh per render).

---

### F1 — MAJOR — `translate_vlan_ids` misses `dot1q_vlan` and `vxlan_vnis[].vlan_id`; rename/drop produces broken configs

- **File:** `netcanon/migration/canonical/vlan_names.py:249-296` (Pass 2 walks only `access_vlan`, `trunk_native_vlan`, `voice_vlan`, `trunk_allowed_vlans`)
- **Confidence:** confirmed (unit + end-to-end repro)
- **Failure scenario:** Source config with a routed sub-interface and a VNI mapping, `vlan_rename_map={10: 20}` via `POST /plan` or `/plan/vlans`:
  - `interface GigabitEthernet0/0/1.10 / encapsulation dot1Q 10` renders **unchanged** (`encapsulation dot1Q 10`) while `vlan 10 → vlan 20` and `switchport access vlan 10 → 20` are rewritten. Job `completed`, zero warnings. The sub-interface now tags a VLAN that no longer exists on the device — L3 on that VLAN is dead on deploy. (E2E reproduced, cisco_iosxe_cli → cisco_iosxe_cli.)
  - `CanonicalVxlan.vlan_id` stays 10. `intent.py:689` explicitly documents the invariant "Matches `CanonicalVlan.id` … codecs that emit VNI mappings should keep both records in sync". The NX-OS renderer unions `{v.id for v in tree.vlans} | set(vni_by_vlan)` (`cisco_nxos/render.py:127-128`), so the rename emits **both** `vlan 20` and a resurrected `vlan 10` carrying the `vn-segment` — the L2VNI stays bound to the old VLAN. A drop (`{10: None}`) resurrects the dropped VLAN the same way.
- **Fix:** In Pass 2, rewrite `iface.dot1q_vlan` exactly like `access_vlan` (rename → renumber; drop → warn, leave or clear). Add a Pass 3 over `intent.vxlan_vnis`: rename `vlan_id` per the map; on drop, remove the VNI record (VNI without its VLAN is meaningless) with a warning. Mention both fields in the module docstring's touched-fields list.

### F2 — MAJOR — port rename map `{A: "B", B: None}` deletes BOTH interfaces; `applied` claims the rename landed

- **File:** `netcanon/migration/canonical/port_names.py:516-517` (strip runs after the rename sweep) + `556-557` (`_strip_dropped_ports` filters interfaces by **post-rename** name against a drop set keyed by **source** names)
- **Confidence:** confirmed (repro)
- **Failure scenario:** Operator retires old port B and renames A to take over its name — `port_rename_map={"GigabitEthernet1/0/1": "GigabitEthernet1/0/2", "GigabitEthernet1/0/2": None}`. The rename pass renames A's interface object to `…1/0/2`; the strip pass then removes every interface whose *current* name is in the dropped set — which now matches the renamed A. Result: `applied={A: B}`, `dropped=[B]`, **zero surviving interfaces**, no warning. The job reports a rename that is absent from the rendered output; A's entire interface config silently vanishes. This is the silent-loss class the repo treats as closed.
- **Fix:** Run `_strip_dropped_ports(intent, user_drops)` **before** the rename sweep (user drops are keyed by source names and are independent of renames), then keep the post-sweep strip only for the auto-drop set accumulated by `strip_unmappable`. Alternatively track dropped *objects*, not names.

### F3 — MEDIUM — empty-string key `{"": None}` in `port_rename_map` silently deletes every gateway-only static route and interface-less DHCP pool

- **File:** `netcanon/migration/canonical/port_names.py:337-341` (no key validation — contrast `local_user_names.py:144-149`) + `572-577` (strip filters `r.interface not in dropped` / `p.interface not in dropped` without a truthiness guard; `interface` defaults to `""`)
- **Confidence:** confirmed (repro)
- **Failure scenario:** `POST /plan` with `port_rename_map={"": null}` (pydantic accepts the empty key). `dropped_set = {""}`; the strip pass deletes **all** static routes whose `interface == ""` — i.e. every normal next-hop-gateway route, including the default route — and every DHCP pool not bound to an interface. Interfaces/VLANs/LAGs are unaffected (non-empty names), so the output looks plausible; job `completed`, `warnings=[]`, `port_drops=[""]`. Repro: 2 gateway routes + 1 pool → 0 and 0.
- **Fix:** Validate map keys in `translate_port_names` like the sibling orchestrators (skip + warn on empty/blank source names). Belt-and-braces: guard the strip filters with `r.interface and r.interface in dropped`.

### F4 — MINOR — snmpv3 rename collision: dropped record still reported in `applied`, missing from `dropped`

- **File:** `netcanon/migration/canonical/snmpv3_user_names.py:212` (`result.applied[u.name] = decision` recorded) vs `213-223` (collision `continue` drops the record without touching `applied`/`dropped`)
- **Confidence:** confirmed (repro)
- **Failure scenario:** Users `[monitor, legacy]`, map `{"legacy": "monitor"}`. `legacy` is dropped first-wins, warning fires — but `job.snmpv3_user_renames == {"legacy": "monitor"}` (a rename that did not survive) and `job.snmpv3_user_drops == []` (a user whose auth/priv config was erased is not listed). UI panes reading applied/drops render a state contradicting the output.
- **Fix:** Move the `result.applied[...]` assignment after the collision check passes; append the collision-dropped source name to `result.dropped` (or a dedicated entry) so the report matches the tree.

### F5 — MEDIUM — `project_switchport_to_vlan` trunk-all stamp is interface-order-dependent and non-idempotent

- **File:** `netcanon/migration/canonical/transforms.py:159-178` (trunk-all branch iterates `intent.vlans` *at that moment in the interface loop*, while `_vlan()` keeps synthesizing records for later interfaces)
- **Confidence:** confirmed (repro)
- **Failure scenario:** Trunk-all port (`switchport trunk allowed vlan 1-4094`) declared **before** an access port whose VLAN has no top-level `vlan` stanza (common in partial captures / forum pastes): the access VLAN is synthesized *after* the trunk-all stamp, so its `tagged_ports` misses the trunk. Repro: trunk-first → `vlan500.tagged_ports == []`; access-first → `['Gi1/0/1']`. On a VLAN-centric target (Aruba AOS-S) the uplink doesn't carry VLAN 500 → blackhole. Also violates the module contract "idempotent — safe to call twice": a second call adds the trunk to the synthesized VLAN (repro: first ≠ second).
- **Fix:** Two-pass: first materialize all `_vlan()` records (access, native, explicit trunk vids) without membership stamping, then run the membership pass — trunk-all stamps against the final VLAN set. Same-input-same-output regardless of interface order, and idempotent.

### F6 — MEDIUM — port rename onto an existing/colliding name produces duplicate interface stanzas, no merge, no warning

- **File:** `netcanon/migration/canonical/port_names.py:375-379` (user-map path applies blindly; no post-sweep duplicate detection anywhere)
- **Confidence:** confirmed (end-to-end repro)
- **Failure scenario:** `port_rename_map={"GigabitEthernet1/0/1": "GigabitEthernet1/0/2"}` while `…1/0/2` exists: rendered output contains **two** `interface GigabitEthernet1/0/2` stanzas with conflicting config (`access vlan 10` vs `20`), job `completed`, `warnings=[]`. Pasted onto a device, the second stanza silently overwrites the first — the uplink's config lands on the wrong port. Same for two sources mapped to one target, and the duplicates propagate into `vlans[].tagged_ports` lists. Every sibling orchestrator (vlan/local-user/snmpv3) detects target collisions and merges + warns; ports — the highest-stakes pane — has zero collision handling.
- **Fix:** After the rename sweep, detect resolved-name duplicates among `intent.interfaces` (and lag names); emit a warning naming both sources, and either refuse the colliding user entry or merge deterministically. Cheap version: warn only — that alone lifts it out of the silent class.

### F7 — MEDIUM — `/plan/vlans`, `/plan/local_users`, `/plan/snmp`, `/plan/snmpv3` still have the API-1 trap fixed on `/plan`: verbatim source-vendor interface names

- **File:** `netcanon/api/routes/migration.py:410-413` (vlans), `473-476` (local_users), `537-540` (snmp), `601-604` (snmpv3) — all leave `port_rename_map=None`, which disengages the port-name translator entirely
- **Confidence:** confirmed (repro; behavior contrast with `/plan`)
- **Failure scenario:** Same body (`cisco_iosxe_cli → juniper_junos`, `vlan_rename_map={20: 30}`) posted to `/plan` renders `set interfaces ge-1/0/2 …`; posted to `/plan/vlans` renders `set interfaces GigabitEthernet1/0/2 …` — invalid Junos names. The `/plan` comment (migration.py:265-274) states the post-v0.5.0 contract: "auto translation is the default for every non-port-map request — the API-1 trap from the 2026-07-03 review"; the four non-port pane endpoints were left on the old behavior (the web UI only calls `/plan`, so this bites API/automation clients using the documented per-pane surface). This is a textbook residual of that review's hardened-path/un-hardened-sibling theme.
- **Fix:** In each of the four handlers pass `port_rename_map=(body.port_rename_map if body.port_rename_map is not None else {})` — the same expression `/plan` uses (callers may legitimately post a port map alongside, today it is silently ignored which the docstring does document; minimum fix is `port_rename_map={}`). Add a parity integration test asserting per-pane renders contain no source-vendor names.

### F8 — MEDIUM — vlan rename + existing SVI renders TWO SVIs with the same IP (stale `Vlan10` + synthesized `Vlan20`)

- **File:** interaction of `vlan_names.py` (SVIs deliberately not renamed, module docstring:51-57) with `transforms.py:390-454` (`synthesize_svis_from_vlan_l3`) and the parse-side fold `transforms.py:308-388` (`project_svi_to_vlan`)
- **Confidence:** confirmed (end-to-end repro)
- **Failure scenario:** Config with `vlan 10` + `interface Vlan10 / ip address 10.1.1.1 255.255.255.0`, `vlan_rename_map={10: 20}`, SVI-model target (cisco_iosxe_cli / arista_eos): parse folds the SVI IP onto VLAN 10; the rename moves the record (with folded L3) to id 20; render sees VLAN 20 with L3 but no `Vlan20` interface and synthesizes one — while the un-renamed `Vlan10` interface also renders. Output: `interface Vlan10` **and** `interface Vlan20`, both `ip address 10.1.1.1 255.255.255.0` — IOS rejects the overlapping subnet; the renamed-away VLAN's SVI is resurrected. Job `completed`, zero warnings. Before `synthesize_svis_from_vlan_l3` existed, the failure was only a stale name (the documented "compose the port map" limitation); the synthesis upgraded it to an actively invalid config.
- **Fix:** In `translate_vlan_ids`, when renaming/dropping id N, detect an interface named `Vlan<N>` (the same `_SVI_NAME_RE` transforms.py uses) and emit a warning telling the operator to add the SVI to the port map (cheap, honest). Better: strip the folded `ipv4_addresses` duplication by renaming the SVI interface alongside the VLAN record when its name matches the canonical `Vlan<N>` pattern — the "vendor-specific SVI naming" objection doesn't apply to the canonical spelling the synthesizer itself uses.

### F9 — MINOR — rename-map entries matching nothing: vlan docstring promises a warning that never fires; port `dropped` over-reports

- **File:** `netcanon/migration/canonical/vlan_names.py:117-119` (docstring: "Mapping a VLAN ID that doesn't exist in `intent.vlans` → warning + no-op") vs `203-244` (no existence check, no warning — repro: `{999: 500}` → `warnings=[]`); `port_names.py:530` (`dropped=sorted(dropped_set)` reports user-supplied names never present in the tree — repro: `{"GONE": None}` → `dropped=['GONE']`, and typo'd rename keys are silently ignored)
- **Confidence:** confirmed (repro)
- **Failure scenario:** Operator typos a VLAN id or port name in an override map: the entry no-ops with no signal (vlan/ports), and `job.port_drops` claims a drop that never happened — the UI displays a drop for a nonexistent port while the intended one survives. `local_user_names.py:177-183` and `snmpv3_user_names.py:190-195` already warn on not-found sources; vlan and port panes are the inconsistent pair (and vlan's docstring promises the warning).
- **Fix:** vlan: add the promised existence check over `{v.id for v in intent.vlans}` ∪ referenced interface vids, warn per miss. port: warn when a `str_map`/drop key matches no name encountered during the sweep, and only report drops that removed something.

---

## Verified non-findings (do not re-hunt)

- **Out-of-range VLAN ids in source configs** (`switchport access vlan 4095`, `interface Vlan9999`): cisco_iosxe_cli / arista_eos / cisco_nxos all wrap the pydantic `ValidationError` into a clean `ParseError` ("input could not be represented as a valid canonical config"). Guard exists.
- **Walker granularity gaps** (DHCP-pool sub-fields, EVPN-Type5 sub-fields, RADIUS ports): consciously tracked as `KNOWN_GAP` exemptions in `tests/unit/migration/test_walker_completeness.py`; walker's unconditional yields (`/lags/lag/mode`, `/vxlan-vnis/udp-port`) only over-report loss — the intended pessimistic bias.
- **Render-side mutation by `project_vlan_to_switchport(tree)`** (arista/iosxe_cli/junos render): contradicts the non-mutation rationale documented on `synthesize_svis_from_vlan_l3`, but every production path (`run_plan`, `tools/sanitize.py`) and the mesh runner (`tools/run_full_mesh.py:655`) parses fresh per render — no observable leak today. Worth a comment-level cleanup only.
- **`_natural_port_sort_key` mixed-type comparison**: safe — `re.split(r"(\d+)")` guarantees strict str/int alternation starting with str, and `int()` accepts every `\d`-matched Unicode digit.
- **vlan swap/chain renames** (`{10:20, 20:10}`, `{10:20, 20:30}`): applied atomically from original values in both Pass 1 and Pass 2 — correct.

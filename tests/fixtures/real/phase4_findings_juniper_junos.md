# Phase 4b — `juniper_junos` source findings

Source codec: `juniper_junos` (`netcanon/migration/codecs/juniper_junos/`).
Reconciled from `tests/fixtures/real/_phase4_runs/latest.json` (run
`2026-05-03T20:35:17Z`) against the seven cross-vendor expectation YAMLs
under `tests/fixtures/cross_vendor_expectations/juniper_junos__*.yaml`.

**Total CODEC_BUGs: 26** (largest per-source slice in the mesh; see
`PHASE4_RECONCILIATION.md` distribution row).

| Target              | CODEC_BUG | Fixtures involved                                              |
|---------------------|----------:|----------------------------------------------------------------|
| arista_eos          |         4 | `ksator_labmgmt_qfx5100`, `kitchen_sink`                       |
| aruba_aoss          |         5 | `batfish_evpntype5_router1`, `ksator_labmgmt_qfx5100`, `kitchen_sink` |
| cisco_iosxe_cli     |         5 | `ksator_labmgmt_qfx5100`, `kitchen_sink`                       |
| fortigate_cli       |         5 | `kitchen_sink`                                                 |
| mikrotik_routeros   |         3 | `kitchen_sink`                                                 |
| opnsense            |         4 | `kitchen_sink`                                                 |
| **Total**           |    **26** |                                                                |

## Bucket totals (A real bug / B stale-YAML / C acceptable lossy)

| Bucket                                       | Count |
|----------------------------------------------|------:|
| **A — real codec bug** (parse or render gap) |    14 |
| **B — stale YAML** (disposition should be `lossy`/`unsupported`) |     8 |
| **C — acceptable lossy** (cosmetic, methodology) |     4 |

Bucket-A locus split: Junos parser-side gaps (vlans[].ipv4_addresses
from irb→l3-interface, vlans[].tagged_ports projection): 3.  Target-side
parser/render gaps: 11 (fortigate.snmp.*, fortigate.domain,
mikrotik.snmp.*, opnsense.snmp.*, aruba lag/switchport/trunk loss,
arista lag drop).

---

## Per-target sections

### juniper_junos → arista_eos (4)

| Fixture | Field | Drift detail | Bucket | Recommendation |
|---|---|---|---|---|
| `ksator_labmgmt_qfx5100_junos173.set` | `interfaces[].lag_member_of` | source `'ae1'` on et-0/0/48..et-1/0/49; target `None` | A (target render) | Arista render: zero-based `ae<N>` → one-based `Port-Channel<N+1>` mesh missing channel-group emit on member ifaces (`netcanon/migration/codecs/arista_eos/render.py`). YAML says `disposition: good`. |
| `ksator_labmgmt_qfx5100_junos173.set` | `lags` | source 2 LAGs (`ae0`,`ae1`); target `[]` ("all 2 lags dropped") | A (target render) | Arista render drops the LAG list entirely on this fixture even though it preserves it for `kitchen_sink` (where it merely renames). Likely conditional-emit gate (`render.py` LAG block) requires every member iface to also be present in the rendered iface list, which fails when the qfx port-name regex disagrees. |
| `kitchen_sink.set` | `lags` | source 2 LAGs; target 2 LAGs but `name` drift `ae0→Port-Channel0`, `ae1→Port-Channel1` | C (cosmetic rename) | Expected vendor rename (zero-based → one-based per YAML note). YAML says `disposition: good`; the comparator counts the rename as drift. Either flip YAML to `lossy` (with name-rename note) or teach the comparator to treat structural rename as preserved. |
| `kitchen_sink.set` | `routing_instances[].name` | count drift `3 → 2` (`virtual-router` instance `RTR_C` dropped) | B (stale YAML) | Arista has no `virtual-router` analogue per YAML note ("instance-type=virtual-router … is unsupported on Arista — drops with banner"). YAML lists `routing_instances[].name: good` but the parent `routing_instances: lossy`. Tighten name disposition to `lossy` to match the documented drop-with-banner behaviour. |

### juniper_junos → aruba_aoss (5)

| Fixture | Field | Drift detail | Bucket | Recommendation |
|---|---|---|---|---|
| `batfish_evpntype5_router1_junos2541.set` | `vlans[].ipv4_addresses` | source `[]` for VLAN100/200/300/400; target carries `172.16.x.x/24` | A (Junos parser gap) | Junos parser does NOT absorb `irb.<unit>` IRB unit IPs back into the VLAN with `l3-interface irb.<unit>`. Locus: `netcanon/migration/codecs/juniper_junos/parse.py` (no `tagged_ports`/`ipv4_addresses` projection — verified with grep). Aruba round-trip exposes it because Aruba does the projection on render+reparse. |
| `ksator_labmgmt_qfx5100_junos173.set` | `interfaces[].switchport_mode` | source `'trunk'` on `ae0`/`ae1`; target `None` | A (target render) | Aruba render does not emit switchport mode on trunk LAG members. YAML expects `good`. Fix locus: aruba_aoss render path for LAG/Trk interfaces. |
| `ksator_labmgmt_qfx5100_junos173.set` | `interfaces[].trunk_allowed_vlans` | source `[1,2,3,…+4091]` on `ae0`/`ae1` ("vlan members all"); target `[]` | A (target render) — and methodology cofactor | Aruba render drops the all-VLANs trunk allow list. Two co-issues: (1) the Junos parser blowing `vlan members all` into `range(1,4095)` is reasonable but creates a structurally large list; (2) the aruba renderer doesn't emit it. Fix aruba render OR teach Junos parser to keep `all` as a sentinel. |
| `ksator_labmgmt_qfx5100_junos173.set` | `interfaces[].lag_member_of` | source `'ae1'` on et-0/0/48..et-1/0/49; target `None` | A (target render) | Aruba render not emitting LAG membership on physical members. YAML says `good`. Same fix-locus as Arista row above (different codec but same surface). |
| `kitchen_sink.set` | `vlans[].ipv4_addresses` | source `[]` on TENANT_A_DATA/TRANSIT; target `172.16.100.1/24`, `172.16.200.1/24` | A (Junos parser gap) | Same as the batfish row — Junos parser does not project `irb.<unit>` family-inet addresses onto `vlans[].ipv4_addresses` via `l3-interface` linkage. Single fix-locus. |

### juniper_junos → cisco_iosxe_cli (5)

| Fixture | Field | Drift detail | Bucket | Recommendation |
|---|---|---|---|---|
| `ksator_labmgmt_qfx5100_junos173.set` | `interfaces[].lag_member_of` | source `'ae1'`; target `'Port-channel1'` | C (cosmetic rename) | Vendor-correct zero-based → one-based mesh (Junos `ae<N>` ↔ Cisco `Port-channel<N>` per YAML note). Comparator flags the string mismatch as CODEC_BUG. YAML says `good`; tighten to `lossy` or absorb rename in comparator. |
| `ksator_labmgmt_qfx5100_junos173.set` | `vlans[].id` | count drift `16 → 4094` | B (stale YAML — `vlan members all` semantics) | Source has `set interfaces ae0/ae1 unit 0 family ethernet-switching vlan members all` which Junos parser expands to `range(1,4095)`; cisco renders all 4094 vlans into the vlan-database, parses back, balloons the list. YAML says `vlans[].id: good`; should be `lossy` for any source carrying `vlan members all`. Same root cause as the trunk_allowed_vlans drop on aruba above. |
| `ksator_labmgmt_qfx5100_junos173.set` | `lags` | source 2 LAGs; target 2 LAGs but `name` rename `ae0→Port-channel0`, `ae1→Port-channel1` | C (cosmetic rename) | Same as Arista lags row — vendor-correct rename flagged by comparator. YAML `lags: good` is honest about everything except the name; comparator should treat structural rename as preserved (or YAML flips to lossy). |
| `kitchen_sink.set` | `vlans[].tagged_ports` | source `[]` on USERS/VOICE; target `['ge-0/0/1']` | A (Junos parser gap) | Junos parser does not project per-iface `vlan members <NAME>` onto the named VLAN's `tagged_ports`. Cisco target codec performs the projection on its render/parse. Locus: `netcanon/migration/codecs/juniper_junos/parse.py` — needs a post-pass after L2 vlan-members resolution (analogous to lag_state materialisation already present at `parse.py:392-426`). |
| `kitchen_sink.set` | `lags` | same as ksator (rename `ae<N>→Port-channel<N>`) | C (cosmetic rename) | See above. |

### juniper_junos → fortigate_cli (5)

| Fixture | Field | Drift detail | Bucket | Recommendation |
|---|---|---|---|---|
| `kitchen_sink.set` | `domain` | source `'lab.example.net'`; target `''` | A (target parser gap) | Fortigate render emits `set domain "<value>"` under `config system dns` (`render.py:443-450`). Fortigate parse only reads `domain` inside DHCP pool blocks (`parse.py:706-708`); no top-level `config system dns` → `intent.domain` wire-up. One-shot fix. |
| `kitchen_sink.set` | `snmp.community` | source `'public'`; target dropped | A (target parser/render gap) | Fortigate codec lacks a top-level SNMP wire-up for the `community` field. YAML says `good`. Same root cause for the next 3 rows. |
| `kitchen_sink.set` | `snmp.location` | source `'Synthetic Lab Rack 7'`; target dropped | A (target parser/render gap) | Same — fortigate render of `snmp.location` missing or asymmetric with parser. |
| `kitchen_sink.set` | `snmp.contact` | source `'noc@example.net'`; target dropped | A (target parser/render gap) | Same. |
| `kitchen_sink.set` | `snmp.trap_hosts` | source list of trap hosts; target dropped | A (target parser/render gap) | Same — `juniper_junos__fortigate_cli.yaml` says `good` for trap_hosts. Investigate fortigate `config system snmp sysinfo` / `config system snmp community` round-trip. |

### juniper_junos → mikrotik_routeros (3)

| Fixture | Field | Drift detail | Bucket | Recommendation |
|---|---|---|---|---|
| `kitchen_sink.set` | `snmp.community` | source `'public'`; target dropped | A (target parser/render gap) | YAML `good`. Locus: mikrotik_routeros codec — `/snmp` round-trip not preserving community. |
| `kitchen_sink.set` | `snmp.location` | source `'Synthetic Lab Rack 7'`; target dropped | A (target parser/render gap) | Same. |
| `kitchen_sink.set` | `snmp.contact` | source `'noc@example.net'`; target dropped | A (target parser/render gap) | Same. (`snmp.trap_hosts` correctly classified `lossy` here per YAML — RouterOS one-target limit.) |

### juniper_junos → opnsense (4)

| Fixture | Field | Drift detail | Bucket | Recommendation |
|---|---|---|---|---|
| `kitchen_sink.set` | `snmp.community` | source `'public'`; target dropped | A (target parser/render gap) | YAML `good`. OPNsense SNMP wire-up gap. |
| `kitchen_sink.set` | `snmp.location` | source `'Synthetic Lab Rack 7'`; target dropped | A (target parser/render gap) | Same. |
| `kitchen_sink.set` | `snmp.contact` | source `'noc@example.net'`; target dropped | A (target parser/render gap) | Same. |
| `kitchen_sink.set` | `snmp.trap_hosts` | source list; target dropped | A (target parser/render gap) | YAML `good` (OPNsense `<system><snmpd>` supports trap-hosts). Same fix locus as the three above — likely a single render-emit-but-parse-rejects asymmetry on the OPNsense XML SNMP block. |

---

## Cross-cutting Junos-source observations

* **Junos parser projection gaps (3 cells).** The Junos parser does
  not project per-interface state onto its associated VLAN: neither
  `vlans[].tagged_ports` (from `vlan members <NAME>` per iface) nor
  `vlans[].ipv4_addresses` (from `irb.<unit>` family-inet via the
  vlan's `l3-interface` linkage).  Both projections already exist for
  the `lag_member_of` → `lags[].members` direction (`parse.py:369-389`)
  — the same post-pass scaffold can be extended.  Three findings
  cluster here (one cell on cisco_iosxe_cli tagged_ports, two cells
  on aruba ipv4_addresses).
* **Repeated SNMP gap across three targets (10 cells).** community /
  location / contact / trap_hosts drop on fortigate_cli, mikrotik_routeros,
  and opnsense — same pattern, three different target codecs.  These
  are target-side codec bugs, not Junos-source quirks; Junos populates
  the canonical SNMP record richly so any target gap shows up here.
* **Cosmetic LAG rename flagged as CODEC_BUG (3 cells).** `ae<N>` →
  `Port-Channel<N>` / `Port-channel<N>` is the vendor-correct rename
  per YAML notes, but the comparator does not recognise structural
  rename and flags every cell.  Bucket-C — methodology improvement
  in the comparator (or YAML disposition flip to `lossy`).
* **`vlan members all` expansion (1 cell, large impact).** Junos's
  trunk-allowed shorthand `vlan members all` parses to
  `range(1,4095)`; this surfaces as either dropped trunk-allowed
  lists (target render can't handle 4094 entries) or as ballooned
  vlan-database (cisco renders & reparses 4094 vlans).  Either keep
  `all` as a sentinel in canonical, or document VLAN range expansion
  as `lossy` in the affected YAMLs.
* **Apply-groups not implicated.** None of the 26 cells trace to the
  Junos two-pass apply-groups dispatch — the GLOBAL-SETTINGS
  inheritance in `kitchen_sink.set` round-trips cleanly through every
  target.  This was a worry area; the data clears it.
* **IRB / per-unit interfaces not implicated directly** — although
  the parser-side gap on `vlans[].ipv4_addresses` is downstream of
  the IRB → VLAN binding, the IRB ifaces themselves materialise
  correctly as `irb.100`, `irb.200` per `parse.py:1085-1110`.

---

## Top 3 recommended fixes

1. **Junos parser: project per-iface VLAN membership and IRB unit IPs
   onto the named VLAN.**  Locus:
   `netcanon/migration/codecs/juniper_junos/parse.py` — add a
   post-pass after the existing L2 vlan-members resolution
   (`parse.py:392-426`) that fills `vlans[].tagged_ports` and a
   parallel post-pass that fills `vlans[].ipv4_addresses` from any
   `irb.<unit>` interface whose name matches the VLAN's
   `l3-interface` field.  Closes 3 Bucket-A cells (one cisco, two
   aruba) and is the only finding where the Junos codec itself is
   the locus.
2. **Target-codec SNMP wire-up: fortigate_cli, mikrotik_routeros,
   opnsense.**  Closes 10 Bucket-A cells in one thematic sweep.
   Each target has a different render path but the symptom is
   identical (community / location / contact / trap_hosts dropped on
   round-trip).  Suggest a per-target unit test that asserts
   round-trip preservation of all four canonical SNMP scalars from a
   minimal `kitchen_sink`-derived intent.
3. **Comparator + YAML hygiene for vendor-correct LAG renames and
   `vlan members all` expansion.**  Closes 4 Bucket-C cells and
   reclassifies 1 Bucket-B cell.  Either teach `actual_disposition`
   in `tools/run_phase4_reconciliation.py` to treat structural
   rename (lag.name `ae0→Port-channel0` while members + mode align)
   as preserved, or flip the relevant YAML rows to `lossy` with a
   rename note.  Same pattern for `vlan members all` — flip
   `juniper_junos__cisco_iosxe_cli.yaml`'s `vlans[].id: good` to
   `lossy` for sources known to use `all` (or keep `all` as a
   canonical sentinel).

---

## See also

* `tests/fixtures/real/PHASE4_RECONCILIATION.md` — top-level matrix.
* `tests/fixtures/real/_phase4_runs/latest.json` — raw per-cell records.
* `tests/fixtures/cross_vendor_expectations/juniper_junos__*.yaml` —
  Phase-3 expectations for the seven target pairs.
* Sibling Phase-4b findings:
  `phase4_findings_arista_eos.md`,
  `phase4_findings_aruba_aoss.md`,
  `phase4_findings_cisco_iosxe.md`,
  `phase4_findings_cisco_iosxe_cli.md`,
  `phase4_findings_fortigate_cli.md`,
  `phase4_findings_mikrotik_routeros.md`,
  `phase4_findings_opnsense.md` — several findings here (LAG rename,
  SNMP gaps) cross-pollinate with peer reports.
* `netcanon/migration/codecs/juniper_junos/parse.py` — Junos parser;
  the only fix locus on the source side (one finding cluster, 3
  cells).

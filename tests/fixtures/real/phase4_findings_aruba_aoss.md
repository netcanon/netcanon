# Phase 4b findings — source vendor: aruba_aoss

Generated against `_phase4_runs/latest.json`.  20 CODEC_BUG
entries across 3 target codecs.  Distribution: arista_eos (7),
cisco_iosxe_cli (1), juniper_junos (12).

The seven aruba_aoss source fixtures driving these cells are:

* `tests/fixtures/real/aruba_aoss/aruba_central_5memberstack_rendered.cfg`
* `tests/fixtures/real/aruba_aoss/hpe_community_2920_wb1608_dhcp_snooping.cfg`
* `tests/fixtures/real/aruba_aoss/hpe_community_2930f_wc1607_intervlan.cfg`
* `tests/fixtures/real/aruba_aoss/hpe_community_2930f_wc1610_dhcp_server.cfg`
* `tests/fixtures/real/aruba_aoss/hpe_community_5406rzl2_kb1515.cfg`
* `tests/fixtures/real/aruba_aoss/user_contrib_2930m_wc1611.cfg`
* `tests/fixtures/synthetic/aruba_aoss/kitchen_sink.cfg`

## Triage classification (3 buckets: A real-bug / B stale-YAML / C acceptable-lossy)

* **Bucket A — real codec bug**: target codec is dropping data that
  the source carried and the YAML promised would survive.  Codec locus
  is the parse or render path of the *target* (or, in the
  reverse-projection case, a missing `project_switchport_to_vlan` step
  in the target parser).
* **Bucket B — stale YAML**: the YAML expectation overstates what the
  current codec stack can do.  The data loss is real and observable
  but the canonical model / cross-pair never had a working path —
  YAML should be downgraded to `lossy` (or `not_applicable`) with a
  reason rather than `good`.
* **Bucket C — acceptable lossy**: the drift is benign canonicalisation
  (e.g. dedup of identical records) or a known structural transform
  the YAML already documents elsewhere.

The dominant pattern (18 of 20 cells) is the same root cause: the
arista_eos and juniper_junos parsers do NOT call
`project_switchport_to_vlan` after parse, so the round-trip
`render -> re-parse` produces a canonical with port-centric
`interfaces[].access_vlan` / `trunk_allowed_vlans` populated but
VLAN-centric `vlans[].tagged_ports` / `untagged_ports` empty.  The
Phase 4b comparator reads the VLAN-centric lists and flags drift.
This is bucket A — the fix is on the **target** codec parse path,
NOT in aruba_aoss source.

The cisco_iosxe_cli cell is a narrower variant of the same pattern:
cisco_iosxe_cli DOES call `project_switchport_to_vlan` on parse, so
it recovers most port memberships, but Cisco does not emit
`switchport access vlan 1` (default VLAN is implicit), so VLAN 1
untagged ports cannot be recovered on round-trip.  Bucket B — the
YAML claims `vlans: good` but VLAN 1 default-membership is
structurally lossy across this pair.

The two non-VLAN cells:

* `kitchen_sink.cfg -> arista_eos :: radius_servers` — arista_eos
  codec has NO render path for radius servers (greps clean for
  `radius-server` in the entire `arista_eos/` codec).  YAML claims
  `radius_servers: good` for this pair.  Bucket A on the target codec
  (missing render).
* `hpe_community_2930f_wc1607_intervlan.cfg -> juniper_junos ::
  static_routes` — source has both `ip default-gateway 192.168.2.11`
  AND `ip route 0.0.0.0 0.0.0.0 192.168.2.11` (lines 8 + 10 of the
  fixture); both normalise to identical canonical records and the
  Junos round-trip dedups them (4 -> 3).  Bucket C — dedup of
  byte-identical canonical records is correct behaviour.

## Bucket totals

| Bucket | Count | Action |
|---|---:|---|
| A | 18 | Fix target codecs (arista_eos parse, juniper_junos parse, arista_eos radius render) |
| B | 1  | Downgrade YAML expectation (cisco_iosxe_cli VLAN-1 default-membership) |
| C | 1  | Document static-route dedup as canonical behaviour; no code change |

## Per-cell findings

### Target: arista_eos

| Fixture | Field | Drift detail | Bucket | Recommendation |
|---|---|---|---|---|
| `aruba_central_5memberstack_rendered.cfg` | `vlans` | All `tagged_ports`/`untagged_ports` empty on target; 24 untagged ports + 2 tagged ports per VLAN drop on round-trip | A | Add `project_switchport_to_vlan` to `arista_eos/parse.py` |
| `hpe_community_2920_wb1608_dhcp_snooping.cfg` | `vlans` | VLAN 1 LAN: 48 untagged ports + SVI ipv4 192.168.176.35/24 drop; VLAN 2 Gast: 6 tagged ports drop | A | Same as above + audit SVI ipv4 reverse projection |
| `hpe_community_2930f_wc1607_intervlan.cfg` | `vlans` | 12 VLANs; tagged/untagged port lists + `ipv4_addresses` (SVI) all empty on target | A | Same as above |
| `hpe_community_2930f_wc1610_dhcp_server.cfg` | `vlans` | 4 VLANs (1, 100, 200, 300) all lose untagged ports + SVI ipv4 addresses | A | Same as above |
| `user_contrib_2930m_wc1611.cfg` | `vlans` | 3 VLANs (1, 2, 10) lose 51 untagged ports + 2 tagged ports | A | Same as above |
| `kitchen_sink.cfg` | `vlans` | 5 VLANs (1, 10, 20, 30, 40) lose all port memberships + SVI ipv4 addresses | A | Same as above |
| `kitchen_sink.cfg` | `radius_servers` | "all 2 radius_servers dropped" — source has 2 servers (10.0.20.10/11) with keys, target empty list | A | Add radius-server render path to `arista_eos/render.py` (currently missing entirely; YAML at line 294-307 promises Cisco-derived `radius-server host <ip> key "..."` form) |

### Target: cisco_iosxe_cli

| Fixture | Field | Drift detail | Bucket | Recommendation |
|---|---|---|---|---|
| `aruba_central_5memberstack_rendered.cfg` | `vlans` | VLAN 1 keeps untagged 1/1..1/24 (cisco's `project_switchport_to_vlan` recovers via explicit access-vlan-1 lines); VLAN 20 USERS loses untagged 1/1..1/12 (cisco renders these as `switchport access vlan 1` since VLAN 1 is the implicit default; round-trip puts them on VLAN 1 not VLAN 20); VLAN 30 VOICE loses 12 untagged ports (same default-VLAN absorption) | B | YAML at `vlans: good` overstates fidelity for sources where VLAN-1 partitioning is implicit on Aruba but rendered explicitly on Cisco; downgrade to `lossy` with reason: "VLAN 1 default-membership round-trip ambiguous when source has non-VLAN-1 untagged ports that map to Cisco access-vlan-1 implicit-default" |

### Target: juniper_junos

All twelve cells are the same root cause: `juniper_junos/parse.py`
does not call `project_switchport_to_vlan` after parse, so
`vlans[].tagged_ports` and `vlans[].untagged_ports` are always empty
on the round-trip-parsed canonical.  Junos render does emit the
correct per-interface `family ethernet-switching vlan members <name>`
output (verified at `juniper_junos/render.py:497-546`); the parser
side just doesn't reconstruct the VLAN-centric view.

| Fixture | Field | Drift detail | Bucket | Recommendation |
|---|---|---|---|---|
| `aruba_central_5memberstack_rendered.cfg` | `vlans[].tagged_ports` | VLAN 20 USERS source `[1/25, 1/26]` -> target `[]` | A | Add reverse projection to junos parser |
| `aruba_central_5memberstack_rendered.cfg` | `vlans[].untagged_ports` | VLAN 1 (24 ports), 20 (12), 30 (12) all empty on target | A | Same |
| `hpe_community_2920_wb1608_dhcp_snooping.cfg` | `vlans[].tagged_ports` | VLAN 2 Gast `[1, 2, 45, 46, 47, 48]` -> `[]` | A | Same |
| `hpe_community_2920_wb1608_dhcp_snooping.cfg` | `vlans[].untagged_ports` | VLAN 1 LAN 48 untagged ports drop | A | Same |
| `hpe_community_2930f_wc1607_intervlan.cfg` | `vlans[].tagged_ports` | VLANs 10, 11, 12, 2 each lose 13 tagged ports | A | Same |
| `hpe_community_2930f_wc1607_intervlan.cfg` | `vlans[].untagged_ports` | VLAN 1 (5), 11 (8), 2 (23) untagged ports drop | A | Same |
| `hpe_community_2930f_wc1607_intervlan.cfg` | `static_routes` | Count drift 4 -> 3: source carries `ip default-gateway 192.168.2.11` (line 8) AND `ip route 0.0.0.0 0.0.0.0 192.168.2.11` (line 10); both normalise to canonical `0.0.0.0/0 -> 192.168.2.11`; Junos round-trip dedups | C | Dedup of byte-identical canonical records is correct behaviour — document as canonical-side dedup in YAML or in `aruba_aoss/parse.py` (could optionally suppress the duplicate at parse time so source_count == target_count) |
| `hpe_community_2930f_wc1610_dhcp_server.cfg` | `vlans[].untagged_ports` | 4 VLANs lose all untagged ports | A | Same as above |
| `user_contrib_2930m_wc1611.cfg` | `vlans[].tagged_ports` | VLAN 2 Management `[1/47, 1/48]` -> `[]` | A | Same |
| `user_contrib_2930m_wc1611.cfg` | `vlans[].untagged_ports` | VLAN 1 (51 ports inc. `1/A1..1/A4`), VLAN 10 test (`1/48`) drop | A | Same |
| `kitchen_sink.cfg` | `vlans[].tagged_ports` | 4 VLANs each lose `[23, 24]` tagged uplinks | A | Same |
| `kitchen_sink.cfg` | `vlans[].untagged_ports` | 4 VLANs lose 1+12+8+2 untagged ports | A | Same |

## Recommended fix work

1. **Add `project_switchport_to_vlan` call to `juniper_junos/parse.py`**
   — single-line fix at the bottom of the parse path, mirroring
   `cisco_iosxe_cli/parse.py:354-355`.  Resolves 11 of 12 junos cells
   (all the `vlans[].tagged_ports` / `vlans[].untagged_ports` drift)
   and is the single highest-leverage change in this triage.
2. **Add `project_switchport_to_vlan` call to `arista_eos/parse.py`**
   — same fix, same one-line shape.  Resolves all 6 arista vlan-port
   cells.  Together with #1 this clears 17 of 20 cells.
3. **Add a radius-server render path to `arista_eos/render.py`** —
   currently grep-clean for `radius-server` in the entire codec.
   The YAML at `aruba_aoss__arista_eos.yaml:294-307` already
   specifies the expected form (`radius-server host <ip> key "..."`,
   default ports 1812/1813).  Resolves the kitchen_sink radius cell.
   Cross-vendor symmetry: this surface should also work for
   cisco_iosxe / cisco_iosxe_cli sources mapping to arista (likely
   same gap surfaces in those triage files).

Tertiary follow-ups (not in top 3):

* Downgrade `vlans: good` -> `vlans: lossy` in
  `aruba_aoss__cisco_iosxe_cli.yaml` with a reason describing
  VLAN-1 default-membership absorption when the source has
  non-VLAN-1 ports that round-trip via Cisco's implicit-access-vlan-1
  rendering.  (1 cell, bucket B.)
* Either suppress `ip default-gateway` -> canonical static-route
  insertion when an explicit `ip route 0.0.0.0 0.0.0.0` already exists
  in `aruba_aoss/parse.py`, OR document the dedup as canonical-correct
  in `aruba_aoss__juniper_junos.yaml` static_routes note.  (1 cell,
  bucket C.)

## See also

- [PHASE4_RECONCILIATION.md](PHASE4_RECONCILIATION.md)
- [_phase4_runs/latest.json](_phase4_runs/latest.json)
- [../cross_vendor_expectations/aruba_aoss__arista_eos.yaml](../cross_vendor_expectations/aruba_aoss__arista_eos.yaml)
- [../cross_vendor_expectations/aruba_aoss__cisco_iosxe_cli.yaml](../cross_vendor_expectations/aruba_aoss__cisco_iosxe_cli.yaml)
- [../cross_vendor_expectations/aruba_aoss__juniper_junos.yaml](../cross_vendor_expectations/aruba_aoss__juniper_junos.yaml)
- [phase4_findings_arista_eos.md](phase4_findings_arista_eos.md) — sibling triage; the `project_switchport_to_vlan` gap on the arista parser likely also surfaces in arista-source -> X cells
- [phase4_findings_juniper_junos.md](phase4_findings_juniper_junos.md) — sibling triage; the junos parser gap likely surfaces there too
- [phase4_findings_cisco_iosxe_cli.md](phase4_findings_cisco_iosxe_cli.md) — sibling triage; check for the inverse VLAN-1 default-membership pattern

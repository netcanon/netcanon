# Phase 4b findings — source vendor: arista_eos

Generated against `_phase4_runs/latest.json` (reconciliation
of `_cross_mesh_runs/<latest>.json`).  17 CODEC_BUG entries
across 5 target codecs.  Distribution: aruba_aoss (2),
cisco_iosxe_cli (5), fortigate_cli (2), juniper_junos (7),
opnsense (1).

## Triage classification

For each CODEC_BUG, assign ONE of three buckets:

* **A: Real bug** — render produces incorrect output; fix in
  the target codec (or, where the breakage is on the
  arista_eos parse side, the source codec).
* **B: Stale expectation** — render is correct but the Phase 3
  expectation YAML doesn't reflect the legitimate translation
  semantic; fix the YAML.
* **C: Acceptable lossy** — neither side wrong; cross-vendor
  semantic genuinely doesn't transfer.  Document as
  `lossy` / `unsupported` in the YAML.

## Bucket totals

| Bucket | Count | Action |
|---|---:|---|
| A: Real bug | 8 | Fix in render / parse |
| B: Stale expectation | 9 | Update YAML disposition |
| C: Acceptable lossy | 0 | — |

## Per-cell findings

### Target: aruba_aoss

| Fixture | Field | Drift detail | Bucket | Recommendation |
|---|---|---|---|---|
| `batfish_labval_dc1_leaf2a_eos4230.txt` | `vlans` | 6 MLAG/peer VLANs gain `ipv4_addresses=10.255.251.2/31` after Aruba round-trip (source had `[]`) | A | Aruba SVI absorption emits the SVI's IP onto every VLAN object — likely the L3 VRF-bound SVI is being absorbed onto every VLAN row.  Locus: `aruba_aoss/codec.py` `addrs` accumulation around `_svi_absorption.py`. |
| `synthetic/kitchen_sink.txt` | `vlans` | VLANs 100/200 gain SVI IPv4 on round-trip | A | Same SVI-absorption over-attribution as above — single source of truth `_svi_absorption.absorbs_svi_into_vlan`. |

### Target: cisco_iosxe_cli

| Fixture | Field | Drift detail | Bucket | Recommendation |
|---|---|---|---|---|
| `batfish_labval_dc1_leaf2a_eos4230.txt` | `vlans` | count drift `15 -> 4093` (target gains all VLANs 1..4094 minus 15) | A | IOS-XE parser is materialising one VLAN per id appearing in any `switchport trunk allowed vlan` range, instead of reusing the explicit `vlan N` declarations.  Locus: `cisco_iosxe_cli/parse.py` near the trunk-allowed range expansion (line ~688). |
| `batfish_labval_dc1_leaf2a_eos4230.txt` | `routing_instances` | `l3_vni` drops from 15001-15004 to `null` on 4 VRFs | A | IOS-XE render path has no `address-family l2vpn evpn` emission, so canonical `l3_vni` doesn't survive the round trip.  YAML already calls this out for VXLAN, but `routing_instances` is marked `good`.  Either fix render or split per-field disposition. |
| `karneliuk_a_eos1_eos4260.txt` | `routing_instances` | `instance_type` `mac-vrf -> vrf` | B | YAML disposition is `good` but its prose acknowledges Cisco "does not emit" mac-vrf.  Reclassify `routing_instances[].instance_type` to `lossy` (mirror Junos pair). |
| `synthetic/kitchen_sink.txt` | `vlans` | tagged/untagged port lists & SVI IP appear on Cisco round-trip; `count_drift 4 -> 4` but every VLAN gains port lists | A | Cisco IOS-XE parser is reverse-attributing trunk membership when it shouldn't — back-fill is overzealous.  Same parse-side locus as the 4093-count case. |
| `synthetic/kitchen_sink.txt` | `routing_instances` | `l3_vni 50100 -> null` and `mac-vrf -> vrf` | A/B | `l3_vni` (A) same VXLAN-render gap; `instance_type` (B) — reclassify field. |

### Target: fortigate_cli

| Fixture | Field | Drift detail | Bucket | Recommendation |
|---|---|---|---|---|
| `ksator_dcs_7150s64_eos4224.txt` | `domain` | `'lab.local' -> ''` | A | FortiGate render emits `set domain` but the FortiGate parser never reads it back — `parse.py` lacks a handler for `system dns / set domain`.  Add a domain-extraction branch alongside `dns-server1`/`dns-server2`. |
| `synthetic/kitchen_sink.txt` | `domain` | `'example.net' -> ''` | A | Same parse-side gap as above. |

### Target: juniper_junos

| Fixture | Field | Drift detail | Bucket | Recommendation |
|---|---|---|---|---|
| `batfish_duplicateprivate_eos4211.txt` | `local_users` | hash prefix `arista:sha512:$6$... -> junos:$6$...`; `privilege_level 15 -> 1` | B | Vendor-prefix asymmetry is by design (each parser tags with its own vendor).  The privilege_level loss is real — Junos has no integer privilege model, only role names.  YAML's `local_users` is `good` but field-level dispositions for `hashed_password` (vendor-prefix) and `privilege_level` (no Junos equivalent) need explicit `lossy` carve-outs. |
| `batfish_labval_dc1_leaf2a_eos4230.txt` | `lags` | 5 lag names rename `Port-Channel<N> -> ae<N>` | B | This is the documented LAG name-rename mesh (YAML note literally says "Arista 'Port-Channel N' maps to Junos 'ae N'").  Field `lags[].name` should be `lossy` (canonical name re-emerges as `ae<N>` after Junos parse).  Comparator can't equate them without a name-rename mesh. |
| `batfish_labval_dc1_leaf2a_eos4230.txt` | `local_users` | hash prefix only | B | Vendor-prefix asymmetry — add `local_users[].hashed_password: lossy` carve-out. |
| `karneliuk_a_eos1_eos4260.txt` | `local_users` | hash prefix; `role '' -> 'super-user'` | B | Vendor prefix as above; role `'' -> super-user` is Junos's default-role injection when source role is blank — document as `lossy` on `local_users[].role`. |
| `ksator_dcs_7150s64_eos4224.txt` | `local_users` | count drift `5 -> 4` (admin user with empty hash dropped) | A | Junos render skips users where `hashed_password == ""` instead of emitting `set system login user X authentication plain-text-password-disabled` or equivalent.  Locus: `juniper_junos/render.py` ~line 142 — the prefix check excludes empty-hash users entirely. |
| `synthetic/kitchen_sink.txt` | `lags` | `Port-Channel10/20 -> ae10/20` | B | Same lag-name-rename — see above. |
| `synthetic/kitchen_sink.txt` | `local_users` | count drift `3 -> 2` (md5 user `readonly` with `arista:5:$1$` hash dropped) | A | Junos render drops MD5 (`$1$`) hashes — only `$6$` SHA-512 makes it through.  Either pass MD5 through (Junos accepts crypt MD5) or document as `lossy` and emit a warning.  Locus: `juniper_junos/render.py` hash-tag check. |

### Target: opnsense

| Fixture | Field | Drift detail | Bucket | Recommendation |
|---|---|---|---|---|
| `synthetic/kitchen_sink.txt` | `interfaces[].ipv6_addresses` | link-local `fe80::1/64` drops from Ethernet1 (only `2001:db8:0:1::1/64` survives) | B | OPNsense's `<ipaddrv6>` slot holds ONE IPv6.  Real captures rarely emit explicit link-local, but synthetic fixture has both.  YAML asserts `good` but acknowledges single-address constraint in the FortiGate twin pair.  Reclassify `interfaces[].ipv6_addresses` as `lossy` with note "OPNsense renders only the first non-link-local IPv6". |

## Recommended fix work

Top 3 most-leveraged actions ordered by `severity x count`:

1. **Fix Aruba SVI absorption over-attribution** (2 cells, both
   high) — the `absorbs_svi_into_vlan` path is leaking a VRF SVI
   address onto unrelated VLANs.  One fix kills both vlan-row
   findings and likely improves intra-vendor parity too.
2. **Fix Cisco IOS-XE VLAN materialisation from trunk ranges**
   (2 cells, the 15->4093 case is dramatic) — parser is
   inflating the canonical VLAN list by treating allowed-vlan
   ranges as VLAN definitions.  Tighten parse.py to only emit
   VLANs declared via top-level `vlan <id>` stanzas.
3. **Reclassify YAML field-level dispositions for vendor-prefix
   hashes & lag-name renames** (4 cells across Junos pair) —
   purely a YAML edit; no codec change.  Adds `local_users[].
   hashed_password: lossy`, `lags[].name: lossy`, and similar
   carve-outs to the arista_eos→juniper_junos expectation file.
   Mirror to other Junos pairs.

Honourable mention: the FortiGate `domain`-parse gap (2 cells)
is a one-line parser fix and should ride alongside #1/#2.

## See also

- `PHASE4_RECONCILIATION.md` — top-level summary
- `tests/fixtures/real/_phase4_runs/latest.json` — full data
- `tests/fixtures/cross_vendor_expectations/arista_eos__aruba_aoss.yaml`
- `tests/fixtures/cross_vendor_expectations/arista_eos__cisco_iosxe_cli.yaml`
- `tests/fixtures/cross_vendor_expectations/arista_eos__fortigate_cli.yaml`
- `tests/fixtures/cross_vendor_expectations/arista_eos__juniper_junos.yaml`
- `tests/fixtures/cross_vendor_expectations/arista_eos__opnsense.yaml`
- `phase4_findings_<other-vendor>.md` — sibling reports

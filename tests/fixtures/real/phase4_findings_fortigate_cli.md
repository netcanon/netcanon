# Phase 4b — fortigate_cli source-vendor findings

Investigation pass over `tests/fixtures/real/_phase4_runs/latest.json`,
filtered to `source_codec == "fortigate_cli"`.  Reconciled against the
three `fortigate_cli__<target>.yaml` Phase 3 expectation files in
`tests/fixtures/cross_vendor_expectations/` that registered drift.

## Aggregate

* **Total CODEC_BUG findings:** 8 (all severity=high)
* **Cells with CODEC_BUG:** 6 (across 4 fixtures × 3 targets)
* **Distribution by target:**
  * `juniper_junos` — 3 (1 cell)
  * `mikrotik_routeros` — 1 (1 cell)
  * `opnsense` — 4 (4 cells)
* **Distinct (target, field) pairs:** 5

Source fixtures driving these CODEC_BUGs:

* `tests/fixtures/real/fortigate/kevinguenay_fgt_70g_branch.conf`
* `tests/fixtures/real/fortigate/kevinguenay_fgt_vm_hub.conf`
* `tests/fixtures/real/fortigate/user_contrib_fg100e_fos7213.conf`
* `tests/fixtures/synthetic/fortigate_cli/kitchen_sink.conf`

## Bucket totals

Each finding classified into one of three buckets per Phase 4b protocol:

| Bucket | Meaning | Count |
|---|---|---:|
| **A** | Real codec bug (parse or render gap) | 7 |
| **B** | Stale Phase 3 YAML expectation (vendor-doc supports drift) | 1 |
| **C** | Comparator / methodology artefact | 0 |

A clearly dominates — the targets' render branches are missing wire-up
for fields the YAML has correctly cleared as `good`.

## Per-target sections

### Target: opnsense (4 CODEC_BUGs across 4 cells)

All four cells trip on the same field with identical drift:

| Fixture | Field | Source | Target | Bucket |
|---|---|---|---|---|
| kevinguenay_fgt_70g_branch.conf | `dns_servers` | `["96.45.45.45", "96.45.46.46"]` | `[]` | A |
| kevinguenay_fgt_vm_hub.conf | `dns_servers` | `["96.45.45.45", "96.45.46.46"]` | `[]` | A |
| user_contrib_fg100e_fos7213.conf | `dns_servers` | `["1.1.1.1", "8.8.8.8"]` | `[]` | A |
| synthetic/kitchen_sink.conf | `dns_servers` | `["1.1.1.1", "8.8.8.8"]` | `[]` | A |

**Locus (A):** `netcanon/migration/codecs/opnsense/render.py` —
`render_canonical()` builds `<system>` (lines 75–179) with
hostname / domain / RADIUS / users / privs but **never emits
`<dnsserver>` from `intent.dns_servers`**.  The only `dns_servers`
reference in render.py is per-DHCP-pool zone (`pool.dns_servers`,
line 321), which is for DHCP scope DNS — not the global resolver.
Parser side `parse.py` line 596 *also* only reads
`<dnsserver>` inside the DHCP scope (`<dhcpd>/<...>/dnsserver`),
not the global `<system>/<dnsserver>` element.  So canonical's
top-level `dns_servers` round-trips to / from nothing on OPNsense.

**YAML:** `fortigate_cli__opnsense.yaml` lines 209–218 declares
`dns_servers` disposition `good` ("FortiOS three-cap collapses
cleanly to OPNsense's repeated `<dnsserver>` elements").  The
expectation is correct per OPNsense schema (`<system>/<dnsserver>`
*does* accept repeated elements) — only the codec wire-up is
missing.  Fix is one render branch + one parse branch on the
opnsense side.

### Target: juniper_junos (3 CODEC_BUGs in 1 cell)

Single fixture: `user_contrib_fg100e_fos7213.conf`.  Three drifts
in lock-step on the same iface list:

| Field | Drift signature | Bucket |
|---|---|---|
| `interfaces[].description` | source `cluster-vlan` → target empty; source `fortihome-ssl` → target `cluster-vlan` (shifted-by-one across iface records) | A |
| `interfaces[].enabled` | source `fortihome-ssl=False` → target `True`; source `ha1=True` → target `False` (shifted) | A |
| `interfaces[].ipv4_addresses` | source `cluster-vlan=10.10.10.100/24` → target `[]`; source `fortihome-ssl=[]` → target `10.10.10.100/24` (shifted) | A |

**Locus (A):** all three sub-fields drift in the same per-record
shift pattern across the same `(cluster-vlan, dmz, fortihome-ssl,
fortilink, ha1)` interface group — strongly indicates a single
upstream cause, not three independent bugs.  The smoking gun is in
`netcanon/migration/codecs/juniper_junos/render.py` lines 207–268:
the `interface-range` auto-collapse promotes any group of ≥3
interfaces sharing `(mtu, description, enabled)` into an
`AUTO-RANGE-N` block + per-iface `member` lines, then **suppresses
the per-iface attrs**.  When `description` is the *same* tuple value
across iface records the collapse is sound; when several FortiGate
edits coincidentally share `enabled=True`, `mtu=None`, and a
non-empty description that differs across members, the parse-back
re-attaches the *range's* description to *every* member (or to the
wrong member by emit order).  The shifted-by-one signature on three
unrelated sub-fields is the tell.

**YAML:** `fortigate_cli__juniper_junos.yaml` lines 309–352 declare
all three sub-fields `good` — vendor-doc supports it (Junos
`set interfaces X description / disable / family inet address`
maps 1:1 to canonical).  Stale-YAML angle nil; bug is in the
range-collapse logic.

### Target: mikrotik_routeros (1 CODEC_BUG in 1 cell)

Single synthetic fixture: `kitchen_sink.conf`.

| Field | Drift signature | Bucket |
|---|---|---|
| `static_routes` | per-record `interface` field: source `port1`/`agg1` → target `""`/`""` | A (also B for stale-YAML wording) |

**Locus (A):** `netcanon/migration/codecs/mikrotik_routeros/render.py`
lines 365–378 emits `/ip route add dst-address=... gateway=GW`.
The interface column is emitted **only when `route.gateway` is
empty** (`elif route.interface:` branch).  Both fixture routes
have *both* gateway and interface populated, so the `interface=`
parameter is never emitted, and re-parse drops the field to `""`.
RouterOS native `/ip route` accepts `gateway=...` and a separate
`pref-src=` / iface routing modifier, but the simpler form is
`/ip route add dst-address=... gateway=GW%IFACE` where `%IFACE`
is appended to the gateway — the codec doesn't emit either form.

**YAML (B side):** `fortigate_cli__mikrotik_routeros.yaml` lines
231–244 disposition `good` with the note "RouterOS render emits
`gateway=<iface>` form when needed", which is **only true when
`route.gateway` is empty**.  Either the YAML should be downgraded
to `lossy` (with reason: "interface field drops when gateway is
populated; RouterOS lacks a clean two-field representation") or
the renderer should emit `gateway=GW%IFACE` syntax.  Vendor doc
(MikroTik help.mikrotik.com `/ip+routing` page) supports the
`%iface` modifier so a render fix is achievable.

## Top-3 fixes (highest payback)

1. **OPNsense `<system>/<dnsserver>` wire-up (parse + render)** —
   single contiguous block in `opnsense/render.py` (after
   `<domain>` near line 87) and one parse hook before line 596
   in `parse.py`.  Closes 4 of the 8 CODEC_BUGs (50% by count)
   across all four fixtures.  Lowest LOC : highest impact.

2. **Junos `interface-range` collapse safety** —
   `juniper_junos/render.py` lines 207–268.  Either tighten the
   collapse-key to require **identical descriptions across the
   whole group AND identical IP-bearing status** (don't collapse
   if any member has a per-iface IP), or only emit
   `interface-range` for genuinely default-attr groups.  The
   shifted-by-one signature suggests the parse-back side of
   range-emission is also assuming attrs apply to *all* members,
   which compounds the loss.  Closes 3 of 8 CODEC_BUGs.

3. **MikroTik static-route interface preservation** —
   `mikrotik_routeros/render.py` line 374 emits
   `gateway={route.gateway}%{route.interface}` when interface is
   non-empty, OR adds an explicit `gateway-interface=` param if
   that's syntactically supported.  Alternative cheaper fix:
   downgrade the YAML disposition to `lossy` with a vendor-doc
   reference for the truncation rationale.  Closes 1 of 8.

Implementing fixes #1 + #2 alone closes 7 of 8 (87.5%) of the
fortigate_cli source-vendor CODEC_BUGs.

## Notes on tricky aspects

* The Junos drift is the only multi-field-in-lockstep finding:
  three sub-fields shift in the same per-record pattern, all on
  the same `interfaces[]` list.  This is *not* three bugs — it's
  one root cause (range-collapse + parse-back asymmetry).  Worth
  flagging upstream so the fix attempt doesn't address the
  symptoms one at a time.
* The OPNsense `dns_servers` finding is uniform across all four
  fixtures including the synthetic one, indicating a clean
  reproducer is trivial — the synthetic kitchen_sink already
  exercises it.
* No B-bucket findings on the OPNsense side: the YAML matches
  vendor-doc, the codec is just unwired.
* No C-bucket findings: comparator did not produce false-positives
  on this slice.

## See also

- `tests/fixtures/real/PHASE4_RECONCILIATION.md` — generation context
- `tests/fixtures/real/_phase4_runs/latest.json` — raw cell data
- `tests/fixtures/cross_vendor_expectations/fortigate_cli__opnsense.yaml`
  — 209–218 (`dns_servers` good)
- `tests/fixtures/cross_vendor_expectations/fortigate_cli__juniper_junos.yaml`
  — 309–352 (interface sub-fields good)
- `tests/fixtures/cross_vendor_expectations/fortigate_cli__mikrotik_routeros.yaml`
  — 231–244 (`static_routes` good)
- `netcanon/migration/codecs/opnsense/render.py` — fix #1 locus
- `netcanon/migration/codecs/juniper_junos/render.py` — fix #2 locus
- `netcanon/migration/codecs/mikrotik_routeros/render.py` — fix #3 locus

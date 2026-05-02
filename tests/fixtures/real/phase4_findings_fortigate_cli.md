# Phase 4b — fortigate_cli source-vendor findings

Investigation pass over `tests/fixtures/real/_phase4_runs/latest.json`,
filtered to `source_codec == "fortigate_cli"`.  Reconciled against the
seven `fortigate_cli__<target>.yaml` Phase 3 expectation files in
`tests/fixtures/cross_vendor_expectations/`.

## Aggregate

| Class | Count |
|---|---:|
| Source-vendor cells | 32 (4 fixtures × 8 targets) |
| CODEC_BUG findings | 21 (severity=high, all 21) |
| Distinct (target, field) pairs with CODEC_BUG | 6 |
| METHODOLOGY_ISSUE_under findings | 512 |
|   with `source_count` 0 / absent | 512 (100%) |
|   with `source_count` > 0 | 0 |

The CROSS_MESH_RESULTS.md skeleton row for fortigate_cli matches this
file's Σ counts: `cisco_iosxe_cli` 4, `mikrotik_routeros` 1,
`opnsense` 16 — total 21 (high) across 9 cells.

The four fixtures that drove the runs:

* `tests/fixtures/real/fortigate/kevinguenay_fgt_70g_branch.conf`
* `tests/fixtures/real/fortigate/kevinguenay_fgt_vm_hub.conf`
* `tests/fixtures/real/fortigate/user_contrib_fg100e_fos7213.conf`
* `tests/fixtures/synthetic/fortigate_cli/kitchen_sink.conf`

## CODEC_BUG breakdown (per (target, field), 6 unique cells)

### A. `dns_servers` dropped on round-trip (8 findings, 4×cisco_iosxe_cli + 4×opnsense)

* **Field that drifted**: top-level `intent.dns_servers` (list of IPv4).
* **Drift detail (every fixture)**: source has 2 servers (e.g.
  `['96.45.45.45', '96.45.46.46']` for the kevinguenay fixtures,
  `['1.1.1.1', '8.8.8.8']` for the FG100E + kitchen-sink fixtures);
  target has `[]`.  `drift_detail.drift = "all 2 dns_servers dropped"`.
* **Phase 3 expectation**: `dns_servers.disposition: good`
  (asymmetric — fortigate→target is the lossless direction in both
  the cisco_iosxe_cli YAML and the opnsense YAML).
* **Side responsible**:

  * `cisco_iosxe_cli` target — **target parse-side bug**.  The
    fortigate_cli parser populates `intent.dns_servers` correctly
    (`netconfig/migration/codecs/fortigate_cli/parse.py` lines
    268–274, `_apply_system_dns`), and the cisco_iosxe_cli renderer
    correctly emits `ip name-server <ip>` lines
    (`netconfig/migration/codecs/cisco_iosxe_cli/render.py` lines
    121–125).  But the cisco_iosxe_cli **parser** has no handler for
    `ip name-server` — confirmed by `grep -i "name.server\|name_server\|ip name"`
    over `cisco_iosxe_cli/parse.py` returning zero matches.  So the
    second-pass parse drops the field, registering as drift.
  * `opnsense` target — **target render-side bug**.  The opnsense
    renderer never emits `intent.dns_servers` — only the per-DHCP-pool
    `pool.dns_servers` ends up in the XML
    (`netconfig/migration/codecs/opnsense/render.py` lines 181–184).
    Top-level `tree.dns_servers` is silently discarded.

* **Likely fix location**:

  * `netconfig/migration/codecs/cisco_iosxe_cli/parse.py` — add a
    line-level handler for `ip name-server <ip>` that appends each IP
    to `intent.dns_servers`.  This is symmetric with the existing
    render at line 122-123.  No structural change needed.
  * `netconfig/migration/codecs/opnsense/render.py` — emit a top-level
    `<system><dnsserver>X</dnsserver>...</system>` block (OPNsense
    real captures use `<system>/<dnsserver>` repeated).  Pair it with
    a parser tweak in `opnsense/parse.py` to read those tags back.

* **Test that would catch the fix**:

  * For cisco_iosxe_cli: a unit-tier test
    `tests/unit/migration/codecs/cisco_iosxe_cli/test_parse_dns_servers.py`
    asserting that `parse("ip name-server 1.1.1.1\nip name-server 8.8.8.8\n").dns_servers == ["1.1.1.1", "8.8.8.8"]`.
  * For opnsense: a unit-tier render+parse round-trip on a
    `CanonicalIntent(dns_servers=["1.1.1.1", "8.8.8.8"])` asserting
    the same list comes back.
  * Both will be caught automatically by the next mesh run if the fix
    lands — the existing Phase 1 `_cross_mesh` job re-derives the
    drift matrix.

### B. `static_routes[].interface` field dropped on mikrotik render (1 finding)

* **Cell**: `tests/fixtures/synthetic/fortigate_cli/kitchen_sink.conf -> mikrotik_routeros`.
* **Field**: `static_routes` (list-of-record drift, sub-field `interface`).
* **Drift detail**: source routes carry both `gateway='198.51.100.1'`
  and `interface='port1'` (and `gateway='10.20.0.254'` /
  `interface='agg1'`).  Target routes have `gateway` preserved but
  `interface=''`.
* **Phase 3 expectation**: `static_routes.disposition: good` for
  fortigate→mikrotik per the YAML.
* **Side responsible**: **target render-side bug**, mikrotik_routeros.
  `netconfig/migration/codecs/mikrotik_routeros/render.py` lines
  221–233 emit `gateway=<addr>` only and never include the
  `<interface>` token, even though RouterOS `/ip route` accepts both
  (`gateway=<addr>%<iface>` syntax, or a separate `interface`
  attribute).  The `elif route.interface` branch at line 230 is only
  reached when gateway is empty, so a route carrying both fields
  silently drops `interface`.
* **Likely fix location**: `netconfig/migration/codecs/mikrotik_routeros/render.py`
  in `_render_static_routes` (lines 221–233) — emit `gateway=<addr>%<iface>`
  when both fields are populated.  Pair with parser support
  (`mikrotik_routeros/parse.py` `_parse_ip_route`, line 807) to split
  `gateway` on `%` and populate `route.interface`.
* **Test that would catch the fix**:
  `tests/unit/migration/codecs/mikrotik_routeros/test_static_routes_interface.py`
  asserting that a `CanonicalStaticRoute(destination='0.0.0.0/0',
  gateway='198.51.100.1', interface='ether1')` renders to a line
  containing `gateway=198.51.100.1%ether1` and parses back to the
  same canonical record.

### C. Interface-count drift on fortigate→opnsense (10 findings: 2 enabled + 3 mtu + 4 ipv4 + 3 ipv6)

* **Field**: list-of-record drift on `interfaces[]` — count drifts
  21→20 (two kevinguenay fixtures), 34→33 (FG100E), and per-record
  shift on the kitchen_sink fixture.
* **Phase 3 expectation**: `interfaces.disposition: lossy` overall,
  but the YAML calls out `enabled: good`, `mtu: good`,
  `ipv4_addresses: good (primary)`, so any drift on those subfields
  is a CODEC_BUG.
* **Side responsible**: **target render-side bug**, opnsense.  Two
  cooperating defects:

  1. *Empty-zone drop*: `netconfig/migration/codecs/opnsense/render.py`
     lines 126–144 emit each interface as a child element under
     `<interfaces>`, with content elements only when populated.  An
     interface with `enabled=False`, no description, no MTU, no IPs
     produces a `<zone_el />` with zero children.  The reciprocal
     parser (`opnsense/parse.py` lines 354–360,
     `_parse_interface_zone_canonical`) drops empty zones via
     `if len(list(el)) == 0: return None`.  Net effect: any disabled
     content-free FortiGate interface vanishes on the round-trip.
     This explains the 21→20 / 34→33 counts.
  2. *Index-shift cascade*: once one interface is dropped, the
     position-indexed comparator surfaces drift for every later
     interface as well — the kitchen_sink per_record shows
     `loopback0` (index 4) `mtu None → 1500` and ipv4/ipv6 addresses
     mismatched by one slot, classic shift artefacts of (1).

* **Likely fix location**:

  * Primary: `netconfig/migration/codecs/opnsense/render.py` lines
    126–144.  Always emit at least one stable child (e.g. an `<if>`
    text element with the iface name, or a `<descr>` placeholder)
    so the parser doesn't drop the zone.  This matches real OPNsense
    XML which always has `<if>` for any defined interface.
  * Secondary: `netconfig/migration/codecs/opnsense/parse.py` lines
    354–360.  Reconsider the empty-zone drop heuristic — the canonical
    intent should preserve named-but-empty interfaces.

* **Test that would catch the fix**:
  `tests/unit/migration/codecs/opnsense/test_disabled_iface_roundtrip.py`
  asserting that `CanonicalIntent(interfaces=[CanonicalInterface(name='port15',
  enabled=False)])` survives render+reparse with the interface still
  present.  A second test should round-trip a multi-interface intent
  whose first entry is "minimal" and assert later entries don't
  position-shift.

## METHODOLOGY_ISSUE_under demotion analysis

All 512 `METHODOLOGY_ISSUE_under` findings have `source_count` ∈
{0, None} — i.e. the source FortiGate fixture has zero records for
that field, so the fact that the round-trip "preserved" an empty
list is trivially true and the lossy/unsupported expectation is
not actually exercised.  Per the prompt's skepticism rule
("demote if source_count=0"), every one of these should be
demoted from medium/low severity to ok / informational.

Concretely, the demotion candidates split as follows (selection,
representative):

* `vxlan_vnis`, `evpn_type5_routes`, `routing_instances` — fortigate
  fixtures never carry these (firewall codec); 100% of cells flag
  them as `under`.  Expected — trim the rule to ignore source-empty
  fields, or upgrade the YAML disposition to `not_applicable` for
  fortigate-source cross-pairs.
* `apply_groups`, `group_content`, `raw_sections` — Junos-flavoured
  Tier 3 fields, not_applicable everywhere, always source-empty for
  fortigate.
* `vlans[].tagged_ports` / `untagged_ports` — fortigate VLAN
  membership is encoded via parent-iface, not as a port list, so
  source list is always empty.  Already documented as lossy in the
  YAMLs; the demotion just keeps the noise out of the high-priority
  bucket.
* `snmp` sub-scalars (`community`, `location`, etc.), `radius_servers`
  — fortigate fixtures in the test corpus don't configure these, so
  source-empty trivially preserves.
* `interfaces[].switchport_mode` / `access_vlan` /
  `trunk_allowed_vlans` / `trunk_native_vlan` / `voice_vlan` —
  fortigate has no L2 switching surface on the firewall edge; these
  are unsupported in the YAML and source-empty in every fixture.

No `METHODOLOGY_ISSUE_under` findings remain after the demotion
sweep — the methodology bucket is fully accounted for by
"YAML expects lossy/unsupported, source has nothing to translate
in the first place".  Recommend the Phase 4 reconciliation tool
gain a post-classification demotion pass that recognises
`source_count == 0` and recategorises to a new
`METHODOLOGY_ISSUE_source_empty` (severity=ok) bucket so the
remaining `METHODOLOGY_ISSUE_under` count is meaningful for
priorities.

## Top three actionable fix locations (ranked by Σ codec-bug count)

1. **`netconfig/migration/codecs/opnsense/render.py` lines 126–144**
   (interface-zone emit).  Always emit a stable child element so
   parser doesn't drop the zone.  Touches **10 of 21** findings.
2. **`netconfig/migration/codecs/cisco_iosxe_cli/parse.py`** —
   add `ip name-server` handler.  Touches **4 of 21** findings
   (and is the cleanest single-symbol fix, ~5 lines).  The
   render side already works.
3. **`netconfig/migration/codecs/opnsense/render.py` lines 181–184
   + sibling parse.py** — emit + reparse top-level
   `<system>/<dnsserver>` for `intent.dns_servers`.  Touches
   **4 of 21** findings.  Independent of (1).

Combined, fixes (1)–(3) clear 18 of 21 fortigate_cli-source CODEC_BUG
findings.  The remaining 3 are the mikrotik static-routes interface
field (one tight render+parse change) and any residual once
opnsense interface-zone emit stabilises.

## See also

* `tests/fixtures/real/PHASE4_RECONCILIATION.md` — Phase 4a aggregate
* `tests/fixtures/cross_vendor_expectations/fortigate_cli__cisco_iosxe_cli.yaml`
* `tests/fixtures/cross_vendor_expectations/fortigate_cli__opnsense.yaml`
* `tests/fixtures/cross_vendor_expectations/fortigate_cli__mikrotik_routeros.yaml`
* `netconfig/migration/codecs/fortigate_cli/parse.py` — confirmed
  source-side parsing of `dns_servers` and `static_routes[].interface`
  is correct; bugs are all on the target side.

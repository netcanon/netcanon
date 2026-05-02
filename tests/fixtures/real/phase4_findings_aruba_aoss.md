# Phase 4b — aruba_aoss source-vendor findings

Investigation pass over `tests/fixtures/real/_phase4_runs/latest.json`,
filtered to `source_codec == "aruba_aoss"`.  Reconciled against the
seven `aruba_aoss__<target>.yaml` Phase 3 expectation files in
`tests/fixtures/cross_vendor_expectations/`.

## Aggregate

| Class | Count |
|---|---:|
| Source-vendor cells | 56 (7 fixtures × 8 targets) |
| CODEC_BUG findings | 36 (severity=high, all 36) |
| Distinct (target, field) pairs with CODEC_BUG | 12 unique fields × 4 distinct targets |
| METHODOLOGY_ISSUE_under findings | 1018 |
|   with `source_count` 0 / absent | 1018 (100%) |
|   with `source_count` > 0 | 0 |

CODEC_BUG findings split by target:

| Target | CODEC_BUG count |
|---|---:|
| `juniper_junos` | 17 |
| `opnsense` | 8 |
| `arista_eos` | 7 |
| `cisco_iosxe_cli` | 4 |
| `aruba_aoss` (intra-vendor self) | 0 |
| `cisco_iosxe` | 0 |
| `fortigate_cli` | 0 |
| `mikrotik_routeros` | 0 |

The seven fixtures that drove the runs:

* `tests/fixtures/real/aruba_aoss/aruba_central_5memberstack_rendered.cfg`
* `tests/fixtures/real/aruba_aoss/hpe_community_2920_wb1608_dhcp_snooping.cfg`
* `tests/fixtures/real/aruba_aoss/hpe_community_2930f_wc1607_intervlan.cfg`
* `tests/fixtures/real/aruba_aoss/hpe_community_2930f_wc1610_dhcp_server.cfg`
* `tests/fixtures/real/aruba_aoss/hpe_community_5406rzl2_kb1515.cfg`
* `tests/fixtures/real/aruba_aoss/user_contrib_2930m_wc1611.cfg`
* `tests/fixtures/synthetic/aruba_aoss/kitchen_sink.cfg`

The structural shape of the bugs is dominated by one root cause:
the **Aruba AOS-S source codec emits VLAN-centric port membership**
(`CanonicalVlan.tagged_ports` / `untagged_ports` / `ipv4_addresses`)
rather than the interface-centric switchport state
(`CanonicalInterface.access_vlan` / `trunk_allowed_vlans`).  The
canonical layer offers `project_vlan_to_switchport` to bridge the
two views, but **only `cisco_iosxe_cli`** calls it on the render
side.  Every other port-centric target codec reads only
interface-level fields and silently drops the VLAN-list inputs.
That single architectural gap accounts for **~25 of 36** findings.

## CODEC_BUG breakdown — by target

### juniper_junos (17 findings)

#### J1. `vlans[].tagged_ports` / `vlans[].untagged_ports` dropped on render (11 findings, 6 fixtures)

* **Field**: `vlans[].tagged_ports` and `vlans[].untagged_ports`
  (per-record, list-of-string).
* **Drift detail (every aruba fixture with VLAN port lists)**:
  source has populated lists e.g. `['1/25', '1/26']` for VLAN 20
  tagged_ports on `aruba_central_5memberstack_rendered.cfg`; target
  is `[]` for every VLAN, every port.
* **Phase 3 expectation**: `vlans.disposition: good` with
  `tagged_ports: good` / `untagged_ports: good` in the
  `aruba_aoss__juniper_junos.yaml` cell.
* **Side responsible**: **target render-side bug**, juniper_junos.
  `netconfig/migration/codecs/juniper_junos/render.py` lines 309–321
  emit `set vlans <NAME> vlan-id <ID>` (and the optional VXLAN VNI),
  but *never* emit `set interfaces <iface> unit 0 family
  ethernet-switching vlan members <NAME>` (or
  `interface-mode access`/`trunk`) for L2 ports.  The renderer also
  ignores `vlan.ipv4_addresses` — Junos `set interfaces irb unit N
  family inet address <ip>/<prefix>` is the equivalent SVI form.
  The L2-on-Junos grammar simply has no codepath in this file.
* **Likely fix location**:
  * `netconfig/migration/codecs/juniper_junos/render.py` — call
    `from ...canonical.transforms import project_vlan_to_switchport`
    `project_vlan_to_switchport(tree)` at the top of `render_intent`
    (mirroring `cisco_iosxe_cli/render.py` lines 70–71), AND extend
    the per-interface emit block (lines 204–307) to handle
    `iface.switchport_mode` by emitting `set interfaces <name> unit
    0 family ethernet-switching interface-mode <access|trunk>` and
    `… vlan members <vlan-name>`.  Use a `vlan_name_by_id` lookup
    built from `tree.vlans` since Junos references VLANs by name,
    not VID.
  * Reciprocal parse-side support already exists implicitly via the
    Junos `family ethernet-switching` grammar but check `parse.py`
    handles the VLAN-by-NAME → vid resolution path (line 608–947 has
    the vlan stanza parser; the per-iface ethernet-switching path
    needs verifying as a separate sub-task).
* **Test that would catch the fix**:
  `tests/unit/migration/codecs/juniper_junos/test_render_l2_switchports.py`
  — build a `CanonicalIntent` containing one `CanonicalVlan(id=10,
  name='USERS', untagged_ports=['ge-0/0/1'])` plus the matching
  `CanonicalInterface(name='ge-0/0/1', switchport_mode='access',
  access_vlan=10)` and assert the rendered output contains both
  `set vlans USERS vlan-id 10` and `set interfaces ge-0/0/1 unit 0
  family ethernet-switching interface-mode access` plus
  `… vlan members USERS`.

#### J2. `vlans[].ipv4_addresses` dropped (4 findings, 3 fixtures: 2920, 2930f-wc1607, 2930f-wc1610)

* **Field**: `vlans[].ipv4_addresses` (list of `{ip, prefix_length}`).
* **Drift detail**: source carries SVI addresses e.g.
  `[{'ip': '192.168.176.35', 'prefix_length': 24}]` on VLAN 1; target
  is `[]`.
* **Phase 3 expectation**: `vlans.ipv4_addresses: good` in
  `aruba_aoss__juniper_junos.yaml`.
* **Side responsible**: **target render-side bug**, juniper_junos.
  Same root cause as **J1** — the renderer drops the SVI on render.
  Junos's idiom is `set interfaces irb unit <vid> family inet address
  X/Y` (per-VLAN sub-unit on the `irb` pseudo-interface).  No code
  path emits this today.
* **Likely fix location**:
  `netconfig/migration/codecs/juniper_junos/render.py` — extend the
  vlans emit block (lines 309–321) to also emit
  `set interfaces irb unit <vlan.id>`, `… vlan-id <vlan.id>` (the
  inner VLAN tag on the IRB unit), and one
  `… family inet address <ip>/<prefix>` per `vlan.ipv4_addresses`
  entry.  Pair with the missing `set vlans <NAME> l3-interface irb.<vid>`
  binding so the SVI is bound to its VLAN.
* **Test**: extend the J1 test with a vlan SVI assertion.

#### J3. `interfaces[].lag_member_of` dropped on kitchen_sink (1 finding)

* **Field**: `interfaces[].lag_member_of`.
* **Drift detail**: source `interfaces[3] {'name': '23'}` and
  `interfaces[4] {'name': '24'}` carry `lag_member_of='trk1'`; target
  is `null` for both.
* **Phase 3 expectation**: `interfaces.lag_member_of: good` in
  `aruba_aoss__juniper_junos.yaml`.
* **Side responsible**: **target render-side bug**, juniper_junos.
  `grep -n "lag\|aggregate\|tree.lags" juniper_junos/render.py`
  returns zero matches — the renderer has no LAG path at all.  Junos
  expresses LAGs as `set interfaces ae<N> aggregated-ether-options
  lacp active` (or static) plus `set interfaces <member>
  ether-options 802.3ad ae<N>`; both forms are absent.
* **Likely fix location**:
  `netconfig/migration/codecs/juniper_junos/render.py` — add a LAG
  block (analogous to the `tree.routing_instances` block at lines
  346–411) that iterates `tree.lags` plus per-interface
  `iface.lag_member_of`, emitting the two-sided `ae<N>` grammar.
  Choose `ae<N>` numbering by stripping the leading non-digit chars
  off the canonical LAG name (`trk1` → `ae1`, `Port-Channel5` →
  `ae5`); fall back to enumeration if no digits.
* **Test**: `tests/unit/migration/codecs/juniper_junos/test_render_lag.py`
  asserting the both-sides emit + reparse round-trip preserves
  `lag_member_of` and `tree.lags` ordering.

#### J4. `static_routes` count drift on hpe_community_2930f_wc1607_intervlan (1 finding)

* **Field**: `static_routes` (list-of-record, count drift 4 → 3).
* **Drift detail**: source has duplicate
  `{destination: '0.0.0.0/0', gateway: '192.168.2.11', ...}` records
  (one from `ip default-gateway`, one from `ip route 0.0.0.0
  0.0.0.0 192.168.2.11` in the fixture).  Target has only one — Junos
  `set routing-options static route 0.0.0.0/0 next-hop 192.168.2.11`
  is naturally idempotent, so the duplicate gets de-dup'd on
  re-parse.
* **Phase 3 expectation**: `static_routes.disposition: good` in
  `aruba_aoss__juniper_junos.yaml`.
* **Side responsible**: **source parse-side bug**, aruba_aoss.  The
  parser at `netconfig/migration/codecs/aruba_aoss/parse.py` should
  not emit two distinct `CanonicalStaticRoute` records for the same
  `(destination, gateway)` tuple.  `ip default-gateway X` and `ip
  route 0.0.0.0 0.0.0.0 X` are operationally equivalent; the parser
  should dedupe.  Equivalently, only one of the two pathways should
  populate `intent.static_routes` (preferred: `ip default-gateway`
  takes precedence and `ip route 0.0.0.0/0` is ignored when an
  identical default-gateway route already exists).
* **Likely fix location**:
  `netconfig/migration/codecs/aruba_aoss/parse.py` — at the static
  routes accumulation point, gate on `(destination, gateway)`
  uniqueness.  Or split into two phases: first pass collects all
  candidates, second pass dedupes by tuple key.
* **Test**: `tests/unit/migration/codecs/aruba_aoss/test_parse_static_routes_dedup.py`
  asserting that an input with both `ip default-gateway 10.0.0.1`
  and `ip route 0.0.0.0 0.0.0.0 10.0.0.1` parses to exactly one
  `CanonicalStaticRoute` for `0.0.0.0/0 → 10.0.0.1`.

### opnsense (8 findings)

#### O1. Interface zone-name lossiness on aruba_central_5memberstack (4 findings)

* **Field**: `interfaces[].description`, `.enabled`, `.ipv4_addresses`,
  `.ipv6_addresses` — all four flag `count drift: 48 → 46` for the
  same fixture.
* **Drift detail**: source has 48 `intent.interfaces`; target has
  46 after round-trip.  All four fields share the same root-cause
  (count change in the underlying list).
* **Phase 3 expectation**: per `aruba_aoss__opnsense.yaml`,
  `interfaces.description / enabled / ipv4_addresses / ipv6_addresses:
  good` (asymmetric — opnsense's IP wireup is best-effort the other
  direction, but `aruba → opnsense` is the lossless direction here).
* **Side responsible**: **target render-side bug** (combined with
  parse-side asymmetry), opnsense.  Two cooperating defects:
  1. *Zone-tag mangling of bare-numeric port names*:
     `netconfig/migration/codecs/opnsense/render.py` line 279
     (`_zone_tag_for`) sanitises Aruba's bare-numeric port names
     (`"1"`, `"25"`, `"1/A1"`) into XML element tags by lowercasing,
     replacing non-alphanumeric chars with `_`, and prepending `if_`
     when the first char is a digit.  Result: port `"1"` → tag
     `<if_1>`, port `"1/A1"` → tag `<if_1_a1>`, etc.  But the
     renderer **never emits an `<if>` child element** carrying the
     original port name (real OPNsense always does;
     `<lan><if>igb0</if>...</lan>`), so the original port-name
     information is destroyed and re-parse uses the sanitised tag
     as the canonical iface name (line 354 of `parse.py`:
     `zone = el.tag` → `iface = CanonicalInterface(name=zone)`).
  2. *Empty-zone drop*: `parse.py` lines 354–360 drop a zone if it
     has no `<if>` *and* zero children (`if len(list(el)) == 0:
     return None`).  When two distinct Aruba ports sanitise to the
     same tag (e.g. when there are duplicates produced by a
     fall-through path in render), one of them collides and the
     parser's element iteration sees only the last write — net 48
     → 46 because two pairs of port names collapsed into the same
     XML tag.
* **Likely fix location**:
  * Primary: `netconfig/migration/codecs/opnsense/render.py` lines
    126–144 — emit a stable `<if>` child element holding the
    original port name (`ET.SubElement(zone_el, "if").text =
    iface.name`) so the parser can recover the canonical name and
    the interface-zone <—> port-name mapping is invertible.  Mirrors
    real OPNsense XML.
  * Secondary: `opnsense/parse.py` `_parse_interface_zone_canonical`
    line 360 — when `<if>` is present, use `iface =
    CanonicalInterface(name=if_el.text.strip())` instead of zone
    tag; when missing, keep the zone tag as a fallback for legacy
    cases.
  * Tertiary: `_zone_tag_for` should detect collisions and append
    a disambiguator (`_2`, `_3`, …) so two distinct iface names
    never end up on the same tag.
* **Test**: `tests/unit/migration/codecs/opnsense/test_iface_name_roundtrip.py`
  with a `CanonicalIntent` carrying interfaces named `"1"`, `"1/A1"`,
  `"GigabitEthernet0/0/0"`, asserting render+reparse preserves the
  canonical names and total count.

#### O2. Per-record description / enabled / ipv4 / ipv6 misalignment on kitchen_sink (4 findings)

* **Field**: `interfaces[].description` (5 records mismatched by index),
  `.enabled` (2 records flipped), `.ipv4_addresses` (2 records),
  `.ipv6_addresses` (2 records).
* **Drift detail**: source `interfaces[0] {'name': '1'}` desc =
  'user-desk-01' but target same index slot desc = 'router-uplink-A'
  (i.e. the iface that was actually `interface A1` in the fixture).
  Confirmed via local repro: source canonical names are
  `['1', '13', '21', '23', '24', 'A1', 'A2', 'Trk1', 'Trk2']`;
  target canonical names are
  `['if_1', 'if_13', 'if_21', 'if_23', 'if_24', 'a1', 'a2', 'trk1', 'trk2']`.
  The drift comparator is keying records by the source-side `name` —
  none of the targets match because they all got mangled — so the
  comparator falls through to positional matching, hence the
  five-by-five "everyone misaligned by index" output.
* **Phase 3 expectation**: same as O1 — opnsense YAML rates these as
  `good` for the aruba→opnsense direction.
* **Side responsible**: **target render-side bug**, opnsense — same
  zone-tag mangling root cause as O1, surfaced differently because
  this fixture has interfaces with distinct names (no collision)
  but the names still lose information (`A1` becomes `a1`,
  `Trk1` becomes `trk1`).  The fix in O1 (emit `<if>` with original
  name) clears these too.
* **Likely fix location**: identical to O1 above.
* **Test**: identical to O1 above (the test cases already cover
  letter-prefix names like `A1`).

### arista_eos (7 findings)

#### A1. `vlans[].tagged_ports` / `untagged_ports` / `ipv4_addresses` dropped (5 findings, 5 fixtures via consolidated `vlans` field)

* **Field**: `vlans` (list-of-record drift, all four sub-fields:
  tagged_ports, untagged_ports, ipv4_addresses).  The Phase 4 cell
  reports this as a single `vlans` field-variance per fixture
  rather than per sub-field.
* **Drift detail**: source has fully populated `tagged_ports` /
  `untagged_ports` / `ipv4_addresses`; target has all three empty
  for every VLAN.
* **Phase 3 expectation**: `vlans.disposition: good` with all three
  sub-fields `good` per `aruba_aoss__arista_eos.yaml`.
* **Side responsible**: **target render-side bug**, arista_eos.
  `netconfig/migration/codecs/arista_eos/render.py` lines 130–135
  emit `vlan <id>` + `   name <name>`, but the renderer never calls
  `project_vlan_to_switchport` (only `cisco_iosxe_cli` does today).
  The per-iface `switchport access vlan` block at lines 159–171
  reads `iface.access_vlan` / `iface.trunk_allowed_vlans` — both
  empty when the source is aruba_aoss (since aruba's parser only
  populates the VLAN-centric port lists).  Result: arista renders
  bare `vlan <id>` declarations and zero switchport assignments.
  The vlan SVI (`interface Vlan<N>` + `   ip address X/Y`) is also
  not emitted — `tree.vlans[].ipv4_addresses` is read nowhere in
  this render.py.
* **Likely fix location**:
  * `netconfig/migration/codecs/arista_eos/render.py` near line 70 —
    add `from ...canonical.transforms import project_vlan_to_switchport`
    and call `project_vlan_to_switchport(tree)` before the interface
    emit loop.  This populates `iface.access_vlan` / `trunk_allowed_vlans`
    / `switchport_mode` from the VLAN-centric source.
  * Same file, near line 135 — extend the vlans block to emit
    `interface Vlan<vlan.id>` + `   ip address <ip>/<prefix>` when
    `vlan.ipv4_addresses` is non-empty (Arista SVI grammar).
* **Test**:
  `tests/unit/migration/codecs/arista_eos/test_render_vlan_centric_input.py`
  asserting that a `CanonicalIntent` carrying VLAN-centric port
  membership (no per-iface `access_vlan`) renders to interface
  stanzas with `switchport mode access` + `switchport access vlan
  N`, plus an `interface Vlan<N>` SVI when `vlan.ipv4_addresses` is
  populated.

#### A2. `radius_servers` dropped on kitchen_sink (1 finding)

* **Field**: `radius_servers` (list-of-record, count drift 2 → 0).
* **Drift detail**: source has two RADIUS servers (10.0.20.10,
  10.0.20.11); target has zero.  `drift_detail.drift = "all 2
  radius_servers dropped"`.
* **Phase 3 expectation**: `radius_servers.disposition: good` in
  `aruba_aoss__arista_eos.yaml`.
* **Side responsible**: **target render-side bug**, arista_eos.
  `grep -n "radius" arista_eos/render.py` returns zero matches —
  `tree.radius_servers` is never read.
* **Likely fix location**:
  `netconfig/migration/codecs/arista_eos/render.py` — add a block
  emitting `radius-server host <host> key <key>` + `auth-port` /
  `acct-port` per `tree.radius_servers` entry (Arista CLI grammar).
* **Test**: `tests/unit/migration/codecs/arista_eos/test_render_radius_servers.py`
  asserting that `CanonicalIntent(radius_servers=[CanonicalRadiusServer(host='1.2.3.4', key='secret', auth_port=1812, acct_port=1813)])` renders the matching `radius-server host 1.2.3.4 key secret auth-port 1812 acct-port 1813` line and round-trips.

#### A3. `interfaces[].lag_member_of` (covered under A1 indirectly)

The kitchen_sink Arista cell does not surface `lag_member_of` drift
explicitly because the EOS render does emit `channel-group N mode
<mode>` when the canonical bears `lag_member_of` (see
`arista_eos/render.py` lines 191–207).  Aruba's `Trk1` LAG name
parses to `lag_member_of='trk1'`, but EOS expects
`Port-Channel<N>` — the regex at line 192 (`r"^Port-Channel(\d+)$"`)
fails to match `trk1` and the channel-group line is suppressed.
This is **not captured** in the JSON CODEC_BUG list because the
field-variance comparator probably treats it as alignable, but it
is a latent issue worth a follow-up: when the canonical LAG name
isn't EOS-shaped, the renderer should map it (`trk1` → `Port-Channel1`)
or emit a `description LAG-trk1` placeholder.

### cisco_iosxe_cli (4 findings)

#### C1. `dns_servers` dropped on round-trip (3 findings, 3 fixtures: aruba_central_5memberstack, hpe_community_2930f_wc1607, kitchen_sink)

* **Field**: `dns_servers` (list of IPv4 strings).
* **Drift detail (every fixture with DNS configured)**:
  e.g. `['192.168.10.4']` for aruba_central; target `[]`.
  `drift_detail.drift = "all N dns_servers dropped"`.
* **Phase 3 expectation**: `dns_servers.disposition: good` in
  `aruba_aoss__cisco_iosxe_cli.yaml`.
* **Side responsible**: **target parse-side bug**, cisco_iosxe_cli.
  Render is correct: `cisco_iosxe_cli/render.py` lines 122–123 emit
  `ip name-server <srv>` per `tree.dns_servers` entry.  But
  `cisco_iosxe_cli/parse.py` has no top-level `ip name-server`
  handler (`grep "name-server\|name_server" cisco_iosxe_cli/parse.py`
  returns only the DHCP-pool sub-handler at line 760).  Net effect:
  the rendered output contains the DNS lines, but re-parse drops
  them.
* **Likely fix location**:
  `netconfig/migration/codecs/cisco_iosxe_cli/parse.py` — add a
  top-level line handler near the existing global-scope handlers
  (e.g. parallel to NTP / banner / domain-name handling).  Pattern:
  match `^ip name-server (.+)$`, split on whitespace, extend
  `intent.dns_servers`.  ~5 lines total.
* **Test**:
  `tests/unit/migration/codecs/cisco_iosxe_cli/test_parse_dns_servers.py`
  asserting that
  `parse_intent("ip name-server 1.1.1.1\nip name-server 8.8.8.8\n").dns_servers == ["1.1.1.1", "8.8.8.8"]`.

#### C2. `vlans[].untagged_ports` partial drift on aruba_central_5memberstack (1 finding, surfaces under `vlans` consolidated)

* **Field**: `vlans` (list-of-record drift, sub-field
  `untagged_ports` on VLAN 20 USERS and VLAN 30 VOICE).
* **Drift detail**: VLAN 1 `DEFAULT_VLAN` keeps its 24 untagged
  ports through the round-trip; but VLAN 20 USERS and VLAN 30 VOICE
  lose their port lists (source had 12 each, target has `[]`).
* **Phase 3 expectation**: `vlans.untagged_ports: good` in
  `aruba_aoss__cisco_iosxe_cli.yaml`.
* **Side responsible**: **target codec ambiguity** — this is the
  one case where `cisco_iosxe_cli` *does* call
  `project_vlan_to_switchport`, but the source data is itself
  ambiguous.  The Aruba fixture has ports `1/1..1/12` listed as
  untagged on **both** VLAN 1 (DEFAULT) AND VLAN 20 (USERS) (the
  fixture uses overlapping membership / "primary-vlan" semantics).
  When `project_vlan_to_switchport` sees a port in two
  `untagged_ports` lists, it can only assign it to a single
  `iface.access_vlan` (line 218–221 of
  `netconfig/migration/canonical/transforms.py` does
  `iface.access_vlan = u_vids[0]`) — the FIRST one wins, which is
  VLAN 1 since it appears first in `intent.vlans`.  After render +
  re-parse + back-projection, those ports get attributed only to
  VLAN 1.
* **Likely fix location**:
  * Either the Aruba parser should resolve overlap at parse time —
    detect when VLAN 1 (DEFAULT) untagged-list duplicates a port
    that is also untagged on a non-default VLAN and DROP the
    DEFAULT side (since on Aruba the explicit VLAN wins
    operationally and DEFAULT is a fallback).  Source:
    `netconfig/migration/codecs/aruba_aoss/parse.py` — at the
    end of `parse_intent`, walk `intent.vlans` and prune ports
    from VLAN 1 (DEFAULT_VLAN) that appear in any other VLAN's
    untagged_ports.
  * Or `project_vlan_to_switchport` should prefer the
    non-default VLAN when a port appears in multiple untagged
    lists (line 218–221 of `transforms.py` — change `u_vids[0]`
    to `next((v for v in u_vids if v != 1), u_vids[0])`).
* **Test**: `tests/unit/migration/codecs/aruba_aoss/test_parse_default_vlan_overlap.py`
  asserting that an Aruba fixture with both
  `vlan 1\n  untagged 1\nvlan 20\n  untagged 1\n` resolves so
  that port `1` ends up only in VLAN 20's untagged_ports (the
  explicit non-default).

## Cross-cutting bugs

Three patterns repeat across multiple targets; fixing them at the
canonical / source layer would resolve **the bulk of the 36
findings** in one stroke:

* **VLAN-centric → port-centric projection is missing on most
  port-centric targets.**  Only `cisco_iosxe_cli` calls
  `project_vlan_to_switchport` today
  (`grep -rn "project_vlan_to_switchport" netconfig/migration/codecs/`
  → 2 hits, both in `cisco_iosxe_cli`).  The same call is missing
  from `arista_eos/render.py` and `juniper_junos/render.py`, which
  is why those two targets account for 24 of 36 findings.  The
  cleanest fix is to add the call (1 line each) at the top of
  each render entry point.  Note `juniper_junos` ALSO needs its
  L2-on-Junos emit codepath built (the projection feeds it data,
  but the emit lines are absent — see J1).
* **Aruba VLAN-centric model loses information vs every
  port-centric target's interface model when there's overlap.**
  When a port appears in multiple `untagged_ports` lists (Aruba's
  primary-vlan semantics), the projection collapses to the first
  match.  See C2.  Either the Aruba parser should pre-resolve
  overlaps at parse time, OR the projection should prefer
  non-default VLAN.
* **OPNsense interface-zone tagging is not invertible.**  Real
  OPNsense XML always emits `<if>foo</if>` inside the zone element;
  the netconfig render emits only the sanitised zone tag.  This
  surfaces as O1+O2 (8 findings) but would also bite any future
  cross-vendor pairing where opnsense is the round-trip stage.

## METHODOLOGY_ISSUE_under demotion analysis

All 1018 `METHODOLOGY_ISSUE_under` findings have `source_count` ∈
{0, None} — i.e. the source aruba fixture has zero records for the
field, so the round-trip "preserved" an empty list trivially.  Per
the prompt's skepticism rule, every one of these demotes from
under-flag to fixture-coverage-gap (severity=ok / informational).

Concretely:

* `vxlan_vnis`, `evpn_type5_routes`, `routing_instances`,
  `apply_groups`, `group_content`, `raw_sections` — Aruba is a
  campus L2 switch codec; these advanced/multi-vendor fields are
  always source-empty and the YAMLs already mark them
  `not_applicable` or `unsupported`.
* `interfaces[].voice_vlan`, `.lag_member_of` (when the fixture
  has no LAGs), `.trunk_native_vlan` — fixture-dependent;
  source-empty when the underlying config doesn't use the feature.
* `dhcp_pools`, `local_users`, `radius_servers`, `snmp.*` — none
  of the fixtures except `kitchen_sink.cfg` exercise these, so
  six of seven fixtures generate spurious `under` flags.

Recommend: the Phase 4 reconciliation tool gain a post-classification
sweep that recategorises any `METHODOLOGY_ISSUE_under` with
`source_count == 0` (or absent) into a new
`METHODOLOGY_ISSUE_source_empty` bucket at severity=ok, so the
remaining `under` count flags only genuine under-coverage.

No high-severity findings remain after this demotion — all 1018
are source-empty.

## Top three actionable fix locations (ranked by Σ codec-bug count)

1. **Add `project_vlan_to_switchport` call to two render entry
   points**: `netconfig/migration/codecs/arista_eos/render.py`
   (near line 130) and `netconfig/migration/codecs/juniper_junos/render.py`
   (near line 309).  One-line addition each, plus building the
   downstream emit paths (Junos has no L2 ethernet-switching emit
   today; Arista already has the per-iface block, just needs the
   data flow).  Touches **~22 of 36** findings (juniper_junos J1+J2
   = 15, arista_eos A1 = 7) once paired with the missing emits.
2. **Add `ip name-server` parser to cisco_iosxe_cli**:
   `netconfig/migration/codecs/cisco_iosxe_cli/parse.py` — a ~5-line
   line-level handler.  Touches **3 of 36** findings (C1) and is
   the cheapest single fix in the set; the render side already works.
3. **Emit `<if>` element + use it on parse for opnsense interfaces**:
   `netconfig/migration/codecs/opnsense/render.py` lines 126–144
   (add `ET.SubElement(zone_el, "if").text = iface.name`) paired
   with `opnsense/parse.py` line 360 (use `<if>` text as canonical
   name).  Touches **8 of 36** findings (O1+O2).

Combined, fixes (1)–(3) clear **~33 of 36** aruba_aoss-source
CODEC_BUG findings.  The remaining 3 are: J3 juniper LAG render
(needs whole-block addition), J4 aruba static_route dedup, and
A2 arista radius_servers render (each a ~10-line addition).

## Demoted findings

None of the 36 CODEC_BUG findings demote — each has `source_count >
0` and a real drift in a Phase-3-`good` field.  The demotion bucket
is entirely populated by the 1018 `METHODOLOGY_ISSUE_under` cells,
which all have `source_count = 0` and are documented above.

## See also

* `tests/fixtures/real/PHASE4_RECONCILIATION.md` — Phase 4a aggregate
* `tests/fixtures/real/phase4_findings_fortigate_cli.md` — sibling
  Phase 4b investigation (overlapping themes: project-projection
  call gaps, opnsense interface-zone bugs)
* `tests/fixtures/real/phase4_findings_mikrotik_routeros.md` — sibling
* `tests/fixtures/cross_vendor_expectations/aruba_aoss__juniper_junos.yaml`
* `tests/fixtures/cross_vendor_expectations/aruba_aoss__opnsense.yaml`
* `tests/fixtures/cross_vendor_expectations/aruba_aoss__arista_eos.yaml`
* `tests/fixtures/cross_vendor_expectations/aruba_aoss__cisco_iosxe_cli.yaml`
* `netconfig/migration/canonical/transforms.py` —
  `project_vlan_to_switchport` is the canonical bridge whose
  under-adoption explains 22+ of 36 findings.

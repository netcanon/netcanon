# Phase 4b — `juniper_junos` (set-form CLI) source findings

Source codec: `juniper_junos`
(`netconfig/migration/codecs/juniper_junos/parse.py`).  This codec is
the most richly populated source in the cross-mesh: a single Junos
`set` config legitimately carries apply-groups + group_content, MAC-VRF
/ L3-VRF / virtual-router routing-instances, VXLAN VNIs (incl. EVPN
type-5 prefix routes), full SNMPv3 with auth/priv passphrases,
multi-hash local users (`$6$` plus `ssh-rsa` keys), and irb / unit
sub-interfaces.  When a target codec has aspirational capability-
matrix wire-up gaps, the rich Junos source surfaces them at high
volume — hence the 97 CODEC_BUG variances flagged across the seven
target pairs (the largest per-source total in the run).

Inputs reconciled:

* `tests/fixtures/real/_phase4_runs/latest.json` (run
  `2026-05-02T06:54:10Z`, mesh run `20260501T141211Z.json`)
* `tests/fixtures/cross_vendor_expectations/juniper_junos__<target>.yaml`
  for the seven cross-vendor pairs (intra-vendor self-pair has no
  Phase-3 YAML by design)
* Six fixtures exercise this source codec — five real captures
  (`batfish_evpntype5_router1_junos2541.set`,
  `batfish_l3vpn_pe1_junos2541.set`,
  `buraglio_netlab_junos184.set`,
  `ksator_labmgmt_ex4550_junos151.set`,
  `ksator_labmgmt_qfx5100_junos173.set`) plus the synthetic
  `kitchen_sink.set` which intentionally maxes out tier-2 and tier-3
  surfaces (16 interfaces, 4 VLANs, 3 routing-instances spanning
  vrf / mac-vrf / virtual-router, full SNMPv3, $6$ + ssh-rsa local
  users, EVPN VXLAN VNIs, apply-groups inheritance).

## CODEC_BUG counts per target

| Target              | CODEC_BUG | Notes                                                                                |
|---------------------|----------:|--------------------------------------------------------------------------------------|
| arista_eos          |         6 | All 6 on `routing_instances[*]` of one fixture — MAC-VRF reverse-binding gap         |
| aruba_aoss          |        40 | Count drift on every fixture except `buraglio` — Aruba parser-side iface regex       |
| cisco_iosxe (NETCONF) |       0 | All drift covered by EXPECTED_LOSSY (Phase-0.5 stub on the target side)              |
| cisco_iosxe_cli     |         4 | `dns_servers` (3 fixtures), `domain` (1) — IOS-XE CLI parser missing top-level wire-up |
| fortigate_cli       |        11 | Pure-L2 VLANs dropped; `domain` not emitted; SNMP false-positives                    |
| juniper_junos (self)|         0 | Self round-trip, no YAML                                                             |
| mikrotik_routeros   |        32 | Render-side gap: descriptions / mtu / enabled never flow through `/ip address`-only ifaces |
| opnsense            |         4 | All 4 SNMP false-positives (Phase-1 dict-snapshot truncation)                        |
| **Σ**               |    **97** |                                                                                      |

The 97 high-severity CODEC_BUG findings reduce to **eight distinct
root causes**.  Three of those are render-side gaps in target codecs
the Junos source is unusually likely to surface (Aruba iface header
regex, Mikrotik render loses non-IP-only iface metadata, Fortigate
drops pure-L2 VLANs and `domain`).  Two are parser-side gaps in
target codecs (Cisco IOS-XE CLI never wires top-level `ip
name-server` / `ip domain name`).  One is a renderer reverse-lookup
gap on the Arista side (MAC-VRF needs vlan-id binding).  And two are
Phase-1 methodology issues (dict source/target snapshots truncated to
key-lists, plus YAML expectations overly optimistic about pure-L2
VLANs and `domain` survival).

---

## Finding 1 — aruba_aoss: count drift cascade from interface header regex (40 / 97)

**Pair affected:** `juniper_junos → aruba_aoss` (40 CODEC_BUGs across
five fixtures: `batfish_evpntype5`, `batfish_l3vpn`,
`ksator_labmgmt_ex4550`, `ksator_labmgmt_qfx5100`, `kitchen_sink`).
Every per-iface field flagged: `description`, `enabled`,
`ipv4_addresses`, `ipv6_addresses`, `switchport_mode`, `access_vlan`,
`trunk_allowed_vlans`, `lag_member_of`.

**What drifted.**  Phase-1 `field_disposition.interfaces` count drifts:

* `batfish_evpntype5`: source_count=10 → target_count=2
* `batfish_l3vpn`:     source_count=4  → target_count=2
* `ksator_ex4550`:     source_count=4  → target_count=1
* `ksator_qfx5100`:    source_count=12 → target_count=2
* `kitchen_sink`:      source_count=16 → target_count=5

Reproduced locally for `kitchen_sink`: Aruba RENDERS all 16
interfaces (including `ge-0/0/0`, `ge-0/0/1.100`, `irb`, `irb.100`,
`xe-0/0/0` style names) but Aruba RE-PARSES only `ae0`, `ae1`, `em0`,
`fxp0`, `lo0`.  Every `ge-`, `xe-`, sub-unit (`*.100`) and `irb`-style
name is silently dropped on re-parse.  The `buraglio_netlab` fixture
is the lone exception (0 CODEC_BUG) because its iface inventory is
limited to simple AOS-S-shaped names.

**Codec responsible.**  Target — aruba_aoss parser, with cooperating
flaw on the render side.

**Likely fix location.**

* `netconfig/migration/codecs/aruba_aoss/parse.py:174-176` —
  ```
  _IFACE_HEADER_RE = re.compile(
      r'^interface\s+("?[A-Za-z]*\d+(?:/\d+)?"?)\s*$', re.IGNORECASE,
  )
  ```
  The regex demands `[A-Za-z]*\d+(?:/\d+)?`: matches `ae0`, `lo0`,
  `1`, `A1`, `Trk1` but rejects `ge-0/0/1` (hyphen + double slash),
  `ge-0/0/1.100` (sub-unit dot), `irb` (no digit), `irb.100` (dot),
  `xe-0/0/0` (hyphen + double slash), `Port-channel1` (hyphen),
  `Vlan100` (works — has digit) and so on.  The render path
  (`render.py:329-332`) emits `interface {iface.name}` literally
  without any port-rename mesh, so it writes bytes the parser
  immediately cannot read.  This is the canonical "render-emits-but-
  parse-rejects" mismatch.

  Two ways to fix:
  * Widen the regex to `^interface\s+("?[A-Za-z][\w./\-]*"?)\s*$`
    (cheap; preserves the asymmetric-rename tech-debt for later);
    OR
  * Apply the existing port-rename mesh in `aruba_aoss/render.py`
    so Junos `ge-0/0/1` → AOS-S `1/1` (or whatever the mesh
    decides) before emit.  Architecturally cleaner.  The
    cross-vendor expectation YAMLs (e.g.
    `juniper_junos__aruba_aoss.yaml`) already presume a port-rename
    mesh for `interfaces[].name`.

**Test that would catch the fix.**

* Pure unit test in
  `tests/unit/migration/codecs/aruba_aoss/test_parse_iface_header.py`
  asserting `_IFACE_HEADER_RE.match("interface ge-0/0/1")`,
  `match("interface ge-0/0/1.100")`, `match("interface irb")` are
  all non-None (currently all None).
* Cross-vendor regression in
  `tests/integration/migration/test_junos_to_aruba_round_trip.py`
  using `kitchen_sink.set` and asserting iface count preserves
  through round-trip (currently 16 → 5; should hold at 16 once
  parser widens or rename mesh applies).

---

## Finding 2 — mikrotik_routeros: render-side gap on non-IP-only interfaces (28 / 97)

**Pair affected:** `juniper_junos → mikrotik_routeros` (28
CODEC_BUGs counting just the per-iface fields; the additional 4 SNMP
findings on the same pair are split out as Finding 7 since they
share root cause with Finding 7).

**What drifted.**  Per-iface fields show count drift in the
mikrotik `field_disposition.interfaces`:

* `batfish_evpntype5`: 10 → 13 (mikrotik adds synthetic vlan ifaces)
* `ksator_ex4550`:     4 → 7
* `ksator_qfx5100`:   12 → 17
* `kitchen_sink`:     16 → 13 (lost 3 net: render-only `/ip address`
  ifaces aren't reattached to a per-iface stanza on parse)

The mikrotik render at
`netconfig/migration/codecs/mikrotik_routeros/render.py:85-191` only
emits a real `/interface ethernet` stanza when an iface has either
`_is_ethernet_name(i.name)` OR `i.default_name` set (Junos source
sets neither for `ge-0/0/X` names — those don't match the RouterOS
"ether1, ether2..." default-name convention).  Junos's
non-ethernet-named ifaces (`ge-0/0/0`, `ge-0/0/1`, `irb`, `lo0`,
`xe-0/0/0`) only reach the wire as bare `add address=A.B.C.D
interface=NAME` lines under `/ip address` — without the
`/interface ethernet` stanza, the description / mtu / enabled / dhcp
flags for those ifaces never make it to the rendered config.  When
re-parsed the iface materialises (because it has an IP record) but
its description/mtu/enabled all read as defaults (drifted vs source).

**Codec responsible.**  Target — mikrotik_routeros render.

**Likely fix location.**

* `netconfig/migration/codecs/mikrotik_routeros/render.py:85-110` —
  the `ethernet_ifaces` filter requires `_is_ethernet_name` or a
  tracked `default_name`.  Cross-vendor source codecs don't populate
  `default_name`, and Junos ports (`ge-`, `xe-`, `et-`) aren't
  `ether1`-shaped.  Two fix shapes:
  * Loosen the filter so any non-VLAN, non-bridge,
    non-bonding iface that carries description / mtu / enabled
    state emits a `/interface ethernet set` line keyed by `name=`
    (RouterOS accepts `set [ find name=ge-0/0/1 ]` even though
    the iface won't exist on a real device — that's a deploy-time
    issue, not a render-time one; the data is preserved).  OR
  * Add a port-rename mesh that maps `ge-0/0/N` → RouterOS
    `etherN+1` etc. so the renderer can target the device's real
    default-name.  Architecturally cleaner; same theme as the
    aruba_aoss port-rename mesh deferred in Finding 1.
* The `/interface vlan` block (line 155-192) already correctly
  surfaces canonical `l3ipvlan` ifaces by name — confirmed
  working for `vlan10` / `vlan20` etc.  The issue is purely the
  ethernet branch.

**Test that would catch the fix.**

* Unit test in
  `tests/unit/migration/codecs/mikrotik_routeros/test_render_non_default_name.py`
  asserting that `render_intent(intent_with_iface(name="ge-0/0/1",
  description="trunk", mtu=9216, enabled=False))` emits both
  `/interface ethernet` set-line AND `/ip address` line; asserting
  re-parse preserves description, mtu, enabled.

---

## Finding 3 — fortigate_cli: pure-L2 VLANs dropped on render (6 / 97)

**Pairs affected:** `juniper_junos → fortigate_cli` —
`vlans[].id` (3) + `vlans[].ipv4_addresses` (3).

**What drifted.**  Phase-1 `field_disposition.vlans` count drifts:

* `ksator_ex4550`:    "all 6 vlans dropped"
* `ksator_qfx5100`:   "all 16 vlans dropped"
* `kitchen_sink`:     4 → 2 (USERS, VOICE dropped; TENANT_A_DATA,
  TRANSIT survive — the latter two have associated `irb.100` /
  `irb.200` SVIs)

Reproduced for `kitchen_sink`: Junos defines four VLANs; only the
two with an irb sub-interface (carrying an IPv4 address) round-trip.
The other two (USERS=10, VOICE=20 — pure L2) are silently dropped.

**Codec responsible.**  Target — fortigate_cli render.

**Likely fix location.**

* `netconfig/migration/codecs/fortigate_cli/render.py:118-147` —
  the VLAN emit path is gated on
  `iface.interface_type == "ianaift:l3ipvlan"
  or _looks_like_vlan_iface(iface.name)`.  Pure `tree.vlans[*]`
  records without an SVI have no canonical interface and never
  reach the loop.  FortiGate-native syntax DOES support a bare
  vlan-child interface without an IP (the `set type vlan / set
  vlanid N` form) — the renderer just doesn't emit one.  Two fix
  options:
  * Add a post-iface-loop pass: for each `tree.vlans[v]` that
    didn't get rendered via an SVI iface, emit
    `edit "VLAN_<v.id>" / set type vlan / set vlanid <v.id> / set
    interface <some-parent-or-aggregate>`.  Picking the parent is
    the hard part — FortiGate vlan-children always live under
    a parent physical port; the canonical source-vlan record
    doesn't carry that info.
  * Mark `vlans[].id` and `vlans[].ipv4_addresses` as `lossy` in
    the `juniper_junos__fortigate_cli.yaml` for the L2-only case.
    Realistic given the model gap — the YAML at line 477-478 says
    `disposition: good`, which is honest only for L3-bound VLANs.

**Test that would catch the fix.**

* Round-trip test in
  `tests/integration/migration/test_junos_to_fortigate_round_trip.py`
  using a fixture with a mix of L2-only and L3-bound VLANs;
  assert L2-only VLAN ids survive (currently all dropped).
* If the team chooses the YAML-fix path, no test code change —
  Phase-4 reconciliation will pick up the new `lossy` disposition
  next run.

---

## Finding 4 — fortigate_cli: `domain` never emitted (1 / 97)

**Pair affected:** `juniper_junos → fortigate_cli` — `domain` (1).

**What drifted.**  Junos source carries `domain="lab.example.net"`
(`set system domain-name lab.example.net`); FortiGate render emits
no `set domain` line under `config system dns`.  Re-parse sees
`domain=""`.

**Codec responsible.**  Target — fortigate_cli render.

**Likely fix location.**

* `netconfig/migration/codecs/fortigate_cli/render.py:73-80` —
  the `config system dns` block emits `set primary` and
  `set secondary` for `tree.dns_servers[0:2]` but never emits
  `set domain "<tree.domain>"`.  FortiOS supports `set domain
  "<fqdn>"` under `config system dns` natively.  One-line addition:
  ```python
  if tree.domain:
      out.append(f'    set domain "{tree.domain}"')
  ```
  inserted at line 79 (before the closing `end`).

**Test that would catch the fix.**

* Unit test in
  `tests/unit/migration/codecs/fortigate_cli/test_render_system_dns.py`
  asserting `render_intent(intent_with_domain("foo.example"))`
  contains the `set domain "foo.example"` line.

---

## Finding 5 — cisco_iosxe_cli: top-level DNS / domain parser wire-up missing (4 / 97)

**Pair affected:** `juniper_junos → cisco_iosxe_cli` —
`dns_servers` (3 fixtures: `ksator_ex4550`, `ksator_qfx5100`,
`kitchen_sink`) + `domain` (1: `kitchen_sink`).

**What drifted.**  Phase-1 reports "all N dns_servers dropped" and
domain `'lab.example.net' → ''`.  Reproduced for `kitchen_sink`:
the cisco_iosxe_cli RENDER output correctly contains
`ip domain name lab.example.net`, `ip name-server 10.0.0.53`,
`ip name-server 10.0.0.54` — but the cisco_iosxe_cli PARSER never
populates `intent.dns_servers` or `intent.domain` from those lines.

**Codec responsible.**  Target — cisco_iosxe_cli parser.

**Likely fix location.**

* `netconfig/migration/codecs/cisco_iosxe_cli/parse.py` — searching
  the file confirms the only `domain` / `name-server` handlers are
  inside `_parse_dhcp_pools` (lines 707-712, 760-768), which apply
  to the indented sub-commands of an `ip dhcp pool` stanza, NOT
  to the top-level device commands `ip domain name X` and
  `ip name-server X.X.X.X`.  Top-level wire-up needs adding:
  parse `^ip domain name (\S+)` → `intent.domain`; parse
  `^ip name-server (.+)` → split-and-extend `intent.dns_servers`
  (Cisco accepts multiple servers space-separated on one line).

**Test that would catch the fix.**

* Unit test in
  `tests/unit/migration/codecs/cisco_iosxe_cli/test_parse_system_globals.py`
  asserting `parse_intent("ip domain name foo.example\nip name-server
  10.0.0.53 10.0.0.54\n").domain == "foo.example"` and
  `.dns_servers == ["10.0.0.53", "10.0.0.54"]`.

---

## Finding 6 — arista_eos: MAC-VRF reverse-binding gap (6 / 97)

**Pair affected:** `juniper_junos → arista_eos` — all six
`routing_instances[*]` sub-fields on the `kitchen_sink` fixture
(`name`, `route_distinguisher`, `rt_imports`, `rt_exports`,
`description`, `l3_vni`).

**What drifted.**  `routing_instances` count drift 3 → 2.  Junos
source has three routing-instances:

* `TENANT_A` — `instance-type vrf` (L3 VRF, RD + RT, l3_vni=50100)
* `TENANT_B` — `instance-type mac-vrf` (L2 EVPN MAC-VRF, RD + RT)
* `RTR_C` — `instance-type virtual-router` (no RD / RT)

Arista renders only TENANT_A (via `vrf instance` + `router bgp / vrf`)
and RTR_C (via bare `vrf instance`).  TENANT_B silently drops.

**Codec responsible.**  Target — arista_eos render, but the
proximate cause is a cross-vendor naming mismatch.

**Likely fix location.**

* `netconfig/migration/codecs/arista_eos/render.py:266-294` — the
  MAC-VRF emit path looks up `vid_by_name = {v.name: v.id for v in
  tree.vlans}` and `ri.name` → vid.  TENANT_B (the mac-vrf instance
  name) doesn't appear in `tree.vlans[*].name` — Junos's mac-vrf
  doesn't carry the binding the Arista code expects.  When the
  reverse-lookup fails AND the name doesn't begin with `VLAN`, the
  block is silently skipped (line 290-293).

  The Junos parser COULD be enhanced to populate the binding: when
  parsing a `mac-vrf` instance with `vlans <vlan-name>`, stash the
  vlan-name on the routing-instance so the Arista renderer can look
  it up.  Failing that, the Arista renderer should at minimum emit
  a banner comment so the data isn't silently dropped — same
  pattern other codecs use for unmodelled data.  Easiest fix: emit
  a `! MAC-VRF <name> dropped on render — no vlan binding resolved`
  banner.

**Test that would catch the fix.**

* Unit test in
  `tests/unit/migration/codecs/arista_eos/test_render_mac_vrf.py`
  asserting that `render_intent(intent_with_mac_vrf_no_vlan_binding)`
  either emits a banner OR resolves to a synthetic `vlan <id>`
  block.  Currently emits nothing.
* Cross-vendor: extend `kitchen_sink` round-trip integration test
  to assert `routing_instances` count preserves 3 → 3 (currently
  3 → 2).

---

## Finding 7 — Phase-1 dict-snapshot truncation: SNMP false CODEC_BUG (12 / 97)

**Pairs affected:** `juniper_junos → fortigate_cli` (4: community,
location, contact, trap_hosts), `juniper_junos → mikrotik_routeros`
(3: community, location, contact — `trap_hosts` correctly
EXPECTED_LOSSY here), `juniper_junos → opnsense` (4: community,
location, contact, trap_hosts), `juniper_junos → cisco_iosxe_cli`
(0 — but the pattern is general).  These overlap with Finding 4's
`domain` count.

**What drifted.**  Reproduced for `kitchen_sink`:
`juniper_junos → mikrotik_routeros` — after parse(render(intent))
the SNMP dict is preserved verbatim except for `v3_users[*].group`
(the only legitimately drifted field, which is correctly flagged
EXPECTED_LOSSY in the YAML).  But Phase-4 reconciliation flags
community / location / contact / trap_hosts as CODEC_BUG anyway.

The cause is in the Phase-1 mesh snapshot: when the parent `snmp`
record drifts (because v3_users.group changed), the runner stores
`source` and `target` as **truncated key-lists**, e.g.
`["community", "location", "contact", "... and 2 more"]`, instead
of the actual dict values.  Phase-4's `_subfield_drift_in_dict`
(`tools/run_phase4_reconciliation.py:220-244`) then sees `src` is a
list (not a dict), bails with `return None`, and the caller treats
`None` as drifted-and-unknown — flagging every sub-field as
CODEC_BUG.

**Codec responsible.**  Neither.  This is a **methodology issue in
Phase 1's record format** — the snapshot has too little fidelity for
Phase-4 to do per-attribute reconciliation when the parent dict drifts.

**Likely fix location.**

* `tools/run_phase4_reconciliation.py:220-244` — when `src` /
  `tgt` come back as truncated lists, the function returns `None`
  and the caller marks drifted.  More honest behaviour: when the
  source snapshot is a key-list (not a dict), the function should
  return `None` and the caller should mark the disposition as
  `methodology` (under-specification of Phase-1 record), not as
  `drifted`.  That way Phase-4 honestly says "I can't tell whether
  this attribute drifted" rather than promoting unknown drift to
  CODEC_BUG.
* `tools/run_full_mesh.py` (or wherever the Phase-1 dict-snapshot
  truncation lives) — store full source/target dict values when
  the field is a singleton dict like `snmp`, so per-attribute
  reconciliation has the values to compare.  Lists / nested
  dicts can stay truncated since they go through the
  `_subfield_drift_in_list` path which uses `per_record` diffs
  (and is unaffected).

**Test that would catch the fix.**

* Unit test in
  `tests/unit/audit/test_run_phase4_reconciliation_dict.py`
  asserting that a Phase-1 record with `source` / `target` as
  truncated lists yields a `methodology` disposition (not
  `drifted`) for sub-fields.  Then a higher-level test on
  `tools/run_full_mesh.py` asserting that the Phase-1 record for
  a singleton-dict field carries the actual dict values.

---

## Finding 8 — fortigate_cli: domain alongside SNMP false-positives (1 / 97 already in F4 + F7)

The fortigate `domain` CODEC_BUG (1 finding) is Finding 4 above.
The fortigate SNMP CODEC_BUGs (4 findings: community / location /
contact / trap_hosts) are Finding 7 above.  Listed here for matrix
completeness so the reader doesn't double-count.

---

## Skepticism on METHODOLOGY_ISSUE_under findings

Per Phase-4 brief: when source emits zero records for a field
(`source_count=0`), Phase-1 trivial preservation can produce
`METHODOLOGY_ISSUE_under` flags that look like drift.  Spot-checking
the Junos cells:

* The `juniper_junos` source code populates `interfaces`, `vlans`,
  `static_routes`, `lags`, `local_users`, `snmp`, `routing_instances`,
  `vxlan_vnis`, `dns_servers`, `domain`, `ntp_servers`, `timezone`,
  `apply_groups`, `group_content` for the kitchen_sink fixture
  (verified by reproducing the parse).  These methodology issues
  are NOT trivial-empty source.
* For the simpler `buraglio_netlab` fixture (a 184-line Junos
  config), `interfaces` is the only Tier-1+2 surface the source
  actually populates.  Methodology issues like
  `routing_instances`, `vxlan_vnis`, `evpn_type5_routes` ARE trivial-
  empty source and should remain at severity=low (no promotion to
  CODEC_BUG warranted).
* The `methodology_under` records in the run JSON have
  `source_count=None` and `target_count=None` (not numeric), so the
  brief's "demote if source_count=0" rule applies vacuously — the
  Phase-1 run isn't recording the count for these fields.  All
  flagged at severity=low or severity=medium, with the high-severity
  flag reserved for the eight findings above.

No `METHODOLOGY_ISSUE_under` finding warrants promotion to CODEC_BUG.

---

## Cross-cutting observations

1. **Render-emits-but-parse-rejects asymmetry** is the dominant bug
   class, surfacing in three target codecs (aruba_aoss,
   mikrotik_routeros, cisco_iosxe_cli).  Junos's iface naming
   (`ge-0/0/X`, `irb.100`, `xe-0/0/0`) is unusually aggressive and
   surfaces these gaps faster than other source codecs.
2. **Pure-L2 VLAN handling** is incomplete on fortigate_cli render
   (Finding 3) and the YAML expectations don't reflect this — Junos
   defines L2 VLANs without SVI which is normal config but doesn't
   round-trip.
3. **MAC-VRF cross-vendor binding** (Finding 6) is one Junos-specific
   instance of a broader issue: routing-instance names that don't
   match VLAN names need a fallback emit path on every target codec
   that has VLAN-bound MAC-VRF (Arista is the obvious one; Cisco
   IOS-XE on EVPN platforms is the next).
4. **Phase-1 record fidelity** (Finding 7) is not a per-vendor issue
   but it disproportionately affects Junos source because Junos has
   the richest SNMP / local_users / routing_instances data — every
   parent-dict drift cascades into 3-5 false sub-field CODEC_BUGs.
5. **Apply-groups handling** is a known good area (Junos parser at
   `parse.py:124-203` does two-pass apply-groups with reversed
   precedence).  None of the CODEC_BUGs trace to apply-group leakage
   — the kitchen_sink's `set apply-groups GLOBAL-SETTINGS` flows
   through cleanly, the inherited `description "Inherited from
   GLOBAL-SETTINGS apply-group"` survives to the canonical model, and
   any drift on the target is downstream of generic count-drift
   issues (Findings 1-2), not apply-group-specific.

---

## Top 5 actionable fix locations

1. **`netconfig/migration/codecs/aruba_aoss/parse.py:174-176`** —
   widen `_IFACE_HEADER_RE` to accept hyphens, dots, and multiple
   slash segments (or apply port-rename mesh on render).  Single-
   line regex change unblocks **40 of the 97 CODEC_BUGs** (41% of
   the per-source total) and addresses a recurring pattern that
   will surface on any source codec carrying complex iface names.
2. **`netconfig/migration/codecs/mikrotik_routeros/render.py:85-110`**
   — loosen the `ethernet_ifaces` filter so non-`ether*`-named ifaces
   carrying description / mtu / enabled state still emit a
   `/interface ethernet set [ find name=X ]` line.  Unblocks
   **28 of the 97 CODEC_BUGs** (29% of the per-source total).
3. **`tools/run_phase4_reconciliation.py:220-244` +
   `tools/run_full_mesh.py`** — fix Phase-1 dict-snapshot
   truncation so snmp / system / etc. dict-typed fields preserve
   actual values (not just key-lists) when the parent drifts;
   then Phase-4 reconciliation can do per-attribute compare
   instead of conservatively flagging every sub-field as drifted.
   Unblocks **12 of the 97 CODEC_BUGs** (12% — and the same fix
   benefits every source codec, not just Junos).
4. **`netconfig/migration/codecs/cisco_iosxe_cli/parse.py`** — add
   top-level handlers for `ip domain name` and `ip name-server`
   (currently only handled inside DHCP-pool stanzas).  Unblocks
   **4 of the 97 CODEC_BUGs** + the same fix would close the
   parallel finding on every other source codec routing through
   IOS-XE CLI.
5. **`netconfig/migration/codecs/fortigate_cli/render.py:73-80`** —
   add `set domain "{tree.domain}"` line under `config system dns`.
   Unblocks **1 of the 97 CODEC_BUGs** but is a one-line addition
   that aligns the renderer with FortiOS native syntax it already
   supports.

Honourable mentions (smaller wins, listed for Phase-4c queue):

* **`netconfig/migration/codecs/fortigate_cli/render.py:118-147`** —
  emit pure-L2 VLAN child interfaces, OR mark `juniper_junos__
  fortigate_cli.yaml:477-482` `vlans[].id` as `lossy` (model gap).
  Unblocks 6 CODEC_BUGs.
* **`netconfig/migration/codecs/arista_eos/render.py:266-294`** —
  banner-comment unresolved MAC-VRF blocks instead of silently
  dropping.  Unblocks 6 CODEC_BUGs.

YAML hygiene (no code change):

* `tests/fixtures/cross_vendor_expectations/juniper_junos__fortigate_cli.yaml:477-482`
  — flip `vlans[].id` from `good` to `lossy` for the L2-only case
  (or fix the renderer per Finding 3).

## See also

* `tests/fixtures/real/PHASE4_RECONCILIATION.md` — top-level
  summary matrix this report drills into for juniper_junos-as-source.
* `tests/fixtures/real/_phase4_runs/latest.json` — raw per-cell
  CODEC_BUG records this report classifies.
* `tests/fixtures/real/phase4_findings_cisco_iosxe.md` — peer
  per-vendor findings (cisco_iosxe NETCONF source); useful for
  cross-pollination since several findings here overlap (Aruba
  iface header regex, mikrotik render gaps).
* `netconfig/migration/codecs/juniper_junos/parse.py` — the source
  codec; the apply-groups two-pass handling at lines 124-203 is
  load-bearing for the rich-source observations and is **NOT** a
  source of any CODEC_BUG in this run.

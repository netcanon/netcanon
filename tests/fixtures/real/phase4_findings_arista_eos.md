# Phase 4 findings — source codec: arista_eos

Investigation of CODEC_BUG variance findings from
`tests/fixtures/real/_phase4_runs/latest.json` where `source_codec` is
`arista_eos`. Generated 2026-05-02.

Method: filter `cells` to `source_codec == "arista_eos"` and
`target_codec != "arista_eos"`, walk `field_variances`, examine each
entry with `variance == "CODEC_BUG"` (`severity == "high"`,
`actual == "drifted"`, `expected == "good"`). Each finding traced
through `parse(arista_eos source) -> render(target) -> parse(target
rendered)` to localise blame to a parse-side or render-side defect on
either end. Cross-referenced against the per-pair expectation YAMLs
under `tests/fixtures/cross_vendor_expectations/`.

## Summary

- Total CODEC_BUG findings investigated: **47** (across 5 fixtures × 7
  cross-vendor target codecs).
- High-severity bugs (real codec defects, retained after caveat audit):
  **47** — every CODEC_BUG cell here has non-empty source data; none
  collapse to "empty-on-both-sides" methodology false positives.
- Demoted to fixture-coverage-gap: **0**.
- Cross-cutting bugs (same defect across multiple targets): **3**
  - **CC-1** Junos render emits `<iface>.0` in routing-instances
    bindings; reparse stub-creates a duplicate interface.
  - **CC-2** Junos parse blindly prepends `junos:` to encrypted-password
    hashes that already carry a vendor tag (`arista:…`).
  - **CC-3** Junos render uses `class <role>` literally without mapping
    non-Junos role names (`network-admin`, `network-operator`) back to
    super-user/operator/read-only, dropping privilege_level on round-trip.
- Five count-drift findings on Junos collapse onto a single root cause
  (CC-1) but each is reported individually below because the
  reconciliation harness scored them as separate fields.

## Bug findings, grouped by target codec

### arista_eos -> aruba_aoss (Σ 2 codec bugs)

#### Bug AR-1: arista parse does not absorb SVI ipv4 onto the matching CanonicalVlan
- **Field**: `vlans[].ipv4_addresses`
- **Fixture(s)**:
  `tests/fixtures/real/arista_eos/batfish_labval_dc1_leaf2a_eos4230.txt`,
  `tests/fixtures/real/arista_eos/kitchen_sink.txt`
- **Drift detail**: source canonical has `vlan(id=100).ipv4_addresses=[]`
  but a matching `interface Vlan100 / ip address 10.100.0.1/24` lives on
  `interfaces[]`. After aruba_aoss render, the SVI ip is absorbed onto
  the `vlan 100` stanza (per AOS-S convention; `_svi_absorption.py`).
  Reparse correctly reads the address back, so target sees
  `vlans[].ipv4_addresses=[10.100.0.1/24]` while source still has `[]`.
  Pair YAML `arista_eos__aruba_aoss.yaml` `vlans:` block explicitly
  documents `vlan.ipv4_addresses` as the canonical landing site for SVI
  L3, so source is the wrong one — arista parse should run the same SVI
  absorption pass cisco_iosxe_cli already runs.
- **Suspected codec**: arista_eos parse-side bug.
- **Likely fix location**: `netconfig/migration/codecs/arista_eos/parse.py`
  — add a post-parse helper modelled on
  `netconfig/migration/codecs/cisco_iosxe_cli/parse.py::_synthesize_vlans_from_svis`
  (~line 494). For each `interface Vlan<N>` with `ipv4_addresses`, merge
  those addresses into the matching `CanonicalVlan` (creating a stub
  vlan record if none exists). Call from `parse_intent` after
  `_parse_vlans` and `_parse_interfaces`.
- **Suggested fix**: copy the `_synthesize_vlans_from_svis` helper
  verbatim into the arista_eos parse module (it's vendor-neutral once
  the iface-name regex `^Vlan\d+$` matches arista's `Vlan<N>` form too —
  same convention) and dispatch from the parse-walk's post-pass.
- **Test that should pass after fix**: extend
  `tests/unit/migration/codecs/test_arista_eos_parse.py` with a fixture
  asserting that `interface Vlan100 / ip address 10.100.0.1/24` produces
  a `CanonicalVlan(id=100, ipv4_addresses=[CanonicalIPv4Address(ip=...)])`.
  Then re-run mesh reconciliation; the
  `arista_eos -> aruba_aoss vlans[].ipv4_addresses` cell should land
  ALIGNED.
- **Severity**: high.
- **Vendor-doc citation**: `arista_eos__aruba_aoss.yaml` `vlans:` block
  (lines 205–221 — explicitly: "Arista's interface Vlan100 / ip address
  X/N lands on CanonicalVlan.ipv4_addresses").

### arista_eos -> cisco_iosxe_cli (Σ 10 codec bugs)

#### Bug CI-1: cisco_iosxe_cli parse does not extract `ip name-server` (DNS servers)
- **Field**: `dns_servers`
- **Fixture(s)**:
  `tests/fixtures/real/arista_eos/batfish_labval_dc1_leaf2a_eos4230.txt`
  (src=2 → tgt=0), `ksator_dcs_7150s64_eos4224.txt` (src=1 → tgt=0),
  `kitchen_sink.txt` (src=2 → tgt=0).
- **Drift detail**: cisco_iosxe_cli render emits `ip name-server <ip>`
  (`render.py:122-125`). Reparse via `parse.py::parse_intent` never
  scans for the line; `intent.dns_servers` stays empty. Round-trip drops
  every DNS server.
- **Suspected codec**: cisco_iosxe_cli parse-side bug (target-side
  parse, evaluated by the round-trip reconciliation).
- **Likely fix location**:
  `netconfig/migration/codecs/cisco_iosxe_cli/parse.py::parse_intent`
  (~line 220, after `_extract_hostname`). Add a regex pass over `raw`
  for `^ip name-server\s+(\S+)` (case-insensitive, multi-line) and
  append each match to `intent.dns_servers`.
- **Suggested fix**: introduce a small `_parse_globals(raw, intent)`
  helper alongside `_extract_hostname` that walks the raw text for
  `ip name-server`, `ip domain name`, `ntp server`, and
  `logging host` lines. The render already emits these (lines
  85–133); parse just needs symmetry.
- **Test that should pass after fix**: new unit in
  `tests/unit/migration/codecs/test_cisco_iosxe_cli_parse.py` —
  feed `"hostname r1\nip name-server 1.1.1.1\nip name-server 8.8.8.8\n"`
  and assert `intent.dns_servers == ["1.1.1.1", "8.8.8.8"]`.
- **Severity**: high.
- **Vendor-doc citation**:
  `arista_eos__cisco_iosxe_cli.yaml` `dns_servers:` block (disposition
  good — bidirectional preservation is the explicit contract).

#### Bug CI-2: cisco_iosxe_cli parse does not extract `ip domain name`
- **Field**: `domain`
- **Fixture(s)**: `ksator_dcs_7150s64_eos4224.txt`
  (`'lab.local' -> ''`), `kitchen_sink.txt` (`'example.net' -> ''`).
- **Drift detail**: render emits `ip domain name <name>`
  (`render.py:88-90`); parse never reads it back. Same root cause
  family as CI-1.
- **Suspected codec**: cisco_iosxe_cli parse-side bug.
- **Likely fix location**: same `_parse_globals(raw, intent)` helper as
  CI-1 — add `^ip domain name\s+(\S+)` capture and assign to
  `intent.domain`.
- **Suggested fix**: see CI-1.
- **Test that should pass after fix**: extend the same unit to assert
  `domain == "example.com"` from `"ip domain name example.com\n"`.
- **Severity**: high.
- **Vendor-doc citation**: `arista_eos__cisco_iosxe_cli.yaml` `domain:`
  block (good — both vendors carry a flat FQDN scalar).

#### Bug CI-3: cisco_iosxe_cli parse does not handle `vrf definition` (routing instances)
- **Field**: `routing_instances`
- **Fixture(s)**:
  `batfish_labval_dc1_leaf2a_eos4230.txt` (src=5 → tgt=0),
  `karneliuk_a_eos1_eos4260.txt` (src=1 → tgt=0),
  `kitchen_sink.txt` (src=2 → tgt=0).
- **Drift detail**: render emits a full `vrf definition <name> /
  description / rd / route-target / address-family` block
  (`render.py:140-155`); parse has zero awareness of these stanzas
  (no matches for `vrf definition` or `routing_instance` anywhere in
  `parse.py`). Every VRF round-trips to nothing.
- **Suspected codec**: cisco_iosxe_cli parse-side bug.
- **Likely fix location**:
  `netconfig/migration/codecs/cisco_iosxe_cli/parse.py` — add a new
  module-level helper `_parse_routing_instances(raw)` returning
  `list[CanonicalRoutingInstance]`. Anchor on `^vrf definition (\S+)`
  and absorb the indented sub-stanza (`description`, `rd`,
  `route-target import|export`, `address-family ipv4|ipv6`,
  `exit-address-family`) until the next non-indented line. Wire into
  `parse_intent` after `_parse_static_routes`.
- **Suggested fix**: model the helper on the existing `_parse_dhcp_pools`
  / `_parse_radius_servers` pattern (each is a regex-anchored block
  walker; ~50–80 lines). Per-interface `vrf forwarding <name>` is
  already emitted by render but the matching parse-side line in
  `_parse_interfaces` should set `iface.vrf` — likewise needs auditing.
- **Test that should pass after fix**: new unit feeding a five-line
  `vrf definition TENANT_A / rd 65000:1 / route-target both 65000:1`
  block and asserting `intent.routing_instances` length and field
  contents.
- **Severity**: high.
- **Vendor-doc citation**: `arista_eos__cisco_iosxe_cli.yaml`
  `routing_instances:` block (good — both vendors share the
  `vrf definition` IOS-XE-15+ syntax).

#### Bug CI-4: cisco_iosxe_cli vlan list explosion via project_switchport_to_vlan
- **Field**: `vlans` (count drift)
- **Fixture(s)**:
  `batfish_labval_dc1_leaf2a_eos4230.txt` (src=15 → tgt=4093),
  `kitchen_sink.txt` (src=4 → tgt=4 with extra tagged_ports/untagged_ports
  populated).
- **Drift detail**: arista source carries
  `interface EthernetX / switchport trunk allowed vlan 2-4094`. The
  arista parse expands the range to a 4093-element
  `iface.trunk_allowed_vlans` list; the cisco_iosxe_cli parse runs
  `project_switchport_to_vlan` (`canonical/transforms.py:68`), which
  synthesises a `CanonicalVlan` record for every vid in
  `trunk_allowed_vlans`, exploding the vlan list to 4093 entries on the
  re-parsed side. The arista source did NOT run this projection (the
  arista parse module never imports it), so the source-side count stays
  at the explicit `vlan N / name X` declarations.
- **Suspected codec**: shared infrastructure asymmetry — but the
  REPORTED bug is on cisco_iosxe_cli parse since arista is the chosen
  reference. Two candidate fixes:
  1. Suppress synthesis when the trunk_allowed range is "all" / "all
     except" / spans 1-4094 (don't materialise per-vid stub records for
     a default trunk-permit range).
  2. Or run `project_switchport_to_vlan` on arista parse too (would
     equalise both sides but compounds the explosion in BOTH trees;
     only a fix if the explosion is acceptable).
- **Likely fix location**:
  `netconfig/migration/canonical/transforms.py::project_switchport_to_vlan`
  ~line 117 — guard the trunk loop: if
  `len(iface.trunk_allowed_vlans) > N` (e.g. 64) don't synthesise
  records for vids without a pre-existing vlan stanza — only mirror the
  iface name into existing records. Real-world VLAN counts almost never
  exceed mid-double-digits; a 4093-element trunk_allowed list is the
  arista "default permit-all" idiom, not an enumeration of declared
  VLANs.
- **Suggested fix**: in the trunk branch (`elif mode == "trunk":`),
  iterate `iface.trunk_allowed_vlans` BUT skip the synthesis call for
  any vid not already in `by_id` when
  `len(iface.trunk_allowed_vlans) > 64`. Comment with rationale and the
  arista `2-4094` motivating case.
- **Test that should pass after fix**: extend
  `tests/unit/migration/canonical/test_transforms.py` (or whichever
  module owns the projection tests) with a case carrying a trunk on a
  4093-element allowed list and a 16-element allowed list; assert the
  former doesn't explode the vlan list while the latter does mirror.
- **Severity**: high.
- **Vendor-doc citation**: `arista_eos__cisco_iosxe_cli.yaml` `vlans:`
  block — preservation contract assumes finite enumerated VLANs.

### arista_eos -> fortigate_cli (Σ 2 codec bugs)

#### Bug FG-1: fortigate_cli render does not emit `set domain` under `config system dns`
- **Field**: `domain`
- **Fixture(s)**: `ksator_dcs_7150s64_eos4224.txt`
  (`'lab.local' -> ''`), `kitchen_sink.txt` (`'example.net' -> ''`).
- **Drift detail**: fortigate `render.py` only emits
  `set hostname` (line 70); never references `tree.domain`. Reparse
  reads back from `config system dns / set domain "<value>"` —
  `parse.py:706-708` — so the parse side is symmetric and ready, but
  the render never produces the line.
- **Suspected codec**: fortigate_cli render-side bug.
- **Likely fix location**:
  `netconfig/migration/codecs/fortigate_cli/render.py` — under the
  existing `config system dns` stanza (search for `dns_servers` or the
  `config system dns` opener). Add `if tree.domain:` →
  `out.append(f'    set domain "{tree.domain}"')` next to where
  primary/secondary DNS servers are emitted.
- **Suggested fix**: one-line addition; mirror the parse-side
  `pool.domain_name = domain_tokens[0]` semantics.
- **Test that should pass after fix**: extend
  `tests/unit/migration/codecs/test_fortigate_cli_render.py` with a
  CanonicalIntent carrying `domain="example.com"` and assert the
  render output contains `set domain "example.com"`.
- **Severity**: high.
- **Vendor-doc citation**: `arista_eos__fortigate_cli.yaml` `domain:`
  block (lines 143–149).

### arista_eos -> juniper_junos (Σ 27 codec bugs)

The Junos target shows the largest CODEC_BUG count by far. Three
distinct root causes account for 26 of the 27 findings; the LAGs drop
is independent.

#### Bug JU-1 (CC-1): Junos routing-instances binding stub-creates a duplicate interface (count drift)
- **Field**: ALL ten `interfaces[].<subfield>` count drift findings on
  Junos round-trip:
  `description / enabled / mtu / ipv4_addresses / ipv6_addresses /
  access_vlan / trunk_allowed_vlans / lag_member_of / dhcp_client / vrf`
  — every count drift on `kitchen_sink.txt` (13 → 14) and
  `batfish_labval_dc1_leaf2a_eos4230.txt` (39 → 56).
- **Fixture(s)**:
  `batfish_labval_dc1_leaf2a_eos4230.txt`,
  `kitchen_sink.txt`.
- **Drift detail**: source has e.g. `Loopback0` carrying VRF binding
  `iface.vrf="TENANT_A"`. Junos render
  (`render.py:391-405`) emits
  `set routing-instances TENANT_A interface Loopback0.0` (the `.0`
  appended because Junos routing-instances always reference a UNIT, and
  the canonical stores the parent name without a unit suffix). Reparse
  via `parse.py:305-339` then sees `Loopback0.0`, can't find an iface
  by that name in `iface_by_name` (only `Loopback0` exists), and
  *creates a stub* `CanonicalInterface(name="Loopback0.0", vrf=...)`.
  Result: every source interface that's bound into a routing-instance
  spawns a duplicate stub on round-trip.
- **Suspected codec**: juniper_junos render-side bug (asymmetric naming
  across render + parse — the render adds a suffix the canonical never
  carried, and parse can't undo it).
- **Likely fix location**:
  `netconfig/migration/codecs/juniper_junos/render.py:397-405` —
  in the `for iface_name in ifaces_by_vrf.get(ri.name, []):` loop,
  emit the canonical-form name. Either:
  1. Drop the `.0` append and emit `Loopback0` (leaves Junos config
     non-canonical but reparse stays balanced — the reparser already
     accepts bare-parent forms via `_apply_routing_instances`'s pending-
     interfaces table).
  2. Keep the `.0` append on render BUT add a normalisation step in
     `parse.py:319-332` — strip a trailing `.0` from `iface_name` before
     the `iface_by_name.get` lookup, falling back to the parent name
     before the stub-creation branch.
- **Suggested fix**: option (2) is safer (preserves Junos-faithful
  output for operator review). Concretely:
  ```python
  iface = iface_by_name.get(iface_name)
  if iface is None and iface_name.endswith(".0"):
      iface = iface_by_name.get(iface_name[:-2])
  if iface is None:
      # ... existing stub creation path ...
  ```
- **Test that should pass after fix**: extend
  `tests/unit/migration/codecs/test_juniper_junos_parse.py` with a
  fixture combining `set interfaces Loopback0 unit 0 family inet
  address ...` and `set routing-instances X interface Loopback0.0` —
  assert `len(intent.interfaces) == 1` and that interface has
  `vrf == "X"`. Then re-run mesh reconciliation; the eight-or-more
  `interfaces[].<*>` count drift findings collapse into ALIGNED on
  the two affected fixtures.
- **Severity**: high (cross-cutting — single fix unblocks 8 of the 27
  Junos CODEC_BUG findings on its own, plus 10 more on the larger
  fixture, for 18 of 27 total).
- **Vendor-doc citation**: `arista_eos__juniper_junos.yaml` `interfaces`
  cluster (lines 180–203 — preservation expected modulo per-port-name
  rewrites which aren't supposed to change interface count).

#### Bug JU-2 (CC-2): Junos parse double-prefixes vendor-tagged hashes
- **Field**: `local_users[].hashed_password`
- **Fixture(s)**:
  `batfish_duplicateprivate_eos4211.txt`,
  `batfish_labval_dc1_leaf2a_eos4230.txt`,
  `karneliuk_a_eos1_eos4260.txt`,
  `ksator_dcs_7150s64_eos4224.txt`,
  `kitchen_sink.txt`
  (every fixture with at least one user with a non-empty
  `hashed_password`).
- **Drift detail**: arista parse stores hashes prefixed `arista:` (e.g.
  `arista:sha512:$6$…`). Junos render (`render.py:113-115`) only
  strips `junos:` prefixes, not `arista:`, so the rendered
  encrypted-password line is `"arista:sha512:$6$…"`. Junos parse
  (`parse.py:693`) UNCONDITIONALLY prepends `junos:` to whatever it
  reads, producing `junos:arista:sha512:$6$…`. Round-trip diff:
  source `arista:sha512:…` vs target `junos:arista:sha512:…`.
- **Suspected codec**: juniper_junos parse-side bug (the prefixing logic
  doesn't check for an existing vendor tag).
- **Likely fix location**:
  `netconfig/migration/codecs/juniper_junos/parse.py:693` —
  ```python
  hash_token = tokens[5]
  # If the hash already carries a vendor tag (any "<vendor>:..."
  # prefix where vendor is alpha-only), don't double-tag.  This is
  # what happens on cross-vendor round-trips where another codec's
  # render emitted its native hash form unchanged.
  if re.match(r"^[a-zA-Z]+:[^/$]", hash_token):
      existing.hashed_password = hash_token
  else:
      existing.hashed_password = f"junos:{hash_token}"
  ```
- **Suggested fix**: above regex. Keep the unconditional `junos:` tag
  for native Junos hashes (which start with `$1$` / `$5$` / `$6$` —
  no leading vendor token).
- **Test that should pass after fix**: new unit asserting
  `parse("set system login user X authentication encrypted-password
  \"arista:sha512:$6$abc\"")` yields `hashed_password ==
  "arista:sha512:$6$abc"`, NOT `"junos:arista:sha512:$6$abc"`.
- **Severity**: high (5 fixtures × 1 to several users each).
- **Vendor-doc citation**: `arista_eos__juniper_junos.yaml`
  `local_users:` block (lines 247–250 — "Hash bytes round-trip
  losslessly").

#### Bug JU-3 (CC-3): Junos render of arista role names drops privilege_level on round-trip
- **Field**: `local_users[].privilege_level` and `local_users[].role`
- **Fixture(s)**:
  `batfish_duplicateprivate_eos4211.txt`,
  `batfish_labval_dc1_leaf2a_eos4230.txt`,
  `karneliuk_a_eos1_eos4260.txt`,
  `ksator_dcs_7150s64_eos4224.txt`,
  `kitchen_sink.txt`.
- **Drift detail**: arista source has user `admin` with
  `role="network-admin"`, `privilege_level=15`. Junos render
  (`render.py:96-108`) emits `class network-admin` literally (the
  first branch `if user.role:` wins, bypassing the privilege-level
  fallback that maps 15→super-user). Junos reparse hits the class
  string and doesn't recognise `network-admin` as a known Junos class,
  so `existing.privilege_level = 15` never fires (only `super-user` /
  `superuser` triggers that branch — `parse.py:684-686`). Result:
  target user has `role="network-admin"` (preserved) but
  `privilege_level=1` (default from `CanonicalLocalUser` ctor).
  Some fixtures also see role drift: `aaa` with empty role on source
  → role=`super-user` on target (because role was "" so the render
  branched into the privilege-level mapping → super-user).
- **Suspected codec**: juniper_junos render-side bug AND parse-side
  bug, but render is the load-bearing one. Render needs to emit a
  Junos-native class even when the canonical role is a vendor-specific
  string; otherwise round-trip can't recover the privilege level.
- **Likely fix location**: `netconfig/migration/codecs/juniper_junos/render.py:96-108`
  — replace the role-derivation chain with:
  ```python
  # Map vendor-native role strings to Junos's four built-in classes.
  # Always derive from privilege_level when role is empty OR is not
  # one of Junos's known classes — Junos rejects unknown class names
  # at commit-time, AND reparse drops the privilege_level if it can't
  # match one of the four built-ins.
  _JUNOS_KNOWN_CLASSES = {"super-user", "superuser", "operator", "read-only", "unauthorized"}
  if user.role in _JUNOS_KNOWN_CLASSES:
      role = user.role
  elif user.privilege_level >= 15:
      role = "super-user"
  elif user.privilege_level >= 5:
      role = "operator"
  else:
      role = "read-only"
  ```
- **Suggested fix**: above; the parse side could optionally gain a
  table mapping non-Junos role strings back to a privilege_level, but
  the render-side fix alone closes the round-trip diff and produces
  valid Junos output.
- **Test that should pass after fix**: new unit asserting
  `render(CanonicalLocalUser(name="x", role="network-admin",
  privilege_level=15))` emits `class super-user` (NOT `class
  network-admin`).
- **Severity**: high.
- **Vendor-doc citation**: `arista_eos__juniper_junos.yaml`
  `local_users:` block (preservation expected; the note acknowledges
  authentication may fail post-migration but doesn't carve out
  privilege_level loss).

#### Bug JU-4: Junos render drops all LAG records
- **Field**: `lags`
- **Fixture(s)**:
  `batfish_labval_dc1_leaf2a_eos4230.txt` (src=5 → tgt=0),
  `kitchen_sink.txt` (src=2 → tgt=0).
- **Drift detail**: `tree.lags` is never iterated by
  `juniper_junos/render.py`. No `aeN` / `aggregated-ether-options`
  emission. Symmetrically, `juniper_junos/parse.py` has no LAG
  recognition either — the codec is genuinely missing the feature on
  both sides.
- **Suspected codec**: juniper_junos render-side bug (and parse-side
  gap; together a missing-feature on the Junos codec).
- **Likely fix location**: new helper in
  `netconfig/migration/codecs/juniper_junos/render.py` invoked from
  `render_intent`. Per `lag` in `tree.lags`:
  - `set chassis aggregated-devices ethernet device-count <max-aeN+1>`
    (once)
  - For each member iface: `set interfaces <member>
    gigether-options 802.3ad ae<N>` (extracting the `<N>` from the
    canonical lag.name, e.g. `Port-Channel10` → `ae10`).
  - `set interfaces ae<N> aggregated-ether-options lacp <mode>` for
    LACP-active/passive.
  - Mirror parse-side handler in `parse.py::_apply_interfaces` to
    consume `gigether-options 802.3ad aeN` and
    `aggregated-ether-options lacp` lines, building a CanonicalLAG
    record and removing the member iface from a "free" pool.
- **Suggested fix**: this is a Phase-3-aspirational wire-up rather
  than a one-line fix. File a target-codec-feature issue. The
  expectation YAML claims `lags: good` — that's aspirational. In the
  short term, the YAML disposition should be downgraded to `lossy`
  with a "TODO: codec gap, render not wired" reason, OR the codec
  should be properly wired. Either is acceptable.
- **Test that should pass after fix**: round-trip test asserting that
  a CanonicalIntent with `lags=[CanonicalLAG(name="Port-Channel10",
  members=["Ethernet4","Ethernet5"], mode="active")]` survives
  parse(render(...)) with the lag, mode, and members intact.
- **Severity**: high.
- **Vendor-doc citation**: `arista_eos__juniper_junos.yaml` `lags:`
  block (lines 241–243 — explicitly claims `Port-Channel N -> ae N`
  preservation).

### arista_eos -> opnsense (Σ 6 codec bugs)

#### Bug OP-1: opnsense render emits empty zone elements that reparse drops
- **Field**: ALL five `interfaces[].<subfield>` count drift findings on
  opnsense round-trip:
  `description / enabled / mtu / ipv4_addresses / ipv6_addresses` —
  count drift on `ksator_dcs_7150s64_eos4224.txt` (66 → 4).
- **Fixture(s)**: `ksator_dcs_7150s64_eos4224.txt` (66 source ifaces;
  only 4 survive — `ethernet1`, `ethernet2`, `loopback0`,
  `management1`, the four with renderable attrs).
- **Drift detail**: opnsense render emits an XML element per iface
  (`<ethernet1>`, `<ethernet2>`, `<ethernet3/>` …) but for ifaces with
  zero renderable attrs (no description, not enabled — i.e. the bare
  switch ports `Ethernet3..Ethernet48`) the element is self-closing
  with no `<if>` child. opnsense parse
  (`parse.py:355-359`,
  `_parse_interface_zone_canonical`): "If `<if>` is missing AND the
  element has no other children, return None". Result: 62 of 66 ifaces
  evaporate.
- **Suspected codec**: opnsense render-side bug (round-trip
  asymmetry — the render skips the `<if>` element, but parse uses it
  as the sentinel for "not a stub").
- **Likely fix location**:
  `netconfig/migration/codecs/opnsense/render.py:128-144` — always emit
  a single child element so the zone is non-empty. Either:
  1. `ET.SubElement(zone_el, "if").text = iface.name` (mirrors
     OPNsense's native config.xml shape — `<if>igb0</if>` etc. — and
     gives reparse a place to recover the canonical name).
  2. Or relax the parse "drop empty stubs" rule to keep stubs (might
     produce phantom ifaces in legitimate sparse OPNsense exports).
- **Suggested fix**: option (1) is correct semantically; option (2)
  changes parse semantics for native OPNsense configs and risks
  regressions. Add `ET.SubElement(zone_el, "if").text = iface.name` at
  the top of the per-iface emission loop, before the conditional
  `<descr>` / `<enable>` etc. emissions.
- **Test that should pass after fix**: new unit
  asserting that rendering a CanonicalIntent with 64 bare interfaces
  (just names, no other attrs), then re-parsing, yields 64 interfaces
  in the round-tripped intent.
- **Severity**: high.
- **Vendor-doc citation**: `arista_eos__opnsense.yaml` `interfaces`
  cluster (preservation expected).

#### Bug OP-2: opnsense schema only carries one IPv6 address per zone, drops link-local
- **Field**: `interfaces[].ipv6_addresses`
- **Fixture(s)**: `ksator_dcs_7150s64_eos4224.txt` (caught up in OP-1
  because the count-drift bug masks the per-record drift),
  `kitchen_sink.txt` (per-record: source has [global, link-local],
  target has [global only]).
- **Drift detail**: opnsense render
  (`render.py:142-144`) emits only `iface.ipv6_addresses[0]` into
  `<ipaddrv6>` + `<subnetv6>`. When source has both a global address
  and a link-local fe80:: address, only the first survives. On the
  `kitchen_sink.txt` cell this is the only field still drifted after
  OP-1 would be fixed; treat as a separate bug.
- **Suspected codec**: opnsense codec gap — OPNsense's flat
  `<ipaddrv6>`/`<subnetv6>` schema can't natively carry both, but
  link-local on a routed interface is auto-generated on most platforms
  and arguably shouldn't sit in the canonical.
- **Likely fix location**: TWO candidate fixes:
  1. arista parse-side: skip auto-generated fe80::/10 link-local
     addresses on routed (non-SVI) ifaces — they're implicit, not
     operator-set. Source canonical wouldn't carry them and
     round-trip stays clean.
  2. opnsense render: skip link-local addresses when emitting
     `<ipaddrv6>` (prefer the global address). Document as
     EXPECTED_LOSSY in the pair YAML.
- **Suggested fix**: option (2) is the smaller, less-controversial
  change. In `render.py:142`, before assigning
  `iface.ipv6_addresses[0]`, walk the list and pick the first
  non-link-local address (skip any with `scope == "link-local"`); if
  none, fall back to whatever's there.
  ALSO update `arista_eos__opnsense.yaml` `interfaces[].ipv6_addresses:`
  to mark link-local-on-routed-iface as EXPECTED_LOSSY.
- **Test that should pass after fix**: new unit asserting render
  picks the global address when both global and link-local are
  present.
- **Severity**: high (per the YAML), but may be re-classified to
  EXPECTED_LOSSY post-fix.
- **Vendor-doc citation**: `arista_eos__opnsense.yaml`
  `interfaces[].ipv6_addresses:` block.

## Cross-cutting bugs

Three of the bugs above each affect multiple downstream finding rows:

- **CC-1 / JU-1** — single Junos parse fix collapses 18 of 27 Junos
  CODEC_BUG findings (every `interfaces[].<subfield>` count drift).
- **CC-2 / JU-2** — single Junos parse fix collapses 5 `local_users`
  hash diffs (one per fixture).
- **CC-3 / JU-3** — single Junos render fix closes the
  `local_users[].privilege_level` discrepancy across 5 fixtures.

OP-1 / OP-2 act similarly within the opnsense slice (one render-side
fix closes 5 findings).

CI-1 / CI-2 / CI-3 are independent missing-parse-paths in
cisco_iosxe_cli; together they account for 8 of the 10 cisco_iosxe_cli
CODEC_BUG findings on this source.

There is NO bug in this source-vendor batch that's a Phase-3-
aspirational wire-up gap on the SOURCE (arista_eos) side: every
finding traces to a target-codec defect or, in the case of AR-1, a
narrow arista parse-side gap (SVI absorption) that already has a
working twin in cisco_iosxe_cli to copy from.

## Demoted findings (likely Phase-1 trivial-preservation false positives)

None. Every CODEC_BUG cell investigated had non-zero source data; the
bugs are real losses (or asymmetric expansions, in CI-4's case), not
empty-on-both-sides methodology artefacts.

The high `METHODOLOGY_ISSUE_under` bucket noted in the Phase-4a report
is concentrated on EXPECTED_LOSSY fields where preservation is
non-trivially good (e.g. `domain` on cells where the vendor-pair
expectation is `lossy` but the round-trip happens to be lossless).
None of those cells are CODEC_BUG, so they're outside this
investigation's scope.

## Top-3 actionable fix locations (ranked by impact)

1. **`netconfig/migration/codecs/juniper_junos/parse.py:319-332`** —
   fix CC-1 (closes 18 CODEC_BUG findings). One-line change to strip
   trailing `.0` before the iface_by_name lookup.
2. **`netconfig/migration/codecs/cisco_iosxe_cli/parse.py::parse_intent`
   ~line 220** — add `_parse_globals` helper for `ip name-server`,
   `ip domain name`, plus a `_parse_routing_instances` helper for
   `vrf definition` (closes CI-1, CI-2, CI-3 → 8 CODEC_BUG findings).
3. **`netconfig/migration/codecs/opnsense/render.py:128`** — emit
   `<if>{iface.name}</if>` as the first child of every interface zone
   element (closes OP-1 → 5 CODEC_BUG findings on the
   ksator_dcs_7150s64 fixture).

These three together close 31 of the 47 CODEC_BUG findings in this
batch.

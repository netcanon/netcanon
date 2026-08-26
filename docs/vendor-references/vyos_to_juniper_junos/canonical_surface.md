# VyOS → Juniper Junos: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/vyos__juniper_junos.yaml`.

**Source of every number here:** a full mesh pass over the committed corpus,
reconciled with the audit's own `actual_disposition()` and the reconciler's
`STRUCTURAL_ONLY` collapse replayed, so this file and the ratchet agree by
construction. Every loss recorded was additionally re-derived by hand —
`vyos.parse()` → `juniper_junos.render()` → `juniper_junos.parse()` on each of
the 13 fixtures — so no claim below rests on the drift shape alone.

- Fixture cells: **13** (12 real captures + 1 synthetic kitchen-sink)
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the measured mesh run, and hand round-trips of the committed
> fixtures. Where a disposition rests on a declaration rather than an observed
> round-trip, the YAML says so explicitly.

This is the closing pair of the mesh audit — `vyos` was the last blind codec,
and `vyos → juniper_junos` its last unwritten expectation. Nothing here is
deferred to a later pass.

## Device-class framing

`vyos` in this corpus is a **Linux-based software edge router**: Debian netdev
names (`eth0`…`eth5`, `lo`, `dum0`, `bond0`, `eth1.100`), dual-stack
addressing, a handful of static routes, one VRF, one LAG and a small VXLAN
netdev surface. `juniper_junos` is a **Junos router/switch** — `set`-form
configuration, `unit` sub-interfaces, `ae<N>` aggregates, `irb` SVIs and a VLAN
database that owns the VXLAN bindings.

The realistic migration is a VyOS edge box replaced by a Junos device carrying
the same routed edge: interface addressing, admin state, descriptions, static
routes, VRF identity, SNMP and local users.

One detection note worth writing down because it looks alarming and is not:
the VyOS `set`-form and the Junos `set`-form share grammar, and
`set protocols bgp|ospf` is common to both. That is **not** a detection veto.
The `vyos` codec parses a curly-brace `config.boot`; a `set`-form input is
converted by `_setform_to_brace` before parsing.

## The structural finding — an empty-record prune, and only that

The interface inventory shrinks. It is the dominant structural signal on the
pair, and it is narrower than it looks.

| measurement | value |
|---|---|
| source interface records, all 13 cells | **55** |
| records after parse → render → re-parse | **46** |
| cells where the interface name set differs | **5** |
| surviving records that were **renamed** | **0** |

The 9 vanished records are `eth1` + `lo` (`metasploit-vyos-config.conf`),
`eth2` + `eth3` + `eth4` + `lo` (`scottlaird-vyos-parser.conf`), and `lo` on
`vyos_forum_snmpv3_user_eq13.conf`, `wcni-kind-gw0.conf` and
`wcni-kind-gw1.conf`.

The mechanism is an **empty-record prune**, and it was tested falsifiably
rather than inferred:

| class | count |
|---|---|
| vanished **and** carrying no renderable attribute | **9** |
| vanished **and** carrying at least one attribute | **0** |
| survived **and** carrying at least one attribute | **45** |
| survived **and** carrying no attribute but an explicit `disable` | **1** |

The Junos render emits a `set interfaces <name> …` line only when there is
something to write. A record with no address, no description, no MTU, no VRF,
no LAG membership, no DHCP client and no admin-state override produces no text
at all, and the re-parse never sees it. Grepping the render for a vanished
record's name returns **0 lines** (checked on
`scottlaird-vyos-parser.conf:eth2` and `wcni-kind-gw0.conf:lo`).

Two controls settle the tempting wrong readings:

- **"loopbacks are dropped"** — `lo` vanishes on 5 cells and **survives** on
  `kitchen_sink.conf`, the one cell where `lo` carries an IPv4 and an IPv6
  address. The prune is attribute-driven, not name-driven.
- **"only addressed ports survive"** — `kitchen_sink.conf:eth3` has no address,
  no description and no MTU. Its only attribute is `enabled=False`, the render
  emits `set interfaces eth3 disable`, and the record survives. One renderable
  attribute is enough.

The consequence for the expectation file: because 5 cells change interface
record count, every `interfaces[].*` sub-field reports drift on those cells for
that **one** reason. That signal is claimed exactly once, by
`interfaces[].name`. The other interface sub-fields are scored on **surviving
records only**, and all of them except `interface_type` drift zero times.

## Per-field measurement (13 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 13 | 0 | 0 |
| domain | 1 | 0 | 12 |
| dns_servers | 1 | 0 | 12 |
| ntp_servers | 11 | 1 | 1 |
| interfaces | 6 | 7 | 0 |
| static_routes | 3 | 1 | 9 |
| snmp | 2 | 2 | 9 |
| lags | 0 | 1 | 12 |
| local_users | 0 | 13 | 0 |
| vxlan_vnis | 0 | 3 | 10 |
| routing_instances | 1 | 0 | 12 |

Fields trivially empty on all 13 cells: `timezone`, `syslog_servers`, every
`vlans[].*` key, `dhcp_servers`, `radius_servers`, `evpn_type5_routes`,
`raw_sections`, `apply_groups`, `group_content`, `anycast_gateway_mac`.

### Per-record detail behind the interface drift (46 surviving records)

| sub-field | populated on source | records drifted | shape |
|---|---|---|---|
| `ipv4_addresses` | 21 | **0** | — |
| `ipv6_addresses` | 20 | **0** | — |
| `description` | 15 | **0** | — |
| `enabled` (explicit `disable`) | 2 | **0** | — |
| `mtu` | 1 | **0** | — |
| `vrrp_groups` | 0 | **0** | — |
| `lag_member_of` | 2 | 2 | `bond0` → `ae0` |
| `interface_type` | 0 | 1 | empty → `ianaift:softwareLoopback` |

`interface_type` is the only interface sub-field with a per-record loss that
stands on its own, and its direction is the opposite of the usual reading.
Across all 46 surviving records the census is: source-empty → target-empty on
**45**, source-empty → target-populated on **1**, source-populated →
target-empty on **0**. The `vyos` parser does not derive an IANA type from a
Linux netdev name, so it emits `""` everywhere; the Junos re-parse recognises
`lo` as a loopback and manufactures `ianaift:softwareLoopback`. Nothing the
source carried was dropped — a value the source never had was invented.

### Adjacent sub-fields that drift but no scored key covers

Recorded so the next reader does not re-hunt them as unexplained:

- `interfaces[].dot1q_vlan` — `100` → `null` on `eth1.100` and `200` → `null`
  on `eth1.200` (`kitchen_sink.conf`). The Junos render writes the VyOS netdev
  name `eth1.100` verbatim rather than `set interfaces eth1 unit 100 vlan-id
  100`, so the tag has no `unit` to ride on. Standing observation, not a
  pair-specific fact: the `vyos` matrix declares
  `/interfaces/interface/dot1q-vlan` **unsupported** while the parser
  demonstrably populates it. That is a source-side matrix under-declaration and
  belongs to a codec change, not to this file.
- `interfaces[].dhcp_client_v6` — `dhcpv6` → `""` on one record
  (`houdev_vyos_dhcpv6_pd_client.conf:eth0`), despite `juniper_junos` declaring
  `/interfaces/interface/dhcp-client-v6` supported.
- `local_users[].privilege_level` — `15` → `1` on all 17 user records.
  `vyos` already declares `/local-users/user/privilege-level` lossy on its own
  side. The scored identity keys (`name`, `role`) are unaffected.

## Source-side gaps vs target-side drops

`vyos` declares these **unsupported at the exact path**, so as a *source* it
never emits them and there is nothing for Junos to lose:

`/system/syslog-server` · `/dhcp-servers/pool` · `/vlans/vlan/id` ·
`/vlans/vlan/ipv4/address/{secondary-ip,virtual-gateway-address,virtual-gateway-mac}` ·
`/interfaces/interface/{switchport-mode,access-vlan,trunk-allowed-vlans,trunk-native-vlan,voice-vlan}` ·
`/interfaces/interface/vrrp-groups/group/*` · `/routing/static-route/vrf` ·
`/routing-instances/instance/l3-vni` · `/vxlan-vnis/l2vni-route-target`

These are recorded `not_applicable`, not `unsupported`. The distinction is
operational: for most of them **juniper_junos declares the field SUPPORTED** —
syslog hosts, DHCP pools, VLAN id and name, per-VRF static routes, and the
whole `/interfaces/interface/vrrp-groups/group` subtree. Re-authoring them on
the target will stick, and the migration report should say so rather than
implying the target cannot hold them.

Three fields are different: **both** matrices declare them unsupported, a
symmetric gap in the pair. Those are recorded `unsupported`:

`/system/timezone` · `/radius-servers/server/host` ·
`/radius-servers/server/key` · `/anycast-gateway-mac`

The six `vlans[].*` `not_applicable` entries are grounded in measurement, not
just declaration: **zero** of the 13 cells produce a canonical VLAN record. A
VyOS box expresses tagging as an `ethN.<vid>` netdev, which lands in
`interfaces[]`. That fact has a consequence one section below.

`snmp.trap_hosts` is a gap on both sides for a different reason: **neither**
codec declares a `/snmp/trap-host` path at all, and the list is empty on both
sides of all 4 cells that carry an SNMP block. The zero drift there is the
trivial kind and the YAML says so rather than implying coverage.

## Findings worth carrying forward

### 1. The VXLAN VNI is the one concept-level loss — and the matrix looks wrong until you probe it

3 of 13 cells carry a VXLAN netdev, one VNI each (VNIs 10, 10 and 10100). On
all three the record count goes **1 → 0**. Total, every time.

The vanish classifier calls this `TOTAL -> unsupported`. The
`juniper_junos` matrix declares `/vxlan-vnis/vni` **supported**. They
disagree, so it was probed rather than argued.

The Junos render emits only the switch-level globals — `set switch-options
vxlan-port 8472` on the two `wcni-kind-gw*` cells, `set switch-options
vtep-source-interface 10.255.0.1` on `kitchen_sink.conf` — and **no**
`set vlans <V> vxlan vni <N>` line on any of them. The reason is in the
renderer: the VNI emission lives inside `for vlan in tree.vlans:` in
`netcanon/migration/codecs/juniper_junos/render.py`, gated on a VLAN record to
hang the binding on. `vyos` produces zero VLAN records on every cell, so the
loop never runs, and the switch-options globals alone do not reconstitute a VNI
on re-parse.

Both matrices are telling the truth. Junos genuinely models VNIs — as a
**property of a VLAN**. VyOS genuinely models VNIs — as a **netdev**. The loss
is in the pairing, not in either codec. It is recorded `unsupported` and not
`lossy` because the record vanishes rather than degrades (#436), and because
`lossy` warns while staying compatible, which would understate losing the
entire overlay on every cell that has one.

`vxlan_vnis[].vlan_id` and `vxlan_vnis[].mcast_group` are recorded `good`.
They measure what happens to a value on a surviving record, and the
disappearance is claimed once, under `vxlan_vnis[].vni`. Recording it three
times would triple-count one loss.

### 2. Credentials survive, behind a codec prefix

17 local-user records across 13 cells. **All 17 survive** — zero accounts
vanish, zero names drift, zero roles drift (every account is `admin`). That is
unusual for this mesh, where identity is normally the first thing to shed
records.

`hashed_password` drifts on **16 of 17** records, across 12 of 13 cells. The
seventeenth is the one account in the corpus with no password at all.

The shape is uniform and was verified exhaustively rather than sampled: on
**16 of 16** drifting records the target value is exactly `junos:` prepended to
the source value. Length grows by exactly the 6 characters of that prefix,
every time. Every source secret is a SHA-512 crypt string (scheme marker
`$6$`); the body is carried through the render into
`set system login user <name> authentication encrypted-password …` unchanged
and re-encoded on parse with the codec prefix.

So the credential is carried. This is recorded `lossy` because the canonical
value after the round-trip is not the canonical value before it, and a
consumer comparing the two strings will see a difference — but it is the
recoverable kind, not the destroyed kind. Contrast the IOS-XR → EOS pair, where
a type-10 secret degrades into a cleartext marker and the hash body is gone
outright.

### 3. The LAG is renamed, not lost — and the rename has a deployability tail

One cell (`kitchen_sink.conf`) carries a LAG, and it **survives**: 1 → 1, with
its members (`eth4`, `eth5`) and its mode (`active`) intact. The only change is
the name, `bond0` → `ae0`, which is the Junos-native aggregate spelling. The
render emits `set interfaces eth4 ether-options 802.3ad ae0`,
`set interfaces eth5 ether-options 802.3ad ae0`,
`set chassis aggregated-devices ethernet device-count 1` and
`set interfaces ae0 aggregated-ether-options lacp active`. The ports come up
bundled, not standalone.

That makes it `lossy`, not `unsupported`. Nothing vanished, so the #436 rule
that forces `unsupported` does not apply, and blocking a migration over a LAG
that arrives correctly bundled under its target-native name would be wrong.
This is the known cross-vendor LAG naming artifact the audit dossier warns
about, confirmed by round-trip rather than assumed.

`lags` and `interfaces[].lag_member_of` are **one mechanism, not two
findings**. The signal is claimed under `lags`, where the record is measured.
The interface-side pointer is `good` because it still points at the right
aggregate. Neither is cited as evidence for the other.

There is a tail, and it is a *deployability* observation rather than a fidelity
loss — recorded here, deliberately not scored in the YAML. The
`CanonicalInterface` named `bond0` round-trips perfectly, description and
`10.50.0.1/24` intact, and the render writes those onto
`set interfaces bond0 …`. Meanwhile the members join `ae0`. On a real Junos
box `bond0` is not a valid interface name, so the aggregate's L3 would land
nowhere and `ae0` would come up unaddressed. The canonical round-trip is clean;
the emitted config needs the addressing moved onto `ae0` by hand.

Standing observation, not a pair-specific fact: the `juniper_junos` matrix
declares **nothing** for `/lags/lag/name`, `/lags/lag/members` or
`/interfaces/interface/lag-member-of` — only `/lags/lag/mode` — while
demonstrably rendering, renaming and re-parsing all three. That is a matrix
under-declaration and belongs to a codec change rather than to this file.

### 4. The NTP drift removes a defect rather than causing one

`ntp_servers` is populated on 12 of 13 cells and drifts on exactly one,
`houdev_vyos_dhcpv6_pd_client.conf`. Reading the direction backwards would be
worse than missing it entirely.

That fixture uses the VyOS 1.4-era `server <host> { }` form — an empty options
block on the same line. The **vyos parser** captures the brace residue into the
hostname, producing canonical values of the shape `time1.vyos.net { }`. The
render passes the residue straight through
(`set system ntp server time1.vyos.net { }`), and the Junos re-parse takes the
first whitespace-delimited token, returning the clean `time1.vyos.net`. Three
servers in, three out, all three correct on the target.

So the canonical value differs — which is why it is recorded as a loss — but
the round-trip **strips** a defect the source introduced. The other 11
populated cells use the bare `server <host>` form and round-trip untouched. The
underlying vyos brace-residue bug belongs to a codec change; it is written down
here so the next reader does not re-hunt it as a Junos rendering problem.

### 5. The static-route metric is the only routing loss

4 of 13 cells populate static routes; 7 routes total, and every record
survives with its destination and next-hop. IPv4 and IPv6 both round-trip. The
one loss is on `kitchen_sink.conf`, where `10.99.0.0/16` goes metric **20 → 0**.

`juniper_junos` already declares `/routing/static-route/metric` lossy and
states the cause: "Render emits destination + next-hop only; the static-route
administrative distance (metric) is dropped." The render confirms it —
`set routing-options static route 10.99.0.0/16 next-hop 10.10.10.254`, with no
`metric` or `preference` clause.

Two adjacent caveats are declared rather than observed, and the YAML says so:
`juniper_junos` declares `/routing/static-route/interface` **unsupported** (a
gateway-less, interface-only route is dropped) and both codecs declare
`/routing/static-route/description` lossy. No committed cell on this pair sets
either, so neither is measured here.

### 6. SNMP: scalars clean, USM material degrades

4 of 13 cells produce an SNMP block. Community (3 cells), location (2 cells)
and contact (2 cells) round-trip with **zero** drift — including a
space-bearing location, `rack 4 / row B`, so the `set snmp location` render
does not truncate at whitespace.

The only SNMP loss is inside the v3 user record, on both cells that carry one.
The record survives; two of its sub-values change:

- **`engine_id` → empty.** This is the real loss. Both source engine IDs (a
  22-hex-digit RFC 3411 form on one cell, a short `0x`-prefixed synthetic on
  the other; neither value is reproduced here) return empty. The render writes
  `set snmp v3 usm local-engine user …` — `local-engine` is exactly the
  declaration that there is no per-user engine ID to emit.
  `juniper_junos` declares `/snmp/v3-user/engine-id` lossy and says why; `vyos`
  declares the same path lossy from its side.
- **`priv_protocol` `aes` → `aes128`.** A normalisation, not a downgrade — the
  render emits `privacy-aes128`, the Junos-native spelling of the same cipher.

Everything else on the record is unchanged, verified field by field: `name`,
`group`, `auth_protocol`, and **both** passphrases (present, length unchanged;
no passphrase value appears in this file or in the YAML).

## Credential material

No hash body, passphrase, community string or engine ID value is reproduced in
this file or in the expectation YAML — only crypt-scheme markers (`$6$`),
prefix strings that contain no key material (`junos:`), record counts and
lengths. Per `AGENTS.md`, password hashes are operator-traceable even when they
are hashes, and a document that quotes the value it describes defeats its own
redaction.

## Two drift-shape readings that are wrong

**"The LAG surface is a total drop."** A mechanical "did the record set
change?" pass flags `lags` as drifting on the one cell that has one, which on
other pairs in this mesh means the bundle vanished. Here the count is 1 → 1
with members and mode intact; only the name moved to the Junos namespace. The
audit dossier flags this trap explicitly, and probing it is what separates a
rename from a drop.

**"The migration lost the interface types."** `interfaces[].interface_type` is
recorded `lossy`, and the row is easy to misread. The source carried **zero**
interface types across all 55 records. The single drifting record gained one it
never had. Read the row as "the canonical type hint is not stable across this
pair", not as "type information was destroyed".

## Deployability caveats that are NOT scored as fidelity losses

Two, both real, both deliberately kept out of the per-field dispositions
because the canonical round-trip is clean and the fidelity harness scores
*preservation*, not target-syntax *validity*:

1. **Port names pass through verbatim.** The mesh round-trip renders with no
   port-rename map, so VyOS `eth0` / `eth1.100` / `dum0` names are written
   straight into the Junos `set interfaces` lines. That is exactly why
   `interfaces[].name` scores 0 renames among the 46 survivors — and it is also
   why the emitted config is not deployable as-is on a Junos box, which expects
   `ge-0/0/0`, `xe-0/0/0`, `lo0`, `ae0`, `irb.<N>` and friends
   (`netcanon/migration/codecs/juniper_junos/port_names.py`). A real cutover
   runs the port-rename path.
2. **The `bond0` / `ae0` split**, described in finding 3 above.

## Apply-groups: the one surface where the target is richer than the source

`apply_groups` and `group_content` are the Junos-native inheritance surface,
and `juniper_junos` is the only codec in the mesh that models them — it
declares `/groups` lossy and parses `set groups <g>` across the full dispatch
surface via GAP 8's two-pass parse. `vyos` has no equivalent concept, declares
nothing, and emits nothing on any of the 13 cells.

So both keys are `not_applicable`: a source-side gap, on the one pair in the
mesh where the target could actually have held the data. Nothing is lost
because nothing arrives.

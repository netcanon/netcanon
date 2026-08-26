# Arista EOS → VyOS: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/arista_eos__vyos.yaml`.

**Source of every number here:** the committed corpus round-tripped by hand —
`arista_eos.parse()` → `vyos.render()` → `vyos.parse()` on each of the 6
fixtures — with per-key dispositions resolved through the audit's own
`actual_disposition()` rather than inferred from the drift shape, so this file
and the ratchet agree by construction. Every loss recorded below was measured
on its own; none is carried over from a sibling field.

- Fixture cells: **6** (5 real captures + 1 synthetic kitchen sink)
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, and hand round-trips of the committed fixtures. Where a
> disposition rests on a declaration rather than an observed round-trip, the
> YAML says so explicitly.

## Device-class framing

`arista_eos` in this corpus is a **DC leaf / campus L3 switch**: EVPN/VXLAN
leaves with VARP anycast gateways (`batfish_eos_evpn_vlan_based_leaf`,
`batfish_labval_dc1_leaf2a_eos4230`), `Port-Channel` bundles, a populated
top-level VLAN database with trunk membership, and one plain access switch
(`ksator_dcs_7150s64_eos4224`, 66 ports). `vyos` is a **Linux software
router** — a VM or appliance doing routed edge work.

The shared surface is therefore the **routed plane**: the interface inventory
with its addressing, MTU, descriptions and admin state; static routes; VRF
identity; local accounts; SNMP. What does not cross is the **L2 fabric**: the
VLAN database, VARP anycast gateways, LAG bonding, and the VXLAN VLAN binding.

## The structural finding — the split runs between interfaces and VLANs

Anyone arriving here from `cisco_iosxr_to_arista_eos/canonical_surface.md`
will recognise the interface half of this shape and should note that the VLAN
half is different.

**The interface inventory is fully preserved. The VLAN database is not.**

| measurement | value |
|---|---|
| source interface records, all 6 cells | **169** |
| interface records after parse → render → re-parse | **169** |
| cells where the interface **name set** differs | **0** |
| source VLAN records, all 6 cells | **29** |
| VLAN records after the round-trip | **0** |

Every EOS interface name survives verbatim — `Ethernet1`, `Loopback0`,
`Management1`, `Vlan110`, `Port-Channel3` all come back under the same name.
Only the *ordering* of the list changes, which is why an index-zipped
comparison misleadingly reports ~147 "renames"; keyed by name the sets are
identical on all 6 cells.

The consequence is the useful one: **every interface loss on this pair is a
genuine per-attribute loss** that stands on its own measurement, and every
interface sub-field that survives is recorded `good` rather than dragged down
by a vanishing parent. Nothing in the interface block is correlated drift.

The VLAN block is the opposite, and the five `vlans[].*` `good` entries in the
YAML depend on understanding why: all 29 VLAN records disappear together, for
one reason, so that disappearance is claimed exactly **once** — under
`vlans[].id` — and the sibling keys are `good` so a single structural loss is
not counted five times.

## Per-field measurement (6 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 6 | 0 | 0 |
| domain | 2 | 0 | 4 |
| dns_servers | 4 | 0 | 2 |
| ntp_servers | 4 | 0 | 2 |
| timezone | 0 | 0 | 6 |
| syslog_servers | 0 | 1 | 5 |
| interfaces | 0 | 6 | 0 |
| vlans | 0 | 4 | 2 |
| static_routes | 3 | 2 | 1 |
| dhcp_servers | 0 | 1 | 5 |
| snmp | 1 | 1 | 4 |
| lags | 0 | 3 | 3 |
| local_users | 0 | 6 | 0 |
| radius_servers | 0 | 0 | 6 |
| vxlan_vnis | 1 | 3 | 2 |
| evpn_type5_routes | 0 | 0 | 6 |
| routing_instances | 0 | 4 | 2 |
| raw_sections | 0 | 0 | 6 |
| apply_groups | 0 | 0 | 6 |
| group_content | 0 | 0 | 6 |
| anycast_gateway_mac | 0 | 2 | 4 |

### Per-record detail behind the interface drift

| sub-field | records affected | of total | shape |
|---|---|---|---|
| `interface_type` | 169 | 169 | value → empty string |
| `lag_member_of` | 15 | 15 populated | value → null |
| `ipv4_addresses` | 14 | 57 populated | anycast virtual-gateway address → empty |
| `description` | 0 | 73 populated | — |
| `mtu` | 0 | 1 populated | — |
| `ipv6_addresses` | 0 | 5 populated | — |
| `enabled` | 0 | 169 | — |

`interface_type` drops **uniformly** — 118 `ianaift:ethernetCsmacd`, 24
`ianaift:l3ipvlan`, 17 `ianaift:softwareLoopback` and 10
`ianaift:ieee8023adLag`, with **zero survivors of any type**. The mechanism is
specific: the vyos codec declares no IANA ifType and re-derives it from the
interface-*name* shape (`ethN` → ethernetCsmacd, `lo`/`dumN` →
softwareLoopback, `bondN` → ieee8023adLag). Because the render preserves EOS
names verbatim, none of `Ethernet1` / `Loopback0` / `Port-Channel3` matches
those shapes and nothing is re-derived. Note this is the **inverse** of the
IOS-XR → EOS pair, where all 18 loopbacks survived because EOS *does* re-derive
from `interface Loopback<N>`. Both matrices already declare
`/interfaces/interface/config/type` lossy.

### Per-record detail behind the VLAN drift

All 29 source VLAN records are richly populated — this is a real L2 database,
not a bare dot1q registry:

| sub-field | records populated | of 29 |
|---|---|---|
| `name` | 28 | 29 |
| `tagged_ports` | 27 | 29 |
| `ipv4_addresses` | 24 | 29 |
| `untagged_ports` | 3 | 29 |
| `description` | 0 | 29 |

All 29 vanish. `vyos` declares `/vlans/vlan/id` **unsupported** and states why:
VyOS has no top-level VLAN database — 802.1Q VLANs are modelled as `vif <vid>`
sub-interfaces. Worth being precise about what *does* survive: the EOS SVI
named `Vlan110` comes back as an interface record called `Vlan110` with its
prefix intact. The **interface** survives; the **VLAN database record**, its
name and its port membership do not.

## Source-side gaps vs target-side drops

`arista_eos` as a *source* never emits these, so there is nothing for VyOS to
lose. They are recorded `not_applicable`:

- `/radius-servers/*` — no path declared at any level; 0 records on all 6 cells.
- `/vxlan-vnis/mcast-group` — declared **lossy on the source side**; 0 of 19
  VNI records carry one. `vyos` declares it *supported*, so re-authoring the
  multicast underlay on the target will stick.
- `/evpn-type5-routes/route` — declared lossy source-side; 0 records.
- `/routing-instances/instance/description` — declared lossy source-side; 0 of
  18 VRF records carry one.
- `raw_sections`, `apply_groups`, `group_content` — 0 records; the latter two
  are Junos-specific canonical surface.

Target-side drops, where `vyos` declares the path **unsupported** and the
migration must be told to block:

`/system/syslog-server` · `/dhcp-servers/pool` · `/vlans/vlan/id` ·
`/anycast-gateway-mac` · `/routing/static-route/vrf` ·
`/interfaces/interface/vrrp-groups/group/*` ·
`/interfaces/interface/ipv4/address/virtual-gateway-address`

`timezone` is the one symmetric gap: **both** matrices declare
`/system/timezone` unsupported. No cell populates it, so it is declared rather
than observed.

## Findings worth carrying forward

### 1. The LAG surface is a total concept drop — and the target over-declares

10 LAG records across the 3 bundle-carrying cells become **0** after the
round-trip, and all 15 interface records with a `lag_member_of` value
(`Port-Channel3`, `5`, `6`, `7`, `10`, `11`, `20`) come back null while the
member ports themselves survive — the dangerous shape, because the ports come
up standalone rather than bundled.

Inspecting the render shows exactly what happens. A source LAG
`Port-Channel10` with members `Ethernet4`, `Ethernet5` and mode `active` is
emitted as:

```
ethernet Port-Channel10 {
    description "Bonded uplink to core"
```

There is **no `interfaces bonding bondN` node and no `bond-group` line
anywhere**. The bundle is rendered as an ordinary *physical* `ethernet`
interface under a name that will not exist on a VyOS box, and the vyos parser —
which builds `CanonicalLAG` only from `interfaces bonding` — finds nothing to
re-parse.

Two matrix observations, in opposite directions, both left to a codec change
rather than fixed here:

- `arista_eos` declares **nothing** for `/lags/lag` as a source — neither
  supported, lossy nor unsupported. This is the same standing under-declaration
  already recorded on the IOS-XR → EOS pair.
- `vyos` declares `/lags/lag/name` and `/lags/lag/members` **supported** and
  `/lags/lag/mode` lossy — and then delivers zero LAG records. That is a
  *target* over-declaration: the matrix promises a surface the render does not
  emit.

Both `lags` and `interfaces[].lag_member_of` are recorded `unsupported`, since
a vanished record is not lossy (#436). **They are one mechanism, not two
independent findings.** Neither is cited as evidence for the other; each is
recorded where it is measured.

### 2. Every local account is promoted to `admin` — a fail-open

All 12 accounts across all 6 cells survive with their names and their
credentials. What does not survive is the **role**, and it fails in the unsafe
direction:

| source role | records | target role |
|---|---|---|
| `network-admin` | 6 | `admin` |
| *(empty)* | 5 | `admin` |
| `network-operator` | 1 | `admin` |

Every role collapses to `admin`. The `network-operator` account — a read-only
operator on the EOS side — arrives on VyOS as a full administrator. The
companion `privilege_level` field moves the same way on the same records
(1 → 15 on 4 of them); that is the **same mechanism**, not independent
corroboration of it.

`vyos` declares `/local-users/user/role` **supported** while flattening every
role, and declares `/local-users/user/privilege-level` lossy with the honest
reason ("the codec maps every login user to privilege…"). The role declaration
is the under-declared half.

Recorded `lossy`, not `unsupported`: the account record survives and the target
models roles — the value degrades rather than vanishing. Review every migrated
account's role before cutover; a migration that silently promotes a read-only
operator is worse than one that drops the account, because nothing looks wrong.

### 3. Credentials survive this pair intact — unusually

`local_users[].hashed_password` is `good`, which is rare in this mesh. Of the
12 accounts, 9 carry a credential and **all 9 round-trip byte-identical**; the
other 3 carry no credential in the source at all. No re-encoding, no scheme
downgrade, no cleartext marker.

This is worth stating positively *and* carefully: it means the migrated
accounts arrive with working passwords **and** with `admin` rights they may not
have had. Finding 2 is what makes finding 3 dangerous.

### 4. The VARP triad: anycast gateways do not cross

Three separate keys measure one absent VyOS grammar — distributed anycast
gateway (VARP). They are recorded separately because each is measured on a
different field, and none is offered as evidence for another:

- `anycast_gateway_mac` — set on 2 of 6 cells, empty on both after the
  round-trip. `arista_eos` declares it supported; `vyos` declares
  `/anycast-gateway-mac` unsupported. → `unsupported`.
- `interfaces[].ipv4_addresses` — 15 address entries across 14 interface
  records lose `virtual_gateway_address`. → `lossy` (see below).
- `vlans[].ipv4_addresses` — moot here, since the VLAN records vanish first.

The `interfaces[].ipv4_addresses` case deserves precision, because the headline
number understates and the disposition could easily be over-claimed. Measured
across the 57 interface records that carry IPv4:

- **0 real `ip address` values are lost.** Every conventional address and
  prefix length survives.
- 15 address entries lose the VARP anycast `virtual_gateway_address`.
- 1 entry loses its `is_secondary` flag (true → false).

The severity lands on the SVIs whose *only* address was the virtual gateway —
an EOS `ip address virtual 10.1.10.1/24` parses with an empty `ip` and the
address in `virtual_gateway_address`, so after the round-trip that entry comes
back carrying a prefix length and **no address at all**. The distributed
gateway is gone and the SVI is unusable until re-addressed.

It is still `lossy`, not `unsupported`: the address list keeps its entry count
and its prefix lengths, the primary addressing surface is 100% clean, and
declaring the whole IPv4 surface `unsupported` would block every EOS → VyOS
migration over an attribute that affects 14 of 57 records.

### 5. The VXLAN VLAN binding comes back *wrong*, not empty

All 19 VNI records across 4 cells survive with their VNI numbers intact — that
part is clean. But `vlan_id` is replaced on 18 of the 19:

| source VLAN | target VLAN |
|---|---|
| 10 | 1822 |
| 110 | 1922 |
| 210 | 2022 |
| 310 | 2122 |

The offset is a constant **+1812** on all 18 drifting records. The single
remaining record (VNI 100 on `karneliuk_a_eos1_eos4260.txt`) returns its source
VLAN `100` unchanged.

`vyos` declares `/vxlan-vnis/vlan-id` lossy and states the cause: VyOS models
one VNI per `vxlan vxlanN` netdev with no VLAN on the device, so the required
canonical `vlan_id` is **synthesised**. Recorded `lossy` — the record survives
and the value degrades — but this is the worst-shaped loss on the pair, because
a silently *wrong* VNI-to-VLAN binding is harder to catch than an absent one.
Re-derive every binding on the target.

### 6. SNMPv3 is a cryptographic downgrade; trap hosts have nowhere to land

2 of 6 cells carry an SNMP block. `community`, `location` and `contact` all
round-trip cleanly. The two sub-fields that do not:

- **`snmp.v3_users`** — both users survive with their names, groups and opaque
  key blobs, but the algorithms are collapsed: `auth_protocol` sha256 → sha,
  and `priv_protocol` aes256 → aes and aes128 → aes. `vyos` declares
  `/snmp/v3-user/auth-protocol` and `/priv-protocol` lossy and names it a
  cryptographic downgrade. Recorded `lossy`: the record survives, the strength
  degrades. Re-key on the target regardless — the carried key material is
  meaningless off-box.
- **`snmp.trap_hosts`** — the single trap destination on the one cell that sets
  one goes to zero. The rendered `service snmp` block emits community, contact,
  location and both v3 users, and contains **no trap-target node at all**.
  `arista_eos` declares `/snmp/trap-host` supported; `vyos` declares **no path
  for it at any level** while dropping it entirely — a third matrix
  under-declaration on this pair, same shape as the `/lags/lag` gap. Recorded
  `unsupported`: the record vanishes and there is no grammar it lands in.

### 7. A management-VRF default route leaks into the global table

`static_routes` is the field most likely to be misread on this pair. All 7
routes across 5 cells **survive** — destination, gateway and metric intact.
What drifts is one attribute on 2 of them:

```
S {"destination": "0.0.0.0/0", "gateway": "192.168.2.1", ..., "vrf": "MGMT"}
T {"destination": "0.0.0.0/0", "gateway": "192.168.2.1", ..., "vrf": ""}
```

`vyos` declares `/routing/static-route/vrf` unsupported — per-VRF static routes
are deferred past the Phase-3 VRF wire-up — while `vrf name <X>` instances
themselves are supported. So a default route that was scoped to the **MGMT
VRF** re-appears in the **global table**. That is not a lost route; it is a
route pointed somewhere else, which is a routing-correctness hazard on a device
whose management network was deliberately isolated.

Recorded `lossy`, not `unsupported`: the route record survives, 5 of the 7 are
untouched, and blocking the entire static-routing surface would misdescribe a
field that is mostly clean. Audit the VRF column of every migrated route.

### 8. The VyOS quote rewrite does not fire on this pair

The vyos render replaces embedded double-quotes in free text with apostrophes,
because VyOS rejects embedded quotes in value strings (`vyos.dev/T1246`), so a
`description` can return with altered punctuation. It is checked and it does
not happen here: **0 of the 73 populated interface descriptions contain an
embedded double quote**, and all 73 round-trip byte-identical.
`interfaces[].description` is `good` for both content *and* punctuation on this
corpus. The hazard is real for other sources; it simply has no material to act
on in these 6 fixtures.

## Credential material

No hash body is reproduced in this file or in the expectation YAML. Only the
*shape* is described: 9 of the 12 accounts carry a value under the codec's own
`arista:` vendor tag prefix, and the round-trip is byte-identical. The SNMPv3
auth and privacy keys are likewise described only as opaque vendor blobs — what
is recorded is that the *algorithm* label degrades, never the key. Per
`AGENTS.md`, password hashes are operator-traceable even when they are hashes,
and a document that quotes the value it describes defeats its own redaction.

## Two drift-shape readings that are wrong

**`static_routes` is not a total drop.** A mechanical "do the records match?"
pass reports the whole field vanishing, because changing `vrf` from `MGMT` to
`""` makes the record fail identity-matching, so the classifier reads it as
"all dropped, all new". The round-trip shows the same 7 destinations and
gateways going in and coming out. See finding 7 for what actually moved.

**`lags` and `local_users` are the known trap.** Renderers key off
`CanonicalInterface.lag_member_of`, not `CanonicalLAG.members`, so a bare
`lags` drift is often a cross-vendor naming artifact rather than a real loss.
Here it was probed rather than assumed, and on this pair it *is* real: the
render contains no bonding node at all (finding 1). `local_users` went the
other way — the bare drift signal is real but it is a role/privilege value
change, not the record loss the shape suggests (finding 2). Both were resolved
by inspecting the rendered configuration, not by reading the drift counts.

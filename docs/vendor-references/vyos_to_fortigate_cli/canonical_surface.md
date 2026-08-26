# VyOS → FortiGate CLI: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/vyos__fortigate_cli.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key
dispositions were resolved through the audit's own `actual_disposition()`
rather than inferred from the drift shape, so this file and the ratchet agree
by construction. Every loss recorded was additionally re-derived by hand —
`vyos.parse()` → `fortigate_cli.render()` → `fortigate_cli.parse()` on each of
the 13 fixtures — so no claim below rests on the drift shape alone.

- Fixture cells: **13** (12 real captures under `tests/fixtures/real/vyos/`
  plus `tests/fixtures/synthetic/vyos/kitchen_sink.conf`)
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the measured mesh run, and hand round-trips of the committed
> fixtures. Where a disposition rests on a declaration rather than an observed
> round-trip, the YAML says so explicitly.

## Device-class framing

`vyos` in this corpus is a **Linux-based software router**: `ethN` /
`bondN` / `dumN` / `lo` interface names, a curly-brace `config.boot`
(set-form input is normalised through `_setform_to_brace` first), dot1q
sub-interfaces written as `ethN.<tag>`, a single VRF, and a small VXLAN
surface on the container-lab fixtures. `fortigate_cli` is a **firewall /
security edge** codec: every port is L3, tenancy is expressed as VDOMs
rather than VRFs, and the whole config is `config … edit … next … end`
blocks.

The shared surface is therefore the **routed edge** — hostname, DNS/NTP,
interface addressing and admin state, static routes, SNMP, LAG bundles and
local administrators. Neither side is doing campus L2 here, and the fabric
surface (VXLAN, EVPN, anycast gateway, routing instances) exists on the VyOS
side but has nowhere to land on a FortiGate.

## The structural finding: interfaces with nothing to say are elided

This is the dominant shape of the pair and everything in the `interfaces[]`
block has to be read against it.

| measurement | value |
|---|---|
| source interface records, all 13 cells | **55** |
| records after parse → render → re-parse | **46** |
| records lost | **9** |
| cells where the interface name set differs | **5 of 13** |

The rule is exact and it is in the renderer, not in a heuristic:
`_iface_is_empty_stub()` (`netcanon/migration/codecs/fortigate_cli/render.py`,
~L371–L414) returns true when an interface has an **empty
`interface_type`** and no description, no IPv4, no IPv6, no MTU override, no
switchport / access-VLAN / trunk state, no `lag_member_of`, no VRF binding, no
DHCP client, and is **not** explicitly shut down. The elision at ~L538–L543
then drops such an interface unless its name matches a FortiOS-native port
shape (`_IS_FORTIGATE_PHYSICAL_PORT_RE` — `portN`, `mgmt`, `wan`, `lan`,
`dmz`, `ha`, `vlanN`, `loopbackN`, …) or it is a LAG bundle name.

VyOS's parser **never populates `interface_type`** — 0 of 55 source records
carry one — so every content-free VyOS port trips the predicate. And `lo` is
not a FortiOS-native shape (the regex accepts `loopbackN`, not `lo`), so a bare
VyOS loopback is elided too.

| cell | records lost |
|---|---|
| `metasploit-vyos-config.conf` | `eth1`, `lo` |
| `scottlaird-vyos-parser.conf` | `eth2`, `eth3`, `eth4`, `lo` |
| `vyos_forum_snmpv3_user_eq13.conf` | `lo` |
| `wcni-kind-gw0.conf` | `lo` |
| `wcni-kind-gw1.conf` | `lo` |

Every one of those nine records is address-less, description-less and
administratively up. The counter-examples in `kitchen_sink.conf` confirm the
predicate rather than contradict it: `eth3` survives because it is explicitly
shut (`enabled=False` is meaningful), and `eth4` / `eth5` survive because they
are `bond0` members.

**Consequence for reading the rest of this file:** on the 5 affected cells the
reconciler collapses every `interfaces[].*` sub-key after the first into
`STRUCTURAL_ONLY`, because one record-count change must not be counted nine
times. `interfaces[].name` carries that signal and is recorded `lossy`. The
surviving sub-fields are recorded `good` — and each of them was separately
measured on the **46 surviving records**, not waved through.

## Per-field measurement (13 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 13 | 0 | 0 |
| domain | 1 | 0 | 12 |
| dns_servers | 0 | 1 | 12 |
| ntp_servers | 12 | 0 | 1 |
| interfaces | 0 | 13 | 0 |
| vlans | 0 | 1 | 12 |
| static_routes | 4 | 0 | 9 |
| snmp | 2 | 2 | 9 |
| lags | 1 | 0 | 12 |
| local_users | 0 | 13 | 0 |
| vxlan_vnis | 0 | 3 | 10 |
| routing_instances | 0 | 1 | 12 |

`interfaces` and `local_users` drift on **every** cell at the top level, but
for reasons that are per-attribute, not per-record: `interface_type` on all 46
surviving interface records, and `role` on all 17 user records. The record
inventories are covered separately above and below.

Fields trivially empty on all 13 cells: `timezone`, `syslog_servers`,
`dhcp_servers`, `radius_servers`, `evpn_type5_routes`, `raw_sections`,
`apply_groups`, `group_content`, `anycast_gateway_mac`.

### Per-record detail on the 46 surviving interface records

| sub-field | records drifted | of surviving | shape |
|---|---|---|---|
| `interface_type` | 46 | 46 | empty → a type the FortiOS parser inferred |
| `description` | 2 | 46 | truncated to 25 chars (exact prefix kept) |
| `dhcp_client` | 3 | 46 | `true` → `false` |
| `dot1q_vlan` | 2 | 46 | tag → null (re-homed into `vlans[]`) |
| `dhcp_client_v6` | 1 | 46 | value → empty |
| `vrf` | 1 | 46 | value → empty |
| `enabled` | 0 | 46 | — |
| `mtu` | 0 | 46 | — |
| `ipv4_addresses` | 0 | 46 | — |
| `ipv6_addresses` | 0 | 46 | — |
| `lag_member_of` | 0 | 46 | — |
| `vrrp_groups` | 0 | 46 | — |

Population counts on the source side, so the thin ones are visible: IPv4 on 21
records / 9 cells, IPv6 on 20 records / 5 cells, description on 15 records / 7
cells, MTU on 1 record / 1 cell, `lag_member_of` on 2 records / 1 cell, VRF on
1 record / 1 cell, `vrrp_groups` on **0** records anywhere.

## `interface_type` is the inverse of the usual loss

Every other pair in this mesh loses the IANA type hint. This one **gains**
one, and that is why the field is still recorded `lossy`: the canonical value
does not round-trip.

- source: `""` on all 55 records (VyOS asserts no ifType)
- target after re-parse, on the 46 survivors: **43** `ianaift:ethernetCsmacd`,
  **2** `ianaift:l3ipvlan`, **1** `ianaift:ieee8023adLag`

The FortiGate parser infers the type from the rendered name shape and the
`set type vlan` / `set type aggregate` sub-settings. Both matrices already
declare `/interfaces/interface/config/type` lossy and both say why — VyOS
"declares no IANA ifType", FortiOS "has no IANA ifType; inferred from
`type vlan` sub-setting or name shape".

The operational point is worth stating plainly: the migrated intent will show
a type claim that **came from the target's name-shape inference, not from the
source config**. Nothing was lost, but nothing was carried either, and a
downstream consumer that trusts `interface_type` is trusting a guess.

## The `description` truncation the audit cannot see

Recorded here rather than as a `lossy` disposition, deliberately.

The FortiGate render caps `set alias` at 25 characters
(`render.py` ~L567–L569, `iface.description[:25]`, per the FortiOS alias
limit the target matrix declares). On `scottlaird-vyos-parser.conf` two
descriptions of 48 characters come back at 25, with the target string an exact
prefix of the source — semicolon-delimited patch-panel metadata, so the
truncation removes the far-end port and the circuit speed.

That cell is **also** one of the five whose interface list shrank. The
reconciler therefore classifies `interfaces[].description` as
`STRUCTURAL_ONLY` there and never emits an evidenced-loss class for it
anywhere on the pair — which means a `lossy` declaration would score as an
unevidenced claim and fail the per-pair ratchet by construction. The YAML says
`good`, and the note says exactly this. The measurement is real; the audit's
granularity cannot carry it.

**This is not the VyOS quote rewrite.** The VyOS *render* replaces embedded
double quotes with apostrophes (VyOS rejects embedded quotes in value strings
even when escaped — vyos.dev/T1246), so a description can come back with
altered punctuation on any pair where VyOS is the **target**. VyOS is the
**source** here, so that mechanism is not in play. What was measured is a
length cap on the FortiOS side: the punctuation is untouched, the tail of the
text is gone.

## The dot1q tag moves house

`vlans` is the one field where records **appear** rather than vanish.

VyOS declares `/vlans/vlan/id` **unsupported** and emits no VLAN record on any
of the 13 cells — a dot1q sub-interface lands in `interfaces[]` as
`eth1.100` with `dot1q_vlan=100`. The FortiGate render writes that as a child
interface (`edit "eth1.100"` / `set type vlan` / `set vlanid 100` /
`set interface "eth1"`), and the FortiGate parser reconstructs it as a
canonical VLAN record. On `kitchen_sink.conf`:

- `vlans`: **0 → 2** (ids 100 and 200, names synthesised as `eth1.100` /
  `eth1.200` from the child-interface names)
- `interfaces[].dot1q_vlan` on those two records: **tag → null**

So the 802.1Q tag survives the migration; the canonical slot it lives in does
not. FortiOS declares `/interfaces/interface/dot1q-vlan` unsupported (not yet
wired, ship-before-wire GAP 7), which is the other half of the same move.
`vlans[].id` carries the record-level signal and is `lossy`; the other five
`vlans[].*` keys are `good`, because there is no surviving source VLAN record
whose value could have degraded — the source produces none at all.

## Identity: nobody disappears, but the vocabulary is rewritten

17 local-user records across all 13 cells, **17 after the round-trip, zero
dropped**. `local_users[].name` is `good` and the record inventory is intact —
the failure mode the IOS-XR pairs have (accounts silently vanishing by secret
type) does not occur here.

Two things do change, on every record:

### Role → FortiOS accprofile

`role` drifts on **17 of 17** records across all 13 cells, uniformly
`admin` → `super_admin`. That is the FortiOS accprofile namespace, and
`super_admin` is its full-privilege profile, so the privilege level is not
being escalated — the token is being translated.

The honest limit of that claim: **every** source record on this corpus carries
role `admin`. There is no `operator` or read-only record in the committed
VyOS fixtures, so this measurement says nothing about whether a lower
privilege level would map to a lower accprofile or would also flatten to
`super_admin`. Verify the mapping for non-admin accounts before cutover
instead of assuming it from this pair.

### Password → `fortios:ENC ` prefix, body intact

`hashed_password` drifts on **16 of 17** records across 12 cells. The 17th does
not drift because its source hash is empty.

The transformation is a constant re-encoding, verified record by record: the
target value equals the literal string `fortios:ENC ` followed by the source
value, byte for byte. Source lengths on this corpus run 10–106 characters, all
in the `$6$` crypt scheme; target lengths are exactly 12 longer. **The
credential is carried.** This is the benign half of the failure mode that
IOS-XR sources hit — no hash body is degraded, replaced, or turned into a
cleartext marker.

`privilege_level` was checked separately and drifts on no record, even though
VyOS declares `/local-users/user/privilege-level` lossy on its own side.

## SNMP: the user survives, its bookkeeping does not

4 of 13 cells populate SNMP. `community`, `location` and `contact` round-trip
byte-identical on every cell that sets them; `trap_hosts` is empty everywhere,
so that key rests on declarations rather than a round-trip.

`v3_users` drifts on the 2 cells that carry a USM user
(`vyos_forum_snmpv3_user_eq13.conf`, `kitchen_sink.conf`). Both users survive
as records — 1 in, 1 out on each cell — with four sub-field changes:

| sub-field | shape | grounded in |
|---|---|---|
| `group` | value → empty | FortiOS declares `/snmp/v3-user/group` lossy: `config system snmp user` carries no VACM group |
| `engine_id` | value → empty (a 22-char and a 12-char id) | FortiOS declares `/snmp/v3-user/engine-id` lossy: engineIDs are device-assigned |
| `priv_protocol` | `aes` → `aes128` | FortiOS declares `/snmp/v3-user/priv-protocol` lossy; here it is a naming normalisation, not a cipher substitution |
| `auth_passphrase` / `priv_passphrase` | literal `ENC ` prefix prepended, body byte-identical | same re-encoding as the admin password |

The `aes` → `aes128` change deserves the distinction: the target matrix's
lossy reason warns about a **3DES** source cipher being substituted with AES,
which is a real security-level change. That is **not** what happens here.
Nothing on this corpus uses 3DES; the observed change is AES being spelled
with its key length. The declared risk is real but untriggered by these
fixtures.

No passphrase, hash body or community string is reproduced in this file or in
the expectation YAML — only the crypt-scheme marker, the constant prefix and
the string lengths are described. Per `AGENTS.md`, a document that quotes the
value it describes defeats its own redaction.

## DNS: FortiOS has two slots

`dns_servers` drifts on exactly one cell, `scottlaird-vyos-parser.conf`:
**3 → 2**. The rendered `config system dns` block carries `set primary` and
`set secondary` and nothing else, so the third resolver has nowhere to go and
is dropped. The first two survive in order.

Both matrices declare `/system/dns-server` supported, and this is not a
concept gap — it is a capacity limit inside a concept both sides model, which
is why it is `lossy` rather than `unsupported`.

`domain` rides in the same rendered block (`set domain`) and round-trips on
the single cell that sets one. Notable: the **fortigate_cli matrix declares
nothing for domain at any level** — neither supported, lossy nor unsupported —
while the render and the parser both handle it. That `good` therefore rests on
the measured round-trip, not on a declaration. Same standing shape as `lags`
below; it is a matrix under-declaration, not a pair-specific fact.

## The fabric surface: three total drops

These are the fields where FortiGate has no construct at all, and each one is
declared `unsupported` at the exact path by the target matrix.

| field | measured | target declaration |
|---|---|---|
| `vxlan_vnis` | 3 cells populate (VNI 10, 10, 10100), **all records → 0** | `/vxlan-vnis/vni`, `/source-interface`, `/udp-port` unsupported — "VXLAN not modelled — FortiGate is a firewall codec" |
| `routing_instances` | 1 cell populates (one VRF), **record → 0** | `/routing-instances/instance` unsupported — "Render emits no VRF/routing-instance construct (VDOMs not modelled)" |
| `interfaces[].vrf` | the same cell's one VRF-bound port, value → empty | same mechanism |

A vanished record is not lossy (#436): `lossy` warns and stays compatible,
which would understate losing every overlay and every VRF binding. Both
`vxlan_vnis[].vni` and `routing_instances[].name` are recorded `unsupported`,
and their sibling sub-keys are `good` because a record-count change must be
counted once, not three times.

`interfaces[].vrf` and `routing_instances[].name` are **one mechanism, not two
independent findings** — neither is cited as evidence for the other.

## `lags` round-trips despite an empty declaration

One LAG record on one cell (`kitchen_sink.conf`: `bond0`, members `eth4` /
`eth5`, mode `active`) and it comes back **byte-identical**, including the
bundle name. The render emits `edit "bond0"` / `set type aggregate` /
`set member "eth4" "eth5"` / `set lacp-mode active`, and the parser reads it
straight back. No reliance on the reconciler's `_canonical_lag_name`
equivalence shim was needed — the raw strings match.

Standing observation, same class as `domain` above: the **fortigate_cli matrix
declares nothing for `/lags/lag`** while implementing it end to end. That is a
matrix under-declaration in the honest direction (the code does more than it
claims), and it belongs to a codec change rather than to this file.

## Source-side gaps vs target-side drops

`vyos` declares these **unsupported at the exact path**, so as a *source* it
never emits them and there is nothing for FortiGate to lose:

`/dhcp-servers/pool` · `/radius-servers/server/host` ·
`/radius-servers/server/key` · `/vlans/vlan/id` · `/anycast-gateway-mac` ·
`/interfaces/interface/dot1q-vlan` ·
`/interfaces/interface/vrrp-groups/group/*` ·
`/interfaces/interface/{switchport-mode,access-vlan,trunk-allowed-vlans,trunk-native-vlan,voice-vlan}`

`raw_sections` is a near-miss worth naming: VyOS declares
`/system/raw-sections/version-banner` **lossy**, but the reason states the
`// vyos-config-version` trailer and the unmodelled `service` / `system`
blocks are *discarded on parse*. The canonical field is consequently empty on
all 13 cells, which makes it a source-side gap in practice — recorded
`not_applicable`, not `lossy`.

`evpn_type5_routes` is declared by neither codec and populated on no cell.

Two fields are symmetric gaps — **both** matrices declare them unsupported —
and those are recorded `unsupported` rather than `not_applicable`:
`/system/timezone` and `/system/syslog-server`. `/anycast-gateway-mac` is also
declared unsupported on both sides and is recorded `unsupported` for the same
reason, even though the source could never have emitted it.

## Declarations that never fired on this corpus

Stated so a future re-pass does not mistake silence for safety:

- `/interfaces/interface/ipv6/address/scope` — FortiOS declares it lossy
  (parse hardcodes `scope=global`, never re-inferring link-local from
  `fe80::/10`). All 20 IPv6-bearing records round-tripped with scope and
  `is_secondary` intact, because no committed VyOS fixture carries a
  link-local or secondary IPv6 address. The declared risk is real and
  untested here.
- `/interfaces/interface/vrrp-groups/group/*` — FortiOS declares five of these
  lossy (single `set vrip`, single `set vrdst`, no per-group description,
  interface-wide virtual MAC, cross-family mode substitution). VyOS emits zero
  VRRP groups on any cell, so none of it was exercised. First-hop redundancy
  must be re-authored on the FortiGate by hand.
- `/routing/static-route/description` — VyOS declares it lossy; no committed
  cell sets a route description. The 7 static routes across 4 cells compared
  field-for-field identical, IPv6 route included.
- `/vlans/vlan/description`, `/vlans/vlan/tagged-ports`,
  `/vlans/vlan/untagged-ports` — FortiOS declares all three lossy or
  unsupported, and they would matter for a source that produces VLAN records.
  VyOS does not.

## Two DHCP-client losses the 43-key walk does not cover

Neither `interfaces[].dhcp_client` nor `interfaces[].dhcp_client_v6` is a key
in the standard canonical walk, so neither carries a disposition in the
expectation YAML. Both were measured on this pair and are recorded here so
they are not lost — they feed the parent `interfaces` drift and nothing else.

**IPv4 — dropped on re-parse.** `dhcp_client` goes `true` → `false` on 3
records across 3 cells (`houdev_vyos_dhcpv6_pd_client.conf` `eth0`,
`scottlaird-vyos-parser.conf` `eth5`, `kitchen_sink.conf` `eth2`). The render
is not at fault: it emits `set mode dhcp` (`render.py` ~L651). The FortiGate
parser has no handler that reads `set mode dhcp` back — the only DHCP-mode
handler is `set ip6-mode dhcp` (`parse.py` ~L397). So a DHCP-configured WAN
port survives as an interface record with no address and no DHCP flag.

**IPv6 — dropped on render.** `dhcp_client_v6` goes `dhcpv6` → `""` on 1
record on 1 cell. This one is a token-vocabulary mismatch between the two
codecs: the VyOS parser writes the sentinel `"dhcpv6"` (`parse.py` ~L896–897)
while the FortiGate render only emits `set ip6-mode dhcp` when the canonical
value is exactly `"dhcp6"` (`render.py` ~L667). The values never match, so
the DHCPv6 client is dropped before it reaches the target text.

Both are codec-level observations rather than pair-level expectations, and
they belong to a codec change rather than to this file. The operational
consequence is the same either way: after migrating a VyOS box whose uplink
was a DHCP client, the FortiGate port comes up with no address at all.

## One drift-shape reading that is wrong

A mechanical "did the target side change?" pass over this pair reports
`local_users` as drifting on **all 13 cells** and invites the conclusion that
the identity surface does not survive. It does. Seventeen accounts go in and
seventeen come out; not one is dropped. What actually changes is the role
*token* (`admin` → `super_admin`, a namespace translation) and the password
*encoding* (a constant `fortios:ENC ` prefix over a byte-identical `$6$`
body). Both are recorded where they are measured, on
`local_users[].role` and `local_users[].hashed_password`, and
`local_users[].name` is `good`.

Reading the parent's drift count as an account loss would raise a migration
alarm that the round-trip does not support — and would bury the two changes
that an operator actually has to check.

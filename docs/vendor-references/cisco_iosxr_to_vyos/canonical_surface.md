# IOS-XR → VyOS: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/cisco_iosxr__vyos.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key
dispositions were resolved through the audit's own `actual_disposition()` rather
than inferred from the drift shape, so this file and the ratchet agree by
construction. Every loss recorded was additionally re-derived by hand —
`cisco_iosxr.parse()` → `vyos.render()` → `vyos.parse()` on each of the 12
fixtures — so no claim below rests on the drift shape alone.

- Fixture cells: **12** (11 real captures + 1 synthetic kitchen-sink)
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the measured mesh run, and hand round-trips of the committed
> fixtures. Where a disposition rests on a declaration rather than an observed
> round-trip, the YAML says so explicitly.

## Device-class framing

`cisco_iosxr` in this corpus is a **service-provider edge/core router**:
4-segment interface names (`GigabitEthernet0/0/0/1`), channelized
sub-interfaces, `Bundle-Ether` LAGs, `BVI` interfaces, `MgmtEth0/RP0/CPU0/0`,
and a heavy VRF surface whose RD is harvested from `router bgp` rather than read
from a VRF stanza.

`vyos` is a **Linux software router**. Its device names are `ethN` / `bondN` /
`dumN` / `lo`; it has no VLAN database (802.1Q is a `vif` sub-interface), no
switchport grammar, and no VARP/anycast-gateway grammar. Its config is a
curly-brace `config.boot`; set-form input is converted through
`_setform_to_brace` before parsing.

The shared surface is therefore the **routed edge** — interface addressing, MTU,
admin state, VRF identity, static-route destinations, local-user identity.
There is no campus L2 surface on either side of this pair to migrate.

## Two structural findings, and they point in opposite directions

### The interface inventory is fully preserved

| measurement | value |
|---|---|
| source interface records, all 12 cells | **156** |
| records after parse → render → re-parse | **156** |
| cells where the interface name set differs | **0** |

IOS-XR 4-segment names, channelized sub-interfaces (`…0/0/0/1.100`),
`Bundle-Ether`, `BVI` and `MgmtEth0/RP0/CPU0/0` all survive the VyOS render
verbatim. The consequence is the useful one: **every interface loss on this pair
is a genuine per-attribute loss** that stands on its own measurement, and every
interface sub-field that survives is recorded `good` rather than being dragged
down by a vanishing parent. Nothing in the interface block is correlated drift.

Preserved is not the same as valid. The render writes `ethernet
GigabitEthernet0/0/0/1 { … }` — a device name no real VyOS box will accept. The
fidelity harness scores **preservation**, not target-syntax validity. That
distinction explains the `interface_type` result below, and it is why the port
translator matters operationally.

### The VLAN records vanish outright

4 of 12 cells populate `vlans`, each with exactly **one** record. All 4 records
are gone after the round-trip: **4 in, 0 out.** VyOS has no top-level VLAN
database to render them into, and its matrix declares `/vlans/vlan/id`
unsupported saying precisely that.

Those 4 records carry **only** an `id` (35, 35, 100, 200) — name, description,
addressing and port membership are empty on every one. So the record-level loss
is real and is claimed once, on `vlans[].id`; the five sibling `vlans[].*` keys
have no value to lose and are recorded `good`. Recording the same disappearance
six times would inflate one loss into six.

## Per-field measurement (12 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 12 | 0 | 0 |
| domain | 8 | 0 | 4 |
| ntp_servers | 1 | 0 | 11 |
| interfaces[].name / enabled / ipv4_addresses | 12 | 0 | 0 |
| interfaces[].mtu | 4 | 0 | 8 |
| interfaces[].ipv6_addresses | 3 | 0 | 9 |
| interfaces[].description | 8 | 1 | 3 |
| interfaces[].interface_type | 0 | 12 | 0 |
| interfaces[].lag_member_of | 0 | 4 | 8 |
| vlans[].* (all six keys) | 0 | 4 | 8 |
| static_routes | 0 | 6 | 6 |
| lags | 0 | 4 | 8 |
| local_users[].name / hashed_password | 9 | 0 | 3 |
| local_users[].role | 0 | 9 | 3 |
| routing_instances[].name | 8 | 0 | 4 |
| routing_instances[].description | 0 | 1 | 11 |

Fields trivially empty on all 12 cells: `dns_servers`, `timezone`,
`syslog_servers`, `interfaces[].vrrp_groups`, `dhcp_servers`, all five `snmp.*`
keys, `radius_servers`, all three `vxlan_vnis[].*` keys, `evpn_type5_routes`,
`raw_sections`, `apply_groups`, `group_content`, `anycast_gateway_mac`.

### Per-record detail behind the interface drift

| sub-field | records affected | of total | shape |
|---|---|---|---|
| `interface_type` | 156 | 156 | value → empty string |
| `lag_member_of` | 15 | 15 populated | value → null |
| `dot1q_vlan` | 4 | 4 populated | value → null |
| `description` | 2 | 156 | embedded `"` → `'` |
| `enabled` | 0 | 156 | — |
| `mtu` | 0 | 11 populated | — |
| `ipv4_addresses` | 0 | 60 populated | — |
| `ipv6_addresses` | 0 | 11 populated | — |

`interface_type` has **no survivors**, which is the sharp difference from the
`cisco_iosxr → arista_eos` pair off the same corpus. There, 18
`ianaift:softwareLoopback` records survive because EOS re-derives the type from
`interface Loopback<N>`. Here all 156 drop: 126 `ianaift:ethernetCsmacd`, 18
`ianaift:softwareLoopback`, 10 `ianaift:ieee8023adLag`, 2 `ianaift:other`. The
vyos codec re-derives ifType from the **Linux device-name shape** (`ethN` →
ethernetCsmacd, `lo`/`dumN` → softwareLoopback, `bondN` → ieee8023adLag), and
because the render preserved IOS-XR names verbatim, not one rendered name
matches. Both matrices already declare `/interfaces/interface/config/type`
lossy.

`description` is the VyOS free-text quote rewrite, and the distinction is
worth keeping straight: **the text survives, the punctuation does not.** VyOS
rejects embedded double quotes in a value string even when escaped
(vyos.dev/T1246), so the render substitutes apostrophes and emits a warning
while doing it. `"BVI for cBR8 port HA, requires static MAC"` returns as
`'BVI for cBR8 port HA, requires static MAC'` — identical words, two characters
changed. This is not a content loss; it is recorded because the audit compares
strings exactly.

## Source-side gaps vs target-side drops vs symmetric gaps

Three different things get confused with each other, so this pair separates
them explicitly.

**Source-side gaps** — `cisco_iosxr` declares these unsupported at the exact
path, so as a *source* it never emits them and there is nothing for VyOS to
lose. These are `not_applicable`:

`/snmp/community` · `/snmp/v3-user/{auth-protocol,priv-protocol,priv-passphrase,group}` ·
`/vxlan-vnis/{vni,source-interface,udp-port}` · `/evpn-type5-routes/route`

For most of them **vyos declares the field supported** — SNMP communities,
location, contact, trap hosts, and the VXLAN VNI surface. Re-authoring on the
target will stick, and a migration report should say so rather than implying
the target cannot hold them.

**Symmetric gaps** — *both* matrices declare the path unsupported. These are
`unsupported`, because a source that did carry them would still lose them:

`/system/timezone` · `/dhcp-servers/pool` ·
`/radius-servers/server/{host,key}` · `/anycast-gateway-mac` ·
`/interfaces/interface/vrrp-groups/group/*`

**Target-side drops** — the source supports it and VyOS does not. On this pair
there is exactly one: `/system/syslog-server`, which cisco_iosxr declares
supported and vyos declares unsupported ("Render emits no syslog config"). No
committed cell populates logging hosts, so that entry rests on the two
declarations and the YAML says so.

## Four findings worth carrying forward

### 1. The LAG surface is a total concept drop

10 LAG records across the 4 bundle-carrying cells become **0** after the
round-trip, and the rendered VyOS config contains no `bonding` block, no `mode`
line and no `member interface` line anywhere. All 15 interface records with a
`lag_member_of` value come back null while the member ports themselves survive
— the dangerous shape, because the ports come up standalone rather than bundled.

The mechanism is a **name-shape dependency**, not a modelling gap. The renderer
picks a block type from the device name (`netcanon/migration/codecs/vyos/render.py`,
`_vyos_block_type`): only a name matching `^bond\d+$` becomes a `bonding` block,
and only a `bonding` block gets the `mode` / `member` lines appended. A bundle
named `Bundle-Ether1` falls through to `ethernet Bundle-Ether1`, so the
aggregation is silently discarded while the parent interface record survives.

Neither matrix predicts this. `cisco_iosxr` declares `/lags/lag/{name,members,mode}`
supported; `vyos` declares the same surface supported bar `/lags/lag/mode`,
which it flags lossy for the non-LACP balancing modes. **The drop is a measured
render-path gap and belongs in a codec issue, not a matrix edit.**

Both `lags` and `interfaces[].lag_member_of` are recorded `unsupported`, since a
vanished record is not lossy (#436) and `lossy` — which warns but stays
compatible — would badly understate losing every bundle on a provider-edge
router. **They are one mechanism, not two independent findings.** Neither is
cited as evidence for the other; each is recorded where it is measured.

**Mitigation, measured not assumed.** Running the canonical port-name translator
before the render recovers the LAG *record*:

```py
from netcanon.migration.canonical.port_names import translate_port_names
res = translate_port_names(src_intent, cisco_iosxr_codec, vyos_codec, rename_map={})
vyos_codec.parse(vyos_codec.render(res.intent))
```

On `batfish_ibgp_border01.txt` that yields `bond23` and `bond45` surviving the
round-trip with `mode=active`. It is **not a fix**: on this corpus every
4-segment member name (`GigabitEthernet0/0/0/2` … `/5`) collapses onto a single
`eth0`, so each bond comes back with one member instead of two and membership is
still not recovered. Note also that the mesh measures the *bare* render, which
does not run the translator.

### 2. Every account arrives as `admin` — a fail-open privilege collapse

All 14 user records across the 9 populated cells survive with their names, and
`local_users[].role` drifts on all 14:

| source role | source privilege | target role | target privilege | records |
|---|---|---|---|---|
| `root-lr` | 15 | `admin` | 15 | 13 |
| `operator` | 1 | `admin` | **15** | 1 |

The 13 `root-lr` → `admin` mappings are fair. The single `operator` record —
`readonly` on `kitchen_sink.cfg` — is the finding: a read-only account arrives
on the target with full administrative access. **The failure direction is
open, not closed.**

The mechanism is a parser constant, not a render gap:
`netcanon/migration/codecs/vyos/parse.py` assigns `privilege_level=15` and
`role="admin"` to every `system login user` it reads, on the grounds that VyOS
login accounts carry no role or numeric privilege in the common case. `vyos`
declares `/local-users/user/privilege-level` lossy and states this; the *role*
leg of the same collapse is not separately declared.

Recorded `lossy`, not `unsupported`: the account does not vanish and VyOS
genuinely models login users — it is a privilege attribute on a surviving
record that degrades. Audit every migrated account's access level before
cutover.

### 3. Secrets survive byte-for-byte — which is not the same as working

`local_users[].hashed_password` is `good`, and this is a clean divergence from
the `cisco_iosxr → arista_eos` pair, where type-10 secrets degrade into a
cleartext marker. Here all 14 records return an identical value, covering all
three IOS-XR secret forms present in the corpus:

| source secret form | records | outcome |
|---|---|---|
| type-5 (crypt) | 6 | identical |
| type-7 (reversible vendor obfuscation) | 5 | identical |
| type-10 (crypt) | 3 | identical |

The render writes the canonical value straight into
`authentication { encrypted-password … }` and the parser reads it straight
back. But the audit scores **preservation, not target-syntax validity**: a Cisco
type-7 or type-10 token is not a Linux crypt string, so a byte-perfect carry
does not make it a credential VyOS can authenticate against. Set passwords on
the target before cutover regardless.

**Credential material.** No hash body, and no fragment of one, is reproduced in
this file or in the expectation YAML — only the IOS-XR type number, the crypt
scheme marker and the string length are described. Per `AGENTS.md`, password
hashes are operator-traceable even when they are hashes, and a document that
quotes the value it describes defeats its own redaction.

### 4. Static routes survive; their VRF scoping does not

20 routes in, 20 out, and **every one of the 20 destinations matched** on the
target side. 12 are fully clean. The other 8:

| loss | routes | shape |
|---|---|---|
| VRF scope | 3 | `AZURE` / `blue` / `CUSTOMER-A` → empty |
| egress interface re-mounted | 4 | `interface` value moves onto `gateway` (`Null0` ×3, `BVI500` ×1) |
| egress interface dropped | 2 | gateway kept, interface qualifier lost |

The VRF loss is the one to act on. The route does not vanish — it **moves**,
out of a customer VRF and into the global table. `vyos` declares
`/routing/static-route/vrf` unsupported and says why: per-VRF static routes are
deferred past the Phase-3 VRF wire-up, while the `vrf name` instances themselves
are supported. A customer prefix silently installed in the global table is a
leak rather than an outage, which is exactly what makes it easy to miss at
cutover.

The interface re-mount is a field-shift, not a content loss: `route 192.0.2.0/24
{ next-hop Null0 }` re-parses with `Null0` in `gateway` instead of `interface`.
Worth knowing that `next-hop Null0` is a Cisco-ism VyOS would express as
`blackhole` — again, preservation is not validity.

The pair is recorded `lossy`, not `unsupported`, because destination and
next-hop — the part that forwards traffic — survive on 20 of 20.

## One drift-shape reading that is wrong

A mechanical "is the target side empty?" pass over this pair reports
`routing_instances` as a **total drop**. It is not. The round-trip shows **15
instance records in and 15 out** across the 8 cells that carry them, every name
matched — `AZURE`, `red` / `blue` / `management`, `CUSTOMER`, `CUSTOMER-A` /
`MGMT` and the numeric `100`. The render emits `vrf { name <X> { table <N> } }`
and binds each interface with a `vrf` leaf. (Match is on the name *set*: the
render sorts instances alphabetically, so `red, blue, management` returns as
`blue, management, red` on the three VPNv4 PE cells. Identity is preserved;
list order is not.)

What actually empties is the **L3VPN plumbing** hanging off those instances, and
the numbers belong here because none of these are audited keys on this pair:

| sub-field | populated records | emptied |
|---|---|---|
| `route_distinguisher` | 10 | **10** |
| `rt_exports` | 12 | **12** |
| `rt_imports` | 12 | **12** |
| `description` | 2 | **2** |

So a VPNv4 PE migrated this way arrives with its VRFs correctly **named** and
empty of L3VPN control-plane state. `routing_instances[].name` is therefore
`good` (identity is clean), `routing_instances[].description` is `lossy` (the
label empties while the record survives), and the "total drop" reading is an
artifact of reading a sub-field emptying as a record vanishing.

`cisco_iosxr` already declares `/routing-instances/instance` lossy on its own
side, because the RD is harvested from `router bgp` rather than read from a VRF
stanza; `vyos` declares `/routing-instances/instance/table` lossy because it
must synthesise the numeric table id (`100 + sort-index`). Neither lossiness
touches the instance name.

It still matters: on a PE, the VRF description is usually the only place the
customer name is written down.

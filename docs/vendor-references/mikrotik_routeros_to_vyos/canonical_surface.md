# MikroTik RouterOS → VyOS: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/mikrotik_routeros__vyos.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key
dispositions were resolved through the audit's own `actual_disposition()` rather
than inferred from the drift shape, so this file and the ratchet agree by
construction. Every loss recorded was additionally re-derived by hand —
`mikrotik_routeros.parse()` → `vyos.render()` → `vyos.parse()` on each of the 5
fixtures — so no claim below rests on the drift shape alone.

- Fixture cells: **5**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the measured mesh run, and hand round-trips of the committed
> fixtures. Where a disposition rests on a declaration rather than an observed
> round-trip, the YAML says so explicitly.

The five cells are `tests/fixtures/real/mikrotik/ntc_ip_address_export.rsc`,
`routeros_diff_verbose_export.rsc`, `taqavi_initial_provisioning.rsc`,
`user_contrib_crs310_ros7.rsc`, and
`tests/fixtures/synthetic/mikrotik_routeros/kitchen_sink.rsc`.

## Device-class framing

`mikrotik_routeros` in this corpus is a **small-to-mid edge router / CRS
switch-router**: `etherN` ports with a factory `default-name`, `bridgeN`
software bridges, `vlanN` L3 sub-interfaces, `bondN` bonds, an on-box DHCP
server, and a local `/user` database. `vyos` is a **Linux software router**:
`ethN` / `bondN` / `lo` device names, 802.1Q expressed as `vif` sub-interfaces
rather than a VLAN table, and no on-box DHCP-server or RADIUS render path.

Both are routers, both are Linux-adjacent, and the shared surface is
correspondingly wide — this is one of the friendlier pairs in the mesh. The
migration this pair models is a MikroTik CCR/CRS at a branch or lab edge being
replaced by a VyOS instance carrying the same ports, addressing, MTU, bonds and
static routing.

## The structural finding — the interface inventory survives whole

| measurement | value |
|---|---|
| source interface records, all 5 cells | **46** |
| records after parse → render → re-parse | **46** |
| cells where the interface name set differs | **0** |

`etherN`, `bridgeN`, `vlanN` and `bondN` names all survive the VyOS render
verbatim; nothing is dropped and nothing is invented. The consequence is the
useful one: **every interface loss on this pair is a genuine per-attribute
loss** that stands on its own measurement, and every interface sub-field that
survives is recorded `good` rather than being dragged down by a vanishing
parent. Nothing in the interface block is correlated drift.

Where this pair *does* lose records is elsewhere — VLAN table entries, DHCP
pools, RADIUS servers and SNMP trap hosts — and each of those is booked exactly
once, on the key the audit measures it on.

## Per-field measurement (5 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 3 | 2 | 0 |
| dns_servers | 1 | 0 | 4 |
| ntp_servers | 3 | 0 | 2 |
| interfaces | 0 | 5 | 0 |
| vlans | 0 | 3 | 2 |
| static_routes | 0 | 1 | 4 |
| dhcp_servers | 0 | 3 | 2 |
| snmp | 2 | 1 | 2 |
| lags | 1 | 0 | 4 |
| local_users | 0 | 1 | 4 |
| radius_servers | 0 | 1 | 4 |

Fields trivially empty on all 5 cells: `domain`, `timezone`, `syslog_servers`,
`vxlan_vnis`, `evpn_type5_routes`, `routing_instances`, `raw_sections`,
`apply_groups`, `group_content`, `anycast_gateway_mac`.

### Per-record detail behind the interface drift

Populated-record census across all 46 interfaces, taken from the hand
round-trip rather than the mesh summary:

| sub-field | records populated | preserved | shape of the loss |
|---|---|---|---|
| `description` | 24 | **24** | — |
| `enabled` (45 up / 1 admin-down) | 46 | **46** | — |
| `mtu` | 17 | **17** | — |
| `ipv4_addresses` (13 addresses) | 13 | **13** | — |
| `ipv6_addresses` (4 addresses) | 3 | **3** | — |
| `lag_member_of` | 4 | **4** | — |
| `vrrp_groups` | 0 | — | not exercised |
| `interface_type` | 44 | **0** | value → empty string |
| `default_name` | 27 | **0** | value → empty string |

`interface_type` breaks down by type — **27** `ianaift:ethernetCsmacd`, **9**
`ianaift:l3ipvlan`, **6** `ianaift:bridge`, **2** `ianaift:ieee8023adLag` — and
**every one of the 44 drops**. Both matrices already declare
`/interfaces/interface/config/type` lossy, so the loss is expected; the
*totality* is the part worth recording. The vyos declaration states an
inference rule (`ethN` → ethernetCsmacd, `lo`/`dumN` → softwareLoopback,
`bondN` → ieee8023adLag), but nothing in this corpus recovers a type — including
`bond1` and `bond2`, which the stated `bondN` rule would cover. A grep of
`netcanon/migration/codecs/vyos/` finds **no assignment to `interface_type`
anywhere in the package**, which is consistent with the measurement. That is a
declaration-versus-behaviour mismatch on the vyos codec, not a pair-specific
fact, and it belongs to a codec change rather than to this file.

`default_name` is MikroTik's factory port label (`ether2` on a port an operator
renamed). It is not one of the audited keys — `interfaces[].name` is, and it is
clean on all 46 records — but it drops on all 27 records that carry one, because
VyOS has no factory-name concept to render it into. Recorded here so the
`interfaces[].name: good` entry cannot be mistaken for a claim that *every*
naming attribute survives.

## Source-side gaps vs target-side drops

`mikrotik_routeros` declares these **unsupported at the exact path**, so as a
*source* it never emits them and there is nothing for VyOS to lose:

`/system/domain` · `/routing-instances/instance` ·
`/routing-instances/instance/instance-type` · `/vxlan-vnis/vni` ·
`/vxlan-vnis/source-interface` · `/vxlan-vnis/udp-port` ·
`/anycast-gateway-mac` · `/vlans/vlan/tagged-ports` ·
`/vlans/vlan/untagged-ports` · `/routing/static-route/vrf` ·
`/interfaces/interface/{dot1q-vlan,switchport-mode,access-vlan,trunk-allowed-vlans,trunk-native-vlan,voice-vlan}`

Most of these are recorded `not_applicable`, not `unsupported`, and the
distinction is operational: vyos declares `/system/domain`,
`/routing-instances/instance/name`, `/vxlan-vnis/vni`, `/vxlan-vnis/mcast-group`
and `/vxlan-vnis/udp-port` **supported**, so re-authoring a search domain, a VRF
or a VXLAN overlay on the VyOS side will stick. The migration report should say
so rather than implying the target cannot hold them.

Three are different, because **both** matrices declare them unsupported — a
symmetric gap that no amount of re-authoring through this pipeline will carry:
`/system/timezone`, `/system/syslog-server`, `/anycast-gateway-mac`. Those are
`unsupported`.

And one runs the other way, which is the asymmetry worth flagging on this pair:
`mikrotik_routeros` declares `/interfaces/interface/vrrp-groups/group`
**supported** while vyos declares that whole subtree **unsupported** ("VyOS
VRRP / VRRPv3 is not modelled by the codec; the group is dropped on
migration"). No committed cell carries a VRRP group, so this is declared rather
than observed — but a real MikroTik edge router very often does, and it would be
dropped in silence.

## Four findings worth carrying forward

### 1. An empty hostname is rendered as the literal `vyos`

3 of 5 cells preserve the hostname byte-for-byte, including `Quinta Router`
with its embedded space. On the other 2 the canonical hostname is the empty
string, and the round-trip returns `'vyos'`:

```
hostname: '' → 'vyos'
```

The mechanism is the VyOS render: it has no omit-the-stanza path, so an empty
hostname renders as the VyOS factory default `host-name vyos`, and re-parsing
that line yields the literal string. Nothing is destroyed — there was no name
to destroy — but the canonical value changes from "unset" to a plausible-looking
name that was never configured, which is exactly the shape that survives a
migration review unnoticed. Recorded `lossy`: it warns, it stays compatible, and
the operator action is one line.

**A separate, source-side observation that explains one of those two cells, and
does not change the declaration above.** `mikrotik_routeros` recognises the
two-line *export* form of `/system identity` but not the one-line *script*
form. Minimal repro from the repo root:

```
py -c "import sys;sys.path.insert(0,'.');\
from netcanon.migration.codecs import mikrotik_routeros;\
from netcanon.migration.codecs.registry import get_codec;\
S=get_codec('mikrotik_routeros');\
print(repr(S.parse('/system identity set name=\"X\"\n').hostname));\
print(repr(S.parse('/system identity\nset name=\"X\"\n').hostname))"
```

prints `''` then `'X'`. That is why `taqavi_initial_provisioning.rsc` reaches
the VyOS render with an empty hostname despite carrying
`/system identity set name=…` on line 11; `ntc_ip_address_export.rsc` has no
identity line at all and is a genuine absence. The same one-line-form gap
affects `/user add …`, which is why that fixture also yields zero
`local_users` — the two-line `/user` + `add name=… group=full` form parses, the
one-line form does not. Both are source-codec parse gaps, out of scope for this
file, and neither alters what VyOS does with what it is handed.

### 2. The VLAN table vanishes; the VLAN's L3 mount does not

**9 VLAN records in, 0 out**, across the 3 cells that carry a VLAN table
(id `84`; ids `100/150/11/20/10`; ids `100/200/300`). Every record carried an
`id` and a `name`, 8 of 9 carried a `description`, and **none** carried
addressing or port membership.

vyos declares `/vlans/vlan/id` unsupported and states exactly why: VyOS has no
top-level VLAN database, and 802.1Q VLANs are modelled as `vif <vid>`
sub-interfaces. `mikrotik_routeros` declares `/vlans/vlan/id` supported, so the
source side is not the problem.

What *does* survive is the L3 sub-interface that MikroTik built the VLAN from:
`vlan100`, `clustervlan100` and friends are all present in the 46-record
interface inventory with their addressing intact. The rendered config carries
them as `interfaces { ethernet vlan100 { … } }` — the string `vif` does not
appear in the render at all, and `dot1q_vlan` is empty on both sides. So the
**tag number survives only as characters inside an interface name**; nothing in
the output declares it as an 802.1Q tag, and re-parsing recovers neither a VLAN
record nor a `dot1q_vlan`.

The record-level loss is booked **once**, on `vlans[].id`. The five sibling
`vlans[].*` keys are recorded `good`: they are about what happens to a value
when the record survives, and recording the same disappearance six times would
turn one loss into six. `vlans[].name` and `vlans[].description` were populated
on the source side and are gone with the record — that is the *same* loss,
already counted, not an additional one.

### 3. Three whole concepts the render never reaches

Each of these is a record-level disappearance, measured, and each is a distinct
mechanism — none is cited as evidence for another.

| field | records in | records out | cells | target declaration |
|---|---|---|---|---|
| `dhcp_servers` | 5 | **0** | 3 | `/dhcp-servers/pool` **unsupported** |
| `radius_servers` | 2 | **0** | 1 | `/radius-servers/server/{host,key}` **unsupported** |
| `snmp.trap_hosts` | 1 | **0** | 1 | **nothing declared** |

The DHCP one is the operationally sharpest: `mikrotik_routeros` declares
`/dhcp-servers/pool/lease-time` lossy — i.e. it genuinely parses pools — and a
small MikroTik edge router is very often the DHCP server for the site it sits
in. Five pools across three of five fixtures is not an edge case on this corpus.

RADIUS carries the usual second loss: the vyos declaration is explicit that
"the RADIUS shared secret is dropped on migration", so even a target that grew
a server list would not carry the key.

The trap-host row is the one that needs a caveat. `mikrotik_routeros` declares
`/snmp/trap-host` **supported**; vyos declares **no path for it at all** —
neither supported, lossy nor unsupported — while dropping trap destinations
entirely: the rendered `snmp { … }` stanza contains no `trap` token anywhere.
The behaviour is measured and the disposition follows the behaviour, but the
missing declaration is a **matrix under-declaration on the vyos codec**, not a
pair-specific fact, and belongs to a codec change rather than to this file.

All three are recorded `unsupported` rather than `lossy`, because a vanished
record is not lossy (#436) — `lossy` warns and stays compatible, which would
badly understate a branch router arriving with no DHCP service.

### 4. Credentials and roles: everything collapses to `admin`

Only `kitchen_sink.rsc` populates local users: **3 records in, 3 out**, all
three surviving by name. What changes is authority.

| user | role src → rt | privilege_level src → rt |
|---|---|---|
| `admin` | `admin` → `admin` | 15 → 15 |
| `operator` | `operator` → **`admin`** | 10 → **15** |
| `auditor` | `operator` → **`admin`** | 1 → **15** |

vyos declares `/local-users/user/privilege-level` lossy and says why: VyOS
`system login user` accounts have no numeric privilege level in the common case,
so "the codec maps every login user to privilege 15 / role `admin`". The role
collapse and the privilege-level collapse are **one mechanism, not two
findings** — neither corroborates the other, and the pair YAML books the loss
once, on `local_users[].role`, because that is the key the audit measures.

This is a privilege *escalation* on migration: two accounts that were read-only
on the MikroTik box arrive on VyOS with full administrative rights. Worth
noting that vyos declares `/local-users/user/role` **supported**, so the
observed role change is another declaration-versus-behaviour mismatch to raise
against the codec rather than to absorb here.

Separately, and not a loss on this pair: **no MikroTik fixture carries any
password material at all** — `hashed_password` is empty on all 3 source records,
because a RouterOS `.rsc` export does not include the user password database.
The rendered VyOS `login` stanza is correspondingly bare (`user admin { }`, no
`authentication` node), so **every migrated account arrives with no
credential**. That is not something the migration lost; it is something the
export never had. Set passwords on the VyOS side before the box is reachable.

### Credential material

No hash body, passphrase or shared secret is reproduced in this file or in the
expectation YAML. The SNMPv3 auth and privacy keys are described only by their
shape — an opaque VyOS `encrypted-password` blob — and every probe used to write
this file redacted the value before printing. One fixture contains a literal
placeholder password inside a comment-annotated `/user add` line; it is
deliberately not quoted here either, because a document that reproduces the
value it describes defeats its own redaction.

## Two drift-shape readings that are wrong

**`static_routes` is not a total drop.** A mechanical "is the target side
empty?" pass classifies this field TOTAL and reaches for `unsupported`. The
round-trip says otherwise: **4 routes in, 4 out** on the one cell that carries
them, with `destination`, `gateway` and `metric` identical on every one —
including the IPv6 default `::/0` and the interface-gateway route via `bridge1`.
What actually empties is `description`, on all 4 records: `Default route to
ISP`, `Branch network via core`, `Blackhole RFC1918 leakage` and `IPv6 default`
all return `''`. vyos declares `/routing/static-route/description` lossy and
states the cause — the render emits destination, next-hop and distance only. So
the field is `lossy`, the routes are intact, and the "total drop" reading is an
artifact of reading a sub-field emptying as a record vanishing.

**`interfaces` is not a total drop either.** The same mechanical pass flags the
whole interface field TOTAL, because the only two sub-fields that drift —
`interface_type` and `default_name` — both empty completely. The inventory is
untouched: 46 records in, 46 out, identical names, and every attribute an
operator actually forwards traffic with round-trips clean.

## SNMPv3: the records survive, the cryptography does not

4 v3 user records across 3 cells; **all 4 survive by name**, and both
passphrase blobs compare equal source-to-target on every record. What degrades
is algorithm strength, on the one cell that uses anything modern:

| user | auth src → rt | privacy src → rt |
|---|---|---|
| `public` (×2 cells) | `md5` → `md5` | `des` → `des` |
| `monitor-v3` | `sha` → `sha` | `aes128` → **`aes`** |
| `audit-v3` | `sha256` → **`sha`** | `aes256` → **`aes`** |

vyos declares both `/snmp/v3-user/auth-protocol` and `/priv-protocol` lossy and
names them cryptographic downgrades: `sha` on the VyOS side is SHA-1, and bare
`aes` loses the AES-192/256 key length. The records are intact, so this is
`lossy`, not `unsupported` — but "lossy" here means an SHA-256/AES-256 user
arrives as SHA-1/AES-128-or-whatever-the-box-defaults-to. Re-key SNMPv3 users
on the target and re-select the algorithms explicitly.

`snmp.community`, `snmp.location` and `snmp.contact` round-trip clean on every
cell that populates them (`public`, `Synthetic Lab Rack 7`, `noc@example.net`),
and all three are declared supported on both sides.

## The vyos quote-rewrite hazard, and why it is not this pair's problem

The vyos render replaces embedded double-quotes in free text with apostrophes,
because VyOS rejects embedded quotes in value strings even when escaped. On
pairs where the source wraps descriptions in literal quotes, that shows up as
punctuation drift in `description` — the text survives, its punctuation does
not.

**It is not exercised here.** Measured: 24 populated interface descriptions
across the 5 cells, **0 containing a quote character on the source side**, and
**24 of 24 preserved byte-for-byte** through the round-trip. `interfaces[].description`
is `good` on the measurement, not on the absence of a counter-example — but the
hazard is real for a MikroTik config whose `comment=` text embeds a quote, and
this corpus simply has none.

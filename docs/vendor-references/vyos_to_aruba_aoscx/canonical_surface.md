# VyOS → Aruba AOS-CX: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/vyos__aruba_aoscx.yaml`.

**Source of every number here:** the committed corpus round-tripped by hand —
`vyos.parse()` → `aruba_aoscx.render()` → `aruba_aoscx.parse()` on each of the
13 fixtures — cross-checked against the audit's own `actual_disposition()`
resolution so this file and the ratchet agree by construction. Nothing below
is inferred from the drift shape alone; every loss was re-derived from the
rendered config.

- Fixture cells: **13** (12 real captures + 1 synthetic kitchen sink)
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the codec source, and hand round-trips of the committed
> fixtures. Where a disposition rests on a declaration rather than an observed
> round-trip, the YAML says so explicitly.

## Device-class framing

`vyos` in this corpus is an **OSS router / firewall** — the Vyatta successor,
a Debian-derived NOS whose configuration is a curly-brace `config.boot` tree.
Its device names are Linux names: `eth0`…`eth7`, `lo`, `dum0`, `bond0`, and
`vif` VLAN sub-interfaces modelled as `eth1.100`. Set-form input is converted
to brace form via `_setform_to_brace` before parsing, and `set protocols
bgp|ospf` is shared with Junos rather than being a detection veto.

`aruba_aoscx` is a **campus / DC switch**: `1/1/1` ports, `interface vlan N`
SVIs, `lag N` bundles, `loopback N`.

The shared surface is the **routed edge** — interface names and addressing,
admin state, MTU, static routes, VRF identity, local users, SNMP. There is no
campus L2 surface on the VyOS side to migrate: `vyos` declares
`/vlans/vlan/id` **unsupported**, so it never emits a canonical VLAN record at
all, and the whole switchport-membership surface with it.

## The structural finding — the interface inventory survives whole

| measurement | value |
|---|---|
| source interface records, all 13 cells | **55** |
| records after parse → render → re-parse | **55** |
| cells where the interface name set differs | **0** |
| cells where a record vanishes | **0** |

`eth0`…`eth7`, `lo`, `dum0`, `bond0` and the `eth1.100` / `eth1.200` `vif`
sub-interfaces all survive the AOS-CX render **verbatim** — the render does no
port-name translation on this path, so a VyOS Linux device name is emitted as
an AOS-CX interface name unchanged.

The consequence is the useful one: **every interface loss on this pair is a
genuine per-attribute loss** that stands on its own measurement. Nothing in
the `interfaces[]` block is correlated drift, and every interface sub-field
that survives is recorded `good` rather than dragged down by a vanishing
parent.

The one place a record *does* vanish on this pair is `local_users` — one
account on one cell — and that single disappearance is claimed exactly once,
under `local_users[].name`. See finding 4.

## Per-field measurement (13 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 13 | 0 | 0 |
| domain | 0 | 1 | 12 |
| dns_servers | 0 | 1 | 12 |
| ntp_servers | 0 | 12 | 1 |
| interfaces[].name / description / enabled / mtu / ipv4_addresses / ipv6_addresses | 13 | 0 | 0 |
| interfaces[].interface_type | 0 | 13 | 0 |
| interfaces[].lag_member_of | 0 | 1 | 12 |
| static_routes | 4 | 0 | 9 |
| snmp.community / location / contact / trap_hosts | 4 | 0 | 9 |
| snmp.v3_users | 2 | 2 | 9 |
| lags | 0 | 1 | 12 |
| local_users[].name / role / hashed_password | 12 | 1 | 0 |
| vxlan_vnis[].vni / vlan_id | 3 | 0 | 10 |
| routing_instances[].name | 1 | 0 | 12 |

Fields trivially empty on all 13 cells: `timezone`, `syslog_servers`,
`interfaces[].vrrp_groups`, all six `vlans[].*` keys, `dhcp_servers`,
`radius_servers`, `vxlan_vnis[].mcast_group`, `evpn_type5_routes`,
`routing_instances[].description`, `raw_sections`, `apply_groups`,
`group_content`, `anycast_gateway_mac`.

### Population depth behind the `good` interface sub-fields

| sub-field | populated records | preserved |
|---|---|---|
| `description` | 15 (across 7 cells) | 15 |
| `ipv4_addresses` | 21 addresses | 21 |
| `ipv6_addresses` | 20 addresses | 20 |
| `mtu` | 1 | 1 |
| `enabled=False` (shut ports) | 2 | 2 |

Descriptions round-trip **verbatim**, including the punctuation-heavy
`router1 to swb;swb;et18/1;SWB-ROUTER1;CORE;40000` on
`scottlaird-vyos-parser.conf`. Worth stating because the *reverse* direction
has a known caveat: the **VyOS render** rewrites embedded double quotes into
apostrophes (VyOS rejects embedded quotes in value strings, vyos.dev/T1246),
so a description can come back with altered punctuation on any pair where
`vyos` is the **target**. That caveat does **not** apply here — `vyos` is the
source, the AOS-CX render performs no such rewrite, and 15 of 15 descriptions
came back byte-identical.

## Six findings worth carrying forward

### 1. The management-plane triad is a clean three-way concept drop

`domain`, `dns_servers` and `ntp_servers` are each **supported on the VyOS
side and declared unsupported on the AOS-CX side** — the AOS-CX render emits
no `domain-name`, no `name-server` and no NTP stanza at all. Measured:

| field | cells populated | outcome |
|---|---|---|
| `domain` | 1 | `internal.sigkill.org` → empty |
| `dns_servers` | 1 | all 3 servers → empty list |
| `ntp_servers` | 12 | all servers → empty list, every cell |

`ntp_servers` is the widest single loss on the pair: **12 of 13 cells** carry
NTP and every one of them arrives empty. These are recorded `unsupported`
rather than `lossy` — the records vanish rather than degrade, and a vanished
record is not lossy (#436). Re-author DNS, domain and NTP on the AOS-CX side
by hand; nothing in the migration carries them.

### 2. `interface_type` is *fabricated*, not dropped — and the direction matters

All **55 of 55** interface records drift, uniformly and in one shape:

```
source '' -> target 'ianaift:other'   (55 records, 13 of 13 cells)
```

The VyOS parse leaves `interface_type` empty on every record. The AOS-CX
codec declares that it infers the IANA ifType from the interface-name shape
(`1/1/1` → ethernetCsmacd, `vlan N` → l3ipvlan, `lag N` → ieee8023adLag,
`loopback N` → softwareLoopback). VyOS Linux device names match **none** of
those shapes — not even `lo` and `bond0`, because the render passes the source
names through untranslated — so every record falls through to
`ianaift:other`.

So the target does not lose a hint; it **invents** one. That is still a
fidelity defect (the round-trip does not reproduce the source value) and both
matrices already declare `/interfaces/interface/config/type` lossy, so the
`lossy` disposition is both evidenced and declared. The operational shape is:
every migrated port arrives typed `ianaift:other` regardless of what it
actually is, and any downstream consumer keying off `interface_type` will read
a value the source never asserted.

Separately worth noting for whoever owns the vyos codec: the VyOS matrix's
lossy reason *describes* a name-shape inference (`ethN` → ethernetCsmacd,
`lo`/`dumN` → softwareLoopback, `bondN` → ieee8023adLag), but the measured
parse output is the empty string on all 55 records. That is a codec-side
observation, not a pair-specific fact, and belongs to a codec change rather
than to this file.

### 3. The bundle is renamed, demoted, and its L3 is orphaned

One cell (`kitchen_sink.conf`) carries a LAG. The round-trip:

| | source | target |
|---|---|---|
| `lags[0].name` | `bond0` | `lag 0` |
| `lags[0].mode` | `active` | `static` |
| `lags[0].members` | `eth4`, `eth5` | `eth4`, `eth5` — **intact** |
| `interfaces[].lag_member_of` on eth4/eth5 | `bond0` | `lag 0` |

The bundle **does not vanish** and its membership is fully preserved, which is
why both `lags` and `interfaces[].lag_member_of` are `lossy` here and not
`unsupported` — the #436 rule that forces `unsupported` applies where the
target cannot express the thing at all, and AOS-CX plainly can.

Three mechanisms, all visible in the rendered config:

- **The rename.** The render emits `lag 0` under each member interface; the
  re-parse rebuilds the bundle from those member lines, so it comes back under
  AOS-CX's native `lag <N>` identity rather than the VyOS `bond0` name.
- **The mode demotion.** The render emits **no `interface lag 0` stanza** — only
  the two member `lag 0` lines — so there is nowhere to hang `lacp mode active`
  and the re-parse defaults the bundle to `static`. This is exactly what the
  AOS-CX matrix declares for `/lags/lag/mode`: the mode survives same-vendor,
  where a kind-`lag` interface exists in the tree, and is lost cross-vendor,
  where it does not.
- **The orphaned L3.** `bond0` also survives as an ordinary interface record,
  carrying the bundle's `ip address 10.50.0.1/24` — but it is no longer the
  bundle. The address now sits on a standalone interface named `bond0` while
  the actual aggregation is `lag 0` with no address. That is the shape to
  check before cutover.

`lags` and `interfaces[].lag_member_of` are **one mechanism, not two
independent findings.** Neither is cited as evidence for the other; each is
recorded where it is measured.

### 4. A passwordless account disappears — and the cause is a render/parse asymmetry

12 of 13 cells round-trip their local users with every record intact. On
`houdev_vyos_dhcpv6_pd_client.conf`, the single account `netadmin` — the only
user on that fixture — **vanishes**, and the canonical `local_users` list comes
back empty.

The mechanism is exact and reproducible:

1. The VyOS source account carries **no password hash** (`hashed_password` is
   the empty string; the account is defined with no `encrypted-password`).
2. The AOS-CX render handles that deliberately — it emits
   `user netadmin group admin`, dropping the `password ciphertext` clause,
   because there is no blob to emit.
3. The AOS-CX parser's `_USER_RE` **requires** the tail:
   `^user\s+(\S+)\s+group\s+(\S+)\s+password\s+ciphertext\s+(\S+)`.
   A `user … group …` line with no password clause matches nothing.

So the account is rendered and then cannot be read back. Recorded `lossy`
rather than `unsupported`: AOS-CX declares `/local-users/user/name` supported
and does emit users — 16 of 17 source accounts survive — so this is a partial
record loss inside a concept the target models, not a concept-level gap. Diff
the source account list against the render before cutover; a silently missing
admin account is how a migration locks you out.

`local_users[].role` and `local_users[].hashed_password` are both `good`, and
deliberately so. Both measure what happens to the **value when the record
survives**, and on all 16 surviving accounts the answer is: nothing. Role
survives (`admin` stays `admin`) and the password hash round-trips
byte-identical. The one account that disappears is accounted for **once**,
under `local_users[].name`. Recording the same disappearance three times would
triple-count one loss.

### 5. Every surviving account is silently demoted — on a field with no audit key

Measured on **16 of 16** surviving user records, across 13 of 13 cells:

```
local_users[].privilege_level:  15 -> 1
```

The AOS-CX render writes the canonical role string straight into the AOS-CX
group slot, producing `user vyos group admin …`. The AOS-CX codec's own
declaration names the groups it recognises — *administrators / operators /
auditors / custom* — and maps `administrators` → 15 and everything else → 1.
`admin` is not `administrators`, so every account re-parses at privilege 1.

`privilege_level` has **no key in the audit's field list**, so no disposition
in the YAML claims it. It is recorded here because it is a real, uniform,
security-relevant outcome: after migration every account looks like an
administrator by role string and a minimum-privilege user by number. It is
also *not* evidence for anything else on this pair — it is not cited under
`local_users[].name`, whose loss is the separate record disappearance in
finding 4.

### 6. SNMPv3 keys pass through byte-identical and are still unusable

2 of the 13 cells carry a v3 USM user (one each). Both users **survive** as
records — nothing vanishes — and two fields drop:

| sub-field | outcome |
|---|---|
| `group` (VACM binding) | `default` / `operators` → empty on both cells |
| `engine_id` | hex engineID string → empty on both cells |

Both are declared: AOS-CX states its `snmpv3 user` syntax carries no VACM group
binding, and that engineIDs are device-assigned so no per-user value is
emitted. The rendered line confirms it —
`snmpv3 user <name> auth sha auth-pass ciphertext <blob> priv aes priv-pass
ciphertext <blob>` — with no group and no engineid token.

The part that needs stating precisely: **the auth and privacy key blobs
round-trip byte-identical**, so a mechanical canonical diff sees no drift on
them. That is not portability. Both matrices declare those paths lossy for the
same reason — the VyOS `encrypted-password` blob is salted with
device-specific constants and the AOS-CX `ciphertext` blob is encrypted with
the device key. The value survives the *model*; the credential does not
survive the *move*. Re-key every v3 user on the target.

The declared **cryptographic downgrade** path (SHA-224/256/384/512 → SHA-1,
AES-192/256 or 3DES → AES-128/DES) did **not** fire on this corpus: both source
users already use `sha` / `aes`, and the measured `auth_protocol` and
`priv_protocol` values round-trip unchanged. It is declared by both codecs and
a stronger source would hit it — but it is not something this pair measured,
and the YAML says so.

## VXLAN sub-fields that drift with no audit key

3 of 13 cells carry exactly one VNI record each. The two keyed sub-fields are
clean — `vni` (10, 10, 10100) and `vlan_id` (10, 10, 1912) are preserved on all
three, and the render emits the binding explicitly as
`interface vxlan 1 / vni <N> / vlan <V>`.

Two *unkeyed* sub-fields do drift, recorded here so the measurement is not
lost:

| sub-field | records | shape |
|---|---|---|
| `flood_list` | 3 | head-end replication VTEP list → empty |
| `udp_port` | 2 | `8472` (legacy) → `4789` (IANA default) |

Both are declared lossy by the AOS-CX matrix: the render emits the VTEP
`source ip` and the per-VNI `vni`/`vlan` bindings but neither a BUM-replication
underlay nor a UDP-port override. No key in the audit's field list covers
either, so no YAML disposition claims them; a source relying on the legacy
8472 port or on static flood VTEPs must re-author both on the target.

## Source-side gaps vs target-side drops

`vyos` declares these **unsupported at the exact path**, so as a *source* it
never emits them and there is nothing for AOS-CX to lose:

`/vlans/vlan/id` · `/interfaces/interface/{switchport-mode,access-vlan,trunk-allowed-vlans,trunk-native-vlan,voice-vlan}`
· `/interfaces/interface/dot1q-vlan` · `/anycast-gateway-mac` ·
`/interfaces/interface/ipv4/address/virtual-gateway-address` ·
`/vlans/vlan/ipv4/address/{secondary-ip,virtual-gateway-address,virtual-gateway-mac}`

These are recorded `not_applicable`, not `unsupported`, and the distinction is
operational. For most of them **aruba_aoscx declares the field supported** —
`/vlans/vlan/{id,name,description,tagged-ports,untagged-ports}`, the whole
switchport surface, and `/anycast-gateway-mac`. Re-authoring a campus VLAN
database, port membership or an anycast gateway on the AOS-CX side will stick;
the migration simply has nothing to hand it, because a VyOS router has no
canonical VLAN records to give.

The **symmetric** gaps — where *both* matrices declare unsupported — are
recorded `unsupported` instead: `/system/timezone`, `/system/syslog-server`,
`/dhcp-servers/pool`, `/radius-servers/server/{host,key}`, and the entire
`/interfaces/interface/vrrp-groups/group/*` subtree. VRRP is the one to
notice: `vyos` does not model VRRP at all and AOS-CX VRRP is an explicitly
deferred phase, so first-hop redundancy neither leaves the source nor lands on
the target. Re-authoring it on AOS-CX will **not** stick in this codec
generation.

`snmp.trap_hosts` deserves its own line. It measures preserved on the 4 cells
that carry an SNMP block — but only empty-to-empty: **neither codec contains a
single line of trap-host code**. `vyos` parses no `trap-target` grammar, and
`aruba_aoscx` declares `/snmp/trap-host` unsupported and emits none. So the
`good` disposition is honest about what it observed and is not a claim that
trap receivers would migrate. A source that did carry them would lose them.

## Two `not_applicable` entries that rest on declarations only

- **`vxlan_vnis[].mcast_group`** — `vyos` declares `/vxlan-vnis/mcast-group`
  *supported*, so unlike the entries above this is not a source-side inability;
  it is simply unexercised. No committed cell sets a multicast group (all three
  VNI records use head-end replication instead), so there is no round-trip to
  point at. AOS-CX declares the path lossy on its own merits.
- **`routing_instances[].description`** — `vyos` supports only
  `/routing-instances/instance/name` and declares no description path, so the
  single VRF on the corpus (`BLUE`, on `kitchen_sink.conf`) carries an empty
  description and there is nothing to lose. AOS-CX declares the path
  unsupported anyway — its `vrf <name>` stanza is a bare name in v1 — so
  re-authoring a VRF description on the target will *not* stick either.

## Credential material

No hash body, ciphertext blob or passphrase is reproduced in this file or in
the expectation YAML — only the crypt-scheme marker and the token length are
described, and the probe used to derive these findings redacted blobs before
printing. Per `AGENTS.md`, password hashes are operator-traceable even when
they are hashes, and a document that quotes the value it describes defeats its
own redaction.

## One drift-shape reading that is wrong

A mechanical "does the target side differ?" pass over `interfaces[]` reports 55
of 55 records drifting and invites the conclusion that the interface surface is
broken. It is not. The inventory is whole, the names are whole, and every
address, description, MTU and admin-state value survives. What drifts on all 55
is a single attribute — `interface_type` — and it drifts because the target
*added* a value the source never carried.

Read the other way round, the pair's real exposures are narrow and specific:
the management-plane triad vanishes, the LAG is renamed and its L3 orphaned,
one passwordless account disappears, and every surviving account is demoted to
privilege 1.

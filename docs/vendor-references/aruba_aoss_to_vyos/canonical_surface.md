# Aruba AOS-S → VyOS: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/aruba_aoss__vyos.yaml`.

**Source of every number here:** an in-process `aruba_aoss.parse()` →
`vyos.render()` → `vyos.parse()` pass over the committed corpus, one cell at a
time. Per-key dispositions were resolved through the audit's own
`actual_disposition()` — including its STRUCTURAL_ONLY collapse — rather than
inferred from the drift shape, so this file and the ratchet agree by
construction. Every loss recorded below was re-derived by hand from the
rendered VyOS config, so no claim rests on a count comparison alone.

- Fixture cells: **7** (6 real AOS-S captures + the synthetic kitchen sink)
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the measured round-trips, and reading the rendered VyOS
> configs. Where a disposition rests on a declaration rather than an observed
> round-trip, the YAML says so explicitly.

## Device-class framing

`aruba_aoss` in this corpus is a **campus access switch** — HPE/Aruba 2920,
2930F, 2930M, 5406R and an Aruba Central-rendered 5-member stack. Its centre of
gravity is the VLAN database: 32 VLAN records across the 7 cells, carrying 357
port-membership entries and 18 SVI addresses. Ports are named `1/25`, `A1`,
`23`; trunks are named `trk1` / `Trk1`.

`vyos` is a **Linux software router**. It has no VLAN database at all —
802.1Q is `vif <vid>` sub-interfaces on a device — and its interface names are
kernel device names (`eth0`, `bond0`, `lo`, `dum0`).

The shared surface is therefore the **routed edge**: hostname, DNS, NTP,
interface addressing / description / admin state, static routes, SNMP and local
user identity. The campus L2 surface has nowhere to land.

## The structural finding — the interface list GROWS

Most pairs in this mesh lose interface records. This one gains them, and the
distinction changes what the `interfaces[].*` keys mean.

| measurement | value |
|---|---|
| source interface records, all 7 cells | **85** |
| records after parse → render → re-parse | **88** |
| source interface names missing from the target | **0** |
| cells where the record count differs | **2** of 7 |

Every AOS-S port survives with its name intact. The extra three records are
**phantom LAG stanzas**: `trk1` on `aruba_central_5memberstack_rendered.cfg`,
`trk1` + `trk2` on `kitchen_sink.cfg` (see "The LAG surface" below).

Because the record count moves on those 2 cells, the audit routes the whole
`interfaces` cell to STRUCTURAL_ONLY there and lets `interfaces[].name` carry
the signal. That is why several interface sub-fields below are recorded `good`
with a measurement rather than a loss: their drift on those cells is the parent
count moving, not the attribute failing, and the loss is recorded once where it
is actually caused.

## Per-field measurement (7 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 7 | 0 | 0 |
| dns_servers | 3 | 0 | 4 |
| ntp_servers | 1 | 0 | 6 |
| interfaces (record set) | 5 | 2 | 0 |
| vlans | 0 | 7 | 0 |
| static_routes | 5 | 0 | 2 |
| snmp | 4 | 2 | 1 |
| lags | 0 | 2 | 5 |
| local_users | 0 | 3 | 4 |
| radius_servers | 0 | 1 | 6 |

Fields trivially empty on all 7 cells: `domain`, `timezone`, `syslog_servers`,
`dhcp_servers`, all three `vxlan_vnis[].*` keys, `evpn_type5_routes`, both
`routing_instances[].*` keys, `raw_sections`, `apply_groups`, `group_content`,
`anycast_gateway_mac`.

### Per-record detail behind the interface block

Matched by name across all 85 source records:

| sub-field | populated on | records drifted | shape |
|---|---|---|---|
| `interface_type` | 85 | **85** | value → empty string |
| `lag_member_of` | 4 | **4** | value → null |
| `description` | 39 | 0 | — |
| `enabled` | 3 admin-down | 0 | — |
| `ipv4_addresses` | 20 (20 addresses) | 0 | — |
| `ipv6_addresses` | 2 (3 addresses) | 0 | — |
| `mtu` | **0** | 0 | never populated on this corpus |
| `vrrp_groups` | **0** | 0 | never populated on this corpus |

`interface_type` is a clean sweep — **65** `ianaift:ethernetCsmacd`, **18**
`ianaift:l3ipvlan` and **2** `ianaift:ieee8023adLag` all drop to the empty
string, and **zero** records keep it. The VyOS parser re-derives the type from
the interface-name shape (`ethN` → ethernetCsmacd, `lo`/`dumN` →
softwareLoopback, `bondN` → ieee8023adLag), and no AOS-S name — `1/25`, `A1`,
`Vlan10` — matches any of those patterns, so nothing is recovered. Both
matrices already declare `/interfaces/interface/config/type` lossy.

The IPv6 result is worth stating because it is narrow but clean: the two
kitchen-sink uplinks carry three addresses between them, including a
`fe80::/64` link-local whose `scope` field survives — `vyos` declares
`/interfaces/interface/ipv6/address/scope` supported and it holds.

## Source-side gaps vs target-side drops

`aruba_aoss` declares these **unsupported at the exact path**, so as a *source*
it never emits them and there is nothing for VyOS to lose:

`/system/domain` · `/dhcp-servers/pool` · `/vxlan-vnis/{vni,source-interface,udp-port}` ·
`/routing-instances/instance` · `/routing-instances/instance/instance-type` ·
`/anycast-gateway-mac`

Most of these are recorded `not_applicable`, not `unsupported`, and the
distinction is operational: `vyos` declares `/system/domain`,
`/routing-instances/instance/name` and `/vxlan-vnis/vni` **supported**, so
re-authoring a domain name, a VRF or a VXLAN VNI on the VyOS side will stick.
The migration is not what prevents them; the AOS-S source simply never carried
them.

Four gaps are **symmetric** — both matrices declare the same path unsupported —
and those are recorded `unsupported`: `/system/timezone`,
`/system/syslog-server`, `/dhcp-servers/pool` and `/anycast-gateway-mac`.

`evpn_type5_routes` is declared by neither codec and populated by neither side
on any cell. A campus access switch has no EVPN control plane to migrate.

## Five findings worth carrying forward

### 1. The VLAN database is a total drop — but the SVI L3 is not

All 7 cells populate `vlans`. **32 VLAN records in, 0 out.**

| what the VLAN records carried | count |
|---|---|
| records | 32 |
| with a name | 29 |
| with an SVI IPv4 address | 18 |
| untagged-port entries | 196 |
| tagged-port entries | 161 |
| with a description | 0 |

The rendered VyOS config contains no VLAN stanza of any kind. `vyos` declares
`/vlans/vlan/id` **unsupported** and states the cause plainly: VyOS has no
top-level VLAN database, and 802.1Q VLANs are modelled as `vif <vid>`
sub-interfaces instead.

The important half of this finding is what *does* survive. The AOS-S parser
absorbs each SVI into a sibling `Vlan<N>` interface record, and those records
round-trip: **18 of 18** SVI addresses were found intact on a surviving
`Vlan<N>` interface after the round-trip, zero missing. So the L3 addressing
migrates; the VLAN *record* and its 357 port-membership entries do not.

Because the record vanishes wholesale, the disappearance is recorded **once**,
on `vlans[].id`, as `unsupported` (a vanished record is not lossy — #436). The
five sibling keys (`name`, `ipv4_addresses`, `untagged_ports`, `tagged_ports`,
`description`) are recorded `good`: they can only drift as a consequence of that
one event, they carry no independent measurement, and recording the same
disappearance six times would report one loss as six.

Port membership is the part an operator must re-author by hand. VyOS expresses
it as bridge members and `vif` sub-interfaces, which is a different model, not a
narrower one.

### 2. The LAG surface drops — and it is a name-shape artifact, not a VyOS gap

On the two cells that carry trunks, **3 LAG records become 0** and the member
ports come back with `lag_member_of` null. The rendered config shows exactly
what happened:

```
    ethernet Trk1 {
        description "stack-uplink-A"
    }
    ethernet trk1 {
    }
```

The mechanism is in `netcanon/migration/codecs/vyos/render.py`:
`_vyos_type_and_name()` maps a name to `bonding <name>` **only** when it matches
`^bond\d+$`, and `_bond_extra()` — which emits `mode 802.3ad` and the
`member { interface … }` list — is called only when that block type is
`bonding`. An AOS-S trunk is called `trk1`, so it falls through to
`ethernet trk1`, an empty stanza with no mode and no members. Re-parsing that
yields a plain interface record and no LAG at all. One mechanism, three
signals: the vanished LAG record, the phantom interface record, and the null
`lag_member_of`.

**This is recoverable, and it was verified rather than assumed.** Running the
standard cross-vendor port-name step first:

```python
translate_port_names(intent, get_codec("aruba_aoss"), get_codec("vyos"))
```

renames `trk1 → bond1` and `trk2 → bond2`, after which the render emits
`bonding bond1 { mode 802.3ad member { interface eth23 … } }` and **both LAG
records survive the round-trip with their members and mode intact**. The mesh
measures the bare render path, which skips that step by design.

That is why `lags` is recorded `lossy` and not `unsupported`, despite the
records vanishing on the measured path. `unsupported` asserts the target cannot
express the concept; `vyos` declares `/lags/lag/name` and `/lags/lag/members`
**supported**, and the proof above shows the renderer honours them. Calling it
`unsupported` would block a migration that works.

`interfaces[].lag_member_of` is recorded `good`, deliberately. Its 4 drifting
records sit on exactly the 2 cells where the interface count moves, so the
audit attributes that signal to `interfaces[].name`; a loss declared here could
never be evidenced. The membership loss is real and it is recorded — under
`lags`, where it is caused.

### 3. Every local user arrives as an administrator

Names and credentials are clean; authority is not.

| measurement (5 user records across 3 cells) | result |
|---|---|
| `name` preserved | **5 / 5** |
| `hashed_password` byte-identical | **5 / 5** |
| `role` preserved | **0 / 5** |
| `privilege_level` preserved | 4 / 5 |

The role transitions are `manager → admin` ×4 and **`operator → admin` ×1**,
and that last one also moves `privilege_level` from **1 to 15**.

The cause is visible in the render: the VyOS `system login` block emits only
`user <name> { authentication { encrypted-password … } }` — no role, no level.
The VyOS parser then assigns every login user `role="admin"`,
`privilege_level=15`
(`netcanon/migration/codecs/vyos/parse.py`, the `CanonicalLocalUser`
construction). `vyos` declares `/local-users/user/privilege-level` lossy and
documents exactly this mapping.

The direction matters more than the count: this **fails open**. A read-only
AOS-S `operator` account becomes a full VyOS administrator. It is recorded
`lossy` rather than `unsupported` because the account record and its credential
survive — it is the authority attached to them that is wrong — but a `lossy`
warning is the floor, not the ceiling, of what this deserves. Re-assert every
account's authority on the target before cutover.

### 4. The VyOS quote rewrite alters punctuation in free text

`snmp.contact` drifts on exactly one cell,
`hpe_community_2920_wb1608_dhcp_snooping.cfg`, where the source line is a
combined AOS-S `snmp-server contact "…" location "…"`. The parsed contact
string contains two embedded double-quote characters, and the VyOS render
replaces both with apostrophes, emitting a warning as it does:

> vyos render: replaced 2 embedded double-quote(s) with apostrophes in a
> free-text value — VyOS rejects embedded quotes in value strings even when
> escaped (vyos.dev/T1246)

Be precise about what was lost: **the text survives, its punctuation does
not.** Every other character round-trips; only the two `"` become `'`. This is
a rendering-legality transform, not a content loss, and it is recorded `lossy`
on that basis.

Worth stating because the opposite is easy to assume: **no interface
description was affected.** 39 populated descriptions across the corpus, zero
drift. The quote rewrite fires only where the source text actually contains a
double-quote, which on this corpus is one SNMP contact string.

### 5. SNMP trap destinations have no emit path at all

3 trap-host records across 2 cells become **0**. The rendered `service snmp`
block carries `community`, `contact`, `location` and the `v3` users — and no
trap target of any kind.

`aruba_aoss` declares `/snmp/trap-host` **supported**. `vyos` declares
**nothing** for it: not supported, not lossy, not unsupported. That is a matrix
under-declaration on the target side — the same shape as the standing
`arista_eos` `/lags/lag` observation — and it belongs to a codec change rather
than to this file. Recorded `unsupported` here because the records vanish and
the target has no grammar they land in (#436).

`snmp.v3_users` is a different and much narrower story: both users on
`kitchen_sink.cfg` survive with names, group and auth protocol intact, and the
single drift is `monitor-usr`'s `priv_protocol` collapsing **`aes128` → `aes`**.
`vyos` declares `/snmp/v3-user/priv-protocol` lossy and names the cause: its
`privacy type` node renders only bare `des` / `aes`, so AES key-length variants
lose their exact strength. It is a cryptographic-strength marker downgrade, not
a lost user, so it is `lossy`.

## Credential material

No hash body, passphrase or community-string secret is reproduced in this file
or in the expectation YAML — only the scheme marker and the length are
described. Per `AGENTS.md`, password hashes are operator-traceable even when
they are hashes, and a document that quotes the value it describes defeats its
own redaction.

Two shape observations that do not require quoting anything:

- Of the 5 local-user credentials on this corpus, 4 carry a `sha1:`-scheme
  marker (45 characters) and 1 carries a **`plaintext:`** scheme marker (31
  characters). All 5 round-trip byte-identical.
- The `plaintext:`-scheme credential is written verbatim into the rendered
  VyOS `authentication { encrypted-password … }` node — a node whose name
  promises a hash. Nothing is lost, which is why `local_users[].hashed_password`
  is `good`, but a cleartext secret lands in the target config and should be
  re-set rather than migrated.

The SNMPv3 auth and privacy passphrases round-trip verbatim as opaque blobs
(31 characters each, unchanged). The mesh comparator strips those two
sub-fields as target-determined cosmetics, so they do not contribute to the
`snmp.v3_users` drift either way.

## Two drift-shape readings that are wrong

**"`lags` is a total drop, so VyOS cannot do LACP."** It can, and the codec
renders it correctly. The drop is caused by the LAG's *name* not matching
`^bond\d+$` on the untranslated path — see finding 2, including the
reproduction that makes both LAGs survive.

**"`vlans[].untagged_ports` lost 196 entries, so it is a lossy field."** The
entries are gone, but not independently: the VLAN *record* vanished and took
every sub-field with it. That is one event, recorded once on `vlans[].id`.
Counting it again on each of the five sibling keys would turn a single
structural drop into six findings and would fail the per-pair ratchet by
construction, because none of those five can be evidenced separately.

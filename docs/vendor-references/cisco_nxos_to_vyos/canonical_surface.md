# NX-OS → VyOS: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/cisco_nxos__vyos.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key
dispositions were resolved through the audit's own `actual_disposition()` rather
than inferred from the drift shape, so this file and the ratchet agree by
construction. Every loss recorded was additionally re-derived by hand —
`cisco_nxos.parse()` → `vyos.render()` → `vyos.parse()` on each of the 13
fixtures — so no claim below rests on the drift shape alone.

- Fixture cells: **13** (12 real captures + the synthetic kitchen sink)
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the measured mesh run, and hand round-trips of the committed
> fixtures. Where a disposition rests on a declaration rather than an observed
> round-trip, the YAML says so explicitly.

## Device-class framing

`cisco_nxos` in this corpus is a **VXLAN/EVPN datacentre leaf-spine switch**:
`Ethernet1/N` ports, `port-channel` bundles, a VLAN database with `Vlan<N>`
SVIs, HSRP first-hop redundancy, distributed anycast gateway
(`fabric forwarding mode anycast-gateway` plus a chassis-wide anycast gateway
MAC), `nve1` VNI bindings and per-tenant VRFs with RD / route-targets.
`vyos` is a **Linux software router / firewall appliance**.

There is no switch inside VyOS: no top-level VLAN database, no `switchport`
mode, no VARP / distributed-anycast grammar, no VRRP in this codec, and no
bundle it can name from an NX-OS `port-channel`. The pair therefore splits
cleanly, and the split is the whole finding.

- The **routed edge and management plane migrate intact** — interface identity,
  IPv4/IPv6 addressing, MTU, admin state, descriptions, per-interface VRF
  binding, static-route destinations and next-hops, hostname, domain, NTP,
  SNMP scalars, user identity and the stored password hash.
- The **fabric and switching planes do not migrate at all** — the VLAN
  database, every LAG and its membership pointers, HSRP, the anycast gateway
  surface, the VNI-to-VLAN binding, the VRF's RD / route-target / L3VNI
  plumbing, SNMP trap destinations and the syslog target.

## The structural finding — the interface list survives, the VLAN list does not

Anyone arriving here from `aruba_aoscx_to_arista_eos/canonical_surface.md`
should not assume that pair's shape. There the interface inventory shrank and
dragged every `interfaces[].*` sub-field into a loss.

**Here the interface inventory is fully preserved.**

| measurement | value |
|---|---|
| source interface records, all 13 cells | **1102** |
| records after parse → render → re-parse | **1102** |
| cells where the interface name set differs | **0** |

`Ethernet1/1`, `port-channel1`, `loopback0`, `mgmt0` and the `Vlan<N>` SVIs all
come back with their names intact. The consequence is the useful one: **every
interface loss on this pair is a genuine per-attribute loss** that stands on
its own measurement, and every interface sub-field that survives is recorded
`good` rather than dragged down by a vanishing parent.

**The list that vanishes is `vlans`** — 84 records across 13 of 13 cells become
**0**. That single structural loss is claimed exactly ONCE, at `vlans[].id`.
The five sibling `vlans[].*` keys are recorded `good` so one drop is counted
once; a loss on any of them would be correlated drift from the same event and
could never be evidenced independently.

**Pair-wide caveat, stated once:** the fidelity harness scores canonical
PRESERVATION, not target-syntax VALIDITY. The vyos render emits NX-OS names
verbatim (`ethernet Ethernet1/1`, `ethernet port-channel1`, `ethernet Vlan10`),
which are not loadable VyOS interface names. `good` means "the canonical value
survived the round-trip", not "the rendered config boots".

## Per-field measurement (13 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 13 | 0 | 0 |
| domain | 2 | 0 | 11 |
| ntp_servers | 1 | 0 | 12 |
| syslog_servers | 0 | 1 | 12 |
| interfaces[].name / description / enabled / mtu / ipv6_addresses | 13 | 0 | 0 |
| interfaces[].ipv4_addresses | 9 | 4 | 0 |
| interfaces[].interface_type | 0 | 13 | 0 |
| interfaces[].lag_member_of | 0 | 5 | 8 |
| interfaces[].vrrp_groups | 0 | 4 | 9 |
| vlans[].* | 0 | 13 | 0 |
| static_routes | 4 | 4 | 5 |
| snmp.community / location / contact | 11 | 0 | 2 |
| snmp.trap_hosts | 9 | 2 | 2 |
| snmp.v3_users | 7 | 4 | 2 |
| lags | 0 | 5 | 8 |
| local_users[].name / hashed_password | 9 | 0 | 4 |
| local_users[].role | 0 | 9 | 4 |
| vxlan_vnis[].vni | 8 | 0 | 5 |
| vxlan_vnis[].vlan_id | 0 | 8 | 5 |
| vxlan_vnis[].mcast_group | 2 | 0 | 11 |
| routing_instances[].name | 12 | 0 | 1 |
| routing_instances[].description | 0 | 1 | 12 |
| anycast_gateway_mac | 0 | 7 | 6 |

Fields trivially empty on all 13 cells: `dns_servers`, `timezone`,
`dhcp_servers`, `radius_servers`, `evpn_type5_routes`, `raw_sections`,
`apply_groups`, `group_content`.

### Per-record detail behind the interface drift

| sub-field | records affected | of total | shape |
|---|---|---|---|
| `interface_type` | 1102 | 1102 | value → empty string |
| `lag_member_of` | 13 | 13 populated | value → null |
| `ipv4_addresses` (`virtual_gateway_address`) | 7 | 7 populated | value → empty string |
| `vrrp_groups` | 4 | 4 populated | group record → dropped |
| `name` / `description` / `enabled` / `mtu` / `ipv6_addresses` | 0 | 1102 | — |

Two further address records (`loopback0` on
`akarneliuk_evpn_vxlan_mcast_leaf_c1l1_nxos939.txt` and on
`busterswt_spine_leaf_xk32_1_nxos9312.txt`) come back with `is_secondary`
flipped `True` → `False`. The harness strips `is_secondary` as a
target-determined rendering artifact (`_COSMETIC_LIST_SUBFIELDS` in
`tools/run_full_mesh.py`), so it is **not** counted as drift and is **not**
cited as evidence anywhere. It is recorded here so the observation is not lost.

### Why every interface loses its type, loopbacks included

`interface_type` breaks down by source type: **1053** `ianaift:ethernetCsmacd`,
**29** `ianaift:l3ipvlan`, **12** `ianaift:softwareLoopback` and **8**
`ianaift:ieee8023adLag`. **None survive** — 0 of 1102.

This is stronger than the IOS-XR → EOS pair, where loopbacks kept their type.
The vyos matrix states the mechanism: VyOS declares no IANA ifType, so the
codec infers it from the interface-**name shape** — `ethN` → ethernetCsmacd,
`lo` / `dumN` → softwareLoopback, `bondN` → ieee8023adLag. NX-OS names match
none of those shapes: `Ethernet1/1` is not `ethN`, and `loopback0` is not `lo`.
Both matrices already declare `/interfaces/interface/config/type` lossy.

## Source-side gaps vs target-side drops

`cisco_nxos` is a wide source: 45 supported paths, and of its 16 unsupported
ones only four touch a canonical key audited here
(`/system/timezone`, `/dhcp-servers/pool`, `/radius-servers/server/host`,
`/radius-servers/server/key` — the rest are Tier-3 protocol/ACL/NAT surfaces
outside `CanonicalIntent`, plus `/interfaces/interface/voice-vlan` and
`/interfaces/interface/ipv6/address/virtual-gateway-address`). Almost every
loss on this pair is therefore a **target-side drop**, not a source-side gap.
That is the opposite of the IOS-XR pairs, where most `not_applicable` entries
came from the source never emitting the field.

Four keys are genuinely symmetric gaps — **both** matrices declare the path
unsupported, so neither side carries the concept:

`/system/timezone` · `/dhcp-servers/pool` ·
`/radius-servers/server/host` · `/radius-servers/server/key`

Those are recorded `unsupported`. Four more are recorded `not_applicable`
because the source emitted nothing on any of the 13 cells and the target
declares no path either way: `evpn_type5_routes`, `raw_sections`,
`apply_groups`, `group_content`.

### Two matrix declarations this pair contradicts

Both are standing observations about the codecs, not pair-specific facts, and
both belong to a codec change rather than to this file.

1. **`/lags/lag/name`, `/lags/lag/members` and
   `/interfaces/interface/lag-member-of` are declared SUPPORTED by vyos**,
   while 8 of 8 LAG records and 13 of 13 membership pointers are dropped on
   this pair. The declaration is honest for a same-vendor round-trip, where
   LAGs are already named `bondN`; it is silently wrong for any source whose
   LAG names have another shape. (The same observation is recorded on
   `aruba_aoscx__vyos.yaml`, independently measured.)
2. **`/snmp/trap-host` is declared by neither side of the target matrix** —
   not supported, not lossy, not unsupported — while every trap destination is
   dropped on render. `cisco_nxos` declares the path SUPPORTED and does emit
   one. This is a target under-declaration.

## Findings worth carrying forward

### 1. The VLAN database is a total concept drop, and the declared mitigation never fires

84 VLAN records across 13 of 13 cells become **0**. vyos declares
`/vlans/vlan/id` UNSUPPORTED and gives the reason: VyOS has no top-level VLAN
database, 802.1Q VLANs are modelled as `vif <vid>` sub-interfaces (rendered as
`ethN.<vid>` interfaces), "which ARE supported".

**On this pair that mitigation does not happen.** `0` of the 13 rendered
configs contains a `vif` node. NX-OS expresses VLANs as a database plus
per-port `switchport` membership, and none of that converts into a routed
sub-interface. The per-port L2 attributes VLAN membership is rebuilt from are
dropped too — `switchport_mode` on 29 records, `access_vlan` on 13,
`trunk_allowed_vlans` on 10, `trunk_native_vlan` on 4, each declared
unsupported by vyos. Those are the same structural event, not extra evidence.

What *does* survive is the VLAN **SVI's layer-3**: `Vlan10` arrives as an
interface record carrying its address, description and VRF binding. The VLAN's
identity, name, port membership and its place in the bridging domain do not.
Rebuild the VLANs on the target as `vif` sub-interfaces plus a bridge.

### 2. The LAG surface is a total concept drop

8 LAG records across the 5 bundle-carrying cells become **0**, and no rendered
config contains a `bonding` block. All 13 interface records with a
`lag_member_of` value come back null while the member ports survive standalone
— the dangerous shape, because the ports come up individually rather than
bundled.

The mechanism, read out of `netcanon/migration/codecs/vyos/render.py`:
`_vyos_type_and_name` maps a canonical interface name to its VyOS block type —
`lo` → `loopback`, `dumN` → `dummy`, `bondN` → `bonding`, and **anything else →
`ethernet <name>`**. The bond-specific emit path (mode plus member list) runs
only for the `bonding` type. NX-OS bundles are named `port-channel1` …
`port-channelN`; none matches `bondN`. Each renders as
`ethernet port-channel1 { description "…" }` and re-parses as a plain
interface.

`lags` and `interfaces[].lag_member_of` are **one mechanism measured in two
places**. Neither is cited as evidence for the other; each is recorded where it
is measured. Both are `unsupported`, since a vanished record is not lossy
(#436).

### 3. Local-user roles collapse to `admin` — a fail-open

10 user records across 9 cells. Names survive 10 of 10. The stored password
hash survives 10 of 10, byte-for-byte. **The role drifts on 10 of 10**: nine
`network-admin` → `admin`, and one `network-operator` → `admin`.

The mechanism is a constant, not a mapping table. The vyos render emits
`user <name> { authentication { encrypted-password … } }` and no role or level
at all, and `netcanon/migration/codecs/vyos/parse.py` assigns every login user
`role="admin"` and `privilege_level=15` unconditionally.

The consequence is the finding to act on: the corpus's one read-only account
(`netops` on `kitchen_sink.cfg`) goes in as `network-operator` at privilege
level 1 and comes back as `admin` at privilege level 15. Role and privilege
level are ONE mechanism; the privilege-level side is not cited as separate
evidence.

Recorded `lossy`, not `unsupported`: the record survives with its name and its
secret, and only the value collapses. Diff the source account list against the
render before cutover and re-apply least privilege by hand — a read-only
operator silently promoted to administrator is a worse outcome than an account
that fails to arrive.

`/local-users/user/role` is declared supported by **both** matrices while
drifting on 10 of 10 records; the adjacent `/local-users/user/privilege-level`
IS declared lossy on both sides, with vyos's reason describing the same
collapse. The role path is under-declared. Independently reproduced here and
on `aruba_aoscx__vyos.yaml`.

### 4. Credentials survive; the SNMPv3 privacy surface does not

`local_users[].hashed_password` is preserved on **10 of 10** records. Every
canonical value is the NX-OS type marker `5 ` followed by a `$5$` crypt string,
and the render drops the whole thing verbatim into the VyOS
`system login user … authentication encrypted-password` leaf. This is the rare
pair where the stored secret actually migrates.

It is also the sharpest illustration of *preservation is not validity*: the
canonical round-trip is clean — which is what the audit measures — but the
rendered leaf still carries the leading `5 ` type marker, which a VyOS box
would not read as a crypt hash. Strip it before loading the render.

SNMPv3 is the opposite. The v3 user records themselves survive (1 → 1 on ten
cells, 2 → 2 on one), but:

- **`priv_protocol` `aes128` → `aes`** on 3 cells — the AES key-length
  variant is gone, exactly as vyos's `LossyPath` reason predicts.
- **`engine_id` `""` → a synthesised value** on 1 cell
  (`nautobot_gc_nxos_snmp_spine01_nxos933.txt`) — vyos carries one
  config-wide engineID and maps it onto every user, so a source that set none
  comes back with one.
- Separately, and **deliberately not counted**: the privacy passphrase goes
  from a 34-character opaque value to empty on 8 records. The harness blanks
  `auth_passphrase` / `priv_passphrase` on both sides before comparing
  (`_COSMETIC_SNMP_V3_SUBFIELDS`), so this is not evidence for the
  disposition — but it is the reason the operational advice is *re-key
  SNMPv3 on the target*, not *check the protocol*.

### 5. Two silent routing hazards

**Static routes lose their VRF.** All 13 routes across the 8 populated cells
survive with destination and next-hop intact — a mechanical "did the records
match?" pass calls this field a total drop and is wrong. What actually happens
is that 6 routes across 4 cells go from a named VRF (`management`, `TENANT-A`)
to the empty string, and the render places them under the global
`protocols static`. A default route deliberately scoped to the out-of-band
management VRF re-appears in the global table. That is not a lost route; it is
a route pointed somewhere else. vyos declares `/routing/static-route/vrf`
UNSUPPORTED — per-VRF static routes are deferred past its Phase-3 VRF wire-up,
while the `vrf name` instances themselves are supported.

**The VNI-to-VLAN binding is rewritten, not dropped.** All 17 VXLAN records
across 8 cells keep their VNI (17 of 17) and their multicast group (4 of 4 on
the 2 cells that set one), but **every one** of the 17 comes back with a
different `vlan_id`: `10` → `1822`, `20` → `1832`, `1001` → `321`, `777` →
`2521`, and so on. VyOS models one VNI per `vxlan vxlanN` netdev with no VLAN
on the device, so the required canonical `vlan_id` is synthesised on re-parse.
A field that silently returns a *plausible wrong number* is more dangerous than
one that returns empty, because nothing downstream flags it.

## One drift-shape reading that is wrong

A mechanical "is the target side empty?" pass over this pair reports
`routing_instances` as a **total drop**. It is not. All 19 VRF records across
the 12 cells that carry them survive with their names — `TENANT-A`,
`management`, `CUST1`, `PUBLIC`, `TENANT-777`, `VRF_SERVICE_CUST_1` and
`VRF_SERVICE_CUST_2` all round-trip, rendered as
`vrf { name <X> { table <n> } }`.

What actually empties is the VRF's control-plane plumbing: `l3_vni`,
`route_distinguisher`, `rt_imports` and `rt_exports` on 7 records, and
`description` on the 2 records of the single cell that sets one
(`kitchen_sink.cfg`: `out-of-band management` and
`tenant a routing instance`, both → empty). So `routing_instances[].name` is
`good`, `routing_instances[].description` is `lossy`, and the "total drop"
reading is an artifact of reading sub-fields emptying as records vanishing.

It still matters: on a multi-tenant leaf the VRF description is usually the
only place the tenant name is written down, and the RD / route-target set is
what makes the tenant's EVPN routes reachable at all.

## Credential material

No hash body, passphrase or vendor ciphertext blob is reproduced in this file
or in the expectation YAML — only the crypt-scheme family, the field length and
the drift shape are described. Per `AGENTS.md`, password hashes are
operator-traceable even when they are hashes, and a document that quotes the
value it describes defeats its own redaction.

## Free-text punctuation on a VyOS target — declared, not observed

The vyos render replaces an embedded double-quote in a free-text value with an
apostrophe, because VyOS rejects embedded quotes in value strings even when
backslash-escaped (`vyos.dev/T1246`); `_q()` in the render logs a warning when
a substitution actually happens. That would alter a description's punctuation
while keeping its text.

**It never fires on this pair.** 33 interface descriptions are populated across
the corpus and **0** of them contain a double-quote character, so all 33
round-trip byte-identical. The behaviour is recorded here so a future reader
does not mistake it for an unmeasured risk, and so that a description drift on
some *other* vyos-target pair is checked against this cause first — the text
survives, its punctuation does not, and those are different claims.

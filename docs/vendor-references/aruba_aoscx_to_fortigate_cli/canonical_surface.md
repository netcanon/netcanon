# AOS-CX → FortiGate CLI: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/aruba_aoscx__fortigate_cli.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`, plus
direct `aruba_aoscx.parse → fortigate_cli.render → fortigate_cli.parse`
round-trips over all 7 cells for the calls the drift shape alone could not
settle. Per-key dispositions were resolved through the audit's own
`actual_disposition()` rather than inferred from the drift shape, so this file
and the ratchet agree by construction.

- Fixture cells: **7**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations and the measured mesh run. Where a disposition rests on a
> declaration rather than an observed round-trip, the YAML says so explicitly.

## Device-class framing

`aruba_aoscx` in this corpus is a **campus / small-DC access-aggregation
switch** — every cell is an L2 switch with VLANs, SVIs, LACP uplinks and a
switchport-per-port model. `fortigate_cli` is a **firewall / security edge**:
FortiOS has no switchport at all, every port is routed, tenancy is a VDOM
rather than a VRF, and there is no fabric surface.

The realistic migration is therefore **not** a like-for-like switch swap. It
is an AOS-CX aggregation switch being replaced at the network edge by a
FortiGate that inherits the routed L3 boundary — SVI subnets, LACP uplinks,
default routes, SNMP polling and admin identity — while the L2 switching it
sat on top of stays behind or moves to a different box.

## The structural finding — and it is the inverse of the EOS pair

On `aruba_aoscx__arista_eos` the dominant loss is the interface inventory
**shrinking**. On this pair it **grows**, and confusing the two is the fastest
way to misread the drift:

| cell | source ifaces | target ifaces | records lost | records added |
|---|---|---|---|---|
| `aoscx_dcn_arch3_ebgp_leaf1a` | 9 | 11 | 0 | 2 |
| `aoscx_dcn_arch3_ibgp_leaf1a` | 9 | 11 | 0 | 2 |
| `aoscx_dcn_arch4_core1_1` | 18 | 22 | 0 | 4 |
| `aoscx_dcn_arch4_core1_2` | 42 | 46 | 0 | 4 |
| `canu_csm17_spine001_ipv6_vrf` | 22 | 30 | 0 | 8 |
| `netutils_aoscx_snmpv3_glcx1009` | 44 | 50 | 0 | 6 |
| `kitchen_sink` (synthetic) | 13 | 17 | 0 | 4 |

**Not one interface record is dropped anywhere in the corpus.** 30 records are
*added*: for every canonical VLAN the FortiOS renderer synthesises an 802.1Q
child interface `edit "vlan<id>" / set type vlan / set vlanid <id> / set
interface "<parent>"`, and re-parsing the render reads each one back as a new
`CanonicalInterface`.

Consequence, and the reason it is worth stating loudly: **every
`interfaces[].*` sub-field measures as drifted on all 7 cells**, because the
comparator sees a record-count change on the parent list. Declaring any of
them `good` would manufacture a false `CODEC_BUG` — but the operator story is
"the record set is inflated and needs review", not "your ports were deleted".

### Which interface sub-fields have INDEPENDENT evidence

The count inflation is one cause and it hits all nine keys at once. Citing one
of those keys as corroboration for another would be double-counting the same
event. Measured separately, on records that exist on **both** sides:

| sub-field | independent drift, all 7 cells | mechanism |
|---|---|---|
| `description` | **6 records** | FortiOS alias truncated to 25 chars |
| `interface_type` | **18 records** | `ianaift:l3ipvlan` → `ianaift:ethernetCsmacd` on AOS-CX `vlan N` SVIs |
| `ipv4_addresses` | **15 records** | address relocates to the synthesised child; 15/15 `virtual_gateway_address` companions dropped |
| `enabled` | **0 records** | no independent signal — count inflation only |
| `mtu` | **0 records** | no independent signal — count inflation only |
| `lag_member_of` | **0 records** | no independent signal — 44/44 member ports byte-identical |
| `ipv6_addresses` | **0 records** | only 2 interface records corpus-wide carry IPv6; neither drifts |
| `name` | 0 lost / 30 added | surviving names verbatim; inflation only |
| `vrrp_groups` | n/a | AOS-CX declares the whole subtree unsupported; 0 groups exist to lose |

Separately, **64 interface records across all 7 cells lose their entire
switchport surface** (`switchport_mode`, `access_vlan`, `trunk_allowed_vlans`,
`trunk_native_vlan` all → empty). Those four canonical paths are declared
`unsupported` by `fortigate_cli` — "FortiOS has no switchport access/trunk
mode — every port is L3". This is the independent, per-record proof behind the
`unsupported` call on `vlans[].untagged_ports` / `vlans[].tagged_ports`; it is
*not* the count inflation wearing a different hat.

### The duplicate-address hazard (verify before you apply)

On `aoscx_dcn_arch4_core1_1`, `aoscx_dcn_arch4_core1_2` and `kitchen_sink` the
render emits the **same IPv4 address on two interfaces**: the AOS-CX SVI
carried through as a plain interface, *and* the synthesised 802.1Q child. From
the `core1_1` render:

```
    edit "vlan 4000"
        set alias "CORE-ROUTING-SVI"
        set ip 10.255.12.1 255.255.255.248
        set mode static
        set status down
    next
    ...
    edit "vlan4000"
        set type vlan
        set vlanid 4000
        set interface "lag 1"
        set ip 10.255.12.1 255.255.255.248
        set mode static
    next
```

A real FortiGate rejects a duplicate subnet across interfaces. **Three of
seven cells produce a render that will not apply as-is.** Delete one of the
two entries — normally the passthrough `vlan <id>` copy — before pushing.

Note also `set interface "lag 1"` on every child. The renderer parents VLAN
children to the *first* `CanonicalLAG` on the tree
(`_build_vlan_children`, "operators almost always trunk VLANs over a LAG"),
regardless of that VLAN's real membership: on `core1_1`, VLAN 4000 was tagged
on `lag 101` and `lag 102`, and still lands on `lag 1`. Re-parent every VLAN
child by hand.

## Per-field measurement (7 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 7 | 0 | 0 |
| interfaces (all sub-fields) | 0 | 7 | 0 |
| vlans[].id | 7 | 0 | 0 |
| vlans[].name | 0 | 7 | 0 |
| vlans[].ipv4_addresses | 0 | 5 | 2 |
| vlans[].untagged_ports | 0 | 7 | 0 |
| vlans[].tagged_ports | 0 | 5 | 2 |
| vlans[].description | 0 | 4 | 3 |
| static_routes | 2 | 0 | 5 |
| snmp.community / location / contact / trap_hosts | 4 | 0 | 3 |
| snmp.v3_users | 3 | 1 | 3 |
| lags | 7 | 0 | 0 |
| local_users[].name | 6 | 0 | 1 |
| local_users[].role | 0 | 6 | 1 |
| local_users[].hashed_password | 0 | 6 | 1 |
| vxlan_vnis[].vni / vlan_id / mcast_group | 0 | 3 | 4 |
| routing_instances[].name / description | 0 | 3 | 4 |
| anycast_gateway_mac | 0 | 5 | 2 |

Fields trivially empty on all 7 cells: `domain`, `dns_servers`,
`ntp_servers`, `timezone`, `syslog_servers`, `dhcp_servers`,
`radius_servers`, `evpn_type5_routes`, `raw_sections`, `apply_groups`,
`group_content`.

VLAN-record totals across the corpus (30 VLAN records on 7 cells):

- names replaced with a synthetic `vlan<id>`: **30 of 30**
- SVI addresses at the VLAN mount: **18 → 0** (relocated, see below)
- `virtual_gateway_address` values: **15 → 0** (genuinely dropped)
- `untagged_ports` lists: **13 → 0** · `tagged_ports` lists: **11 → 0**
- descriptions: **6 → 0**

## Total drop vs degradation — the calls that needed a round-trip

`lossy` warns and stays compatible; `unsupported` blocks (netcanon #436, "a
vanished record is not lossy"). Three keys on this pair looked like total
drops from the drift shape and are **not**:

**1. `vlans[].ipv4_addresses` — relocation, not loss.** The VLAN mount is
empty on the target for all 18 populated records, which reads as a total drop.
The round-trip shows the /24 reappearing on the synthesised `vlan<id>`
interface record with the same prefix length. The subnet is still in the
config; it moved mounts. What *is* genuinely lost is the anycast companion —
15/15 `virtual_gateway_address` values are gone, and `fortigate_cli` declares
`/vlans/vlan/ipv4/address/virtual-gateway-address` unsupported ("FortiGate is
a firewall/edge platform with no anycast-gateway fabric primitive"). Recorded
`lossy`: `unsupported` would tell an operator the subnet does not migrate,
which is false.

**2. `vlans[].description` — a surviving record, an emptied scalar.** The
vanish classifier calls this a total drop because every populated description
lands as `''`. But the VLAN record itself survives with its id, so nothing is
blocked, and `fortigate_cli` declares `/vlans/vlan/description` **lossy** in
its own matrix ("Render emits the VLAN name but not a separate description
line"). Signal and declaration only appear to disagree: the classifier is
record-blind. `lossy`.

**3. `local_users[].hashed_password` — re-labelled, not dropped.** The target
value is the source ciphertext behind a `fortios:ENC ` marker (measured: the
canonical string grows by exactly the 12 characters of that prefix on every
one of the 6 populated cells). Nothing is deleted, so `lossy` — but see the
credential section below for why that is still a broken account.

Conversely, four surfaces are **real total drops** and are recorded
`unsupported`, each with the target's own matrix entry agreeing:

| key | measured | target declaration |
|---|---|---|
| `anycast_gateway_mac` | scalar → `''` on 5 of 5 populated cells | `/anycast-gateway-mac` unsupported |
| `routing_instances[].*` | "all 2 routing_instances dropped" on 3 cells | `/routing-instances/instance` unsupported — "VDOMs not modelled" |
| `vxlan_vnis[].*` | "all 1/2 vxlan_vnis dropped" on 3 cells | `/vxlan-vnis/vni` unsupported — "VXLAN not modelled — FortiGate is a firewall codec" |
| `vlans[].untagged_ports` / `tagged_ports` | 13 → 0 and 11 → 0 lists | `/vlans/vlan/untagged-ports`, `/vlans/vlan/tagged-ports` unsupported |

## Source-side gaps vs symmetric gaps

AOS-CX declares these **unsupported at the exact path**, so as a *source* it
never emits them:

`/system/domain` · `/system/dns-server` · `/system/ntp-server` ·
`/system/syslog-server` · `/dhcp-servers/pool` ·
`/radius-servers/server/host` · `/radius-servers/server/key`

Most are recorded `not_applicable`. For `dns_servers` and `ntp_servers`
**`fortigate_cli` declares the field SUPPORTED**, so re-authoring resolvers and
NTP peers on the FortiGate will stick — worth doing by hand at cutover.

Two are different and are recorded `unsupported`, because the gap is
**symmetric** — the target drops them too, so "re-author on the target" is not
advice that works:

- `/system/timezone` — unsupported on both sides.
- `/system/syslog-server` — unsupported on both sides. `fortigate_cli`:
  "Render emits no logging/syslog config; intent.syslog_servers are dropped on
  migration." *(This differs from the EOS pair, where the target supports
  syslog and the same source gap is `not_applicable`. Read the target column,
  not the source column, before copying a disposition between pairs.)*

## Two matrix declarations that do not match the measurement

Neither is fixed here — this is an expectation file, not a codec change — but
both should be carried forward.

**1. `lags` is under-declared on the target.** `fortigate_cli` declares
**nothing at all** for `/lags/lag` — not supported, not lossy, not
unsupported. It nevertheless round-trips the surface perfectly: **34 LAG
records and 44 member ports across all 7 cells, byte-identical on name,
members and LACP mode**, rendered as `set type aggregate` / `set member` /
`set lacp-mode`. `interfaces[].lag_member_of` is likewise identical on every
member port. This is the exact mirror of the EOS pair, where the matrix is
silent *and* the render drops LAGs entirely.

**2. `/vlans/vlan/name` is over-declared on the target.** `fortigate_cli`
lists it **supported**, yet all 30 VLAN records in the corpus come back with
the operator name replaced by a synthetic `vlan<id>` — `PROD-WEB` → `vlan101`,
`NMN` → `vlan2`, and an unnamed VLAN 1 arrives *named* `vlan1`. The name is
derived from the child-interface identifier on re-parse, so the operator label
never survives.

## Identity: roles and credentials

**Roles are remapped, not lost.** The AOS-CX `administrators` role renders to
the FortiOS `super_admin` accessprofile on all 6 populated cells; `operators`
passes through unchanged (measured on `kitchen_sink`, which carries both).
The privilege intent is preserved and arguably correct — but the canonical
string changes, so any downstream tooling keyed on the literal role name will
not match, and `super_admin` on a FortiGate is unrestricted. Review the
mapping before it becomes a production account.

**Credentials do not migrate.** `local_users[].hashed_password` drifts on all
6 populated cells. AOS-CX stores the user secret in its own encrypted form —
an `AQB…`-prefixed ciphertext blob — and the FortiOS render re-emits that same
blob behind a `set password ENC` marker. The bytes survive; the *meaning* does
not. A FortiGate decrypts `ENC` material with FortiOS-internal key material,
so an ArubaOS-CX ciphertext presented as a FortiOS `ENC` blob is not a
password a FortiGate can ever authenticate.

Every migrated account therefore arrives **without a working credential**. Set
passwords on the target before cutover, or the accounts are unusable.

The ciphertext values are deliberately not reproduced in this file or in the
expectation YAML. Per `AGENTS.md`, encrypted secrets are operator-traceable
even when encrypted, and a document that quotes the value it describes defeats
its own redaction. The same applies to the SNMPv3 auth/priv passphrases
discussed below.

## SNMP

`snmp.community`, `snmp.location` and `snmp.contact` are preserved on all 4
cells where the SNMP record is populated. Read that precisely: a non-empty
community is observed and preserved on 1 cell and non-empty location/contact
on 3; on the remainder the scalars are empty on both sides, and the audit
scores "unchanged" as preserved.

`snmp.trap_hosts` is `good` for the weaker of the two possible reasons.
**aruba_aoscx declares `/snmp/trap-host` unsupported**, so as a source it
never emits trap hosts; the list is empty on both sides on every cell. The
disposition means "no divergence", not "trap destinations migrate". Re-author
SNMP trap receivers on the FortiGate by hand.

`snmp.v3_users` drifts on exactly 1 of the 4 populated cells. The mesh
comparator deliberately blanks `auth_passphrase` / `priv_passphrase` as opaque
per-vendor digests (`tools/run_full_mesh.py`, the cosmetic-normalisation
list), so a passphrase-only difference reads as preserved — and there *is* one:
both passphrases acquire an `ENC ` marker on render, exactly as the local-user
secret does, with the same consequence. The one comparator-visible drift is
the privacy cipher: `aes` is normalised to `aes128`. USM users must be
re-created on the FortiGate with fresh passphrases regardless of what the
drift count shows.

## What actually survives a cutover

Worth stating positively, because most of this file is loss:

- `hostname` — 7/7 cells.
- `lags` — 34 records, 44 member ports, 7/7 cells, including LACP mode.
- `vlans[].id` — 30/30 VLAN ids.
- `static_routes` — identical on both populated cells, including a non-default
  metric (`10.99.0.0/16` at metric 200 on `kitchen_sink`).
- `local_users[].name` — 6/6 populated cells.
- SVI subnets — relocated to synthesised child interfaces, not lost.

Everything an operator must rebuild by hand: port-to-VLAN membership, VLAN
names and descriptions, first-hop/anycast gateway addressing, VRFs, VXLAN,
SNMPv3 users, trap receivers, syslog, DNS, NTP, timezone, and every local
password.

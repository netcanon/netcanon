# IOS-XR → AOS-CX: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/cisco_iosxr__aruba_aoscx.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key
dispositions were resolved through the audit's own `actual_disposition()` rather
than inferred from the drift shape, so this file and the ratchet agree by
construction. The mechanisms described below were additionally re-derived by
hand, parsing each fixture with `cisco_iosxr` and rendering with `aruba_aoscx`.

- Fixture cells: **12**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the measured mesh run, and hand round-trips of the committed
> fixtures. Where a disposition rests on a declaration rather than an observed
> round-trip, the YAML says so explicitly.

## Device-class framing

`cisco_iosxr` in this corpus is a **service-provider edge/core router** — MPLS
L3VPN PEs, iBGP route-reflectors, eBGP borders, SR/SRv6 lab nodes.
`aruba_aoscx` is a **campus access/aggregation switch**. This is the widest
device-class gap in the mesh, and it shapes the whole result: the surfaces
IOS-XR is rich in (VRFs with RD/route-targets, per-VRF static routing,
4-segment interface naming, `Bundle-Ether` aggregation) are precisely the
surfaces AOS-CX either flattens or defers, while the surfaces AOS-CX is built
around (VLAN port membership, SVIs, switchport modes, active-gateway) are ones
IOS-XR never populates at all.

The realistic migration this pair describes is therefore **not** a like-for-like
re-home. It is an SP-edge router's *management and L3 skeleton* being re-landed
on a campus switch: hostname, interface inventory and addressing, default-VRF
static routes, VRF names, VLAN IDs and user identity carry across; the VPN
plumbing, the SNMP/NTP/DNS/syslog management plane and the credential material
do not.

## The structural finding — and how it differs from the campus pairs

**The interface inventory does NOT shrink on this pair.** This is the important
negative result, because the neighbouring AOS-CX-sourced pairs are dominated by
record loss and it would be easy to assume the same shape here. It is not the
same shape:

| cell | source interfaces | rendered + re-parsed |
|---|---|---|
| `iosxr_design_cst_pa3_xr752.cfg` | 55 | 55 |
| `batfish_vpnv4_pe1.txt` | 6 | 6 |
| `kitchen_sink.cfg` (synthetic) | 9 | 9 |

Every interface record survives, and `name`, `description`, `enabled`, `mtu`,
`ipv4_addresses` and `ipv6_addresses` are preserved on every populated cell.
Those six keys are therefore recorded `good`, not lossy — declaring a loss on
any of them would manufacture a false `CODEC_BUG`.

The interface loss on this pair is **per-attribute**, and there are exactly two
attributes:

1. `interface_type` — drifts on all 12 cells, 154 records in aggregate. Every
   IANA ifType collapses to `ianaift:other`, including
   `ianaift:softwareLoopback` on `Loopback0` and `ianaift:ieee8023adLag` on the
   `Bundle-Ether` interfaces. Both codecs declare
   `/interfaces/interface/config/type` lossy in their own right — AOS-CX
   declares no IANA ifType and the codec infers it from the interface-name
   shape (`1/1/1` → ethernetCsmacd, `vlan N` → l3ipvlan), and an IOS-XR
   4-segment name matches none of those shapes.
2. `lag_member_of` — see below; it is a name-form change, not a membership loss.

## Per-field measurement (12 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 12 | 0 | 0 |
| domain | 0 | 8 | 4 |
| ntp_servers | 0 | 1 | 11 |
| interfaces[].name | 12 | 0 | 0 |
| interfaces[].description | 9 | 0 | 3 |
| interfaces[].enabled | 12 | 0 | 0 |
| interfaces[].mtu | 4 | 0 | 8 |
| interfaces[].ipv4_addresses | 12 | 0 | 0 |
| interfaces[].ipv6_addresses | 3 | 0 | 9 |
| interfaces[].interface_type | 0 | 12 | 0 |
| interfaces[].lag_member_of | 0 | 4 | 8 |
| vlans[].id | 4 | 0 | 8 |
| static_routes | 3 | 3 | 6 |
| lags | 0 | 4 | 8 |
| local_users[].name | 9 | 0 | 3 |
| local_users[].role | 9 | 0 | 3 |
| local_users[].hashed_password | 0 | 9 | 3 |
| routing_instances[].name | 8 | 0 | 4 |
| routing_instances[].description | 0 | 1 | 11 |

Fields trivially empty on all 12 cells: `dns_servers`, `timezone`,
`syslog_servers`, `interfaces[].vrrp_groups`, `vlans[].name`,
`vlans[].ipv4_addresses`, `vlans[].untagged_ports`, `vlans[].tagged_ports`,
`vlans[].description`, `dhcp_servers`, all five `snmp.*` keys,
`radius_servers`, all three `vxlan_vnis[].*` keys, `evpn_type5_routes`,
`raw_sections`, `apply_groups`, `group_content`, `anycast_gateway_mac`.

## Source-side gaps vs target-side drops

The corpus is dominated by trivially-empty fields, and lumping them together
would hide the operationally important distinction: whether re-authoring the
field **on the AOS-CX side** would stick.

**Source-side gaps — `cisco_iosxr` never emits these, `aruba_aoscx` supports
them.** Recorded `not_applicable`; re-author on the target and it will hold:

`/snmp/community` · `/snmp/location` · `/snmp/contact` · `/snmp/v3-user` ·
`/vxlan-vnis/vni` · `/anycast-gateway-mac` · `/vlans/vlan/name` ·
`/vlans/vlan/description` · `/vlans/vlan/tagged-ports` ·
`/vlans/vlan/untagged-ports`

The VLAN entries in that list deserve spelling out. The `cisco_iosxr` codec
synthesises its VLAN id-list from `encapsulation dot1q` sub-interfaces, and its
own source comment states the consequence: *"no port membership; name always
empty"*. It additionally declares `/interfaces/interface/switchport-mode`,
`/access-vlan`, `/trunk-allowed-vlans` and `/trunk-native-vlan` unsupported —
there is no campus L2 surface on an SP router to migrate. AOS-CX supports all of
it. The whole L2 edge must be authored fresh on the target; nothing is being
lost in translation because nothing was there.

**Target-side drops — the source has the data (or could) and `aruba_aoscx`
declares it unsupported.** Recorded `unsupported`:

`/system/domain` · `/system/dns-server` · `/system/ntp-server` ·
`/system/syslog-server` · `/snmp/trap-host` ·
`/routing-instances/instance/description`

`domain` and `ntp_servers` are the two of these the corpus actually exercises,
and both are total drops rather than degradations —
`'lab.example.net' → ''` on the synthetic cell, and both configured NTP servers
dropped to `[]` on `iosxr_design_cst_pa3_xr752.cfg`.

**Symmetric gaps — both matrices declare unsupported.** Also `unsupported`, but
for a different reason, and the YAML says which:

`/system/timezone` · `/dhcp-servers/pool` · `/radius-servers/server/*` ·
`/interfaces/interface/vrrp-groups/group/*`

## Three findings worth carrying forward

### 1. `interfaces[].lag_member_of` drift here is a naming artifact — do not read it as membership loss

The audit canonicalises LAG names before comparing (`_LAG_NAME_FIELDS` →
`_canonical_lag_name`) so that a vendor-correct rename does not fire drift. Its
regex accepts `ae<N>`, `Po<N>`, `Port-channel<N>`, `Port-Channel<N>`,
`trk<N>`, `Trk<N>`, `agg<N>` and `bond<N>`.

**It covers neither side of this pair.** IOS-XR's `Bundle-Ether<N>` and AOS-CX's
`lag <N>` (note the space) both fall through to `None`, so the comparison
reverts to raw string equality and the rename registers as drift:

```
'Bundle-Ether321' -> None      'lag 321' -> None
'Bundle-Ether1'   -> None      'lag 1'   -> None
'Port-channel1'   -> 'LAG1'    'ae1'     -> 'LAG1'
```

The binding itself is intact. On `iosxr_design_cst_pa3_xr752.cfg` the member
lists round-trip exactly — `lag 321` comes back with
`['TenGigE0/0/0/18', 'TenGigE0/0/0/30']`, the same two members
`Bundle-Ether321` had. The key is declared `lossy` because it does drift and the
declaration must be evidenced, but a reader must not infer that ports fall out
of their bundles.

This is the mirror image of the AOS-CX → Arista finding, where the canonicaliser
*did* apply and the residual drift was therefore real. Same key, opposite
reading. The gap in `_LAG_NAME_RE` is a reconciler observation, not a
pair-specific fact, and is left for a tooling change rather than fixed here.

### 2. `lags` loses LACP mode and member-less bundles — that part is real

Round-tripping `iosxr_design_cst_pa3_xr752.cfg` by hand, 5 source bundles become
3:

| source | members | mode | rendered |
|---|---|---|---|
| `Bundle-Ether321` | 2 | `active` | `lag 321`, members intact, mode `static` |
| `Bundle-Ether421` | 2 | `active` | `lag 421`, members intact, mode `static` |
| `Bundle-Ether500` | 1 | `static` | `lag 500`, members intact, mode `static` |
| `Bundle-Ether2123` | 0 | `active` | **absent** |
| `Bundle-Ether2124` | 0 | `active` | **absent** |

Two independent losses. The mode downgrade `active → static` is declared:
AOS-CX's `/lags/lag/mode` is a `LossyPath` because it emits `lacp mode` only for
a kind-`lag` interface present in the tree. Operationally it means LACP is off
on the target — the bundle becomes a static trunk, which is a link-negotiation
behaviour change, not cosmetics. Separately, bundles that carry no members are
dropped entirely, because the renderer keys off `CanonicalInterface.lag_member_of`
rather than `CanonicalLAG.members`.

The field stays `lossy` rather than `unsupported`: 3 of 5 bundles survive with
their membership intact, so the pair remains compatible.

### 3. `static_routes` loses exactly the VRF-bound subset

The split is clean and fully explained by one declaration: AOS-CX supports
`/routing/static-route` but declares `/routing/static-route/vrf` **unsupported**
("per-VRF static-route binding parses-and-ignores in Phase 1; only default-VRF
`ip route` is wired"). IOS-XR declares *both* supported.

Measured, by hand:

- `iosxr_design_cst_pa3_xr752.cfg` — 12 routes, all default-VRF → **12 survive**
- `kitchen_sink.cfg` — 4 routes, 3 default-VRF + 1 `vrf CUSTOMER-A` → **3 survive**
- `batfish_vpnv4_pe1.txt` — 1 route, `vrf blue` → **0 survive**

That last cell is why the aggregate reads as a total drop on 3 of 12 cells: those
cells happen to carry *only* VRF-bound routes, so losing the subset loses
everything they had. The field-level truth is still a subset loss, which is why
it is `lossy` and not `unsupported`. On an L3VPN PE the practical impact is
large — audit the per-VRF routing table before cutover.

## VRF surface

`routing_instances[].name` survives on all 8 populated cells; the VRF anchors
themselves land as bare `vrf <name>` stanzas. Everything hung off the anchor
does not. AOS-CX declares `description`, `route-distinguisher`, `rt-imports`,
`rt-exports` and `l3-vni` unsupported — "VRF RD lives under the deferred `evpn`
block".

On `kitchen_sink.cfg`:

```
SRC  name='CUSTOMER-A'  desc='customer a l3vpn'  rd='65001:100'
TGT  name='CUSTOMER-A'  desc=''                  rd=''
```

Only `description` is a tracked key in the expectation YAML, and it is a total
drop, so it is `unsupported`. It is worth recording that the RD and both
route-target lists vanish alongside it — that is the entire L3VPN identity of
the instance, and the mesh shows it drifting on 10–12 records. A VRF that
arrives on AOS-CX is a namespace, not a VPN.

## Credential material

`local_users[].hashed_password` drifts on 9 of the 12 cells. The mechanism is
narrower than "the target cannot hold a hash", and the difference matters, so it
was isolated rather than assumed.

The AOS-CX `user <name> group <g> password ciphertext <blob>` grammar takes a
**single** token for the secret. An IOS-XR secret arrives as **two** tokens — a
numeric type marker followed by the secret itself — and the render emits both.
On re-parse, AOS-CX keeps only the leading token, so the canonical
`hashed_password` comes back as the bare marker digit.

Fed to the `aruba_aoscx` parser directly, with synthetic placeholder secrets:

| input form | parsed `hashed_password` |
|---|---|
| native single-token blob | 19 chars, 1 token — intact |
| two-token `<marker> <secret>` | **1 char, 1 token — secret gone** |

Confirmed end-to-end on `kitchen_sink.cfg`: a 63-character source secret in the
crypt(3) `$6$` family comes back as a 2-character marker; on
`iosxr_design_cst_pa3_xr752.cfg` the Cisco type-7 obfuscated secrets come back
as the single digit `7`.

Every migrated account therefore arrives **without a working credential**.

Two things follow that are not in the matrices:

- `aruba_aoscx` declares `/local-users/user/hashed-password` **supported**. The
  round-trip does not preserve it. That is a target-side matrix
  under-declaration; it is a codec-level fact rather than a pair-level one, and
  is recorded here rather than papered over in the YAML.
- `local_users[].role` *is* preserved (`root-lr`, `operator` both round-trip),
  but the adjacent `privilege_level` degrades 15 → 1, which AOS-CX declares
  lossy — it maps `administrators → 15` and everything else → 1. `role` is a
  tracked key and is `good`; `privilege_level` is not tracked, and the note on
  `role` says so rather than letting the `good` imply the whole identity
  survived.

No secret value — crypt hash, type-7 string, or ciphertext blob — is reproduced
in this file or in the expectation YAML. Per `AGENTS.md`, encrypted and hashed
secrets are operator-traceable even when they cannot be reversed, and a document
that quotes the value it describes defeats its own redaction. Only shapes
(length, field count, family prefix) are recorded.

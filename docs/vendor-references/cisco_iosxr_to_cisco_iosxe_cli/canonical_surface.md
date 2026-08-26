# IOS-XR → IOS-XE (CLI): measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/cisco_iosxr__cisco_iosxe_cli.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key
dispositions were resolved through the audit's own `actual_disposition()` rather
than inferred from the drift shape, so this file and the ratchet agree by
construction. Every claim below was additionally re-derived by parsing each
fixture with `cisco_iosxr`, rendering with `cisco_iosxe_cli` and re-parsing the
render.

- Fixture cells: **12**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations and the measured mesh run. Where a disposition rests on a
> declaration rather than an observed round-trip, the YAML says so explicitly.

## Device-class framing

`cisco_iosxr` in this corpus is a **service-provider edge/core router** — seven
Batfish PE/RR/border fixtures, an `xrdtools` ISIS/SR/SRv6 trio, one real
`iosxr_design` chassis (55 interfaces) and the synthetic kitchen sink.
`cisco_iosxe_cli` is a **general-purpose enterprise/branch router** reading and
writing IOS-XE CLI text.

The shared surface is therefore the **routed** surface: interface addressing,
admin state, MTU, descriptions, static routes and VRFs. The campus L2 surface
is not shared and is not lost either — IOS-XR simply never populates it.

## The structural finding — and it is the *opposite* of the AOS-CX pair

**The interface inventory does not shrink on this pair.** Source and re-parsed
target interface counts are equal on **12 of 12 cells** (9/9, 17/17, 55/55 on
the three largest), and no interface name is dropped on any cell.

That matters because it is the inverse of the `aruba_aoscx__arista_eos`
precedent, where every `interfaces[].*` sub-field had to be declared lossy
because the parent records vanished. Here there is **no structural loss to
inherit**, so each interface sub-field is judged purely on what happens to its
own value — and most of them survive intact:

| interface sub-field | populated records | preserved |
|---|---|---|
| `description` | 39 | 39 |
| `mtu` | 11 | 11 |
| `ipv6_addresses` | 11 | 11 |
| `ipv4_addresses` | all | all (12/12 cells) |
| `enabled` | all | all (12/12 cells) |
| `name` | all | all (12/12 cells) |

Notably the IOS-XR **4-segment names survive verbatim** — `TenGigE0/0/0/18`,
`HundredGigE0/0/1/0`, `MgmtEth0/RP0/CPU0/0`, `GigabitEthernet0/0/0/12.200` all
round-trip through the IOS-XE CLI render unchanged. `cisco_iosxr` declares
`/interfaces/interface/4th-port-segment` lossy in its own matrix; that
declaration does not bite on this pair.

## Per-field measurement (12 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 12 | 0 | 0 |
| domain | 8 | 0 | 4 |
| ntp_servers | 1 | 0 | 11 |
| interfaces (record inventory) | 12 | 0 | 0 |
| interfaces[].interface_type | 2 | 10 | 0 |
| interfaces[].lag_member_of | 0 | 4 | 8 |
| vlans[].id | 4 | 0 | 8 |
| static_routes | 6 | 0 | 6 |
| lags | 0 | 4 | 8 |
| local_users[].name / .hashed_password | 9 | 0 | 3 |
| local_users[].role | 0 | 9 | 3 |
| routing_instances[].name | 8 | 0 | 4 |
| routing_instances[].description | 1 | 0 | 11 |

Trivially empty on all 12 cells: `dns_servers`, `timezone`, `syslog_servers`,
`interfaces[].vrrp_groups`, `vlans[].name`, `vlans[].ipv4_addresses`,
`vlans[].untagged_ports`, `vlans[].tagged_ports`, `vlans[].description`,
`dhcp_servers`, every `snmp.*` key, `radius_servers`, every `vxlan_vnis[].*`
key, `evpn_type5_routes`, `raw_sections`, `apply_groups`, `group_content`,
`anycast_gateway_mac`.

## The four real losses

### 1. `interfaces[].interface_type` — 60 records degrade to `ianaift:other`

The largest single loss on the pair, and it is a genuine per-record value
degradation on records that survive. Aggregated across all 12 cells:

| transition | records |
|---|---|
| `ianaift:ethernetCsmacd` → `ianaift:other` | 50 |
| `ianaift:ieee8023adLag` → `ianaift:other` | 10 |

The mechanism is exactly what the `cisco_iosxe_cli` matrix says about
`/interfaces/interface/config/type`: the CLI parser **infers the IANA type from
the name prefix**. Splitting the 60 by prefix shows a clean rule — prefixes
IOS-XE also uses keep their type, XR-only prefixes do not:

| prefix | type preserved? | records |
|---|---|---|
| `GigabitEthernet` | yes | 72 |
| `Loopback` (incl. `Loopback123` / `Loopback1588`) | yes | 18 |
| `HundredGigE` | yes | 4 |
| `BVI` | yes | 1 |
| `TenGigE` | **no** | 40 |
| `MgmtEth` | **no** | 10 |
| `Bundle-Ether` | **no** | 10 |

`TenGigE`, `MgmtEth` and `Bundle-Ether` are IOS-XR spellings with no IOS-XE
equivalent (IOS-XE uses `TenGigabitEthernet`, a `GigabitEthernet0/0` management
port, and `Port-channel`), so the re-parse cannot recover the type and falls to
`ianaift:other`. Both matrices already declare the path lossy — the measurement
agrees with both declarations.

### 2. `interfaces[].lag_member_of` — a rename, and why it counts as drift

Membership itself is **intact**. On every populated cell the same member
interfaces carry the same bundle, and only the bundle *name* changes:

```
src: GigabitEthernet0/0/0/2 -> Bundle-Ether23 ; GigabitEthernet0/0/0/3 -> Bundle-Ether23
rt : GigabitEthernet0/0/0/2 -> Port-channel23 ; GigabitEthernet0/0/0/3 -> Port-channel23
```

The reconciler *has* a LAG-rename equivalence (`_LAG_NAME_FIELDS`, applied to
`lags[].name` and `interfaces[].lag_member_of`) that collapses vendor-native LAG
spellings to a canonical `LAG<N>` token — but `_LAG_NAME_RE` allows only
`ae` / `Po` / `Port-channel` / `Port-Channel` / `trk` / `Trk` / `agg` / `bond`.
IOS-XR's `Bundle-Ether<N>` is **not** in that whitelist:

```
_canonical_lag_name('Bundle-Ether23') = None
_canonical_lag_name('Port-channel23') = 'LAG23'
_canonical_lag_name('ae23')  = 'LAG23'      _canonical_lag_name('trk23')  = 'LAG23'
_canonical_lag_name('Po23')  = 'LAG23'      _canonical_lag_name('agg23')  = 'LAG23'
                                            _canonical_lag_name('bond23') = 'LAG23'
```

So the rename falls through to raw equality and surfaces as drift, where the
same rename from any other vendor would not. That is a gap in the audit tool's
whitelist, not a codec defect — but the rename is also operator-visible on the
target, so the key is declared `lossy` on its own merits rather than explained
away. Extending `_LAG_NAME_RE` is a tooling change and is deliberately left
outside this pair's scope.

### 3. `lags` — a partial record loss on one cell, on top of the rename

Two independent things happen to `lags`, and only the second is a record loss:

1. The `Bundle-Ether<N>` → `Port-channel<N>` rename, on all 4 populated cells.
2. On **1 of the 4** cells (`iosxr_design_cst_pa3_xr752.cfg`) the LAG count
   drops **5 → 3**. The two that vanish are `Bundle-Ether2123` and
   `Bundle-Ether2124`, and both have an **empty member list**.

The mechanism follows from how the IOS-XE CLI render emits LAGs: it writes a
`channel-group <N> mode ...` line under each *member* interface rather than a
standalone bundle stanza. A bundle with zero members produces no
`channel-group` line anywhere in the render, so re-parsing cannot reconstruct
it. Bundles that have members survive with their full membership — on the same
cell, `Bundle-Ether321`, `421` and `500` all round-trip with their member sets
intact.

The loss is therefore **partial**, which is why the key is `lossy` and not
`unsupported`: `lossy` warns and stays compatible, and the LAG surface as a
whole does survive. Note the two member-less bundles are lost only as *LAG*
records — their **interface** records survive the round-trip.

Worth recording separately: `cisco_iosxe_cli` declares **nothing** for
`/lags/lag` — not supported, not lossy, not unsupported — while its render
plainly emits `channel-group` lines. That is a target-side matrix
under-declaration, not a pair-specific fact, and is left for a codec change.

### 4. `local_users[].role` — `root-lr` collapses to `admin`

Aggregated across the 9 populated cells (14 user records):

| transition | user records |
|---|---|
| `root-lr` → `admin` | 13 |
| `operator` → `operator` | 1 (preserved) |

IOS-XR's `root-lr` (root-logical-router task group) has no IOS-XE equivalent and
the render maps it to `admin`. The `operator` role passes through unchanged, so
this is a specific mapping collapse rather than a blanket role drop. The user
record itself survives — `name` and `hashed_password` are untouched.

Review the resulting privilege level on the target before cutover: the mapping
is one-way and role granularity present on the XR side is not recoverable from
the render.

## Credential material

`local_users[].hashed_password` is **preserved byte-for-byte on all 14 user
records across the 9 populated cells** — the only pair-relevant credential fact,
and it is a positive one.

The stored secrets are opaque vendor password tokens; none of them matched a
crypt(3) `$id$` prefix in this corpus. Their values are deliberately not
reproduced here or in the expectation YAML. Per `AGENTS.md`, encrypted or
hashed secrets are operator-traceable even when not reversible, and a document
that quotes the value it describes defeats its own redaction.

Both `local_users[].name` and `local_users[].hashed_password` are declared
supported by `cisco_iosxr` and declared **nothing at all** by `cisco_iosxe_cli`
— a second target-side under-declaration, since the render emits `username`
lines. The `good` dispositions rest on the measurement, not on that silence.

## Source-side gaps vs target-side drops

IOS-XR declares these **unsupported at the exact path**, so as a *source* it
never emits them and there is nothing for IOS-XE to lose. These are recorded
`not_applicable`, not `unsupported`:

`/dhcp-servers/pool` · `/snmp/community` · `/snmp/v3-user/*` ·
`/radius-servers/server/host` · `/radius-servers/server/key` ·
`/vxlan-vnis/vni` · `/vxlan-vnis/source-interface` · `/vxlan-vnis/udp-port` ·
`/evpn-type5-routes/route` · `/anycast-gateway-mac` ·
`/interfaces/interface/vrrp-groups/group` (and its seven children) ·
`/interfaces/interface/switchport-mode` · `/access-vlan` ·
`/trunk-allowed-vlans` · `/trunk-native-vlan` · `/voice-vlan`

The distinction is operational, and on this pair it is unusually
consequential: **`cisco_iosxe_cli` declares most of these SUPPORTED** — SNMP
community/contact/location/trap-host/v3-user, VXLAN VNI + source-interface +
mcast-group, the VRRP group subtree, and `/anycast-gateway-mac`. So re-authoring
them on the IOS-XE side after cutover will stick. The migration report should
say that rather than implying the target cannot hold them.

`timezone` is the one genuinely symmetric gap: **both** matrices declare
`/system/timezone` unsupported. That one is `unsupported`.

## Why the VLAN surface is empty rather than lost

Four cells produce a VLAN record, and every one of them is **ID-only**:

```
batfish_ebgp_border01: id=35   batfish_ebgp_border02: id=35
iosxr_design_cst_pa3_xr752: id=200        kitchen_sink: id=100
```

`name`, `description`, `untagged_ports`, `tagged_ports` and `ipv4_addresses`
are empty on the source **and** on the re-parsed target. These IDs come from
dot1q encapsulation on routed sub-interfaces
(`/interfaces/interface/dot1q-vlan`, supported on both sides), not from a
campus VLAN database — IOS-XR has no `switchport` surface at all. The empty
sub-fields are a source-side gap, not a translation loss.

## Declarations that exist but are never exercised

Three declared losses do not bite on this corpus, and the YAML says so rather
than borrowing their authority:

- **`/routing/static-route/description`** — declared lossy by *both* codecs.
  Zero static routes in the corpus carry a description, and all 6 populated
  cells round-trip destination + gateway + VRF identically.
- **`/interfaces/interface/subinterfaces/subinterface/ipv6`** — declared
  unsupported by `cisco_iosxe_cli` (Phase 0.5 is IPv4-only there). No committed
  IOS-XR cell puts an IPv6 address on a sub-interface, so the gap is untested.
  An XR config that does would lose it.
- **`/routing-instances/instance` + `/instance-type`** — declared lossy by both
  codecs. VRF *names* are preserved on all 8 populated cells (`AZURE`,
  `red`/`blue`/`management`, `CUSTOMER`, `100`, `CUSTOMER-A`/`MGMT`) and the two
  VRF descriptions on the single populated cell survive verbatim. The lossy
  declarations concern the instance body and the mac-vrf/vrf discriminator, not
  the name.

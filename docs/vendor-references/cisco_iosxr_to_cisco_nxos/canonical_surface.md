# IOS-XR → NX-OS: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/cisco_iosxr__cisco_nxos.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key
dispositions were resolved through the audit's own `actual_disposition()`
rather than inferred from the drift shape, so this file and the ratchet agree
by construction. Every loss recorded in the YAML was additionally re-derived by
hand — parse the fixture with `cisco_iosxr`, render with `cisco_nxos`, re-parse
the render, diff the two canonical trees — rather than read off the mesh JSON.

- Fixture cells: **12** (11 real captures + 1 synthetic kitchen-sink)
- Render errors: **0** · re-parse errors: **0**
- Interface records compared: **156** source → **156** target
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations and the measured round-trip. Where a disposition rests on a
> declaration rather than an observed round-trip, the YAML says so explicitly.

## Device-class framing

`cisco_iosxr` in this corpus is a **service-provider edge/core router** — PE,
P and route-reflector roles, 4-segment port names (`GigabitEthernet0/0/0/0`,
`TenGigE0/0/0/18`), `Bundle-Ether` aggregates, BVIs, and a VRF surface whose RD
is harvested from `router bgp`. `cisco_nxos` is a **DC leaf/spine**.

The realistic migration is a PE/P router being re-homed onto a Nexus, so the
shared surface is the routed edge — interface addressing, MTU, admin state,
VRF names, static routes, local user identity. The campus L2 surface is thin on
both ends and effectively absent on the source: IOS-XR declares
`/interfaces/interface/switchport-mode`, `/access-vlan`,
`/trunk-allowed-vlans`, `/trunk-native-vlan` and `/voice-vlan` all
**unsupported**, because "IOS-XR is SP-routing with no L2 switchport model".

## The structural finding — and it is the opposite of the AOS-CX pair

**READ THIS BEFORE COMPARING WITH `aruba_aoscx__arista_eos.yaml`.** There, the
dominant loss was structural: the interface list shrank 9 → 5 and *every*
`interfaces[].*` sub-field was dragged to `lossy` with it. Here the interface
inventory is **fully preserved**:

- 156 interface records in, 156 out
- identical name sets on **all 12 cells** (no record missing, none added)

So there is no structural collapse to absorb blame on this pair. Every
interface sub-field that survives is declared `good` on its own measurement,
and the two that do not are genuine per-attribute losses.

`interfaces[].name` surviving is not a given: `cisco_iosxr` declares
`/interfaces/interface/4th-port-segment` **lossy** because IOS-XR port names
carry four segments (rack/slot/instance/port) while the cross-vendor
`PortIdentity` models only three. That path bites the port-*rename* helper, not
the bare render — the NX-OS render emits the IOS-XR name verbatim, so the
canonical name round-trips byte-identical here.

## Per-field measurement (12 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 12 | 0 | 0 |
| domain | 8 | 0 | 4 |
| ntp_servers | 1 | 0 | 11 |
| interfaces[].name | 12 | 0 | 0 |
| interfaces[].enabled | 12 | 0 | 0 |
| interfaces[].ipv4_addresses | 12 | 0 | 0 |
| interfaces[].description | 9 | 0 | 3 |
| interfaces[].mtu | 4 | 0 | 8 |
| interfaces[].ipv6_addresses | 3 | 0 | 9 |
| **interfaces[].interface_type** | **0** | **12** | 0 |
| **interfaces[].lag_member_of** | **0** | **4** | 8 |
| vlans[].id | 4 | 0 | 8 |
| static_routes | 6 | 0 | 6 |
| **lags** | **0** | **4** | 8 |
| local_users[].name / role / hashed_password | 9 | 0 | 3 |
| routing_instances[].name | 8 | 0 | 4 |
| routing_instances[].description | 1 | 0 | 11 |

Trivially empty on all 12 cells — the source never populates them:
`dns_servers`, `timezone`, `syslog_servers`, `dhcp_servers`, `radius_servers`,
`snmp.*`, `vxlan_vnis[].*`, `evpn_type5_routes`, `raw_sections`,
`apply_groups`, `group_content`, `anycast_gateway_mac`,
`interfaces[].vrrp_groups`, and every `vlans[]` sub-field except `id`.

Record-level counts behind the three drifting rows:

| key | drifting records | populated records |
|---|---|---|
| interfaces[].interface_type | 126 | 156 |
| interfaces[].lag_member_of | 15 | 15 |
| lags — renamed, record survives | 8 | 10 |
| lags — record vanishes | 2 | 10 |

## Loss 1 — `interfaces[].interface_type`, 126 of 156 records

The IANA interface-type hint degrades to `ianaift:other`:

| source name shape | source type | target type | records |
|---|---|---|---|
| `GigabitEthernet…` | `ianaift:ethernetCsmacd` | `ianaift:other` | 72 |
| `TenGigE…` | `ianaift:ethernetCsmacd` | `ianaift:other` | 40 |
| `HundredGigE…` | `ianaift:ethernetCsmacd` | `ianaift:other` | 4 |
| `Bundle-Ether…` | `ianaift:ieee8023adLag` | `ianaift:other` | 10 |
| `Loopback…` | `ianaift:softwareLoopback` | *(preserved)* | 18 |
| `MgmtEth…` | `ianaift:ethernetCsmacd` | *(preserved)* | 10 |
| `BVI…` / a `preconfigure` record | `ianaift:other` | *(preserved)* | 2 |

(126 drifted + 30 preserved = 156.)

**Mechanism.** Neither codec stores the type; both *infer* it from the name
prefix on parse. The `cisco_nxos` matrix says so directly: "NX-OS
interface-type is inferred from the name prefix (Ethernet → ethernetCsmacd,
loopback → softwareLoopback, Vlan → l3ipvlan, port-channel → ieee8023adLag,
nve → tunnel, mgmt …)". The render preserves the IOS-XR name verbatim, and
IOS-XR's SP naming matches none of those prefixes, so the re-parse falls
through to `ianaift:other`. `Loopback` and `MgmtEth` survive because they do
land on an NX-OS prefix.

Both matrices already declare `/interfaces/interface/config/type` **lossy** —
this is a declared, expected degradation, not a codec defect. The record and
every other attribute on it survive, so it is `lossy`, not `unsupported`.

**Operational reading:** nothing forwards differently. The degraded value is a
classification hint used by reporting and by downstream type-aware tooling; a
migration report generated from the target tree will call every revenue port
"other".

## Loss 2 — the LAG surface: `interfaces[].lag_member_of` and `lags`

These are **one mechanism, not two independent findings.** Do not read either
as corroborating the other.

The NX-OS render emits the aggregate as `interface Bundle-Ether<N>` (the IOS-XR
name, verbatim) and each member as `channel-group <N> mode active|on`. On
re-parse the NX-OS codec rebuilds the LAG from the `channel-group` number and
names it `port-channel<N>`. So:

- the **bundle ID** survives (`Bundle-Ether321` → `port-channel321`)
- the **member set** survives byte-identical
- the **LACP mode** survives
- the **operator-facing name form** does not

Both codecs declare `/lags/lag/name`, `/lags/lag/members` and `/lags/lag/mode`
supported, and they are right about members and mode.

**The one genuine record loss.** On `iosxr_design_cst_pa3_xr752.cfg` the source
carries five bundles, two of which (`Bundle-Ether2123`, `Bundle-Ether2124`)
have **no members**. With no member port there is no `channel-group 2123` line
anywhere in the render, so the re-parse has nothing to rebuild the LAG from and
the record vanishes: 5 → 3. Their *interface* records survive (`interface
Bundle-Ether2123` renders and re-parses fine) — it is only the `CanonicalLAG`
that is lost.

That makes `lags` a mixed case: on 3 of the 4 populated cells every bundle
survives with a renamed name, and on the fourth two memberless bundles drop.
Recorded `lossy` rather than `unsupported`: the concept round-trips and the
forwarding-relevant content survives, so `warn + compatible=True` is the honest
severity. `unsupported` blocks, and blocking a migration whose LAG members all
survive would be a false alarm. (#436 — "a vanished record is not lossy" —
governs a *total* concept drop; this is not one.)

**Why the audit does not forgive the rename.** `_LAG_NAME_RE` in
`tools/run_phase4_reconciliation.py` canonicalises `ae<N>` / `Po<N>` /
`Port-channel<N>` / `Port-Channel<N>` / `trk<N>` / `Trk<N>` / `agg<N>` /
`bond<N>` to a common `LAG<N>` token so a pure rename does not fire drift.
Neither side of this pair matches it: IOS-XR's `Bundle-Ether<N>` is not in the
prefix set, and the NX-OS re-parse produces lowercase `port-channel<N>`, which
the regex also rejects (it allows only `Port-channel` / `Port-Channel`). Both
fall through to raw equality.

That is an observation about the **audit tooling**, not about this pair, and it
is recorded here rather than acted on: widening `_LAG_NAME_RE` is a
cross-cutting change to a shared reconciler that every pair's ratchet depends
on, and it belongs in a tooling PR with its own regression run — not in a
per-pair expectation file. Until then the declaration stands on the measurement
that exists.

## Local users: the drift is real but it is not one of these keys

`local_users` drifts on 9 of 12 cells, and that number is easy to misread.
Measured record by record across all 9 populated user records (5 cells):

- `name` — preserved on every record
- `role` — preserved on every record (`root-lr` → `root-lr`, `operator` →
  `operator`)
- `hashed_password` — preserved **byte-identical** on every record

The whole of the parent list's drift is `privilege_level`, which degrades
`15 → 1`. `cisco_nxos` declares `/local-users/user/privilege-level` **lossy**
for exactly this: "NX-OS uses a named `role` … instead of a numeric privilege.
The codec maps network-admin / vdc-admin → 15 and everything else → 1". An
IOS-XR `root-lr` account is not in that map, so it re-parses at privilege 1.

`privilege_level` is **not a key in this pair's expectation set**, so no
disposition below claims it. It is documented here so the next reader does not
see "local_users drifts on 9 cells" and reach for a loss declaration on
`name`, `role` or `hashed_password` — all three are clean, and declaring a loss
on any of them would be an unevidenced over-claim the ratchet rejects.

Two honest caveats that follow from the same mechanism:

1. The render passes the IOS-XR role token through verbatim (`username <name>
   … role root-lr`). `root-lr` is an IOS-XR role name, not an NX-OS one. The
   *canonical* fidelity is perfect; the emitted config still needs a role-name
   rewrite before it is idiomatic NX-OS.
2. The password digest is copied across verbatim into an NX-OS `username …
   password <type> …` line. Round-trip fidelity through the canonical tree says
   nothing about whether the target platform will *accept* that digest form.
   Verify authentication on the target before cutover.

No credential value — plaintext, digest or vendor blob — is reproduced in this
file or in the expectation YAML. Per `AGENTS.md`, a document that quotes the
secret it describes defeats its own redaction.

## Source-side gaps vs symmetric gaps

`cisco_iosxr` declares these **unsupported at the exact path**, so as a
*source* it never emits them and there is nothing for NX-OS to lose. Every one
is trivially empty on all 12 cells, confirming the declaration:

| path | NX-OS declares |
|---|---|
| `/snmp/community`, `/snmp/v3-user/*` | **supported** |
| `/vxlan-vnis/vni`, `/source-interface`, `/udp-port` | supported / lossy |
| `/evpn-type5-routes/route` | lossy |
| `/anycast-gateway-mac` | **supported** |
| `/interfaces/interface/vrrp-groups/group` *(whole subtree)* | lossy (rendered as HSRP) |

These are recorded `not_applicable`, not `unsupported`. The distinction is
operational: the target *can* hold this configuration, so re-authoring SNMP,
VXLAN, EVPN type-5, the anycast gateway MAC and FHRP groups on the Nexus will
stick. A migration report should say that rather than imply the target cannot.

Three fields are **symmetric** gaps — both matrices declare them unsupported —
and those are recorded `unsupported`:

`/system/timezone` · `/dhcp-servers/pool` · `/radius-servers/server/host` +
`/radius-servers/server/key`

## The VLAN surface is dot1q harvest, not campus L2

VLANs are populated on 4 cells (IDs 35, 35, 200, 100) and `id` round-trips on
all four. Every other `vlans[]` sub-field is empty on **every** cell, because
IOS-XR does not have campus VLAN records at all — the codec harvests the ID
from `encapsulation dot1q <N>` on a sub-interface. Verified directly: on all
four cells each VLAN record carries an `id` and nothing else — `name` `''`,
`description` `''`, `ipv4_addresses` `[]`, `untagged_ports` `[]`,
`tagged_ports` `[]`.

So `vlans[].untagged_ports` / `tagged_ports` / `description` /
`ipv4_addresses` are source-side gaps, and the L3 address for those VLANs
lives on the sub-interface record (`GigabitEthernet0/0/0/1.35`), which
round-trips cleanly under `interfaces[].ipv4_addresses`.

`vlans[].name` is the one exception worth flagging: **both** codecs declare
`/vlans/vlan/name` supported, so it is recorded `good` — but no committed cell
populates it, so that `good` rests on the two declarations, not on an observed
round-trip. Same for `dns_servers` and `syslog_servers`.

## Two matrix observations, recorded not fixed

**1. `cisco_iosxr` under-declares `/system/domain`.** Its matrix lists the path
nowhere — not supported, not lossy, not unsupported — yet the codec parses
`domain name <x>` and the value is preserved on all 8 cells that carry one
(`test.com`, `test.lab`, `lab.com`, `lab.example.net`). The disposition below
is `good` on the measurement. The missing declaration is a matrix gap, not a
pair fact, and belongs in a codec change.

**2. The VRF surface survives by name only, and the RD does not travel with
it.** `routing_instances[].name` is preserved on all 8 populated cells and
`routing_instances[].description` on the one cell that sets it — both `good`.
But `cisco_iosxr` declares `/routing-instances/instance` itself **lossy**, and
`cisco_nxos` declares `/routing-instances/instance/route-distinguisher`,
`/rt-imports` and `/instance-type` lossy. None of those paths is a key in this
pair's expectation set, so nothing below claims them.

This matters for a PE migration specifically: IOS-XR derives the VRF RD from
`router bgp` (the ASN-from-RD-admin harvest), and `router bgp` itself is
declared **unsupported** as Tier-3 on the source side. A `good` on
`routing_instances[].name` means the VRF *names* arrive. It does not mean the
L3VPN arrives. Re-author RD, route-targets and the BGP address-families on the
Nexus by hand.

## Correlated drift — what does and does not corroborate what

Only two interface sub-fields drift on this pair, and they drift for unrelated
reasons: `interface_type` because NX-OS re-infers the type from a name prefix
it does not recognise, `lag_member_of` because the LAG is rebuilt from
`channel-group <N>`. Neither is evidence for the other, and neither is evidence
for `lags`.

`lag_member_of` and `lags` *do* share one mechanism — that is why the YAML
states the shared cause once and cross-references it rather than counting it
twice.

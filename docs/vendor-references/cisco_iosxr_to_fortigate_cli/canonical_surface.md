# IOS-XR → FortiGate CLI: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/cisco_iosxr__fortigate_cli.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`, plus a
direct `parse -> render -> re-parse` round-trip over all 12 cells for the calls
the drift shape alone could not settle. Per-key dispositions were resolved
through the audit's own `actual_disposition()` rather than inferred from the
drift shape, so this file and the ratchet agree by construction.

- Fixture cells: **12**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the measured mesh run, and round-trips run by hand against the
> committed fixtures. Where a disposition rests on a declaration rather than an
> observed round-trip, the YAML says so explicitly.

## Device-class framing

`cisco_iosxr` in this corpus is a **service-provider edge/core router**:
4-segment interface names (`GigabitEthernet0/0/0/1`), channelized and dot1q
sub-interfaces, `Bundle-Ether` aggregates, BVIs, `MgmtEth0/RP0/CPU0/0`, and a
heavy VRF surface with the RD harvested from `router bgp`. `fortigate_cli` is a
**firewall edge**: every port routed, no switchport surface at all, tenancy
expressed as a VDOM rather than a VRF, no fabric surface.

The realistic migration is a PE/CE router replaced at the L3 boundary by a
FortiGate that inherits the routed interfaces, their addressing, the aggregates
and the static routing. What it cannot inherit is the multi-VRF structure the
IOS-XR box exists to provide.

## The structural finding

The interface inventory does **not** shrink on this pair — it **grows**, and
that inversion is the single most important thing to know before reading the
drift numbers.

Corpus-wide: **156 interface records in, 160 out. Zero lost, four added.**

The four additions are on the four cells that carry a canonical VLAN
(`batfish_ebgp_border01`, `batfish_ebgp_border02`,
`iosxr_design_cst_pa3_xr752`, `kitchen_sink`): 15 → 16, 15 → 16, 55 → 56,
9 → 10. The FortiOS renderer synthesises an 802.1Q child interface for every
canonical VLAN —

```
edit "vlan35"
    set type vlan
    set vlanid 35
    set interface "Loopback123"
next
```

— and the re-parse reads each one back as a new interface record. That
record-count change is what the comparator sees on the parent list, which is
why every `interfaces[].*` sub-field measures as drifted on exactly those 4
cells regardless of whether its own value changed.

Two consequences worth acting on before pushing a render:

1. **The synthesised child is misparented on every cell.** The renderer
   resolves the parent as the first `CanonicalLAG` on the tree, falling back to
   a LAN-preference scorer when there is none
   (`netcanon/migration/codecs/fortigate_cli/render.py`,
   `_vlan_child_interfaces`). Measured: `vlan200` lands on `Bundle-Ether321`,
   `vlan100` on `Bundle-Ether1`, and — on both `batfish_ebgp_border0*` cells —
   `vlan35` lands on **`Loopback123`**, a loopback. On IOS-XR the VLAN's real
   parent is the dot1q sub-interface's physical port
   (`GigabitEthernet0/0/0/1.35` → `GigabitEthernet0/0/0/1`). Re-parent the
   children by hand.
2. **Unlike the AOS-CX source, there is no duplicate-address hazard here.** The
   synthesised children carry no IP on any of the 4 cells, because IOS-XR mounts
   L3 on the dot1q sub-interface record rather than on the VLAN record. The
   addressing stays where it was, on a surviving interface record.

## The loss the structural collapse hides

`interfaces[].vrf` is the largest genuine per-record loss on this pair and it
has **no key of its own** in the expectation YAML, so it is recorded here.

Measured by direct round-trip: **16 of the 156 interface records arrive with a
non-empty `vrf` emptied**, across 8 of the 12 cells —

| cell | records losing `vrf` |
|---|---|
| batfish_ebgp_border01 | `Loopback123`, `GigabitEthernet0/0/0/1.35` (`AZURE`) |
| batfish_ebgp_border02 | `Loopback123`, `GigabitEthernet0/0/0/1.35` (`AZURE`) |
| batfish_vpnv4_pe1 | `MgmtEth0/RP0/CPU0/0`, `Gi0/0/0/2`, `Gi0/0/0/3` |
| batfish_vpnv4_pe2 | `MgmtEth0/RP0/CPU0/0`, `Gi0/0/0/1` |
| batfish_vpnv4_pe3 | `MgmtEth0/RP0/CPU0/0`, `Gi0/0/0/2` |
| xrdtools_sr_xrd1 | `Gi0/0/0/2` (`100`) |
| xrdtools_srv6_pe1 | `Gi0/0/0/0` (`CUSTOMER`) |
| kitchen_sink | `Gi0/0/0/1`, `Gi0/0/0/1.100`, `MgmtEth0/RP0/CPU0/0` |

The mesh comparator sees only **9** of those 16, on 5 cells. The other 7 sit on
the 4 cells where the interface list changes length, and there the drift record
is the wholesale string `count drift: N → N+1 (interfaces)` with no per-record
slice — the count change masks them.

This is the same event as `routing_instances[].name`: the VRF is not modelled by
the target, so both the instance and every binding to it disappear. It is
recorded once, under `routing_instances[].name`. **Do not read the two as
independent corroboration.**

## Per-field measurement (12 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 12 | 0 | 0 |
| domain | 8 | 0 | 4 |
| ntp_servers | 1 | 0 | 11 |
| interfaces (record count) | 8 | 4 | 0 |
| vlans[].id | 4 | 0 | 8 |
| vlans[].name | 0 | 4 | 8 |
| static_routes | 3 | 3 | 6 |
| lags | 4 | 0 | 8 |
| local_users[].name | 9 | 0 | 3 |
| local_users[].role | 0 | 9 | 3 |
| local_users[].hashed_password | 0 | 9 | 3 |
| routing_instances | 0 | 8 | 4 |

Fields trivially empty on all 12 cells: `dns_servers`, `timezone`,
`syslog_servers`, `vlans[].ipv4_addresses`, `vlans[].untagged_ports`,
`vlans[].tagged_ports`, `vlans[].description`, `dhcp_servers`, every `snmp.*`
sub-field, `radius_servers`, every `vxlan_vnis[].*` sub-field,
`evpn_type5_routes`, `raw_sections`, `apply_groups`, `group_content`,
`anycast_gateway_mac`.

### Interface sub-fields, measured on records present on both sides

| sub-field | drifting records (of 156) |
|---|---|
| enabled | 0 |
| mtu | 0 |
| ipv4_addresses | 0 |
| ipv6_addresses | 0 |
| lag_member_of | 0 |
| interface_type | 2 |
| description | 4 |
| vrf | 16 |

The `description` and `interface_type` drift is real but **comparator-invisible
on this corpus**: all 6 records are on `iosxr_design_cst_pa3_xr752.cfg`, which
is also one of the 4 count-drift cells, so the mesh never emits a per-record
slice for them.

- **description** — 4 records truncated to exactly 25 characters
  (`Bundle-Ether500` 30 → 25, `GigabitEthernet0/0/0/12` 58 → 25,
  `TenGigE0/0/0/25` 33 → 25, `BVI500` 43 → 25); in each case the surviving text
  is the first 25 characters of the source. fortigate_cli declares
  `/interfaces/interface/config/description` lossy for exactly this reason
  ("FortiOS limits alias to 25 characters").
- **interface_type** — 2 records, `BVI500` and a `preconfigure` record, both
  `ianaift:other` → `ianaift:ethernetCsmacd`. All 18 `ianaift:softwareLoopback`
  records in the corpus survive with their type intact.

## Source-side gaps vs target-side drops vs symmetric gaps

Three distinct shapes hide behind "the field is empty on both sides", and the
YAML uses a different disposition for each.

**Source-side gap → `not_applicable`.** cisco_iosxr declares these unsupported
at the exact path (or never emits them on this corpus), while fortigate_cli
would hold them — so re-authoring on the FortiGate sticks:

`/snmp/community` and the `/snmp/v3-user/*` children · `/dhcp-servers/pool` ·
`/radius-servers/server/host` + `/key` · `/evpn-type5-routes/route` ·
the VLAN-mounted L3 surface (`vlans[].ipv4_addresses`, `vlans[].description`)

The IOS-XR parser produces **no SNMP block at all** on any of the 12 cells —
`intent.snmp` is `None` everywhere — while fortigate_cli declares five `/snmp/*`
paths supported. Every SNMP setting is greenfield work on the target.

**Target-side drop → `unsupported`.** cisco_iosxr declares
`/system/syslog-server` **supported**; fortigate_cli declares it unsupported
("Render emits no logging/syslog config; intent.syslog_servers are dropped on
migration"). Calling this `not_applicable` would imply re-authoring helps; it
does not, because the renderer would drop it again.

**Symmetric gap → `unsupported`.** Both matrices declare these unsupported:
`/system/timezone` · `/vlans/vlan/untagged-ports` + `/tagged-ports` ·
`/vxlan-vnis/vni` + `/source-interface` + `/udp-port` · `/anycast-gateway-mac`.

## Three findings worth carrying forward

**1. VRFs are the concept this pair cannot carry, and it is the whole point of
the source device.** All 15 routing instances across 8 cells are dropped —
`AZURE`, `red` / `blue` / `management` (on three PEs), `100`, `CUSTOMER`,
`CUSTOMER-A` / `MGMT`. fortigate_cli declares `/routing-instances/instance`
unsupported in those words ("Render emits no VRF/routing-instance construct
(VDOMs not modelled)"). The render contains no VDOM stanza and no per-route
VRF binding anywhere. The knock-on effects are the 16 interface `vrf` bindings
above and the 3 static routes below; all three are the same event.

**2. Static routes survive, their VRF binding does not — and that is a
forwarding change, not a cosmetic one.** 20 routes across 6 cells, 20 after the
round-trip, with destination, gateway, outgoing interface and metric identical
on every one; the FortiOS render even preserves the discard route as
`set dst 192.0.2.0 255.255.255.0 / set device "Null0"`. The 3 routes that carry
a VRF (`AZURE` on `batfish_ebgp_border02`, `blue` on `batfish_vpnv4_pe1`,
`CUSTOMER-A` on `kitchen_sink`) all arrive with `vrf` empty, which lands them in
the global table. fortigate_cli declares `/routing/static-route/vrf`
unsupported ("Per-VRF static-route binding parses-and-ignores in v1"). Recorded
`lossy` at the list level because the route records themselves survive — which
is what `lossy`'s compatible=True is for — but a customer route leaking into the
global table is the kind of loss to catch before cutover, not after.

**3. LAGs survive completely, against the expectation the arista_eos pair
sets.** 10 `Bundle-Ether` records across 4 cells round-trip byte-identical on
name and members, rendering as
`edit "Bundle-Ether1" / set type aggregate / set member ... / set lacp-mode
active`, and `interfaces[].lag_member_of` is identical on every member port.
On `cisco_iosxr__arista_eos` the same surface is dropped entirely — do not
generalise from one pair to the other. Note also that fortigate_cli declares
**nothing** for `/lags/lag` — not supported, not lossy, not unsupported — while
rendering the surface faithfully. That is a target matrix under-declaration,
left for a codec change rather than fixed here.

## Credential material

`local_users[].hashed_password` drifts on all 9 cells that populate local users,
and the two failure modes are different enough that both need stating. Measured
across 14 user records:

- **11 of 14 lose the credential entirely.** Every IOS-XR **type-5** (crypt
  `$1$`) and **type-7** (the reversible vendor-obfuscated form) secret is
  dropped. The renderer is explicit about it rather than silent — it emits a
  review comment in place of the password line, of the form
  `# password manager user-name "<name>" -- review: <type> hash from source
  vendor cannot be re-used on FortiOS; reset this user password manually` — and
  the re-parse yields an empty `hashed_password`.
- **3 of 14 keep their bytes but not their meaning.** IOS-XR **type-10** (crypt
  `$6$`, SHA-512) secrets are re-emitted behind a FortiOS `set password ENC`
  marker; the canonical string grows by exactly the 12 characters of the
  `fortios:ENC ` prefix and is otherwise unchanged. A FortiGate decrypts `ENC`
  material with FortiOS-internal key material, so a crypt hash presented as a
  FortiOS `ENC` blob is not a password any FortiGate can authenticate.

Every migrated account therefore arrives **without a working credential**. Set
passwords on the target before cutover.

Hash bodies and ciphertext are deliberately not reproduced in this file or in
the expectation YAML — only the crypt-scheme marker, the type number and the
length are described. Per `AGENTS.md`, encrypted secrets are operator-traceable
even when encrypted, and a document that quotes the value it describes defeats
its own redaction.

`local_users[].role` is a deliberate remap rather than a loss: 13 of 14 records
change, all the same way — IOS-XR `root-lr` renders to the FortiOS
`super_admin` accessprofile. It is scoped, not blanket: the single `operator`
account (`readonly` on `kitchen_sink`) passes through unchanged. The privilege
intent is arguably preserved, but `super_admin` on a FortiGate is unrestricted
access — review the mapping before any migrated account becomes production.

## Reproducing these numbers

```
py tools/run_full_mesh.py                    # mechanical drift matrix
py tools/run_phase4_reconciliation.py        # variance classification
```

The per-record round-trip counts above were taken by parsing each fixture with
`get_codec("cisco_iosxr")`, rendering with `get_codec("fortigate_cli")` and
re-parsing the render, then diffing attribute-by-attribute on records present on
both sides.

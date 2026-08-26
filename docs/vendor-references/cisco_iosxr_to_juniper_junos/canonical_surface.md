# IOS-XR → Junos: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/cisco_iosxr__juniper_junos.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key
dispositions were resolved through the audit's own `actual_disposition()` rather
than inferred from the drift shape, so this file and the ratchet agree by
construction. Every record-level count below was additionally re-derived by
round-tripping each fixture directly
(`juniper_junos.parse(juniper_junos.render(cisco_iosxr.parse(raw)))`) so no
claim rests on a single sampled drift entry.

- Fixture cells: **12** (11 real captures + the synthetic kitchen sink)
- Render errors: **0** · re-parse errors: **0**
- Source interface records across all cells: **156**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations and the measured mesh run. Where a disposition rests on a
> declaration rather than an observed round-trip, the YAML says so explicitly.

## Device-class framing

`cisco_iosxr` in this corpus is a **service-provider edge/core router** —
4-segment interface names (`TenGigE0/0/0/18`), `Bundle-Ether` LAGs, VPNv4 PEs,
IS-IS / SR / SRv6 lab configs, and a heavy VRF surface with RDs derived from
`router bgp`. `juniper_junos` is a **general-purpose Junos router** and is the
closest device-class match of any target in the mesh.

The consequence runs the opposite way to the campus pairs: the routing surface
is where the fidelity is, and the campus L2 surface is not thin so much as
**structurally absent on the source**. IOS-XR carries no switchport model at
all — `cisco_iosxr` declares `/interfaces/interface/switchport-mode`,
`/access-vlan`, `/trunk-allowed-vlans` and `/trunk-native-vlan` unsupported —
so VLAN port membership, VLAN SVI addressing and VLAN descriptions are never
populated from this source and cannot be lost by Junos.

## The structural finding: there isn't one

This is the load-bearing difference from the campus pairs, and it is worth
stating first because it inverts the usual authoring trap. **The interface
inventory does not shrink.** All 156 source interface records survive by name
on all 12 cells; the target list is the same length on every cell (15 → 15,
17 → 17, 55 → 55, …).

So the `interfaces[].*` sub-fields are genuinely independent here. Where one
is `good`, that is a measurement of the attribute itself, not a record that
happened to survive. Per-record comparison across all 156 records finds **zero**
mismatches on `name`, `description`, `enabled`, `mtu`, `ipv4_addresses` and
`ipv6_addresses`.

The two `interfaces[].*` losses below are attribute-level and each has its own
independent cause. Neither is cited as evidence for the other.

## Per-field measurement (12 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 12 | 0 | 0 |
| domain | 8 | 0 | 4 |
| ntp_servers | 1 | 0 | 11 |
| interfaces[].name / .description / .enabled | 12 / 9 / 12 | 0 | 0 / 3 / 0 |
| interfaces[].mtu | 4 | 0 | 8 |
| interfaces[].ipv4_addresses / .ipv6_addresses | 12 / 3 | 0 | 0 / 9 |
| interfaces[].interface_type | 0 | 12 | 0 |
| interfaces[].lag_member_of | 0 | 4 | 8 |
| vlans[].id | 4 | 0 | 8 |
| vlans[].name | 0 | 4 | 8 |
| static_routes | 1 | 5 | 6 |
| lags | 0 | 4 | 8 |
| local_users[].name / .role | 5 | 4 | 3 |
| local_users[].hashed_password | 0 | 9 | 3 |
| routing_instances[].name | 8 | 0 | 4 |
| routing_instances[].description | 1 | 0 | 11 |

Fields trivially empty on all 12 cells: `dns_servers`, `timezone`,
`syslog_servers`, `interfaces[].vrrp_groups`, `vlans[].ipv4_addresses`,
`vlans[].untagged_ports`, `vlans[].tagged_ports`, `vlans[].description`,
`dhcp_servers`, every `snmp.*` key, `radius_servers`, every `vxlan_vnis[].*`
key, `evpn_type5_routes`, `raw_sections`, `apply_groups`, `group_content`,
`anycast_gateway_mac`.

## Source-side gaps vs target-side drops vs symmetric gaps

`cisco_iosxr` declares these **unsupported at the exact path**, so as a
*source* it never emits them and there is nothing for Junos to lose. They are
recorded `not_applicable`:

`/dhcp-servers/pool` · `/snmp/community` · `/snmp/v3-user/*` ·
`/vxlan-vnis/*` · `/evpn-type5-routes/route` ·
`/interfaces/interface/vrrp-groups/group/*` · the four switchport paths

The distinction is operational rather than cosmetic. For `dhcp_servers`,
`snmp.*` and `vxlan_vnis[].*`, **juniper_junos declares those paths
SUPPORTED** — `/snmp` alone has four supported child paths — so re-authoring
them on the Junos side will stick, and a migration report should say so rather
than implying the target cannot hold them. `snmp` in particular is measured
`None` on the source side of all 12 cells: the IOS-XR parser produced no SNMP
block from any committed fixture.

Two fields are **symmetric** gaps — both matrices declare them unsupported —
and those are `unsupported`, not `not_applicable`:

- `timezone` (`/system/timezone` on both sides). Confirmed by injection rather
  than left on the declarations: setting `intent.timezone = "UTC"` on a parsed
  kitchen sink and rendering produces no `set system time-zone` line, and the
  value re-parses empty.
- `anycast_gateway_mac` (`/anycast-gateway-mac` on both sides).
- `radius_servers` is the third: both codecs declare
  `/radius-servers/server/host` and `/radius-servers/server/key` unsupported.
  Neither parses nor renders AAA RADIUS config, so a shared secret cannot
  survive because it never enters the canonical intent.

## Fields declared nowhere that round-trip anyway

Three fields are `good` on measured behaviour while the **target** matrix
declares nothing for them. This is a matrix under-declaration on
`juniper_junos`, not a pair-specific fact, and is recorded here rather than
fixed by a codec change:

- `domain` — neither matrix declares `/system/domain`; preserved on all 8
  populated cells.
- `ntp_servers` — `cisco_iosxr` declares `/system/ntp-server` supported,
  `juniper_junos` declares nothing; preserved on the 1 populated cell.
- `dns_servers` — same shape. No committed cell populates it, so this rests on
  an injection probe rather than a corpus observation: setting
  `dns_servers = ["192.0.2.53", "198.51.100.53"]` on a parsed intent renders
  `set system name-server …` and re-parses identically. `syslog_servers`
  behaves the same way (`set system syslog host … any any`) and is declared
  supported on both sides.

## Four findings worth carrying forward

### 1. `interface_type` survives only for loopbacks

`interfaces[].interface_type` drifts on all 12 cells — but the shape matters.
Of 156 records, **18 preserve the type and all 18 are `ianaift:softwareLoopback`**.
The 138 that drift to `""` break down as 126 `ianaift:ethernetCsmacd`,
10 `ianaift:ieee8023adLag` and 2 `ianaift:other`. So the Junos render carries
the loopback type through and emits nothing the re-parse can use to recover a
physical or bundle type. `cisco_iosxr` independently declares
`/interfaces/interface/config/type` lossy in its own matrix, which agrees.

The interface record itself survives intact, so this is `lossy`, not
`unsupported`.

### 2. `lags` is the naming artifact here — but the rename splits the bundle

The evidence dossier flags a bare `lags` drift as usually the known
cross-vendor naming artifact. That is what this is, and it was probed rather
than assumed: the LAG count is identical on all 4 cells that carry bundles
(2 → 2, 2 → 2, 5 → 5, 1 → 1) and every member interface keeps its membership.
What changes is the name, `Bundle-Ether23` → `ae23`.

The audit's LAG-name canonicalisation (`_LAG_NAME_FIELDS` /
`_canonical_lag_name`) collapses `ae1` ↔ `Port-channel1` ↔ `trk1` ↔ `bond1`,
but its regex admits only `ae|Po|Port-channel|Port-Channel|trk|Trk|agg|bond`.
IOS-XR's `Bundle-Ether<N>` is **not** in that set, so the rename scores as
drift on both `lags` and `interfaces[].lag_member_of`. Those two are the same
mechanism observed twice; neither corroborates the other.

There is a real hazard underneath the cosmetic rename, visible only by reading
the render. On the kitchen sink the output contains **both**:

```
set interfaces GigabitEthernet0/0/0/3 ether-options 802.3ad ae1
set interfaces Bundle-Ether1 description "backbone bundle"
set interfaces Bundle-Ether1 unit 0 family inet address 10.0.0.1/31
set interfaces ae1 aggregated-ether-options lacp active
```

The bundle's L3 configuration stays on an interface named `Bundle-Ether1`
while LACP membership binds to `ae1`. The addressing and the member ports land
on two different interface names on the target. Re-home the bundle addressing
onto `ae<N>` by hand after cutover.

### 3. A `vlans[].name` is invented, not dropped — and the dot1q tag *is* dropped

IOS-XR VLANs in this corpus come from 802.1Q subinterface encapsulation
(`GigabitEthernet0/0/0/1.100` with `encapsulation dot1q 100`) plus one BVI, so
the source carries a VLAN id with an **empty** name. Junos has no anonymous
VLAN object — `set vlans <name> vlan-id <id>` requires a name — so the render
synthesises `VLAN-<id>` (`set vlans VLAN-35 vlan-id 35`) and the re-parse reads
that back. The drift on all 4 populated cells is therefore an addition on the
target side, not a loss on the source side. It is still a fidelity drift: the
canonical value changed, and a later diff or reverse migration will not see the
source's name.

Separately, and **not** as corroboration of the above: the subinterface's
encapsulation tag does not survive. `interfaces[].dot1q_vlan` drifts on 4
records (100 → `None` on the kitchen sink), because the render emits the
subinterface as a literal name plus `unit 0`
(`set interfaces GigabitEthernet0/0/0/1.100 unit 0 family inet address …`)
rather than `unit 100 vlan-id 100`. The record, its description and its address
all survive; only the tag is gone. **There is no audited YAML key for
`interfaces[].dot1q_vlan`**, so this loss is invisible to the ratchet and is
recorded here instead.

### 4. Static routes: gateway-less routes vanish silently

`static_routes` drifts on 5 of the 6 populated cells. `juniper_junos` declares
`/routing/static-route/interface` unsupported with the reason "render emits
`next-hop <gateway>` only; a gateway-less / interface-only (connected) static
route is dropped", and the corpus behaves exactly that way:

| cell | src → tgt | what went |
|---|---|---|
| `batfish_ibgp_border01` | 1 → 0 | `192.0.2.1/32` via `Null0` |
| `xrdtools_sr_xrd1` | 1 → 0 | `0.0.0.0/1` via `Null0` |
| `kitchen_sink` | 4 → 3 | `192.0.2.0/24` via `Null0` |
| `iosxr_design_cst_pa3_xr752` | 12 → 10 | `2001:db8:23:23::2/128` via `BVI500`, plus one exact-duplicate route collapsing |
| `batfish_vpnv4_pe1` | 1 → 1 | route survives; its `interface` attribute empties |

The routes that disappear are discard/blackhole routes (`Null0`) and an
interface-only IPv6 route. A null route silently not arriving is the
security-relevant case: traffic the source deliberately blackholed is forwarded
by the target. Routes carrying a gateway survive with destination, gateway and
VRF intact, which is why this is `lossy` at the list level rather than
`unsupported`.

The duplicate collapse on `iosxr_design_cst_pa3_xr752` is benign: the source
carries `192.0.2.0/8` via `198.51.100.1` twice with identical attributes, and
the pair re-parses once.

## Credential material

Two distinct things happen to `local_users`, and they must not be conflated.

**Accounts without an encrypted secret are dropped entirely.** On
`batfish_vpnv4_pe1` the source carries one account whose secret is a bare
plaintext token with no crypt(3) marker; the render emits **no**
`set system login user` line at all and the target parses zero users. The same
happens to 1 of 2 accounts on `batfish_vpnv4_pe2` and `batfish_vpnv4_pe3`, and
to 2 of 3 on `iosxr_design_cst_pa3_xr752` — 4 cells, and on one of them the
device's only account. The account name, class and privilege all go with it.
This is why `local_users[].name` carries the record-level loss for the list.

**Accounts with a crypt hash survive, and the hash body survives byte for
byte.** The drift on `local_users[].hashed_password` is a change of vendor type
marker, not of key material: the IOS-XR side carries a numeric type marker
ahead of the crypt string, the render passes that marker through into the Junos
`encrypted-password` value, and the Junos parser prefixes its own `junos:`
tag. Verified without printing the secret by substring-testing the stripped
crypt body against the target value: it is present on every surviving account.

Two cautions on that survival:

- The render writes the IOS-XR numeric type marker *inside* the Junos
  `encrypted-password` string. Whether a real Junos device accepts that form
  was not tested here and is not claimed.
- `privilege_level` re-parses as `1` on every surviving account regardless of
  its source value (15 on most of this corpus). Junos carries the authorisation
  in `class`, which round-trips correctly (`root-lr` → `root-lr`,
  `operator` → `operator`), so `local_users[].role` is `good`. There is no
  audited YAML key for `local_users[].privilege_level`, so — like
  `interfaces[].dot1q_vlan` — this drift is recorded here rather than declared.

No hash, ciphertext or plaintext secret is reproduced in this file or in the
expectation YAML. Per `AGENTS.md`, a document that quotes the value it
describes defeats its own redaction; only the shape (marker, family, length
delta) is stated.

## A note on `local_users[].role`

`local_users[].role` is declared `good` even though the mesh records it as
drifted on 4 cells. That is deliberate and is the rule that failed six
declarations on the previous wave. The drift on those 4 cells is purely the
parent list changing length — the same dropped accounts described above — and
the reconciler's structural-only collapse assigns that signal to the first
`local_users[].*` key in YAML order, which is `local_users[].name`. A loss
declared on `role` could never be evidenced by any cell, so it would fail the
per-pair unevidenced ratchet by construction. On every account that survives,
the role is intact.

The same reasoning explains why the YAML's key order is not alphabetical: it
follows the order the reconciler iterates, so `local_users[].name` claims the
structural signal before its siblings are considered.

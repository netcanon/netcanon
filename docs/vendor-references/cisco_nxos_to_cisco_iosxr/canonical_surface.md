# NX-OS → IOS-XR: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/cisco_nxos__cisco_iosxr.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key
dispositions were resolved through the audit's own `actual_disposition()`
rather than inferred from the drift shape, so this file and the ratchet agree
by construction. Every claim below that goes *beyond* the reconciled table was
additionally reproduced by hand — parse with `cisco_nxos`, render with
`cisco_iosxr`, re-parse — and the four such claims are called out explicitly in
"Claims reproduced by hand" at the end.

- Fixture cells: **13**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations and the measured mesh run. Where a disposition rests on a
> declaration rather than an observed round-trip, the YAML says so explicitly.

## Device-class framing

`cisco_nxos` in this corpus is a **DC leaf/spine** — VXLAN/EVPN fabric nodes,
HSRP-fronted SVIs, campus-style L2 trunks. `cisco_iosxr` is a **service-provider
edge/core router**: 4-segment interface names, RD derived from `router bgp`, a
heavy VRF surface, and **no campus L2 model at all**.

That asymmetry is the whole story of this pair, and it is the opposite shape
from the AOS-CX pairs. There the interface *inventory* shrank. Here it does
not — the losses are clean, whole-subsystem drops of the things an SP router
does not model, sitting alongside a routed/VRF surface that crosses almost
untouched.

## The structural finding: the interface list does NOT shrink

Worth stating first because it is the assumption most other pairs in this mesh
teach you to make, and it is wrong here. **Zero of 13 cells lose an interface
record.** The counts are identical end to end — 129→129, 131→131, 134→134,
72→72, 12→12.

Consequence: on this pair the per-`interfaces[].*` dispositions are *independent
measurements*, not shadows of a record drop. `interfaces[].description`,
`.enabled`, `.mtu`, `.ipv6_addresses` and `.name` are `good` because they were
each measured intact on every surviving record — **0 per-record mismatches
across all 13 cells** — not because the audit is blind to them. Conversely,
`interfaces[].ipv4_addresses`, `.interface_type`, `.lag_member_of` and
`.vrrp_groups` each drift for their own, separately identified reason.

This matters for the anti-correlation rule: none of the four interface losses
below corroborates any of the others. They have four different causes.

## What is dropped wholesale

Four subsystems vanish entirely. NX-OS carries them; the IOS-XR render emits
nothing for them; re-parsing the render yields empty.

| subsystem | measured | target declaration |
|---|---|---|
| VLANs | 84 source VLANs → **0**, on 13/13 cells; render contains no `vlan` line | *(over-declared — see below)* |
| SNMP | `intent.snmp is None` on 11/11 populated cells | `/snmp/community` UNSUPPORTED — "SNMP parse + render is out of the v1 XR scope" |
| VXLAN VNIs | all VNIs dropped on 8/8 populated cells | `/vxlan-vnis/vni`, `/vxlan-vnis/source-interface`, `/vxlan-vnis/udp-port` UNSUPPORTED |
| FHRP groups | 4 HSRP groups → **0**, on 4/4 populated cells | `/interfaces/interface/vrrp-groups/group` UNSUPPORTED — "out of the v1 IOS-XR scope" |

Plus the chassis-wide `anycast_gateway_mac`, dropped to `''` on all 7 cells
that set it (`/anycast-gateway-mac` UNSUPPORTED).

All five are recorded **`unsupported`, not `lossy`** — a vanished record is not
lossy (#436). `lossy` warns and stays `compatible=True`, which would understate
a total drop into a subsystem that has no target grammar to degrade into.

### A target-matrix over-declaration on VLANs

`cisco_iosxr` declares **`/vlans/vlan/id` and `/vlans/vlan/name` SUPPORTED**,
and declares nothing unsupported under `/vlans`. The render drops every VLAN
anyway, on every cell.

This is not a pair-specific fact and it is not a judgement call — it is
reproduced below. It is recorded here and in the YAML as an over-declaration in
the IOS-XR matrix, and left for a codec change rather than papered over in a
per-pair expectation file. The disposition follows the measurement, not the
declaration.

(The declaration is *coherent* with the rest of the IOS-XR matrix, which is
what makes it easy to miss: XR declares `/interfaces/interface/switchport-mode`,
`/access-vlan`, `/trunk-allowed-vlans` and `/trunk-native-vlan` all unsupported
because "IOS-XR is SP-routing with no L2 switchport model; VLANs are dot1q
sub-interfaces". Everything *around* the VLAN record is honestly declared; the
VLAN record itself is not.)

## The LAG trap — this drift is a rename, not a loss

The evidence dossier flags `lags` as a trap, and on this pair the trap is live.

`lags` drifts on 5 of 5 populated cells and `interfaces[].lag_member_of` drifts
on the same 5. **On all 5, the bundle number and the exact member set survive.**

```
port-channel1    ['Ethernet1/3','Ethernet1/4']  →  Bundle-Ether1    ['Ethernet1/3','Ethernet1/4']
port-channel2002 ['Ethernet1/6']                →  Bundle-Ether2002 ['Ethernet1/6']
port-channel10   ['Ethernet1/3']                →  Bundle-Ether10   ['Ethernet1/3']
port-channel999  ['Ethernet1/6','Ethernet1/7']  →  Bundle-Ether999  ['Ethernet1/6','Ethernet1/7']
```

The render emits `bundle id <N> mode active` on each member. Nothing is lost
except the *name*.

The reason it registers as drift at all is that the audit's LAG-name
canonicaliser does not cover either end of this rename. `_LAG_NAME_RE` in
`tools/run_phase4_reconciliation.py` matches
`ae|Po|Port-channel|Port-Channel|trk|Trk|agg|bond` — it does **not** match
NX-OS's lowercase `port-channel<N>`, and it does not match IOS-XR's
`Bundle-Ether<N>`. Both sides canonicalise to `None`, the comparison falls
through to raw equality, and a vendor-correct rename surfaces as drift.

Both keys are therefore `lossy`, and the reason says exactly this: the
identity changes, the aggregation does not. The operational exposure is
name-based references — monitoring, scripts, anything keyed on
`port-channel1` — not forwarding. Extending `_LAG_NAME_RE` to cover these two
shapes is a reconciler change, deliberately not made from a per-pair
expectation file.

## Per-field measurement (13 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 13 | 0 | 0 |
| domain | 2 | 0 | 11 |
| ntp_servers | 1 | 0 | 12 |
| syslog_servers | 1 | 0 | 12 |
| interfaces[].name | 13 | 0 | 0 |
| interfaces[].enabled | 13 | 0 | 0 |
| interfaces[].description | 9 | 0 | 4 |
| interfaces[].mtu | 6 | 0 | 7 |
| interfaces[].ipv6_addresses | 3 | 0 | 10 |
| interfaces[].ipv4_addresses | 9 | 4 | 0 |
| interfaces[].interface_type | 0 | 13 | 0 |
| interfaces[].lag_member_of | 0 | 5 | 8 |
| interfaces[].vrrp_groups | 0 | 4 | 9 |
| vlans[].* (all sub-fields) | 0 | 13 | 0 |
| static_routes | 8 | 0 | 5 |
| snmp.community / location / contact / trap_hosts | 9 | 2 | 2 |
| snmp.v3_users | 0 | 11 | 2 |
| lags | 0 | 5 | 8 |
| local_users[].name / role / hashed_password | 9 | 0 | 4 |
| vxlan_vnis[].* (all sub-fields) | 0 | 8 | 5 |
| routing_instances[].name | 12 | 0 | 1 |
| routing_instances[].description | 1 | 0 | 12 |
| anycast_gateway_mac | 0 | 7 | 6 |

Trivially empty on all 13 cells: `dns_servers`, `timezone`, `dhcp_servers`,
`radius_servers`, `evpn_type5_routes`, `raw_sections`, `apply_groups`,
`group_content`.

Note the `snmp.*` scalar row: 9 "preserved" cells are cells where the *source*
carries no community/location/contact either, so `'' → ''` compares equal even
though the target's SNMP record is `None`. The two drifted cells are the two
that actually set the scalars. The subsystem is gone on all 11; only 2 cells
have data with which to prove it on those keys.

## Two per-record degradations that are not drops

**`interfaces[].interface_type`** drifts on all 13 cells, across **1090
interface records**. It is a *downgrade*, not a drop — every record survives and
keeps a type, just a less specific one:

| source | target | records |
|---|---|---|
| `ianaift:ethernetCsmacd` | `ianaift:other` | 1053 |
| `ianaift:l3ipvlan` | `ianaift:other` | 29 |
| `ianaift:ieee8023adLag` | `ianaift:other` | 8 |
| `ianaift:softwareLoopback` | `ianaift:softwareLoopback` | 12 (preserved) |

Both matrices declare `/interfaces/interface/config/type` LOSSY, and the XR
reason explains the mechanism: the XR CLI parser infers type from the name
prefix (`GigabitEthernet`→ethernetCsmacd, `Loopback`→softwareLoopback,
`Bundle-Ether`→ieee8023adLag …), and NX-OS names such as `Ethernet1/1` carry no
prefix XR recognises. Loopbacks survive because `loopback0` *is* a prefix both
sides agree on. `lossy` is the correct call — the declarations and the
measurement agree.

**`interfaces[].ipv4_addresses`** drifts on 4 cells. The IP and prefix-length
set is **identical on all 13 cells** — 0 cells lose an address. What drops is
the anycast companion attribute `virtual_gateway_address`, exactly as
`cisco_iosxr` declares
(`/interfaces/interface/ipv4/address/virtual-gateway-address` UNSUPPORTED —
"IOS-XR has no VARP / anycast-gateway grammar"). Addressing survives;
distributed-anycast first-hop redundancy does not. `lossy`, and the reason says
which half is which.

## What crosses cleanly — and why that is the interesting half

This is a same-vendor, adjacent-platform migration, and the routed surface shows
it. Preserved with zero drift anywhere in the corpus:

- **`hostname`** (13/13), **`domain`** (2/2), **`ntp_servers`** (1/1),
  **`syslog_servers`** (1/1) — the render emits `domain name …`, `ntp` and
  `logging <ip>`.
- **`static_routes`** — destination + gateway match exactly on 8/8 populated
  cells.
- **`routing_instances[].name`** (12/12) and **`.description`** (1/1). The VRF
  surface is XR's home ground and it shows.
- **`local_users[].name` / `.role` / `.hashed_password`** — all 10 user records
  across 4 cells cross byte-identical.

Two honest caveats on that last group, both stated in the YAML rather than left
for a reader to discover:

- The `routing_instances` *record* survives but three sub-fields below the
  audited key set do not: `l3_vni` drops on 7 records (EVPN L3VNI has no v1 XR
  mapping), and the NX-OS `auto` route-target token drops from **both**
  `rt_imports` and `rt_exports` on the **same 6 VRF records across 5 cells** —
  one cause, two sub-fields, not two findings — while explicit numeric RTs
  (`65000:901002`) cross intact. `route_distinguisher` survives on 7/7. So
  "VRF name is `good`" is true and "the VRF arrives complete" is not.
- `local_users[].role` being `good` is not the same as privileges crossing
  intact: `privilege_level` — not an audited key on this pair — collapses
  15 → 1 on 9 records, which `cisco_nxos` honestly declares LOSSY at
  `/local-users/user/privilege-level`. The named role crosses; the numeric
  privilege does not.

## Credential material

`local_users[].hashed_password` is `good` here — genuinely, on all 10 records
across the 4 populated cells, byte-identical after the round-trip. This is the
same-vendor dividend: both codecs speak the same crypt form, so unlike every
cross-vendor pair in this mesh the accounts arrive with **working credentials**.

The hash *shape* only, never a value: NX-OS type-5 marker followed by a
SHA-256-crypt string, lengths 32–55 characters across the corpus. No hash
value is reproduced in this file or in the expectation YAML — per `AGENTS.md`,
crypt material is operator-traceable, and a document that quotes the value it
describes defeats its own redaction.

`snmp.v3_users` is the opposite case and the more urgent one: the whole SNMP
record is dropped, so v3 auth and privacy key material does not reach the
target at all. SNMPv3 users must be re-created on the XR side.

## Claims reproduced by hand

Four statements above are not readable off the reconciled table. Each was
reproduced directly. Script:
`<scratchpad>/nq_repro.py` — parse with `cisco_nxos`, render with
`cisco_iosxr`, re-parse, over all 13 cells of the pair.

```
1. VLANs: 13/13 cells drop ALL vlans (84 source VLANs -> 0);
          cisco_iosxr declares /vlans/vlan/id + /vlans/vlan/name SUPPORTED
2. SNMP : 11/11 populated cells render intent.snmp is None (total drop, not partial)
3. LAGs : 5/5 cells are RENAME-ONLY
          (bundle number + member set identical; port-channel<N> -> Bundle-Ether<N>)
4. Ifaces: 0/13 cells shrink the interface list (no structural interface loss)
```

Claim 2 is also a correction: the mechanical vanish-classifier scored `snmp` as
`partial → lossy` on this pair. It is wrong, for a legible reason — the
heuristic looks at drifting observations, and on 9 of 11 cells the source SNMP
scalars are themselves empty, so the "target empty" test does not fire cleanly.
The target matrix (`/snmp/community` UNSUPPORTED, "out of the v1 XR scope") and
the round-trip both say total. The YAML records `unsupported`.

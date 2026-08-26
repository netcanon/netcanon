# IOS-XR → MikroTik RouterOS: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/cisco_iosxr__mikrotik_routeros.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key
dispositions were resolved through the audit's own `actual_disposition()` rather
than inferred from the drift shape, so this file and the ratchet agree by
construction. Every mechanism described below was additionally re-derived by
hand, parsing each of the 12 fixtures with `cisco_iosxr` and rendering with
`mikrotik_routeros`.

- Fixture cells: **12**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the measured mesh run, the codecs' own source, and hand
> round-trips of the committed fixtures. Where a disposition rests on a
> declaration rather than an observed round-trip, the YAML says so explicitly.

## Device-class framing

`cisco_iosxr` in this corpus is a **service-provider edge/core router** — MPLS
L3VPN PEs, iBGP route-reflectors, eBGP borders, SR/SRv6 lab nodes, plus one
large real-world aggregation chassis (55 interfaces). `mikrotik_routeros` is a
**small-router / ISP-edge OS** whose canonical surface is `/interface ethernet`,
`/interface bridge`, `/interface vlan`, `/interface bonding`, `/ip address`,
`/ip route`, `/user`, `/system identity` and `/system ntp client`.

The two device classes overlap on exactly one thing and it is the thing that
survives: **the routed L3 skeleton**. Interface inventory, admin state,
IPv4/IPv6 addressing, LAG membership and default-VRF static routes all
round-trip. What does not survive is everything that makes the source an SP
box — the VRF/L3VPN construct and the per-VRF half of the routing table — plus
the whole credential and management plane.

## The structural finding, and why the AOS-CX shape does not transfer

On the AOS-CX-sourced pairs the dominant loss is the interface list
**shrinking**, and every `interfaces[].*` sub-field is declared lossy to cover
records that vanish. **That shape is the exact inverse of what happens here and
copying it onto this pair would be wrong.**

Measured across all 12 cells: **not one source interface is lost.** On 8 cells
the count is identical (17→17, 16→16, 6→6, 5→5, 3→3). On the other 4 the list
**grows by exactly two** — 15→17, 15→17, 55→57, 9→11 — and the two added
records are always the same pair, `bridge1` and `vlan<id>`:

```
/interface bridge
add name=bridge1
/interface vlan
add interface=bridge1 name=vlan200 vlan-id=200
```

The RouterOS renderer materialises a bridge plus one L3 VLAN interface for each
canonical VLAN record, because RouterOS has no way to express a VLAN other than
as an interface. The 4 cells that grow are precisely the 4 cells that carry a
VLAN. So `interfaces[].name` drifts on 4 of 12 cells, and the cause is
**synthesis, not deletion**.

Consequence for the expectation file: `interfaces[].name` is `lossy` — the name
list does not round-trip, and after migration nothing distinguishes an
operator-authored interface from one the renderer invented. But the sub-fields
that ride on the record (`description`, `enabled`, `ipv4_addresses`,
`ipv6_addresses`, `lag_member_of`, `vrrp_groups`) are `good`: on this pair the
record always survives, so the only drift those keys show is their parent list
changing length, which `interfaces[].name` already claims. Declaring a loss on
them could never be evidenced by any cell.

## Per-field measurement (12 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 12 | 0 | 0 |
| domain | 0 | 8 | 4 |
| dns_servers | 0 | 0 | 12 |
| ntp_servers | 1 | 0 | 11 |
| timezone | 0 | 0 | 12 |
| syslog_servers | 0 | 0 | 12 |
| interfaces | 0 | 12 | 0 |
| vlans | 0 | 4 | 8 |
| static_routes | 0 | 6 | 6 |
| dhcp_servers | 0 | 0 | 12 |
| snmp | 0 | 0 | 12 |
| lags | 4 | 0 | 8 |
| local_users | 0 | 9 | 3 |
| radius_servers | 0 | 0 | 12 |
| vxlan_vnis | 0 | 0 | 12 |
| evpn_type5_routes | 0 | 0 | 12 |
| routing_instances | 0 | 8 | 4 |
| raw_sections | 0 | 0 | 12 |
| apply_groups | 0 | 0 | 12 |
| group_content | 0 | 0 | 12 |
| anycast_gateway_mac | 0 | 0 | 12 |

The `interfaces` row reading 12/12 drifted is the correlated-drift trap in its
purest form: `interface_type` alone drifts on 146 of the 156 surviving interface
records, which is enough to mark the parent field drifted on every cell. It is
**not** evidence that any other interface attribute is unsafe, and no sibling
key may be cited as corroborating another.

## Sub-field drift, separated by cause

Of the 156 interface records that survive the round-trip across the whole
corpus, exactly three attribute classes drift:

| attribute | records affected | independent of the structural signal? |
|---|---|---|
| `interface_type` | 146 / 156 | **yes** — drifts on all 12 cells including the 8 with no count change |
| `mtu` | 8 / 156 | **yes** — 2 of the 3 affected cells have no count change |
| `description` | 3 / 156 | no — all 3 fall on VLAN-bearing cells |

**`interface_type`.** Both matrices declare `/interfaces/interface/config/type`
lossy, and the target's reason is exact: *"RouterOS does not expose IANA ifType;
the codec infers it from the interface-name prefix (etherN → ethernetCsmacd,
vlanN → l3ipvlan)."* IOS-XR names (`GigabitEthernet0/0/0/0`, `TenGigE0/0/0/20`,
`Bundle-Ether321`, `MgmtEth0/RP0/CPU0/0`) match none of those prefixes, so the
inferred type comes back **empty**; `Loopback0` comes back as
`ianaift:bridge` rather than `ianaift:softwareLoopback`, because RouterOS
expresses a loopback as a bridge. This is a real per-record loss on cells with
no structural change at all.

**`mtu`.** All 8 affected records are `Bundle-Ether*` with `mtu 9216`, on
`batfish_ibgp_border01`, `batfish_ibgp_rr` and `iosxr_design_cst_pa3_xr752`.
The first two have identical interface counts (17→17, 16→16), so this is
independent of the structural signal. The mechanism is visible in the render:
the `/interface ethernet` rows carry MTU —

```
set [ find name=TenGigE0/0/0/20 ] disabled=no mtu=9216
```

— while the `/interface bonding` rows do not:

```
add slaves=TenGigE0/0/0/26 mode=active-backup name=Bundle-Ether500 comment="…"
```

So **MTU on a physical port survives and MTU on a bundle does not.** On an SP
box where the jumbo-MTU setting lives on the bundle rather than the members,
that is the whole jumbo configuration silently reverting to default.

**`description`.** All three cases are routed dot1q sub-interfaces —
`GigabitEthernet0/0/0/1.35` on both `batfish_ebgp_border*` fixtures and
`GigabitEthernet0/0/0/1.100` on `kitchen_sink` — and all three fall on
VLAN-bearing cells, i.e. exactly the cells that already drift structurally. The
render emits the sub-interface only as the target of an `/ip address` row; there
is no `/interface … set` row on which to hang a `comment=`, which is consistent
with the target declaring `/interfaces/interface/dot1q-vlan` unsupported. This
is one root cause with the count growth, not a second independent one, so
`interfaces[].description` stays `good` and the artefact is recorded here in
prose instead. Every other description in the corpus round-trips as a RouterOS
`comment=`.

Two attributes were checked and found clean, which is worth recording so nobody
re-hunts them: **`enabled`** — 74 administratively-down source interfaces across
the corpus, all 74 still disabled after the round-trip; and **`ipv6_addresses`**
— 3 cells carry interface IPv6, all preserved exactly.

## Source-side gaps vs target-side drops

`cisco_iosxr` cannot emit these at all, so there is nothing for RouterOS to
lose. They are `not_applicable`, not `unsupported`:

- **SNMP, in full.** `netcanon/migration/codecs/cisco_iosxr/parse.py` contains
  no SNMP handling whatsoever, and `intent.snmp` is `None` on all 12 cells.
  This is not corpus luck: `iosxr_design_cst_pa3_xr752.cfg` contains three
  `snmp-server` lines that the codec discards before the pair is involved. The
  IOS-XR matrix additionally declares `/snmp/community` and four
  `/snmp/v3-user/*` paths unsupported. RouterOS is the *stronger* side here
  (supported=5), so re-authoring SNMP on the target will stick.
- **VLAN body.** `_parse_dot1q_vlans` is explicit: *"IOS-XR routers have no
  classic `vlan N / name X` stanza — VLAN ids appear only on sub-interfaces via
  `encapsulation dot1q <vid>`. Each distinct tag becomes a bare `CanonicalVlan`
  (`name` always empty; no port membership)."* So `vlans[].name`,
  `vlans[].description`, `vlans[].tagged_ports`, `vlans[].untagged_ports` and
  `vlans[].ipv4_addresses` are structurally empty from this source, by
  construction rather than by accident.
- **`dhcp_servers`** (`/dhcp-servers/pool` unsupported), **`radius_servers`**
  (`/radius-servers/server/host` + `/key` unsupported), **`evpn_type5_routes`**
  (`/evpn-type5-routes/route` unsupported).

These are **target-side drops** — the source has the data and RouterOS has
nowhere to put it, so they are `unsupported`:

- **`domain`.** IOS-XR parses it (`test.com`, `test.lab`, `lab.example.net` on
  8 of 12 cells); the render emits no domain line at all and it comes back
  empty every time. `/system/domain` is declared unsupported on the target.
- **`syslog_servers`.** IOS-XR declares `/system/syslog-server` supported;
  RouterOS declares it unsupported. No committed cell populates it, so this
  rests on the declarations.
- **`routing_instances`** — see below.

`timezone`, `vxlan_vnis[]` and `anycast_gateway_mac` are **symmetric gaps**:
both matrices declare `/system/timezone`, `/vxlan-vnis/vni` (+
`/source-interface`, `/udp-port`) and `/anycast-gateway-mac` unsupported.
Recorded `unsupported` rather than `not_applicable`, because re-authoring on the
target would not help either.

## The three findings that decide this migration

**1. Every VRF disappears, and half the routing table quietly changes meaning.**
`routing_instances` goes to zero on all 8 cells that populate it —
`['AZURE']`, `['red','blue','management']`, `['CUSTOMER-A','MGMT']`,
`['CUSTOMER']`, `['100']` all render to `[]`. The target declares
`/routing-instances/instance` unsupported: *"Render emits no VRF/routing-instance
construct."* That is a vanished record, so it is `unsupported`, not `lossy`
(#436).

The dangerous part is what happens to routes bound to those VRFs. RouterOS
declares `/routing/static-route/vrf` unsupported (parses-and-ignores, wire-up
scheduled for v0.2.0), so a VRF-scoped route does not disappear — it renders
into the **global** table:

```
source :  10.99.0.0/16  via 203.0.113.2   vrf=CUSTOMER-A
render :  add dst-address=10.99.0.0/16 gateway=203.0.113.2
re-parse: 10.99.0.0/16  via 203.0.113.2   vrf=''
```

A customer VPN route silently becomes a global route. Nothing warns; the
destination and gateway are byte-identical. This is the single most important
thing to check before cutover.

Two smaller static-route artefacts share the same key: an interface-only next
hop moves into the gateway slot (`interface='Null0'` → `gateway='Null0'`), so
the canonical route stops distinguishing "via interface" from "via gateway
address"; a combined next hop (`gateway%interface`) round-trips intact.

**2. No account arrives with a working credential, but the render says so.**
`local_users[].hashed_password` drifts on all 9 cells that populate users, and
the loss is structural in the target *parser*, documented in
`netcanon/migration/codecs/mikrotik_routeros/parse.py`: *"RouterOS `/export`
intentionally omits password hashes … `hashed_password` will be empty from this
parser."* The render side behaves well: when the source hash is not re-usable on
RouterOS it deliberately **does not** emit it as `password=` — that would set
the user's password to the literal hash string — and instead emits a
`# password manager user-name "…" -- review: … reset this user password manually`
comment. So the credential is lost loudly, not silently.

Role fares slightly better but still coerces: the IOS-XR task-group `root-lr`
renders as RouterOS `group=full` and re-parses as `admin`, on 9 of 12 cells.
`operator` survives as `operator`. The username itself is preserved everywhere.

**3. VLAN names are invented, not lost.** IOS-XR always produces
`CanonicalVlan(name="")`; RouterOS names the VLAN interface `vlan<id>` and
re-parses that back as the VLAN name, so `('' → 'vlan35')`, `('' → 'vlan200')`,
`('' → 'vlan100')` on the 4 VLAN-bearing cells. The target declares
`/vlans/vlan/name` lossy for exactly this: *"MikroTik stores a VLAN's name as
the L3 interface name (e.g. vlan10), NOT a separate descriptive name field."*
The VLAN **id** is preserved on all 4 cells. Read the drift as a fabricated
value rather than a destroyed one — the practical consequence is that any
config-diff or inventory reconciliation after the migration reports VLAN names
that no operator ever authored.

## LAGs: the one place the trap warning does not fire

The evidence dossier warns that a bare `lags` drift is usually the cross-vendor
naming artefact. On this pair `lags` does not drift at all: 4 cells populate it,
all 4 preserved, with `Bundle-Ether*` names, member lists and modes intact
(`active` and `static` both round-trip, verified on
`iosxr_design_cst_pa3_xr752.cfg` and `kitchen_sink.cfg`), and
`interfaces[].lag_member_of` round-trips exactly — 5 members on the 55-interface
chassis, 2 on the kitchen sink.

RouterOS declares `/lags/lag/mode` lossy for one specific case: a `passive`
LACP bundle re-parses as `active`, because MikroTik `mode=802.3ad` has no
passive variant. **No committed IOS-XR fixture carries a passive bundle**, so
that path is undeclared-by-observation here — `lags` is `good` on this corpus
and the caveat belongs to the target matrix, not to this pair.

## Credential material

`local_users[].hashed_password` is empty after the round-trip on every one of
the 9 populated cells. The source hashes are IOS-XR type-tagged crypt strings;
their values are deliberately **not** reproduced in this file or in the
expectation YAML, only their fate. Per `AGENTS.md`, hashed secrets remain
operator-traceable, and a document that quotes the value it describes defeats
its own redaction.

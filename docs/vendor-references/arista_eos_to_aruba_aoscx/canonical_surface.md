# Arista EOS → AOS-CX: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/arista_eos__aruba_aoscx.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key
dispositions were resolved through the audit's own `actual_disposition()` rather
than inferred from the drift shape, so this file and the ratchet agree by
construction. Where a call was ambiguous it was settled by re-running the
round-trip by hand — `aruba_aoscx.parse(aruba_aoscx.render(arista_eos.parse(raw)))`
— and reading the rendered text, not by reasoning from grammar.

- Fixture cells: **6** (5 real captures + 1 synthetic kitchen-sink)
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the measured mesh run, and hand-run round-trips over the
> committed fixtures. Where a disposition rests on a declaration rather than an
> observed round-trip, the YAML says so explicitly.

## Device-class framing

`arista_eos` in this corpus is a **DC leaf/spine** — EVPN/VXLAN leaves with
anycast SVI gateways, MLAG peer bundles and per-tenant VRFs. `aruba_aoscx` is a
**campus access/aggregation** switch. The realistic migration is a small DC or
collapsed-core EOS switch being replaced by an AOS-CX box, so the shared surface
is the L2/L3 edge plus the VLAN↔VNI bindings — not the EVPN control-plane
surface the EOS fixtures are built around.

This is the reverse of `aruba_aoscx__arista_eos.yaml`, and it does **not**
mirror it. The two directions fail in structurally different places.

## The structural finding — and how it differs from the reverse pair

**The interface inventory does not shrink on this pair.** Measured record counts,
source → round-tripped, on all six cells: 17→17, 30→30, 39→39, 4→4, 66→66,
13→13. `interfaces[].name` is preserved on 6 of 6 cells.

That matters for how the rest of this file should be read. On the reverse pair
(`aruba_aoscx → arista_eos`) the record count collapses, so every
`interfaces[].*` sub-field drifts for one shared reason and none of them carries
independent signal. Here the opposite holds: **each `interfaces[].*` drift is an
independent measurement**, and the four sub-fields that survive intact
(`description`, `enabled`, `mtu`, `ipv6_addresses`) are genuinely good rather
than good-by-luck.

## Per-key measurement (6 cells)

Counts are cells: drifted / preserved / trivially empty.

| key | drifted | preserved | trivially empty |
|---|---|---|---|
| hostname | 0 | 6 | 0 |
| domain | 2 | 0 | 4 |
| dns_servers | 4 | 0 | 2 |
| ntp_servers | 4 | 0 | 2 |
| syslog_servers | 1 | 0 | 5 |
| dhcp_servers | 1 | 0 | 5 |
| interfaces[].name | 0 | 6 | 0 |
| interfaces[].description | 0 | 4 | 2 |
| interfaces[].enabled | 0 | 6 | 0 |
| interfaces[].mtu | 0 | 1 | 5 |
| interfaces[].ipv6_addresses | 0 | 2 | 4 |
| interfaces[].ipv4_addresses | 2 | 4 | 0 |
| interfaces[].interface_type | 6 | 0 | 0 |
| interfaces[].lag_member_of | 3 | 0 | 3 |
| vlans[].id | 0 | 4 | 2 |
| vlans[].name | 0 | 4 | 2 |
| vlans[].ipv4_addresses | 3 | 0 | 3 |
| vlans[].untagged_ports | 2 | 0 | 4 |
| vlans[].tagged_ports | 3 | 0 | 3 |
| static_routes | 2 | 3 | 1 |
| snmp.community / location / contact | 0 | 2 | 4 |
| snmp.trap_hosts | 1 | 1 | 4 |
| snmp.v3_users | 1 | 1 | 4 |
| lags | 3 | 0 | 3 |
| local_users[].name | 2 | 4 | 0 |
| local_users[].role | 3 | 3 | 0 |
| local_users[].hashed_password | 2 | 4 | 0 |
| vxlan_vnis[].vni / vlan_id | 0 | 4 | 2 |
| routing_instances[].name | 0 | 4 | 2 |
| anycast_gateway_mac | 0 | 2 | 4 |

Keys trivially empty on all 6 cells: `timezone`, `interfaces[].vrrp_groups`,
`vlans[].description`, `radius_servers`, `vxlan_vnis[].mcast_group`,
`evpn_type5_routes`, `routing_instances[].description`, `raw_sections`,
`apply_groups`, `group_content`.

## Finding 1 — one root cause behind three symptoms: port-name shape

This is the dominant loss on the pair, and it is **one cause with three measured
symptoms, not three independent findings**:

- `vlans[].untagged_ports` and `vlans[].tagged_ports` empty out;
- `interfaces[].interface_type` degrades to `ianaift:other` on every record
  (169 record-cells in the aggregate — the single largest drift population on
  the pair);
- the whole switchport surface underneath — `switchport_mode` (11
  record-cells), `trunk_allowed_vlans` (9), `access_vlan` (2),
  `trunk_native_vlan` (1) — goes to null/empty.

The mesh round-trip carries EOS interface names through verbatim, so a port
arrives at the AOS-CX renderer as `Ethernet2`. The rendered stanza is then:

```
interface Ethernet2
    no shutdown
    description Access port for end-host
```

No `no routing`, no `vlan access 10`. Across all six cells the render emits
**zero** `vlan access` / `vlan trunk` / `no routing` lines.

**Controlled experiment.** Taking the same parsed intent and renaming
`EthernetN` → `1/1/N` (interfaces, `lag_member_of`, VLAN member lists and LAG
member lists), then re-rendering with the same codec:

```
interface 1/1/2
    no shutdown
    description Access port for end-host
    no routing
    vlan access 10
```

and the round-trip then yields `vlan 10 untagged_ports == ['1/1/2']`,
`tagged_ports == ['1/1/3']`, `1/1/2` with `switchport_mode='access'`,
`access_vlan=10`, and `interface_type == 'ianaift:ethernetCsmacd'`. All three
symptoms clear at once.

Two consequences worth carrying forward:

1. **The target is not missing the feature.** `aruba_aoscx` declares
   `/vlans/vlan/untagged-ports`, `/vlans/vlan/tagged-ports`,
   `/interfaces/interface/switchport-mode`, `/interfaces/interface/access-vlan`,
   `/interfaces/interface/trunk-allowed-vlans` and
   `/interfaces/interface/trunk-native-vlan` all **supported**, and the
   experiment shows it honours them. That is why these keys are recorded
   `lossy` and not `unsupported` even though the round-trip drop is total: the
   loss is gated on the shape of the source port names, not on a target
   capability gap, and `unsupported` would block a migration that works.
2. **Operator action is concrete.** The bare mesh round-trip runs no port-name
   translation. A real cutover should apply the port-rename map (see
   `run_plan_with_overrides(port_rename_map=...)`); with AOS-CX-shaped names the
   VLAN edge migrates intact.

`interfaces[].interface_type` stays `lossy` on its own merits regardless —
`aruba_aoscx` declares `/interfaces/interface/config/type` lossy because it
carries no IANA ifType and infers one from the name shape.

## Finding 2 — the anycast SVI arrives without a primary address

`anycast_gateway_mac` is preserved on both cells that populate it, and the
render really does emit the active-gateway lines. Do **not** read that as
"anycast gateway migrates cleanly".

On the two EVPN leaf cells the EOS SVIs carry `ip address virtual` only — a
virtual gateway address with no primary interface address. The rendered AOS-CX
SVI is:

```
interface Vlan110
    no shutdown
    description Tenant_A_OPZone_1
    vrf attach Tenant_A_OPZone
    ip address /24
    active-gateway ip mac 00:dc:00:00:00:01
    active-gateway ip 10.1.10.1
    ip address /24 secondary
```

The `active-gateway` lines survive; the `ip address` line is emitted with an
**empty address** and the round-trip re-parses the SVI with
`ipv4_addresses == []`. That is the whole of `interfaces[].ipv4_addresses`
drift on this pair (14 record-cells, 2 of 6 cells) — every EOS SVI whose only
address was virtual. Cells whose interfaces carry real addresses preserve them
(the kitchen-sink `Vlan100` keeps `10.100.0.1/24`).

Plan to assign primary SVI addresses on the AOS-CX side before cutover.

## Finding 3 — `vlans[].ipv4_addresses` re-homes, it does not evaporate

`aruba_aoscx` declares `/vlans/vlan/ipv4/address/ip` lossy with the reason that
it renders SVI L3 from a sibling *interface* stanza, never from the VLAN record.
The round-trip confirms this precisely: on the kitchen-sink cell the source
carries `10.100.0.1/24` on VLAN record 100, the round-tripped VLAN record 100
has `ipv4_addresses == []`, and the round-tripped **interface** `Vlan100` has
`10.100.0.1/24` intact.

So the address is still in the config — it changed canonical mount point. That
is why this key is `lossy` and not `unsupported`, and it is the one place where
the coarse total-drop classifier and the target matrix disagreed; the
round-trip settled it in favour of the matrix.

## Finding 4 — LAG bundles keep their members; the name form and LACP mode do not

Round-tripped on three cells: `Port-Channel3 (mode=active, members
[Ethernet3, Ethernet4])` → `lag 3 (mode=static, members [Ethernet3,
Ethernet4])`. Membership is intact on every bundle across every cell.

Two separable losses:

- **LACP mode.** `active` → `static` on 10 record-cells. `aruba_aoscx` declares
  `/lags/lag/mode` lossy for exactly this cross-vendor case. A bundle that was
  LACP-negotiated arrives as a static trunk — re-apply `lacp mode active` on the
  target or the bundle will not negotiate.
- **Name form.** `Port-Channel3` → `lag 3`. Note that the reconciler's
  `_canonical_lag_name` collapses `ae<N>` / `Po<N>` / `Port-channel<N>` /
  `trk<N>` / `agg<N>` / `bond<N>` to a common token, but the AOS-CX form
  `lag 3` contains a space and matches none of them, so it falls through to raw
  equality and registers as drift on both `lags` and
  `interfaces[].lag_member_of`. The bundle is not actually lost. This is a
  reconciler coverage gap, not a pair-specific fact, and is left for a codec
  change rather than papered over here.

## Finding 5 — passwordless accounts vanish; the hash itself survives

`local_users` shrinks on 2 of 6 cells (5 → 3 and 3 → 2). The dropped accounts
are exactly the ones whose `hashed_password` is empty: the render emits
`user admin group network-admin` with no password clause, and the AOS-CX parser
does not read that back as a user.

Two things follow, and the second is a trap:

- The surviving accounts keep their secret **verbatim** — same length, same
  token, no re-encoding. `local_users[].hashed_password` shows **no** sub-field
  drift anywhere in the aggregate; its 2 drifting cells are precisely the 2
  cells where records vanish. Its loss is therefore *correlated with* the record
  drop and is not independent evidence of a hash-format problem.
- Role and privilege are remapped in both directions. Where the EOS source
  carries no role, the AOS-CX side materialises one from the privilege level
  (empty + priv 15 → `administrators`; empty + priv 1 → `operators`). Where the
  source carries an EOS role name, it passes through verbatim
  (`network-admin`) and the privilege level degrades 15 → 1 because the group is
  not one AOS-CX recognises. `aruba_aoscx` declares
  `/local-users/user/privilege-level` lossy for this mapping.

Audit before cutover for accounts with no configured secret — they will not
exist on the target at all.

## Credential material

No secret value from any fixture is reproduced in this file or in the
expectation YAML. The EOS user secrets are opaque single-token strings; the
AOS-CX SNMPv3 render carries `ciphertext`-form blobs. Per `AGENTS.md`, encrypted
and hashed secrets are operator-traceable even when they cannot be reversed, and
a document that quotes the value it claims to redact defeats its own redaction.
Only shapes and lengths were inspected.

## Source-side gaps vs target-side drops

Everything that vanishes wholesale on this pair is a **target-side drop**, and
in every case `aruba_aoscx` declares it unsupported at the exact path:

`/system/domain` · `/system/dns-server` · `/system/ntp-server` ·
`/system/syslog-server` · `/dhcp-servers/pool` · `/snmp/trap-host` ·
`/routing/static-route/vrf`

`arista_eos` declares `dns_servers`, `ntp_servers`, `syslog_servers` and
`dhcp_servers` **supported** and populates them in the corpus, so these are real
losses an operator must re-author by hand, not modelling gaps. Verified in the
round-trip: `domain 'lab.local' → ''`, both DNS servers dropped, both NTP
servers dropped, the single syslog host dropped, both DHCP pools dropped.

`static_routes` is the one conditional entry in that list. Default-VRF routes
round-trip cleanly (`ip route 0.0.0.0/0 192.168.100.1` is emitted; preserved on
3 cells). The 2 drifting cells each carry a single route bound to the `MGMT`
VRF, and the render emits **no `ip route` line at all** for it — matching the
declared reason that only default-VRF `ip route` is wired. Recorded
`unsupported` because the record vanishes with no trace and no operator-side
input recovers it, with the scope stated plainly in the YAML.

`timezone` is symmetric: **both** matrices declare `/system/timezone`
unsupported. `interfaces[].vrrp_groups` and `routing_instances[].description`
are unexercised by the corpus and rest on the target's explicit unsupported
declarations, which the YAML says out loud.

## Fabric surface: what survives

VNI and VLAN↔VNI binding are preserved on all 4 populated cells; so are VRF
names. What drops around them, all declared by the target matrix:

- `vxlan_vnis[].source_interface` — `Loopback1` → `""` (19 record-cells).
  AOS-CX states the VTEP source as an IPv4 address, not an interface name.
- `routing_instances` RD (16 record-cells), `rt_imports` (16), `rt_exports`
  (16), `l3_vni` (8) and `instance_type` (`mac-vrf` → `vrf`, 8) — all live under
  AOS-CX's deferred `evpn` block.

None of those are keys in the expectation YAML, but they are the reason the
`routing_instances` and `vxlan_vnis` parents show as drifted while the keys that
matter are `good`.

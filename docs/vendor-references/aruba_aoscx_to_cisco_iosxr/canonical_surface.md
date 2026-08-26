# AOS-CX → Cisco IOS-XR: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/aruba_aoscx__cisco_iosxr.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, plus a per-fixture `target.parse(target.render(source.parse()))`
replay of all 7 cells run while authoring this note. Per-key dispositions were
resolved through the audit's own `actual_disposition()` rather than inferred
from the drift shape, so this file and the ratchet agree by construction.

- Fixture cells: **7**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the codec source, and the measured round-trips. Where a
> disposition rests on a declaration rather than an observed round-trip, the
> YAML says so explicitly.

## Device-class framing

`aruba_aoscx` in this corpus is a **campus / DC access-aggregation switch**;
`cisco_iosxr` is a **service-provider edge/core router** (ASR 9000, NCS 5500 /
540 / 8000). This is the widest device-class gap in the AOS-CX expectation
mesh, and it decides the shape of the whole file: IOS-XR has no campus L2
model at all.

The surviving shared surface is the routed edge — hostname, interface
addressing and admin state, LAG membership, VRFs, static routes, local user
identity. Everything that is *campus* — the VLAN table, per-port VLAN
membership, SVI anycast gateways, VXLAN, SNMP — has no IOS-XR representation
and is dropped whole.

## The structural finding

The interface **inventory does not shrink**: 157 source interface records
against 157 re-parsed records across the 7 cells. This pair's interface losses
are therefore per-record, not structural, and each one is declared on its own
evidence rather than inherited from a vanishing parent.

Three separate mechanisms, each measured:

**1. Two-token names lose their index.** AOS-CX names logical interfaces with
a space (`lag 1`, `vlan 101`, `loopback 0`). The IOS-XR renderer emits them
verbatim (`interface lag 1`), and the IOS-XR parser takes the first
whitespace-delimited token as the name — so they come back as bare `lag`,
`vlan`, `loopback`. 62 of 157 records are two-token, and 56 of the 157
re-parsed records end up sharing a name with at least one sibling (43 records
in excess of the distinct name count). Physical ports (`1/1/1`) and `mgmt` are
unaffected.

**2. Interface type collapses.** The IOS-XR parser infers
`interface_type` from the name prefix (`GigabitEthernet` → `ethernetCsmacd`,
`Loopback` → `softwareLoopback`, `Bundle-Ether` → `ieee8023adLag`, `MgmtEth` →
`ethernetCsmacd`). AOS-CX names carry none of those prefixes, so the source
distribution — 95 `ethernetCsmacd`, 34 `ieee8023adLag`, 18 `l3ipvlan`,
10 `softwareLoopback` — re-parses as **147 `ianaift:other` + 10
`softwareLoopback`**. Only `loopback 0` survives, because `loopback` happens
to match an IOS-XR prefix.

**3. The active-gateway address is dropped.** All 41 interface IPv4 address
records survive with IP and prefix intact; **15 `virtual_gateway_address`
values go in and 0 come out.** `cisco_iosxr` declares
`/interfaces/interface/ipv4/address/virtual-gateway-address` unsupported —
IOS-XR has no VARP / anycast-gateway grammar.

Mechanisms 1 and 2 are properties of the bare parse-render-parse path the mesh
measures, not of the canonical model. Re-running the same 7 cells through
`netcanon.migration.canonical.port_names.translate_port_names` (source
`aruba_aoscx`, target `cisco_iosxr`, empty rename map) yields IOS-XR-native
names — `GigabitEthernet1/1/1/0`, `Bundle-Ether256`, `Loopback0`,
`MgmtEth0/RP0/CPU0/0` — with **0 duplicates, 0 renamed records on re-parse,
34/34 LAGs (one better than the bare path) and the full source type
distribution restored (95 + 34 + 10)**.

The price is explicit: the rename path **auto-drops all 18 SVI records**
(`vlan N`), because IOS-XR has no SVI. Mechanism 3 survives the rename path
untouched — all 15 active-gateway addresses are still lost.

So: plan the cutover through the port-rename path, and treat the campus L3
edge as something to re-architect rather than migrate.

## Per-field measurement (7 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 7 | 0 | 0 |
| interfaces[].name | 0 | 7 | 0 |
| interfaces[].description | 7 | 0 | 0 |
| interfaces[].enabled | 7 | 0 | 0 |
| interfaces[].mtu | 7 | 0 | 0 |
| interfaces[].ipv6_addresses | 2 | 0 | 5 |
| interfaces[].ipv4_addresses | 2 | 5 | 0 |
| interfaces[].interface_type | 0 | 7 | 0 |
| interfaces[].lag_member_of | 0 | 7 | 0 |
| vlans[] (every sub-field) | 0 | 7 | 0 |
| static_routes | 2 | 0 | 5 |
| snmp.community | 3 | 1 | 3 |
| snmp.location | 1 | 3 | 3 |
| snmp.contact | 1 | 3 | 3 |
| snmp.trap_hosts | 4 | 0 | 3 |
| snmp.v3_users | 2 | 2 | 3 |
| lags | 0 | 7 | 0 |
| local_users[].name / role / hashed_password | 6 | 0 | 1 |
| vxlan_vnis[] (every sub-field) | 0 | 3 | 4 |
| routing_instances[].name | 3 | 0 | 4 |
| anycast_gateway_mac | 0 | 5 | 2 |

Fields trivially empty on all 7 cells: `domain`, `dns_servers`, `ntp_servers`,
`timezone`, `syslog_servers`, `interfaces[].vrrp_groups`, `dhcp_servers`,
`radius_servers`, `evpn_type5_routes`, `routing_instances[].description`,
`raw_sections`, `apply_groups`, `group_content`.

### Record-level aggregates (all 7 cells, bare round-trip)

| list | source | re-parsed |
|---|---|---|
| interfaces | 157 | 157 (56 share a name) |
| interface IPv4 address records | 41 | 41 |
| `virtual_gateway_address` values | 15 | **0** |
| interface IPv6 address records | 2 | 2 |
| lag membership (`lag_member_of` set) | 44 | 44 (every value rewritten) |
| lags | 34 | 33 |
| vlans | 30 | **0** |
| vxlan_vnis | 4 | **0** |
| cells with an SNMP record | 4 | **0** |
| local_users | 7 | 7 |
| routing_instances | 6 | 6 |
| static_routes | 3 | 3 |
| cells with `anycast_gateway_mac` | 5 | **0** |

## Source-side gaps vs target-side drops

AOS-CX declares these **unsupported at the exact path**, so as a *source* it
never emits them and there is nothing for IOS-XR to lose:

`/system/domain` · `/system/dns-server` · `/system/ntp-server` ·
`/system/syslog-server` · `/routing-instances/instance/description`

These are recorded `not_applicable`, not `unsupported`. The distinction is
operational: for `dns_servers`, `ntp_servers` and `syslog_servers`,
**cisco_iosxr declares the field SUPPORTED** — re-authoring them on the target
will stick, and the migration report should say so rather than implying the
target cannot hold them.

Symmetric gaps — **both** matrices declare them unsupported, so they are
`unsupported` rather than `not_applicable`: `timezone` (`/system/timezone`),
`dhcp_servers` (`/dhcp-servers/pool`), `radius_servers`
(`/radius-servers/server/host` + `/key`), and the whole
`/interfaces/interface/vrrp-groups/group` subtree.

`snmp.trap_hosts` is a third shape and the one most likely to be misread.
AOS-CX declares `/snmp/trap-host` unsupported too, so the canonical field is
empty on every cell — but because empty arrives as empty, the audit measures
it *preserved* on the 4 SNMP-bearing cells. It is therefore recorded `good`,
in the vacuous sense only: there is no trap-host data on this pair for IOS-XR
to lose, and the SNMP block it would live in does not survive at all. The
YAML entry says exactly that rather than letting the `good` stand alone.

## Where the vanish probe and the target matrix disagree

Two keys needed a round-trip to settle, because the drift-shape heuristic and
`cisco_iosxr`'s own `CapabilityMatrix` pointed in opposite directions. Both
were settled by rendering, not by reasoning.

**`vlans` — matrix says supported, behaviour says dropped.** `cisco_iosxr`
declares `/vlans/vlan/id` and `/vlans/vlan/name` *supported*, and four
`/vlans/vlan/ipv4/address/*` paths *lossy* — no unsupported declaration at
all. But those declarations describe VLANs **synthesised from
`encapsulation dot1q` sub-interfaces** (`parse.py::_parse_dot1q_vlans`); the
renderer emits nothing whatsoever for `intent.vlans`. Measured: **30 VLAN
records in, 0 out, on all 7 cells, and zero top-level `vlan` stanzas in any of
the 7 renders.** An AOS-CX VLAN table has nowhere to land. Recorded
`unsupported` on `vlans[].id` per #436 — a vanished record is not lossy.

**`snmp` — heuristic says lossy, behaviour says dropped.** The vanish probe
classified `snmp` as a partial degradation, but only because its
string-drift branch does not recognise `… → None` as an emptied target; the
whole `CanonicalSNMP` record is replaced by `None`. Measured: the 4 cells that
carry SNMP produce **zero `snmp` lines across all 7 renders**, and
`cisco_iosxr` agrees in its own matrix — `/snmp/community` unsupported, reason
"SNMP parse + render is out of the v1 XR scope". Recorded `unsupported`.

`vxlan_vnis` and `anycast_gateway_mac` needed no adjudication: probe and
matrix both say total drop, and the renders contain no `nve` / `vxlan` /
`anycast` line anywhere.

## Two findings worth carrying forward

**1. `lags` loses exactly one record, and it is the member-less one.** The
IOS-XR renderer writes LAG membership as `bundle id <N> mode active` on the
*member* port, and the IOS-XR parser reconstructs `CanonicalLAG` records from
those member lines — never from the LAG's own stanza. So `lag N` becomes
`Bundle-EtherN` (a name rewrite, with all 44 member relationships intact), but
a LAG with **no members cannot be reconstructed at all**: the synthetic
kitchen-sink fixture's empty `lag 2` is the single record lost, 34 → 33.
The rename path recovers it (34 → 34), because the LAG then renders under a
name the IOS-XR parser recognises.

Note the internal inconsistency in the bare render worth knowing about before
hand-editing one: member ports point at `Bundle-EtherN` while the LAG's own
stanza is still emitted as `interface lag N`.

**2. `anycast_gateway_mac` and the per-address gateway fail together.** Unlike
the EOS pair — where the chassis MAC survives while the per-SVI address does
not — IOS-XR drops **both**: 5 of 5 `anycast_gateway_mac` values and 15 of 15
`virtual_gateway_address` values. `cisco_iosxr` declares
`/anycast-gateway-mac` unsupported for the same stated reason as the
per-address paths: no VARP / distributed-anycast-gateway grammar. First-hop
redundancy on this pair is not migrated, it is redesigned.

## Credential material

`local_users[].hashed_password` is **preserved byte-for-byte on all 7 user
records** — as it is on the two other Cisco-CLI targets in this mesh
(`aruba_aoscx__cisco_iosxe_cli`, `aruba_aoscx__cisco_nxos`, both `good`),
and unlike the six pairs that record it `lossy` or `unsupported`. That is
worth reading carefully rather than as good news.

AOS-CX stores the user secret in its own encrypted form — an `AQB`-prefixed
ciphertext blob, 184 characters on the DC fixtures. The IOS-XR renderer keeps
a hash's type-digit prefix when there is one and otherwise emits the bare
value behind type 0 (`render.py::_render_local_user`), which the codec's own
parser docstring names "the plaintext marker". So the canonical field
round-trips intact, and what lands in the rendered config is an AOS-CX
ciphertext string presented to IOS-XR as a plaintext password.

The canonical disposition is therefore `good` and the operational advice is
the same as on every other AOS-CX pair: **set the password on the target
before cutover.** A preserved field is not a working credential.

`snmp.v3_users` is the other credential-bearing surface, and it does not
survive at all — the 2 v3 users in the corpus (each carrying an auth
passphrase and a priv passphrase) go with the dropped SNMP record. They must
be re-created on the target.

No ciphertext, hash or passphrase value is reproduced in this file or in the
expectation YAML. Per `AGENTS.md`, encrypted secrets are operator-traceable
even when encrypted, and a document that quotes the value it describes defeats
its own redaction.

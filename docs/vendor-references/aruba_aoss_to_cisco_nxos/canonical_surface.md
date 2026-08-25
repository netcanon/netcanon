# Aruba AOS-S -> Cisco NX-OS: measured canonical surface

Source: `netcanon/migration/codecs/aruba_aoss/codec.py` and
`netcanon/migration/codecs/cisco_nxos/codec.py` (`CapabilityMatrix`), joined
against a full in-process `tools/run_full_mesh.py` pass over the committed
fixture corpus.
Retrieved: 2026-08-20

7 fixture cells (6 real AOS-S captures under `tests/fixtures/real/aruba_aoss/`
plus the synthetic `tests/fixtures/synthetic/aruba_aoss/kitchen_sink.cfg`);
**0 render errors, 0 re-parse errors**.

The pair is asymmetric by device class. `aruba_aoss` declares a campus access
switch (L2 + basic L3, no VRF / VXLAN / EVPN / DHCP-server surface);
`cisco_nxos` declares a DC leaf/spine. Nearly all of the NX-OS-only fabric
surface is therefore *structurally absent on the source* rather than dropped
by the target — those rows are `not_applicable`, not `unsupported`. The real
losses on this direction are concentrated in three places: VLAN port
membership, LAG bundles whose members are not themselves interface records,
and the administrative privilege of local users.

The mesh path is a bare `parse -> render -> parse`
(`tools/run_full_mesh.process_cell`): no port-rename mesh, no
`project_vlan_to_switchport` reprojection, no orchestrator overrides. It
scores PRESERVATION of canonical content, not target-syntax validity.

## Per-field measurement (7 cells)

| field | preserved | drifted | untested | what drifts |
|---|---:|---:|---:|---|
| `hostname` | 7 | 0 | 0 | — |
| `dns_servers` | 3 | 0 | 4 | — |
| `ntp_servers` | 1 | 0 | 6 | — |
| `static_routes` | 5 | 0 | 2 | — |
| `snmp` | 6 | 0 | 1 | — |
| `vlans` | 2 | 5 | 0 | `untagged_ports`, `tagged_ports` |
| `interfaces` | 1 | 4 | 2 | `interface_type`, `lag_member_of` |
| `local_users` | 0 | 3 | 4 | `privilege_level` |
| `lags` | 0 | 2 | 5 | `name`; one whole record dropped |
| `radius_servers` | 0 | 1 | 6 | whole record — all servers dropped |
| `domain` | 0 | 0 | 7 | — |
| `timezone` | 0 | 0 | 7 | — |
| `syslog_servers` | 0 | 0 | 7 | — |
| `dhcp_servers` | 0 | 0 | 7 | — |
| `vxlan_vnis` | 0 | 0 | 7 | — |
| `evpn_type5_routes` | 0 | 0 | 7 | — |
| `routing_instances` | 0 | 0 | 7 | — |
| `raw_sections` | 0 | 0 | 7 | — |
| `apply_groups` | 0 | 0 | 7 | — |
| `group_content` | 0 | 0 | 7 | — |
| `anycast_gateway_mac` | 0 | 0 | 7 | — |

"untested" is the reconciler's `trivially_preserved`: both sides carry no data
on the field, so the cell cannot validate any disposition claim.

## Per-sub-field measurement (the keys the YAML actually declares)

Resolved through `run_phase4_reconciliation.actual_disposition`, i.e. exactly
what the Phase-4 reconciler will compare each YAML key against. `pres` /
`drift` / `triv` are counts of the 7 cells.

| key | pres | drift | triv |
|---|---:|---:|---:|
| `interfaces[].name` | 5 | 0 | 2 |
| `interfaces[].description` | 5 | 0 | 2 |
| `interfaces[].enabled` | 5 | 0 | 2 |
| `interfaces[].dhcp_client` | 5 | 0 | 2 |
| `interfaces[].ipv4_addresses` | 4 | 0 | 3 |
| `interfaces[].switchport_mode` | 4 | 0 | 3 |
| `interfaces[].access_vlan` | 4 | 0 | 3 |
| `interfaces[].trunk_allowed_vlans` | 3 | 0 | 4 |
| `interfaces[].trunk_native_vlan` | 1 | 0 | 6 |
| `interfaces[].ipv6_addresses` | 1 | 0 | 6 |
| `interfaces[].interface_type` | 1 | **4** | 2 |
| `interfaces[].lag_member_of` | 0 | **2** | 5 |
| `interfaces[].mtu` | 0 | 0 | 7 |
| `interfaces[].dot1q_vlan` | 0 | 0 | 7 |
| `interfaces[].voice_vlan` | 0 | 0 | 7 |
| `interfaces[].vrf` | 0 | 0 | 7 |
| `vlans[].id` | 7 | 0 | 0 |
| `vlans[].name` | 6 | 0 | 1 |
| `vlans[].ipv4_addresses` | 4 | 0 | 3 |
| `vlans[].tagged_ports` | 2 | **3** | 2 |
| `vlans[].untagged_ports` | 1 | **5** | 1 |
| `vlans[].description` | 0 | 0 | 7 |
| `snmp.community` / `.location` / `.contact` / `.trap_hosts` / `.v3_users` | 6 | 0 | 1 |
| `local_users[].name` | 3 | 0 | 4 |
| `local_users[].hashed_password` | 3 | 0 | 4 |
| `local_users[].role` | 3 | 0 | 4 |
| `local_users[].privilege_level` | 0 | **3** | 4 |
| `lags` (whole record) | 0 | **2** | 5 |
| `radius_servers` (whole record) | 0 | **1** | 6 |
| `static_routes` (whole record) | 5 | 0 | 2 |

Every sub-field not listed above as drifting is preserved on every cell that
exercises it. Six keys carry a real, observed loss:
`interfaces[].interface_type`, `interfaces[].lag_member_of`,
`vlans[].tagged_ports`, `vlans[].untagged_ports`, `lags`,
`local_users[].privilege_level`; plus `radius_servers`, where the record does
not survive at all.

## Mechanisms behind each observed loss

* **`vlans[].untagged_ports` / `vlans[].tagged_ports`** — the largest loss on
  this pair. AOS-S membership is VLAN-centric (`vlan 2 / untagged 1-24 /
  tagged 45-48`) and lands directly on the canonical VLAN record. The NX-OS
  render emits `vlan <id> / name <name>` plus the SVIs, and expresses port
  membership ONLY as per-interface `switchport access vlan N` /
  `switchport trunk allowed vlan ...` lines. On the bare mesh path no
  reprojection runs, so membership survives only for ports that already exist
  as `CanonicalInterface` records (those with explicit per-port AOS-S config).
  Everything else is dropped. Measured on
  `hpe_community_2930f_wc1607_intervlan.cfg`: 12 VLANs re-render with **every**
  tagged/untagged list emptied except a single port on VLAN 2. On
  `hpe_community_2920_wb1608_dhcp_snooping.cfg` VLAN 1 goes from 48 untagged
  ports to 8. On the kitchen sink, VLAN 10 goes from 12 untagged ports to 1.
* **`lags`** — the NX-OS render emits NO `interface port-channel<N>` stanza; a
  bundle exists on the target only as `channel-group <N> mode <mode>` lines on
  its member interfaces. So (a) the bundle name is reconstructed on re-parse as
  `port-channel<N>` from an AOS-S `trk<N>` — a vendor-correct rename that the
  reconciler's LAG canonicalisation does NOT absorb here, because the
  re-parsed token is lower-case `port-channel1` and `_LAG_NAME_RE` only accepts
  `Po` / `Port-channel` / `Port-Channel`; and (b) a LAG whose members are not
  themselves interface records leaves no trace at all. Measured on the kitchen
  sink: `trk1` (members `23`, `24`, both interface records) survives as
  `port-channel1` with members and LACP mode intact, while `trk2` (members
  `A3`, `A4`, which have no interface record) vanishes entirely — `lags` count
  drift 2 -> 1.
* **`interfaces[].lag_member_of`** — same root cause, seen from the member
  side: `trk1` -> `port-channel1` on the two member ports of the kitchen sink
  and on `aruba_central_5memberstack_rendered.cfg`. The membership relation
  survives; the operator-facing bundle name does not.
* **`interfaces[].interface_type`** — NX-OS infers the IANA ifType from the
  interface-name prefix (`Ethernet` -> `ethernetCsmacd`, `Vlan` -> `l3ipvlan`,
  `port-channel` -> `ieee8023adLag`, ...). AOS-S port names are bare numerics
  or module-lettered (`1`, `1/1`, `A1`), so the inference falls through:
  `ianaift:ethernetCsmacd` -> `ianaift:other` on every physical port (49 of 49
  records on the 5-member stack). The one cell that preserves the field,
  `hpe_community_2930f_wc1610_dhcp_server.cfg`, carries only SVIs, whose
  `Vlan<N>` names the NX-OS inference does recognise.
* **`local_users[].privilege_level`** — 15 -> 1 on every AOS-S manager account
  (4 records across 3 cells). The NX-OS codec derives the numeric privilege
  from the named role, mapping `network-admin` / `vdc-admin` -> 15 and
  everything else -> 1. AOS-S roles are `manager` / `operator`, which are not
  NX-OS role names, so every administrator re-parses as privilege 1.
* **`radius_servers`** — dropped wholesale (`all 2 radius_servers dropped` on
  the kitchen sink). The `cisco_nxos` matrix declares both
  `/radius-servers/server/host` and `/radius-servers/server/key` unsupported:
  the render emits no AAA radius-server config at all, so the records do not
  survive. This is `unsupported`, not `lossy`.

## Surfaces that survive, and why that is worth stating

* **`vlans[].ipv4_addresses`** — preserved on all 4 cells that carry an SVI.
  The `cisco_nxos` matrix declares `/vlans/vlan/ipv4/address/ip` lossy ("renders
  VLAN SVI L3 only from a sibling interface stanza"), but the `aruba_aoss`
  parser's SVI absorption (`_svi_absorption.py`) populates BOTH the VLAN record
  and a matching `CanonicalInterface`, so the sibling stanza the NX-OS renderer
  needs is always there and the address folds back onto the VLAN on re-parse.
  The matrix declaration is honest in general and simply does not bind on this
  source — which is why the measurement, not the matrix, decides the
  disposition.
* **`snmp.v3_users`** — the kitchen sink carries two SNMPv3 USM users; name,
  group, auth-protocol, priv-protocol and both opaque passphrase blobs
  round-trip byte-identically. The NX-OS matrix declares
  `/snmp/v3-user/auth-passphrase` / `priv-passphrase` / `engine-id` lossy
  (`localizedkey` digest normalisation), and that caveat is real for a live
  device, but it does not fire on this corpus.
* **`local_users[].hashed_password`** — preserved verbatim, including the
  AOS-S vendor tag, in the shape `sha1:<digest>` / `plaintext:<secret>`. The
  NX-OS render emits it as `username <name> password 0 <tagged-hash>
  role <role>` — a type-0 (plaintext-marker) field. The canonical string
  survives; it is not a credential the target device would accept.
* **`local_users[].role`** — the string survives verbatim (`manager` /
  `operator`), which is what the mesh scores; those are not NX-OS role names.
* **`interfaces[].ipv4_addresses` / `ipv6_addresses` / `switchport_mode` /
  `access_vlan` / `trunk_allowed_vlans` / `trunk_native_vlan` / `description` /
  `enabled` / `name` / `dhcp_client`** — all preserved on every cell that
  exercises them.
* **`static_routes`** — preserved on all 5 cells that populate routes, including
  the AOS-S `ip default-gateway` legacy form normalised to a `0.0.0.0/0`
  record. `metric` / `description` / `vrf` are never populated by this source.

## Structural absences (source-side, not target losses)

The `aruba_aoss` matrix declares these unsupported, so `CanonicalIntent` is
empty on every cell and the NX-OS target has nothing to drop:
`/system/domain`, `/system/syslog-server`, `/dhcp-servers/pool`,
`/vxlan-vnis/*`, `/routing-instances/instance`, `/anycast-gateway-mac`,
`/interfaces/interface/dot1q-vlan`. The AOS-S parser likewise never sets
`CanonicalInterface.mtu`, `CanonicalInterface.vrf` or
`CanonicalVlan.description`. `apply_groups` / `group_content` are Junos-only.
NX-OS *can* render most of these (domain, syslog, VXLAN, VRFs, anycast MAC),
so closing an AOS-S parse-side gap would move that row off `not_applicable`
rather than leave it there.

Two surfaces are dropped by BOTH codecs and are therefore `unsupported` rather
than `not_applicable` — closing the AOS-S parse side would not help, because
`cisco_nxos` renders neither: `/system/timezone` ("render emits no
clock/timezone stanza") and `/dhcp-servers/pool`. The same applies to
`/interfaces/interface/voice-vlan`, which the NX-OS codec explicitly declares
unsupported on render.

## Surfaces intentionally left without a YAML key

`interfaces[].vrrp_groups` and `interfaces[].tunnel_type` are modelled by both
codecs (each matrix declares them `lossy`, not `unsupported`) but no committed
AOS-S fixture populates either, so this corpus cannot evidence a disposition
for them. They carry no key rather than an invented one. The caveat operators
should know: the AOS-S parser DOES read `vrrp vrid N` inside a `vlan` stanza,
and the NX-OS renderer emits every `CanonicalVRRPGroup` as an `hsrp` block
regardless of the source `mode` — so an AOS-S VRRP group would arrive on the
target as HSRP, with the advertisement interval and group description dropped.
Re-audit both keys as soon as a fixture exercises them.

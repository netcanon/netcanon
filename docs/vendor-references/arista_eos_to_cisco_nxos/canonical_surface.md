# Arista EOS -> Cisco NX-OS: measured canonical surface

Source of truth for this note is **this repository**, not a vendor page:

* `netcanon/migration/codecs/arista_eos/codec.py` and
  `netcanon/migration/codecs/cisco_nxos/codec.py` — each codec's
  `CapabilityMatrix` (`supported` / `lossy` / `unsupported` xpaths), and
* a full in-process `tools/run_full_mesh.py` pass over the committed
  fixture corpus, filtered to the `(arista_eos, cisco_nxos)` cells.

Retrieved: 2026-08-20.

Both codecs declare `device_classes = [switch, router]`, so this is a
switch-to-switch pair with a wide shared surface: the realistic migration is
an Arista 7050/7280 EVPN-VXLAN leaf replaced by a Nexus 9000 in the same
fabric role.

## Corpus

6 fixture cells; **0 render errors, 0 re-parse errors**.

| cell |
|---|
| `batfish_duplicateprivate_eos4211.txt` |
| `batfish_eos_evpn_vlan_based_leaf.txt` |
| `batfish_labval_dc1_leaf2a_eos4230.txt` |
| `karneliuk_a_eos1_eos4260.txt` |
| `ksator_dcs_7150s64_eos4224.txt` |
| `synthetic/kitchen_sink.txt` |

## Per-field measurement (6 cells)

`trivial` = both sides carried no data on the field, so the cell could not
test any disposition.

| field | preserved | drifted | trivial | what drifts |
|---|---:|---:|---:|---|
| `hostname` | 6 | 0 | 0 | — |
| `domain` | 2 | 0 | 4 | — |
| `dns_servers` | 4 | 0 | 2 | — |
| `ntp_servers` | 4 | 0 | 2 | — |
| `timezone` | 0 | 0 | 6 | — (never populated) |
| `syslog_servers` | 1 | 0 | 5 | — |
| `interfaces` | 0 | 6 | 0 | `interface_type`, `lag_member_of`, `ipv4_addresses` |
| `vlans` | 2 | 2 | 2 | `ipv4_addresses` |
| `static_routes` | 5 | 0 | 1 | — |
| `dhcp_servers` | 0 | 1 | 5 | whole record — all pools dropped |
| `snmp` | 2 | 0 | 4 | — |
| `lags` | 0 | 3 | 3 | `name` |
| `local_users` | 1 | 5 | 0 | whole record (count drift), `privilege_level`, `role` |
| `radius_servers` | 0 | 0 | 6 | — (never populated) |
| `vxlan_vnis` | 4 | 0 | 2 | — |
| `evpn_type5_routes` | 0 | 0 | 6 | — (never populated) |
| `routing_instances` | 1 | 3 | 2 | `instance_type` |
| `raw_sections` | 0 | 0 | 6 | — (never populated) |
| `apply_groups` | 0 | 0 | 6 | — (Junos-only) |
| `group_content` | 0 | 0 | 6 | — (Junos-only) |
| `anycast_gateway_mac` | 2 | 0 | 4 | — |

## Sub-field drift — the authoritative list

These are the ONLY sub-fields that drift anywhere in the pair. Every other
sub-field of the same parent is preserved on every cell where it carries
data, which is why the expectation YAML omits the parent key and declares
`good` per sub-field.

| sub-field | cells | drift |
|---|---|---|
| `interfaces[].interface_type` | all 6 | `ianaift:ethernetCsmacd` -> `ianaift:other`, confined to `Management1` |
| `interfaces[].lag_member_of` | 3 | `Port-Channel<N>` -> `port-channel<N>` (case only) |
| `interfaces[].ipv4_addresses` | 1 | VARP-only SVI address list -> `[]` |
| `vlans[].ipv4_addresses` | 2 | SVI-on-VLAN address record -> `[]` |
| `lags[].name` | 3 | `Port-Channel<N>` -> `port-channel<N>` (case only) |
| `local_users` (whole record) | 2 | count drift 5 -> 3 and 3 -> 2 |
| `local_users[].privilege_level` | 2 | `1` -> `15` |
| `local_users[].role` | 1 | `""` -> `network-admin` |
| `routing_instances[].instance_type` | 3 | `mac-vrf` -> `vrf` |
| `dhcp_servers` (whole record) | 1 | all pools dropped |

## Notes grounding the dispositions

### `interfaces[].ipv4_addresses` / `vlans[].ipv4_addresses` — the SVI gateway

The largest operator-visible loss on this pair. Arista leaves express the
tenant gateway as VARP: `interface Vlan110` carrying `ip address virtual
10.1.10.1/24` and **no** primary `ip address`. Canonically that is an address
record with `ip=""` and `virtual_gateway_address` set. On
`batfish_eos_evpn_vlan_based_leaf` three SVIs (`Vlan110`, `Vlan111`,
`Vlan210`) render to NX-OS with `ipv4_addresses: []` — the whole address list
is gone, not just the anycast companion.

The NX-OS matrix declares
`/interfaces/interface/ipv4/address/virtual-gateway-address` **lossy** for
exactly this shape: NX-OS Distributed Anycast Gateway round-trips only when
`virtual_gateway_address == the interface's primary IP` (per-SVI `fabric
forwarding mode anycast-gateway`), so a *separate* VARP virtual address with
no primary IP has no NX-OS form and drops.

The VLAN-side variant is the same loss seen from the VLAN record: the Arista
parser folds SVI addressing onto `CanonicalVlan.ipv4_addresses`, and the
NX-OS matrix declares `/vlans/vlan/ipv4/address/ip` lossy — the render emits
an SVI only from a sibling `interface Vlan<N>` stanza, never from the VLAN
record.

### `local_users` — a password-less account disappears

Kept as a whole-record disposition because the record itself does not
survive: `ksator_dcs_7150s64` goes 5 users -> 3 and `kitchen_sink` goes
3 -> 2. On both cells the account that vanishes is the one with an EMPTY
`hashed_password` (Arista `username admin privilege 15 nopassword ... role
network-admin`). NX-OS `username` render has no password-less form, so the
account is not emitted at all.

Everything else about the surviving users is re-derived rather than carried:

* `privilege_level` — NX-OS models a named `role`, not a number. The codec
  maps `network-admin` / `vdc-admin` -> 15 and everything else -> 1
  (`/local-users/user/privilege-level`, declared lossy). Measured on two
  cells as `1` -> `15` for a user whose role is `network-admin`.
* `role` — a blank source role is filled in on render, measured as `""` ->
  `network-admin` on `karneliuk_a_eos1`.
* `hashed_password` — preserved verbatim, including the vendor/type marker.
  Shape only: `arista:sha512:$6$<salt>$<digest>` on both sides. No drift.

### `lags[].name` / `interfaces[].lag_member_of` — case, not content

The bundle, its member list and its LACP mode all survive. Only the spelling
changes: `Port-Channel3` -> `port-channel3`, NX-OS's native lowercase form.
Nothing is lost on the device. It still counts as drift because the
reconciler's LAG canonicalisation (`_canonical_lag_name` in
`tools/run_phase4_reconciliation.py`) recognises `ae<N>` / `Po<N>` /
`Port-channel<N>` / `Port-Channel<N>` / `trk<N>` / `agg<N>` / `bond<N>` but
not the lowercase NX-OS spelling, so name-keyed joins across the migration
(rename panes, inventory diffs) see every bundle as changed.

### `interfaces[].interface_type` — `Management1` only

Cosmetic and confined to the management port on all 6 cells. NX-OS infers
the IANA ifType from the name prefix (`Ethernet` -> `ethernetCsmacd`,
`loopback` -> `softwareLoopback`, `Vlan` -> `l3ipvlan`, `port-channel` ->
`ieee8023adLag`, `nve` -> `tunnel`, `mgmt` -> ...). Arista's `Management1`
matches no entry in that table, so it lands on `ianaift:other`. The
interface, its addressing and its state all survive.

### `routing_instances[].instance_type` — `mac-vrf` collapses to `vrf`

Arista EVPN leaves declare a per-VLAN MAC-VRF (`router bgp / vlan <id>`
instances parsed as `instance_type="mac-vrf"`). NX-OS renders every routing
instance as `vrf context <name>`, which has no MAC-VRF form, so the
discriminator downgrades to `vrf` (`/routing-instances/instance/instance-type`,
declared lossy). Measured on 3 cells, 8 instances. The instance name, RD, RTs
and L3 VNI all round-trip.

### `dhcp_servers` — the record cannot be represented

`kitchen_sink` carries 2 pools; the NX-OS render emits none ("all 2
dhcp_servers dropped"). The NX-OS matrix declares `/dhcp-servers/pool`
**unsupported** — "Render emits no DHCP server pool; intent.dhcp_servers are
dropped on migration". The whole record vanishes, so this is `unsupported`,
not `lossy`.

### Fields declared from the matrices because no fixture exercises them

Stated so the basis is explicit rather than implied:

* `timezone` — both matrices declare `/system/timezone` unsupported with the
  same reason ("Render emits no clock/timezone stanza"). Never populated on
  this pair, so the declaration is the only evidence.
* `radius_servers` — the NX-OS matrix declares BOTH
  `/radius-servers/server/host` and `/radius-servers/server/key` unsupported
  ("Render emits no AAA radius-server config"). No committed Arista fixture
  populates the field, so nothing was observed dropping.
* `interfaces[].voice_vlan` — declared unsupported by BOTH matrices.
* `interfaces[].vrrp_groups` — the NX-OS matrix declares
  `/interfaces/interface/vrrp-groups/group` lossy: every `CanonicalVRRPGroup`
  renders as an `hsrp` block regardless of the source `mode`, and the
  advertisement interval, IPv6 virtual addresses and group description are
  dropped. No Arista fixture on this pair carries a VRRP group.
* `interfaces[].tunnel_type` — NX-OS lossy: `gre` / `ipip` round-trip,
  `ipsec` / `vxlan` / `eoip` have no NX-OS interface-encap equivalent.
* `vlans[].description` and `static_routes[].description` — declared lossy by
  both matrices (the NX-OS render emits the VLAN name but no separate
  description line, and emits destination + next-hop + metric only). Neither
  is populated by any fixture on this pair.

### Declared `good` DESPITE a target-side lossy path, because nothing drifted

The measurement outranks the matrix here — declaring these lossy would claim
a loss the corpus never exhibits:

* `vxlan_vnis[].udp_port` — NX-OS declares `/vxlan-vnis/udp-port` lossy (a
  non-default port such as the legacy 8472 is dropped), but all 4 populated
  cells use the IANA default 4789 and preserve it.
* `vxlan_vnis[].vni` — NX-OS declares `/vxlan-vnis/vni` lossy for per-VNI
  sub-flags (`suppress-arp`, `ingress-replication protocol bgp`) that live
  below canonical granularity. The VNI value itself preserves on all 4 cells.
* `routing_instances[].route_distinguisher` / `[].rt_imports` — NX-OS
  declares both lossy (the `rd auto` sentinel and the `route-target both <rt>
  evpn` address-family discriminator), but neither drifts on this corpus.
* `snmp.v3_users` — NX-OS declares the v3 auth and privacy passphrases lossy
  (the codec normalises to the older `localizedkey` digest form). `snmp`
  preserves on both populated cells, so no re-keying was observed.

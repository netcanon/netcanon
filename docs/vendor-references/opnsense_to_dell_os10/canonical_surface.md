# OPNsense → Dell OS10: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/opnsense__dell_os10.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key dispositions were resolved through the audit's own `actual_disposition()` rather than inferred from the drift shape, so this file and the ratchet agree by construction.

- Fixture cells: **8**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-09-21

> **No device-vendor documentation was consulted for this file.** Everything below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix` declarations and the measured mesh run. Where a disposition rests on a declaration rather than an observed round-trip, the YAML says so explicitly.

## Why the dispositions could not be written in advance

The binding constraint on this pair is not the capability matrices, it is `test_no_new_pair_declares_a_loss_it_never_observes`: a pair absent from `_UNEVIDENCED_BASELINE` is allowed **zero** fields that are declared lossy/unsupported but never observed to drift. So a field this corpus preserves on every cell must be `good` — hedging it to `lossy` fails the build exactly as under-declaring a real loss does. Every row below was measured first.

## Structural finding

Across the 8 cells, 30 source interface records produce 40 re-parsed records — the interface inventory is intact.

## Disposition summary

| Disposition | Fields |
|---|---|
| `good` | 21 |
| `lossy` | 10 |
| `unsupported` | 13 |
| `not_applicable` | 2 |

## Per-field measurement

`preserved` / `drifted` / `both-empty` are cell counts. A field with `drifted` 0 and `preserved` > 0 is `good` by rule. Some fields with `drifted` > 0 are **also** `good`, and that is not a loss being hidden: where a list parent drifted wholesale, the reconciler attributes that single structural event to one owner sub-field and collapses its siblings to `STRUCTURAL_ONLY`, so those siblings evidence no *independent* loss on this pair. Each such field's YAML note says so explicitly, and the parent-level drift stays recorded against the owner key.

| Field | Disposition | preserved | drifted | both-empty |
|---|---|---|---|---|
| `anycast_gateway_mac` | unsupported | 0 | 0 | 8 |
| `apply_groups` | good | 0 | 0 | 8 |
| `dhcp_servers` | unsupported | 0 | 4 | 4 |
| `dns_servers` | unsupported | 0 | 4 | 4 |
| `domain` | unsupported | 0 | 7 | 1 |
| `evpn_type5_routes` | unsupported | 0 | 0 | 8 |
| `group_content` | good | 0 | 0 | 8 |
| `hostname` | good | 7 | 0 | 1 |
| `interfaces[].description` | lossy | 3 | 2 | 3 |
| `interfaces[].enabled` | good | 6 | 2 | 0 |
| `interfaces[].interface_type` | lossy | 0 | 8 | 0 |
| `interfaces[].ipv4_addresses` | good | 6 | 2 | 0 |
| `interfaces[].ipv6_addresses` | lossy | 0 | 2 | 6 |
| `interfaces[].lag_member_of` | lossy | 0 | 2 | 6 |
| `interfaces[].mtu` | lossy | 0 | 2 | 6 |
| `interfaces[].name` | good | 6 | 2 | 0 |
| `interfaces[].vrrp_groups` | lossy | 0 | 4 | 4 |
| `lags` | lossy | 0 | 1 | 7 |
| `local_users` | lossy | 0 | 7 | 1 |
| `local_users[].hashed_password` | lossy | 0 | 7 | 1 |
| `local_users[].name` | good | 2 | 5 | 1 |
| `local_users[].role` | good | 2 | 5 | 1 |
| `ntp_servers` | unsupported | 0 | 0 | 8 |
| `radius_servers` | unsupported | 0 | 1 | 7 |
| `raw_sections` | good | 0 | 0 | 8 |
| `routing_instances` | good | 0 | 0 | 8 |
| `routing_instances[].description` | good | 0 | 0 | 8 |
| `routing_instances[].name` | good | 0 | 0 | 8 |
| `snmp.community` | good | 3 | 0 | 5 |
| `snmp.contact` | good | 3 | 0 | 5 |
| `snmp.location` | good | 3 | 0 | 5 |
| `snmp.trap_hosts` | good | 3 | 0 | 5 |
| `snmp.v3_users` | good | 3 | 0 | 5 |
| `static_routes` | lossy | 2 | 1 | 5 |
| `syslog_servers` | unsupported | 0 | 0 | 8 |
| `timezone` | unsupported | 0 | 0 | 8 |
| `vlans[].description` | good | 0 | 0 | 8 |
| `vlans[].id` | good | 2 | 0 | 6 |
| `vlans[].ipv4_addresses` | good | 0 | 0 | 8 |
| `vlans[].name` | good | 2 | 0 | 6 |
| `vlans[].tagged_ports` | not_applicable | 0 | 0 | 8 |
| `vlans[].untagged_ports` | not_applicable | 0 | 0 | 8 |
| `vxlan_vnis` | unsupported | 0 | 0 | 8 |
| `vxlan_vnis[].mcast_group` | unsupported | 0 | 0 | 8 |
| `vxlan_vnis[].vlan_id` | unsupported | 0 | 0 | 8 |
| `vxlan_vnis[].vni` | unsupported | 0 | 0 | 8 |

## Observed loss mechanisms

### `anycast_gateway_mac` — unsupported

Drifted on 0 of 8 cells (preserved on 0, both sides empty on 8).

> OS10 expresses first-hop redundancy as real VRRP, not a chassis-wide anycast-gateway MAC; nothing renders it.

### `dhcp_servers` — unsupported

Drifted on 4 of 8 cells (preserved on 0, both sides empty on 4).

> Phase 1 parses no DHCP server pool.

Sample: `all 1 dhcp_servers dropped`

### `dns_servers` — unsupported

Drifted on 4 of 8 cells (preserved on 0, both sides empty on 4).

> Phase 1 parses no `ip name-server`.

Sample: `all 1 dns_servers dropped`

### `domain` — unsupported

Drifted on 7 of 8 cells (preserved on 0, both sides empty on 1).

> Phase 1 parses no `ip domain-name`.

Sample: `domain: 'localdomain' → ''`

### `evpn_type5_routes` — unsupported

Drifted on 0 of 8 cells (preserved on 0, both sides empty on 8).

> No EVPN is rendered; BGP / EVPN is Tier-3 on OS10.

### `interfaces[].description` — lossy

Drifted on 2 of 8 cells (preserved on 3, both sides empty on 3).

> OPNsense imposes no length limit on description text; other vendors (Cisco 240 chars, Juniper 900) may truncate on render.

### `interfaces[].interface_type` — lossy

Drifted on 8 of 8 cells (preserved on 0, both sides empty on 0).

> OS10 interface-type is inferred from the name prefix (ethernet -> ethernetCsmacd, vlan -> l3ipvlan, port-channel -> ieee8023adLag, loopback -> softwareLoopback, mgmt -> ethernetCsmacd).  Inference is best-effort and will not recover every IANA type a cross-vendor source carried.

### `interfaces[].ipv6_addresses` — lossy

Drifted on 2 of 8 cells (preserved on 0, both sides empty on 6).

### `interfaces[].lag_member_of` — lossy

Drifted on 2 of 8 cells (preserved on 0, both sides empty on 6).

### `interfaces[].mtu` — lossy

Drifted on 2 of 8 cells (preserved on 0, both sides empty on 6).

### `interfaces[].vrrp_groups` — lossy

Drifted on 4 of 8 cells (preserved on 0, both sides empty on 4).

> OPNsense's <virtualip> hosts CARP-only HA groups in the v1 wire-up.  CanonicalVRRPGroup records with mode='vrrp' or mode='hsrp' are SKIPPED on render — OPNsense has no native HSRP wire protocol, and its pure-VRRP mode under <virtualip> is rarely deployed and not yet emitted by this codec.  Only mode='carp' round-trips.  Additionally, the advskew↔priority mapping (priority = 254 - advskew) preserves relative HA-pair ordering but not exact election timing — VRRP priorities are advisory weights, CARP advskews are advertisement-interval offsets, so cross-protocol migration loses the timing semantics.

### `lags` — lossy

Drifted on 1 of 8 cells (preserved on 0, both sides empty on 7).

Sample: `all 1 lags dropped`

### `local_users` — lossy

Drifted on 7 of 8 cells (preserved on 0, both sides empty on 1).

### `local_users[].hashed_password` — lossy

Drifted on 7 of 8 cells (preserved on 0, both sides empty on 1).

### `ntp_servers` — unsupported

Drifted on 0 of 8 cells (preserved on 0, both sides empty on 8).

> Phase 1 parses no `ntp server`.

### `radius_servers` — unsupported

Drifted on 1 of 8 cells (preserved on 0, both sides empty on 7).

> Phase 1 parses no AAA radius-server config.

Sample: `all 2 radius_servers dropped`

### `static_routes` — lossy

Drifted on 1 of 8 cells (preserved on 2, both sides empty on 5).

> Parse harvests routes (the <gateways> default route + <staticroutes>/<route> entries, resolving named gateways to their IP; promotion #15), but the config.xml renderer emits no <staticroutes>/<route> block, so the ENTIRE route is dropped on render. Declared unsupported (block): the record does not survive, which is not a lossy round-trip (audit f92e97a T0-1; severity corrected in the scope re-weight wave).

Sample: `{"static_routes[0] {'destination': '172.16.0.0/12'}": {'description': {'source': 'Corporate transit', 'target': ''}}}`

### `syslog_servers` — unsupported

Drifted on 0 of 8 cells (preserved on 0, both sides empty on 8).

> Phase 1 parses no `logging server`.

### `timezone` — unsupported

Drifted on 0 of 8 cells (preserved on 0, both sides empty on 8).

> Phase 1 parses no `clock timezone` stanza; intent.timezone is dropped.

### `vxlan_vnis` — unsupported

Drifted on 0 of 8 cells (preserved on 0, both sides empty on 8).

> OS10 VXLAN uses a `virtual-network <vnid>` indirection between VLAN and VNI rather than NX-OS's direct `vlan N / vn-segment` binding; deferred past v1.

### `vxlan_vnis[].mcast_group` — unsupported

Drifted on 0 of 8 cells (preserved on 0, both sides empty on 8).

> No VXLAN overlay is rendered.

### `vxlan_vnis[].vlan_id` — unsupported

Drifted on 0 of 8 cells (preserved on 0, both sides empty on 8).

> No VXLAN overlay is rendered (see /vxlan-vnis/vni).

### `vxlan_vnis[].vni` — unsupported

Drifted on 0 of 8 cells (preserved on 0, both sides empty on 8).

> OS10 VXLAN uses a `virtual-network <vnid>` indirection between VLAN and VNI rather than NX-OS's direct `vlan N / vn-segment` binding; deferred past v1.

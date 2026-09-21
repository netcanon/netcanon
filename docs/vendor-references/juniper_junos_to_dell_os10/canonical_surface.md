# Junos → Dell OS10: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/juniper_junos__dell_os10.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key dispositions were resolved through the audit's own `actual_disposition()` rather than inferred from the drift shape, so this file and the ratchet agree by construction.

- Fixture cells: **11**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-09-21

> **No device-vendor documentation was consulted for this file.** Everything below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix` declarations and the measured mesh run. Where a disposition rests on a declaration rather than an observed round-trip, the YAML says so explicitly.

## Why the dispositions could not be written in advance

The binding constraint on this pair is not the capability matrices, it is `test_no_new_pair_declares_a_loss_it_never_observes`: a pair absent from `_UNEVIDENCED_BASELINE` is allowed **zero** fields that are declared lossy/unsupported but never observed to drift. So a field this corpus preserves on every cell must be `good` — hedging it to `lossy` fails the build exactly as under-declaring a real loss does. Every row below was measured first.

## Structural finding

Across the 11 cells, 151 source interface records produce 277 re-parsed records — the interface inventory is intact.

## Disposition summary

| Disposition | Fields |
|---|---|
| `good` | 20 |
| `lossy` | 13 |
| `unsupported` | 13 |
| `not_applicable` | 0 |

## Per-field measurement

`preserved` / `drifted` / `both-empty` are cell counts. A field with `drifted` 0 and `preserved` > 0 is `good` by rule. Some fields with `drifted` > 0 are **also** `good`, and that is not a loss being hidden: where a list parent drifted wholesale, the reconciler attributes that single structural event to one owner sub-field and collapses its siblings to `STRUCTURAL_ONLY`, so those siblings evidence no *independent* loss on this pair. Each such field's YAML note says so explicitly, and the parent-level drift stays recorded against the owner key.

| Field | Disposition | preserved | drifted | both-empty |
|---|---|---|---|---|
| `anycast_gateway_mac` | unsupported | 0 | 0 | 11 |
| `apply_groups` | lossy | 0 | 6 | 5 |
| `dhcp_servers` | unsupported | 0 | 2 | 9 |
| `dns_servers` | unsupported | 0 | 6 | 5 |
| `domain` | unsupported | 0 | 2 | 9 |
| `evpn_type5_routes` | unsupported | 0 | 0 | 11 |
| `group_content` | lossy | 0 | 6 | 5 |
| `hostname` | good | 10 | 0 | 1 |
| `interfaces[].description` | lossy | 2 | 7 | 2 |
| `interfaces[].enabled` | good | 4 | 7 | 0 |
| `interfaces[].interface_type` | lossy | 0 | 11 | 0 |
| `interfaces[].ipv4_addresses` | good | 3 | 7 | 1 |
| `interfaces[].ipv6_addresses` | good | 3 | 7 | 1 |
| `interfaces[].lag_member_of` | lossy | 0 | 7 | 4 |
| `interfaces[].mtu` | lossy | 0 | 7 | 4 |
| `interfaces[].name` | good | 4 | 7 | 0 |
| `interfaces[].vrrp_groups` | lossy | 0 | 7 | 4 |
| `lags` | lossy | 0 | 5 | 6 |
| `local_users` | lossy | 0 | 8 | 3 |
| `local_users[].hashed_password` | lossy | 0 | 8 | 3 |
| `local_users[].name` | good | 7 | 1 | 3 |
| `local_users[].role` | good | 7 | 1 | 3 |
| `ntp_servers` | unsupported | 0 | 6 | 5 |
| `radius_servers` | unsupported | 0 | 0 | 11 |
| `raw_sections` | good | 0 | 0 | 11 |
| `routing_instances` | lossy | 0 | 6 | 5 |
| `routing_instances[].description` | lossy | 0 | 2 | 9 |
| `routing_instances[].name` | good | 6 | 0 | 5 |
| `snmp.community` | good | 6 | 0 | 5 |
| `snmp.contact` | good | 6 | 0 | 5 |
| `snmp.location` | good | 6 | 0 | 5 |
| `snmp.trap_hosts` | good | 6 | 0 | 5 |
| `snmp.v3_users` | lossy | 4 | 2 | 5 |
| `static_routes` | good | 9 | 0 | 2 |
| `syslog_servers` | unsupported | 0 | 6 | 5 |
| `timezone` | unsupported | 0 | 0 | 11 |
| `vlans[].description` | good | 0 | 0 | 11 |
| `vlans[].id` | good | 7 | 0 | 4 |
| `vlans[].ipv4_addresses` | good | 1 | 0 | 10 |
| `vlans[].name` | good | 7 | 0 | 4 |
| `vlans[].tagged_ports` | good | 6 | 0 | 5 |
| `vlans[].untagged_ports` | good | 0 | 0 | 11 |
| `vxlan_vnis` | unsupported | 0 | 3 | 8 |
| `vxlan_vnis[].mcast_group` | unsupported | 0 | 3 | 8 |
| `vxlan_vnis[].vlan_id` | unsupported | 0 | 3 | 8 |
| `vxlan_vnis[].vni` | unsupported | 0 | 3 | 8 |

## Observed loss mechanisms

### `anycast_gateway_mac` — unsupported

Drifted on 0 of 11 cells (preserved on 0, both sides empty on 11).

> OS10 expresses first-hop redundancy as real VRRP, not a chassis-wide anycast-gateway MAC; nothing renders it.

### `apply_groups` — lossy

Drifted on 6 of 11 cells (preserved on 0, both sides empty on 5).

Sample: `all 1 apply_groups dropped`

### `dhcp_servers` — unsupported

Drifted on 2 of 11 cells (preserved on 0, both sides empty on 9).

> Phase 1 parses no DHCP server pool.

Sample: `all 4 dhcp_servers dropped`

### `dns_servers` — unsupported

Drifted on 6 of 11 cells (preserved on 0, both sides empty on 5).

> Phase 1 parses no `ip name-server`.

Sample: `all 1 dns_servers dropped`

### `domain` — unsupported

Drifted on 2 of 11 cells (preserved on 0, both sides empty on 9).

> Phase 1 parses no `ip domain-name`.

Sample: `domain: 'example.com' → ''`

### `evpn_type5_routes` — unsupported

Drifted on 0 of 11 cells (preserved on 0, both sides empty on 11).

> No EVPN is rendered; BGP / EVPN is Tier-3 on OS10.

### `group_content` — lossy

Drifted on 6 of 11 cells (preserved on 0, both sides empty on 5).

Sample: `{'only_in_source': ['MNHA-SYNC'], 'only_in_target': [], 'value_drift_keys': []}`

### `interfaces[].description` — lossy

Drifted on 7 of 11 cells (preserved on 2, both sides empty on 2).

### `interfaces[].interface_type` — lossy

Drifted on 11 of 11 cells (preserved on 0, both sides empty on 0).

> OS10 interface-type is inferred from the name prefix (ethernet -> ethernetCsmacd, vlan -> l3ipvlan, port-channel -> ieee8023adLag, loopback -> softwareLoopback, mgmt -> ethernetCsmacd).  Inference is best-effort and will not recover every IANA type a cross-vendor source carried.

### `interfaces[].lag_member_of` — lossy

Drifted on 7 of 11 cells (preserved on 0, both sides empty on 4).

### `interfaces[].mtu` — lossy

Drifted on 7 of 11 cells (preserved on 0, both sides empty on 4).

### `interfaces[].vrrp_groups` — lossy

Drifted on 7 of 11 cells (preserved on 0, both sides empty on 4).

### `lags` — lossy

Drifted on 5 of 11 cells (preserved on 0, both sides empty on 6).

Sample: `all 2 lags dropped`

### `local_users` — lossy

Drifted on 8 of 11 cells (preserved on 0, both sides empty on 3).

### `local_users[].hashed_password` — lossy

Drifted on 8 of 11 cells (preserved on 0, both sides empty on 3).

### `ntp_servers` — unsupported

Drifted on 6 of 11 cells (preserved on 0, both sides empty on 5).

> Phase 1 parses no `ntp server`.

Sample: `all 1 ntp_servers dropped`

### `radius_servers` — unsupported

Drifted on 0 of 11 cells (preserved on 0, both sides empty on 11).

> Phase 1 parses no AAA radius-server config.

### `routing_instances` — lossy

Drifted on 6 of 11 cells (preserved on 0, both sides empty on 5).

Sample: `{"routing_instances[0] {'name': 'TENANT-A'}": {'l3_vni': {'source': 50000, 'target': None}, 'route_distinguisher': {'source': '172.16.0.100:10000', 'target': ''}, 'rt_exports': {'s`

### `routing_instances[].description` — lossy

Drifted on 2 of 11 cells (preserved on 0, both sides empty on 9).

> The OS10 `ip vrf <name>` stanza carries no description line; the VRF renders, its description does not.

### `snmp.v3_users` — lossy

Drifted on 2 of 11 cells (preserved on 4, both sides empty on 5).

### `syslog_servers` — unsupported

Drifted on 6 of 11 cells (preserved on 0, both sides empty on 5).

> Phase 1 parses no `logging server`.

Sample: `all 2 syslog_servers dropped`

### `timezone` — unsupported

Drifted on 0 of 11 cells (preserved on 0, both sides empty on 11).

> Phase 1 parses no `clock timezone` stanza; intent.timezone is dropped.

### `vxlan_vnis` — unsupported

Drifted on 3 of 11 cells (preserved on 0, both sides empty on 8).

> OS10 VXLAN uses a `virtual-network <vnid>` indirection between VLAN and VNI rather than NX-OS's direct `vlan N / vn-segment` binding; deferred past v1.

Sample: `all 4 vxlan_vnis dropped`

### `vxlan_vnis[].mcast_group` — unsupported

Drifted on 3 of 11 cells (preserved on 0, both sides empty on 8).

> No VXLAN overlay is rendered.

### `vxlan_vnis[].vlan_id` — unsupported

Drifted on 3 of 11 cells (preserved on 0, both sides empty on 8).

> No VXLAN overlay is rendered (see /vxlan-vnis/vni).

### `vxlan_vnis[].vni` — unsupported

Drifted on 3 of 11 cells (preserved on 0, both sides empty on 8).

> OS10 VXLAN uses a `virtual-network <vnid>` indirection between VLAN and VNI rather than NX-OS's direct `vlan N / vn-segment` binding; deferred past v1.

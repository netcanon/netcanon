# Arista EOS → Dell OS10: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/arista_eos__dell_os10.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key dispositions were resolved through the audit's own `actual_disposition()` rather than inferred from the drift shape, so this file and the ratchet agree by construction.

- Fixture cells: **6**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-09-21

> **No device-vendor documentation was consulted for this file.** Everything below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix` declarations and the measured mesh run. Where a disposition rests on a declaration rather than an observed round-trip, the YAML says so explicitly.

## Why the dispositions could not be written in advance

The binding constraint on this pair is not the capability matrices, it is `test_no_new_pair_declares_a_loss_it_never_observes`: a pair absent from `_UNEVIDENCED_BASELINE` is allowed **zero** fields that are declared lossy/unsupported but never observed to drift. So a field this corpus preserves on every cell must be `good` — hedging it to `lossy` fails the build exactly as under-declaring a real loss does. Every row below was measured first.

## Structural finding

Across the 6 cells, 169 source interface records produce 173 re-parsed records — the interface inventory is intact.

## Disposition summary

| Disposition | Fields |
|---|---|
| `good` | 17 |
| `lossy` | 16 |
| `unsupported` | 13 |
| `not_applicable` | 0 |

## Per-field measurement

`preserved` / `drifted` / `both-empty` are cell counts. A field with `drifted` 0 and `preserved` > 0 is `good` by rule. Some fields with `drifted` > 0 are **also** `good`, and that is not a loss being hidden: where a list parent drifted wholesale, the reconciler attributes that single structural event to one owner sub-field and collapses its siblings to `STRUCTURAL_ONLY`, so those siblings evidence no *independent* loss on this pair. Each such field's YAML note says so explicitly, and the parent-level drift stays recorded against the owner key.

| Field | Disposition | preserved | drifted | both-empty |
|---|---|---|---|---|
| `anycast_gateway_mac` | unsupported | 0 | 2 | 4 |
| `apply_groups` | good | 0 | 0 | 6 |
| `dhcp_servers` | unsupported | 0 | 1 | 5 |
| `dns_servers` | unsupported | 0 | 4 | 2 |
| `domain` | unsupported | 0 | 2 | 4 |
| `evpn_type5_routes` | unsupported | 0 | 0 | 6 |
| `group_content` | good | 0 | 0 | 6 |
| `hostname` | good | 6 | 0 | 0 |
| `interfaces[].description` | lossy | 2 | 3 | 1 |
| `interfaces[].enabled` | good | 3 | 3 | 0 |
| `interfaces[].interface_type` | lossy | 0 | 6 | 0 |
| `interfaces[].ipv4_addresses` | lossy | 2 | 4 | 0 |
| `interfaces[].ipv6_addresses` | lossy | 0 | 3 | 3 |
| `interfaces[].lag_member_of` | lossy | 0 | 4 | 2 |
| `interfaces[].mtu` | lossy | 0 | 3 | 3 |
| `interfaces[].name` | lossy | 2 | 4 | 0 |
| `interfaces[].vrrp_groups` | lossy | 0 | 3 | 3 |
| `lags` | lossy | 0 | 3 | 3 |
| `local_users` | lossy | 0 | 6 | 0 |
| `local_users[].hashed_password` | lossy | 0 | 6 | 0 |
| `local_users[].name` | good | 4 | 2 | 0 |
| `local_users[].role` | lossy | 3 | 3 | 0 |
| `ntp_servers` | unsupported | 0 | 4 | 2 |
| `radius_servers` | unsupported | 0 | 0 | 6 |
| `raw_sections` | good | 0 | 0 | 6 |
| `routing_instances` | lossy | 0 | 4 | 2 |
| `routing_instances[].description` | good | 0 | 0 | 6 |
| `routing_instances[].name` | good | 4 | 0 | 2 |
| `snmp.community` | good | 2 | 0 | 4 |
| `snmp.contact` | good | 2 | 0 | 4 |
| `snmp.location` | good | 2 | 0 | 4 |
| `snmp.trap_hosts` | good | 2 | 0 | 4 |
| `snmp.v3_users` | lossy | 1 | 1 | 4 |
| `static_routes` | good | 5 | 0 | 1 |
| `syslog_servers` | unsupported | 0 | 1 | 5 |
| `timezone` | unsupported | 0 | 0 | 6 |
| `vlans[].description` | good | 0 | 0 | 6 |
| `vlans[].id` | good | 4 | 0 | 2 |
| `vlans[].ipv4_addresses` | lossy | 1 | 2 | 3 |
| `vlans[].name` | lossy | 1 | 3 | 2 |
| `vlans[].tagged_ports` | good | 3 | 0 | 3 |
| `vlans[].untagged_ports` | good | 2 | 0 | 4 |
| `vxlan_vnis` | unsupported | 0 | 4 | 2 |
| `vxlan_vnis[].mcast_group` | unsupported | 0 | 4 | 2 |
| `vxlan_vnis[].vlan_id` | unsupported | 0 | 4 | 2 |
| `vxlan_vnis[].vni` | unsupported | 0 | 4 | 2 |

## Observed loss mechanisms

### `anycast_gateway_mac` — unsupported

Drifted on 2 of 6 cells (preserved on 0, both sides empty on 4).

> OS10 expresses first-hop redundancy as real VRRP, not a chassis-wide anycast-gateway MAC; nothing renders it.

Sample: `anycast_gateway_mac: '00:dc:00:00:00:01' → ''`

### `dhcp_servers` — unsupported

Drifted on 1 of 6 cells (preserved on 0, both sides empty on 5).

> Phase 1 parses no DHCP server pool.

Sample: `all 2 dhcp_servers dropped`

### `dns_servers` — unsupported

Drifted on 4 of 6 cells (preserved on 0, both sides empty on 2).

> Phase 1 parses no `ip name-server`.

Sample: `all 2 dns_servers dropped`

### `domain` — unsupported

Drifted on 2 of 6 cells (preserved on 0, both sides empty on 4).

> Phase 1 parses no `ip domain-name`.

Sample: `domain: 'lab.local' → ''`

### `evpn_type5_routes` — unsupported

Drifted on 0 of 6 cells (preserved on 0, both sides empty on 6).

> No EVPN is rendered; BGP / EVPN is Tier-3 on OS10.

### `interfaces[].description` — lossy

Drifted on 3 of 6 cells (preserved on 2, both sides empty on 1).

### `interfaces[].interface_type` — lossy

Drifted on 6 of 6 cells (preserved on 0, both sides empty on 0).

> OS10 interface-type is inferred from the name prefix (ethernet -> ethernetCsmacd, vlan -> l3ipvlan, port-channel -> ieee8023adLag, loopback -> softwareLoopback, mgmt -> ethernetCsmacd).  Inference is best-effort and will not recover every IANA type a cross-vendor source carried.

### `interfaces[].ipv4_addresses` — lossy

Drifted on 4 of 6 cells (preserved on 2, both sides empty on 0).

### `interfaces[].ipv6_addresses` — lossy

Drifted on 3 of 6 cells (preserved on 0, both sides empty on 3).

### `interfaces[].lag_member_of` — lossy

Drifted on 4 of 6 cells (preserved on 0, both sides empty on 2).

### `interfaces[].mtu` — lossy

Drifted on 3 of 6 cells (preserved on 0, both sides empty on 3).

### `interfaces[].name` — lossy

Drifted on 4 of 6 cells (preserved on 2, both sides empty on 0).

### `interfaces[].vrrp_groups` — lossy

Drifted on 3 of 6 cells (preserved on 0, both sides empty on 3).

### `lags` — lossy

Drifted on 3 of 6 cells (preserved on 0, both sides empty on 3).

Sample: `{"lags[0] {'name': 'Port-Channel3'}": {'name': {'source': 'Port-Channel3', 'target': 'port-channel3'}}, "lags[1] {'name': 'Port-Channel5'}": {'name': {'source': 'Port-Channel5', 't`

### `local_users` — lossy

Drifted on 6 of 6 cells (preserved on 0, both sides empty on 0).

### `local_users[].hashed_password` — lossy

Drifted on 6 of 6 cells (preserved on 0, both sides empty on 0).

### `local_users[].role` — lossy

Drifted on 3 of 6 cells (preserved on 3, both sides empty on 0).

### `ntp_servers` — unsupported

Drifted on 4 of 6 cells (preserved on 0, both sides empty on 2).

> Phase 1 parses no `ntp server`.

Sample: `all 2 ntp_servers dropped`

### `radius_servers` — unsupported

Drifted on 0 of 6 cells (preserved on 0, both sides empty on 6).

> Phase 1 parses no AAA radius-server config.

### `routing_instances` — lossy

Drifted on 4 of 6 cells (preserved on 0, both sides empty on 2).

Sample: `{"routing_instances[1] {'name': 'Tenant_A_OPZone'}": {'l3_vni': {'source': 50101, 'target': None}, 'route_distinguisher': {'source': '192.168.255.4:50101', 'target': ''}, 'rt_expor`

### `snmp.v3_users` — lossy

Drifted on 1 of 6 cells (preserved on 1, both sides empty on 4).

### `syslog_servers` — unsupported

Drifted on 1 of 6 cells (preserved on 0, both sides empty on 5).

> Phase 1 parses no `logging server`.

Sample: `all 1 syslog_servers dropped`

### `timezone` — unsupported

Drifted on 0 of 6 cells (preserved on 0, both sides empty on 6).

> Phase 1 parses no `clock timezone` stanza; intent.timezone is dropped.

### `vlans[].ipv4_addresses` — lossy

Drifted on 2 of 6 cells (preserved on 1, both sides empty on 3).

### `vlans[].name` — lossy

Drifted on 3 of 6 cells (preserved on 1, both sides empty on 2).

### `vxlan_vnis` — unsupported

Drifted on 4 of 6 cells (preserved on 0, both sides empty on 2).

> OS10 VXLAN uses a `virtual-network <vnid>` indirection between VLAN and VNI rather than NX-OS's direct `vlan N / vn-segment` binding; deferred past v1.

Sample: `all 6 vxlan_vnis dropped`

### `vxlan_vnis[].mcast_group` — unsupported

Drifted on 4 of 6 cells (preserved on 0, both sides empty on 2).

> No VXLAN overlay is rendered.

### `vxlan_vnis[].vlan_id` — unsupported

Drifted on 4 of 6 cells (preserved on 0, both sides empty on 2).

> No VXLAN overlay is rendered (see /vxlan-vnis/vni).

### `vxlan_vnis[].vni` — unsupported

Drifted on 4 of 6 cells (preserved on 0, both sides empty on 2).

> OS10 VXLAN uses a `virtual-network <vnid>` indirection between VLAN and VNI rather than NX-OS's direct `vlan N / vn-segment` binding; deferred past v1.

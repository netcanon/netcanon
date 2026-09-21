# Cisco IOS-XE → Dell OS10: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/cisco_iosxe_cli__dell_os10.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key dispositions were resolved through the audit's own `actual_disposition()` rather than inferred from the drift shape, so this file and the ratchet agree by construction.

- Fixture cells: **15**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-09-21

> **No device-vendor documentation was consulted for this file.** Everything below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix` declarations and the measured mesh run. Where a disposition rests on a declaration rather than an observed round-trip, the YAML says so explicitly.

## Why the dispositions could not be written in advance

The binding constraint on this pair is not the capability matrices, it is `test_no_new_pair_declares_a_loss_it_never_observes`: a pair absent from `_UNEVIDENCED_BASELINE` is allowed **zero** fields that are declared lossy/unsupported but never observed to drift. So a field this corpus preserves on every cell must be `good` — hedging it to `lossy` fails the build exactly as under-declaring a real loss does. Every row below was measured first.

## Structural finding

Across the 15 cells, 144 source interface records produce 144 re-parsed records — the interface inventory is intact.

## Disposition summary

| Disposition | Fields |
|---|---|
| `good` | 21 |
| `lossy` | 12 |
| `unsupported` | 13 |
| `not_applicable` | 0 |

## Per-field measurement

`preserved` / `drifted` / `both-empty` are cell counts. A field with `drifted` 0 and `preserved` > 0 is `good` by rule. Some fields with `drifted` > 0 are **also** `good`, and that is not a loss being hidden: where a list parent drifted wholesale, the reconciler attributes that single structural event to one owner sub-field and collapses its siblings to `STRUCTURAL_ONLY`, so those siblings evidence no *independent* loss on this pair. Each such field's YAML note says so explicitly, and the parent-level drift stays recorded against the owner key.

| Field | Disposition | preserved | drifted | both-empty |
|---|---|---|---|---|
| `anycast_gateway_mac` | unsupported | 0 | 0 | 15 |
| `apply_groups` | good | 0 | 0 | 15 |
| `dhcp_servers` | unsupported | 0 | 1 | 14 |
| `dns_servers` | unsupported | 0 | 1 | 14 |
| `domain` | unsupported | 0 | 3 | 12 |
| `evpn_type5_routes` | unsupported | 0 | 0 | 15 |
| `group_content` | good | 0 | 0 | 15 |
| `hostname` | good | 14 | 0 | 1 |
| `interfaces[].description` | good | 8 | 0 | 7 |
| `interfaces[].enabled` | good | 11 | 0 | 4 |
| `interfaces[].interface_type` | lossy | 2 | 9 | 4 |
| `interfaces[].ipv4_addresses` | good | 9 | 0 | 6 |
| `interfaces[].ipv6_addresses` | good | 3 | 0 | 12 |
| `interfaces[].lag_member_of` | lossy | 0 | 3 | 12 |
| `interfaces[].mtu` | good | 4 | 0 | 11 |
| `interfaces[].name` | lossy | 7 | 4 | 4 |
| `interfaces[].vrrp_groups` | good | 1 | 0 | 14 |
| `lags` | lossy | 0 | 3 | 12 |
| `local_users` | lossy | 1 | 6 | 8 |
| `local_users[].hashed_password` | lossy | 1 | 6 | 8 |
| `local_users[].name` | good | 1 | 6 | 8 |
| `local_users[].role` | good | 1 | 6 | 8 |
| `ntp_servers` | unsupported | 0 | 1 | 14 |
| `radius_servers` | unsupported | 0 | 1 | 14 |
| `raw_sections` | good | 0 | 0 | 15 |
| `routing_instances` | lossy | 1 | 2 | 12 |
| `routing_instances[].description` | lossy | 0 | 1 | 14 |
| `routing_instances[].name` | good | 3 | 0 | 12 |
| `snmp.community` | good | 2 | 0 | 13 |
| `snmp.contact` | good | 2 | 0 | 13 |
| `snmp.location` | good | 2 | 0 | 13 |
| `snmp.trap_hosts` | good | 2 | 0 | 13 |
| `snmp.v3_users` | lossy | 1 | 1 | 13 |
| `static_routes` | lossy | 5 | 2 | 8 |
| `syslog_servers` | unsupported | 0 | 3 | 12 |
| `timezone` | unsupported | 0 | 0 | 15 |
| `vlans[].description` | lossy | 0 | 1 | 14 |
| `vlans[].id` | good | 3 | 1 | 11 |
| `vlans[].ipv4_addresses` | good | 2 | 1 | 12 |
| `vlans[].name` | lossy | 0 | 3 | 12 |
| `vlans[].tagged_ports` | good | 1 | 1 | 13 |
| `vlans[].untagged_ports` | good | 3 | 1 | 11 |
| `vxlan_vnis` | unsupported | 0 | 1 | 14 |
| `vxlan_vnis[].mcast_group` | unsupported | 0 | 1 | 14 |
| `vxlan_vnis[].vlan_id` | unsupported | 0 | 1 | 14 |
| `vxlan_vnis[].vni` | unsupported | 0 | 1 | 14 |

## Observed loss mechanisms

### `anycast_gateway_mac` — unsupported

Drifted on 0 of 15 cells (preserved on 0, both sides empty on 15).

> OS10 expresses first-hop redundancy as real VRRP, not a chassis-wide anycast-gateway MAC; nothing renders it.

### `dhcp_servers` — unsupported

Drifted on 1 of 15 cells (preserved on 0, both sides empty on 14).

> Phase 1 parses no DHCP server pool.

Sample: `all 2 dhcp_servers dropped`

### `dns_servers` — unsupported

Drifted on 1 of 15 cells (preserved on 0, both sides empty on 14).

> Phase 1 parses no `ip name-server`.

Sample: `all 3 dns_servers dropped`

### `domain` — unsupported

Drifted on 3 of 15 cells (preserved on 0, both sides empty on 12).

> Phase 1 parses no `ip domain-name`.

Sample: `domain: 'test.lab' → ''`

### `evpn_type5_routes` — unsupported

Drifted on 0 of 15 cells (preserved on 0, both sides empty on 15).

> No EVPN is rendered; BGP / EVPN is Tier-3 on OS10.

### `interfaces[].interface_type` — lossy

Drifted on 9 of 15 cells (preserved on 2, both sides empty on 4).

> OS10 interface-type is inferred from the name prefix (ethernet -> ethernetCsmacd, vlan -> l3ipvlan, port-channel -> ieee8023adLag, loopback -> softwareLoopback, mgmt -> ethernetCsmacd).  Inference is best-effort and will not recover every IANA type a cross-vendor source carried.

### `interfaces[].lag_member_of` — lossy

Drifted on 3 of 15 cells (preserved on 0, both sides empty on 12).

### `interfaces[].name` — lossy

Drifted on 4 of 15 cells (preserved on 7, both sides empty on 4).

### `lags` — lossy

Drifted on 3 of 15 cells (preserved on 0, both sides empty on 12).

Sample: `{"lags[0] {'name': 'Port-channel1'}": {'name': {'source': 'Port-channel1', 'target': 'port-channel1'}}}`

### `local_users` — lossy

Drifted on 6 of 15 cells (preserved on 1, both sides empty on 8).

### `local_users[].hashed_password` — lossy

Drifted on 6 of 15 cells (preserved on 1, both sides empty on 8).

### `ntp_servers` — unsupported

Drifted on 1 of 15 cells (preserved on 0, both sides empty on 14).

> Phase 1 parses no `ntp server`.

Sample: `all 2 ntp_servers dropped`

### `radius_servers` — unsupported

Drifted on 1 of 15 cells (preserved on 0, both sides empty on 14).

> Phase 1 parses no AAA radius-server config.

Sample: `all 2 radius_servers dropped`

### `routing_instances` — lossy

Drifted on 2 of 15 cells (preserved on 1, both sides empty on 12).

Sample: `{"routing_instances[0] {'name': 'cml_demo'}": {'l3_vni': {'source': 100200, 'target': None}, 'route_distinguisher': {'source': '200:1', 'target': ''}, 'rt_exports': {'source': ['20`

### `routing_instances[].description` — lossy

Drifted on 1 of 15 cells (preserved on 0, both sides empty on 14).

> The OS10 `ip vrf <name>` stanza carries no description line; the VRF renders, its description does not.

### `snmp.v3_users` — lossy

Drifted on 1 of 15 cells (preserved on 1, both sides empty on 13).

### `static_routes` — lossy

Drifted on 2 of 15 cells (preserved on 5, both sides empty on 8).

Sample: `{"static_routes[5] {'destination': '0.0.0.0/0'}": {'description': {'source': 'boppety', 'target': ''}}, "static_routes[6] {'destination': '1.2.3.0/25'}": {'description': {'source':`

### `syslog_servers` — unsupported

Drifted on 3 of 15 cells (preserved on 0, both sides empty on 12).

> Phase 1 parses no `logging server`.

Sample: `all 6 syslog_servers dropped`

### `timezone` — unsupported

Drifted on 0 of 15 cells (preserved on 0, both sides empty on 15).

> Phase 1 parses no `clock timezone` stanza; intent.timezone is dropped.

### `vlans[].description` — lossy

Drifted on 1 of 15 cells (preserved on 0, both sides empty on 14).

> OS10 carries exactly one human label for a VLAN — the SVI's `description` — and the render spends it on CanonicalVlan.name.  A separate canonical VLAN description has no second place to go and is dropped.

### `vlans[].name` — lossy

Drifted on 3 of 15 cells (preserved on 0, both sides empty on 12).

### `vxlan_vnis` — unsupported

Drifted on 1 of 15 cells (preserved on 0, both sides empty on 14).

> OS10 VXLAN uses a `virtual-network <vnid>` indirection between VLAN and VNI rather than NX-OS's direct `vlan N / vn-segment` binding; deferred past v1.

Sample: `all 1 vxlan_vnis dropped`

### `vxlan_vnis[].mcast_group` — unsupported

Drifted on 1 of 15 cells (preserved on 0, both sides empty on 14).

> No VXLAN overlay is rendered.

### `vxlan_vnis[].vlan_id` — unsupported

Drifted on 1 of 15 cells (preserved on 0, both sides empty on 14).

> No VXLAN overlay is rendered (see /vxlan-vnis/vni).

### `vxlan_vnis[].vni` — unsupported

Drifted on 1 of 15 cells (preserved on 0, both sides empty on 14).

> OS10 VXLAN uses a `virtual-network <vnid>` indirection between VLAN and VNI rather than NX-OS's direct `vlan N / vn-segment` binding; deferred past v1.

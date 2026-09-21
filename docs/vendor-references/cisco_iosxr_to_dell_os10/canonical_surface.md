# Cisco IOS-XR → Dell OS10: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/cisco_iosxr__dell_os10.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key dispositions were resolved through the audit's own `actual_disposition()` rather than inferred from the drift shape, so this file and the ratchet agree by construction.

- Fixture cells: **12**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-09-21

> **No device-vendor documentation was consulted for this file.** Everything below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix` declarations and the measured mesh run. Where a disposition rests on a declaration rather than an observed round-trip, the YAML says so explicitly.

## Why the dispositions could not be written in advance

The binding constraint on this pair is not the capability matrices, it is `test_no_new_pair_declares_a_loss_it_never_observes`: a pair absent from `_UNEVIDENCED_BASELINE` is allowed **zero** fields that are declared lossy/unsupported but never observed to drift. So a field this corpus preserves on every cell must be `good` — hedging it to `lossy` fails the build exactly as under-declaring a real loss does. Every row below was measured first.

## Structural finding

Across the 12 cells, 156 source interface records produce 156 re-parsed records — the interface inventory is intact.

## Disposition summary

| Disposition | Fields |
|---|---|
| `good` | 15 |
| `lossy` | 16 |
| `unsupported` | 13 |
| `not_applicable` | 2 |

## Per-field measurement

`preserved` / `drifted` / `both-empty` are cell counts. A field with `drifted` 0 and `preserved` > 0 is `good` by rule. Some fields with `drifted` > 0 are **also** `good`, and that is not a loss being hidden: where a list parent drifted wholesale, the reconciler attributes that single structural event to one owner sub-field and collapses its siblings to `STRUCTURAL_ONLY`, so those siblings evidence no *independent* loss on this pair. Each such field's YAML note says so explicitly, and the parent-level drift stays recorded against the owner key.

| Field | Disposition | preserved | drifted | both-empty |
|---|---|---|---|---|
| `anycast_gateway_mac` | unsupported | 0 | 0 | 12 |
| `apply_groups` | good | 0 | 0 | 12 |
| `dhcp_servers` | unsupported | 0 | 0 | 12 |
| `dns_servers` | unsupported | 0 | 0 | 12 |
| `domain` | unsupported | 0 | 8 | 4 |
| `evpn_type5_routes` | unsupported | 0 | 0 | 12 |
| `group_content` | good | 0 | 0 | 12 |
| `hostname` | good | 12 | 0 | 0 |
| `interfaces[].description` | lossy | 8 | 1 | 3 |
| `interfaces[].enabled` | good | 12 | 0 | 0 |
| `interfaces[].interface_type` | lossy | 0 | 12 | 0 |
| `interfaces[].ipv4_addresses` | good | 12 | 0 | 0 |
| `interfaces[].ipv6_addresses` | good | 3 | 0 | 9 |
| `interfaces[].lag_member_of` | lossy | 0 | 4 | 8 |
| `interfaces[].mtu` | good | 4 | 0 | 8 |
| `interfaces[].name` | good | 12 | 0 | 0 |
| `interfaces[].vrrp_groups` | not_applicable | 0 | 0 | 12 |
| `lags` | lossy | 0 | 4 | 8 |
| `local_users` | lossy | 0 | 9 | 3 |
| `local_users[].hashed_password` | lossy | 0 | 9 | 3 |
| `local_users[].name` | lossy | 0 | 9 | 3 |
| `local_users[].role` | lossy | 0 | 9 | 3 |
| `ntp_servers` | unsupported | 0 | 1 | 11 |
| `radius_servers` | unsupported | 0 | 0 | 12 |
| `raw_sections` | good | 0 | 0 | 12 |
| `routing_instances` | lossy | 0 | 8 | 4 |
| `routing_instances[].description` | lossy | 0 | 1 | 11 |
| `routing_instances[].name` | good | 8 | 0 | 4 |
| `snmp.community` | not_applicable | 0 | 0 | 12 |
| `snmp.contact` | good | 0 | 0 | 12 |
| `snmp.location` | good | 0 | 0 | 12 |
| `snmp.trap_hosts` | good | 0 | 0 | 12 |
| `snmp.v3_users` | good | 0 | 0 | 12 |
| `static_routes` | good | 6 | 0 | 6 |
| `syslog_servers` | unsupported | 0 | 0 | 12 |
| `timezone` | unsupported | 0 | 0 | 12 |
| `vlans[].description` | lossy | 0 | 4 | 8 |
| `vlans[].id` | lossy | 0 | 4 | 8 |
| `vlans[].ipv4_addresses` | lossy | 0 | 4 | 8 |
| `vlans[].name` | lossy | 0 | 4 | 8 |
| `vlans[].tagged_ports` | lossy | 0 | 4 | 8 |
| `vlans[].untagged_ports` | lossy | 0 | 4 | 8 |
| `vxlan_vnis` | unsupported | 0 | 0 | 12 |
| `vxlan_vnis[].mcast_group` | unsupported | 0 | 0 | 12 |
| `vxlan_vnis[].vlan_id` | unsupported | 0 | 0 | 12 |
| `vxlan_vnis[].vni` | unsupported | 0 | 0 | 12 |

## Observed loss mechanisms

### `anycast_gateway_mac` — unsupported

Drifted on 0 of 12 cells (preserved on 0, both sides empty on 12).

> OS10 expresses first-hop redundancy as real VRRP, not a chassis-wide anycast-gateway MAC; nothing renders it.

### `dhcp_servers` — unsupported

Drifted on 0 of 12 cells (preserved on 0, both sides empty on 12).

> Phase 1 parses no DHCP server pool.

### `dns_servers` — unsupported

Drifted on 0 of 12 cells (preserved on 0, both sides empty on 12).

> Phase 1 parses no `ip name-server`.

### `domain` — unsupported

Drifted on 8 of 12 cells (preserved on 0, both sides empty on 4).

> Phase 1 parses no `ip domain-name`.

Sample: `domain: 'test.com' → ''`

### `evpn_type5_routes` — unsupported

Drifted on 0 of 12 cells (preserved on 0, both sides empty on 12).

> No EVPN is rendered; BGP / EVPN is Tier-3 on OS10.

### `interfaces[].description` — lossy

Drifted on 1 of 12 cells (preserved on 8, both sides empty on 3).

### `interfaces[].interface_type` — lossy

Drifted on 12 of 12 cells (preserved on 0, both sides empty on 0).

> OS10 interface-type is inferred from the name prefix (ethernet -> ethernetCsmacd, vlan -> l3ipvlan, port-channel -> ieee8023adLag, loopback -> softwareLoopback, mgmt -> ethernetCsmacd).  Inference is best-effort and will not recover every IANA type a cross-vendor source carried.

### `interfaces[].lag_member_of` — lossy

Drifted on 4 of 12 cells (preserved on 0, both sides empty on 8).

### `lags` — lossy

Drifted on 4 of 12 cells (preserved on 0, both sides empty on 8).

Sample: `all 2 lags dropped`

### `local_users` — lossy

Drifted on 9 of 12 cells (preserved on 0, both sides empty on 3).

### `local_users[].hashed_password` — lossy

Drifted on 9 of 12 cells (preserved on 0, both sides empty on 3).

### `local_users[].name` — lossy

Drifted on 9 of 12 cells (preserved on 0, both sides empty on 3).

### `local_users[].role` — lossy

Drifted on 9 of 12 cells (preserved on 0, both sides empty on 3).

### `ntp_servers` — unsupported

Drifted on 1 of 12 cells (preserved on 0, both sides empty on 11).

> Phase 1 parses no `ntp server`.

Sample: `all 2 ntp_servers dropped`

### `radius_servers` — unsupported

Drifted on 0 of 12 cells (preserved on 0, both sides empty on 12).

> Phase 1 parses no AAA radius-server config.

### `routing_instances` — lossy

Drifted on 8 of 12 cells (preserved on 0, both sides empty on 4).

Sample: `{"routing_instances[0] {'name': 'AZURE'}": {'route_distinguisher': {'source': '10.188.62.3:151', 'target': ''}, 'rt_exports': {'source': ['65100:151'], 'target': []}, 'rt_imports':`

### `routing_instances[].description` — lossy

Drifted on 1 of 12 cells (preserved on 0, both sides empty on 11).

> The OS10 `ip vrf <name>` stanza carries no description line; the VRF renders, its description does not.

### `syslog_servers` — unsupported

Drifted on 0 of 12 cells (preserved on 0, both sides empty on 12).

> Phase 1 parses no `logging server`.

### `timezone` — unsupported

Drifted on 0 of 12 cells (preserved on 0, both sides empty on 12).

> Phase 1 parses no `clock timezone` stanza; intent.timezone is dropped.

### `vlans[].description` — lossy

Drifted on 4 of 12 cells (preserved on 0, both sides empty on 8).

> OS10 carries exactly one human label for a VLAN — the SVI's `description` — and the render spends it on CanonicalVlan.name.  A separate canonical VLAN description has no second place to go and is dropped.

### `vlans[].id` — lossy

Drifted on 4 of 12 cells (preserved on 0, both sides empty on 8).

### `vlans[].ipv4_addresses` — lossy

Drifted on 4 of 12 cells (preserved on 0, both sides empty on 8).

> Renders VLAN SVI / management L3 only from a sibling interface stanza; an L3 address carried on the VLAN record itself (the Junos irb / Aruba SVI-on-VLAN shape, folded onto CanonicalVlan.ipv4_addresses) is dropped on render because this codec does not synthesize an SVI from the VLAN record. Declared lossy so validate_against surfaces the loss instead of reporting severity:ok (blind-audit 3ec11f3 T0-2).

### `vlans[].name` — lossy

Drifted on 4 of 12 cells (preserved on 0, both sides empty on 8).

### `vlans[].tagged_ports` — lossy

Drifted on 4 of 12 cells (preserved on 0, both sides empty on 8).

### `vlans[].untagged_ports` — lossy

Drifted on 4 of 12 cells (preserved on 0, both sides empty on 8).

### `vxlan_vnis` — unsupported

Drifted on 0 of 12 cells (preserved on 0, both sides empty on 12).

> OS10 VXLAN uses a `virtual-network <vnid>` indirection between VLAN and VNI rather than NX-OS's direct `vlan N / vn-segment` binding; deferred past v1.

### `vxlan_vnis[].mcast_group` — unsupported

Drifted on 0 of 12 cells (preserved on 0, both sides empty on 12).

> No VXLAN overlay is rendered.

### `vxlan_vnis[].vlan_id` — unsupported

Drifted on 0 of 12 cells (preserved on 0, both sides empty on 12).

> No VXLAN overlay is rendered (see /vxlan-vnis/vni).

### `vxlan_vnis[].vni` — unsupported

Drifted on 0 of 12 cells (preserved on 0, both sides empty on 12).

> OS10 VXLAN uses a `virtual-network <vnid>` indirection between VLAN and VNI rather than NX-OS's direct `vlan N / vn-segment` binding; deferred past v1.

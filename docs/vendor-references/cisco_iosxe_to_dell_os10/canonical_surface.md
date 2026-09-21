# Cisco IOS-XE (NETCONF) → Dell OS10: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/cisco_iosxe__dell_os10.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key dispositions were resolved through the audit's own `actual_disposition()` rather than inferred from the drift shape, so this file and the ratchet agree by construction.

- Fixture cells: **1**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-09-21

> **No device-vendor documentation was consulted for this file.** Everything below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix` declarations and the measured mesh run. Where a disposition rests on a declaration rather than an observed round-trip, the YAML says so explicitly.

## Why the dispositions could not be written in advance

The binding constraint on this pair is not the capability matrices, it is `test_no_new_pair_declares_a_loss_it_never_observes`: a pair absent from `_UNEVIDENCED_BASELINE` is allowed **zero** fields that are declared lossy/unsupported but never observed to drift. So a field this corpus preserves on every cell must be `good` — hedging it to `lossy` fails the build exactly as under-declaring a real loss does. Every row below was measured first.

## Structural finding

Across the 1 cell, 10 source interface records produce 10 re-parsed records — the interface inventory is intact.

## Disposition summary

| Disposition | Fields |
|---|---|
| `good` | 22 |
| `lossy` | 3 |
| `unsupported` | 13 |
| `not_applicable` | 8 |

## Per-field measurement

`preserved` / `drifted` / `both-empty` are cell counts. A field with `drifted` 0 and `preserved` > 0 is `good` by rule. Some fields with `drifted` > 0 are **also** `good`, and that is not a loss being hidden: where a list parent drifted wholesale, the reconciler attributes that single structural event to one owner sub-field and collapses its siblings to `STRUCTURAL_ONLY`, so those siblings evidence no *independent* loss on this pair. Each such field's YAML note says so explicitly, and the parent-level drift stays recorded against the owner key.

| Field | Disposition | preserved | drifted | both-empty |
|---|---|---|---|---|
| `anycast_gateway_mac` | unsupported | 0 | 0 | 1 |
| `apply_groups` | good | 0 | 0 | 1 |
| `dhcp_servers` | unsupported | 0 | 0 | 1 |
| `dns_servers` | unsupported | 0 | 0 | 1 |
| `domain` | unsupported | 0 | 0 | 1 |
| `evpn_type5_routes` | unsupported | 0 | 0 | 1 |
| `group_content` | good | 0 | 0 | 1 |
| `hostname` | not_applicable | 0 | 0 | 1 |
| `interfaces[].description` | good | 1 | 0 | 0 |
| `interfaces[].enabled` | good | 1 | 0 | 0 |
| `interfaces[].interface_type` | lossy | 0 | 1 | 0 |
| `interfaces[].ipv4_addresses` | good | 1 | 0 | 0 |
| `interfaces[].ipv6_addresses` | good | 1 | 0 | 0 |
| `interfaces[].lag_member_of` | good | 0 | 0 | 1 |
| `interfaces[].mtu` | good | 0 | 0 | 1 |
| `interfaces[].name` | lossy | 0 | 1 | 0 |
| `interfaces[].vrrp_groups` | not_applicable | 0 | 0 | 1 |
| `lags` | lossy | 0 | 1 | 0 |
| `local_users` | good | 0 | 0 | 1 |
| `local_users[].hashed_password` | good | 0 | 0 | 1 |
| `local_users[].name` | good | 0 | 0 | 1 |
| `local_users[].role` | good | 0 | 0 | 1 |
| `ntp_servers` | unsupported | 0 | 0 | 1 |
| `radius_servers` | unsupported | 0 | 0 | 1 |
| `raw_sections` | good | 0 | 0 | 1 |
| `routing_instances` | good | 0 | 0 | 1 |
| `routing_instances[].description` | good | 0 | 0 | 1 |
| `routing_instances[].name` | good | 0 | 0 | 1 |
| `snmp.community` | not_applicable | 0 | 0 | 1 |
| `snmp.contact` | not_applicable | 0 | 0 | 1 |
| `snmp.location` | not_applicable | 0 | 0 | 1 |
| `snmp.trap_hosts` | not_applicable | 0 | 0 | 1 |
| `snmp.v3_users` | not_applicable | 0 | 0 | 1 |
| `static_routes` | not_applicable | 0 | 0 | 1 |
| `syslog_servers` | unsupported | 0 | 0 | 1 |
| `timezone` | unsupported | 0 | 0 | 1 |
| `vlans[].description` | good | 0 | 0 | 1 |
| `vlans[].id` | good | 1 | 0 | 0 |
| `vlans[].ipv4_addresses` | good | 1 | 0 | 0 |
| `vlans[].name` | good | 1 | 0 | 0 |
| `vlans[].tagged_ports` | good | 0 | 0 | 1 |
| `vlans[].untagged_ports` | good | 0 | 0 | 1 |
| `vxlan_vnis` | unsupported | 0 | 0 | 1 |
| `vxlan_vnis[].mcast_group` | unsupported | 0 | 0 | 1 |
| `vxlan_vnis[].vlan_id` | unsupported | 0 | 0 | 1 |
| `vxlan_vnis[].vni` | unsupported | 0 | 0 | 1 |

## Observed loss mechanisms

### `anycast_gateway_mac` — unsupported

Drifted on 0 of 1 cells (preserved on 0, both sides empty on 1).

> OS10 expresses first-hop redundancy as real VRRP, not a chassis-wide anycast-gateway MAC; nothing renders it.

### `dhcp_servers` — unsupported

Drifted on 0 of 1 cells (preserved on 0, both sides empty on 1).

> Phase 1 parses no DHCP server pool.

### `dns_servers` — unsupported

Drifted on 0 of 1 cells (preserved on 0, both sides empty on 1).

> Phase 1 parses no `ip name-server`.

### `domain` — unsupported

Drifted on 0 of 1 cells (preserved on 0, both sides empty on 1).

> Phase 1 parses no `ip domain-name`.

### `evpn_type5_routes` — unsupported

Drifted on 0 of 1 cells (preserved on 0, both sides empty on 1).

> No EVPN is rendered; BGP / EVPN is Tier-3 on OS10.

### `interfaces[].interface_type` — lossy

Drifted on 1 of 1 cells (preserved on 0, both sides empty on 0).

> OS10 interface-type is inferred from the name prefix (ethernet -> ethernetCsmacd, vlan -> l3ipvlan, port-channel -> ieee8023adLag, loopback -> softwareLoopback, mgmt -> ethernetCsmacd).  Inference is best-effort and will not recover every IANA type a cross-vendor source carried.

### `interfaces[].name` — lossy

Drifted on 1 of 1 cells (preserved on 0, both sides empty on 0).

### `lags` — lossy

Drifted on 1 of 1 cells (preserved on 0, both sides empty on 0).

Sample: `1 lags appeared in target (parser bug?)`

### `ntp_servers` — unsupported

Drifted on 0 of 1 cells (preserved on 0, both sides empty on 1).

> Phase 1 parses no `ntp server`.

### `radius_servers` — unsupported

Drifted on 0 of 1 cells (preserved on 0, both sides empty on 1).

> Phase 1 parses no AAA radius-server config.

### `syslog_servers` — unsupported

Drifted on 0 of 1 cells (preserved on 0, both sides empty on 1).

> Phase 1 parses no `logging server`.

### `timezone` — unsupported

Drifted on 0 of 1 cells (preserved on 0, both sides empty on 1).

> Phase 1 parses no `clock timezone` stanza; intent.timezone is dropped.

### `vxlan_vnis` — unsupported

Drifted on 0 of 1 cells (preserved on 0, both sides empty on 1).

> OS10 VXLAN uses a `virtual-network <vnid>` indirection between VLAN and VNI rather than NX-OS's direct `vlan N / vn-segment` binding; deferred past v1.

### `vxlan_vnis[].mcast_group` — unsupported

Drifted on 0 of 1 cells (preserved on 0, both sides empty on 1).

> No VXLAN overlay is rendered.

### `vxlan_vnis[].vlan_id` — unsupported

Drifted on 0 of 1 cells (preserved on 0, both sides empty on 1).

> No VXLAN overlay is rendered (see /vxlan-vnis/vni).

### `vxlan_vnis[].vni` — unsupported

Drifted on 0 of 1 cells (preserved on 0, both sides empty on 1).

> OS10 VXLAN uses a `virtual-network <vnid>` indirection between VLAN and VNI rather than NX-OS's direct `vlan N / vn-segment` binding; deferred past v1.

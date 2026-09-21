# AOS-S → Dell OS10: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/aruba_aoss__dell_os10.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key dispositions were resolved through the audit's own `actual_disposition()` rather than inferred from the drift shape, so this file and the ratchet agree by construction.

- Fixture cells: **7**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-09-21

> **No device-vendor documentation was consulted for this file.** Everything below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix` declarations and the measured mesh run. Where a disposition rests on a declaration rather than an observed round-trip, the YAML says so explicitly.

## Why the dispositions could not be written in advance

The binding constraint on this pair is not the capability matrices, it is `test_no_new_pair_declares_a_loss_it_never_observes`: a pair absent from `_UNEVIDENCED_BASELINE` is allowed **zero** fields that are declared lossy/unsupported but never observed to drift. So a field this corpus preserves on every cell must be `good` — hedging it to `lossy` fails the build exactly as under-declaring a real loss does. Every row below was measured first.

## Structural finding

Across the 7 cells, 85 source interface records produce 96 re-parsed records — the interface inventory is intact.

## Disposition summary

| Disposition | Fields |
|---|---|
| `good` | 18 |
| `lossy` | 15 |
| `unsupported` | 13 |
| `not_applicable` | 0 |

## Per-field measurement

`preserved` / `drifted` / `both-empty` are cell counts. A field with `drifted` 0 and `preserved` > 0 is `good` by rule. Some fields with `drifted` > 0 are **also** `good`, and that is not a loss being hidden: where a list parent drifted wholesale, the reconciler attributes that single structural event to one owner sub-field and collapses its siblings to `STRUCTURAL_ONLY`, so those siblings evidence no *independent* loss on this pair. Each such field's YAML note says so explicitly, and the parent-level drift stays recorded against the owner key.

| Field | Disposition | preserved | drifted | both-empty |
|---|---|---|---|---|
| `anycast_gateway_mac` | unsupported | 0 | 0 | 7 |
| `apply_groups` | good | 0 | 0 | 7 |
| `dhcp_servers` | unsupported | 0 | 0 | 7 |
| `dns_servers` | unsupported | 0 | 3 | 4 |
| `domain` | unsupported | 0 | 0 | 7 |
| `evpn_type5_routes` | unsupported | 0 | 0 | 7 |
| `group_content` | good | 0 | 0 | 7 |
| `hostname` | good | 7 | 0 | 0 |
| `interfaces[].description` | lossy | 1 | 5 | 1 |
| `interfaces[].enabled` | good | 1 | 5 | 1 |
| `interfaces[].interface_type` | good | 1 | 5 | 1 |
| `interfaces[].ipv4_addresses` | good | 1 | 5 | 1 |
| `interfaces[].ipv6_addresses` | lossy | 0 | 5 | 2 |
| `interfaces[].lag_member_of` | lossy | 0 | 5 | 2 |
| `interfaces[].mtu` | lossy | 0 | 5 | 2 |
| `interfaces[].name` | lossy | 0 | 6 | 1 |
| `interfaces[].vrrp_groups` | lossy | 0 | 5 | 2 |
| `lags` | lossy | 0 | 2 | 5 |
| `local_users` | lossy | 0 | 3 | 4 |
| `local_users[].hashed_password` | lossy | 0 | 3 | 4 |
| `local_users[].name` | lossy | 0 | 3 | 4 |
| `local_users[].role` | lossy | 0 | 3 | 4 |
| `ntp_servers` | unsupported | 0 | 1 | 6 |
| `radius_servers` | unsupported | 0 | 1 | 6 |
| `raw_sections` | good | 0 | 0 | 7 |
| `routing_instances` | good | 0 | 0 | 7 |
| `routing_instances[].description` | good | 0 | 0 | 7 |
| `routing_instances[].name` | good | 0 | 0 | 7 |
| `snmp.community` | good | 6 | 0 | 1 |
| `snmp.contact` | good | 6 | 0 | 1 |
| `snmp.location` | good | 6 | 0 | 1 |
| `snmp.trap_hosts` | good | 6 | 0 | 1 |
| `snmp.v3_users` | lossy | 5 | 1 | 1 |
| `static_routes` | good | 5 | 0 | 2 |
| `syslog_servers` | unsupported | 0 | 0 | 7 |
| `timezone` | unsupported | 0 | 0 | 7 |
| `vlans[].description` | lossy | 0 | 1 | 6 |
| `vlans[].id` | good | 6 | 1 | 0 |
| `vlans[].ipv4_addresses` | good | 4 | 1 | 2 |
| `vlans[].name` | good | 6 | 1 | 0 |
| `vlans[].tagged_ports` | lossy | 2 | 4 | 1 |
| `vlans[].untagged_ports` | lossy | 1 | 6 | 0 |
| `vxlan_vnis` | unsupported | 0 | 0 | 7 |
| `vxlan_vnis[].mcast_group` | unsupported | 0 | 0 | 7 |
| `vxlan_vnis[].vlan_id` | unsupported | 0 | 0 | 7 |
| `vxlan_vnis[].vni` | unsupported | 0 | 0 | 7 |

## Observed loss mechanisms

### `anycast_gateway_mac` — unsupported

Drifted on 0 of 7 cells (preserved on 0, both sides empty on 7).

> OS10 expresses first-hop redundancy as real VRRP, not a chassis-wide anycast-gateway MAC; nothing renders it.

### `dhcp_servers` — unsupported

Drifted on 0 of 7 cells (preserved on 0, both sides empty on 7).

> Phase 1 parses no DHCP server pool.

### `dns_servers` — unsupported

Drifted on 3 of 7 cells (preserved on 0, both sides empty on 4).

> Phase 1 parses no `ip name-server`.

Sample: `all 1 dns_servers dropped`

### `domain` — unsupported

Drifted on 0 of 7 cells (preserved on 0, both sides empty on 7).

> Phase 1 parses no `ip domain-name`.

### `evpn_type5_routes` — unsupported

Drifted on 0 of 7 cells (preserved on 0, both sides empty on 7).

> No EVPN is rendered; BGP / EVPN is Tier-3 on OS10.

### `interfaces[].description` — lossy

Drifted on 5 of 7 cells (preserved on 1, both sides empty on 1).

### `interfaces[].ipv6_addresses` — lossy

Drifted on 5 of 7 cells (preserved on 0, both sides empty on 2).

### `interfaces[].lag_member_of` — lossy

Drifted on 5 of 7 cells (preserved on 0, both sides empty on 2).

### `interfaces[].mtu` — lossy

Drifted on 5 of 7 cells (preserved on 0, both sides empty on 2).

### `interfaces[].name` — lossy

Drifted on 6 of 7 cells (preserved on 0, both sides empty on 1).

### `interfaces[].vrrp_groups` — lossy

Drifted on 5 of 7 cells (preserved on 0, both sides empty on 2).

### `lags` — lossy

Drifted on 2 of 7 cells (preserved on 0, both sides empty on 5).

Sample: `all 1 lags dropped`

### `local_users` — lossy

Drifted on 3 of 7 cells (preserved on 0, both sides empty on 4).

### `local_users[].hashed_password` — lossy

Drifted on 3 of 7 cells (preserved on 0, both sides empty on 4).

### `local_users[].name` — lossy

Drifted on 3 of 7 cells (preserved on 0, both sides empty on 4).

### `local_users[].role` — lossy

Drifted on 3 of 7 cells (preserved on 0, both sides empty on 4).

### `ntp_servers` — unsupported

Drifted on 1 of 7 cells (preserved on 0, both sides empty on 6).

> Phase 1 parses no `ntp server`.

Sample: `all 2 ntp_servers dropped`

### `radius_servers` — unsupported

Drifted on 1 of 7 cells (preserved on 0, both sides empty on 6).

> Phase 1 parses no AAA radius-server config.

Sample: `all 2 radius_servers dropped`

### `snmp.v3_users` — lossy

Drifted on 1 of 7 cells (preserved on 5, both sides empty on 1).

### `syslog_servers` — unsupported

Drifted on 0 of 7 cells (preserved on 0, both sides empty on 7).

> Phase 1 parses no `logging server`.

### `timezone` — unsupported

Drifted on 0 of 7 cells (preserved on 0, both sides empty on 7).

> Phase 1 parses no `clock timezone` stanza; intent.timezone is dropped.

### `vlans[].description` — lossy

Drifted on 1 of 7 cells (preserved on 0, both sides empty on 6).

> OS10 carries exactly one human label for a VLAN — the SVI's `description` — and the render spends it on CanonicalVlan.name.  A separate canonical VLAN description has no second place to go and is dropped.

### `vlans[].tagged_ports` — lossy

Drifted on 4 of 7 cells (preserved on 2, both sides empty on 1).

### `vlans[].untagged_ports` — lossy

Drifted on 6 of 7 cells (preserved on 1, both sides empty on 0).

### `vxlan_vnis` — unsupported

Drifted on 0 of 7 cells (preserved on 0, both sides empty on 7).

> OS10 VXLAN uses a `virtual-network <vnid>` indirection between VLAN and VNI rather than NX-OS's direct `vlan N / vn-segment` binding; deferred past v1.

### `vxlan_vnis[].mcast_group` — unsupported

Drifted on 0 of 7 cells (preserved on 0, both sides empty on 7).

> No VXLAN overlay is rendered.

### `vxlan_vnis[].vlan_id` — unsupported

Drifted on 0 of 7 cells (preserved on 0, both sides empty on 7).

> No VXLAN overlay is rendered (see /vxlan-vnis/vni).

### `vxlan_vnis[].vni` — unsupported

Drifted on 0 of 7 cells (preserved on 0, both sides empty on 7).

> OS10 VXLAN uses a `virtual-network <vnid>` indirection between VLAN and VNI rather than NX-OS's direct `vlan N / vn-segment` binding; deferred past v1.

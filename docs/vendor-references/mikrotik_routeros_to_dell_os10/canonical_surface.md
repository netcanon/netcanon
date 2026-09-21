# RouterOS → Dell OS10: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/mikrotik_routeros__dell_os10.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key dispositions were resolved through the audit's own `actual_disposition()` rather than inferred from the drift shape, so this file and the ratchet agree by construction.

- Fixture cells: **5**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-09-21

> **No device-vendor documentation was consulted for this file.** Everything below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix` declarations and the measured mesh run. Where a disposition rests on a declaration rather than an observed round-trip, the YAML says so explicitly.

## Why the dispositions could not be written in advance

The binding constraint on this pair is not the capability matrices, it is `test_no_new_pair_declares_a_loss_it_never_observes`: a pair absent from `_UNEVIDENCED_BASELINE` is allowed **zero** fields that are declared lossy/unsupported but never observed to drift. So a field this corpus preserves on every cell must be `good` — hedging it to `lossy` fails the build exactly as under-declaring a real loss does. Every row below was measured first.

## Structural finding

Across the 5 cells, 46 source interface records produce 52 re-parsed records — the interface inventory is intact.

## Disposition summary

| Disposition | Fields |
|---|---|
| `good` | 20 |
| `lossy` | 11 |
| `unsupported` | 13 |
| `not_applicable` | 2 |

## Per-field measurement

`preserved` / `drifted` / `both-empty` are cell counts. A field with `drifted` 0 and `preserved` > 0 is `good` by rule. Some fields with `drifted` > 0 are **also** `good`, and that is not a loss being hidden: where a list parent drifted wholesale, the reconciler attributes that single structural event to one owner sub-field and collapses its siblings to `STRUCTURAL_ONLY`, so those siblings evidence no *independent* loss on this pair. Each such field's YAML note says so explicitly, and the parent-level drift stays recorded against the owner key.

| Field | Disposition | preserved | drifted | both-empty |
|---|---|---|---|---|
| `anycast_gateway_mac` | unsupported | 0 | 0 | 5 |
| `apply_groups` | good | 0 | 0 | 5 |
| `dhcp_servers` | unsupported | 0 | 3 | 2 |
| `dns_servers` | unsupported | 0 | 1 | 4 |
| `domain` | unsupported | 0 | 0 | 5 |
| `evpn_type5_routes` | unsupported | 0 | 0 | 5 |
| `group_content` | good | 0 | 0 | 5 |
| `hostname` | lossy | 2 | 1 | 2 |
| `interfaces[].description` | lossy | 2 | 2 | 1 |
| `interfaces[].enabled` | good | 3 | 2 | 0 |
| `interfaces[].interface_type` | lossy | 0 | 5 | 0 |
| `interfaces[].ipv4_addresses` | good | 3 | 2 | 0 |
| `interfaces[].ipv6_addresses` | good | 1 | 2 | 2 |
| `interfaces[].lag_member_of` | lossy | 0 | 3 | 2 |
| `interfaces[].mtu` | good | 1 | 2 | 2 |
| `interfaces[].name` | good | 3 | 2 | 0 |
| `interfaces[].vrrp_groups` | lossy | 0 | 2 | 3 |
| `lags` | lossy | 0 | 1 | 4 |
| `local_users` | good | 1 | 0 | 4 |
| `local_users[].hashed_password` | good | 0 | 0 | 5 |
| `local_users[].name` | good | 1 | 0 | 4 |
| `local_users[].role` | good | 1 | 0 | 4 |
| `ntp_servers` | unsupported | 0 | 3 | 2 |
| `radius_servers` | unsupported | 0 | 1 | 4 |
| `raw_sections` | good | 0 | 0 | 5 |
| `routing_instances` | good | 0 | 0 | 5 |
| `routing_instances[].description` | good | 0 | 0 | 5 |
| `routing_instances[].name` | good | 0 | 0 | 5 |
| `snmp.community` | good | 3 | 0 | 2 |
| `snmp.contact` | good | 3 | 0 | 2 |
| `snmp.location` | good | 3 | 0 | 2 |
| `snmp.trap_hosts` | good | 3 | 0 | 2 |
| `snmp.v3_users` | lossy | 0 | 3 | 2 |
| `static_routes` | lossy | 0 | 1 | 4 |
| `syslog_servers` | unsupported | 0 | 0 | 5 |
| `timezone` | unsupported | 0 | 0 | 5 |
| `vlans[].description` | lossy | 0 | 2 | 3 |
| `vlans[].id` | good | 3 | 0 | 2 |
| `vlans[].ipv4_addresses` | lossy | 0 | 1 | 4 |
| `vlans[].name` | lossy | 2 | 1 | 2 |
| `vlans[].tagged_ports` | not_applicable | 0 | 0 | 5 |
| `vlans[].untagged_ports` | not_applicable | 0 | 0 | 5 |
| `vxlan_vnis` | unsupported | 0 | 0 | 5 |
| `vxlan_vnis[].mcast_group` | unsupported | 0 | 0 | 5 |
| `vxlan_vnis[].vlan_id` | unsupported | 0 | 0 | 5 |
| `vxlan_vnis[].vni` | unsupported | 0 | 0 | 5 |

## Observed loss mechanisms

### `anycast_gateway_mac` — unsupported

Drifted on 0 of 5 cells (preserved on 0, both sides empty on 5).

> OS10 expresses first-hop redundancy as real VRRP, not a chassis-wide anycast-gateway MAC; nothing renders it.

### `dhcp_servers` — unsupported

Drifted on 3 of 5 cells (preserved on 0, both sides empty on 2).

> Phase 1 parses no DHCP server pool.

Sample: `all 2 dhcp_servers dropped`

### `dns_servers` — unsupported

Drifted on 1 of 5 cells (preserved on 0, both sides empty on 4).

> Phase 1 parses no `ip name-server`.

Sample: `all 2 dns_servers dropped`

### `domain` — unsupported

Drifted on 0 of 5 cells (preserved on 0, both sides empty on 5).

> Phase 1 parses no `ip domain-name`.

### `evpn_type5_routes` — unsupported

Drifted on 0 of 5 cells (preserved on 0, both sides empty on 5).

> No EVPN is rendered; BGP / EVPN is Tier-3 on OS10.

### `hostname` — lossy

Drifted on 1 of 5 cells (preserved on 2, both sides empty on 2).

Sample: `hostname: 'Quinta Router' → 'Quinta'`

### `interfaces[].description` — lossy

Drifted on 2 of 5 cells (preserved on 2, both sides empty on 1).

### `interfaces[].interface_type` — lossy

Drifted on 5 of 5 cells (preserved on 0, both sides empty on 0).

> OS10 interface-type is inferred from the name prefix (ethernet -> ethernetCsmacd, vlan -> l3ipvlan, port-channel -> ieee8023adLag, loopback -> softwareLoopback, mgmt -> ethernetCsmacd).  Inference is best-effort and will not recover every IANA type a cross-vendor source carried.

### `interfaces[].lag_member_of` — lossy

Drifted on 3 of 5 cells (preserved on 0, both sides empty on 2).

### `interfaces[].vrrp_groups` — lossy

Drifted on 2 of 5 cells (preserved on 0, both sides empty on 3).

### `lags` — lossy

Drifted on 1 of 5 cells (preserved on 0, both sides empty on 4).

Sample: `all 2 lags dropped`

### `ntp_servers` — unsupported

Drifted on 3 of 5 cells (preserved on 0, both sides empty on 2).

> Phase 1 parses no `ntp server`.

Sample: `all 1 ntp_servers dropped`

### `radius_servers` — unsupported

Drifted on 1 of 5 cells (preserved on 0, both sides empty on 4).

> Phase 1 parses no AAA radius-server config.

Sample: `all 2 radius_servers dropped`

### `snmp.v3_users` — lossy

Drifted on 3 of 5 cells (preserved on 0, both sides empty on 2).

### `static_routes` — lossy

Drifted on 1 of 5 cells (preserved on 0, both sides empty on 4).

Sample: `{"static_routes[0] {'destination': '0.0.0.0/0'}": {'description': {'source': 'Default route to ISP', 'target': ''}}, "static_routes[1] {'destination': '10.50.0.0/16'}": {'descripti`

### `syslog_servers` — unsupported

Drifted on 0 of 5 cells (preserved on 0, both sides empty on 5).

> Phase 1 parses no `logging server`.

### `timezone` — unsupported

Drifted on 0 of 5 cells (preserved on 0, both sides empty on 5).

> Phase 1 parses no `clock timezone` stanza; intent.timezone is dropped.

### `vlans[].description` — lossy

Drifted on 2 of 5 cells (preserved on 0, both sides empty on 3).

> OS10 carries exactly one human label for a VLAN — the SVI's `description` — and the render spends it on CanonicalVlan.name.  A separate canonical VLAN description has no second place to go and is dropped.

### `vlans[].ipv4_addresses` — lossy

Drifted on 1 of 5 cells (preserved on 0, both sides empty on 4).

> Renders VLAN SVI / management L3 only from a sibling interface stanza; an L3 address carried on the VLAN record itself (the Junos irb / Aruba SVI-on-VLAN shape, folded onto CanonicalVlan.ipv4_addresses) is dropped on render because this codec does not synthesize an SVI from the VLAN record. Declared lossy so validate_against surfaces the loss instead of reporting severity:ok (blind-audit 3ec11f3 T0-2).

### `vlans[].name` — lossy

Drifted on 1 of 5 cells (preserved on 2, both sides empty on 2).

> MikroTik stores a VLAN's name as the L3 interface name (e.g. vlan10), NOT a separate descriptive name field.  Cross-vendor rendering may conflate the two.

### `vxlan_vnis` — unsupported

Drifted on 0 of 5 cells (preserved on 0, both sides empty on 5).

> OS10 VXLAN uses a `virtual-network <vnid>` indirection between VLAN and VNI rather than NX-OS's direct `vlan N / vn-segment` binding; deferred past v1.

### `vxlan_vnis[].mcast_group` — unsupported

Drifted on 0 of 5 cells (preserved on 0, both sides empty on 5).

> No VXLAN overlay is rendered.

### `vxlan_vnis[].vlan_id` — unsupported

Drifted on 0 of 5 cells (preserved on 0, both sides empty on 5).

> No VXLAN overlay is rendered (see /vxlan-vnis/vni).

### `vxlan_vnis[].vni` — unsupported

Drifted on 0 of 5 cells (preserved on 0, both sides empty on 5).

> OS10 VXLAN uses a `virtual-network <vnid>` indirection between VLAN and VNI rather than NX-OS's direct `vlan N / vn-segment` binding; deferred past v1.

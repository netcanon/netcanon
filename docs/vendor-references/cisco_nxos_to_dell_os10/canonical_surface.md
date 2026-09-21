# Cisco NX-OS → Dell OS10: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/cisco_nxos__dell_os10.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key dispositions were resolved through the audit's own `actual_disposition()` rather than inferred from the drift shape, so this file and the ratchet agree by construction.

- Fixture cells: **13**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-09-21

> **No device-vendor documentation was consulted for this file.** Everything below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix` declarations and the measured mesh run. Where a disposition rests on a declaration rather than an observed round-trip, the YAML says so explicitly.

## Why the dispositions could not be written in advance

The binding constraint on this pair is not the capability matrices, it is `test_no_new_pair_declares_a_loss_it_never_observes`: a pair absent from `_UNEVIDENCED_BASELINE` is allowed **zero** fields that are declared lossy/unsupported but never observed to drift. So a field this corpus preserves on every cell must be `good` — hedging it to `lossy` fails the build exactly as under-declaring a real loss does. Every row below was measured first.

## Structural finding

Across the 13 cells, 1102 source interface records produce 1149 re-parsed records — the interface inventory is intact.

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
| `anycast_gateway_mac` | unsupported | 0 | 7 | 6 |
| `apply_groups` | good | 0 | 0 | 13 |
| `dhcp_servers` | unsupported | 0 | 0 | 13 |
| `dns_servers` | unsupported | 0 | 0 | 13 |
| `domain` | unsupported | 0 | 2 | 11 |
| `evpn_type5_routes` | unsupported | 0 | 0 | 13 |
| `group_content` | good | 0 | 0 | 13 |
| `hostname` | good | 13 | 0 | 0 |
| `interfaces[].description` | lossy | 2 | 7 | 4 |
| `interfaces[].enabled` | good | 11 | 2 | 0 |
| `interfaces[].interface_type` | lossy | 3 | 10 | 0 |
| `interfaces[].ipv4_addresses` | lossy | 3 | 10 | 0 |
| `interfaces[].ipv6_addresses` | lossy | 1 | 3 | 9 |
| `interfaces[].lag_member_of` | good | 4 | 2 | 7 |
| `interfaces[].mtu` | lossy | 2 | 5 | 6 |
| `interfaces[].name` | lossy | 3 | 10 | 0 |
| `interfaces[].vrrp_groups` | lossy | 0 | 5 | 8 |
| `lags` | good | 5 | 0 | 8 |
| `local_users` | lossy | 0 | 9 | 4 |
| `local_users[].hashed_password` | lossy | 0 | 9 | 4 |
| `local_users[].name` | good | 9 | 0 | 4 |
| `local_users[].role` | good | 9 | 0 | 4 |
| `ntp_servers` | unsupported | 0 | 1 | 12 |
| `radius_servers` | unsupported | 0 | 0 | 13 |
| `raw_sections` | good | 0 | 0 | 13 |
| `routing_instances` | lossy | 6 | 6 | 1 |
| `routing_instances[].description` | lossy | 0 | 1 | 12 |
| `routing_instances[].name` | good | 12 | 0 | 1 |
| `snmp.community` | good | 11 | 0 | 2 |
| `snmp.contact` | good | 11 | 0 | 2 |
| `snmp.location` | good | 11 | 0 | 2 |
| `snmp.trap_hosts` | good | 11 | 0 | 2 |
| `snmp.v3_users` | lossy | 1 | 10 | 2 |
| `static_routes` | good | 8 | 0 | 5 |
| `syslog_servers` | unsupported | 0 | 1 | 12 |
| `timezone` | unsupported | 0 | 0 | 13 |
| `vlans[].description` | lossy | 0 | 3 | 10 |
| `vlans[].id` | good | 10 | 3 | 0 |
| `vlans[].ipv4_addresses` | lossy | 2 | 7 | 4 |
| `vlans[].name` | lossy | 1 | 9 | 3 |
| `vlans[].tagged_ports` | good | 4 | 3 | 6 |
| `vlans[].untagged_ports` | good | 7 | 3 | 3 |
| `vxlan_vnis` | unsupported | 0 | 8 | 5 |
| `vxlan_vnis[].mcast_group` | unsupported | 0 | 8 | 5 |
| `vxlan_vnis[].vlan_id` | unsupported | 0 | 8 | 5 |
| `vxlan_vnis[].vni` | unsupported | 0 | 8 | 5 |

## Observed loss mechanisms

### `anycast_gateway_mac` — unsupported

Drifted on 7 of 13 cells (preserved on 0, both sides empty on 6).

> OS10 expresses first-hop redundancy as real VRRP, not a chassis-wide anycast-gateway MAC; nothing renders it.

Sample: `anycast_gateway_mac: '00:00:00:5e:12:34' → ''`

### `dhcp_servers` — unsupported

Drifted on 0 of 13 cells (preserved on 0, both sides empty on 13).

> Phase 1 parses no DHCP server pool.

### `dns_servers` — unsupported

Drifted on 0 of 13 cells (preserved on 0, both sides empty on 13).

> Phase 1 parses no `ip name-server`.

### `domain` — unsupported

Drifted on 2 of 13 cells (preserved on 0, both sides empty on 11).

> Phase 1 parses no `ip domain-name`.

Sample: `domain: 'lab.karneliuk.com' → ''`

### `evpn_type5_routes` — unsupported

Drifted on 0 of 13 cells (preserved on 0, both sides empty on 13).

> No EVPN is rendered; BGP / EVPN is Tier-3 on OS10.

### `interfaces[].description` — lossy

Drifted on 7 of 13 cells (preserved on 2, both sides empty on 4).

### `interfaces[].interface_type` — lossy

Drifted on 10 of 13 cells (preserved on 3, both sides empty on 0).

> OS10 interface-type is inferred from the name prefix (ethernet -> ethernetCsmacd, vlan -> l3ipvlan, port-channel -> ieee8023adLag, loopback -> softwareLoopback, mgmt -> ethernetCsmacd).  Inference is best-effort and will not recover every IANA type a cross-vendor source carried.

### `interfaces[].ipv4_addresses` — lossy

Drifted on 10 of 13 cells (preserved on 3, both sides empty on 0).

### `interfaces[].ipv6_addresses` — lossy

Drifted on 3 of 13 cells (preserved on 1, both sides empty on 9).

### `interfaces[].mtu` — lossy

Drifted on 5 of 13 cells (preserved on 2, both sides empty on 6).

### `interfaces[].name` — lossy

Drifted on 10 of 13 cells (preserved on 3, both sides empty on 0).

### `interfaces[].vrrp_groups` — lossy

Drifted on 5 of 13 cells (preserved on 0, both sides empty on 8).

> NX-OS expresses FHRP as HSRP (`interface VlanN / hsrp N / ip <vip> / priority / preempt`).  The codec renders EVERY CanonicalVRRPGroup as an `hsrp` block regardless of the source `mode` discriminator, so a cross-vendor VRRP / CARP group normalises to HSRP on NX-OS — the operator's redundancy intent for the virtual IP survives, but the wire protocol changes.  Same-vendor HSRP round-trips losslessly.  Sub-second timers, virtual-MAC, and track objects are not modelled in v1.

### `local_users` — lossy

Drifted on 9 of 13 cells (preserved on 0, both sides empty on 4).

### `local_users[].hashed_password` — lossy

Drifted on 9 of 13 cells (preserved on 0, both sides empty on 4).

### `ntp_servers` — unsupported

Drifted on 1 of 13 cells (preserved on 0, both sides empty on 12).

> Phase 1 parses no `ntp server`.

Sample: `all 2 ntp_servers dropped`

### `radius_servers` — unsupported

Drifted on 0 of 13 cells (preserved on 0, both sides empty on 13).

> Phase 1 parses no AAA radius-server config.

### `routing_instances` — lossy

Drifted on 6 of 13 cells (preserved on 6, both sides empty on 1).

Sample: `{"routing_instances[0] {'name': 'VRF_SERVICE_CUST_1'}": {'l3_vni': {'source': 901001, 'target': None}, 'route_distinguisher': {'source': 'auto', 'target': ''}, 'rt_exports': {'sour`

### `routing_instances[].description` — lossy

Drifted on 1 of 13 cells (preserved on 0, both sides empty on 12).

> The OS10 `ip vrf <name>` stanza carries no description line; the VRF renders, its description does not.

### `snmp.v3_users` — lossy

Drifted on 10 of 13 cells (preserved on 1, both sides empty on 2).

### `syslog_servers` — unsupported

Drifted on 1 of 13 cells (preserved on 0, both sides empty on 12).

> Phase 1 parses no `logging server`.

Sample: `all 1 syslog_servers dropped`

### `timezone` — unsupported

Drifted on 0 of 13 cells (preserved on 0, both sides empty on 13).

> Phase 1 parses no `clock timezone` stanza; intent.timezone is dropped.

### `vlans[].description` — lossy

Drifted on 3 of 13 cells (preserved on 0, both sides empty on 10).

> OS10 carries exactly one human label for a VLAN — the SVI's `description` — and the render spends it on CanonicalVlan.name.  A separate canonical VLAN description has no second place to go and is dropped.

### `vlans[].ipv4_addresses` — lossy

Drifted on 7 of 13 cells (preserved on 2, both sides empty on 4).

> Renders VLAN SVI / management L3 only from a sibling interface stanza; an L3 address carried on the VLAN record itself (the Junos irb / Aruba SVI-on-VLAN shape, folded onto CanonicalVlan.ipv4_addresses) is dropped on render because this codec does not synthesize an SVI from the VLAN record. Declared lossy so validate_against surfaces the loss instead of reporting severity:ok (blind-audit 3ec11f3 T0-2).

### `vlans[].name` — lossy

Drifted on 9 of 13 cells (preserved on 1, both sides empty on 3).

### `vxlan_vnis` — unsupported

Drifted on 8 of 13 cells (preserved on 0, both sides empty on 5).

> OS10 VXLAN uses a `virtual-network <vnid>` indirection between VLAN and VNI rather than NX-OS's direct `vlan N / vn-segment` binding; deferred past v1.

Sample: `all 5 vxlan_vnis dropped`

### `vxlan_vnis[].mcast_group` — unsupported

Drifted on 8 of 13 cells (preserved on 0, both sides empty on 5).

> No VXLAN overlay is rendered.

### `vxlan_vnis[].vlan_id` — unsupported

Drifted on 8 of 13 cells (preserved on 0, both sides empty on 5).

> No VXLAN overlay is rendered (see /vxlan-vnis/vni).

### `vxlan_vnis[].vni` — unsupported

Drifted on 8 of 13 cells (preserved on 0, both sides empty on 5).

> OS10 VXLAN uses a `virtual-network <vnid>` indirection between VLAN and VNI rather than NX-OS's direct `vlan N / vn-segment` binding; deferred past v1.

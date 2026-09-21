# Dell OS10 → Junos: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/dell_os10__juniper_junos.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key dispositions were resolved through the audit's own `actual_disposition()` rather than inferred from the drift shape, so this file and the ratchet agree by construction.

- Fixture cells: **1**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-09-21

> **No device-vendor documentation was consulted for this file.** Everything below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix` declarations and the measured mesh run. Where a disposition rests on a declaration rather than an observed round-trip, the YAML says so explicitly.

## Why the dispositions could not be written in advance

The binding constraint on this pair is not the capability matrices, it is `test_no_new_pair_declares_a_loss_it_never_observes`: a pair absent from `_UNEVIDENCED_BASELINE` is allowed **zero** fields that are declared lossy/unsupported but never observed to drift. So a field this corpus preserves on every cell must be `good` — hedging it to `lossy` fails the build exactly as under-declaring a real loss does. Every row below was measured first.

⚠️ **Thin source corpus.** `dell_os10` has no committed real-capture corpus — its OS10 captures carry live password hashes and are held out-of-tree — so this direction measures the synthetic kitchen-sink fixture only. Fields that fixture does not populate are recorded as trivially empty rather than claimed either way.

## Structural finding

Across the 1 cell, 14 source interface records produce 14 re-parsed records — the interface inventory is intact.

## Disposition summary

| Disposition | Fields |
|---|---|
| `good` | 26 |
| `lossy` | 7 |
| `unsupported` | 3 |
| `not_applicable` | 10 |

## Per-field measurement

`preserved` / `drifted` / `both-empty` are cell counts. A field with `drifted` 0 and `preserved` > 0 is `good` by rule. Some fields with `drifted` > 0 are **also** `good`, and that is not a loss being hidden: where a list parent drifted wholesale, the reconciler attributes that single structural event to one owner sub-field and collapses its siblings to `STRUCTURAL_ONLY`, so those siblings evidence no *independent* loss on this pair. Each such field's YAML note says so explicitly, and the parent-level drift stays recorded against the owner key.

| Field | Disposition | preserved | drifted | both-empty |
|---|---|---|---|---|
| `anycast_gateway_mac` | unsupported | 0 | 0 | 1 |
| `apply_groups` | good | 0 | 0 | 1 |
| `dhcp_servers` | not_applicable | 0 | 0 | 1 |
| `dns_servers` | not_applicable | 0 | 0 | 1 |
| `domain` | not_applicable | 0 | 0 | 1 |
| `evpn_type5_routes` | not_applicable | 0 | 0 | 1 |
| `group_content` | good | 0 | 0 | 1 |
| `hostname` | good | 1 | 0 | 0 |
| `interfaces[].description` | good | 1 | 0 | 0 |
| `interfaces[].enabled` | good | 1 | 0 | 0 |
| `interfaces[].interface_type` | lossy | 0 | 1 | 0 |
| `interfaces[].ipv4_addresses` | good | 1 | 0 | 0 |
| `interfaces[].ipv6_addresses` | good | 1 | 0 | 0 |
| `interfaces[].lag_member_of` | lossy | 0 | 1 | 0 |
| `interfaces[].mtu` | good | 1 | 0 | 0 |
| `interfaces[].name` | good | 1 | 0 | 0 |
| `interfaces[].vrrp_groups` | good | 1 | 0 | 0 |
| `lags` | lossy | 0 | 1 | 0 |
| `local_users` | lossy | 0 | 1 | 0 |
| `local_users[].hashed_password` | lossy | 0 | 1 | 0 |
| `local_users[].name` | good | 1 | 0 | 0 |
| `local_users[].role` | good | 1 | 0 | 0 |
| `ntp_servers` | not_applicable | 0 | 0 | 1 |
| `radius_servers` | unsupported | 0 | 0 | 1 |
| `raw_sections` | good | 0 | 0 | 1 |
| `routing_instances` | good | 1 | 0 | 0 |
| `routing_instances[].description` | good | 0 | 0 | 1 |
| `routing_instances[].name` | good | 1 | 0 | 0 |
| `snmp.community` | good | 1 | 0 | 0 |
| `snmp.contact` | good | 1 | 0 | 0 |
| `snmp.location` | good | 1 | 0 | 0 |
| `snmp.trap_hosts` | good | 1 | 0 | 0 |
| `snmp.v3_users` | lossy | 0 | 1 | 0 |
| `static_routes` | good | 1 | 0 | 0 |
| `syslog_servers` | not_applicable | 0 | 0 | 1 |
| `timezone` | unsupported | 0 | 0 | 1 |
| `vlans[].description` | good | 0 | 0 | 1 |
| `vlans[].id` | good | 1 | 0 | 0 |
| `vlans[].ipv4_addresses` | good | 1 | 0 | 0 |
| `vlans[].name` | lossy | 0 | 1 | 0 |
| `vlans[].tagged_ports` | good | 1 | 0 | 0 |
| `vlans[].untagged_ports` | good | 1 | 0 | 0 |
| `vxlan_vnis` | not_applicable | 0 | 0 | 1 |
| `vxlan_vnis[].mcast_group` | not_applicable | 0 | 0 | 1 |
| `vxlan_vnis[].vlan_id` | not_applicable | 0 | 0 | 1 |
| `vxlan_vnis[].vni` | not_applicable | 0 | 0 | 1 |

## Observed loss mechanisms

### `anycast_gateway_mac` — unsupported

Drifted on 0 of 1 cells (preserved on 0, both sides empty on 1).

> Junos has no system-wide anycast-gateway MAC: per-IRB-unit overrides live on CanonicalIPv4Address.virtual_gateway_mac (the ``set interfaces irb unit <vid> virtual-gateway-v4-mac`` / ``-v6-mac`` grammar) and round-trip through the supported per-address surface instead.  The top-level CanonicalIntent.anycast_gateway_mac field is silently dropped on render — cross-vendor migration from a source carrying the system-wide MAC (Arista ``ip virtual-router mac-address``, NX-OS ``fabric forwarding anycast-gateway-mac``) must distribute the value across every IRB unit's per-address MAC on the receiving Junos side.

### `interfaces[].interface_type` — lossy

Drifted on 1 of 1 cells (preserved on 0, both sides empty on 0).

> OS10 interface-type is inferred from the name prefix (ethernet -> ethernetCsmacd, vlan -> l3ipvlan, port-channel -> ieee8023adLag, loopback -> softwareLoopback, mgmt -> ethernetCsmacd).  Inference is best-effort and will not recover every IANA type a cross-vendor source carried.

### `interfaces[].lag_member_of` — lossy

Drifted on 1 of 1 cells (preserved on 0, both sides empty on 0).

### `lags` — lossy

Drifted on 1 of 1 cells (preserved on 0, both sides empty on 0).

Sample: `{"lags[0] {'name': 'port-channel100'}": {'name': {'source': 'port-channel100', 'target': 'ae100'}}, "lags[1] {'name': 'port-channel200'}": {'name': {'source': 'port-channel200', 't`

### `local_users` — lossy

Drifted on 1 of 1 cells (preserved on 0, both sides empty on 0).

### `local_users[].hashed_password` — lossy

Drifted on 1 of 1 cells (preserved on 0, both sides empty on 0).

### `radius_servers` — unsupported

Drifted on 0 of 1 cells (preserved on 0, both sides empty on 1).

> Render emits no AAA radius-server config; RADIUS host is dropped on migration.

### `snmp.v3_users` — lossy

Drifted on 1 of 1 cells (preserved on 0, both sides empty on 0).

### `timezone` — unsupported

Drifted on 0 of 1 cells (preserved on 0, both sides empty on 1).

> Render emits no clock/timezone stanza; intent.timezone is dropped on migration.

### `vlans[].name` — lossy

Drifted on 1 of 1 cells (preserved on 0, both sides empty on 0).

# FortiGate → Dell OS10: measured canonical surface

<!-- os10-management-plane -->
> **Update 2026-11-12 — OS10 reads and writes its management plane.**  This page was measured when the dell_os10 parser read no `ip domain-name`, `ip name-server`, `ntp server` or `logging server` line and its renderer wrote none.  It now reads each in its bare form and writes it (an NTP or syslog server as a host name or an address, at most three name servers, a value the form does not take left out under a `! review:` line), and the four keys are measured again: `domain` good (preserved on 1, both sides empty on 3 of 4 cells); `dns_servers` good (preserved on 4 of 4 cells); `ntp_servers` good (preserved on 1, both sides empty on 3 of 4 cells); `syslog_servers` unsupported (none of the 4 cells states one).  The sections below for these keys keep the measurement of their date; `tests/fixtures/cross_vendor_expectations/fortigate_cli__dell_os10.yaml` holds the current one.

<!-- a-fortios-route-the-tree-cannot-hold -->
> **Update 2026-11-12 — a FortiOS route printed with no `set dst` is the default route, and a route the tree cannot hold is left out and said.**  The FortiOS parser read a `config router static` entry with no `set dst` (FortiOS prints none for the default, 0.0.0.0/0) as no route, read a blackhole route as a route with no next hop and a route of a VRF other than 0 as a route of the global table, and dropped a route to an address object or an Internet service without a word.  It now reads the first as the default route and leaves each of the others out with a row in `dropped_tier3_sections` (a route of `status disable` with a `disabled:` row); `config router static6` is read by the same rules, and `set gateway 0.0.0.0` is no gateway.  Measured after the change: the drift on two cells went with the blackhole routes; `static_routes` is preserved on 2 cells and empty on 2, and the YAML calls it `good`.  Sentences below that describe a blackhole route reaching this pair, or say that `set vrf` is not parsed, describe the codec before that change; a sentence that says `set comment` is not parsed is older still, for the parser reads a route's comment into its description.  Current dispositions are in `tests/fixtures/cross_vendor_expectations/fortigate_cli__dell_os10.yaml`.

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/fortigate_cli__dell_os10.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key dispositions were resolved through the audit's own `actual_disposition()` rather than inferred from the drift shape, so this file and the ratchet agree by construction.

- Fixture cells: **4**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-09-21

> **No device-vendor documentation was consulted for this file.** Everything below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix` declarations and the measured mesh run. Where a disposition rests on a declaration rather than an observed round-trip, the YAML says so explicitly.

## Why the dispositions could not be written in advance

The binding constraint on this pair is not the capability matrices, it is `test_no_new_pair_declares_a_loss_it_never_observes`: a pair absent from `_UNEVIDENCED_BASELINE` is allowed **zero** fields that are declared lossy/unsupported but never observed to drift. So a field this corpus preserves on every cell must be `good` — hedging it to `lossy` fails the build exactly as under-declaring a real loss does. Every row below was measured first.

## Structural finding

Across the 4 cells, 86 source interface records produce 95 re-parsed records — the interface inventory is intact.

## Disposition summary

| Disposition | Fields |
|---|---|
| `good` | 18 |
| `lossy` | 13 |
| `unsupported` | 13 |
| `not_applicable` | 2 |

## Per-field measurement

`preserved` / `drifted` / `both-empty` are cell counts. A field with `drifted` 0 and `preserved` > 0 is `good` by rule. Some fields with `drifted` > 0 are **also** `good`, and that is not a loss being hidden: where a list parent drifted wholesale, the reconciler attributes that single structural event to one owner sub-field and collapses its siblings to `STRUCTURAL_ONLY`, so those siblings evidence no *independent* loss on this pair. Each such field's YAML note says so explicitly, and the parent-level drift stays recorded against the owner key.

| Field | Disposition | preserved | drifted | both-empty |
|---|---|---|---|---|
| `anycast_gateway_mac` | unsupported | 0 | 0 | 4 |
| `apply_groups` | good | 0 | 0 | 4 |
| `dhcp_servers` | unsupported | 0 | 4 | 0 |
| `dns_servers` | unsupported | 0 | 4 | 0 |
| `domain` | unsupported | 0 | 1 | 3 |
| `evpn_type5_routes` | unsupported | 0 | 0 | 4 |
| `group_content` | good | 0 | 0 | 4 |
| `hostname` | good | 4 | 0 | 0 |
| `interfaces[].description` | lossy | 1 | 3 | 0 |
| `interfaces[].enabled` | good | 1 | 3 | 0 |
| `interfaces[].interface_type` | lossy | 0 | 4 | 0 |
| `interfaces[].ipv4_addresses` | good | 1 | 3 | 0 |
| `interfaces[].ipv6_addresses` | lossy | 0 | 3 | 1 |
| `interfaces[].lag_member_of` | lossy | 0 | 3 | 1 |
| `interfaces[].mtu` | lossy | 0 | 3 | 1 |
| `interfaces[].name` | good | 1 | 3 | 0 |
| `interfaces[].vrrp_groups` | lossy | 0 | 3 | 1 |
| `lags` | lossy | 0 | 4 | 0 |
| `local_users` | lossy | 0 | 4 | 0 |
| `local_users[].hashed_password` | lossy | 0 | 4 | 0 |
| `local_users[].name` | lossy | 0 | 4 | 0 |
| `local_users[].role` | lossy | 0 | 4 | 0 |
| `ntp_servers` | unsupported | 0 | 1 | 3 |
| `radius_servers` | unsupported | 0 | 2 | 2 |
| `raw_sections` | good | 0 | 0 | 4 |
| `routing_instances` | good | 0 | 0 | 4 |
| `routing_instances[].description` | good | 0 | 0 | 4 |
| `routing_instances[].name` | good | 0 | 0 | 4 |
| `snmp.community` | good | 2 | 0 | 2 |
| `snmp.contact` | good | 2 | 0 | 2 |
| `snmp.location` | good | 2 | 0 | 2 |
| `snmp.trap_hosts` | good | 2 | 0 | 2 |
| `snmp.v3_users` | lossy | 1 | 1 | 2 |
| `static_routes` | lossy | 1 | 2 | 1 |
| `syslog_servers` | unsupported | 0 | 0 | 4 |
| `timezone` | unsupported | 0 | 0 | 4 |
| `vlans[].description` | good | 0 | 0 | 4 |
| `vlans[].id` | good | 3 | 0 | 1 |
| `vlans[].ipv4_addresses` | good | 0 | 0 | 4 |
| `vlans[].name` | good | 3 | 0 | 1 |
| `vlans[].tagged_ports` | not_applicable | 0 | 0 | 4 |
| `vlans[].untagged_ports` | not_applicable | 0 | 0 | 4 |
| `vxlan_vnis` | unsupported | 0 | 0 | 4 |
| `vxlan_vnis[].mcast_group` | unsupported | 0 | 0 | 4 |
| `vxlan_vnis[].vlan_id` | unsupported | 0 | 0 | 4 |
| `vxlan_vnis[].vni` | unsupported | 0 | 0 | 4 |

## Observed loss mechanisms

### `anycast_gateway_mac` — unsupported

Drifted on 0 of 4 cells (preserved on 0, both sides empty on 4).

> OS10 expresses first-hop redundancy as real VRRP, not a chassis-wide anycast-gateway MAC; nothing renders it.

### `dhcp_servers` — unsupported

Drifted on 4 of 4 cells (preserved on 0, both sides empty on 0).

> Phase 1 parses no DHCP server pool.

Sample: `all 1 dhcp_servers dropped`

### `dns_servers` — unsupported

Drifted on 4 of 4 cells (preserved on 0, both sides empty on 0).

> Phase 1 parses no `ip name-server`.

Sample: `all 2 dns_servers dropped`

### `domain` — unsupported

Drifted on 1 of 4 cells (preserved on 0, both sides empty on 3).

> Phase 1 parses no `ip domain-name`.

Sample: `domain: 'example.test' → ''`

### `evpn_type5_routes` — unsupported

Drifted on 0 of 4 cells (preserved on 0, both sides empty on 4).

> No EVPN is rendered; BGP / EVPN is Tier-3 on OS10.

### `interfaces[].description` — lossy

Drifted on 3 of 4 cells (preserved on 1, both sides empty on 0).

> FortiOS limits alias to 25 characters; longer descriptions from other vendors will be truncated.

### `interfaces[].interface_type` — lossy

Drifted on 4 of 4 cells (preserved on 0, both sides empty on 0).

> OS10 interface-type is inferred from the name prefix (ethernet -> ethernetCsmacd, vlan -> l3ipvlan, port-channel -> ieee8023adLag, loopback -> softwareLoopback, mgmt -> ethernetCsmacd).  Inference is best-effort and will not recover every IANA type a cross-vendor source carried.

### `interfaces[].ipv6_addresses` — lossy

Drifted on 3 of 4 cells (preserved on 0, both sides empty on 1).

### `interfaces[].lag_member_of` — lossy

Drifted on 3 of 4 cells (preserved on 0, both sides empty on 1).

### `interfaces[].mtu` — lossy

Drifted on 3 of 4 cells (preserved on 0, both sides empty on 1).

### `interfaces[].vrrp_groups` — lossy

Drifted on 3 of 4 cells (preserved on 0, both sides empty on 1).

### `lags` — lossy

Drifted on 4 of 4 cells (preserved on 0, both sides empty on 0).

Sample: `all 2 lags dropped`

### `local_users` — lossy

Drifted on 4 of 4 cells (preserved on 0, both sides empty on 0).

### `local_users[].hashed_password` — lossy

Drifted on 4 of 4 cells (preserved on 0, both sides empty on 0).

### `local_users[].name` — lossy

Drifted on 4 of 4 cells (preserved on 0, both sides empty on 0).

### `local_users[].role` — lossy

Drifted on 4 of 4 cells (preserved on 0, both sides empty on 0).

### `ntp_servers` — unsupported

Drifted on 1 of 4 cells (preserved on 0, both sides empty on 3).

> Phase 1 parses no `ntp server`.

Sample: `all 2 ntp_servers dropped`

### `radius_servers` — unsupported

Drifted on 2 of 4 cells (preserved on 0, both sides empty on 2).

> Phase 1 parses no AAA radius-server config.

Sample: `all 1 radius_servers dropped`

### `snmp.v3_users` — lossy

Drifted on 1 of 4 cells (preserved on 1, both sides empty on 2).

### `static_routes` — lossy

Drifted on 2 of 4 cells (preserved on 1, both sides empty on 1).

Sample: `{"static_routes[0] {'destination': '10.100.0.0/16'}": {'interface': {'source': '', 'target': '254'}, 'metric': {'source': 254, 'target': 0}}}`

### `syslog_servers` — unsupported

Drifted on 0 of 4 cells (preserved on 0, both sides empty on 4).

> Phase 1 parses no `logging server`.

### `timezone` — unsupported

Drifted on 0 of 4 cells (preserved on 0, both sides empty on 4).

> Phase 1 parses no `clock timezone` stanza; intent.timezone is dropped.

### `vxlan_vnis` — unsupported

Drifted on 0 of 4 cells (preserved on 0, both sides empty on 4).

> OS10 VXLAN uses a `virtual-network <vnid>` indirection between VLAN and VNI rather than NX-OS's direct `vlan N / vn-segment` binding; deferred past v1.

### `vxlan_vnis[].mcast_group` — unsupported

Drifted on 0 of 4 cells (preserved on 0, both sides empty on 4).

> No VXLAN overlay is rendered.

### `vxlan_vnis[].vlan_id` — unsupported

Drifted on 0 of 4 cells (preserved on 0, both sides empty on 4).

> No VXLAN overlay is rendered (see /vxlan-vnis/vni).

### `vxlan_vnis[].vni` — unsupported

Drifted on 0 of 4 cells (preserved on 0, both sides empty on 4).

> OS10 VXLAN uses a `virtual-network <vnid>` indirection between VLAN and VNI rather than NX-OS's direct `vlan N / vn-segment` binding; deferred past v1.

# Dell OS10 → Cisco IOS-XE (NETCONF): measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/dell_os10__cisco_iosxe.yaml`.

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
| `good` | 9 |
| `lossy` | 14 |
| `unsupported` | 21 |
| `not_applicable` | 2 |

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
| `hostname` | unsupported | 0 | 1 | 0 |
| `interfaces[].description` | good | 1 | 0 | 0 |
| `interfaces[].enabled` | good | 1 | 0 | 0 |
| `interfaces[].interface_type` | good | 1 | 0 | 0 |
| `interfaces[].ipv4_addresses` | good | 1 | 0 | 0 |
| `interfaces[].ipv6_addresses` | good | 1 | 0 | 0 |
| `interfaces[].lag_member_of` | lossy | 0 | 1 | 0 |
| `interfaces[].mtu` | lossy | 0 | 1 | 0 |
| `interfaces[].name` | good | 1 | 0 | 0 |
| `interfaces[].vrrp_groups` | unsupported | 0 | 1 | 0 |
| `lags` | lossy | 0 | 1 | 0 |
| `local_users` | lossy | 0 | 1 | 0 |
| `local_users[].hashed_password` | lossy | 0 | 1 | 0 |
| `local_users[].name` | lossy | 0 | 1 | 0 |
| `local_users[].role` | lossy | 0 | 1 | 0 |
| `ntp_servers` | unsupported | 0 | 0 | 1 |
| `radius_servers` | unsupported | 0 | 0 | 1 |
| `raw_sections` | good | 0 | 0 | 1 |
| `routing_instances` | lossy | 0 | 1 | 0 |
| `routing_instances[].description` | lossy | 0 | 1 | 0 |
| `routing_instances[].name` | lossy | 0 | 1 | 0 |
| `snmp.community` | unsupported | 0 | 1 | 0 |
| `snmp.contact` | unsupported | 0 | 1 | 0 |
| `snmp.location` | unsupported | 0 | 1 | 0 |
| `snmp.trap_hosts` | unsupported | 0 | 1 | 0 |
| `snmp.v3_users` | unsupported | 0 | 1 | 0 |
| `static_routes` | unsupported | 0 | 1 | 0 |
| `syslog_servers` | unsupported | 0 | 0 | 1 |
| `timezone` | unsupported | 0 | 0 | 1 |
| `vlans[].description` | lossy | 0 | 1 | 0 |
| `vlans[].id` | unsupported | 0 | 1 | 0 |
| `vlans[].ipv4_addresses` | lossy | 0 | 1 | 0 |
| `vlans[].name` | unsupported | 0 | 1 | 0 |
| `vlans[].tagged_ports` | lossy | 0 | 1 | 0 |
| `vlans[].untagged_ports` | lossy | 0 | 1 | 0 |
| `vxlan_vnis` | unsupported | 0 | 0 | 1 |
| `vxlan_vnis[].mcast_group` | not_applicable | 0 | 0 | 1 |
| `vxlan_vnis[].vlan_id` | not_applicable | 0 | 0 | 1 |
| `vxlan_vnis[].vni` | unsupported | 0 | 0 | 1 |

## Observed loss mechanisms

### `anycast_gateway_mac` — unsupported

Drifted on 0 of 1 cells (preserved on 0, both sides empty on 1).

> System-wide anycast-gateway MAC parses-and-ignores in v1.  Schema exists on CanonicalIntent; wire-up scheduled for v0.2.0 Wave C.

### `dhcp_servers` — unsupported

Drifted on 0 of 1 cells (preserved on 0, both sides empty on 1).

> Phase 0.5 stub render emits only interfaces; intent.dhcp_servers dropped on render.

### `dns_servers` — unsupported

Drifted on 0 of 1 cells (preserved on 0, both sides empty on 1).

> Phase 0.5 stub render emits no `<system><dns>` element.  intent.dns_servers dropped on render.

### `domain` — unsupported

Drifted on 0 of 1 cells (preserved on 0, both sides empty on 1).

> Phase 0.5 stub render emits only interfaces; intent.domain dropped on render.

### `evpn_type5_routes` — unsupported

Drifted on 0 of 1 cells (preserved on 0, both sides empty on 1).

> EVPN Type-5 advertisement requires VXLAN render wire-up plus VRF render wire-up — both deferred in this Phase 0.5 stub.

### `hostname` — unsupported

Drifted on 1 of 1 cells (preserved on 0, both sides empty on 0).

> Phase 0.5 stub render emits only the openconfig-interfaces subtree.  intent.hostname is dropped on render — no `<system>` element in the output XML.  Flips to `supported` once _render_canonical() walks intent.hostname into an openconfig-system `<system><config><hostname>` child.

Sample: `hostname: 'dellos10-kitchensink' → ''`

### `interfaces[].lag_member_of` — lossy

Drifted on 1 of 1 cells (preserved on 0, both sides empty on 0).

### `interfaces[].mtu` — lossy

Drifted on 1 of 1 cells (preserved on 0, both sides empty on 0).

> IOS-XE OC model tracks MTU but some platform-specific MTU tweaks (IP vs link) are only representable in CLI; YANG-only round-trip loses the distinction.

### `interfaces[].vrrp_groups` — unsupported

Drifted on 1 of 1 cells (preserved on 0, both sides empty on 0).

> VRRP / HSRP / CARP redundancy groups parse-and-ignore in v1.  CanonicalVRRPGroup schema exists; wire-up scheduled for v0.2.0 Wave B (see docs/v0.2.0-planning/01-vrrp-canonical/).

### `lags` — lossy

Drifted on 1 of 1 cells (preserved on 0, both sides empty on 0).

Sample: `all 2 lags dropped`

### `local_users` — lossy

Drifted on 1 of 1 cells (preserved on 0, both sides empty on 0).

### `local_users[].hashed_password` — lossy

Drifted on 1 of 1 cells (preserved on 0, both sides empty on 0).

### `local_users[].name` — lossy

Drifted on 1 of 1 cells (preserved on 0, both sides empty on 0).

### `local_users[].role` — lossy

Drifted on 1 of 1 cells (preserved on 0, both sides empty on 0).

### `ntp_servers` — unsupported

Drifted on 0 of 1 cells (preserved on 0, both sides empty on 1).

> Phase 0.5 stub render emits no `<system><ntp>` element.  intent.ntp_servers dropped on render.

### `radius_servers` — unsupported

Drifted on 0 of 1 cells (preserved on 0, both sides empty on 1).

> Phase 0.5 stub render emits only interfaces; RADIUS host dropped on render.

### `routing_instances` — lossy

Drifted on 1 of 1 cells (preserved on 0, both sides empty on 0).

Sample: `all 2 routing_instances dropped`

### `routing_instances[].description` — lossy

Drifted on 1 of 1 cells (preserved on 0, both sides empty on 0).

> The OS10 `ip vrf <name>` stanza carries no description line; the VRF renders, its description does not.

### `routing_instances[].name` — lossy

Drifted on 1 of 1 cells (preserved on 0, both sides empty on 0).

### `snmp.community` — unsupported

Drifted on 1 of 1 cells (preserved on 0, both sides empty on 0).

> Phase 0.5 stub render does not walk intent.snmp.  v1/v2c surface is render-side wire-up gap; the v3 surface is doubly unsupported (see /snmp/v3-user).

### `snmp.contact` — unsupported

Drifted on 1 of 1 cells (preserved on 0, both sides empty on 0).

> Same render-side wire-up gap as /snmp/community.

### `snmp.location` — unsupported

Drifted on 1 of 1 cells (preserved on 0, both sides empty on 0).

> Same render-side wire-up gap as /snmp/community.

### `snmp.trap_hosts` — unsupported

Drifted on 1 of 1 cells (preserved on 0, both sides empty on 0).

> Same render-side wire-up gap as /snmp/community.

### `snmp.v3_users` — unsupported

Drifted on 1 of 1 cells (preserved on 0, both sides empty on 0).

> The NETCONF/OpenConfig codec is a stub (Phase 0.5 experimental) — SNMPv3 USM wire-up requires the Cisco-IOS-XE-snmp native YANG module, not covered today.  The ``cisco_iosxe_cli`` sibling codec parses v3 users from ``show running-config`` output instead.

### `static_routes` — unsupported

Drifted on 1 of 1 cells (preserved on 0, both sides empty on 0).

> Phase 0.5 stub render does not walk intent.static_routes or emit `<network-instances>/<protocols><protocol identifier=STATIC>`.  Render-side wire-up gap.

Sample: `all 3 static_routes dropped`

### `syslog_servers` — unsupported

Drifted on 0 of 1 cells (preserved on 0, both sides empty on 1).

> Phase 0.5 stub render emits only interfaces; intent.syslog_servers dropped on render.

### `timezone` — unsupported

Drifted on 0 of 1 cells (preserved on 0, both sides empty on 1).

> Phase 0.5 stub render emits only interfaces; intent.timezone dropped on render.

### `vlans[].description` — lossy

Drifted on 1 of 1 cells (preserved on 0, both sides empty on 0).

> OS10 carries exactly one human label for a VLAN — the SVI's `description` — and the render spends it on CanonicalVlan.name.  A separate canonical VLAN description has no second place to go and is dropped.

### `vlans[].id` — unsupported

Drifted on 1 of 1 cells (preserved on 0, both sides empty on 0).

> Phase 0.5 stub render does not walk intent.vlans or emit a top-level `<vlans>` subtree.  Synthesised SVI interfaces (intent.interfaces[name='VlanN']) DO survive via the interfaces walk, but the accompanying VLAN declaration does not.

### `vlans[].ipv4_addresses` — lossy

Drifted on 1 of 1 cells (preserved on 0, both sides empty on 0).

### `vlans[].name` — unsupported

Drifted on 1 of 1 cells (preserved on 0, both sides empty on 0).

> Same render-side wire-up gap as /vlans/vlan/id.

### `vlans[].tagged_ports` — lossy

Drifted on 1 of 1 cells (preserved on 0, both sides empty on 0).

### `vlans[].untagged_ports` — lossy

Drifted on 1 of 1 cells (preserved on 0, both sides empty on 0).

### `vxlan_vnis` — unsupported

Drifted on 0 of 1 cells (preserved on 0, both sides empty on 1).

> VXLAN not modelled in this NETCONF/OpenConfig stub codec.  CLI sibling defers VXLAN wire-up until Catalyst demand arrives; NETCONF stays in lockstep.

### `vxlan_vnis[].vni` — unsupported

Drifted on 0 of 1 cells (preserved on 0, both sides empty on 1).

> VXLAN not modelled in this NETCONF/OpenConfig stub codec.  CLI sibling defers VXLAN wire-up until Catalyst demand arrives; NETCONF stays in lockstep.

# NX-OS -> OPNsense: measured canonical surface

Source: `netcanon/migration/codecs/cisco_nxos/codec.py` and
`netcanon/migration/codecs/opnsense/codec.py` (`CapabilityMatrix`), joined
against a full in-process `tools/run_full_mesh.py` run over the committed
corpus.
Retrieved: 2026-08-20

`cisco_nxos` is a DC leaf/spine switch codec (`device_classes = [switch,
router]`); `opnsense` is a FreeBSD router/firewall codec that reads and writes
`config.xml`. Nearly all of the loss measured below is that role mismatch plus
the OPNsense codec's render-side coverage, not a codec defect. 13 fixture
cells; **0 render errors, 0 re-parse errors**.

## Per-field measurement (13 cells)

| field | preserved | drifted | untested | what drifts |
|---|---:|---:|---:|---|
| `hostname` | 13 | 0 | 0 | — |
| `domain` | 2 | 0 | 11 | — |
| `lags` | 5 | 0 | 8 | — |
| `vlans` | 5 | 8 | 0 | `ipv4_addresses`, `untagged_ports`, `tagged_ports` |
| `dns_servers` | 0 | 0 | 13 | — (no fixture populates it) |
| `timezone` | 0 | 0 | 13 | — (both matrices declare it unsupported) |
| `dhcp_servers` | 0 | 0 | 13 | — (NX-OS never populates it) |
| `radius_servers` | 0 | 0 | 13 | — (NX-OS never populates it) |
| `evpn_type5_routes` | 0 | 0 | 13 | — (carried as a VRF property instead) |
| `raw_sections` | 0 | 0 | 13 | — |
| `apply_groups` / `group_content` | 0 | 0 | 13 | — (Junos-only) |
| `ntp_servers` | 0 | 1 | 12 | whole record dropped |
| `syslog_servers` | 0 | 1 | 12 | whole record dropped |
| `anycast_gateway_mac` | 0 | 7 | 6 | whole scalar dropped |
| `static_routes` | 0 | 8 | 5 | whole record dropped |
| `vxlan_vnis` | 0 | 8 | 5 | whole record dropped |
| `local_users` | 0 | 9 | 4 | `hashed_password`, `role` |
| `snmp` | 0 | 11 | 2 | `v3_users` |
| `routing_instances` | 0 | 12 | 1 | whole record dropped |
| `interfaces` | 0 | 13 | 0 | `interface_type`, `switchport_mode`, `vrf`, `access_vlan`, `trunk_allowed_vlans`, `ipv4_addresses`, `vrrp_groups`, `trunk_native_vlan` |

No cell shows a list-count drift on `interfaces`, `vlans` or `local_users`:
every source record survives as a record, so those three fields are addressed
by SUB-FIELD keys only in the expectation YAML and no `STRUCTURAL_ONLY`
collapse occurs on this pair.

## Drifting sub-fields (the authoritative aggregate)

Only the sub-fields listed here drift anywhere in the pair. Every other
sub-field of the same parent is preserved on every cell that exercises it, so
`good` is the measured disposition for those.

| parent | sub-field | drifting record-occurrences |
|---|---|---:|
| `interfaces` | `interface_type` | 1102 |
| `interfaces` | `switchport_mode` | 29 |
| `interfaces` | `vrf` | 28 |
| `interfaces` | `access_vlan` | 13 |
| `interfaces` | `trunk_allowed_vlans` | 10 |
| `interfaces` | `ipv4_addresses` | 9 |
| `interfaces` | `vrrp_groups` | 4 |
| `interfaces` | `trunk_native_vlan` | 4 |
| `vlans` | `ipv4_addresses` | 14 |
| `vlans` | `untagged_ports` | 12 |
| `vlans` | `tagged_ports` | 8 |
| `local_users` | `hashed_password` | 10 |
| `local_users` | `role` | 10 |
| `snmp` | `v3_users` | 11 cells |

Sub-fields with NO data anywhere on the corpus (measured, not assumed):
`interfaces[].dot1q_vlan`, `interfaces[].voice_vlan`,
`interfaces[].tunnel_type`, `interfaces[].dhcp_client_v6`,
`interfaces[].default_name`, `interfaces[].kind`, `vlans[].description`.

## Rendered evidence

The `cisco_nxos` synthetic kitchen-sink rendered to `config.xml` (excerpt,
elided for length):

```xml
<system>
  <hostname>nxos-kitchensink</hostname>
  <user>
    <name>admin</name>
    <!-- password manager user-name "admin" - review: 5 hash from source
         vendor cannot be re-used on OPNsense; reset this user password
         manually -->
    <scope>system</scope>
    <groupname>admins</groupname>
    <priv>page-all</priv>
  </user>
</system>
<interfaces>
  <vlan20><if>Vlan20</if><descr>tenant-a anycast gateway SVI</descr>
    <enable/><ipaddr>10.20.20.1</ipaddr><subnet>24</subnet></vlan20>
  <ethernet1_3><if>Ethernet1/3</if><descr>access port</descr><enable/></ethernet1_3>
</interfaces>
<vlans>
  <vlan><if>port-channel1</if><tag>10</tag><descr>PROD</descr>
    <vlanif>port-channel1_vlan10</vlanif></vlan>
</vlans>
<laggs>
  <lagg><laggif>port-channel1</laggif>
    <members>Ethernet1/5,Ethernet1/6</members><proto>lacp</proto></lagg>
</laggs>
<snmpd>
  <rocommunity>public-ro</rocommunity><syslocation>DataCenter-1-RackB</syslocation>
  <syscontact>netops@example.net</syscontact><traphost>192.0.2.50</traphost>
</snmpd>
```

There is no `<staticroutes>`, no `<gateways>`, no `<virtualip>`, no
`<timeservers>`, no `<syslog>` and no `<timezone>` element anywhere in the
render — which is exactly what the whole-record drops below measure.

## Notes grounding the dispositions

* **The routing table does not survive — the pair's worst loss.** Every one of
  the 8 cells that carries static routes re-parses with zero
  (`"all N static_routes dropped"`; 13 route records in total, 6 of them
  default routes, including an IPv6 default `::/0`). The opnsense matrix
  declares `/routing/static-route` and every leaf beneath it unsupported: the
  codec PARSES `<gateways>` + `<staticroutes>` (promotion #15) but the
  `config.xml` renderer emits neither block, so destination, next hop, metric,
  description and VRF binding all go together. A migrated box has no default
  route at all until the operator re-creates it — on OPNsense that means a
  named `<gateway_item>` first, then a route referencing it.
* **`interfaces[].ipv4_addresses` loses secondaries and the anycast
  companion, not the primary.** 9 drifting record-occurrences, of two kinds.
  (1) A distributed-anycast SVI keeps its own address and loses only the
  `virtual_gateway_address` companion — `192.168.10.1` with
  `virtual_gateway_address=192.168.10.1` re-parses as `192.168.10.1` with the
  companion blank (the matrix declares
  `/interfaces/interface/ipv4/address/virtual-gateway-address` unsupported,
  "parses-and-ignores in v1"). (2) A loopback carrying a SECONDARY address
  loses that address entirely: `akarneliuk_evpn_vxlan_mcast_leaf_c1l1_nxos939`
  `loopback0` goes `[10.0.255.30/32, 10.0.254.201/32 (secondary)]` ->
  `[10.0.255.30/32]`, and `busterswt_spine_leaf_xk32_1_nxos9312` `loopback0`
  goes `[192.168.0.5/32, 192.168.0.15/32 (secondary)]` -> `[192.168.0.5/32]`.
  On an NX-OS VTEP that secondary loopback is the shared/anycast VTEP address,
  so this is a fabric-identity loss, not a cosmetic one. The matrix declares
  `/interfaces/interface/ipv4/address/secondary-ip` unsupported ("Render emits
  one IPv4 address per interface ... a whole-subnet reachability loss").
* **`vlans[].ipv4_addresses` is a mount change here, not a data loss.** The
  VLAN-record copy of the SVI address re-parses empty on all 14 populated
  records, because the OPNsense render carries L3 on the interface record
  (`<vlan10><if>Vlan10</if><ipaddr>...`), never back onto the `<vlans>` entry —
  the matrix declares `/vlans/vlan/ipv4/address/ip` lossy for exactly that
  reason. The address itself survives on the sibling `interfaces[]` `Vlan<N>`
  record (measured: `Vlan10` `192.168.10.1` preserved on the akarneliuk cell
  while the VLAN-mounted copy dropped). `interfaces[].ipv4_addresses` is the
  row that matters operationally.
* **VLAN port membership does not survive.** OPNsense binds a VLAN to exactly
  ONE parent (`<vlan><if>port-channel1</if><tag>10</tag>`), so
  `untagged_ports` (12 occurrences) and `tagged_ports` (8) re-parse empty;
  both are declared unsupported on the matrix. Combined with
  `interfaces[].access_vlan` / `trunk_allowed_vlans`, both directions of the
  port-to-VLAN mapping disappear together — capture it off the Nexus first.
* **`vlans[].name` survives; `vlans[].description` is untested.** The name
  lands in the VLAN entry's `<descr>` and re-parses intact on all 5 cells that
  populate it. The matrix declares `/vlans/vlan/description` lossy because
  `<descr>` is a single slot shared with the canonical description — but the
  NX-OS parser folds `vlan / name <X>` into `name` and never populates
  `description`, so the collision is never exercised on this pair.
* **The whole L2 switching surface drops.** `switchport_mode` (29
  occurrences, `trunk` / `access` -> `null`), `access_vlan` (13, e.g. `10` ->
  `null`), `trunk_allowed_vlans` (10, `[10, 2000]` -> `[]`) and
  `trunk_native_vlan` (4, `999` -> `null`) are each declared unsupported on the
  opnsense matrix — a BSD firewall has no switching fabric. An access port
  re-parses as a bare enabled interface with no VLAN binding at all.
* **VRF membership drops on both mounts.** `interfaces[].vrf` drifts on 28
  record-occurrences (`VRF_SERVICE_CUST_1` -> `""`, `management` -> `""`) and
  `routing_instances` loses every record on 12 of 13 cells; the matrix
  declares `/routing-instances/instance` unsupported ("Render emits no
  VRF/routing-instance construct"). Tenant separation collapses into one
  global table, and the out-of-band `management` VRF goes with it.
* **`interfaces[].vrrp_groups` does not survive.** All 4 drifting occurrences
  go to `[]`. The NX-OS corpus only ever produces `mode="hsrp"` groups and the
  opnsense render emits CARP only — the matrix says a non-CARP mode "is
  skipped on render and the whole group drops". No `<virtualip>` block appears
  in the render, so the virtual IP that hosts use as their default gateway
  (`10.10.10.3` on the two HSRP fixtures, `100.64.90.1` on busterswt) is
  absent from the migrated config.
* **`local_users[].hashed_password` never survives.** All 10 populated user
  records re-parse with an empty hash: shape `5 $5$<salt>$<digest>` -> `""`.
  The render emits a review comment in place of the credential ("5 hash from
  source vendor cannot be re-used on OPNsense; reset this user password
  manually"), so every migrated account arrives with no password.
* **`local_users[].role` is remapped onto OPNsense's binary group model.**
  10 occurrences: `network-admin` -> `admin` (9, rendered as
  `<groupname>admins</groupname>` + `<priv>page-all</priv>`) and
  `network-operator` -> `user` (1, `<groupname>users</groupname>`). The
  account survives and lands on the correct side of the admin boundary, but
  any finer NX-OS RBAC role has to be rebuilt as an OPNsense group.
  `privilege_level` (`15`) round-trips unchanged on all 9 cells.
* **SNMP: v1/v2c survives, v3 does not.** On the 2 cells that carry a
  community (`nautobot_gc_nxos_snmp_spine01_nxos933`, `kitchen_sink`),
  `community`, `location`, `contact` and `trap_hosts` all round-trip verbatim
  into `<snmpd>`. `v3_users` drifts on all 11 cells that populate SNMP; the
  matrix declares `/snmp/v3-user` unsupported because OPNsense keeps USM users
  in the bsnmpd / net-snmp plugin's own `snmpd.conf`, not in `config.xml`. On
  the 9 cells whose source SNMP is v3-ONLY, the whole `snmp` record therefore
  re-parses as absent — there is nothing left for `<snmpd>` to carry.
* **Whole-record drops on the services surface.** `ntp_servers` ("all 2
  dropped") and `syslog_servers` ("all 1 dropped") each hit the one cell that
  populates them; the matrix declares `/system/ntp-server` and
  `/system/syslog-server` unsupported ("Render emits no
  `<system><timeservers>`" / "no remote-syslog config"). `timezone` is
  declared unsupported on BOTH matrices and is never populated.
  `dns_servers` is declared supported on both and is never populated — `good`
  there rests on the declarations, not on an observed round-trip.
* **`anycast_gateway_mac` drops on all 7 cells that set it**
  (`00:00:00:5e:12:34` -> `""`); the matrix declares `/anycast-gateway-mac`
  unsupported (parses-and-ignores in v1). With the anycast companion address
  gone too, the distributed-gateway construct does not exist on the target.
* **`vxlan_vnis` drops wholesale** on all 8 populated cells ("all 5
  vxlan_vnis dropped"), matching `/vxlan-vnis/vni` unsupported — "VXLAN not
  modelled — OPNsense is a firewall codec". VNI-to-VLAN bindings, the VTEP
  source interface and the multicast replication groups go together.
* **`lags` round-trips intact.** Preserved on all 5 cells that populate one:
  name, members and LACP mode carry verbatim (`port-channel1`, members
  `Ethernet1/5` / `Ethernet1/6`, mode `active`) via
  `<laggs><lagg><laggif>port-channel1</laggif>`. The opnsense matrix declares
  `/lags/lag/mode` lossy because FreeBSD `lagg` has one `lacp` proto and a
  `passive` bundle re-parses as `active` — every bundle in this corpus is
  already `active`, so the corpus never exercises that collapse.
  `interfaces[].lag_member_of` is preserved on the same 5 cells.
* **`interfaces[].interface_type` drifts everywhere and matters least.** 1102
  record-occurrences, always `ianaift:ethernetCsmacd` -> `""`: OPNsense's
  `<interfaces>` block has no type element, so the IANA ifType is dropped and
  re-inferred from the name on the target. Interface identity, description,
  admin state, MTU and IPv6 addressing are preserved on every cell.

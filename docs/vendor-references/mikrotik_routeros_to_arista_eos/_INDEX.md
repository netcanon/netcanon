# MikroTik RouterOS to Arista EOS — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/mikrotik_routeros__arista_eos.yaml`
per-field expectations.  See sibling
`tests/fixtures/cross_vendor_expectations/README.md` for the
canonical schema definition.

This pair is the **inverse** of `arista_eos_to_mikrotik_routeros/`.
This direction is the SMB/WISP-router-to-DC-class-switch
direction: typical use case is operators consolidating onto an
Arista-standard estate, or moving lab / edge sites onto Arista
hardware to align with an existing DC fabric.

The asymmetry on this direction is different from the forward:
RouterOS source carries lots of Tier-3 plumbing (firewall, NAT,
queues, wireless, scripts, hotspot, IPsec, PPP/L2TP/WireGuard
tunnels) that the canonical model does not capture and that
Arista has no first-class home for.  These surfaces lift to
`raw_sections` on RouterOS parse and silently drop on Arista
render.  This is the largest source of cross-vendor information
loss in this direction.

The other big loss is **password material**: RouterOS does not
surface hashed passwords in `/export`, so the canonical
`hashed_password` arrives empty and the Arista render emits no
`secret` clause.  Operator MUST re-set passwords manually on the
target.

The good news: the basic-services surface (hostname / DNS / NTP /
IPv4-IPv6 addresses / static routes / SNMP v1+v2c / RADIUS) tracks
reasonably well — RouterOS uses MD5/SHA1 + DES/AES (= AES-128) for
v3 USM, all of which are subsets of Arista's broader algorithm
support, so v3 algorithm-set is NOT a bottleneck in this
direction (only the engineID-salted passphrases require re-key).

| Topic | Summary |
|---|---|
| `system_services.md` | Hostname / DNS / NTP / timezone / syslog.  RouterOS modern Olson form (`America/Los_Angeles`) versus Arista historical alias form (`US/Pacific`).  Domain not_applicable (RouterOS source structurally absent). |
| `interfaces.md` | RouterOS flat `etherN` / `sfp-sfpplus<N>` versus Arista `Ethernet<N>` / `Ethernet<unit>/<slot>/<port>`.  Free-form RouterOS comment names lift to Arista description.  Loopback emulation (RouterOS empty-bridge) -> Arista first-class `Loopback<N>`. |
| `vlans.md` | RouterOS two-plane model (`/interface vlan` for L3 + bridge VLAN filtering for L2) versus Arista interface-centric switchport.  Plane-2 wire-up partial in v1; Arista render may under-populate access/trunk membership lists. |
| `static_routes.md` | RouterOS `/ip route add dst-address=X/N gateway=Y` versus Arista `ip route X/N <gw>`.  CIDR preserved both ways.  Per-VRF `routing-table=X` and `blackhole=yes` partially lossy (canonical schema gaps). |
| `dhcp_server.md` | RouterOS three-section form (`/ip pool` + `/ip dhcp-server network` + `/ip dhcp-server`) joins on parse to Arista `ip dhcp pool` block.  Static reservations / option codes lossy. |
| `snmp_aaa.md` | RouterOS `/snmp` + `/snmp community add v3=yes` versus Arista `snmp-server community/host/user`.  RouterOS narrow algorithm set (MD5/SHA1 + DES/AES-128) is a subset of Arista's; algorithm-set is NOT a bottleneck.  Passphrases re-key required. |
| `local_users.md` | RouterOS `/user add group=full` (NO password material in /export) versus Arista `username X privilege Y role Z secret sha512 $6$...`.  Major loss: Arista render emits no secret clause; operator MUST re-set passwords. |
| `lags.md` | RouterOS `/interface bonding mode=802.3ad` versus Arista `interface Port-Channel<N>` + `channel-group N mode active`.  RouterOS-only modes (active-backup, balance-rr, etc.) collapse with banner. |
| `firewall_unsupported.md` | RouterOS-rich Tier-3 plumbing (firewall / NAT / queues / wireless / scripts / hotspot / IPsec / PPP / L2TP / WireGuard) drops to raw_sections.  Arista has no canonical-portable target for these surfaces.  Major asymmetric loss. |
| `vxlan_evpn_unsupported.md` | RouterOS does not carry VXLAN / EVPN / MAC-VRF data into canonical; Arista target has no source data to consume.  Empty surface in this direction. |

Retrieved 2026-05-01.

See also:
- `../README.md` (citation cache layout)
- `../arista_eos_to_mikrotik_routeros/_INDEX.md` (the inverse pair)
- `../mikrotik_routeros_to_aruba_aoss/_INDEX.md` (sibling RouterOS-source enterprise->campus pair)
- `../mikrotik_routeros_to_cisco_iosxe_cli/_INDEX.md` (sibling RouterOS-source enterprise pair)

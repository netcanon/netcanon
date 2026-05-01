# Cisco IOS-XE CLI to MikroTik RouterOS — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/cisco_iosxe_cli__mikrotik_routeros.yaml`
per-field expectations.  See sibling
`tests/fixtures/cross_vendor_expectations/README.md` for the
canonical schema definition.

This is an **enterprise-to-SMB/WISP** pair: Cisco IOS-XE targets
enterprise / carrier markets with stanza-based config; MikroTik
RouterOS targets SMB / WISP / power-user markets with `/export`-
form section-and-set grammar.  The CLI is structurally different
even where the underlying intent overlaps.  Wire-format mismatch
matters more here than syntax similarity — the keyword-stable
surface across Cisco / Arista / Juniper does not extend to
RouterOS.

| Topic | Summary |
|---|---|
| `system_services.md` | Hostname / DNS / NTP / timezone / syslog.  Cisco `clock timezone PST -8 0` (offset+name) versus RouterOS `/system clock set time-zone-name=America/Los_Angeles` (TZ database). |
| `interface_naming.md` | Cisco's speed-encoded prefix (`GigabitEthernet0/0/1`) versus RouterOS's flat `etherN` / `sfp-sfpplus<N>`.  Rename mesh handles. |
| `ip_addressing.md` | Cisco `ip address A.B.C.D MASK` (dotted-mask, on-interface) versus RouterOS `/ip address add address=A.B.C.D/N interface=etherN` (CIDR, decoupled section). |
| `vlans.md` | Cisco interface-centric switchport model versus RouterOS's two-plane model (`/interface vlan` for routed sub-interfaces; bridge VLAN filtering for switching).  Plane mismatch documented. |
| `switching_model.md` | Philosophy difference — Cisco distinguishes L2/L3 ports natively; RouterOS is router-first with optional bridge for switching.  Cisco-to-MikroTik mode mapping table. |
| `static_routes.md` | Cisco `ip route DEST MASK GW` versus RouterOS `/ip route add dst-address=X/N gateway=Y`.  Default-VRF round-trips; per-VRF deferred (canonical schema gap). |
| `dhcp_server.md` | Cisco's bundled `ip dhcp pool` versus RouterOS's three-section split (`/ip pool` + `/ip dhcp-server network` + `/ip dhcp-server`).  Static reservations / option codes lossy. |
| `snmp.md` | `snmp-server community` versus `/snmp community add` (RouterOS overloads section for v1/v2c + v3).  v3 SHA-2 / AES-256 / 3DES not available on RouterOS — downgrade required.  USM passphrases re-key required regardless. |
| `local_users.md` | Cisco `username X privilege Y secret 9 $9$...` versus RouterOS `/user add name=X group=full password=...`.  Hash formats are NOT cross-compatible.  Privilege-number to named-group mapping is operator-curated. |
| `radius_aaa.md` | Cisco `radius server <name> / address ipv4 X` versus RouterOS `/radius add address=X service=login,...`.  Shared-secret pass-through opaque; service-binding versus method-list models diverge. |
| `lags.md` | Cisco `Port-channel<N>` + per-interface `channel-group <N> mode active` versus RouterOS `/interface bonding add slaves=etherN,etherM mode=802.3ad`.  Mode mapping documented. |
| `routing_instances_vrf.md` | Cisco `vrf definition <name>` versus RouterOS `/ip vrf add interfaces=...`.  Both codecs parse-and-ignore VRF declarations in v1; whole surface unsupported pending wire-up. |

Retrieved over 2026-04-30.

See also:
- `../README.md` (citation cache layout)
- `../mikrotik_routeros_to_cisco_iosxe_cli/_INDEX.md` (the inverse pair)
- `../cisco_iosxe_cli_to_arista_eos/_INDEX.md` (sibling Cisco-source pair, high-overlap reference)

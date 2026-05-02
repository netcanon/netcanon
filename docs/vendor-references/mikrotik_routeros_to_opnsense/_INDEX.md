# MikroTik RouterOS to OPNsense — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/mikrotik_routeros__opnsense.yaml`
per-field expectations.  See sibling
`tests/fixtures/cross_vendor_expectations/README.md` for the canonical
schema definition.

This is an **SMB router -> FreeBSD firewall** pair.  MikroTik RouterOS
targets SMB / WISP / power-user markets with a router-first model
(``/export`` section-and-set form).  OPNsense is a FreeBSD-based
firewall (pfSense fork) with an XML-stored config (``config.xml``).
Both target small-network use cases but with different feature focus
— RouterOS leans on routing / wireless / queues, OPNsense leans on
firewall / NAT / VPN.

Asymmetry on this direction concentrates on:

* **RouterOS-rich plumbing drops** — firewall / NAT / mangle / queues
  / wireless / hotspot / scripts / scheduler / OVPN / IPsec / PPP
  are Tier-3 on canonical (RouterOS codec lists them as unsupported)
  and have no auto-rendered destination on OPNsense.  Tier-3 carries
  in `raw_sections` for operator review only.
* **Password-export gap** — RouterOS's ``/export`` does not surface
  hashed passwords, so the OPNsense target render emits user records
  with NO ``<password>`` element.  Operators MUST set passwords
  manually post-migration.  Same gap as RouterOS -> Cisco IOS-XE / Aruba.
* **Switching-state mismatch** — RouterOS Plane-2 (bridge VLAN
  filtering) port lists have no destination on OPNsense (which has
  no per-port allowed-VLAN model); cross-pair drops switching state.
* **VRF parser gap** — RouterOS 7+ ``/ip vrf`` is not yet parsed by
  the MikroTik codec, AND OPNsense has no VRF model in
  ``config.xml``; structurally absent on both sides.

| Topic | Summary |
|---|---|
| `system_services.md` | Hostname (RouterOS bare -> OPNsense `<hostname>`) / DNS (RouterOS comma-list -> OPNsense repeated `<dnsserver>`) / NTP / IANA tz database name (shared shape, OPNsense render wire-up pending) / syslog. |
| `interfaces.md` | RouterOS `etherN` / `default-name` versus OPNsense zone-tag (`<wan>` / `<lan>` / `<optN>`) plus BSD `<if>`.  IP / MTU / enable round-trip cleanly.  VRF structurally absent. |
| `vlans.md` | RouterOS two-plane model (Plane 1 `/interface vlan` + Plane 2 bridge VLAN filtering) versus OPNsense's "VLAN as one tagged sub-interface on one parent NIC" model.  No port-membership concept on OPNsense. |
| `static_routes.md` | RouterOS CIDR `/ip route` versus OPNsense's two-block `<gateways>` + `<staticroutes>` model.  OPNsense codec render wire-up pending. |
| `dhcp.md` | RouterOS three-section DHCP form (`/ip pool` + `/ip dhcp-server` + `/ip dhcp-server network`) versus OPNsense's interface-keyed `<dhcpd>/<lan>` zone form.  Lease-time units shared (seconds). |
| `snmp.md` | RouterOS overloaded `/snmp community` versus OPNsense `<snmpd>`.  v1/v2c surface round-trips; SNMPv3 USM unsupported on OPNsense (lives in plugin's `snmpd.conf`, not `config.xml`). |
| `local_users.md` | RouterOS named groups (full/write/read) versus OPNsense binary admin/users.  Hash format gap dominates — RouterOS `/export` carries no password material, OPNsense expects bcrypt. |
| `lags.md` | RouterOS `bond<N>` (Linux bonding modes: 802.3ad / active-backup / balance-xor / etc.) versus OPNsense FreeBSD `lagg<N>` (lacp / failover / loadbalance / roundrobin).  RouterOS-rich modes collapse. |
| `radius.md` | RouterOS flat `/radius` versus OPNsense `<authserver>` with `<type>radius</type>` discriminator.  Round-trips host / port / secret cleanly. |
| `firewall_natively_unsupported.md` | RouterOS firewall / NAT / mangle / queues / wireless / scripts / IPsec / OVPN are Tier-3 (raw_sections); OPNsense rule shape is unsupported on canonical anyway. |
| `vrf_unsupported.md` | MikroTik codec does not yet parse `/ip vrf`; OPNsense has no VRF schema in `config.xml`.  EVPN / VXLAN unsupported on both codecs. |

Retrieved 2026-04-30.

## See also

- `../README.md` — citation cache layout (top-level index).
- `../opnsense_to_mikrotik_routeros/_INDEX.md` — reverse direction.
- `../mikrotik_routeros_to_aruba_aoss/_INDEX.md` — sibling RouterOS-source pair.
- `../mikrotik_routeros_to_cisco_iosxe_cli/_INDEX.md` — sibling RouterOS-source pair.
- `../aruba_aoss_to_opnsense/_INDEX.md` — sibling OPNsense-target pair.
- `../../../tests/fixtures/cross_vendor_expectations/README.md` — schema spec.

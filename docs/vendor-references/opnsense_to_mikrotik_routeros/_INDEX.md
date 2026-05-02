# OPNsense to MikroTik RouterOS — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/opnsense__mikrotik_routeros.yaml`
per-field expectations.  See sibling
`tests/fixtures/cross_vendor_expectations/README.md` for the
canonical schema definition.

This pair is a **FreeBSD firewall -> SMB router** translation — the
reverse of the `mikrotik_routeros_to_opnsense/` direction.  Both
target small-network use cases but with different feature focus
(OPNsense leans on firewall / NAT / VPN; RouterOS leans on routing /
wireless / queues).

Asymmetry on this direction concentrates on:

* **Switching state never populated** — OPNsense source has no
  switching fabric to model (no `switchport_mode`, `access_vlan`,
  `tagged_ports` lists).  Cross-pair fields are `not_applicable`
  (source-side absence) rather than `unsupported` (target-side
  refusal).  The mirror of the inverse direction.
* **VRF not modelled on either end** — OPNsense has no VRF schema;
  RouterOS codec parser is a known gap.  Both ends absent.
* **OPNsense firewall / NAT / VPN drops** — these fields are
  parse-and-ignored on the OPNsense side per the codec's capability
  matrix, never reaching canonical.  RouterOS target also lists
  firewall / NAT under unsupported (Tier-3).  Both ends drop.
* **Hash-format incompatibility** — OPNsense bcrypt cannot be
  transplanted to RouterOS's vendor-private password format.
  Operators MUST set passwords manually on the RouterOS target.

| Topic | Summary |
|---|---|
| `system_services.md` | Hostname (OPNsense `<hostname>` -> RouterOS `/system identity`) / domain / DNS / NTP / IANA tz database name (shared shape) / syslog.  OPNsense parse wire-up pending for several Tier-1 fields. |
| `interfaces.md` | OPNsense zone-tag (`<wan>` / `<lan>` / `<optN>`) plus BSD `<if>` versus RouterOS `etherN` / `default-name=`.  IP / MTU / enable round-trip cleanly. |
| `vlans.md` | OPNsense's "VLAN as one tagged sub-interface on one parent" model versus RouterOS two-plane (Plane-1 `/interface vlan` + Plane-2 bridge VLAN filtering).  No port-membership data from OPNsense source. |
| `static_routes.md` | OPNsense two-block `<gateways>` + `<staticroutes>` model versus RouterOS CIDR `/ip route`.  OPNsense parse wire-up pending; gateway-name indirection requires resolution. |
| `dhcp.md` | OPNsense interface-keyed `<dhcpd>/<lan>` zone form versus RouterOS three-section DHCP form.  OPNsense parses to canonical; RouterOS renders the three sections. |
| `snmp.md` | OPNsense `<snmpd>` (multiple `<traphost>`) versus RouterOS overloaded `/snmp community` (single trap-target).  v3 USM is not_applicable from OPNsense source (lives in plugin's `snmpd.conf`). |
| `local_users.md` | OPNsense bcrypt versus RouterOS vendor-private password format.  RouterOS does not accept foreign hash material — operator re-key required regardless. |
| `lags.md` | OPNsense FreeBSD `lagg<N>` (lacp / failover / loadbalance / roundrobin) versus RouterOS `bond<N>` (Linux bonding modes).  OPNsense modes are a subset of RouterOS modes. |
| `radius.md` | OPNsense `<authserver>` with `<type>radius</type>` versus RouterOS flat `/radius`.  Round-trips host / port / secret cleanly.  Service-binding drops. |
| `firewall_drops_on_render.md` | OPNsense firewall / NAT / VPN parse-and-ignored on source; RouterOS firewall unsupported on canonical too.  Both ends drop. |
| `switching_not_modeled.md` | OPNsense never populates switching state — `not_applicable` rather than `unsupported`. |
| `vrf_not_modeled.md` | OPNsense has no VRF schema; MikroTik codec parser gap.  Both ends absent.  EVPN / VXLAN unsupported on both. |

Retrieved 2026-04-30.

## See also

- `../README.md` — citation cache layout (top-level index).
- `../mikrotik_routeros_to_opnsense/_INDEX.md` — reverse direction.
- `../opnsense_to_aruba_aoss/_INDEX.md` — sibling OPNsense-source pair.
- `../opnsense_to_cisco_iosxe_cli/_INDEX.md` — sibling OPNsense-source pair.
- `../mikrotik_routeros_to_aruba_aoss/_INDEX.md` — sibling RouterOS-target pair (peer SMB).
- `../../../tests/fixtures/cross_vendor_expectations/README.md` — schema spec.

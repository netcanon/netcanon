# MikroTik RouterOS to Juniper Junos — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/mikrotik_routeros__juniper_junos.yaml`
per-field expectations.  See sibling `README.md` (one level up) for
the canonical schema definition.

This is a **SMB/WISP router to DC-class router** pair.  MikroTik
RouterOS = SMB / WISP router-first OS with rich firewall / NAT /
queue / wireless / hotspot plumbing.  Juniper Junos = full DC-class
router with EVPN-VXLAN, apply-groups inheritance, two-pass parse,
multi-instance routing.  Same router-class chassis but different
feature focus and target market.

The asymmetry shapes the cross-pair (inverse direction):

* RouterOS source carries Tier-3 plumbing (`/ip firewall`,
  `/interface wireguard`, `/ip hotspot`, `/system script`, `/queue`,
  `/interface wireless`) that has no canonical Junos analogue —
  drops to raw_sections.
* Junos-only surface (apply-groups, mac-vrf, VXLAN-EVPN) is
  structurally empty on RouterOS source side (not_applicable).
* Wire formats differ fundamentally — RouterOS `/section` + `add/set`
  flat record list vs Junos `set ...` form with hierarchical
  inheritance and per-unit interface families.
* Keyword-stable surface (`hostname`, DNS, NTP, IP addresses,
  static routes, SNMP, RADIUS) round-trips through the canonical
  model despite the syntactic gap.

| Topic | Summary |
|---|---|
| `system_services.md` | Hostname / DNS / NTP / timezone clean; syslog filter semantics drop; domain attribute scope mismatch (RouterOS DNS-resolver vs Junos identity). |
| `interfaces.md` | RouterOS flat `etherN` -> Junos speed-encoded `ge-0/0/X` via rename mesh; per-interface `comment=` / `mtu=` / `disabled=` clean; bridge-vs-irb structural difference. |
| `vlans.md` | RouterOS two-plane VLAN model (`/interface vlan` Plane 1 + `/interface bridge vlan` Plane 2) -> Junos named VLANs + per-interface `family ethernet-switching`; Plane-2 partial wire-up; `_` -> `-` name sanitisation. |
| `static_routes.md` | RouterOS `/ip route add dst-address=X/N gateway=Y` -> Junos `set routing-options static route X/N next-hop Y`; per-VRF flatten; blackhole / type semantics drop. |
| `snmp_aaa.md` | v1/v2c clean; v3 USM algorithm overlap MD5/SHA1/SHA256 + DES/AES/AES-256; engineID-salted passphrases never cross-portable; multi-target trap-host = single on RouterOS source. |
| `local_users.md` | RouterOS `full`/`write`/`read` -> Junos `super-user`/`operator`/`read-only`; RouterOS NEVER carries password hashes in /export, so cross-vendor user migration always lands without password. |
| `lags.md` | RouterOS `bond<N>` + `slaves=` -> Junos `ae<N>` + per-member `ether-options 802.3ad`; RouterOS-only modes (active-backup, balance-rr, balance-tlb, balance-alb, broadcast) collapse with banner. |
| `dhcp.md` | RouterOS three-stage `/ip pool` + `/ip dhcp-server` + `/ip dhcp-server network` -> Junos two-stage `dhcp-local-server` + `address-assignment pool`; lease-time duration round-trip; static reservations + DHCP options lossy. |
| `vxlan_evpn_unsupported.md` | RouterOS source codec lists `/vxlan-vnis/*` as unsupported; canonical empty after RouterOS parse — Junos render emits no fabric overlay.  Not_applicable on this direction. |
| `routing_instances_vrf.md` | RouterOS `/ip vrf` parsing not wired up in v1; canonical empty after RouterOS parse — Junos render emits no `routing-instances`.  Will upgrade to lossy on RouterOS-side wire-up (RD/RT live under BGP, not /ip vrf). |
| `firewall_unsupported.md` | RouterOS `/ip firewall` + `/ip hotspot` + `/system script` + `/queue` + `/interface wireguard` + `/interface wireless` are Tier-3 unsupported on Junos target; remain in raw_sections. |

Retrieved 2026-05-01.

See also: `../README.md` (citation cache layout).

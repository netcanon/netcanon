# MikroTik RouterOS to Juniper Junos — vendor reference index

<!-- an-account-with-no-password -->
> **Update 2026-11-04 — an account with no password is no longer written.**  Up to this change the Junos render wrote an account whose source holds no password (an empty secret, or a tag with nothing after it) as `set system login user <name> class <class>` with no `authentication` statement.  It now writes one review comment IN PLACE of the account, `# user "<name>" -- review: no password for this account was read from the source, and an account written for Junos without one could log in with none; it is left out: add it on the device with a password, or as an account for remote (RADIUS or TACACS+) login`, and the job carries one warning naming each such account.  A RouterOS `/user` export holds no passwords, so every account from this source is such a line.  Measured on this pair: **3** such accounts across 1 cell (the synthetic kitchen sink).  All 3 used to arrive, and none does now: `local_users` in/out over the 1 cell that populates users goes from **3 / 3** to **3 / 0**.  Any statement below that such an account is written, arrives without a password, or renders `nopassword` describes the render before this change.  Current dispositions are in `tests/fixtures/cross_vendor_expectations/mikrotik_routeros__juniper_junos.yaml`.

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
| `lags.md` | RouterOS `bond<N>` + `slaves=` -> Junos `ae<N>` + per-member `ether-options 802.3ad`; static modes (balance-xor, balance-rr, broadcast) become an `ae<N>` with no `lacp`; active-backup, balance-tlb and balance-alb, whose peer needs no aggregate, the same with a `# review:` line. |
| `dhcp.md` | RouterOS three-stage `/ip pool` + `/ip dhcp-server` + `/ip dhcp-server network` -> Junos two-stage `dhcp-local-server` + `address-assignment pool`; lease-time duration round-trip; static reservations + DHCP options lossy. |
| `vxlan_evpn_unsupported.md` | RouterOS source codec lists `/vxlan-vnis/*` as unsupported; canonical empty after RouterOS parse — Junos render emits no fabric overlay.  Not_applicable on this direction. |
| `routing_instances_vrf.md` | RouterOS `/ip vrf` parsing not wired up in v1; canonical empty after RouterOS parse — Junos render emits no `routing-instances`.  Will upgrade to lossy on RouterOS-side wire-up (RD/RT live under BGP, not /ip vrf). |
| `firewall_unsupported.md` | RouterOS `/ip firewall` + `/ip hotspot` + `/system script` + `/queue` + `/interface wireguard` + `/interface wireless` are Tier-3 unsupported on Junos target; remain in raw_sections. |

Retrieved 2026-05-01.

See also: `../README.md` (citation cache layout).

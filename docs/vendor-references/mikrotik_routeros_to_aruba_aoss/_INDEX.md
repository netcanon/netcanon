# MikroTik RouterOS to Aruba AOS-S — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/mikrotik_routeros__aruba_aoss.yaml`
per-field expectations.  See sibling
`tests/fixtures/cross_vendor_expectations/README.md` for the
canonical schema definition.

This is the **inverse** of the aruba_aoss -> mikrotik_routeros pair
(an SMB/WISP RouterOS device migrated onto an Aruba campus switch,
or a router-first deployment retired in favour of an enterprise
ProCurve estate).  Asymmetry shows up in two places:

* **RouterOS-rich plumbing drops** — firewall / NAT / queues /
  wireless / scripts / IPsec are Tier-3 on canonical and have no
  Aruba equivalent.  This is the dominant lossy path on this
  direction — the canonical model captures far less than the
  RouterOS source carries.
* **Password-export gap** — RouterOS does not surface hashed
  passwords in `/export`, so the Aruba target render emits
  `password manager user-name "..." sha1 ""` and the operator
  MUST set passwords manually post-migration.  Same gap as on the
  RouterOS -> Cisco IOS-XE pair.

| Topic | Summary |
|---|---|
| `system_services.md` | Hostname (RouterOS bare -> Aruba quoted) / DNS (comma-list -> priority-ordered) / NTP-vs-SNTP / tz-database name -> minute-offset timezone. |
| `interface_naming.md` | RouterOS `etherN` / `bond<N>` -> Aruba bare-numeric / `Trk<N>`.  Operator-friendly RouterOS name -> Aruba `name "..."` (description). |
| `ip_addressing.md` | CIDR <-> CIDR; v6 link-local discriminator preserved.  Routed-vs-L2 gating synthesised on Aruba render. |
| `vlans.md` | RouterOS two-plane model (Plane-1 / Plane-2) -> Aruba VLAN-centric.  Plane-2 wire-up partial in v1; `name` conflated with L3 interface name. |
| `switching_model.md` | Philosophy mismatch — RouterOS L3-by-default vs Aruba L2-by-default.  Tier-3 plumbing (firewall / NAT / queues / wireless) is the dominant lossy path. |
| `static_routes.md` | RouterOS CIDR -> Aruba CIDR / dotted-mask.  Per-VRF (`routing-table=`) drops; blackhole flag drops; interface-as-gateway drops. |
| `dhcp.md` | RouterOS three-section DHCP form joins on parse; Aruba target drops the pool entirely (relay-only on AOS-S). |
| `snmp.md` | v1/v2c access-keyword mapping (RouterOS flags -> Aruba Operator/Manager).  v3 USM auth/priv overlap; AES-256 -> AES-128 downgrade with banner. |
| `local_users.md` | RouterOS named groups (full/write/read) -> Aruba two-role.  Password-export gap dominates — Aruba render emits empty SHA-1 hash. |
| `lags.md` | RouterOS `bond<N>` (`802.3ad` / `balance-xor` / etc.) -> Aruba `Trk<N>`.  Non-LACP bonding modes collapse to static `trunk` with banner. |
| `radius_aaa.md` | RouterOS `/radius` <-> Aruba flat `radius-server host`.  Service binding (`service=ppp,wireless,…`) drops on Aruba render. |
| `routing_instances_vrf.md` | RouterOS codec parser gap on `/ip vrf`; Aruba structurally has no VRF concept.  EVPN / VXLAN unsupported on both. |

Retrieved 2026-04-30.

See also:
- `../README.md` (citation cache layout)
- `../aruba_aoss_to_mikrotik_routeros/_INDEX.md` (the inverse pair)
- `../mikrotik_routeros_to_cisco_iosxe_cli/_INDEX.md` (sibling RouterOS-source pair)
- `../aruba_aoss_to_cisco_iosxe_cli/_INDEX.md` (sibling Aruba-target pair)

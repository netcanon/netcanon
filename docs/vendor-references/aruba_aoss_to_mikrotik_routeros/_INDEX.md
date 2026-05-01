# Aruba AOS-S to MikroTik RouterOS — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/aruba_aoss__mikrotik_routeros.yaml`
per-field expectations.  See sibling
`tests/fixtures/cross_vendor_expectations/README.md` for the
canonical schema definition.

This is an **enterprise switch -> SMB/WISP router** pair.  Aruba
AOS-S targets enterprise campus deployments (ProCurve heritage,
2930F / 2930M / 3810 / 5400R class) with a switching-first model;
MikroTik RouterOS targets SMB / WISP / power-user markets with a
router-first model and optional bridge for switching.  The wire
formats differ greatly (Aruba Cisco-style stanza grammar vs
RouterOS `/export` section-and-set form), and the underlying
philosophy differs even more (Aruba L2-by-default vs RouterOS
L3-by-default).

| Topic | Summary |
|---|---|
| `system_services.md` | Hostname (Aruba quoted -> RouterOS bare) / DNS (priority -> comma-list) / SNTP-vs-NTP / minute-offset timezone -> tz-database name. |
| `interface_naming.md` | Aruba bare-numeric / `Trk<N>` -> RouterOS `etherN` / `bond<N>`.  Loopback emulation (Aruba VLAN-SVI vs RouterOS empty-bridge). |
| `ip_addressing.md` | CIDR <-> CIDR; v6 link-local discriminator preserved. |
| `vlans.md` | Aruba VLAN-centric -> RouterOS two-plane model (`/interface vlan` for L3 + bridge-VLAN filtering for L2).  Plane-2 wire-up partial in v1. |
| `switching_model.md` | Philosophy mismatch — Aruba L2-by-default vs RouterOS L3-by-default.  L2 features (DHCP-snooping, ARP-protect, BPDU-guard) drop on cross-pair. |
| `static_routes.md` | Aruba CIDR / dotted-mask -> RouterOS CIDR.  `ip default-gateway` legacy form normalises.  Per-VRF routes deferred (canonical schema gap). |
| `dhcp.md` | Aruba is relay-only / no server pools.  RouterOS three-section DHCP form joins on parse and lossy on Aruba target. |
| `snmp.md` | Aruba `Operator/Manager` access keywords vs RouterOS `read-access=` / `write-access=` flags.  v3 USM auth/priv overlap (MD5/SHA1 + AES/DES); passphrases re-key required. |
| `local_users.md` | Aruba two-role (manager/operator) <-> RouterOS named groups (full/write/read).  Hash format incompatibility — re-key required. |
| `lags.md` | Aruba `Trk<N>` (`lacp` / `trunk` / `fec` / `dt-lacp`) <-> RouterOS `bond<N>` (`802.3ad` / `balance-xor` / etc.).  RouterOS-only modes lossy. |
| `radius_aaa.md` | Aruba flat `radius-server host` <-> RouterOS `/radius add address=`.  Service binding / method-list policy not modelled canonically. |
| `routing_instances_vrf.md` | Both ends do not model VRF in v1.  Aruba structurally has no VRF concept; RouterOS codec parser gap.  EVPN / VXLAN unsupported on both. |

Retrieved 2026-04-30.

See also:
- `../README.md` (citation cache layout)
- `../mikrotik_routeros_to_aruba_aoss/_INDEX.md` (the inverse pair)
- `../aruba_aoss_to_cisco_iosxe_cli/_INDEX.md` (sibling Aruba-source pair)
- `../cisco_iosxe_cli_to_mikrotik_routeros/_INDEX.md` (sibling RouterOS-target pair)

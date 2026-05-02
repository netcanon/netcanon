# FortiGate FortiOS to OPNsense — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/fortigate_cli__opnsense.yaml`
per-field expectations.  See `tests/fixtures/cross_vendor_expectations/
README.md` for the canonical schema definition.

This pair is a firewall-to-firewall translation — the most
role-compatible pair in the cross-mesh matrix.  Both vendors are
session-based stateful firewalls with native models for the same
core concepts: WAN/LAN/zone interfaces, DHCP scopes, IPsec VPN, RADIUS,
local users, SNMP, NAT, firewall policy.  The shared canonical surface
is therefore larger than any switch-to-firewall pair: hostname /
domain / DNS / interfaces / VLANs (as 802.1Q child interfaces — both
vendors share this idiom) / SNMP v1/v2c / local users / RADIUS / LAGs
/ DHCP server pools.

The unfortunate gap on this pair is that despite both ends modelling
firewall / NAT / VPN natively, the canonical-portable form does NOT
carry these features (Tier 3 — policy semantics differ enough between
vendors that auto-translation would be unsafe in v1).  Operators
consolidating between FortiGate and OPNsense must manually reconstruct
firewall policy, NAT, and VPN config after migration.

| Topic | Summary |
|---|---|
| `system_services.md` | Hostname / domain / DNS (3-cap on FortiOS) / NTP / syslog / timezone (numeric-vs-Olson). |
| `interfaces.md` | FortiOS edit-table (`port1`, `internal`, `agg1`) versus OPNsense XML zone labels (`<wan>`/`<lan>`/`<optN>`) over BSD device names. |
| `vlans.md` | Both vendors use 802.1Q child interfaces (NOT VLAN-centric port lists) — relatively clean fit. |
| `static_routes.md` | FortiOS flat per-route table versus OPNsense's two-block `<gateways>` + `<staticroutes>` model (named-gateway JOIN). |
| `dhcp.md` | Both interface-bound; differ on edit-id-vs-zone-label addressing. |
| `snmp.md` | v1/v2c surface round-trips; SNMPv3 USM lives in OPNsense plugin's snmpd.conf, not config.xml. |
| `local_users.md` | FortiOS `ENC` versus OPNsense bcrypt — both vendor-private; hashes are not cross-compatible. |
| `radius.md` | RADIUS server config — FortiOS single auth-port versus OPNsense explicit auth+acct ports. |
| `lags.md` | FortiOS `set type aggregate` versus OPNsense `lagg(4)` driver naming + LACP-mode collapse. |
| `firewall_role_match_but_unsupported.md` | Both vendors model firewall / NAT / VPN natively — but canonical schema doesn't (Tier 3); cross-pair drops these features. |
| `vrf_vdom.md` | FortiGate VDOMs / per-interface integer VRF versus OPNsense (no VRF in base OS). |

Retrieved over 2026-04-30 to 2026-05-01.

## See also

- `../README.md` — citation cache layout (top-level index).
- `../opnsense_to_fortigate_cli/_INDEX.md` — reverse direction.
- `../../../tests/fixtures/cross_vendor_expectations/README.md` — schema spec.

# OPNsense to FortiGate FortiOS — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/opnsense__fortigate_cli.yaml`
per-field expectations.  See `tests/fixtures/cross_vendor_expectations/
README.md` for the canonical schema definition.

This is the REVERSE direction of fortigate_cli_to_opnsense.  Both
vendors are firewall-class platforms with native models for the same
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
consolidating between OPNsense and FortiGate must manually reconstruct
firewall policy, NAT, and VPN config after migration.

| Topic | Summary |
|---|---|
| `system_services.md` | OPNsense unbounded DNS list versus FortiOS three-cap; Olson zoneinfo versus numeric index. |
| `interfaces.md` | OPNsense XML zone labels (`<wan>`/`<lan>`/`<optN>`) over BSD device names versus FortiOS edit-table flat namespace. |
| `vlans.md` | Both vendors use 802.1Q child interfaces — relatively clean fit modulo SVI projection gap. |
| `static_routes.md` | OPNsense's two-block `<gateways>` + `<staticroutes>` model versus FortiOS flat per-route table. |
| `dhcp.md` | OPNsense zone-label addressing versus FortiOS edit-id addressing; DNS three-cap on FortiOS. |
| `snmp.md` | v1/v2c surface round-trips; OPNsense source never carries SNMPv3 (lives in plugin's snmpd.conf). |
| `local_users.md` | OPNsense bcrypt versus FortiOS `ENC` — both vendor-private; hashes are not cross-compatible. |
| `radius.md` | OPNsense cleartext secret versus FortiOS `ENC`; OPNsense explicit acct-port drops on FortiGate render. |
| `lags.md` | OPNsense `lagg(4)` driver naming versus FortiOS operator-named aggregates + LACP-mode collapse. |
| `firewall_role_match_but_unsupported.md` | Both vendors model firewall / NAT / VPN natively — but canonical schema doesn't (Tier 3); cross-pair drops. |
| `vrf_vdom.md` | OPNsense has no VRF (not_applicable); FortiGate VDOMs / per-interface integer VRF target-side. |

Retrieved over 2026-04-30 to 2026-05-01.

## See also

- `../README.md` — citation cache layout (top-level index).
- `../fortigate_cli_to_opnsense/_INDEX.md` — forward direction.
- `../../../tests/fixtures/cross_vendor_expectations/README.md` — schema spec.

# Fortinet FortiGate — What works for me?

If you operate Fortinet FortiGate devices and want to know what
Netcanon does for you, this is the page.

## TL;DR

- **`fortigate_cli`** — FortiOS `show full-configuration` (nested
  `config / edit / set / next / end` syntax) parse + render.
  **Certification: certified.**  Bidirectional.

The codec covers FortiOS 7.2.x through 7.6.x across FortiGate VM,
70G branch, and 100E physical-appliance fixtures.

**Important Tier-3 boundary**: FortiGate's flagship surfaces —
firewall policy table, NAT, IPsec VPN, SSL-VPN, web-filter,
antivirus, IPS — are **deliberately deferred** (see Tier 3 below).
Netcanon translates the SHARED-NETWORK-FUNCTION subset (interfaces,
VLANs, DHCP, RADIUS, SNMP) — not the security-product DNA.  If
firewall translation is your primary need, see
[`../COMPARISON.md`](../COMPARISON.md) for adjacent tools.

## What translates well

[Tier 1](../CAPABILITIES.md#tier-1--auto-translatable-cross-vendor-stable):

- `hostname` (alias / hostname), `domain`, DNS / NTP / syslog
- Interfaces — physical (`port1`-`portN`, `wan1`/`wan2`,
  `internal1`-`internalN`), VLAN sub-interfaces (`VL_<id>`,
  `LAN_TRUNK`), aggregate (`fortilink`, `LAG_INTERNAL`), tunnel
  (SSL-VPN, IPsec); descriptions, IPv4 + IPv6, enabled state.
  **Note:** per-interface MTU is parsed when FortiGate is the
  *source* (carried into the canonical model and rendered by other
  target codecs that emit MTU) but not emitted when FortiGate is the
  *target* — see codec capability matrix.  Per-interface VRF is
  routing-instance-scoped, not a Tier-1 binding.
- VLANs — VLAN sub-interface form (`config system interface` →
  `set type vlan` + `set vlanid <N>`)
- Static routes (`config router static`)
- LAGs (`config system interface` with `set type aggregate` +
  member lists)

[Tier 2](../CAPABILITIES.md#tier-2--translatable-with-caveats):

- SNMP v1/v2c/v3 USM — `config system snmp community` for v1/v2c;
  `config system snmp user` with `auth-proto` / `priv-proto` /
  `auth-pwd ENC ...` for v3
- RADIUS servers — `config user radius` with shared secret
- DHCP servers — `config system dhcp server` with per-pool subnet,
  range, gateway, dns-server, options
- Local admin / user accounts — `config system admin` with
  `set password ENC ...` form-preserving migration

## Lossy paths

- **`/system/dns`** with view scoping — view definitions parse-and-
  ignore (`config system dns-database`); cross-vendor mappings
  collapse to global DNS.
- See per-codec `CapabilityMatrix.lossy` declarations for the
  full list.

## What we don't do

These are the FortiGate flagship surfaces deliberately deferred to
[Tier 3](../CAPABILITIES.md#tier-3--opaque-carry--not-auto-rendered):

- **Firewall policy table** — `config firewall policy` (the
  zone-pair / interface-pair stateful policy table is FortiGate's
  primary semantic; cross-vendor translation doesn't preserve
  meaning)
- **NAT** — VIPs, IP pools, central-NAT, SNAT, DNAT
  (`config firewall vip` etc.)
- **IPsec VPN** — `config vpn ipsec phase1-interface` /
  `phase2-interface`
- **SSL-VPN** — `config vpn ssl settings`, portal config, web-mode
  bookmarks
- **Web-filter / antivirus / IPS / application-control** — UTM
  profiles
- **SD-WAN** — health-check, SLA, performance-SLA rules
- **FortiGuard categories** — license-bound URL category lists
- **Routing protocols** — BGP / OSPF stanzas (informational only)
- **Certificates / PKI**

## Real-world fixtures we've validated against

Provenance in
[`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md):

- **`kevinguenay_fgt_70g_branch.conf`** — FortiOS 7.6.6 branch
  config for FortiGate 70G ZTP deployment (12,317 lines covering
  system global, fortilink, LAG_INTERNAL aggregates, BGP loopback,
  SD-WAN, IPsec, firewall policies, web-filter, antivirus, IPS —
  the Tier-3 surface here is silently carried past)
- **`kevinguenay_fgt_vm_hub.conf`** — FortiOS 7.6.6 VM-based hub
  config (13,827 lines; hub-side counterpart to the branch)
- **`user_contrib_fg100e_fos7213.conf`** — operator-contributed
  physical FortiGate 100E on FortiOS 7.2.13 (35K+ lines, 34
  interfaces, 5 VLAN sub-interfaces, 2 LAGs, 6 DHCP servers,
  full firewall policy table, VIPs, SDWAN health-check, IPsec,
  SSL-VPN portal — first physical-appliance + first 7.2.x
  capture in the corpus)

Spans FortiOS 7.2.x and 7.6.x; FortiGate VM, 70G branch hardware,
and 100E physical hardware.

## Common gotchas

- **`ENC <base64>` encrypted secrets** — round-trip through the
  canonical `hashed_password` field with format-preservation; never
  decoded to plaintext.
- **`set vdom`** scoping — Netcanon parses single-VDOM configs
  cleanly; multi-VDOM scoping is a known gap (deferred follow-up).
- **Most of a FortiGate config is Tier-3** (firewall, NAT, VPN,
  UTM); Netcanon translates the cross-vendor-translatable subset
  (interfaces, VLANs, DHCP, RADIUS, SNMP) and silently carries the
  rest past on parse.  The migrate page's Tier-3 banner surfaces
  what was detected-but-not-translated.
- **Backup-side**: requires netmiko or paramiko-shell collector
  with `cisco_more_paging: false`.

## See also

- [`../CAPABILITIES.md`](../CAPABILITIES.md) — full capability matrix
- [`../../tests/fixtures/real/RESULTS.md`](../../tests/fixtures/real/RESULTS.md)
  — live certification state
- [`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md)
  — fixture provenance
- [`../COMPARISON.md`](../COMPARISON.md) — Capirca / Aerleon for
  firewall ACL translation
- [`../../BUG_REPORTING.md`](../../BUG_REPORTING.md)
- [`../TROUBLESHOOTING.md`](../TROUBLESHOOTING.md)
- [`../HOW_WE_TEST.md`](../HOW_WE_TEST.md)

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

## L3 redundancy: VRRP (no anycast)

**New in v0.2.0** (Wave B — classic VRRP wire-up).

FortiGate delivers HA / L3 redundancy exclusively through VRRP
groups; there's no anycast-gateway surface (anycast is a fabric
primitive on DC switches, not on edge firewalls).  The codec parses
the nested `config vrrp / edit N` sub-block inside `config system
interface`.

### Grammar

```text
config system interface
    edit "vlan10"
        set vdom "root"
        set ip 10.0.10.1 255.255.255.0
        config vrrp
            edit 10
                set vrip 10.0.10.254
                set priority 110
                set preempt enable
                set adv-interval 1
                set authentication "secretpass"
                set vrdst port2
                set status enable
            next
        end
    next
end
```

Sub-commands handled: `set vrip <X>` (IPv4 virtual), `set vrip6 <X>`
(IPv6 VRRPv3), `set priority`, `set preempt enable|disable`,
`set adv-interval <S>`, `set authentication "<token>"` (→
`plain:<token>`), `set vrdst <iface>` (destination-tracking, maps
to canonical `track_interfaces`).  Multiple `edit N` blocks under
one `config vrrp` produce multiple `CanonicalVRRPGroup` records.

VRID is bounded to 1-255 (IETF spec + pydantic validator); edits
with out-of-range IDs or missing `set vrip` are silently dropped on
parse.

### Known limitations

- **Single VIP per group.**  FortiOS `set vrip` accepts a single
  address per group.  Cross-vendor migration from multi-IP sources
  (Cisco IOS-XE secondaries, Junos `virtual-address [ X Y Z ]`)
  emits the first VIP and drops the tail with a `# review:` line
  — operator must split into multiple groups manually.
- **Custom virtual-MAC per group drops.**  FortiOS uses
  `set vrrp-virtual-mac enable/disable` as an interface-wide toggle
  (defaults to disable — FortiOS uses its NPU MAC instead of the
  IETF `00:00:5E:00:01:VRID`).  The canonical `virtual_mac`
  per-group override has no FortiOS equivalent.
- **Single `vrdst` per group.**  FortiOS `set vrdst` takes one
  interface.  Multi-track canonical groups (IOS-XE `track` objects,
  Arista `vrrp N track ... decrement N`) emit the first and drop
  the rest with a `# review:` line.  The decrement value is also
  lossy — `vrdst` is a binary up/down trigger, not a priority-
  decrement scheme.
- **`vrgrp`, `vrdst-priority`, `start-time`**, and other FortiOS-
  specific knobs (group-of-groups synchronisation, alternate-
  priority for destination unreachable, startup-delay) are not in
  canonical scope and drop on cross-vendor render.
- **No anycast-gateway grammar.**  FortiGate is a firewall / edge
  platform; the three anycast canonical paths
  (`virtual-gateway-address` v4/v6, `anycast-gateway-mac`) are
  declared `unsupported` and parse-and-ignore.

### Cross-references

- [`../v0.2.0-planning/01-vrrp-canonical/`](../v0.2.0-planning/01-vrrp-canonical/)
  — VRRP canonical model; see `02-per-vendor-grammar.md` §
  "FortiGate" for the per-knob lossiness rationale.
- [`../v0.2.0-planning/02-anycast-gateway/`](../v0.2.0-planning/02-anycast-gateway/)
  — anycast-gateway design (FortiGate explicitly out of scope as a
  firewall/edge platform without fabric primitives).

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

# FortiGate firewall / NAT / VPN / UTM — unsupported on Juniper Junos targets

## Why this is unsupported

FortiGate's primary product surface is the firewall: stateful
session-based policy + NAT + IPsec VPN + SSL VPN + UTM (AV / IPS /
web-filter / app-control) + SD-WAN.  None of these are modelled in
the canonical migration tree:

- The canonical `CanonicalIntent` schema has no `firewall_rules`,
  `nat_rules`, `vpn_tunnels`, `sd_wan_zones` fields.  These were
  intentionally left out of v1 scope (the migration product targets
  the L2 / L3 / system-services / SNMP / RADIUS / LAG surface that
  is portable across vendors; firewall semantics are session-based
  and zone-aware in ways that don't translate).
- The Junos target side has its own firewall product surface
  (firewall filters, services NAT, IPsec, IDP / AppSecure) but the
  semantics are stateless-default / interface-attached, not
  session-based.  Auto-translation would silently change the
  security posture.

## FortiGate firewall surface (illustrative; not in canonical)

Source: [Fortinet — FortiOS Cookbook — Firewall policy / VIP / NAT](https://docs.fortinet.com/document/fortigate/7.4.0/cookbook/).
Retrieved: 2026-05-01.

```
config firewall policy
    edit 1
        set name "ALLOW-INTERNAL-OUT"
        set srcintf "internal"
        set dstintf "wan1"
        set srcaddr "INTERNAL-NET"
        set dstaddr "all"
        set service "ALL"
        set action accept
        set nat enable
        set utm-status enable
        set av-profile "default"
        set webfilter-profile "default"
    next
end
config firewall vip
    edit "WEB-VIP"
        set extip 198.51.100.20
        set extintf "wan1"
        set mappedip "10.0.0.20"
        set portforward enable
        set extport 443
        set mappedport 443
    next
end
```

## Disposition on cross-vendor migration

- **All firewall / NAT / VPN / SD-WAN / UTM intent** is
  `unsupported` on FortiGate -> Junos in v1.
- The FortiGate codec parses these into `raw_sections` (Tier 3)
  for display only; cross-vendor migration drops the section with
  a banner.
- Operators must keep an upstream firewall (or migrate the
  firewall portion separately to Junos's services NAT / firewall
  filter / IPsec) — Junos-as-router is not a 1:1 replacement for
  a FortiGate.

## What this means in practice

The cross-vendor expectations YAML treats the canonical fields
only.  For fields that are:

- structurally absent from the canonical (firewall_rules,
  nat_rules, vpn_tunnels): no per-field entry exists.
- captured in `raw_sections` as Tier-3 informational: marked
  `not_applicable` (Tier 3 is never auto-rendered).

This document exists to make the rationale citeable from the
`raw_sections` field's `not_applicable` entry rather than burying
it in the YAML notes.

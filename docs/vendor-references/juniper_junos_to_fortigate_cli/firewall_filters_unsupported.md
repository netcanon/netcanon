# Junos firewall filters / policy-statement / BGP / OSPF / MPLS — unsupported

## Junos source surface (illustrative; not in canonical)

Source: [Junos firewall filters / policy-statement overview](https://www.juniper.net/documentation/us/en/software/junos/routing-policy/topics/topic-map/firewall-filter-overview.html).
Retrieved: 2026-05-01.

Junos has rich routing-policy + firewall surfaces under:

- `set protocols bgp / ospf / isis / mpls ...` — routing protocols.
- `set policy-options policy-statement <name>` — route filters,
  prefix lists, AS-path matching, community matching.
- `set firewall family inet filter <name> term <T> from / then` —
  stateless interface-attached firewall filters (the "Junos ACL"
  equivalent).
- `set services nat ... ` / `set services ipsec-vpn` — services
  routing-engine functions.

Examples:

```
set protocols bgp group EXTERNAL type external
set protocols bgp group EXTERNAL neighbor 10.0.0.5 peer-as 65001
#
set policy-options policy-statement ADV-LOOPBACKS from protocol direct
set policy-options policy-statement ADV-LOOPBACKS from route-filter 172.16.0.0/12 orlonger
set policy-options policy-statement ADV-LOOPBACKS then accept
#
set firewall family inet filter BLOCK-RFC1918 term DENY-10 from source-address 10.0.0.0/8
set firewall family inet filter BLOCK-RFC1918 term DENY-10 then discard
set firewall family inet filter BLOCK-RFC1918 term ALLOW-OTHER then accept
```

## Disposition on cross-vendor migration

These surfaces are **out of canonical scope in v1**:

- The canonical `CanonicalIntent` schema has no `bgp_neighbors`,
  `ospf_areas`, `policy_statements`, `firewall_filters` fields.
  These were intentionally left out of v1 scope (the migration
  product targets the L2 / L3 / system-services / SNMP / RADIUS /
  LAG portable surface; routing-policy + firewall semantics are
  vendor-specific in ways that don't auto-translate cleanly).
- The Junos codec parses these into `raw_sections` (Tier 3) for
  display only; cross-vendor migration drops the section with a
  banner.
- The Junos codec capability matrix lists `/routing/bgp` and
  `/firewall/filter` under unsupported with rationale "BGP /
  IS-IS / OSPF / MPLS stanzas parse-and-ignore in v1" and "Junos
  firewall filters are Tier-3 — the grammar (family / term / from
  / then) is distinct from ACL models in other codecs and defers."

## FortiGate has its own analogous surfaces

FortiGate has analogous (but semantically distinct) surfaces:

- **Routing protocols**: `config router bgp / ospf / rip / static`
  — modelled differently, not auto-translatable from Junos.
- **Firewall policies**: `config firewall policy` — session-based
  stateful, semantically different from Junos's stateless
  interface-attached filters.

Auto-translating Junos firewall filters -> FortiGate firewall
policies would silently change the security posture.

## Disposition

- **`raw_sections`** is `not_applicable` (Tier 3, never auto-rendered).
- All BGP / OSPF / MPLS / firewall-filter / policy-statement intent
  drops on cross-vendor migration.
- Operators must reconstruct routing-policy and firewall semantics
  manually on the FortiGate target — typically with assistance from
  a vendor migration tool that targets the firewall surface
  specifically (FortiConverter / similar).

This document exists to make the rationale citeable from the
`raw_sections` `not_applicable` entry.

# Firewall / role mismatch: Junos versus OPNsense

Why Junos firewall filters and policy-statements don't cross to
OPNsense, and why OPNsense's firewall / NAT / VPN don't cross back
to Junos.

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/routing-policy/topics/topic-map/routing-policies.html (retrieved 2026-05-01)
- OPNsense: https://docs.opnsense.org/manual/firewall.html (retrieved 2026-04-30)

## Junos firewall filters / policy-statements

Junos's firewall filters and routing policy live in distinct
hierarchies:

```
set firewall family inet filter EDGE-IN term BLOCK_RFC1918 from source-address 10.0.0.0/8
set firewall family inet filter EDGE-IN term BLOCK_RFC1918 then discard
set firewall family inet filter EDGE-IN term ACCEPT_REST then accept
set interfaces ge-0/0/0 unit 0 family inet filter input EDGE-IN

set policy-options policy-statement EXPORT-DIRECT from protocol direct
set policy-options policy-statement EXPORT-DIRECT then accept
```

The juniper_junos codec capability matrix lists `/firewall/filter`
under `unsupported` ("Junos firewall filters are Tier-3 — the
grammar (family / term / from / then) is distinct from ACL models
in other codecs and defers").

## OPNsense firewall

OPNsense's firewall is the platform's primary purpose.  Rules live
in `<filter>/<rule>` blocks with rich semantic (interface scope,
schedules, GeoIP, statefulness, advanced-options).  NAT lives in
`<nat>/<outbound>` and `<nat>/<rule>`.  VPN configuration spans
`<openvpn>`, `<ipsec>`, plugins for WireGuard.

The opnsense codec capability matrix lists `/filter/rule` and
`/nat/outbound` under `unsupported` with rationale "Firewall rules
require the netcanon-ext YANG module" / "NAT table translation
needs netcanon-ext + careful semantic mapping".

## Cross-vendor mapping

This is the **role-mismatch** axis of the cross-pair:

* Junos firewall filters and policy-statements → OPNsense:
  parse-and-ignore on Junos (Tier-3 by capability matrix).  Even if
  they reached canonical, OPNsense's firewall-rule model is
  structurally different (PF table syntax versus Junos's
  family/term/from/then).
* OPNsense firewall / NAT / VPN → Junos: parse-and-ignore on
  OPNsense (Tier-3 by capability matrix).  Even if they reached
  canonical, Junos has no PF-equivalent surface.

Both sides correctly recognise this is OUT OF SCOPE for cross-
vendor canonical translation.  Tier-3 carry-through via
`raw_sections` would be possible but is intentionally not wired —
operators rebuild firewall / NAT / VPN policy on the target
platform from scratch.

Disposition: **not_applicable** for the canonical fields (these
features have no canonical surface).  Tier-3 raw_sections content
drops with a banner.

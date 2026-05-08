# Firewall / role mismatch: OPNsense source versus Junos target

Why OPNsense's firewall / NAT / VPN don't cross to Junos.

Sources:
- OPNsense: https://docs.opnsense.org/manual/firewall.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/routing-policy/topics/topic-map/routing-policies.html (retrieved 2026-05-01)

## OPNsense firewall

OPNsense's firewall is the platform's primary purpose.  Rules live
in `<filter>/<rule>` blocks with rich semantic (interface scope,
schedules, GeoIP, statefulness, advanced-options).  NAT lives in
`<nat>/<outbound>` and `<nat>/<rule>`.  VPN configuration spans
`<openvpn>`, `<ipsec>`, plugins for WireGuard.  Captive portal,
proxy, IDS/IPS round out the security feature set.

The opnsense codec capability matrix lists `/filter/rule` and
`/nat/outbound` under `unsupported` ("Firewall rules require the
netcanon-ext YANG module" / "NAT table translation needs
netcanon-ext + careful semantic mapping").

## Junos firewall filters / policy-statements

Junos's firewall filters live in distinct hierarchies:

```
set firewall family inet filter EDGE-IN term BLOCK_RFC1918 from source-address 10.0.0.0/8
set firewall family inet filter EDGE-IN term BLOCK_RFC1918 then discard
```

The juniper_junos codec capability matrix lists `/firewall/filter`
under `unsupported` ("Junos firewall filters are Tier-3 — the
grammar (family / term / from / then) is distinct from ACL models
in other codecs and defers").

Note: **Junos has no PF-equivalent stateful firewall surface in the
SRX line that maps cleanly onto OPNsense's PF rule semantic.**  Even
if the canonical model carried firewall rules, the translation is
not mechanical.

## Cross-vendor mapping

* OPNsense firewall / NAT / VPN → Junos: parse-and-ignore on
  OPNsense (Tier-3 by capability matrix).  Even if they reached
  canonical, Junos's `firewall family inet filter` model is
  structurally different.
* WireGuard / OpenVPN / IPsec on OPNsense don't have first-class
  Junos analogues at the canonical level (Junos IPsec lives in
  `services ipsec-vpn` hierarchy, with very different semantics).

Both sides correctly recognise this is OUT OF SCOPE for cross-
vendor canonical translation.  Tier-3 carry-through via
`raw_sections` would be possible but is intentionally not wired —
operators rebuild firewall / NAT / VPN policy on the target
platform from scratch.

Disposition: **not_applicable** for canonical fields (these features
have no canonical surface).  Tier-3 raw_sections content drops with
a banner.

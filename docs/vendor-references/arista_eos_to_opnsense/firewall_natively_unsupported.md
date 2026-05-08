# Firewall / NAT / VPN: cross-vendor scope (Arista source side)

## Arista EOS

Source: [Arista EOS User Manual — Access Control Lists](https://www.arista.com/en/um-eos/eos-acls)
Retrieved: 2026-05-01

Arista EOS supports IP / IPv6 / MAC ACLs (`ip access-list <name>`,
`ipv6 access-list <name>`, etc.) but the arista_eos codec treats
them as Tier 3 informational (`raw_sections`).  ACLs do not reach
the canonical surface.

There is no NAT, no IPsec / OpenVPN / WireGuard, no captive portal
on Arista — these are out of the platform's role as a DC L2/L3
switch.  Stateful firewall capability is limited (Arista offers
service ACLs and TAP-aggregator filtering rather than a
session-tracking firewall).

## OPNsense

Source: [OPNsense Firewall manual](https://docs.opnsense.org/manual/firewall.html)
Retrieved: 2026-04-30

OPNsense's primary purpose is firewall / NAT / VPN.  `<filter>`,
`<nat>`, `<openvpn>`, `<ipsec>`, `<wireguard>`, `<captiveportal>`
etc. carry the bulk of an OPNsense config — none of these are
modelled in `CanonicalIntent` v1.  The opnsense codec capability
matrix lists `/filter/rule` and `/nat/outbound` as unsupported
pending the netcanon-ext YANG module.

## Cross-vendor disposition

`raw_sections` on either codec is Tier 3 by design — never
auto-rendered.  Arista ACLs land in `raw_sections` on parse; the
OPNsense target couldn't render them as `<filter>` / `<nat>`
rules anyway (OPNsense uses a stateful pf-based engine with
fundamentally different semantics from Arista's stateless ACLs).

For this direction (Arista → OPNsense): the Arista source
firewall content is informational only; the OPNsense target
firewall surface is structurally absent on the canonical tree.
Disposition for `raw_sections` is `not_applicable` (Tier 3 by
design).

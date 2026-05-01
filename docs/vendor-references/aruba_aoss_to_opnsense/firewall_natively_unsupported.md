# Firewall / NAT / VPN: cross-vendor scope

## Aruba AOS-S

Source: [Aruba AOS-S 16.10 Access Security Guide — ACL](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ASG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

Aruba AOS-S supports IP / IPv6 / MAC ACLs (`ip access-list extended
<name>`, `ipv6 access-list <name>`, etc.) but the aruba_aoss codec
treats them as Tier 3 informational (raw_sections).  ACLs do not
reach the canonical surface.

There is no NAT, no IPsec / OpenVPN / WireGuard, no captive portal
in AOS-S — these are out of the platform's role as a campus L2/L3
switch.

## OPNsense

Source: [OPNsense Firewall manual](https://docs.opnsense.org/manual/firewall.html)
Retrieved: 2026-04-30

OPNsense's primary purpose is firewall / NAT / VPN.  `<filter>`,
`<nat>`, `<openvpn>`, `<ipsec>`, `<wireguard>`, `<captiveportal>`,
`<dpinger>`, plugin blocks etc. carry the bulk of an OPNsense
config — none of these are modelled in `CanonicalIntent` v1.  The
opnsense codec capability matrix lists `/filter/rule` and
`/nat/outbound` as unsupported pending the netconfig-ext YANG
module.

## Cross-vendor disposition

`raw_sections` on either codec is Tier 3 by design — never auto-
rendered.  Aruba ACLs land in raw_sections on parse and OPNsense
target couldn't render them as XML rules anyway.  OPNsense firewall
rules don't survive a cross-pair to Aruba either (the AOS-S
side has no equivalent table-of-rules surface — its ACLs are
applied per-interface / per-VLAN, with very different semantics).

For this direction (Aruba → OPNsense): the Aruba source firewall
content is informational only; the OPNsense target firewall surface
is structurally absent on the canonical tree.  Disposition for
`raw_sections` is `not_applicable` (Tier 3 by design).

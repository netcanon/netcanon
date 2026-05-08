# Firewall / NAT / VPN drops on render (OPNsense source side)

## OPNsense

Source: [OPNsense Firewall manual](https://docs.opnsense.org/manual/firewall.html)
Retrieved: 2026-04-30

OPNsense's primary purpose is firewall / NAT / VPN.  `<filter>`,
`<nat>`, `<openvpn>`, `<ipsec>`, `<wireguard>`, `<captiveportal>`,
`<dpinger>`, plugin blocks etc. carry the bulk of an OPNsense
config.  None of these are modelled in `CanonicalIntent` v1.  The
opnsense codec capability matrix lists `/filter/rule` and
`/nat/outbound` as unsupported pending the netcanon-ext YANG
module.

## Arista EOS

Source: [Arista EOS User Manual — Access Control Lists](https://www.arista.com/en/um-eos/eos-acls)
Retrieved: 2026-05-01

Arista EOS supports stateless IP / IPv6 / MAC ACLs.  These have
fundamentally different semantics from OPNsense's stateful
pf-based engine — a one-to-one rule mapping is impossible.  The
arista_eos codec lands ACLs in `raw_sections` (Tier 3) rather
than canonical.

There is no NAT, no IPsec / OpenVPN / WireGuard, no captive
portal on Arista EOS — these are out of platform role for a DC
switch.

## Cross-vendor disposition

`raw_sections` on either codec is Tier 3 by design — never
auto-rendered.  OPNsense's firewall / NAT / VPN content stays
inside `raw_sections` (when carried at all); the Arista target
couldn't accept it as ACLs because:

1. The semantic mismatch (stateful pf rules vs stateless ACL
   entries) makes any auto-translation unsound.
2. Arista has no NAT, VPN, or captive-portal surface to land on.

Disposition for `raw_sections` is `not_applicable` (Tier 3 by
design) on this direction.  Operators redesign firewall / NAT /
VPN intent on the target platform out of band.

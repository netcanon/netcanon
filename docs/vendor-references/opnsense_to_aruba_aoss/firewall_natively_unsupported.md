# Firewall / NAT / VPN: cross-vendor scope

## OPNsense

Source: [OPNsense Firewall manual](https://docs.opnsense.org/manual/firewall.html)
Retrieved: 2026-04-30

OPNsense's primary purpose is firewall / NAT / VPN.  `<filter>`,
`<nat>`, `<openvpn>`, `<ipsec>`, `<wireguard>`, `<captiveportal>`
blocks carry the bulk of an OPNsense config.  None of these are
modelled in `CanonicalIntent` v1.  The opnsense codec capability
matrix lists `/filter/rule` and `/nat/outbound` as unsupported
pending the netconfig-ext YANG module.  Such state may land in
`raw_sections` (Tier 3, informational) on parse.

## Aruba AOS-S

Source: [Aruba AOS-S 16.10 Access Security Guide](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ASG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

Aruba AOS-S is a campus L2/L3 switch.  Its security surface is
ACL-based (`ip access-list extended <name>` etc.) with very
different semantics from a stateful firewall — per-port / per-VLAN
filter application, no connection tracking, no NAT, no VPN
termination.  The aruba_aoss codec treats ACLs as Tier 3
(raw_sections), and there is no destination shape on AOS-S for
OPNsense's stateful filter / NAT / VPN tables.

## Cross-vendor disposition

`raw_sections` is Tier 3 by design — never auto-rendered.  OPNsense
firewall content informs operator review only; the Aruba target
couldn't accept it as a stateful policy.  Disposition for
`raw_sections` is `not_applicable` (Tier 3 by design).

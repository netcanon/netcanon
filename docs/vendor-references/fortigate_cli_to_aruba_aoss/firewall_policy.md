# Firewall policies: FortiGate FortiOS versus Aruba AOS-S

This is the reverse-direction sibling of
[`../aruba_aoss_to_fortigate_cli/firewall_policy.md`](../aruba_aoss_to_fortigate_cli/firewall_policy.md).

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate Cookbook — Firewall policies](https://docs.fortinet.com/document/fortigate/7.4.0/cookbook/).
Retrieved: 2026-04-30

FortiGate's firewall policy is its **primary product surface**:
session-based, zone-aware, UTM-enabled.  See
[`../aruba_aoss_to_fortigate_cli/firewall_policy.md`](../aruba_aoss_to_fortigate_cli/firewall_policy.md)
for the FortiOS specifics.

The FortiGate codec lists `/filter/rule` and `/nat/rule` under
unsupported in its capability matrix — Tier 3 (informational) /
not auto-translatable.

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Access Security Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ASG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S has only Tier-3 named extended ACLs.  No stateful firewall,
no NAT, no VPN, no UTM.  The codec lists `/filter/rule` under
unsupported.

## Cross-vendor mapping (FortiGate -> Aruba)

Canonical surface: **none**.  v1 canonical model has no
representation for firewall policy / NAT / VPN / UTM.

Disposition: **not_applicable** for this cross-pair (no canonical
field exists).  More fundamentally, FortiGate's session-based
zone-aware policy semantics have no Aruba analogue at all —
operators consolidating a FortiGate firewall to a downstream Aruba
edge switch must keep an upstream firewall (Palo Alto, Cisco
Firepower, another FortiGate, etc.) for the policy / NAT / VPN
surface; AOS-S cannot fill that role even with Tier-3 ACL hand-
translation.

The FortiGate firewall config falls into `raw_sections` for
display only.

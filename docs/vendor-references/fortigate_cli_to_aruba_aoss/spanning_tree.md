# Spanning-tree: FortiGate FortiOS versus Aruba AOS-S

This is the reverse-direction sibling of
[`../aruba_aoss_to_fortigate_cli/spanning_tree.md`](../aruba_aoss_to_fortigate_cli/spanning_tree.md).

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/).
Retrieved: 2026-04-30

FortiGate appliances are typically the L3 termination point of a
network — STP is irrelevant to firewall operation.  The hardware-
switch sub-feature on 60E-class units exposes a basic
`config system switch-interface` block but no STP knobs.  See
[`../aruba_aoss_to_fortigate_cli/spanning_tree.md`](../aruba_aoss_to_fortigate_cli/spanning_tree.md)
for FortiGate L2-surface specifics.

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Multicast and Routing Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MRG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S supports MSTP (default), RPVST+, and legacy STP.  See
forward-direction sibling for full Aruba specifics.

## Cross-vendor mapping (FortiGate -> Aruba)

Canonical surface: **none**.  v1 canonical model has no
representation for spanning-tree.

Disposition: **not_applicable** for this cross-pair (no canonical
field exists).  The FortiGate source carries no STP intent
(firewall is typically the L3 termination point); the Aruba
target requires STP for L2 loop prevention but the operator must
configure it manually post-migration based on the deployed
topology.

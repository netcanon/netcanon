# Spanning-tree: Aruba AOS-S versus FortiGate FortiOS

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Multicast and Routing Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MRG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S supports MSTP (default mode), RPVST+, and legacy STP:

```
spanning-tree
spanning-tree mode mstp
spanning-tree priority 4096
spanning-tree config-name "campus-mst"
spanning-tree config-revision 1

spanning-tree 1-24 admin-edge-port
spanning-tree 1-24 bpdu-protection
```

Notable AOS-S specifics:

- **MSTP is default** with up to 16 instances.
- **Port-level features**: `admin-edge-port` (PortFast analogue),
  `bpdu-protection` (BPDU guard), `root-guard`, `loop-protect`.
- **Per-VLAN priority** in RPVST+ mode.

The aruba_aoss codec does NOT parse spanning-tree state into
canonical records (no canonical field exists).  STP config falls
into `raw_sections` if at all.

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/).
Retrieved: 2026-04-30

FortiGate appliances are **typically the L3 termination point** of
a network — STP is irrelevant to firewall operation.  The
hardware-switch sub-feature on 60E-class units exposes a basic
`config system switch-interface` block but no STP knobs.  Higher-
end FortiGates with FortiSwitch managed-switch integration
(`config switch-controller managed-switch`) can drive remote
FortiSwitch STP but that is an out-of-scope FortiSwitch surface
for the FortiGate CLI codec.

## Cross-vendor mapping (Aruba -> FortiGate)

Canonical surface: **none**.  v1 canonical model has no
representation for spanning-tree.

Disposition: **not_applicable** for this cross-pair (no canonical
field exists).  Aruba's MSTP / RPVST+ has no FortiGate target;
operators consolidating an AOS-S edge into a FortiGate lose all
STP intent.  This is rarely a problem in practice — FortiGate
deployments are typically a leaf in a routed topology where STP
isn't required.

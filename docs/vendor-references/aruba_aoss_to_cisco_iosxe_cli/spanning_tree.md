# Spanning-tree: Aruba AOS-S versus Cisco IOS-XE

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Multicast and Routing Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MRG/2930F-3810-5400/index.htm) (spanning-tree chapter)
Retrieved: 2026-04-30

AOS-S defaults to **MSTP** (802.1s):

```
spanning-tree
spanning-tree mode mstp
spanning-tree priority 8
spanning-tree 1-24 admin-edge-port
spanning-tree 1-24 bpdu-protection
```

`admin-edge-port` is the AOS-S equivalent of Cisco's `portfast`.
`bpdu-protection` is the equivalent of Cisco's `bpduguard`.

AOS-S has **no PVST equivalent** — the platform pre-dates per-VLAN
spanning-tree and never adopted it.

## Cisco IOS-XE

Source: [Cisco IOS XE 17.x Layer 2 Configuration Guide — Configuring Spanning-Tree Protocol](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9400/software/release/17-14/configuration_guide/lyr2/b_1714_lyr_2_9400_cg/configuring_spanning_tree_protocol.html)
Retrieved: 2026-04-30

Cisco IOS-XE defaults to **rapid-pvst** (per-VLAN), with `mst` as
opt-in:

```
spanning-tree mode rapid-pvst
spanning-tree vlan 1-4094 priority 24576
spanning-tree portfast bpduguard default
```

## Cross-vendor mapping

Spanning-tree is **Tier 3 informational** in the canonical model;
neither codec populates a structured field.  The directives drop
into `raw_sections` for operator review on parse but are not
auto-rendered cross-vendor.

Operator considerations Aruba -> Cisco:

* AOS-S MSTP -> Cisco MSTP would round-trip the mode but not the
  per-instance VLAN-to-region mapping (codec doesn't model it).
* AOS-S `admin-edge-port` -> Cisco `portfast` requires manual
  remap.

Disposition: **not_applicable** to the canonical-portable surface
(field not modelled).  Operator-driven manual reconciliation
required.

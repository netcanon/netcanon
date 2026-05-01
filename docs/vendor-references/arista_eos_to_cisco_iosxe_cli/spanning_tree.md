# Spanning-tree mode: Arista EOS versus Cisco IOS-XE

## Arista EOS

Source: [EOS 4.36.0F — Spanning Tree Protocol](https://www.arista.com/en/um-eos/eos-spanning-tree-protocol)
Retrieved: 2026-04-30

Arista's default spanning-tree mode is `mstp` (Multiple Spanning Tree
Protocol, IEEE 802.1s).  Supported modes:

```
spanning-tree mode mstp
spanning-tree mode rapid-pvst
spanning-tree mode rstp
spanning-tree mode none
```

Per-VLAN priority and other tuning:

```
spanning-tree vlan-id 100 priority 4096
spanning-tree mst 0 priority 4096
```

## Cisco IOS-XE

Source: [Cisco IOS XE 17 Layer 2 Configuration Guide — Configuring Spanning Tree](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9500/software/release/17-7/configuration_guide/lyr2/b_177_lyr2_9500_cg/configuring_optional_spanning_tree_features.html)
Retrieved: 2026-04-30

Cisco's default spanning-tree mode on Catalyst 9000 IOS-XE is
`pvst` (Per-VLAN Spanning Tree, Cisco extension).  Supported modes:

```
spanning-tree mode pvst
spanning-tree mode rapid-pvst
spanning-tree mode mst
```

Per-VLAN priority:

```
spanning-tree vlan 100 priority 4096
spanning-tree mst 0 priority 4096
```

## Cross-vendor mapping

Spanning-tree mode + per-VLAN tuning is **out of canonical scope** in
v1.  No `CanonicalSpanningTree` model exists.  Both codecs treat
`spanning-tree ...` lines as parse-and-ignore.

Arista's `mstp` default differs from Cisco's `pvst` default; cross-
vendor migrations need an operator decision (the safest cross-vendor
default is `rapid-pvst` which both vendors support).  Without a
canonical model, this decision is out of scope for the auto-render
path.

Disposition: **unsupported** (Tier 3 informational on both vendors;
no canonical model).

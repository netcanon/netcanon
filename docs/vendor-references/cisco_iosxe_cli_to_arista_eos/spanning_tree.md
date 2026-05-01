# Spanning-tree mode: Cisco IOS-XE versus Arista EOS

## Cisco IOS-XE

Source: Cisco IOS XE LAN Switching Configuration Guide — Spanning
Tree.

Cisco's default mode on Catalyst is `pvst` (Per-VLAN Spanning Tree
Plus).  Modern deployments commonly switch to `rapid-pvst` or `mst`:

```
spanning-tree mode pvst        ! default on most Catalyst IOS-XE
spanning-tree mode rapid-pvst
spanning-tree mode mst
```

MST configuration:

```
spanning-tree mst configuration
 name REGION1
 revision 1
 instance 1 vlan 10-19
 instance 2 vlan 20-29
```

## Arista EOS

Source: [EOS 4.36.0F — Spanning Tree Protocol](https://www.arista.com/en/um-eos/eos-spanning-tree-protocol)
Source: [Arista — STP Interoperability with Cisco (white paper)](https://www.arista.com/assets/data/pdf/Whitepapers/STPInteroperabilitywithCisco.pdf)
Retrieved: 2026-04-30

Arista's default mode is `mstp` (a notable difference from Cisco's
`pvst` default).  The EOS manual states: "By default, Arista switches
use MSTP."

Supported modes:

```
spanning-tree mode mstp          ! default on Arista
spanning-tree mode rapid-pvst
spanning-tree mode rstp
spanning-tree mode rapid-pvst
spanning-tree mode none
```

MST region config mirrors Cisco:

```
spanning-tree mst configuration
 name REGION1
 revision 1
 instance 1 vlan 10-19
```

Arista documents native support for MSTP-Rapid-PVST+ interoperation
at boundary ports via the
"MSTP-Rapid PVST+ interoperation" feature, allowing mixed regions.

## Cross-vendor mapping

Spanning-tree configuration is currently **out of canonical scope**
on both codecs.  No `CanonicalSpanningTree` model exists; the entire
stanza lands in `raw_sections` for display, and renderers do NOT
emit spanning-tree config.

Cross-vendor migration considerations (operator-curated, not
auto-translated):

- Cisco `pvst` -> Arista has no equivalent.  Operator must choose
  `rapid-pvst` (closest-match) or `mstp` (Arista default).
- Cisco `rapid-pvst` -> Arista `rapid-pvst`: equivalent.
- Cisco `mst` -> Arista `mstp`: equivalent (config-format identical).
- Cisco `mst configuration / instance N vlan ...` -> Arista same form.

Disposition: **unsupported** (Tier 3 informational; both codecs
parse-and-ignore the stanza).  Reason: no canonical model; cross-
vendor default-mode mismatch (Cisco pvst vs Arista mstp) requires
operator policy decision.

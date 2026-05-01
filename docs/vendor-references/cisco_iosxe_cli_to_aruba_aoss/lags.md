# LAGs (Port-channel / Trk): Cisco IOS-XE versus Aruba AOS-S

## Cisco IOS-XE

Source: [Cisco IOS XE 17.x EtherChannel Configuration Guide](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9400/software/release/17-14/configuration_guide/lyr2/b_1714_lyr_2_9400_cg/configuring_etherchannels.html)
Retrieved: 2026-04-30

Cisco LAGs are configured **per member port** with `channel-group <N>
mode <mode>`; the `Port-channel<N>` virtual interface is auto-created
and accepts independent switchport / L3 configuration:

```
interface Port-channel1
 switchport mode trunk
 switchport trunk allowed vlan 10,20,30
!
interface GigabitEthernet1/0/1
 channel-group 1 mode active
!
interface GigabitEthernet1/0/2
 channel-group 1 mode active
```

LACP modes: `active` / `passive` (LACP), `on` (static / no LACP),
`auto` / `desirable` (PAgP — Cisco-only legacy).

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Advanced Traffic Management Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ATMG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S uses a **single global `trunk` declaration** that names the
member ports and the trunk type (LACP versus static):

```
trunk 1-4 trk1 lacp
trunk A1,A2 trk2 trunk
trunk 25,26 trk3 dt-lacp
```

Trunk-type values (verbatim from the manual):

- `lacp` — 802.3ad dynamic LACP.
- `trunk` — static / manual aggregation, no LACP frames.
- `fec` — HP-proprietary Fast EtherChannel (legacy).
- `dt-lacp` — distributed-trunk LACP for stacked Aruba switches.

The aggregated logical interface is named `Trk<N>` and accepts the
same VLAN-membership grammar as a physical port.

The codec parses these trunks via `_AOS_TRUNK_TYPE_TO_MODE`:

```
_AOS_TRUNK_TYPE_TO_MODE = {
    "lacp":    "active",
    "trunk":   "static",
    "fec":     "static",
    "dt-lacp": "active",
}
```

## Cross-vendor mapping

The canonical model is `CanonicalLAG(name, members, mode)`.  Both
codecs round-trip:

* `members` — list of member port names.
* `mode` — `"active"` (LACP) / `"passive"` / `"static"`.

Name divergence:

* Cisco emits `Port-channel1` (lowercase 'c').
* Aruba emits `Trk1`.

Both forms are valid `CanonicalLAG.name` values; the rename mesh
canonicalises if the operator wants the target name to follow the
source vendor's convention.  The codec helper
`_lag_name_to_aos_trunk` normalises a Cisco-style name (`Port-channel1`)
to AOS-S `trk1` on render.

Cross-vendor caveats:

* Cisco's `auto` / `desirable` PAgP modes are not valid LACP modes
  on Aruba (AOS-S supports LACP-only).  Codec normalises to
  `static`.
* Aruba's `dt-lacp` (distributed-trunk) is a stack-only feature
  with no Cisco equivalent.  Cross-vendor render emits a comment.
* Aruba's `fec` (HP-proprietary) is dead grammar; codec normalises
  to `static`.

Disposition: **lossy** (LAG name capitalisation differs; Cisco-
unique modes (PAgP) and Aruba-unique modes (dt-lacp / fec) collapse
to `static`).

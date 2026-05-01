# LAGs (Trk / Port-channel): Aruba AOS-S versus Cisco IOS-XE

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Advanced Traffic Management Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ATMG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S uses a single global `trunk` declaration:

```
trunk 1-4 trk1 lacp
trunk A1,A2 trk2 trunk
trunk 25,26 trk3 dt-lacp
trunk 5,6 trk4 fec
```

Trunk-type values:

- `lacp` — 802.3ad dynamic LACP -> canonical `mode="active"`.
- `trunk` — static / manual aggregation -> canonical `mode="static"`.
- `fec` — HP-proprietary Fast EtherChannel (legacy, dead grammar)
  -> canonical `mode="static"`.
- `dt-lacp` — distributed-trunk LACP (multi-chassis, AOS-S
  stack-only feature) -> canonical `mode="active"`.

The aggregated logical interface name takes the form `Trk<N>`.

The codec parses these via:

```
_AOS_TRUNK_TYPE_TO_MODE = {
    "lacp":    "active",
    "trunk":   "static",
    "fec":     "static",
    "dt-lacp": "active",
}
```

## Cisco IOS-XE

Source: [Cisco IOS XE 17.x EtherChannel Configuration Guide](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9400/software/release/17-14/configuration_guide/lyr2/b_1714_lyr_2_9400_cg/configuring_etherchannels.html)
Retrieved: 2026-04-30

Cisco LAGs are **per-member**:

```
interface Port-channel1
 switchport mode trunk
!
interface GigabitEthernet1/0/1
 channel-group 1 mode active
```

LACP modes: `active` / `passive` (LACP), `on` (static), `auto` /
`desirable` (PAgP — Cisco-only legacy).

## Cross-vendor mapping

The canonical model is `CanonicalLAG(name, members, mode)`.

Aruba -> Cisco specifics:

* `name`: Aruba `Trk1` -> Cisco `Port-channel1`.  The codec's
  helper `_extract_lag_number` parses the integer suffix and
  emits the Cisco-style name.
* `members`: list of port names.  Aruba's `1-4` port-list expands
  to four canonical port records on parse via `_parse_port_list`;
  Cisco render lists each member with a `channel-group N mode <mode>`
  line.
* `mode`: `active` / `static` round-trips cleanly.  Aruba's
  `dt-lacp` (multi-chassis) has no Cisco equivalent — codec
  renders as `active` plus a `! NOTE: source dt-lacp ...`
  comment.

Disposition: **lossy** (LAG name capitalisation + Aruba-unique
`dt-lacp` / `fec` modes collapse).

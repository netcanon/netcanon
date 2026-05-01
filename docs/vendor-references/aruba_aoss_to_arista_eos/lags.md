# LAGs (Trk / Port-Channel): Aruba AOS-S versus Arista EOS

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

The aggregated logical interface name takes the form `Trk<N>`
(capital T).

## Arista EOS

Source: [Arista EOS — Data Transfer / Port Channels](https://www.arista.com/en/um-eos/eos-data-transfer)
Retrieved: 2026-05-01

Arista EOS uses **per-member `channel-group`** declarations
(Cisco-compatible grammar) plus an explicit `interface
Port-Channel<N>` LAG stanza:

```
interface Port-Channel10
   description "Bonded uplink to core"
   no switchport
   ip address 10.0.1.1/31
!
interface Ethernet4
   description "LAG member 1"
   channel-group 10 mode active
!
interface Ethernet5
   description "LAG member 2"
   channel-group 10 mode active
```

LACP modes: `active` / `passive` (LACP), `on` (static).  No
PAgP support (Cisco-only legacy).

Note the **capital 'C'** in `Port-Channel<N>` — distinct from
Cisco IOS's lower-case `Port-channel<N>`.

## Cross-vendor mapping

The canonical model is `CanonicalLAG(name, members, mode)`.

Aruba -> Arista specifics:

* `name`: Aruba `Trk1` -> Arista `Port-Channel1`.  The codec's
  helper `_extract_lag_number` parses the integer suffix; Arista
  render emits the capital-C form.
* `members`: list of port names.  Aruba's `1-4` port-list expands
  to four canonical port records on parse via `_parse_port_list`;
  Arista render lists each member with a `channel-group N mode
  <mode>` line on the member-port stanza, plus a parent
  `interface Port-Channel<N>` block.
* `mode`: `active` / `static` round-trips cleanly.  Aruba's
  `dt-lacp` (multi-chassis distributed-trunk) has no Arista
  equivalent — codec collapses to `active` on render.  Aruba's
  `fec` (HP-proprietary Fast EtherChannel) collapses to `static`.

The Aruba kitchen-sink exercises both forms:

```
trunk 23-24 trk1 lacp                   ; -> Port-Channel1, mode active
trunk A3-A4 trk2 trunk                  ; -> Port-Channel2, mode static
```

Plus stub interface stanzas (`interface Trk1 / name "stack-uplink-A"`)
that round-trip to Arista's `interface Port-Channel1 / description
"stack-uplink-A"`.

Disposition: **lossy** (LAG name capitalisation flip handled by
the rename mesh; Aruba-unique `dt-lacp` / `fec` modes collapse on
render; LACP active/passive/static round-trip cleanly).

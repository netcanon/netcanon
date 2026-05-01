# LAGs (Port-Channel / Trk): Arista EOS versus Aruba AOS-S

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
interface Port-Channel20
   description "Bonded trunk to leaf-02"
   switchport mode trunk
   switchport trunk allowed vlan 100,200
!
interface Ethernet4
   description "LAG member 1"
   channel-group 10 mode active
!
interface Ethernet5
   description "LAG member 2"
   channel-group 10 mode active
!
interface Ethernet6
   description "LAG member 3"
   channel-group 20 mode active
```

LACP modes: `active` / `passive` (LACP), `on` (static).

The `Port-Channel<N>` form uses **capital 'C'**.

Arista EOS supports MLAG (multi-chassis LAG) via `mlag <id>`
inside the Port-Channel stanza; this is a separate feature from
the `channel-group` membership and is not modelled in canonical
v1.

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

- `lacp` -> canonical `mode="active"`.
- `trunk` -> canonical `mode="static"` (manual aggregation).
- `fec` -> canonical `mode="static"` (HP legacy).
- `dt-lacp` -> canonical `mode="active"` (multi-chassis stack).

The aggregated logical interface name takes the form `Trk<N>`.

## Cross-vendor mapping

The canonical model is `CanonicalLAG(name, members, mode)`.

Arista -> Aruba specifics:

* `name`: Arista `Port-Channel10` -> Aruba `Trk10`.  Codec
  helper extracts the integer suffix; capital-C drops on render
  to the Aruba `Trk<N>` form.
* `members`: list of port names.  Each Arista member's
  `channel-group N mode active` line gets aggregated by parse
  into a single `CanonicalLAG.members` list; Aruba render
  collapses the list back into a single `trunk <port-list> trk<N>
  lacp` line via the `_collapse_port_list` helper.
* `mode`: `active` / `passive` -> Aruba `lacp`; `on` (static) ->
  Aruba `trunk` (static).  Aruba's `dt-lacp` and `fec` modes are
  Aruba-only and not produced from Arista source.
* MLAG: Arista's `mlag <id>` line on the Port-Channel stanza has
  no Aruba equivalent (AOS-S has VSF stacking but it's a
  different model).  Drops with a banner.

Trunk-mode VLAN attributes (`switchport mode trunk` /
`switchport trunk allowed vlan ...`) on the Port-Channel parent
stanza re-project via `project_switchport_to_vlan` into VLAN-
centric membership lists for Aruba's `tagged <port-list>` form.

The Arista kitchen-sink exercises both routed (`Port-Channel10`
with IP) and switched (`Port-Channel20` with trunk mode) bonded
interfaces — both render to clean Aruba `trunk N-M trkX lacp`
lines plus matching VLAN port-list memberships.

Disposition: **lossy** (LAG name capitalisation flip; MLAG
config drops; LACP active/passive/static round-trip cleanly).

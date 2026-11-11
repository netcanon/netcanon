# Interface naming: MikroTik RouterOS versus Aruba AOS-S

## MikroTik RouterOS

Sources:
- [Ethernet — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/41746442/Ethernet)
- [Bridge — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/47579231/Bridging+and+Switching)

Retrieved: 2026-04-30

RouterOS uses a **flat factory naming** scheme: `ether1`, `ether2`,
… for copper Ethernet; `sfp1` / `sfp-sfpplus1` for SFP / SFP+ cages;
`wlan1` / `wlan2` for wireless radios; `bridge1` for bridges;
`bond1` for bonded interfaces; `vlan10` / `vlan100` for VLAN
sub-interfaces.

Operators routinely **rename** interfaces away from the factory
defaults via `/interface ethernet set [ find default-name=ether1 ]
name="WAN uplink"`.  The `default_name` discriminator on
`CanonicalInterface` carries the factory binding so the RouterOS
codec can emit the `set [ find default-name=X ] name=Y` lookup on
render, even when the operator has renamed the interface.

LAGs use `bond<N>`, bridges use `bridge<N>`.  Loopbacks are
emulated as **empty bridges** (`/interface bridge add name=lo0`
plus `/ip address add address=10.255.0.1/32 interface=lo0`) — no
first-class loopback family.

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Basic Operation Guide for
2930F / 2930M / 3810 / 5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/BOG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

Aruba uses **bare numeric** port identifiers on standalone units
(`interface 1`, `interface 24`) and chassis-letter forms on stacked
or modular chassis (`interface A1`, `interface A4`).

LAGs use `Trk<N>` (`interface Trk1`).  VLAN SVIs are absorbed into
the `vlan <id>` stanza (no separate `interface Vlan<N>` block on
AOS-S — the `absorbs_svi_into_vlan: true` codec class-var captures
this).  Loopbacks are `interface loopback <0-7>`, with a space, each
with addresses given with no mask (Aruba Basic Operation Guide,
"Managing loopback interfaces").

Interfaces carry an operator-friendly `name "..."` attribute that
populates `CanonicalInterface.description` on parse (Aruba's bare
numeric is the wire name; the friendly name is metadata).

## Cross-vendor mapping

RouterOS's flat factory naming has no structural cousin on Aruba —
interface names are rebound by the rename mesh.  Default mapping:

- RouterOS `ether1` … `ether24` -> Aruba `1` … `24`
- RouterOS `sfp-sfpplus1` … `sfp-sfpplus4` -> Aruba `A1` … `A4`
  (SFP+ cages map to chassis-letter uplink ports)
- RouterOS `bond1` -> Aruba `Trk1`
- RouterOS `bridge1` (when used as L2 bridge) -> Aruba (no
  equivalent — Aruba has no bridge primitive; bridges materialise
  as VLAN membership + the configured ports)
- RouterOS `vlan100` (sub-interface) -> Aruba absorbed into
  `vlan 100 / ip address X/N`

The operator-friendly RouterOS name (`/interface ethernet set [ ... ]
name="WAN uplink"`) cannot survive on Aruba — Aruba interface names
are fixed by the hardware layout.  Cross-vendor migration converts
the operator name to an Aruba `name "..."` attribute (the
description field) and replaces the in-band name with the rename-
mesh-chosen Aruba identity.

The `default_name` discriminator (RouterOS factory binding) is
meaningless to Aruba and drops on cross-vendor render — Aruba does
not have factory-default-name semantics.

RouterOS 7's own loopback, `lo`, is AOS-S `interface loopback 0`,
its address written with no mask.  An empty bridge used as a
loopback is a bridge to the parser (its type is `bridge`, and the
classifier reads no port in a name like `lo0`), and AOS-S has no form
for a bridge: the name is left as it is, written `interface lo0`
with its address, and the job is `partial` and lists it, for an
entry in the port map to settle.

### Disposition

| Field | Disposition |
|---|---|
| `interfaces[].name` | lossy (operator name on RouterOS lost; chassis-letter / SFP+ mapping heuristic) |
| `interfaces[].default_name` | not_applicable on Aruba target (Aruba has no factory binding) |
| `interfaces[].description` | good (RouterOS `comment=` <-> Aruba `name "..."`) |
| `interfaces[].interface_type` | lossy (inferred from name shape on both codecs) |
| Loopback | good for RouterOS 7 `lo` -> `loopback 0`; an empty-bridge loopback is left under its name and holds the job (`partial`) |

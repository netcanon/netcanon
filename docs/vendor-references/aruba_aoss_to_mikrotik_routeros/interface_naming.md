# Interface naming: Aruba AOS-S versus MikroTik RouterOS

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Basic Operation Guide for
2930F / 2930M / 3810 / 5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/BOG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

Aruba uses **bare numeric** port identifiers on standalone units
(`interface 1`, `interface 24`) and chassis-letter forms on stacked
or modular chassis (`interface A1`, `interface A4`, `interface 5400-2/A1`).
The codec's `_IFACE_HEADER_RE` recognises the standalone forms but
not all slot/letter combinations on the modular 5400R chassis line.

LAGs use `Trk<N>` (`interface Trk1`, `interface Trk2`).

VLAN SVIs are absorbed into the `vlan <id>` stanza (no separate
`interface Vlan<N>` block on AOS-S — the `absorbs_svi_into_vlan: true`
codec class-var captures this).

There is no first-class **loopback** family on AOS-S.  Operators
emulate loopbacks by creating an empty VLAN with an SVI address.

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
render.

LAGs use `bond<N>` (RouterOS bonding), bridges use `bridge<N>`
(routing-style L3 bridge or VLAN-filtered switching bridge), and
loopbacks are emulated as empty bridges (`/interface bridge add
name=lo0` plus `/ip address add address=10.255.0.1/32
interface=lo0`).  The `interface_type` field on
`CanonicalInterface` is inferred from the name shape on both
codecs.

## Cross-vendor mapping

Aruba's bare-numeric / chassis-letter forms have no structural
cousin on RouterOS — interface names are rebound by the rename
mesh.  Default mapping:

- Aruba `1` … `24` -> RouterOS `ether1` … `ether24`
- Aruba `A1` … `A4` -> RouterOS `sfp-sfpplus1` … `sfp-sfpplus4`
  (uplink modules typically map to SFP+ ports)
- Aruba `Trk1` -> RouterOS `bond1`
- Aruba VLAN SVI inside `vlan <id>` block -> RouterOS
  `/interface vlan` + `/ip address`

The Aruba operator-friendly free-form `name "user-desk-01"` populates
`CanonicalInterface.description` (NOT `name` — Aruba treats the bare
numeric as the wire name).  RouterOS render emits the description
on `comment=` for the matching `/interface ethernet` line.

The `default_name` discriminator is empty on Aruba parse (Aruba does
not have factory-default-name semantics) — the RouterOS render falls
back to the rename-mesh-chosen interface name and emits a positional
`set` on the assumed default-name.  Operators must verify the port
binding post-migration.

Loopback emulation is **lossy** on the cross-pair: Aruba has no
loopback at all.  Inverse direction (RouterOS source) lifts cleanly
into a synthetic Aruba VLAN SVI via the codec's interface_type
inference, but Aruba-side post-migration fidelity is poor — the
operator must allocate a VLAN id for the loopback by hand.

### Disposition

| Field | Disposition |
|---|---|
| `interfaces[].name` | lossy (rename mesh re-binds; chassis-letter -> SFP+ heuristic) |
| `interfaces[].default_name` | lossy (Aruba has no factory binding; RouterOS render falls back) |
| `interfaces[].description` | good (Aruba `name "..."` <-> RouterOS `comment=`) |
| `interfaces[].interface_type` | lossy (inferred from name shape on both codecs) |
| Loopback first-class | unsupported on Aruba; lossy on cross-pair |

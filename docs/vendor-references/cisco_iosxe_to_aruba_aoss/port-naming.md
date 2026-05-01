# Port naming: Cisco IOS-XE NETCONF source vs Aruba AOS-S target

Source: [openconfig-interfaces YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-interfaces.html)
Retrieved: 2026-05-01

Source: [Cisco IOS XE 17 Interface and Hardware Component Configuration Guide](https://www.cisco.com/c/en/us/td/docs/routers/ios/config/17-x/int-hw/b-int-hw.html)
Retrieved: 2026-05-01

Source: [Aruba ArubaOS-Switch 16.10 Basic Operation Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/BOG/2930F-3810-5400/index.htm)
Retrieved: 2026-05-01

## Cisco -> AOS-S name-shape mapping

Identical to the `cisco_iosxe_cli_to_aruba_aoss` direction (see
`../cisco_iosxe_cli_to_aruba_aoss/port_naming.md` for the in-depth
treatment).  The port-rename mesh is wire-format-agnostic — whether
the Cisco source comes from CLI text or NETCONF XML, the canonical
`intent.interfaces[].name` carries the GigabitEthernet/Tengig/...
shape verbatim.

## Direction-specific observations

OpenConfig source emits `<interface><name>GigabitEthernet1/0/1</name>`
opaquely.  The cisco_iosxe parser stores it on
`CanonicalInterface.name` as-is.  When the aruba_aoss render walks,
the rename mesh (if engaged) maps:

| Cisco shape | AOS-S shape |
|---|---|
| `GigabitEthernet1/0/1` | `1/A1` (stack member) or `1` (single member) |
| `TenGigabitEthernet1/1/1` | `25` (uplink) — operator-curated |
| `Port-channel1` | `Trk1` |
| `Vlan10` | (no AOS-S SVI interface — absorbed into vlan stanza) |
| `Loopback0` | (no AOS-S equivalent — typically dropped) |

Without the rename mesh, the literal `GigabitEthernet1/0/1` flows
through to the AOS-S CLI render, which emits
`interface GigabitEthernet1/0/1` — syntactically rejected by an
AOS-S device (the `_IFACE_HEADER_RE` accepts
`interface <[A-Za-z]*\d+(/\d+)?>` but not the slot/letter/port form).

## Loopback and tunnel handling

OpenConfig carries Loopback / Tunnel as first-class IANA-typed
interfaces.  AOS-S has no analog — Tunnel doesn't exist on AOS-S
campus switches at all, and Loopback is used rarely (chiefly for
OSPF router-id scenarios).  The aruba_aoss render emits whatever
canonical name was carried; if it's `Loopback0`, the resulting
`interface Loopback0 / enable` line is rejected by the AOS-S
device.  This is a deeper canonical-model gap (no notion of
"this interface type doesn't exist on this vendor's hardware") and
not specific to this codec pair.

Disposition: lossy with reason "interface-type compatibility gap"
when loopback / tunnel sources reach AOS-S.

## Disposition

`interfaces[].name`: **good** through the rename mesh; **lossy**
without it (operator hazard with Cisco-shaped names hitting AOS-S
syntax rejection).  Loopback / Tunnel: **lossy** for the type
mismatch.

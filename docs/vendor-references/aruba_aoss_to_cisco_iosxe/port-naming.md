# Port naming: Aruba AOS-S source vs Cisco IOS-XE NETCONF target

Source: [Aruba ArubaOS-Switch 16.10 Basic Operation Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/BOG/2930F-3810-5400/index.htm)
Retrieved: 2026-05-01

Source: [Cisco IOS XE 17 Interface and Hardware Component Configuration Guide](https://www.cisco.com/c/en/us/td/docs/routers/ios/config/17-x/int-hw/b-int-hw.html)
Retrieved: 2026-05-01

Source: [openconfig-interfaces YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-interfaces.html)
Retrieved: 2026-05-01

## Aruba bare-numeric to Cisco GigabitEthernet

Identical to the `aruba_aoss_to_cisco_iosxe_cli` direction (see
`../aruba_aoss_to_cisco_iosxe_cli/port_naming.md` for the in-depth
treatment).  The port-rename mesh is target-codec-agnostic — the
mapping from AOS-S `1` / `A1` / `1/1` to Cisco
`GigabitEthernet1/0/1` happens at the canonical bridge boundary, not
at the wire format.

## Direction-specific note for OpenConfig target

OpenConfig's `openconfig-interfaces` model uses opaque interface
names as the list key, just like the CLI form.  The cisco_iosxe
render emits `<interface><name>GigabitEthernet1/0/1</name>...`
verbatim — there is no IANA-form normalisation step on the wire.

If the operator does not engage the rename mesh, the AOS-S bare
numeric port names (e.g. `1`, `A2`, `Trk1`) flow through to the
`<interface><name>...` text on the wire.  A real Cisco device
receiving such NETCONF would reject the edit with an error
("interface 1 not found") because Catalyst devices expect
`GigabitEthernet1/0/1`-form names.  This is the same operator
hazard as the CLI direction, just expressed through a different
wire format.

## SVI naming

AOS-S has no separate SVI interface — `interface VlanN` does not
exist as a stanza.  L3 state lives inside the VLAN stanza
(`absorbs_svi_into_vlan: true`).  When the cisco_iosxe render walks
`intent.interfaces`, it emits whatever the AOS-S parser put there.
The aruba_aoss parser DOES synthesise a dummy SVI in
`CanonicalInterface` records when a VLAN has IP addressing — but
the render-side wire-up gap means the target NETCONF still won't
emit a `<vlans>` declaration because the cisco_iosxe codec
ignores `intent.vlans`.

## Disposition

`interfaces[].name`: **good** through the rename mesh; **lossy**
without it (operator hazard with bare-numeric names hitting Cisco
device-side rejection).

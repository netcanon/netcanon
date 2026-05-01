# arista_eos → juniper_junos — vendor reference index

Curated documentation cache backing
`tests/fixtures/cross_vendor_expectations/arista_eos__juniper_junos.yaml`.

## Topics

| File | Topic | Citation ids |
|---|---|---|
| `vtep-source-interface.md` | VTEP source interface (Loopback0 ↔ lo0.0) | `arista-vxlan-cg`, `junos-vtep-source-iface` |
| `vlan-to-vni-mapping.md` | VLAN-to-VNI binding (`vxlan vlan N vni X` ↔ `set vlans NAME vxlan vni X`) | `arista-vxlan-cg`, `junos-evpn-irb-example` |
| `mac-vrf-and-l2vpn-evpn.md` | MAC-VRF + EVPN BGP address-family | `arista-evpn-cg`, `junos-evpn-irb-example` |
| `ipv6-address-forms.md` | IPv6 address syntax + link-local discrimination | `arista-iface-cg`, `junos-iface-fundamentals`, `junos-family-inet6` |
| `vlan-name-constraints.md` | VLAN name allowed-character / length constraints | `arista-vlan-cg`, `junos-vlans-statement` |
| `local-user-hash-formats.md` | Local-user hashed password storage (`$1$` / `$5$` / `$6$`) | `arista-user-security`, `junos-password-cli`, `junos-kb-password-format` |
| `port-naming-convention.md` | Physical + logical interface naming (Ethernet1 / ge-0/0/0 etc) | `arista-ethernet-ports`, `junos-iface-naming` |
| `vrf-and-l3-vni.md` | VRF / routing-instance + L3 VNI for EVPN Type-5 IRB | `arista-evpn-cg`, `junos-evpn-irb-example` |

## Re-fetch notes

- Juniper's PDF interop guide (`evpn-vxlan-interoperability-arista-eos-junos-os.pdf`)
  was binary-encoded in the form WebFetch surfaces and could not be
  curated directly; the Arista- and Junos-specific pages above carry
  the same per-vendor primitives that the PDF cross-references.
  Future contributors with the PDF in hand can extract additional
  side-by-side worked examples.

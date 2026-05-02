# Interface canonical-core fields — OpenConfig NETCONF source to Arista EOS target

Source: [openconfig-interfaces YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-interfaces.html)
Retrieved: 2026-05-01

Source: [openconfig-if-ip YANG schema docs (IPv4 / IPv6 augment)](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-if-ip.html)
Retrieved: 2026-05-01

Source: [Arista EOS Interface Configuration (4.35.2F)](https://www.arista.com/en/um-eos/eos-interface-configuration)
Retrieved: 2026-05-01

Source: [Arista EOS Ethernet Ports (4.36.0F)](https://www.arista.com/en/um-eos/eos-ethernet-ports)
Retrieved: 2026-05-01

## Field-by-field disposition

The interface subtree is the only canonical surface where the
cisco_iosxe NETCONF source actually populates data.  Arista EOS as
the render target is `certified`-grade, so the interface fields the
source provides round-trip cleanly with the Arista render.

| Canonical field | NETCONF parse | Arista render | Disposition |
|---|---|---|---|
| `interfaces[].name` | from `<interface><name>` text | emitted as `interface <name>` after rename mesh | lossy (rename direction Cisco -> Arista loses speed token + Port-channel capitalisation flip) |
| `interfaces[].description` | from `<config><description>` | emitted as `description "<text>"` | good |
| `interfaces[].enabled` | from `<config><enabled>` (strict YANG bool) | emitted as `shutdown` / `no shutdown` | good |
| `interfaces[].interface_type` | from `<config><type>` (IANA ident) | inferred on render from name prefix; canonical `interface_type` is informational | lossy (type informational on Arista; inference asymmetry) |
| `interfaces[].mtu` | parsed into intermediate dict, NOT carried to canonical | n/a (canonical never receives) | not_applicable (parse-side bridge gap) |
| `interfaces[].ipv4_addresses` | from `subinterface[index=0]/ipv4/addresses/address` | emitted as `ip address X/N` (CIDR form) | good (with secondary-address surface caveat) |
| `interfaces[].ipv6_addresses` | from `subinterface[index=0]/ipv6/addresses/address`, scope hard-coded global | emitted as `ipv6 address X/N` | lossy (link-local scope discriminator dropped before reaching canonical) |
| `interfaces[].switchport_mode` | not parsed (codec walks `<interfaces>` only) | n/a (canonical never receives) | not_applicable |
| `interfaces[].access_vlan` | not parsed | n/a | not_applicable |
| `interfaces[].trunk_allowed_vlans` | not parsed | n/a | not_applicable |
| `interfaces[].trunk_native_vlan` | not parsed | n/a | not_applicable |
| `interfaces[].voice_vlan` | not parsed | n/a | not_applicable |
| `interfaces[].lag_member_of` | not parsed (`openconfig-if-aggregate` augment ignored) | n/a | not_applicable |
| `interfaces[].dhcp_client` | not parsed | n/a | not_applicable |
| `interfaces[].vrf` | not parsed (`<network-instances>` not walked) | n/a | not_applicable |

## Sub-interface flattening

The cisco_iosxe parser walks every `<subinterface>` under each
`<interface>` and flattens the addresses up onto the parent
`CanonicalInterface`.  For example, a Cisco source with a
`GigabitEthernet0/0/3` parent + dot1q sub-interface at index 100:

```xml
<interface>
  <name>GigabitEthernet0/0/3</name>
  <subinterfaces>
    <subinterface><index>0</index><ipv4>...172.16.0.1/30...</ipv4></subinterface>
    <subinterface><index>100</index><ipv4>...172.16.100.1/24...</ipv4></subinterface>
  </subinterfaces>
</interface>
```

Both addresses end up on the canonical
`CanonicalInterface(name="GigabitEthernet0/0/3").ipv4_addresses`
list.  The dot1q tag (encoded in the OpenConfig sub-interface
`vlan/match` augment) is NOT preserved.  The Arista render emits
both addresses on a single bare interface without dot1q encapsulation
— operationally incorrect for trunked sub-interfaces.  This is a
canonical-model gap that pre-exists this codec pair (no
sub-interface-aware canonical model today).

## Interface naming and speed-hint loss

Cisco encodes speed in interface names: `GigabitEthernet0/0/0`,
`TenGigabitEthernet1/0/49`, `HundredGigE1/0/49`.  Arista uses a
flat-numbered Ethernet form regardless of speed: `Ethernet1`,
`Ethernet48`, `Ethernet49/1`.  This is **the better direction** for
the speed hint: the source name carries the speed token, and the
rename mesh can map `GigabitEthernet1/0/24` to `Ethernet24` (or
similar based on operator overrides) without losing information —
the speed token is just dropped on the way to a name shape that
doesn't have one.

Port-channel naming carries the documented capitalisation flip:
Cisco source `Port-channel<N>` (lower-case c) -> Arista target
`Port-Channel<N>` (capital C).  Codec render handles this; rename
mesh canonicalises if cross-pane overrides are configured.

## IPv6 link-local

The cisco_iosxe codec's `_iface_dict_to_canonical()` body hard-codes
`scope="global"` on every parsed IPv6 address.  Even if the source
XML carried a draft `address-type` augment indicating link-local,
the canonical record receives `scope="global"`.  The Arista target
render emits `ipv6 address X/N` without the `link-local` keyword
regardless.

For a `fe80::/10` address, the Arista output is operationally
ambiguous — EOS treats `ipv6 address fe80::1/64` (without
`link-local`) as a global address declaration on a link-local
prefix, which it then rejects on commit.  Operators see a
configuration-apply failure on the target device.

This is upstream of the codec layer (canonical-model gap) but
manifests on Arista EOS specifically because EOS is strict about
the keyword.  Disposition: lossy with reason citing the canonical-
model + parse-side scope-discrimination gap.

## MTU

The cisco_iosxe parser DOES read `<config><mtu>` into its
intermediate parsed dict (see `_parse_config()`) but the canonical
bridge `_iface_dict_to_canonical()` does NOT copy `mtu` onto
`CanonicalInterface.mtu`.  Result: `intent.interfaces[].mtu` is
always None on this direction; the Arista render never emits
`mtu N`.

This is a doubly-deferred gap: even with the bridge wired, the
codec's matrix declares `/interfaces/interface/config/mtu` as
`lossy` because OpenConfig's single MTU leaf collapses the link-MTU
/ IP-MTU / IPv6-MTU / MPLS-MTU distinction the CLI carries
separately.

## Disposition summary

* good: description, enabled, ipv4_addresses
* lossy: name (rename + speed token shed), interface_type
  (inference asymmetry), ipv6_addresses (link-local scope dropped
  upstream)
* not_applicable: mtu, switchport_mode, access_vlan,
  trunk_allowed_vlans, trunk_native_vlan, voice_vlan,
  lag_member_of, dhcp_client, vrf

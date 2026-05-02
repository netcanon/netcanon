# Interface canonical-core fields — Arista EOS source to OpenConfig NETCONF target

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
cisco_iosxe NETCONF target codec actually emits XML output, so this
is where the dispositions are highest-confidence.

| Canonical field | Arista parse | NETCONF render | Disposition |
|---|---|---|---|
| `interfaces[].name` | parsed verbatim from `interface <name>` stanza | emitted as `<name>` text after port-rename mesh | lossy (rename + speed-hint) |
| `interfaces[].description` | parsed from `description "<text>"` | emitted as `<description>` | good |
| `interfaces[].enabled` | parsed from `shutdown` / `no shutdown` (default enabled) | emitted as YANG bool `<enabled>true/false</enabled>` | good |
| `interfaces[].interface_type` | inferred from name prefix (`Ethernet*` -> ethernetCsmacd, `Loopback*` -> softwareLoopback, `Port-Channel*` -> ieee8023adLag, `Vlan*` -> l2vlan, `Vxlan*` -> other) | emitted as `<config><type>` IANA ident | lossy (Arista names carry no speed token) |
| `interfaces[].mtu` | parsed from `mtu N` | NOT emitted (codec render drops the leaf even though parse populates) | lossy (render-side gap; matrix declares lossy) |
| `interfaces[].ipv4_addresses` | parsed from `ip address X/N` (CIDR form on bare interface and SVI) | emitted as `subinterface[index=0]/ipv4/addresses/address` | good |
| `interfaces[].ipv6_addresses` | parsed from `ipv6 address X/N` and `ipv6 address X/N link-local` | emitted as `subinterface[index=0]/ipv6/addresses/address` | lossy (link-local scope discriminator dropped) |
| `interfaces[].switchport_mode` | parsed from `switchport mode {access\|trunk}` and `no switchport` | NOT emitted (render-side `switched-vlan` augment gap) | unsupported |
| `interfaces[].access_vlan` | parsed from `switchport access vlan N` | NOT emitted | unsupported |
| `interfaces[].trunk_allowed_vlans` | parsed from `switchport trunk allowed vlan N,M,...` | NOT emitted | unsupported |
| `interfaces[].trunk_native_vlan` | parsed from `switchport trunk native vlan N` | NOT emitted | unsupported |
| `interfaces[].voice_vlan` | not parsed today (codec gap) | NOT emitted | unsupported |
| `interfaces[].lag_member_of` | parsed from `channel-group N mode <m>` (yields `Port-Channel<N>`) | NOT emitted (`openconfig-if-aggregate` augment gap) | unsupported |
| `interfaces[].dhcp_client` | not parsed today (Arista has `ip address dhcp` but parser doesn't extract) | NOT emitted | unsupported |
| `interfaces[].vrf` | parsed from `vrf <name>` interface sub-command | NOT emitted (no `<network-instances>` walk) | unsupported |

## Interface naming and speed-hint loss

Arista EOS uses a flat-numbered Ethernet form regardless of speed:
`Ethernet1`, `Ethernet48`, `Ethernet49/1` (breakout sub-port).  Cisco
encodes speed in the name: `GigabitEthernet0/0/0`,
`TenGigabitEthernet1/0/49`, `HundredGigE1/0/49`, etc.

Arista source -> Cisco render direction: the source name carries no
speed token, so the rename mesh defaults to `GigabitEthernet`.  An
operator running 25/100G fabrics on Arista will see less-specific
names on the OpenConfig output.  The interface_type IANA ident is
the same (`ethernetCsmacd` for all bare Ethernet ports), so the
NETCONF wire format itself doesn't lose information — the name
string is the only place speed is recoverable.

Port-channel naming flips capitalisation: Arista `Port-Channel<N>`
(capital C) -> Cisco `Port-channel<N>` (lower-case c).  The rename
mesh canonicalises this on cross-pane overrides; on default the
canonical name carries whatever the source produced.

## IPv6 link-local

Arista EOS source distinguishes link-local explicitly:

```
interface Ethernet1
   ipv6 address 2001:db8::1/64
   ipv6 address fe80::1 link-local
```

The Arista codec parses both forms and populates
`CanonicalIPv6Address.scope = "link-local"` for the second.  The
cisco_iosxe codec hard-codes `scope="global"` on every parsed IPv6
address (see `_iface_dict_to_canonical`); the render side emits the
address verbatim regardless of scope but provides no
`link-local`-style discriminator in the OpenConfig wire format.

Result: a `fe80::/10` address declared by Arista as `link-local`
emits in the OpenConfig XML as a normal address, and a downstream
OpenConfig consumer receives no `link-local` flag — the address is
indistinguishable from an unintentionally-routable global one.  This
is doubly upstream of the codec: the OpenConfig `openconfig-if-ip`
model has `address-type` augmentation only on draft modules, not
universally deployed.

Disposition: lossy with reason citing the canonical-model + render
gap.

## MTU

Arista parses `mtu 9214` into `CanonicalInterface.mtu = 9214`.  The
cisco_iosxe codec's `_render_canonical()` body does not emit
`<config><mtu>` — the render path simply skips the leaf.  The
matrix already declares `/interfaces/interface/config/mtu` as
`lossy` (because OpenConfig's single MTU leaf collapses the
link-MTU / IP-MTU / IPv6-MTU / MPLS-MTU distinction the CLI carries
separately).  In practice on this codec pair the loss is total
rather than per-form: the leaf is simply absent in the output XML.

## Disposition summary

* good: name (within rename mesh), description, enabled,
  ipv4_addresses
* lossy: name (cross-vendor speed hint), interface_type (speed
  inference), ipv6_addresses (link-local scope), mtu (render-side
  gap)
* unsupported: switchport_mode, access_vlan, trunk_allowed_vlans,
  trunk_native_vlan, voice_vlan, lag_member_of, dhcp_client, vrf

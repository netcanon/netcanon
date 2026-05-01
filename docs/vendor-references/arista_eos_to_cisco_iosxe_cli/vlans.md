# VLAN configuration: Arista EOS versus Cisco IOS-XE

## Arista EOS

Source: [EOS 4.36.0F — Virtual LANs (VLANs)](https://www.arista.com/en/um-eos/eos-virtual-lans-vlans)
Retrieved: 2026-04-30

VLAN definition syntax (global config):

```
switch(config)# vlan 100
switch(config-vlan-100)# name engineering
switch(config-vlan-100)# exit
```

VLAN ID range 1-4094.  The `name` keyword takes up to 32 characters.

## Cisco IOS-XE

Source: [Cisco IOS XE 17.14 VLAN Configuration Guide — Configuring VLANs (Catalyst 9400)](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9400/software/release/17-14/configuration_guide/vlan/b_1714_vlan_9400_cg/configuring_vlans.html)
Retrieved: 2026-04-30

VLAN definition syntax (global config):

```
Switch(config)# vlan 100
Switch(config-vlan)# name engineering
Switch(config-vlan)# state active
Switch(config-vlan)# exit
```

Same range and same character limit on `name`.  `state active`
defaults are implicit; not relevant to the cross-vendor surface.

## Cross-vendor mapping

Grammar is identical for the cross-vendor-stable surface
(`CanonicalVlan.id`, `CanonicalVlan.name`, `CanonicalVlan.description`).
Both codecs round-trip a vlan + name with no transformation.

VLAN-state, MTU-per-vlan, and private-vlan extensions are out of
canonical scope on both sides.

Disposition: **good**.

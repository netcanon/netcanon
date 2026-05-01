# VLAN configuration: Cisco IOS-XE versus Arista EOS

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

VLAN ID range 1-4094 (1 reserved as default; 1002-1005 historically
reserved for Token Ring / FDDI on legacy IOS).  Names truncated to 32
characters.

## Arista EOS

Source: [EOS 4.36.0F — Virtual LANs (VLANs)](https://www.arista.com/en/um-eos/eos-virtual-lans-vlans)
Retrieved: 2026-04-30

VLAN definition syntax (global config):

```
switch(config)# vlan 100
switch(config-vlan-100)# name engineering
switch(config-vlan-100)# exit
```

Arista documents: "The **name** command configures the VLAN name.
The name can have up to 32 characters."

## Cross-vendor mapping

The grammar is identical for the cross-vendor-stable surface
(`CanonicalVlan.id`, `CanonicalVlan.name`, `CanonicalVlan.description`).
Both codecs round-trip a vlan + name with no transformation.

VLAN-state, MTU-per-vlan, and private-vlan extensions are out of
canonical scope on both sides.

Disposition: **good**.

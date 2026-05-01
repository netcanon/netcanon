# Switchport mode: Arista EOS versus Cisco IOS-XE

## Arista EOS

Source: [EOS 4.36.0F — Virtual LANs (VLANs)](https://www.arista.com/en/um-eos/eos-virtual-lans-vlans)
Retrieved: 2026-04-30

Access port:

```
switch(config)# interface ethernet 4
switch(config-if-Et4)# switchport mode access
switch(config-if-Et4)# switchport access vlan 10
```

Trunk port (verbatim example from the EOS manual):

```
switch(config-if-Et4)# switchport trunk allowed vlan 10-13,20,210-213,220
switch(config-if-Et4)# switchport mode trunk
switch(config-if-Et4)# switchport trunk native vlan 99
```

EOS documents five switching modes: `access`, `trunk`, `dot1q-tunnel`,
`tap`, `tool`.  The first two are the cross-vendor surface; the latter
three are EOS-specific (DANZ tap aggregation).

## Cisco IOS-XE

Source: [Cisco IOS XE 17.14 VLAN Trunks Configuration Guide (Catalyst 9400)](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9400/software/release/17-14/configuration_guide/vlan/b_1714_vlan_9400_cg/configuring_vlan_trunks.html)
Retrieved: 2026-04-30

Access port:

```
Switch(config)# interface GigabitEthernet1/0/10
Switch(config-if)# switchport mode access
Switch(config-if)# switchport access vlan 10
```

Trunk port:

```
Switch(config-if)# switchport mode trunk
Switch(config-if)# switchport trunk allowed vlan 10,20,30
Switch(config-if)# switchport trunk native vlan 99
```

Cisco's older IOS platforms required `switchport trunk encapsulation
dot1q`; Catalyst 9000 IOS-XE accepts dot1q implicitly.

## Cross-vendor mapping

The keyword grammar is byte-identical: same command tokens, same VLAN
list syntax (range with `-`, comma-separated lists), same native-VLAN
keyword.

Round-trips lossless on:
- `CanonicalInterface.switchport_mode` ("access" / "trunk")
- `CanonicalInterface.access_vlan`
- `CanonicalInterface.trunk_allowed_vlans`
- `CanonicalInterface.trunk_native_vlan`

Arista's `switchport trunk allowed vlan add 100` incremental form
parses to the same canonical list as Cisco's `switchport trunk
allowed vlan add 100` — both codecs flatten into a single allowed-list
in the canonical tree.

EOS-only modes (`dot1q-tunnel`, `tap`, `tool`) are out of canonical
scope.  Cisco's `switchport voice vlan` round-trips via
`CanonicalInterface.voice_vlan`.

Disposition: **good**.

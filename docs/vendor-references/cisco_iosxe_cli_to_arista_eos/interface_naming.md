# Interface naming: Cisco IOS-XE versus Arista EOS

## Cisco IOS-XE

Source: [Cisco IOS Interface and Hardware Component Command Reference (IOS XE Gibraltar 16.10.1)](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/interface/command/ir-cr-book/ir-s7.html)

Cisco encodes speed and slot/sub-slot/port in the interface name:

```
GigabitEthernet0/0/0
GigabitEthernet1/0/24
TenGigabitEthernet1/0/49
TwentyFiveGigE1/0/49
FortyGigabitEthernet1/0/53
HundredGigE1/0/49
FastEthernet0/0
```

Loopbacks use a flat ID: `Loopback0`.  SVIs: `Vlan100`.  Tunnels:
`Tunnel1`.  Port-channels: `Port-channel10` (lower-case `c`).

Operators routinely abbreviate (`int gi1/0/1`); the running-config
always emits the canonical form.

## Arista EOS

Source: [EOS 4.36.0F — Data Transfer (Ethernet ports)](https://www.arista.com/en/um-eos/eos-data-transfer)
Retrieved: 2026-04-30

Arista uses a single flat-numbered Ethernet form regardless of speed:

```
Ethernet1
Ethernet48
Ethernet49/1   (breakout sub-port)
```

Loopbacks: `Loopback0`.  SVIs: `Vlan100`.  Port-channels: `Port-Channel10`
(capital `C` — a documented difference from Cisco).  Management:
`Management1`.

EOS does not encode speed in the name; the same `Ethernet49` slot
might run at 10G, 25G, 40G, or 100G depending on optics + speed
config.  This is the load-bearing semantic difference: a Cisco
`GigabitEthernet1/0/49` carries a speed hint that Arista's `Ethernet49`
does not.

## Cross-vendor mapping

NetConfig handles this via the existing port-name rename mesh
(`netconfig/migration/codecs/cisco_iosxe_cli/port_names.py` and the
sibling `arista_eos/port_names.py`).  The canonical interface stores
the vendor-native name as-is per the
`CanonicalInterface.name` schema; the rename pane is the user-facing
remediation surface for cross-vendor migrations.

Speed-hint loss is documented in the codec capability matrices.
Cisco IOS-XE `_CAPS.lossy` lists
`/interfaces/interface/config/type` with rationale "CLI parser infers
interface type from the name prefix".  Arista EOS `_CAPS.lossy` lists
the same xpath with rationale "EOS interface names don't encode
speed; the parser defaults to 'gig' speed-hint for all Ethernet<N>
ports."

Disposition: **lossy** (interface_type / speed-hint round-trips imperfectly).

# Interface naming: Arista EOS versus Cisco IOS-XE

## Arista EOS

Source: [EOS 4.36.0F — Data Transfer (Ethernet ports)](https://www.arista.com/en/um-eos/eos-data-transfer)
Retrieved: 2026-04-30

Arista uses a single flat-numbered Ethernet form regardless of speed:

```
Ethernet1
Ethernet48
Ethernet49/1   (breakout sub-port)
```

Loopbacks: `Loopback0`.  SVIs: `Vlan100`.  Port-channels:
`Port-Channel10` (capital `C` — a documented difference from Cisco).
Management: `Management1`.

EOS does not encode speed in the name; the same `Ethernet49` slot
might run at 10G, 25G, 40G, or 100G depending on optics + speed
config.

## Cisco IOS-XE

Source: [Cisco IOS Interface and Hardware Component Command Reference (IOS XE Gibraltar 16.10.1)](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/interface/command/ir-cr-book/ir-s7.html)
Retrieved: 2026-04-30

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

Loopbacks: `Loopback0`.  SVIs: `Vlan100`.  Tunnels: `Tunnel1`.
Port-channels: `Port-channel10` (lower-case `c`).

## Cross-vendor mapping

Netcanon handles this via the existing port-name rename mesh
(`netconfig/migration/codecs/arista_eos/port_names.py` and the sibling
`cisco_iosxe_cli/port_names.py`).  The canonical interface stores the
vendor-native name as-is per the `CanonicalInterface.name` schema; the
rename pane is the user-facing remediation surface for cross-vendor
migrations.

The Arista→Cisco direction is the **harder** direction for the speed
hint: Arista sources don't carry a speed token in the interface name,
so the Cisco render path must pick a default prefix.  The codec
defaults to `GigabitEthernet` (the most common match) but operators
running 10G+ fabrics will see less-specific prefixes than the original
Arista hardware actually had.  Documented in both codecs' capability
matrices as `LossyPath` on `/interfaces/interface/config/type`.

Port-channel naming carries the documented capitalisation flip:
Arista's `Port-Channel<N>` re-emits as Cisco's `Port-channel<N>`
(lower-case `c`).  Codec render handles this; rename mesh
canonicalises if cross-pane overrides are configured.

Disposition: **lossy** (interface_type / speed-hint round-trips
imperfectly; PortChannel capitalisation flips).

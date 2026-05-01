# Interface naming: Cisco IOS-XE versus FortiGate FortiOS

## Cisco IOS-XE

Source: [Cisco IOS XE Interface and Hardware Component Configuration Guide](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/interface/command/ir-cr-book/ir-s7.html).

Cisco encodes interface speed in the name prefix:

```
interface GigabitEthernet0/0/0
interface TenGigabitEthernet0/0/0
interface FortyGigE0/0/0
interface HundredGigE0/0/0
interface FastEthernet0/0
interface Loopback0
interface Vlan100
interface Port-channel10
interface Tunnel0
```

The numeric portion follows a `<chassis>/<slot>/<port>` or
`<slot>/<port>` form depending on platform.

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide — Networking / Interfaces](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/954635/interface-settings)
Retrieved: 2026-04-30

FortiOS uses opaque port labels — the platform stamps factory-default
port names that are speed-agnostic on the wire:

```
config system interface
    edit "port1"          # factory-default; physical
    edit "port2"
    edit "wan1"           # platform-specific (FGT-60E carries wan1/wan2)
    edit "internal"       # default LAN switch on consumer-grade
    edit "mgmt"           # out-of-band management
    edit "VL_100"         # operator-named VLAN child interface
    edit "LAG_INTERNAL"   # operator-named aggregate
    edit "ssl.root"       # SSL-VPN tunnel virtual interface
    edit "loopback1"      # loopback
end
```

FortiOS does not encode speed in the port name; the port type is
inferred from the platform model (FGT-60E, FGT-100D, etc.) and from
`set type {physical | vlan | aggregate | tunnel | ...}` settings on
the edit block.

VLAN child interfaces are operator-named; convention is `VL_<id>` or
`<role>_<id>` but no FortiOS-internal naming requirement enforces it.

LAG aggregates are likewise operator-named; convention is
`LAG_<role>` or `agg<n>` but again no enforced grammar.

## Cross-vendor mapping

The canonical surface is `CanonicalInterface.name` (opaque vendor-
native string) and `CanonicalInterface.interface_type` (IANA ifType
inference).

The codec's `classify_port_name` / `format_port_identity` bridge
methods (see `port_names.py`) handle the rename mesh: Cisco
`GigabitEthernet0/0/0` lands as a generic Ethernet identity that
FortiGate emits as the next available `port<N>` slot, or as the
operator-overridden name from the per-pane port-rename surface.

Speed-prefix loss: Cisco `TenGigabitEthernet` / `HundredGigE` carry
speed information that FortiGate's flat `port1` / `port2` namespace
discards.  This is the same lossy-on-cross-vendor pattern that the
Arista pair surfaces (Arista `Ethernet1` is also speed-agnostic).
The canonical model preserves the source name verbatim; the rename
mesh applies operator-curated mappings on render.

LAG / VLAN names are operator-controlled on FortiGate, so cross-
vendor mappings (`Port-channel10` -> `LAG_10`, `Vlan100` -> `VL_100`)
are convention rather than vendor-mandated.  The codec preserves
whatever the source emitted.

Disposition: **lossy**.  Reason: speed-prefix encoding lost on Cisco
-> FortiGate; FortiGate's flat `port<N>` namespace cannot
reconstruct `TenGigabitEthernet` / `HundredGigE` semantics on the
reverse path.

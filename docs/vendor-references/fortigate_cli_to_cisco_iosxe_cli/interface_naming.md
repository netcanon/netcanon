# Interface naming: FortiGate FortiOS versus Cisco IOS-XE

Reverse-direction sibling of
[`../cisco_iosxe_cli_to_fortigate_cli/interface_naming.md`](../cisco_iosxe_cli_to_fortigate_cli/interface_naming.md).
Source URLs unchanged.

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide — Interface settings](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/954635/interface-settings).
Retrieved: 2026-04-30

FortiOS uses opaque speed-agnostic port names — factory-defaults
like `port1` / `port2` on enterprise SKUs, `wan1` / `wan2` /
`internal` on consumer SKUs.  VLAN child interfaces and aggregate
interfaces are operator-named.

```
config system interface
    edit "port1"
    edit "port2"
    edit "wan1"
    edit "internal"
    edit "VL_100"
    edit "LAG_INTERNAL"
    edit "loopback1"
end
```

## Cisco IOS-XE

Source: [Cisco IOS XE Interface and Hardware Component Configuration Guide](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/interface/command/ir-cr-book/ir-s7.html).

Cisco encodes speed in the name prefix:

```
interface GigabitEthernet0/0/0
interface TenGigabitEthernet0/0/0
interface FortyGigE0/0/0
interface HundredGigE0/0/0
interface Loopback0
interface Vlan100
interface Port-channel10
```

## Cross-vendor mapping (FortiGate -> Cisco)

Canonical surface: `CanonicalInterface.name` (opaque) +
`CanonicalInterface.interface_type` (IANA ifType inference).

The codec's `classify_port_name` / `format_port_identity` bridge
methods (see `port_names.py`) handle the rename mesh.  FortiGate
`port1` -> generic Ethernet identity -> Cisco emits as the next
available `GigabitEthernet0/0/N` slot, or as the operator-overridden
name from the per-pane port-rename surface.

The reverse-direction observation: where Cisco -> FortiGate **lost**
speed information (10G/40G/100G tokens absent on FortiGate's
namespace), FortiGate -> Cisco **must invent** speed information
the source never had.  The Cisco render defaults to
`GigabitEthernet` for all FortiGate physical ports unless the
operator overrides via the per-pane port-rename surface.  This
will misrepresent 10G/100G FortiGate ports as 1G on Cisco emit.

Loopback / VLAN / LAG names also need synthesis:

- FortiGate `loopback1` -> Cisco `Loopback1` (case adjustment).
- FortiGate `VL_100` (VLAN child of parent `internal`) -> Cisco
  `Vlan100` (SVI on the L2 VLAN).
- FortiGate `LAG_INTERNAL` -> Cisco `Port-channel<N>` where `<N>`
  is operator-curated (canonical model has no integer LAG ID; the
  Cisco render synthesises one).

Disposition: **lossy**.  Reason: FortiGate's flat namespace forces
the Cisco render to invent speed prefixes (defaulting to
`GigabitEthernet`) and integer LAG IDs.  Operators rename via the
per-pane port-rename surface for non-default mappings.

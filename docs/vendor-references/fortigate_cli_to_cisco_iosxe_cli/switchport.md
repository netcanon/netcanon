# Switching features: FortiGate FortiOS versus Cisco IOS-XE

Reverse-direction sibling of
[`../cisco_iosxe_cli_to_fortigate_cli/switchport.md`](../cisco_iosxe_cli_to_fortigate_cli/switchport.md).
Source URLs unchanged.

## FortiGate FortiOS CLI

Source: [Fortinet FortiOS Administration Guide — Hardware switch / Virtual switch](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/).
Retrieved: 2026-04-30

FortiGate is an L3 firewall surface.  No `switchport mode {access |
trunk}` keyword.  No `voice vlan`.  No spanning-tree.  Multi-VLAN
trunking is implicit: stack VLAN child interfaces on a parent.

Hardware-switch SKUs (FGT-60E, FGT-100D-LAN-PORTS) carry an internal
switch fabric that is configured via `config system virtual-switch`
or `config system switch-interface` (platform-specific).  Out of
canonical scope.

## Cisco IOS-XE

Source: Cisco IOS XE LAN Switching Configuration Guide.

```
interface GigabitEthernet0/0/1
 switchport mode access
 switchport access vlan 100
 switchport voice vlan 200
 spanning-tree portfast
```

## Cross-vendor mapping (FortiGate -> Cisco)

Canonical surface lives on `CanonicalInterface`:

```
class CanonicalInterface(BaseModel):
    switchport_mode: str | None = None
    access_vlan: int | None = None
    trunk_allowed_vlans: list[int] = Field(default_factory=list)
    trunk_native_vlan: int | None = None
    voice_vlan: int | None = None
```

After FortiGate parse, **all switchport_* fields are empty** — FortiGate
has no L2 surface to populate them from.  Cross-vendor migration
on FortiGate -> Cisco therefore emits routed-port (no `switchport`)
configuration on every interface, even where the original FortiGate
parent was carrying multiple VLAN children that Cisco would express
as a trunk port.

This is the inverse asymmetry of the forward direction:

- **Forward (Cisco -> FortiGate)**: switchport intent loses its
  target on FortiGate (no L2 model).
- **Reverse (FortiGate -> Cisco)**: switchport intent never made
  it to the canonical tree (FortiGate parse never populates
  switchport_*); Cisco render emits routed ports.

In practice, multi-VLAN-child FortiGate interfaces should manually
become Cisco trunk ports post-migration.  The operator-curated step
is mandatory.

Disposition for the entire switching surface: **unsupported**.
Reason: FortiGate has no L2 switching CLI primitives that the
canonical model would need to populate; cross-vendor migration to
Cisco emits L3-routed-port-only configurations regardless of how
the FortiGate parent was being used.

Spanning-tree is also `unsupported` on the FortiGate side — there
is no canonical field for STP and no FortiGate CLI to parse from.

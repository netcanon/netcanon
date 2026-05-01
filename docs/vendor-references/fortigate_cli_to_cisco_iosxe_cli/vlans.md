# VLAN configuration: FortiGate FortiOS versus Cisco IOS-XE

Reverse-direction sibling of
[`../cisco_iosxe_cli_to_fortigate_cli/vlans.md`](../cisco_iosxe_cli_to_fortigate_cli/vlans.md).
Source URLs unchanged.

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide — VLAN sub-interface](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/954635/interface-settings).
Source: [Fortinet FortiOS Cookbook — Configuring VLANs](https://docs.fortinet.com/document/fortigate/7.4.0/cookbook/).
Retrieved: 2026-04-30

```
config system interface
    edit "VL_100"
        set type vlan
        set vlanid 100
        set interface "internal"
        set ip 10.0.100.1 255.255.255.0
        set alias "Data"
    next
end
```

VLAN child interfaces hang off a parent (physical or aggregate).
Some real configs omit `set type vlan`, leaving `vlanid` + `interface`
as the only VLAN signal — the FortiGate codec accepts both forms
(see `parse._apply_system_interface` heuristic).

## Cisco IOS-XE

Source: Cisco IOS XE LAN Switching Configuration Guide — VLAN
configuration.

```
vlan 100
 name DATA
!
interface Vlan100
 description "Data SVI"
 ip address 10.0.100.1 255.255.255.0
!
interface GigabitEthernet0/0/1
 switchport mode access
 switchport access vlan 100
```

## Cross-vendor mapping (FortiGate -> Cisco)

Canonical surface (same as forward direction):

```
class CanonicalVlan(BaseModel):
    id: int
    name: str = ""
    description: str = ""
    tagged_ports: list[str] = Field(default_factory=list)
    untagged_ports: list[str] = Field(default_factory=list)
    ipv4_addresses: list[CanonicalIPv4Address]
```

- **vlans[].id** — `good`.  Direct preservation.
- **vlans[].name** — `lossy`.  FortiGate uses the interface edit ID
  as the canonical VLAN name (`VL_100`); Cisco renders `vlan 100 /
  name VL_100`.  The mapping is mechanical but the operator-
  expected Cisco-side name (`DATA`) is lost — the FortiOS-side
  alias (`set alias "Data"`) lives on the interface description,
  not the VLAN name, so cross-vendor migration would need an
  operator-curated re-mapping for clean Cisco-side naming.
- **vlans[].description** — `lossy`.  FortiGate has no VLAN-level
  description; the canonical field is always empty after FortiGate
  parse.  Cisco render emits no `description` line under the
  `vlan` stanza.
- **vlans[].tagged_ports / untagged_ports** — `lossy`.  The
  canonical VLAN-centric port list is empty after FortiGate parse
  (FortiGate's child-interface model encodes membership via the
  parent's identity, not as a port list per VLAN).  Cross-vendor
  migration on FortiGate -> Cisco loses the port-membership intent;
  the operator must manually configure `switchport access vlan X`
  on the Cisco target.  This is a model translation gap.
- **vlans[].ipv4_addresses (SVI)** — `good`.  FortiGate's `set ip`
  on the VLAN child interface lands in the canonical SVI list,
  which Cisco emits as `interface Vlan<N> / ip address`.

Disposition for vlans[].id: **good**.

Disposition for vlans[].name and vlans[].description: **lossy**.

Disposition for vlans[].tagged_ports / untagged_ports: **lossy**
(FortiGate's child-interface model carries no canonical port-
list; cross-vendor render emits an empty L2 VLAN on Cisco).

Disposition for vlans[].ipv4_addresses (SVI): **good**.

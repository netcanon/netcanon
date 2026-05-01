# VLAN configuration: Cisco IOS-XE versus FortiGate FortiOS

## Cisco IOS-XE

Source: Cisco IOS XE LAN Switching Configuration Guide — VLAN
configuration.

Cisco models VLANs as **first-class objects** with an associated
optional Switched Virtual Interface (SVI):

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
!
interface GigabitEthernet0/0/2
 switchport mode trunk
 switchport trunk allowed vlan 100,200,300
 switchport trunk native vlan 1
```

Membership is **interface-centric** — each switchport declares which
VLAN(s) it carries.  The codec transposes this into the canonical
VLAN-centric form on parse.

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide — Networking / Interfaces / VLAN sub-interface](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/954635/interface-settings)
Source: [Fortinet FortiOS Cookbook — Configuring VLANs](https://docs.fortinet.com/document/fortigate/7.4.0/cookbook/) — VLAN sub-interface examples.
Retrieved: 2026-04-30

FortiOS models VLANs as **child interfaces** of a physical or
aggregate parent, with no first-class VLAN object:

```
config system interface
    edit "VL_100"
        set type vlan
        set vlanid 100
        set interface "internal"
        set ip 10.0.100.1 255.255.255.0
        set alias "Data"
    next
    edit "VL_200"
        set type vlan
        set vlanid 200
        set interface "LAG_INTERNAL"
        set ip 10.0.200.1 255.255.255.0
    next
end
```

Notable FortiOS specifics:

- **No global `vlan <id>` declaration.**  FortiOS does not have a
  separate VLAN-database concept; the VLAN exists if and only if at
  least one child interface declares `set type vlan / set vlanid <N>`.
- **VLAN name = interface name.**  The interface's edit ID (`VL_100`)
  doubles as the VLAN's display name.  Cisco's `vlan 100 / name DATA`
  has no FortiOS analogue — the FortiGate codec uses the interface
  name as the canonical VLAN name and drops Cisco's separate `name`.
- **No trunk / access dichotomy on FortiGate.**  FortiOS's hardware
  switch is an L3 firewall surface; trunking is implicit (any parent
  interface can carry tagged children).  There is no `switchport
  mode trunk` / `switchport mode access` keyword.  Multi-VLAN trunks
  on a single physical port are expressed by stacking multiple
  child VLAN interfaces on the same parent.
- **No `voice vlan` / `native vlan` model.**  FortiOS has no first-
  class voice-VLAN construct; no per-trunk native-VLAN tag (each
  child interface is independently tagged or untagged via parent
  inheritance).

## Cross-vendor mapping (Cisco -> FortiGate)

Canonical surface:

```
class CanonicalVlan(BaseModel):
    id: int
    name: str = ""
    description: str = ""
    tagged_ports: list[str] = Field(default_factory=list)
    untagged_ports: list[str] = Field(default_factory=list)
    ipv4_addresses: list[CanonicalIPv4Address]   # SVI
```

- **vlans[].id** — `good`.  Both vendors round-trip the integer VLAN
  ID.  FortiGate emits `set vlanid <id>`.
- **vlans[].name** — `lossy`.  Cisco's `vlan 100 / name DATA`
  separate name does not survive on FortiGate where the interface
  edit ID doubles as the name.  The FortiGate render path uses the
  CanonicalVlan name as the interface edit ID; round-trip preserves
  the string but cross-vendor migration of long descriptive names
  may collide with FortiOS's interface-name length cap (15
  characters per FortiOS).
- **vlans[].description** — `lossy`.  FortiOS does not have a
  per-VLAN description field; the closest analogue is the parent
  interface's `set alias "..."` (capped at 25 chars).
- **vlans[].tagged_ports / untagged_ports** — `lossy`.  The Cisco
  switchport model declares VLAN membership on each port; FortiOS
  expresses it as child VLAN interfaces hanging off a parent.  The
  FortiGate codec creates one VLAN-child interface per VLAN with
  `set interface "<parent>"` set to the first untagged or tagged
  port, but cannot represent multi-port VLAN membership without
  spawning multiple child interfaces.  This is a known gap; on
  Cisco -> FortiGate the membership becomes a model translation
  rather than a literal port-list copy.
- **vlans[].ipv4_addresses (SVI)** — `good`.  Cisco's `interface
  Vlan100 / ip address X` maps directly to FortiOS's `set ip` on
  the VL_100 child interface.

Disposition for vlans[].id: **good**.

Disposition for vlans[].name and vlans[].description: **lossy**.

Disposition for vlans[].tagged_ports / untagged_ports: **lossy**
(model translation; literal port-list copy not possible without
multi-child-interface synthesis).

Disposition for vlans[].ipv4_addresses (SVI): **good**.

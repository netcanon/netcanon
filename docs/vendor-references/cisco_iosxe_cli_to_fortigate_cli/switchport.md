# Switching features (switchport modes / spanning-tree): Cisco IOS-XE versus FortiGate FortiOS

## Cisco IOS-XE

Source: Cisco IOS XE LAN Switching Configuration Guide.

Cisco IOS-XE switchports model L2 access / trunk / dynamic
relationships explicitly:

```
interface GigabitEthernet0/0/1
 switchport mode access
 switchport access vlan 100
 switchport voice vlan 200
 spanning-tree portfast
 spanning-tree bpduguard enable
!
interface GigabitEthernet0/0/2
 switchport mode trunk
 switchport trunk allowed vlan 100,200,300
 switchport trunk native vlan 1
```

Spanning-tree is configured globally and per-port:

```
spanning-tree mode rapid-pvst
spanning-tree extend system-id
```

## FortiGate FortiOS CLI

Source: [Fortinet FortiOS Administration Guide — Hardware switch](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/) (FGT consumer-grade SKUs only).
Retrieved: 2026-04-30

FortiOS is an L3 firewall surface with no first-class L2 switching
features:

- **No `switchport mode {access | trunk}` keyword.**  Each port is an
  L3 interface by default; multi-VLAN trunking is expressed by
  stacking VLAN child interfaces on a parent (see `vlans.md`).
- **No `voice vlan`** — FortiOS has no equivalent to Cisco's
  per-port `switchport voice vlan <id>`.  Voice VLAN tagging on
  FortiGate-attached IP phones must be set on the phone itself or
  on an upstream switch.
- **No spanning-tree.**  FortiOS does not run STP / RSTP / MSTP on
  its data plane.  Hardware-switch SKUs (FGT-60E and similar) carry
  an internal switch fabric that runs STP transparently, but it is
  not configurable from CLI.  Enterprise SKUs (FGT-100D+) are
  pure-routed and have no STP at all.
- **Hardware switch / virtual switch.**  Some consumer-grade FGT
  SKUs offer a `config system virtual-switch` mode that bridges
  multiple physical ports into a single L3 interface.  This is the
  closest FortiOS construct to a Cisco access-port group, but it is
  platform-specific and not modelled in the canonical schema.

## Cross-vendor mapping (Cisco -> FortiGate)

Canonical surface lives on `CanonicalInterface`:

```
class CanonicalInterface(BaseModel):
    switchport_mode: str | None = None      # "access" | "trunk" | None
    access_vlan: int | None = None
    trunk_allowed_vlans: list[int] = Field(default_factory=list)
    trunk_native_vlan: int | None = None
    voice_vlan: int | None = None
```

- **switchport_mode** — `unsupported` on FortiGate.  FortiOS has no
  L2 access / trunk dichotomy; the field is parse-and-ignore on the
  FortiGate render path.
- **access_vlan** — `unsupported`.  Cisco's per-port VLAN assignment
  has no FortiGate analogue; cross-vendor migration loses the
  port-to-VLAN mapping unless the operator manually creates VLAN
  child interfaces on FortiGate.
- **trunk_allowed_vlans** — `unsupported`.  Same model gap — multi-
  VLAN trunking is implicit on FortiGate (stack VLAN children on the
  parent), not declarative.
- **trunk_native_vlan** — `unsupported`.  No FortiOS analogue.
- **voice_vlan** — `unsupported`.  No FortiOS analogue.

Spanning-tree is also `unsupported` on the FortiGate side — there is
no canonical field for STP today, and the `raw_sections` Tier-3
carry-through is the only place STP intent could land.  The Cisco
codec parse-and-ignores spanning-tree per its own capability matrix.

Disposition for the entire switching surface: **unsupported**.
Reason: FortiGate is an L3 firewall and does not model Cisco-style
L2 switching as configurable CLI primitives.  Operators migrating
from a Cisco access switch to a FortiGate edge would pair the
FortiGate with a separate L2 switch (FortiSwitch or third-party) and
configure switching on that downstream device.

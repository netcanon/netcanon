# Switching features: FortiGate FortiOS versus Aruba AOS-S

This is the reverse-direction sibling of
[`../aruba_aoss_to_fortigate_cli/switchport.md`](../aruba_aoss_to_fortigate_cli/switchport.md).

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide — Networking](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/).
Retrieved: 2026-04-30

FortiGate is **L3-only** beyond a hardware-switch sub-feature on a
few low-end models (60E-class).  See
[`../aruba_aoss_to_fortigate_cli/switchport.md`](../aruba_aoss_to_fortigate_cli/switchport.md)
for the FortiGate L2-surface specifics.

The key implication for **this** direction is that FortiGate parse
**never populates** the canonical L2 fields:

- `CanonicalInterface.switchport_mode` — never set.
- `CanonicalInterface.access_vlan` — never set.
- `CanonicalInterface.trunk_allowed_vlans` — never set.
- `CanonicalInterface.trunk_native_vlan` — never set.
- `CanonicalInterface.voice_vlan` — never set.
- `CanonicalVlan.tagged_ports` — never populated.
- `CanonicalVlan.untagged_ports` — never populated.

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Advanced Traffic Management Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ATMG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

Aruba is a campus L2/L3 switch with rich switching features.  See
the forward-direction sibling for full details.

## Cross-vendor mapping (FortiGate -> Aruba)

Canonical surface:

```
class CanonicalInterface(BaseModel):
    ...
    switchport_mode: str | None = None
    access_vlan: int | None = None
    trunk_allowed_vlans: list[int]
    trunk_native_vlan: int | None = None
    voice_vlan: int | None = None
class CanonicalVlan(BaseModel):
    ...
    tagged_ports: list[str]
    untagged_ports: list[str]
```

- **switchport_mode / access_vlan / trunk_allowed_vlans /
  trunk_native_vlan** — `unsupported`.  FortiGate parse never
  populates these; Aruba render emits routed-port-only
  configurations regardless of any L2 intent the FortiGate source
  carried.  Operators consolidating a FortiGate edge into an
  Aruba access switch must manually configure port-VLAN
  membership on the Aruba target.
- **voice_vlan** — `unsupported`.  No FortiGate concept; AOS-S
  uses LLDP-MED policy.
- **CanonicalVlan.tagged_ports / untagged_ports** — `unsupported`.
  FortiGate's child-interface VLAN model carries membership via
  parent identity, not as a port list.  FortiGate parse leaves
  these canonical lists empty.

Disposition: **unsupported**.  Reason: FortiGate has no L2
trunking primitive to populate the canonical switchport / VLAN-
port-list fields; Aruba target has the field but receives no
data.

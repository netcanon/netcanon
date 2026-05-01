# Switching features: Aruba AOS-S versus FortiGate FortiOS

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Advanced Traffic Management Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ATMG/2930F-3810-5400/index.htm)
Source: [Aruba ArubaOS-Switch 16.10 Multicast and Routing Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MRG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S is a campus L2/L3 switch with a dense L2 surface:

- **VLAN-centric port lists.**  See `vlans.md`.  Membership is
  declared from the VLAN side (`tagged <ports>` /
  `untagged <ports>`) rather than per-port.
- **Spanning-tree.**  AOS-S supports MSTP / RSTP-PVST.  Configured
  at the global / per-VLAN level (`spanning-tree`,
  `spanning-tree priority 4096`, etc.).  Not modelled in canonical
  in v1.
- **DHCP snooping.**  `dhcp-snooping vlan <list>` per-VLAN trust
  policy.  Not modelled in canonical.
- **IGMP snooping.**  `ip igmp-snooping` per-VLAN.  Not modelled
  in canonical.
- **Voice VLAN via LLDP-MED policy.**  AOS-S handles voice traffic
  via LLDP-MED network-policy TLVs (separate `lldp config` block)
  rather than a `voice-vlan N` per-port directive like Cisco.  The
  aruba_aoss codec does not currently parse voice-VLAN intent.
- **Routed-port hint.**  The `routing` keyword inside an
  `interface <N>` stanza tags the port as L3 routed (no
  switchport behaviour).

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide — Networking](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/).
Retrieved: 2026-04-30

FortiGate is **L3-only** beyond the hardware-switch sub-feature on
a few low-end models:

- **No L2 trunking primitive.**  Multiple VLANs on a single port
  require multiple VLAN child interfaces; there is no
  `switchport mode trunk / allowed vlan ...` analogue.
- **No spanning-tree.**  FortiGate appliances are typically the
  L3 termination point; STP is irrelevant.  The hardware-switch
  feature on 60E-class units exposes a basic `config system
  switch-interface` but no STP knobs.
- **No DHCP snooping / IGMP snooping** at the firewall level.
  Hardware-switch ports may expose limited L2 features through
  `config switch-controller` (managed via FortiSwitch), which is
  out of scope for the firewall-codec parse path.
- **No voice-VLAN concept.**  FortiOS treats LLDP as a discovery
  protocol only.
- **All ports are L3 by default.**  Even hardware-switch ports
  expose `set ip` rather than a `switchport access vlan N`
  directive.

## Cross-vendor mapping (Aruba -> FortiGate)

Canonical surface:

```
class CanonicalInterface(BaseModel):
    ...
    switchport_mode: str | None = None
    access_vlan: int | None = None
    trunk_allowed_vlans: list[int]
    trunk_native_vlan: int | None = None
    voice_vlan: int | None = None
```

- **switchport_mode / access_vlan / trunk_allowed_vlans /
  trunk_native_vlan** — `unsupported`.  Aruba populates these via
  `project_vlan_to_switchport` on parse, but FortiGate has no
  target — the canonical L2 fields are dropped on render.
  Operators consolidating an AOS-S edge into a FortiGate must
  manually rearchitect the L2 design (multiple VLAN child
  interfaces, hardware-switch grouping if available, separate
  FortiSwitch box for L2 surface).
- **voice_vlan** — `unsupported`.  The aruba_aoss codec does not
  currently parse voice-VLAN intent; the FortiGate codec has no
  voice-VLAN render path.
- **Spanning-tree / DHCP-snooping / IGMP-snooping** — Tier 3 (not
  in canonical).  Drop on parse, no render path.

Disposition: **unsupported**.  Reason: FortiGate is L3-only;
target absent on this direction.

# VLAN configuration: Arista EOS versus FortiGate FortiOS

## Arista EOS

Source: [Arista EOS User Manual — VLAN Configuration (4.35.2F)](https://www.arista.com/en/um-eos/eos-vlan-configuration)
Retrieved: 2026-05-01

```
vlan 10
   name USERS
!
vlan 20
   name VOICE
!
interface Ethernet2
   switchport mode access
   switchport access vlan 10
!
interface Ethernet3
   switchport mode trunk
   switchport trunk native vlan 1
   switchport trunk allowed vlan 10,20,100,200
!
interface Vlan100
   description "Tenant A data SVI"
   ip address 10.100.0.1/24
```

Notable Arista specifics:

- **VLAN-stanza names are unquoted** and accept letters, digits,
  hyphens, underscores, periods (typical: `USERS`, `MGMT-VLAN`,
  `Tenant_A`).
- **Per-port VLAN membership** — switchport state lives on the port
  via `switchport mode access` / `switchport access vlan N`,
  `switchport mode trunk` / `switchport trunk allowed vlan ...`.
- **Native VLAN** for trunk ports via `switchport trunk native vlan
  N`.
- **Voice VLAN** via `switchport voice vlan N` (uses LLDP-MED
  signalling under the hood).
- **SVIs** via `interface Vlan<N>` with `ip address X/N`; the SVI
  carries the L3 surface for that VLAN.
- **VLAN-centric port-list** is NOT how Arista emits it in
  `running-config` — the codec re-projects per-port `switchport`
  state into `CanonicalVlan.tagged_ports` / `untagged_ports` on
  parse via the `project_switchport_to_vlan` helper.

## FortiGate FortiOS CLI

Source: [Fortinet Document Library — VLAN configuration (FortiOS 7.4 Cookbook)](https://docs.fortinet.com/document/fortigate/7.4.0/cookbook/)
Source: [Fortinet Document Library — Interface Settings (Admin Guide)](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/954635/interface-settings)
Retrieved: 2026-05-01

```
config system interface
    edit "agg1.100"
        set alias "data-vlan-100"
        set type vlan
        set vlanid 100
        set interface "agg1"
        set ip 10.100.0.1 255.255.255.0
        set status up
    next
    edit "VL_200"
        set alias "voice-vlan-200"
        set vlanid 200
        set interface "agg1"
        set ip 10.200.0.1 255.255.255.0
        set status up
    next
end
```

Notable FortiOS specifics:

- **No top-level `vlan <N>` stanza.**  VLAN identity emerges from
  child interfaces with `set type vlan / set vlanid <N>` hanging off
  a parent (`set interface "<parent>"`).
- **No port-list per VLAN.**  Membership is encoded by which parent
  interface the child VLAN attaches to — a single VLAN spanning
  multiple physical ports requires multiple child VLAN interfaces
  (one per parent), not a single VLAN stanza with a port list.
- **VLAN name is the edit-ID** of the child interface (`agg1.100` or
  arbitrary `VL_200`); there is no separate `name` slot.  Aliases
  (`set alias "..."`) carry human-readable description.
- **No native VLAN concept** in the FortiGate VLAN model — untagged
  membership on a parent is the parent's own (non-VLAN child) state,
  while VLAN child interfaces always tag.
- **No voice VLAN** — FortiGate has no voice-VLAN primitive (and no
  LLDP-MED policy server).
- **L3 SVI** is the same child VLAN interface — `set ip` directly on
  `agg1.100` carries the SVI's L3 config (no separate `interface
  Vlan100`).

## Cross-vendor mapping (Arista -> FortiGate)

Canonical surface:

```
vlans[].id: int
vlans[].name: str
vlans[].description: str
vlans[].tagged_ports: list[str]
vlans[].untagged_ports: list[str]
vlans[].ipv4_addresses: list[CanonicalIPv4Address]   # SVI absorption
```

- **id** — `good`.  Round-trips cleanly via `set vlanid N`.
- **name** — `lossy`.  Arista `vlan 10 / name USERS` populates
  canonical name; FortiGate render uses the edit ID as identity
  (synthesises `VL_10` or `<parent>.10`).  Operator-readable name
  drops unless operators authored a per-pane VLAN-rename mapping.
- **description** — `unsupported`.  FortiGate has no per-VLAN
  description slot beyond the alias on the child interface.
- **tagged_ports / untagged_ports** — `unsupported (model gap)`.
  This is the major asymmetric loss.  Arista's per-port switchport
  state re-projects to canonical VLAN-centric port lists on parse;
  FortiGate's child-interface model encodes membership via parent
  identity.  Cross-vendor render on Arista -> FortiGate would have
  to **synthesise multiple VLAN-child interfaces** (one per VLAN per
  parent port) which v1 render does not do.  Operators must
  manually reconstruct multi-port VLAN membership on the target.
- **ipv4_addresses (SVI)** — `good`.  Arista `interface Vlan100 / ip
  address X/N` populates canonical via SVI absorption; FortiGate
  render emits the address on the synthesised VLAN child interface
  (`set ip` on `agg1.100` or similar).

Per-interface (companion) fields driven by VLAN intent:

- **switchport_mode / access_vlan / trunk_allowed_vlans /
  trunk_native_vlan** — `unsupported`.  FortiGate is L3-only beyond
  the hardware-switch sub-feature on a few low-end models; these
  fields drop entirely on render.  Codec emits no equivalent (no
  `config switch-controller managed-switch` on a non-FortiSwitch-
  aware platform).
- **voice_vlan** — `unsupported`.  No FortiGate analogue.

Disposition summary: **good** for VLAN id and SVI absorption.
**Lossy** for VLAN name (FortiGate render synthesises).
**Unsupported** for description, port-list synthesis (model gap),
and all switchport/voice fields.

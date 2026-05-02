# VLAN configuration: FortiGate FortiOS versus Arista EOS

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
    edit "port4.300"
        set alias "guest-vlan-300"
        set type vlan
        set vlanid 300
        set interface "port4"
        set ip 10.30.0.1 255.255.255.0
        set status down
    next
end
```

Notable FortiOS specifics:

- **No top-level `vlan <N>` stanza.**  VLAN identity emerges from
  child interfaces with `set type vlan / set vlanid <N>` hanging
  off a parent (`set interface "<parent>"`).
- **No port-list per VLAN.**  Membership is encoded by which parent
  interface the child VLAN attaches to — a single VLAN spanning
  multiple physical ports requires multiple child VLAN interfaces
  (one per parent), not a single VLAN stanza with a port list.
- **VLAN name is the edit-ID** of the child interface (`agg1.100`,
  `VL_200`, `port4.300`); arbitrary string.
- **No native VLAN concept** in the FortiGate VLAN model — untagged
  membership on a parent is the parent's own (non-VLAN child) state.
- **No voice VLAN** primitive.
- **L3 SVI lives directly on the child** — `set ip` carries the SVI.

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

- **Top-level `vlan <N>` stanza with optional `name <X>`.**  The
  separate name slot is operator-readable.
- **Per-port switchport state** — `switchport mode access/trunk`,
  `switchport access vlan N`, `switchport trunk allowed vlan ...`.
- **Native VLAN** for trunk ports via `switchport trunk native
  vlan N`.
- **Voice VLAN** via `switchport voice vlan N`.
- **SVIs as separate interfaces** — `interface Vlan<N>` with `ip
  address X/N`.

## Cross-vendor mapping (FortiGate -> Arista)

Canonical surface:

```
vlans[].id: int
vlans[].name: str
vlans[].description: str
vlans[].tagged_ports: list[str]
vlans[].untagged_ports: list[str]
vlans[].ipv4_addresses: list[CanonicalIPv4Address]   # SVI absorption
```

- **id** — `good`.  FortiGate `set vlanid 100` -> Arista `vlan
  100`.
- **name** — `lossy`.  FortiGate uses the edit ID (`agg1.100`,
  `VL_200`, `port4.300`) as the canonical VLAN name.  Arista
  render emits `vlan 100 / name agg1.100` which is mechanical
  but not operator-readable.  Operators authoring per-pane VLAN-
  rename mappings can override (e.g. `agg1.100` -> `USERS`).
- **description** — `not_applicable`.  FortiGate has no per-VLAN
  description slot beyond the alias on the child interface; the
  canonical field is empty on FortiGate parse.  Arista renders
  no description.
- **tagged_ports / untagged_ports** — `unsupported`.  FortiGate's
  child-interface model encodes membership via parent identity,
  not per-VLAN port lists.  CanonicalIntent.vlans[].tagged_ports
  / untagged_ports are EMPTY after FortiGate parse — there is
  nothing to lose because the source did not encode the data
  that way.  Arista render therefore emits VLAN stanzas without
  port-list data; operators MUST manually reconstruct
  `switchport access vlan N` on each Arista access port and
  `switchport trunk allowed vlan ...` on each trunk port.  This
  is the **inverse model gap** of the forward direction (where
  Arista populates port lists that FortiGate render cannot
  consume).
- **ipv4_addresses (SVI)** — `good`.  FortiGate's `set ip` on the
  child VLAN interface lands on CanonicalVlan.ipv4_addresses via
  SVI absorption; Arista render emits the SVI as `interface
  Vlan100 / ip address X/N`.

Per-interface companion fields (the inverse of vlans[].port-list):

- **switchport_mode / access_vlan / trunk_allowed_vlans /
  trunk_native_vlan** — `unsupported` (for an inverse reason
  vs. the forward direction).  FortiGate parse never populates
  these because the parent-interface VLAN model carries
  membership via the parent's identity.  Arista render needs
  these to emit per-port `switchport` lines, but the canonical
  fields are empty — the operator must reconstruct.
- **voice_vlan** — `not_applicable`.  No FortiGate analogue;
  field empty on parse.

Disposition summary: **good** for VLAN id and SVI absorption.
**Lossy** for VLAN name (FortiGate edit-ID becomes the VLAN name).
**Not_applicable** for description (FortiGate source never carries
it).  **Unsupported** for port-list synthesis (model gap, inverse
direction — operator must reconstruct per-port switchport state on
Arista target).

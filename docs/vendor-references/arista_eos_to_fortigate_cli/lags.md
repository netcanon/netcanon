# LAG / port-channel / aggregate: Arista EOS versus FortiGate FortiOS

## Arista EOS

Source: [Arista EOS User Manual — Data Transfer (Port-Channel) (4.35.2F)](https://www.arista.com/en/um-eos/eos-data-transfer)
Retrieved: 2026-05-01

```
interface Ethernet4
   description "LAG member 1"
   channel-group 10 mode active
!
interface Ethernet5
   description "LAG member 2"
   channel-group 10 mode active
!
interface Port-Channel10
   description "Bonded uplink to core"
   no switchport
   ip address 10.0.1.1/31
!
interface Port-Channel20
   description "Bonded trunk to leaf-02"
   switchport mode trunk
   switchport trunk allowed vlan 100,200
```

Notable Arista specifics:

- **Mandatory `Port-Channel<N>` form** with capital 'C' — the integer
  N matches the `channel-group N` modifier on each member.
- **Member binding via `channel-group N mode {active|passive|on}`**
  on each member port.  Modes:
  - `active` — LACP active (will initiate LACP).
  - `passive` — LACP passive (responds only).
  - `on` — static (no LACP, manual aggregation).
- **The Port-Channel interface stanza carries the L2/L3 surface**
  (switchport mode, IP address, VRF binding, etc.); members carry
  only the channel-group binding plus optional speed/transceiver
  settings.
- **MLAG** (`mlag <id>` inside the Port-Channel stanza) is an Arista-
  specific dual-active extension; not modelled in canonical.
- **No PAgP** (Cisco's pre-LACP protocol) — Arista is LACP-only.

## FortiGate FortiOS CLI

Source: [Fortinet Document Library — Aggregate Interface (FortiOS 7.4 Admin Guide)](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/954635/interface-settings)
Retrieved: 2026-05-01

```
config system interface
    edit "agg1"
        set alias "downstream-bond"
        set type aggregate
        set member "port2" "port3"
        set lacp-mode active
        set ip 10.20.0.1 255.255.255.0
        set status up
    next
    edit "agg2"
        set alias "passive-bond"
        set type aggregate
        set member "port5" "port6"
        set lacp-mode passive
        set ip 10.21.0.1 255.255.255.0
        set status up
    next
end
```

Notable FortiOS specifics:

- **Operator-named aggregate** (`agg1`, `LAG_INTERNAL`,
  `MyTrunk`) — no mandatory integer-suffix form.  Codec must
  invent / preserve the name.
- **`set type aggregate`** discriminator on the parent interface.
- **Member list via `set member "port2" "port3" ...`** — a
  whitespace-separated list of physical ports.  Member ports
  themselves do not carry a `channel-group` style binding.
- **LACP mode via `set lacp-mode {active|passive|static}`** — three-
  way enum matching Arista's `active`/`passive`/`on`.  No PAgP /
  HP-proprietary modes.
- **L3 surface lives on the aggregate interface itself** (same
  semantics as Arista's Port-Channel stanza).

## Cross-vendor mapping (Arista -> FortiGate)

Canonical surface:

```
lags[].name: str
lags[].members: list[str]
lags[].mode: str   ("active" | "passive" | "static")
```

- **name** — `lossy`.  Arista's `Port-Channel10` does not match
  FortiGate's operator-named aggregates.  Codec policy on cross-
  vendor render: extract the integer suffix and emit `LAG_<N>` /
  `agg<N>` (operator override via per-pane port-rename surface).
  Member-port names also need the rename mesh (Arista `Ethernet4` ->
  FortiGate `port4`).
- **members** — `good`.  Member list round-trips through the canonical
  list; rename mesh applies on each member.
- **mode** — `good`.  Arista `mode active` / `mode passive` / `mode
  on` map directly to FortiGate `set lacp-mode active` / `passive` /
  `static`.  Cross-vendor render is mechanical.

Per-LAG L3 surface (description / IP / switchport mode / trunk
allowed VLANs / VRF binding) is carried via the parent `interfaces[]`
record — see interfaces.md and vlans.md for the per-field treatment.

Disposition summary: **good** for members and mode.  **Lossy** for
name (rename mesh required to bridge `Port-Channel<N>` and `agg<N>`
shapes).  No unsupported items beyond the per-LAG L3/L2 fields which
are governed by interfaces.md / vlans.md.

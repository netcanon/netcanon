# LAG / aggregate / port-channel: FortiGate FortiOS versus Arista EOS

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

- **Operator-named aggregate** — no mandatory integer suffix.
  Common shapes: `agg1`, `LAG_INTERNAL`, `MyTrunk`.
- **`set type aggregate`** discriminator on the parent interface.
- **Member list via `set member "port2" "port3" ...`** — whitespace-
  separated list of physical port names.  Member ports do NOT
  carry a `channel-group` style binding on the member side.
- **LACP mode via `set lacp-mode {active|passive|static}`**.
- **L3 surface lives on the aggregate interface itself** (matches
  Arista's Port-Channel stanza semantics).

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
```

Notable Arista specifics:

- **Mandatory `Port-Channel<N>` form** with capital 'C'; integer N
  matches the `channel-group N` modifier on each member.
- **Member binding via `channel-group N mode {active|passive|on}`**
  on each member port.
- **Port-Channel interface stanza carries the L2/L3 surface**.
- **MLAG** (`mlag <id>`) — Arista-specific dual-active extension.
- **No PAgP** — Arista is LACP-only.

## Cross-vendor mapping (FortiGate -> Arista)

Canonical surface:

```
lags[].name: str
lags[].members: list[str]
lags[].mode: str   ("active" | "passive" | "static")
```

- **name** — `lossy`.  FortiGate's operator-named `agg1` /
  `LAG_INTERNAL` doesn't carry an integer suffix that Arista's
  `Port-Channel<N>` form needs.  Codec policy on cross-vendor
  render: extract the integer suffix when present (`agg1` -> 1)
  or invent the next available integer (operator override via
  per-pane LAG-rename surface).  Member-port names also need the
  rename mesh (FortiGate `port2` -> Arista `Ethernet2`).
- **members** — `good`.  Member list round-trips through the
  canonical list; rename mesh applies on each member.  Arista
  render emits one `interface Ethernet<N> / channel-group N mode
  ...` stanza per member.
- **mode** — `good`.  FortiOS `set lacp-mode active` / `passive` /
  `static` map directly to Arista `mode active` / `passive` /
  `on`.  Cross-vendor render is mechanical.

Per-LAG L3 surface (description / IP / VRF binding) is carried
via the parent `interfaces[]` record — see interfaces.md and
firewall_unsupported.md for the per-field treatment.

Disposition summary: **good** for members and mode.  **Lossy** for
name (rename mesh required to bridge `agg<N>` and `Port-Channel<N>`
shapes; integer-suffix invention).

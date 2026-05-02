# LAG / aggregate / aggregated-Ethernet: FortiGate FortiOS versus Juniper Junos

## FortiGate FortiOS

Source: [FortiGate / FortiOS Administration Guide — Aggregate interfaces](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/954635/interface-settings).
Retrieved: 2026-05-01.

FortiGate models LAGs as interface-typed children of `config system
interface`:

```
config system interface
    edit "agg1"
        set type aggregate
        set member "port2" "port3"
        set lacp-mode active
        set ip 10.20.0.1 255.255.255.0
        set status up
    next
    edit "agg2"
        set type aggregate
        set member "port5" "port6"
        set lacp-mode passive
    next
end
```

Notable FortiOS specifics:

- **Operator-named** aggregates (`agg1`, `LAG_INTERNAL`).  No
  enforced naming convention.
- **Members**: `set member "p1" "p2" ...` (whitespace-delimited
  list; member names are the parent FortiGate interface names).
- **LACP mode**: `lacp-mode {static|active|passive}`.  No PAgP
  analogue.
- **L3 on aggregate**: `set ip` directly on the aggregate.  IP
  addressing is the same as a routed port.
- **LAG-as-VLAN-trunk**: child VLAN interfaces declare
  `set interface "agg1"`.

## Juniper Junos

Source: [Junos LAG overview topic-map](https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/topic-map/lag-overview.html).
Source: [Junos aggregated-Ethernet configuration example](https://www.juniper.net/documentation/us/en/software/junos/sampling-forwarding-monitoring/topics/example/lag-aggregated-ethernet-link-configuring.html).
Retrieved: 2026-05-01.

Junos models LAGs as `ae<N>` interfaces with members declaring their
own membership via `ether-options` or `gigether-options 802.3ad`:

```
set chassis aggregated-devices ethernet device-count 4
#
set interfaces ge-0/0/2 description "LAG ae0 member 1"
set interfaces ge-0/0/2 ether-options 802.3ad ae0
set interfaces ge-0/0/3 description "LAG ae0 member 2"
set interfaces ge-0/0/3 ether-options 802.3ad ae0
#
set interfaces ae0 description "Bonded uplink to spine"
set interfaces ae0 mtu 9192
set interfaces ae0 aggregated-ether-options lacp active
set interfaces ae0 unit 0 family inet address 10.1.0.1/31
```

Notable Junos specifics:

- **Integer-keyed names**: `ae0`, `ae1`, ..., up to chassis-wide
  device-count cap.  No operator-friendly names without aliases.
- **Members declare membership**: each physical interface declares
  `set interfaces <X> ether-options 802.3ad ae<N>` (or
  `gigether-options` on QFX).  No member list on the parent.
- **LACP mode**: `aggregated-ether-options lacp {active|passive}`.
  Static LAG omits the `lacp` block entirely.
- **Chassis device-count**: `set chassis aggregated-devices ethernet
  device-count N` allocates the maximum number of `ae<N>` interfaces
  available; required to be at least 1 for any LAG.
- **L3 on ae<N>**: per-unit family declarations as on any interface.

## Cross-vendor mapping (FortiGate -> Junos)

Canonical surface (`CanonicalLAG`):

```
class CanonicalLAG(BaseModel):
    name: str
    members: list[str]
    mode: str = "active"   # "active" | "passive" | "static"
```

- **name** — `lossy`.  FortiGate operator-named (`agg1`,
  `LAG_INTERNAL`) -> Junos integer-keyed (`ae0`).  The FortiGate
  source string preserves in canonical; Junos render assigns an
  `ae<N>` integer (operator override via rename mesh recommended).
- **members** — `good` after rename mesh.  FortiGate member names
  (`port2`, `port3`) map to Junos forms (`ge-0/0/2`, `ge-0/0/3`).
- **mode** — `good`.  `active` / `passive` / `static` all preserve.
- **device-count** — `lossy` (canonical schema gap).  Junos render
  synthesises a default `set chassis aggregated-devices ethernet
  device-count N` based on canonical LAG count.

## Cross-vendor mapping (Junos -> FortiGate)

Reverse direction (see also `../juniper_junos_to_fortigate_cli/lags.md`):

- **name** — `lossy`.  Junos `ae<N>` -> FortiGate operator-friendly
  name.  Without rename mesh, FortiGate render keeps `ae<N>` verbatim
  (legal but non-conventional FortiGate edit-IDs).
- **device-count** drops on FortiGate render (FortiGate auto-allocates).

# LAG / aggregated-Ethernet / aggregate: Juniper Junos versus FortiGate FortiOS

## Juniper Junos

Source: [Junos LAG overview topic-map](https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/topic-map/lag-overview.html).
Source: [Junos aggregated-Ethernet configuration example](https://www.juniper.net/documentation/us/en/software/junos/sampling-forwarding-monitoring/topics/example/lag-aggregated-ethernet-link-configuring.html).
Retrieved: 2026-05-01.

Junos models LAGs as `ae<N>` interfaces with members declaring their
own membership via `ether-options 802.3ad`:

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

- **Integer-keyed names**: `ae0`, `ae1`, ...; chassis device-count
  caps maximum.
- **Members declare membership** (no member list on the parent).
- **LACP modes**: `aggregated-ether-options lacp {active|passive}`.
  Static LAG omits the `lacp` block.
- **Chassis device-count**: required allocation directive.
- **L3 on `ae<N>`**: per-unit family declarations.

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
    next
end
```

- **Operator-named** aggregates.
- **Members on parent**: `set member "p1" "p2" ...`.
- **LACP mode**: `lacp-mode {static|active|passive}`.
- **No chassis-wide device-count** required (FortiGate auto-allocates).

## Cross-vendor mapping (Junos -> FortiGate)

Canonical surface (`CanonicalLAG`).

- **name** — `lossy`.  Junos `ae<N>` -> FortiGate operator-friendly
  edit ID.  Without rename mesh, FortiGate render keeps `ae<N>`
  verbatim (legal but non-conventional FortiGate edit-IDs).
- **members** — `good` after rename mesh.  Junos `ge-0/0/2`-form
  member names map to FortiGate forms (`port2`).
- **mode** — `good`.  `active` / `passive` / `static` preserve.
- **device-count** drops on FortiGate render (no analogue).

## Cross-vendor mapping (FortiGate -> Junos)

Reverse direction (see also `../fortigate_cli_to_juniper_junos/lags.md`):

- **name** — `lossy`.  FortiGate operator-named -> Junos integer-
  keyed; rename mesh recommended for `agg1` -> `ae0` mapping.
- **device-count** — Junos render synthesises a default based on
  canonical LAG count.

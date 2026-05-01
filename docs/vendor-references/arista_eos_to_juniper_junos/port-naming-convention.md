# Port naming convention

How physical and logical interfaces are named on each platform.

Sources:
- Arista: https://www.arista.com/en/um-eos/eos-ethernet-ports (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/en_US/junos12.3/topics/concept/interfaces-naming-conventions-qfx-series.html (retrieved 2026-05-01)

Citation ids: `arista-ethernet-ports`, `junos-iface-naming`.

## Arista EOS form

Physical:
- `Ethernet1`, `Ethernet48` — non-modular boxes use sequential
  numbering, no speed prefix.
- `Ethernet3/1` — modular: card/port (no PIC concept).
- `Ethernet50/1` — QSFP breakout child (lane 1-4 of port 50).

Logical:
- `Loopback0`, `Loopback42`
- `Vlan100` (SVI)
- `Port-Channel10` (LAG; capital `C` distinguishes from Cisco's
  `Port-channel`)
- `Management1`
- `Vxlan1`

## Junos form

Physical: `<media>-<fpc>/<pic>/<port>[.<unit>]`:
- `ge-0/0/0` (GE), `xe-0/0/0` (10GE), `et-0/0/0` (40/100GE)
- `ge-0/0/0.0` — logical unit on the physical
- `mge-0/0/0` (multi-rate GE), `fe-0/0/0` (legacy FE)

Logical:
- `lo0`, `lo0.0` (loopback with unit)
- `irb.100` (Integrated Routing and Bridging — Junos's SVI form)
- `ae0`, `ae0.0` (aggregated Ethernet — LAG)
- `me0`, `em0`, `fxp0` (management variants by platform line)

## Mapping notes

- **Speed prefix collapse.** Arista physical names carry no speed
  hint; the canonical port-classification defaults to `gig` speed
  hint for `Ethernet<N>`.  Junos render picks `ge-` (GE) for
  unknown speeds, which may understate 10G/25G/100G ports — the
  operator typically adjusts via the per-pane port-rename surface.
- **Slot/PIC/port synthesis.** Arista's flat `Ethernet1` maps to
  Junos `ge-0/0/0` by default (FPC 0, PIC 0, port 0-indexed).  The
  port number maps 1-indexed → 0-indexed (`Ethernet1` → port 0).
- **LAG naming.** `Port-Channel10` ↔ `ae10`.  Both use a sequential
  index; the canonical mapping is straightforward.
- **SVI naming.** `Vlan100` (Arista L3 SVI) ↔ `irb.100` (Junos
  IRB) is the documented mapping for EVPN-VXLAN bridging.
- **Loopback unit.** `Loopback0` ↔ `lo0.0` — Junos always carries
  the unit number; the canonical name carries the operator-form
  string and the rename surface bridges them.

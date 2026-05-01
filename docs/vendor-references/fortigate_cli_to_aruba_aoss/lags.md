# LAG / aggregate / Trk: FortiGate FortiOS versus Aruba AOS-S

This is the reverse-direction sibling of
[`../aruba_aoss_to_fortigate_cli/lags.md`](../aruba_aoss_to_fortigate_cli/lags.md).

## FortiGate FortiOS CLI

Source: [Fortinet FortiOS Administration Guide — Aggregate interfaces](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/954635/interface-settings).
Retrieved: 2026-04-30

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

Operator-named aggregate edits (no mandated form).  See
[`../aruba_aoss_to_fortigate_cli/lags.md`](../aruba_aoss_to_fortigate_cli/lags.md)
for full FortiGate specifics.

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Advanced Traffic Management Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ATMG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
trunk 23-24 trk1 lacp
trunk A3-A4 trk2 trunk

interface Trk1
   name "downstream-bond"
   enable
   exit
```

`Trk<N>` mandated form.  See
[`../aruba_aoss_to_fortigate_cli/lags.md`](../aruba_aoss_to_fortigate_cli/lags.md)
for full Aruba specifics.

## Cross-vendor mapping (FortiGate -> Aruba)

Canonical surface:

```
class CanonicalLAG(BaseModel):
    name: str
    members: list[str]
    mode: str = "active"
```

- **name** — `lossy`.  FortiOS operator-named aggregate (`agg1` /
  `LAG_INTERNAL`) -> Aruba's `Trk<N>` integer-suffix form
  requires invention on render: canonical model has no LAG-ID
  field, so the Aruba render picks the next available integer
  (operators override via per-pane port-rename surface).
- **members** — `good`.  Direct preservation; the rename mesh
  applies on member names.  FortiGate's `set member "port2"
  "port3"` lands on canonical and Aruba renders as a `trunk
  <port-list> trk<N> lacp` directive.
- **mode** — `lossy`.  FortiOS `active` / `passive` / `static`
  map to Aruba `lacp` / `lacp` (Aruba does not expose passive
  separately on LACP) / `trunk` (HP-static).  FortiGate has no
  PAgP / `dt-lacp` / `fec` analogue so cross-vendor render is
  best-effort on the standard LACP modes only.

Disposition: **lossy**.  Reason: name-shape divergence (operator-
named -> Trk<N>) requires the rename mesh; mode coercion loses
FortiGate `passive` distinction.

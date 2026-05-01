# LAG / Trk / aggregate: Aruba AOS-S versus FortiGate FortiOS

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Advanced Traffic Management Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ATMG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S models LAGs as `Trk<N>` virtual interfaces with members
declared via the `trunk` global directive:

```
trunk 23-24 trk1 lacp
trunk A3-A4 trk2 trunk

interface Trk1
   name "stack-uplink-A"
   enable
   exit
interface Trk2
   name "stack-uplink-B"
   enable
   exit
```

Notable AOS-S specifics:

- **`trunk <port-list> trk<N> <mode>`** — global directive declaring
  membership.  Modes: `lacp` (LACP active), `trunk` (HP-proprietary
  static), `dt-lacp` (multi-chassis distributed-trunk), `fec`
  (HP-proprietary fast-EtherChannel).
- **`Trk<N>` interface stanza** — per-trunk L3 / description state
  lives in a dedicated `interface Trk<N>` block.
- **Port-list expansion.**  `23-24` expands to ports 23 and 24;
  the codec splits on parse.

## FortiGate FortiOS CLI

Source: [Fortinet FortiOS Administration Guide — Aggregate interfaces](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/954635/interface-settings).
Source: FortiOS CLI Reference — `config system interface / set type aggregate`.
Retrieved: 2026-04-30

FortiOS models LAGs via `set type aggregate` on a parent interface
edit, with `set member` listing the bundled physical ports:

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
end
```

Notable FortiOS specifics:

- **Operator-named aggregate.**  Convention: `LAG_<role>` or
  `agg<n>`.  No mandated form like Aruba's `Trk<N>`.
- **`set member` list.**  Membership is declared from the
  aggregate side.  The FortiGate codec second-pass synthesises
  the `lag_member_of` reverse-link on each member's
  `CanonicalInterface`.
- **LACP modes**: `static`, `passive`, `active`.  No PAgP, no
  HP-proprietary `dt-lacp` / `fec` analogues.

## Cross-vendor mapping (Aruba -> FortiGate)

Canonical surface:

```
class CanonicalLAG(BaseModel):
    name: str
    members: list[str]
    mode: str = "active"
```

- **name** — `lossy`.  Aruba's `Trk1` differs in shape from
  FortiGate's operator-named `LAG_<role>` / `agg<n>`.  The
  port-rename mesh applies operator-curated mappings on cross-
  vendor render; without an override the FortiGate render preserves
  whatever the source emitted.
- **members** — `good`.  Aruba's `1-4` port-list expands to four
  canonical port records on parse; FortiGate render emits
  `set member "port1" "port2" ...` (with the rename mesh applied
  to each member).
- **mode** — `lossy`.  AOS-S `lacp` -> FortiOS `active`.  AOS-S
  `trunk` (HP-static) -> FortiOS `static`.  AOS-S `dt-lacp` /
  `fec` collapse to `static` with a banner — FortiOS LACP only
  offers active/passive/static, so multi-chassis distributed-trunk
  semantics are lost.

Disposition: **lossy**.  Reason: name-shape divergence (Trk<N> ->
operator-named) requires the rename mesh; mode collapse for
HP-proprietary modes.

# Port naming: Aruba AOS-S versus Arista EOS

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Basic Operation Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/BOG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S uses bare numeric port identifiers — **no speed prefix**:

```
interface 1                             ; standalone-switch ethernet port
interface A1                            ; 5400R chassis: module A, port 1
interface 1/1                           ; 2930M stack: stack-member 1, port 1
interface Trk1                          ; LAG (link-aggregation) trunk
```

LAG names take the literal form `Trk<N>` (capital T, three-letter
prefix).  The codec's `port_names.py` classifies the form via:

* Bare integer `<N>` -> standalone-switch ethernet port.
* Letter+integer `<L><N>` -> chassis-module ethernet port.
* `<stack>/<port>` -> stack-member ethernet port.
* `Trk<N>` -> aggregated logical port.

## Arista EOS

Source: [Arista EOS — Data Transfer / Interface Configuration](https://www.arista.com/en/um-eos/eos-data-transfer)
Retrieved: 2026-05-01

Arista EOS interface names are **flat and speed-agnostic**:

```
interface Ethernet1                     ; first port on the box (or 1/1 on chassis)
interface Ethernet1/1                   ; chassis with linecards
interface Ethernet48/1                  ; breakout child of Ethernet48
interface Management1                   ; out-of-band mgmt port
interface Loopback0
interface Vlan100
interface Port-Channel10                ; LAG (NOTE: capital 'C')
interface Vxlan1                        ; VTEP
```

Crucially, `Ethernet<N>` carries **no speed token** (unlike Cisco
IOS's `GigabitEthernet1/0/1` or `TenGigabitEthernet1/0/49`).  The
EOS codec treats all `Ethernet<N>` as a single physical-port class
and lets the underlying transceiver determine speed.

The `Port-Channel<N>` form uses **capital 'C'** (versus Cisco's
lower-case `Port-channel<N>`).

## Cross-vendor mapping

The canonical model carries `CanonicalInterface.name` as the
vendor-native string.  Cross-vendor translation depends on the
per-pane port-rename mesh:

* Aruba `1` -> Arista `Ethernet1` (standalone-switch default;
  operator-overridable).
* Aruba `A1` -> Arista `Ethernet1` (5400R chassis default — the
  letter prefix collapses since EOS has no chassis-module token).
* Aruba `1/1` -> Arista `Ethernet1/1` (2930M stack -> chassis form).
* Aruba `Trk1` -> Arista `Port-Channel1` (note capital 'C'; see
  `lags.md` for capitalisation rationale).

Speed-hint inference:

* Aruba source -> Arista render: **lossless on naming** because
  EOS does not encode speed in the name.  This is the better
  direction than Aruba -> Cisco IOS-XE (where the codec must guess
  `GigabitEthernet` for all 10G/25G/100G ports).  The
  `interface_type` canonical field still degrades because both
  codecs infer it from the name shape, but the inference defaults
  match — both end up at "ethernetCsmacd".

The Aruba synthetic kitchen-sink uses `interface 1`, `interface
13`, `interface A1`, `interface A2`, `interface Trk1`, `interface
Trk2` — each renames cleanly to Arista's flat form.

Disposition: **good** for the bare-numeric ethernet form (no
speed-loss on this direction); **lossy** for `Trk<N>` ->
`Port-Channel<N>` capitalisation flip (rename mesh handles).

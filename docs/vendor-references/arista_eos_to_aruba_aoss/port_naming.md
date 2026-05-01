# Port naming: Arista EOS versus Aruba AOS-S

## Arista EOS

Source: [Arista EOS — Data Transfer / Interface Configuration](https://www.arista.com/en/um-eos/eos-data-transfer)
Retrieved: 2026-05-01

Arista EOS interface names are **flat and speed-agnostic**:

```
interface Ethernet1                     ; first port on the box
interface Ethernet1/1                   ; chassis with linecards
interface Ethernet48/1                  ; breakout child of Ethernet48
interface Management1                   ; out-of-band mgmt port
interface Loopback0
interface Vlan100
interface Port-Channel10                ; LAG (capital 'C')
interface Vxlan1                        ; VTEP
```

`Ethernet<N>` carries no speed token (unlike Cisco IOS's
`GigabitEthernet1/0/1` or `TenGigabitEthernet1/0/49`).  EOS
treats all `Ethernet<N>` as a single physical-port class and lets
the underlying transceiver determine link speed.

The `Port-Channel<N>` form uses **capital 'C'**.

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Basic Operation Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/BOG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S uses bare numeric port identifiers with optional letter /
slot prefix:

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

## Cross-vendor mapping

The canonical model carries `CanonicalInterface.name` as the
vendor-native string.  Cross-vendor translation depends on the
per-pane port-rename mesh:

* Arista `Ethernet1` -> Aruba `1` (default standalone-switch
  shape; operator may override to `A1` / `1/1` for chassis or
  stack targets).
* Arista `Ethernet1/1` -> Aruba `1/1` (stack form).
* Arista `Port-Channel1` -> Aruba `Trk1` (capital-C drops; codec
  helper strips the prefix and emits the Aruba `Trk<N>` form).
* Arista `Loopback0` / `Vlan100` -> Aruba does not model
  loopbacks; SVIs absorb into the VLAN stanza (no separate
  `interface Vlan100` directive on Aruba).

Speed-hint inference:

* Arista source -> Aruba render: lossless on naming because
  neither vendor encodes speed in the port name.  The
  `interface_type` canonical field still degrades because both
  codecs infer it from the name shape, but the inference defaults
  match.

Loopback and Vxlan interface types:

* Arista's `Loopback0` (router-id / VTEP) has no Aruba equivalent
  on the `aruba_aoss` codec — Aruba does support loopback
  interfaces in firmware but the codec does not advertise the
  path; Aruba render drops `Loopback<N>` records.
* Arista's `Vxlan1` (VTEP) drops with the rest of the VXLAN
  surface — see `vxlan_unsupported.md`.

The Arista synthetic kitchen-sink uses Ethernet1-7,
Port-Channel10, Port-Channel20, Loopback0, Management1, Vlan100,
Vlan200, Vxlan1 — exercising all the canonical interface
shapes.  The bare `Ethernet<N>` and `Port-Channel<N>` forms
rename to Aruba's bare-numeric / `Trk<N>` cleanly; loopback and
vxlan drop.

Disposition: **good** for `Ethernet<N>` -> bare-numeric (no
speed-loss); **lossy** for `Port-Channel<N>` -> `Trk<N>`
capitalisation flip; **unsupported** for `Loopback<N>` /
`Vxlan<N>` (Aruba target has no render path).

# Link aggregation (LACP / Port-channel / lagg): Cisco IOS-XE versus OPNsense

## Cisco IOS-XE

Source: Cisco IOS XE LAN Switching Configuration Guide — EtherChannel.

```
interface Port-channel10
 description LAG to dist-sw
 switchport
 switchport mode trunk
 switchport trunk allowed vlan 10,20,30
!
interface GigabitEthernet1/0/47
 channel-group 10 mode active
!
interface GigabitEthernet1/0/48
 channel-group 10 mode active
!
```

The ``Port-channel<N>`` parent interface carries the L2/L3 config;
member interfaces declare ``channel-group <N> mode {active | passive |
on | desirable | auto}``.  ``active`` / ``passive`` are LACP;
``on`` is static; ``desirable`` / ``auto`` are PAgP (Cisco-only).

## OPNsense

Source: [OPNsense Devices manual — LAGG tab](https://docs.opnsense.org/manual/other-interfaces.html)
Retrieved: 2026-04-30

OPNsense models link aggregation via FreeBSD's ``lagg(4)`` driver:

```xml
<opnsense>
  <laggs>
    <lagg>
      <laggif>lagg0</laggif>
      <members>em0,em1</members>
      <proto>lacp</proto>
      <descr>Uplink LAG</descr>
    </lagg>
  </laggs>
</opnsense>
```

Notable shape:

- ``<laggif>`` is the synthesised lagg device name (``lagg0``,
  ``lagg1``, ...).  Operators reference it by this name when
  assigning to a zone (``<lan>/<if>lagg0</if>``).
- ``<members>`` is a COMMA-SEPARATED list of physical NIC names
  inside a single element, not repeated child elements.
- ``<proto>`` accepts ``lacp`` (LACP active), ``failover``,
  ``loadbalance``, ``roundrobin``.  No equivalent of LACP-passive
  (FreeBSD's ``lagg(4)`` always advertises actively when ``lacp`` is
  selected); no equivalent of Cisco PAgP modes.

The OPNsense codec parses ``<laggs>/<lagg>`` blocks into
``CanonicalLAG`` records and reverse-links the canonical
``CanonicalInterface.lag_member_of`` back-pointer for each member.

## Cross-vendor mapping

Canonical fields (see ``CanonicalLAG``):

```
name: str           # vendor-native name
members: list[str]  # member interface names
mode: str           # "active" | "passive" | "static"
```

Cisco -> OPNsense:

- ``name``: **lossy** — Cisco's ``Port-channel10`` does not survive
  literally; OPNsense uses sequential ``lagg<N>`` names per the
  ``lagg(4)`` driver.  Port-rename mesh handles the conversion.
- ``members``: **good** — direct mapping (canonical list ↔
  comma-separated ``<members>`` string).  Member interface name
  translation runs through the per-pane port-rename surface.
- ``mode``: **lossy** — Cisco LACP modes (``active``, ``passive``)
  collapse to OPNsense's single ``lacp`` proto.  ``passive`` LACP is
  not directly representable on OPNsense; renders as ``lacp`` and
  the device advertises actively.  ``static`` Cisco mode (``on``)
  has no LACP packet exchange and maps loosely to OPNsense's
  ``loadbalance`` or ``failover`` (which are also non-LACP) — the
  semantics differ.

Disposition: **lossy** at the field level.  At the WIRE-UP level:
the OPNsense codec parses ``<laggs>`` (per ``parse.py``) but the
codec's capability matrix does not currently advertise ``/lag/aggregate``
paths.  Cross-pair render of LAGs is partial.

# Link aggregation: OPNsense versus Cisco IOS-XE

## OPNsense

Source: [OPNsense Devices manual — LAGG tab](https://docs.opnsense.org/manual/other-interfaces.html)
Retrieved: 2026-04-30
Source: [FreeBSD lagg(4)](https://man.freebsd.org/cgi/man.cgi?query=lagg&sektion=4)

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

- ``<laggif>`` is the synthesised ``lagg<N>`` device name.
- ``<members>`` is comma-separated NIC names in a single element.
- ``<proto>``: ``lacp`` (LACP active), ``failover``, ``loadbalance``,
  ``roundrobin``.

The OPNsense codec parses ``<laggs>/<lagg>`` into ``CanonicalLAG``
and reverse-links members.  ``<proto>lacp</proto>`` maps to mode
``active``; ``failover``, which by default accepts traffic only on
the active port and needs no aggregate on the peer, to
``active-backup``; ``fec``, ``loadbalance`` and ``roundrobin``
(static: ``loadbalance`` "does not negotiate aggregation with the
peer", lagg(4)) to ``static``; and ``none``, which passes no
traffic, to ``static`` as well (a known limitation: the tree has no
value for it).

## Cisco IOS-XE

```
interface Port-channel10
 description Uplink LAG
 switchport
 switchport mode trunk
!
interface GigabitEthernet1/0/47
 channel-group 10 mode active
!
```

Cisco LAG modes: ``active`` / ``passive`` (LACP), ``on`` (static),
``desirable`` / ``auto`` (PAgP — Cisco-only).

## Cross-vendor mapping

Canonical fields (see ``CanonicalLAG``):

```
name, members, mode
```

OPNsense -> Cisco:

- ``name``: **lossy** — OPNsense ``lagg0`` doesn't match Cisco's
  ``Port-channel<N>`` form; port-rename mesh handles.  The Cisco
  renderer extracts a numeric index from the canonical name when
  possible (``lagg0`` -> ``Port-channel0``); otherwise synthesises
  a sequential id.
- ``members``: **good** — both vendors model member lists.  Member
  name translation runs through port-rename mesh.
- ``mode``: **lossy** — OPNsense ``lacp`` ↔ Cisco ``active``.
  OPNsense's ``failover`` / ``loadbalance`` / ``roundrobin`` modes
  have no LACP-equivalent on Cisco; the cross-pair render emits
  ``channel-group N mode active`` for ``lacp`` and ``mode on`` for
  the non-LACP modes (lossy semantics — Cisco static-mode is
  link-aggregation without LACP exchange, OPNsense
  ``loadbalance`` / ``roundrobin`` carry per-flow distribution
  rules that don't translate).  ``failover`` needs no aggregate on
  the peer, and IOS-XE has no such bond: its ``mode on`` carries a
  ``! review:`` line and a job warning, and the switch's ports must
  then be configured as that static aggregate (or the host bond
  re-designed).

WIRE-UP DISPOSITION: the OPNsense codec's capability matrix classifies
``/lags/lag/name`` and ``/lags/lag/members`` as supported and
``/lags/lag/mode`` as lossy.

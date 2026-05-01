# Link aggregation: OPNsense versus Cisco IOS-XE

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

- ``<laggif>`` is the synthesised ``lagg<N>`` device name.
- ``<members>`` is comma-separated NIC names in a single element.
- ``<proto>``: ``lacp`` (LACP active), ``failover``, ``loadbalance``,
  ``roundrobin``.

The OPNsense codec parses ``<laggs>/<lagg>`` into ``CanonicalLAG``
and reverse-links members.  ``<proto>lacp</proto>`` maps to mode
``active``.

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
  ``failover``/``loadbalance`` carry per-flow distribution rules
  that don't translate).

WIRE-UP DISPOSITION: the OPNsense codec parses ``<laggs>`` (per
``parse.py``) but the Cisco codec's capability matrix does not
currently advertise ``/lag/aggregate`` paths.  Cross-pair render of
LAGs is partial.

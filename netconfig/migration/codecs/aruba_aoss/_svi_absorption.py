"""
Aruba AOS-S SVI absorption — shared constant + authoritative
explanation of the quirk that ties three distinct code paths in
:mod:`netconfig.migration.codecs.aruba_aoss.codec` together.

The quirk
---------
AOS-S (ProCurve / 2530 / 2540 / 2930) is VLAN-centric: the L3
configuration of a VLAN (its ``ip address``) lives *inside* the
``vlan <id>`` stanza, NOT on a separate ``interface Vlan<N>``
stanza like Cisco IOS(-XE), MikroTik, OPNsense, or FortiGate.

    vlan 10
       name "users"
       untagged 1-24
       ip address 10.0.10.1/24   ← SVI L3 lives here
       exit

On those other vendors the same configuration is split:

    vlan 10
     name users
    !
    interface Vlan10              ← SVI L3 is a separate object
     ip address 10.0.10.1 255.255.255.0

Canonical model
---------------
The canonical tree represents every SVI uniformly as a named
``CanonicalInterface`` with ``name="Vlan<N>"`` and
``interface_type="ianaift:l3ipvlan"``.  Every codec therefore has
to reconcile its native config shape with this canonical shape —
and Aruba's reconciliation involves three separate code paths in
``codec.py`` that *all* have to know about the absorption rule:

1. **Parse** — when the parser reads a ``vlan <id>`` stanza that
   declares ``ip address``, it synthesises a ``Vlan<N>``
   :class:`CanonicalInterface` alongside the :class:`CanonicalVlan`
   so downstream consumers see the L3 record at the canonical
   location.  (``codec.py`` — see the ``vlan.ipv4_addresses``
   branch inside the top-level parse loop.)

2. **Render** — when the renderer emits a ``vlan`` stanza, it
   reads the address list from BOTH the :class:`CanonicalVlan`
   *and* any sibling ``Vlan<N>`` :class:`CanonicalInterface`,
   honouring whichever has data.  The standalone ``Vlan<N>``
   interface is then skipped by the interface-emission pass (it's
   already been absorbed).  (``codec.py`` — see the ``addrs``
   reconciliation inside the VLAN emission loop, plus the
   ``startswith("vlan")`` skip further down.)

3. **Port-name format** — when the cross-vendor port-name
   translator asks the Aruba codec to format an ``svi`` identity,
   it returns ``None`` rather than inventing a name.  The target
   renderer's own VLAN-absorption path handles the L3 data; the
   port-name layer has nothing to contribute.  (``codec.py`` —
   see :meth:`ArubaAOSSCodec.format_port_identity`, the
   ``identity.kind == "svi"`` branch.)

The cross-vendor orchestrator in
:mod:`netconfig.migration.canonical.port_names` respects this by
reading the :attr:`CodecBase.absorbs_svi_into_vlan` class flag —
when ``True`` it suppresses the "no native representation"
warning for SVI identities, since the L3 data reaches the target
via the VLAN stanza render path rather than a port-name rewrite.

Why this module exists
----------------------
Before this extraction the three code paths shared the rule
implicitly — a reader modifying one (e.g. rendering) had to know
to go find the other two (parse + port-name) to keep them
consistent.  Centralising the rule here:

* gives one place to update the documentation when the rule
  changes;
* gives a single grep target (``_svi_absorption``) to find every
  code path that participates in the pattern;
* exports :data:`ABSORBS_SVI_INTO_VLAN` as the single source of
  truth for the class flag, so the value can't diverge from the
  docstring that explains it.

When to touch it
----------------
Update this module when:

* A new code path participates in SVI absorption (add to the
  numbered list above).
* The rule changes shape (e.g. if a future AOS-S version adds a
  separate ``interface Vlan<N>`` concept — unlikely but possible
  if Aruba harmonises toward AOS-CX syntax).
* A sibling codec (AOS-CX, HPE Comware, Huawei) adopts a similar
  pattern — in which case lift this module to a shared
  cross-codec location.

Do NOT add new absorption *logic* here; keep this module as
documentation + constant only.  Logic stays in ``codec.py``
alongside the parse / render / port-name methods that need it.
"""

from __future__ import annotations

#: Whether the Aruba AOS-S codec absorbs SVI L3 config into the
#: VLAN stanza (True) rather than using a separate
#: ``interface Vlan<N>`` (False).
#:
#: This is the single source of truth for
#: :attr:`ArubaAOSSCodec.absorbs_svi_into_vlan` — the codec class
#: imports it from here rather than duplicating the literal.  If
#: the value ever needs to be recomputed (e.g. per-firmware-
#: version toggle) the change happens in one place.
ABSORBS_SVI_INTO_VLAN: bool = True

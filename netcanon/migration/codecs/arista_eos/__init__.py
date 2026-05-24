"""
Arista EOS codec — 6th shipped codec, first DC-switching specialist.

Scope
-----
Parses / renders Arista EOS ``show running-config`` text.  EOS CLI
is a deliberate Cisco-IOS dialect but with several divergences that
warrant a distinct codec rather than folding into ``cisco_iosxe_cli``:

    * Port naming: ``Ethernet1`` (flat, no speed prefix) not Cisco's
      ``GigabitEthernet0/1``.  Speed comes from the port-profile /
      transceiver metadata rather than the name.  Breakouts use
      2-part slash: ``Ethernet50/1`` ... ``Ethernet50/4``.
    * IP-address form: CIDR (``10.0.0.1/31``) not dotted-mask
      (``10.0.0.1 255.255.255.254``).
    * Local-user grammar: ``username X role <name>`` replaces Cisco's
      ``privilege <N>`` semantics; password algorithm labels are
      explicit (``secret sha512 $6$...``, ``secret 5 $1$...``).
    * Port-channel name: capitalised ``Port-Channel1``, not Cisco's
      ``Port-channel1``.  CanonicalLAG.name preserves the case.
    * Default L2/L3: physical interfaces default to L2
      (``switchport`` implicit); ``no switchport`` flips to L3.  On
      Cisco IOS-XE the L2/L3 default varies by platform and the
      explicit mode setting is always present.

Supported / lossy / unsupported xpaths: see ``_CAPS`` on
:class:`.codec.AristaEOSCodec`.  Tier-3 parse-tolerant stanzas
(BGP/OSPF, MLAG/VXLAN/VRF, eAPI, STP, AAA, TerminAttr) are
detected and routed to ``CanonicalIntent.dropped_tier3_sections``
for the migrate-page banner.

Direction: ``bidirectional``.
Certainty: ``certified``.

Module layout:
    * codec.py — ``AristaEOSCodec`` class (metadata, delegation,
                 probe, port-name bridges)
    * parse.py — line-scan + per-stanza dispatch over EOS
                 ``show running-config`` text
    * render.py — canonical tree → EOS CLI text
    * port_names.py — cross-vendor port-name bridge
"""

from .codec import AristaEOSCodec

__all__ = ["AristaEOSCodec"]

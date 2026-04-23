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

Supported blocks (Tier 1 + Tier 2):
    * hostname, dns domain, ip name-server, ntp server
    * interface Ethernet / Management / Loopback / Vlan /
      Port-Channel, including L3 IP (CIDR), description (quoted),
      shutdown, no switchport, channel-group
    * vlan <N> stanzas with ``name``
    * ip route <dest>/<prefix> <gateway>
    * snmp-server community <name> <ro|rw>, snmp-server host
    * username <name> role <role> {nopassword | secret <alg> <hash>}

Silently ignored (Tier 3 — parse-tolerant):
    * router bgp / router ospf — neighbour tables, redistribution
    * mlag / vxlan / vrf / ip vrf forwarding
    * management api http-commands — eAPI enable
    * spanning-tree mode / aaa authentication / daemon TerminAttr

Module layout:
    * codec.py — parse/render/probe entry class
    * port_names.py — cross-vendor port-name bridge
"""

from .codec import AristaEOSCodec

__all__ = ["AristaEOSCodec"]

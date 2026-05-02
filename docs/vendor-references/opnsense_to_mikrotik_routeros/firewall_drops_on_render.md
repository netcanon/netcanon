# Firewall / NAT / VPN cross-vendor scope: OPNsense source -> RouterOS target

Both vendors carry rich firewall / NAT / VPN feature sets, but
**neither vendor's native rules survive cross-vendor migration**:

## Source side: OPNsense unsupported on canonical

OPNsense's ``<filter>`` (firewall rules), ``<nat>`` (translation
rules), ``<openvpn>``, ``<ipsec>``, ``<wireguard>``, ``<captiveportal>``
and plugin-state blocks are **NOT in canonical scope** on the
OPNsense codec — its capability matrix lists ``/filter/rule`` and
``/nat/outbound`` under unsupported.  These are parse-and-ignored on
the OPNsense side; canonical never sees them.

## Target side: RouterOS Tier-3

The MikroTik codec lists ``/filter/rule`` and ``/nat/rule`` as
unsupported (Tier-3, informational only).  Even if the canonical
surface DID carry firewall / NAT intent, the RouterOS render path
would emit no ``/ip firewall filter`` / ``/ip firewall nat`` blocks.

## What this means in practice

Cross-vendor migration of OPNsense -> RouterOS **never auto-renders
firewall / NAT / VPN intent**.  OPNsense ``<filter><rule>`` content
never reaches the canonical translation layer (parse-and-ignored on
the OPNsense side); the RouterOS target receives no firewall config.

Operators must:

1. Review the OPNsense source firewall / NAT / VPN content via the
   OPNsense GUI or by reading ``config.xml`` directly.
2. Recreate the equivalent RouterOS rules manually under
   ``/ip firewall filter``, ``/ip firewall nat``, ``/ip firewall
   mangle``, ``/ip ipsec`` and ``/interface ovpn-server`` /
   ``/interface wireguard``.
3. Recreate captive-portal (OPNsense plugin) as a RouterOS hotspot
   if needed (``/ip hotspot``).

This is the dominant cross-vendor information loss path on this
direction by design — both codecs explicitly route firewall / NAT /
VPN state outside the canonical translation layer.

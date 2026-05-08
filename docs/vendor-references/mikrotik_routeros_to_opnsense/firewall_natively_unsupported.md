# Firewall / NAT / VPN cross-vendor scope: RouterOS source -> OPNsense target

Both vendors carry rich firewall / NAT / VPN feature sets, but
**neither vendor's native rules survive cross-vendor migration**:

## Source side: RouterOS Tier-3

The RouterOS source carries ``/ip firewall filter`` /
``/ip firewall nat`` / ``/ip firewall mangle`` / ``/ip ipsec`` /
``/ip vpn-pptp-server`` / ``/interface ovpn-server`` / ``/queue tree``
/ ``/queue simple`` / ``/system script`` / ``/system scheduler``
content.  These are Tier-3 (informational) on the canonical surface
— the MikroTik codec lists them as unsupported in its capability
matrix and routes them into ``raw_sections`` for operator review.
They never reach the canonical translation layer.

## Target side: OPNsense unsupported

OPNsense's canonical-portable surface (the codec's capability matrix
``supported[]``) excludes:

- ``/filter/rule`` (firewall rules require netcanon-ext YANG —
  capability matrix unsupported entry).
- ``/nat/outbound`` (NAT translation requires careful semantic
  mapping to OPNsense's stateful engine — capability matrix
  unsupported entry).

OPNsense-side firewall / NAT / IPsec / OpenVPN / WireGuard /
captive-portal / plugin state would be unsupported on the inverse
direction.

## What this means in practice

Cross-vendor migration of RouterOS -> OPNsense **never auto-renders
firewall / NAT / VPN intent**.  RouterOS ``/ip firewall filter`` rules
land in ``raw_sections`` (visible in the operator review pane but not
emitted as XML) and the OPNsense target receives no ``<filter>`` /
``<nat>`` block at all.

Operators must:

1. Review the RouterOS-source firewall content in the validation
   report (raw_sections).
2. Recreate the equivalent OPNsense rules manually via the GUI or
   ``<filter><rule>`` XML blocks.
3. Recreate NAT translations via OPNsense's ``<nat><outbound>`` and
   ``<nat><onetoone>`` blocks.
4. Recreate VPN endpoints via OPNsense's ``<openvpn>`` /
   ``<ipsec>`` / ``<wireguard>`` plugin configurations.

This is the dominant cross-vendor information loss path on this
direction and is a documented architectural decision (Tier-3 by
design — see ``netcanon/migration/canonical/intent.py`` module
docstring).

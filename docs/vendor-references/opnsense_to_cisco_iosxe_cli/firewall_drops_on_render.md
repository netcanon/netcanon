# Firewall rules / NAT / VPN / captive portal: OPNsense versus Cisco IOS-XE

## OPNsense

OPNsense's primary role is firewalling.  Its config.xml carries:

- ``<filter><rule>`` — pf-based stateful firewall rules (typically
  the LARGEST section by element count in a real ``config.xml``)
- ``<nat><outbound>`` / ``<nat><onetoone>`` / ``<nat><reflection>``
- ``<openvpn>`` / ``<ipsec>`` / ``<wireguard>`` — VPN tunnels
- ``<captiveportal>`` — captive-portal zones
- ``<traffic_shaper>`` — pf altq / dummynet shaping

The OPNsense codec's capability matrix lists these as
``unsupported``:

- ``/filter/rule`` — "Firewall rules require the netcanon-ext YANG
  module (Phase 2) — OpenConfig has no firewall model."
- ``/nat/outbound`` — "NAT table translation needs netcanon-ext +
  careful semantic mapping to target stateful engines."

VPN and captive-portal blocks are not in the canonical model at all.

## Cisco IOS-XE

Cisco IOS-XE has its own firewall / NAT / VPN feature sets (Zone-Based
Policy Firewall, classic NAT, IPsec / GRE / DMVPN), but the
``cisco_iosxe_cli`` codec lists them as out-of-scope:

> Limitations: Routing protocols (BGP/OSPF), ACLs, crypto, AAA-policy,
> QoS, and route-maps are silently skipped on parse and not emitted on
> render — out of canonical scope.

## Cross-vendor mapping

The OPNsense source / Cisco target migration drops:

- ``filter`` rules — never reach the canonical surface; the
  validation report surfaces them via ``raw_sections`` only when the
  parser routes them there (currently the OPNsense parser does not).
- ``nat`` blocks — same as ``filter``.
- ``openvpn`` / ``ipsec`` / ``wireguard`` — same.
- ``captiveportal`` — same.
- ``traffic_shaper`` — same.

Disposition: **unsupported** — the firewall/NAT/VPN cross-vendor
surface is intentionally out of canonical scope.  Operators
migrating an OPNsense firewall to a Cisco router should expect the
firewall semantics to be re-implemented as ``access-list`` /
``ip nat`` / ``crypto`` / ``policy-map`` constructs manually on
the Cisco side, with very different syntax.

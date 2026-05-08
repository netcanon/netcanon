# Firewall rules / NAT / VPN: Cisco IOS-XE versus OPNsense

## Cisco IOS-XE

Cisco IOS-XE has multiple firewall / NAT / VPN feature sets:

- IOS Zone-Based Policy Firewall (ZBFW)
- ``access-list`` / ``ip access-group`` style ACLs
- Classic NAT (``ip nat inside`` / ``ip nat outside``)
- IPsec / GRE / DMVPN VPN constructs

These are out of canonical scope on the IOS-XE codec — see the
Limitations section of ``netcanon/migration/codecs/cisco_iosxe_cli/
codec.py``: "Routing protocols (BGP/OSPF), ACLs, crypto, AAA-policy,
QoS, and route-maps are silently skipped on parse and not emitted on
render".  None reach the canonical surface.

## OPNsense

OPNsense's primary role is firewalling.  Its config.xml carries:

- ``<filter><rule>`` — pf-based stateful firewall rules
- ``<nat><outbound>`` / ``<nat><onetoone>`` — outbound and 1:1 NAT
- ``<openvpn>`` / ``<ipsec>`` / ``<wireguard>`` — VPN tunnels
- ``<captiveportal>`` — captive-portal zones
- ``<traffic_shaper>`` — pf altq / dummynet shaping

The OPNsense codec's capability matrix explicitly lists these as
``unsupported``:

- ``/filter/rule`` — "Firewall rules require the netcanon-ext YANG
  module (Phase 2) — OpenConfig has no firewall model."
- ``/nat/outbound`` — "NAT table translation needs netcanon-ext +
  careful semantic mapping to target stateful engines."

VPN constructs are not in the canonical model at all.

## Cross-vendor mapping

The Cisco-source / OPNsense-target migration drops:

- ``raw_sections`` may carry Cisco ACL / NAT / crypto stanzas as
  Tier-3 informational text, but these are never auto-rendered into
  OPNsense XML.  Operators see them in the validation report and
  must re-create equivalent OPNsense rules manually.

Disposition: **unsupported** — the firewall/NAT/VPN cross-vendor
surface is intentionally out of canonical scope on both sides.
This is documented as a known gap and the cross-pair migration banner
surfaces the limitation.

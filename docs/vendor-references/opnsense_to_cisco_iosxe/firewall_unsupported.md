# OPNsense firewall / NAT / VPN — out of canonical scope

Source: [OPNsense Firewall manual](https://docs.opnsense.org/manual/firewall.html)
Retrieved: 2026-05-01

Source: `netcanon.migration.codecs.opnsense.codec.OPNsenseCodec._CAPS.unsupported`
(in-tree authoritative declaration)
Retrieved: 2026-05-01

## OPNsense's primary feature surface

OPNsense's primary role is firewalling.  `config.xml` carries large
blocks for:

- `<filter>/<rule>` — pf rule entries.
- `<nat>/<outbound>`, `<nat>/<rule>` — outbound and 1:1 NAT.
- `<openvpn>/<openvpn-server>`, `<ipsec>` — VPN tunnels.
- `<captiveportal>` — captive portal zones.

These represent the bulk of an operational OPNsense config.  None
of them are in canonical scope for cross-vendor migration.

## Codec declares unsupported

The OPNsense codec's `CapabilityMatrix._CAPS` declares these under
`unsupported`:

- `/filter/rule` — "Firewall rules require the netcanon-ext YANG
  module (Phase 2) — OpenConfig has no firewall model."
- `/nat/outbound` — "NAT table translation needs netcanon-ext +
  careful semantic mapping to target stateful engines."

The OPNsense parser does NOT route these subtrees into
`raw_sections` Tier-3 carry-through either; they're parse-and-
ignored entirely.  An OPNsense source's firewall / NAT / VPN
content is invisible to any cross-pair consumer.

## Cisco target side — also out of canonical scope

The cisco_iosxe codec's matrix doesn't list ACL / NAT / crypto
surfaces under `supported` either.  Cisco IOS-XE running-config
carries these via `ip access-list`, `ip nat`, `crypto ikev2`,
`crypto map`, etc., but they're well outside the OpenConfig
canonical surface this codec walks.

For both ends of this pair, firewall / NAT / VPN configuration is
operator-curated post-migration: there's no meaningful canonical
shape that round-trips between a stateful packet filter and a
zone-based router ACL.

## Cross-pair disposition

| Canonical field | Disposition | Reason |
|---|---|---|
| `raw_sections` | not_applicable | Tier-3 dict by design; firewall / NAT / VPN never reach canonical anyway |

These vendor-private surfaces drop silently on the cross-pair.
The validation report surfaces no banner because there's nothing
in the canonical tree to flag.  Operators planning an OPNsense ->
Cisco IOS-XE migration must hand-translate the security policy
themselves.

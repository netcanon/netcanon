# LAGs + DHCP server — NETCONF source rendered to IOS-XE CLI

For full bidirectional content (CLI form, openconfig-if-aggregate
form, DHCP server discussion) see the sibling file
`../cisco_iosxe_cli_to_cisco_iosxe/lags-and-dhcp.md`.

## Direction-specific disposition

The OpenConfig NETCONF codec does not parse the
`openconfig-if-aggregate` augment or any DHCP server XML.  Its
parse path walks `<interfaces>` only and extracts name /
description / enabled / type / IPv4 / IPv6.

| Canonical field | NETCONF -> CLI |
|---|---|
| `lags[].name` | not_applicable — parser never populates |
| `lags[].members` | not_applicable |
| `lags[].mode` | not_applicable |
| `interfaces[].lag_member_of` | not_applicable |
| `dhcp_servers` | not_applicable |

Once `openconfig-if-aggregate` is wired (parse the
`<aggregation>` container under each interface and the
`<aggregate-id>` leaf under `<ethernet>`), the cross-pair flips to
`good` for all four LAG fields — same `Port-channel<N>` naming,
same LACP modes (`active`, `passive`, `static`), no capitalisation
divergence.

DHCP server is more nuanced.  OpenConfig has no fully-baked DHCP
server model; bridging the Cisco-IOS-XE-dhcp native YANG into the
canonical `CanonicalDHCPPool` would require a native-YANG codec
sibling.  Disposition is therefore **`unsupported`** going forward
rather than `lossy: deferred` — the gap isn't a Phase-0.5 wire-up
gap, it's a model-coverage gap in OpenConfig itself.

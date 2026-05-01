# Static routes — NETCONF source rendered to IOS-XE CLI

For full bidirectional content (CLI form, OpenConfig
network-instance form, per-VRF discussion) see the sibling file
`../cisco_iosxe_cli_to_cisco_iosxe/static-routes.md`.

## Direction-specific disposition

The OpenConfig NETCONF codec does not parse
`<network-instances><protocols><protocol identifier=STATIC>`.  Its
parse path only walks `<interfaces>`.

| Canonical field | NETCONF -> CLI |
|---|---|
| `static_routes` | not_applicable — parser never populates |

Once the NETCONF codec wires `openconfig-network-instance` parsing,
the cross-pair flips to:

* Default-VRF static routes (destination + gateway + metric) ->
  `good`.  CLI render emits `ip route <DEST> <MASK> <GW> [<metric>]`
  which is byte-identical to what the source device would emit.
* Per-VRF static routes -> `lossy`.  Same canonical-model gap as in
  the CLI -> NETCONF direction: `CanonicalStaticRoute` lacks a
  `vrf` field, so per-VRF routes either drop or all collapse into
  the default VRF on round-trip.  The CLI codec parses `ip route
  vrf X ...` lines today but parse-and-ignores the VRF prefix.

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
* Per-VRF static routes -> `good`.  The canonical
  `CanonicalStaticRoute.vrf` field carries the discriminator, and
  the CLI target codec parses `ip route vrf X ...` lines into it and
  renders them back out (`/routing/static-route/vrf` is `supported`
  on the CLI codec).  Once the NETCONF source parser populates
  per-instance static routes, the VRF survives the round-trip; the
  remaining blocker on this pair is the NETCONF source stub, not the
  canonical schema or the CLI render path.

# VRF / network-instance — NETCONF source rendered to IOS-XE CLI

For full bidirectional content (CLI form, OpenConfig
`<network-instance type=L3VRF>` form, route-target plumbing) see the
sibling file
`../cisco_iosxe_cli_to_cisco_iosxe/vrf-and-network-instance.md`.

## Direction-specific disposition

The OpenConfig NETCONF codec does not parse
`<network-instances><network-instance>` at all.  The CLI codec's
capability matrix lists `/routing-instances/instance` as
`unsupported` for the same reason — the canonical schema exists but
the codec wire-up is deferred.

| Canonical field | NETCONF -> CLI |
|---|---|
| `routing_instances[].name` | not_applicable — parser never populates |
| `routing_instances[].instance_type` | not_applicable |
| `routing_instances[].route_distinguisher` | not_applicable |
| `routing_instances[].rt_imports` | not_applicable |
| `routing_instances[].rt_exports` | not_applicable |
| `routing_instances[].description` | not_applicable |
| `routing_instances[].l3_vni` | not_applicable |

Once both codecs wire VRF parsing (the NETCONF codec via
`openconfig-network-instance`, the CLI codec via the `vrf
definition` block parser), the same-vendor cross-pair will flip to
`good` for everything except `instance_type` (which remains slightly
ambiguous because the CLI form always implies `vrf` whereas
OpenConfig models a discriminated `L3VRF` / `L2VSI` / `L2P2P` enum).

Same-vendor `route_distinguisher` and route-target lists round-trip
verbatim (both codecs consume and emit the same `<asn>:<nn>` /
`<ip>:<nn>` syntax that IOS-XE accepts on the device).

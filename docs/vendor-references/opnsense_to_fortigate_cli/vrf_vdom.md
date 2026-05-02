# VRF / VDOM: OPNsense versus FortiGate FortiOS

Reverse direction.  Forward direction in
`../fortigate_cli_to_opnsense/vrf_vdom.md`.

## OPNsense

Source: [OPNsense routing
docs](https://docs.opnsense.org/manual/) (general FreeBSD routing —
no VRF feature)
Retrieved: 2026-05-01

OPNsense has NO VRF / routing-instance / multi-tenancy primitive in
the base OS.  FreeBSD has a "FIB" (forwarding information base)
mechanism similar in spirit to VRFs (`setfib`), but OPNsense's
`config.xml` does not surface it.  Multi-tenant deployments
typically use multiple OPNsense VMs.

## FortiGate FortiOS

See `../fortigate_cli_to_opnsense/vrf_vdom.md` for the FortiGate-side
shape.  Key points:

- VDOMs are heavyweight multi-tenant containers (independent policy,
  address books, admin sessions, routing tables).
- VRFs (FortiOS 7.0+) are per-interface integer IDs (range 0-251).

## Cross-vendor mapping

Canonical fields covered:

```
CanonicalIntent.routing_instances: list[CanonicalRoutingInstance]
CanonicalInterface.vrf: str
```

OPNsense -> FortiGate:

- **not_applicable** — OPNsense source has no VRF schema in
  config.xml, so canonical `routing_instances` and
  `CanonicalInterface.vrf` are always empty on OPNsense parse.
- FortiGate target accepts `set vrf <id>` per-interface (FortiOS
  7.0+) but the FortiGate codec does not currently parse / render
  this in v1; the canonical empty list maps to nothing on render
  regardless.
- Note the asymmetry from the forward direction: forward FortiGate ->
  OPNsense, the disposition is **unsupported** (FortiGate may carry
  VRFs but OPNsense can't accept).  Reverse OPNsense -> FortiGate,
  the disposition is **not_applicable** (OPNsense never carries
  VRFs to begin with).

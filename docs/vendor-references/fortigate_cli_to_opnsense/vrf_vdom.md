# VRF / VDOM: FortiGate FortiOS versus OPNsense

## FortiGate FortiOS

Source: [FortiGate / FortiOS 7.4 Administration Guide — VDOMs and
VRFs](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/)
Retrieved: 2026-05-01

FortiGate has TWO multi-tenancy primitives:

```
config vdom
    edit "tenant-a"
    next
    edit "tenant-b"
    next
end

config system interface
    edit "port5"
        set vdom "tenant-a"
        set vrf 10
    next
end
```

- **VDOMs** are heavyweight multi-tenant containers.  Each VDOM has
  its own firewall policy table, address books, admin sessions,
  routing tables, system-services configuration.  Inter-VDOM
  routing requires explicit VDOM-link interfaces.
- **VRFs** (FortiOS 7.0+) are per-interface integer IDs (range
  0-251).  A route on a VRF-tagged interface stays in that VRF's
  routing table.  No name, no RD, no RT — just an integer scope.

## OPNsense

Source: [OPNsense routing
docs](https://docs.opnsense.org/manual/) (general FreeBSD
routing — no VRF feature)
Retrieved: 2026-05-01

OPNsense has NO VRF / routing-instance / multi-tenancy primitive in
the base OS.  FreeBSD has a "FIB" (forwarding information base)
mechanism similar in spirit to VRFs (`setfib`), but OPNsense's
`config.xml` does not surface it.  Multi-tenant deployments
typically use multiple OPNsense VMs.

## Cross-vendor mapping

Canonical fields covered:

```
CanonicalIntent.routing_instances: list[CanonicalRoutingInstance]
CanonicalInterface.vrf: str
```

FortiGate -> OPNsense:

- **unsupported** — Multiple loss vectors:
  1. The FortiGate codec does NOT currently parse `set vrf <id>`
     into `CanonicalInterface.vrf` in v1.
  2. Even if it did, there is no destination on OPNsense — `config.xml`
     has no VRF schema.  The OPNsense codec capability matrix lists
     `/routing-instances/instance` under unsupported.
  3. VDOMs are a heavyweight multi-tenancy primitive that requires
     per-VDOM canonical-tree splitting (a fundamentally different
     pipeline than the per-config canonical tree v1 implements).
     Out of v1 scope.
- Cross-vendor migration of VRF / VDOM intent is therefore not
  possible in v1.  Operators consolidating multi-tenant FortiGate
  into OPNsense must deploy multiple OPNsense instances, one per
  VDOM, and manually re-create per-tenant config.

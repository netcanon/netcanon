# VRF / VDOMs — unsupported on FortiGate -> Juniper Junos in v1

## FortiGate model: VDOMs + per-interface integer VRF

Source: [FortiGate / FortiOS Administration Guide — Virtual Domains (VDOMs)](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/).
Retrieved: 2026-05-01.

FortiGate has two distinct multi-tenancy primitives:

1. **VDOMs (Virtual Domains)** — heavyweight multi-tenancy with
   independent firewall policy tables, address objects, admin
   sessions, and routing tables.  Enabled via
   `config system global / set vdom-mode multi-vdom`.  Each VDOM
   is configured under `config vdom / edit <name> / config ...`.
2. **Per-interface integer VRF** — FortiOS 7.0+ supports
   `set vrf <id>` on routed interfaces (range 0-251, default 0).
   This is closer in spirit to Cisco VRF-Lite but uses integer
   keys with no name, no RD, no RT.

Neither is parsed into canonical CanonicalRoutingInstance records
in v1:

- VDOMs require per-VDOM canonical-tree splitting (out of the v1
  pipeline scope; the migration model is one CanonicalIntent per
  device).
- Per-interface integer VRF is parse-and-ignore in v1 (FortiGate
  codec capability matrix does not advertise the path).

## Junos model: routing-instances with instance-type discriminator

Source: [Junos `instance-type` statement reference](https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/instance-type-edit-routing-instances.html).
Retrieved: 2026-05-01.

Junos models VRF and tenant separation under `set routing-instances
<name> ...`:

```
set routing-instances TENANT_A instance-type vrf
set routing-instances TENANT_A description "Tenant A L3 VRF"
set routing-instances TENANT_A route-distinguisher 172.16.0.1:10000
set routing-instances TENANT_A vrf-target target:65000:10000
set routing-instances TENANT_A interface irb.100
set routing-instances TENANT_A protocols evpn ip-prefix-routes vni 50100
#
set routing-instances TENANT_B instance-type mac-vrf
set routing-instances TENANT_B route-distinguisher 172.16.0.1:20000
#
set routing-instances RTR_C instance-type virtual-router
```

The `instance-type` discriminator selects the semantic:

- **vrf** — L3 VPN MP-BGP-imported VRF (the cross-vendor baseline).
- **virtual-router** — lightweight, no MP-BGP plumbing.
- **mac-vrf** — L2 EVPN MAC-VRF (broadcast domain in EVPN-VXLAN).
- **l2vpn** — Layer-2 VPN (VPLS / EVPN E-LINE / E-LAN).
- **evpn** — full EVPN routing-instance.

## Disposition on cross-vendor migration

- **routing_instances** — `unsupported` on FortiGate -> Junos in v1.
  FortiGate codec doesn't populate CanonicalRoutingInstance from
  source (`set vrf <id>` parse-and-ignore; VDOM requires
  per-tree-split).
- **interfaces[].vrf** — `unsupported` for the same reason.
- **routing_instances[].instance_type** — even when v2 wires
  FortiGate parse, the integer VRF model has no source intent for
  non-`vrf` types (mac-vrf, l2vpn, evpn) which are L2-fabric
  constructs FortiGate doesn't model at all.

## Lands when …

The FortiGate codec gains:

1. Per-VDOM canonical-tree splitting (enabling VDOM -> Junos
   logical-system mapping).
2. Per-interface `set vrf <id>` parse into
   CanonicalRoutingInstance with operator-curated lookup tables
   for integer-id -> name + RD + RT.

Both are deferred to subsequent audit passes.

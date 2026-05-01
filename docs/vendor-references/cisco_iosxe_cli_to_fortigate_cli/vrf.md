# VRF / VDOM: Cisco IOS-XE versus FortiGate FortiOS

## Cisco IOS-XE

Source: Cisco IOS XE Multiprotocol VPN Configuration Guide — VRF Lite
chapter.

Cisco models VRFs via `vrf definition <name>` blocks plus per-
interface `vrf forwarding <name>`:

```
vrf definition MGMT
 description "Management VRF"
 rd 65000:100
 address-family ipv4
  route-target export 65000:100
  route-target import 65000:100
 exit-address-family
!
interface GigabitEthernet0/0/0
 vrf forwarding MGMT
 ip address 10.0.0.1 255.255.255.0
```

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide — Virtual Domains (VDOMs)](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/) — `config vdom` chapter.
Source: [Fortinet FortiOS Cookbook — VDOM examples](https://docs.fortinet.com/document/fortigate/7.4.0/cookbook/).
Source: FortiOS CLI Reference — `config system interface / set vrf`
(VRF integer ID per-interface; FortiOS 7.0+).
Retrieved: 2026-04-30

FortiGate has **two distinct multi-tenancy primitives**:

### 1. VDOMs (Virtual Domains)

Heavyweight: each VDOM is a near-independent firewall instance with
its own routing table, firewall policies, address objects, and admin
profile.  Configured via:

```
config global
    set vdom-mode multi-vdom
end
config vdom
edit "MGMT"
    config system interface
        edit "port1"
            ...
        next
    end
    config router static
        edit 1
            ...
        next
    end
end
```

VDOMs do not map to Cisco VRFs cleanly — VDOMs carry their own
firewall policies, routing tables, address objects, and even admin
sessions.  Cisco VRFs are L3-isolation-only.

### 2. Per-interface VRF integer ID (FortiOS 7.0+)

Lightweight: single integer (0 to 251) per interface marks routing-
table membership.  Configured per-interface:

```
config system interface
    edit "port1"
        set vrf 10
        set ip 10.0.0.1 255.255.255.0
    next
end
config router static
    edit 1
        set dst 10.1.0.0 255.255.0.0
        set gateway 10.0.0.2
        set vrf 10
    next
end
```

This is the closer analogue to Cisco's VRF-Lite — a per-interface
routing-table tag without firewall-policy or address-object
isolation.  Numeric IDs only (no string names); operator-curated
documentation is the only way to map names <-> IDs.

## Cross-vendor mapping

Canonical surface:

```
class CanonicalRoutingInstance(BaseModel):
    name: str
    instance_type: str = "vrf"
    route_distinguisher: str = ""
    rt_imports: list[str] = Field(default_factory=list)
    rt_exports: list[str] = Field(default_factory=list)
    description: str = ""
    l3_vni: int | None = None

class CanonicalInterface:
    vrf: str = ""                   # back-pointer to routing-instance name
```

Both codecs list `/routing-instances/instance` as `unsupported` in
their capability matrices:

- **Cisco IOS-XE codec** explicitly parse-and-ignores `vrf
  definition` and `vrf forwarding` (see `_CAPS.unsupported`).
- **FortiGate codec** has no per-interface VRF integer wired into
  the canonical model; the codec parses `set vrf <id>` only as part
  of `raw_sections` (if at all).

Cross-vendor migration of VRF intent is therefore **unsupported**
in v1.  More fundamentally:

- Cisco's named-VRF / RD / RT / route-target model maps poorly to
  FortiGate's integer-tag model (no RD, no RT, no name).
- Cross-vendor migration of VDOMs (the FortiGate primitive that
  best preserves Cisco-VRF-like isolation semantics) would require
  a fundamentally different pipeline structure (one canonical tree
  per VDOM, not one tree per device).  Out of scope for v1.

Disposition for `routing_instances`: **unsupported**.
Reason: canonical schema gap (Cisco IOS-XE codec parse-and-ignores
VRF declarations) plus model divergence (Cisco named VRFs versus
FortiGate integer VRF IDs versus FortiGate VDOMs).

Disposition for per-interface `interfaces[].vrf`: **unsupported**.
Same rationale.

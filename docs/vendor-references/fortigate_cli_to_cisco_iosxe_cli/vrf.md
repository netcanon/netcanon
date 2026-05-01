# VRF / VDOM: FortiGate FortiOS versus Cisco IOS-XE

Reverse-direction sibling of
[`../cisco_iosxe_cli_to_fortigate_cli/vrf.md`](../cisco_iosxe_cli_to_fortigate_cli/vrf.md).
Source URLs unchanged.

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide — VDOMs](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/).
Source: FortiOS CLI Reference — `config system interface / set vrf`
(integer per-interface; FortiOS 7.0+).
Retrieved: 2026-04-30

FortiGate has two distinct multi-tenancy primitives:

1. **VDOMs** (heavyweight) — full firewall-instance isolation.
2. **Per-interface integer VRF ID** (FortiOS 7.0+) — lightweight
   routing-table tag.

```
# Per-interface integer VRF (FortiOS 7.0+):
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

## Cisco IOS-XE

Source: Cisco IOS XE Multiprotocol VPN Configuration Guide — VRF
Lite.

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

## Cross-vendor mapping (FortiGate -> Cisco)

Canonical surface (same as forward direction):

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
    vrf: str = ""
```

Both codecs list `/routing-instances/instance` as `unsupported` in
their capability matrices:

- **FortiGate codec**: `set vrf <id>` is parse-and-ignored in v1.
  No canonical record of FortiOS-side VRF tags.
- **Cisco IOS-XE codec**: `vrf definition` and `vrf forwarding`
  are parse-and-ignored in v1.

Cross-vendor migration of FortiGate VRF intent to Cisco is
**unsupported**.  More fundamentally:

- FortiGate's per-interface integer VRF IDs (no name, no RD, no
  RT) cannot be expressed as Cisco's named-VRF + RD + RT model
  without operator-curated lookup tables.
- VDOMs are not a single-tree concept — each VDOM is effectively
  its own device's configuration.  Cross-vendor migration of a
  multi-VDOM FortiGate would require splitting the canonical tree
  per-VDOM, which is out of v1 pipeline structure.

Disposition for `routing_instances`: **unsupported**.
Disposition for per-interface `interfaces[].vrf`: **unsupported**.

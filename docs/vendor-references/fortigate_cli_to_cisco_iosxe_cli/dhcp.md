# DHCP server: FortiGate FortiOS versus Cisco IOS-XE

Reverse-direction sibling of
[`../cisco_iosxe_cli_to_fortigate_cli/dhcp.md`](../cisco_iosxe_cli_to_fortigate_cli/dhcp.md).
Source URLs unchanged.

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide — DHCP server](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/) — `config system dhcp server`.
Retrieved: 2026-04-30

```
config system dhcp server
    edit 1
        set lease-time 86400
        set default-gateway 10.0.100.1
        set netmask 255.255.255.0
        set interface "VL_100"
        set dns-service specify
        set dns-server1 10.0.0.53
        set dns-server2 10.0.0.54
        set domain "example.com"
        config ip-range
            edit 1
                set start-ip 10.0.100.10
                set end-ip 10.0.100.200
            next
        end
    next
end
```

## Cisco IOS-XE

Source: Cisco IOS XE IP Addressing Configuration Guide — DHCP.

```
ip dhcp pool DATA-POOL
 network 10.0.100.0 255.255.255.0
 default-router 10.0.100.1
 dns-server 10.0.0.53 10.0.0.54
 lease 7
 domain-name example.com
!
ip dhcp excluded-address 10.0.100.1 10.0.100.10
ip dhcp excluded-address 10.0.100.201 10.0.100.254
```

## Cross-vendor mapping (FortiGate -> Cisco)

Canonical surface (same as forward direction):

```
class CanonicalDHCPPool(BaseModel):
    interface: str = ""
    network: str = ""
    start_ip: str = ""
    end_ip: str = ""
    gateway: str = ""
    dns_servers: list[str] = Field(default_factory=list)
    lease_time: int = 86400         # seconds
    domain_name: str = ""
```

The Cisco IOS-XE codec capability matrix does **not** advertise
`/dhcp/pool` paths under `supported`, so cross-vendor migration on
FortiGate -> Cisco emits no DHCP-pool blocks regardless of how
many FortiGate pools the source had.

- **interface** — `lossy`.  FortiGate's interface-bound model
  cannot survive directly on Cisco's pool-only model; the
  canonical preserves the interface name but Cisco render currently
  drops it.
- **network** — `lossy`.  Derived from FortiOS `set default-gateway`
  + `set netmask` at parse-time (canonical CIDR).  Cisco render
  would emit `network <ip> <mask>` if DHCP-pool render were wired,
  but the Cisco codec capability matrix lists DHCP as not-yet-
  supported on render.
- **start_ip / end_ip** — `lossy`.  FortiOS's positive range
  doesn't translate cleanly to Cisco's `excluded-address`
  inverse model without computing the complement.  Canonical
  carries the range; Cisco render is not wired to translate it.
- **gateway** — `lossy`.  Direct map exists at the schema level
  but Cisco DHCP render path is unwired.
- **dns_servers** — `lossy`.  Cisco accepts arbitrarily many in
  one `dns-server` line; canonical preserves the list but Cisco
  render-path gap is the bottleneck.
- **lease_time** — `lossy`.  Unit conversion: FortiOS seconds
  (86400) to Cisco days (`lease 1`) is straightforward; canonical
  stores seconds.
- **domain_name** — `lossy`.  Direct map exists but Cisco render
  path unwired.

Disposition for DHCP pools overall: **lossy**.  Reason: Cisco
IOS-XE codec capability matrix does not advertise DHCP render
support; cross-vendor migration on FortiGate -> Cisco drops DHCP
configurations entirely with a banner.  The canonical model would
support the round-trip if Cisco render were wired up — schema gap
is solvable but unscheduled in v1.

# DHCP server: MikroTik RouterOS versus FortiGate FortiOS

## MikroTik RouterOS

Sources:
- [DHCP — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/24805500/DHCP) — three-section form.

Retrieved: 2026-04-30

```
/ip pool
add name=lan_pool ranges=10.0.0.100-10.0.0.200

/ip dhcp-server
add address-pool=lan_pool authoritative=yes disabled=no \
    interface=bridge1 lease-time=1h name=lan-dhcp

/ip dhcp-server network
add address=10.0.0.0/24 gateway=10.0.0.1 \
    dns-server=10.0.0.1,1.1.1.1 domain=lab.example.net
```

A complete DHCP server requires three sections:

1. `/ip pool add name=<NAME> ranges=<START>-<END>` — the address range.
2. `/ip dhcp-server add name=<NAME> address-pool=<POOL> interface=<IFACE> lease-time=<DUR>` — the server instance.
3. `/ip dhcp-server network add address=<CIDR> gateway=<GW> dns-server=<csv> domain=<FQDN>` — the network options.

The MikroTik codec joins the three on parse and emits the three on render.  Lease time accepts duration strings (`8h`, `1d`) or seconds; DNS list is unbounded.

Static leases live on `/ip dhcp-server lease` (not modelled in canonical).  DHCP options 43 / 82 etc. are not modelled.

## FortiGate FortiOS CLI

Sources:
- [FortiGate / FortiOS 7.4 Administration Guide — DHCP servers](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/) — `config system dhcp server`.

Retrieved: 2026-04-30

```
config system dhcp server
    edit 1
        set lease-time 86400
        set default-gateway 10.0.0.1
        set netmask 255.255.255.0
        set interface "port4"
        set dns-service specify
        set dns-server1 10.0.0.1
        set dns-server2 1.1.1.1
        set domain "lab.example.net"
        config ip-range
            edit 1
                set start-ip 10.0.0.100
                set end-ip 10.0.0.200
            next
        end
    next
end
```

FortiGate DHCP is **interface-bound** (one pool per interface).  `set default-gateway` + `set netmask` define the subnet implicitly (FortiOS derives the network).  DNS caps at three (`dns-server1` / `dns-server2` / `dns-server3`).  Lease time is in seconds.

## Cross-vendor mapping (RouterOS → FortiGate)

Canonical surface (per-pool):

```
CanonicalDHCPPool.interface: str
CanonicalDHCPPool.network: str           # CIDR
CanonicalDHCPPool.start_ip: str
CanonicalDHCPPool.end_ip: str
CanonicalDHCPPool.gateway: str
CanonicalDHCPPool.dns_servers: list[str]
CanonicalDHCPPool.lease_time: int        # seconds
CanonicalDHCPPool.domain_name: str
```

- **interface** — `good`.  RouterOS `interface=bridge1` -> FortiOS `set interface "port4"` after the rename mesh.
- **network** — `good`.  RouterOS `address=10.0.0.0/24` populates the canonical CIDR; FortiOS render derives `set netmask` from the prefix length and infers the network from `set default-gateway`.
- **start_ip / end_ip** — `good`.  RouterOS `ranges=10.0.0.100-10.0.0.200` parses to canonical start/end; FortiOS render emits `config ip-range / edit 1 / set start-ip / set end-ip`.  RouterOS multi-range pools (`ranges=A-B,C-D,...`) are uncommon and the MikroTik codec collapses them to the first range; multi-range FortiOS sub-table renders the first range only.
- **gateway** — `good`.  RouterOS `gateway=10.0.0.1` -> FortiOS `set default-gateway 10.0.0.1`.
- **dns_servers** — `lossy`.  RouterOS `dns-server=10.0.0.1,1.1.1.1,8.8.8.8` (unbounded) versus FortiOS three-server cap.  RouterOS-source lists with four+ entries lose the tail on FortiGate render — typical RouterOS deployments carry only two DNS servers, so the loss is uncommon in practice.
- **lease_time** — `good`.  RouterOS `lease-time=1h` parses to canonical seconds (`3600`); FortiOS render emits `set lease-time 3600`.
- **domain_name** — `good`.  RouterOS `domain=lab.example.net` -> FortiOS `set domain "lab.example.net"`.
- **static leases / reservations** — `unsupported`.  RouterOS `/ip dhcp-server lease` and FortiOS `config reserved-address` are both vendor-private and not modelled in canonical.
- **DHCP options** — `unsupported`.  RouterOS `/ip dhcp-server option` (option 43, 82, etc.) and FortiOS `config options` have no canonical field.
- **authoritative flag** — `unsupported`.  RouterOS `authoritative=yes/no` has no canonical field; FortiOS DHCP servers are always authoritative on their bound interface.

# DHCP server: FortiGate FortiOS versus MikroTik RouterOS

## FortiGate FortiOS CLI

Sources:
- [FortiGate / FortiOS 7.4 Administration Guide — DHCP servers](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/) — `config system dhcp server`.

Retrieved: 2026-04-30

```
config system dhcp server
    edit 1
        set lease-time 86400
        set default-gateway 10.10.0.1
        set netmask 255.255.255.0
        set interface "port4"
        set dns-service specify
        set dns-server1 1.1.1.1
        set dns-server2 8.8.8.8
        set domain "lab.example.org"
        config ip-range
            edit 1
                set start-ip 10.10.0.100
                set end-ip 10.10.0.200
            next
        end
    next
end
```

Notable FortiOS specifics:

- DHCP servers live on `config system dhcp server / edit <N>` with numeric edit-ids.
- `set interface "<name>"` binds the pool to a serving interface — the FortiGate model is **interface-bound** (one pool per interface).
- `set default-gateway` + `set netmask` define the subnet implicitly; there is no explicit `network=<CIDR>` directive — FortiOS derives it from gateway + mask.
- `config ip-range` is a sub-table allowing multiple ranges; typical pools have a single range.
- DNS servers: `set dns-service specify` + `set dns-server1` / `set dns-server2` / `set dns-server3` (capped at three).  `set dns-service default` uses the box's primary DNS.
- Lease time is in seconds (`set lease-time 86400` = 24 h).
- Static reservations: `config reserved-address` sub-table; not modelled in canonical.

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
    dns-server=10.0.0.1,1.1.1.1 domain=lab.example.org
```

Notable RouterOS specifics:

- A complete DHCP server requires three sections:
  1. `/ip pool add name=<NAME> ranges=<START>-<END>` — the address range.
  2. `/ip dhcp-server add name=<NAME> address-pool=<POOL> interface=<IFACE> lease-time=<DUR>` — the server instance, bound to a serving interface.
  3. `/ip dhcp-server network add address=<CIDR> gateway=<GW> dns-server=<csv> domain=<FQDN>` — the network-level options.
- Lease time accepts duration strings (`8h`, `1d`, `30m`) or integer seconds.  RouterOS `1h` = FortiOS `3600`.
- DNS servers are `dns-server=10.0.0.1,1.1.1.1` (comma-list, unbounded).
- Static leases live on `/ip dhcp-server lease`; not modelled in canonical.

## Cross-vendor mapping (FortiGate → RouterOS)

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

- **interface** — `good`.  FortiOS `set interface "port4"` populates `interface=port4`; RouterOS render emits `interface=ether4` (after rename mesh) on `/ip dhcp-server`.
- **network** — `good`.  FortiOS gateway + netmask compose to a CIDR (`10.10.0.0/24`); RouterOS render emits `address=10.10.0.0/24` on `/ip dhcp-server network`.
- **start_ip / end_ip** — `good`.  FortiOS `config ip-range` first edit (`set start-ip` / `set end-ip`) parses to canonical; RouterOS render emits `/ip pool add ranges=START-END`.  Multi-range FortiOS pools (rare) collapse to the first range only on canonical.
- **gateway** — `good`.  FortiOS `set default-gateway` -> RouterOS `gateway=` on the network record.
- **dns_servers** — `lossy`.  FortiOS three-server cap (`dns-server1` / `dns-server2` / `dns-server3`) is well within RouterOS's unbounded `dns-server=<csv>`.  No truncation in this direction; loss is only that FortiOS-source pools rarely carry more than two so the RouterOS render is typically smaller than what RouterOS could express.
- **lease_time** — `good`.  FortiOS integer seconds round-trip via canonical; RouterOS render emits the seconds-form or duration-form (`86400` or `1d`) depending on codec preference.
- **domain_name** — `good`.  FortiOS `set domain "..."` -> RouterOS `domain=...` on the network record.
- **static reservations** — `unsupported`.  FortiOS `config reserved-address` and RouterOS `/ip dhcp-server lease` are both vendor-private and not modelled in canonical; cross-vendor migration drops them.
- **DHCP options** — `unsupported`.  FortiOS `config options` and RouterOS `/ip dhcp-server option` (option codes 43, 82, etc.) have no canonical field.

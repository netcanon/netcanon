# DHCP server: FortiGate FortiOS versus Juniper Junos

## FortiGate FortiOS

Source: [FortiGate / FortiOS Administration Guide — Networking / DHCP server (`config system dhcp server`)](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/).
Retrieved: 2026-05-01.

FortiGate scopes DHCP servers per-interface, keyed by numeric edit
ID:

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

- **Interface binding** (`set interface "<name>"`) is mandatory; the
  pool inherits the interface's subnet.
- **Lease in seconds**.
- **Numeric edit IDs** on each pool.
- **Nested `config ip-range`** for the start/end allocation range.
  Multiple ranges supported; canonical model carries one start/end
  pair (only first range survives in v1).
- **DNS server cap**: `dns-server1` / `dns-server2` / `dns-server3`
  (max three).
- **Static reservations**: `config reserved-address` (host-MAC
  bindings).  Not modelled canonically.

## Juniper Junos

Source: [Junos DHCP server topic-map](https://www.juniper.net/documentation/us/en/software/junos/dhcp/topics/topic-map/dhcp-server.html).
Source: [Junos DHCP local-server overview](https://www.juniper.net/documentation/us/en/software/junos/dhcp/topics/concept/dhcp-local-server-overview.html).
Retrieved: 2026-05-01.

Junos splits DHCP server into two stages: a `dhcp-local-server`
binding (which interfaces should run DHCP) plus an `access
address-assignment pool` (the address pool with options):

```
set system services dhcp-local-server group local-pool interface ge-0/0/4.0
#
set access address-assignment pool TENANT_A family inet network 10.10.0.0/24
set access address-assignment pool TENANT_A family inet range LAB-RANGE low 10.10.0.100
set access address-assignment pool TENANT_A family inet range LAB-RANGE high 10.10.0.200
set access address-assignment pool TENANT_A family inet dhcp-attributes router 10.10.0.1
set access address-assignment pool TENANT_A family inet dhcp-attributes name-server 1.1.1.1
set access address-assignment pool TENANT_A family inet dhcp-attributes domain-name "lab.example.org"
set access address-assignment pool TENANT_A family inet dhcp-attributes maximum-lease-time 86400
```

Notable Junos specifics:

- **Two-stage**: `dhcp-local-server` (interface binding, can be
  per-routing-instance) plus `address-assignment pool` (pool
  semantics).
- **Multi-range**: multiple named ranges per pool.
- **DNS unbounded**: `dhcp-attributes name-server X` repeated.
- **Lease in seconds** (`maximum-lease-time`).

## Cross-vendor mapping (FortiGate -> Junos)

Canonical surface (`CanonicalDHCPPool`):

```
class CanonicalDHCPPool(BaseModel):
    interface: str = ""
    network: str = ""               # CIDR
    start_ip: str = ""
    end_ip: str = ""
    gateway: str = ""
    dns_servers: list[str]
    lease_time: int = 86400         # seconds
    domain_name: str = ""
```

- **interface** — `good` after rename mesh.  FortiOS interface name
  -> Junos form (`port4` -> `ge-0/0/4.0`).
- **network** — `good`.  FortiOS netmask + gateway derive the network;
  Junos render emits CIDR directly.
- **start_ip / end_ip** — `lossy`.  FortiOS multi-range collapses to
  single canonical pair; Junos can emit multiple named ranges from
  the same pool but canonical only carries the first.
- **gateway** — `good`.  Direct map.
- **dns_servers** — `good` in this direction (FortiGate cap of 3
  fits Junos's unbounded list).
- **lease_time** — `good`.  Both seconds.
- **domain_name** — `good`.  Direct map.

The canonical model does not carry DHCP options 43 / 60 / 66 / 150
or static reservations; these are vendor-private.

## Cross-vendor mapping (Junos -> FortiGate)

Reverse direction (see also `../juniper_junos_to_fortigate_cli/dhcp.md`):

- **interface** — `lossy`.  Junos pools are not directly
  interface-scoped; the FortiGate render must look up the interface
  owning each pool's network.
- **start_ip / end_ip** — `lossy`.  Junos multi-range drops to first
  on canonical-side.
- **dns_servers** — `lossy` because FortiOS caps at 3.

Disposition for DHCP pools overall: **lossy** in both directions.

# DHCP server: FortiGate FortiOS versus Juniper Junos

> **Update 2026-11-07 — the FortiGate parser reads a pool as its server hands addresses out.**  This page was written when `fortigate_cli` kept a pool's first `config ip-range` and read no `config exclude-range` and no `dns-service`, so a second range and every exclusion were lost, and nothing said so.  The parser now reads every range less every excluded range (Fortinet's CLI reference, `config system dhcp server`) and keeps the largest run, with a row of the sections not translated for any other; gives a pool the DNS servers its `dns-service` names (the interface's own address for `local`, the FortiGate's own for `default`, `dns-server1` to `dns-server4` for `specify`, `0.0.0.0` being none); reads a lease the pool does not state as FortiOS's 604800 seconds and `0` as one that does not end; and leaves out, and says, a pool of `status disable`.  Reserved addresses, DHCP options, NTP servers and the like are a row each.  See `docs/vendors/fortigate.md` § "What translates well".

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
  pair (the largest run of the ranges less the excluded ranges, with
  a row of the sections not translated for any other).
- **DNS server cap**: `dns-server1` to `dns-server4` (max four,
  FortiOS 7.0 and later; 6.2 takes three).
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
  the same pool but canonical only carries the largest run (any
  other is a row of the sections not translated).
- **gateway** — `good`.  Direct map.
- **dns_servers** — `good` in this direction (FortiGate cap of four
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
- **dns_servers** — `lossy` because FortiOS caps at four (a fifth
  is a `# review:` line).

Disposition for DHCP pools overall: **lossy** in both directions.

# DHCP server: Juniper Junos versus FortiGate FortiOS

## Juniper Junos

Source: [Junos DHCP server topic-map](https://www.juniper.net/documentation/us/en/software/junos/dhcp/topics/topic-map/dhcp-server.html).
Source: [Junos DHCP local-server overview](https://www.juniper.net/documentation/us/en/software/junos/dhcp/topics/concept/dhcp-local-server-overview.html).
Retrieved: 2026-05-01.

Junos splits DHCP server into two stages: `dhcp-local-server`
(interface bindings) and `access address-assignment pool` (pool
semantics):

```
set system services dhcp-local-server group local-pool interface ge-0/0/4.0
#
set access address-assignment pool TENANT_A family inet network 10.10.0.0/24
set access address-assignment pool TENANT_A family inet range LAB-RANGE low 10.10.0.100
set access address-assignment pool TENANT_A family inet range LAB-RANGE high 10.10.0.200
set access address-assignment pool TENANT_A family inet dhcp-attributes router 10.10.0.1
set access address-assignment pool TENANT_A family inet dhcp-attributes name-server 1.1.1.1
set access address-assignment pool TENANT_A family inet dhcp-attributes name-server 8.8.8.8
set access address-assignment pool TENANT_A family inet dhcp-attributes domain-name "lab.example.org"
set access address-assignment pool TENANT_A family inet dhcp-attributes maximum-lease-time 86400
```

Notable Junos specifics:

- **Two-stage**: `dhcp-local-server` may be per-routing-instance.
- **Multiple ranges** per pool (named).
- **DNS unbounded**: `name-server X` repeated.
- **Lease in seconds**.
- **VRF-scoped**: `dhcp-local-server` block may sit inside
  `routing-instances <name>`.

## FortiGate FortiOS

Source: [FortiGate / FortiOS Administration Guide — Networking / DHCP server](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/).
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

- **Interface-bound**.
- **DNS cap at 3** (`dns-server1` / `dns-server2` / `dns-server3`).
- **Multiple ranges** allowed (multiple `config ip-range / edit N`).
- **Lease in seconds**.

## Cross-vendor mapping (Junos -> FortiGate)

Canonical surface (`CanonicalDHCPPool`).

- **interface** — `lossy`.  Junos pools are not directly interface-
  scoped; FortiGate render must look up interface owning the pool's
  network.
- **network** — `good`.  CIDR -> FortiGate netmask + gateway derive.
- **start_ip / end_ip** — `lossy`.  Junos multi-range drops to first
  on canonical-side (canonical model has single start/end pair).
- **gateway** — `good`.
- **dns_servers** — `lossy`.  FortiOS caps at 3; Junos source with
  more drops the tail.
- **lease_time** — `good`.  Both seconds.
- **domain_name** — `good`.

## Cross-vendor mapping (FortiGate -> Junos)

Reverse direction (see also `../fortigate_cli_to_juniper_junos/dhcp.md`):

- **interface** — `good` after rename mesh (FortiGate `port4` ->
  Junos `ge-0/0/4.0`).
- **dns_servers** — `good` (FortiGate cap of 3 fits Junos).

Disposition for DHCP pools overall: **lossy** in both directions.

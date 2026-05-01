# DHCP server: Cisco IOS-XE versus FortiGate FortiOS

## Cisco IOS-XE

Source: Cisco IOS XE IP Addressing Configuration Guide — DHCP
chapter.

Cisco models DHCP server pools as named global blocks:

```
ip dhcp pool DATA-POOL
 network 10.0.100.0 255.255.255.0
 default-router 10.0.100.1
 dns-server 10.0.0.53 10.0.0.54
 lease 7
 domain-name example.com
!
ip dhcp excluded-address 10.0.100.1 10.0.100.10
```

The lease time is in days (or `lease <days> <hours> <minutes>`);
the `excluded-address` directive carves out reserved IPs.

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide — Networking / DHCP server](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/) — `config system dhcp server`.
Source: FortiOS CLI Reference — `config system dhcp server`.
Retrieved: 2026-04-30

FortiOS scopes DHCP servers per-interface:

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

Notable FortiOS specifics:

- **`set interface`** binds the pool to a specific FortiGate
  interface; the pool inherits the interface's subnet.  Cisco's
  pool-only model (no interface binding) requires the FortiGate
  codec to look up which interface owns the pool's network on
  cross-vendor render.
- **Lease time in seconds**, unlike Cisco's days/hours/minutes.
  Both codecs normalise to seconds in canonical
  `CanonicalDHCPPool.lease_time`.
- **Numeric edit IDs** on each pool.
- **Nested `config ip-range`** for the start/end allocation range.
  Cisco uses `excluded-address` to subtract from the pool's
  network; FortiGate uses the inverse (range-based assignment).

## Cross-vendor mapping (Cisco -> FortiGate)

Canonical surface:

```
class CanonicalDHCPPool(BaseModel):
    interface: str = ""
    network: str = ""               # CIDR
    start_ip: str = ""
    end_ip: str = ""
    gateway: str = ""
    dns_servers: list[str] = Field(default_factory=list)
    lease_time: int = 86400         # seconds
    domain_name: str = ""
```

- **interface** — `lossy`.  Cisco does not bind pools to interfaces
  (the pool's `network` declares the subnet); FortiGate requires
  an interface binding.  Cross-vendor migration on Cisco -> FortiGate
  requires synthesising the interface name from the canonical
  network — the operator may need to confirm.
- **network** — `lossy`.  Cisco emits `network <ip> <mask>`;
  FortiGate derives the network from `set netmask` + `set
  default-gateway`.  Both codecs round-trip the canonical CIDR.
- **start_ip / end_ip** — `lossy`.  Cisco's `excluded-address`
  inverse model translates imperfectly to FortiGate's positive
  range.  The FortiGate render path emits a single inferred range
  spanning `gateway+1` to the broadcast minus 1; operators should
  confirm post-migration.
- **gateway** — `good`.  Direct map.
- **dns_servers** — `lossy`.  FortiOS caps at three DNS servers
  (`dns-server1` through `dns-server3`); Cisco can carry more.
- **lease_time** — `good` (with unit-conversion caveat — Cisco
  days versus FortiOS seconds; both codecs handle the unit at
  parse-time).
- **domain_name** — `good`.  Direct map.

The canonical model does not carry DHCP options 60 / 66 / 67 / 150
or static reservations (host-MAC bindings); these are vendor-private
and live in `raw_sections` if at all.

Disposition for DHCP pools overall: **lossy**.  Reason: model
divergence (Cisco pool-only versus FortiGate interface-bound) and
range-versus-exclusion semantics require operator review on
cross-vendor migration.

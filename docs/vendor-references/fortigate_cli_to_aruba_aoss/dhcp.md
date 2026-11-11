# DHCP server (FortiGate) versus DHCP relay (Aruba)

> **Update 2026-11-10 — the codec writes the pool.**  This page describes AOS-S as a relay platform.  AOS-S 16.x switches run a DHCP server of their own (HPE's AOS-S Management and Configuration Guide: a `dhcp-server pool`, served on a VLAN that states `dhcp-server`, once `dhcp-server enable` is set), the aruba_aoss parser reads one, and the renderer now writes one as the switch prints it: a `dhcp-server pool` stanza after the VLANs (`default-router`, `dns-server`, `domain-name`, `lease DD:HH:MM`, `network`, `range`), `dhcp-server` in the stanza of the VLAN that serves it, and `dhcp-server enable` last.  A pool is served where the output's VLAN stanza for its interface holds an address of its network; where none does, it is written with a `; review:` line, and the switch serves it only to clients a DHCP relay forwards to it.  A FortiGate pool is served on a port, an aggregate or a VLAN interface, none of which the FortiGate parser makes a VLAN of, so each is written with its review line: the disposition is now `lossy`, for where the pool is served, and the body below, written when it was `unsupported`, is kept as it was.  The reverse direction is `good` (see the sibling page).

This is the reverse-direction sibling of
[`../aruba_aoss_to_fortigate_cli/dhcp.md`](../aruba_aoss_to_fortigate_cli/dhcp.md)
but with a substantively different disposition because the
FortiGate-source DHCP-server pools have **no Aruba target**.

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide — DHCP server](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/).
Retrieved: 2026-04-30

FortiGate is a **first-class DHCP server**:

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
    edit 2
        set lease-time 43200
        set default-gateway 10.30.0.1
        set netmask 255.255.255.0
        set interface "port4.300"
        set dns-service specify
        set dns-server1 9.9.9.9
        set domain "guest.example.org"
        config ip-range
            edit 1
                set start-ip 10.30.0.50
                set end-ip 10.30.0.150
            next
        end
    next
end
```

The FortiGate codec parses `config system dhcp server` blocks into
`CanonicalDHCPPool` records on canonical.

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 IPv4 Configuration Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/IPv4/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S is primarily a **DHCP relay** platform.  The aruba_aoss
codec does NOT advertise `/dhcp/pool` in its supported set.
Server-pool configuration on AOS-S is limited and not parsed
into canonical records by the codec.

## Cross-vendor mapping (FortiGate -> Aruba)

Canonical surface:

```
class CanonicalDHCPPool(BaseModel):
    interface: str = ""
    network: str = ""
    start_ip: str = ""
    end_ip: str = ""
    gateway: str = ""
    dns_servers: list[str]
    lease_time: int = 86400
    domain_name: str = ""
```

The FortiGate parse path populates `CanonicalDHCPPool` records
cleanly (multiple pools per source).  But **the Aruba render path
has no target** — the aruba_aoss codec emits the pool config into
a relay-comment block describing what was lost rather than into
native AOS-S CLI.

Disposition: **unsupported**.  Reason: AOS-S is relay-only on the
aruba_aoss codec; FortiGate-source DHCP pools drop on render with
a comment-block lost-feature notice.

Operators migrating a FortiGate firewall to an AOS-S edge switch
must redirect DHCP-server duties to a separate appliance (a
dedicated DHCP server reached via Aruba's `dhcp-relay` /
`ip helper-address` path).

Promote to **lossy** when the aruba_aoss codec wires AOS-S 16.11+
DHCP-server pool render.

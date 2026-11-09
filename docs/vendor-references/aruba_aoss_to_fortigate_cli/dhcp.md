# DHCP relay (Aruba) versus DHCP server (FortiGate)

> **Update 2026-11-05 — an AOS-S switch's own DHCP server is now read.**  This page was written when the aruba_aoss parser read no `dhcp-server pool` and took AOS-S for a relay platform with no pool to translate.  AOS-S runs a DHCP server of its own (HPE's AOS-S 16.11 Management and Configuration Guide: a `dhcp-server pool`, served on a VLAN that states `dhcp-server`, once `dhcp-server enable` is set), and the parser now reads each pool of a server that is enabled: onto the `Vlan<N>` whose subnet is its network (no interface for a pool of relayed clients), with its network, range, default router, DNS servers, domain name and lease.  A server that is not enabled, a pool that is incomplete, and what the canonical pool has no place for (a second range or router, a static binding, an option) are rows of the sections not translated.  Of the committed inputs, `hpe_community_2930f_wc1610_dhcp_server.cfg` holds 3 pools and the others none.  On FortiGate each pool is written as a `config system dhcp server` entry on the interface of its VLAN and comes back whole: `dhcp_servers` is `good` on this pair, not `not_applicable`.  The relay half of this page is unchanged: `ip helper-address` is still not modelled.

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 IPv4 Configuration Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/IPv4/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S devices act primarily as **DHCP relay** — the platform is
not designed to be an enterprise DHCP server.  The DHCP-relay
syntax uses the `dhcp-relay` keyword:

```
dhcp-relay

vlan 10
   ip helper-address 10.0.0.10
   exit
```

`ip helper-address` is configured per-VLAN inside the VLAN stanza
on AOS-S (not per-physical-interface as on Cisco).

Newer AOS-S firmware (16.11+) introduces basic DHCP-server pool
support (`dhcp-server pool <name>`); the aruba_aoss codec does NOT
advertise `/dhcp/pool` in its supported set, so server pools, where
deployed, are emitted into a relay-comment block by the Aruba
renderer rather than parsed into canonical records.

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide — DHCP server](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/).
Retrieved: 2026-04-30

FortiGate has a first-class DHCP-server feature with **interface-
bound** scopes:

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

- **`set interface`** binds the pool to a specific FortiGate
  interface; the pool inherits the interface's subnet.
- **Lease-time in seconds** under `set lease-time`.
- **DNS server cap** at four (`dns-server1` to `dns-server4`, FortiOS
  7.0 and later; 6.2 takes three).  A fifth and beyond is a
  `# review:` line of the pool.
- **Nested `config ip-range`** for the start/end allocation range.
  FortiGate uses positive ranges (no inverse `excluded-address`
  form).

## Cross-vendor mapping (Aruba -> FortiGate)

Aruba source carries no DHCP server pools (the codec does not
parse them), so `CanonicalIntent.dhcp_servers` is always empty on
this direction — there is nothing to lose.

The FortiGate target's `config system dhcp server` block simply
emits nothing on render.

`ip helper-address` directives on Aruba VLAN stanzas are not
modelled in the canonical tree (no `CanonicalInterface.helper_addresses`
field).  These drop on parse and are not preserved across
migration.

Disposition: **not_applicable**.  Aruba source carries no DHCP
server pool data to migrate; helper-address relay intent is also
unmodelled in canonical.

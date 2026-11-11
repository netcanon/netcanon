# DHCP: OPNsense `<dhcpd>` server versus Aruba AOS-S relay

> **Update 2026-11-10 — the codec writes the pool.**  This page describes AOS-S as a relay platform.  AOS-S 16.x switches run a DHCP server of their own (HPE's AOS-S Management and Configuration Guide: a `dhcp-server pool`, served on a VLAN that states `dhcp-server`, once `dhcp-server enable` is set), the aruba_aoss parser reads one, and the renderer now writes one as the switch prints it: a `dhcp-server pool` stanza after the VLANs (`default-router`, `dns-server`, `domain-name`, `lease DD:HH:MM`, `network`, `range`), `dhcp-server` in the stanza of the VLAN that serves it, and `dhcp-server enable` last.  A pool is served where the output's VLAN stanza for its interface holds an address of its network; where none does, it is written with a `; review:` line, and the switch serves it only to clients a DHCP relay forwards to it.  An OPNsense zone is most often a port, for which the output has no VLAN stanza, so such a pool is written with its review line.  The disposition below (`lossy`) stands, for where a pool is served rather than for the pool itself.

## OPNsense

Source: [OPNsense ISC DHCPv4 manual](https://docs.opnsense.org/manual/isc.html)
Retrieved: 2026-04-30

```xml
<opnsense>
  <dhcpd>
    <lan>
      <enable>1</enable>
      <range>
        <from>10.0.10.100</from>
        <to>10.0.10.200</to>
      </range>
      <gateway>10.0.10.1</gateway>
      <domain>example.net</domain>
      <dnsserver>10.0.10.1</dnsserver>
      <defaultleasetime>7200</defaultleasetime>
      <maxleasetime>86400</maxleasetime>
    </lan>
  </dhcpd>
</opnsense>
```

OPNsense DHCP server model:

- The XML tag IS the zone interface (`<lan>`, `<opt1>`, …).
- Network / mask is INFERRED from the zone interface's `<ipaddr>` +
  `<subnet>` — not stored on the pool.
- Lease time in seconds.
- Default route advertised to clients via `<gateway>` (typically
  the firewall's address on this zone).
- The opnsense codec parses these blocks and populates
  `CanonicalDHCPPool` records.

## Aruba AOS-S

Source: [Aruba AOS-S 16.10 IPv4 Configuration Guide — DHCP relay](https://www.arubanetworks.com/techdocs/AOS-S/16.10/IPv4/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S 16.x is primarily a DHCP RELAY platform.  Per-VLAN
`ip helper-address` directives forward client DHCP discovers /
requests to a central server:

```
vlan 10
   ip address 10.10.10.1/24
   ip helper-address 10.0.0.50
   exit
```

The aruba_aoss codec does NOT advertise `/dhcp/pool` in its
capability matrix `supported` list — AOS-S is relay-only from the
canonical perspective.  Newer firmware (16.11+ on some platforms)
adds a `dhcp-server pool <name>` surface, but the codec does not
currently render it.

## Cross-vendor mapping

Canonical fields (`CanonicalDHCPPool`):

```
interface, network, start_ip, end_ip, gateway,
dns_servers, lease_time, domain_name
```

OPNsense -> Aruba:

- `dhcp_servers`: **lossy** — OPNsense source populates the
  canonical list with one `CanonicalDHCPPool` per zone interface
  carrying a DHCP scope.  Aruba target has no destination for these
  pools (codec doesn't advertise `/dhcp/pool`); cross-pair render
  drops the pool config and emits a comment block describing what
  was lost.  Operator-relevant note: the equivalent operational
  pattern on Aruba is to deploy an external DHCP server (e.g.
  Windows DHCP, ISC dhcpd, dnsmasq) and configure
  `ip helper-address <addr>` on the VLAN SVIs; the canonical schema
  has no helper-address field today, so this redesign is operator-
  driven.

# DHCP: OPNsense `<dhcpd>` server versus Aruba AOS-S relay

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

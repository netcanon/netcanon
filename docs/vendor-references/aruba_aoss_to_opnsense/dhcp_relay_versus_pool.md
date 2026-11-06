# DHCP: Aruba AOS-S relay versus OPNsense `<dhcpd>` server

> **Update 2026-11-05 — an AOS-S switch's own DHCP server is now read.**  This page was written when the aruba_aoss parser read no `dhcp-server pool` and took AOS-S for a relay platform with no pool to translate.  AOS-S runs a DHCP server of its own (HPE's AOS-S 16.11 Management and Configuration Guide: a `dhcp-server pool`, served on a VLAN that states `dhcp-server`, once `dhcp-server enable` is set), and the parser now reads each pool of a server that is enabled: onto the `Vlan<N>` whose subnet is its network (no interface for a pool of relayed clients), with its network, range, default router, DNS servers, domain name and lease.  A server that is not enabled, a pool that is incomplete, and what the canonical pool has no place for (a second range or router, a static binding, an option) are rows of the sections not translated.  Of the committed inputs, `hpe_community_2930f_wc1610_dhcp_server.cfg` holds 3 pools and the others none.  On OPNsense each pool is written under the zone of its VLAN's interface with its range, gateway, DNS servers and lease; an OPNsense pool states no network (the zone's address gives it), so `dhcp_servers` is `lossy` on this pair, not `not_applicable`.

## Aruba AOS-S

Source: [Aruba AOS-S 16.10 IPv4 Configuration Guide — DHCP relay /
DHCP server](https://www.arubanetworks.com/techdocs/AOS-S/16.10/IPv4/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S 16.x is primarily a DHCP relay platform.  Per-VLAN
`ip helper-address` directives forward client broadcasts to a
central DHCP server:

```
vlan 10
   ip address 10.10.10.1/24
   ip helper-address 10.0.0.50
   exit
```

A dhcp-server pool surface exists in newer AOS-S releases (16.11+
firmware on some platforms) but the aruba_aoss codec does NOT
advertise `/dhcp/pool` in its capability matrix `supported` list —
it remains a relay-only platform from the canonical perspective.

The canonical `dhcp_servers: list[CanonicalDHCPPool]` is therefore
ALWAYS empty after an Aruba parse.  `ip helper-address` is also not
modelled in canonical (no `CanonicalInterface.helper_addresses`
field), so even relay state drops.

## OPNsense

Source: [OPNsense ISC DHCPv4 manual](https://docs.opnsense.org/manual/isc.html)
Retrieved: 2026-04-30

OPNsense uses the ISC dhcpd backend (or Kea on newer releases) with
INTERFACE-KEYED pool blocks:

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

- The XML tag IS the zone interface (`<lan>`, `<opt1>`, …) — there
  is no separate `<name>` element.
- Network / mask is INFERRED from the zone interface's `<ipaddr>` +
  `<subnet>`; not stored on the pool record.
- Lease time is in seconds (no day/hour/minute units).
- Excluded ranges are implicit (the pool `<range>` is the only
  allocatable window).

## Cross-vendor mapping

Canonical fields covered (`CanonicalDHCPPool`):

```
interface: str
network: str
start_ip: str
end_ip: str
gateway: str
dns_servers: list[str]
lease_time: int
domain_name: str
```

Aruba -> OPNsense:

- `dhcp_servers`: **not_applicable** — Aruba source never populates
  the canonical list (no `/dhcp/pool` in the capability matrix).
  OPNsense target would happily render `<dhcpd>` blocks if the
  canonical list were populated, but on this direction there is
  nothing to lose.  Operator-relevant note: Aruba's per-VLAN
  `ip helper-address` directives also drop because the canonical
  schema has no helper-address field.

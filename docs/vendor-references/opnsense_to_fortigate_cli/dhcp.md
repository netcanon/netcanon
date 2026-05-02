# DHCP server: OPNsense versus FortiGate FortiOS

Reverse direction.  Forward direction in
`../fortigate_cli_to_opnsense/dhcp.md`.

## OPNsense

Source: [OPNsense ISC DHCPv4
manual](https://docs.opnsense.org/manual/isc.html)
Retrieved: 2026-05-01

```xml
<opnsense>
  <dhcpd>
    <lan>
      <enable>1</enable>
      <range>
        <from>10.0.10.100</from>
        <to>10.0.10.199</to>
      </range>
      <gateway>10.0.10.1</gateway>
      <dnsserver>10.0.10.1</dnsserver>
      <dnsserver>198.51.100.53</dnsserver>
      <defaultleasetime>86400</defaultleasetime>
      <maxleasetime>172800</maxleasetime>
      <domain>lab.example.invalid</domain>
    </lan>
    <opt2>
      <enable>1</enable>
      <range>
        <from>10.10.20.100</from>
        <to>10.10.20.199</to>
      </range>
      <gateway>10.10.20.1</gateway>
    </opt2>
  </dhcpd>
</opnsense>
```

OPNsense notes:

- DHCP scopes are interface-bound — XML element name (`<lan>`,
  `<opt2>`) matches a zone label.
- `<range>/<from>` + `<range>/<to>` carry one v4 range per scope.
- Multiple `<dnsserver>` elements supported (no fixed cap).
- IPv6 DHCP is `<dhcpdv6>` separate block (out of canonical scope v1).

## FortiGate FortiOS

See `../fortigate_cli_to_opnsense/dhcp.md` for the FortiGate-side
shape.  Key points:

- DHCP scopes are also interface-bound.
- Each `edit` is identified by a numeric ID; references parent via
  `set interface`.
- `set lease-time` is in seconds.
- `dns-server1` / `dns-server2` / `dns-server3` — three-cap.
- `<exclude-range>` carves holes out of `<ip-range>`.

## Cross-vendor mapping (OPNsense -> FortiGate)

Canonical fields covered (`CanonicalDHCPPool`):

```
name, interface, range_start, range_end, default_gateway,
dns_servers, domain_name, lease_time
```

- **lossy** — Both vendors are interface-bound, philosophical match,
  but:
  1. OPNsense addressing by zone label versus FortiGate addressing
     by edit ID.  Cross-pair render must invent a numeric ID.
  2. Interface name needs the rename mesh conversion (OPNsense `lan`
     -> FortiGate `internal`).
- DNS server cap differs: OPNsense unbounded → FortiOS three-cap.
  Truncation if OPNsense source has 4+ DNS servers per scope (rare).
- Default-gateway preserves cleanly.
- Lease-time preserves cleanly (both seconds).  OPNsense
  `<maxleasetime>` has no FortiOS equivalent; drops on canonical.
- IPv6 DHCP scopes from OPNsense `<dhcpdv6>` are not modelled in
  canonical v1.
- Static-mappings (per-MAC reservations) are not modelled in
  canonical v1.

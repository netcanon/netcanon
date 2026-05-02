# DHCP server: FortiGate FortiOS versus OPNsense

Both vendors are DHCP servers (not relay-only) on their primary edge
roles.  The model shapes diverge in interesting ways.

## FortiGate FortiOS

Source: [FortiGate / FortiOS 7.4 Administration Guide — `config system
dhcp server`](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/)
Retrieved: 2026-05-01

```
config system dhcp server
    edit 1
        set status enable
        set lease-time 86400
        set dns-server1 10.0.10.1
        set dns-server2 198.51.100.53
        set domain "lab.example.invalid"
        set default-gateway 10.0.10.1
        set netmask 255.255.255.0
        set interface "internal"
        config ip-range
            edit 1
                set start-ip 10.0.10.100
                set end-ip 10.0.10.199
            next
        end
        config exclude-range
            edit 1
                set start-ip 10.0.10.150
                set end-ip 10.0.10.155
            next
        end
    next
end
```

Notes:

- DHCP scopes are **interface-bound** — each `edit` references a
  parent `set interface` (a physical / VLAN / aggregate name).
- Address space derives from the parent interface's IP/netmask;
  the scope itself just declares ranges.
- `set lease-time` is in seconds.
- `set dns-server1` / `dns-server2` / `dns-server3` — three-cap.
- Multiple `<ip-range>` edits supported (uncommon but legal).
- `<exclude-range>` carves holes out of the assigned ranges.

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
  </dhcpd>
</opnsense>
```

Notes:

- DHCP scopes are also **interface-bound** — but the binding is via
  the XML element name (`<lan>`, `<opt2>`, ...) matching a zone
  label rather than a `set interface` reference.
- `<range>/<from>` + `<range>/<to>` carry one v4 range per scope.
- Multiple `<dnsserver>` elements supported (no fixed cap).
- `<defaultleasetime>` and `<maxleasetime>` in seconds.
- Static-mappings (per-MAC reservations) live as repeated
  `<staticmap>` elements under each scope.
- IPv6 DHCP uses a separate `<dhcpdv6>` block — out of canonical
  scope in v1.

## Cross-vendor mapping

Canonical fields covered (`CanonicalDHCPPool`):

```
name, interface, range_start, range_end, default_gateway,
dns_servers, domain_name, lease_time
```

FortiGate -> OPNsense:

- **lossy** — Both vendors are interface-bound, which is a
  philosophical match.  However:
  1. FortiGate scopes are addressed by numeric edit ID;
     OPNsense scopes are addressed by zone label.  The cross-pair
     render must invent the matching zone label from the FortiGate
     `set interface` value via the rename mesh.
  2. The OPNsense codec's capability matrix does NOT currently
     advertise `/dhcp/pool` paths under supported; render is
     unwired pending wire-up.
- DNS server cap differs: FortiOS three (dns-server1/2/3) ↔
  OPNsense unbounded.  No truncation in this direction (3 fits in
  unbounded).
- Default-gateway preserves cleanly.
- Lease-time preserves cleanly (both in seconds).
- FortiGate `<exclude-range>` has no direct OPNsense equivalent
  (OPNsense requires the operator to split the range or add
  static-mappings to reserve specific addresses).  Cross-pair
  drops exclude-ranges with a banner.
- FortiGate's multiple `<ip-range>` edits collapse to a single
  range on canonical (`range_start` / `range_end` are scalars);
  multi-range FortiGate scopes lose all but the first.

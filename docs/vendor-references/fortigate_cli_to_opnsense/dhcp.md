# DHCP server: FortiGate FortiOS versus OPNsense

> **Update 2026-11-07 — the FortiGate parser reads a pool as its server hands addresses out.**  This page was written when `fortigate_cli` kept a pool's first `config ip-range` and read no `config exclude-range` and no `dns-service`, so a second range and every exclusion were lost, and nothing said so.  The parser now reads every range less every excluded range (Fortinet's CLI reference, `config system dhcp server`) and keeps the largest run, with a row of the sections not translated for any other; gives a pool the DNS servers its `dns-service` names (the interface's own address for `local`, the FortiGate's own for `default`, `dns-server1` to `dns-server4` for `specify`, `0.0.0.0` being none); reads a lease the pool does not state as FortiOS's 604800 seconds and `0` as one that does not end; and leaves out, and says, a pool of `status disable`.  Reserved addresses, DHCP options, NTP servers and the like are a row each.  See `docs/vendors/fortigate.md` § "What translates well".

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
- `set dns-server1` to `dns-server4` — four-cap (FortiOS 7.0 and
  later; 6.2 takes three).
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
- DNS server cap differs: FortiOS four (dns-server1 to dns-server4,
  7.0 and later; 6.2 takes three) ↔ OPNsense unbounded.  No
  truncation in this direction (four fits in unbounded).
- Default-gateway preserves cleanly.
- Lease-time preserves cleanly (both in seconds).
- FortiGate `<exclude-range>` has no direct OPNsense equivalent
  (OPNsense requires the operator to split the range or add
  static-mappings to reserve specific addresses).  Cross-pair
  drops exclude-ranges with a banner.
- FortiGate's multiple `<ip-range>` edits collapse to a single
  range on canonical (`range_start` / `range_end` are scalars);
  multi-range FortiGate scopes lose all but the first.

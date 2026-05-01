# DHCP server scopes: Cisco IOS-XE versus OPNsense

## Cisco IOS-XE

Source: Cisco IOS XE IP Addressing Services Configuration Guide —
DHCP Server.

```
ip dhcp pool USERS
 network 10.10.10.0 255.255.255.0
 default-router 10.10.10.1
 dns-server 10.0.0.53 10.0.0.54
 lease 0 8 0
 domain-name example.com
!
ip dhcp pool SERVERS
 network 10.10.20.0 255.255.255.0
 default-router 10.10.20.1
 dns-server 10.0.0.53
 lease 7
!
ip dhcp excluded-address 10.10.10.1 10.10.10.10
```

Pools are named blocks under global config.  ``network`` carries the
subnet (dotted-mask).  ``default-router`` lists per-pool gateways.
``lease`` accepts ``<days> <hours> <minutes>`` triples or
``<days>`` alone, with ``infinite`` as a special token.  Excluded
ranges live in separate ``ip dhcp excluded-address`` lines, not
inside the pool.

The Cisco codec parses ``ip dhcp pool`` blocks and emits
``CanonicalDHCPPool`` records (per its capability matrix).

## OPNsense

Source: [OPNsense ISC DHCPv4 manual](https://docs.opnsense.org/manual/isc.html)
Retrieved: 2026-04-30
Source: [OPNsense DHCP overview](https://docs.opnsense.org/manual/dhcp.html)
Retrieved: 2026-04-30

OPNsense's legacy ISC DHCPv4 server lives in ``<dhcpd>`` per zone:

```xml
<opnsense>
  <dhcpd>
    <lan>
      <enable>1</enable>
      <range>
        <from>10.10.10.100</from>
        <to>10.10.10.200</to>
      </range>
      <gateway>10.10.10.1</gateway>
      <dnsserver>10.0.0.53</dnsserver>
      <dnsserver>10.0.0.54</dnsserver>
      <domain>example.com</domain>
      <defaultleasetime>28800</defaultleasetime>
      <maxleasetime>86400</maxleasetime>
    </lan>
    <opt1>
      <enable>1</enable>
      <range>
        <from>192.0.2.100</from>
        <to>192.0.2.200</to>
      </range>
      <gateway>192.0.2.1</gateway>
    </opt1>
  </dhcpd>
</opnsense>
```

Notable shape differences:

- DHCPd configuration is INTERFACE-KEYED, not pool-keyed.  The child
  tag inside ``<dhcpd>`` is the OPNsense zone label (``lan``,
  ``opt1``, ...) — there is no ``<name>`` field for the pool.
- ``<range>`` uses explicit ``<from>`` and ``<to>`` IP addresses, not
  a network + exclusions model.  The pool's network is INFERRED from
  the zone interface's IP + prefix.
- Lease time is in seconds (``<defaultleasetime>28800</defaultleasetime>``
  = 8 hours), not the ``<days> <hours> <minutes>`` triple.
- Multiple ``<dnsserver>`` entries are supported.
- OPNsense is migrating from ISC DHCP (legacy) to Kea DHCP — the
  ``<dhcpd>`` block models the ISC layout.  Kea uses a different
  ``<kea>`` element under ``<system>``; the OPNsense codec parses
  the legacy ``<dhcpd>`` shape only.

## Cross-vendor mapping

Canonical fields (see ``CanonicalDHCPPool``):

```
interface: str
network: str
start_ip: str
end_ip: str
gateway: str
dns_servers: list[str]
lease_time: int    # seconds
domain_name: str
```

Cisco -> OPNsense considerations:

- ``network``: **lossy** — OPNsense doesn't model the pool's
  network/mask explicitly (it's inherited from the zone interface).
  The cross-vendor render must compute the OPNsense zone whose
  ``<ipaddr>`` + ``<subnet>`` matches the canonical network and emit
  the ``<dhcpd>`` child under that zone tag.  When no matching zone
  exists, the render path has nowhere to put the pool.
- ``start_ip`` / ``end_ip``: **good** — direct mapping to
  ``<range><from>`` / ``<range><to>``.
- ``gateway``: **good** — direct mapping to ``<gateway>``.
- ``dns_servers``: **good** — both vendors model a DNS list.
- ``lease_time``: **lossy** — Cisco's ``lease 0 8 0``
  (days/hours/minutes) versus OPNsense's seconds is a units conversion
  the codec must do; arbitrary fractional days don't map cleanly.
- ``domain_name``: **good** — both vendors model a per-pool domain.
- ``interface``: **lossy** — the OPNsense zone label (``lan``,
  ``opt1``) is the natural pool identifier; Cisco's pool name
  (``USERS``) is operator-chosen and has no OPNsense surface.

Cisco's ``ip dhcp excluded-address`` ranges are not modelled in the
canonical schema; they parse-and-ignore on Cisco-side.  OPNsense's
``<staticmap>`` (per-MAC reservations) is similarly out of canonical
scope.

Disposition: **lossy** overall — the canonical surface round-trips
but pool-network resolution requires the OPNsense zone to exist and
the OPNsense codec's capability matrix does not currently advertise
``/dhcp/pool`` paths.  Lands when OPNsense ``<dhcpd>`` parse + render
wire-up is completed.

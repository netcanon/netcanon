# DHCP server scopes: OPNsense versus Cisco IOS-XE

## OPNsense

Source: [OPNsense ISC DHCPv4 manual](https://docs.opnsense.org/manual/isc.html)
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
  </dhcpd>
</opnsense>
```

Notable:

- DHCPd configuration is INTERFACE-KEYED — the child tag inside
  ``<dhcpd>`` is the OPNsense zone label (``lan`` / ``opt1`` / ...).
- ``<range>`` uses explicit ``<from>`` / ``<to>`` IPs.  Pool network
  is INFERRED from the zone interface's ``<ipaddr>`` + ``<subnet>``.
- Lease times are seconds.
- OPNsense is migrating to Kea DHCP; the legacy ``<dhcpd>`` is what
  this codec parses (per ``parse.py`` ``_parse_opnsense_dhcp_zone``).

## Cisco IOS-XE

```
ip dhcp pool USERS
 network 10.10.10.0 255.255.255.0
 default-router 10.10.10.1
 dns-server 10.0.0.53 10.0.0.54
 lease 0 8 0
 domain-name example.com
!
```

Cisco pool names are operator-chosen.  ``network`` carries the
subnet+mask explicitly (no inference).  ``lease`` accepts
``<days> <hours> <minutes>``.

## Cross-vendor mapping

Canonical fields (see ``CanonicalDHCPPool``):

```
interface, network, start_ip, end_ip, gateway,
dns_servers, lease_time, domain_name
```

OPNsense -> Cisco:

- ``interface``: **lossy** — OPNsense's zone label (``lan``) becomes
  the synthesised Cisco pool name.  Cisco's pool naming convention
  is operator-chosen so the result is acceptable but loses the
  OPNsense zone-as-identifier semantic.
- ``network``: **lossy** — OPNsense's parser computes the network
  from the zone's ``<ipaddr>`` + ``<subnet>``; cross-pair must
  preserve that computed value into the Cisco ``network`` line.
- ``start_ip`` / ``end_ip``: **good** — direct mapping to the
  ``ip dhcp pool`` ``range`` directive.  (Note: Cisco's pool model
  uses a ``network`` directive plus ``ip dhcp excluded-address``
  ranges OUTSIDE the pool; the canonical schema's
  ``start_ip`` / ``end_ip`` is OPNsense-natural and Cisco render
  must adapt.)
- ``gateway``: **good** — OPNsense ``<gateway>`` ↔ Cisco
  ``default-router``.
- ``dns_servers``: **good** — both vendors model a DNS list.
- ``lease_time``: **lossy** — OPNsense's seconds need conversion to
  Cisco's days/hours/minutes triple.
- ``domain_name``: **good** — both vendors model a per-pool domain.

WIRE-UP DISPOSITION: the OPNsense codec parses ``<dhcpd>`` (per
``_parse_opnsense_dhcp_zone``) but the Cisco render path's DHCP
emission status is per-codec — Cisco IOS-XE codec has no
``/dhcp/pool`` advertised in its capability matrix, so the
cross-pair render of DHCP pools is partial.  Operator review
required.

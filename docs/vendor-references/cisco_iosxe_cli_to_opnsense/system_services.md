# System services (hostname / domain / DNS / NTP / syslog): Cisco IOS-XE versus OPNsense

## Cisco IOS-XE

Source: Cisco IOS XE Network Management Configuration Guide — system
services.

```
hostname core-rtr01
ip domain name example.com
ip name-server 10.0.0.53
ip name-server 10.0.0.54

ntp server 10.0.0.130
ntp server 10.0.0.131 prefer

clock timezone PST -8 0
clock summer-time PDT recurring

logging host 10.0.0.200
logging trap informational
logging facility local6
```

The ``ip domain name`` directive carries the device's primary DNS
suffix.  ``ip name-server`` lines feed the resolver.  ``ntp server``
and ``logging host`` accept multiple instances.

## OPNsense

Source: [OPNsense General Settings — System: Settings: General](https://docs.opnsense.org/manual/settingsmenu.html)
Retrieved: 2026-04-30

OPNsense stores system identity inside ``<system>`` in
``config.xml``:

```xml
<opnsense>
  <system>
    <hostname>fw01</hostname>
    <domain>example.com</domain>
    <dnsserver>10.0.0.53</dnsserver>
    <dnsserver>10.0.0.54</dnsserver>
    <timezone>America/Los_Angeles</timezone>
    <timeservers>0.opnsense.pool.ntp.org 1.opnsense.pool.ntp.org</timeservers>
    <syslog>
      <reverse>0</reverse>
      <nentries>50</nentries>
      <remoteserver>10.0.0.200</remoteserver>
    </syslog>
  </system>
</opnsense>
```

Notable shape differences:

- ``hostname`` is the bare short name; ``domain`` is a sibling element
  rather than a hyphen / space variant of a single keyword.
- DNS resolvers live as repeated ``<dnsserver>`` elements (one per
  resolver).
- NTP servers are space-separated inside a SINGLE ``<timeservers>``
  element rather than one element per server.  This is a documented
  OPNsense convention and round-trips fine through the codec.
- Timezone uses an Olson / zoneinfo identifier
  (``America/Los_Angeles``).  No DST offset companion — the OS derives
  DST behaviour from the zoneinfo database.

## Cross-vendor mapping

Canonical fields covered:

```
hostname: str
domain: str
dns_servers: list[str]
ntp_servers: list[str]
timezone: str
syslog_servers: list[str]
```

The hostname / domain / DNS / NTP / syslog round-trips are fundamentally
sound — each is a list-of-strings or scalar that both vendors model
directly.  The OPNsense codec reads ``<hostname>`` and ``<domain>``
(parse) and emits them in render; it currently does NOT round-trip
``<dnsserver>`` / ``<timeservers>`` / ``<syslog>`` / ``<timezone>`` (no
parser branch wires those into the canonical surface — see the codec's
capability matrix entry for ``/system/dns-server`` and ``/system/ntp-server``).
The cross-vendor render Cisco-source -> OPNsense-target therefore
emits the bare ``<hostname>`` + ``<domain>`` and drops the rest.

Disposition for hostname / domain: **good**.

Disposition for dns_servers / ntp_servers / syslog_servers / timezone:
**lossy** — the canonical model carries the data but the OPNsense
render path does not yet emit the corresponding XML elements.  Lands
when OPNsense ``<dnsserver>`` / ``<timeservers>`` / ``<syslog>`` wire-
up is added.

Timezone is doubly lossy: even with wire-up, Cisco's ``clock timezone
PST -8 0`` (offset+DST tokens) and OPNsense's ``America/Los_Angeles``
(zoneinfo) carry different semantics.  An operator-curated mapping
table would be required for byte-for-byte fidelity.

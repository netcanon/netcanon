# System services (hostname / domain / DNS / NTP / syslog): OPNsense versus Cisco IOS-XE

## OPNsense

Source: [OPNsense General Settings](https://docs.opnsense.org/manual/settingsmenu.html)
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
      <remoteserver>10.0.0.200</remoteserver>
    </syslog>
  </system>
</opnsense>
```

Notable:

- ``<hostname>`` carries the bare short name; ``<domain>`` is a
  separate sibling element.
- DNS resolvers are repeated ``<dnsserver>`` elements.
- NTP servers are SPACE-SEPARATED inside a single ``<timeservers>``
  element.
- Timezone uses an Olson / zoneinfo identifier
  (``America/Los_Angeles``).

The OPNsense codec parses ``<hostname>`` and ``<domain>`` (per
``parse.py``); ``<dnsserver>`` / ``<timeservers>`` / ``<timezone>`` /
``<syslog>`` parsing is not currently wired into the canonical
surface.

## Cisco IOS-XE

Source: Cisco IOS XE Network Management Configuration Guide.

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
```

Cisco uses ``ip domain name`` (space) versus OPNsense's bare
``<domain>``; the canonical model normalises to a domain string.

## Cross-vendor mapping

Canonical fields (see ``CanonicalIntent``):

```
hostname: str
domain: str
dns_servers: list[str]
ntp_servers: list[str]
timezone: str
syslog_servers: list[str]
```

OPNsense -> Cisco:

- ``hostname``: **good** — direct mapping.
- ``domain``: **good** — OPNsense ``<domain>`` ↔ Cisco
  ``ip domain name``.
- ``dns_servers``: **lossy** — OPNsense codec parse path doesn't
  currently surface ``<dnsserver>`` into ``CanonicalIntent.dns_servers``.
  Even after wire-up, the round-trip is mechanical.
- ``ntp_servers``: **lossy** — OPNsense's space-separated
  ``<timeservers>`` would split cleanly to Cisco's ``ntp server``
  list once parse wire-up lands.
- ``timezone``: **lossy** — OPNsense's zoneinfo ID
  (``America/Los_Angeles``) versus Cisco's offset+DST tokens
  (``PST -8 0``) carry different semantics; operator-curated mapping
  required for byte-for-byte fidelity.
- ``syslog_servers``: **lossy** — OPNsense's ``<syslog><remoteserver>``
  would map to Cisco's ``logging host`` list once parse wire-up lands.

Disposition for hostname / domain: **good**.  All other system-service
fields: **lossy** pending OPNsense parse wire-up for the relevant
``<system>`` children.

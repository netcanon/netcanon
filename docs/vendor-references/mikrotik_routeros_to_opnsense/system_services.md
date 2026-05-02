# System services (hostname / DNS / NTP / timezone / syslog): MikroTik RouterOS versus OPNsense

## MikroTik RouterOS

Sources:
- [Identity — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/40992856/Identity)
- [DNS — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/37945004/DNS)
- [NTP Client — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/37224622/NTP+Client+and+Server)
- [Clock — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/40992866/Clock)
- [Log — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/14091786/Log)

Retrieved: 2026-04-30

```
/system identity
set name=ks-edge-01

/ip dns
set servers=1.1.1.1,8.8.8.8

/system ntp client
set enabled=yes servers=10.0.0.123,pool.ntp.org

/system clock
set time-zone-name=America/New_York

/system logging action
add bsd-syslog=no name=remote-syslog remote=10.0.0.20 remote-port=514 \
    target=remote
```

RouterOS keeps each service in its own `/system <area>` section.
``/system identity`` carries only the bare short name; FQDN context lives
on the DNS resolver instead.  ``/ip dns set servers=`` is a single
comma-separated value.  ``/system ntp client`` accepts a single
comma-separated server list and lacks per-server modifiers.  Timezone
uses the IANA tz database name.  Syslog destinations are split between
``/system logging action`` (where to send) and ``/system logging``
(what topics / severities).

## OPNsense

Source: [OPNsense General Settings — System: Settings: General](https://docs.opnsense.org/manual/settingsmenu.html)

Retrieved: 2026-04-30

```xml
<opnsense>
  <system>
    <hostname>fw01</hostname>
    <domain>example.net</domain>
    <dnsserver>1.1.1.1</dnsserver>
    <dnsserver>9.9.9.9</dnsserver>
    <timezone>Etc/UTC</timezone>
    <timeservers>0.opnsense.pool.ntp.org 1.opnsense.pool.ntp.org</timeservers>
    <syslog>
      <remoteserver>10.0.0.200</remoteserver>
    </syslog>
  </system>
</opnsense>
```

OPNsense aggregates system-identity attributes inside ``<system>``.
``<hostname>`` is the bare short name; ``<domain>`` is a sibling
element.  DNS resolvers each get their own ``<dnsserver>`` element
(repeated).  NTP servers are SPACE-SEPARATED inside a single
``<timeservers>`` element rather than one element per server (a
documented OPNsense convention).  Timezone uses an Olson zoneinfo
identifier (``America/Los_Angeles``).  Syslog remotes live under
``<system>/<syslog>/<remoteserver>``.

## Cross-vendor mapping

The canonical surface is

```
hostname: str
domain: str
dns_servers: list[str]
ntp_servers: list[str]
timezone: str
syslog_servers: list[str]
```

### hostname

RouterOS ``/system identity / set name=X`` ↔ OPNsense
``<system>/<hostname>X</hostname>``.  Both vendors model the bare
short name; the codec preserves it verbatim.

### domain

RouterOS does not surface a top-level FQDN identity field — the
canonical ``domain`` value is empty after a RouterOS parse.  OPNsense
target render emits no ``<domain>`` element when the canonical field
is empty.  Structural absence on the source side, not a translation
loss.

### dns_servers

RouterOS ``/ip dns / set servers=1.1.1.1,8.8.8.8`` parses into the
``list[str]`` cleanly.  OPNsense capability matrix declares
``/system/dns-server`` supported but the OPNsense codec's render
path does not currently emit ``<dnsserver>`` elements (no wire-up).
Cross-pair drops the resolver list pending wire-up.

### ntp_servers

RouterOS ``/system ntp client / set servers=10.0.0.123,pool.ntp.org``
maps to OPNsense's space-separated ``<timeservers>`` element.  The
OPNsense codec does not currently wire ``<timeservers>`` into
``CanonicalIntent.ntp_servers`` on render.  Per-server NTP options
are not modelled on either side (RouterOS surfaces none; OPNsense
keeps them under ``<ntpd>`` which is separate from ``<system>``).

### timezone

RouterOS uses the IANA tz database name directly
(``America/New_York``).  OPNsense uses the same Olson zoneinfo form
(``<system>/<timezone>America/New_York</timezone>``).  Both vendors
share the IANA convention so the string survives a same-string
round-trip — but the OPNsense render path does not yet wire timezone
into canonical, so cross-pair drops on render.

### syslog

RouterOS splits destination (``/system logging action add target=
remote remote=X``) from filter (``/system logging add action=remote
topics=info``).  Canonical surface stores host addresses only; per-
topic / per-severity filters drop on round-trip.  OPNsense codec does
not currently wire ``<system>/<syslog>/<remoteserver>`` into
``CanonicalIntent.syslog_servers``.

### Disposition summary

| Field | Disposition |
|---|---|
| `hostname` | good |
| `domain` | not_applicable (RouterOS source carries none) |
| `dns_servers` | lossy (OPNsense render wire-up pending) |
| `ntp_servers` | lossy (OPNsense render wire-up pending; per-server options drop) |
| `timezone` | lossy (OPNsense render wire-up pending; otherwise IANA-equal) |
| `syslog_servers` | lossy (OPNsense render wire-up pending; filter context drops) |

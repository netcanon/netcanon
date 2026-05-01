# System services (hostname / DNS / SNTP / syslog / timezone): Aruba AOS-S versus OPNsense

## Aruba AOS-S

Source: [Aruba AOS-S 16.10 Management and Configuration Guide — System
configuration](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MCG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
hostname "ks-aoss-edge-01"

ip dns server-address priority 1 10.0.10.53
ip dns server-address priority 2 10.0.10.54

sntp server priority 1 10.0.10.123
sntp server priority 2 10.0.10.124

time timezone -480
time daylight-time-rule continental-us-and-canada

logging 10.0.10.200
logging 10.0.10.201
```

Aruba AOS-S notes:

- Hostname is double-quoted in `show running-config` output; the codec
  strips the quotes on parse and re-quotes on render.
- There is no first-class `domain` directive — operators that want
  an FQDN-shape identifier fold it into the hostname (`hostname
  "host.example.com"`).  The aruba_aoss codec does NOT extract a
  separate domain on parse.
- Time protocol is SNTP (lightweight client) rather than full NTP.
- Timezone is a minute-offset integer (`-480` = UTC-08:00 = PST).
  DST behaviour is a separate `time daylight-time-rule <region>`
  directive; the codec does not currently parse either timezone form
  into the canonical surface.

## OPNsense

Source: [OPNsense General Settings — System: Settings: General](https://docs.opnsense.org/manual/settingsmenu.html)
Retrieved: 2026-04-30

OPNsense stores system identity inside `<system>` in `config.xml`:

```xml
<opnsense>
  <system>
    <hostname>fw01</hostname>
    <domain>example.com</domain>
    <dnsserver>10.0.10.53</dnsserver>
    <dnsserver>10.0.10.54</dnsserver>
    <timezone>America/Los_Angeles</timezone>
    <timeservers>0.opnsense.pool.ntp.org 1.opnsense.pool.ntp.org</timeservers>
    <syslog>
      <reverse>0</reverse>
      <nentries>50</nentries>
      <remoteserver>10.0.10.200</remoteserver>
    </syslog>
  </system>
</opnsense>
```

Notable shape differences from Aruba:

- `hostname` is the bare short name; `domain` is a sibling element.
- DNS resolvers are repeated `<dnsserver>` elements (no priority
  ordinal — list order implies precedence).
- NTP servers are space-separated inside a SINGLE `<timeservers>`
  element rather than one element per server.
- Timezone uses an Olson / zoneinfo identifier
  (`America/Los_Angeles`).  No DST offset companion — the OS derives
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

- `hostname`: **good** — Aruba quoted-form ↔ OPNsense `<hostname>`.
  Canonical preserves the bare string.
- `domain`: **not_applicable** on this direction — Aruba source has
  no separate domain directive in the parse surface, so the field is
  always empty on Aruba parse.  OPNsense target would happily accept
  `<domain>` but there is no source data to populate it.
- `dns_servers`: **lossy** — Aruba's priority-ordered
  `ip dns server-address` lines collapse to a bare list on canonical;
  the OPNsense codec capability matrix declares `/system/dns-server`
  as supported but render wire-up is currently parse-only on OPNsense
  (no render branch emits `<dnsserver>` elements yet).
- `ntp_servers`: **lossy** — Aruba's SNTP server list maps to the
  space-separated `<timeservers>` element; OPNsense codec also lacks
  render wire-up here.
- `timezone`: **lossy** — Aruba minute-offset (`-480`) vs OPNsense
  Olson zoneinfo (`America/Los_Angeles`) require an operator-curated
  mapping table.  Codec-side wire-up gap on both vendors.
- `syslog_servers`: **lossy** — Aruba `logging <addr>` ↔ OPNsense
  `<syslog>/<remoteserver>`.  Codec capability matrices on both ends
  do not advertise syslog round-trip; field drops on render.

The fundamental shape (host / list-of-strings / scalar) is sound on
both vendors; most fields land at `lossy` because the OPNsense codec
parse-and-render wire-up is incomplete for several `<system>` children.

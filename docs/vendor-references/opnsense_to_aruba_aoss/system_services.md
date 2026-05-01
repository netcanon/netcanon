# System services (hostname / domain / DNS / NTP / syslog / timezone): OPNsense versus Aruba AOS-S

## OPNsense

Source: [OPNsense General Settings — System: Settings: General](https://docs.opnsense.org/manual/settingsmenu.html)
Retrieved: 2026-04-30

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

OPNsense notes:

- `<hostname>` is the bare short name; `<domain>` is a sibling.
- DNS resolvers are repeated `<dnsserver>` elements (no priority).
- NTP servers are SPACE-SEPARATED inside a single `<timeservers>`
  element.  `<system><timezone>` uses Olson zoneinfo
  (`America/Los_Angeles`).
- Syslog remote receivers under `<system>/<syslog>/<remoteserver>`.
- The opnsense codec parses `<hostname>` and `<domain>` (declared
  supported in capability matrix); `<dnsserver>` / `<timeservers>` /
  `<timezone>` / `<syslog>` are declared supported but parser /
  render wire-up is incomplete on several of them.

## Aruba AOS-S

Source: [Aruba AOS-S 16.10 Management and Configuration Guide](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MCG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
hostname "fw01"

ip dns server-address priority 1 10.0.10.53
ip dns server-address priority 2 10.0.10.54

sntp server priority 1 10.0.10.123

time timezone -480
time daylight-time-rule continental-us-and-canada

logging 10.0.10.200
```

Aruba AOS-S notes:

- Hostname is double-quoted in `show running-config`.  No first-class
  `domain` directive — operators fold an FQDN into the hostname when
  needed.  The aruba_aoss codec does not parse a separate domain.
- DNS resolvers carry priority ordinals; SNTP server list also.
- Time protocol is SNTP, not full NTP.
- Timezone is a minute-offset integer; DST is a separate
  `time daylight-time-rule <region>` directive.

## Cross-vendor mapping

OPNsense -> Aruba:

- `hostname`: **good** — OPNsense `<hostname>` (bare short name) ↔
  Aruba quoted form.  Round-trip is lossless on the string content.
- `domain`: **lossy** — OPNsense `<domain>` has no first-class Aruba
  destination.  The aruba_aoss codec does not currently parse or
  render a separate domain directive; cross-pair render drops the
  field unless the operator pre-folds it into the hostname
  (`hostname "host.example.com"`).
- `dns_servers`: **good** — OPNsense `<dnsserver>` list (in element
  order) maps to Aruba `ip dns server-address priority N <addr>`
  with priority synthesised from list index (priority 1 = first).
- `ntp_servers`: **lossy** — OPNsense's space-separated
  `<timeservers>` element parses to a list of strings on canonical;
  Aruba's `sntp server priority N <addr>` lines round-trip the host
  list but lose the OPNsense pool-server semantic
  (`pool.ntp.org`-style host names work but Aruba's SNTP client may
  not handle pool A-record rotation as gracefully as OPNsense's full
  NTP daemon).  Per-server modifiers drop on round-trip.
- `timezone`: **lossy** — OPNsense Olson zoneinfo
  (`America/Los_Angeles`) versus Aruba `time timezone <minutes>`
  (e.g. `-480` for PST) require an operator-curated mapping table.
- `syslog_servers`: **good** — OPNsense `<syslog>/<remoteserver>` ↔
  Aruba `logging <addr>`.  Codec wire-up is incomplete on the
  OPNsense side today; the field drops at parse boundary pending the
  capability matrix `/system/syslog-remote-host` wire-up.  Marked
  `lossy` rather than `good` until parse lands.

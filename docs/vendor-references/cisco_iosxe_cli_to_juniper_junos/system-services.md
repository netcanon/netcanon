# System services: Cisco IOS-XE versus Juniper Junos

Hostname, domain, DNS, NTP, syslog, and timezone — the small surface
shared by every device.

Sources:
- Cisco: https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/fundamentals/configuration/xe-17/fundamentals-xe-17-book.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/system-basics/topics/topic-map/initial-configuration-junos-os.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/sys-mgmt/topics/concept/syslog-overview.html (retrieved 2026-04-30)

Citation ids: `cisco-fundamentals`, `junos-initial-config`, `junos-syslog-overview`.

## Cisco IOS-XE form

```
hostname leaf-01
ip domain name example.com
ip name-server 10.0.0.53
ip name-server 10.0.0.54
ntp server 10.0.0.10
ntp server 10.0.0.11 prefer
clock timezone PST -8 0
clock summer-time PDT recurring
logging host 10.0.0.99
logging trap informational
```

## Junos form

```
set system host-name leaf-01
set system domain-name example.com
set system name-server 10.0.0.53
set system name-server 10.0.0.54
set system ntp server 10.0.0.10
set system ntp server 10.0.0.11 prefer
set system time-zone America/Los_Angeles
set system syslog host 10.0.0.99 any info
```

## Mapping notes

- **Hostname.** `hostname X` -> `set system host-name X`.
  Round-trip is lossless on the FQDN/short-name string.
- **Domain.** Cisco's `ip domain name X` (or the deprecated `ip
  domain-name X`) -> Junos's `set system domain-name X`.  Both
  accept the same FQDN form; round-trip lossless.
- **DNS servers.** Both vendors accept multiple `name-server`
  lines.  Round-trip is lossless on the address list.  Canonical
  `dns_servers: list[str]` is the cross-vendor surface.
- **NTP servers.** Address list round-trips; per-server options
  (`prefer`, `iburst`, `key <id>`, `source <iface>`) are NOT
  modelled canonically and drop on cross-vendor round-trip.
- **Timezone.** Cisco emits `clock timezone <abbrev> <offset>
  <minutes>` plus optional `clock summer-time` for DST.  Junos
  emits `set system time-zone <Olson-id>` (e.g.
  `America/Los_Angeles`).  Cisco abbreviation -> Olson mapping is
  not canonical; operator-curated translation is required for
  full DST fidelity.  Canonical preserves the source string
  verbatim, so a Cisco-derived `PST -8 0` token will not round-
  trip cleanly to Junos.
- **Syslog.** Cisco's `logging host X` (with implicit
  any-severity) maps to Junos's `set system syslog host X any
  info` (explicit severity required).  Per-facility / severity
  filters are not modelled canonically; the host list round-trips.

Disposition: **good** on hostname / domain / DNS / NTP-host-list /
syslog-host-list; **lossy** on timezone (token form) and per-
server NTP options.

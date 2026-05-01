# System services: Juniper Junos versus Cisco IOS-XE

Hostname, domain, DNS, NTP, syslog, and timezone.

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/system-basics/topics/topic-map/initial-configuration-junos-os.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/sys-mgmt/topics/concept/syslog-overview.html (retrieved 2026-04-30)
- Cisco: https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/fundamentals/configuration/xe-17/fundamentals-xe-17-book.html (retrieved 2026-04-30)

Citation ids: `junos-initial-config`, `junos-syslog-overview`, `cisco-fundamentals`.

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
set system syslog file messages any notice
```

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

## Mapping notes

- **Hostname / domain / DNS / NTP host list.** Round-trip cleanly.
  Canonical `hostname`, `domain`, `dns_servers`, `ntp_servers`
  all carry the cross-vendor surface losslessly on the lists/
  primary scalars.
- **Timezone.** Junos uses Olson zoneinfo names
  (`America/Los_Angeles`); Cisco uses abbreviation +
  offset/minute tokens (`PST -8 0`) plus optional
  `clock summer-time` for DST.  Junos -> Cisco render needs an
  Olson-to-abbreviation translation table for full DST fidelity;
  canonical preserves the source string verbatim, so the operator
  may need to adjust manually after migration.
- **NTP per-server options.** Junos's `prefer` / `iburst` / `key`
  / `boot-server` and Cisco's `prefer` / `iburst` / `key` /
  `source` flags are not modelled canonically; the address list
  round-trips, options drop.
- **Syslog.** Junos's `set system syslog host X any info`
  (severity required) maps to Cisco's `logging host X`
  (severity implicit).  Per-facility / severity filters are not
  modelled; the host list round-trips.

Disposition: **good** on hostname / domain / DNS / NTP-host-list /
syslog-host-list; **lossy** on timezone (token form) and per-
server NTP options.

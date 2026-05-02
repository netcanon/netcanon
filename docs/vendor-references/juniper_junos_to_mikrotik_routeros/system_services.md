# System services (hostname / DNS / NTP / syslog / timezone): Juniper Junos versus MikroTik RouterOS

How baseline system-identity directives are declared on each platform.

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/system-basics/topics/topic-map/initial-configuration-junos-os.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/sys-mgmt/topics/concept/syslog-overview.html (retrieved 2026-05-01)
- MikroTik: https://help.mikrotik.com/docs/spaces/ROS/pages/40992856/Identity (retrieved 2026-05-01)
- MikroTik: https://help.mikrotik.com/docs/spaces/ROS/pages/40992866/Clock (retrieved 2026-05-01)

Citation ids: `junos-initial-config`, `junos-syslog-overview`,
`mikrotik-identity`, `mikrotik-clock`.

## Junos form

```
set system host-name kitchen-sink-junos
set system domain-name lab.example.net
set system name-server 10.0.0.53
set system name-server 10.0.0.54
set system ntp server 10.0.0.123
set system ntp server 10.0.0.124 prefer
set system syslog host 10.0.0.250 any any
set system time-zone America/New_York
```

Junos uses Olson zoneinfo names exclusively for `time-zone`.  Per-host
syslog severity / facility filters are explicit per-host
(`set system syslog host X any info`).  Junos's `set system domain-name`
is a first-class device-identity attribute used for FQDN expansion
and as the default DNS-resolver search domain.

## RouterOS form

```
/system identity
set name=ks-edge-01

/system clock
set time-zone-name=America/New_York

/ip dns
set servers=1.1.1.1,8.8.8.8

/system ntp client
set enabled=yes servers=10.0.0.123,pool.ntp.org

/system logging action
add bsd-syslog=no name=remote-syslog remote=10.0.0.20 remote-port=514 \
    target=remote
```

RouterOS keeps domain hints inside the DNS resolver search list
(`/ip dns set domain=...`) rather than as a top-level identity
attribute.  RouterOS uses NTPv4 (`/system ntp client`) — there is no
SNTP-vs-NTP distinction on this platform.  Syslog destinations split
into a `/system logging action` (the destination) plus a `/system
logging` rule (the topic filter); the canonical surface stores host
addresses only, so per-severity / per-facility semantics drop on
round-trip.

## Cross-vendor mapping

* `hostname`: Junos `set system host-name X` -> RouterOS `/system
  identity set name=X`.  Identical semantic; clean direct map.
* `domain`: Junos `set system domain-name <fqdn>` has no first-class
  RouterOS analogue.  RouterOS's `/ip dns set domain=` is a DNS-
  resolver attribute with different scope.  Drop on render unless
  the codec emits it as a `/ip dns` line, which changes its semantic.
* `dns_servers`: Junos's per-line `set system name-server <addr>`
  collapses to a list; RouterOS emits a single comma-separated
  `/ip dns set servers=<addr>,<addr>`.  Round-trip preserves the
  ordered list.
* `ntp_servers`: address list round-trips (Junos `set system ntp
  server X` -> RouterOS `/system ntp client set servers=X,...`).
  Junos per-server modifiers (`prefer`, `key`, `iburst`, `source`)
  drop on canonical round-trip — canonical model is `list[str]` only
  and RouterOS exposes no per-server options.
* `timezone`: both vendors use Olson zoneinfo names
  (`America/New_York`).  Junos `set system time-zone X` -> RouterOS
  `/system clock set time-zone-name=X`.  Direct mapping for
  parsable Olson names.
* `syslog_servers`: Junos `set system syslog host X any info` ->
  RouterOS `/system logging action add target=remote remote=X` plus
  a `/system logging add` rule for the topic filter.  Per-severity /
  per-facility semantics drop on round-trip.

Disposition: **good** for hostname / DNS / timezone; **lossy** for NTP
(per-server modifiers) and syslog (severity/facility filters); **lossy**
for domain (semantic-scope mismatch between identity and DNS-resolver
attribute).

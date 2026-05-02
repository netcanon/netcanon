# System services (hostname / DNS / NTP / syslog / timezone): MikroTik RouterOS versus Juniper Junos

How baseline system-identity directives are declared on each platform.

Sources:
- MikroTik: https://help.mikrotik.com/docs/spaces/ROS/pages/40992856/Identity (retrieved 2026-05-01)
- MikroTik: https://help.mikrotik.com/docs/spaces/ROS/pages/40992866/Clock (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/system-basics/topics/topic-map/initial-configuration-junos-os.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/sys-mgmt/topics/concept/syslog-overview.html (retrieved 2026-05-01)

Citation ids: `mikrotik-identity`, `mikrotik-clock`,
`junos-initial-config`, `junos-syslog-overview`.

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

RouterOS uses `/system identity set name=` for hostname.  Domain
hints live in `/ip dns set domain=` (DNS-resolver scope) rather than
as a top-level identity attribute.  RouterOS uses NTPv4 (`/system
ntp client`), comma-separated server list.  Timezone uses Olson
zoneinfo names in `/system clock set time-zone-name=`.  Syslog
destinations split into `/system logging action` (the destination)
plus `/system logging` (the topic filter).  The mikrotik_routeros
codec does not advertise NTP or timezone or syslog as supported in
its parse path today (only hostname / DNS / IP / VLAN / static
routes / SNMP / RADIUS / DHCP-server / user / interface ethernet /
bonding / vlan); per-direction the canonical fields populate from
parsed surfaces only.

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
syslog severity / facility filters are explicit per-host (`set system
syslog host X any info`).  Domain (`set system domain-name X`) is a
first-class device-identity attribute used for FQDN expansion and as
the default DNS-resolver search domain.

## Cross-vendor mapping

* `hostname`: RouterOS `/system identity set name=X` -> Junos
  `set system host-name X`.  Identical semantic.
* `domain`: RouterOS source rarely carries `domain` (lives under DNS
  resolver, not modelled in the canonical surface today).  Field is
  typically empty after RouterOS parse so Junos render emits no
  `set system domain-name` line.  Inverse direction: Junos source's
  domain attribute (identity scope) drops on RouterOS render
  because the target attribute (DNS-resolver scope) carries different
  semantic.
* `dns_servers`: RouterOS comma-separated `/ip dns set servers=A,B`
  -> Junos per-line `set system name-server A` lines.  List
  preserved.
* `ntp_servers`: RouterOS `/system ntp client set servers=A,B,...`
  -> Junos per-line `set system ntp server A`.  Round-trip clean.
* `timezone`: both use Olson zoneinfo names; RouterOS `/system clock
  set time-zone-name=America/New_York` -> Junos `set system time-zone
  America/New_York`.  Direct mapping.
* `syslog_servers`: RouterOS `/system logging action add target=
  remote remote=X` -> Junos `set system syslog host X any any`.
  RouterOS splits filter (topics) from destination; the canonical
  surface stores host addresses only, so per-severity / per-facility
  semantics drop on round-trip.

Disposition: **good** for hostname / DNS / NTP / timezone; **lossy**
for syslog (severity/facility filters drop) and for domain (parse-
side absence on RouterOS source path).

# System services (DNS / NTP / syslog / hostname / domain): Juniper Junos versus Aruba AOS-S

How baseline system services are declared on each platform.

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/system-basics/topics/topic-map/initial-configuration-junos-os.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/sys-mgmt/topics/concept/syslog-overview.html (retrieved 2026-05-01)
- Aruba: https://www.arubanetworks.com/techdocs/AOS-S/16.10/MCG/2930F-3810-5400/index.htm (retrieved 2026-05-01)

Citation ids: `junos-initial-config`, `junos-syslog-overview`,
`aruba-system-services`.

## Junos form

```
set system host-name kitchen-sink-junos
set system domain-name lab.example.net
set system name-server 10.0.0.53
set system name-server 10.0.0.54
set system ntp server 10.0.0.123
set system ntp server 10.0.0.124 prefer
set system syslog host 10.0.0.250 any any
set system syslog host 10.0.0.251 any notice
set system time-zone America/New_York
```

Junos uses Olson zoneinfo names exclusively for `time-zone`.  Per-
host syslog severity / facility filters are explicit per-host
(`set system syslog host X any info`).

## Aruba AOS-S form

```
hostname "ks-aoss-edge-01"

ip dns server-address priority 1 10.0.10.53
ip dns server-address priority 2 10.0.10.54

sntp server priority 1 10.0.10.123
sntp server priority 2 10.0.10.124
```

The aruba_aoss codec's parse + render surface does NOT include
`domain`, `syslog`, `mtu`, or `timezone` directives — these
parse-and-ignore on Aruba target render today (per the kitchen-sink
fixture header: "timezone, syslog, mtu, domain — NOT supported by
the aruba_aoss codec parser; intentionally omitted").

## Cross-vendor mapping

* `hostname`: Junos `host-name` -> Aruba `hostname`; Aruba quotes
  the value on `show running-config`.  Round-trip lossless on the
  string.
* `domain`: Junos `set system domain-name` lands on
  `CanonicalIntent.domain`.  Aruba codec's render path does NOT emit
  a domain directive (no parse path for `ip domain-name` or
  equivalent on AOS-S today), so the field is dropped on Aruba
  render.  Lossy by deferral.
* `dns_servers`: Junos `set system name-server <addr>` lines collect
  into the canonical list; Aruba render emits `ip dns server-address
  priority N <addr>` lines with synthetic priority numbers (1, 2,
  ...).
* `ntp_servers`: protocol distinction (Junos NTP vs Aruba SNTP) is
  not modelled canonically.  Per-server modifiers (Junos `prefer` /
  `key`) drop on round-trip.
* `syslog_servers`: Junos `set system syslog host X any info`
  populates the canonical host list (severity / facility filters
  drop on canonical layer).  Aruba render does NOT emit syslog
  directives (no parse path for `logging <host>` on the AOS-S
  codec today).  Lossy by deferral.
* `timezone`: Junos `time-zone <Olson>` lands on
  `CanonicalIntent.timezone` verbatim.  Aruba render does not emit
  `time timezone <minute-offset>` (no parse path on the codec
  today).  Lossy by deferral.

Disposition: **good** for hostname / DNS; **lossy** for NTP
(protocol distinction); **unsupported** for domain / syslog /
timezone on Aruba target (codec render path absent).

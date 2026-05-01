# System services (DNS / NTP / syslog / hostname / domain): Aruba AOS-S versus Juniper Junos

How baseline system services are declared on each platform.

Sources:
- Aruba: https://www.arubanetworks.com/techdocs/AOS-S/16.10/MCG/2930F-3810-5400/index.htm (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/system-basics/topics/topic-map/initial-configuration-junos-os.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/sys-mgmt/topics/concept/syslog-overview.html (retrieved 2026-05-01)

Citation ids: `aruba-system-services`, `junos-initial-config`,
`junos-syslog-overview`.

## Aruba AOS-S form

```
hostname "ks-aoss-edge-01"

ip dns server-address priority 1 10.0.10.53
ip dns server-address priority 2 10.0.10.54

sntp server priority 1 10.0.10.123
sntp server priority 2 10.0.10.124
```

Hostname is quoted on AOS-S `show running-config` output; the codec
strips the quotes on parse.  AOS-S uses **SNTP** (Simple NTP) as its
time-protocol primitive — the protocol distinction from full NTP is
not modelled canonically.

The aruba_aoss codec's parse surface does **not** include `domain`,
`syslog`, `mtu`, or `timezone` directives — these are intentionally
omitted from the codec's supported set today, so the canonical
fields are always empty on Aruba parse (per the kitchen-sink fixture
header comment).

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

Junos uses Olson zoneinfo names exclusively for `time-zone`.  Per-
host syslog severity / facility filters are explicit per-host
(`set system syslog host X any info`).

## Cross-vendor mapping

* `hostname`: Aruba quoted hostname -> Junos `set system host-name X`.
  Quote-stripping happens on Aruba parse; Junos render emits the
  bare token.  Round-trip is lossless on the FQDN/short-name string.
* `domain`: Aruba parse does not populate `domain` (no first-class
  parse path); Junos source -> Aruba drops the field with no Aruba
  emission.  Aruba source always carries an empty value.
* `dns_servers`: Aruba's priority-ordered `ip dns server-address`
  lines collapse to a list (priority sort applied); Junos render
  emits `set system name-server <addr>` lines in that order.  The
  priority numeric drops on the canonical layer.
* `ntp_servers`: protocol distinction (Aruba SNTP vs Junos NTP) is
  not modelled canonically.  Per-server modifiers (Aruba priority
  overrides; Junos `prefer` / `key`) drop on round-trip.
* `syslog_servers`: Aruba parse does not populate the canonical
  list (no syslog parse path on the codec today); Junos source ->
  Aruba drops the host list with no Aruba emission.
* `timezone`: Aruba parse does not populate `timezone`; Junos source
  -> Aruba drops the value.

Disposition: **good** for hostname / DNS; **lossy** for NTP (protocol
distinction + per-server modifiers); **not_applicable** for domain /
syslog / timezone on Aruba source (parse path absent).

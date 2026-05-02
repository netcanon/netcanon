# System services (hostname / DNS / NTP / domain / timezone / syslog)

How the basic management-plane scalars are configured on each platform.

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/system-basics/topics/topic-map/initial-configuration-junos-os.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/sys-mgmt/topics/concept/syslog-overview.html (retrieved 2026-05-01)
- Arista: https://www.arista.com/en/um-eos/eos-system-management (retrieved 2026-05-01)

Citation ids: `junos-initial-config`, `junos-syslog-overview`,
`arista-system-management`.

## Junos form

```
set system host-name leaf01
set system domain-name example.net
set system name-server 1.1.1.1
set system name-server 8.8.8.8
set system ntp server 10.0.0.1
set system ntp server 10.0.0.2 prefer
set system time-zone America/Los_Angeles
set system syslog host 10.0.5.1 any info
set system syslog host 10.0.5.1 authorization any
set system syslog host 10.0.5.1 firewall any
```

Junos requires Olson timezone IDs (`America/Los_Angeles`).  `set system
syslog host` allows per-host facility/severity filters; the
`any info` shortcut is the closest match to Arista's implicit "send
everything informational and above".

## Arista form

```
hostname leaf01
ip domain-name example.net
ip name-server vrf default 1.1.1.1
ip name-server vrf default 8.8.8.8
ntp server 10.0.0.1
ntp server 10.0.0.2 prefer
clock timezone America/Los_Angeles
logging host 10.0.5.1
```

Arista accepts both Olson IDs (`America/Los_Angeles`) and shortened
abbreviations (`PST`, `EST`); the operator-typed Junos Olson ID
round-trips losslessly.  `logging host` is implicitly any-any (every
syslog message of every facility, severity threshold tunable
separately).

## Mapping notes

- **Hostname.** Round-trip lossless on the FQDN/short-name string.
- **Domain.** Junos's `set system domain-name` -> Arista's
  `ip domain-name` — one-to-one.
- **DNS servers.** Junos's `set system name-server <addr>` lines
  collect into the canonical list; Arista render emits
  `ip name-server vrf default <addr>` lines (Arista requires the
  explicit `vrf default` qualifier or it parses as a VRF-named server).
- **NTP servers.** Both use NTP (no SNTP/NTP protocol distinction
  here, unlike the Aruba pair).  Per-server modifiers (`prefer`)
  preserved.
- **Timezone.** Junos's strict Olson form is a strict subset of
  Arista's accepted set; lossless one direction (Junos -> Arista).
- **Syslog.** Junos's per-host facility filters
  (`firewall any`, `authorization any`) drop on canonical layer (the
  `CanonicalSyslogServer` model carries host + transport but not
  per-host facility map); the host list itself maps to Arista
  `logging host`.  Per-severity gating on Arista lives at the
  device-global `logging trap` level — different shape, no
  bidirectional facility-level fidelity.

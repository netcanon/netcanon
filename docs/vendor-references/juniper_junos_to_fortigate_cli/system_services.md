# System services (hostname / DNS / NTP / syslog / clock / domain): Juniper Junos versus FortiGate FortiOS

## Juniper Junos

Source: [Junos Initial Configuration topic-map](https://www.juniper.net/documentation/us/en/software/junos/system-basics/topics/topic-map/initial-configuration-junos-os.html).
Source: [Junos syslog overview](https://www.juniper.net/documentation/us/en/software/junos/sys-mgmt/topics/concept/syslog-overview.html).
Retrieved: 2026-05-01.

Junos uses hierarchical `set system ...` form:

```
set system host-name junos-edge
set system domain-name example.com
set system time-zone America/Los_Angeles
set system name-server 10.0.0.53
set system name-server 10.0.0.54
set system name-server 10.0.0.55
set system ntp server 0.pool.ntp.org
set system ntp server time.google.com prefer
set system syslog host 10.0.0.250 any any
set system syslog host 10.0.0.251 any notice
set system syslog host 10.0.0.252 any info
```

Notable Junos specifics:

- **Time-zone**: Olson zoneinfo names (`America/Los_Angeles`, `UTC`,
  `Europe/London`, `Asia/Tokyo`).
- **DNS**: repeated `set system name-server X` (unbounded).
- **NTP**: repeated `set system ntp server X [prefer]` (unbounded);
  per-server options include `prefer`, `key`, `boot-server`,
  `source-address`.
- **Syslog**: repeated `set system syslog host X <facility>
  <severity>` (unbounded); per-host facility / severity filters.

## FortiGate FortiOS

Source: [Fortinet Document Library — FortiGate / FortiOS CLI Reference 7.4](https://docs.fortinet.com/document/fortigate/7.4.0/cli-reference/).
Source: [FortiGate / FortiOS Administration Guide 7.4](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/).
Retrieved: 2026-05-01.

FortiOS uses `config / edit / set / next / end` 5-keyword grammar:

```
config system global
    set hostname "fgt-edge"
    set timezone 04
end
config system dns
    set primary 10.0.0.53
    set secondary 10.0.0.54
    set domain "example.com"
end
config system ntp
    set ntpsync enable
    set type custom
    config ntpserver
        edit 1
            set server "0.pool.ntp.org"
        next
        edit 2
            set server "time.google.com"
        next
    end
end
config log syslogd setting
    set status enable
    set server "10.0.0.250"
    set facility local6
    set port 514
end
config log syslogd2 setting
    set status enable
    set server "10.0.0.251"
end
config log syslogd3 setting
    set status enable
    set server "10.0.0.252"
end
```

Notable FortiOS caps:

- **DNS** caps at 3 (primary / secondary / hidden tertiary).
- **Syslog backends** cap at 3 (syslogd / syslogd2 / syslogd3).
- **Timezone** uses numeric index (e.g. `04` = US Pacific, `12` = UTC).
- **NTP** under `config ntpserver` table; sequential edit IDs.

## Cross-vendor mapping (Junos -> FortiGate)

Canonical surface:

```
hostname: str = ""
domain: str = ""
dns_servers: list[str] = Field(default_factory=list)
ntp_servers: list[str] = Field(default_factory=list)
timezone: str = ""
syslog_servers: list[str] = Field(default_factory=list)
```

- **hostname** — `good`.  Junos accepts up to 255 chars; FortiOS caps
  at 35 — long Junos hostnames truncate on FortiGate render.
- **domain** — `good`.  Same FQDN preserved.
- **dns_servers** — `lossy`.  FortiOS caps at 3; Junos source with
  more loses the tail.  The FortiGate codec emits the first two from
  the canonical list.
- **ntp_servers** — `lossy`.  Address list preserves; per-server
  options drop.
- **timezone** — `lossy`.  Olson zoneinfo -> FortiOS numeric index
  requires operator-curated lookup.
- **syslog_servers** — `lossy`.  FortiOS caps at 3 backends; Junos
  source with more drops the tail.  Severity / facility tokens drop.

## Cross-vendor mapping (FortiGate -> Junos)

Reverse direction (see also `../fortigate_cli_to_juniper_junos/system_services.md`):

- **dns_servers** and **syslog_servers** are `good` in that
  direction (FortiOS source already capped at 3; Junos accepts more).
- The other fields are direction-symmetric.

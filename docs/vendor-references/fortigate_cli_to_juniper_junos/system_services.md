# System services (hostname / DNS / NTP / syslog / clock / domain): FortiGate FortiOS versus Juniper Junos

## FortiGate FortiOS

Source: [Fortinet Document Library — FortiGate / FortiOS CLI Reference 7.4 — `config system global / dns / ntp` ](https://docs.fortinet.com/document/fortigate/7.4.0/cli-reference/).
Source: [FortiGate / FortiOS Administration Guide 7.4](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/).
Retrieved: 2026-05-01.

FortiOS uses the `config / edit / set / next / end` 5-keyword grammar
for every section.  System services live in `config system <topic>`
blocks:

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
    set server "10.0.0.200"
    set facility local6
    set port 514
end
```

Notable FortiOS specifics:

- `set timezone <NN>` uses a numeric index per the FortiOS Cookbook
  timezone table (e.g. `04` = US Pacific, `12` = UTC).
- `set domain` lives under `config system dns`, not as a separate
  `domain-name` directive.  Both vendors capture the same FQDN.
- NTP servers nest inside `config ntpserver` table under `config
  system ntp` with numeric edit IDs.  `set type custom` must be set
  or FortiOS reverts to its built-in pool.
- Syslog under `config log syslogd setting` (or `syslogd2` /
  `syslogd3` peers for additional backends — capped at three).

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
set system ntp server 0.pool.ntp.org
set system ntp server time.google.com prefer
set system syslog host 10.0.0.200 any info
```

Notable Junos specifics:

- `set system time-zone` uses Olson zoneinfo names
  (`America/Los_Angeles`, `UTC`, `Europe/London`).
- DNS via repeated `set system name-server X` (unbounded).
- NTP via repeated `set system ntp server X [prefer]` (unbounded);
  per-server options include `prefer`, `key`, `boot-server`,
  `source-address`.
- Syslog via `set system syslog host X <facility> <severity>` —
  unbounded.

## Cross-vendor mapping (FortiGate -> Junos)

Canonical surface:

```
hostname: str = ""
domain: str = ""
dns_servers: list[str] = Field(default_factory=list)
ntp_servers: list[str] = Field(default_factory=list)
timezone: str = ""
syslog_servers: list[str] = Field(default_factory=list)
```

- **hostname** — `good`.  FortiOS `set hostname "X"` -> Junos `set
  system host-name X`.  FortiOS caps at 35 chars; Junos accepts up to
  255 — no truncation in this direction.
- **domain** — `good`.  Same FQDN preserved.
- **dns_servers** — `good`.  FortiOS caps at 3; Junos unbounded — no
  truncation in this direction.
- **ntp_servers** — `lossy`.  Address list survives; per-server
  options (FortiOS `set authentication`, Junos `prefer`/`key`)
  drop on round-trip (canonical schema gap).
- **timezone** — `lossy`.  FortiOS numeric index <-> Olson zoneinfo
  requires operator-curated lookup table.  FortiGate codec does not
  parse / render the timezone field today.
- **syslog_servers** — `good`.  FortiOS three-backend cap fits Junos's
  unbounded list; Junos render emits `set system syslog host X any
  info` per server.  Severity / facility tokens drop (canonical
  schema gap).

## Cross-vendor mapping (Junos -> FortiGate)

Reverse direction (see also `../juniper_junos_to_fortigate_cli/system_services.md`):

- **dns_servers** — `lossy` because FortiOS caps at 3; Junos source
  with more loses the tail.
- **syslog_servers** — `lossy` because FortiOS caps at 3 backends.
- The other fields are direction-symmetric.

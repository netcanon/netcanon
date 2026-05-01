# System services (hostname / NTP / DNS / logging / clock): Cisco IOS-XE versus FortiGate FortiOS CLI

## Cisco IOS-XE

Source: Cisco IOS XE Network Management Configuration Guide — system
services chapter; same surface used in the
[`cisco_iosxe_cli_to_arista_eos/system_services.md`](../cisco_iosxe_cli_to_arista_eos/system_services.md)
sibling document.

```
hostname switch1
ip domain name example.com
ip name-server 10.0.0.53
ip name-server 10.0.0.54

ntp server 10.0.0.130
ntp server 10.0.0.131 prefer

clock timezone PST -8 0
clock summer-time PDT recurring

logging host 10.0.0.200
logging trap informational
logging facility local6
```

The directives are top-level globals; no `config / end` block grammar.

## FortiGate FortiOS CLI

Source: [Fortinet Document Library — FortiGate CLI Reference / system global](https://docs.fortinet.com/document/fortigate/7.4.0/cli-reference/) (FortiOS 7.4 CLI Reference).
Source: [Fortinet Document Library — FortiOS Cookbook — system / dns, system / ntp, system / dns-server](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/).
Retrieved: 2026-04-30

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
            set server "10.0.0.130"
        next
        edit 2
            set server "10.0.0.131"
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

- `set timezone <NN>` uses a **numeric index** (e.g. `04` = US Pacific,
  `12` = UTC) per the FortiOS Cookbook timezone table — unlike Cisco's
  `clock timezone PST -8 0` (offset+DST tokens) or Arista's zoneinfo
  string.  All three vendors carry different surface representations of
  the same underlying concept.
- `set domain` lives under `config system dns`, not in a separate
  `domain-name` directive.  Both vendors capture the same FQDN.
- NTP servers are nested inside `config ntpserver` table under
  `config system ntp`, with numeric edit IDs.  The associated `set
  type custom` must be set or FortiOS reverts to its built-in pool.
- Syslog is written under `config log syslogd setting` (or the
  `syslogd2` / `syslogd3` peers for a second / third backend).
  FortiOS does not have a Cisco-style `logging trap <severity>`;
  severity is set via `set severity <level>` (debug | information |
  notification | warning | error | critical | alert | emergency).

## Cross-vendor mapping (Cisco -> FortiGate)

The canonical surface is several scalar / list fields on
`CanonicalIntent`:

```
hostname: str = ""
domain: str = ""
dns_servers: list[str] = Field(default_factory=list)
ntp_servers: list[str] = Field(default_factory=list)
timezone: str = ""
syslog_servers: list[str] = Field(default_factory=list)
```

- **hostname** — `good`.  Cisco `hostname switch1` -> FortiOS `set
  hostname "switch1"`.  Both accept free-form names within length
  limits (FortiOS caps at 35 characters per the system-global
  reference; Cisco caps at 63).  Names longer than 35 chars truncate
  on FortiOS render.
- **domain** — `good` (with caveat).  Cisco `ip domain name X` -> FortiOS
  `set domain "X"` under `config system dns`.  Same FQDN preserved.
- **dns_servers** — `lossy`.  FortiOS schemas its DNS into `set primary`
  + `set secondary` (and a hidden `set tertiary`), so the third+
  servers in a Cisco list will be dropped on render.  The FortiOS codec
  emits the first two from the canonical list.
- **ntp_servers** — `lossy`.  Address list itself is preserved, but
  Cisco's per-server `prefer` / `key` / `source` options are not in the
  canonical model and drop on round-trip.
- **timezone** — `lossy`.  Cisco `clock timezone PST -8 0` and FortiOS
  `set timezone 04` carry semantically equivalent intent through
  vendor-specific surfaces.  Cross-vendor migration would require
  an operator-curated lookup table from offset/zoneinfo to FortiOS's
  numeric index.  Canonical model stores the source string verbatim;
  the FortiGate codec does not currently parse / render the timezone
  numeric index.
- **syslog_servers** — `lossy`.  Cisco's host list maps to FortiOS's
  `config log syslogd setting / set server` (single server) plus the
  second/third peers (`syslogd2`, `syslogd3`).  FortiOS therefore
  caps at three syslog backends; lists longer than three drop the
  tail.  Severity / facility tokens are not canonically modelled.

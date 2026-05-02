# System services (hostname / DNS / NTP / syslog / clock / domain): FortiGate FortiOS CLI versus Arista EOS

## FortiGate FortiOS CLI

Source: [Fortinet Document Library — FortiGate CLI Reference 7.4](https://docs.fortinet.com/document/fortigate/7.4.0/cli-reference/)
Source: [Fortinet Document Library — FortiOS Cookbook (timezone numeric-index table)](https://docs.fortinet.com/document/fortigate/7.4.0/cookbook/)
Retrieved: 2026-05-01

```
config system global
    set hostname "fgt-edge"
    set timezone 04
end
config system dns
    set primary 10.0.0.53
    set secondary 10.0.0.54
    set domain "example.net"
end
config system ntp
    set ntpsync enable
    set type custom
    config ntpserver
        edit 1
            set server "10.0.0.123"
        next
    end
end
config log syslogd setting
    set status enable
    set server "10.0.0.250"
    set facility local6
end
```

Notable FortiOS specifics:

- **Hostname is quoted**, caps at 35 characters under ``config
  system global``.
- **DNS schema is fixed**: `set primary` / `set secondary` / hidden
  `set tertiary`; codec parses all three when present.
- **Domain lives under `config system dns`** as `set domain "X"`.
- **NTP daemon** with explicit `set ntpsync enable` and `set type
  custom` outside the per-server table.
- **Timezone is a numeric index** (`set timezone 04`) per the
  FortiOS Cookbook timezone table.
- **Three syslog backends** (`syslogd` / `syslogd2` / `syslogd3`).

## Arista EOS

Source: [Arista EOS User Manual — Switch Administration Commands (4.35.2F)](https://www.arista.com/en/um-eos/eos-switch-administration-commands)
Retrieved: 2026-05-01

```
hostname ks-leaf-01
!
ip name-server vrf default 10.0.0.53
ip name-server vrf default 10.0.0.54
dns domain example.net
!
ntp server 10.0.0.123
ntp server 10.0.0.124 prefer
!
clock timezone US/Pacific
!
logging host 10.0.0.250
logging trap informational
logging facility local6
```

Notable Arista specifics:

- **Hostname is unquoted**, accepts up to 255 characters.
- **DNS via `ip name-server vrf default <addr>`** (modern form);
  legacy `ip domain-name` etc. also accepted.  No fixed cap on
  number of name-servers.
- **Domain via `dns domain <fqdn>`** as a top-level scalar.
- **Full NTP** (not SNTP) with per-server modifiers (`prefer`,
  `iburst`, `key`, `source`) — modifiers drop on canonical.
- **`clock timezone` accepts zoneinfo names** (e.g. `US/Pacific`);
  DST is implicit in zoneinfo data.
- **`logging host <addr>`** with global severity / facility filters
  via `logging trap` / `logging facility`.

## Cross-vendor mapping (FortiGate -> Arista)

Canonical surface:

```
hostname: str = ""
domain: str = ""
dns_servers: list[str]
ntp_servers: list[str]
timezone: str = ""
syslog_servers: list[str]
```

- **hostname** — `good`.  FortiOS `set hostname "fgt-edge"` ->
  Arista `hostname fgt-edge`.  Codec strips/adds quotes.  No
  truncation in this direction (FortiOS source is at most 35;
  Arista accepts much more).
- **domain** — `good`.  FortiOS `set domain "X"` -> Arista `dns
  domain X`.  Round-trip lossless.
- **dns_servers** — `good`.  FortiOS source carries at most three
  DNS servers (primary / secondary / tertiary).  Arista accepts
  more, so cross-vendor round-trip preserves the lot — no
  truncation in this direction.
- **ntp_servers** — `lossy`.  Address list preserves; per-server
  modifiers drop both ways.  FortiOS's `set ntpsync enable` /
  `set type custom` are codec-internal defaults rather than
  canonical fields.  Functional equivalence at the server-list
  level.
- **timezone** — `lossy`.  FortiOS numeric index (`04`) cannot be
  algorithmically converted to Arista zoneinfo (`US/Pacific`)
  without an operator-curated lookup.  Plus: the FortiGate codec
  does not currently parse the timezone field at all, so the
  canonical scalar is empty on this direction — the field is
  effectively `not_applicable` until codec wire-up completes,
  but classified `lossy` because the gap is a known wire-up gap
  rather than a structural absence.
- **syslog_servers** — `good`.  FortiOS three syslog backends
  collapse to canonical list; Arista emits unbounded `logging
  host <addr>` lines.  No truncation in this direction.
  Severity / facility (`set facility`) drops on round-trip.

Disposition summary: **good** for hostname / domain / dns_servers
/ syslog_servers (FortiGate-source list-length sits within Arista's
unbounded targets).  **Lossy** for ntp_servers (per-server
modifiers), timezone (format mismatch + codec wire-up gap).

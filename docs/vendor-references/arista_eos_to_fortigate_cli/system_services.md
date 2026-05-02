# System services (hostname / DNS / NTP / syslog / clock / domain): Arista EOS versus FortiGate FortiOS CLI

## Arista EOS

Source: [Arista EOS User Manual — Switch Administration Commands (4.35.2F)](https://www.arista.com/en/um-eos/eos-switch-administration-commands)
Source: [Arista EOS User Manual — System Logging (4.35.2F)](https://www.arista.com/en/um-eos/eos-system-logging)
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

- **Hostname is unquoted** in `show running-config`; codec takes the
  bare token.  EOS accepts up to 255 characters but typical operator
  use stays under 63.
- **DNS qualifies by VRF** (`ip name-server vrf default <addr>` is the
  canonical form on modern EOS); the codec strips the `vrf default`
  qualifier on parse and stores the bare address.  Per-VRF nameservers
  in non-default VRFs are not modelled.
- **Domain is a top-level scalar** via `dns domain <fqdn>` (legacy
  `ip domain-name` form is also accepted).
- **NTP is full NTP** (not SNTP) with per-server modifiers like
  `prefer` / `iburst` / `key <id>` / `source <iface>`.  Modifiers drop
  on round-trip (canonical surface is host-list-only).
- **`clock timezone` accepts zoneinfo names** (e.g. `US/Pacific`,
  `Europe/Berlin`); DST is implicit in the zoneinfo data.  Some older
  configs use abbreviation+offset (`PST -8 0`) but modern operator
  practice is the zoneinfo string.
- **`logging host` is the modern form** (older `logging <addr>` is
  also accepted).  Severity filters via `logging trap <severity>` are
  global, not per-host.

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
        edit 2
            set server "10.0.0.124"
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

- **Hostname is quoted** in running-config and **caps at 35
  characters** under `config system global`.  Arista hostnames longer
  than 35 will truncate on FortiGate render (uncommon but possible).
- **DNS schema is fixed**: `set primary` / `set secondary` plus a
  hidden `set tertiary`.  Arista source lists with more than three
  servers drop the tail.
- **Domain lives under `config system dns`** as `set domain "X"` (not
  the top-level scalar Arista uses).
- **NTP daemon** with explicit `set ntpsync enable` and `set type
  custom` outside the per-server table.  Per-server entries live in
  `config ntpserver` with sequential numeric edit IDs.
- **Timezone is a numeric index** (`set timezone <NN>`) per the
  FortiOS Cookbook timezone table (e.g. `04` = US Pacific,
  `28` = Europe/Berlin).  No zoneinfo-name form.
- **Three syslog backends** (`syslogd` / `syslogd2` / `syslogd3`)
  with separate `config log syslogd setting` / `config log syslogd2
  setting` blocks.  Lists longer than three drop the tail.

## Cross-vendor mapping (Arista -> FortiGate)

Canonical surface:

```
hostname: str = ""
domain: str = ""
dns_servers: list[str]
ntp_servers: list[str]
timezone: str = ""
syslog_servers: list[str]
```

- **hostname** — `good`.  Arista `hostname X` -> FortiOS `set hostname
  "X"`.  Length-cap caveat: 35-character FortiGate limit is below
  Arista's 255-character ceiling, but operator-typical hostnames sit
  well under 35.
- **domain** — `good`.  Arista `dns domain X` -> FortiOS `set domain
  "X"` under `config system dns`.  Cross-vendor stable.
- **dns_servers** — `lossy`.  Arista's flat `ip name-server vrf
  default <addr>` list collapses to bare addresses on canonical;
  FortiOS render emits `set primary` / `set secondary` (and hidden
  `tertiary`).  Lists longer than three drop the tail.
- **ntp_servers** — `lossy`.  Address list itself preserves; per-
  server modifiers (Arista `prefer` / `iburst`; FortiGate per-server
  `set authentication`) drop on round-trip.  Functional equivalence
  at the server-list level.
- **timezone** — `lossy`.  Arista zoneinfo name (`US/Pacific`) cannot
  be algorithmically converted to FortiOS numeric index (`04`)
  without an operator-curated lookup table.  Canonical preserves the
  source string verbatim; cross-vendor render produces a token only
  with manual intervention.  Arista codec parses timezone; FortiGate
  codec does not currently render it.
- **syslog_servers** — `lossy`.  Arista's host list maps to FortiOS's
  three syslog backends; lists longer than three drop the tail.
  Severity / facility tokens (Arista `logging trap` / `logging
  facility`) are not canonically modelled.

Disposition summary: **good** for hostname / domain.  **Lossy** for
dns_servers (3-cap), ntp_servers (per-server modifiers),
timezone (format mismatch), syslog_servers (3-cap + facility loss).

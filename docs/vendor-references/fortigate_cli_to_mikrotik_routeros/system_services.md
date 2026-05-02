# System services (hostname / DNS / NTP / timezone / syslog): FortiGate FortiOS versus MikroTik RouterOS

## FortiGate FortiOS CLI

Sources:
- [FortiGate / FortiOS 7.4 CLI Reference — system global](https://docs.fortinet.com/document/fortigate/7.4.0/cli-reference/) — `config system global / set hostname`, `set timezone <NN>`.
- [FortiGate / FortiOS 7.4 Administration Guide — DNS settings](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/) — `config system dns / set primary / set secondary / set domain`.
- [FortiGate / FortiOS 7.4 Administration Guide — NTP settings](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/) — `config system ntp / config ntpserver / set server`.
- [FortiGate / FortiOS 7.4 Administration Guide — Logging to syslog](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/) — `config log syslogd setting / set server`.

Retrieved: 2026-04-30

```
config system global
    set hostname "fgt-edge-01"
    set timezone 04
end
config system dns
    set primary 1.1.1.1
    set secondary 8.8.8.8
    set domain "lab.example.org"
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
    set server "10.50.0.20"
    set facility local6
end
```

Notable FortiOS specifics:

- `set timezone <NN>` uses a **numeric index** (e.g. `04` = US Pacific, `12` = UTC) per the FortiOS Cookbook timezone table.
- `set domain` lives under `config system dns` (one FQDN, not a search list).
- NTP servers are nested inside `config ntpserver` table under `config system ntp` with numeric edit IDs; `set type custom` must also be set or FortiOS reverts to its built-in pool.
- Syslog is written under `config log syslogd setting` (or `syslogd2` / `syslogd3` for additional backends) — capped at three remote backends.

## MikroTik RouterOS

Sources:
- [Identity — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/40992856/Identity) — `/system identity / set name=<NAME>`.
- [Clock — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/40992866/Clock) — `/system clock / set time-zone-name=<TZ>`.
- [DNS — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/37748767/DNS) — `/ip dns / set servers=<csv>`.
- [NTP — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/37748794/NTP) — `/system ntp client / set servers=<csv>`.
- [Log — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/40992869/Log) — `/system logging action / add target=remote remote=<addr>`.

Retrieved: 2026-04-30

```
/system identity
set name=fgt-edge-01

/system clock
set time-zone-name=America/Los_Angeles

/ip dns
set servers=1.1.1.1,8.8.8.8

/system ntp client
set enabled=yes servers=0.pool.ntp.org,time.google.com

/system logging action
add target=remote remote=10.50.0.20 name=remote-syslog
/system logging
add action=remote topics=info,error
```

RouterOS keeps the device name on `/system identity / set name=`.  DNS resolvers go on `/ip dns / set servers=<comma-list>`.  NTP client servers go on `/system ntp client / set servers=<comma-list>`.

Timezone uses **Olson / IANA tz database** names (`America/Los_Angeles`, `Europe/Berlin`).  RouterOS does not accept a numeric offset and does not have a separate DST-rule directive — the tz database entry already encodes DST behaviour.

Syslog requires a `/system logging action` destination plus a `/system logging` rule that binds topic / severity filters to the destination.  The destination is reusable across multiple rules.

There is no first-class `domain` directive on RouterOS at the identity scope — operators who need a default DNS search domain set it as `/ip dns set domain=<fqdn>`, which is a per-resolver attribute and not an identity attribute.

## Cross-vendor mapping (FortiGate → RouterOS)

The canonical surface is

```
CanonicalIntent.hostname: str
CanonicalIntent.domain: str
CanonicalIntent.dns_servers: list[str]
CanonicalIntent.ntp_servers: list[str]
CanonicalIntent.timezone: str
CanonicalIntent.syslog_servers: list[str]
```

- **hostname** — `good`.  FortiOS `set hostname "fgt-edge-01"` parses to `hostname="fgt-edge-01"` (quotes stripped); RouterOS render emits `/system identity / set name=fgt-edge-01`.  RouterOS rejects whitespace inside the name; FortiOS accepts spaces in quoted names but the FortiGate codec does not produce whitespace-bearing hostnames in normal use.
- **domain** — `lossy`.  FortiOS `set domain "<fqdn>"` parses, but RouterOS has no top-level identity-scope domain; the cross-vendor render lands on `/ip dns set domain=<fqdn>` which is structurally a resolver-level field.  The MikroTik codec does not currently parse / render that line either, so the value typically drops on render.
- **dns_servers** — `good`.  FortiGate's two-server (`primary` / `secondary`) surface fits inside RouterOS's comma-list; FortiGate-source lists never exceed three so RouterOS's unbounded list does not truncate.
- **ntp_servers** — `lossy`.  Address list itself round-trips cleanly.  FortiGate-side global flags (`set ntpsync enable`, `set type custom`) and per-server modifiers (`set authentication`) are not modelled canonically; RouterOS has no per-server modifier surface anyway.
- **timezone** — `lossy`.  FortiOS `set timezone 04` (numeric index) versus RouterOS `/system clock / set time-zone-name=America/Los_Angeles` (IANA tz name).  Cross-vendor migration requires operator-curated mapping from FortiOS numeric index to IANA name (the FortiGate codec does not currently parse the timezone numeric index, and the MikroTik codec does not currently parse the tz-name).
- **syslog_servers** — `lossy`.  FortiOS `config log syslogd setting / set server` (capped at three) maps to RouterOS `/system logging action add target=remote remote=<addr>` plus a separate `/system logging` filter rule.  Severity / facility tokens (FortiOS `set facility local6`, RouterOS topic / severity binding) are not modelled canonically and drop on round-trip.

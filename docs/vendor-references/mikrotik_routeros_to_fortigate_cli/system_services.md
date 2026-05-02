# System services (hostname / DNS / NTP / timezone / syslog): MikroTik RouterOS versus FortiGate FortiOS

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
set name=ks-edge-01

/system clock
set time-zone-name=America/Los_Angeles

/ip dns
set servers=1.1.1.1,8.8.8.8

/system ntp client
set enabled=yes servers=10.0.0.123,pool.ntp.org

/system logging action
add target=remote remote=10.0.0.20 name=remote-syslog
/system logging
add action=remote topics=info,error
```

The MikroTik codec parses **hostname / DNS / NTP** into the canonical `hostname` / `dns_servers` / `ntp_servers` fields.  Timezone, syslog actions, and the `/ip dns set domain=` value are NOT parsed by the current codec — they would silently drop on parse anyway.

RouterOS does not have a first-class identity-scope domain attribute.  An optional `/ip dns set domain=<fqdn>` may be set as a resolver-level attribute but is not commonly used.

Timezone uses **Olson / IANA tz database** names (`America/Los_Angeles`, `Europe/Berlin`).  Syslog requires a `/system logging action` destination plus a `/system logging` rule binding topic / severity filters to the destination.

## FortiGate FortiOS CLI

Sources:
- [FortiGate / FortiOS 7.4 CLI Reference — system global](https://docs.fortinet.com/document/fortigate/7.4.0/cli-reference/) — `config system global / set hostname / set timezone <NN>`.
- [FortiGate / FortiOS 7.4 Administration Guide — DNS / NTP / Syslog](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/).

Retrieved: 2026-04-30

```
config system global
    set hostname "ks-edge-01"
    set timezone 04
end
config system dns
    set primary 1.1.1.1
    set secondary 8.8.8.8
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
    set server "10.0.0.20"
    set facility local6
end
```

FortiOS uses the `config / edit / set / next / end` 5-keyword grammar.  Timezone is a numeric index (`04` = US Pacific per the FortiOS Cookbook table).  DNS caps at three servers (`primary` / `secondary` / hidden `tertiary`); syslog caps at three backends (`syslogd` / `syslogd2` / `syslogd3`).

## Cross-vendor mapping (RouterOS → FortiGate)

The canonical surface is

```
CanonicalIntent.hostname: str
CanonicalIntent.domain: str
CanonicalIntent.dns_servers: list[str]
CanonicalIntent.ntp_servers: list[str]
CanonicalIntent.timezone: str
CanonicalIntent.syslog_servers: list[str]
```

- **hostname** — `good`.  RouterOS `/system identity / set name=ks-edge-01` parses to `hostname="ks-edge-01"`; FortiOS render emits `set hostname "ks-edge-01"`.  FortiOS caps at 35 characters; RouterOS-source names exceeding 35 chars truncate.
- **domain** — `not_applicable`.  RouterOS does not surface a top-level identity-scope domain field; the canonical `domain` is empty after parsing a RouterOS source.  FortiOS render emits no `set domain` line.  This is a structural absence on the source, not a translation loss.
- **dns_servers** — `lossy`.  RouterOS unbounded comma-list versus FortiOS three-server cap (`primary` / `secondary` / `tertiary`).  RouterOS-source lists with four+ entries lose the tail on FortiOS render.  Most RouterOS deployments carry only two.
- **ntp_servers** — `lossy`.  RouterOS unbounded list versus FortiOS table form with sequential edit ids.  Address list itself round-trips; FortiOS-side global flags (`set ntpsync enable`, `set type custom`) and the per-edit numeric edit id are not modelled canonically.  No per-server modifiers on either side.
- **timezone** — `lossy`.  RouterOS `/system clock / set time-zone-name=America/Los_Angeles` (IANA tz name) versus FortiOS `set timezone 04` (numeric index).  Cross-vendor migration requires operator-curated mapping from IANA name to FortiOS numeric index — neither codec currently parses / emits the timezone field.
- **syslog_servers** — `lossy`.  RouterOS `/system logging action add target=remote remote=<addr>` parses (when the codec lands the parser) to canonical syslog_servers list; FortiOS render emits `config log syslogd setting / set server` (single primary) plus `syslogd2` / `syslogd3` peers.  FortiOS caps at three.  Severity / facility / topic-filter context drops on round-trip — neither vendor's per-server filter taxonomy survives the canonical bottleneck.

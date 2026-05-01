# System services (hostname / DNS / NTP / timezone / syslog): MikroTik RouterOS versus Cisco IOS-XE

## MikroTik RouterOS

Sources:
- [Identity — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/40992856/Identity)
- [Clock — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/40992866/Clock)
- [DNS — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/37945004/DNS)
- [NTP — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/37224622/NTP+Client+and+Server)
- [Logging — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/14091786/Log)

Retrieved: 2026-04-30

```
/system identity
set name=router1

/ip dns
set servers=1.1.1.1,8.8.8.8

/system ntp client
set enabled=yes servers=10.0.0.130,10.0.0.131

/system clock
set time-zone-name=America/Los_Angeles

/system logging action
add name=remote target=remote remote=10.0.0.200
```

## Cisco IOS-XE

Source: Cisco IOS XE Network Management Configuration Guide.

```
hostname router1
ip domain name example.com
ip name-server 1.1.1.1
ip name-server 8.8.8.8

ntp server 10.0.0.130
ntp server 10.0.0.131

clock timezone PST -8 0
clock summer-time PDT recurring

logging host 10.0.0.200
```

## Cross-vendor mapping

The canonical surface is

```
hostname: str = ""
domain: str = ""
dns_servers: list[str] = Field(default_factory=list)
ntp_servers: list[str] = Field(default_factory=list)
timezone: str = ""
syslog_servers: list[str] = Field(default_factory=list)
```

### Round-trip behaviour from MikroTik source

`hostname` -> Cisco `hostname X` is a clean direct map.

`domain` is empty on MikroTik source — RouterOS does not surface a
top-level FQDN identity field — so the Cisco render emits no `ip
domain name` directive.  Operator review surface flags absence if
the target deployment expects one.

`dns_servers` round-trip the comma-separated list as one Cisco
`ip name-server` line per address.

`ntp_servers` round-trip the same way.  RouterOS does not expose
per-server NTP options; nothing to lose on the MikroTik source side
(the canonical model truncates to bare addresses anyway).

### timezone

RouterOS uses TZ-database names (`America/Los_Angeles`) directly.
Cisco's `clock timezone <name> <offset> <dst>` form expects 3-letter
abbreviations plus offset; auto-rendering an Olson name as Cisco
syntax produces a token Cisco accepts grammatically but with
default-zero offset and no DST behaviour.  Operator-curated mapping
table needed for full fidelity — this matches the
`arista -> juniper` and `cisco -> arista` timezone
characterisation.

### syslog

`/system logging action add target=remote remote=X` (RouterOS) maps
to Cisco's `logging host X`.  RouterOS's filter-side rules
(`/system logging add topics=...`) are richer than Cisco's
default-to-all behaviour; per-topic / per-severity filters drop
on the canonical round-trip (host-only model).

### Disposition summary

| Field | Disposition (MikroTik -> Cisco) |
|---|---|
| `hostname` | good |
| `domain` | not_applicable (RouterOS source rarely populates) |
| `dns_servers` | good |
| `ntp_servers` | good |
| `timezone` | lossy (TZ-database -> Cisco offset/abbrev) |
| `syslog_servers` | lossy (per-topic filters drop) |

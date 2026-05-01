# System services (hostname / DNS / NTP / timezone / syslog): Cisco IOS-XE versus MikroTik RouterOS

## Cisco IOS-XE

Source: Cisco IOS XE Network Management Configuration Guide — system
services.

```
hostname router1
ip domain name example.com
ip name-server 1.1.1.1
ip name-server 8.8.8.8

ntp server 10.0.0.130
ntp server 10.0.0.131 prefer

clock timezone PST -8 0
clock summer-time PDT recurring

logging host 10.0.0.200
logging trap informational
logging facility local6
```

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
/system logging
add action=remote topics=info
```

## Cross-vendor mapping

The canonical surface is the scalar / list set on `CanonicalIntent`:

```
hostname: str = ""
domain: str = ""
dns_servers: list[str] = Field(default_factory=list)
ntp_servers: list[str] = Field(default_factory=list)
timezone: str = ""
syslog_servers: list[str] = Field(default_factory=list)
```

### hostname / DNS / NTP

`hostname` is a direct map (`hostname X` -> `/system identity / set name=X`).
The `domain` field has no first-class RouterOS equivalent — RouterOS
carries the FQDN inside the DNS resolver search list rather than a
top-level identity attribute, so `ip domain name X` does NOT have a
clean per-pane render on the MikroTik side.  Most RouterOS deployments
omit it; the Cisco codec preserves the parsed string but the MikroTik
render emits no equivalent line.

`dns_servers` and `ntp_servers` round-trip cleanly as bare-address
lists.  RouterOS aggregates them on a single comma-separated value
(`servers=1.1.1.1,8.8.8.8`) while Cisco emits one line per server;
both codecs reconstitute the list shape on parse.  Per-server NTP
options (Cisco's `prefer` / `iburst` / `key` / `source`) drop on
canonical round-trip — the canonical model stores `list[str]` of
addresses only, and RouterOS's `/system ntp client` does not surface
per-server options anyway (it accepts a single comma-separated list
of equally-weighted servers).

### timezone

Cisco's `clock timezone PST -8 0` form (offset + name + DST tokens)
versus RouterOS's TZ-database name (`America/Los_Angeles`) is a
documented divergence.  RouterOS uses the IANA tz database directly;
Cisco accepts arbitrary 3-letter zone abbreviations plus an explicit
offset.  Cross-vendor migration may emit a token the target accepts
but with different DST semantics — operator-curated mapping table
needed for full fidelity.

### syslog

`logging host X` (Cisco) versus `/system logging action add target=
remote remote=X` (MikroTik) with separate `/system logging add action=
... topics=...` rules — RouterOS splits the destination
(action) from the filter (rule) where Cisco fuses both.  The canonical
surface stores host addresses only; per-severity / per-facility
filters drop on round-trip.  Both render paths produce a working
syslog destination but the rich filter semantics on the source side
do not survive.

### Disposition summary

| Field | Disposition |
|---|---|
| `hostname` | good |
| `domain` | lossy (no clean RouterOS render) |
| `dns_servers` | good |
| `ntp_servers` | lossy (per-server options drop) |
| `timezone` | lossy (offset+DST vs TZ-database name) |
| `syslog_servers` | lossy (host-only; severity/facility drop) |

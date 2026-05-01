# System services (hostname / NTP / DNS / logging / clock): Cisco IOS-XE versus Arista EOS

## Cisco IOS-XE

Source: Cisco IOS XE Network Management Configuration Guide — system
services.

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

## Arista EOS

Source: [EOS 4.36.0F — Switch Administration Commands](https://www.arista.com/en/um-eos/eos-switch-administration-commands)
Source: [EOS 4.36.0F — System Clock and Time Protocols](https://www.arista.com/en/um-eos/eos-system-clock-and-time-protocols)
Source: [Arista EOS Central — Configure and Troubleshoot DNS on EOS](https://ipv6-eos.arista.com/configure-and-troubleshoot-dns-on-eos/)
Retrieved: 2026-04-30

```
hostname switch1
ip domain-name example.com
ip name-server 10.0.0.53
ip name-server 10.0.0.54

ntp server 10.0.0.130 iburst
ntp server 10.0.0.131 prefer

clock timezone US/Pacific

logging host 10.0.0.200
logging trap informational
logging facility local6
```

Two notable Arista quirks:

- `ip domain-name` (hyphenated) versus Cisco's `ip domain name` (space).
  Both codecs handle the keyword variation.
- Arista timezone uses zoneinfo names (`US/Pacific`) while Cisco uses
  abbreviated zones (`PST`, with a separate `clock summer-time`
  declaration for DST).  Both forms parse to the same canonical
  string but the running-config emission differs.
- Arista NTP defaults to `iburst` for faster sync; Cisco does not.

## Cross-vendor mapping

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

Round-trip is good for hostname / domain / dns_servers /
ntp_servers / syslog_servers.

Timezone is **lossy**: Cisco's `clock timezone PST -8 0` and Arista's
`clock timezone US/Pacific` carry different information (offset+DST
versus zoneinfo).  Both codecs store the timezone as an opaque
string; cross-vendor migration may emit a token the target accepts
but with different DST behaviour.

NTP options (`prefer`, `iburst`, `key`, `source`) are dropped: the
canonical model stores `ntp_servers: list[str]` as bare addresses
only.  This is a known truncation; the canonical schema does not
model per-server NTP options.

Disposition for hostname / domain / dns_servers / ntp_servers /
syslog_servers: **good**.

Disposition for timezone: **lossy**.  Reason: zoneinfo (Arista)
versus offset+DST (Cisco) carry different semantics.

Disposition for NTP per-server options: **lossy** (truncated to
host-only list).

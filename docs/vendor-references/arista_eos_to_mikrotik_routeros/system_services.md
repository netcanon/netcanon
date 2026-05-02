# System services: Arista EOS versus MikroTik RouterOS

## Arista EOS

Sources:
- [Arista EOS — System Management](https://www.arista.com/en/um-eos/eos-system-management)
- [Arista EOS — Logging](https://www.arista.com/en/um-eos/eos-logging)
- [Arista EOS — DNS configuration](https://www.arista.com/en/um-eos/eos-domain-name-server)

Retrieved: 2026-05-01

```
hostname ks-leaf-01

dns domain example.net

ip name-server vrf default 10.0.0.53
ip name-server vrf default 10.0.0.54

ntp server 10.0.0.123
ntp server 10.0.0.124

clock timezone US/Pacific

logging host 10.0.0.20
```

Arista keeps the hostname as a bare unquoted token on `hostname X`.
The `dns domain` directive declares the default search domain
(separate from the hostname).  DNS resolvers attach to a
per-VRF qualifier; `vrf default` is the typical default-VRF form.

NTP uses full RFC 5905 NTPv4 (`ntp server <addr>`, one line per
server).  Per-server modifiers (`prefer`, `iburst`, `key`,
`source`) live on the same line.

Timezone uses **Olson / IANA tz database** names but Arista
historically prefers the older alias form (`US/Pacific`,
`US/Eastern`); modern aliases (`America/Los_Angeles`) are also
accepted on recent EOS releases.

Syslog uses `logging host <addr>` with optional per-host modifiers
(`vrf X`, `severity Y`, `protocol UDP`).

The `arista_eos` codec parses **hostname / DNS / NTP / dns
domain** into the canonical `hostname` / `dns_servers` /
`ntp_servers` / `domain` fields.  Timezone and syslog hosts are
not currently parsed by the codec — they would silently drop on
parse.

## MikroTik RouterOS

Sources:
- [Identity — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/40992856/Identity)
- [Clock — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/40992866/Clock)
- [DNS — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/37748767/DNS)
- [NTP — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/37748794/NTP)
- [Log — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/40992869/Log)

Retrieved: 2026-05-01

```
/system identity
set name=ks-leaf-01

/system clock
set time-zone-name=America/Los_Angeles

/ip dns
set servers=10.0.0.53,10.0.0.54

/system ntp client
set enabled=yes servers=10.0.0.123,10.0.0.124

/system logging action
add target=remote remote=10.0.0.20 name=remote-syslog
/system logging
add action=remote topics=info,error
```

RouterOS keeps the device name on `/system identity / set name=`.
DNS resolvers go on `/ip dns / set servers=<comma-list>`.  NTP
client servers go on `/system ntp client / set servers=<comma-
list>`.

Timezone uses **Olson / IANA tz database** names, preferring the
modern `Continent/City` form (`America/Los_Angeles`,
`Europe/Berlin`).  Older aliases (`US/Pacific`) may produce a
deprecation warning or fail validation on some RouterOS builds.

Syslog requires a `/system logging action` destination plus a
`/system logging` rule that binds topic / severity filters to the
destination.

There is no first-class `domain` directive on RouterOS — operators
who need a default DNS search domain set it as
`/ip dns set domain=<fqdn>`, which is a per-resolver attribute and
not an identity attribute.

## Cross-vendor mapping

The canonical surface is

```
CanonicalIntent.hostname: str
CanonicalIntent.domain: str
CanonicalIntent.dns_servers: list[str]
CanonicalIntent.ntp_servers: list[str]
CanonicalIntent.timezone: str
CanonicalIntent.syslog_servers: list[str]
```

Hostname round-trips cleanly: Arista `hostname ks-leaf-01` parses
to `hostname="ks-leaf-01"` and the RouterOS render emits `/system
identity / set name=ks-leaf-01`.  Both vendors accept hostname-
safe characters bare; RouterOS additionally accepts quoted forms
but the codec emits bare.

DNS servers round-trip well: Arista's per-line `ip name-server
vrf default <addr>` parses to a flat address list (the `vrf
default` qualifier is dropped); RouterOS render emits `/ip dns
set servers=<addr>,<addr>`.  Non-default-VRF DNS resolution on
Arista (rare) does not survive the cross-pair.

NTP servers round-trip cleanly at the address-list level.  Per-
server modifiers (Arista `prefer` / `iburst`) drop on the
canonical layer.

Timezone is **lossy**: both vendors use Olson form, but Arista's
older alias `US/Pacific` may not validate on RouterOS — operator-
curated mapping recommended.

Domain is **lossy** in this direction.  Arista source carries
`dns domain example.net` into `CanonicalIntent.domain="example.net"`,
but RouterOS has no first-class top-level FQDN directive — render
emits no direct domain line.  Operator must add `/ip dns set
domain=` manually.

Syslog hosts are **lossy**: Arista's `logging host <addr>` is not
parsed by the arista_eos codec today (no canonical population on
this side) so RouterOS render emits no syslog config in this
direction.  Even with parser wire-up, RouterOS's destination +
filter pair is richer than the canonical surface.

Disposition: **good** for hostname / dns_servers / ntp_servers;
**lossy** for domain / timezone / syslog_servers.

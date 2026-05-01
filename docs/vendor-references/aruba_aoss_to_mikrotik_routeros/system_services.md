# System services: Aruba AOS-S versus MikroTik RouterOS

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Management and Configuration Guide
for 2930F / 2930M / 3810 / 5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MCG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
hostname "ks-aoss-edge-01"

ip dns server-address priority 1 10.0.10.53
ip dns server-address priority 2 10.0.10.54

sntp server priority 1 10.0.10.123
sntp server priority 2 10.0.10.124

time timezone -480
time daylight-time-rule pacific

logging 10.0.10.20
logging facility local6
```

Aruba quotes the hostname value in `show running-config` output and on
authored config files; the codec strips the quotes on parse and re-
quotes on render.  DNS server lists carry a per-entry `priority N`
ordinal so the order is explicit on the wire.

Aruba uses **SNTP** as its time-protocol primitive (`sntp server
priority N <addr>`), not full NTP.  The protocol distinction is a
deliberate AOS-S design choice — full RFC 5905 NTPv4 is not
implemented on the platform.

Timezone is expressed as a **minute offset** (`time timezone -480` =
PST = UTC-8) plus a separate region-keyed daylight-time rule.  No
human-readable name on the wire.

Syslog destinations use a bare `logging <addr>` directive; severity
and facility tokens are configured separately and do not currently
parse into the canonical model.

The aruba_aoss codec parses **hostname / DNS / SNTP** into the
canonical `hostname` / `dns_servers` / `ntp_servers` fields.
Timezone, syslog hosts, and the domain directive are NOT parsed by
the current codec — they would silently drop on parse anyway.

## MikroTik RouterOS

Sources:
- [Identity — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/40992856/Identity)
- [Clock — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/40992866/Clock)
- [DNS — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/37748767/DNS)
- [NTP — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/37748794/NTP)
- [Log — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/40992869/Log)

Retrieved: 2026-04-30

```
/system identity
set name=ks-edge-01

/system clock
set time-zone-name=America/Los_Angeles

/ip dns
set servers=10.0.10.53,10.0.10.54

/system ntp client
set enabled=yes servers=10.0.10.123,10.0.10.124

/system logging action
add target=remote remote=10.0.10.20 name=remote-syslog
/system logging
add action=remote topics=info,error
```

RouterOS keeps the device name on `/system identity / set name=`.
DNS resolvers go on `/ip dns / set servers=<comma-list>`.  NTP
client servers go on `/system ntp client / set servers=<comma-list>`
(also a comma-separated list, single attribute).

Timezone uses **Olson / IANA tz database** names
(`America/Los_Angeles`, `Europe/Berlin`).  RouterOS does not accept
a numeric offset and does not have a separate DST-rule directive —
the tz database entry already encodes DST behaviour.

Syslog requires a `/system logging action` destination plus a
`/system logging` rule that binds topic / severity filters to the
destination.  The destination is reusable across multiple rules.

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

Hostname round-trips cleanly: Aruba `hostname "ks-aoss-edge-01"`
parses to `hostname="ks-aoss-edge-01"` (quotes stripped) and the
RouterOS render emits `/system identity / set name=ks-aoss-edge-01`.
RouterOS does not support quoted names and does not accept arbitrary
whitespace; Aruba hostnames containing spaces (rare but valid in
quotes) lose the spaces or fail to apply on RouterOS.

DNS servers round-trip well: Aruba's per-entry priority ordinal
collapses into list ordering on parse; RouterOS render emits
`/ip dns set servers=<addr>,<addr>`.

NTP servers round-trip at the address-list level — the SNTP-vs-NTP
protocol distinction is not modelled canonically.  Both sides treat
the list as bare addresses; per-server modifiers
(Aruba `priority N`, RouterOS none) drop on the canonical layer.

Timezone is **lossy** in either direction.  Aruba `time timezone
-480` (minute-offset) does not parse into the canonical timezone
field on the current aruba_aoss codec (left empty on parse), and
even if it did, mapping a numeric offset to an Olson name requires
operator intervention (`-480` could be `America/Los_Angeles`,
`America/Tijuana`, `Pacific/Pitcairn`, etc.).  RouterOS source
timezone is a tz-database name; auto-rendering as Aruba's minute-
offset form is a one-way translation that loses the region context.

Syslog hosts are **lossy**: Aruba's bare `logging <addr>` is not
parsed by the aruba_aoss codec today (no canonical population on
this side); RouterOS source carries the destination + filter pair
which the canonical model truncates to host-only.  Per-vendor
filter / severity / facility surfaces drop on round-trip.

Domain directive is **lossy on parse from Aruba**: the AOS-S codec
does not parse a domain directive (Aruba folds it into the
quoted hostname).  RouterOS render therefore emits no `/ip dns set
domain=` line on this direction.  In the inverse direction
(RouterOS source), the field is **not_applicable** because RouterOS
does not surface a top-level FQDN identity field.

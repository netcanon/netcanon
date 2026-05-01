# System services: MikroTik RouterOS versus Aruba AOS-S

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
set time-zone-name=America/New_York

/ip dns
set servers=1.1.1.1,8.8.8.8

/system ntp client
set enabled=yes servers=10.0.0.123,pool.ntp.org

/system logging action
add target=remote remote=10.0.0.20 name=remote-syslog
/system logging
add action=remote topics=info,error
```

RouterOS keeps the device name on `/system identity / set name=`.
DNS resolvers go on `/ip dns / set servers=<comma-list>`; NTP
client servers go on `/system ntp client / set servers=<comma-list>`.
Both attributes accept hostname or IP entries, comma-separated.

Timezone uses **Olson / IANA tz database** names
(`America/New_York`, `Europe/Berlin`, `UTC`).  RouterOS does not
accept a numeric offset and does not have a separate DST-rule
directive — the tz database entry already encodes DST behaviour.

Syslog requires a `/system logging action` destination plus a
`/system logging` rule binding topic / severity filters to the
destination.  The destination is reusable across multiple rules.

There is **no first-class `domain` directive** on RouterOS — the
nearest equivalent is `/ip dns / set domain=<fqdn>`, which
configures a default DNS search suffix on the resolver, not a
device-identity attribute.  The mikrotik_routeros codec does not
populate `CanonicalIntent.domain` from a RouterOS source — the
field is empty after parsing a RouterOS config.

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Management and Configuration Guide
for 2930F / 2930M / 3810 / 5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MCG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
hostname "ks-edge-01"

ip dns server-address priority 1 1.1.1.1
ip dns server-address priority 2 8.8.8.8

sntp server priority 1 10.0.0.123
sntp server priority 2 pool.ntp.org

time timezone -300
time daylight-time-rule continental-us-and-canada

logging 10.0.0.20
```

Aruba quotes the hostname value on `show running-config` output and
on authored config files; the codec strips the quotes on parse and
re-quotes on render.

Aruba uses **SNTP** as its time-protocol primitive (`sntp server
priority N <addr>`), not full NTPv4.  Per-server priority ordinal
is explicit on the wire.

Timezone is expressed as a **minute offset** plus a region-keyed
DST rule.  No human-readable IANA name on the wire.

Syslog destinations use a bare `logging <addr>` directive.
Severity / facility live on separate `logging severity` /
`logging facility` directives that the aruba_aoss codec does not
currently parse.

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

Hostname round-trips cleanly: RouterOS `/system identity / set
name=ks-edge-01` -> Aruba `hostname "ks-edge-01"`.  RouterOS
hostnames are bare; Aruba renders with quotes.

DNS servers round-trip well: RouterOS comma-separated
`servers=1.1.1.1,8.8.8.8` lifts to a list; Aruba render emits
per-entry `ip dns server-address priority N <addr>` with priority
synthesised from the canonical list order.

NTP servers round-trip at the address-list level; the SNTP-vs-NTP
protocol distinction is not modelled canonically.  RouterOS source
NTP servers (full NTPv4) emit as Aruba SNTP entries; functional
equivalence is good for typical campus deployments.

Timezone is **lossy**: RouterOS `time-zone-name=America/New_York`
auto-renders as Aruba's minute-offset form (`-300` for EST), but the
tz-database region context drops on the canonical layer (canonical
stores the operator-typed string verbatim, and the auto-render
mapping is one-way).  DST rule binding (`time daylight-time-rule
continental-us-and-canada`) requires operator selection.

Syslog hosts are **lossy** in this direction: RouterOS source
carries the destination + filter pair from `/system logging
action` + `/system logging`; the canonical model truncates to
host-only.  Aruba target renders the bare `logging <addr>` lines
without per-topic / per-severity binding.

Domain directive is **not_applicable** in this direction: RouterOS
does not surface a top-level FQDN identity field.  The canonical
`domain` is empty after RouterOS parse, so Aruba target render
emits no domain directive.

### Disposition

| Field | Disposition |
|---|---|
| `hostname` | good |
| `domain` | not_applicable (RouterOS has no field) |
| `dns_servers` | good (comma-list -> priority-ordered) |
| `ntp_servers` | lossy (NTP -> SNTP protocol distinction lost) |
| `timezone` | lossy (Olson name -> minute-offset; DST rule operator-curated) |
| `syslog_servers` | lossy (per-topic filter drops to host-only) |

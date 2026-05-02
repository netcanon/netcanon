# System services: MikroTik RouterOS versus Arista EOS

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
set name=ks-edge-01

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

RouterOS does not surface a top-level FQDN identity field — there
is no equivalent to Arista's `dns domain` directive.  The closest
analogue is `/ip dns set domain=<fqdn>` which is a per-resolver
attribute, not a device-identity attribute.  After parsing a
RouterOS source, `CanonicalIntent.domain` is empty.

DNS resolvers go on `/ip dns / set servers=<comma-list>`.  The
list shape lifts to `dns_servers: list[str]` cleanly.

NTP uses RFC 5905 NTPv4 via `/system ntp client / set
servers=<comma-list>`.  Per-server modifiers are not surfaced —
RouterOS treats the server list as bare addresses.

Timezone uses Olson / IANA tz database names in the modern
`Continent/City` form (`America/Los_Angeles`, `Europe/Berlin`).

Syslog requires a `/system logging action` destination row plus a
`/system logging` rule binding topic / severity filters to the
destination.  The destination is reusable.

The `mikrotik_routeros` codec parses **hostname / DNS / NTP**
into the canonical `hostname` / `dns_servers` / `ntp_servers`
fields.  Timezone, syslog, and (non-existent) domain are not
parsed by the current codec — the canonical fields stay empty.

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

Arista keeps the hostname as a bare unquoted token.  `dns domain`
declares the default search domain.  DNS resolvers attach with a
per-VRF qualifier (`vrf default` is the typical form for a
single-VRF device).

Timezone uses Olson form, but Arista historically prefers the
older alias form (`US/Pacific`).  Modern aliases
(`America/Los_Angeles`) are also accepted on recent EOS
releases.

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

RouterOS -> Arista round-trip:

* **Hostname** — round-trips cleanly: RouterOS `set name=
  ks-edge-01` -> Arista `hostname ks-edge-01`.  Both vendors
  accept hostname-safe characters bare; RouterOS's quoted form
  (rare) loses spaces or fails to apply on Arista.

* **Domain** — `not_applicable`: RouterOS source has no top-
  level FQDN field; canonical `domain` is empty after parse;
  Arista render emits no `dns domain` directive.  This is a
  structural absence on the source, not a translation loss.

* **DNS servers** — round-trip cleanly: RouterOS `set
  servers=10.0.0.53,10.0.0.54` parses to flat list; Arista
  render emits `ip name-server vrf default <addr>` (one line
  per address, with the `vrf default` qualifier added by the
  Arista render path to match Arista's default form).

* **NTP servers** — round-trip cleanly: RouterOS does not
  surface per-server NTP options anyway, so the canonical
  truncation is not a loss in this direction.

* **Timezone** — lossy: RouterOS modern form
  (`America/Los_Angeles`) versus Arista's older preference
  (`US/Pacific`).  Both Olson; auto-rendering RouterOS's modern
  form on Arista works on recent EOS releases but the in-band
  display may differ from operator expectation.

* **Syslog hosts** — lossy: RouterOS's destination + filter pair
  is richer than the canonical surface (host-only); per-topic /
  per-severity filters drop on the cross-vendor migration.

Disposition: **good** for hostname / dns_servers / ntp_servers;
**not_applicable** for domain (structural source absence);
**lossy** for timezone / syslog_servers.

# System services (hostname / DNS / NTP / logging / clock / domain): Cisco IOS-XE versus Aruba AOS-S

## Cisco IOS-XE

Source: [Cisco IOS XE 17.x System Management Configuration Guide](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/fundamentals/configuration/xe-17/fundamentals-xe-17-book.html)
Retrieved: 2026-04-30

Hostname / domain:

```
hostname Router
ip domain name example.com
```

DNS:

```
ip name-server 8.8.8.8
ip name-server 1.1.1.1
```

NTP:

```
ntp server 192.0.2.1 prefer
ntp server 198.51.100.1 iburst
clock timezone PST -8 0
clock summer-time PDT recurring
```

Syslog:

```
logging host 10.0.0.5
logging host 10.0.0.6 transport udp port 514
logging trap informational
logging facility local6
```

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Management and Configuration Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MCG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

Hostname:

```
hostname "sw-edge-01"
```

The hostname value is quoted on AOS-S; the codec strips the quotes
on parse.

Domain (the codec does NOT currently parse a separate domain
directive; AOS-S folds the FQDN into the hostname when set).

DNS:

```
ip dns server-address priority 1 8.8.8.8
ip dns server-address priority 2 1.1.1.1
```

The `priority N` ordinal is positional; the codec sorts by priority
on parse to preserve the operator's preference order.

NTP — AOS-S uses **SNTP** as its time-protocol primitive, NOT NTP:

```
sntp unicast
sntp server priority 1 192.0.2.1
sntp server priority 2 198.51.100.1
time daylight-time-rule continental-us-and-canada
time timezone -480
```

The `time timezone` directive takes a **minute offset** (so PST is
`-480`, not `-8`).  No DST-rule keyword form.  This is a syntactic
divergence from Cisco's `clock timezone PST -8 0` form.

Syslog:

```
logging 10.0.0.5
logging facility local6
logging severity info
```

AOS-S `logging <addr>` is the equivalent of Cisco's `logging host
<addr>`; the codec accepts both.

## Cross-vendor mapping

`CanonicalIntent.hostname` round-trips losslessly (quoted shell
versus bare token is normalised).

`CanonicalIntent.domain` round-trips Cisco -> Aruba -> Cisco only
within Cisco; AOS-S has no first-class domain directive in the
codec's parse surface, so this field is dropped Aruba <- Cisco
unless the FQDN is folded into the hostname.

`CanonicalIntent.dns_servers` round-trips cleanly — both vendors
list IP addresses; priority ordering is preserved on Aruba's side
via the explicit ordinal.

`CanonicalIntent.ntp_servers` is the cross-vendor surface for both
NTP (Cisco) and SNTP (Aruba).  The protocol distinction is lost on
canonical (the field is `list[str]` of host addresses) but typical
deployments treat NTP/SNTP interchangeably at the server-list level.
Per-server `prefer` / `iburst` (Cisco) and `priority N` (Aruba)
modifiers are not modelled.

`CanonicalIntent.timezone` is the most lossy of the system-services
fields:

* Cisco emits `clock timezone <name> <hours> <minutes-offset>` plus
  separate `clock summer-time` line.
* Aruba emits `time timezone <minute-offset>` with no name and a
  separate `time daylight-time-rule <region>`.

The canonical `timezone: str` stores the operator-typed value
verbatim.  Cross-vendor migration may produce a token the target
accepts syntactically but with different DST behaviour.

`CanonicalIntent.syslog_servers` round-trips the host list cleanly.
Severity / facility tokens (`logging trap informational`, `logging
facility local6`) are not modelled — drop on round-trip.

Disposition: **good** for hostname / dns_servers / ntp_servers
(host list).  **Lossy** for timezone (DST semantics) and
syslog_servers (severity / facility loss).

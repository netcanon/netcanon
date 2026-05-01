# System services: Aruba AOS-S versus Cisco IOS-XE

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Management and Configuration Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MCG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

Hostname (quoted on AOS-S):

```
hostname "sw-edge-01"
```

DNS:

```
ip dns server-address priority 1 8.8.8.8
ip dns server-address priority 2 1.1.1.1
```

Time — AOS-S uses **SNTP** as its time-protocol primitive:

```
sntp unicast
sntp server priority 1 192.0.2.1
time daylight-time-rule continental-us-and-canada
time timezone -480
```

`time timezone` accepts a **minute offset** (PST = `-480`).  No
DST-rule keyword form — the `daylight-time-rule` directive takes a
named region rule.

Syslog:

```
logging 10.0.0.5
logging facility local6
logging severity info
```

## Cisco IOS-XE

Source: [Cisco IOS XE 17.x System Management Configuration Guide](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/fundamentals/configuration/xe-17/fundamentals-xe-17-book.html)
Retrieved: 2026-04-30

```
hostname Router
ip domain name example.com
ip name-server 8.8.8.8
ntp server 192.0.2.1 prefer
clock timezone PST -8 0
clock summer-time PDT recurring
logging host 10.0.0.5
```

Cisco's `clock timezone` takes `<name> <hours-offset>
<minutes-offset>`; DST is a separate `clock summer-time` line.

## Cross-vendor mapping

`hostname`: round-trips losslessly (codec strips the AOS-S quotes
on parse).

`domain`: AOS-S has no first-class domain directive; on this
direction the canonical `domain` field is empty, so nothing
renders on Cisco.  This is **not_applicable** for the
Aruba -> Cisco direction (no domain to lose).

`dns_servers`: Aruba's `ip dns server-address priority N <addr>`
collapses to bare addresses on canonical, then renders as Cisco
`ip name-server <addr>` lines.  Priority ordering preserved by
the parser sort.

`ntp_servers`: Aruba's SNTP and Cisco's NTP both use UDP/123 and
the canonical model treats them as a list of addresses.  Per-
server modifiers (`prefer`, `iburst` on Cisco; `priority N` on
Aruba) drop on round-trip.  The protocol distinction (NTP vs
SNTP) is also lost — but typical deployments treat the two as
interchangeable.

`timezone`: Aruba `time timezone -480` (minute offset) versus
Cisco `clock timezone <name> -8 0`.  Canonical stores an opaque
string, so the cross-vendor render produces a token that is
syntactically valid only with manual intervention.  **Lossy**.

`syslog_servers`: Aruba's bare host list maps to Cisco's
`logging host <addr>` directive.  Severity / facility tokens
(`logging facility local6`, `logging severity info`) are not
modelled — drop on round-trip.

Disposition: **good** for hostname / dns_servers / ntp_servers
host list.  **Lossy** for timezone (offset format), syslog_servers
(severity / facility loss).  **Not applicable** for domain.

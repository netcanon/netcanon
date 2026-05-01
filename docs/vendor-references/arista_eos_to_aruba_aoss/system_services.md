# System services: Arista EOS versus Aruba AOS-S

## Arista EOS

Source: [Arista EOS — Switch Administration Commands](https://www.arista.com/en/um-eos/eos-switch-administration-commands)
Retrieved: 2026-05-01

Arista's surface (Cisco-style):

```
hostname ks-leaf-01

ip name-server vrf default 10.0.0.53
ip name-server vrf default 10.0.0.54
dns domain example.net

ntp server 10.0.0.123
ntp server 10.0.0.124

logging host 10.0.50.10
logging facility local6

clock timezone US/Pacific                  ; zoneinfo name
```

Key shape notes:

- `hostname` value is **bare** (no quotes).
- DNS uses `ip name-server` directly; carries an optional
  `vrf default` qualifier the codec strips on parse.
- Time protocol is **NTP**.
- Timezone uses **zoneinfo names** (`US/Pacific`,
  `Europe/London`) and DST is implicit in the zoneinfo data.

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Management and Configuration Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MCG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

Aruba's small system-services surface:

```
hostname "ks-aoss-edge-01"

ip dns server-address priority 1 10.0.10.53
ip dns server-address priority 2 10.0.10.54

sntp server priority 1 10.0.10.123
sntp server priority 2 10.0.10.124

logging 10.0.50.10                         ; syslog
logging facility local6

time timezone -480                         ; minute-offset (PST)
time daylight-time-rule continental-us-and-canada
```

Key shape notes:

- `hostname` value is **quoted**.
- DNS uses `ip dns server-address priority N <addr>` with explicit
  priority; codec sorts and collapses to a flat list.
- Time protocol is **SNTP** (subset of NTP wire-format but
  different keyword).
- Timezone is a **minute offset** (`-480` = PST = UTC-8h00m), and
  DST is a separate named-region rule.

## Cross-vendor mapping

Canonical fields involved:

- `hostname` (str)
- `domain` (str)
- `dns_servers` (list[str])
- `ntp_servers` (list[str])
- `timezone` (str)
- `syslog_servers` (list[str])

Arista -> Aruba round-trip:

* `hostname`: bare string on Arista normalises to canonical;
  Aruba renderer wraps in quotes.  Round-trip lossless on the
  string content.  **good**.
* `domain`: Arista's `dns domain <fqdn>` -> Aruba does not
  parse-or-render a separate domain directive (AOS-S folds the
  FQDN into the hostname when set).  Drops on this direction.
  **lossy**.
* `dns_servers`: Arista's flat list -> Aruba's
  `ip dns server-address priority N <addr>` with synthesised
  priorities (1, 2, ... in source order).  **good**.
* `ntp_servers`: protocol-keyword distinction (NTP vs SNTP) is
  lost on the canonical layer.  Functional equivalence at the
  server-list level since AOS-S's SNTP client successfully
  queries NTP servers.  Per-server modifiers (Arista `prefer` /
  `iburst`) drop.  **lossy**.
* `timezone`: Arista `US/Pacific` (zoneinfo) -> Aruba
  `time timezone <minute-offset>` requires a curated lookup table
  to convert.  Cross-vendor migration produces a token Aruba's
  parser will reject (`US/Pacific` is not a valid Aruba time-
  timezone value).  Operator override needed.  **lossy**.
* `syslog_servers`: Arista `logging host <addr>` -> Aruba
  `logging <addr>`.  Both vendors round-trip the host list
  cleanly.  Severity / facility tokens drop (canonical surface
  is host-list-only).  **good**.

The Arista kitchen-sink (`ks-leaf-01`) exercises hostname / DNS /
NTP cleanly; timezone / syslog are not in the kitchen-sink
because the codec's parse surface focuses on the supported
list.  Real captures with `clock timezone US/Pacific` will hit
the lossy timezone path.

Disposition: mostly **good**; **lossy** for `domain` /
`ntp_servers` / `timezone`.

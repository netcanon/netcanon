# System services: Aruba AOS-S versus Arista EOS

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

domain-suffix "example.com"                ; rarely seen
```

Key shape notes:

- `hostname` value is **quoted** in the running-config; the codec
  strips quotes on parse.
- DNS uses `ip dns server-address priority N <addr>` with an
  explicit priority integer; the codec sorts by priority and
  collapses to a flat address list.
- Time protocol is **SNTP** (not NTP) and uses a priority-tagged
  list.
- Timezone is a **minute offset** (`-480` = PST = UTC-8h00m), and
  DST is a separate named-region rule.

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
- DNS uses `ip name-server` directly, no priority concept; carries
  an optional `vrf default` qualifier the EOS codec strips on
  parse.
- Time protocol is **NTP** (Aruba's SNTP is a subset of NTP wire
  format but uses a different keyword).
- Timezone uses **zoneinfo names** (`US/Pacific`, `Europe/London`)
  and DST is implicit in the zoneinfo data.

## Cross-vendor mapping

Canonical fields involved:

- `hostname` (str)
- `domain` (str)
- `dns_servers` (list[str])
- `ntp_servers` (list[str])
- `timezone` (str)
- `syslog_servers` (list[str])

Aruba -> Arista round-trip:

* `hostname`: quoted-form on Aruba normalises to bare-string
  canonical; Arista renders bare.  Round-trip lossless on the
  string content.  **good**.
* `domain`: Aruba parser does not extract `domain-suffix`
  reliably (not in the codec's supported set); the field is
  empty on this direction.  **not_applicable**.
* `dns_servers`: Aruba's priority-ordered list collapses to a
  flat list (sorted by priority); Arista emits one
  `ip name-server <addr>` per entry.  **good**.
* `ntp_servers`: protocol-keyword distinction (SNTP vs NTP) is
  lost on the canonical layer (host-list-only).  Functional
  equivalence at the server-list level since SNTP clients
  successfully query NTP servers.  Per-server modifiers (Aruba
  priority overrides; Arista `prefer` / `iburst`) drop on round-
  trip.  **lossy** (protocol keyword + per-server modifiers).
* `timezone`: Aruba `-480` (minute-offset) -> Arista `US/Pacific`
  (zoneinfo name) cannot be auto-mapped without a curated table.
  Canonical stores the operator-typed string verbatim; cross-
  vendor migration produces a token Arista's parser will reject
  (`-480` is not a valid zoneinfo name).  **lossy** with operator
  override needed.
* `syslog_servers`: Aruba `logging <addr>` -> Arista `logging
  host <addr>`.  Both vendors round-trip the host list cleanly.
  Severity / facility tokens drop (canonical surface is host-
  list-only).  **good**.

The Aruba kitchen-sink omits timezone / syslog / domain
deliberately (those fields are not in the codec's supported
parse set), so the round-trip-stable test only exercises
`hostname` / `dns_servers` / `ntp_servers` (via SNTP) on this
direction.

Disposition: mostly **good**; **lossy** for `ntp_servers` and
`timezone`; **not_applicable** for `domain`.

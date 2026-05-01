# System services — AOS-S source to OpenConfig NETCONF target

Source: [openconfig-system YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-system.html)
Retrieved: 2026-05-01

Source: [Aruba ArubaOS-Switch 16.11 Management and Configuration Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MCG/2930F-3810-5400/index.htm)
Retrieved: 2026-05-01

## OpenConfig system model — what would survive if wired

The `openconfig-system` YANG model defines a `<system>` top-level
container with these subtrees:

* `<system><config><hostname>` — single string
* `<system><dns><servers>` — list of DNS server addresses
* `<system><ntp><servers>` — list of NTP server addresses + auth
* `<system><clock><config><timezone-name>` — IANA tz database ident
* `<system><logging><remote-servers>` — list of syslog destinations

The aruba_aoss parser populates the corresponding canonical fields:

* `intent.hostname` from `hostname "<name>"` (quoted)
* `intent.dns_servers` from `ip dns server-address priority N <addr>`
* `intent.ntp_servers` from `sntp server priority N <addr>` (note:
  AOS-S uses SNTP; canonical normalises both)
* `intent.timezone` not parsed today (codec gap)
* `intent.syslog_servers` from `logging <addr>`

## What the cisco_iosxe target render actually emits

Nothing.  The render path walks `intent.interfaces` only.  No
`<system>` element appears in the output.

The CapabilityMatrix declares `/system/hostname`, `/system/dns-server`,
and `/system/ntp-server` under `supported` to keep cross-codec mesh
translations from classifying these paths as `unsupported` on the
target side, but the render is aspirational.

## Direction-specific detail

AOS-S source carries SNTP not NTP — even if the cisco_iosxe render
were wired, the protocol distinction would already be erased on the
canonical layer (both vendors collapse to a `list[str]` of server
addresses).  This loss happens at parse time, upstream of the
render-side wire-up gap.

For timezone, the codec gap is on the AOS-S parse side: the codec
does not extract `time timezone <minute-offset>` today, so even a
hypothetical fully-wired cisco_iosxe render would have no source
data to emit.  Disposition: lossy with reason "deferred" on the
parse side.

## Disposition

| Field | Disposition | Reason |
|---|---|---|
| `hostname` | unsupported | target render gap |
| `domain` | not_applicable | AOS-S parser doesn't populate |
| `dns_servers` | unsupported | target render gap |
| `ntp_servers` | unsupported | target render gap (also SNTP/NTP collapse upstream) |
| `timezone` | lossy | deferred — AOS-S parse-side gap |
| `syslog_servers` | unsupported | target render gap |

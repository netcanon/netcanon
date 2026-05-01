# System services — Cisco NETCONF source to AOS-S CLI target

Source: [openconfig-system YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-system.html)
Retrieved: 2026-05-01

Source: [Aruba ArubaOS-Switch 16.11 Management and Configuration Guide](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MCG/2930F-3810-5400/index.htm)
Retrieved: 2026-05-01

## What OpenConfig models

The `openconfig-system` model has subtrees for hostname, DNS, NTP,
clock/timezone, syslog/logging.  A real Cisco device's
`<get-config>` response will populate all of these where the
operator has configured them.

## What the cisco_iosxe parser actually reads

None of `<system>`.  The parser walks `<interfaces>` and ignores
everything else.  `intent.hostname`, `intent.domain`, `intent.dns_servers`,
`intent.ntp_servers`, `intent.timezone`, `intent.syslog_servers`
all stay empty after parse.

## What the AOS-S target render does with empty input

Nothing.  Render emits no `hostname` line, no `ip dns server-address`,
no `sntp server`, no `time timezone`, no `logging` lines.  The
resulting AOS-S CLI is missing all system-services declarations.

## What WOULD survive a hypothetical wire-up

If the cisco_iosxe parser were extended to walk `<system>`, the
AOS-S target accepts the corresponding canonical fields
(`/system/hostname`, `/system/dns-server`, `/system/ntp-server`
all declared `supported` in the AOS-S matrix).  The dispositions
would flip:

* `hostname` -> `good` (string round-trip; AOS-S quotes the value)
* `domain` -> `lossy` (AOS-S has no first-class `ip domain-name`
  directive surfaced by the codec; would round-trip via raw_sections)
* `dns_servers` -> `good` (host-list)
* `ntp_servers` -> `lossy` (Cisco emits NTP, AOS-S emits SNTP — same
  protocol-distinction loss already present in the canonical model)
* `timezone` -> `lossy` (Cisco's `clock timezone NAME OFFSET` vs
  AOS-S's `time timezone <minute-offset>` — format mismatch)
* `syslog_servers` -> `good` (host-list)

But none of this happens today.

## Disposition

| Field | Today | After hypothetical wire-up |
|---|---|---|
| `hostname` | not_applicable | good |
| `domain` | not_applicable | lossy |
| `dns_servers` | not_applicable | good |
| `ntp_servers` | not_applicable | lossy |
| `timezone` | not_applicable | lossy |
| `syslog_servers` | not_applicable | good |

The current YAML reflects the today column.  The "after wire-up"
column is documentation that motivates the parser-extension work
(not part of the YAML disposition).

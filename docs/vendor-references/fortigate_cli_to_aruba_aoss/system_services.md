# System services: FortiGate FortiOS versus Aruba AOS-S

This is the reverse-direction sibling of
[`../aruba_aoss_to_fortigate_cli/system_services.md`](../aruba_aoss_to_fortigate_cli/system_services.md).
The vendor surfaces and source URLs are unchanged; this file flips
the cross-vendor mapping perspective so a FortiGate-source
migration to Aruba AOS-S is the worked direction.

## FortiGate FortiOS CLI

Source: [Fortinet Document Library — FortiGate CLI Reference](https://docs.fortinet.com/document/fortigate/7.4.0/cli-reference/) (FortiOS 7.4 CLI Reference).
Source: [Fortinet Document Library — FortiOS Cookbook](https://docs.fortinet.com/document/fortigate/7.4.0/cookbook/) (timezone numeric-index table).
Retrieved: 2026-04-30

```
config system global
    set hostname "fgt-edge"
    set timezone 04
end
config system dns
    set primary 10.0.0.53
    set secondary 10.0.0.54
    set domain "example.com"
end
config system ntp
    set ntpsync enable
    set type custom
    config ntpserver
        edit 1
            set server "10.0.0.130"
        next
    end
end
config log syslogd setting
    set status enable
    set server "10.0.0.200"
    set facility local6
end
```

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Management and Configuration Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MCG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
hostname "fgt-edge"

ip dns server-address priority 1 10.0.0.53
ip dns server-address priority 2 10.0.0.54

sntp unicast
sntp server priority 1 10.0.0.130
time daylight-time-rule continental-us-and-canada
time timezone -480

logging 10.0.0.200
logging facility local6
```

## Cross-vendor mapping (FortiGate -> Aruba)

Canonical surface (same as the forward direction):

```
hostname: str = ""
domain: str = ""
dns_servers: list[str]
ntp_servers: list[str]
timezone: str = ""
syslog_servers: list[str]
```

- **hostname** — `good`.  FortiOS `set hostname` -> Aruba
  `hostname "X"` (re-quoted on render).  FortiOS caps at 35
  characters; AOS-S typically caps at 32 — a 35-char FortiGate
  hostname truncates on Aruba render.
- **domain** — `lossy`.  FortiOS `set domain "example.com"` lands
  in canonical, but the aruba_aoss codec does not currently
  render a separate domain directive.  The value drops on Aruba
  render unless the operator pre-folds it into the hostname
  (`hostname "fgt-edge.example.com"`).
- **dns_servers** — `good`.  FortiOS exposes only primary /
  secondary / hidden tertiary; these all land in the canonical
  list and Aruba renders `ip dns server-address priority N <addr>`
  in canonical-list order.  No truncation in this direction.
- **ntp_servers** — `lossy`.  Address list is preserved.  FortiOS
  uses NTP, Aruba uses SNTP — protocol distinction lost.
  Per-server modifiers drop on round-trip.
- **timezone** — `lossy`.  FortiOS `set timezone 04` (numeric
  index) cannot be algorithmically converted to Aruba's
  `time timezone -480` (minute offset) without an operator-curated
  lookup; DST behaviour also differs.
- **syslog_servers** — `good`.  FortiOS's three syslog backends
  (`syslogd` / `syslogd2` / `syslogd3`) collapse to the canonical
  list which Aruba's `logging <addr>` directive can emit unbounded.
  No truncation in this direction.  Severity / facility tokens not
  modelled.

Reverse-direction observation: most of the lossy-ness on the
forward (Aruba -> FortiGate) direction came from FortiOS's tighter
schemas (3-DNS, 3-syslog, 3-NTP); on FortiGate -> Aruba the bottle-
neck flips to the canonical schema's domain-not-rendered gap and
timezone-format mismatch.

Disposition summary: **good** for hostname / dns_servers / syslog_servers.
**Lossy** for domain (Aruba codec render gap) / ntp_servers (protocol
distinction) / timezone (format mismatch).

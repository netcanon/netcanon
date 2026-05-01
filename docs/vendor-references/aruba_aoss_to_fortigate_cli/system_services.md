# System services (hostname / DNS / SNTP-NTP / syslog / clock): Aruba AOS-S versus FortiGate FortiOS

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Management and Configuration Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MCG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
hostname "ks-aoss-edge-01"

ip dns server-address priority 1 10.0.10.53
ip dns server-address priority 2 10.0.10.54

sntp unicast
sntp server priority 1 10.0.10.123
sntp server priority 2 10.0.10.124
time daylight-time-rule continental-us-and-canada
time timezone -480

logging 10.0.0.5
logging facility local6
logging severity info
```

Notable AOS-S specifics:

- **Hostname is quoted** in `show running-config`; the codec strips
  the quotes on parse.
- **AOS-S uses SNTP** as its time-protocol primitive (`sntp server
  priority N <addr>`); there is no full-NTP daemon on the platform.
- **`time timezone` accepts a minute offset** (PST = `-480`).  No
  named-zone form — operators must compute the offset.  DST is
  controlled by a separate `daylight-time-rule <region>` directive.
- **No first-class domain directive** in the codec's parse surface.
  The AOS-S CLI folds the FQDN into the hostname via
  `hostname "<host>.<domain>"` when both are configured.

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

Notable FortiOS specifics:

- **Hostname caps at 35 characters** under `config system global`.
- **DNS schema is fixed**: `set primary` / `set secondary` plus a
  hidden `set tertiary`.  Lists longer than three drop the tail.
- **NTP daemon** with explicit `set ntpsync enable` and `set type
  custom` outside the per-server table.  Per-server entries live in
  `config ntpserver` with sequential numeric edit IDs.
- **Timezone is a numeric index** (`set timezone <NN>`) per the
  FortiOS Cookbook timezone table (e.g. `04` = US Pacific).  No
  offset form.
- **Three syslog backends** (`syslogd` / `syslogd2` / `syslogd3`)
  with separate `config log syslogd setting` / `config log syslogd2
  setting` blocks.  Lists longer than three drop the tail.

## Cross-vendor mapping (Aruba -> FortiGate)

Canonical surface:

```
hostname: str = ""
domain: str = ""
dns_servers: list[str]
ntp_servers: list[str]
timezone: str = ""
syslog_servers: list[str]
```

- **hostname** — `good`.  Aruba `hostname "X"` -> FortiOS `set
  hostname "X"`.  Codec strips/re-quotes; FortiOS 35-char cap is
  not a practical bottleneck (AOS-S typically caps at 32).
- **domain** — `not_applicable`.  Aruba codec has no first-class
  domain directive in its parse surface, so the canonical field is
  always empty on this direction.  Nothing renders on the FortiGate
  target.
- **dns_servers** — `good`.  Aruba `ip dns server-address priority
  N <addr>` collapses to bare addresses on canonical (sorted by
  priority).  FortiOS render emits `set primary` / `set secondary`
  in canonical-list order.  Real-capture fixtures rarely exceed
  two DNS servers, so the FortiOS three-server cap is not a
  bottleneck.
- **ntp_servers** — `lossy`.  Aruba's SNTP and FortiOS's NTP both
  use UDP/123 and the canonical model treats them as a list of
  addresses.  Per-server modifiers (Aruba `priority N` overrides;
  FortiOS authentication) drop on round-trip.  Protocol distinction
  also lost.
- **timezone** — `lossy`.  Aruba `time timezone -480` (minute
  offset) cannot be algorithmically converted to FortiOS `set
  timezone 04` (numeric index) without an operator-curated lookup
  table.  Canonical preserves the source string verbatim; cross-
  vendor render produces a token only with manual intervention.
- **syslog_servers** — `lossy`.  Aruba's bare host list maps to
  FortiOS's three syslog backends; lists longer than three drop
  the tail.  Severity / facility tokens not modelled.

Disposition summary: **good** for hostname / dns_servers.
**Lossy** for ntp_servers (protocol distinction) / timezone (format
mismatch) / syslog_servers (FortiOS three-backend cap).
**Not applicable** for domain (Aruba source carries no value).

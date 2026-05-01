# System services (hostname / NTP / DNS / logging / clock): FortiGate FortiOS versus Cisco IOS-XE

This is the reverse-direction sibling of
[`../cisco_iosxe_cli_to_fortigate_cli/system_services.md`](../cisco_iosxe_cli_to_fortigate_cli/system_services.md).
The vendor surfaces and source URLs are unchanged; this file flips
the cross-vendor mapping perspective so a FortiGate-source migration
to Cisco IOS-XE is the worked direction.

## FortiGate FortiOS CLI

Source: [Fortinet Document Library — FortiGate CLI Reference](https://docs.fortinet.com/document/fortigate/7.4.0/cli-reference/) (FortiOS 7.4 CLI Reference).
Source: [Fortinet Document Library — FortiOS Cookbook](https://docs.fortinet.com/document/fortigate/7.4.0/cookbook/).
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

## Cisco IOS-XE

Source: Cisco IOS XE Network Management Configuration Guide.

```
hostname switch1
ip domain name example.com
ip name-server 10.0.0.53
ip name-server 10.0.0.54

ntp server 10.0.0.130

clock timezone PST -8 0
clock summer-time PDT recurring

logging host 10.0.0.200
logging trap informational
logging facility local6
```

## Cross-vendor mapping (FortiGate -> Cisco)

Canonical surface (same as the forward direction):

```
hostname: str = ""
domain: str = ""
dns_servers: list[str] = Field(default_factory=list)
ntp_servers: list[str] = Field(default_factory=list)
timezone: str = ""
syslog_servers: list[str] = Field(default_factory=list)
```

- **hostname** — `good`.  FortiOS `set hostname` -> Cisco `hostname`.
  FortiOS caps at 35 characters; Cisco accepts up to 63 — no
  truncation in this direction.
- **domain** — `good`.  FortiOS `set domain` (under `config system
  dns`) -> Cisco `ip domain name`.  Same FQDN preserved.
- **dns_servers** — `good`.  FortiOS exposes only `primary` /
  `secondary` (and an internal `tertiary`); these all land in the
  canonical list and Cisco accepts arbitrarily many `ip name-server`
  directives — so FortiGate -> Cisco is **lossless** in this
  direction (the truncation happened on the FortiGate-side parse
  if the source had more than three).
- **ntp_servers** — `lossy`.  Address list itself is preserved, but
  Cisco's per-server `prefer` / `iburst` / `key` / `source` options
  are not modelled in canonical (so FortiGate-source configs that
  could express none of these don't lose anything; the lossy bit is
  the canonical schema gap, not the cross-vendor migration).
- **timezone** — `lossy`.  FortiOS `set timezone <NN>` (numeric
  index, e.g. `04` = US Pacific per FortiOS Cookbook) cannot be
  algorithmically converted to Cisco's `clock timezone PST -8 0`
  (offset+DST tokens) without an operator-curated lookup table.
  The canonical model preserves the source string verbatim; the
  Cisco render path may emit a token Cisco accepts but with
  different DST behaviour.
- **syslog_servers** — `good`.  FortiOS's three syslog backends
  (`syslogd`, `syslogd2`, `syslogd3`) collapse to the canonical
  list which Cisco's `logging host` directive can emit unbounded.
  Severity / facility tokens are not canonically modelled.

The reverse-direction observation: most of the lossy-ness on the
forward (Cisco -> FortiGate) direction came from FortiOS's tighter
schema (only-2-DNS, only-3-syslog, fixed-3-NTP); on FortiGate ->
Cisco the bottleneck flips to the canonical schema's per-server-
options gap and timezone-format mismatch.

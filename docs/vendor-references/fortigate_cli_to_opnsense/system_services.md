# System services: FortiGate FortiOS versus OPNsense

Hostname / domain / DNS / NTP / syslog / timezone — the small foundation
surface that transcribes between any two vendors.

## FortiGate FortiOS

Source: [FortiGate / FortiOS 7.4 CLI Reference — `config system global` /
`config system dns` /
`config system ntp`](https://docs.fortinet.com/document/fortigate/7.4.0/cli-reference/)
Retrieved: 2026-05-01

```
config system global
    set hostname "fgt-edge-01"
    set timezone 04
end
config system dns
    set primary 192.0.2.53
    set secondary 198.51.100.53
    set domain "example.com"
end
config system ntp
    set ntpsync enable
    set type custom
    config ntpserver
        edit 1
            set server "time1.example.invalid"
        next
        edit 2
            set server "time2.example.invalid"
        next
    end
end
config log syslogd setting
    set status enable
    set server "10.0.10.200"
end
```

FortiOS notes:

- `set hostname` caps at 35 characters on FortiOS 7.x.
- `set domain` (under `config system dns`) carries a single DNS suffix.
  FortiOS does not surface a domain-list separate from the DNS resolver
  table.
- DNS resolvers schema as `set primary` / `set secondary` (and a hidden
  `set tertiary`).  No more than three DNS resolvers are exposed.
- NTP servers live under a numbered edit-table.  FortiOS additionally
  requires `set ntpsync enable` plus `set type custom` outside the
  per-server edit-table; canonical does not model these as scalars.
- Timezone is a numeric index per the FortiOS Cookbook timezone table
  (`04` = US Pacific).
- Syslog servers split across `config log syslogd setting` (primary)
  plus `syslogd2` / `syslogd3` siblings — at most three remote backends.

## OPNsense

Source: [OPNsense General Settings
manual](https://docs.opnsense.org/manual/settingsmenu.html)
Retrieved: 2026-05-01

```xml
<opnsense>
  <system>
    <hostname>fgt-edge-01</hostname>
    <domain>example.com</domain>
    <dnsserver>192.0.2.53</dnsserver>
    <dnsserver>198.51.100.53</dnsserver>
    <timeservers>time1.example.invalid time2.example.invalid</timeservers>
    <timezone>America/Los_Angeles</timezone>
    <syslog>
      <remoteserver>10.0.10.200</remoteserver>
    </syslog>
  </system>
</opnsense>
```

OPNsense notes:

- `<hostname>` carries a bare short name; `<domain>` carries the DNS
  suffix as a separate element (so the FQDN is reconstructed as
  `<hostname>.<domain>`).
- `<dnsserver>` is a repeated element — there is no fixed cap (the GUI
  shows a four-row form but config.xml accepts more).
- `<timeservers>` is a SINGLE element with space-separated host names.
  This is unlike the per-host array shape FortiOS uses.
- `<timezone>` is an Olson zoneinfo string (e.g. `America/Los_Angeles`),
  not a numeric index.
- Syslog config lives under `<system>/<syslog>/<remoteserver>` — one or
  more elements.

## Cross-vendor mapping

Canonical fields covered:

```
hostname, domain, dns_servers, ntp_servers, timezone, syslog_servers
```

FortiGate -> OPNsense:

- `hostname`: **good** — FortiOS `set hostname "X"` strips quotes on
  parse; OPNsense renders bare `<hostname>X</hostname>`.  No length
  conflict (35 char FortiOS cap fits OPNsense's unlimited).
- `domain`: **good** — FortiOS `set domain "example.com"` ↔
  OPNsense `<domain>example.com</domain>`.  Both vendors carry a
  single suffix string.
- `dns_servers`: **good** — FortiOS three-server cap (primary /
  secondary / tertiary) collapses cleanly to OPNsense's repeated
  `<dnsserver>` elements.
- `ntp_servers`: **lossy** — FortiOS protocol distinction (full NTP
  with `ntpsync enable` / `set type custom` versus OPNsense's basic
  ntpd) is not modelled in canonical.  Per-server modifiers (FortiOS
  `set authentication` / `set ntp-auth-key`) drop on canonical.  The
  OPNsense codec does not currently wire `<timeservers>` into
  `CanonicalIntent.ntp_servers` on parse, so the inverse direction
  drops too.  On render the OPNsense codec emits a space-separated
  `<timeservers>` element from the canonical list.
- `timezone`: **lossy** — FortiOS numeric index (`set timezone 04`)
  versus OPNsense Olson zoneinfo (`America/Los_Angeles`) requires an
  operator-curated lookup.  Codec wire-up gap on both ends.
- `syslog_servers`: **lossy** — FortiOS three-backend cap
  (syslogd / syslogd2 / syslogd3) maps to OPNsense's repeated
  `<remoteserver>` elements; no truncation in this direction.
  Severity / facility tokens not modelled.  OPNsense codec's
  syslog parse/render branch is not currently wired to canonical.

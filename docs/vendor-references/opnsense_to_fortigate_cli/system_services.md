# System services: OPNsense versus FortiGate FortiOS

Hostname / domain / DNS / NTP / syslog / timezone — reverse direction
of the FortiGate-to-OPNsense pair.

## OPNsense

Source: [OPNsense General Settings
manual](https://docs.opnsense.org/manual/settingsmenu.html)
Retrieved: 2026-05-01

```xml
<opnsense>
  <system>
    <hostname>opnsense-edge-01</hostname>
    <domain>example.com</domain>
    <dnsserver>192.0.2.53</dnsserver>
    <dnsserver>198.51.100.53</dnsserver>
    <dnsserver>203.0.113.53</dnsserver>
    <dnsserver>203.0.113.54</dnsserver>
    <timeservers>0.opnsense.pool.ntp.org 1.opnsense.pool.ntp.org</timeservers>
    <timezone>America/Los_Angeles</timezone>
    <syslog>
      <remoteserver>10.0.10.200</remoteserver>
    </syslog>
  </system>
</opnsense>
```

OPNsense notes:

- `<hostname>` is bare short name; `<domain>` carries the suffix.
- `<dnsserver>` is repeated — no fixed cap.  Operators may have
  more than three DNS resolvers configured.
- `<timeservers>` is a SINGLE element with space-separated host names.
  This is unlike FortiOS's per-host edit-table.
- `<timezone>` is an Olson zoneinfo string.
- Syslog config under `<system>/<syslog>/<remoteserver>` — one or more.

## FortiGate FortiOS

Source: [FortiGate / FortiOS 7.4 CLI
Reference](https://docs.fortinet.com/document/fortigate/7.4.0/cli-reference/)
Retrieved: 2026-05-01

```
config system global
    set hostname "opnsense-edge-01"
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
            set server "0.opnsense.pool.ntp.org"
        next
        edit 2
            set server "1.opnsense.pool.ntp.org"
        next
    end
end
config log syslogd setting
    set status enable
    set server "10.0.10.200"
end
```

FortiGate notes:

- `set hostname` caps at 35 characters.
- `set domain` (under `config system dns`) — single suffix string.
- DNS resolvers schema as primary / secondary / hidden tertiary —
  three-cap.
- NTP servers under numbered edit-table.  Per-server `set authentication`
  / `set ntp-auth-key` not modelled in canonical.
- Timezone is a numeric index per the FortiOS Cookbook table
  (`04` = US Pacific).
- Syslog: primary `config log syslogd setting` plus syslogd2 / syslogd3 —
  three-cap.

## Cross-vendor mapping

OPNsense -> FortiGate:

- `hostname`: **good** — OPNsense bare short name fits in FortiOS's
  35-char cap (operators rarely use longer hostnames).  Long
  OPNsense hostnames truncate.
- `domain`: **good** — OPNsense `<domain>example.com</domain>` ↔
  FortiOS `set domain "example.com"`.  Same FQDN preserved.
- `dns_servers`: **lossy** — OPNsense allows unbounded `<dnsserver>`
  elements; FortiOS three-cap (primary/secondary/tertiary) drops
  the tail when an OPNsense source has 4+ resolvers.  In typical
  deployments OPNsense has 2-3 DNS servers so the cap rarely bites,
  but it's a structural truncation worth flagging.  Marked lossy
  for the cap.  Additionally the OPNsense codec does not currently
  wire `<dnsserver>` into canonical on parse (capability matrix
  declares the path supported but parser branch is incomplete) —
  cross-pair drops the resolver list pending wire-up.
- `ntp_servers`: **lossy** — OPNsense's space-separated
  `<timeservers>` element splits on whitespace into the canonical
  list; FortiGate emits via numbered edit-table.  Pool-server
  rotation semantics (`pool.ntp.org`) preserve only as the original
  hostname; the OPNsense codec does not currently wire `<timeservers>`
  into canonical on parse — cross-pair drops pending wire-up.
- `timezone`: **lossy** — OPNsense Olson zoneinfo
  (`America/Los_Angeles`) versus FortiOS numeric index requires an
  operator-curated lookup table.  Codec wire-up gap on both ends.
- `syslog_servers`: **lossy** — OPNsense's repeated
  `<remoteserver>` elements collapse into the FortiOS three-cap
  (syslogd / syslogd2 / syslogd3).  No truncation in typical
  deployments (1-2 syslog servers).  OPNsense codec does not
  currently wire `<syslog>` into canonical.

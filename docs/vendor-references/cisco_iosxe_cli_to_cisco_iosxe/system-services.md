# System services — IOS-XE CLI versus OpenConfig NETCONF

## CLI form

Source: [System Management Configuration Guide, Cisco IOS XE 17.x](https://www.cisco.com/c/en/us/td/docs/routers/ios/config/17-x/syst-mgmt/b-system-management.html)
(retrieved 2026-04-30).

```
hostname leaf-01
ip domain name example.com
ip name-server 10.0.0.10
ip name-server 10.0.0.11
ntp server 10.0.0.20
ntp server 10.0.0.21 prefer
clock timezone PST -8 0
clock summer-time PDT recurring
logging host 10.0.0.30
logging host 10.0.0.31 transport tcp port 1514
```

## OpenConfig NETCONF form

Source: [openconfig-system YANG model](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-system.html)
(retrieved 2026-04-30).

OpenConfig models system services under a single tree:

```xml
<system xmlns="http://openconfig.net/yang/system">
  <config>
    <hostname>leaf-01</hostname>
    <domain-name>example.com</domain-name>
  </config>
  <dns>
    <servers>
      <server>
        <address>10.0.0.10</address>
        <config>
          <address>10.0.0.10</address>
          <port>53</port>
        </config>
      </server>
    </servers>
  </dns>
  <ntp>
    <servers>
      <server>
        <address>10.0.0.20</address>
        <config>
          <address>10.0.0.20</address>
        </config>
      </server>
    </servers>
  </ntp>
  <clock>
    <config>
      <timezone-name>PST8PDT</timezone-name>
    </config>
  </clock>
  <logging>
    <remote-servers>
      <remote-server>
        <host>10.0.0.30</host>
        <config>
          <host>10.0.0.30</host>
        </config>
      </remote-server>
    </remote-servers>
  </logging>
</system>
```

## Cross-format mapping in this repository

The OpenConfig NETCONF codec declares `/system/hostname`,
`/system/dns-server`, `/system/ntp-server` as `supported` but does
not actually emit `<system>` XML on render today (Phase-0.5 stub
limitation).  The CLI codec parses all of these from
`running-config` text.

| Canonical field | CLI -> NETCONF | NETCONF -> CLI |
|---|---|---|
| `hostname` | unsupported (NETCONF render emits no `<system>` element today) | not_applicable |
| `domain` | unsupported | not_applicable |
| `dns_servers` | unsupported | not_applicable |
| `ntp_servers` | unsupported | not_applicable |
| `timezone` | unsupported | not_applicable |
| `syslog_servers` | unsupported | not_applicable |

Once `<system>` rendering is wired:

* `hostname`, `domain`, `dns_servers`, `ntp_servers`, `syslog_servers`
  -> `good` for the host-list surface (same engine, same database).
* `timezone` -> `lossy`.  CLI uses Cisco's named-zone-with-offset
  form (`clock timezone PST -8 0`); OpenConfig models a single
  `timezone-name` leaf that prefers IANA tz database identifiers
  (`America/Los_Angeles`).  Mapping requires an operator-curated
  table, and DST transitions (`clock summer-time`) are a separate
  CLI concept that doesn't survive the round-trip.

Per-server NTP options (`prefer`, `iburst`, `key`, `source`) are
not modelled in the canonical tree — `ntp_servers: list[str]` is
host-only.  Same shape as the canonical NTP surface used everywhere
else in this repository (matches the
`cisco_iosxe_cli__arista_eos.yaml` `ntp_servers` `lossy` rationale).

Per-host syslog severity / facility tokens are not modelled either;
`syslog_servers: list[str]` is host-only.

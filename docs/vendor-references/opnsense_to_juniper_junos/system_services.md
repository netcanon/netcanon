# System services (hostname / domain / DNS / NTP / syslog / timezone): OPNsense versus Junos

## OPNsense

Source: [OPNsense General Settings — System: Settings: General](https://docs.opnsense.org/manual/settingsmenu.html)
Retrieved: 2026-04-30

```xml
<opnsense>
  <system>
    <hostname>fw01</hostname>
    <domain>example.com</domain>
    <dnsserver>10.0.10.53</dnsserver>
    <dnsserver>10.0.10.54</dnsserver>
    <timezone>America/Los_Angeles</timezone>
    <timeservers>0.opnsense.pool.ntp.org 1.opnsense.pool.ntp.org</timeservers>
    <syslog>
      <reverse>0</reverse>
      <nentries>50</nentries>
      <remoteserver>10.0.10.200</remoteserver>
    </syslog>
  </system>
</opnsense>
```

OPNsense system-services notes:

- `<hostname>` is the bare short name; `<domain>` is a sibling DNS
  suffix.
- DNS resolvers stack as repeated `<dnsserver>` elements.
- NTP servers SPACE-SEPARATED inside a SINGLE `<timeservers>` element
  (a flat string, not repeated elements).
- Timezone uses Olson zoneinfo (`America/Los_Angeles`,
  `Etc/UTC`).
- Syslog remote receivers under `<system>/<syslog>/<remoteserver>`.
- The opnsense codec parses `<hostname>` and `<domain>`; `<dnsserver>`
  / `<timeservers>` / `<timezone>` / `<syslog>` are declared
  supported in the capability matrix but parser / render wire-up
  is incomplete.

## Junos

Source: [Junos OS Initial Configuration topic-map](https://www.juniper.net/documentation/us/en/software/junos/system-basics/topics/topic-map/initial-configuration-junos-os.html)
Source: [Junos syslog overview](https://www.juniper.net/documentation/us/en/software/junos/sys-mgmt/topics/concept/syslog-overview.html)
Retrieved: 2026-05-01

```
set system host-name leaf-01
set system domain-name lab.example.net
set system name-server 10.0.0.53
set system name-server 10.0.0.54
set system ntp server 10.0.0.123
set system ntp server 10.0.0.124 prefer
set system time-zone America/New_York
set system syslog host 10.0.0.250 any any
set system syslog host 10.0.0.251 any notice
```

Junos notes:

- Bare-short hostname; `domain-name` sibling.
- `name-server` lines stack.
- `ntp server` per-line; per-server modifiers extend the same
  hierarchy.
- Olson zoneinfo for `time-zone`.
- Syslog host requires explicit facility + severity (no implicit
  any-severity shortcut).

## Cross-vendor mapping

OPNsense -> Junos:

- `hostname`: **good** — OPNsense `<hostname>` ↔ Junos `host-name`.
  Lossless.
- `domain`: **good** — OPNsense `<domain>` ↔ Junos `domain-name`.
  Lossless.
- `dns_servers`: **lossy** — OPNsense `<dnsserver>` list maps to Junos
  `name-server` lines.  The opnsense codec does not currently parse
  `<dnsserver>` into the canonical list (declared supported, wire-up
  incomplete); cross-pair drops the resolver list pending wire-up.
- `ntp_servers`: **lossy** — OPNsense's space-separated
  `<timeservers>` element splits into Junos's per-server `ntp server`
  lines.  Per-server modifiers (`prefer`, `iburst`, `key`) drop on
  the canonical list (host-list-only model).  OPNsense codec does
  not currently wire `<timeservers>` into canonical.
- `timezone`: **lossy** — both vendors use Olson zoneinfo, so the
  semantic round-trips, BUT the opnsense codec does not currently
  wire `<timezone>` into `CanonicalIntent.timezone`.  Cross-pair
  drops the field pending wire-up.
- `syslog_servers`: **lossy** — OPNsense `<syslog>/<remoteserver>`
  maps to Junos `syslog host <addr> any any`.  Junos REQUIRES
  facility + severity tokens — canonical model has only host list,
  so render synthesises `any any`.  OPNsense codec does not
  currently parse syslog into canonical.

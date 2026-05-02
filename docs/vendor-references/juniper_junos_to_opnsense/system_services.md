# System services (hostname / domain / DNS / NTP / syslog / timezone): Junos versus OPNsense

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

Junos system-services notes:

- Hostname is the bare short name; `domain-name` is a sibling.
- DNS resolvers stack as repeated `name-server` set lines.
- NTP servers each declare their own `set system ntp server <addr>`
  line; per-server modifiers (`prefer`, `iburst`, `key`, `version`,
  `source-address`) extend the same hierarchy.
- Timezone uses Olson zoneinfo identifiers
  (`America/New_York`, `Etc/UTC`).
- Syslog remote receivers use `set system syslog host <addr> <facility>
  <severity>` form.  Severity is REQUIRED on Junos — there's no
  implicit "any-severity" shortcut.

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

OPNsense notes:

- `<hostname>` is the bare short name; `<domain>` is a sibling.
- DNS resolvers are repeated `<dnsserver>` elements (no priority).
- NTP servers are SPACE-SEPARATED inside a single `<timeservers>`
  element (a key shape mismatch with Junos's per-server lines).
- Timezone uses Olson zoneinfo (`America/Los_Angeles`).
- Syslog remote receivers under `<system>/<syslog>/<remoteserver>`.
- The opnsense codec parses `<hostname>` and `<domain>` (declared
  supported in capability matrix); `<dnsserver>` / `<timeservers>` /
  `<timezone>` / `<syslog>` are declared supported but parser /
  render wire-up is incomplete.

## Cross-vendor mapping

Junos -> OPNsense:

- `hostname`: **good** — Junos `host-name` ↔ OPNsense `<hostname>`.
  Both vendors model bare short name; round-trip is lossless.
- `domain`: **good** — Junos `domain-name` ↔ OPNsense `<domain>`.
  Both store as sibling DNS suffix.
- `dns_servers`: **lossy** — Junos `name-server` lines map to OPNsense
  repeated `<dnsserver>` elements.  The OPNsense codec does not
  currently parse `<dnsserver>` into the canonical `dns_servers` list,
  and does not currently emit `<dnsserver>` on render.  Cross-pair
  drops the resolver list pending wire-up.
- `ntp_servers`: **lossy** — Junos's per-server `ntp server <addr>` set
  lines collapse to OPNsense's space-separated `<timeservers>`
  element.  Per-server modifiers (`prefer`, `iburst`, `key`) drop on
  the canonical list (host-list-only model).  OPNsense codec does not
  currently wire `<timeservers>` into `CanonicalIntent.ntp_servers`.
- `timezone`: **lossy** — both vendors use Olson zoneinfo, so the
  semantic round-trips, BUT the opnsense codec does not currently
  wire `<timezone>` into `CanonicalIntent.timezone`.  Cross-pair
  drops the field pending wire-up.
- `syslog_servers`: **lossy** — Junos's host-list with required
  facility/severity collapses to a host-only canonical list; per-
  facility filters drop.  OPNsense codec does not currently parse
  syslog into `syslog_servers`.

Disposition rationale: a CLOSE structural match on the surface
(both vendors model the same primitives), but the opnsense codec's
incomplete parse / render wire-up degrades several Tier-1 fields
to `lossy` rather than `good`.  These are codec-implementation
gaps, not vendor-modelling gaps.

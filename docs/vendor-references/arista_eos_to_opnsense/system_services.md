# System services (hostname / domain / DNS / NTP / syslog / timezone): Arista EOS versus OPNsense

## Arista EOS

Source: [Arista EOS User Manual — System Configuration](https://www.arista.com/en/um-eos/eos-system-configuration)
Retrieved: 2026-05-01

```
hostname ks-leaf-01

ip name-server vrf default 10.0.0.53
ip name-server vrf default 10.0.0.54
dns domain example.net

ntp server 10.0.0.123
ntp server 10.0.0.124

clock timezone PST -8 0

logging host 10.0.0.200
logging host 10.0.0.201
```

Arista EOS notes:

- `hostname` is the bare short name (no quoting).
- `dns domain <fqdn>` carries the DNS suffix (renamed from the older
  `ip domain-name`).  The arista_eos codec parses both forms.
- `ip name-server vrf default <addr>` — Arista qualifies every
  resolver with a VRF; the codec strips the VRF qualifier on parse
  for the global / `default` VRF and stores resolvers in
  `CanonicalIntent.dns_servers`.
- NTP is full NTP (not SNTP); per-server modifiers (`prefer`,
  `iburst`, `key`, `source`) are accepted on the wire but not
  modelled on the canonical surface.
- Timezone uses `clock timezone <name> <hh-offset> <min-offset>`
  with optional `summer-time` companion; the canonical surface
  carries only the bare name.
- `logging host <addr>` is the syslog destination directive;
  severity / facility tokens are accepted but not modelled.

## OPNsense

Source: [OPNsense General Settings — System: Settings: General](https://docs.opnsense.org/manual/settingsmenu.html)
Retrieved: 2026-04-30

OPNsense stores system identity inside `<system>` in `config.xml`:

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

Notable shape differences from Arista:

- `hostname` is the bare short name; `domain` is a sibling element.
- DNS resolvers are repeated `<dnsserver>` elements (no priority
  ordinal — list order implies precedence).
- NTP servers are space-separated inside a SINGLE `<timeservers>`
  element rather than one element per server.
- Timezone uses an Olson / zoneinfo identifier
  (`America/Los_Angeles`).  No DST offset companion.
- Syslog destinations live in `<syslog>/<remoteserver>`.

## Cross-vendor mapping (Arista -> OPNsense)

Canonical fields covered:

```
hostname: str
domain: str
dns_servers: list[str]
ntp_servers: list[str]
timezone: str
syslog_servers: list[str]
```

- `hostname`: **good** — Arista bare-name ↔ OPNsense `<hostname>`.
- `domain`: **good** — Arista `dns domain` ↔ OPNsense `<domain>`.
  Both vendors model the DNS suffix as a separate scalar from the
  hostname.
- `dns_servers`: **lossy** — Arista per-resolver lines collapse to
  a bare list; OPNsense codec capability matrix declares
  `/system/dns-server` supported but render wire-up does not
  currently emit `<dnsserver>` elements on cross-vendor.
- `ntp_servers`: **lossy** — Arista one-per-line lines map to
  OPNsense's space-separated `<timeservers>` element; OPNsense
  codec does not currently wire `<timeservers>` into canonical on
  render.  Per-server NTP options not modelled.
- `timezone`: **lossy** — Arista `PST -8 0` (offset+DST tokens)
  versus OPNsense Olson zoneinfo (`America/Los_Angeles`) require an
  operator-curated mapping table.  Codec wire-up gap on both ends.
- `syslog_servers`: **lossy** — OPNsense codec does not currently
  wire `<syslog>` into canonical on render; severity / facility
  tokens are not modelled either.

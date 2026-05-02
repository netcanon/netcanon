# System services (hostname / domain / DNS / NTP / syslog / timezone): OPNsense versus Arista EOS

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

OPNsense identity layer notes:

- `hostname` is the bare short name; `domain` is a sibling DNS
  suffix.
- DNS resolvers are repeated `<dnsserver>` elements; list order
  implies precedence.
- NTP servers are space-separated inside a SINGLE
  `<timeservers>` element (rather than one element per server,
  as Arista emits).
- Timezone uses an Olson / zoneinfo identifier
  (`America/Los_Angeles`).
- Syslog destinations live in `<syslog>/<remoteserver>`; severity
  / facility filters are simpler than Arista's per-host
  classification grammar.

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

Arista identity layer notes:

- `hostname` is bare (no quoting).
- `dns domain <fqdn>` carries the DNS suffix; the older `ip
  domain-name` form parses too.
- `ip name-server vrf default <addr>` — Arista qualifies every
  resolver with a VRF; the codec strips the VRF qualifier on
  parse for the global / `default` VRF.
- NTP is full NTP (not SNTP); per-server modifiers (`prefer`,
  `iburst`) are accepted but not modelled.
- Timezone uses `clock timezone <name> <hh-offset> <min-offset>`;
  the canonical surface carries only the bare name.
- `logging host <addr>` is the syslog destination directive.

## Cross-vendor mapping (OPNsense -> Arista EOS)

Canonical fields covered:

```
hostname: str
domain: str
dns_servers: list[str]
ntp_servers: list[str]
timezone: str
syslog_servers: list[str]
```

- `hostname`: **good** — OPNsense `<hostname>` ↔ Arista bare-name.
- `domain`: **good** — OPNsense `<domain>` ↔ Arista `dns domain`.
- `dns_servers`: **lossy** — OPNsense codec parser does not
  currently wire `<dnsserver>` into
  `CanonicalIntent.dns_servers` (capability matrix declares the
  path supported but parser branch is incomplete).  Cross-pair
  drops the resolver list pending wire-up.
- `ntp_servers`: **lossy** — OPNsense's space-separated
  `<timeservers>` element is not currently wired into canonical
  on parse.
- `timezone`: **lossy** — OPNsense Olson zoneinfo
  (`America/Los_Angeles`) versus Arista `<name> <hh> <mm>`
  (`PST -8 0`) require an operator-curated mapping table.
- `syslog_servers`: **lossy** — OPNsense codec does not
  currently wire `<syslog>` into canonical on parse.

# SNMP: OPNsense versus Arista EOS

## OPNsense

Source: [OPNsense Net-SNMP plugin reference](https://docs.opnsense.org/development/api/plugins/netsnmp.html)
Retrieved: 2026-04-30

OPNsense's snmpd configuration lives in `<snmpd>`:

```xml
<opnsense>
  <snmpd>
    <syslocation>Synthetic-Lab Rack 7</syslocation>
    <syscontact>netops@example.invalid</syscontact>
    <rocommunity>public</rocommunity>
    <traphost>10.0.0.250</traphost>
  </snmpd>
</opnsense>
```

Notes:

- `<rocommunity>` carries the read-only community.
  `<rwcommunity>` is supported but rare; the opnsense codec
  collapses to RO on canonical.
- Multiple `<traphost>` elements are accepted.
- SNMPv3 USM is conspicuously absent from `config.xml`.  The
  OPNsense codec capability matrix lists `/snmp/v3-user` as
  unsupported with rationale: "OPNsense's SNMPv3 user store
  lives in the bsnmpd / net-snmp plugin's own configuration
  format (`/usr/local/etc/snmpd.conf` createUser lines), not
  in the config.xml this codec reads."

## Arista EOS

Source: [Arista EOS User Manual — SNMP](https://www.arista.com/en/um-eos/eos-snmp)
Retrieved: 2026-05-01

```
snmp-server community public ro
snmp-server location "Synthetic Lab Rack 7"
snmp-server contact "noc@example.net"
snmp-server host 10.0.0.250
snmp-server user monitor netadmin v3 auth sha $9$fake$authHash$1 priv aes256 $9$fake$privHash$1
```

- v1/v2c: `snmp-server community <name> {ro|rw}`.
- `snmp-server location` / `contact` carry quoted free-text.
- `snmp-server host <addr>` declares trap-receivers.
- v3 USM users: `snmp-server user <name> <group> v3 auth
  {md5|sha|sha256|...} <hash> priv {des|aes|aes256|...} <hash>`.
  Arista codec capability matrix declares `/snmp/v3-user`
  supported.

## Cross-vendor mapping (OPNsense -> Arista EOS)

Canonical fields covered (`CanonicalSNMP`).

- `snmp.community`: **good** — OPNsense `<rocommunity>` ↔
  Arista `snmp-server community X ro`.
- `snmp.location` / `snmp.contact`: **good** — direct mapping to
  Arista `snmp-server location` / `contact`.
- `snmp.trap_hosts`: **good** — OPNsense `<traphost>` ↔ Arista
  `snmp-server host <addr>` (multiple).
- `snmp.v3_users`: **not_applicable** — OPNsense source never
  populates `v3_users` (capability matrix declares
  `/snmp/v3-user` unsupported), so the canonical list is always
  empty on OPNsense parse.  Arista target would happily render
  `snmp-server user` lines but on this direction there is
  nothing to emit.

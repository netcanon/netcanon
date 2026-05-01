# SNMP: Aruba AOS-S versus MikroTik RouterOS

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Management and Configuration Guide
— SNMPv3 chapter](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MCG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
snmp-server community "public" Operator
snmp-server location "Synthetic-Lab Rack 7"
snmp-server contact "netops@example.invalid"
snmp-server host 10.0.10.200
snmp-server host 10.0.10.201

snmpv3 user "monitor-usr" auth sha "$1$fakeAJ$auth1abcdef0123456789" priv aes "$1$fakeAJ$priv1abcdef0123456789"
snmpv3 group "auth-priv-grp" user "monitor-usr" sec-model ver3
snmpv3 user "audit-usr" auth md5 "$1$fakeAJ$auth2abcdef0123456789" priv des "$1$fakeAJ$priv2abcdef0123456789"
snmpv3 group "auth-priv-grp" user "audit-usr" sec-model ver3
```

Aruba models v1/v2c with `snmp-server community "<str>" {Operator|
Manager}` (Operator = read-only; Manager = read-write).  Location and
contact land on bare globals; trap targets via `snmp-server host
<addr>` (multiple lines OK).

v3 USM splits across two directives:
- `snmpv3 user "<name>" auth {md5|sha} "<pass>" priv {aes|des}
  "<pass>"` — defines the user identity + crypto material.
- `snmpv3 group "<group>" user "<name>" sec-model ver3` — binds
  the user into a VACM access group.

Aruba supports auth = `md5` / `sha` (= SHA-1) and priv = `aes` (=
AES-128) / `des`.  SHA-2 family auth and AES-192 / AES-256 are NOT
available on AOS-S in 16.x.

## MikroTik RouterOS

Source: [SNMP — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/8978519/SNMP)
Retrieved: 2026-04-30

```
/snmp
set enabled=yes contact="netops@example.invalid" \
    location="Synthetic-Lab Rack 7" trap-target=10.0.10.200

/snmp community
set [ find default=yes ] name=public
add name=monitor-v3 authentication-protocol=SHA1 \
    authentication-password="<pass>" \
    encryption-protocol=AES \
    encryption-password="<pass>"
add name=audit-v3 authentication-protocol=MD5 \
    authentication-password="<pass>" \
    encryption-protocol=DES \
    encryption-password="<pass>"
```

RouterOS overloads the `/snmp community` section for BOTH v1/v2c
and v3 USM users — disambiguated by the presence of the crypto
knobs.  The `security=` parameter encodes the v3 securityLevel:
`none` = noAuthNoPriv, `authorized` = authNoPriv, `private` =
authPriv.

Authentication options on RouterOS 7.x are `MD5` / `SHA1` only.
Encryption options are `DES` / `AES` (= AES-128).  Newer RouterOS
builds expose `aes-192-cfb` / `aes-256-cfb` cipher names via the
`encryption-protocol=` attribute, but the canonical mapping
treats them as AES-256 / AES-192 for SNMPv3 USM purposes.

Trap targets configure on the global `/snmp / set trap-target=<addr>`,
**single-target only** — RouterOS 7.x does not support a list of
trap destinations.

## Cross-vendor mapping

The canonical surface is

```
CanonicalSNMP(community, location, contact, trap_hosts[], v3_users[])
CanonicalSNMPv3User(name, group, auth_protocol, auth_passphrase,
                    priv_protocol, priv_passphrase, engine_id)
```

### v1/v2c

`community` / `location` / `contact` round-trip cleanly.  Aruba uses
Operator/Manager access keywords; the canonical model stores only
the bare community string, so cross-vendor render to RouterOS treats
the access-level distinction as a `read-access=yes` /
`write-access=yes` flag set per community.  Inverse direction
(RouterOS source) defaults Aruba target communities to Operator.

### Trap hosts

Aruba supports multiple `snmp-server host` lines; RouterOS supports
**only one** trap target.  Multi-target Aruba source -> RouterOS
render keeps the first target only; remaining targets land in
`raw_sections` for operator review with a banner.

### v3 USM

Documented divergences:

- **Auth protocol overlap**: Aruba's `md5` / `sha` matches RouterOS
  `MD5` / `SHA1` exactly.  No downgrade required on this pair.
- **Priv cipher overlap**: Aruba's `aes` (= AES-128) / `des` matches
  RouterOS `AES` (= AES-128) / `DES`.  No downgrade required.
- **Passphrase opacity**: USM keys are salted with the device's
  engineID per RFC 3414.  Aruba-derived passphrases will fail
  authentication on RouterOS after migration even when both ends
  list `SHA1` + `AES`.  Operator must re-key on the target device.
  This is a vendor-side property, not a codec issue.
- **Group semantics**: Aruba carries a separate `snmpv3 group "<g>"
  user "<u>" sec-model ver3` binding; RouterOS does not model groups
  at all (v3 access is gated by the same `read-access=` /
  `write-access=` flags as v1/v2c).  Aruba source group field
  drops on RouterOS render.

### Disposition

| Field | Disposition |
|---|---|
| `snmp.community` | good |
| `snmp.location` | good |
| `snmp.contact` | good |
| `snmp.trap_hosts` | lossy (RouterOS single-target) |
| `snmp.v3_users[].name` | good |
| `snmp.v3_users[].group` | lossy (no RouterOS group concept) |
| `snmp.v3_users[].auth_protocol` | good (MD5 / SHA1 overlap) |
| `snmp.v3_users[].auth_passphrase` | lossy (engineID-salted; re-key required) |
| `snmp.v3_users[].priv_protocol` | good (AES-128 / DES overlap) |
| `snmp.v3_users[].priv_passphrase` | lossy (engineID-salted; re-key required) |

# SNMP: Cisco IOS-XE versus MikroTik RouterOS

## Cisco IOS-XE

Sources:
- [Cisco IOS XE SNMP Configuration Guide — SNMPv3](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/snmp/configuration/xe-3se/3850/snmp-xe-3se-3850-book/nm-snmp-snmpv3.html)

```
snmp-server community public RO
snmp-server community netops-ro RO 99
snmp-server community netops-rw RW
snmp-server location dc-1-rack-7
snmp-server contact noc@example.com
snmp-server host 10.0.0.50 version 2c public

! v3 USM
snmp-server group RO-GROUP v3 priv read v1default
snmp-server user readuser RO-GROUP v3 auth sha S3cretAuth! priv aes 128 S3cretPriv!
```

Cisco lays out v1/v2c as `snmp-server community <name> {RO|RW} [acl]`,
with location/contact as bare globals and trap targets via
`snmp-server host`.  v3 takes a separate `snmp-server group` plus
`snmp-server user` with `auth {md5|sha}` and `priv {des|3des|aes
{128|192|256}}` keyword forms.

## MikroTik RouterOS

Source: [SNMP — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/8978519/SNMP)

Retrieved: 2026-04-30

```
/snmp
set enabled=yes contact=noc@example.com location=dc-1-rack-7 \
  trap-version=2 trap-community=public trap-target=10.0.0.50 \
  trap-generators=interfaces

/snmp community
set [ find default=yes ] name=public
add name=netops-ro security=none read-access=yes write-access=no
add name=netops-rw security=none read-access=yes write-access=yes
add name=v3readuser security=private \
    authentication-protocol=SHA1 authentication-password=S3cretAuth! \
    encryption-protocol=AES encryption-password=S3cretPriv!
```

RouterOS overloads the `/snmp community` section to carry BOTH v1/v2c
and v3 USM users — disambiguated by the presence of crypto knobs
(`authentication-protocol=` indicates a v3 user).  The `security=`
parameter is RouterOS's encoding of the v3 securityLevel:

- `security=none`           = noAuthNoPriv (v1/v2c-style or v3 with no crypto)
- `security=authorized`     = authNoPriv
- `security=private`        = authPriv

Authentication options are `MD5` and `SHA1` only on RouterOS — the
SHA-2 family (`sha256` / `sha384` / `sha512`) that Cisco supports
from IOS-XE 17.10 onward has no RouterOS equivalent in v7.x.

Encryption options are `DES` and `AES` (which RouterOS treats as
AES-128); Cisco's `aes 192` and `aes 256` and `3des` cipher options
have no RouterOS equivalents.

Trap targets configure on the global `/snmp set trap-target=...`,
single-target only — Cisco supports multiple `snmp-server host`
declarations.

## Cross-vendor mapping

The canonical surface is

```
CanonicalSNMP(community, location, contact, trap_hosts[], v3_users[])
CanonicalSNMPv3User(name, group, auth_protocol, auth_passphrase,
                    priv_protocol, priv_passphrase, engine_id)
```

### v1/v2c

`community` / `location` / `contact` round-trip cleanly.  RouterOS
emits a single primary community name on `/snmp community / set
[ find default=yes ] name=X`; additional communities live as
extra `add` lines.

### Trap hosts

Cisco's `snmp-server host` list maps to RouterOS's single
`trap-target=` setting — RouterOS supports only ONE trap target
in v7.x.  Multi-target Cisco source -> RouterOS render drops to
the first target only; the rest land in `raw_sections` for
operator review.

### v3 USM

Documented divergences:

- **Auth protocol downgrade**: SHA-2 family auth on Cisco
  (`auth sha256`, etc.) cannot render on RouterOS — only
  `MD5` and `SHA1` are available.  Cross-vendor migration of an
  SHA-256 v3 user emits a `SHA1` line with a banner; operator
  must rotate the user's password.
- **Priv cipher downgrade**: Cisco's `aes 192` / `aes 256` /
  `3des` have no RouterOS equivalent.  Render drops to AES-128
  with a banner.
- **Passphrase opacity**: USM keys are salted with the device's
  engineID per RFC 3414.  Cisco-derived passphrases will fail
  authentication on RouterOS after migration even when both ends
  list `SHA1` + `AES`.  Operator must re-key on the target.
  This is a vendor-side property, not a codec issue.
- **Group semantics**: Cisco's `snmp-server group / read view`
  fine-grained access-control has no first-class RouterOS
  equivalent — RouterOS gates v3 access via the same
  `read-access=yes / write-access=yes` flags it uses for v1/v2c.

### Disposition

| Field | Disposition |
|---|---|
| `snmp.community` | good |
| `snmp.location` | good |
| `snmp.contact` | good |
| `snmp.trap_hosts` | lossy (RouterOS single-target) |
| `snmp.v3_users[].name` | good |
| `snmp.v3_users[].group` | lossy (no RouterOS group concept) |
| `snmp.v3_users[].auth_protocol` | lossy (SHA-2 -> SHA1 downgrade) |
| `snmp.v3_users[].auth_passphrase` | lossy (engineID-salted; re-key required) |
| `snmp.v3_users[].priv_protocol` | lossy (AES-192/256/3DES -> AES-128) |
| `snmp.v3_users[].priv_passphrase` | lossy (engineID-salted; re-key required) |

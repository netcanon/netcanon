# SNMP: MikroTik RouterOS versus Cisco IOS-XE

## MikroTik RouterOS

Source: [SNMP — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/8978519/SNMP)

Retrieved: 2026-04-30

```
/snmp
set enabled=yes contact=noc@example.com location=dc-1-rack-7 \
  trap-version=2 trap-community=public trap-target=10.0.0.50

/snmp community
set [ find default=yes ] name=public
add name=netops-ro security=none read-access=yes write-access=no
add name=v3readuser security=private \
    authentication-protocol=SHA1 authentication-password=S3cretAuth! \
    encryption-protocol=AES encryption-password=S3cretPriv!
```

RouterOS overloads `/snmp community` to carry both v1/v2c
communities and v3 USM users — disambiguated by the presence of
`authentication-protocol=`.  Auth options: `MD5` / `SHA1`.
Encryption options: `DES` / `AES` (AES-128).  Trap target is
single-valued.

## Cisco IOS-XE

Sources:
- [Cisco IOS XE SNMP Configuration Guide — SNMPv3](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/snmp/configuration/xe-3se/3850/snmp-xe-3se-3850-book/nm-snmp-snmpv3.html)

```
snmp-server community public RO
snmp-server community netops-ro RO
snmp-server location dc-1-rack-7
snmp-server contact noc@example.com
snmp-server host 10.0.0.50 version 2c public

snmp-server group RO-GROUP v3 priv
snmp-server user v3readuser RO-GROUP v3 \
  auth sha S3cretAuth! priv aes 128 S3cretPriv!
```

Cisco models v1/v2c with `snmp-server community` and v3 with
`snmp-server group` + `snmp-server user`.  Auth options:
`md5` / `sha` (= SHA-1) / `sha256` / `sha384` / `sha512` (17.10+).
Privacy options: `des` / `3des` / `aes 128` / `aes 192` / `aes 256`.
Multiple `snmp-server host` lines for multi-target traps.

## Cross-vendor mapping

The canonical surface is

```
CanonicalSNMP(community, location, contact, trap_hosts[], v3_users[])
CanonicalSNMPv3User(name, group, auth_protocol, auth_passphrase,
                    priv_protocol, priv_passphrase, engine_id)
```

### Round-trip behaviour from MikroTik source

`community` / `location` / `contact` round-trip cleanly.

`trap_hosts[]` is single-element (RouterOS supports only one
trap target); rendering on Cisco emits one `snmp-server host` line.
This is the inverse-direction lossy: MikroTik source carries less
information than Cisco can express.

### v3 USM upgrade direction

When the MikroTik source is v3-enabled:

- **Auth protocol** is always `MD5` or `SHA1` from RouterOS.
  Cisco accepts both directly — no information loss in this
  direction.  Cisco's broader algorithm support (SHA-256+) is
  unused.
- **Priv cipher** from RouterOS is always `DES` or `AES`
  (= AES-128).  Cisco accepts both — `AES` -> Cisco `aes 128`.
  Cisco's `aes 192` / `aes 256` / `3des` are unused.
- **Passphrase** is opaque and engineID-salted per RFC 3414.
  Cross-vendor migration of v3 user passphrases requires re-
  keying on the target — same constraint as cisco -> mikrotik.
- **Group** field is empty from RouterOS source (RouterOS does
  not model SNMP groups).  Cisco render emits a default group
  name if none was provided; operator may need to wire up
  views and access control separately.

### Disposition

| Field | Disposition (MikroTik -> Cisco) |
|---|---|
| `snmp.community` | good |
| `snmp.location` | good |
| `snmp.contact` | good |
| `snmp.trap_hosts` | good (single-target collapses cleanly) |
| `snmp.v3_users[].name` | good |
| `snmp.v3_users[].group` | lossy (no source data; default group injected) |
| `snmp.v3_users[].auth_protocol` | good (MD5/SHA1 -> Cisco md5/sha direct map) |
| `snmp.v3_users[].auth_passphrase` | lossy (engineID-salted; re-key required) |
| `snmp.v3_users[].priv_protocol` | good (DES/AES -> Cisco des/aes 128) |
| `snmp.v3_users[].priv_passphrase` | lossy (engineID-salted; re-key required) |

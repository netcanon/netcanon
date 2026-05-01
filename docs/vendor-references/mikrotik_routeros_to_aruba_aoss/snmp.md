# SNMP: MikroTik RouterOS versus Aruba AOS-S

## MikroTik RouterOS

Source: [SNMP — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/8978519/SNMP)
Retrieved: 2026-04-30

```
/snmp
set enabled=yes contact="noc@example.net" \
    location="Synthetic Lab Rack 7" trap-target=10.0.0.250

/snmp community
set [ find default=yes ] name=public
add name=monitor-v3 authentication-protocol=SHA1 \
    authentication-password="<pass>" \
    encryption-protocol=AES \
    encryption-password="<pass>"
```

RouterOS overloads `/snmp community` for both v1/v2c and v3 USM.
Auth = `MD5` / `SHA1` only on the canonical-stable surface.  Priv
= `DES` / `AES` (= AES-128).  Trap target is **single** —
`trap-target=` accepts only one address.  The newer
`encryption-protocol=aes-256-cfb` variant is treated as AES-256
canonically.

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

snmpv3 user "monitor-usr" auth sha "<hash>" priv aes "<hash>"
snmpv3 group "auth-priv-grp" user "monitor-usr" sec-model ver3
```

Aruba uses `snmp-server community "<str>" {Operator|Manager}`.
Multiple `snmp-server host` lines are accepted (multi-target trap
list).  v3 USM splits across `snmpv3 user` (identity + crypto) and
`snmpv3 group ... user ... sec-model ver3` (VACM binding).
Auth = `md5` / `sha` (SHA-1).  Priv = `aes` (AES-128) / `des`.
SHA-2 family and AES-192/256 are NOT available on AOS-S 16.x.

## Cross-vendor mapping

The canonical surface is

```
CanonicalSNMP(community, location, contact, trap_hosts[], v3_users[])
CanonicalSNMPv3User(name, group, auth_protocol, auth_passphrase,
                    priv_protocol, priv_passphrase, engine_id)
```

### v1/v2c

`community` / `location` / `contact` round-trip cleanly.  RouterOS
has no Operator/Manager access-keyword distinction (uses
`read-access=` / `write-access=` flags); cross-vendor render to
Aruba defaults RouterOS source communities to **Operator**
(read-only) unless the source had `write-access=yes` set.

### Trap hosts

RouterOS supports only ONE trap target — single-element list
collapses cleanly to one `snmp-server host` line on the Aruba
render.  No fan-out loss in this direction.

### v3 USM

- **Auth protocol overlap**: RouterOS source `MD5` / `SHA1` matches
  Aruba `md5` / `sha`.  No downgrade required.
- **Priv cipher**: RouterOS `AES` (= AES-128) / `DES` matches
  Aruba `aes` / `des`.  RouterOS-specific `aes-256-cfb` (when
  present) does NOT have an Aruba equivalent — render emits Aruba
  `aes` (= AES-128) with a banner.
- **Passphrase opacity**: USM keys are salted with the device's
  engineID per RFC 3414 — operator MUST re-key on the target Aruba
  device after migration.
- **Group**: RouterOS does not model SNMPv3 groups (canonical
  `group` is empty after RouterOS parse).  Aruba target render
  injects a default group name (`canonical-default-grp` or
  similar) and emits the `snmpv3 group ... user ... sec-model ver3`
  binding with a banner.

### Disposition

| Field | Disposition |
|---|---|
| `snmp.community` | good |
| `snmp.location` | good |
| `snmp.contact` | good |
| `snmp.trap_hosts` | good (RouterOS single-target collapses cleanly) |
| `snmp.v3_users[].name` | good |
| `snmp.v3_users[].group` | lossy (RouterOS has no group; Aruba target injects default) |
| `snmp.v3_users[].auth_protocol` | good (MD5 / SHA1 overlap) |
| `snmp.v3_users[].auth_passphrase` | lossy (engineID-salted; re-key required) |
| `snmp.v3_users[].priv_protocol` | lossy (AES-256 -> AES-128 downgrade with banner; AES/DES overlap otherwise) |
| `snmp.v3_users[].priv_passphrase` | lossy (engineID-salted; re-key required) |

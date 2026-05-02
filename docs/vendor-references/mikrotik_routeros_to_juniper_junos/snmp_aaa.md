# SNMP + AAA (RADIUS): MikroTik RouterOS versus Juniper Junos

How SNMP v1/v2c/v3 and RADIUS servers are declared on each platform.

Sources:
- MikroTik: https://help.mikrotik.com/docs/spaces/ROS/pages/8978519/SNMP (retrieved 2026-05-01)
- MikroTik: https://help.mikrotik.com/docs/spaces/ROS/pages/13402205/RADIUS (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/network-mgmt/topics/concept/snmp-overview.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/network-mgmt/topics/topic-map/snmpv3-configuration.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/radius-server-edit-system.html (retrieved 2026-05-01)

Citation ids: `mikrotik-snmp`, `mikrotik-radius`,
`junos-snmp-overview`, `junos-snmpv3-cg`, `junos-radius-cli`.

## RouterOS form

```
/snmp
set enabled=yes contact="noc@example.net" location="Synthetic Lab Rack 7" \
    trap-target=10.0.0.250

/snmp community
set [ find default=yes ] name=public
add name=write-rw
add name=monitor-v3 authentication-protocol=SHA1 \
    authentication-password="fake-auth-passphrase-1" \
    encryption-protocol=AES \
    encryption-password="fake-priv-passphrase-1"

/radius
add address=10.0.0.10 secret=fake-radius-shared-secret-1 service=login \
    authentication-port=1812 accounting-port=1813
```

RouterOS overloads `/snmp community` for both v1/v2c and v3 (the
`authentication-protocol=` / `encryption-protocol=` parameters
discriminate v3 from v1/v2c).  Algorithm tokens: `MD5` / `SHA1` /
`SHA256` for auth (SHA256 added in 7.13+); `DES` / `AES` (= AES-128)
on early lines; v7.13+ also accepts `aes-256-cfb`.  A SINGLE
`trap-target=` parameter — RouterOS does NOT support multi-target
trap lists in the canonical surface.  RADIUS secrets stored opaque
(`secret=<string>`); /export shows the value clear unless
`hide-sensitive` is set.

## Junos form

```
set snmp community public authorization read-only
set snmp community private authorization read-write
set snmp location "Synthetic Lab Rack 7"
set snmp contact "noc@example.net"
set snmp trap-group monitoring targets 10.0.0.250
set snmp trap-group monitoring targets 10.0.0.251

set snmp v3 usm local-engine user monitor authentication-md5 \
    authentication-key "$9$fakeMd5AuthKey$1"
set snmp v3 usm local-engine user monitor privacy-des \
    privacy-key "$9$fakeDesPrivKey$1"
set snmp v3 vacm security-to-group security-model usm \
    security-name monitor group netadmin

set system radius-server 10.0.0.200 secret "$9$fakeRadiusSecret$1"
```

Junos models v3 USM with explicit `authentication-{md5,sha,sha224,
sha256}` and `privacy-{des,aes128,aes192,aes256}` algorithm tokens,
plus a separate `vacm security-to-group` binding for VACM access
control.  Encrypted-key blobs use Junos's reversible `$9$...` format.
RADIUS shared secrets are also `$9$...`-encrypted on disk.

## Cross-vendor mapping

* `snmp.community`: RouterOS `/snmp community add name=X
  read-access=yes` -> Junos `set snmp community X authorization
  read-only`.  RouterOS gates access via `read-access=` /
  `write-access=` flags; canonical model carries only the bare
  community string, so codec policy decision: `read-access=yes`
  -> `read-only`, `write-access=yes` -> `read-write`.
* `snmp.location` / `snmp.contact`: scalar strings, direct mapping.
* `snmp.trap_hosts`: RouterOS's single `/snmp set trap-target=X` ->
  Junos `set snmp trap-group <synthesised-name> targets X`.  Junos
  supports multiple targets per group; RouterOS source provides at
  most one — Junos render emits a single-target trap-group.
* `snmp.v3_users` (USM):
  * Algorithm overlap good: RouterOS `MD5` / `SHA1` -> Junos
    `authentication-md5` / `authentication-sha`; `DES` / `AES`
    (= AES-128) -> `privacy-des` / `privacy-aes128`.  RouterOS
    7.13+ `SHA256` / `aes-256-cfb` -> Junos
    `authentication-sha256` / `privacy-aes256`.
  * Passphrases are engineID-salted per RFC 3414; RouterOS opaque
    passphrase form is not portable to Junos's `$9$...` format —
    operator MUST re-key on the target.
  * VACM groups: RouterOS does not model VACM groups (gates v3
    access via `read-access=` / `write-access=`); Junos render
    synthesises a default group based on access flags.
* `radius_servers`: RouterOS `/radius add address=<ip> secret=<key>
  authentication-port=<p>` -> Junos `set system radius-server <ip>
  secret <key> port <p>`.  Default ports (1812 / 1813) preserved.
  Secret cross-decrypt impossible: RouterOS plaintext secret is
  imported verbatim into Junos but Junos will encrypt on disk to
  `$9$...` form; cross-vendor migration of the running secret value
  works ONLY if the RouterOS source had `hide-sensitive` off and
  the operator captured the cleartext value.

Disposition: **good** for community / location / contact and trap-host
list (single-target); **lossy** for v3 USM (engineID-salted
passphrases, VACM-group synthesis required); **lossy** for RADIUS
(secret form mismatch).

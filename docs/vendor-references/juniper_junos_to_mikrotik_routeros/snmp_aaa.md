# SNMP + AAA (RADIUS): Juniper Junos versus MikroTik RouterOS

How SNMP v1/v2c/v3 and RADIUS servers are declared on each platform.

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/network-mgmt/topics/concept/snmp-overview.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/network-mgmt/topics/topic-map/snmpv3-configuration.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/radius-server-edit-system.html (retrieved 2026-05-01)
- MikroTik: https://help.mikrotik.com/docs/spaces/ROS/pages/8978519/SNMP (retrieved 2026-05-01)
- MikroTik: https://help.mikrotik.com/docs/spaces/ROS/pages/13402205/RADIUS (retrieved 2026-05-01)

Citation ids: `junos-snmp-overview`, `junos-snmpv3-cg`,
`junos-radius-cli`, `mikrotik-snmp`, `mikrotik-radius`.

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
set system radius-server 10.0.0.201 port 1812 secret "$9$fakeRadiusSecret$2"
```

Junos models v3 USM with explicit `authentication-{md5,sha,sha224,
sha256}` and `privacy-{des,aes128,aes192,aes256}` algorithm tokens,
plus a separate `vacm security-to-group` binding for VACM access
control.  Encrypted-key blobs use Junos's reversible `$9$...` format.
RADIUS shared secrets are also `$9$...`-encrypted on disk.

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

RouterOS overloads `/snmp community` for both v1/v2c (`name=public`,
no auth/priv) AND v3 (`authentication-protocol=` + `encryption-
protocol=`).  Algorithm tokens are case-sensitive and limited:
`MD5` / `SHA1` for auth, `DES` / `AES` (= AES-128) for priv on
v6 / early v7; v7.13+ accepts `SHA256` / `aes-256-cfb` extensions.
A single `trap-target=` parameter — RouterOS does NOT support
multi-target trap lists in the canonical surface.  RADIUS secrets
are stored opaque (`secret=<string>`); RouterOS does not expose a
reversible-encrypted on-disk form — `/export` shows the value in
clear unless `hide-sensitive` is set.

## Cross-vendor mapping

* `snmp.community`: Junos `set snmp community X authorization
  read-only` -> RouterOS `/snmp community add name=X`.  Authorization
  (read-only / read-write) is canonically per-community on Junos but
  RouterOS gates access via `read-access=yes` / `write-access=yes`
  flags — codec policy decision required.
* `snmp.location` / `snmp.contact`: scalar strings, direct mapping.
* `snmp.trap_hosts`: Junos's `trap-group <name> targets <addr>` (with
  multiple targets per group) flattens to the canonical list;
  RouterOS supports only ONE `trap-target=` value, so multi-target
  Junos source drops to the first with a banner.
* `snmp.v3_users` (USM):
  * Algorithm overlap: MD5 / SHA1 / SHA256 supported on both for
    auth (Junos `authentication-md5` / `authentication-sha` /
    `authentication-sha256` -> RouterOS `MD5` / `SHA1` / `SHA256`);
    DES / AES (=AES-128) supported on both for priv.  Junos's
    AES-192 / AES-256 (`privacy-aes192` / `privacy-aes256`) downgrade
    to RouterOS `AES` (AES-128) on early RouterOS, or map to v7.13+
    `aes-256-cfb` if the target version supports it.
  * Passphrases are engineID-salted per RFC 3414; Junos's `$9$...`
    blobs are not portable to RouterOS — operator MUST re-key on
    the target.
  * VACM groups: Junos's `security-to-group` binding has no
    first-class RouterOS equivalent (RouterOS gates v3 access via
    the same `read-access= / write-access=` flags as v1/v2c); group
    field drops on render.
* `radius_servers`: Junos `set system radius-server <ip> secret <key>
  port <p>` -> RouterOS `/radius add address=<ip> secret=<key>
  authentication-port=<p>`.  Default ports (1812 / 1813) preserved.
  Secret cross-decrypt impossible: Junos's `$9$...` reversible form
  cannot be decoded by RouterOS, and operator must re-set the
  shared secret on the target.

Disposition: **good** for community / location / contact and trap-host
list (with truncation to first entry on render); **lossy** for v3
USM (engineID-salted passphrases, downgraded crypto on early
RouterOS, group binding drops); **lossy** for RADIUS (secret
cross-decrypt impossible).

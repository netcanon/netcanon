# SNMP and RADIUS AAA: Arista EOS versus MikroTik RouterOS

## Arista EOS

Sources:
- [Arista EOS — SNMP Configuration](https://www.arista.com/en/um-eos/eos-snmp)
- [Arista EOS — AAA / RADIUS](https://www.arista.com/en/um-eos/eos-aaa)

Retrieved: 2026-05-01

```
snmp-server community public ro
snmp-server location "Synthetic Lab Rack 7"
snmp-server contact "noc@example.net"
snmp-server host 10.0.0.250 version 2c public
snmp-server host 10.0.0.251 version 3 priv monitor

snmp-server user monitor netadmin v3 auth sha $9$fake$authHash$1 priv aes256 $9$fake$privHash$1
snmp-server user readonly readonly v3 auth sha256 $9$fake$authHash$2 priv aes $9$fake$privHash$2

radius-server host 10.0.0.30 key 7 fakeRadiusObfuscatedKey
radius-server host 10.0.0.31 auth-port 1812 acct-port 1813 key cleartextSecret

aaa group server radius RADIUS-AUTH
   server 10.0.0.30
   server 10.0.0.31

aaa authentication login default group RADIUS-AUTH local
```

Arista's SNMP grammar is the Cisco-IOS-derived `snmp-server
community / location / contact / host / user` form.  v3 USM
supports the broader algorithm set: `auth {md5|sha|sha256|sha384|
sha512}` and `priv {des|aes|aes192|aes256|3des}`.  The `aes`
keyword bare means AES-128.

Trap hosts are **multi-target** — multiple `snmp-server host`
declarations are allowed, each with its own version + community
or v3-user binding.

RADIUS uses Cisco-derived `radius-server host` form with
optional `key 7 ...` (Cisco type-7 reversible obfuscation) or
plaintext `key cleartextSecret`.  Method-list policy (`aaa group
server radius` + `aaa authentication login default group ...`)
binds RADIUS to specific service contexts.

The `arista_eos` codec capability matrix lists `/snmp/community`,
`/snmp/location`, `/snmp/contact`, `/snmp/trap-host`, and
`/snmp/v3-user` under **supported**.

## MikroTik RouterOS

Sources:
- [SNMP — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/8978519/SNMP)
- [RADIUS — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/13402205/RADIUS)

Retrieved: 2026-05-01

```
/snmp
set enabled=yes contact="noc@example.net" location="Synthetic Lab Rack 7" \
    trap-target=10.0.0.250

/snmp community
set [ find default=yes ] name=public
add name=monitor-v3 authentication-protocol=SHA1 \
    authentication-password="fake-auth-passphrase-1" \
    encryption-protocol=AES \
    encryption-password="fake-priv-passphrase-1"

/radius
add address=10.0.0.30 secret=fake-radius-shared-secret-1 service=login \
    authentication-port=1812 accounting-port=1813
add address=10.0.0.31 secret=fake-radius-shared-secret-2 service=login,dhcp \
    authentication-port=1645 accounting-port=1646
```

RouterOS's `/snmp` block carries the **device-level** scalars
(contact / location / trap-target).  `trap-target=` is a single
attribute — RouterOS supports only ONE trap target.

RouterOS overloads `/snmp community` for both v1/v2c (bare
`name=`) and v3 (with `authentication-protocol=` /
`authentication-password=` / `encryption-protocol=` /
`encryption-password=`).  Algorithms are narrower than Arista's:
`MD5` / `SHA1` for auth, `DES` / `AES` (= AES-128) for priv.
SHA-2 family and AES-192/256 are NOT supported on the standard
RouterOS build (some 7.x builds expose `aes-256-cfb` but it is
not the conventional canonical AES-256 USM mode).

RADIUS uses `/radius add address=X secret=K service=login,...`
form.  `service=` binds the RADIUS server to specific service
contexts (login, ppp, wireless, hotspot, dhcp, ipsec).

The `mikrotik_routeros` codec capability matrix lists
`/snmp/community`, `/snmp/location`, `/snmp/contact`,
`/snmp/trap-host`, and `/snmp/v3-user` under **supported**.

## Cross-vendor mapping

The canonical surface is `CanonicalIntent.snmp:
CanonicalSNMP | None` (with `community` / `location` / `contact`
/ `trap_hosts: list[str]` / `v3_users: list[CanonicalSNMPv3User]`)
plus `CanonicalIntent.radius_servers: list[CanonicalRADIUSServer]`.

Arista -> RouterOS round-trip:

**SNMP v1/v2c surface** — round-trips cleanly:

* `snmp-server community public ro` -> `/snmp community / set [
  find default=yes ] name=public` (or `/snmp community / add
  name=public read-access=yes` for additional communities).
* `snmp-server location "..."` -> `/snmp / set location="..."`.
* `snmp-server contact "..."` -> `/snmp / set contact="..."`.

**Trap hosts** — lossy: Arista supports multiple `snmp-server
host` declarations; RouterOS supports only one `trap-target=`.
Multi-target Arista source drops to the first host with a
banner; the rest land in raw_sections.

**v3 USM surface** — multiple cliffs:

* Algorithm downgrade: Arista's `auth sha256 / sha384 / sha512`
  collapses to RouterOS's `SHA1` (the codec maps SHA-2 family to
  SHA1 with a banner because RouterOS does not implement SHA-2
  USM).  Arista's `priv aes192 / aes256 / 3des` collapses to
  RouterOS's `AES` (AES-128) with a banner.
* Passphrases: USM keys are engineID-salted per RFC 3414 and
  never cross-portable.  Operator MUST re-key on the RouterOS
  target.
* Group / view-based access control: Arista's
  `snmp-server group <name>` view-based access has no
  first-class RouterOS equivalent — RouterOS gates v3 access via
  `read-access=yes` / `write-access=yes` flags on the same
  `/snmp community` row.  Group field on
  `CanonicalSNMPv3User.group` drops on render.

**RADIUS** — lossy:

* Host / auth_port / acct_port round-trip cleanly.
* Shared secret: Arista's `key 7 ...` (type-7 reversible) or
  cleartext `key K` -> RouterOS's `secret=K`.  Both codecs pass
  through verbatim.
* Service binding: RouterOS's `service=login,ppp,wireless,...`
  versus Arista's method-list / server-group model is not
  modelled canonically.  Arista `aaa group server radius` /
  `aaa authentication login default ...` lands in raw_sections;
  RouterOS render defaults to `service=login` with a banner.

Disposition: **lossy** — see the YAML for the per-field break-
down.

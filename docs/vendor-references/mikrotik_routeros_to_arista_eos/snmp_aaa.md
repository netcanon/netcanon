# SNMP and RADIUS AAA: MikroTik RouterOS versus Arista EOS

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
add name=write-rw
add name=monitor-v3 authentication-protocol=SHA1 \
    authentication-password="fake-auth-passphrase-1" \
    encryption-protocol=AES \
    encryption-password="fake-priv-passphrase-1"
add name=audit-v3 authentication-protocol=SHA256 \
    authentication-password="fake-auth-passphrase-2" \
    encryption-protocol=aes-256-cfb \
    encryption-password="fake-priv-passphrase-2"

/radius
add address=10.0.0.10 secret=fake-radius-shared-secret-1 service=login \
    authentication-port=1812 accounting-port=1813
add address=10.0.0.11 secret=fake-radius-shared-secret-2 service=login,dhcp \
    authentication-port=1645 accounting-port=1646
```

RouterOS overloads `/snmp community` for both v1/v2c and v3.
v1/v2c entries have just `name=`; v3 entries add
`authentication-protocol=` (`MD5` / `SHA1`) +
`authentication-password=` + `encryption-protocol=` (`DES` /
`AES`) + `encryption-password=`.

`trap-target=` is a single attribute — RouterOS supports only
ONE trap target.

(Note: some RouterOS 7 builds expose `aes-256-cfb` as an
`encryption-protocol=` value, but it is not the conventional
canonical AES-256 USM mode.  The kitchen-sink fixture uses it as
realistic context; the codec maps it to canonical
`priv_protocol="aes256"` for downstream interpretation.)

RADIUS uses `/radius add address=X secret=K service=login,...`
with `authentication-port=` and `accounting-port=` for non-
default ports.

The `mikrotik_routeros` codec capability matrix lists
`/snmp/community`, `/snmp/location`, `/snmp/contact`,
`/snmp/trap-host`, and `/snmp/v3-user` under **supported**.

## Arista EOS

Sources:
- [Arista EOS — SNMP Configuration](https://www.arista.com/en/um-eos/eos-snmp)
- [Arista EOS — AAA / RADIUS](https://www.arista.com/en/um-eos/eos-aaa)

Retrieved: 2026-05-01

```
snmp-server community public ro
snmp-server location "Synthetic Lab Rack 7"
snmp-server contact "noc@example.net"
snmp-server host 10.0.0.250

snmp-server user monitor-v3 default v3 auth sha fake-auth-passphrase-1 priv aes fake-priv-passphrase-1
snmp-server user audit-v3 default v3 auth sha256 fake-auth-passphrase-2 priv aes256 fake-priv-passphrase-2

radius-server host 10.0.0.10 key fake-radius-shared-secret-1
radius-server host 10.0.0.11 auth-port 1645 acct-port 1646 key fake-radius-shared-secret-2

aaa authentication login default group radius local
```

Arista's SNMP grammar is the Cisco-IOS-derived `snmp-server
community / location / contact / host / user` form.  v3 USM
supports the broader algorithm set: `auth {md5|sha|sha256|sha384|
sha512}` and `priv {des|aes|aes192|aes256|3des}`.

Trap hosts are multi-target — multiple `snmp-server host`
declarations are allowed.

RADIUS uses `radius-server host <addr> [auth-port N] [acct-port
M] key <secret>` form.  Method-list policy via `aaa
authentication login default group ...`.

## Cross-vendor mapping

The canonical surface is `CanonicalIntent.snmp:
CanonicalSNMP | None` (community / location / contact /
trap_hosts / v3_users) plus
`CanonicalIntent.radius_servers: list[CanonicalRADIUSServer]`.

RouterOS -> Arista round-trip:

**SNMP v1/v2c surface** — round-trips cleanly:

* RouterOS `/snmp / set contact=... location=...` -> Arista
  `snmp-server contact "..."` / `snmp-server location "..."`.
* RouterOS `/snmp community / set [ find default=yes ] name=public`
  -> Arista `snmp-server community public ro`.

**Trap hosts** — clean: RouterOS `trap-target=10.0.0.250` (single
target) -> Arista `snmp-server host 10.0.0.250` (single line).
The narrow-to-broad direction has no loss.

**v3 USM surface** — the algorithm-set is NOT a bottleneck in
this direction:

* RouterOS source uses `MD5` / `SHA1` (mapped to canonical
  `auth_protocol="md5" | "sha"`) and `DES` / `AES` (mapped to
  canonical `priv_protocol="des" | "aes"` (= AES-128)).  All
  four are subsets of Arista's broader algorithm support.
* Arista render emits `snmp-server user <name> default v3 auth
  {md5|sha} <hash> priv {des|aes} <hash>`.  The mapping is
  direct.
* Passphrases: USM keys are engineID-salted per RFC 3414 and
  never cross-portable.  Operator MUST re-key on the Arista
  target.
* Group field is empty on RouterOS source (RouterOS does not
  model groups); Arista render injects a default group name
  (`default`) with banner.

**RADIUS** — lossy:

* Host / auth_port / acct_port round-trip cleanly.
* Shared secret: RouterOS opaque `secret=K` -> Arista's `key K`.
  Both codecs pass through verbatim; Arista may auto-encode on
  write so byte-on-disk differs.
* Service binding: RouterOS's `service=login,ppp,wireless,...`
  versus Arista's method-list / server-group model is not
  modelled canonically.  RouterOS-side service bindings beyond
  standard login drop to raw_sections; Arista render emits
  default `aaa authentication login default group radius local`.

The MikroTik synthetic kitchen-sink carries:
- v1/v2c: `public` + `write-rw` communities, `noc@example.net`
  contact, `Synthetic Lab Rack 7` location, `10.0.0.250` trap
  target
- v3: `monitor-v3` (SHA1 + AES) + `audit-v3` (SHA256 + AES-256-CFB)
- RADIUS: `10.0.0.10` (login) + `10.0.0.11` (login,dhcp; non-
  default ports)

All entries lift to canonical and render to Arista; only the
`audit-v3` SHA256+AES-256-CFB combo carries algorithm metadata
that Arista accepts unchanged (canonical `auth=sha256
priv=aes256`).

Disposition: **lossy** — see the YAML for the per-field break-
down.  This direction is friendlier than the inverse because
RouterOS's narrow algorithm set fits inside Arista's broader
support.

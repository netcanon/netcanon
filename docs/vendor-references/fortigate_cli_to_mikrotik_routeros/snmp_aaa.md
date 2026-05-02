# SNMP / RADIUS / AAA: FortiGate FortiOS versus MikroTik RouterOS

## FortiGate FortiOS CLI

Sources:
- [FortiGate / FortiOS 7.4 CLI Reference — `config system snmp`](https://docs.fortinet.com/document/fortigate/7.4.0/cli-reference/) — `sysinfo`, `community`, `user` sub-commands.
- [FortiGate / FortiOS 7.4 Administration Guide — RADIUS server](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/) — `config user radius`.

Retrieved: 2026-04-30

```
config system snmp sysinfo
    set status enable
    set location "data-center-rack-7"
    set contact-info "noc@example.org"
end
config system snmp community
    edit 1
        set name "public-ro"
        config hosts
            edit 1
                set ip "10.50.0.10 255.255.255.255"
            next
        end
    next
end
config system snmp user
    edit "monitor-readonly"
        set security-level auth-priv
        set auth-proto sha256
        set auth-pwd ENC fakeAuthHashAAAA==
        set priv-proto aes256
        set priv-pwd ENC fakePrivHashBBBB==
    next
end

config user radius
    edit "primary-radius"
        set server "10.50.0.20"
        set secret ENC fakeRadiusSecret11111111==
        set auth-type auto
        set radius-port 1812
    next
end
```

Notable FortiOS specifics:

- v1/v2c communities live in a separate edit-table (`config system snmp community / edit <N> / set name "<community>"`) with associated `config hosts` for trap targets.  Multiple communities are supported (each edit-id is independent).
- v3 users live on `config system snmp user / edit "<username>" / set auth-proto / set priv-proto / set auth-pwd ENC ... / set priv-pwd ENC ...`.  Hashes use the FortiOS proprietary `ENC <opaque-base64>` format derived from an internal key.
- Auth protocols: `md5`, `sha1`, `sha224`, `sha256`, `sha384`, `sha512`.  Priv protocols: `des`, `aes128`, `aes192`, `aes256`.
- RADIUS: `config user radius / edit "<name>" / set server <ip> / set secret ENC ... / set radius-port <port>` — single `radius-port` (no separate acct-port; FortiOS derives as auth + 1).

## MikroTik RouterOS

Sources:
- [SNMP — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/8978519/SNMP) — `/snmp`, `/snmp community`.
- [RADIUS — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/13402205/RADIUS) — `/radius`.

Retrieved: 2026-04-30

```
/snmp
set enabled=yes contact="noc@example.org" location="data-center-rack-7" \
    trap-target=10.50.0.10

/snmp community
set [ find default=yes ] name=public-ro
add name=monitor-v3 authentication-protocol=SHA1 \
    authentication-password="fake-auth-passphrase-1" \
    encryption-protocol=AES \
    encryption-password="fake-priv-passphrase-1"

/radius
add address=10.50.0.20 secret=fake-radius-shared-secret \
    service=login authentication-port=1812 accounting-port=1813
```

Notable RouterOS specifics:

- v1/v2c communities live on `/snmp community` records.  v3 USM uses the same `/snmp community` table with `authentication-protocol=` / `authentication-password=` / `encryption-protocol=` / `encryption-password=` attributes added.
- RouterOS supports only **MD5 / SHA1** for auth and **DES / AES (= AES-128) / AES-256** for priv — the algorithm set is narrower than FortiOS's.
- Single `trap-target=` on `/snmp` (singleton, not a list).  FortiOS-source multi-host communities collapse to the first on render.
- v3 auth/priv passphrases are stored as opaque strings; passphrases are engineID-salted per RFC 3414 and never cross-portable.
- RADIUS records support `service=login,ppp,wireless,...` (a comma-list selecting which RouterOS daemons consult the server) and separate `authentication-port=` / `accounting-port=`.

## Cross-vendor mapping (FortiGate → RouterOS)

Canonical surface:

```
CanonicalSNMP.community: str
CanonicalSNMP.location: str
CanonicalSNMP.contact: str
CanonicalSNMP.trap_hosts: list[str]
CanonicalSNMP.v3_users: list[CanonicalSNMPv3User]
CanonicalRADIUSServer.host / .key / .auth_port / .acct_port
```

### SNMP

- **community** — `lossy`.  FortiOS allows multiple community edit-records but canonical holds a single scalar; cross-vendor render takes the first community on parse.  RouterOS render emits the community via `/snmp community`.  Operator/Manager-style permission distinctions on FortiOS map only positionally.
- **location / contact** — `good`.  FortiOS `sysinfo` strings round-trip to RouterOS `/snmp set location= / set contact=`.
- **trap_hosts** — `lossy`.  FortiOS allows multiple trap host edit-records under `config hosts` per community; canonical normalises to a list, but RouterOS supports only a single `trap-target=` value — multi-host FortiOS sources collapse to the first on render.
- **v3_users** — `lossy`.  Multi-cliff loss:
  - FortiOS supports SHA-2 family (sha224/256/384/512) and AES-192/256 but RouterOS supports only MD5 / SHA1 / AES-128 / AES-256.  Stronger algorithms downgrade with banner.
  - FortiOS `ENC <opaque-base64>` hashes are encrypted with FortiOS internal-key; RouterOS expects plain passphrase strings (then engineID-salts internally).  Cross-vendor migration requires re-keying.
  - Both vendors engineID-salt USM keys per RFC 3414, so even matching algorithm choices would not survive a hash transplant.

### RADIUS

- **host** — `good`.  FortiOS `set server "<ip>"` -> RouterOS `add address=<ip>`.
- **key** — `lossy`.  FortiOS `set secret ENC <opaque-base64>` (FortiOS-internal-key encrypted) versus RouterOS bare `secret=<text>`.  Cross-vendor migration requires re-keying.  Both codecs preserve the secret verbatim with vendor tags so the loss surfaces in the validation report.
- **auth_port / acct_port** — `lossy`.  FortiOS exposes only `set radius-port` (single value; acct-port is derived as auth+1 per RFC default).  Non-default acct-port values cannot be expressed in the FortiOS source; RouterOS render emits `accounting-port=auth+1` by default.  In the FortiGate-source case, acct-port differs from RFC default only when operators tweak it on RouterOS targets.
- **service binding** — RouterOS `service=login,ppp,wireless,...` has no FortiOS source counterpart (FortiOS RADIUS records bind to authentication contexts via separate FortiGate-side configuration).  RouterOS render defaults to `service=login` on cross-vendor.

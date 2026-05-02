# SNMP / RADIUS / AAA: MikroTik RouterOS versus FortiGate FortiOS

## MikroTik RouterOS

Sources:
- [SNMP — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/8978519/SNMP) — `/snmp`, `/snmp community`.
- [RADIUS — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/13402205/RADIUS) — `/radius`.

Retrieved: 2026-04-30

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
add name=audit-v3 authentication-protocol=SHA256 \
    authentication-password="fake-auth-passphrase-2" \
    encryption-protocol=aes-256-cfb \
    encryption-password="fake-priv-passphrase-2"

/radius
add address=10.0.0.10 secret=fake-radius-shared-secret-1 service=login \
    authentication-port=1812 accounting-port=1813
```

Notable RouterOS specifics:

- v1/v2c communities live on `/snmp community` records; `[find default=yes]` is the built-in `public` community which can be renamed.  Multiple communities can be added.
- v3 USM uses the same `/snmp community` table augmented with `authentication-protocol=` / `authentication-password=` / `encryption-protocol=` / `encryption-password=`.
- RouterOS supports **MD5 / SHA1** for auth and **DES / AES (= AES-128) / AES-256** for priv.  Some recent RouterOS versions also accept SHA256 / SHA512 — the MikroTik codec accepts these tokens but they may not be portable to all RouterOS deployments.
- Single `trap-target=` on `/snmp` (singleton, not a list).
- v3 passphrases are stored as opaque strings; engineID-salted per RFC 3414 and never cross-portable.
- RADIUS records support `service=login,ppp,wireless,...` (which RouterOS daemons consult the server) and separate `authentication-port=` / `accounting-port=`.

## FortiGate FortiOS CLI

Sources:
- [FortiGate / FortiOS 7.4 CLI Reference — `config system snmp`](https://docs.fortinet.com/document/fortigate/7.4.0/cli-reference/) — `sysinfo`, `community`, `user` sub-commands.
- [FortiGate / FortiOS 7.4 Administration Guide — RADIUS server](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/) — `config user radius`.

Retrieved: 2026-04-30

```
config system snmp sysinfo
    set status enable
    set location "Synthetic Lab Rack 7"
    set contact-info "noc@example.net"
end
config system snmp community
    edit 1
        set name "public"
        config hosts
            edit 1
                set ip "10.0.0.250 255.255.255.255"
            next
        end
    next
end
config system snmp user
    edit "monitor-v3"
        set security-level auth-priv
        set auth-proto sha1
        set auth-pwd ENC fakeAuthHash==
        set priv-proto aes128
        set priv-pwd ENC fakePrivHash==
    next
end
config user radius
    edit "primary-radius"
        set server "10.0.0.10"
        set secret ENC fakeRadiusSecret==
        set radius-port 1812
    next
end
```

FortiOS supports auth `md5 / sha1 / sha224 / sha256 / sha384 / sha512` and priv `des / aes128 / aes192 / aes256`.  Hashes use the FortiOS proprietary `ENC <opaque-base64>` format derived from an internal key.

RADIUS exposes only `set radius-port` (single value; FortiOS derives acct-port as auth + 1 per RFC default).

## Cross-vendor mapping (RouterOS → FortiGate)

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

- **community** — `lossy`.  RouterOS supports multiple `/snmp community` records but canonical holds a single scalar; the first community parses to canonical.  FortiOS render emits `config system snmp community / edit 1 / set name "<community>"`.
- **location / contact** — `good`.  RouterOS `set location=` / `set contact=` -> FortiOS sysinfo strings.
- **trap_hosts** — `lossy`.  RouterOS supports only a single `trap-target=` value; canonical holds it as a one-element list.  FortiOS render emits the trap host under `config hosts` with edit id 1.  RouterOS-source single-host case round-trips with no information loss; if the trap-target field is empty the canonical list is empty.
- **v3_users** — `lossy`.  Multi-cliff loss:
  - RouterOS auth set is narrower (MD5 / SHA1, with some recent versions accepting SHA256 / SHA512).  FortiOS supports SHA-2 family natively, so RouterOS-source SHA-2 algorithms (`SHA256`, `aes-256-cfb`) round-trip cleanly to FortiOS but RouterOS-source MD5 / SHA1 are weak by FortiOS standards.
  - RouterOS plaintext-or-engineID-salted-stored passphrases versus FortiOS `ENC <opaque-base64>` (FortiOS-internal-key encrypted).  Cross-vendor migration requires re-keying.
  - Both vendors engineID-salt USM keys per RFC 3414, so even matching algorithm choices would not survive a hash transplant.
- **engine_id** — `lossy`.  Field exists in canonical but neither codec wires it through.

### RADIUS

- **host** — `good`.  RouterOS `add address=10.0.0.10` -> FortiOS `set server "10.0.0.10"`.
- **key** — `lossy`.  RouterOS `secret=<text>` (plaintext on /export) versus FortiOS `set secret ENC <opaque-base64>` (FortiOS-internal-key encrypted).  Cross-vendor migration requires re-keying.  Both codecs preserve the secret verbatim with vendor tags so the loss surfaces in the validation report.
- **auth_port / acct_port** — `lossy`.  RouterOS exposes both `authentication-port=` and `accounting-port=` independently; FortiOS exposes only `set radius-port` (auth-port; acct-port is derived as auth + 1).  RouterOS-source pairs where acct-port != auth-port + 1 lose the divergence — the FortiGate render emits only the auth-port value.
- **service binding** — RouterOS `service=login,ppp,wireless,...` has no FortiOS counterpart and drops on render (FortiOS RADIUS records bind to authentication contexts via separate FortiGate-side configuration).

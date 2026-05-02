# SNMP + AAA / RADIUS: Arista EOS versus FortiGate FortiOS

## Arista EOS — SNMP

Source: [Arista EOS User Manual — SNMP (4.35.2F)](https://www.arista.com/en/um-eos/eos-snmp)
Retrieved: 2026-05-01

```
snmp-server community public ro
snmp-server location "Synthetic Lab Rack 7"
snmp-server contact "noc@example.net"
snmp-server host 10.0.0.250 version 2c public
!
snmp-server user monitor netadmin v3 auth sha $9$fake$authHash$1 \
                                       priv aes256 $9$fake$privHash$1
snmp-server user readonly readonly v3 auth sha256 $9$fake$authHash$2 \
                                       priv aes $9$fake$privHash$2
```

Notable Arista specifics:

- **Cisco-derived SNMPv3 grammar** — `snmp-server user <name> <group>
  v3 auth {md5|sha|sha224|sha256|sha384|sha512} <pass> priv
  {des|aes|aes128|aes192|aes256|3des} <pass>`.
- **Group and view membership** under `snmp-server group` (not in
  scope for the canonical `v3_users` list).
- **Community / location / contact / trap-host** are flat scalars —
  the canonical model captures the bare values.

## Arista EOS — AAA / RADIUS

Source: [Arista EOS User Manual — RADIUS (4.35.2F)](https://www.arista.com/en/um-eos/eos-radius)
Retrieved: 2026-05-01

```
radius-server host 10.50.0.20 key "fakeRadiusKeyAAA"
radius-server host 10.50.0.21 auth-port 1812 acct-port 1813 \
                              key "fakeRadiusKeyBBB"
!
aaa group server radius CORE
   server 10.50.0.20
   server 10.50.0.21
!
aaa authentication login default group CORE local
```

Notable Arista specifics:

- **Cisco-derived `radius-server host` grammar** — host/key are
  positional with optional `auth-port`/`acct-port` modifiers.
- **Default ports**: 1812 auth / 1813 acct (RFC 2865/2866).
- **AAA method-list grammar** is not modelled in canonical (Tier 3).
- **TACACS+** is also not modelled in canonical v1.

## FortiGate FortiOS CLI — SNMP

Source: [Fortinet Document Library — SNMP CLI Reference (FortiOS 7.4)](https://docs.fortinet.com/document/fortigate/7.4.0/cli-reference/)
Retrieved: 2026-05-01

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
        set auth-pwd ENC fakeAuthHashAAAAAAAAAAAAAA==
        set priv-proto aes256
        set priv-pwd ENC fakePrivHashBBBBBBBBBBBBBB==
    next
end
```

Notable FortiOS specifics:

- **Edit-table community** — multiple community strings possible (each
  with its own host list); canonical model holds a single scalar so
  multi-community sources lose all but the first on parse.
- **Trap hosts live inside `config hosts`** under each community —
  with a dotted-mask discriminator (often `/32`) that the codec
  strips.
- **SNMPv3 user fields** — `set security-level
  {no-auth-no-priv|auth-no-priv|auth-priv}`; `set auth-proto
  {md5|sha|sha224|sha256|sha384|sha512}`; `set priv-proto
  {aes|aes256|aes256cisco|des}`.  Hashes are stored as
  `ENC <opaque-base64>` — FortiOS-internal encryption keyed to the
  device.

## FortiGate FortiOS CLI — RADIUS

Source: [Fortinet Document Library — RADIUS server configuration (FortiOS 7.4 Admin Guide)](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/)
Retrieved: 2026-05-01

```
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

- **Edit-table form** with a per-server name (not host-keyed).
- **`set secret ENC <opaque-base64>`** — FortiOS-internal encryption
  that is NOT cross-compatible with other vendors' shared-secret
  formats.
- **No separate acct-port field** — derived as auth-port + 1 per RFC
  default.  Non-default Arista `acct-port` values drop on render.
- **Per-server attribute support** under `config user radius`
  (e.g. `set nas-ip`, `set h3c-compatibility`).

## Cross-vendor mapping (Arista -> FortiGate) — SNMP

Canonical surface:

```
snmp.community: str
snmp.location: str
snmp.contact: str
snmp.trap_hosts: list[str]
snmp.v3_users: list[CanonicalSNMPv3User]
```

- **community / location / contact** — `good`.  Scalar string
  preservation; both codecs round-trip.  Caveat: FortiOS edit-table
  can carry multiple community strings but canonical holds a single
  scalar, so multi-community FortiGate-source migrations lose detail
  (not a concern in this direction since Arista source has only one).
- **trap_hosts** — `good`.  Both vendors emit a host list; FortiGate
  renders inside `config hosts` under the community edit.
- **v3_users** — `lossy`.  Username / group / protocol enum
  round-trip cleanly.  Auth/priv passphrases are NOT cross-compatible
  — Arista hashes (`$9$<scrypt>` for service-encryption-keyed
  blobs) cannot be decrypted by FortiOS, and FortiOS's `ENC <base64>`
  cannot be decrypted by Arista.  Operator MUST re-key v3 users on
  the target.  Protocol-enum coercion: Arista's `aes`/`aes128` ->
  FortiOS `aes`; Arista's `aes192` has no FortiOS analogue (FortiOS
  supports `aes` (128) / `aes256`/`aes256cisco`/`des`) and would
  drop or coerce.
- **engine_id** — `lossy`.  Field exists in canonical but not wired
  through either codec's parse/render path in v1.

## Cross-vendor mapping (Arista -> FortiGate) — RADIUS

Canonical surface:

```
radius_servers[].host: str
radius_servers[].key: str
radius_servers[].auth_port: int
radius_servers[].acct_port: int
```

- **host / auth_port** — `good`.  Direct scalar mapping.
- **key (shared secret)** — `lossy`.  Format incompatible: Arista
  emits plaintext or type-7 reversible (`7 <hex>`); FortiOS uses
  `ENC <opaque-base64>`.  Cross-vendor migration requires re-keying.
  Both codecs preserve the source-form verbatim with vendor tags so
  the loss is visible in the validation report.
- **acct_port** — `lossy`.  FortiOS has no separate acct-port field
  (derived as auth-port + 1 per RFC default), so non-default Arista
  acct-port values drop.

Disposition summary: **good** for SNMP scalars (community / location /
contact / trap_hosts), RADIUS host/auth_port.  **Lossy** for v3 USM
passphrases (re-keying required), RADIUS shared-secret (re-keying),
RADIUS acct_port (no separate field).  TACACS+ and AAA method-list
not modelled.

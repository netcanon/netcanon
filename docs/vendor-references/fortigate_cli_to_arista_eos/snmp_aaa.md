# SNMP + AAA / RADIUS: FortiGate FortiOS versus Arista EOS

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
            edit 2
                set ip "10.50.0.11 255.255.255.255"
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
    edit "noc-fullaccess"
        set security-level auth-priv
        set auth-proto sha512
        set auth-pwd ENC fakeAuthHashCCCCCCCCCCCCCC==
        set priv-proto aes256
        set priv-pwd ENC fakePrivHashDDDDDDDDDDDDDD==
    next
end
```

Notable FortiOS specifics:

- **Edit-table community** — multiple community strings possible.
  Each carries its own host list with optional dotted-mask
  discriminator.  Canonical model holds a single scalar; multi-
  community FortiGate sources lose all but one on parse.
- **SNMPv3 user fields** — `set security-level
  {no-auth-no-priv|auth-no-priv|auth-priv}`; `set auth-proto
  {md5|sha|sha224|sha256|sha384|sha512}`; `set priv-proto
  {aes|aes256|aes256cisco|des}`.  Hashes stored as `ENC <opaque-
  base64>` keyed to the device.

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
    edit "secondary-radius"
        set server "10.50.0.21"
        set secret ENC fakeRadiusSecret22222222==
        set auth-type auto
        set radius-port 1645
    next
end
```

Notable FortiOS specifics:

- **Edit-table form** with a per-server name (not host-keyed).
- **`set secret ENC <opaque-base64>`** — FortiOS-internal
  encryption that is NOT cross-compatible with other vendors'
  shared-secret formats.
- **No separate acct-port field** (derived as auth-port + 1).

## Arista EOS — SNMP + RADIUS

Source: [Arista EOS User Manual — SNMP (4.35.2F)](https://www.arista.com/en/um-eos/eos-snmp)
Source: [Arista EOS User Manual — RADIUS (4.35.2F)](https://www.arista.com/en/um-eos/eos-radius)
Retrieved: 2026-05-01

```
snmp-server community public ro
snmp-server location "Synthetic Lab Rack 7"
snmp-server contact "noc@example.net"
snmp-server host 10.0.0.250 version 2c public
!
snmp-server user monitor netadmin v3 auth sha $9$fake$authHash$1 \
                                       priv aes256 $9$fake$privHash$1
!
radius-server host 10.50.0.20 key "fakeRadiusKeyAAA"
radius-server host 10.50.0.21 auth-port 1812 acct-port 1813 \
                              key "fakeRadiusKeyBBB"
```

Notable Arista specifics:

- **Cisco-derived SNMPv3 grammar** — `snmp-server user <name>
  <group> v3 auth ... priv ...`.
- **Single community per access-mode** (`ro` / `rw`) — multi-
  community via multiple `snmp-server community` lines.
- **Cisco-derived `radius-server host` grammar** — host/key are
  positional with optional auth-port/acct-port modifiers.

## Cross-vendor mapping (FortiGate -> Arista) — SNMP

Canonical surface:

```
snmp.community: str
snmp.location: str
snmp.contact: str
snmp.trap_hosts: list[str]
snmp.v3_users: list[CanonicalSNMPv3User]
```

- **community / location / contact** — `lossy`.  FortiGate's edit-
  table can carry multiple community strings; canonical holds a
  single scalar.  Multi-community FortiOS configs lose all but one
  on parse.  Otherwise scalar preservation is clean.
- **trap_hosts** — `good`.  FortiGate `config hosts` host list
  collapses to canonical list; Arista renders one `snmp-server
  host <addr>` line per entry.
- **v3_users** — `lossy`.  Username / group / protocol enum round-
  trip cleanly.  Auth/priv passphrases NOT cross-compatible —
  FortiOS `ENC <opaque-base64>` requires the FortiGate device's
  master key; Arista cannot decrypt and would emit the source-form
  blob untouched (which Arista's parser will reject).  Operator
  MUST re-key v3 users on the target.  Protocol-enum coercion:
  FortiOS `aes256cisco` has no Arista analogue (Arista accepts
  des / aes / aes128 / aes192 / aes256 / 3des); FortiOS `sha224`
  maps to Arista `sha224` directly.
- **engine_id** — `lossy`.  Field exists in canonical but not
  wired through either codec in v1.

## Cross-vendor mapping (FortiGate -> Arista) — RADIUS

Canonical surface:

```
radius_servers[].host: str
radius_servers[].key: str
radius_servers[].auth_port: int
radius_servers[].acct_port: int
```

- **host / auth_port** — `good`.  Direct scalar mapping.  FortiGate
  edit-name (e.g. `primary-radius`) is dropped (Arista's flat
  host-keyed form has no per-server name slot).
- **key (shared secret)** — `lossy`.  FortiOS `ENC <opaque-base64>`
  is not Arista-parseable; cross-vendor migration requires re-
  keying.  Both codecs preserve source-form with vendor tags so
  the loss surfaces in the validation report.
- **acct_port** — `lossy`.  FortiOS has no separate acct-port
  field (derived as auth-port + 1 per RFC default).  Canonical
  default is 1813; Arista renders `acct-port 1813`.  Non-default
  Arista-target acct-port values would need operator override.

Disposition summary: **good** for SNMP scalars (location / contact /
trap_hosts), RADIUS host/auth_port.  **Lossy** for community (multi-
community collapses to single scalar), v3 USM passphrases (re-keying
required), RADIUS shared-secret (re-keying), RADIUS acct_port
(default-derived).

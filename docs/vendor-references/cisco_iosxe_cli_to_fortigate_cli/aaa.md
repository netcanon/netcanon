# AAA / RADIUS / TACACS+: Cisco IOS-XE versus FortiGate FortiOS

## Cisco IOS-XE

Source: Cisco IOS XE Security Configuration Guide — Authentication,
Authorization, and Accounting (AAA).

Modern Cisco IOS-XE uses the named server form:

```
radius server PRIMARY
 address ipv4 10.0.0.10 auth-port 1812 acct-port 1813
 key SHARED-SECRET
!
radius server SECONDARY
 address ipv4 10.0.0.11
 key SHARED-SECRET
!
aaa group server radius RADIUS-AUTH
 server name PRIMARY
 server name SECONDARY
!
aaa authentication login default group RADIUS-AUTH local
```

Cisco TACACS+ has the same shape with `tacacs server <name>`.  Both
auth-port (default 1812 for RADIUS, 49 for TACACS+) and acct-port
(default 1813) are explicit when non-default.

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide — Authentication / RADIUS server](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/) — `config user radius`.
Source: FortiOS CLI Reference — `config user radius` and
`config user tacacs+`.
Retrieved: 2026-04-30

FortiOS uses the `config user radius` block:

```
config user radius
    edit "MyRadius"
        set server "10.0.0.10"
        set secret ENC <opaque-base64>
        set auth-type auto
        set radius-port 1812
        set source-ip 10.0.0.1
        set acct-interim-interval 600
    next
    edit "MyRadius2"
        set server "10.0.0.11"
        set secret ENC <opaque-base64>
    next
end
```

TACACS+ has the parallel `config user tacacs+` block with
`set port 49` (default) instead of `radius-port`.

Notable FortiOS specifics:

- **Single port field.**  FortiOS exposes `set radius-port <N>` as a
  single integer (the auth port); the acct port is derived as
  `radius-port + 1` per RFC default.  No separate `acct-port`
  override.  This means Cisco-side configurations with non-default
  acct-port values lose information on round-trip.
- **`set radius-port 0` idiom.**  FortiOS uses `0` as a placeholder
  for "use the default 1812"; the FortiGate codec normalises this
  to the effective value `1812` so round-trip stays stable (see
  `parse._apply_user_radius`).
- **`ENC` prefix on shared secrets.**  Same convention as admin
  passwords — FortiOS encrypts with an internal key.

## Cross-vendor mapping (Cisco -> FortiGate)

Canonical surface:

```
class CanonicalRADIUSServer(BaseModel):
    host: str
    key: str = ""              # shared secret (opaque)
    auth_port: int = 1812
    acct_port: int = 1813
```

- **host** — `good`.  Direct preservation; FortiGate edit ID is
  operator-curated and the canonical host carries the IP.
- **key** — `lossy`.  Cisco's `key SHARED-SECRET` (plaintext or
  type-7-encoded) versus FortiOS's `ENC <opaque-base64>`.  Cross-
  vendor migration of RADIUS shared secrets requires re-setting
  the key on the target device.  Both codecs pass through verbatim
  with vendor tags so the loss surfaces in the validation report.
- **auth_port** — `good`.  Direct map to `set radius-port`.
- **acct_port** — `lossy`.  FortiOS has no separate acct-port field;
  non-default values from Cisco drop on round-trip.

TACACS+ servers are **not modelled in v1** (no `CanonicalTACACSServer`
class); cross-vendor migration of TACACS+ configurations is
unsupported.  Lands when canonical schema gets a TACACS class.

Disposition for RADIUS host / auth_port: **good**.

Disposition for RADIUS key: **lossy** (cross-vendor secret formats
incompatible; re-keying required).

Disposition for RADIUS acct_port: **lossy** (FortiOS schema gap;
non-default acct-port values drop).

Disposition for TACACS+: **unsupported** (canonical schema gap).

Disposition for `aaa authentication login default ...` and other
AAA orchestration: **unsupported** (no canonical model in v1; both
vendors carry rich auth-method-list semantics that don't map 1:1).

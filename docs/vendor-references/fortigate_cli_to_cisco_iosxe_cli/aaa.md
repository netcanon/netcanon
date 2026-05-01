# AAA / RADIUS / TACACS+: FortiGate FortiOS versus Cisco IOS-XE

Reverse-direction sibling of
[`../cisco_iosxe_cli_to_fortigate_cli/aaa.md`](../cisco_iosxe_cli_to_fortigate_cli/aaa.md).
Source URLs unchanged.

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide — Authentication / RADIUS server](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/).
Retrieved: 2026-04-30

```
config user radius
    edit "MyRadius"
        set server "10.0.0.10"
        set secret ENC <opaque-base64>
        set auth-type auto
        set radius-port 1812
    next
end
```

## Cisco IOS-XE

Source: Cisco IOS XE Security Configuration Guide — AAA.

```
radius server PRIMARY
 address ipv4 10.0.0.10 auth-port 1812 acct-port 1813
 key SHARED-SECRET
```

## Cross-vendor mapping (FortiGate -> Cisco)

Canonical surface (same as forward direction):

```
class CanonicalRADIUSServer(BaseModel):
    host: str
    key: str = ""
    auth_port: int = 1812
    acct_port: int = 1813
```

- **host** — `good`.  Direct preservation.
- **key** — `lossy`.  FortiOS `ENC <opaque-base64>` is not
  Cisco-accepted; cross-vendor migration of RADIUS shared secrets
  requires re-setting the key on the target device.  Both codecs
  pass through verbatim with vendor tags so the loss surfaces in
  the validation report.
- **auth_port** — `good`.  Direct map.  FortiGate's `0` placeholder
  for "use default 1812" is normalised at parse-time (see
  `parse._apply_user_radius`), so canonical `auth_port` is
  always the effective integer.
- **acct_port** — `lossy`.  FortiOS has no separate acct-port
  field; canonical `acct_port` is always the default `1813`
  after FortiGate parse, so Cisco-side configurations expecting
  a non-default acct-port lose information.

TACACS+ servers are **not modelled in v1** (no
`CanonicalTACACSServer` class).

Disposition for RADIUS host / auth_port: **good**.

Disposition for RADIUS key: **lossy**.

Disposition for RADIUS acct_port: **lossy** (FortiOS schema gap).

Disposition for TACACS+: **unsupported** (canonical schema gap).

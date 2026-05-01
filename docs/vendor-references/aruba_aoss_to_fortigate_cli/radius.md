# RADIUS: Aruba AOS-S versus FortiGate FortiOS

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Access Security Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ASG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S declares RADIUS servers in a flat, host-keyed form:

```
radius-server host 10.0.20.10 key "fakeRadiusSecret-A"
radius-server host 10.0.20.11 key "fakeRadiusSecret-B"
radius-server key "global-default-secret"
```

Notable AOS-S specifics:

- **Host-keyed identity.**  No server-name field; the host address
  IS the identity.
- **Per-server `key`** override or **global default** via the
  bare `radius-server key`.  The codec normalises to per-server
  keys on parse.
- **Default ports** (1812 auth / 1813 acct) are implicit; the
  shape `radius-server host <ip> auth-port 1812 acct-port 1813
  key "X"` is also accepted but rare in real captures.

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide — RADIUS](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/).
Retrieved: 2026-04-30

FortiOS uses an edit-table form with explicit named records:

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

- **Named edit ID.**  Operators provide a free-form name; FortiOS
  uses it everywhere downstream (for `config user group` membership,
  `config system admin / set remote-auth`, etc.).
- **`set secret ENC <opaque-base64>`** — internal-key-encrypted
  shared secret.  NOT cross-compatible with Aruba's plaintext /
  shadowed forms.
- **No separate `acct-port` field.**  FortiOS derives the
  accounting port as `radius-port + 1` per RFC default.  Non-1813
  accounting ports require operator override outside the
  `config user radius` block.
- **`set auth-type auto`** specifies the authentication protocol
  (PAP / CHAP / MS-CHAPv2 / MS-CHAP / auto).  Not modelled in
  canonical.

## Cross-vendor mapping (Aruba -> FortiGate)

Canonical surface:

```
class CanonicalRADIUSServer(BaseModel):
    host: str
    key: str = ""
    auth_port: int = 1812
    acct_port: int = 1813
```

- **host** — `good`.  Direct preservation.
- **key** — `lossy`.  Aruba's plaintext / shadowed string lands in
  canonical; FortiOS render emits `set secret ENC <encrypted>`
  with the shared-secret material wrapped in the FortiGate
  internal-key cipher.  The cipher is device-specific so Aruba-
  source secrets will not authenticate after migration without
  re-keying.
- **auth_port** — `good`.  Default 1812 round-trips.
- **acct_port** — `lossy`.  FortiOS has no separate field;
  non-default acct ports drop on render.
- **server-name** (FortiOS-only) — synthesised from the host
  address on render (e.g. `radius_10.0.20.10`).  Operators may
  want to override post-migration.

Disposition: **lossy**.  Reason: shared-secret format
incompatibility (re-keying required) and acct-port loss for
non-default values.

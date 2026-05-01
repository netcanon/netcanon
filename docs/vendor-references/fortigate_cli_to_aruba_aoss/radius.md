# RADIUS: FortiGate FortiOS versus Aruba AOS-S

This is the reverse-direction sibling of
[`../aruba_aoss_to_fortigate_cli/radius.md`](../aruba_aoss_to_fortigate_cli/radius.md).

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide — RADIUS](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/).
Retrieved: 2026-04-30

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

- Named edit ID required.
- `set secret ENC <opaque-base64>` — internal-key encryption.
- No separate `acct-port` field (derived as `radius-port + 1`).

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Access Security Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ASG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
radius-server host 10.50.0.20 key "<plaintext-or-shadowed>"
radius-server host 10.50.0.21
radius-server key "global-default-secret"
```

Flat host-keyed form.  No server-name field.  See
[`../aruba_aoss_to_fortigate_cli/radius.md`](../aruba_aoss_to_fortigate_cli/radius.md)
for full Aruba specifics.

## Cross-vendor mapping (FortiGate -> Aruba)

Canonical surface:

```
class CanonicalRADIUSServer(BaseModel):
    host: str
    key: str = ""
    auth_port: int = 1812
    acct_port: int = 1813
```

- **host** — `good`.  Direct preservation (FortiOS `set server` ->
  Aruba `radius-server host`).
- **key** — `lossy`.  FortiOS `ENC <opaque-base64>` is not
  Aruba-accepted.  Cross-vendor migration requires re-keying.
  Aruba renders the per-host `radius-server host <ip> key
  "<secret>"` form with the canonical secret material; the source
  FortiOS encryption is opaque so the rendered string will not
  authenticate.
- **auth_port** — `good`.  Default 1812 round-trips.  FortiOS
  non-default `set radius-port 1645` (non-standard) preserves on
  canonical and lands on Aruba's `radius-server host <ip>
  auth-port 1645 key "<secret>"` form.
- **acct_port** — `lossy`.  FortiOS has no separate field;
  canonical defaults to 1813.  Aruba accepts a non-default
  `acct-port` but the FortiGate source can't carry it.
- **server-name** (FortiOS-only) — drops on Aruba render (Aruba
  uses the host address as identity).

Disposition: **lossy**.  Reason: shared-secret format
incompatibility + FortiGate's named edit ID drops on Aruba's
host-keyed form.

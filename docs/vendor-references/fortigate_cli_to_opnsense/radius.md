# RADIUS: FortiGate FortiOS versus OPNsense

## FortiGate FortiOS

Source: [FortiGate / FortiOS 7.4 Administration Guide — `config user
radius`](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/)
Retrieved: 2026-05-01

```
config user radius
    edit "corp-radius"
        set server "10.0.10.50"
        set secret ENC fakeEncodedRadiusSecret==
        set radius-port 1812
        set auth-type auto
        set source-ip 10.0.10.1
    next
end
```

Notes:

- RADIUS servers are an edit-table; the edit name is operator-chosen
  (used inside policy / VPN references).
- `set secret` uses FortiOS's `ENC <opaque-base64>` form.
- `set radius-port` is the auth port.  FortiOS does NOT have a
  separate acct-port field — the accounting port is derived as
  `auth-port + 1` per RFC 2866 default.
- `set auth-type` enumerates pap / chap / mschap / mschap2 / auto.
- FortiOS uses `set radius-port 0` as a placeholder meaning
  "use the default 1812"; the codec normalises to the effective
  default at parse-time.

## OPNsense

Source: [OPNsense Users manual — Authentication
servers](https://docs.opnsense.org/manual/users.html)
Retrieved: 2026-05-01

```xml
<opnsense>
  <system>
    <authserver>
      <type>radius</type>
      <name>corp-radius</name>
      <host>10.0.10.50</host>
      <radius_secret>shared-secret-cleartext</radius_secret>
      <radius_auth_port>1812</radius_auth_port>
      <radius_acct_port>1813</radius_acct_port>
      <radius_protocol>PAP</radius_protocol>
      <radius_timeout>5</radius_timeout>
    </authserver>
  </system>
</opnsense>
```

Notes:

- `<authserver>` with `<type>radius</type>` discriminator (the same
  block also carries LDAP / TACACS-style servers under different
  `<type>`).
- `<radius_secret>` is stored in cleartext in `config.xml` (file
  permissions restrict access).
- BOTH `<radius_auth_port>` and `<radius_acct_port>` are explicit
  fields, unlike FortiGate's single auth-port.
- `<radius_protocol>` enumerates PAP / CHAP / MSCHAPv1 / MSCHAPv2.
- `<radius_timeout>` is per-server.

## Cross-vendor mapping

Canonical fields covered (`CanonicalRADIUSServer`):

```
name, host, key, auth_port, acct_port
```

FortiGate -> OPNsense:

- `name`: **good** — FortiGate edit name (`corp-radius`) ↔
  OPNsense `<name>`.
- `host`: **good** — direct address transfer.
- `key`: **lossy** — FortiOS `ENC <opaque-base64>` is FortiOS-
  internal-key-encrypted; OPNsense expects cleartext.  Cross-vendor
  migration requires re-keying — operators must paste the cleartext
  shared secret into OPNsense after migration.  The codec passes
  the FortiOS-encoded form through verbatim with a vendor tag so
  the loss surfaces in the validation report.
- `auth_port`: **good** — direct integer transfer.  FortiOS
  placeholder `0` is normalised to 1812 at parse-time.
- `acct_port`: **lossy** — FortiOS has no separate field
  (canonical defaults to 1813, which is OPNsense's default too).
  Non-default FortiOS deployments would require operator override
  on render.
- FortiOS `set auth-type` / `set source-ip` / `set timeout` drop on
  canonical (no schema fields); OPNsense `<radius_protocol>` /
  `<radius_timeout>` likewise drop on the inverse direction.

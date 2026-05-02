# RADIUS: OPNsense versus FortiGate FortiOS

Reverse direction.  Forward direction in
`../fortigate_cli_to_opnsense/radius.md`.

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

OPNsense notes:

- `<authserver>` with `<type>radius</type>` discriminator (the same
  block also carries LDAP / TACACS-style servers under different
  `<type>`).
- `<radius_secret>` is stored cleartext in `config.xml`.
- BOTH `<radius_auth_port>` and `<radius_acct_port>` are explicit
  fields.
- `<radius_protocol>` enumerates PAP / CHAP / MSCHAPv1 / MSCHAPv2.

## FortiGate FortiOS

See `../fortigate_cli_to_opnsense/radius.md` for the FortiGate-side
shape.  Key points:

- RADIUS servers are `config user radius` edit-table.
- `set secret ENC <opaque-base64>` is FortiOS proprietary form.
- `set radius-port` is auth port; acct-port is derived as auth+1.

## Cross-vendor mapping (OPNsense -> FortiGate)

- `name`: **good** — OPNsense `<name>` ↔ FortiGate edit name.
- `host`: **good** — direct address transfer.
- `key`: **lossy** — OPNsense cleartext `<radius_secret>` ↔ FortiOS
  `ENC <opaque-base64>` (FortiOS-internal-key-encrypted).  The
  canonical `key` field carries the cleartext from OPNsense; the
  FortiGate render must re-encrypt with the target's internal key,
  which the codec cannot do offline.  Cross-vendor migration
  requires re-keying on the FortiGate target, OR exporting the
  cleartext from OPNsense and pasting it into FortiOS so FortiOS
  re-encrypts on commit.
- `auth_port`: **good** — direct integer transfer.
- `acct_port`: **lossy** — OPNsense has an explicit
  `<radius_acct_port>` field; FortiOS does not.  Non-default OPNsense
  acct-port values drop on FortiGate render (FortiOS computes
  acct = auth + 1 implicitly).
- OPNsense `<radius_protocol>` / `<radius_timeout>` drop on canonical
  (no schema fields).

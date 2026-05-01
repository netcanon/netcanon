# Local users + password hashes: Juniper Junos versus Cisco IOS-XE

Sources:
- Juniper: https://www.juniper.net/documentation//us/en/software/junos/cli-reference/topics/ref/statement/password-edit-system-login.html (retrieved 2026-04-30)
- Juniper KB: https://kb.juniper.net/InfoCenter/index?page=content&id=KB31903 (retrieved 2026-04-30)
- Cisco: https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/security/m1/sec-m1-cr-book/sec-cr-u1.html (retrieved 2026-04-30)
- Cisco (type-9 scrypt): https://community.cisco.com/t5/networking-knowledge-base/understanding-the-differences-between-the-cisco-password-secret/ta-p/4671523 (retrieved 2026-04-30)

Citation ids: `junos-password-cli`, `junos-kb-password-format`, `cisco-username-cli`, `cisco-password-types`.

## Junos form

```
set system login user admin class super-user
set system login user admin authentication encrypted-password "$6$randomSalt$LongSha512CryptHashValue=="
set system login user noc class operator
set system login user noc authentication encrypted-password "$1$mdSalt$shorterMd5Hash"
```

`encrypted-password` accepts hashes prefixed with `$1$` (MD5),
`$5$` (SHA-256), `$6$` (SHA-512; default since Junos 17.2), or
`$sha1$...` (FIPS images only).

`class` is a named role: `super-user`, `operator`, `read-only`,
`unauthorized`, or operator-defined classes.

## Cisco IOS-XE form

```
username admin privilege 15 secret 9 $9$abcDef.../...
username noc privilege 5 secret 5 $1$mdSalt$shorterMd5Hash
```

Hash format markers in the `secret <N>` slot:

- `secret 0 <plain>` — plaintext on input.
- `secret 5 <hash>` — md5_crypt (`$1$...`).
- `secret 8 <hash>` — pbkdf2-sha256 (`$8$...`).
- `secret 9 <hash>` — scrypt (`$9$...`); Cisco-only.

## Mapping notes

- **Hash compatibility matrix:**

  | Hash | Junos `encrypted-password` | Cisco `secret` | Cross-portable |
  |---|---|---|---|
  | `$1$` (MD5) | accepted | secret 5 | Yes |
  | `$5$` (SHA-256) | accepted | rare in Cisco emit | Junos -> Cisco may not parse |
  | `$6$` (SHA-512) | default since 17.2 | not Cisco's default | Junos -> Cisco unsupported in modern IOS-XE |
  | `$8$` (pbkdf2-sha256) | not accepted | secret 8 | Cisco-only |
  | `$9$` (scrypt) | not accepted | secret 9 | Cisco-only |

  Junos -> Cisco migration of recent `$6$` SHA-512 hashes
  typically requires re-keying on the target.
- **Class versus privilege.** Junos's named classes (`super-user`,
  `operator`, `read-only`) don't 1:1 to Cisco's numeric
  `privilege 1-15`.  Operator-curated mapping table required;
  canonical preserves the source string verbatim.
- **Plaintext refusal.** Both vendors accept plaintext on input
  and reformat on save.  The canonical pipeline never ingests
  plaintext; codecs only read the hashed form from
  `running-config`.
- **Login-class richness.** Junos custom `system login class`
  blocks (`permissions`, `allow-commands`, `deny-commands`)
  carry policy detail Cisco doesn't model uniformly.  Canonical
  `CanonicalLocalUser.role` carries the class name only;
  per-class permission detail is parse-and-ignore.

Disposition: **lossy** — only `$1$` MD5 round-trips losslessly;
modern hash formats require re-keying after migration.

# Local users + password hashes: Cisco IOS-XE versus Juniper Junos

How local user accounts are declared and how hashed passwords are
stored on each platform.

Sources:
- Cisco: https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/security/m1/sec-m1-cr-book/sec-cr-u1.html (retrieved 2026-04-30)
- Cisco (type-9 scrypt): https://community.cisco.com/t5/networking-knowledge-base/understanding-the-differences-between-the-cisco-password-secret/ta-p/4671523 (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation//us/en/software/junos/cli-reference/topics/ref/statement/password-edit-system-login.html (retrieved 2026-04-30)
- Juniper KB: https://kb.juniper.net/InfoCenter/index?page=content&id=KB31903 (retrieved 2026-04-30)

Citation ids: `cisco-username-cli`, `cisco-password-types`, `junos-password-cli`, `junos-kb-password-format`.

## Cisco IOS-XE form

```
username admin privilege 15 secret 9 $9$abcDef.../...
username noc privilege 5 secret 5 $1$mdSalt$shorterMd5Hash
username readonly privilege 1 password 0 PlaintextDoNotUse
```

Hash format markers in the `secret <N>` slot:

- `secret 0 <plain>` — plaintext on input; reformatted on save.
- `secret 5 <hash>` — md5_crypt (`$1$...`); deprecated.
- `secret 8 <hash>` — pbkdf2-sha256 (`$8$...`).
- `secret 9 <hash>` — scrypt (`$9$...`); Cisco-only format,
  cannot be ported.
- `password <N> <text>` — type-7 obfuscation (reversible);
  deprecated for credentials.

`privilege <N>` is a numeric 0-15 enable level.

## Junos form

```
set system login user admin class super-user
set system login user admin authentication encrypted-password "$6$randomSalt$LongSha512CryptHashValue=="
set system login user noc class operator
set system login user noc authentication encrypted-password "$1$mdSalt$shorterMd5Hash"
```

Hash formats accepted by `encrypted-password`:

- `$1$...` — md5_crypt
- `$5$...` — sha256_crypt
- `$6$...` — sha512_crypt (default since Junos 17.2)
- `$sha1$...` — FIPS-mode default (older releases)

`class` is a named role: `super-user`, `operator`, `read-only`,
`unauthorized`, or operator-defined.

## Mapping notes

- **Hash compatibility matrix:**

  | Hash | Cisco | Junos | Cross-portable |
  |---|---|---|---|
  | `$1$` (MD5) | secret 5 | encrypted-password | Yes |
  | `$5$` (SHA-256) | not commonly emitted | encrypted-password | Junos -> Cisco may not parse |
  | `$6$` (SHA-512) | not Cisco's default; rare | encrypted-password (default) | Junos -> Cisco unsupported |
  | `$8$` (pbkdf2-sha256) | secret 8 | not accepted | Cisco-only |
  | `$9$` (scrypt) | secret 9 | not accepted | Cisco-only |

  Only `$1$` MD5 is universally cross-portable, and it's deprecated
  on both platforms.  Operator-curated re-keying is required for
  cross-vendor migrations of recent-format hashes.
- **Privilege versus class.** Cisco's numeric `privilege 1-15` and
  Junos's named `class super-user / operator / ...` are not 1:1.
  The codec round-trip preserves whichever the source emitted;
  cross-vendor mapping requires operator judgement (typically
  privilege 15 -> super-user, 1 -> read-only).
- **Plaintext on input.** Both vendors accept plaintext on first
  configuration and reformat to a hash on save.  Canonical model
  refuses to ingest plaintext; codecs only read the hashed form
  from `running-config`.
- **Username-derived salt.** Cisco's secret 9 / 5 hashes are
  salted with the username by default (similar to Arista); Junos's
  `$6$` salts are random.  Even where the hash format crosses,
  authentication can still fail post-migration if the salt
  derivation differs.

Disposition: **lossy** — only the `$1$` MD5 form round-trips
losslessly; operator must re-key after migration for any other
hash type.

# Local user hash formats

How each platform stores hashed local-user passwords in
`running-config`.

Sources:
- Arista: https://www.arista.com/en/um-eos/eos-user-security (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation//us/en/software/junos/cli-reference/topics/ref/statement/password-edit-system-login.html (retrieved 2026-05-01)
- Juniper: https://kb.juniper.net/InfoCenter/index?page=content&id=KB31903 (retrieved 2026-05-01)

Citation ids: `arista-user-security`, `junos-password-cli`, `junos-kb-password-format`.

## Arista EOS form

```
username admin privilege 15 secret sha512 $6$randomSalt$LongSha512CryptHashValue==
username readonly secret 5 $1$mdSalt$shorterMd5Hash
```

Two literal hash schemes:

- `secret 5 <hash>` — md5_crypt (legacy; `$1$<salt>$<hash>`).
- `secret sha512 <hash>` — SHA-512-crypt (`$6$<salt>$<hash>`).

EOS salts the password with the username by default when generating
new hashes; copy-paste between devices works only when the username
matches.

## Junos form

```
set system login user admin class super-user
set system login user admin authentication encrypted-password "$6$randomSalt$LongSha512CryptHashValue=="
```

`encrypted-password` accepts hashes prefixed with `$1$` (MD5),
`$5$` (SHA-256-crypt), or `$6$` (SHA-512-crypt).  Junos OS Release
17.2 and later default new hashes to `$6$` SHA-512.  FIPS images
default to SHA-1; this is the exception, not the rule.

## Mapping notes

- Both vendors use the same Linux-style `crypt()` family
  (`$1$/$5$/$6$`), so the **hash bytes themselves round-trip
  losslessly** — `secret sha512 $6$...$...` on Arista and
  `encrypted-password "$6$...$..."` on Junos consume identical hash
  formats.
- Authentication MAY still fail after migration if the salt was
  derived from the username (Arista default) and the username
  changes.  The hash format is portable; the salting policy is not.
- Canonical `CanonicalLocalUser.hashed_password` is opaque — codecs
  pass the hash through verbatim with no parsing or re-hashing.
- `secret 5` (MD5) is accepted by both vendors but is deprecated;
  cross-vendor migration emits the original format unchanged.

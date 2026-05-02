# Local users (classes, hashed passwords, SSH keys)

How local-user accounts, classes / privilege levels, and stored
password hashes are configured on each platform.

Sources:
- Juniper: https://www.juniper.net/documentation//us/en/software/junos/cli-reference/topics/ref/statement/password-edit-system-login.html (retrieved 2026-05-01)
- Juniper: https://kb.juniper.net/InfoCenter/index?page=content&id=KB31903 (retrieved 2026-05-01)
- Arista: https://www.arista.com/en/um-eos/eos-user-security (retrieved 2026-05-01)

Citation ids: `junos-password-cli`, `junos-kb-password-format`,
`arista-user-security`.

## Junos form

```
set system login user alice class super-user
set system login user alice authentication encrypted-password "$6$rounds=656000$abc...$xyz..."

set system login user bob class operator
set system login user bob authentication encrypted-password "$5$abc$xyz..."

set system login user carol class read-only

set system login user dave class super-user
set system login user dave authentication ssh-rsa "ssh-rsa AAAAB3NzaC1yc2E..."
```

Junos accepts password hashes in `$1$` (MD5 legacy), `$5$`
(SHA-256), and `$6$` (SHA-512 default since Junos 17.2 per KB31903)
formats — the standard Linux crypt() hash family.  SSH-RSA / DSA /
ED25519 public keys are configured under
`set system login user X authentication ssh-rsa "<key>"`.

Built-in classes: `super-user`, `operator`, `read-only`, `unauthorized`.
Operator-defined classes can also be created.

## Arista form

```
username alice privilege 15 secret sha512 $6$rounds=656000$abc...$xyz...
username bob privilege 1 secret sha512 $6$xyz...
username carol privilege 1 nopassword

username dave privilege 15 sshkey ssh-rsa AAAAB3NzaC1yc2E...
```

Arista accepts password hashes via `secret sha512 <hash>` (SHA-512
crypt form, same `$6$` family as Junos).  Older Arista images also
accepted MD5 (`secret 5 <hash>`) but the modern preferred form is
sha512.

Privilege levels: integer 0-15 (1 = read-only, 15 = enable).  No
named classes; the privilege integer is the discriminator.

## Mapping notes

- **Class -> privilege mapping.**
  - `super-user` -> Arista `privilege 15` (full enable).
  - `operator` -> Arista `privilege 7` (operator-typical).
  - `read-only` -> Arista `privilege 1` (basic read).
  - `unauthorized` -> Arista `privilege 0` (rare; closest match).
  - Operator-defined Junos classes collapse to `privilege 7` with
    a comment.
- **Hash format compatibility.**
  - **`$6$` (SHA-512).** Junos -> Arista lossless
    (`secret sha512 $6$...`).  Both use the same Linux crypt()
    encoding; bytes round-trip exactly.
  - **`$5$` (SHA-256).** Junos accepts; Arista's `secret sha512`
    keyword is the modern path — older `secret 5` accepted SHA-256
    but newer images may not.  Codec policy: re-encode as `$6$`
    is impossible (would require the cleartext); render emits the
    `$5$` hash on Arista with a comment that SHA-256 may need a
    re-key on newer EOS images.  Lossy (image-dependent).
  - **`$1$` (MD5).** Both accepted historically; deprecated on
    both.  Render with comment.
- **SSH public-key auth.** Junos's `authentication ssh-rsa "<key>"`
  has no canonical fit in the hash-shaped
  `CanonicalLocalUser.hashed_password` field — parse-and-ignore
  today.  Arista does support `username X sshkey ssh-rsa <key>`,
  so the round-trip is functionally possible if the canonical
  model gains a separate `ssh_keys` field (deferred — schema gap).
  Lossy by deferral.
- **Re-keying caveat.** Even on `$6$` lossless transit, Arista's
  default salt convention may differ from Junos's; if the original
  Junos `$6$` hash was computed with a username-based salt (the
  cleartext + salt produces the digest), changing the user's name
  on the target invalidates the hash.  Verbatim username preserves
  authentication.

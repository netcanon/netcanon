# Local users + admin profiles: Arista EOS versus FortiGate FortiOS

## Arista EOS

Source: [Arista EOS User Manual — User Security (4.35.2F)](https://www.arista.com/en/um-eos/eos-user-security)
Retrieved: 2026-05-01

```
username admin privilege 15 role network-admin nopassword
username operator privilege 15 role network-admin secret sha512 \
        $6$fakeSalt$fakeHashSha512AbcDefGhiJklMnoPqrStuVwxYz...
username readonly privilege 1 role network-operator secret 5 \
        $1$fakeSalt$fakeMd5Hash01234
```

Notable Arista specifics:

- **Numeric privilege levels** (1-15) inherited from Cisco IOS.
  Privilege 15 = enable-equivalent admin; lower levels are
  configurable via `aaa authorization commands` (rarely used in DC
  practice).
- **Role-based access** layered on top via `role <name>` (e.g.
  `network-admin`, `network-operator`); roles are resolved against
  on-box `aaa authorization` definitions.
- **Hash families**:
  - `secret 5 $1$<salt>$<hash>` — MD5-crypt (Cisco type-5 lineage).
  - `secret sha512 $6$<salt>$<hash>` — SHA-512-crypt (modern EOS
    default; matches Linux `crypt(3)` family with `$6$` prefix).
  - `secret 7 <reversible-hex>` — Cisco type-7 reversible (legacy).
  - `secret 8 $8$<...>` — PBKDF2.
  - `secret 9 $9$<...>` — scrypt.
  - `nopassword` — explicit no-password form.

## FortiGate FortiOS CLI

Source: [Fortinet Document Library — Admin Profile (FortiOS 7.4 Admin Guide)](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/)
Retrieved: 2026-05-01

```
config system admin
    edit "admin"
        set accprofile "super_admin"
        set password ENC fakeAdminHashEEEEEEEEEEEEEE==
        set trusthost1 10.0.0.0 255.255.0.0
    next
    edit "netops"
        set accprofile "prof_admin"
        set password ENC fakeNetopsHashFFFFFFFFFFFFFF==
    next
    edit "auditor"
        set accprofile "super_admin_readonly"
        set password ENC fakeAuditorHashGGGGGGGGGGGGGG==
    next
end
```

Notable FortiOS specifics:

- **Named accprofile strings** (not numeric levels): `super_admin`
  (full read/write), `super_admin_readonly` (read-only),
  `prof_admin` (configurable), and operator-defined custom profiles
  via `config system accprofile`.
- **Hash format is `ENC <opaque-base64>`** — FortiOS-internal
  encryption keyed to the device's master key.  Not interoperable
  with any other vendor's hash family.
- **`set trusthost1` ... `set trusthost10`** — FortiOS-specific IP
  source restrictions on admin sessions.  Not modelled in canonical.

## Cross-vendor mapping (Arista -> FortiGate)

Canonical surface:

```
local_users[].name: str
local_users[].privilege_level: int
local_users[].hashed_password: str   (opaque, vendor-tagged)
local_users[].role: str
```

- **name** — `good`.  Username string round-trips directly.
- **privilege_level / role** — `lossy`.  Arista's numeric privilege
  (1-15) plus role string flattens onto FortiGate's named accprofile
  strings via codec policy: privilege >= 15 -> `super_admin`,
  privilege 1 -> `prof_admin`, role hint preserved as-is in the
  canonical `role` field.  The reverse direction (FortiGate ->
  Arista) requires the inverse heuristic (`super_admin` -> 15;
  others -> 1).  Granular Cisco-style privilege levels (2-14) are
  flattened.
- **hashed_password** — `lossy`.  Hash formats are NOT cross-
  compatible:
  - Arista `$6$<salt>$<sha512crypt>` is not parseable by FortiOS.
  - Arista `$1$<salt>$<md5crypt>` is not parseable by FortiOS.
  - Arista `$9$<scrypt>` (used internally for service-encryption-key
    wrapping) is Arista-private.
  - FortiOS `ENC <opaque-base64>` requires the FortiGate device's
    master key.

  Cross-vendor migration of admin accounts therefore requires
  **re-setting passwords on the target device**.  Both codecs
  preserve hashes verbatim with vendor tags (`arista_eos:` /
  `fortios:`) so the loss surfaces in the validation report.  Modern
  EOS defaults to `secret sha512` so this bites every migration.
- **trusthost / IP-source-restriction** — `unsupported`.  FortiOS
  `set trusthost1` is FortiGate-specific and has no canonical
  representation; on the FortiGate render side the field is empty
  for cross-vendor sources.  Operators wanting to emulate the
  network-restriction must use a separate firewall policy.

Disposition summary: **good** for username.  **Lossy** for
privilege/role mapping (flattening), hashed_password (re-keying
required, hash families incompatible).  **Unsupported** for
trusthost (FortiGate-specific extension).

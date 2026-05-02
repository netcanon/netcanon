# Local users + admin profiles: FortiGate FortiOS versus Arista EOS

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
        set trusthost1 10.50.0.0 255.255.255.0
    next
    edit "auditor"
        set accprofile "super_admin_readonly"
        set password ENC fakeAuditorHashGGGGGGGGGGGGGG==
    next
end
```

Notable FortiOS specifics:

- **Named accprofile strings** (not numeric levels):
  - `super_admin` — full read/write.
  - `super_admin_readonly` — read-only.
  - `prof_admin` — configurable; permissions defined by `config
    system accprofile` for that role.
  - Operator-defined custom profiles via `config system
    accprofile`.
- **Hash format is `ENC <opaque-base64>`** — FortiOS-internal
  encryption keyed to the device's master key.  Not interoperable
  with other vendors' hash families.
- **`set trusthost1` ... `set trusthost10`** — FortiOS-specific IP
  source-restriction on admin sessions (subnet form).  Not
  modelled in canonical.

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
- **Role-based access** layered via `role <name>` (e.g.
  `network-admin`, `network-operator`).
- **Hash families**: `secret 5 $1$<...>` (md5_crypt), `secret
  sha512 $6$<...>` (sha512_crypt — modern default), `secret 7
  <hex>` (Cisco type-7 reversible), `secret 8 $8$<...>` (PBKDF2),
  `secret 9 $9$<...>` (scrypt).
- **`nopassword`** explicit form.

## Cross-vendor mapping (FortiGate -> Arista)

Canonical surface:

```
local_users[].name: str
local_users[].privilege_level: int
local_users[].hashed_password: str   (opaque, vendor-tagged)
local_users[].role: str
```

- **name** — `good`.  Username string round-trips directly.
- **privilege_level / role** — `lossy`.  FortiGate's named
  accprofile strings flatten onto Arista's numeric privilege +
  role string via codec policy:
  - `super_admin` -> privilege 15, role `network-admin`.
  - `super_admin_readonly` -> privilege 15, role
    `network-operator` (or operator-curated role).
  - `prof_admin` and custom profiles -> privilege 1, role
    preserved as-is in the canonical `role` field.

  Granular per-profile detail (FortiGate accprofile permission
  matrices) is lost — Arista has no equivalent of FortiGate's
  per-profile feature-permission grid.  Operators wanting
  Arista's role-based control must define matching `role`
  records via `aaa authorization` on the target.
- **hashed_password** — `lossy`.  FortiOS `ENC <opaque-base64>`
  requires the FortiGate device's master key for decryption.
  Arista accepts `$1$` (md5_crypt) / `$5$` (sha256_crypt) /
  `$6$` (sha512_crypt) / `$8$` (PBKDF2) / `$9$` (scrypt) /
  type-7 reversible — none of which match FortiOS `ENC`.  Cross-
  vendor migration requires re-setting passwords on the target.
  Both codecs preserve source-form hashes verbatim with vendor
  tags (`fortios:` / `arista_eos:`) so the loss surfaces in the
  validation report.
- **trusthost / IP-source-restriction** — `not_applicable`.
  FortiOS `set trusthost1` is FortiGate-specific and has no
  canonical representation; Arista source has no equivalent
  field.  Cross-vendor render emits no source-restriction; the
  operator must reconstruct via `aaa authentication policy` or
  control-plane ACLs on Arista.

Disposition summary: **good** for username.  **Lossy** for
privilege/role mapping (flattening), hashed_password (re-keying
required, hash families incompatible).  **Not_applicable** for
trusthost (FortiGate-specific extension; Arista source structurally
absent).

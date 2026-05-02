# Local users + admin profiles: FortiGate FortiOS versus Juniper Junos

## FortiGate FortiOS

Source: [FortiGate / FortiOS Administration Guide — System administrators](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/).
Retrieved: 2026-05-01.

FortiOS models admin accounts under `config system admin` keyed by
the username:

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

- **Account profiles** (`accprofile`): `super_admin`, `prof_admin`,
  `super_admin_readonly`, plus operator-defined custom profiles
  declared under `config system accprofile`.
- **Hash form**: `password ENC <opaque-base64>` — FortiOS
  proprietary encryption; not cross-vendor portable.
- **Trust hosts**: `set trusthost1` ... `set trusthost10` (per-source
  ACL).  Not modelled canonically.

The FortiGate codec maps `accprofile`:

- `super_admin` -> privilege 15 (Cisco-style) / `super-user` (Junos).
- Other profiles -> privilege 1 with the profile name preserved in
  canonical `role`.

## Juniper Junos

Source: [Junos `password` (Login) CLI reference](https://www.juniper.net/documentation//us/en/software/junos/cli-reference/topics/ref/statement/password-edit-system-login.html).
Source: [Juniper KB31903 — password format SHA512 default in 17.2+](https://kb.juniper.net/InfoCenter/index?page=content&id=KB31903).
Retrieved: 2026-05-01.

Junos models login users under `set system login user <name> ...`:

```
set system login user admin uid 2000
set system login user admin class super-user
set system login user admin authentication encrypted-password "$6$fakeAdmin$fakeAdminHash01234567890123"
set system login user operator uid 2001
set system login user operator class operator
set system login user operator authentication encrypted-password "$6$fakeOp$fakeOpHash9876543210"
set system login user readonly uid 2002
set system login user readonly class read-only
set system login user readonly authentication ssh-rsa "ssh-rsa AAAAB3...readonly@host"
```

Notable Junos specifics:

- **Class**: named privilege class — `super-user` (full), `operator`
  (most operational commands), `read-only`, `unauthorized`, plus
  operator-defined classes declared under `set system login class
  <name>`.
- **Hash forms**: Junos accepts `$1$` (MD5), `$5$` (SHA-256), `$6$`
  (SHA-512, default since 17.2 per KB31903).
- **SSH-key authentication**: `set system login user X authentication
  ssh-rsa "..."` — common in DC operator workflows.  Not modelled
  canonically.
- **No password aging in canonical** (vendor-specific).

## Cross-vendor mapping (FortiGate -> Junos)

Canonical surface (`CanonicalLocalUser`):

```
class CanonicalLocalUser(BaseModel):
    name: str
    privilege_level: int = 1
    hashed_password: str = ""
    role: str = ""
```

- **name** — `good`.  Direct map.
- **privilege_level** — `lossy`.  FortiGate accprofile collapses to a
  numeric privilege via the FortiGate codec mapping (`super_admin` =
  15; others = 1).  Junos render then maps the numeric back to a
  named class (15 -> `super-user`; 1 -> `operator`).
- **hashed_password** — `lossy`.  FortiOS `ENC <opaque>` is not a
  Junos-accepted format.  Cross-vendor migration requires re-setting
  passwords.  Both codecs preserve hashes verbatim with vendor tags.
- **role** — `lossy`.  FortiGate accprofile string preserved in
  canonical for intra-vendor round-trip but Junos render uses the
  numeric privilege to derive the class name; the original
  accprofile string drops.

## Cross-vendor mapping (Junos -> FortiGate)

Reverse direction (see also `../juniper_junos_to_fortigate_cli/local_users.md`):

- **privilege_level / role** — `lossy`.  Junos class string preserved
  in canonical `role`; FortiGate render maps `super-user` ->
  `super_admin`, others -> `prof_admin`.
- **hashed_password** — `lossy`.  Junos `$1$` / `$5$` / `$6$` are
  not FortiOS-accepted formats.
- **SSH-key authentication** — `lossy` (canonical schema gap).
  Junos's `ssh-rsa` keys drop on FortiGate render.

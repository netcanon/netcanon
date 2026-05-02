# Local users + admin profiles: Juniper Junos versus FortiGate FortiOS

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

- **Class**: named privilege class — `super-user` (full),
  `operator`, `read-only`, `unauthorized`, plus operator-defined
  classes under `set system login class <name>`.
- **Hash forms**: `$1$` (MD5), `$5$` (SHA-256), `$6$` (SHA-512,
  default since 17.2 per KB31903).
- **SSH-key authentication**: `set system login user X
  authentication ssh-rsa "..."` — common in DC operator workflows.
  Not modelled canonically.
- **UID** is per-user numeric (Unix-style); not modelled canonically.

## FortiGate FortiOS

Source: [FortiGate / FortiOS Administration Guide — System administrators](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/).
Retrieved: 2026-05-01.

FortiGate models admin accounts under `config system admin`:

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
end
```

- **Accprofile**: `super_admin`, `prof_admin`,
  `super_admin_readonly`, plus operator-defined.
- **Hash form**: `ENC <opaque-base64>` — FortiOS proprietary.

## Cross-vendor mapping (Junos -> FortiGate)

Canonical surface (`CanonicalLocalUser`).

- **name** — `good`.  Direct map.
- **privilege_level** — `lossy`.  Junos class -> canonical numeric
  via codec mapping (`super-user` -> 15, others -> 1); FortiGate
  render maps numeric back to accprofile (`super_admin` /
  `prof_admin`).
- **hashed_password** — `lossy`.  Junos `$1$` / `$5$` / `$6$` are
  not FortiOS-accepted.  Cross-vendor migration requires
  re-setting passwords.
- **role** — `lossy`.  Junos class string preserved in canonical for
  intra-vendor round-trip; FortiGate render uses numeric privilege
  to derive accprofile, so the original Junos class string drops.
- **SSH-key authentication** — `lossy` (canonical schema gap).
  Junos `ssh-rsa` keys drop on FortiGate render.

## Cross-vendor mapping (FortiGate -> Junos)

Reverse direction (see also `../fortigate_cli_to_juniper_junos/local_users.md`):

- **privilege_level / role** — `lossy` for the symmetric reason
  (FortiGate accprofile -> canonical numeric -> Junos class).
- **hashed_password** — `lossy`.  FortiOS `ENC <opaque>` is not
  Junos-accepted.

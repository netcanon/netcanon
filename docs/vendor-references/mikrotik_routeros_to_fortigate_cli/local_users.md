# Local users and admin profiles: MikroTik RouterOS versus FortiGate FortiOS

## MikroTik RouterOS

Sources:
- [User — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/8978504/User) — `/user`, `/user group`, `/user aaa`.

Retrieved: 2026-04-30

```
/user
add group=full name=admin
add group=write name=operator
add group=read name=auditor
```

Notable RouterOS specifics:

- Local users live on `/user` records.  `name=` is the username; `group=` references a built-in or custom user-group.
- Built-in groups: `full` (all permissions), `write` (most read+write but not user-management), `read` (read-only).
- Custom groups can be defined on `/user group / add name=... policy=read,write,reboot,...`.
- **RouterOS does not surface its hashed password material in `/export`** — passwords are stored on the box but the `/export` output never includes them.  The MikroTik codec therefore parses no `hashed_password` value for any user; canonical `hashed_password` is always empty for RouterOS sources.
- Per-user IP-restriction is `address=<CIDR>` on the `/user` record.

## FortiGate FortiOS CLI

Sources:
- [FortiGate / FortiOS 7.4 Administration Guide — Administrator accounts](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/) — `config system admin`.

Retrieved: 2026-04-30

```
config system admin
    edit "admin"
        set accprofile "super_admin"
        set password ENC fakeAdminHash==
    next
    edit "operator"
        set accprofile "prof_admin"
        set password ENC fakeOperatorHash==
    next
end
```

FortiOS uses named admin profiles (`super_admin`, `prof_admin`, `super_admin_readonly`, `no_access`, custom) and `ENC <opaque-base64>` password format.  Plaintext input is accepted but re-encrypted on storage.

`set trusthost1 NETWORK MASK` (and trusthost2..10) restricts admin login by source-IP subnet — FortiGate-specific.

## Cross-vendor mapping (RouterOS → FortiGate)

Canonical surface (per-user):

```
CanonicalLocalUser.name: str
CanonicalLocalUser.privilege_level: int
CanonicalLocalUser.hashed_password: str
CanonicalLocalUser.role: str
```

- **name** — `good`.  RouterOS `add name=admin` parses to canonical `name="admin"`; FortiOS render emits `edit "admin"`.
- **privilege_level** — `lossy`.  RouterOS group names map to canonical privilege via the convention `full -> 15`, `write -> 7`, `read -> 1`.  FortiOS render then maps privilege >= 15 to `set accprofile "super_admin"` and lower to `set accprofile "prof_admin"`, which collapses the RouterOS `write` and `read` distinction.
- **hashed_password** — `lossy`.  RouterOS `/export` does NOT include hashed password material — the MikroTik codec parses no password for any user, so canonical `hashed_password` is empty.  FortiOS render therefore emits no `set password ENC ...` line for migrated users; the FortiGate target will reject the admin account at first login.  Operators MUST set passwords interactively on the FortiGate target after migration.
- **role** — `lossy`.  RouterOS `group=` populates canonical `role` (`full` / `write` / `read` / custom-name).  FortiOS render maps the role string to the closest accprofile (`full -> super_admin`, `write -> prof_admin`, `read -> prof_admin` with note).  Custom RouterOS group names lose their permission semantics on the FortiGate side without operator-curated `config system accprofile` re-creation.
- **per-user IP restriction** — RouterOS `address=<CIDR>` and FortiOS `set trusthost1 NETWORK MASK` are conceptually similar but neither side currently parses into canonical, so the restriction drops on render.

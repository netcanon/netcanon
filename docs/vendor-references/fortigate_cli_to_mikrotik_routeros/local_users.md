# Local users and admin profiles: FortiGate FortiOS versus MikroTik RouterOS

## FortiGate FortiOS CLI

Sources:
- [FortiGate / FortiOS 7.4 Administration Guide — Administrator accounts](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/) — `config system admin`.

Retrieved: 2026-04-30

```
config system admin
    edit "admin"
        set accprofile "super_admin"
        set password ENC fakeAdminHashEEEE==
        set trusthost1 10.0.0.0 255.255.0.0
    next
    edit "netops"
        set accprofile "prof_admin"
        set password ENC fakeNetopsHashFFFF==
        set trusthost1 10.50.0.0 255.255.255.0
    next
    edit "auditor"
        set accprofile "super_admin_readonly"
        set password ENC fakeAuditorHashGGGG==
    next
end
```

Notable FortiOS specifics:

- Admin accounts live on `config system admin / edit "<username>"`.
- `set accprofile "<name>"` references a named profile from `config system accprofile` — the canonical built-in profiles include `super_admin` (root-level), `prof_admin` (administrator with default scope), `super_admin_readonly` (read-only root), and `no_access` (lockout).  Custom profiles can be defined.
- `set password ENC <opaque-base64>` is the FortiOS internal-key-encrypted password format.  Plaintext `set password "<text>"` is also accepted on input but the box re-encrypts on storage.
- `set trusthost1 NETWORK MASK` (and `trusthost2`, ..., `trusthost10`) restricts admin login by source-IP subnet — FortiGate-specific, no canonical model.
- 2FA, RADIUS-bound admin auth, and PKI client-cert auth are FortiOS-specific extensions outside canonical scope.

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
- Built-in groups: `full` (all permissions), `write` (most read+write but not user-management), `read` (read-only).  Custom groups can be defined on `/user group / add name=... policy=read,write,reboot,...`.
- **RouterOS does not surface its hashed password material in `/export`** — passwords are stored on the box but the `/export` output never includes them.  Operators must `/user set <name> password=<plaintext>` interactively after migration.  This is a deliberate RouterOS design choice and applies in either direction.
- Per-user IP-restriction is `address=<CIDR>` on the `/user` record — analogous to FortiOS `trusthost1` but with a single CIDR, not a netmask form.

## Cross-vendor mapping (FortiGate → RouterOS)

Canonical surface (per-user):

```
CanonicalLocalUser.name: str
CanonicalLocalUser.privilege_level: int    # vendor-specific; 15 = admin on Cisco
CanonicalLocalUser.hashed_password: str    # opaque hash, never plaintext
CanonicalLocalUser.role: str               # "manager"/"operator"/"admin"/...
```

- **name** — `good`.  FortiOS `edit "netops"` parses to canonical `name="netops"`; RouterOS render emits `add name=netops`.
- **privilege_level** — `lossy`.  FortiOS does not use numeric privilege levels; the FortiGate codec normalises `super_admin` accprofile to canonical privilege 15 and other profiles to privilege 1, with the profile name preserved in `role`.  RouterOS render then maps privilege >= 15 to `group=full` and lower to `group=read`, which loses the `prof_admin` / `super_admin_readonly` distinction in the middle.
- **hashed_password** — `lossy`.  Triple loss:
  - FortiOS `ENC <opaque-base64>` is FortiOS-internal-key encrypted; not portable.
  - RouterOS `/export` does not surface password material at all, so the rendered `/user add` line carries no password attribute.  Operators MUST set passwords interactively on the target.
  - Both codecs preserve the source hash verbatim with vendor tags so the loss surfaces in the validation report, but the rendered RouterOS config will not include the FortiOS hash.
- **role** — `lossy`.  FortiOS `set accprofile "<profile>"` populates canonical `role` (e.g. `super_admin`, `prof_admin`, `super_admin_readonly`, custom).  RouterOS has no first-class profile concept — the closest analogue is `/user group` with custom policy bits.  Default mapping collapses to one of the three built-in groups (`full` / `write` / `read`).  Custom FortiOS accprofile names lose their permission semantics on RouterOS without operator-curated `/user group` re-creation.
- **trusthost** — FortiOS-specific source-IP restriction has no first-class canonical field; RouterOS supports `address=<CIDR>` on `/user` records but the FortiGate-source `trusthost1 NETWORK MASK` form does not currently parse into canonical, so it drops on render.

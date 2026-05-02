# Local users: OPNsense versus MikroTik RouterOS

## OPNsense

Source: [OPNsense Users manual](https://docs.opnsense.org/manual/users.html)

Retrieved: 2026-04-30

```xml
<system>
  <group>
    <name>admins</name>
    <description>System Administrators</description>
    <scope>system</scope>
    <gid>1999</gid>
    <member>0</member>
    <member>2000</member>
    <priv>page-all</priv>
  </group>
  <user>
    <name>netops</name>
    <descr>Network Operations</descr>
    <scope>user</scope>
    <groupname>admins</groupname>
    <password>$2b$10$fakeAJhashNetopsAccountPlaceholderObviouslySynthetic000</password>
    <uid>2000</uid>
  </user>
</system>
```

OPNsense stores user accounts inside ``<system>/<user>`` blocks.
``<groupname>`` references a ``<system>/<group>`` block (with GID +
member UID list + privilege strings).

Password material is **bcrypt** (FreeBSD ``crypt(3)``-compatible:
``$2a$`` / ``$2b$`` / ``$2y$`` accepted interchangeably).  This is
incompatible with most other vendors' hash forms.

## MikroTik RouterOS

Source: [User — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/8978504/User)

Retrieved: 2026-04-30

```
/user
add group=full name=admin
add group=write name=operator
add group=read name=auditor
```

RouterOS models local users with named groups.  Built-in groups are
``full`` (admin), ``write`` (limited admin), and ``read`` (read-only);
operators can add custom groups under ``/user group``.

**Critical note**: RouterOS uses a vendor-private password hash
format that is NOT exposed in ``/export``.  ``/user export`` emits
``add group=full name=admin`` with NO password attribute; passwords
live in the binary ``user.dat`` file.  This means RouterOS rejects
foreign hash material on import too — there is no documented format
for cross-vendor password injection.  Operators MUST set passwords
manually on the RouterOS target post-migration regardless of source
hash format.

## Cross-vendor mapping

Canonical surface:

```
CanonicalLocalUser(name, privilege_level, hashed_password, role)
```

### name

Round-trips cleanly.

### privilege_level / role

OPNsense's binary admin / non-admin model (group membership in
``admins`` versus ``users``) collapses to RouterOS's named groups:

- OPNsense ``<groupname>admins</groupname>`` → RouterOS ``group=full``
  (privilege 15 equivalent)
- OPNsense ``<groupname>users</groupname>`` → RouterOS ``group=read``
  (privilege 1 equivalent)
- OPNsense custom groups → RouterOS ``group=read`` with banner;
  operator must define matching RouterOS group policies via
  ``/user group`` post-migration.

OPNsense's free-form ``<priv>`` strings (e.g. ``page-all``) have no
canonical model and drop on render.

### hashed_password

OPNsense bcrypt hash material arrives in the canonical
``hashed_password`` field — but RouterOS's password format is
vendor-private and undocumented for cross-vendor injection.  The
canonical hash CANNOT be transplanted onto RouterOS.  RouterOS
render emits the user account (``/user add group=... name=...``)
WITHOUT a password attribute; the operator MUST set passwords
manually on the target.

This is symmetric with the inverse direction (RouterOS ``/export``
also carries no password material) — but the failure mode is
different: this direction has hash material that cannot be used,
the inverse has no hash material at all.

### Disposition

| Field | Disposition |
|---|---|
| `local_users[].name` | good |
| `local_users[].privilege_level` | lossy (OPNsense binary admin/users → RouterOS named groups) |
| `local_users[].role` | lossy (OPNsense `<priv>` strings have no canonical model) |
| `local_users[].hashed_password` | unsupported (RouterOS does not accept foreign hash material) |

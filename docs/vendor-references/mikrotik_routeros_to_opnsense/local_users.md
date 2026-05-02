# Local users: MikroTik RouterOS versus OPNsense

## MikroTik RouterOS

Source: [User — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/8978504/User)

Retrieved: 2026-04-30

```
/user
add group=full name=admin
add group=write name=operator
add group=read name=auditor

/user group
add name=custom-noc policy=read,write,sniff,test,!sensitive
```

RouterOS models local users with named groups.  Built-in groups are
``full`` (admin), ``write`` (limited admin), and ``read`` (read-only);
operators can add custom groups under ``/user group`` with explicit
policy lists.

**Critical gap**: RouterOS ``/export`` does NOT include hashed
passwords.  ``/user export`` emits the ``add group=full name=admin``
line WITHOUT a password attribute.  Passwords are stored encrypted
inside ``user.dat`` (a vendor-private binary file under ``/rw/disk/
nova/store/`` or RAM-only on devices without flash) which is not
serialised to text.  Cross-vendor migration of user accounts cannot
preserve password material — operators MUST re-set passwords on the
target post-migration.

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
Each user has a ``<groupname>`` reference into a ``<system>/<group>``
block (groups carry GID + member UID list + privilege strings).

Password material is **bcrypt** (FreeBSD ``crypt(3)``-compatible:
``$2a$`` / ``$2b$`` / ``$2y$`` prefixes accepted interchangeably).
This is incompatible with most other vendors' hash forms — Cisco
type-9 / type-8 / type-5, Aruba SHA-1 hex / plaintext, and Junos
``$1$`` MD5-crypt all fail OPNsense's bcrypt-only validator on
apply.

## Cross-vendor mapping

Canonical surface:

```
CanonicalLocalUser(name, privilege_level, hashed_password, role)
```

### name

Round-trips cleanly.  Username is opaque text on both vendors.

### privilege_level / role

RouterOS named groups (``full`` / ``write`` / ``read`` / custom)
collapse to OPNsense's binary admin / non-admin model:

- RouterOS ``full`` → OPNsense ``<groupname>admins</groupname>``
  (privilege 15 equivalent)
- RouterOS ``write`` → OPNsense ``<groupname>admins</groupname>``
  with banner (closest analogue; OPNsense has no "limited admin")
- RouterOS ``read`` → OPNsense ``<groupname>users</groupname>``
  (privilege 1 equivalent)
- Custom RouterOS groups → OPNsense ``<groupname>users</groupname>``
  with banner; operator must define matching OPNsense privilege
  strings under ``<system>/<group>/<priv>`` post-migration.

### hashed_password

RouterOS ``/export`` does not surface hashed passwords (see above).
``CanonicalLocalUser.hashed_password`` arrives EMPTY after a
RouterOS parse.  OPNsense render therefore emits the user record
without a ``<password>`` element — OPNsense will refuse login until
the operator sets a password manually post-migration.

This is the structural blocker on this direction: even though
OPNsense bcrypt is well-documented, the source side carries no
password material to convert.

### Disposition

| Field | Disposition |
|---|---|
| `local_users[].name` | good |
| `local_users[].privilege_level` | lossy (RouterOS named groups → OPNsense binary admin/user) |
| `local_users[].role` | lossy (custom groups collapse with banner) |
| `local_users[].hashed_password` | unsupported (RouterOS source carries no password material) |

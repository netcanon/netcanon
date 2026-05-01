# Local users + hash formats: Cisco IOS-XE versus OPNsense

## Cisco IOS-XE

Source: [Cisco IOS XE Security Configuration Guide — User Security](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/security/m1/sec-m1-cr-book/sec-m1-cr-book_chapter_010.html)

```
username admin privilege 15 secret 9 $9$AbCdEfGhIjKlM$nOpQrStUvWxYz
username operator privilege 5 secret 5 $1$abc$def123ghijkl
username monitor privilege 1 secret 8 $8$AbCdEfGhIjKlM$nOpQ
```

Cisco's ``privilege <N>`` is a numeric level (1-15) with 15 = full
admin.  Hash type prefixes are:

- type 5: ``$1$<salt>$<hash>`` — legacy MD5-crypt
- type 8: ``$4$...`` — PBKDF2-SHA256
- type 9: ``$9$...`` — scrypt (Cisco-specific salt+params encoding)

Type 9 is the modern recommendation; type 5 is the only cross-vendor
interoperable form (Linux ``crypt(3)`` ``$1$``).

## OPNsense

Source: [OPNsense Users manual](https://docs.opnsense.org/manual/users.html)
Retrieved: 2026-04-30

OPNsense user records live as ``<user>`` siblings inside
``<system>``:

```xml
<opnsense>
  <system>
    <user>
      <name>admin</name>
      <descr>System Administrator</descr>
      <password>$2y$10$oNopK1dE8FzGhIjKlMnOpQrStUvWxYzAbCdEfGhIjKlMnOpQrSt</password>
      <uid>0</uid>
      <groupname>admins</groupname>
      <scope>system</scope>
    </user>
    <user>
      <name>operator</name>
      <password>$2y$10$AnOtHeRbCrYpThAsHvAlUeFoRtHiSuSeRaCcOuNtExAmPlEaB</password>
      <uid>2000</uid>
      <groupname>operators</groupname>
      <scope>user</scope>
    </user>
  </system>
</opnsense>
```

Notable shape:

- ``<password>`` carries a bcrypt hash (``$2y$<cost>$<salt><hash>``)
  by default (the documented "Blowfish" option).  An optional
  ``<system><sshd><require_sha512>`` toggle forces SHA-512 hashing
  (``$6$``) for FIPS-compliance environments.
- Privilege is GROUP-MEMBERSHIP-DRIVEN, not a numeric level.  Group
  ``admins`` (gid 1999 historically) confers full admin access;
  every other group / no-group is operator-equivalent.
- ``<scope>`` distinguishes ``system`` (built-in accounts like
  ``root``) from ``user`` (operator-created); both can be in any
  group.

The OPNsense codec parses these into ``CanonicalLocalUser`` records
with ``hashed_password`` tagged ``bcrypt:<hash>`` so target renderers
can route the hash format correctly.

## Cross-vendor mapping

Canonical fields (see ``CanonicalLocalUser``):

```
name: str
privilege_level: int    # 1-15 Cisco scale
hashed_password: str
role: str
```

Cisco -> OPNsense:

- ``name``: **good** — direct mapping.
- ``privilege_level``: **lossy** — Cisco's 1-15 numeric scale must
  collapse to OPNsense's binary admin / non-admin (group ``admins``
  versus other).  Convention: privilege >= 15 → ``admins``; anything
  lower → ``users`` (or whichever non-admin group).
- ``hashed_password``: **lossy** — Cisco type-9 (``$9$``) and type-8
  (``$4$``) hashes are NOT bcrypt and OPNsense will reject them.
  Type-5 (``$1$`` MD5-crypt) might work if OPNsense is configured
  to accept legacy hashes via PAM, but is not the default.  Operators
  must reset passwords on the OPNsense target device.  Both codecs
  pass hashes through verbatim; the loss surfaces as a banner.
- ``role``: **lossy** — Cisco has no first-class role string (the
  privilege number is the closest proxy).  OPNsense's ``<groupname>``
  is the role surface.  The cross-pair render synthesises ``admins``
  for privilege >= 15 and ``users`` otherwise.

Disposition: **lossy** at the field level; password carry-through
will fail authentication post-migration without operator re-keying.

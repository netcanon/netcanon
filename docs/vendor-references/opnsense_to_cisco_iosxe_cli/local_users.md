# Local users + hash formats: OPNsense versus Cisco IOS-XE

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

- ``<password>`` carries a bcrypt hash (``$2y$<cost>$<salt><hash>``)
  by default ("Blowfish").  Optional SHA-512 (``$6$``) toggle for
  FIPS environments.
- Privilege is GROUP-MEMBERSHIP-DRIVEN: ``admins`` group ↔ admin;
  any other group ↔ operator.

The OPNsense codec parses these into ``CanonicalLocalUser`` with
``hashed_password`` tagged ``"bcrypt:<hash>"`` (per ``parse.py``).
Privilege is set to 15 for admins (groupname == ``"admins"``) and 1
otherwise.

## Cisco IOS-XE

Source: [Cisco IOS XE Security Configuration Guide — User Security](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/security/m1/sec-m1-cr-book/sec-m1-cr-book_chapter_010.html)

```
username admin privilege 15 secret 9 $9$AbCdEfGhIjKlM$nOpQrStUvWxYz
username operator privilege 5 secret 5 $1$abc$def123ghijkl
```

Cisco hash type prefixes:

- type 5: ``$1$`` — legacy MD5-crypt (POSIX-standard; cross-vendor)
- type 8: ``$4$`` — PBKDF2-SHA256
- type 9: ``$9$`` — scrypt (Cisco-specific)

bcrypt (``$2y$``) is NOT a Cisco-recognised hash type.

## Cross-vendor mapping

Canonical fields (see ``CanonicalLocalUser``):

```
name, privilege_level, hashed_password, role
```

OPNsense -> Cisco:

- ``name``: **good** — direct mapping.
- ``privilege_level``: **good** — the OPNsense parser sets the
  canonical ``privilege_level`` to 15 for admins and 1 otherwise;
  Cisco's render path uses the same scale.
- ``hashed_password``: **lossy** — OPNsense bcrypt (``$2y$``) is not
  a recognised Cisco hash type.  The Cisco codec passes the
  bcrypt hash through into the ``secret`` line but the device will
  reject it on apply.  Operators must reset passwords on the Cisco
  target.  The codec's ``bcrypt:`` tag prefix surfaces the format
  divergence in the validation report.
- ``role``: **lossy** — OPNsense's free-form ``<groupname>`` doesn't
  map to Cisco's privilege number; the cross-pair drops the role
  string and Cisco synthesises the privilege from
  ``CanonicalLocalUser.privilege_level``.

Disposition: **lossy** at the field level; password authentication
will fail post-migration without operator re-keying.

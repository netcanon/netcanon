# Local users + AAA — IOS-XE CLI versus OpenConfig NETCONF

## CLI form

Source: [Security Configuration Guide, Cisco IOS XE 17.x — User
Accounts](https://www.cisco.com/c/en/us/td/docs/routers/ios/config/17-x/sec-usr/b-sec-usr.html)
(retrieved 2026-04-30).

Local users:

```
username netadmin privilege 15 secret 9 $9$ENJL...
username opsuser privilege 7 secret 5 $1$abcd...
```

`secret <type> <hash>` indicates the hash family:

* `secret 5` — type-5 MD5-crypt (`$1$...`)
* `secret 8` — PBKDF2-SHA256
* `secret 9` — type-9 scrypt (`$9$...`)

RADIUS:

```
radius server SRV-01
 address ipv4 10.0.0.50 auth-port 1812 acct-port 1813
 key 7 ENC-SHARED-SECRET
!
```

## OpenConfig NETCONF form

OpenConfig models local users under `openconfig-system / aaa`:

```xml
<system xmlns="http://openconfig.net/yang/system">
  <aaa>
    <authentication>
      <users>
        <user>
          <username>netadmin</username>
          <config>
            <username>netadmin</username>
            <role>admin</role>
            <password-hashed>$9$ENJL...</password-hashed>
          </config>
        </user>
      </users>
    </authentication>
    <server-groups>
      <server-group>
        <name>radius-default</name>
        <config>
          <name>radius-default</name>
          <type>RADIUS</type>
        </config>
        <servers>
          <server>
            <address>10.0.0.50</address>
            <radius>
              <config>
                <auth-port>1812</auth-port>
                <acct-port>1813</acct-port>
              </config>
            </radius>
          </server>
        </servers>
      </server-group>
    </server-groups>
  </aaa>
</system>
```

The Cisco-IOS-XE-native YANG mirrors the CLI grammar (`username
<name> privilege <N> secret <type> <hash>`), and IOS-XE 17.x
translates `<aaa>` OpenConfig leaves to / from the native form.
Privilege-level <-> role mapping is platform-specific.

## Cross-format mapping in this repository

The OpenConfig NETCONF codec in this repository does not wire AAA
at all (no path declared in its capability matrix's
`supported`/`lossy` lists).  The CLI codec parses local users +
RADIUS servers and populates the canonical lists.

| Canonical field | CLI -> NETCONF | NETCONF -> CLI |
|---|---|---|
| `local_users` | unsupported (NETCONF render emits no AAA XML) | not_applicable |
| `radius_servers` | unsupported | not_applicable |

Once wired (NETCONF -> bridge native `aaa` model), the disposition
flips to:

* `local_users[].name` / `privilege_level` / `role` -> `good` (same
  vendor, same database).
* `local_users[].hashed_password` -> **`good`** for same-vendor.
  Unlike the cross-vendor case (where Cisco type-9 `$9$` is not
  portable to Arista or Juniper), here both sides are consuming the
  same Cisco hash family, so verbatim pass-through round-trips
  cleanly.  This is one of the cleanest wins of the same-vendor-
  different-wire-format case.
* `radius_servers` -> `good` (host / key / auth_port / acct_port).
  The encrypted shared-secret ciphertext (`key 7 ENC...`) round-
  trips verbatim same-vendor-same-engine.

This is one of the high-value wire-up opportunities for this codec
pair: when an operator is migrating between an OPN orchestration
plane (NETCONF) and a CLI-pasted backup, AAA continuity matters and
the canonical model already carries it.
